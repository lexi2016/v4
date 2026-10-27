from pathlib import Path
from contextlib import contextmanager
from datetime import datetime as RealDatetime
from types import SimpleNamespace
import json,plistlib
import pytest
import controller as c

class Log:
 def __init__(self):self.events=[];self.commands=[];self.action_counts={}
 def record(self,event,**kw):self.events.append((event,kw))
 def command(self,args):
  self.commands.append(args);self.action_counts[tuple(args)]=self.action_counts.get(tuple(args),0)+1
  return SimpleNamespace(returncode=0)

def rows(tmp_path):
 result=[]
 for name,label in c.LABELS.items():
  p=tmp_path/(name+'.plist');p.write_text('before-'+name)
  result.append({'component':name,'label':label,'plist':str(p),'before_sha256':c.sha(p),'after_sha256':'after-'+name})
 return result

def base(tmp_path):
 x=c.Capsule.__new__(c.Capsule);x.p={'operations':rows(tmp_path),'minimum_switch_margin_seconds':300,'protected_deploy_windows':[['0924','0927']]}
 x.op=SimpleNamespace(op=lambda plan,name:next(r for r in plan['operations'] if r['component']==name))
 x.j=Log();x.attempted_service_actions=set();x.action_progress={k:{} for k in c.LABELS};x.graph_disabled_by_this_activation=False;x.forward_first_action_pending=False;x.graph_fd=42
 return x

def bindings():
 return {name:{'kind':'LOADED','file_version':'OLD','loaded_version':'OLD','pid':0 if name=='collector' else 11 if name=='main' else 12,'identity':None if name=='collector' else {'pid':11 if name=='main' else 12,'start':'original'},'plist_sha256':'before-'+name} for name in c.LABELS}

def recovery_fixture(tmp_path):
 x=base(tmp_path);state=bindings();x.observe_service_binding=lambda name:state[name];x.graph_disabled=lambda:False
 graphroot=tmp_path/'state';snap=graphroot/'runtime_graph/v4/snapshot.json';snap.parent.mkdir(parents=True);snap.write_text('{"original":true}')
 cfg=tmp_path/'old-config.json';cfg.write_text(json.dumps({'graph_root':str(graphroot)}));cfgsha=c.sha(cfg)
 oldplan={'config_path':str(cfg),'config_target':str(cfg),'config_sha256':cfgsha};p=tmp_path/'old-plan.json';p.write_text(json.dumps(oldplan));x.p['old_graph_plan']=str(p)
 x.op.verify_release=lambda *a:None;x.op.observe_api=lambda p:{'proof':'original'};x.op.validate_api_observation=lambda *a:True
 status={'config_sha256':cfgsha,'snapshot_sha256':c.sha(snap),'monitor':{'config_sha256':cfgsha,'registration':'LOADED','state':'IDLE'}}
 x.read_graph_status=lambda:status
 return x,state,status

@pytest.mark.parametrize('mode',['unloaded','disabled','wrong_config','missing_registration','failed_monitor'])
def test_recovery_cannot_complete_with_unrestored_collector_or_monitor(tmp_path,mode):
 x,state,status=recovery_fixture(tmp_path)
 if mode=='unloaded':state['collector']={'kind':'ABSENT','file_version':'OLD','pid':None}
 if mode=='disabled':x.graph_disabled=lambda:True
 if mode=='wrong_config':status['monitor']['config_sha256']='new-or-unknown'
 if mode=='missing_registration':status['monitor']['registration']='UNLOADED'
 if mode=='failed_monitor':status['monitor']['state']='FAILED'
 with pytest.raises(c.Stop):x.verify_rollback()
 assert not any('PROOF_VERIFIED' in event or event=='ROLLBACK_EXACT_OLD_BINDINGS_CWD_VERIFIED' for event,_ in x.j.events)
 assert x.j.commands==[]

def test_idle_queue_collector_without_pid_is_valid_when_real_bindings_and_monitor_match(tmp_path):
 x,state,status=recovery_fixture(tmp_path);x.verify_rollback()
 final=x.j.events[-1];assert final[0]=='ROLLBACK_EXACT_OLD_BINDINGS_CWD_VERIFIED' and final[1]['collector_pid']==0 and final[1]['collector_enabled'] is True
 assert final[1]['standard_api_dispatcher']=='BASELINE_CUSTOM_SCHEMA_CANNOT_CONFIRM'


def test_precise_partial_bootout_failure_restores_only_absent_collector(tmp_path):
 x=base(tmp_path);state=bindings();x.op.label_state=lambda label:None if state[next(k for k,v in c.LABELS.items() if v==label)]['kind']=='ABSENT' else state[next(k for k,v in c.LABELS.items() if v==label)]['pid']
 x.g=SimpleNamespace(identity=lambda pid:{'pid':pid,'start':'original'},cwd=lambda pid:'/old')
 def command(args):
  x.j.commands.append(args);x.j.action_counts[tuple(args)]=x.j.action_counts.get(tuple(args),0)+1
  label=args[-1].split('/')[-1] if args[1]=='bootout' else Path(args[-1]).name.removesuffix('.plist')
  if args[1]=='bootout':
   if label==c.LABELS['main']:raise c.Stop('COMMAND_NONZERO_OUTCOME_RECONCILE_NO_RETRY')
   state['collector']={'kind':'ABSENT','file_version':'OLD','plist_sha256':'before-collector','pid':None}
  else:state['collector']=bindings()['collector']
  return SimpleNamespace(returncode=0)
 # Source row filenames are not label filenames in this synthetic fixture;
 # bootstrap command is known to be collector after the minimal plan.
 x.j.command=command
 x.bootout('collector')
 with pytest.raises(c.Stop,match='COMMAND_NONZERO'):x.bootout('main')
 x.observe_service_binding=lambda name:state[name];x.graph_disabled=lambda:False;x.release_graph_collector_lock=lambda:None;x.verify_rollback=lambda:x.j.record('VERIFIED_ONLY_AFTER_MINIMAL_RESTORE')
 x.rollback()
 assert [cmd[1] for cmd in x.j.commands]==['bootout','bootout','bootstrap']
 assert x.j.commands[-1][-1]==x.op.op(x.p,'collector')['plist']
 assert state['main']==bindings()['main'] and state['api']==bindings()['api']
 # Global action tokens survive recovery. No retry of unknown Main bootout.
 with pytest.raises(c.Stop,match='ALREADY_ATTEMPTED'):x.bootout('main')
 assert len(x.j.commands)==3


def test_unknown_partial_state_stops_before_touching_healthy_api(tmp_path):
 x=base(tmp_path);state=bindings()
 def observe(name):
  if name=='main':raise c.Stop('RECOVERY_LOADED_BINDING_UNKNOWN_OR_MISMATCH:main')
  return state[name]
 x.observe_service_binding=observe;x.graph_disabled=lambda:False
 with pytest.raises(c.Stop,match='UNKNOWN'):x.rollback()
 assert x.j.commands==[]


def test_new_running_owner_without_own_bootstrap_progress_is_not_stopped(tmp_path):
 x=base(tmp_path);state=bindings();state['main']={**state['main'],'file_version':'NEW','loaded_version':'NEW'};x.observe_service_binding=lambda name:state[name];x.graph_disabled=lambda:False
 with pytest.raises(c.Stop,match='WITHOUT_OWN_BOOTSTRAP'):x.rollback()
 assert x.j.commands==[]


def printed(plist):
 lines=['gui/501/fixed = {','\targuments = {',*['\t\t'+arg for arg in plist['ProgramArguments']],'\t}','\tworking directory = '+plist['WorkingDirectory'],'\tenvironment = {']
 lines+=['\t\t'+key+' => '+str(val) for key,val in plist.get('EnvironmentVariables',{}).items()]
 lines+=['\t}','\t"QueueDirectories" => '+str(plist.get('QueueDirectories',[])),'}'];return '\n'.join(lines)

@pytest.mark.parametrize('wrong',['config_argument','environment_release','working_directory'])
def test_loaded_collector_binding_is_read_from_launchctl_not_just_plist(tmp_path,monkeypatch,wrong):
 x=base(tmp_path);label=c.LABELS['collector'];before={'ProgramArguments':['python','-B','/old/collect.py','--config','/old/config.json'],'WorkingDirectory':'/old/app','EnvironmentVariables':{'V35_RELEASE_ID':'old-id','PYTHONPATH':'/old/app'},'QueueDirectories':['/inbox']}
 raw=plistlib.dumps(before);row=x.op.op(x.p,'collector');Path(row['plist']).write_bytes(raw);row['before_sha256']=c.sha(row['plist'])
 (tmp_path/(label+'.before.plist')).write_bytes(raw);after={**before,'WorkingDirectory':'/new/app','ProgramArguments':['python','-B','/new/collect.py','--config','/new/config.json']}
 x.op.proposed_bytes=lambda *a:plistlib.dumps(after);x.g=SimpleNamespace(identity=lambda pid:None,cwd=lambda pid:'/old/app')
 observed=json.loads(json.dumps(before))
 if wrong=='config_argument':observed['ProgramArguments'][-1]='/wrong/config.json'
 if wrong=='environment_release':observed['EnvironmentVariables']['V35_RELEASE_ID']='wrong-id'
 if wrong=='working_directory':observed['WorkingDirectory']='/wrong/app'
 monkeypatch.setattr(c,'D',tmp_path);monkeypatch.setattr(c.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=printed(observed),stderr=''))
 with pytest.raises(c.Stop,match='LOADED_BINDING_UNKNOWN'):x.observe_service_binding('collector')


def test_loaded_idle_collector_exact_cli_and_config_are_accepted(tmp_path,monkeypatch):
 x=base(tmp_path);row=x.op.op(x.p,'collector');before={'ProgramArguments':['python','-B','/old/collect.py','--config','/old/config.json'],'WorkingDirectory':'/old/app','EnvironmentVariables':{'V35_RELEASE_ID':'old-id','PYTHONPATH':'/old/app'},'QueueDirectories':['/inbox']};raw=plistlib.dumps(before);Path(row['plist']).write_bytes(raw);row['before_sha256']=c.sha(row['plist']);(tmp_path/(row['label']+'.before.plist')).write_bytes(raw)
 after={**before,'WorkingDirectory':'/new/app'};x.op.proposed_bytes=lambda *a:plistlib.dumps(after);x.g=SimpleNamespace(identity=lambda pid:None,cwd=lambda pid:'/old/app')
 monkeypatch.setattr(c,'D',tmp_path);monkeypatch.setattr(c.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=printed(before),stderr=''))
 result=x.observe_service_binding('collector');assert result['kind']=='LOADED' and result['file_version']=='OLD' and result['pid']==0

@pytest.mark.parametrize('stamp,ready',[('09:18:59',True),('09:19:00',False),('09:23:59',False),('09:24:01',False),('09:27:59',False),('09:28:00',True)])
def test_conservative_five_minute_window_margin(tmp_path,stamp,ready):
 x=base(tmp_path);now=RealDatetime.fromisoformat('2026-10-27T'+stamp+'+08:00');assert x.deployment_boundary(now)['ready'] is ready


def test_last_bootout_observation_crossing_window_is_rejected_before_token_or_command(tmp_path):
 x=base(tmp_path);x.forward_first_action_pending=True;x.op.label_state=lambda label:0;x.g=SimpleNamespace(identity=lambda pid:None);x.deployment_boundary=lambda:{'ready':False,'reason':'crossed'}
 with pytest.raises(c.Stop,match='WINDOW_REVOKED'):x.bootout('collector')
 assert x.attempted_service_actions==set() and x.j.commands==[] and x.forward_first_action_pending is True


def test_final_graph_get_crosses_window_releases_business_and_api_guards(tmp_path,monkeypatch):
 x=base(tmp_path);oldplan=tmp_path/'oldplan.json';oldplan.write_text('{}');x.p.update(old_graph_plan=str(oldplan),old_api_app='/old/api')
 clock={'now':RealDatetime.fromisoformat('2026-10-27T09:23:59+08:00')}
 class Clock:
  @classmethod
  def now(cls,tz=None):return clock['now']
 monkeypatch.setattr(c,'datetime',Clock);monkeypatch.setattr(c,'approve',lambda *a:None)
 log=Log();monkeypatch.setattr(c,'Journal',lambda:log);x.graph_disabled=lambda:False;x.compare=lambda:None;x.stage=lambda:None;x.history_http=lambda *a:{}
 x.g=SimpleNamespace(initial_old=lambda pid:{'pid':pid},identity=lambda pid:{'pid':pid},cwd=lambda pid:'/old/api')
 @contextmanager
 def owner():yield
 entries=[];held={'lane':False,'api':False}
 @contextmanager
 def guards(old):
  if entries:raise RuntimeError('TEST_STOP_AFTER_GUARDS_RELEASED')
  entries.append('enter');held.update(lane=True,api=True)
  try:yield
  finally:held.update(lane=False,api=False);entries.append('released')
 x.original_main_control_owner=owner;x.all_original_guards=guards
 def final_get(plan):clock['now']=RealDatetime.fromisoformat('2026-10-27T09:24:01+08:00');return {'api_pid':12}
 x.op.observe_api=final_get;x.op.validate_api_observation=lambda *a:True;x.bootout=lambda name:pytest.fail('no bootout across protected window')
 with pytest.raises(RuntimeError,match='TEST_STOP_AFTER'):x.execute(tmp_path/'review','sha',11)
 assert entries==['enter','released'] and held=={'lane':False,'api':False}
 assert any(e=='FINAL_FRESH_OBSERVATION_CROSSED_BOUNDARY_RELEASE_GUARDS' for e,_ in log.events)
 assert log.commands==[]


def test_near_window_wait_never_acquires_business_lane_or_api_guard(tmp_path,monkeypatch):
 x=base(tmp_path);x.deployment_boundary=lambda:{'ready':False,'reason':'near window'}
 x.ledger=SimpleNamespace(try_acquire_scheduler_lane=lambda lane:pytest.fail('must not touch business lane while waiting out window'))
 def halt(seconds):raise RuntimeError('STOP_WAIT_WITHOUT_GUARDS')
 monkeypatch.setattr(c.time,'sleep',halt)
 with pytest.raises(RuntimeError,match='WITHOUT_GUARDS'):
  with x.natural_idle_lanes({'pid':11}):pytest.fail('cannot reach API guards')
 assert x.j.commands==[] and x.j.events[-1][0]=='WAIT_PROTECTED_OR_NEAR_WINDOW_WITHOUT_BUSINESS_GUARDS'
