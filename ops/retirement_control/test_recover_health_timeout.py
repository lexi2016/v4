"""R5 finite continuation tests; fake lifecycle and temporary evidence only."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util,json,sys,subprocess
import pytest
import recover_health_timeout as r
ROOT=Path(__file__).resolve().parent
CONTROL=ROOT if (ROOT/'retirement_control.py').exists() else ROOT.parent/'control'
c=r.module(CONTROL/'retirement_control.py','r5_test_control',r.CONTROL_SHA)
sys.modules['retirement_control']=c
spec=importlib.util.spec_from_file_location('r5_fake_helpers',CONTROL/'test_retirement_control.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

def failed_fixture(tmp_path,monkeypatch):
 monkeypatch.setattr(c,'HERE',tmp_path);p={};old='a'*32;run=tmp_path/('owned-run-'+old);run.mkdir()
 failed={'pid':98633,'ps_sha256':'b'*64,'ps_text':'failed-new'};restored={'pid':99334,'ps_sha256':'c'*64,'ps_text':'restored-old'}
 f={'schema':'v4.retirement.role.v1','operation_id':old,'plan_sha256':c.sha(c.canonical(p)),'phase':'HEALTH_FAILED','original_identity':{'pid':67002},'new':failed};back={**f,'original_identity':failed,'new':restored}
 c.save(run/'owned-api.checkpoint.json',f);c.save(run/'owned-api-health-rollback.checkpoint.json',back)
 h={'prior_operation_id':old,'operation_id':'d'*32,'nonce':'d'*32,'identities':{'api':restored},'failed_api_checkpoints':{name:c.sha(c.read(run/name)) for name in ['owned-api.checkpoint.json','owned-api-health-rollback.checkpoint.json']}}
 return p,h,run

def test_late_restored_evidence_never_rewrites_old_failure_checkpoints(tmp_path,monkeypatch):
 p,h,run=failed_fixture(tmp_path,monkeypatch);before={f.name:f.read_bytes() for f in run.iterdir()};monkeypatch.setattr(c,'Live',lambda *args:SimpleNamespace(new=lambda role:h['identities']['api'],health=lambda deadline:True))
 capsule=tmp_path/'new-evidence';capsule.mkdir();assert r.restored(c,p,h,run,capsule)==h['identities']['api']
 assert before=={f.name:f.read_bytes() for f in run.iterdir()}
 result=json.loads((capsule/'late-inverse-baseline-reconciliation.json').read_text())
 assert result['status']=='LATE_RESTORED_BASELINE_OBSERVED' and result['retroactive_30_second_pass'] is False
 assert all(json.loads(raw)['phase']=='HEALTH_FAILED' for raw in before.values())

def test_new_api_attempt_identity_and_namespace_are_truthful(tmp_path,monkeypatch):
 p,h,run=failed_fixture(tmp_path,monkeypatch);s=r.api_state(c,p,h)
 assert s['original_identity']['pid']==99334 and s['original_identity']['pid']!=67002
 assert s['operation_id']==h['nonce'] and s['operation_id']!=h['prior_operation_id']
 assert s['failed_api_checkpoints']==h['failed_api_checkpoints'] and s['children']=={}
 h['operation_id']=h['prior_operation_id']
 with pytest.raises(c.Stop,match='DISTINCT_API_STATE_REQUIRED'):r.api_state(c,p,h)

def test_existing_after_plist_reused_without_overwriting_any_source_bytes(tmp_path):
 old=tmp_path/'old.plist';after=tmp_path/'new.plist';old.write_bytes(b'original');after.write_bytes(b'accepted-new');meta=c.metadata.snapshot(old)
 p={'operations':[{'role':'api','plist':str(old),'new_plist':str(after),'before_sha256':c.sha(old.read_bytes()),'after_sha256':c.sha(after.read_bytes()),'plist_metadata':meta}]};events=[];o=SimpleNamespace(absent=lambda role:events.append('absent'),cas_confirmed=lambda role:events.append('exact-after-confirmed'))
 before=(old.read_bytes(),after.read_bytes());r.reuse_api_plist(c,p,o,tmp_path)
 assert (old.read_bytes(),after.read_bytes())==before and events==['absent','exact-after-confirmed']
 with pytest.raises(c.Stop,match='PLIST_RECONCILIATION_EXISTS_NO_RETRY'):r.reuse_api_plist(c,p,o,tmp_path)

def test_existing_after_plist_drift_fails_without_republish(tmp_path):
 old=tmp_path/'old';new=tmp_path/'new';old.write_bytes(b'old');new.write_bytes(b'drift');p={'operations':[{'role':'api','plist':str(old),'new_plist':str(new),'before_sha256':c.sha(b'old'),'after_sha256':c.sha(b'accepted'),'plist_metadata':c.metadata.snapshot(old)}]};o=SimpleNamespace(absent=lambda role:None,cas_confirmed=lambda role:pytest.fail('must not accept drift'))
 with pytest.raises(c.Stop,match='SHA_DRIFT'):r.reuse_api_plist(c,p,o,tmp_path)
 assert new.read_bytes()==b'drift'

def test_aux_only_real_recipe_never_visits_api_main_admin_or_rekicks_collector(tmp_path,monkeypatch):
 real=c.Recipe;seen=[];fakes={};p={'operations':[{'role':role,'old_disabled_before':False,'new_disabled_before':False} for role in r.AUX]};ss={};paths={}
 for role in r.AUX:
  ss[role]={'phase':'AUX_WAIT_IDLE' if role=='collector' else 'WAITING_ROOT_ACK','original_identity':None,'children':{}};paths[role]=tmp_path/(role+'.json')
 monkeypatch.setattr(c,'handoff',lambda *args:True);monkeypatch.setattr(c.time,'sleep',lambda *args:None)
 def make(p,h,o,s,path):
  role=path.stem;seen.append(role);fake=base.Fake();fake.current=fake.guard_i if role=='collector' else None;fakes[role]=fake;return real(p,h,fake,s,path)
 monkeypatch.setattr(c,'Recipe',make);monkeypatch.setattr(r,'api_helper',lambda *args:pytest.fail('AUX cannot create root helper'))
 r.finish_aux(c,p,{},object(),ss,paths)
 assert seen==list(r.AUX) and all(s['phase']=='DONE' for s in ss.values())
 assert not any('TERM' in o.events for o in fakes.values()) and 'KICK_NO_K' not in fakes['collector'].events
 assert all(o.events.count('BOOTOUT_SLEEP')==1 for o in fakes.values())

def test_api_helper_only_arms_current_old_api_once_and_fixed_new_rollback(tmp_path):
 p={'guard_program_sha256':'a'*64,'operations':[{'role':'api','plist':'/fixed/old.plist','new_plist':'/fixed/new.plist','before_sha256':'b'*64,'after_sha256':'c'*64}]};h={'operation_id':'d'*32,'nonce':'d'*32,'expires_epoch':400,'root_ack_dir':'/private/var/tmp/v4-retirement-nextspawn-'+'d'*32,'identities':{'api':{'pid':99334,'ps_sha256':'e'*64}}}
 script=r.api_helper(c,p,h,{'pid':123,'ps_sha256':'f'*64},tmp_path/'ready.json','1'*64,tmp_path/'finish.json')
 assert script.count('/bin/launchctl debug ')==2
 assert script.count('/bin/launchctl debug gui/501/'+c.OLD['api']+' ')==1
 assert script.count('/bin/launchctl debug gui/501/'+c.NEW['api']+' ')==1
 assert '99334' in script and '67002' not in script and 'controller-supplied arguments' in script
 for role in c.ROLES:
  if role!='api':assert c.OLD[role] not in script and c.NEW[role] not in script
 for forbidden in ('kill ','bootout','bootstrap',' disable ',' enable ','sudo','python','rm '):assert forbidden not in script
 path=tmp_path/'helper.sh';path.write_text(script);assert subprocess.run(['/bin/sh','-n',str(path)],capture_output=True).returncode==0

def test_existing_pending_old_api_override_is_never_rearmed():
 o=SimpleNamespace(original=lambda *args:None,identity=lambda pid:{'pid':pid},service=lambda role:{'pid':99334,'text':'\tprogram = /usr/bin/env\n\t\t+ /bin/sleep\n'})
 with pytest.raises(c.Stop,match='OLD_API_PENDING_OVERRIDE_NOT_EMPTY'):r.no_api_pending(c,{},o,{'pid':99334})
