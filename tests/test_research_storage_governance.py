"""Tiny fixtures and controlled failure injection; never touch active assets."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_storage_governance as g
from ops import research_storage_retention as r


@pytest.fixture
def policy(tmp_path,monkeypatch):
    root=tmp_path/'outputs';root.mkdir()
    value=dict(data_root=str(tmp_path),run_root=str(root),formal_roots={},governance=dict(
        enabled=True,registry_root=str(tmp_path/'registry'),pool_id='test-apfs-shared-container',
        pool_identity_verified=True,ordinary_peak_budget_bytes=200*g.GIB,
        debug_output_roots=[str(tmp_path/'debug')],product_output_roots=[str(root)]))
    monkeypatch.setattr(g.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=200*g.GIB,total=1000*g.GIB))
    return value


def claim(policy,key='a',directory=None,predicted=1024*1024,**kwargs):
    return g.admission(policy,key=key,directory=directory or Path(policy['run_root'])/key,predicted=predicted,**kwargs)


def complete(active,directory,content=b'valid'):
    directory=Path(directory);directory.mkdir(exist_ok=True,parents=True)
    path=directory/'result';active.watch(path);active.checkpoint(incoming=len(content))
    path.write_bytes(content);active.observe(path)
    result=dict(status='READY',path=str(path))
    active.finish(result,[path]);return result


def test_three_serial_invocations_one_materialization_across_entry_names(policy):
    directory=Path(policy['run_root'])/'a';made=[]
    for entry in ['daily','retry','another-entry']:
        with claim(policy) as (active,cached):
            if cached is None:
                made.append(entry);cached=complete(active,directory)
            assert Path(cached['path']).read_bytes()==b'valid'
    assert made==['daily']
    assert list(directory.iterdir())==[directory/'result']


def test_identity_ignores_presentation_and_binds_dirty_input_order_schema():
    inputs=dict(snapshot='abc',revision='20260101')
    def identity(scope=('000001.SZ','600000.SH'),formula='v1',schema=('date','close')):
        return g.computation_identity(inputs=inputs,scope=list(scope),calculation=dict(formula=formula),schema=list(schema))
    original=identity()
    # Repository commit/style/path aren't accepted identity parameters.
    assert identity()==original
    assert identity(formula='dirty bytes')!=original
    assert identity(scope=('600000.SH','000001.SZ'))!=original
    assert identity(schema=('date','close','signal'))!=original
    inputs['revision']='historical correction';assert identity()!=original


@pytest.mark.parametrize('damage',['missing','corrupt'])
def test_success_marker_does_not_hide_missing_or_corrupt_result(policy,damage):
    with claim(policy) as (active,_):result=complete(active,Path(policy['run_root'])/'a')
    path=Path(result['path'])
    if damage=='missing':path.unlink()
    else:path.write_bytes(b'wrong')
    (path.parent/'SUCCESS').write_text('READY')
    with pytest.raises((r.RetentionError,FileNotFoundError)):
        with claim(policy):pytest.fail('invalid READY must not be accepted')


def test_failed_half_output_resumes_original_directory_preserves_valid_shard(policy):
    directory=Path(policy['run_root'])/'a';directory.mkdir()
    good=directory/'verified-stock';good.write_bytes(b'complete')
    original=r.digest(good)
    with pytest.raises(RuntimeError):
        with claim(policy) as (active,_):
            partial=directory/'pending';active.watch(partial);partial.write_bytes(b'half');active.observe(partial)
            raise RuntimeError('injected interruption')
    with pytest.raises(r.RetentionError,match='ORIGINAL_DIRECTORY'):
        with claim(policy,directory=Path(policy['run_root'])/'new'):pass
    with claim(policy) as (active,cached):
        assert cached is None and r.digest(good)==original
        result=complete(active,directory,b'uninterrupted-equivalent')
    assert Path(result['path']).read_bytes()==b'uninterrupted-equivalent'


def test_same_process_nested_claim_does_not_release_outer_reservation(policy):
    with claim(policy) as (outer,_):
        with claim(policy) as (inner,_):
            assert inner is outer
            inner.finish(dict(status='READY'),[])
        row=outer.registry.read()['tasks']['a']
        assert row['state']=='RUNNING' and row['reserved_bytes']>0
        with pytest.raises(r.RetentionError,match='NESTED_TASK'):
            with claim(policy,key='different'):pass
        complete(outer,Path(policy['run_root'])/'a')


def test_other_thread_competes_for_kernel_pool_lock_even_different_directory(policy):
    with claim(policy) as (active,_):
        with ThreadPoolExecutor(1) as pool:
            def other():
                with claim(policy,key='b'):pass
            with pytest.raises(r.RetentionError,match='POOL_WRITER_BUSY'):
                pool.submit(other).result()
        complete(active,Path(policy['run_root'])/'a')


def test_lowspace_preflight_creates_no_output_and_status_read_never_writes(policy,monkeypatch):
    monkeypatch.setattr(g.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=63*g.GIB,total=1000*g.GIB))
    with pytest.raises(g.SpaceBlocked):
        with claim(policy):pytest.fail('no writes')
    assert not (Path(policy['run_root'])/'a').exists()
    before={str(p):p.stat().st_mtime_ns for p in Path(policy['governance']['registry_root']).iterdir()}
    status=g.read_only_status(policy)
    after={str(p):p.stat().st_mtime_ns for p in Path(policy['governance']['registry_root']).iterdir()}
    assert before==after and status['free_bytes']==63*g.GIB


def test_midwrite_space_drop_preserves_checkpoint_and_current_and_retains_reservation(policy,monkeypatch):
    current=Path(policy['data_root'])/'CURRENT';current.write_bytes(b'old-current')
    with pytest.raises(g.SpaceBlocked):
        with claim(policy) as (active,_):
            directory=Path(active.directory);directory.mkdir()
            checkpoint=directory/'verified';active.watch(checkpoint);checkpoint.write_bytes(b'good');active.observe(checkpoint)
            monkeypatch.setattr(g.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=50*g.GIB,total=1000*g.GIB))
            active.checkpoint()
    assert current.read_bytes()==b'old-current' and checkpoint.read_bytes()==b'good'
    registry=g.Registry(g.configuration(policy),policy['data_root'])
    row=registry.read()['tasks']['a'];assert row['state']=='SPACE_BLOCKED'
    assert registry.remaining(row)>0


def test_remaining_reservation_not_double_counting_already_written(policy,monkeypatch):
    with claim(policy,predicted=2*g.GIB) as (active,_):
        state=active.registry.read();state['tasks']['a']['written_bytes']=g.GIB
        # Tiny fault-injected accounting values; no GiB file is ever allocated.
        sample=active.registry.space(state,'a',active.registry.remaining(state['tasks']['a']),category='ordinary',optional_full=False)
        assert sample['remaining_bytes']==g.GIB
        state['tasks']['other']=dict(state='FAILED_RECOVERABLE',reserved_bytes=3*g.GIB,written_bytes=2*g.GIB,category='ordinary')
        sample=active.registry.space(state,'a',g.GIB,category='ordinary',optional_full=False)
        assert sample['other_remaining_bytes']==g.GIB
        complete(active,Path(policy['run_root'])/'a')


def test_atomic_competing_reservations_do_not_overgrant(policy,monkeypatch):
    registry=g.Registry(g.configuration(policy),policy['data_root'])
    with registry.transaction():
        state=registry.read();state['tasks']['unreconciled']=dict(state='FAILED_RECOVERABLE',category='ordinary',
            directory=str(Path(policy['run_root'])/'other'),owner=dict(pid=999999,started='dead'),reserved_bytes=100*g.GIB,written_bytes=0)
        registry.save(state)
    monkeypatch.setattr(g.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=170*g.GIB,total=1000*g.GIB))
    with pytest.raises(g.SpaceBlocked,match='RESERVATION'):
        with claim(policy,predicted=3*g.GIB):pass
    assert registry.read()['tasks']['unreconciled']['reserved_bytes']==100*g.GIB


def test_unknown_owner_and_reused_pid_never_blindly_released(policy,monkeypatch):
    registry=g.Registry(g.configuration(policy),policy['data_root'])
    with registry.transaction():
        state=registry.read();state['tasks']['old']=dict(state='RUNNING',category='ordinary',
            directory=str(Path(policy['run_root'])/'old'),owner=g.process_identity(),reserved_bytes=10,written_bytes=0)
        registry.save(state)
    with pytest.raises(r.RetentionError,match='OWNER_LIVE_OR_UNKNOWN'):
        with claim(policy):pass
    monkeypatch.setattr(g,'process_identity',lambda pid=None:dict(pid=pid or os.getpid(),started='reused-process'))
    assert g.owner_state(dict(pid=os.getpid(),started='earlier-process'))=='DEAD'
    with pytest.raises(r.RetentionError,match='RECONCILIATION'):
        with claim(policy):pass


def test_registry_failure_does_not_block_existing_safe_reads(policy):
    root=Path(policy['governance']['registry_root']);root.mkdir();(root/'registry.json').write_bytes(b'{half')
    current=Path(policy['data_root'])/'READY';current.write_bytes(b'existing')
    assert g.read_only_status(policy)['status']=='REGISTRY_UNAVAILABLE_SAFE_READS_UNAFFECTED'
    assert current.read_bytes()==b'existing'
    with pytest.raises(ValueError):
        with claim(policy):pass


@pytest.mark.parametrize('limit',['own_budget_bytes','max_registry_bytes','max_tasks'])
def test_governance_own_evidence_bound_blocks_new_work_without_deleting(policy,limit):
    policy['governance'][limit]=1
    if limit=='max_tasks':
        with claim(policy,key='first') as (active,_):complete(active,Path(policy['run_root'])/'first')
    with pytest.raises(r.RetentionError,match='BUDGET'):
        with claim(policy):pass
    assert not (Path(policy['run_root'])/'a').exists()


def test_ratio_and_optional_full_tighter_boundary(policy,monkeypatch):
    monkeypatch.setattr(g.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=120*g.GIB,total=1000*g.GIB))
    with pytest.raises(g.SpaceBlocked,match='RATIO'):
        with claim(policy,optional_full=True):pass
    with claim(policy) as (active,_):complete(active,Path(policy['run_root'])/'a')


def test_all_registered_debug_roots_share_category_budget(policy):
    policy['governance']['debug_budget_bytes']=50
    with pytest.raises(g.SpaceBlocked,match='CATEGORY'):
        with claim(policy,predicted=100,category='debug'):pass


def test_file_and_job_limits_refuse_instead_of_truncate(policy,tmp_path):
    rows=pd.DataFrame(dict(ts_code=['000001.SZ']*30,trade_date=list(range(20260101,20260131)),close=np.arange(30,dtype=float)))
    source=tmp_path/'source.parquet';pq.write_table(pa.Table.from_pandas(rows),source)
    policy['governance']['max_debug_file_bytes']=1
    with pytest.raises(g.SpaceBlocked,match='DEBUG_FILE'):
        g.debug_projection(policy=policy,source=source,output_root=tmp_path/'debug')
    assert not list((tmp_path/'debug').rglob('*.parquet'))
    policy['governance']['max_debug_file_bytes']=64*g.MIB;policy['governance']['max_debug_job_bytes']=1
    with pytest.raises(g.SpaceBlocked,match='MEMORY_OUTPUT'):
        g.debug_projection(policy=policy,source=source,output_root=tmp_path/'debug')


def test_default_three_stocks_twenty_days_projects_exact_formal_values_with_full_lookback(policy,tmp_path):
    frames=[]
    for code in ['000001.SZ','600000.SH','000002.SZ','000003.SZ']:
        close=pd.Series(np.linspace(10,30,140))
        ema=close.ewm(span=120,adjust=False).mean()
        frames.append(pd.DataFrame(dict(ts_code=code,trade_date=np.arange(20260001,20260141),close=close,
            long_ema=ema,nullable_signal=[None]*125+[True]*15,buy_gate=False)))
    formal=pd.concat(frames,ignore_index=True);source=tmp_path/'formal.parquet'
    pq.write_table(pa.Table.from_pandas(formal,preserve_index=False),source)
    result=g.debug_projection(policy=policy,source=source,output_root=tmp_path/'debug',columns=list(formal.columns))
    actual=pq.read_table(result['output']).to_pandas()
    expected=formal[formal.ts_code.isin(result['symbols'])&formal.trade_date.isin(result['dates'])].reset_index(drop=True)
    pd.testing.assert_frame_equal(actual,expected,check_exact=True)
    assert len(result['symbols'])==3 and len(result['dates'])==20 and actual.shape[0]==60
    # EMA uses all 140 rows in authoritative source, not the output's 20 rows.
    truncated=expected[expected.ts_code==result['symbols'][0]].close.ewm(span=120,adjust=False).mean().iloc[0]
    assert actual.long_ema.iloc[0]!=truncated
    assert g.debug_projection(policy=policy,source=source,output_root=tmp_path/'debug',columns=list(formal.columns))==result
    assert len(list((tmp_path/'debug').glob('*/projection.parquet')))==1


def test_actual_qfq_checkpoint_rejects_half_file_reuses_verified_stock_and_matches_baseline(policy,tmp_path,monkeypatch):
    from ops import research_panel_qfq as q
    before=r.digest(Path(q.__file__));calls=[]
    def compute(code,item,target,driver):
        calls.append(code);return pd.DataFrame(dict(ts_code=[code]*3,trade_date=['20260101','20260102','20260103'],close=[1.,2.,3.]))
    monkeypatch.setattr(q,'rebuild_symbol',compute)
    identity=dict(input_sha256='snapshot',formula_sha256='sameformula')
    root=tmp_path/'checkpoint';root.mkdir();(root/'000001.SZ.parquet').write_bytes(b'half')
    q._symbol_checkpoint('000001.SZ',{},20260103,identity,root,{},None)
    original=r.digest(root/'000001.SZ.parquet')
    q._symbol_checkpoint('000001.SZ',{},20260103,identity,root,{},None)
    assert calls==['000001.SZ']
    baseline=tmp_path/'baseline';baseline.mkdir()
    q._symbol_checkpoint('000001.SZ',{},20260103,identity,baseline,{},None)
    assert r.digest(baseline/'000001.SZ.parquet')==original
    assert before==r.digest(Path(q.__file__))==r.CERTIFIED_QFQ_OWNER


def test_scoped_qfq_writer_proxy_restores_after_failure_does_not_mutate_pyarrow(policy,tmp_path):
    from ops import research_panel_qfq as q
    originals={name:getattr(q,name) for name in ('pq','_write','ThreadPoolExecutor','_symbol_checkpoint','publish_pair')}
    shared_writer=pq.ParquetWriter
    with pytest.raises(RuntimeError,match='injected'):
        with claim(policy) as (active,_):
            with g.qfq_write_seams(q,active):
                assert q.pq is not pq and pq.ParquetWriter is shared_writer
                table=pa.table(dict(x=[1,2]))
                with q.pq.ParquetWriter(tmp_path/'file.parquet',table.schema) as writer:writer.write_table(table)
                raise RuntimeError('injected')
    assert all(getattr(q,name) is value for name,value in originals.items())


def test_qfq_write_seam_blocks_before_next_data_write_and_allows_bounded_failure_receipt(policy,tmp_path,monkeypatch):
    from ops import research_panel_qfq as q
    with claim(policy) as (active,_):
        with g.qfq_write_seams(q,active):
            q._write(tmp_path/'data',b'good')
            monkeypatch.setattr(g.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=50*g.GIB,total=1000*g.GIB))
            with pytest.raises(g.SpaceBlocked):q._write(tmp_path/'next-data',b'not-written')
            q._json(tmp_path/'stage_status.json',dict(status='FAILED',error='space'))
            assert not (tmp_path/'next-data').exists()
        active.finish(error=g.SpaceBlocked('space'))
    assert json.loads((tmp_path/'stage_status.json').read_text())['status']=='FAILED'


def test_current_verification_binds_both_panels_and_current_compute_identity(policy,tmp_path,monkeypatch):
    # Tiny owner metadata fixture; no actual authority refresh/compute invoked.
    identity=dict(input_sha256='snapshot',formula_sha256='formula',turnover_input_sha256='turnover')
    generation='a'*64;run=Path(policy['run_root'])/('qfq_'+generation[:20]);run.mkdir()
    paths={role:tmp_path/(role+'.parquet') for role in ['selector','backtest']}
    pointers={}
    for role,path in paths.items():
        path.write_bytes(role.encode());ptr=tmp_path/(role+'.txt');ptr.write_text(str(path));pointers[role]=str(ptr)
    policy['pointers']=pointers
    policy['formal_roots']={role:str(tmp_path) for role in paths}
    status=dict(status='READY',generation_id=generation,run_dir=str(run),selector_pointer_ready=True,backtest_pointer_ready=True,**r.FLAGS,candidates={k:str(v) for k,v in paths.items()},candidate_sha256={k:r.digest(v) for k,v in paths.items()})
    (run/'stage_status.json').write_text(json.dumps(status));(run/'candidate_receipt.json').write_text(json.dumps(status))
    owner=types.SimpleNamespace(input_path=lambda data:tmp_path/'snapshot',load_snapshot=lambda p,t:{},
        generation_identity=lambda *a:{k:v for k,v in identity.items() if k!='turnover_input_sha256'},
        panel_contract=lambda p:dict(asof_date=20260101,generation_id=generation,**identity))
    turnover=types.ModuleType('ops.research_panel_turnover');turnover.load_daily=lambda *a:types.SimpleNamespace(identity='turnover')
    monkeypatch.setitem(sys.modules,'ops.research_panel_turnover',turnover)
    kwargs=dict(driver_path=tmp_path/'driver',formula_path=tmp_path/'formula',contract_csv=tmp_path/'contract',tdx_root=tmp_path)
    assert g.verified_qfq_current(owner,policy,20260101,kwargs)['already_current']
    paths['backtest'].write_bytes(b'corrupt')
    with pytest.raises(r.RetentionError,match='CURRENT_ARTIFACT_CORRUPT'):g.verified_qfq_current(owner,policy,20260101,kwargs)
    identity['formula_sha256']='new-formula'
    owner.panel_contract=lambda p:dict(asof_date=20260101,generation_id=generation,input_sha256='snapshot',formula_sha256='formula',turnover_input_sha256='turnover')
    assert g.verified_qfq_current(owner,policy,20260101,kwargs) is None


def test_real_subprocess_claim_collision_and_dead_owner_same_directory_resume(tmp_path):
    # Real flock and process liveness, no disk allocation beyond small JSON.
    root=tmp_path/'out';root.mkdir()
    policy=dict(data_root=str(tmp_path),run_root=str(root),formal_roots={},governance=dict(enabled=True,
        registry_root=str(tmp_path/'registry'),pool_id='same-pool',pool_identity_verified=True))
    config=tmp_path/'policy.json';config.write_text(json.dumps(policy));marker=tmp_path/'started'
    script='''import json,sys,time,os
from pathlib import Path
from ops.research_storage_governance import admission
p=json.loads(Path(sys.argv[1]).read_text())
with admission(p,key='same',directory=Path(p['run_root'])/'same',predicted=1024*1024) as (claim,_):
 Path(sys.argv[2]).write_text('owner')
 time.sleep(30)
'''
    process=subprocess.Popen([sys.executable,'-c',script,str(config),str(marker)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        deadline=time.monotonic()+10
        while not marker.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        assert marker.exists(),process.communicate(timeout=1)
        with pytest.raises(r.RetentionError,match='POOL_WRITER_BUSY'):
            with g.admission(policy,key='same',directory=root/'same',predicted=1024*1024):pass
        # Terminate ONLY this test's own process to simulate owner crash.
        process.kill();process.wait(timeout=5)
        with g.admission(policy,key='same',directory=root/'same',predicted=1024*1024) as (active,_):
            assert active.registry.read()['tasks']['same']['resumed']
            complete(active,root/'same')
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)
        process.stdout.close();process.stderr.close()


def test_actual_dispatch_seams_use_function_local_imports_and_no_numeric_owner_diff():
    import ast
    root=Path(__file__).resolve().parents[1]
    gate=ast.parse((root/'ops/macos_research_panel_daily_gate.py').read_text())
    run_a=next(node for node in ast.walk(gate) if isinstance(node,ast.FunctionDef) and node.name=='run_a')
    assert any(isinstance(node,ast.ImportFrom) and node.module=='ops.research_storage_governance' for node in ast.walk(run_a))
    assert any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='governed_product' for node in ast.walk(run_a))
    scheduler=(root/'infrastructure/scheduling/executor_registry.py').read_text()
    assert 'governed_product(complete_daily_derivatives,' in scheduler
    assert 'governed_product(materialize_daily_product,' in scheduler
    assert r.digest(root/'ops/research_panel_qfq.py')==r.CERTIFIED_QFQ_OWNER


def test_original_pair_publication_rollback_is_not_blocked_mid_transaction(policy,tmp_path,monkeypatch):
    from ops import research_panel_qfq as q
    pointers={role:tmp_path/(role+'.txt') for role in ['selector','backtest']}
    old={role:tmp_path/('old-'+role) for role in pointers}
    new={role:tmp_path/('new-'+role) for role in pointers}
    for role,path in pointers.items():
        old[role].write_bytes(b'old');new[role].write_bytes(b'new');path.write_text(str(old[role])+'\n')
    expected={role:path.read_bytes() for role,path in pointers.items()}
    original=q._write;failed=False
    def injected(path,payload):
        nonlocal failed
        original(path,payload)
        if Path(path)==pointers['selector'] and not failed:
            failed=True
            monkeypatch.setattr(g.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=30*g.GIB,total=1000*g.GIB))
            raise OSError('injected after first pointer replacement')
    monkeypatch.setattr(q,'_write',injected)
    with claim(policy,predicted=128*g.MIB) as (active,_):
        with g.qfq_write_seams(q,active):
            with pytest.raises(OSError,match='first pointer'):
                q.publish_pair(pointers,new,expected,tmp_path/'journal.json')
        assert {role:path.read_bytes() for role,path in pointers.items()}==expected
        assert json.loads((tmp_path/'journal.json').read_text())['status']=='ROLLED_BACK'
        active.finish(error=OSError('injected'))


def test_original_pair_recovery_after_prepared_journal_preserves_exact_old_pair(policy,tmp_path):
    from ops import research_panel_qfq as q
    import base64
    pointers={role:tmp_path/(role+'.txt') for role in ['selector','backtest']}
    before={role:('old-'+role+'\n').encode() for role in pointers}
    after={role:'new-'+role+'\n' for role in pointers}
    journal=tmp_path/'journal.json'
    r.atomic_json(journal,dict(status='PREPARED',pointers={r:str(p) for r,p in pointers.items()},
        before_base64={r:base64.b64encode(v).decode() for r,v in before.items()},after=after))
    pointers['selector'].write_text(after['selector']);pointers['backtest'].write_bytes(before['backtest'])
    with claim(policy) as (active,_):
        with g.qfq_write_seams(q,active):q.recover_pair(journal,pointers)
        assert {role:path.read_bytes() for role,path in pointers.items()}==before
        complete(active,Path(policy['run_root'])/'a')


def test_actual_rebound_gate_run_a_retains_local_hook_without_real_producer(policy,tmp_path,monkeypatch):
    import ast
    root=Path(__file__).resolve().parents[1]
    node=next(node for node in ast.walk(ast.parse((root/'ops/macos_research_panel_daily_gate.py').read_text()))
        if isinstance(node,ast.FunctionDef) and node.name=='run_a')
    module=ast.Module(body=[node],type_ignores=[])
    product=types.ModuleType('ops.research_panel_daily_product')
    product.materialize_daily_product=lambda **kwargs:dict(status='READY',scope=kwargs['target'])
    monkeypatch.setitem(sys.modules,'ops.research_panel_daily_product',product)
    receipt=types.ModuleType('ops.macos_research_panel_daily_receipts')
    receipt.build_a_lane_outcome=lambda *args:dict(status='READY')
    monkeypatch.setitem(sys.modules,'ops.macos_research_panel_daily_receipts',receipt)
    seen=[]
    monkeypatch.setattr(g,'governed_product',lambda fn,**kw:(seen.append(kw) or fn(**kw)))
    paths={key:str(tmp_path/key.lstrip('-')) for key in ['--a-sync-script','--a-formula-script','--a-data-root',
        '--a-selector-pointer','--a-backtest-pointer','--a-selector-seed','--a-backtest-seed','--a-contract-csv','--a-canonical-formula','--a-return-root']}
    namespace=dict(Path=Path,os=os,Any=object,SnapshotGateError=ValueError,
        args=types.SimpleNamespace(a_tdx_root=tmp_path,a_host=None,a_port=None,receipt_root=tmp_path,a_minimum_rows=1),
        authority_paths=paths,a_sync_run_budget=1,_a_day_files=lambda _:['existing'],
        run_windows_a_sync_authority=lambda *a,**k:{},run_windows_a_formula_authority=lambda *a,**k:dict(status='READY'))
    exec(compile(ast.fix_missing_locations(module),'actual-rebound-run-a','exec'),namespace)
    rebound=types.FunctionType(namespace['run_a'].__code__,namespace)
    assert rebound('20260101')['daily_product']['status']=='READY' and len(seen)==1


def test_product_parent_submit_stops_new_work_and_preserves_real_future_wait_interface(policy,tmp_path,monkeypatch):
    from concurrent.futures import wait
    parts=tmp_path/'parts';parts.mkdir()
    module=types.SimpleNamespace(ProcessPoolExecutor=ThreadPoolExecutor)
    def checkpoint(symbol):
        path=parts/(symbol+'.json');path.write_text(symbol)
        return dict(symbol=symbol,ref=dict(path=str(path),sha256=r.digest(path)))
    with claim(policy,predicted=1024*1024) as (active,_):
        original=module.ProcessPoolExecutor
        with g.product_write_seams([module],active):
            with module.ProcessPoolExecutor(max_workers=1,initargs=(None,None,str(tmp_path),str(parts))) as pool:
                future=pool.submit(checkpoint,'000001.SZ')
                done,_=wait([future]);assert future in done
                assert future.result()['symbol']=='000001.SZ'
                monkeypatch.setattr(g.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=20*g.GIB,total=1000*g.GIB))
                with pytest.raises(g.SpaceBlocked):pool.submit(checkpoint,'600000.SH')
        assert module.ProcessPoolExecutor is original
        active.finish(error=g.SpaceBlocked('drop'))
    assert (parts/'000001.SZ.json').exists() and not (parts/'600000.SH.json').exists()


def test_actual_product_adapter_preserves_original_resume_and_restores_module_seams(policy,tmp_path,monkeypatch):
    policy['governance']['product_peak_bytes']=1024*1024
    root=Path(policy['run_root'])/'daily';code=tmp_path/'owner.py';code.write_text('unchanged owner source')
    owner=types.ModuleType('ops.research_panel_daily_product');owner.__file__=str(code)
    owner.SourceContext=lambda *a:types.SimpleNamespace(identity={'generation':'original'},config_ref={'sha256':'config'},scope=['000001.SZ'],root=root)
    def save(path,value,*args,**kwargs):r.atomic_json(path,value);return dict(path=str(path),sha256=r.digest(path))
    owner.save=save;owner.root=root;owner.generated=0
    exec('''def materialize_daily_product(*,data_root,target):
 path=root/'stock.json'
 if not path.exists():
  global generated
  generated+=1
  save(path,{'symbol':'000001.SZ','values':[1.,2.,None]})
 save(root/'index.json',{'stock':str(path)})
 return {'status':'READY','path':str(path)}
''',owner.__dict__)
    monkeypatch.setitem(sys.modules,owner.__name__,owner)
    for name in ('ops.research_daily_product_parallel','ops.render_original_formula_projection'):
        monkeypatch.setitem(sys.modules,name,types.ModuleType(name))
    monkeypatch.setattr(g,'configured_policy',lambda:policy)
    for _ in range(3):
        result=g.governed_product(owner.materialize_daily_product,data_root=tmp_path,target=20260101)
        assert result['status']=='READY' and owner.save is save
    assert owner.generated==1
    assert json.loads((root/'stock.json').read_text())['values']==[1.,2.,None]


def test_committed_qfq_success_survives_registry_recording_failure(policy,tmp_path,monkeypatch):
    from ops import research_panel_qfq as q
    for name in ('driver','formula','fields','snapshot'):(tmp_path/name).write_text(name)
    monkeypatch.setattr(q,'input_path',lambda _:tmp_path/'snapshot')
    paths={role:tmp_path/(role+'.parquet') for role in ('selector','backtest')}
    for path in paths.values():path.write_bytes(b'existing-committed')
    def committed(**kwargs):return dict(status='READY',**{k:str(v) for k,v in paths.items()})
    monkeypatch.setattr(g.Claim,'finish',lambda *a,**k:(_ for _ in ()).throw(OSError('registry-full')))
    result=g.governed_qfq(committed,policy,dict(predicted_bytes=1024*1024,managed_bytes=0),
        data_root=tmp_path,return_root=Path(policy['run_root']),pointers={},target=20260101,
        driver_path=tmp_path/'driver',formula_path=tmp_path/'formula',contract_csv=tmp_path/'fields')
    assert result['status']=='READY' and result['storage_governance']['status']=='COMMITTED_REGISTRY_RECORDING_BLOCKED'
    assert all(path.read_bytes()==b'existing-committed' for path in paths.values())


def test_pending_parquet_rename_consumes_reservation_once_in_thread_checkpoint(policy,tmp_path,monkeypatch):
    from ops import research_panel_qfq as q
    monkeypatch.setattr(q,'rebuild_symbol',lambda *args:pd.DataFrame(dict(ts_code=['000001.SZ']*3,close=[1.,2.,3.])))
    parts=tmp_path/'parts';parts.mkdir()
    with claim(policy) as (active,_):
        with g.qfq_write_seams(q,active):q._symbol_checkpoint('000001.SZ',{},20260101,dict(input='exact'),parts,{},None)
        active.checkpoint()
        row=active.registry.read()['tasks']['a']
        expected=sum(path.stat().st_blocks*512 for path in parts.iterdir())
        assert row['written_bytes']==expected
        assert not list(parts.glob('*.pending'))
        active.finish(error=RuntimeError('test accounting only'))


def test_projection_output_root_cannot_escape_approved_paths(policy,tmp_path):
    source=tmp_path/'source.parquet';pq.write_table(pa.table(dict(ts_code=['000001.SZ'],trade_date=[20260101],close=[1.])),source)
    with pytest.raises(r.RetentionError,match='ROOT_NOT_APPROVED'):
        g.debug_projection(policy=policy,source=source,output_root=tmp_path/'protected-raw-inputs')
    assert not (tmp_path/'protected-raw-inputs').exists()


def test_registered_output_rejects_unverified_different_filesystem(policy,tmp_path,monkeypatch):
    policy['governance']['pool_member_devices']=[-1]
    with pytest.raises(r.RetentionError,match='OUTSIDE_VERIFIED_SHARED_POOL'):
        with claim(policy):pass
    assert not Path(policy['governance']['registry_root']).exists()


def test_registry_lock_and_unknown_state_fail_closed_in_bounded_time(policy):
    registry=g.Registry(g.configuration(policy),policy['data_root'])
    with registry.transaction():
        with pytest.raises(r.RetentionError,match='REGISTRY_BUSY_BOUNDED_WAIT'):
            with registry.transaction():pass
        state=registry.read();state['tasks']['invalid']=dict(state='TYPO_RUNNING',reserved_bytes=100,written_bytes=0,category='ordinary',directory=policy['run_root'])
        registry.save(state)
    with pytest.raises(r.RetentionError,match='REGISTRY_TASK_SCHEMA'):
        with claim(policy):pass


def test_legitimate_hardlinked_chart_billing_is_unique_and_not_a_delete_permission(policy,tmp_path):
    directory=Path(policy['run_root'])/'charts';directory.mkdir()
    original=directory/'000035.SZ.png';original.write_bytes(b'original-chart')
    linked=directory/'another.png';os.link(original,linked)
    assert g.billing_bytes(directory)==len(b'original-chart')
    # Destructive/ownership integrity validator stays strict; only read billing
    # accepts existing aliases. New hardlinks to old bytes consume no new payload.
    with pytest.raises(r.RetentionError,match='ALIAS'):r.stamp(original)
    with claim(policy,directory=directory) as (active,_):
        another=directory/'new-link.png';active.watch(another);os.link(original,another);active.observe(another)
        active.checkpoint();row=active.registry.read()['tasks']['a']
        assert row['written_bytes']==0 and row['category_baseline_bytes']==len(b'original-chart')
        active.finish(error=RuntimeError('read-only alias accounting test'))
