"""Frozen daily caller / ledger / due tests. All external children are replayed."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import pytest

FLAGS = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def request():
    from contracts.runtime_tasks import DispatchRequest, DispatchMode
    return DispatchRequest(scheduled_date='20261023', business_date='20261023', target_date='20261026', slot='1700', mode=DispatchMode.LIVE)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    data=tmp_path/'data';data.mkdir()
    receipts=tmp_path/'receipts';receipts.mkdir()
    tdx=tmp_path/'tdx';tdx.mkdir()
    app=Path(__import__('infrastructure.scheduling.executor_registry',fromlist=['x']).__file__).resolve().parents[2]
    for name in ('RECEIPT_ROOT','A_RECEIPT_ROOT'):
        monkeypatch.setenv('V35_RESEARCH_PANEL_'+name,str(receipts))
    names=('A_TDX_ROOT','HK_TDX_ROOT','A_SYNC_SCRIPT','A_FORMULA_SCRIPT','A_SEED_PANEL','A_DATA_ROOT','A_SELECTOR_POINTER','A_BACKTEST_POINTER','A_SELECTOR_SEED','A_BACKTEST_SEED','A_CONTRACT_CSV','A_CANONICAL_FORMULA','A_RETURN_ROOT','HK_UPDATER_SCRIPT','HK_ASSET_ROOT','HK_PYTHON_EXECUTABLE')
    for name in names:
        path=tdx if name=='A_TDX_ROOT' else tmp_path/(name+'.py' if name.endswith('SCRIPT') else name)
        if name.endswith('SCRIPT'):
            path.write_text('# frozen owned test authority\n')
        monkeypatch.setenv('V35_RESEARCH_PANEL_'+name,str(path))
    monkeypatch.setenv('V35_DATA_ROOT',str(data))
    monkeypatch.setenv('V35_RELEASE_ID','test-candidate')
    monkeypatch.setenv('V35_UPSTREAM_FINGERPRINT','static-tree')
    from infrastructure.scheduling import dispatcher
    if hasattr(dispatcher,'validate_release_identity'):
        entries=[{'path':rel,'kind':'file','size':(app/rel).stat().st_size,'sha256':digest(app/rel)} for rel in dispatcher._RUNTIME_IDENTITY_FILES]
        manifest=write(tmp_path/'release-manifest.json',{'schema_version':'v4.release_candidate.v1','candidate':{'app_root':str(app),'release_id':'test-candidate'},'application_inventory':{'entry_count':len(entries),'entries':entries,'aggregate_sha256':hashlib.sha256(json.dumps(entries,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()}})
        monkeypatch.setenv('V35_APP_ROOT',str(app));monkeypatch.setenv('V35_RELEASE_MANIFEST_PATH',str(manifest));monkeypatch.setenv('V35_RELEASE_MANIFEST_SHA256',digest(manifest))
    return SimpleNamespace(data=data,receipts=receipts,tdx=tdx,app=app,tmp=tmp_path)


def native_failure(roots, mutate=None):
    # Native task shape is frozen from the private diagnosis; only paths, run
    # time and synthetic .day bytes are rebound to this isolated child run.
    run_id='20261023-e663c5e385206afd-'+str(time.time_ns())
    rows={}
    for symbol,market,reason,prefix in [('688390',1,'PROTOCOL_RESPONSE_MALFORMED','sh'),('000001',0,'HOST_UNAVAILABLE','sz')]:
        p=roots.tdx/f'vipdoc/{prefix}/lday/{prefix}{symbol}.day';p.parent.mkdir(parents=True,exist_ok=True)
        if not p.exists():p.write_bytes(b'previous day immutable fixture')
        rows[symbol]={'symbol':symbol,'market':market,'status':'FAILED','fetch_status':'REBUILD_REQUIRED','classification':'QUARANTINED','quarantine':True,'reason_code':reason,'target_date_ready':False,'path':str(p),'source_sha256_before':digest(p),'source_sha256_after':digest(p),'run_id':run_id}
    summary=dict(task_name='tdxpy_daily_vipdoc_sync_v1',run_id=run_id,rule_id='A-FI-SYNC-001',rule_version='1',field_rule_id='A-FI-SYNC-001.FIELD_SIGNATURE',field_rule_version='1',status='FAILED',exit_code=2,target_date='20261023',target_fingerprint='e663c5e385206afdb1d38e960e821860a7baa16c61227f3f76f31d93753d3beb',target_count=2,accepted_count=0,accepted_target_date_file_count=0,quarantine_count=2,pending_count=0,completed_count=0,updated_count=0,coverage_rate=0.0,authority_status='FAILED',timeout=False,interrupted=False,dry_run=False,RESEARCH_ONLY=True,run_dir=str(roots.receipts/'a_sync_authority/20261023'),tdx_root=str(roots.tdx),markets=['a','bj'],count=20,by_symbol=rows,**FLAGS)
    receipt=dict(schema_version='v3.macos.research_panel_receipt.v1',target_date='20261023',lane='A',status='FAILED',runner_called=True,receipt_written=True,exit_code=1,error='SnapshotGateError: A sync partial closure has no healthy accepted subset',exception_type='SnapshotGateError',coverage_rate=None,sha256='',**FLAGS)
    from infrastructure.scheduling.input_retry_identity import bind_native_daily_failure
    error=ValueError('native failure context fixture')
    bind_native_daily_failure(error,summary)
    receipt['native_failure']=error.result['native_failure']
    context_before=copy.deepcopy(receipt['native_failure'])
    if mutate:mutate(summary,receipt)
    if receipt.get('native_failure')==context_before:
        bind_native_daily_failure(error,summary)
        receipt['native_failure']=error.result['native_failure']
    summary_path=roots.receipts/'a_sync_authority/20261023/summary.json'
    summary_path.parent.mkdir(parents=True,exist_ok=True)
    summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
    receipt_path=write(roots.receipts/'a-20261023.json',receipt)
    lane={k:receipt[k] for k in ('status','target_date','coverage_rate','sha256','error',*FLAGS)}
    if 'native_failure' in receipt:lane['native_failure']=receipt['native_failure']
    lane.update(receipt_bytes=receipt_path.stat().st_size,receipt_sha256=digest(receipt_path))
    payload=dict(schema_version='v3.macos.research_panel_authority_envelope.v1',target_date='20261023',lane='A',requested_lane='A',status='FAILED',lanes={'A':lane},**FLAGS)
    return payload,summary_path


def registry(roots,mutate=None,transport=None,after=None):
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    calls=[]
    def external(command,*,cwd,timeout_seconds,env):
        assert command[2]=='ops.macos_research_panel_daily'
        calls.append(command)
        if transport:raise transport
        payload,path=native_failure(roots,mutate)
        if after:after(payload,path)
        return subprocess.CompletedProcess(command,1,json.dumps(payload),'')
    return FixedExecutorRegistry(data_root=roots.data,repo_root=roots.app,runner=external),calls


def call_failed(reg):
    from infrastructure.scheduling.executor_registry import WorkloadExecutionError
    with pytest.raises(WorkloadExecutionError) as caught:
        reg._research_panel_daily(request(),lane='A')
    return caught.value.result


def test_exact_same_run_native_failure_becomes_typed_wait(setup):
    reg,calls=registry(setup)
    result=call_failed(reg)
    assert result['failure_class']=='INVALID_INPUT'
    assert result['failure_code']=='A_DAILY_PROTOCOL_SOURCE_REJECTED'
    assert result['input_wait']['wait_for_input_change'] is True
    assert len(result['input_wait']['daily_source_refs'])==2
    assert len(calls)==1


def test_fresh_timestamp_without_explicit_native_context_is_not_correlation(setup):
    reg,_=registry(setup,lambda summary,receipt:receipt.pop('native_failure'))
    result=call_failed(reg)
    assert result['failure_class']=='UNKNOWN'
    assert 'input_wait' not in result


@pytest.mark.parametrize('change',[
    lambda s,r:r.update(native_failure={}),
    lambda s,r:s.update(target_date='20261022'),
    lambda s,r:r.update(target_date='20261022'),
    lambda s,r:s.update(run_id='20261023-e663c5e385206afd-1000000000000000000'),
    lambda s,r:s['by_symbol']['688390'].update(run_id='another-run'),
    lambda s,r:r['native_failure'].update(summary_sha256='0'*64),
    lambda s,r:r['native_failure'].update(summary_relative='../outside/summary.json'),
    lambda s,r:s['by_symbol']['688390'].update(source_sha256_after='0'*64),
    lambda s,r:s['by_symbol']['688390'].update(path='/tmp/foreign.day'),
    lambda s,r:s['by_symbol']['688390'].update(market=0),
    lambda s,r:s.update(production_allowed=True),
    lambda s,r:r.update(orders_sent=True),
    lambda s,r:s.update(accepted_count=1),
    lambda s,r:s.update(timeout=True),
    lambda s,r:s['by_symbol']['688390'].update(reason_code='NETWORK'),
])
def test_wrong_native_evidence_never_creates_input_permission(setup,change):
    result=call_failed(registry(setup,change)[0])
    assert result['failure_class']=='UNKNOWN'
    assert 'input_wait' not in result


def catalog():
    from contracts.runtime_tasks import RuntimeCatalog,WorkloadDefinition,SafetyBoundary
    from contracts.trading_calendar import MarketScope,RunPolicy,SessionRequirement
    safe=SafetyBoundary(**FLAGS)
    workloads=tuple(WorkloadDefinition(workload_id=n,owner_id=n,run_policy=RunPolicy.NATURAL_DAY,market_scope=MarketScope.CROSS_MARKET,session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,slots=('1700',),command=(),aliases=(),enabled=True,scheduled_date_role='SCHEDULED_DATE',signal_date_role='BUSINESS_DATE',target_date_role='TARGET_DATE',safety=safe) for n in ['research_panel_daily_a','successful_sibling'])
    return RuntimeCatalog(schema_version='test',workloads=workloads,task_registrations=(),retired_owners=(),safety=safe,_source_payload={})


def due(ledger,**kwargs):
    import importlib.util
    if importlib.util.find_spec('ops.run_v35_macos_scheduler_due') is not None:
        from ops.run_v35_macos_scheduler_due import _slot_blocks_retry
    else:
        from ops.run_v35_macos_scheduler import _slot_blocks_retry
    return _slot_blocks_retry(ledger.root,'20261023','1700',release_id='test-candidate',upstream_fingerprint='static-tree',**kwargs)


def test_real_daily_caller_ledger_due_waits_and_relevant_change_wakes_once(setup,monkeypatch):
    from infrastructure.scheduling.dispatcher import dispatch_due
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    reg,calls=registry(setup);ledger=ExecutionLedger(setup.tmp/'ledger');siblings=[]
    reads=[];original=Path.read_bytes
    def read(path):
        if path==setup.receipts/'a_sync_authority/20261023/summary.json':reads.append(path)
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',read)
    def execute(workload,req,decision):
        if workload.workload_id=='successful_sibling':siblings.append('success');return {'status':'SUCCEEDED',**FLAGS}
        return reg._research_panel_daily(req,lane='A')
    first=dispatch_due(request(),catalog(),execute,ledger=ledger)
    assert first.status=='FAILED'
    claim=ledger.root/'workloads/live/20261023/1700/successful_sibling.workload-claim.json';before=digest(claim)
    assert len(calls)==1 and len(reads)==1
    moment=datetime.now(UTC)+timedelta(hours=1)
    assert due(ledger,moment=moment) is True
    dispatch_due(request(),catalog(),execute,ledger=ledger)
    assert len(calls)==1 and len(reads)==1
    # Generated native copies, receipt timestamps, stdout/logs and unrelated
    # hourly files cannot manufacture input progress or cause another audit.
    write(setup.receipts/'a_sync_authority/20261023/error-copy-new-uuid.json',{'attempt':99})
    write(setup.data/'research/incoming/20261023/1800.json',{'generated_at':'later'})
    report=setup.receipts/'a_sync_authority/20261023/summary.json';report.write_text('{fresh generated failure copy}')
    write(setup.receipts/'a-20261023.json',{'generated_at':'later','error':'same'})
    assert due(ledger,moment=moment) is True
    assert len(reads)==1
    day=setup.tdx/'vipdoc/sh/lday/sh688390.day';day.write_bytes(b'relevant changed source')
    assert due(ledger,moment=moment) is False
    dispatch_due(request(),catalog(),execute,ledger=ledger)
    assert len(calls)==2 and len(reads)==2
    assert due(ledger,moment=moment) is True
    dispatch_due(request(),catalog(),execute,ledger=ledger)
    assert len(calls)==2 and siblings==['success'] and digest(claim)==before


@pytest.mark.parametrize('kind',['code','config'])
def test_fixed_code_or_explicit_host_change_permits_one_validation(setup,monkeypatch,kind):
    from infrastructure.scheduling.dispatcher import dispatch_due
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    reg,calls=registry(setup);ledger=ExecutionLedger(setup.tmp/'ledger')
    def execute(workload,req,decision):
        return reg._research_panel_daily(req,lane='A') if workload.workload_id=='research_panel_daily_a' else {'status':'SUCCEEDED',**FLAGS}
    dispatch_due(request(),catalog(),execute,ledger=ledger)
    if kind=='config':monkeypatch.setenv('V35_A_SYNC_HOST','existing-explicit-owned-host:7709')
    else:Path(os.environ['V35_RESEARCH_PANEL_A_SYNC_SCRIPT']).write_text('# actual configured source changed\n')
    assert due(ledger,moment=datetime.now(UTC)+timedelta(hours=1)) is False
    dispatch_due(request(),catalog(),execute,ledger=ledger)
    dispatch_due(request(),catalog(),execute,ledger=ledger)
    assert len(calls)==2
    assert due(ledger,moment=datetime.now(UTC)+timedelta(hours=1)) is True


@pytest.mark.parametrize('transport',[ConnectionRefusedError('test transport refusal'),subprocess.TimeoutExpired('test child',5)])
def test_genuine_connect_failure_keeps_bounded_backoff(setup,monkeypatch,transport):
    from infrastructure.scheduling import dispatcher
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    clock=[datetime(2026,10,23,10,tzinfo=UTC)]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)
    monkeypatch.setattr(dispatcher,'datetime',Clock)
    reg,calls=registry(setup,transport=transport)
    ledger=ExecutionLedger(setup.tmp/'ledger')
    def execute(workload,req,decision):
        return reg._research_panel_daily(req,lane='A') if workload.workload_id=='research_panel_daily_a' else {'status':'SUCCEEDED',**FLAGS}
    first=dispatcher.dispatch_due(request(),catalog(),execute,ledger=ledger)
    lane=next(r for r in first.workload_results if r['workload_id']=='research_panel_daily_a')
    assert lane['failure_class']=='NETWORK' and 'input_wait' not in lane and lane['retry_after']
    assert due(ledger,moment=clock[0]+timedelta(minutes=4)) is True
    dispatcher.dispatch_due(request(),catalog(),execute,ledger=ledger)
    assert len(calls)==1
    clock[0]+=timedelta(minutes=6)
    assert due(ledger,moment=clock[0]) is False
    dispatcher.dispatch_due(request(),catalog(),execute,ledger=ledger)
    assert len(calls)==2


@pytest.mark.parametrize('kind',['SAFETY','UNKNOWN'])
def test_changed_daily_input_never_reopens_terminal_blocks(setup,kind):
    from infrastructure.scheduling.dispatcher import dispatch_due
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    ledger=ExecutionLedger(setup.tmp/'ledger')
    def execute(workload,req,decision):
        return {'status':'FAILED','failure_class':kind,**FLAGS} if workload.workload_id=='research_panel_daily_a' else {'status':'SUCCEEDED',**FLAGS}
    first=dispatch_due(request(),catalog(),execute,ledger=ledger)
    lane=next(r for r in first.workload_results if r['workload_id']=='research_panel_daily_a')
    assert lane['failure_class']==kind and 'input_wait' not in lane
    Path(os.environ['V35_RESEARCH_PANEL_A_SYNC_SCRIPT']).write_text('# relevant changed code')
    assert due(ledger,moment=datetime.now(UTC)+timedelta(hours=1)) is True


def test_successful_daily_and_sibling_claims_are_reused_without_children(setup):
    from infrastructure.scheduling.dispatcher import dispatch_due
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    ledger=ExecutionLedger(setup.tmp/'ledger');calls=[]
    def execute(workload,req,decision):
        calls.append(workload.workload_id)
        return {'status':'SUCCEEDED',**FLAGS}
    first=dispatch_due(request(),catalog(),execute,ledger=ledger)
    assert first.status=='SUCCEEDED'
    claims={p.name:digest(p) for p in (ledger.root/'workloads/live/20261023/1700').glob('*.json')}
    dispatch_due(request(),catalog(),execute,ledger=ledger)
    assert calls==['research_panel_daily_a','successful_sibling']
    assert claims=={p.name:digest(p) for p in (ledger.root/'workloads/live/20261023/1700').glob('*.json')}


def test_same_child_native_context_survives_actual_adapter_failed_receipt(setup):
    from ops import macos_research_panel_daily as adapter
    from infrastructure.scheduling.input_retry_identity import bind_native_daily_failure
    payload,path=native_failure(setup)
    reported=json.loads(path.read_bytes())
    def failed(target):
        error=adapter.SnapshotGateError('A sync partial closure has no healthy accepted subset')
        bind_native_daily_failure(error,reported)
        raise error
    def forbidden(target):pytest.fail('unrequested healthy HK runner called')
    result=adapter.run_lanes(target_date='20261023',receipt_root=setup.receipts,a_runner=failed,hk_runner=forbidden,lane='A')
    context=result['lanes']['A']['native_failure']
    assert context['summary_sha256']==digest(path)
    receipt=json.loads((setup.receipts/'a-20261023.json').read_bytes())
    assert receipt['native_failure']==context and receipt['status']=='FAILED'


def test_actual_authority_attaches_its_returned_native_object_before_rejecting(setup):
    from ops import macos_research_panel_daily as adapter
    _,path=native_failure(setup)
    reported=json.loads(path.read_bytes())
    rows=list(reported['by_symbol'].values())
    descriptors=[{'code':r['symbol'],'market':r['market'],'path':r['path']} for r in sorted(rows,key=lambda r:r['symbol'])]
    reported['target_fingerprint']=hashlib.sha256(json.dumps(descriptors,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    reported['symbol_reconciliation']=rows
    path.write_text(json.dumps(reported,ensure_ascii=False,indent=2,default=str))
    # Only the native module boundary is replayed. Both real adapter variants,
    # their rejection paths, and failed receipts run unchanged around it.
    script=setup.tmp/'replayed_native_authority.py'
    script.write_text('import json\ndef run(args):\n    return json.loads('+repr(json.dumps(reported))+')\n')
    with pytest.raises(adapter.SnapshotGateError) as caught:
        adapter.run_windows_a_sync_authority(script,setup.tdx,'20261023',setup.receipts,minimum_target_date_files=5000)
    context=caught.value.result['native_failure']
    assert context['run_id']==reported['run_id'] and context['summary_sha256']==digest(path)
    assert not (setup.receipts/'a_sync_authority.json').exists()


def test_actual_native_exception_receipt_stdout_and_registry_chain(setup,monkeypatch):
    import contextlib
    import inspect
    import io
    import sys
    from ops import macos_research_panel_daily as adapter
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    def external(command,*,cwd,timeout_seconds,env):
        _,path=native_failure(setup)
        reported=json.loads(path.read_bytes())
        rows=list(reported['by_symbol'].values())
        descriptors=[{'code':r['symbol'],'market':r['market'],'path':r['path']} for r in sorted(rows,key=lambda r:r['symbol'])]
        reported['target_fingerprint']=hashlib.sha256(json.dumps(descriptors,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        reported['symbol_reconciliation']=rows
        script=Path(os.environ['V35_RESEARCH_PANEL_A_SYNC_SCRIPT'])
        script.write_text('import json,time\ndef run(args):\n'
            +'    result=json.loads('+repr(json.dumps(reported))+')\n'
            +"    result['run_id']=str(args.target_date)+'-'+result['target_fingerprint'][:16]+'-'+str(time.time_ns())\n"
            +"    result['run_dir']=str(RUN_DIR)\n"
            +"    for row in result['by_symbol'].values():row['run_id']=result['run_id']\n"
            +"    for row in result['symbol_reconciliation']:row['run_id']=result['run_id']\n"
            +"    RUN_DIR.mkdir(parents=True,exist_ok=True)\n"
            +"    (RUN_DIR/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))\n"
            +'    return result\n')
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            if 'argv' in inspect.signature(adapter.main).parameters:
                code=adapter.main(command[3:])
            else:
                with monkeypatch.context() as scoped:
                    scoped.setattr(sys,'argv',['replayed-child',*command[3:]])
                    code=adapter.main()
        return subprocess.CompletedProcess(command,code,output.getvalue(),'')
    reg=FixedExecutorRegistry(data_root=setup.data,repo_root=setup.app,runner=external)
    result=call_failed(reg)
    assert result['failure_class']=='INVALID_INPUT',result.get('daily_failure_evidence_error',result)
    context=result['source_result']['lanes']['A']['native_failure']
    receipt=json.loads((setup.receipts/'a-20261023.json').read_bytes())
    assert receipt['native_failure']==context
    assert result['daily_failure_evidence']['native_summary_sha256']==context['summary_sha256']
    assert result['failure_code']=='A_DAILY_PROTOCOL_SOURCE_REJECTED'


def test_context_binding_error_cannot_replace_original_authority_rejection(setup,monkeypatch):
    from ops import macos_research_panel_daily as adapter
    from infrastructure.scheduling import input_retry_identity as identity
    _,path=native_failure(setup)
    reported=json.loads(path.read_bytes());rows=list(reported['by_symbol'].values())
    descriptors=[{'code':r['symbol'],'market':r['market'],'path':r['path']} for r in sorted(rows,key=lambda r:r['symbol'])]
    reported['target_fingerprint']=hashlib.sha256(json.dumps(descriptors,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    reported['symbol_reconciliation']=rows
    script=setup.tmp/'replay_metadata_fault.py';script.write_text('import json\ndef run(args):\n    return json.loads('+repr(json.dumps(reported))+')\n')
    def broken(*a,**k):raise ValueError('metadata cannot hide original failure')
    monkeypatch.setattr(identity,'bind_native_daily_failure',broken)
    with pytest.raises(adapter.SnapshotGateError,match='A sync (partial closure has no healthy accepted subset|authority did not prove exact-date success)'):
        adapter.run_windows_a_sync_authority(script,setup.tdx,'20261023',setup.receipts,minimum_target_date_files=5000)



@pytest.mark.parametrize('case',['concurrent_native','stdout_run','receipt_context','malformed_report','nonobject_report','nonobject_lane'])
def test_concurrent_or_swapped_evidence_never_uses_freshness_as_correlation(setup,case):
    def after(payload,path):
        if case=='concurrent_native':
            current=json.loads(path.read_bytes())
            current['run_id']='20261023-e663c5e385206afd-'+str(time.time_ns())
            path.write_text(json.dumps(current,ensure_ascii=False,indent=2,default=str))
        elif case=='stdout_run':
            payload['lanes']['A']['native_failure']=dict(payload['lanes']['A']['native_failure'],run_id='other-child')
        elif case=='receipt_context':
            receipt=json.loads((setup.receipts/'a-20261023.json').read_bytes())
            receipt['native_failure']['run_id']='other-child'
            write(setup.receipts/'a-20261023.json',receipt)
        elif case=='nonobject_lane':payload['lanes']['A']=None
        elif case=='nonobject_report':
            path.write_text('[]')
            context=payload['lanes']['A']['native_failure']
            context['summary_sha256']=digest(path)
            receipt=json.loads((setup.receipts/'a-20261023.json').read_bytes())
            receipt['native_failure']=context
            write(setup.receipts/'a-20261023.json',receipt)
            payload['lanes']['A'].update(receipt_sha256=digest(setup.receipts/'a-20261023.json'),receipt_bytes=(setup.receipts/'a-20261023.json').stat().st_size)
        else:path.write_text('{malformed native report')
    result=call_failed(registry(setup,after=after)[0])
    assert result['failure_class']=='UNKNOWN' and 'input_wait' not in result


@pytest.mark.parametrize('reason',['UNRECOGNIZED_NATIVE_FAILURE','UNKNOWN','SAFETY'])
def test_r2_mixed_native_terminal_reason_never_gets_protocol_wait(setup,reason):
    def mutate(summary,receipt):summary['by_symbol']['000001']['reason_code']=reason
    result=call_failed(registry(setup,mutate)[0])
    assert result['failure_class']=='UNKNOWN' and 'input_wait' not in result


@pytest.mark.parametrize('kind',['UNKNOWN','SAFETY'])
def test_r2_mixed_native_explicit_terminal_class_never_gets_protocol_wait(setup,kind):
    def mutate(summary,receipt):summary['by_symbol']['000001']['failure_class']=kind
    result=call_failed(registry(setup,mutate)[0])
    assert result['failure_class'] in {'UNKNOWN','SAFETY'} and 'input_wait' not in result


@pytest.mark.parametrize('reason',['CROSS_DAY_CLOSE_RATIO','KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE','A_SYNC_TIMEOUT'])
def test_r2_known_mixed_native_rejections_keep_diagnosed_protocol_wait(setup,reason):
    def mutate(summary,receipt):summary['by_symbol']['000001']['reason_code']=reason
    result=call_failed(registry(setup,mutate)[0])
    assert result['failure_class']=='INVALID_INPUT' and result['input_wait']['wait_for_input_change'] is True
    assert result['input_wait']['daily_source_refs']==['vipdoc/sh/lday/sh688390.day']


def test_r2_same_path_cas_config_change_permits_one_actual_validation(setup,monkeypatch):
    from infrastructure.scheduling.dispatcher import dispatch_due
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    config=write(setup.tmp/'trusted-cas.json',{'schema_version':'trusted-cas-fixture','inputs':[]})
    monkeypatch.setenv('V35_A_SYNC_TRUSTED_CAS_INPUTS',str(config))
    reg,calls=registry(setup);ledger=ExecutionLedger(setup.tmp/'ledger')
    def execute(workload,req,decision):
        return reg._research_panel_daily(req,lane='A') if workload.workload_id=='research_panel_daily_a' else {'status':'SUCCEEDED',**FLAGS}
    dispatch_due(request(),catalog(),execute,ledger=ledger)
    sibling=ledger.root/'workloads/live/20261023/1700/successful_sibling.workload-claim.json';sibling_before=digest(sibling)
    moment=datetime.now(UTC)+timedelta(hours=1)
    assert due(ledger,moment=moment) is True
    write(config,{'schema_version':'trusted-cas-fixture','inputs':[{'changed':'relevant native config input'}]})
    assert due(ledger,moment=moment) is False
    dispatch_due(request(),catalog(),execute,ledger=ledger)
    assert len(calls)==2 and digest(sibling)==sibling_before
    assert due(ledger,moment=moment) is True
    dispatch_due(request(),catalog(),execute,ledger=ledger)
    assert len(calls)==2


@pytest.mark.parametrize('case',['symlink','parent_symlink','relative','oversize','missing'])
def test_r2_config_identity_is_bounded_exact_and_fail_closed(setup,monkeypatch,case):
    from infrastructure.scheduling.input_retry_identity import observe_input_identity,make_input_wait,input_wait_changed
    config=setup.tmp/'trusted-cas.json'
    if case=='symlink':
        target=write(setup.tmp/'outside.json',{'secret':'unread'})
        config.symlink_to(target)
    elif case=='parent_symlink':
        directory=setup.tmp/'real-config';directory.mkdir()
        target=write(directory/'trusted-cas.json',{'secret':'unread'})
        link=setup.tmp/'config-link';link.symlink_to(directory,target_is_directory=True)
        config=link/'trusted-cas.json'
    elif case=='relative':config=Path('relative-config.json')
    elif case=='oversize':
        config.write_bytes(b'x'*(16*1024*1024+1))
    monkeypatch.setenv('V35_A_SYNC_TRUSTED_CAS_INPUTS',str(config))
    reads=[];original=Path.read_bytes
    def read(path):
        if path==config or (case in {'symlink','parent_symlink'} and path==target):reads.append(path)
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',read)
    wait=make_input_wait(observe_input_identity('research_panel_daily_a','20261023','20261026','1700'),'A_DAILY_PROTOCOL_SOURCE_REJECTED')
    assert input_wait_changed(wait) is False
    if case in {'symlink','parent_symlink'}:
        write(target,{'secret':'changed but still unowned'})
        assert input_wait_changed(wait) is False
    assert reads==[]
