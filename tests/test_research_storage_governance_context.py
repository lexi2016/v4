"""Memory-only regression for the reviewed cross-thread claim leak."""
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from pathlib import Path
import threading
import types

import pytest

from ops import research_storage_governance as g


class ProbeClaim:
    def __init__(self):
        self.paused = False
        self.events = []
        self.directory = '/NO_FILE_WRITTEN/owner'
        self.baselines = {}
    def watch(self, path):
        self.events.append(('watch', str(path)))
    def observe(self, path):
        self.events.append(('observe', str(path)))
    def checkpoint(self, **kwargs):
        self.events.append(('checkpoint', threading.get_ident()))
        if self.paused:
            raise g.SpaceBlocked('intentional owning claim pause')


@contextmanager
def owning(claim):
    token = g._ACTIVE.set(claim)
    try:
        yield
    finally:
        g._ACTIVE.reset(token)


def qfq_probe():
    calls = []
    def record(name):
        def call(*args, **kwargs):
            calls.append((name, args))
            return name
        call.__name__ = name
        return call
    class Writer:
        def __init__(self, *args, **kwargs):
            calls.append(('construct_writer', args))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            calls.append(('exit_writer', args))
        write_table = record('write_table')
        write_batch = record('write_batch')
        close = record('close')
    module = types.SimpleNamespace(_write=record('_write'),spool_current=record('spool_current'),
        publish_pair=record('publish_pair'),recover_pair=record('recover_pair'),
        _symbol_checkpoint=record('_symbol_checkpoint'),pq=types.SimpleNamespace(
            ParquetWriter=Writer,write_table=record('pq.write_table')),
        ThreadPoolExecutor=ThreadPoolExecutor,ProcessPoolExecutor=ThreadPoolExecutor)
    return module, calls


def product_probe():
    calls = []
    def record(name):
        def call(*args, **kwargs):
            calls.append((name, args))
            return name
        call.__name__ = name
        return call
    module = types.SimpleNamespace(ThreadPoolExecutor=ThreadPoolExecutor,ProcessPoolExecutor=ThreadPoolExecutor)
    for name in ('save','write_json','compute_stock','run_incremental_history','publish_current_history_view',
                 'build','stage','record_daily_attempt','retain_owner_result','finalize_owner_charts','owner_pngs'):
        setattr(module,name,record(name))
    return module,calls


@pytest.mark.parametrize('foreign_claim', [False,True])
def test_qfq_foreign_thread_and_foreign_claim_bypass_every_adapter_without_billing(foreign_claim):
    module,calls=qfq_probe();original=dict(vars(module));claim=ProbeClaim();table=types.SimpleNamespace(nbytes=1)
    def foreign():
        token=g._ACTIVE.set(ProbeClaim() if foreign_claim else None)
        try:
            module._write('/NO_FILE_WRITTEN/foreign.json',b'value')
            module.spool_current('foreign')
            module.publish_pair({}, {}, {}, 'foreign-journal')
            module.recover_pair('foreign-journal', {})
            module._symbol_checkpoint('foreign')
            module.pq.write_table(table,'/NO_FILE_WRITTEN/foreign.parquet')
            with module.pq.ParquetWriter('/NO_FILE_WRITTEN/foreign.parquet') as writer:
                assert type(writer) is original['pq'].ParquetWriter
                writer.write_table(table);writer.write_batch(table);writer.close()
            for name in ('ThreadPoolExecutor','ProcessPoolExecutor'):
                with getattr(module,name)(max_workers=1) as pool:
                    assert type(pool) is ThreadPoolExecutor
                    assert pool.submit(lambda:g._ACTIVE.get()).result() is None
        finally:g._ACTIVE.reset(token)
    with owning(claim),g.qfq_write_seams(module,claim):
        claim.paused=True
        with ThreadPoolExecutor(1) as pool:pool.submit(foreign).result(timeout=3)
        assert claim.events==[]
    assert calls and all(getattr(module,name) is value for name,value in original.items())


@pytest.mark.parametrize('foreign_claim', [False,True])
def test_product_foreign_thread_bypasses_save_boundaries_and_executor_constructors(foreign_claim):
    module,calls=product_probe();original=dict(vars(module));claim=ProbeClaim()
    def foreign():
        token=g._ACTIVE.set(ProbeClaim() if foreign_claim else None)
        try:
            module.save('/NO_FILE_WRITTEN/foreign.json',{'value':1})
            module.write_json('/NO_FILE_WRITTEN/foreign.json',{'value':1})
            for name in original.keys()-{'save','write_json','ThreadPoolExecutor','ProcessPoolExecutor'}:
                getattr(module,name)('foreign')
            for name in ('ThreadPoolExecutor','ProcessPoolExecutor'):
                with getattr(module,name)(max_workers=1) as pool:
                    assert type(pool) is ThreadPoolExecutor
                    pool.submit(lambda:module.save('/NO_FILE_WRITTEN/foreign-worker.json',{})).result()
        finally:g._ACTIVE.reset(token)
    with owning(claim),g.product_write_seams([module],claim):
        claim.paused=True
        with ThreadPoolExecutor(1) as pool:pool.submit(foreign).result(timeout=3)
        assert claim.events==[]
    assert calls and all(getattr(module,name) is value for name,value in original.items())


@pytest.mark.parametrize('kind',['qfq','product'])
def test_participating_thread_inherits_context_and_blocks_at_worker_write_boundary(kind):
    module,calls=qfq_probe() if kind=='qfq' else product_probe()
    claim=ProbeClaim();entered=threading.Event();release=threading.Event();observed=[]
    manager=lambda:g.qfq_write_seams(module,claim) if kind=='qfq' else g.product_write_seams([module],claim)
    original=dict(vars(module))
    def worker():
        observed.append(g._ACTIVE.get() is claim)
        # Propagated nested adapter entry must reuse existing wrappers without
        # acquiring the main thread's install RLock or duplicating wrappers.
        wrapped=module._write if kind=='qfq' else module.save
        with manager():
            assert (module._write if kind=='qfq' else module.save) is wrapped
            entered.set();assert release.wait(3)
            if kind=='qfq':module._write('/NO_FILE_WRITTEN/owned.json',b'value')
            else:module.save('/NO_FILE_WRITTEN/owned.json',{'value':1})
    with owning(claim),manager():
        with module.ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(worker)
            assert isinstance(future,Future) and entered.wait(3)
            claim.paused=True;release.set()
            assert future in wait([future],timeout=3).done
            with pytest.raises(g.SpaceBlocked,match='owning claim pause'):future.result()
    assert observed==[True]
    assert ('watch','/NO_FILE_WRITTEN/owned.json') in claim.events
    assert not any(name in {'_write','save'} for name,_ in calls)
    assert all(getattr(module,name) is value for name,value in original.items())


@pytest.mark.parametrize('kind',['qfq','product'])
def test_participating_done_callback_inherits_context_and_does_not_lose_guard(kind):
    module,calls=qfq_probe() if kind=='qfq' else product_probe();claim=ProbeClaim()
    release=threading.Event();callback_done=threading.Event();observed=[]
    manager=lambda:g.qfq_write_seams(module,claim) if kind=='qfq' else g.product_write_seams([module],claim)
    def callback(future):
        try:
            observed.append(g._ACTIVE.get() is claim)
            if kind=='qfq':module._write('/NO_FILE_WRITTEN/callback.json',b'x')
            else:module.save('/NO_FILE_WRITTEN/callback.json',{})
        except g.SpaceBlocked:observed.append('blocked')
        finally:callback_done.set()
    with owning(claim),manager():
        with module.ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(lambda:release.wait(3))
            future.add_done_callback(callback)
            claim.paused=True;release.set()
            assert future.result(timeout=3) is True
            assert callback_done.wait(3)
    assert observed==[True,'blocked']
    assert ('watch','/NO_FILE_WRITTEN/callback.json') in claim.events
    assert not any(name in {'_write','save'} for name,_ in calls)


@pytest.mark.parametrize('kind',['qfq','product'])
def test_owner_constructed_adapter_instances_called_from_foreign_thread_do_not_bill(kind):
    module,calls=qfq_probe() if kind=='qfq' else product_probe();claim=ProbeClaim()
    manager=lambda:g.qfq_write_seams(module,claim) if kind=='qfq' else g.product_write_seams([module],claim)
    table=types.SimpleNamespace(nbytes=1)
    with owning(claim),manager():
        writer=module.pq.ParquetWriter('/NO_FILE_WRITTEN/owned.parquet') if kind=='qfq' else None
        with module.ThreadPoolExecutor(max_workers=1) as pool:
            claim.events.clear();claim.paused=True
            def foreign():
                assert g._ACTIVE.get() is None
                if writer:
                    writer.write_table(table);writer.write_batch(table);writer.close();writer.__exit__(None,None,None)
                future=pool.submit(lambda:g._ACTIVE.get())
                assert future.result(timeout=3) is None
            with ThreadPoolExecutor(1) as unrelated:unrelated.submit(foreign).result(timeout=3)
            assert claim.events==[]


@pytest.mark.parametrize('kind',['qfq','product'])
def test_nested_scope_exception_restores_identity_and_retired_closures_pass_through(kind):
    module,calls=qfq_probe() if kind=='qfq' else product_probe();claim=ProbeClaim();original=dict(vars(module))
    manager=lambda:g.qfq_write_seams(module,claim) if kind=='qfq' else g.product_write_seams([module],claim)
    before=g._ADAPTER_SCOPES.get()
    with owning(claim):
        with pytest.raises(RuntimeError,match='scope exit'):
            with manager():
                retained=module._write if kind=='qfq' else module.save
                with manager():
                    assert (module._write if kind=='qfq' else module.save) is retained
                raise RuntimeError('scope exit')
        assert g._ADAPTER_SCOPES.get()==before
        claim.events.clear();claim.paused=True
        retained('/NO_FILE_WRITTEN/late',b'x' if kind=='qfq' else {})
        assert claim.events==[]
    assert all(getattr(module,name) is value for name,value in original.items())


@pytest.mark.parametrize('kind',['qfq','product'])
def test_process_submission_keeps_original_callable_and_parent_future_guard(kind):
    module,_=qfq_probe() if kind=='qfq' else product_probe();claim=ProbeClaim();submitted=[]
    class ProcessProbe:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def submit(self,function,*args,**kwargs):
            submitted.append(function)
            future=Future();future.set_result('process-result');return future
    module.ProcessPoolExecutor=ProcessProbe
    function=lambda:'not executed here'
    manager=lambda:g.qfq_write_seams(module,claim) if kind=='qfq' else g.product_write_seams([module],claim)
    with owning(claim),manager():
        with module.ProcessPoolExecutor() as pool:
            future=pool.submit(function)
            assert isinstance(future,Future) and future.result()=='process-result'
    assert submitted==[function] and any(name=='checkpoint' for name,_ in claim.events)
    assert 'result' not in future.__dict__ and 'add_done_callback' not in future.__dict__


@pytest.mark.parametrize('kind',['qfq','product'])
def test_foreign_callback_registration_is_not_promoted_to_owner_context(kind):
    module,calls=qfq_probe() if kind=='qfq' else product_probe();claim=ProbeClaim()
    release=threading.Event();done=threading.Event();contexts=[]
    manager=lambda:g.qfq_write_seams(module,claim) if kind=='qfq' else g.product_write_seams([module],claim)
    def callback(future):
        contexts.append(g._ACTIVE.get())
        if kind=='qfq':module._write('/NO_FILE_WRITTEN/foreign-callback',b'x')
        else:module.save('/NO_FILE_WRITTEN/foreign-callback',{})
        done.set()
    with owning(claim),manager():
        with module.ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(lambda:release.wait(3))
            with ThreadPoolExecutor(1) as unrelated:unrelated.submit(future.add_done_callback,callback).result(timeout=3)
            claim.events.clear();claim.paused=True;release.set()
            assert future.result(timeout=3) is True and done.wait(3)
            assert claim.events==[]
    assert contexts==[None]
    assert any(name in {'_write','save'} for name,_ in calls)


@pytest.mark.parametrize('kind',['qfq','product'])
def test_foreign_future_result_skips_known_path_observation_and_retire_restores_methods(kind):
    module,_=qfq_probe() if kind=='qfq' else product_probe();claim=ProbeClaim()
    class ProcessProbe:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def submit(self,*args,**kwargs):
            future=Future();future.set_result('done');return future
    module.ProcessPoolExecutor=ProcessProbe
    def _symbol_process_task(payload):pass
    manager=lambda:g.qfq_write_seams(module,claim) if kind=='qfq' else g.product_write_seams([module],claim)
    with owning(claim),manager():
        kwargs={} if kind=='qfq' else dict(initargs=(None,None,'/NO_FILE_WRITTEN','/NO_FILE_WRITTEN/parts'))
        with module.ProcessPoolExecutor(**kwargs) as pool:
            if kind=='qfq':future=pool.submit(_symbol_process_task,('000001.SZ',{},20260101,{},'/NO_FILE_WRITTEN/parts',{}))
            else:future=pool.submit(lambda symbol:None,'000001.SZ')
            claim.events.clear();claim.paused=True
            with ThreadPoolExecutor(1) as unrelated:assert unrelated.submit(future.result).result(timeout=3)=='done'
            assert claim.events==[]
    assert 'result' not in future.__dict__ and 'add_done_callback' not in future.__dict__
