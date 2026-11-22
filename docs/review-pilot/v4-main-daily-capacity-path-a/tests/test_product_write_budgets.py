"""Real incumbent serializers and spawned functions under isolated limits."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import multiprocessing
import os

import pytest
from ops import research_daily_capacity as capacity
from ops import research_storage_governance as governance
from ops import research_panel_daily_product as product
from ops import materialize_workbench_score_action as score


class TraceClaim:
    def __init__(self):
        self.baselines = {}
        self.checkpoints = []
        self.observed = {}
    def watch(self,path):
        path=Path(path)
        if path not in self.baselines:
            st=path.stat() if path.exists() else None
            self.baselines[path]=(st.st_size,st.st_blocks*512) if st else (0,0)
    def checkpoint(self,*,incoming=0):
        self.checkpoints.append(incoming)
    def observe(self,path):
        path=Path(path)
        if path.exists():self.observed[str(path)]=(path.stat().st_size,path.stat().st_blocks*512)


def make_plan(tmp_path,phase='daily_product',*,scope=('000001.SZ','600000.SH'),slot=256*1024,fixed=128*1024,**overrides):
    source=tmp_path/'input.json'
    if not source.exists():source.write_bytes(b'{"exact_input":1}')
    limits=dict(fixed_bytes=64*1024**2 if phase=='qfq' else fixed,per_symbol_bytes=slot,
                per_changed_row_bytes=4096,max_file_bytes=512*1024,max_symbols=10,max_changed_rows=1000,
                max_revised_symbols=0,max_files=4096,max_files_per_symbol=64,
                max_response_bytes=128*1024,max_response_items=32,receipt_bytes=4096)
    limits.update(overrides)
    phases={name:dict(limits,fixed_bytes=max(64*1024**2,limits['fixed_bytes']) if name=='qfq' else limits['fixed_bytes'])for name in capacity.PHASES}
    review=tmp_path/(phase+'-review.json')
    review.write_bytes(capacity.encoded(dict(schema='v4.daily_incremental_limits_review.v1',status='PASS',phase_limits=phases,
        evidence_scope='ISOLATED_FIXTURE',source_bindings=capacity.writer_sources())))
    policy=dict(governance=dict(incremental_capacity=dict(schema=capacity.SCHEMA,enabled=True,phases=phases,
        reviewed_limits=dict(path=str(review),sha256=hashlib.sha256(review.read_bytes()).hexdigest()))))
    counts={symbol:1 for symbol in scope}
    plan=capacity.build_plan(policy,phase,target=20261123,scope=sorted(scope),
        source_identity=dict(generation='fixture-exact-generation',changed_rows_by_symbol=counts),
        references=[capacity.file_reference(source)],changed_rows=len(scope))
    return plan,policy


def worker_save(symbol,root,fail=False,oversize=False):
    value={'symbol':symbol,'payload':'x'*(1000000 if oversize else 20)}
    ref=product.save(Path(root)/(symbol+'.json'),value,immutable=True)
    if fail:raise capacity.CapacityProofError('FIXTURE_AFTER_REAL_WRITE')
    return dict(symbol=symbol,ref=ref,pid=os.getpid())


def test_spawned_slots_reconcile_success_failure_and_drain(tmp_path):
    plan,_=make_plan(tmp_path)
    claim=TraceClaim();root=tmp_path/'output';root.mkdir()
    namespace=SimpleNamespace(ProcessPoolExecutor=ProcessPoolExecutor)
    token=governance._ACTIVE.set(claim)
    try:
        with capacity.writer_scope(plan,claim=claim,roots=[root]) as budget, governance.product_write_seams([namespace],claim):
            with namespace.ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as pool:
                good=pool.submit(worker_save,'000001.SZ',str(root))
                bad=pool.submit(worker_save,'600000.SH',str(root),True)
                assert budget.inflight==2*capacity.symbol_slot(plan,'000001.SZ')
                assert max(claim.checkpoints)>=budget.inflight
                assert good.result()['pid']!=os.getpid()
                with pytest.raises(capacity.CapacityProofError,match='AFTER_REAL_WRITE'):bad.result()
            assert budget.inflight==0 and budget.inflight_files==0
            assert set(claim.observed)=={str(root/'000001.SZ.json'),str(root/'600000.SH.json')}
            assert budget.spent==8192
    except capacity.CapacityProofError as error:
        assert str(error)=='FIXTURE_AFTER_REAL_WRITE'
        assert budget.inflight==0
    finally:governance._ACTIVE.reset(token)


def test_spawned_oversize_fails_before_file_and_cannot_become_unknown(tmp_path):
    plan,_=make_plan(tmp_path)
    claim=TraceClaim();root=tmp_path/'output';root.mkdir()
    namespace=SimpleNamespace(ProcessPoolExecutor=ProcessPoolExecutor)
    token=governance._ACTIVE.set(claim)
    try:
        with pytest.raises(capacity.CapacityProofError,match='SINGLE_WRITE_BOUND'):
            with capacity.writer_scope(plan,claim=claim,roots=[root]) as budget, governance.product_write_seams([namespace],claim):
                with namespace.ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn')) as pool:
                    future=pool.submit(worker_save,'000001.SZ',str(root),False,True)
                    future.result()
        assert budget.inflight==0 and not list(root.iterdir())
    finally:governance._ACTIVE.reset(token)


def test_two_pending_slots_refused_before_second_submission(tmp_path):
    plan,_=make_plan(tmp_path,scope=('000001.SZ',),fixed=4096)
    claim=TraceClaim();root=tmp_path/'output';root.mkdir()
    with capacity.writer_scope(plan,claim=claim,roots=[root]) as budget:
        held=budget.reserve('000001.SZ')
        with pytest.raises(capacity.CapacityProofError,match='INFLIGHT_SLOT'):budget.reserve('000001.SZ')
        assert budget.inflight==held
        budget.settle(held)
        assert budget.inflight==0


def test_symbol_cumulative_file_and_byte_limits_fail_before_side_effect(tmp_path):
    plan,_=make_plan(tmp_path,scope=('000001.SZ',),slot=4096,max_files_per_symbol=1)
    root=tmp_path/'output';root.mkdir()
    with capacity.writer_scope(plan,symbol='000001.SZ',roots=[root]):
        product.save(root/'one.json',{'v':1})
        with pytest.raises(capacity.CapacityProofError,match='FILE_COUNT'):product.save(root/'two.json',{'v':2})
    assert {p.name for p in root.iterdir()}=={'one.json'}


def test_score_real_spawn_map_and_cache_serializers_are_counted(tmp_path,monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq
    symbols=['000001.SZ','600000.SH'];target=20261123
    root=tmp_path/'output';root.mkdir()
    panel=tmp_path/'source.parquet'
    rows=[dict(ts_code=s,trade_date=str(target),open=1.,high=2.,low=1.,close=1.,volume=10.,pre_close=1.,pct_chg=0.,user_v1_sell_signal_daily=False)for s in symbols]
    pq.write_table(pa.Table.from_pylist(rows),panel)
    refs={}
    for symbol in symbols:refs[symbol]=product.save(root/(symbol+'.source.json'),dict(symbol=symbol,data_date=str(target),qualification={'status':'UNKNOWN'}))
    context=SimpleNamespace(panel=panel,root=root,target=target,generation='g',identity={'basis':{'price_basis':'QFQ_ASOF'},'input_sha256':'i','selector_artifact_sha256':'s'},unchanged=lambda:None)
    plan,_=make_plan(tmp_path)
    monkeypatch.setattr(score,'authority_identity',lambda:{'fixture_rule':'exact-preserved-unknown-branch'})
    claim=TraceClaim();token=governance._ACTIVE.set(claim)
    try:
        with capacity.writer_scope(plan,claim=claim,roots=[root])as budget,governance.product_write_seams([score],claim):
            result=score.materialize(context,{'rows':[{'symbol':s}for s in symbols],'row_refs':refs},{'path':'fixture','sha256':'f'},workers=2)
            assert result['counts']==dict(total=2,materialized=0,unknown=2)
            assert budget.inflight==0
            assert len(list((root/'score_action/stock_cache').rglob('*.json')))==2
            assert any('stock_cache' in path for path in claim.observed)
    finally:governance._ACTIVE.reset(token)


def test_real_f10_request_limit_prevents_content_fetch(tmp_path):
    from ops import research_panel_f10 as f10
    plan,_=make_plan(tmp_path,max_response_bytes=16)
    class Api:
        def connect(self,*args):return True
        def get_company_info_category(self,*args):return [{'filename':'f','start':0,'length':1000}]
        def get_company_info_content(self,*args):pytest.fail('oversized request cannot reach vendor')
        def disconnect(self):pass
    with capacity.writer_scope(plan,symbol='000001.SZ',roots=[tmp_path]):
        with pytest.raises(capacity.CapacityProofError,match='RESPONSE_BOUND|REQUEST_BOUND'):
            f10.fetch_one('000001.SZ','SZ',api_factory=Api,vendor=(SimpleNamespace(),None))


def test_capacity_failure_passes_real_daily_catch_and_png_gate(tmp_path,monkeypatch):
    from ops import research_daily_product_parallel as parallel
    from ops import render_original_formula_projection as projection
    plan,_=make_plan(tmp_path)
    context=SimpleNamespace(root=tmp_path,target=20261123,scope=['000001.SZ'],identity={},
        engine=lambda:SimpleNamespace(compute=lambda *_:None),unchanged=lambda:None)
    monkeypatch.setattr(parallel,'_CONTEXT',context);monkeypatch.setattr(parallel,'_PARTS',tmp_path)
    monkeypatch.setattr(product,'compute_stock',lambda *a,**k:(_ for _ in ()).throw(capacity.CapacityProofError('FIXTURE_SERIALIZER_CAP')))
    with capacity.writer_scope(plan,symbol='000001.SZ',roots=[tmp_path]):
        with pytest.raises(capacity.CapacityProofError,match='FIXTURE_SERIALIZER_CAP'):parallel.checkpoint('000001.SZ')
        with pytest.raises(capacity.CapacityProofError,match='OWNER_PNGS'):projection.owner_pngs([])
    assert not (tmp_path/'000001.SZ.json').exists()


def publication_fixture(tmp_path,monkeypatch):
    from ops import research_panel_top200 as top
    from ops import sync_stock_history_completion as sync
    root=tmp_path/'product';root.mkdir();(root/'events').mkdir()
    lock=tmp_path/'owner.lock';lock.touch()
    monkeypatch.setattr(sync,'DEFAULT_OWNER_LOCK',lock)
    monkeypatch.setattr(sync,'_inherited_owner_duplicate',lambda *_:None)
    numeric=product.save(root/'numeric.json',{'fixture_source':'exact'})
    product.save(root/'index.json',{'dates':{'20261123':numeric}})
    product.save(root/'events/latest.json',{'data_date':'20261123','manifest':numeric})
    payload=dict(data_date='20261123',numeric_manifest=numeric,top200=[{'symbol':'000001.SZ'}],source_generation='g')
    return root,payload,top,sync


def test_real_top200_staging_publish_and_replay(tmp_path,monkeypatch):
    root,payload,top,sync=publication_fixture(tmp_path,monkeypatch)
    plan,_=make_plan(tmp_path,'top200')
    claim=TraceClaim()
    with capacity.writer_scope(plan,claim=claim,roots=[root]) as budget:
        staged=top.stage(payload,root,root/'stage',product.reference(product.__file__))
        result=sync.publish(staged)
        assert result['status']=='PUBLISHED_TOP200'
        index=json.loads((root/'index.json').read_bytes())
        event=json.loads((root/'events/latest.json').read_bytes())
        assert index['top200']['20261123']==event['top200']
        assert top.load(event['top200'])==payload
        assert budget.spent>0


def test_real_top200_pair_preflight_and_exact_rollback_capacity(tmp_path,monkeypatch):
    root,payload,top,sync=publication_fixture(tmp_path,monkeypatch)
    staged=top.stage(payload,root,root/'stage',product.reference(product.__file__))
    before={path:path.read_bytes()for path in (root/'index.json',root/'events/latest.json')}
    plan,_=make_plan(tmp_path,'top200')
    claim=TraceClaim()
    with capacity.writer_scope(plan,claim=claim,roots=[root]) as budget:
        # The full forward/rollback group cannot be split across a quota gate.
        budget.limit=4096
        with pytest.raises(capacity.CapacityProofError,match='PUBLICATION_CONTROL_SLOT'):
            sync.publish(staged)
    assert all(path.read_bytes()==raw for path,raw in before.items())
    assert not list((root/'top200').rglob('*.json')) if (root/'top200').exists() else True

    # Inject an actual event writer failure after the original index write.
    original=product.save
    def fail_event(path,value,*args,**kwargs):
        if Path(path)==root/'events/latest.json':raise OSError('FIXTURE_EVENT_WRITE')
        return original(path,value,*args,**kwargs)
    # publish loads the pinned owner under an alias. Replace only its loader's
    # module execution output to intercept that real serializer at its call.
    execute=sync.importlib.util.spec_from_file_location
    def loader(name,path):
        spec=execute(name,path)
        original_exec=spec.loader.exec_module
        def exec_module(module):
            original_exec(module)
            if name=='accepted_history_sync_owner':module.save=fail_event
        spec.loader.exec_module=exec_module
        return spec
    monkeypatch.setattr(sync.importlib.util,'spec_from_file_location',loader)
    with capacity.writer_scope(plan,claim=claim,roots=[root]):
        with pytest.raises(OSError,match='FIXTURE_EVENT_WRITE'):sync.publish(staged)
    assert all(path.read_bytes()==raw for path,raw in before.items())


def test_f10_and_supplement_serializers_are_prewrite_and_failures_escape(tmp_path):
    from ops import research_panel_f10 as f10
    from ops._formula_groups_daily_parts import workbench_supplements as supplements
    plan,_=make_plan(tmp_path,max_file_bytes=16)
    root=tmp_path/'output';root.mkdir()
    with capacity.writer_scope(plan,symbol='000001.SZ',roots=[root]):
        for invoke in (lambda:f10._write(root/'f10.json',{'large':'x'*100}),
                       lambda:supplements._immutable(root/'supplement',{'large':'x'*100}),
                       lambda:supplements._atomic_pointer(root/'pointer.json',{'large':'x'*100},'ABSENT')):
            with pytest.raises(capacity.CapacityProofError,match='SINGLE_WRITE_BOUND'):invoke()
    assert not list(root.iterdir())


def test_immutable_reuse_does_not_consume_slot_twice(tmp_path):
    plan,_=make_plan(tmp_path,scope=('000001.SZ',),max_files_per_symbol=1)
    root=tmp_path/'out';root.mkdir()
    with capacity.writer_scope(plan,symbol='000001.SZ',roots=[root]) as budget:
        before=product.save(root/'one.json',{'v':1},immutable=True)
        assert product.save(root/'one.json',{'v':1},immutable=True)==before
        assert budget.file_count==1 and budget.spent==4096


def test_noncanonical_top200_preimage_rejected_before_publication(tmp_path,monkeypatch):
    root,payload,top,sync=publication_fixture(tmp_path,monkeypatch)
    index=root/'index.json';value=json.loads(index.read_bytes());index.write_text(json.dumps(value,indent=2))
    staged=top.stage(payload,root,root/'stage',product.reference(product.__file__))
    before=index.read_bytes();plan,_=make_plan(tmp_path,'top200');claim=TraceClaim()
    with capacity.writer_scope(plan,claim=claim,roots=[root]):
        with pytest.raises(capacity.CapacityProofError,match='PREIMAGE_NONCANONICAL'):sync.publish(staged)
    assert index.read_bytes()==before
    assert not (root/'top200').exists()


def test_receipt_slot_is_held_before_business_writes(tmp_path):
    plan,_=make_plan(tmp_path,scope=('000001.SZ',),fixed=4096,slot=4096,receipt_bytes=4096)
    root=tmp_path/'out';root.mkdir();claim=TraceClaim()
    with capacity.writer_scope(plan,claim=claim,roots=[root]) as budget:
        budget.limit=8192
        product.save(root/'business.json',{'v':1})
        with pytest.raises(capacity.CapacityProofError,match='WRITE_SLOT'):product.save(root/'extra.json',{'v':2})
        with capacity.control_writes():product.save(root/'failure.json',{'status':'CANNOT_CONFIRM'})
        assert budget.control_remaining==0
    assert {p.name for p in root.iterdir()}=={'business.json','failure.json'}


def test_supplement_actual_public_entry_routes_through_real_claim(tmp_path,monkeypatch):
    from ops._formula_groups_daily_parts import workbench_supplements as supplements
    plan,policy=make_plan(tmp_path,scope=('000001.SZ',),slot=1024*1024)
    product_root=tmp_path/'products';product_root.mkdir();group_root=tmp_path/'groups';group_root.mkdir()
    runs=tmp_path/'runs';runs.mkdir();ledger=tmp_path/'ledger'
    policy.update(data_root=str(tmp_path),run_root=str(runs),formal_roots={},pointers={},keep_completed=2)
    policy['governance'].update(enabled=True,pool_id='FIXTURE_SUPPLEMENT_ONLY',pool_identity_verified=True,
        registry_root=str(ledger),ordinary_peak_budget_bytes=261*1024**3,
        product_output_roots=[str(product_root),str(group_root)])
    ref=product.save(tmp_path/'source-ref.json',{'source':'bound'})
    formula=product.save(tmp_path/'formula.json',{'observation_date':'2026-11-24'})
    context=SimpleNamespace(root=product_root,data_root=tmp_path,target=20261123,scope=['000001.SZ'],
        identity={'generation':'g','input_sha256':'i'},receipt_ref=ref,snapshot_ref=ref,config_ref=ref,reader_ref=ref,
        read=lambda symbol:([{'trade_date':20261123}],None),unchanged=lambda:None)
    monkeypatch.setattr(governance,'configured_policy',lambda:policy)
    monkeypatch.setattr(supplements,'_numeric_product',lambda context:(ref,{}, {'row_refs':{'000001.SZ':ref}},{}))
    monkeypatch.setattr(supplements,'_group_identity',lambda *args:('2026-11-23',['000001.SZ'],'fixture-roster'))
    def owned(context,root,formula,receipt):
        assert capacity.current_writer() is not None
        value={'status':'PARTIAL','roster':['000001.SZ']}
        pointer=Path(root)/'2026-11-23/supplements/latest.json'
        pointer.parent.mkdir(parents=True,exist_ok=True)
        ref=supplements._atomic_pointer(pointer,value,'ABSENT')
        return {'status':'PARTIAL','pointer':ref}
    monkeypatch.setattr(supplements,'_complete_owned',owned)
    result=supplements.complete(context,group_root,formula,ref)
    assert result['status']=='PARTIAL'
    state=json.loads((ledger/'registry.json').read_bytes());rows=list(state['tasks'].values())
    assert len(rows)==1 and rows[0]['state']=='READY'
    assert rows[0]['reserved_bytes']==0 and rows[0]['logical_written_bytes']>0


def test_prepaid_file_count_includes_all_inflight_slots(tmp_path):
    plan,_=make_plan(tmp_path,scope=('000001.SZ',),max_files=2,max_files_per_symbol=2)
    root=tmp_path/'out';root.mkdir();claim=TraceClaim()
    with capacity.writer_scope(plan,claim=claim,roots=[root]) as budget:
        held=budget.reserve('000001.SZ')
        before=list(claim.checkpoints)
        with pytest.raises(capacity.CapacityProofError,match='PUBLICATION_CONTROL_SLOT'):
            with capacity.prepaid_writes([(root/'extra.json',b'{}\n',1)]):
                pytest.fail('file budget must reject before any writer')
        assert not list(root.iterdir()) and claim.checkpoints==before
        assert budget.inflight_files==2 and budget.file_count==0
        budget.settle(held)
        with capacity.prepaid_writes([(root/'allowed.json',b'{}\n',1)]):
            with capacity.serialized_write(root/'allowed.json',b'{}\n'):
                (root/'allowed.json').write_bytes(b'{}\n')
        assert budget.file_count==1 and budget.inflight_files==0


def daily_completion_fixture(tmp_path,monkeypatch):
    from ops import research_daily_product_parallel as parallel
    from ops import complete_workbench_v192_assets as v192
    root=tmp_path/'daily';root.mkdir();symbol='000001.SZ'
    row=dict(symbol=symbol,display_name='fixture',data_date='20261123',groups='',pending_groups='',
        evaluation={'groups':{g:{'status':'FALSE'}for g in product.GROUPS}},historical_coverage={},statistics=None,**product.FLAGS)
    row_ref=product.save(root/'retained-row.json',row)
    product.save(root/'index.json',{'dates':{'20261120':{'previous':True}}})
    product.save(root/'events/latest.json',{'data_date':'20261120'})
    context=SimpleNamespace(d30_projection=None,root=root,target=20261123,scope=[symbol],source_scope=[symbol],
        current_universe_exclusions={},identity={'input_sha256':'i'},generation='g',config_ref={},snapshot_ref={},unchanged=lambda:None)
    monkeypatch.setattr(product,'SourceContext',lambda *_:context)
    monkeypatch.setattr(parallel,'prefill_missing',lambda *_args,**_kwargs:{'chart_gaps':{}})
    monkeypatch.setattr(product,'read_complete_daily_rows',lambda *_: [(dict(row),row_ref)])
    monkeypatch.setattr(score,'materialize',lambda *_args,**_kwargs:{'status':'READY'})
    monkeypatch.setattr(v192,'at_numeric_completion',lambda *_args,**_kwargs:{'status':'UNKNOWN'})
    monkeypatch.delenv('V4_WORKBENCH_STATISTICS_ROOT',raising=False)
    monkeypatch.delenv('V4_RESEARCH_EVENT_CASE_CACHE',raising=False)
    return root


def test_real_daily_completion_quota_does_not_advance_either_pointer(tmp_path,monkeypatch):
    root=daily_completion_fixture(tmp_path,monkeypatch)
    before={path:path.read_bytes()for path in (root/'index.json',root/'events/latest.json')}
    plan,_=make_plan(tmp_path,scope=('000001.SZ',),max_files=4,max_files_per_symbol=1)
    with capacity.writer_scope(plan,claim=TraceClaim(),roots=[root]):
        with pytest.raises(capacity.CapacityProofError,match='PUBLICATION_CONTROL_SLOT'):
            product.materialize_daily_product(data_root=tmp_path,target=20261123,original_charts=False)
    assert all(path.read_bytes()==raw for path,raw in before.items())


def test_real_daily_completion_event_io_error_restores_exact_pair(tmp_path,monkeypatch):
    root=daily_completion_fixture(tmp_path,monkeypatch)
    # Exact rollback also covers historical JSON formatting.
    (root/'index.json').write_text(json.dumps(json.loads((root/'index.json').read_bytes()),indent=2))
    before={path:path.read_bytes()for path in (root/'index.json',root/'events/latest.json')}
    original=product.save
    def fail_event(path,value,*args,**kwargs):
        if Path(path)==root/'events/latest.json':raise OSError('DAILY_EVENT_IO_FIXTURE')
        return original(path,value,*args,**kwargs)
    monkeypatch.setattr(product,'save',fail_event)
    plan,_=make_plan(tmp_path,scope=('000001.SZ',))
    with capacity.writer_scope(plan,claim=TraceClaim(),roots=[root]):
        with pytest.raises(OSError,match='DAILY_EVENT_IO_FIXTURE'):
            product.materialize_daily_product(data_root=tmp_path,target=20261123,original_charts=False)
    assert all(path.read_bytes()==raw for path,raw in before.items())


def test_real_daily_statistics_failure_restores_pair_and_module_pointer(tmp_path,monkeypatch):
    from ops import build_mac_workbench as workbench
    root=daily_completion_fixture(tmp_path,monkeypatch)
    statistics=tmp_path/'statistics';(statistics/'2026-11-23').mkdir(parents=True)
    head=statistics/'2026-11-23/latest.json'
    head.write_bytes(b'{"prior_module":true}\n')
    before={path:path.read_bytes()for path in (root/'index.json',root/'events/latest.json',head)}
    monkeypatch.setenv('V4_WORKBENCH_STATISTICS_ROOT',str(statistics))
    def fail_after_stats_index(product_root,output):
        index=json.loads((product_root/'index.json').read_bytes())
        assert index['latest_date']=='20261123'
        artifact=product.save(output/'2026-11-23/statistics.json',{'numeric_manifest':index['dates']['20261123']})
        product.save(head,{'date':'2026-11-23','artifact':artifact})
        raise capacity.CapacityProofError('STATS_AFTER_MODULE_POINTER')
    monkeypatch.setattr(workbench,'materialize_statistics',fail_after_stats_index)
    plan,_=make_plan(tmp_path,scope=('000001.SZ',))
    with capacity.writer_scope(plan,claim=TraceClaim(),roots=[root,statistics]):
        with pytest.raises(capacity.CapacityProofError,match='STATS_AFTER_MODULE_POINTER'):
            product.materialize_daily_product(data_root=tmp_path,target=20261123,original_charts=False)
    assert all(path.read_bytes()==raw for path,raw in before.items())


def test_supplement_immutable_reuse_has_zero_new_charge(tmp_path):
    from ops._formula_groups_daily_parts import workbench_supplements as supplements
    root=tmp_path/'out';root.mkdir();value={'v':1}
    ref=supplements._immutable(root,value);path=Path(ref['path']);before=path.stat()
    plan,_=make_plan(tmp_path,scope=('000001.SZ',));claim=TraceClaim()
    with capacity.writer_scope(plan,claim=claim,roots=[root])as budget:
        assert supplements._immutable(root,value)==ref
        assert budget.spent==budget.file_count==0 and not claim.checkpoints
    after=path.stat();assert (before.st_ino,before.st_mtime_ns)==(after.st_ino,after.st_mtime_ns)
    path.write_bytes(b'conflicting bytes')
    with capacity.writer_scope(plan,claim=claim,roots=[root]):
        with pytest.raises(ValueError,match='IMMUTABLE_CONFLICT'):supplements._immutable(root,value)
    assert path.read_bytes()==b'conflicting bytes'
