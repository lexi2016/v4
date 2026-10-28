"""One reviewed V4 API-only cutover; no main/collector/scheduler operations."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import argparse,importlib.util,json,os,plistlib,subprocess,sys,time
from urllib.request import urlopen
HERE=Path(__file__).resolve().parent
PLIST=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist')
LABEL='com.lexi.v4.api'
OP_SHA='74edabd6a0bc1cf0ed1c38af07ae535b494d456f7a6a5ce184e44573ef7d0ae2'
def sh(raw):return sha256(raw).hexdigest()
def require(ok,reason):
 if not ok:raise RuntimeError(reason)
def pin(path,digest):require(sh(Path(path).read_bytes())==digest,'PIN_DRIFT:'+str(path))
def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
class ProcessSamplePending(RuntimeError):
 def __init__(self,reason,ps_identity=None):
  super().__init__(reason);self.ps_identity=ps_identity

def process(pid,*,sample_timeout_seconds=None):
 # Strict by default: only exit_wait/verify_running catch the typed absence.
 sample_deadline=None if sample_timeout_seconds is None else time.monotonic()+sample_timeout_seconds
 try:p=subprocess.run(['/bin/ps','-p',str(pid),'-o','pid=,lstart=,command='],capture_output=True,text=True,timeout=sample_timeout_seconds)
 except subprocess.TimeoutExpired as error:raise ProcessSamplePending('PS_SAMPLE_PENDING') from error
 if p.returncode:
  require(p.returncode==1 and not p.stdout.strip() and not p.stderr.strip(),'PS_SAMPLE_FAILED')
  return None
 identity=p.stdout.strip();require(len(identity.splitlines())==1 and identity.split()[0]==str(pid),'PS_IDENTITY_INVALID')
 remaining=None if sample_deadline is None else sample_deadline-time.monotonic()
 if remaining is not None and remaining<=0:raise ProcessSamplePending('CWD_SAMPLE_PENDING',identity)
 try:c=subprocess.run(['/usr/sbin/lsof','-a','-p',str(pid),'-d','cwd','-Fn'],capture_output=True,text=True,timeout=remaining)
 except subprocess.TimeoutExpired as error:raise ProcessSamplePending('CWD_SAMPLE_PENDING',identity) from error
 dirs=[x[1:] for x in c.stdout.splitlines() if x.startswith('n')]
 require(c.returncode in (0,1) and not c.stderr.strip(),'CWD_SAMPLE_FAILED')
 if not dirs:raise ProcessSamplePending('CWD_SAMPLE_PENDING',identity)
 require(len(dirs)==1,'CWD_SAMPLE_AMBIGUOUS')
 return {'pid':pid,'ps_identity':identity,'cwd':dirs[0]}

def listeners(*,sample_timeout_seconds=None):
 p=subprocess.run(['/usr/sbin/lsof','-nP','-iTCP:8873','-sTCP:LISTEN','-Fp'],capture_output=True,text=True,timeout=sample_timeout_seconds)
 return {int(x[1:]) for x in p.stdout.splitlines() if x.startswith('p')}
def idle(pid):
 p=subprocess.run(['/bin/ps','-axo','pid=,ppid='],capture_output=True,text=True,check=True)
 require(not [x for line in p.stdout.splitlines() if len(x:=line.split())==2 and x[1]==str(pid)],'API_CHILD_MUST_COMPLETE')
 q=subprocess.run(['/usr/sbin/lsof','-nP','-a','-p',str(pid),'-iTCP','-sTCP:ESTABLISHED'],capture_output=True,text=True)
 require(q.returncode==1 and not q.stdout and not q.stderr,'API_CONNECTION_ACTIVE_OR_UNCONFIRMED')
def get_json(url,*,timeout_seconds=20):
 with urlopen('http://127.0.0.1:8873'+url,timeout=timeout_seconds) as r:
  require(r.status==200,'HTTP_NOT_200');return json.load(r)
def runtime(*,timeout_seconds=20):return get_json('/api/v1/runs/date-list?date='+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d'),timeout_seconds=timeout_seconds).get('runtime_identity',{})
def window(plan,moment=None):
 ref=plan['window_source'];pin(ref['path'],ref['sha256']);catalog=json.loads(Path(ref['path']).read_bytes())
 require(catalog['timezone']=='Asia/Shanghai' and catalog['protection_margin_seconds']==300,'WINDOW_POLICY')
 for source in catalog['current_sources']:
  if 'plist' in source:pin(source['plist'],source['plist_sha256']);pin(source['catalog'],source['catalog_sha256'])
  else:pin(source['schedule_module'],source['sha256'])
 pin(catalog['historical_policy_path'],catalog['historical_policy_sha256'])
 now=(moment or datetime.now(ZoneInfo('Asia/Shanghai'))).astimezone(ZoneInfo('Asia/Shanghai'))
 for start,end in catalog['historical_conservative_windows']+[[x,x] for x in catalog['scheduled_slots']]:
  for offset in (-1,0,1):
   day=now+timedelta(days=offset);a=day.replace(hour=int(start[:2]),minute=int(start[2:]),second=0,microsecond=0)-timedelta(seconds=300);b=day.replace(hour=int(end[:2]),minute=int(end[2:]),second=0,microsecond=0)+timedelta(seconds=360)
   require(not a<=now<b,'PROTECTED_BUSINESS_WINDOW')
 return now.isoformat()
def assets(plan):
 ref=plan['assets'];pin(ref['manifest'],ref['sha256']);files=json.loads(Path(ref['manifest']).read_bytes())['files'];require(len(files)==452,'ASSET_COUNT')
 for e in files:pin(Path(ref['root'])/e['path'],e['sha256'])
def dependencies(plan):
 old=Path(plan['base_app']);pin(old/'ops/api_release_integration.py',plan['integration_sha256']);pin(HERE/'publication_operator.py',OP_SHA);pin(HERE/'api_module_contracts.current-v4.json',plan['module_contract_sha256'])
 sys.path.insert(0,str(old));integ=module(old/'ops/api_release_integration.py','r19_current_integration');integ.MODULE_CONTRACT_PATH=HERE/'api_module_contracts.current-v4.json';op=module(HERE/'publication_operator.py','r19_original_operator');return integ,op

_STAGE_LABELS = ('com.lexi.stage-center.scheduler', 'com.lexi.stage-center.a-opening-precapture')
def stage_rows(plan):
 rows=plan['stage_operations']
 require(tuple(r['label'] for r in rows)==_STAGE_LABELS,'EXACT_STAGE_PAIR_REQUIRED')
 for row in rows:require(row['plist']==str(PLIST.parent/(row['label']+'.plist')),'STAGE_PLIST_SCOPE')
 return rows
def stage_idle(plan,op):
 # Read process command identities only. Never kill, cancel, lock or collect.
 result=subprocess.run(['/bin/ps','-axo','pid=,ppid=,command='],capture_output=True,text=True,check=True)
 roots=(plan['stage_base_app']+'/',str(Path(plan['stage_candidate_root'])/'app')+'/')
 require(not any(any(root in line for root in roots) for line in result.stdout.splitlines()),'STAGE_PROCESS_OR_DESCENDANT_MUST_COMPLETE')
def stage_definition(row,op,after):
 op.metadata_pin(row)
 expected=row['after_sha256'] if after else row['before_sha256'];pin(row['plist'],expected)
 require(op.label_state(row['label'])==0,'STAGE_MUST_BE_LOADED_WITHOUT_PID')
 loaded=op.run(['print',f'gui/{os.getuid()}/'+row['label']])
 app=row['new_prefix'] if after else row['replace_prefix']
 require(loaded.returncode==0 and app.encode() in loaded.stdout,'STAGE_LOADED_DEFINITION_DRIFT')
 return {'label':row['label'],'plist_sha256':expected,'loaded_pid':None,'app_root':app}
def stage_before(plan,op):
 stage_idle(plan,op);rows=stage_rows(plan)
 for row in rows:
  raw=Path(row['plist']).read_bytes();after=Path(row['template_path']).read_bytes()
  require(op.proposed_bytes(row,raw)==after,'STAGE_EXACT_CAS_TEMPLATE')
  a,b=plistlib.loads(raw),plistlib.loads(after)
  require(a.get('RunAtLoad') is False and b.get('RunAtLoad') is False,'NO_RUN_AT_LOAD')
  require(a.get('StartCalendarInterval')==b.get('StartCalendarInterval'),'STAGE_CALENDAR_CHANGED')
  require({k for k in a|b if a.get(k)!=b.get(k)}=={'EnvironmentVariables','WorkingDirectory','ProgramArguments'},'STAGE_PLIST_DELTA_SCOPE')
  env_a,env_b=a['EnvironmentVariables'],b['EnvironmentVariables']
  allowed={'V4_APP_ROOT','V4_RELEASE_ID','V4_RELEASE_MANIFEST_PATH','V4_RELEASE_MANIFEST_SHA256','PYTHONPATH','STAGE_CENTER_CONFIG'}
  require({k for k in env_a|env_b if env_a.get(k)!=env_b.get(k)}==allowed,'STAGE_ENV_DELTA_SCOPE')
  require(env_b['V4_APP_ROOT']==str(Path(plan['stage_candidate_root'])/'app') and env_b['V4_RELEASE_ID']==Path(plan['stage_candidate_root']).name and env_b['V4_RELEASE_MANIFEST_SHA256']==plan['components']['stage']['sha256'],'STAGE_RELEASE_TUPLE')
  stage_definition(row,op,False)
 cfg=Path(plan['stage_candidate_root'])/'app/stage_center_tick_config.json';pin(cfg,plan['stage_config_sha256']);config=json.loads(cfg.read_bytes())
 require(config['release_id']==Path(plan['stage_candidate_root']).name and config['research_owner_binding']==plan['unchanged_main_binding'],'STAGE_CONFIG_MAIN_BINDING')
 meta=plan['components']['stage'];root=Path(meta['release_root']);pin(root/'release-manifest.json',meta['sha256'])
 manifest=json.loads((root/'release-manifest.json').read_bytes())
 require(manifest['app_root']==str(root/'app') and manifest['release_id']==root.name,'STAGE_MANIFEST_TUPLE')
 for entry in manifest['app_files']:
  path=root/'app'/entry['path'];require(not path.is_symlink() and path.resolve()==path,'STAGE_RELEASE_PATH_UNSAFE');pin(path,entry['sha256'])
 require(all(manifest.get(k) is False for k in ('production_allowed','buy_gate_updated','orders_sent')),'STAGE_UNSAFE_FLAGS')
 return [stage_definition(row,op,False) for row in rows]
def stage_service(op,row,args):
 require(args in (['bootout',f'gui/{os.getuid()}/'+row['label']],['bootstrap',f'gui/{os.getuid()}',row['plist']]),'STAGE_SERVICE_SCOPE')
 require(op.run(args).returncode==0,'STAGE_LAUNCHCTL_UNCONFIRMED')
def stage_apply(plan,op):
 stage_before(plan,op);window(plan)
 for row in stage_rows(plan):
  stage_service(op,row,['bootout',f'gui/{os.getuid()}/'+row['label']]);require(op.label_state(row['label']) is None,'STAGE_UNLOAD_UNCONFIRMED')
  require(op.install_plist(row)=='INSTALLED_UNLOADED','STAGE_FORWARD_CAS')
  stage_service(op,row,['bootstrap',f'gui/{os.getuid()}',row['plist']])
 return [stage_definition(row,op,True) for row in stage_rows(plan)]
def stage_rollback(plan,op):
 stage_idle(plan,op)
 for row in reversed(stage_rows(plan)):
  current=sh(Path(row['plist']).read_bytes());require(current in (row['before_sha256'],row['after_sha256']),'STAGE_ROLLBACK_UNKNOWN_CAS')
  state=op.label_state(row['label']);require(state in (None,0),'STAGE_ROLLBACK_ACTIVE_PROCESS_NO_KILL')
  if current==row['before_sha256'] and state==0:stage_definition(row,op,False);continue
  if state==0:
   loaded=op.run(['print',f'gui/{os.getuid()}/'+row['label']]);require(loaded.returncode==0 and any(root.encode() in loaded.stdout for root in (row['replace_prefix'],row['new_prefix'])),'STAGE_ROLLBACK_UNKNOWN_DEFINITION')
   stage_service(op,row,['bootout',f'gui/{os.getuid()}/'+row['label']])
  require(op.label_state(row['label']) is None,'STAGE_ROLLBACK_UNLOAD_UNCONFIRMED')
  if current==row['after_sha256']:require(op.install_plist(row,rollback=True)=='ROLLED_BACK','STAGE_INVERSE_CAS')
  stage_service(op,row,['bootstrap',f'gui/{os.getuid()}',row['plist']])
 return [stage_definition(row,op,False) for row in stage_rows(plan)]
def reuse_admission(plan):
 ref=plan['admission'];require(ref.get('mode')=='reuse','ADMISSION_REUSE_ONLY')
 target=Path(ref['target']);require(target.is_file() and not any(p.is_symlink() for p in (target,*target.parents)),'ADMISSION_EXISTING_REGULAR_FILE_REQUIRED')
 pin(ref['source'],ref['sha256']);pin(target,ref['sha256'])

def check(plan,integ,op):
 require(plan['label']==LABEL and plan['operation']['plist']==str(PLIST),'API_ONLY_SCOPE')
 op.metadata_pin(plan['operation'])
 pin(PLIST,plan['operation']['before_sha256']);pin(plan['owner_handoff']['path'],plan['owner_handoff']['sha256'])
 pin(plan['workbench_config']['path'],plan['workbench_config']['sha256'])
 cfg=json.loads(Path(plan['workbench_config']['path']).read_bytes());require(str(Path(cfg['state_root'])/'manager_workbench')==plan['announcement_workbench_root'],'WORKBENCH_CONFIG_ROOT')
 require(op.proposed_bytes(plan['operation'],PLIST.read_bytes())==Path(plan['operation']['template_path']).read_bytes(),'EXACT_TEMPLATE_OPERATOR')
 before=plistlib.loads(PLIST.read_bytes());after=plistlib.loads(Path(plan['operation']['template_path']).read_bytes())
 require(after['ProgramArguments']==before['ProgramArguments'],'PROGRAM_ARGUMENTS_CHANGED')
 allowed={'V4_APP_ROOT','V4_RELEASE_ID','V4_RELEASE_MANIFEST_PATH','V4_RELEASE_MANIFEST_SHA256','PYTHONPATH','V4_RESEARCH_PANEL_ROOT','V4_RESEARCH_PANEL_ASSET_MANIFEST'}
 require({k for k in before['EnvironmentVariables']|after['EnvironmentVariables'] if before['EnvironmentVariables'].get(k)!=after['EnvironmentVariables'].get(k)}==allowed,'ENV_DELTA_SCOPE')
 require({k for k in before|after if before.get(k)!=after.get(k)}=={'EnvironmentVariables','WorkingDirectory'},'PLIST_DELTA_SCOPE')
 active=integ.read_active_release(PLIST);require(active['release_manifest_sha256']==plan['base_manifest_sha256'],'BASE_IDENTITY')
 integ.verify_api_release_candidate(candidate_root=Path(plan['candidate_root']),active_api_plist_path=PLIST,expected_manifest_sha256=plan['candidate_manifest_sha256'])
 assets(plan);reuse_admission(plan);stage_before(plan,op)
 require(not any(p.is_symlink() for p in (Path(plan['admission']['target']),*Path(plan['admission']['target']).parents)),'ADMISSION_SYMLINK')
 pid=op.label_state(LABEL);require(pid==plan['before_process']['pid'] and listeners()=={pid} and process(pid)==plan['before_process'],'LOADED_PID_START_CWD_DRIFT')
 loaded=op.run(['print',f'gui/{os.getuid()}/'+LABEL]);require(loaded.returncode==0 and plan['base_app'].encode() in loaded.stdout,'LOADED_DEFINITION_DRIFT')
 r=runtime();require(r.get('release_id')==active['release_id'] and r.get('manifest_sha256')==plan['base_manifest_sha256'] and r.get('status')=='MANIFEST_EXECUTION_FILES_VERIFIED','RUNTIME_IDENTITY_DRIFT')
 idle(pid);window(plan);return {'status':'BEFORE_PASS','process':process(pid),'runtime':r,'inventory_count':len(active['inventory'])}
def service(op,args):
 # Metadata is checked in preflight/installer/loaded readback; no active setters.
 require(args in (['bootout',f'gui/{os.getuid()}/'+LABEL],['bootstrap',f'gui/{os.getuid()}',str(PLIST)]),'SERVICE_SCOPE')
 require(op.run(args).returncode==0,'LAUNCHCTL_UNCONFIRMED')
def exit_wait(identity,*,wait_seconds=10):
 deadline=time.monotonic()+wait_seconds;last='NO_EXIT_OBSERVATION'
 while time.monotonic()<deadline:
  remaining=deadline-time.monotonic()
  if remaining<=0:break
  try:now=process(identity['pid'],sample_timeout_seconds=min(2,remaining))
  except ProcessSamplePending as error:
   if error.ps_identity is not None:require(error.ps_identity==identity['ps_identity'],'PID_REUSED')
   last=str(error)
  else:
   if now is None:return
   require(now==identity,'PID_REUSED');last='KNOWN_PROCESS_STILL_PRESENT'
  time.sleep(min(.1,max(0,deadline-time.monotonic())))
 raise RuntimeError('EXIT_UNCONFIRMED_NO_KILL:'+last)

def verify_running(plan,integ,op,candidate,*,wait_seconds=45):
 root=Path(plan['candidate_root']) if candidate else Path(plan['base_app']).parent;digest=plan['candidate_manifest_sha256'] if candidate else plan['base_manifest_sha256']
 op.metadata_pin(plan['operation'])
 expected=plan['operation']['after_sha256'] if candidate else plan['operation']['before_sha256'];pin(PLIST,expected)
 deadline=time.monotonic()+wait_seconds;bound_pid=None;bound_ps=None;last='NO_STARTUP_OBSERVATION';attempts=0
 def bind_ps(identity):
  nonlocal bound_ps
  if identity is None:return
  if bound_ps is None:bound_ps=identity
  else:require(identity==bound_ps,'STARTUP_PID_REUSED')
 while time.monotonic()<deadline:
  attempts+=1;pid=op.label_state(LABEL)
  if bound_pid is not None:require(pid==bound_pid,'STARTUP_LABEL_PID_CHANGED')
  if type(pid) is int and pid>0:
   if bound_pid is None:bound_pid=pid
   try:
    identity=process(pid,sample_timeout_seconds=min(2,max(.001,deadline-time.monotonic())))
    if identity is None:raise ProcessSamplePending('PS_NOT_VISIBLE_YET')
    bind_ps(identity['ps_identity']);require(identity['cwd']==str(root/'app'),'STARTUP_CWD_MISMATCH')
    if listeners(sample_timeout_seconds=min(2,max(.001,deadline-time.monotonic())))=={pid}:
     remaining=deadline-time.monotonic()
     if remaining<=0:break
     try:r=runtime(timeout_seconds=min(20,remaining))
     except (OSError,ValueError) as error:last=type(error).__name__+':'+str(error);r=None
     if time.monotonic()>=deadline:break
     if r is not None and r.get('release_id')==root.name and r.get('manifest_sha256')==digest and r.get('status')=='MANIFEST_EXECUTION_FILES_VERIFIED':
      require(op.label_state(LABEL)==pid,'STARTUP_LABEL_PID_CHANGED')
      final=process(pid,sample_timeout_seconds=min(2,max(.001,deadline-time.monotonic())))
      if final is None:raise ProcessSamplePending('PS_NOT_VISIBLE_AFTER_READBACK')
      bind_ps(final['ps_identity']);require(final['cwd']==str(root/'app'),'STARTUP_CWD_MISMATCH')
      strict=integ.read_active_release(PLIST);require(strict['release_manifest_sha256']==digest,'STRICT_AFTER_IDENTITY')
      require(time.monotonic()<deadline,'STARTUP_OBSERVATION_DEADLINE')
      return {'process':final,'runtime':r,'identity_sample_attempts':attempts,'observation_wait_budget_seconds':wait_seconds}
     if r is not None:last='RUNTIME_MANIFEST_NOT_VERIFIED'
    else:last='LISTENER_NOT_READY'
   except ProcessSamplePending as error:bind_ps(error.ps_identity);last=str(error)
   except subprocess.TimeoutExpired as error:last='LISTENER_SAMPLE_PENDING:'+str(error)
  time.sleep(min(.1,max(0,deadline-time.monotonic())))
 raise RuntimeError('RUNTIME_READBACK_UNCONFIRMED:'+last)
def rollback(plan,integ,op):
 stage_rollback(plan,op)
 op.metadata_pin(plan['operation'])
 current=sh(PLIST.read_bytes());require(current in (plan['operation']['before_sha256'],plan['operation']['after_sha256']),'ROLLBACK_UNKNOWN_PLIST')
 pid=op.label_state(LABEL)
 if pid is not None:
  if pid:
   ident=process(pid);require(ident and ident['cwd'] in (plan['base_app'],str(Path(plan['candidate_root'])/'app')),'ROLLBACK_UNKNOWN_PROCESS');idle(pid)
  else:
   loaded=op.run(['print',f'gui/{os.getuid()}/'+LABEL]);require(loaded.returncode==0 and any(root.encode() in loaded.stdout for root in (plan['base_app'],str(Path(plan['candidate_root'])/'app'))),'ROLLBACK_UNKNOWN_LOADED_DEFINITION')
  service(op,['bootout',f'gui/{os.getuid()}/'+LABEL])
  if pid:exit_wait(ident)
 require(op.label_state(LABEL) is None,'ROLLBACK_LABEL_NOT_UNLOADED')
 if current==plan['operation']['after_sha256']:require(op.install_plist(plan['operation'],rollback=True)=='ROLLED_BACK','INVERSE_PLIST_CAS')
 reuse_admission(plan)
 pin(PLIST,plan['operation']['before_sha256']);service(op,['bootstrap',f'gui/{os.getuid()}',str(PLIST)]);return verify_running(plan,integ,op,False)
def record(state):
 p=HERE/'EXECUTION_RECEIPT.json'
 with p.open('w') as f:json.dump(state,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 print(json.dumps({'status':state['status'],'receipt':str(p)},ensure_ascii=False),flush=True)
def recovery_record(state):
 # Receipt failure, including Ctrl-C, must never bypass guarded recovery.
 try:record(state)
 except BaseException:pass
def execute(plan,integ,op):
 state={'status':'PRECHECK','guards_held':False};record(state)
 with integ.announcement_flash_cutover_guard(Path(plan['announcement_workbench_root']),timeout_seconds=10) as announcement:
  with integ.shared_api_release_lock(PLIST,timeout_seconds=2,role='gateway') as lease:
   integ.assert_api_release_lock(lease,PLIST,role='gateway');state.update(guards_held=True,announcement_guard=announcement);state['before']=check(plan,integ,op);record(state)
   try:
    service(op,['bootout',f'gui/{os.getuid()}/'+LABEL]);exit_wait(plan['before_process']);require(op.label_state(LABEL) is None,'API_NOT_UNLOADED')
    reuse_admission(plan);require(op.install_plist(plan['operation'])=='INSTALLED_UNLOADED','FORWARD_PLIST_CAS')
    service(op,['bootstrap',f'gui/{os.getuid()}',str(PLIST)]);state['stage_after']=stage_apply(plan,op);state['after']=verify_running(plan,integ,op,True)
    integ.verify_api_release_candidate(candidate_root=Path(plan['candidate_root']),active_api_plist_path=PLIST,expected_manifest_sha256=plan['candidate_manifest_sha256'],active_pointer='candidate',lock_lease=lease,require_shared_lock=True)
    answer=get_json('/api/v4/research/a-share/history?ts_code=600715.SH&start_date=20261026&end_date=20261027&formula_version=R19_FROZEN_151_20261027')
    require(answer.get('status')=='READY' and answer.get('profile_id')=='R19_FROZEN_151_20261027' and len(answer['rows'])==2 and len(answer['r19_research']['last_row']['values'])==51,'LIVE_PROFILE_READBACK')
    for name in ('daily.html','r19-results.js','r19-chart.js'):
     with urlopen('http://127.0.0.1:8873/research-panel/'+name,timeout=20) as r:pin_bytes=r.read()
     require(sh(pin_bytes)==sh((Path(plan['assets']['root'])/name).read_bytes()),'LIVE_UI_ASSET_SHA')
    close=get_json('/api/v4/review?date=20261028')['market_reviews']['A']
    canonical=sh(json.dumps(close,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
    require(canonical==plan['a_close_original_canonical_sha256'] and close.get('source_role')=='V3_5_NATIVE_CLOSE_MODEL' and all(close.get(k) is False for k in ('production_allowed','buy_gate_updated','orders_sent')),'A_CLOSE_DATE_ROLE_SHA_READBACK')
    state['a_close']={'trade_date':'20261028','canonical_sha256':canonical,'cannot_confirm':close.get('cannot_confirm'),'natural_verified':False}
    state.update(status='DEPLOYED_API_STAGE_AND_A_CLOSE_VERIFIED_UI_BROWSER_PENDING');record(state)
   except BaseException as error:
    state.update(status='CUTOVER_FAILED_GUARDS_HELD',error=repr(error))
    while True:
     try:
      recovery_record(state)
      if state['status']=='CUTOVER_FAILED_GUARDS_HELD':
       state['rollback']=rollback(plan,integ,op);state.update(status='ROLLED_BACK_BASE_HEALTH_VERIFIED');recovery_record(state);break
      action=sys.stdin.readline().strip()
      if action=='HANDOFF_RECOVERY':state.update(status='ROOT_EXPLICIT_RECOVERY_HANDOFF_UNVERIFIED');recovery_record(state);break
      if action=='ROLLBACK':state['rollback']=rollback(plan,integ,op);state.update(status='ROLLED_BACK_BASE_HEALTH_VERIFIED');recovery_record(state);break
      if not action:time.sleep(1)
     except BaseException as recovery_error:
      # Ctrl-C is not authorization to release the two held kernel locks.
      key='rollback_error' if state['status']=='CUTOVER_FAILED_GUARDS_HELD' else 'recovery_error'
      state.update(status='ROLLBACK_UNCONFIRMED_GUARDS_HELD',**{key:repr(recovery_error)})
 state['guards_held']=False;record(state)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['check','execute']);ap.add_argument('--plan-sha256',required=True);ap.add_argument('--review');ap.add_argument('--review-sha256');a=ap.parse_args()
 require(sys.dont_write_bytecode and sys.flags.no_user_site,'PYTHON_ISOLATION_FLAGS');path=HERE/'API_PROFILE_PUBLISH_PLAN.json';pin(path,a.plan_sha256);plan=json.loads(path.read_bytes());require(plan['controller_sha256']==sh(Path(__file__).read_bytes()),'CONTROLLER_DRIFT');integ,op=dependencies(plan)
 if a.action=='check':print(json.dumps(check(plan,integ,op),ensure_ascii=False));return
 require(a.review and a.review_sha256,'SCOPED_INDEPENDENT_REVIEW_REQUIRED');op.require_review(path,a.review,a.review_sha256);execute(plan,integ,op)
if __name__=='__main__':main()
