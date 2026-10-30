"""Exact-release overlay only; fake clocks/transports and temporary ledgers."""
import ast
from dataclasses import replace
from datetime import datetime
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT=Path(__file__).resolve().parents[1]
HANDOFF=ROOT/'docs/handoffs/a_daily_dashboard_closure_20261029/a_daily_1540_source'
BASE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-daily-sop-closure-20261029-r1-main/app')
TZ=ZoneInfo('Asia/Shanghai')
def moment(slot,date='20261030'):return datetime.strptime(date+slot,'%Y%m%d%H%M').replace(tzinfo=TZ)


@pytest.fixture(scope='module')
def candidate(tmp_path_factory):
    inventory=json.loads((HANDOFF/'OVERLAY_INVENTORY.json').read_text())
    overlay=tmp_path_factory.mktemp('exact-overlay')
    for name,ref in inventory['files'].items():
        raw=(subprocess.run(['git','show',inventory['C4_commit']+':'+name],cwd=ROOT,check=True,capture_output=True).stdout if ref['base_kind']=='C4_COMMIT' else (BASE/name).read_bytes())
        if ref['base_kind']!='C4_GATE_HOOK_COMPOSED':assert hashlib.sha256(raw).hexdigest()==ref['before_sha256']
        p=overlay/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    dependency=ROOT/inventory['gate_dependency']['path'];assert hashlib.sha256(dependency.read_bytes()).hexdigest()==inventory['gate_dependency']['sha256']
    subprocess.run(['git','apply',str(dependency)],cwd=overlay,check=True,capture_output=True)
    assert hashlib.sha256((overlay/'ops/macos_research_panel_daily_gate.py').read_bytes()).hexdigest()==inventory['gate_dependency']['hook_composed_sha256']
    subprocess.run(['git','apply','--check',str(HANDOFF/'CANDIDATE_OVERLAY.patch')],cwd=overlay,check=True,capture_output=True)
    subprocess.run(['git','apply',str(HANDOFF/'CANDIDATE_OVERLAY.patch')],cwd=overlay,check=True,capture_output=True)
    for name,ref in inventory['files'].items():assert hashlib.sha256((overlay/name).read_bytes()).hexdigest()==ref['after_sha256']
    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname.split('.')[0] not in {'ops','contracts','infrastructure','domains','stage_center','shared_data','upstreams'}:return None
            if fullname in {'ops.render_original_formula_projection','domains.research_daily_product','domains.research_daily_statistics'}:
                p=ROOT/Path(*fullname.split('.')).with_suffix('.py');return importlib.util.spec_from_file_location(fullname,p)
            relative=Path(*fullname.split('.'))
            for source in (overlay,BASE,BASE/'upstreams'):
                file=source/relative.with_suffix('.py');init=source/relative/'__init__.py'
                if file.is_file():return importlib.util.spec_from_file_location(fullname,file)
                if init.is_file():return importlib.util.spec_from_file_location(fullname,init,submodule_search_locations=[str(init.parent)])
                if (source/relative).is_dir():
                    from importlib.machinery import ModuleSpec
                    spec=ModuleSpec(fullname,loader=None,is_package=True);spec.submodule_search_locations=[str(source/relative)];return spec
    finder=Finder();sys.meta_path.insert(0,finder)
    from contracts.runtime_tasks import DispatchRequest,DispatchMode
    from infrastructure.scheduling.catalog import load_workload_catalog
    from infrastructure.scheduling.dispatcher import dispatch_due
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    from infrastructure.scheduling import executor_registry as registry
    from ops import run_v4_macos_scheduler as scheduler
    from ops.run_v4_macos_scheduler_daemon import SlotProcessLanes
    from ops import macos_research_panel_daily_gate as gate
    from ops import research_panel_daily_source as source
    from ops import research_panel_daily_product as producer
    registry.shanghai_now=lambda:moment('1540')
    catalog=load_workload_catalog(overlay/'contracts/runtime_workloads.json')
    def request(slot,date='20261030'):return DispatchRequest(scheduled_date=date,business_date=date,target_date=date,slot=slot,mode=DispatchMode.LIVE)
    yield SimpleNamespace(**locals())
    sys.meta_path.remove(finder)


def test_overlay_changes_only_a_catalog_and_bound_paths(candidate):
    current=json.loads((candidate.overlay/'contracts/runtime_workloads.json').read_text());old=json.loads((BASE/'contracts/runtime_workloads.json').read_text())
    next(w for w in old['workloads'] if w['workload_id']=='research_panel_daily_a')['slots']=['1540','1610','1640']
    assert current==old
    assert next(w for w in candidate.catalog.workloads if w.workload_id=='research_panel_daily_hk').slots==('1720',)
    assert '1700' in next(w for w in candidate.catalog.workloads if w.workload_id=='hourly_research').slots


@pytest.mark.parametrize('slot,expected',[('1539',None),('1540','1540'),('1545','1540'),('1700','1700'),('1720','1720')])
def test_fake_clock_natural_due(candidate,tmp_path,monkeypatch,slot,expected):
    monkeypatch.setattr(candidate.scheduler,'_slot_blocks_retry',lambda root,date,s,**kw:s not in {'1540','1700','1720'})
    answer=candidate.scheduler.resolve_due_slot(ledger_root=tmp_path,now=moment(slot))
    if expected is None:assert answer.get('slot') not in candidate.scheduler.ALL_SLOTS
    else:assert answer['slot']==expected


def test_1540_dispatch_once_success_not_replayed(candidate,tmp_path):
    catalog=replace(candidate.catalog,workloads=tuple(w for w in candidate.catalog.workloads if w.workload_id=='research_panel_daily_a'))
    calls=[]
    for slot in ['1539','1540','1540','1700']:
        candidate.dispatch_due(candidate.request(slot),catalog,lambda w,r,*args:calls.append((w.workload_id,r.slot)) or {'status':'SUCCEEDED'},ledger=candidate.ExecutionLedger(tmp_path))
    assert calls==[('research_panel_daily_a','1540')]


@pytest.mark.parametrize('date',['20261001','20261101'])
def test_same_calendar_no_a_provider_holiday_weekend(candidate,tmp_path,date):
    catalog=replace(candidate.catalog,workloads=tuple(w for w in candidate.catalog.workloads if w.workload_id=='research_panel_daily_a'))
    calls=[];candidate.dispatch_due(candidate.request('1540',date),catalog,lambda *args:calls.append(1) or {'status':'SUCCEEDED'},ledger=candidate.ExecutionLedger(tmp_path))
    assert calls==[]


@pytest.mark.parametrize('slot',['1540','1610','1640','1700','1720'])
def test_parent_child_lane_identity_and_kernel_lock(candidate,tmp_path,monkeypatch,slot):
    lane=candidate.SlotProcessLanes.lane(slot);assert lane==('A_LONG' if slot in {'1540','1610','1640'} else 'DEFAULT')
    ledger=candidate.ExecutionLedger(tmp_path);fd=ledger.try_acquire_scheduler_lane(lane);assert fd is not None
    try:
        assert candidate.ExecutionLedger(tmp_path).try_acquire_scheduler_lane(lane) is None
        for k,v in {'V4_SCHEDULER_LANE_FD':str(fd),'V4_SCHEDULER_LANE_NAME':lane,'V4_SCHEDULER_RESOLVED_DATE':'20261030','V4_SCHEDULER_RESOLVED_SLOT':slot}.items():monkeypatch.setenv(k,v)
        ledger.validate_scheduler_lane('20261030',slot,now=moment(slot))
    finally:os.close(fd)


def test_healthy_a_owner_is_queued_behind_and_never_cancelled(candidate,tmp_path):
    lanes=candidate.SlotProcessLanes.__new__(candidate.SlotProcessLanes)
    child=SimpleNamespace(pid=123,poll=lambda:None)
    lanes.active={'A_LONG':{'slot':'1540','business_date':'20261030','child':child}}
    lanes.queued={};lanes.handover_blocked={};lanes.clock=lambda:moment('1640');lanes.ledger=candidate.ExecutionLedger(tmp_path)
    lanes._observe=lambda *args,**kw:None
    lanes.enqueue('20261030','1610',moment('1610'));lanes.enqueue('20261030','1640',moment('1640'))
    lanes.pulse(moment('1640'))
    assert lanes.active['A_LONG']['child'] is child and len(lanes.queued)==2


@pytest.mark.parametrize('lane,slot,called',[('A','1539',False),('A','1540',True),('HK','1540',False),('ALL','1540',False),('HK','1700',True)])
def test_implicit_guard_only_a_earlier(candidate,tmp_path,monkeypatch,lane,slot,called):
    gate=candidate.gate;calls=[]
    monkeypatch.setattr(gate,'selector_pointer_is_ready',lambda *a:False);monkeypatch.setattr(gate,'_a_lane_receipt_ready',lambda *a:(False,False));monkeypatch.setattr(gate,'_hk_lane_receipt_ready',lambda *a:False)
    monkeypatch.setattr(gate,'run_lanes',lambda **kw:calls.append(kw['lane']) or {'lanes':{},'overall_status':'FAILED'})
    gate.ensure_after_1700(target_date='20261030',receipt_root=tmp_path,selector_pointer=tmp_path/'pointer',a_runner=lambda _:None,hk_runner=lambda _:None,lane=lane,now=moment(slot))
    assert bool(calls)==called


@pytest.mark.parametrize('slot,status,allowed',[('1540','FAILED',True),('1610','FAILED',True),('1640','FAILED',True),('1610',None,False),('1640','CANNOT_CONFIRM',True)])
def test_retry_requires_prior_exact_failed_receipt(candidate,tmp_path,monkeypatch,slot,status,allowed):
    registry=candidate.registry
    for k,v in {'V4_RESEARCH_PANEL_RECEIPT_ROOT':str(tmp_path),'V4_RESEARCH_PANEL_A_SELECTOR_POINTER':str(tmp_path/'s'),'V4_RESEARCH_PANEL_A_BACKTEST_POINTER':str(tmp_path/'b')}.items():monkeypatch.setenv(k,v)
    monkeypatch.setattr(registry,'_read_exact_dated_receipt',lambda *args,**kwargs:({'status':status} if status else None,None))
    from ops import macos_research_panel_daily_receipts as receipts
    monkeypatch.setattr(receipts,'validate_a_receipt',lambda *args,**kw:'CANNOT_CONFIRM')
    obj=registry.FixedExecutorRegistry.__new__(registry.FixedExecutorRegistry);obj._active_workload_id=None;calls=[];obj._research_panel_daily=lambda *args,**kw:calls.append(1) or {'status':'SUCCEEDED'}
    if allowed:obj._run_a_daily(candidate.request(slot))
    else:
        with pytest.raises(registry.WorkloadExecutionError):obj._run_a_daily(candidate.request(slot))
    assert bool(calls)==allowed


@pytest.mark.parametrize('slot',['1540','1610','1640'])
def test_completed_same_date_reused_zero_provider(candidate,tmp_path,monkeypatch,slot):
    registry=candidate.registry
    for k,v in {'V4_RESEARCH_PANEL_RECEIPT_ROOT':str(tmp_path),'V4_RESEARCH_PANEL_A_SELECTOR_POINTER':str(tmp_path/'s'),'V4_RESEARCH_PANEL_A_BACKTEST_POINTER':str(tmp_path/'b')}.items():monkeypatch.setenv(k,v)
    (tmp_path/'a-20261030.json').write_text('{}')
    monkeypatch.setattr(registry,'_read_exact_dated_receipt',lambda *args,**kwargs:({'status':'READY'},None))
    from ops import macos_research_panel_daily_receipts as receipts
    monkeypatch.setattr(receipts,'validate_a_receipt',lambda *args,**kw:'PARTIAL_WITH_ROWS');monkeypatch.setattr(candidate.gate,'selector_pointer_is_ready',lambda *args:True)
    obj=registry.FixedExecutorRegistry.__new__(registry.FixedExecutorRegistry);obj._active_workload_id=None;obj._research_panel_daily=lambda *args,**kw:pytest.fail('completed date must not invoke provider')
    answer=obj._run_a_daily(candidate.request(slot));assert answer['provider_invoked'] is False and answer['natural_1540_verified'] is False


def test_source_wait_window_never_reads_old_date_or_fetches(candidate,tmp_path):
    source=candidate.source
    with pytest.raises(Exception,match='OFFICIAL_DAILY_SOURCE_WAIT_WINDOW'):
        source.acquire_daily_input(20261030,tmp_path,fetch=lambda:pytest.fail('before1540'),now=moment('1539'))
    with pytest.raises(Exception,match='OFFICIAL_DAILY_TARGET_NOT_TRADING_DAY'):
        source.acquire_daily_input(20261101,tmp_path,fetch=lambda:pytest.fail('nontrading'),now=moment('1540','20261101'))
    def not_ready():raise OSError('provider_not_ready_fixture')
    with pytest.raises(Exception,match='OFFICIAL_DAILY_SOURCE_NOT_READY'):
        source.acquire_daily_input(20261030,tmp_path,fetch=not_ready,now=moment('1540'),sleep=lambda _:None)
    assert not list(tmp_path.rglob('input.json'))


@pytest.mark.parametrize('status',['FAILED','CANNOT_CONFIRM'])
def test_real_failure_receipt_without_success_sha_is_observation_only(candidate,tmp_path,monkeypatch,status):
    registry=candidate.registry
    receipt={'schema_version':'v3.macos.research_panel_receipt.v1','target_date':'20261030','lane':'A','status':status,
             'sha256':'','coverage_rate':None,'row_count':None,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    (tmp_path/'a-20261030.json').write_text(json.dumps(receipt))
    args=['--date','20261030','--lane','A','--receipt-root',str(tmp_path)]
    assert registry._read_exact_dated_receipt('ops.macos_research_panel_daily',args)[0] is None
    assert registry._read_exact_dated_receipt('ops.macos_research_panel_daily',args,allow_a_failure=True)[0]==receipt
    for k,v in {'V4_RESEARCH_PANEL_RECEIPT_ROOT':str(tmp_path),'V4_RESEARCH_PANEL_A_SELECTOR_POINTER':str(tmp_path/'s'),'V4_RESEARCH_PANEL_A_BACKTEST_POINTER':str(tmp_path/'b')}.items():monkeypatch.setenv(k,v)
    obj=registry.FixedExecutorRegistry.__new__(registry.FixedExecutorRegistry);obj._active_workload_id=None;calls=[];obj._research_panel_daily=lambda *args,**kw:calls.append(1) or {'status':'SUCCEEDED'}
    obj._run_a_daily(candidate.request('1610'));assert calls==[1]
    receipt['status']='READY';(tmp_path/'a-20261030.json').write_text(json.dumps(receipt))
    assert registry._read_exact_dated_receipt('ops.macos_research_panel_daily',args,allow_a_failure=True)[0] is None
    calls.clear()
    with pytest.raises(registry.WorkloadExecutionError):obj._run_a_daily(candidate.request('1640'))
    assert calls==[]


def test_1700_is_alert_only_and_does_not_start_failed_owner(candidate,tmp_path,monkeypatch):
    registry=candidate.registry
    for k,v in {'V4_RESEARCH_PANEL_RECEIPT_ROOT':str(tmp_path),'V4_RESEARCH_PANEL_A_SELECTOR_POINTER':str(tmp_path/'s'),'V4_RESEARCH_PANEL_A_BACKTEST_POINTER':str(tmp_path/'b')}.items():monkeypatch.setenv(k,v)
    monkeypatch.setattr(registry,'_read_exact_dated_receipt',lambda *args,**kwargs:({'status':'FAILED'},None))
    from ops import macos_research_panel_daily_receipts as receipts
    monkeypatch.setattr(receipts,'validate_a_receipt',lambda *args,**kw:'CANNOT_CONFIRM');monkeypatch.setattr(registry,'shanghai_now',lambda:moment('1700'))
    obj=registry.FixedExecutorRegistry.__new__(registry.FixedExecutorRegistry);obj._active_workload_id=None;obj._research_panel_daily=lambda *args,**kw:pytest.fail('17 alert must not start provider')
    with pytest.raises(registry.WorkloadExecutionError) as error:obj._run_a_daily(candidate.request('1610'))
    assert error.value.result['reason']=='A_DAILY_OUTSIDE_WINDOW_ALERT_ONLY'


def test_ready_fast_path_enters_original_cache_only_leaf(candidate,tmp_path,monkeypatch):
    registry=candidate.registry
    for k,v in {'V4_RESEARCH_PANEL_RECEIPT_ROOT':str(tmp_path),'V4_RESEARCH_PANEL_A_SELECTOR_POINTER':str(tmp_path/'s'),'V4_RESEARCH_PANEL_A_BACKTEST_POINTER':str(tmp_path/'b'),'V4_RESEARCH_PANEL_A_DATA_ROOT':str(tmp_path/'owner')}.items():monkeypatch.setenv(k,v)
    (tmp_path/'a-20261030.json').write_text('{}');monkeypatch.setattr(registry,'_read_exact_dated_receipt',lambda *args,**kw:({'status':'READY'},None))
    from ops import macos_research_panel_daily_receipts as receipts
    monkeypatch.setattr(receipts,'validate_a_receipt',lambda *args,**kw:'PARTIAL_WITH_ROWS');monkeypatch.setattr(candidate.gate,'selector_pointer_is_ready',lambda *args:True)
    calls=[]
    monkeypatch.setattr(candidate.producer,'materialize_daily_product',lambda **kw:calls.append(kw) or {'status':'READY','cache_only':True,'original_chart_leaf':{'status':'OWNER_CHARTS_PARTIAL'}})
    obj=registry.FixedExecutorRegistry.__new__(registry.FixedExecutorRegistry);obj._active_workload_id=None;obj._research_panel_daily=lambda *args,**kw:pytest.fail('no numeric/provider rerun')
    answer=obj._run_a_daily(candidate.request('1640'));assert answer['provider_invoked'] is False and answer['numeric_recomputed'] is False
    assert calls==[{'data_root':str(tmp_path/'owner'),'target':20261030,'cache_only':True}]


def test_cache_only_missing_numeric_checkpoint_never_computes(candidate,tmp_path,monkeypatch):
    producer=candidate.producer
    context=SimpleNamespace(root=tmp_path,target=20261030,scope=['600025.SH'],identity={},config_ref={},unchanged=lambda:None)
    monkeypatch.setattr(producer,'SourceContext',lambda *args,**kw:context)
    monkeypatch.setattr(producer,'compute_stock',lambda *args,**kw:pytest.fail('cache-only must not compute'))
    with pytest.raises(ValueError,match='DAILY_NUMERIC_CHECKPOINT_MISSING_CACHE_ONLY_NO_RECOMPUTE'):
        producer.materialize_daily_product(data_root=tmp_path,target=20261030,cache_only=True)
    assert not list(tmp_path.rglob('index.json'))


def test_cache_only_leaf_reuses_existing_numeric_bytes(candidate,tmp_path,monkeypatch):
    # Reuse the accepted C4 fixture factory, not its old test suite or canary.
    import copy
    from unittest.mock import patch
    from ops import render_original_formula_projection as helper
    tree=ast.parse((ROOT/'tests/test_daily_original_chart_owner.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'owner_fixture','run_owner'}]
    env={'owner':candidate.producer,'renderer':helper,'copy':copy,'json':json,'SimpleNamespace':SimpleNamespace,'Path':Path,'patch':patch}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'accepted-C4-fixture-functions-only','exec'),env)
    owner_fixture,run_owner=env['owner_fixture'],env['run_owner']
    context,calls,evaluate,png=owner_fixture(tmp_path)
    first=run_owner(context,evaluate,png,original_charts=False)
    calls['compute']=0
    monkeypatch.setattr(candidate.producer,'compute_stock',lambda *args,**kw:pytest.fail('cache-only must not compute'))
    from ops import render_original_formula_projection as helper
    monkeypatch.setattr(helper,'finalize_owner_charts',lambda c,p,product,manifest,artifact,**kw:{'status':'OWNER_CHARTS_PARTIAL','numeric_manifest':manifest})
    second=run_owner(context,evaluate,png,cache_only=True)
    assert first['artifact']==second['artifact'] and first['manifest']==second['manifest'] and calls['compute']==0
    assert second['cache_only'] is True and second['numeric_recomputed'] is False


def test_1540_exact_main_precedes_old_backlog(candidate,tmp_path):
    answer=candidate.scheduler.resolve_due_slot(ledger_root=tmp_path,now=moment('1540'))
    assert answer['slot']=='1540' and answer['catchup'] is False


def test_cache_only_checkpoint_disappears_after_precheck_never_computes(candidate,tmp_path,monkeypatch):
    producer=candidate.producer
    context=SimpleNamespace(root=tmp_path,target=20261030,scope=['600025.SH'],identity={},config_ref={},unchanged=lambda:None)
    monkeypatch.setattr(producer,'SourceContext',lambda *args,**kw:context)
    observed=[];calls=[];real=Path.is_file
    def changes_after_precheck(path):
        if path.name=='600025.SH.json':
            observed.append(len(observed)==0)
            return observed[-1]
        return real(path)
    monkeypatch.setattr(Path,'is_file',changes_after_precheck)
    def forbidden(*args,**kwargs):
        calls.append('compute_stock')
        raise AssertionError('cache_only entered compute after checkpoint disappeared')
    monkeypatch.setattr(producer,'compute_stock',forbidden)
    with pytest.raises(ValueError,match='DAILY_NUMERIC_CHECKPOINT_DISAPPEARED_CACHE_ONLY_NO_RECOMPUTE'):
        producer.materialize_daily_product(data_root=tmp_path,target=20261030,cache_only=True)
    assert observed==[True,False] and calls==[]
    assert not list(tmp_path.rglob('index.json')) and not list(tmp_path.rglob('latest.json'))
