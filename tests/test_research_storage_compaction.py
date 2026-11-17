from __future__ import annotations

import copy
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import stat
import sys

import pytest

from ops import research_storage_compaction as c
from ops import research_storage_governance as governance
from ops import research_daily_product_parallel as parallel
from ops import research_panel_daily_product as product

RESOURCE = dict(cpu_count=18, physical_memory_bytes=128*1024**3, memory_free_percent=86,
                workers=2, pending_limit=4, reserve_bytes=24*1024**3)


def fixture_job(tmp_path):
    root = tmp_path/'data';root.mkdir()
    locks = []
    for name in ('completion.lock','owner.lock','qfq.lock'):
        p=tmp_path/name;p.touch();locks.append(str(p))
    job=dict(day='20261112', generation='a'*64, roots=[str(root)], owner_locks=locks,
             job_id='fixture', product_root=str(root), data_root=str(tmp_path))
    return root, job


def write(path, content):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
    return path


def test_native_compression_clone_preserves_bytes_dates_and_original_reader(tmp_path):
    root, job = fixture_job(tmp_path)
    raw = json.dumps({'events':[{'day':'20261112','value':1.25}]*3000}).encode()
    a=write(root/'a.json',raw);b=write(root/'b.json',raw)
    original={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in (a,b)}
    plan=c.dry_run(job,resource=RESOURCE)
    assert plan['exact_duplicate_files']==1
    result=c.compact_job(job,output=tmp_path/'rollup.json',resource=RESOURCE,expected_plan=plan)
    assert result['status']=='PASS'
    assert result['counts']['NATIVE_COMPRESSED']==1
    assert result['counts']['EXACT_APFS_CLONE']==1
    assert result['content_identity_sha256']==result['after_content_identity_sha256']
    assert result['after_allocated_bytes']<result['before_allocated_bytes']
    assert result['clone_exclusive_savings']=='CANNOT_CONFIRM'
    for p in (a,b):
        assert (p.read_bytes(),p.stat().st_mtime_ns)==original[str(p)]
        assert p.stat().st_nlink==1 and p.stat().st_flags & c.COMPRESSED
        assert json.loads(p.read_bytes())['events'][0]['value']==1.25
    assert not list(root.glob('.storage-compact-*'))
    assert c.compact_job(job,output=tmp_path/'rollup.json',resource=RESOURCE)['reused'] is True


@pytest.mark.parametrize('kind',['symlink','hardlink','pending','raw'])
def test_scope_rejects_aliases_unclosed_files_and_raw_sources(tmp_path,kind):
    root, job=fixture_job(tmp_path)
    source=write(tmp_path/'source.json',b'x'*20000)
    if kind=='symlink':(root/'item.json').symlink_to(source)
    elif kind=='hardlink':os.link(source,root/'item.json')
    elif kind=='pending':write(root/'.item.pending',b'x'*20000)
    else:write(root/'sh600000.day',b'x'*20000)
    with pytest.raises(c.RetentionError):c.dry_run(job,resource=RESOURCE)
    assert source.read_bytes()==b'x'*20000


def test_native_failure_and_source_CAS_never_replace_original(tmp_path,monkeypatch):
    root,job=fixture_job(tmp_path);p=write(root/'a.json',b'x'*20000)
    item=c.content_inventory(c.inventory(job['roots']),RESOURCE)[0]
    real=c.subprocess.run
    def failed(command,**kwargs):
        if command[0]=='/usr/bin/ditto':
            Path(command[-1]).write_bytes(b'partial')
            raise OSError('native copy failed')
        return real(command,**kwargs)
    monkeypatch.setattr(c.subprocess,'run',failed)
    with pytest.raises(OSError,match='native copy failed'):c.transform(item)
    assert p.read_bytes()==b'x'*20000
    assert not list(root.glob('.storage-compact-*'))
    p.write_bytes(b'y'*20000)
    with pytest.raises(c.RetentionError,match='PREIMAGE_STAMP_DRIFT'):c.transform(item)
    assert p.read_bytes()==b'y'*20000


def test_owner_busy_and_plan_CAS_fail_before_any_native_copy(tmp_path,monkeypatch):
    root,job=fixture_job(tmp_path);p=write(root/'a.json',b'x'*20000)
    plan=c.dry_run(job,resource=RESOURCE)
    with open(job['owner_locks'][1],'rb') as held:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):c.compact_job(job,output=tmp_path/'result.json',resource=RESOURCE)
    p.write_bytes(b'y'*20000)
    with pytest.raises(c.RetentionError,match='PLAN_CAS_DRIFT'):
        c.compact_job(job,output=tmp_path/'result.json',resource=RESOURCE,expected_plan=plan)
    assert p.read_bytes()==b'y'*20000


def test_zero_budget_defers_then_next_owner_pass_resumes_and_new_F10_is_seen(tmp_path):
    root,job=fixture_job(tmp_path);write(root/'a.json',b'x'*20000)
    out=tmp_path/'result.json'
    first=c.compact_job(job,output=out,resource=RESOURCE,seconds=0)
    assert first['status']=='DEFERRED' and first['counts']['DEFERRED']==1
    assert (root/'a.json').stat().st_flags & c.COMPRESSED==0
    second=c.compact_job(job,output=out,resource=RESOURCE)
    assert second['status']=='PASS'
    write(root/'new_f10.json',b'y'*20000)
    third=c.compact_job(job,output=out,resource=RESOURCE)
    assert third['status']=='PASS' and third['counts']['REUSED_COMPRESSED']==1
    assert third['counts']['NATIVE_COMPRESSED']==1


def test_repeated_native_failure_stops_submissions_and_bounds_failure_log(tmp_path,monkeypatch):
    root,job=fixture_job(tmp_path)
    for i in range(20):write(root/f'{i}.json',bytes([65+i])*20000)
    calls=[]
    def fail(item,**kwargs):calls.append(item['path']);raise OSError('same native failure')
    monkeypatch.setattr(c,'transform',fail)
    result=c.compact_job(job,output=tmp_path/'result.json',resource=RESOURCE)
    assert result['status']=='FAILED'
    assert 3 <= len(calls) <= RESOURCE['pending_limit']+2
    assert result['counts']['DEFERRED']>0 and len(result['failures'])==len(calls)


def test_pending_queue_keeps_closure_and_serves_old_job_without_new_timer(tmp_path,monkeypatch):
    root,job=fixture_job(tmp_path);write(root/'a.json',b'x'*20000)
    state=tmp_path/'registry';state.mkdir()
    claim=SimpleNamespace(finalized=True,registry=SimpleNamespace(root=state))
    context=SimpleNamespace(data_root=tmp_path,target=20261112,generation='a'*64,snapshot_ref={})
    result=dict(schema='V4_A_DAILY_DERIVATIVES_V1',status='COMPLETE_DESCRIPTIVE_NONPIT',completed_source_provenance={'numeric_manifest':{}})
    current=copy.deepcopy(job)
    monkeypatch.setattr(c,'closed_job',lambda **kwargs:copy.deepcopy(current))
    calls=[]
    def compact(job,**kwargs):
        calls.append((job['job_id'],kwargs['seconds']))
        return {'status':'DEFERRED'} if job['job_id']=='fixture' else {'status':'PASS'}
    monkeypatch.setattr(c,'compact_job',compact)
    token=governance._ACTIVE.set(claim)
    try:
        c.completed_event(claim=claim,context=context,product_root=root,receipt_root=root,result=result,resource=RESOURCE)
        pending=json.loads((state/'compaction/pending.json').read_bytes())
        assert pending['jobs']['fixture']['job']==job
        current['job_id']='new_day';current['day']='20261113'
        c.completed_event(claim=claim,context=context,product_root=root,receipt_root=root,result=result,resource=RESOURCE)
        assert calls[-2][0]=='new_day' and calls[-1][0]=='fixture'
        assert calls[-2][1] < 11  # fair half-budget reserved for pending
        assert set(json.loads((state/'compaction/pending.json').read_bytes())['jobs'])=={'fixture'}
    finally:governance._ACTIVE.reset(token)


def test_maintenance_failure_cannot_change_or_block_completed_business_result(tmp_path,monkeypatch):
    result=dict(schema='V4_A_DAILY_DERIVATIVES_V1',status='COMPLETE_DESCRIPTIVE_NONPIT',untouched={'a':1})
    original=copy.deepcopy(result)
    def fail(**kwargs):raise ValueError('maintenance only failure')
    monkeypatch.setattr(c,'completed_event',fail)
    claim=SimpleNamespace(registry=SimpleNamespace(root=tmp_path))
    governance._after_product_compaction(claim,None,tmp_path,(None,None,None,tmp_path),{},result)
    assert result==original
    assert json.loads((tmp_path/'compaction/last_event_error.json').read_bytes())['status']=='FAILED'


@pytest.mark.parametrize('failure',[BlockingIOError('owner busy'),ValueError('SHARED_INHERITED_OWNER_FD_INVALID:identity')])
def test_busy_pending_owner_is_retried_at_a_later_completion_event(tmp_path,monkeypatch,failure):
    root,job=fixture_job(tmp_path);write(root/'a.json',b'x'*20000)
    state=tmp_path/'registry';state.mkdir()
    claim=SimpleNamespace(finalized=True,registry=SimpleNamespace(root=state))
    context=SimpleNamespace(data_root=tmp_path,target=20261112,generation='a'*64,snapshot_ref={})
    result=dict(schema='V4_A_DAILY_DERIVATIVES_V1',status='COMPLETE_DESCRIPTIVE_NONPIT',completed_source_provenance={'numeric_manifest':{}})
    monkeypatch.setattr(c,'closed_job',lambda **kwargs:copy.deepcopy(job))
    attempts=[]
    def compact(job,**kwargs):
        attempts.append(job['job_id'])
        if len(attempts)==1:raise failure
        return {'status':'PASS'}
    monkeypatch.setattr(c,'compact_job',compact)
    token=governance._ACTIVE.set(claim)
    try:
        first=c.completed_event(claim=claim,context=context,product_root=root,receipt_root=root,result=result,resource=RESOURCE)
        assert first['status']=='DEFERRED'
        second=c.completed_event(claim=claim,context=context,product_root=root,receipt_root=root,result=result,resource=RESOURCE)
        assert second['status']=='PASS' and attempts==['fixture','fixture']
    finally:governance._ACTIVE.reset(token)


def test_real_inherited_owner_helper_accepts_old_pending_under_current_day_lease(tmp_path,monkeypatch):
    import ast,stat,sys
    # Execute the unchanged real helper function, with its original source path;
    # avoid importing unrelated producer/bootstrap code into an isolated test.
    source=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-prepool-publication-20261112-r1/main/app/ops/sync_stock_history_completion.py')
    tree=ast.parse(source.read_text())
    function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='_inherited_owner_duplicate')
    namespace={'os':os,'stat':stat,'fcntl':fcntl}
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),namespace)
    monkeypatch.setitem(sys.modules,'ops.sync_stock_history_completion',SimpleNamespace(_inherited_owner_duplicate=namespace['_inherited_owner_duplicate']))
    root,job=fixture_job(tmp_path)
    fd=os.open(job['owner_locks'][1],os.O_RDONLY|os.O_NOFOLLOW)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for key,value in {'V4_SCHEDULER_LANE_FD':str(fd),'V4_SCHEDULER_LANE_NAME':'A_LONG',
                'V4_SCHEDULER_RESOLVED_DATE':'20261113','V4_SCHEDULER_RESOLVED_SLOT':'1640'}.items():
            monkeypatch.setenv(key,value)
        with c.closed_owner_locks(job):pass
        # Closing the duplicate must leave the original current-day lock held.
        with open(job['owner_locks'][1],'rb') as probe:
            with pytest.raises(BlockingIOError):fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert job['day']=='20261112'  # lease identity never relabels old data
    finally:os.close(fd)


def test_no_benefit_prefix_is_terminal_across_budgets_and_new_files(tmp_path,monkeypatch):
    import time
    root,job=fixture_job(tmp_path)
    for i in range(5):write(root/f'{i}.json',bytes([65+i])*20000)
    calls=[]
    def no_benefit(item,**kwargs):
        calls.append(Path(item['path']).name);time.sleep(.07)
        return dict(status='NO_ALLOCATED_BENEFIT',action='NATIVE_COMPRESSED',logical_bytes=20000,
                    before_allocated=20480,after_allocated=20480)
    monkeypatch.setattr(c,'transform',no_benefit)
    resource=dict(RESOURCE,workers=1,pending_limit=1)
    out=tmp_path/'result.json'
    for unused in range(5):
        result=c.compact_job(job,output=out,resource=resource,seconds=.05)
    assert result['status']=='PASS'
    assert sorted(calls)==[f'{i}.json' for i in range(5)]
    write(root/'new_f10.json',b'z'*20000)
    c.compact_job(job,output=out,resource=resource)
    assert calls[-1]=='new_f10.json' and len(calls)==6
    (root/'0.json').write_bytes(b'changed'*4000)
    c.compact_job(job,output=out,resource=resource)
    assert calls[-1]=='0.json' and len(calls)==7


@pytest.mark.skipif(sys.platform != 'darwin', reason='Darwin native row storage')
@pytest.mark.parametrize('parallel_worker', [False, True])
def test_daily_row_write_is_byte_exact_for_readers_and_governance(tmp_path, monkeypatch, parallel_worker):
    from infrastructure.research_lane_source import ResearchLaneSource

    root = tmp_path / 'daily_products'
    symbol, day = '600000.SH', '20261117'
    context = SimpleNamespace(root=root, target=int(day), scope=[symbol], identity={'input_sha256': 'fixture'},
        generation='fixture', snapshot_ref={}, config_ref={},
        engine=lambda: SimpleNamespace(compute=lambda *_: None), unchanged=lambda: None)
    row = dict(symbol=symbol, data_date=day, groups='', pending_groups='',
        evaluation={'groups': {name: {'status': 'FALSE'} for name in product.GROUPS}},
        statistics={'history': ['历史标签' * 10] * 2000}, **product.FLAGS)
    expected = product.canonical(row) + b'\n'
    legacy_ref = product.save(tmp_path / 'legacy.json', row, immutable=True)
    monkeypatch.delenv('V4_STORAGE_PAIR_ROOT', raising=False)
    monkeypatch.delenv('V4_STORAGE_PAIR_DATA_ROOT', raising=False)
    monkeypatch.setattr(product, 'SourceContext', lambda *_: context)
    monkeypatch.setattr(product, 'compute_stock', lambda *_args, **_kwargs: (dict(row), None, None))
    monkeypatch.setattr(product, 'save_history_checkpoint', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(parallel, '_CONTEXT', context)
    monkeypatch.setattr(parallel, '_PARTS', parallel.checkpoint_parts(context, [symbol]))
    monkeypatch.setattr(parallel, '_CHARTS', False)
    watched, observed = [], {}
    claim = SimpleNamespace(watch=watched.append, checkpoint=lambda **_kwargs: None,
        observe=lambda path: observed.__setitem__(path, path.stat().st_blocks * 512))

    def materialize_ref():
        if parallel_worker:
            return parallel.checkpoint(symbol)['ref']
        result = product.materialize_daily_product(data_root=tmp_path, target=int(day),
            symbols=[symbol], original_charts=False)
        return json.loads(product.checked(result['artifact']).read_bytes())['row_refs'][symbol]

    token = governance._ACTIVE.set(claim)
    try:
        with governance.product_write_seams([product, parallel], claim):
            reference = materialize_ref()
            path = parallel._PARTS / (symbol + '.json')
            source = ResearchLaneSource.__new__(ResearchLaneSource)
            source._a_product_root = lambda: tmp_path
            assert reference == {'path': str(path), 'sha256': legacy_ref['sha256']}
            assert source._a_product_reference(reference) == source._a_product_reference(legacy_ref) == row
            assert path.read_bytes() == product.checked(legacy_ref).read_bytes() == expected
            assert path in watched and observed[path] < Path(legacy_ref['path']).stat().st_blocks * 512
            assert path.stat().st_flags & stat.UF_COMPRESSED
            assert stat.S_IMODE(path.stat().st_mode) == stat.S_IMODE(Path(legacy_ref['path']).stat().st_mode)
            before = c.stamp(path)
            assert materialize_ref() == reference and c.stamp(path) == before
    finally:
        governance._ACTIVE.reset(token)
    assert not list(path.parent.glob('.daily-row-*.pending'))


@pytest.mark.skipif(sys.platform != 'darwin', reason='Darwin native row storage')
@pytest.mark.parametrize('native_outcome', ['unsupported', 'no_gain', 'hash', 'mode', 'io'])
def test_daily_row_uses_verified_plain_bytes_only_for_known_no_benefit(tmp_path, monkeypatch, native_outcome):
    path = tmp_path / '000001.SZ.json'
    row = {'row': 'ab' * 10000}
    original = product.canonical(row) + b'\n'

    def native(source, candidate):
        if native_outcome == 'unsupported':
            raise OSError(errno.ENOTSUP, 'unsupported test filesystem')
        if native_outcome == 'io':
            raise OSError(errno.EIO, 'native test I/O error')
        candidate.write_bytes(original if native_outcome != 'hash' else b'x' + original[1:])
        mode = stat.S_IMODE(source.stat().st_mode)
        os.chmod(candidate, mode ^ stat.S_IXUSR if native_outcome == 'mode' else mode)

    monkeypatch.setattr(c, 'native_compressed_copy', native)
    if native_outcome in {'unsupported', 'no_gain'}:
        reference = product.save(path, row, immutable=True, compress_row=True)
        assert product.checked(reference).read_bytes() == original
        assert not path.stat().st_flags & stat.UF_COMPRESSED
    else:
        with pytest.raises((c.RetentionError, OSError)):
            product.save(path, row, immutable=True, compress_row=True)
        assert not path.exists()
    assert not list(tmp_path.glob('.daily-row-*.pending'))


@pytest.mark.skipif(sys.platform != 'darwin', reason='Darwin native row storage')
def test_concurrent_different_values_never_overwrite_immutable_row(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / '000001.SZ.json'
    barrier = Barrier(2)

    def write_row(text):
        barrier.wait(timeout=5)
        try:
            return product.save(path, {'row': text * 20000}, immutable=True, compress_row=True)
        except ValueError as error:
            assert str(error).startswith('DAILY_IMMUTABLE_CONFLICT:')
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(write_row, ['a', 'b'])
    winner = [x for x in (first, second) if x is not None]
    assert winner == [product.reference(path)] and product.checked(winner[0]) == path
    assert not list(tmp_path.glob('.daily-row-*.pending'))


@pytest.mark.skipif(sys.platform != 'darwin', reason='Darwin native row storage')
def test_large_daily_row_uses_single_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'native_compressed_copy', lambda *_: pytest.fail('oversized row compressed'))
    value = {'row': 'x' * c.MAX_DAILY_ROW_COMPRESSION_BYTES}
    path = tmp_path / '000001.SZ.json'
    reference = product.save(path, value, immutable=True, compress_row=True)
    assert product.checked(reference).read_bytes() == product.canonical(value) + b'\n'
    assert not list(tmp_path.glob('.daily-row-*.pending'))


def test_spawn_binding_includes_daily_row_storage_code(tmp_path, monkeypatch):
    app = Path(product.__file__).resolve().parents[1]
    sources = [Path(module.__file__) for module in (product, parallel, product.history_checkpoint, c)]
    entries = [{'path': str(path.relative_to(app)), 'sha256': product.sha(path)} for path in sources]
    release = tmp_path / 'release.json'

    def bind(items):
        ref = product.save(release, {'app_root': str(app), 'application_inventory': {'entries': items}})
        monkeypatch.setenv('V4_RELEASE_MANIFEST_PATH', ref['path'])
        monkeypatch.setenv('V4_RELEASE_MANIFEST_SHA256', ref['sha256'])

    bind(entries)
    assert product.reference(sources[-1]) in parallel.bound_main_sources()['code']
    bind(entries[:-1])
    with pytest.raises(ValueError, match='DAILY_PARALLEL_MAIN_SOURCE_BINDING:.*research_storage_compaction'):
        parallel.bound_main_sources()
