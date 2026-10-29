"""Frozen active-Main scheduler regression; no providers or live state access."""
from datetime import datetime
from pathlib import Path
from dataclasses import replace
import json, os, subprocess, sys
from zoneinfo import ZoneInfo
import pytest
from contracts.runtime_tasks import DispatchRequest, DispatchMode
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from ops import run_v4_macos_scheduler as scheduler
from ops.run_v4_macos_scheduler_daemon import SlotProcessLanes
from ops import macos_research_panel_daily_gate as gate
TZ=ZoneInfo('Asia/Shanghai')
ROOT=Path(__file__).resolve().parents[1]
def moment(hhmm,date='20261029'):
    return datetime.strptime(date+hhmm,'%Y%m%d%H%M').replace(tzinfo=TZ)
def request(slot,date='20261029'):
    return DispatchRequest(scheduled_date=date,business_date=date,target_date=date,slot=slot,mode=DispatchMode.LIVE)
def catalog(): return load_workload_catalog(ROOT/'contracts/runtime_workloads.json')
def a_catalog():
    c=catalog(); return replace(c,workloads=tuple(w for w in c.workloads if w.workload_id=='research_panel_daily_a'))
def test_catalog_only_a_slot_changes():
    current=json.loads((ROOT/'contracts/runtime_workloads.json').read_text())
    baseline=Path(os.environ['A_DAILY_BASELINE'])
    old=json.loads((baseline/'contracts/runtime_workloads.json').read_text())
    a=next(w for w in old['workloads'] if w['workload_id']=='research_panel_daily_a'); a['slots']=['1530']
    assert current==old
    assert next(w for w in catalog().workloads if w.workload_id=='hourly_research').slots.count('1700')==1
@pytest.mark.parametrize('slot,expected',[('1529',False),('1530',True),('1700',False),('1720',False)])
def test_only_new_slot_invokes_a(tmp_path,slot,expected):
    calls=[]
    r=dispatch_due(request(slot),a_catalog(),lambda w,r,*args: calls.append(w.workload_id) or {'status':'SUCCEEDED'},ledger=ExecutionLedger(tmp_path))
    assert bool(calls)==expected
    assert calls==(['research_panel_daily_a'] if expected else [])
@pytest.mark.parametrize('date',['20261001','20261101'])
def test_holiday_and_weekend_do_not_invoke_a(tmp_path,date):
    calls=[]
    dispatch_due(request('1530',date),a_catalog(),lambda w,r,*args:calls.append(w.workload_id) or {'status':'SUCCEEDED'},ledger=ExecutionLedger(tmp_path))
    assert calls==[]
def test_restart_duplicate_dispatch_is_blocked(tmp_path):
    calls=[]
    for _ in range(2):
        dispatch_due(request('1530'),a_catalog(),lambda w,r,*args:calls.append(w.workload_id) or {'status':'SUCCEEDED'},ledger=ExecutionLedger(tmp_path))
    assert calls==['research_panel_daily_a']
@pytest.mark.parametrize('slot',['1530','1700','1720'])
def test_lane_identity_and_restart_lock(tmp_path,monkeypatch,slot):
    ledger=ExecutionLedger(tmp_path); lane=SlotProcessLanes.lane(slot)
    assert lane==('A_LONG' if slot=='1530' else 'DEFAULT')
    fd=ledger.try_acquire_scheduler_lane(lane); assert fd is not None
    try:
        assert ExecutionLedger(tmp_path).try_acquire_scheduler_lane(lane) is None
        for k,v in {'V4_SCHEDULER_LANE_FD':str(fd),'V4_SCHEDULER_LANE_NAME':lane,'V4_SCHEDULER_RESOLVED_DATE':'20261029','V4_SCHEDULER_RESOLVED_SLOT':slot}.items():monkeypatch.setenv(k,v)
        ledger.validate_scheduler_lane('20261029',slot,now=moment(slot))
        monkeypatch.setenv('V4_SCHEDULER_LANE_NAME','DEFAULT' if lane=='A_LONG' else 'A_LONG')
        with pytest.raises(ValueError,match='SCHEDULER_LANE_IDENTITY_INVALID'):ledger.validate_scheduler_lane('20261029',slot,now=moment(slot))
    finally:os.close(fd)
    recovered=ExecutionLedger(tmp_path).try_acquire_scheduler_lane(lane); assert recovered is not None; os.close(recovered)
def test_a_lane_does_not_lock_hourly_or_hk_lane(tmp_path):
    l=ExecutionLedger(tmp_path); a=l.try_acquire_scheduler_lane('A_LONG'); default=l.try_acquire_scheduler_lane('DEFAULT')
    assert a is not None and default is not None
    os.close(a); os.close(default)
@pytest.mark.parametrize('hhmm,expected',[('1529',None),('1530','1530'),('1535','1530'),('1700','1700'),('1720','1720')])
def test_natural_due_resolution_and_catchup(tmp_path,monkeypatch,hhmm,expected):
    # Suppress unrelated owners so only the changed slot and unchanged exact
    # hourly/HK owners are measured; no live receipt or calendar is modified.
    monkeypatch.setattr(scheduler,'_slot_blocks_retry',lambda root,date,slot,**kw:slot not in {'1530','1700','1720'})
    resolved=scheduler.resolve_due_slot(ledger_root=tmp_path,now=moment(hhmm))
    if expected is None:
        assert resolved.get('slot') not in scheduler.ALL_SLOTS
    else:
        assert resolved.get('slot')==expected
@pytest.mark.parametrize('lane,hhmm,called',[('A','1529',False),('A','1530',True),('A','1535',True),('HK','1530',False),('ALL','1530',False),('HK','1700',True)])
def test_implicit_time_guard_preserves_other_lanes(tmp_path,monkeypatch,lane,hhmm,called):
    calls=[]
    monkeypatch.setattr(gate,'selector_pointer_is_ready',lambda *a:False)
    monkeypatch.setattr(gate,'_a_lane_receipt_ready',lambda *a:(False,False))
    monkeypatch.setattr(gate,'_hk_lane_receipt_ready',lambda *a:False)
    monkeypatch.setattr(gate,'run_lanes',lambda **kw:calls.append(kw['lane']) or {'lanes':{},'overall_status':'FAILED'})
    r=gate.ensure_after_1700(target_date='20261029',receipt_root=tmp_path,selector_pointer=tmp_path/'pointer',a_runner=lambda _:None,hk_runner=lambda _:None,lane=lane,now=moment(hhmm))
    assert bool(calls)==called
    if not called:assert gate.ensure_exit_code(r)==0
def test_failed_a_slot_retains_backoff_then_retries(tmp_path):
    receipts=tmp_path/'receipts/live/20261029/1530';receipts.mkdir(parents=True)
    (receipts/'network.dispatch-receipt.json').write_text(json.dumps({'status':'FAILED','failure_class':'NETWORK','attempt':1,'finished_at':moment('1530').isoformat(),'workload_results':[]}))
    assert scheduler._slot_blocks_retry(tmp_path,'20261029','1530',moment=moment('1531'))
    assert not scheduler._slot_blocks_retry(tmp_path,'20261029','1530',moment=moment('1535'))
