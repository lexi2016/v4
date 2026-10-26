"""R5 only: native sleep argv, consumed-failure closure, new ACK binding."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest
import admin_bridge as b
import guard_recipe as g

CASE=Path(__file__).resolve().parent

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    work=tmp_path/'r5';legacy=tmp_path/'r4';work.mkdir();legacy.mkdir()
    shutil.copytree(CASE/'FAILED_R4',work/'FAILED_R4')
    for name in ('owned-checkpoint.json','service-owned-operation.json','admin-request.json'):
        (legacy/name).write_bytes((CASE/'FAILED_R4'/name).read_bytes())
    lock=tmp_path/'service.owner.lock';lock.touch()
    closure=json.loads((CASE/'CONSUMED_R4_CLOSURE.json').read_text())
    closure['stable_lock_inode']=lock.stat().st_ino
    (work/'CONSUMED_R4_CLOSURE.json').write_text(json.dumps(closure))
    monkeypatch.setattr(g,'ROOT',work);monkeypatch.setattr(b,'ROOT',work)
    monkeypatch.setattr(b,'LEGACY',legacy);monkeypatch.setattr(b,'LOCK_PATH',lock)
    monkeypatch.setattr(b,'EXPECTED_LOCK_INODE',lock.stat().st_ino)
    return work,legacy,lock

class FixtureOps:
    p={'service':b.SERVICE,'guard_seconds':618518,'guard_program_sha256':'fixture-sleep-pin'}
    def __init__(self):self.package_checks=0
    def check_old(self,old):pass
    def command(self,args):
        assert args[:3]==['/bin/ps','-ww','-p']
        return SimpleNamespace(stdout='fixture newly-owned original main identity\n')
    def verify_package(self):self.package_checks+=1

def test_native_duplicate_sleep_argument_fails_and_correct_argv_exits_naturally():
    bad=subprocess.run(['/bin/sleep','/bin/sleep','0.1'],capture_output=True,text=True,timeout=1)
    assert bad.returncode==1 and 'sleep: invalid time interval: /bin/sleep' in bad.stderr
    start=time.monotonic()
    child=subprocess.Popen(['/bin/sleep','0.2'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    comm=subprocess.check_output(['/bin/ps','-p',str(child.pid),'-o','comm='],text=True).strip()
    out,err=child.communicate(timeout=1)
    assert comm=='/bin/sleep' and child.returncode==0 and not out and not err
    assert time.monotonic()-start>=0.15
    assert b.COMMAND==['/bin/launchctl','debug',b.SERVICE,'--program','/bin/sleep','--','618518']
    assert b.LEGACY_COMMAND[-3:]==['--','/bin/sleep','618518']

def test_consumed_failure_closure_preserves_armed_history_and_same_lock(isolated):
    work,legacy,lock=isolated
    original=(legacy/'owned-checkpoint.json').read_bytes();cp=json.loads(original)
    j=g.Journal(work/'owned-checkpoint.json',{'fixture_target':'same-main-r2'})
    try:
        assert cp['armed'] is True and cp['phase']=='DRAINING'
        assert j.data['legacy_consumed_failed_closure']['classification']=='CONSUMED_FAILED_SLEEP_ARGUMENT'
        assert os.fstat(j.fd).st_ino==lock.stat().st_ino
        with pytest.raises(g.StopOwned,match='OWNED_EXECUTOR_STILL_RUNNING'):
            g.Journal(work/'other.checkpoint.json',{'fixture_target':'same-main-r2'})
    finally:j.close()
    assert (legacy/'owned-checkpoint.json').read_bytes()==original
    closure=json.loads((work/'CONSUMED_R4_CLOSURE.json').read_text());closure['classification']='UNKNOWN_PENDING_DEBUG'
    (work/'CONSUMED_R4_CLOSURE.json').write_text(json.dumps(closure))
    with pytest.raises(b.BridgeStop,match='LEGACY_CONSUMED_CLOSURE_OR_LOCK_BINDING_MISMATCH'):
        g.Journal(work/'owned-checkpoint.json',{'fixture_target':'same-main-r2'},resume=True)
    (legacy/'owned-checkpoint.json').write_bytes(original+b' ')
    with pytest.raises(b.BridgeStop,match='LEGACY_FAILURE_HISTORY_CHANGED'):
        g.Journal(work/'owned-checkpoint.json',{'fixture_target':'same-main-r2'},resume=True)

def test_new_fixed_helper_and_ack_cannot_reuse_consumed_root_ack(isolated,monkeypatch):
    work,legacy,lock=isolated
    j=g.Journal(work/'owned-checkpoint.json',{'fixture_target':'same-main-r2'})
    ops=FixtureOps()
    try:
        j.save(old={'pid':12345,'start':'new-owned-start','command':'new-owned-original-main'})
        j.intent('ARM_REQUESTED','launchctl debug next invocation /bin/sleep')
        with pytest.raises(b.BridgeStop,match='ADMIN_ACK_REQUIRED_NO_TERM_SENT'):b.prepare(j,ops)
        request=json.loads((work/'admin-request.json').read_text());helper=work/'admin-debug-once.sh'
        assert request['operation_id']!=b.FAILED_OPERATION and request['command']==b.COMMAND
        assert request['legacy_consumed_failure']['operation_id']==b.FAILED_OPERATION
        exact='/bin/launchctl debug gui/501/com.lexi.v35.scheduler --program /bin/sleep -- 618518'
        assert helper.read_text().count(exact)==1
        assert '-- /bin/sleep 618518' not in helper.read_text()
        assert subprocess.run(['/bin/sh','-n',str(helper)],capture_output=True).returncode==0
        assert os.getuid()!=0
        run=subprocess.run(['/bin/sh',str(helper)],capture_output=True,text=True)
        assert run.returncode==2 and 'ROOT_REQUIRED' in run.stderr
        assert not b.ack_directory(request).exists()
        old_ack=json.loads((work/'FAILED_R4/root-result.json').read_text())
        monkeypatch.setattr(b,'trusted_root_ack',lambda path:old_ack)
        with pytest.raises(b.BridgeStop,match='ADMIN_ACK_MISMATCH_OR_NONZERO_NO_TERM'):b.accept(j,ops)
        assert j.data['phase']=='ARM_REQUESTED' and not j.data['armed']
        def missing(path):raise FileNotFoundError(path)
        monkeypatch.setattr(b,'trusted_root_ack',missing)
        with pytest.raises(b.BridgeStop,match='MISSING_UNKNOWN_NO_DEBUG_OR_TERM_RETRY'):b.accept(j,ops)
        ack={'schema':'v4.main_guard.root_debug_ack.v1','request_sha256':b.digest(b.canonical(request)),
           'operation_id':j.data['operation_id'],'plan_sha256':j.data['plan_sha256'],'old':j.data['old'],
           'service':b.SERVICE,'program':'/bin/sleep','command':b.COMMAND,'rc':0}
        # Explicit root metadata fixture only; no new actual root action exists.
        monkeypatch.setattr(b,'trusted_root_ack',lambda path:ack)
        b.accept(j,ops)
        assert j.data['phase']=='ARMED' and j.data['armed'] and ops.package_checks==1
    finally:j.close()
