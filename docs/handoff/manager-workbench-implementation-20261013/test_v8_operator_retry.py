from pathlib import Path
import importlib.util,json,plistlib,sys
from types import SimpleNamespace
import pytest
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('mwb_v8_retry',HERE/'operate_scheduled_lanes_v8.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def pair(tmp_path):
 p=tmp_path/'service.plist';p.write_bytes(plistlib.dumps(dict(ProgramArguments=['/usr/bin/env','V35_APP_ROOT=/verified/app','V35_RELEASE_ID=verified','V35_RELEASE_MANIFEST_PATH=/verified/release-manifest.json','V35_RELEASE_MANIFEST_SHA256='+'a'*64],Label='test')))
 return dict(label='test',formal_path=str(p),original_sha256=m.operator.sha(p.read_bytes()),staged_sha256='b'*64)


def fake_launch(monkeypatch,failures):
 state={'loaded':False,'bootstraps':0};identity='/verified/app verified '+ 'a'*64
 def run(args,**kwargs):
  assert 0<kwargs['timeout']<=2
  if args[1]=='print':return SimpleNamespace(returncode=0 if state['loaded'] else 3,stdout=identity if state['loaded'] else '',stderr='' if state['loaded'] else 'Could not find service')
  state['bootstraps']+=1
  if state['bootstraps']<=failures:return SimpleNamespace(returncode=5,stdout='',stderr='Input/output error')
  state['loaded']=True;return SimpleNamespace(returncode=0,stdout='',stderr='')
 monkeypatch.setattr(m.subprocess,'run',run);monkeypatch.setattr(m.time,'sleep',lambda _:None)
 return state


def test_transient5_retry_and_no_duplicate_loaded_bootstrap(tmp_path,monkeypatch):
 p=pair(tmp_path);state=fake_launch(monkeypatch,2);m.launch('bootstrap',p)
 assert state['bootstraps']==3
 m.launch('bootstrap',p);assert state['bootstraps']==3


def test_transient5_exhaustion_is_bounded(tmp_path,monkeypatch):
 state=fake_launch(monkeypatch,99)
 with pytest.raises(RuntimeError,match='TRANSIENT_5_EXHAUSTED'):m.launch('bootstrap',pair(tmp_path))
 assert state['bootstraps']==4 and state['loaded'] is False


def test_loaded_other_identity_never_retried(tmp_path,monkeypatch):
 monkeypatch.setattr(m.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout='/other/app',stderr=''))
 with pytest.raises(RuntimeError,match='LOADED_IDENTITY_MISMATCH'):m.launch('bootstrap',pair(tmp_path))


def test_failure_journal_is_terminal_and_previous_attempt_preserved(tmp_path,monkeypatch):
 # Runtime journal only in a temporary handoff subdirectory, no service actions.
 root=HERE/'.tmp'/('operator-retry-test-'+__import__('uuid').uuid4().hex);root.mkdir(exist_ok=False)
 plan=root/'plan.json';plan.write_text('{}');previous=root/'operator-apply-journal.json';previous.write_text('original failure')
 monkeypatch.setattr(sys,'argv',['op','--plan',str(plan),'--plan-sha256',m.operator.sha(plan.read_bytes()),'--execute'])
 monkeypatch.setattr(m.operator,'validate',lambda *a:None)
 def fail(plan,mode,journal):journal.write_text('{"status":"WRITTEN","started":[]}');raise RuntimeError('restore bootstrap exhausted')
 monkeypatch.setattr(m.operator,'execute',fail)
 with pytest.raises(RuntimeError):m.main()
 journals=list(root.glob('operator-apply-*-journal.json'))
 assert len(journals)==1 and json.loads(journals[0].read_text())['status']=='FAILED_RESTORE_OR_ACTIVATION_REQUIRES_READBACK'
 assert previous.read_text()=='original failure'


def test_formal_drift_after_transient5_never_bootstraps_again(tmp_path,monkeypatch):
 p=pair(tmp_path);calls=[]
 def run(args,**kwargs):
  if args[1]=='print':return SimpleNamespace(returncode=3,stdout='',stderr='Could not find service')
  calls.append(args);Path(p['formal_path']).write_text('parallel replacement')
  return SimpleNamespace(returncode=5,stdout='',stderr='Input/output error')
 monkeypatch.setattr(m.subprocess,'run',run)
 with pytest.raises(ValueError,match='BOOTSTRAP_PLIST_IDENTITY_DRIFT'):m.launch('bootstrap',p)
 assert len(calls)==1


def test_bootout_waits_for_known_old_label_absence(tmp_path,monkeypatch):
 p=pair(tmp_path);state={'print':0,'bootout':0}
 def run(args,**kwargs):
  if args[1]=='bootout':state['bootout']+=1;return SimpleNamespace(returncode=0,stdout='',stderr='')
  state['print']+=1
  if state['print']<=3:return SimpleNamespace(returncode=0,stdout='/verified/app verified '+'a'*64,stderr='')
  return SimpleNamespace(returncode=3,stdout='',stderr='Could not find service')
 monkeypatch.setattr(m.subprocess,'run',run);monkeypatch.setattr(m.time,'sleep',lambda _:None)
 m.launch('bootout',p)
 assert state=={'print':4,'bootout':1}


def test_bootout_label_never_leaves_times_out_without_write(tmp_path,monkeypatch):
 p=pair(tmp_path);clock=[0.0];original=Path(p['formal_path']).read_bytes()
 monkeypatch.setattr(m.time,'monotonic',lambda:clock[0]);monkeypatch.setattr(m.time,'sleep',lambda delay:clock.__setitem__(0,clock[0]+delay))
 def run(args,**kwargs):return SimpleNamespace(returncode=0,stdout='/verified/app verified '+'a'*64,stderr='')
 monkeypatch.setattr(m.subprocess,'run',run)
 with pytest.raises(RuntimeError,match='BOOTOUT_LABEL_EXIT_TIMEOUT'):m.launch('bootout',p)
 assert clock[0]<10 and Path(p['formal_path']).read_bytes()==original
