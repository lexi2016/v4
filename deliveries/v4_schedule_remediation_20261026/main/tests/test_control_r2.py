from datetime import datetime, timedelta, UTC
from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess
import sys
import time
import pytest
from contracts.runtime_tasks import DispatchRequest, DispatchMode
from infrastructure.scheduling import dispatcher
from infrastructure.scheduling import execution_ledger as ledger_module
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.catalog import load_workload_catalog
from ops import run_v35_macos_scheduler as scheduler
from ops import run_v35_macos_scheduler_daemon as daemon

DAY='20261026'
START=datetime(2026,10,26,9,1,tzinfo=daemon.SHANGHAI)


def fail(root, at, cls, source, slot='0901'):
    ledger=ExecutionLedger(root)
    ledger.write_receipt(f'receipts/live/{DAY}/{slot}/{at:%H%M%S}.dispatch-receipt.json',
        {'business_date':DAY,'slot':slot,'status':'FAILED','finished_at':at.isoformat(),'failure_class':cls,'source_identity':source})


def test_network_history_does_not_exempt_current_data_episode(tmp_path):
    pointer=tmp_path/'source.txt';pointer.write_text('source-sha-one')
    identity=dispatcher.refresh_retry_source_identity({'descriptors':[{'path':str(pointer),'kind':'pointer'}]})
    root=tmp_path/'ledger'
    fail(root,START,'NETWORK',None)
    fail(root,START+timedelta(minutes=5),'UPSTREAM_NOT_READY',identity)
    for minute in (10,15,20,30,58):
        assert scheduler._slot_blocks_retry(root,DAY,'0901',moment=START+timedelta(minutes=minute))
    pointer.write_text('source-sha-two')
    assert not scheduler._slot_blocks_retry(root,DAY,'0901',moment=START+timedelta(minutes=10))


def test_unknown_episode_budget_restarts_after_network_without_unbounded_retries(tmp_path):
    root=tmp_path/'ledger';unknown=dispatcher.refresh_retry_source_identity({'descriptors':[]})
    fail(root,START,'NETWORK',None)
    fail(root,START+timedelta(minutes=5),'INPUT_MISSING',unknown)
    assert not scheduler._slot_blocks_retry(root,DAY,'0901',moment=START+timedelta(minutes=10))
    fail(root,START+timedelta(minutes=10),'UPSTREAM_NOT_READY',unknown)
    assert scheduler._slot_blocks_retry(root,DAY,'0901',moment=START+timedelta(minutes=15))
    # A later actual transient network failure gets its own original backoff.
    fail(root,START+timedelta(minutes=20),'NETWORK',None)
    assert scheduler._slot_blocks_retry(root,DAY,'0901',moment=START+timedelta(minutes=24))
    assert not scheduler._slot_blocks_retry(root,DAY,'0901',moment=START+timedelta(minutes=25))


def test_a_output_pointers_are_explicitly_unknown_not_input_identity(tmp_path,monkeypatch):
    selector=tmp_path/'selector'
    output=selector/'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt'
    output.parent.mkdir(parents=True);output.write_text('unchanged-output')
    monkeypatch.setenv('V35_RESEARCH_PANEL_A_SELECTOR_POINTER',str(output))
    monkeypatch.setenv('V35_RESEARCH_PANEL_A_BACKTEST_POINTER',str(output))
    tdx=tmp_path/'fixture.day';tdx.write_bytes(b'old-actual-input')
    request=DispatchRequest(DAY,DAY,DAY,'1700',DispatchMode.LIVE)
    identity=dispatcher.capture_retry_source_identity(SimpleNamespace(selector_data_root=selector,research_panel_a_tdx_root=tmp_path),request,('hourly_research','research_panel_daily_a'))
    assert identity['status']=='CANNOT_CONFIRM' and identity['descriptors']==[]
    assert identity['reason']=='A_DAILY_INPUT_IDENTITY_UNAVAILABLE'
    root=tmp_path/'ledger';at=START.replace(hour=17,minute=0)
    fail(root,at,'UPSTREAM_NOT_READY',identity,slot='1700')
    tdx.write_bytes(b'repaired-actual-input')
    assert not scheduler._slot_blocks_retry(root,DAY,'1700',moment=at+timedelta(minutes=10))
    fail(root,at+timedelta(minutes=10),'UPSTREAM_NOT_READY',identity,slot='1700')
    assert scheduler._slot_blocks_retry(root,DAY,'1700',moment=at.replace(hour=23,minute=58))
    assert not scheduler._slot_blocks_retry(root,DAY,'1700',moment=at.replace(hour=23,minute=59))


def test_claim_io_delay_rechecks_current_wall_before_spawn(tmp_path,monkeypatch):
    clock=[START.replace(minute=19,second=59,microsecond=950000)]
    spawned=[]
    lanes=daemon.SlotProcessLanes(['--ledger-root',str(tmp_path/'ledger'),'--data-root',str(tmp_path)],
        release_id='fixture',clock=lambda:clock[0],popen_factory=lambda *a,**kw:spawned.append(a))
    lanes.enqueue(DAY,'0915',clock[0])
    def slow_claim(*a,**kw):clock[0]+=timedelta(milliseconds=100);return False
    monkeypatch.setattr(scheduler,'_slot_blocks_retry',slow_claim)
    lanes.pulse(clock[0])
    assert not spawned and not lanes.active and not lanes.queued
    observations=list((tmp_path/'ledger/scheduler_observations/live'/DAY/'0915').glob('*.json'))
    assert any(json.loads(p.read_bytes())['status']=='EXPIRED' for p in observations)
    fd=lanes.ledger.try_acquire_scheduler_lane('DEFAULT')
    assert fd is not None
    os.close(fd)


@pytest.fixture
def child_lane(tmp_path,monkeypatch):
    ledger=ExecutionLedger(tmp_path/'ledger')
    fd=ledger.try_acquire_scheduler_lane('DEFAULT')
    for key,value in {'V35_SCHEDULER_LANE_FD':str(fd),'V35_SCHEDULER_LANE_NAME':'DEFAULT',
        'V35_SCHEDULER_RESOLVED_DATE':DAY,'V35_SCHEDULER_RESOLVED_SLOT':'0915'}.items():monkeypatch.setenv(key,value)
    clock=[START.replace(minute=19,second=59,microsecond=950000)]
    class ClockDateTime(datetime):
        @classmethod
        def now(cls,tz=None):return clock[0].astimezone(tz or UTC)
    monkeypatch.setattr(ledger_module,'datetime',ClockDateTime)
    yield ledger,clock
    os.close(fd)


def test_late_child_forced_slot_cannot_enter_prerequisite(child_lane,tmp_path,monkeypatch,capsys):
    ledger,clock=child_lane;clock[0]+=timedelta(milliseconds=100)
    monkeypatch.setattr(scheduler,'compute_dates',lambda **kw:pytest.fail('expired child entered compute/prerequisite'))
    monkeypatch.setattr(scheduler,'run_scheduled_slot',lambda **kw:pytest.fail('expired child dispatch'))
    assert scheduler.main(['--data-root',str(tmp_path),'--ledger-root',str(ledger.root),'--slot','0915','--date',DAY])==0
    assert json.loads(capsys.readouterr().out)['status']=='EXPIRED'
    assert not list(ledger.root.rglob('*.claim.json'))


def test_child_rechecks_after_prerequisite_before_dispatch(child_lane,tmp_path,monkeypatch,capsys):
    ledger,clock=child_lane
    monkeypatch.setattr(scheduler,'compute_dates',lambda **kw:{'business_date':DAY,'scheduled_date':DAY,'target_date':DAY})
    monkeypatch.setattr(scheduler,'_is_non_trading_day',lambda *a:False)
    def prerequisite(**kw):clock[0]+=timedelta(milliseconds=100);return {'status':'READY'}
    monkeypatch.setattr(scheduler,'ensure_stage_candidate_input',prerequisite)
    monkeypatch.setattr(scheduler,'run_scheduled_slot',lambda **kw:pytest.fail('late dispatch after prerequisite'))
    assert scheduler.main(['--data-root',str(tmp_path),'--ledger-root',str(ledger.root),'--stage-selection-root',str(tmp_path/'stage'),'--slot','0915','--date',DAY])==0
    assert json.loads(capsys.readouterr().out)['status']=='EXPIRED'


def test_dispatcher_rechecks_after_claim_io_before_executor(child_lane,monkeypatch):
    ledger,clock=child_lane
    original=ledger.try_claim_dispatch
    def delayed_claim(request):
        claim=original(request);clock[0]+=timedelta(milliseconds=100);return claim
    monkeypatch.setattr(ledger,'try_claim_dispatch',delayed_claim)
    request=DispatchRequest(DAY,DAY,DAY,'0915',DispatchMode.LIVE)
    result=dispatcher.dispatch_due(request,load_workload_catalog(),lambda *a:pytest.fail('late executor'),ledger=ledger)
    assert result.status=='FAILED' and result.failure_class=='NOT_DUE'
    assert not result.invoked_workload_ids


def until(check,seconds=5):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if check():return
        time.sleep(.01)
    assert check(),'owned fixture condition timed out'


DELAYED_CHILD=r'''
import sys,time,json,os
from pathlib import Path
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from contracts.runtime_tasks import DispatchRequest,DispatchMode
root,slot,tag=Path(sys.argv[1]),sys.argv[2],sys.argv[3]
(root/(tag+'.started')).write_text(str(os.getpid()))
while not (root/'release').exists():time.sleep(.01)
claim=ExecutionLedger(root).try_claim_dispatch(DispatchRequest('20261026','20261026','20261026',slot,DispatchMode.LIVE))
(root/(tag+'.claim')).write_text(json.dumps({'acquired':claim.acquired,'pid':os.getpid()}))
(root/(tag+'.finished')).touch()
'''


def test_preclaim_parent_crash_keeps_two_global_lanes_across_restarts(tmp_path):
    root=tmp_path/'ledger';root.mkdir()
    parent_code=r'''
import sys,subprocess,time,os
from pathlib import Path
from datetime import datetime
from ops import run_v35_macos_scheduler_daemon as d
root=Path(sys.argv[1]);at=datetime(2026,10,26,17,tzinfo=d.SHANGHAI)
def spawn(command,**kwargs):
 return subprocess.Popen([sys.executable,'-B','-c',sys.argv[2],str(root),'1700','old1700'],**kwargs)
lanes=d.SlotProcessLanes(['--ledger-root',str(root),'--data-root',str(root)],release_id='fixture',popen_factory=spawn,clock=lambda:at)
lanes.enqueue('20261026','1700',at);lanes.pulse(at)
while not (root/'old1700.started').exists():time.sleep(.01)
os._exit(9)
'''
    parent=subprocess.Popen([sys.executable,'-B','-c',parent_code,str(root),DELAYED_CHILD],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    children=[];lanes=None
    try:
        assert parent.wait(timeout=5)==9
        assert not (root/'claims/live'/DAY/'1700/dispatch.claim.json').exists()
        def spawn(command,**kwargs):
            slot=command[command.index('--slot')+1]
            child=subprocess.Popen([sys.executable,'-B','-c',DELAYED_CHILD,str(root),slot,'new'+slot],**kwargs)
            children.append(child);return child
        at=START.replace(hour=17,minute=10)
        lanes=daemon.SlotProcessLanes(['--ledger-root',str(root),'--data-root',str(root)],release_id='fixture',popen_factory=spawn,clock=lambda:at)
        lanes.enqueue(DAY,'1700',at);lanes.pulse(at)
        lanes.enqueue(DAY,'1710',at);lanes.pulse(at)
        until(lambda:(root/'new1710.started').exists())
        assert not (root/'new1700.started').exists()
        assert len(children)==1 and len(lanes.active)==1 and len(lanes.queued)==1
        assert lanes.ledger.try_acquire_scheduler_lane('A_LONG') is None
        assert lanes.ledger.try_acquire_scheduler_lane('DEFAULT') is None
        another=daemon.SlotProcessLanes(['--ledger-root',str(root),'--data-root',str(root)],release_id='fixture',popen_factory=lambda *a,**k:pytest.fail('third child'),clock=lambda:at)
        another.enqueue(DAY,'1700',at);another.enqueue(DAY,'1720',at);another.pulse(at)
        assert not another.active and len(another.queued)==2
        old_pid=int((root/'old1700.started').read_text());os.kill(old_pid,0)
    finally:
        (root/'release').touch()
        for child in children:child.wait(timeout=5)
        until(lambda:(root/'old1700.finished').exists())
        if lanes:lanes.pulse(at,dispatch=False)
