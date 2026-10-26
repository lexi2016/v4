# R2 lifecycle regression with the newly explicit injected wall clock.
from datetime import datetime, timedelta
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import threading
import time
import pytest
from ops import run_v35_macos_scheduler_daemon as daemon
from ops import run_v35_macos_scheduler as scheduler
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from contracts.runtime_tasks import DispatchRequest, DispatchMode

DAY='20261026'
AT=datetime(2026,10,26,17,0,tzinfo=daemon.SHANGHAI)
CHILD_CODE=r'''
import sys,time,json
from pathlib import Path
from contracts.runtime_tasks import DispatchRequest,DispatchMode
from infrastructure.scheduling.execution_ledger import ExecutionLedger
root,day,slot=sys.argv[1:]
root=Path(root); ledger=ExecutionLedger(root)
request=DispatchRequest(day,day,day,slot,DispatchMode.LIVE)
claim=ledger.try_claim_dispatch(request)
(root/(slot+'.started')).write_text(json.dumps({'pid':__import__('os').getpid(),'run_id':claim.run_id,'acquired':claim.acquired}))
if not claim.acquired:
 print(json.dumps({'status':'CONCURRENCY_SKIPPED'}),flush=True);sys.exit(0)
while not (root/(slot+'.release')).exists(): time.sleep(.01)
if (root/(slot+'.crash')).exists():sys.exit(7)
payload={'status':'SUCCEEDED','run_id':claim.run_id,'business_date':day,'slot':slot,'mode':'LIVE',
 'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,'finished_at':__import__('datetime').datetime.now(__import__('datetime').UTC).isoformat()}
ledger.write_receipt(ledger.receipt_relative(request,run_id=claim.run_id),payload)
(root/(slot+'.finished')).touch()
print(json.dumps(payload),flush=True)
'''

def until(check, seconds=4):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if check():return
        time.sleep(.01)
    assert check(),'fixture condition timed out'


class Factory:
    def __init__(self,root): self.root=root;self.children=[];self.commands=[]
    def __call__(self,command,**kwargs):
        self.commands.append(command)
        slot=command[command.index('--slot')+1]
        child=subprocess.Popen([sys.executable,'-B','-c',CHILD_CODE,str(self.root),DAY,slot],**kwargs)
        self.children.append(child)
        return child
    def release(self,slot): (self.root/(slot+'.release')).touch()
    def cleanup(self):
        for cmd in self.commands:self.release(cmd[cmd.index('--slot')+1])
        for child in self.children:
            try:child.wait(timeout=4)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=2)


@pytest.fixture
def fixture(tmp_path):
    root=tmp_path/'ledger';root.mkdir();factory=Factory(root)
    lanes=daemon.SlotProcessLanes(['--ledger-root',str(root),'--data-root',str(tmp_path),'--release-id','fixture'],release_id='fixture',popen_factory=factory,clock=lambda:AT)
    # Explicit virtual wall clock seam added by R2. Each retained test's pulse
    # now advances both planning and current wall time; delay tests are separate.
    original_pulse=lanes.pulse
    def pulse_at(moment, **kwargs):
        lanes.clock=lambda:moment
        return original_pulse(moment, **kwargs)
    lanes.pulse=pulse_at
    yield lanes,factory,root
    factory.cleanup()


def observations(root,slot):
    return [json.loads(p.read_bytes()) for p in (root/'scheduler_observations/live'/DAY/slot).glob('*.observation.json')]


def test_two_lanes_keep_full_1700_owner_and_other_lane_order(fixture):
    lanes,factory,root=fixture
    lanes.enqueue(DAY,'1700',AT);lanes.pulse(AT)
    until(lambda:(root/'1700.started').exists())
    lanes.enqueue(DAY,'1710',AT+timedelta(minutes=10));lanes.pulse(AT+timedelta(minutes=10))
    until(lambda:(root/'1710.started').exists())
    lanes.enqueue(DAY,'1720',AT+timedelta(minutes=20));lanes.pulse(AT+timedelta(minutes=20))
    assert len(lanes.active)==2 and len(factory.children)==2
    q=[p for p in observations(root,'1720') if p['status']=='QUEUED_BEHIND']
    assert q and q[0]['blocking_slot']=='1710' and q[0]['blocking_pid']==lanes.active['DEFAULT']['child'].pid
    factory.release('1710')
    until(lambda:factory.children[1].poll() is not None)
    lanes.pulse(AT+timedelta(minutes=20,seconds=1))
    until(lambda:(root/'1720.started').exists())
    assert lanes.active['A_LONG']['slot']=='1700' and lanes.active['DEFAULT']['slot']=='1720'
    started=json.loads((root/'1700.started').read_bytes())
    claim=json.loads((root/'claims/live'/DAY/'1700/dispatch.claim.json').read_bytes())
    assert claim['pid']==started['pid']!=os.getpid()
    assert ExecutionLedger(root).dispatch_claim_blocks_retry(DAY,'1700')
    assert all(cmd[:4]==[sys.executable,'-B','-m','ops.run_v35_macos_scheduler'] for cmd in factory.commands)
    assert factory.commands[0].count('--slot')==1


def test_duplicate_queued_or_active_slot_never_spawns_twice(fixture):
    lanes,factory,root=fixture
    lanes.enqueue(DAY,'1700',AT);lanes.enqueue(DAY,'1700',AT)
    lanes.pulse(AT);lanes.enqueue(DAY,'1700',AT);lanes.pulse(AT)
    assert len(factory.children)==1 and len(lanes.active)==1


def test_due_resolver_excludes_reserved_slots_without_new_scheduler(tmp_path):
    due=scheduler.resolve_due_slot(ledger_root=tmp_path,now=AT,excluded_slots=frozenset({'1700'}))
    assert due['slot']!='1700'


def test_success_claim_prevents_restarting_completed_slot(fixture):
    lanes,factory,root=fixture
    lanes.enqueue(DAY,'1700',AT);lanes.pulse(AT)
    until(lambda:(root/'1700.started').exists());factory.release('1700')
    until(lambda:factory.children[0].poll() is not None);lanes.pulse(AT+timedelta(seconds=1))
    assert not lanes.active
    lanes.enqueue(DAY,'1700',AT+timedelta(seconds=2));lanes.pulse(AT+timedelta(seconds=2))
    assert len(factory.children)==1 and not lanes.queued
    assert any(o['status']=='CLAIM_OR_RECEIPT_BLOCKED' for o in observations(root,'1700'))


def test_hk_auction_queue_expires_without_late_child(fixture):
    lanes,factory,root=fixture
    morning=AT.replace(hour=9,minute=1)
    lanes.enqueue(DAY,'0901',morning);lanes.pulse(morning)
    until(lambda:(root/'0901.started').exists())
    lanes.enqueue(DAY,'0915',morning.replace(minute=15))
    lanes.pulse(morning.replace(minute=20))
    assert len(factory.children)==1 and not lanes.queued
    assert any(o['status']=='EXPIRED' for o in observations(root,'0915'))
    assert lanes.active['DEFAULT']['slot']=='0901'


def test_old_date_and_late_queued_job_expire_without_execution(fixture):
    lanes,factory,root=fixture
    lanes.enqueue('20261025','1700',AT)
    assert not factory.children and not lanes.queued
    lanes.enqueue(DAY,'1700',AT)
    lanes.pulse(AT+timedelta(days=1))
    assert not factory.children and not lanes.queued


def test_monitor_observation_and_log_errors_preserve_child_owner(fixture,monkeypatch):
    lanes,factory,root=fixture
    lanes.enqueue(DAY,'1700',AT);lanes.pulse(AT)
    until(lambda:(root/'1700.started').exists())
    child=lanes.active['A_LONG']['child'];real_poll=child.poll
    monkeypatch.setattr(child,'poll',lambda:(_ for _ in ()).throw(OSError('monitor error')))
    monkeypatch.setattr(lanes.ledger,'write_scheduler_observation',lambda *a,**k:(_ for _ in ()).throw(OSError('disk full')))
    monkeypatch.setattr(daemon,'_emit',lambda *a:(_ for _ in ()).throw(OSError('log full')))
    lanes.pulse(AT+timedelta(minutes=1))
    assert lanes.active['A_LONG']['child'] is child
    assert ExecutionLedger(root).dispatch_claim_blocks_retry(DAY,'1700')
    lanes.enqueue(DAY,'1700',AT);assert len(factory.children)==1
    monkeypatch.setattr(child,'poll',real_poll)


def test_observation_failure_after_start_does_not_drop_child(fixture,monkeypatch):
    lanes,factory,root=fixture
    lanes.enqueue(DAY,'1700',AT)
    monkeypatch.setattr(lanes.ledger,'write_scheduler_observation',lambda *a,**k:(_ for _ in ()).throw(OSError('full')))
    lanes.pulse(AT)
    until(lambda:(root/'1700.started').exists())
    assert len(lanes.active)==1 and len(factory.children)==1
    assert ExecutionLedger(root).dispatch_claim_blocks_retry(DAY,'1700')


def test_child_crash_keeps_claim_until_actual_exit_then_can_recover(fixture):
    lanes,factory,root=fixture
    lanes.enqueue(DAY,'1700',AT);lanes.pulse(AT)
    until(lambda:(root/'1700.started').exists())
    assert ExecutionLedger(root).dispatch_claim_blocks_retry(DAY,'1700')
    (root/'1700.crash').touch();factory.release('1700')
    until(lambda:factory.children[0].poll() is not None);lanes.pulse(AT+timedelta(seconds=1))
    assert not lanes.active
    assert not ExecutionLedger(root).dispatch_claim_blocks_retry(DAY,'1700')
    assert any(o['status']=='FINISHED_CANNOT_CONFIRM' and o['return_code']==7 for o in observations(root,'1700'))


def test_parent_wait_does_not_cancel_alive_child(fixture):
    lanes,factory,root=fixture
    lanes.enqueue(DAY,'1700',AT);lanes.pulse(AT)
    until(lambda:(root/'1700.started').exists())
    waiter=threading.Thread(target=lambda:lanes.wait_for_children(lambda:AT))
    waiter.start();time.sleep(.08)
    assert waiter.is_alive() and factory.children[0].poll() is None
    assert ExecutionLedger(root).dispatch_claim_blocks_retry(DAY,'1700')
    factory.release('1700');waiter.join(timeout=4)
    assert not waiter.is_alive() and not lanes.active


def test_start_failure_is_bounded_and_keeps_queue(fixture,monkeypatch):
    lanes,factory,root=fixture
    called=[]
    monkeypatch.setattr(lanes,'popen_factory',lambda *a,**k:called.append(1) or (_ for _ in ()).throw(OSError('start failed')))
    lanes.enqueue(DAY,'1700',AT);lanes.pulse(AT);lanes.pulse(AT+timedelta(seconds=1))
    assert len(called)==1 and len(lanes.queued)==1 and not lanes.active
    lanes.pulse(AT+timedelta(seconds=300));assert len(called)==2


def test_parent_signal_waits_and_child_holds_own_claim(tmp_path):
    root=tmp_path/'ledger';root.mkdir()
    code='''import sys,threading,time,subprocess\nfrom pathlib import Path\nfrom datetime import datetime\nfrom ops import run_v35_macos_scheduler_daemon as d\nroot=Path(sys.argv[1]); event=threading.Event();d._install_signal_handlers(event)\ndef spawn(cmd,**kw):\n return subprocess.Popen([sys.executable,'-B','-c',sys.argv[2],str(root),'20261026','1700'],**kw)\nlanes=d.SlotProcessLanes(['--ledger-root',str(root),'--data-root',str(root)],release_id='fixture',popen_factory=spawn)\nat=datetime(2026,10,26,17,tzinfo=d.SHANGHAI)\nlanes.enqueue('20261026','1700',at);lanes.pulse(at)\n(root/'parent.ready').touch()\ntry:\n while not event.wait(.01):pass\nfinally:lanes.wait_for_children(lambda:at)\n(root/'parent.finished').touch()\n'''
    parent=subprocess.Popen([sys.executable,'-B','-c',code,str(root),CHILD_CODE],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        until(lambda:(root/'parent.ready').exists() and (root/'1700.started').exists())
        claim=json.loads((root/'claims/live'/DAY/'1700/dispatch.claim.json').read_bytes())
        assert claim['pid']!=parent.pid
        os.kill(parent.pid,signal.SIGTERM);time.sleep(.1)
        assert parent.poll() is None and ExecutionLedger(root).dispatch_claim_blocks_retry(DAY,'1700')
        (root/'1700.release').touch();assert parent.wait(timeout=4)==0
        assert (root/'parent.finished').exists()
    finally:
        (root/'1700.release').touch()
        try:parent.wait(timeout=4)
        except subprocess.TimeoutExpired:parent.kill();parent.wait(timeout=2)


def test_daemon_default_path_dispatches_child_and_waits_on_stop(fixture,monkeypatch,capsys):
    lanes,factory,root=fixture
    monkeypatch.setenv('V35_RELEASE_ID','fixture')
    monkeypatch.delenv('V4_MANAGER_WORKBENCH_CONFIG_PATH',raising=False)
    monkeypatch.setattr(daemon.AnnouncementCycleHook,'from_environment',lambda **kw:None)
    monkeypatch.setattr(daemon.PdfQueueDrainHook,'from_environment',lambda **kw:None)
    original=daemon.SlotProcessLanes
    monkeypatch.setattr(daemon,'SlotProcessLanes',lambda *a,**kw:lanes)
    # Keep the static log seam available on the constructor replacement.
    daemon.SlotProcessLanes._log=original._log
    class StopAfterDispatch:
        done=False
        def is_set(self):return self.done
        def set(self):self.done=True
        def wait(self,seconds):
            self.done=True
            return True
    def release_when_started():
        until(lambda:(root/'1700.started').exists())
        time.sleep(.05)
        factory.release('1700')
    releaser=threading.Thread(target=release_when_started);releaser.start()
    result=daemon.run_daemon(lanes.argv,clock=lambda:AT,stop_event=StopAfterDispatch(),install_signals=False)
    releaser.join(timeout=4)
    assert result==0 and len(factory.children)==1 and not lanes.active
    output=capsys.readouterr().out
    assert 'DAEMON_DISPATCH_CYCLE' in output and 'DAEMON_STOPPED' in output
    assert output.index('DAEMON_WAITING_FOR_CHILDREN')<output.index('DAEMON_STOPPED')


def test_reap_monitor_error_never_forgets_child_handle(fixture,monkeypatch):
    lanes,factory,root=fixture
    lanes.enqueue(DAY,'1700',AT);lanes.pulse(AT)
    until(lambda:(root/'1700.started').exists());factory.release('1700')
    until(lambda:factory.children[0].poll() is not None)
    child=factory.children[0];original_wait=child.wait
    monkeypatch.setattr(child,'wait',lambda **kw:(_ for _ in ()).throw(OSError('reap uncertain')))
    lanes.pulse(AT+timedelta(seconds=1))
    assert lanes.active['A_LONG']['child'] is child
    lanes.enqueue(DAY,'1700',AT);assert len(factory.children)==1
    monkeypatch.setattr(child,'wait',original_wait)
    lanes.pulse(AT+timedelta(seconds=2));assert not lanes.active


def test_hard_parent_exit_does_not_make_alive_child_claim_reclaimable(tmp_path):
    root=tmp_path/'ledger';root.mkdir()
    code='''import sys,subprocess,time,os\nfrom pathlib import Path\nfrom datetime import datetime\nfrom ops import run_v35_macos_scheduler_daemon as d\nroot=Path(sys.argv[1])\ndef spawn(cmd,**kw):\n return subprocess.Popen([sys.executable,'-B','-c',sys.argv[2],str(root),'20261026','1700'],**kw)\nlanes=d.SlotProcessLanes(['--ledger-root',str(root),'--data-root',str(root)],release_id='fixture',popen_factory=spawn)\nat=datetime(2026,10,26,17,tzinfo=d.SHANGHAI)\nlanes.enqueue('20261026','1700',at);lanes.pulse(at)\nwhile not (root/'1700.started').exists():time.sleep(.01)\nos._exit(9)\n'''
    parent=subprocess.Popen([sys.executable,'-B','-c',code,str(root),CHILD_CODE],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        assert parent.wait(timeout=4)==9
        claim=json.loads((root/'claims/live'/DAY/'1700/dispatch.claim.json').read_bytes())
        assert claim['pid']!=parent.pid
        assert ExecutionLedger(root).dispatch_claim_blocks_retry(DAY,'1700')
        # Another dispatcher cannot reclaim while the real child remains alive.
        request=DispatchRequest(DAY,DAY,DAY,'1700',DispatchMode.LIVE)
        assert not ExecutionLedger(root).try_claim_dispatch(request).acquired
        (root/'1700.release').touch()
        until(lambda:(root/'1700.finished').exists())
    finally:
        (root/'1700.release').touch()
        try:parent.wait(timeout=4)
        except subprocess.TimeoutExpired:parent.kill();parent.wait(timeout=2)
