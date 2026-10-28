"""Targeted finite continuation tests; fake lifecycle only."""
import importlib.util,json,sys,subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
import recover_remaining as r

ROOT=Path(__file__).resolve().parent
CONTROL=ROOT if (ROOT/'retirement_control.py').exists() else ROOT.parent/'control'
c=r.load_control(CONTROL)
sys.modules['retirement_control']=c
spec=importlib.util.spec_from_file_location('fixed_recipe_test_helpers',CONTROL/'test_retirement_control.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

def sample(tmp_path):
 p={'operations':[{'role':role,'plist':'/Users/lexi/Library/LaunchAgents/'+c.OLD[role]+'.plist','new_plist':'/Users/lexi/Library/LaunchAgents/'+c.NEW[role]+'.plist','before_sha256':'b'*64,'after_sha256':'c'*64,'old_disabled_before':False,'new_disabled_before':False} for role in c.ROLES],'guard_program_sha256':'a'*64}
 old={'pid':11,'ps_sha256':'a'*64,'ps_text':'old'};new={'pid':21,'ps_sha256':'b'*64,'ps_text':'new'}
 l={'schema':'v4.retirement.remaining_lease.r1','nonce':'e'*32,'operation_id':'d'*32,'plan_sha256':c.sha(c.canonical(p)),'observed_epoch':100,'expires_epoch':400,'root_ack_dir':'/private/var/tmp/v4-retirement-renew-'+'d'*32+'-'+'e'*32,'identities':{role:old if role=='api' else None for role in r.REMAINING},'checkpoint_sha256':{},'main':{'phase':'DONE','new_identity':new,'checkpoint_sha256':''}}
 m={'schema':'v4.retirement.role.v1','phase':'DONE','operation_id':l['operation_id'],'plan_sha256':l['plan_sha256'],'original_identity':old,'new':new,'term_sent':True}
 path=tmp_path/'owned-main.checkpoint.json';c.save(path,m);l['main']['checkpoint_sha256']=c.sha(c.read(path))
 for role in r.REMAINING:
  path=tmp_path/('owned-'+role+'.checkpoint.json');c.save(path,{'schema':'v4.retirement.role.v1','phase':'WAITING_ROOT_ACK','operation_id':l['operation_id'],'plan_sha256':l['plan_sha256'],'original_identity':l['identities'][role],'children':{}});l['checkpoint_sha256'][role]=c.sha(c.read(path))
 l['prearmed_collector']={'guard':{'pid':12,'ps_sha256':c.sha(b'/bin/sleep 604800'),'ps_text':'/bin/sleep 604800'},'original_checkpoint_sha256':l['checkpoint_sha256']['collector']}
 proof=tmp_path/'original-proof.json';proof.write_text(json.dumps({'helper':{'path':'/fixed/original-helper.sh','sha256':'a'*64},'request':{'path':'/fixed/original-request.json','sha256':'b'*64},'handoff':{'path':'/fixed/original-handoff.json','sha256':'c'*64},'root_files':{name:'d'*64 for name in ['plan_sha256','COMPLETE',*[role+'.rc' for role in c.ROLES]]}}));l['original_arm_proof']={'path':str(proof),'sha256':c.sha(proof.read_bytes())}
 return p,l

def test_preflight_main_is_completed_only_and_six_originals_one_explicit_guard(tmp_path,monkeypatch):
 p,l=sample(tmp_path);events=[]
 monkeypatch.setattr(r,'collector_guard',lambda *args:events.append(('prearmed','collector',l['prearmed_collector']['guard'])))
 monkeypatch.setattr(r,'pending_guard',lambda c,p,o,role:events.append(('pending',role,None)))
 o=SimpleNamespace(completed=lambda role,i:events.append(('completed',role,i)),original=lambda role,i:events.append(('original',role,i)))
 before=(tmp_path/'owned-main.checkpoint.json').read_bytes();ss,paths=r.states(c,p,l,o,tmp_path)
 assert tuple(ss)==r.REMAINING and tuple(paths)==r.REMAINING
 assert [v[1] for v in events if v[0]=='original']==[role for role in r.REMAINING if role!='collector']
 assert [v[1] for v in events if v[0]=='prearmed']==['collector']
 assert events[0]==('completed','main',l['main']['new_identity'])
 assert (tmp_path/'owned-main.checkpoint.json').read_bytes()==before
 ss['api']['phase']='ARMED';c.save(paths['api'],ss['api'])
 with pytest.raises(c.Stop,match='SHA_DRIFT'):r.states(c,p,l,o,tmp_path)

def test_validate_truthful_main_new_identity_without_replacing_checkpoint(tmp_path,monkeypatch):
 p,l=sample(tmp_path);observed=[]
 monkeypatch.setattr(c,'handoff',lambda p,h,reverse:observed.append(h))
 monkeypatch.setattr(r,'original_arm_proof',lambda *args:None)
 h=r.validate(c,p,l)
 assert observed[0]['identities']['main']==l['main']['new_identity']
 assert observed[0]['role_observations']['main']['disposition']=='COMPLETED'
 assert observed[0]['role_observations']['collector']=={'phase':'WAITING_ROOT_ACK','current_identity':l['prearmed_collector']['guard'],'disposition':'IN_PROGRESS'}
 assert h['recovery_root_ack_dir']==l['root_ack_dir']
 l['identities']['main']=l['main']['new_identity']
 with pytest.raises(c.Stop,match='EXACT_REMAINING_SEVEN'):r.validate(c,p,l)

def test_new_helper_watch_only_with_one_api_rollback_and_zero_original_rearms(tmp_path):
 p,l=sample(tmp_path);script=r.helper(c,p,l,{'pid':123,'ps_sha256':'f'*64},tmp_path/'request.json','1'*64,tmp_path/'finish.json')
 assert script.count('/bin/launchctl debug ')==1
 assert c.OLD['main'] not in script and c.NEW['main'] not in script
 for role in r.REMAINING:assert '/bin/launchctl debug gui/501/'+c.OLD[role]+' --program /bin/sleep -- 604800' not in script
 assert '/bin/launchctl debug gui/501/'+c.OLD['collector'] not in script
 assert 'PREARMED_GUARD_VERIFIED_NO_ARM' in script and '/collector.rc' not in script.split('umask 022')[1]
 assert 'ORIGINAL8_ACK_AND_CURRENT_PENDING_GUARDS_VERIFIED' in script
 for role in r.REMAINING:assert '/'+role+'.rc' not in script.split('umask 022')[1]
 assert '/v4-retirement-nextspawn-'+l['operation_id']+'/collector.rc' in script
 assert '/bin/launchctl debug gui/501/'+c.NEW['api']+' --program /bin/sleep -- 604800' in script
 assert l['nonce'] in script and 'heartbeat' in script and 'helper_ps_sha256' in script
 for forbidden in ('sudo','osascript','kill ','bootout','bootstrap',' disable ',' enable ','python','rm '):assert forbidden not in script
 f=tmp_path/'helper.sh';f.write_text(script)
 assert subprocess.run(['/bin/sh','-n',str(f)],capture_output=True).returncode==0

def test_loop_dispatches_exactly_remaining_seven_never_main(tmp_path,monkeypatch):
 seen=[]
 class Recipe:
  def __init__(self,*args):pass
  def step(self,role):seen.append(role);return True
 monkeypatch.setattr(c,'Recipe',Recipe)
 r.continue_roles(c,{}, {},object(),dict.fromkeys(r.REMAINING,{}),dict.fromkeys(r.REMAINING,tmp_path/'unused'))
 assert seen==list(r.REMAINING) and 'main' not in seen

def test_real_recipe_30_seconds_failure_uses_new_lease_ack_and_actual_inverse(tmp_path,monkeypatch):
 now=[100.0];monkeypatch.setattr(c.time,'time',lambda:now[0]);monkeypatch.setattr(c,'HERE',tmp_path)
 root=tmp_path/'fresh-lease';(root/'rollback-api').mkdir(parents=True);(root/'rollback-api/COMPLETE').write_text('complete')
 oldroot=tmp_path/'expired-ack'
 p={'operations':[{'role':'api','old_disabled_before':False,'new_disabled_before':False}]}
 o=base.Fake();o.new_loaded=True;o.current={'pid':21,'ps_sha256':'c'*64,'ps_text':'failed-new'};o.healthy=False
 s={'phase':'HEALTH','health_started_epoch':100,'new':o.current,'original_identity':o.ident};path=tmp_path/'owned-api.checkpoint.json';c.save(path,s)
 bo=base.Fake(True);bo.ident=o.current;bo.current=o.current
 monkeypatch.setattr(c,'Live',lambda *a:bo)
 acknowledged=[];monkeypatch.setattr(c,'rollback_ack',lambda p,h:acknowledged.append(h['root_ack_dir']))
 def advance(_):
  now[0]+=1
  if bo.current is None and bo.loaded:bo.current=bo.guard_i
 monkeypatch.setattr(c.time,'sleep',advance)
 h={'operation_id':'d'*32,'expires_epoch':400,'root_ack_dir':str(oldroot),'recovery_root_ack_dir':str(root),'identities':{'api':o.ident}}
 with pytest.raises(c.Stop,match='API_HEALTH_FAILED_ROLLED_BACK_BATCH_STOPPED'):r.continue_roles(c,p,h,o,{'api':s},{'api':path})
 assert now[0]>=130 and s['phase']=='ROLLED_BACK' and acknowledged==[str(root),str(root)]
 assert bo.events.count('TERM')==1 and bo.events.count('BOOTOUT_SLEEP')==1
 assert bo.disabled_values[c.NEW['api']] is True and bo.disabled_values[c.OLD['api']] is False
 assert not oldroot.exists()

def test_unknown_outcome_propagates_no_retry_or_rollback(tmp_path,monkeypatch):
 seen=[]
 class Unknown:
  def __init__(self,*args):pass
  def step(self,role):seen.append(role);raise c.Stop('BOOTSTRAP_OUTCOME_UNKNOWN_NO_REPEAT')
 monkeypatch.setattr(c,'Recipe',Unknown);monkeypatch.setattr(c,'auto_api_rollback',lambda *a:pytest.fail('unexpected rollback'))
 with pytest.raises(c.Stop,match='BOOTSTRAP_OUTCOME_UNKNOWN_NO_REPEAT'):r.continue_roles(c,{}, {},object(),{'api':{}},{'api':tmp_path/'unused'})
 assert seen==['api']

@pytest.mark.parametrize('now,heartbeat,identity,reason',[
 (105,100,{'ps_sha256':'a'*64},'LEASE_NOT_ALIVE'),
 (401,400,{'ps_sha256':'a'*64},'LEASE_NOT_ALIVE'),
 (100,100,None,'LEASE_HELPER_EXITED'),
 (100,100,{'ps_sha256':'b'*64},'LEASE_HELPER_EXITED'),
])
def test_stale_expired_or_dead_helper_cannot_authorize_lifecycle(monkeypatch,now,heartbeat,identity,reason):
 monkeypatch.setattr(r.time,'time',lambda:now)
 values={'heartbeat':str(heartbeat),'helper_pid':'123','helper_ps_sha256':'a'*64}
 with pytest.raises(c.Stop,match=reason):r.lease_alive(c,{'observed_epoch':100,'expires_epoch':400},SimpleNamespace(identity=lambda pid:identity),values.__getitem__)

def test_live_fresh_helper_lease_is_accepted(monkeypatch):
 monkeypatch.setattr(r.time,'time',lambda:103)
 values={'heartbeat':'100','helper_pid':'123','helper_ps_sha256':'a'*64}
 r.lease_alive(c,{'observed_epoch':100,'expires_epoch':400},SimpleNamespace(identity=lambda pid:{'ps_sha256':'a'*64}),values.__getitem__)

def test_prearmed_collector_reconciliation_preserves_none_identity_and_never_kicks(tmp_path,monkeypatch):
 p,l=sample(tmp_path);path=tmp_path/'owned-collector.checkpoint.json';s=json.loads(path.read_text());o=base.Fake();o.current=o.guard_i
 monkeypatch.setattr(r,'collector_guard',lambda *args:o.guard_i)
 h={'identities':{'collector':None}};ss={'collector':s};paths={'collector':path}
 r.reconcile_collector(c,p,h,l,o,ss,paths,tmp_path)
 assert s['phase']=='AUX_WAIT_IDLE' and s['original_identity'] is None
 assert s['operation_id']==l['operation_id'] and s['plan_sha256']==l['plan_sha256']
 record=json.loads((tmp_path/'collector-prearmed-reconciliation.json').read_text())
 assert record['original_identity'] is None and record['checkpoint_before_sha256']==l['checkpoint_sha256']['collector']
 recipe=c.Recipe(p,h,o,s,path);base.finish(recipe,'collector')
 assert s['phase']=='DONE' and s['original_identity'] is None
 assert o.events.count('BOOTOUT_SLEEP')==1 and not set(o.events)&{'TERM','KICK_NO_K'}
 with pytest.raises(c.Stop,match='COLLECTOR_RECONCILE_SCOPE'):r.reconcile_collector(c,p,h,l,o,ss,paths,tmp_path)

@pytest.mark.parametrize('changed',['guard','cwd'])
def test_exact_guard_identity_and_cwd_required_before_reconciliation(tmp_path,monkeypatch,changed):
 p,l=sample(tmp_path);row=c.row(p,'collector');file=tmp_path/'collector.plist';file.write_bytes(b'original collector')
 row.update(plist=str(file),before_sha256=c.sha(file.read_bytes()),plist_metadata=c.metadata.snapshot(file),old_working_directory='/expected/old/app')
 observed=l['prearmed_collector']['guard'];actual={**observed,'pid':13} if changed=='guard' else observed
 o=SimpleNamespace(disabled=lambda label:False,service_label=lambda label:{'loaded':False},guard=lambda role,old:actual,cmd=lambda *args:SimpleNamespace(stdout='p12\nfcwd\nn/wrong/cwd\n'))
 with pytest.raises(c.Stop,match='COLLECTOR_PREARMED_GUARD_DRIFT' if changed=='guard' else 'COLLECTOR_GUARD_CWD'):r.collector_guard(c,p,l,o)

def pending_fixture(tmp_path):
 import plistlib
 file=tmp_path/'old.plist';definition={'ProgramArguments':['/usr/bin/env','PYTHONNOUSERSITE=1','/fixed/python','-m','old.api'],'WorkingDirectory':'/fixed/old/app','EnvironmentVariables':{'OWNER':'original'}};file.write_bytes(plistlib.dumps(definition))
 p={'operations':[{'role':'api','plist':str(file),'before_file':str(file),'before_sha256':c.sha(file.read_bytes()),'plist_metadata':c.metadata.snapshot(file)}]}
 text='\tpath = '+str(file)+'\n\tprogram = /usr/bin/env\n\t\t+ /bin/sleep\n\targuments = {\n'+''.join('\t\t'+v+'\n' for v in definition['ProgramArguments'])+'\t}\n\tcontroller-supplied arguments = {\n\t\t/bin/sleep\n\t\t604800\n\t}\n\tworking directory = /fixed/old/app\n\tenvironment = {\n\t\tOWNER => original\n\t}\n'
 return p,text

def test_actual_host_pending_print_requires_exact_program_arguments_and_binding(tmp_path):
 p,text=pending_fixture(tmp_path)
 r.pending_guard(c,p,SimpleNamespace(service=lambda role:{'text':text}),'api')

@pytest.mark.parametrize('old,new',[
 ('\t\t+ /bin/sleep\n',''),
 ('\t\t+ /bin/sleep\n','\t\t+ /bin/sh\n'),
 ('\tprogram = /usr/bin/env','\tprogram = /wrong/program'),
 ('\t\t604800\n','\t\t5\n'),
 ('\t\t/fixed/python\n','\t\t/wrong/python\n'),
 ('OWNER => original','OWNER => changed'),
 ('working directory = /fixed/old/app','working directory = /wrong/cwd'),
])
def test_missing_extra_or_different_pending_print_fails_closed(tmp_path,old,new):
 p,text=pending_fixture(tmp_path)
 with pytest.raises(c.Stop):r.pending_guard(c,p,SimpleNamespace(service=lambda role:{'text':text.replace(old,new)}),'api')

def test_error37_does_not_prove_pending_arm(tmp_path):
 p,_=pending_fixture(tmp_path)
 with pytest.raises(c.Stop,match='ORIGINAL_PENDING_PROGRAM_NOT_VERIFIED'):r.pending_guard(c,p,SimpleNamespace(service=lambda role:{'text':'Configuration failed: 37: Operation already in progress'}),'api')

def test_original_arm_proof_requires_exact_private_capsule_and_sha(tmp_path):
 p,l=sample(tmp_path)
 with pytest.raises(c.Stop,match='ORIGINAL_ARM_PROOF_SCOPE'):r.original_arm_proof(c,p,l)
