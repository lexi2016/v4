"""Only the external-root ACK delta; no launchd/producer/network execution."""
from pathlib import Path
import fcntl
import json
import os
from types import SimpleNamespace

import pytest
import admin_bridge as b
import guard_recipe as g

CASE=Path(__file__).resolve().parent

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    work=tmp_path/'r4';legacy=tmp_path/'r3';work.mkdir();legacy.mkdir()
    for name in ('owned-checkpoint.json','service-owned-operation.json'):
        (legacy/name).write_bytes((CASE/'FAILED_R3'/name).read_bytes())
    lock=legacy/'service.owner.lock';lock.touch()
    closure=json.loads((CASE/'DENIED_R3_CLOSURE.json').read_text())
    closure['stable_lock_inode']=lock.stat().st_ino
    (work/'DENIED_R3_CLOSURE.json').write_text(json.dumps(closure))
    monkeypatch.setattr(g,'ROOT',work);monkeypatch.setattr(b,'ROOT',work)
    monkeypatch.setattr(b,'LEGACY',legacy);monkeypatch.setattr(b,'LOCK_PATH',lock)
    return work,legacy,lock

class FixtureOps:
    p={'service':b.SERVICE,'guard_seconds':618518,'guard_program_sha256':'sleep-pin'}
    def __init__(self):self.checked=[];self.package_checks=0
    def check_old(self,old):self.checked.append(old)
    def command(self,args):
        assert args[:3]==['/bin/ps','-ww','-p']
        return SimpleNamespace(stdout='fixture old PID/start/command\n')
    def verify_package(self):self.package_checks+=1

def requested(work):
    j=g.Journal(work/'owned-checkpoint.json',{'final_fixture_plan':'r2'})
    j.save(old={'pid':12345,'start':'fixture-original-start','command':'fixture-python -S -m ops.run_v35_macos_scheduler_daemon','identity_sha256':'fixture-identity'})
    j.intent('ARM_REQUESTED','launchctl debug next invocation /bin/sleep')
    ops=FixtureOps()
    with pytest.raises(b.BridgeStop,match='ADMIN_ACK_REQUIRED_NO_TERM_SENT'):b.prepare(j,ops)
    return j,ops,json.loads((work/'admin-request.json').read_text())

def valid_ack(j,request):
    return {'schema':'v4.main_guard.root_debug_ack.v1','request_sha256':b.digest(b.canonical(request)),
       'operation_id':j.data['operation_id'],'plan_sha256':j.data['plan_sha256'],'old':j.data['old'],
       'service':b.SERVICE,'program':'/bin/sleep','command':b.COMMAND,'rc':0}

def test_explicit_denial_preserved_and_same_inode_serializes_new_operation(isolated):
    work,legacy,lock=isolated
    original=(legacy/'owned-checkpoint.json').read_bytes()
    j=g.Journal(work/'owned-checkpoint.json',{'final_fixture_plan':'r2'})
    try:
        assert j.data['legacy_denied_unarmed_closure']['operation_id']==b.DENIED_OPERATION
        assert os.fstat(j.fd).st_ino==lock.stat().st_ino
        with pytest.raises(g.StopOwned,match='OWNED_EXECUTOR_STILL_RUNNING'):
            g.Journal(work/'another.checkpoint.json',{'final_fixture_plan':'r2'})
        j.intent('ARM_REQUESTED','fixed debug intent')
    finally:j.close()
    with pytest.raises(g.StopOwned,match='EXISTING_ARMED_OPERATION_REQUIRES_ITS_CHECKPOINT'):
        g.Journal(work/'another.checkpoint.json',{'final_fixture_plan':'r2'})
    assert (legacy/'owned-checkpoint.json').read_bytes()==original
    (legacy/'owned-checkpoint.json').write_bytes(original+b' ')
    with pytest.raises(b.BridgeStop,match='LEGACY_DENIAL_HISTORY_CHANGED'):
        g.Journal(work/'owned-checkpoint.json',{'final_fixture_plan':'r2'},resume=True)

def test_fixed_helper_root_boundary_and_rc0_ack_continue_same_operation(isolated,monkeypatch):
    import subprocess
    work,legacy,lock=isolated;j,ops,req=requested(work)
    try:
        helper=work/'admin-debug-once.sh'
        assert subprocess.run(['/bin/sh','-n',str(helper)],capture_output=True).returncode==0
        assert os.getuid()!=0,'fixture must never run as root'
        run=subprocess.run(['/bin/sh',str(helper)],capture_output=True,text=True)
        assert run.returncode==2 and 'ROOT_REQUIRED' in run.stderr
        assert not b.ack_directory(req).exists()
        text=helper.read_text()
        exact='/bin/launchctl debug gui/501/com.lexi.v35.scheduler --program /bin/sleep -- /bin/sleep 618518'
        assert text.count(exact)==1 and 'bootstrap' not in text and 'bootout' not in text
        assert not any(line.startswith(('/usr/bin/python','/Users/')) for line in text.splitlines())
        assert text.index('/bin/mkdir -m 755')<text.index(exact)
        assert 'EXISTING_ADMIN_INTENT_NO_RETRY' in text
        op=j.data['operation_id'];plan=j.data['plan_sha256']
        monkeypatch.setattr(b,'trusted_root_ack',lambda path:valid_ack(j,req))
        b.accept(j,ops)
        assert j.data['phase']=='ARMED' and j.data['armed'] and j.data['operation_id']==op and j.data['plan_sha256']==plan
        assert ops.package_checks==1
        with pytest.raises(b.BridgeStop,match='ADMIN_ACK_PHASE'):b.accept(j,ops)
        # Only target-dependent delta: final r2 release id is read from its
        # pinned plan, while the unchanged interpreter/module checks still run.
        target=work/'final.plist';target.write_bytes(b'fixture-reviewed-r2-plist')
        plan={**FixtureOps.p,'guard_program':'/bin/sleep','new_root':str(work/'final-r2/app'),
            'new_release_id':'final-r2','new_manifest_sha256':'fixture-r2-manifest',
            'expected_python':'/fixture/python with spaces','live_plist':str(target),
            'after_plist_sha256':g.sha(target.read_bytes())}
        reader=g.LiveOps(plan)
        identity={'pid':12345,'start':'fixture-start','command':plan['expected_python']+' -S -m ops.run_v35_macos_scheduler_daemon'}
        env={'V35_APP_ROOT':plan['new_root'],'V35_RELEASE_ID':'final-r2',
            'V35_RELEASE_MANIFEST_PATH':str(Path(plan['new_root']).parent/'release-manifest.json'),
            'V35_RELEASE_MANIFEST_SHA256':plan['new_manifest_sha256']}
        reader.service=lambda:{'loaded':True,'pid':12345,'text':'\n'.join(k+' => '+v for k,v in env.items())}
        reader.identity=lambda pid:identity;reader.cwd=lambda pid:plan['new_root']
        reader.verify_python_executable=lambda identity:None;reader.verify_package=lambda:None
        assert reader.new_binding()==identity
        env['V35_RELEASE_ID']='old-r1'
        with pytest.raises(g.StopOwned,match='NEW_ENV_BINDING_MISMATCH:V35_RELEASE_ID'):reader.new_binding()
    finally:j.close()

def test_missing_nonzero_cross_operation_and_untrusted_ack_never_arm(isolated,monkeypatch):
    work,legacy,lock=isolated;j,ops,req=requested(work)
    try:
        def missing(path):raise FileNotFoundError(path)
        monkeypatch.setattr(b,'trusted_root_ack',missing)
        with pytest.raises(b.BridgeStop,match='MISSING_UNKNOWN_NO_DEBUG_OR_TERM_RETRY'):b.accept(j,ops)
        for key,value in [('rc',1),('rc',False),('operation_id','0'*32),('plan_sha256','wrong'),('old',{'pid':999}),('request_sha256','wrong')]:
            ack={**valid_ack(j,req),key:value}
            monkeypatch.setattr(b,'trusted_root_ack',lambda path,ack=ack:ack)
            with pytest.raises(b.BridgeStop,match='MISMATCH_OR_NONZERO_NO_TERM'):b.accept(j,ops)
            assert j.data['phase']=='ARM_REQUESTED' and not j.data['armed']
        # Actual filesystem ownership rejection, not a mocked root-trust claim.
        normal=work/'user-owned';normal.mkdir();(normal/'result.json').write_text(json.dumps(valid_ack(j,req)))
        with pytest.raises(b.BridgeStop,match='DIRECTORY_NOT_ROOT_OWNED'):
            ORIGINAL_TRUSTED(normal/'result.json')
        with pytest.raises(b.BridgeStop,match='ADMIN_REQUEST_EXISTS_NO_REPREPARE'):b.prepare(j,ops)
        assert ops.package_checks==0
        helper=work/'admin-debug-once.sh';helper.chmod(0o600);helper.write_text(helper.read_text()+'# changed\n')
        with pytest.raises(b.BridgeStop,match='ADMIN_HELPER_BYTES_CHANGED'):b.accept(j,ops)
    finally:j.close()

ORIGINAL_TRUSTED=b.trusted_root_ack
