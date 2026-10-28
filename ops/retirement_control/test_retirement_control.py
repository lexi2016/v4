"""Fake lifecycle only: no launchctl, service, provider or authoritative-data calls."""
import json
from pathlib import Path
import pytest
import retirement_control as c

class Fake:
 def __init__(self,reverse=False):
  self.reverse=reverse;self.events=[];self.ident={'pid':11,'ps_sha256':'a'*64,'ps_text':'original'};self.current=self.ident;self.loaded=True;self.new_loaded=False;self.guard_i={'pid':12,'ps_sha256':'b'*64,'ps_text':'/bin/sleep 604800'};self.disabled_values={v:False for v in set(c.OLD.values())|set(c.NEW.values())};self.healthy=True;self.children={};self.persisted_old=True
 def protection(self,h):self.events.append('protect')
 def ack(self,h):self.events.append('ack')
 def original(self,role,i):assert self.current==i;self.events.append('original')
 def pdf_boundary(self):self.events.append('pdf')
 def initial_main_idle(self,i):self.events.append('idle')
 def descendants(self,pid):return self.children.copy()
 def term(self,role,i):assert role in c.CONTINUOUS;assert self.current==i;self.events.append('TERM');self.current=None;self.loaded=True
 def identity(self,pid):return self.current if self.current and self.current['pid']==pid else None
 def service(self,role):return {'loaded':self.loaded,'pid':self.current['pid'] if self.current else None}
 def no_old_root_processes(self,role):self.events.append('old-absent')
 def guard(self,role,old):
  if self.current!=self.guard_i:raise c.Stop('UNEXPECTED_REPLACEMENT_NO_SIGNAL')
  return self.guard_i
 def kick_guard(self,role):assert role not in c.CONTINUOUS or (role=='api' and self.reverse and getattr(self,'allow_empty_api',False));self.events.append('KICK_NO_K');self.current=self.guard_i
 def bootout_guard(self,role,g,old):assert g==self.current==self.guard_i;assert self.identity((old or {}).get('pid')) is None;self.events.append('BOOTOUT_SLEEP');self.loaded=False;self.current=None
 def absent(self,role):assert not self.loaded and not self.new_loaded
 def cas(self,role):self.absent(role);assert self.persisted_old;self.events.append('CAS_INVERSE' if self.reverse else 'CAS_NO_OVERWRITE')
 def cas_confirmed(self,role):self.events.append('confirm-cas')
 def disable_origin(self,role):self.absent(role);self.events.append('DISABLE_UNLOADED');self.disabled_values[c.labels(role,self.reverse)[0]]=True
 def disabled(self,label):return self.disabled_values[label]
 def enable_destination(self,role):self.absent(role);self.events.append('ENABLE_DEST');self.disabled_values[c.labels(role,self.reverse)[1]]=False
 def bootstrap(self,role):self.absent(role);self.events.append('BOOTSTRAP');self.new_loaded=True;self.current={'pid':21,'ps_sha256':'c'*64,'ps_text':'replacement'}
 def new(self,role):assert self.new_loaded;return self.current
 def completed(self,role,expected):assert expected==self.current
 def health(self,deadline=None):self.events.append('HEALTH');return self.healthy

def setup(tmp_path,monkeypatch,role='main',reverse=False):
 monkeypatch.setattr(c,'handoff',lambda *a:True)
 p={'operations':[{'role':role,'old_disabled_before':False,'new_disabled_before':False}]};o=Fake(reverse);h={'identities':{role:o.ident}};s={'phase':'WAITING_ROOT_ACK','original_identity':o.ident if role in c.CONTINUOUS else None,'children':{}}
 if role not in c.CONTINUOUS:o.current=None
 return c.Recipe(p,h,o,s,tmp_path/'checkpoint.json'),o

def finish(recipe,role):
 for _ in range(40):
  if recipe.s['phase']=='DRAINING' and recipe.o.current is None:recipe.o.current=recipe.o.guard_i
  if recipe.step(role):return
 pytest.fail('not completed')

@pytest.mark.parametrize('role',['main','api'])
def test_renamed_drains_then_unloads_guard_disables_old_and_starts_new(tmp_path,monkeypatch,role):
 r,o=setup(tmp_path,monkeypatch,role);finish(r,role)
 events=o.events
 assert events.count('TERM')==1
 assert events.index('TERM')<events.index('BOOTOUT_SLEEP')<events.index('CAS_NO_OVERWRITE')<events.index('DISABLE_UNLOADED')<events.index('BOOTSTRAP')
 assert o.disabled_values[c.OLD[role]] is True and o.disabled_values[c.NEW[role]] is False
 assert o.persisted_old and r.s['phase']=='DONE'

@pytest.mark.parametrize('role',['collector','stage','precapture','stage-deadline','review-daily','us'])
def test_auxiliary_uses_no_kick_kill_and_does_not_signal_healthy_job(tmp_path,monkeypatch,role):
 r,o=setup(tmp_path,monkeypatch,role)
 r.step(role);r.step(role)
 o.current=o.ident
 assert r.step(role) is False and r.s['phase']=='AUX_WAIT_IDLE'
 assert 'TERM' not in o.events and 'KICK_NO_K' not in o.events
 o.current=None
 finish(r,role)
 assert o.events.count('KICK_NO_K')==1 and 'TERM' not in o.events
 assert o.events.count('BOOTOUT_SLEEP')==1


def test_child_keeps_drain_pending_without_second_term_or_busy_bootout(tmp_path,monkeypatch):
 r,o=setup(tmp_path,monkeypatch);r.step('main');r.step('main')
 # A live original is observed, then exits. No kill/second TERM.
 o.current=o.ident;r.step('main');assert r.s['phase']=='DRAINING'
 assert o.events.count('TERM')==1 and 'BOOTOUT_SLEEP' not in o.events
 o.current=o.guard_i;finish(r,'main');assert o.events.count('TERM')==1

@pytest.mark.parametrize('phase',['TERM_INTENT','BOOTSTRAP_INTENT','AUX_KICK_INTENT'])
def test_unknown_intents_stop_without_repeating_mutation(tmp_path,monkeypatch,phase):
 r,o=setup(tmp_path,monkeypatch);r.s['phase']=phase
 with pytest.raises(c.Stop):r.step('main')
 assert not any(v in o.events for v in ['TERM','BOOTSTRAP','KICK_NO_K','BOOTOUT_SLEEP'])


def test_inverse_preserves_original_bytes_and_restores_old_disabled_value(tmp_path,monkeypatch):
 r,o=setup(tmp_path,monkeypatch,'api',True);o.disabled_values[c.OLD['api']]=True
 finish(r,'api')
 assert o.events.count('CAS_INVERSE')==1 and o.persisted_old
 assert o.disabled_values[c.OLD['api']] is False and o.disabled_values[c.NEW['api']] is True


def test_api_health_30_seconds_fails_then_guarded_inverse_is_executable(tmp_path,monkeypatch):
 now=[100.0];monkeypatch.setattr(c.time,'time',lambda:now[0]);r,o=setup(tmp_path,monkeypatch,'api');o.healthy=False
 while r.s['phase']!='HEALTH':
  if r.s['phase']=='DRAINING' and o.current is None:o.current=o.guard_i
  r.step('api')
 assert r.step('api') is False
 now[0]=129.999;assert r.step('api') is False
 now[0]=130
 with pytest.raises(c.Stop,match='API_HEALTH_FAILED_REQUIRES_GUARDED_ROLLBACK'):r.step('api')
 assert r.s['phase']=='HEALTH_FAILED' and o.events.count('TERM')==1
 # The fixed admin acknowledgement is supplied at the boundary; the inverse
 # recipe then drains the exact replacement once, preserving old preimage.
 monkeypatch.setattr(c,'rollback_ack',lambda *a:None)
 back,bo=setup(tmp_path/'back',monkeypatch,'api',True);(tmp_path/'back').mkdir();back.s['phase']='ARMED';back.h['api_health_rollback']=True
 finish(back,'api')
 assert bo.events.count('TERM')==1 and bo.events.count('BOOTOUT_SLEEP')==1
 assert bo.disabled_values[c.OLD['api']] is False


def test_fixed_root_helper_has_no_lifecycle_or_unbounded_capability():
 p={'guard_program_sha256':'a'*64,'operations':[{'role':r,'plist':'/Users/lexi/Library/LaunchAgents/'+c.OLD[r]+'.plist','new_plist':'/Users/lexi/Library/LaunchAgents/'+c.NEW[r]+'.plist','before_sha256':'b'*64,'after_sha256':'c'*64} for r in c.ROLES]}
 h={'operation_id':'d'*32,'root_ack_dir':'/private/var/tmp/v4-retirement-nextspawn-'+'d'*32,'expires_epoch':999,'reverse':False,'identities':{r:None for r in c.ROLES}}
 script=c.root_helper(p,h,{'pid':123,'ps_sha256':'e'*64},'f'*64)
 assert script.count('/bin/launchctl debug ')==9
 assert '--program /bin/sleep -- 604800' in script
 for forbidden in ('sudo','osascript','kill ','bootout','bootstrap',' disable ',' enable ','python','rm '):assert forbidden not in script
 assert 'case "$pid"' in script and 'COORDINATOR' not in script


def test_actual_auto_api_rollback_wiring_after_failed_health(tmp_path,monkeypatch):
 monkeypatch.setattr(c,'HERE',tmp_path);monkeypatch.setattr(c,'rollback_ack',lambda *a:None)
 root=tmp_path/'root-ack';(root/'rollback-api').mkdir(parents=True);(root/'rollback-api/COMPLETE').write_text('complete')
 p={'operations':[{'role':'api','old_disabled_before':False,'new_disabled_before':False}]};o=Fake();o.new_loaded=True;o.current={'pid':21,'ps_sha256':'c'*64,'ps_text':'replacement'}
 state={'phase':'HEALTH_FAILED','failure':'API_HEALTH_30_SECONDS','new':o.current};path=tmp_path/'owned-api.checkpoint.json';c.save(path,state)
 bo=Fake(True);bo.ident=o.current;bo.current=o.current
 monkeypatch.setattr(c,'Live',lambda *a:bo)
 def advance(_):
  if bo.current is None and bo.loaded:bo.current=bo.guard_i
 monkeypatch.setattr(c.time,'sleep',advance)
 h={'operation_id':'d'*32,'expires_epoch':c.time.time()+60,'root_ack_dir':str(root),'identities':{'api':o.current}}
 result=c.auto_api_rollback(p,h,o,state,path)
 assert result['phase']=='DONE' and state['phase']=='ROLLED_BACK'
 assert bo.events.count('TERM')==1 and bo.events.count('BOOTOUT_SLEEP')==1
 assert bo.disabled_values[c.NEW['api']] is True and bo.disabled_values[c.OLD['api']] is False
 assert json.loads(path.read_text())['phase']=='ROLLED_BACK'


def test_real_rename_cas_retains_original_and_refuses_overwrite(tmp_path,monkeypatch):
 before=tmp_path/'old.plist';after=tmp_path/'new.plist';before.write_bytes(b'original');meta=c.metadata.snapshot(before);definition=tmp_path/'after-file';definition.write_bytes(b'new exact')
 x={'role':'api','plist':str(before),'new_plist':str(after),'before_file':str(before),'after_file':str(definition),'before_sha256':c.sha(b'original'),'after_sha256':c.sha(b'new exact'),'plist_metadata':meta}
 live=c.Live({'operations':[x]});monkeypatch.setattr(live,'absent',lambda _:None)
 live.cas('api')
 assert before.read_bytes()==b'original' and after.read_bytes()==b'new exact'
 assert c.metadata.snapshot(after)==meta
 with pytest.raises(c.Stop,match='DESTINATION_EXISTS_NO_OVERWRITE'):live.cas('api')
 reverse=c.Live({'operations':[x]},True);monkeypatch.setattr(reverse,'absent',lambda _:None);reverse.cas('api')
 assert before.read_bytes()==b'original' and after.read_bytes()==b'new exact'


def test_real_health_contract_requires_runtime_identity_and_release(monkeypatch):
 import io,urllib.request
 responses=[{'status':'ok'},{'runtime_identity':{'status':'MANIFEST_EXECUTION_FILES_VERIFIED','release_id':'new-api'}},{'status':'VERIFIED','api_release_id':'new-api'}]
 urls=[]
 def get(url,timeout):urls.append(url);return io.BytesIO(json.dumps(responses.pop(0)).encode())
 monkeypatch.setattr(urllib.request,'urlopen',get)
 live=c.Live({'operations':[{'role':'api','new_release_id':'new-api'}]})
 assert live.health() is True
 assert urls==['http://127.0.0.1:8873/healthz','http://127.0.0.1:8873/api/v1/runs/date-list','http://127.0.0.1:8873/api/v4/runtime-graph/frontend-build']


def test_inverse_health_matches_exact_known_unbound_baseline(monkeypatch):
 import io,urllib.request
 identity={'application':'V4','status':'CANNOT_CONFIRM','release_id':'','process_status':'CANNOT_CONFIRM'}
 frontend={'status':'CANNOT_CONFIRM','reason':'API_RELEASE_IDENTITY_UNBOUND'}
 responses=[{'status':'ok'},{'runtime_identity':identity},frontend];urls=[]
 def get(url,timeout):urls.append(url);return io.BytesIO(json.dumps(responses.pop(0)).encode())
 monkeypatch.setattr(urllib.request,'urlopen',get)
 live=c.Live({'operations':[{'role':'api'}],'api_inverse_baseline':{'health':{'status':'ok'},'runtime_identity':identity,'frontend_build':frontend}},True)
 assert live.health() is True and urls[-1].endswith('/api/v3/runtime-graph/frontend-build')


def test_resume_completed_roles_does_not_repeat_term(tmp_path):
 p={};o=Fake();o.new_loaded=True;o.current={'pid':21,'ps_sha256':'c'*64,'ps_text':'replacement'}
 h={'operation_id':'d'*32,'identities':{},'role_observations':{}}
 for role in c.ROLES:
  old={'pid':11,'ps_sha256':'a'*64,'ps_text':'original'};h['identities'][role]=old
  state={'schema':'v4.retirement.role.v1','operation_id':h['operation_id'],'plan_sha256':c.sha(c.canonical(p)),'original_identity':old,'phase':'DONE','new':o.current}
  c.save(tmp_path/('owned-'+role+'.checkpoint.json'),state);h['role_observations'][role]={'phase':'DONE','current_identity':o.current,'disposition':'COMPLETED'}
 states,paths=c.resume_states(p,h,o,tmp_path)
 assert len(states)==len(c.ROLES) and 'TERM' not in o.events
 h['role_observations']['api']['current_identity']=None
 with pytest.raises(c.Stop,match='COMPLETED_OBSERVATION'):c.resume_states(p,h,o,tmp_path)


def test_root_request_rejects_shell_injection_in_process_identity():
 h={'operation_id':'d'*32,'expires_epoch':999,'identities':{}}
 with pytest.raises(c.Stop,match='ROOT_REQUEST_IDENTITY'):
  c.root_helper({},h,{'pid':'1;bad','ps_sha256':'e'*64},'f'*64)


def test_collector_actual_once_trigger_is_not_a_continuous_term_target():
 assert c.CONTINUOUS=={'main','api'}
 evidence=Path(__file__).resolve().parent.parent/'PLIST_PLAN.json'
 if not evidence.exists():pytest.skip('private actual-trigger evidence is excluded from public source')
 plan=json.loads(evidence.read_text())
 x=next(x for x in plan if x['owner']=='collector')
 import plistlib
 before=plistlib.loads(Path(x['source_plist']).read_bytes())
 assert before.get('KeepAlive') is not True and before.get('QueueDirectories')


def test_calendar_handoff_blocks_stage_trigger_window(tmp_path,monkeypatch):
 from datetime import datetime
 from zoneinfo import ZoneInfo
 import plistlib
 operations=[]
 for role in ['stage','precapture','stage-deadline','review-daily','us']:
  path=tmp_path/(role+'.plist');path.write_bytes(plistlib.dumps({'StartCalendarInterval':[{'Hour':9,'Minute':25}] if role=='stage' else []}));operations.append({'role':role,'before_file':str(path),'before_sha256':c.sha(path.read_bytes())})
 p={'operations':operations};epoch=datetime(2026,10,28,9,20,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp();monkeypatch.setattr(c.time,'time',lambda:epoch)
 h={'operation_id':'d'*32,'plan_sha256':c.sha(c.canonical(p)),'reverse':False,'root_ack_dir':'/private/var/tmp/v4-retirement-nextspawn-'+'d'*32,'observed_epoch':epoch,'expires_epoch':epoch+240}
 with pytest.raises(c.Stop,match='CALENDAR_WINDOW_CONFLICT:stage'):c.handoff(p,h)


def test_api_health_failure_with_no_pid_uses_guard_kick_without_signal(tmp_path,monkeypatch):
 monkeypatch.setattr(c,'HERE',tmp_path);monkeypatch.setattr(c,'rollback_ack',lambda *a:None)
 root=tmp_path/'root';(root/'rollback-api').mkdir(parents=True);(root/'rollback-api/COMPLETE').write_text('complete')
 p={'operations':[{'role':'api','old_disabled_before':False,'new_disabled_before':False}]};o=Fake();o.new_loaded=True;o.current=None
 state={'phase':'HEALTH_FAILED','failure':'API_HEALTH_30_SECONDS','new':None};path=tmp_path/'owned-api.checkpoint.json';c.save(path,state)
 bo=Fake(True);bo.current=None;bo.ident=None
 monkeypatch.setattr(c,'Live',lambda *a:bo);monkeypatch.setattr(c.time,'sleep',lambda _:None)
 h={'operation_id':'d'*32,'expires_epoch':c.time.time()+60,'root_ack_dir':str(root),'identities':{'api':None}}
 result=c.auto_api_rollback(p,h,o,state,path)
 assert result['phase']=='DONE' and state['phase']=='ROLLED_BACK'
 assert 'TERM' not in bo.events and bo.events.count('KICK_NO_K')==1 and bo.events.count('BOOTOUT_SLEEP')==1
 request=json.loads((tmp_path/('owned-api-rollback-'+'d'*32+'.json')).read_text())
 assert request['pid']==0 and request['ps_sha256']=='NONE'


@pytest.mark.parametrize('token,want',[('disabled',True),('enabled',False),('true',True),('false',False)])
def test_disabled_readback_actual_macos_tokens(token,want):
 from types import SimpleNamespace
 o=c.Live({})
 o.cmd=lambda *a:SimpleNamespace(stdout='\n\tdisabled services = {\n\t\t"com.lexi.v35.scheduler" => '+token+'\n\t}\n')
 assert o.disabled(c.OLD['main']) is want

@pytest.mark.parametrize('text',[
 'disabled services = {\n"com.lexi.v35.scheduler" => UNKNOWN\n}',
 'disabled services = {\n"com.lexi.v35.scheduler" => disabled\n"com.lexi.v35.scheduler" => enabled\n}',
 'not a disabled services map',
 'disabled services = {\n"com.lexi.v35.scheduler" => disabled',
])
def test_disabled_readback_unknown_fails_closed(text):
 from types import SimpleNamespace
 o=c.Live({});o.cmd=lambda *a:SimpleNamespace(stdout=text)
 with pytest.raises(c.Stop):o.disabled(c.OLD['main'])


def test_disabled_absent_valid_map_is_default_enabled():
 from types import SimpleNamespace
 o=c.Live({});o.cmd=lambda *a:SimpleNamespace(stdout='disabled services = {\n"other" => disabled\n}\n')
 assert o.disabled(c.NEW['main']) is False


def test_disabled_intent_main_resume_uses_actual_parser_without_replaying_prior_mutations(tmp_path,monkeypatch):
 from types import SimpleNamespace
 r,o=setup(tmp_path,monkeypatch)
 r.s.update(phase='OLD_DISABLE_INTENT',term_sent=True,guard=o.guard_i)
 original=r.s['original_identity'].copy()
 o.current=None;o.loaded=False;o.disabled_values[c.OLD['main']]=True
 live=c.Live({})
 live.cmd=lambda *a:SimpleNamespace(stdout='disabled services = {\n"com.lexi.v35.scheduler" => disabled\n}\n')
 o.disabled=live.disabled
 finish(r,'main')
 assert r.s['phase']=='DONE' and r.s['original_identity']==original and r.s['term_sent'] is True
 assert o.events.count('BOOTSTRAP')==1
 assert not set(o.events)&{'TERM','DISABLE_UNLOADED','CAS_NO_OVERWRITE','BOOTOUT_SLEEP','KICK_NO_K'}


@pytest.mark.parametrize('reverse',[False,True])
def test_health_slow_catalog_above_2_9_seconds_uses_shared_budget(monkeypatch,reverse):
 import io,urllib.request
 now=[100.0];seen=[]
 monkeypatch.setattr(c.time,'time',lambda:now[0])
 identity={'status':'MANIFEST_EXECUTION_FILES_VERIFIED','release_id':'new-api'}
 frontend={'status':'VERIFIED','api_release_id':'new-api'}
 if reverse:identity={'application':'V4','status':'CANNOT_CONFIRM','release_id':'','process_status':'CANNOT_CONFIRM'};frontend={'status':'CANNOT_CONFIRM','reason':'API_RELEASE_IDENTITY_UNBOUND'}
 values=[{'status':'ok'},{'runtime_identity':identity},frontend]
 def get(url,timeout):
  delay=2.95 if 'date-list' in url else .01
  seen.append((url,timeout,now[0]))
  if timeout<delay:now[0]+=timeout;raise TimeoutError('legitimate2.95secondcatalog')
  now[0]+=delay;return io.BytesIO(json.dumps(values.pop(0)).encode())
 monkeypatch.setattr(urllib.request,'urlopen',get)
 p={'operations':[{'role':'api','new_release_id':'new-api'}],'api_inverse_baseline':{'health':{'status':'ok'},'runtime_identity':identity,'frontend_build':frontend}}
 assert c.Live(p,reverse).health(130) is True
 assert len(seen)==3 and now[0]<130
 assert all(0<timeout<=130-start for _,timeout,start in seen)


def test_health_cannot_extend_remaining_global_deadline(monkeypatch):
 import io,urllib.request
 now=[129.5];seen=[];monkeypatch.setattr(c.time,'time',lambda:now[0])
 def get(url,timeout):
  seen.append(timeout);now[0]+=timeout;raise TimeoutError('deadline exhausted')
 monkeypatch.setattr(urllib.request,'urlopen',get)
 assert c.Live({'operations':[{'role':'api','new_release_id':'new'}]}).health(130) is False
 assert seen==[.5] and now[0]==130


@pytest.mark.parametrize('field',['identity','frontend','health'])
def test_health_slow_catalog_does_not_relax_body_identity_or_status(monkeypatch,field):
 import io,urllib.request
 now=[100.0];monkeypatch.setattr(c.time,'time',lambda:now[0])
 values=[{'status':'ok'},{'runtime_identity':{'status':'MANIFEST_EXECUTION_FILES_VERIFIED','release_id':'new-api'}},{'status':'VERIFIED','api_release_id':'new-api'}]
 if field=='identity':values[1]['runtime_identity']['release_id']='wrong'
 elif field=='frontend':values[2]['status']='CANNOT_CONFIRM'
 else:values[0]['status']='unhealthy'
 def get(url,timeout):now[0]+=2.95 if 'date-list' in url else .01;return io.BytesIO(json.dumps(values.pop(0)).encode())
 monkeypatch.setattr(urllib.request,'urlopen',get)
 assert c.Live({'operations':[{'role':'api','new_release_id':'new-api'}]}).health(130) is False
