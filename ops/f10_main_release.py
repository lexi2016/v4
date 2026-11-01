"""Prepare one F10 continuation against the existing Main scheduler owner.

Only the controller may invoke activate/rollback/recover, after independent
review and a fresh idle observation. No panel pointers or seed values change.
"""
from __future__ import annotations
import argparse, ast, contextlib, fcntl, hashlib, importlib.util, json, os, plistlib, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
LOCAL=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
BASE=LOCAL/'releases/workbench-daily-chain-20261031-r6-main'
PLIST=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.scheduler.plist')
BASE_PLIST_SHA='90dc1efc38a0dfa1c3020374bfbc6eb9d193fcbcc4af3ed5977e2c1255f8294c'
BASE_MANIFEST_SHA='f32d922fafcbf8c1e6f9958d5802eef80e58195502f16410a6d11f744e98ac74'
BASE_TOP_SHA='a0e6b67d42ff67c45e8c61e129a0cec2a6d5ff47f608574f98458f72cc3329e1'
TOOLS=LOCAL/'candidates/stage-four-repairs-20261101-r4-api/app/ops/api_release_integration.py'
TOOLS_SHA='35ac1a9b6f3ea885b2788a9476dbc2f4dc21f42f43a359b63a0c22265c1fd154'
CHANGES=('ops/research_panel_top200.py','ops/research_panel_f10.py','ops/vendor/tdx_f10_concepts_existing.py','ops/vendor/tdx_f10_fetch_existing.py')
LANES=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners')
DOMAIN=f'gui/{os.getuid()}'; JOB=DOMAIN+'/com.lexi.v4.scheduler'
PANEL_PYTHON='/Users/lexi/Desktop/学习/runtime/venvs/v3.5-mac/bin/python'
RUNTIME=LOCAL/'runtime/retirement-main-20261028/venvs/v4-mac'
FLAGS={'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}


def sha(raw):return hashlib.sha256(raw).hexdigest()
def file_sha(p):return sha(Path(p).read_bytes())
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def checked(p,digest):
 p=Path(p)
 if p.is_symlink() or not p.is_file() or file_sha(p)!=digest:raise ValueError('PIN_CHANGED:'+str(p))
 return p

def write_json(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);raw=(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
 with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 sync(p.parent);return {'path':str(p),'sha256':sha(raw)}

def sync(path):
 fd=os.open(path,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)

def tools():
 spec=importlib.util.spec_from_file_location('f10_main_inventory',checked(TOOLS,TOOLS_SHA));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def source_identity():return {name:file_sha(REPO/name) for name in CHANGES}
def target():return LOCAL/'candidates'/('f10-daily-20261101-'+sha(canonical(source_identity()))[:16]+'-main')

def launch(*args):return subprocess.run(['/bin/launchctl',*args],capture_output=True,text=True,timeout=20)
def service_state():
 result=launch('print',JOB)
 if result.returncode:
  if 'could not find service' in result.stderr.lower():return None
  raise ValueError('MAIN_SERVICE_STATE_UNKNOWN')
 match=re.search(r'^\s*pid = (\d+)\s*$',result.stdout,re.M)
 if not match:raise ValueError('MAIN_SERVICE_PID_UNKNOWN')
 pid=int(match.group(1));info=subprocess.check_output(['ps','-p',str(pid),'-o','lstart=,command='],text=True).strip()
 cwd=subprocess.check_output(['lsof','-a','-p',str(pid),'-d','cwd','-Fn'],text=True)
 match=re.search(r'^n(.+)$',cwd,re.M)
 if not match or 'ops.run_v4_macos_scheduler_daemon' not in info:raise ValueError('MAIN_PROCESS_IDENTITY_UNKNOWN')
 return {'pid':pid,'start_command_sha256':sha(info.encode()),'root':match.group(1)}

def assert_active(expected_sha,expected_process):
 if file_sha(PLIST)!=expected_sha:raise ValueError('MAIN_PLIST_CAS_DRIFT')
 if service_state()!=expected_process:raise ValueError('MAIN_PROCESS_CAS_DRIFT')

def check_delta():
 before=checked(BASE/'app/ops/research_panel_top200.py',BASE_TOP_SHA).read_text();after=(REPO/CHANGES[0]).read_text()
 point='    return receipt\n\n\ndef record_daily_attempt(root,receipt):'
 if before.count(point)!=1 or after.count(point)!=1:raise ValueError('MAIN_OWNER_INSERTION_POINT_DRIFT')
 prefix=after.split(point,1)[0]
 if not prefix.startswith(before.split(point,1)[0]):raise ValueError('MAIN_OWNER_UNRELATED_CHANGE')
 added=prefix[len(before.split(point,1)[0]):]
 if not (added.startswith("    if receipt['status']=='COMPLETE_DESCRIPTIVE_NONPIT':\n") and 'complete_f10(context' in added and 'publish_f10_completion(context' in added):raise ValueError('MAIN_OWNER_DELTA_UNEXPECTED')
 if after!=before.replace(point,added+point,1):raise ValueError('MAIN_OWNER_UNRELATED_CHANGE')
 for name in CHANGES[1:]:
  if (BASE/'app'/name).exists():raise ValueError('MAIN_NEW_FILE_ALREADY_EXISTS:'+name)
 return added

def base_inventory(t):
 checked(BASE/'release-manifest.json',BASE_MANIFEST_SHA);manifest=json.loads((BASE/'release-manifest.json').read_bytes())
 entries=t.inventory_tree(BASE/'app');expected=manifest['application_inventory']
 if entries!=expected['entries'] or t.inventory_digest(entries)!=expected['aggregate_sha256']:raise ValueError('MAIN_BASE_INVENTORY_DRIFT')
 return manifest,entries

def replace_file(path,raw):
 path.parent.mkdir(parents=True,exist_ok=True);mode=(path.stat().st_mode&0o777) if path.exists() else 0o644
 with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.f10-overlay-',delete=False) as f:
  temp=Path(f.name)
  try:f.write(raw);f.flush();os.fsync(f.fileno());temp.chmod(mode);os.replace(temp,path)
  finally:temp.unlink(missing_ok=True)

def new_plist(old,manifest_sha,T):
 value=plistlib.loads(old);env=value['EnvironmentVariables'];env.update(V4_APP_ROOT=str(T/'app'),V4_RELEASE_ID=T.name,V4_RELEASE_MANIFEST_PATH=str(T/'release-manifest.json'),V4_RELEASE_MANIFEST_SHA256=manifest_sha)
 if value['ProgramArguments']!=['/bin/bash',str(BASE/'app/ops/launch_v4_macos_scheduler.sh')] or value['WorkingDirectory']!=str(BASE/'app'):raise ValueError('MAIN_PLIST_PROGRAM_UNEXPECTED')
 value['ProgramArguments'][1]=str(T/'app/ops/launch_v4_macos_scheduler.sh');value['WorkingDirectory']=str(T/'app')
 return plistlib.dumps(value)

def smoke(T):
 script="import inspect,sys;from pathlib import Path;from infrastructure.scheduling.executor_registry import FixedExecutorRegistry;from ops import research_panel_top200 as t,research_panel_f10 as f;import pytdx,pyarrow;s=inspect.getsource(FixedExecutorRegistry._run_a_daily);assert 'complete_daily_derivatives' in s;assert Path(t.__file__).resolve()==Path('ops/research_panel_top200.py').resolve();assert Path(f.__file__).resolve()==Path('ops/research_panel_f10.py').resolve();assert 'complete_f10(context' in inspect.getsource(t.complete_daily_derivatives);assert 'publish_f10_completion(context' in inspect.getsource(t.complete_daily_derivatives);print('MAIN_LOADED_CALLER_AND_F10_IMPORT_PASS')"
 env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'PYTHONPATH':str(T/'app')+':'+str(RUNTIME/'lib/python3.14/site-packages'),'PYTHONDONTWRITEBYTECODE':'1'}
 p=subprocess.run([str(RUNTIME/'bin/python'),'-S','-c',script],cwd=T/'app',env=env,capture_output=True,text=True,timeout=30)
 if p.returncode or 'MAIN_LOADED_CALLER_AND_F10_IMPORT_PASS' not in p.stdout:raise ValueError('MAIN_IMPORT_SMOKE_FAILED:'+p.stderr[-1200:])
 return p.stdout.strip()

def prepare():
 if os.path.realpath(sys.executable)!=os.path.realpath(PANEL_PYTHON):raise ValueError('PANEL_PYTHON_REQUIRED')
 T=target();t=tools();check_delta();checked(PLIST,BASE_PLIST_SHA);process=service_state()
 if not process or process['root']!=str(BASE/'app'):raise ValueError('MAIN_BASE_ROOT_CHANGED')
 manifest,before=base_inventory(t);T.mkdir();subprocess.run(['/bin/cp','-cRp',str(BASE/'app'),str(T/'app')],check=True,timeout=180)
 if t.inventory_tree(T/'app')!=before:raise ValueError('MAIN_COPY_DRIFT')
 for name in CHANGES:ast.parse((REPO/name).read_text(),filename=name);replace_file(T/'app'/name,(REPO/name).read_bytes())
 after=t.inventory_tree(T/'app');b={x['path']:x for x in before};a={x['path']:x for x in after};delta={k:{'before':b.get(k),'after':a.get(k)} for k in sorted(set(a)|set(b)) if a.get(k)!=b.get(k)}
 if set(delta)!=set(CHANGES):raise ValueError('MAIN_UNLISTED_DELTA:'+str(list(delta)))
 preserved=[v for k,v in b.items() if k not in delta];manifest.update(release_id=T.name,app_root=str(T/'app'),source_root=str(REPO),activation_status='NOT_ACTIVATED')
 manifest['candidate']={'root':str(T),'app_root':str(T/'app'),'release_id':T.name,'module_role':'main'}
 manifest['application_inventory']={'entries':after,'entry_count':len(after),'aggregate_sha256':t.inventory_digest(after)};manifest['app_files']=[x for x in after if x['kind']=='file']
 manifest['f10_daily_integration']={'base_manifest_sha256':BASE_MANIFEST_SHA,'source_sha256':source_identity(),'delta':delta,'non_delta_count':len(preserved),'non_delta_sha256':t.inventory_digest(preserved),'scheduler':'existing_complete_daily_derivatives','natural_run':'NOT_RUN',**FLAGS}
 mref=write_json(T/'release-manifest.json',manifest);(T/'config').mkdir();old=PLIST.read_bytes();(T/'config/before.plist').write_bytes(old);new=new_plist(old,mref['sha256'],T);(T/'config/candidate.plist').write_bytes(new)
 result=smoke(T);assert_active(BASE_PLIST_SHA,process);base_inventory(t);check_delta()
 receipt={'schema':'v4.f10_main_preparation.v1','status':'PREPARED_NOT_ACTIVATED','operator_sha256':file_sha(__file__),'base_plist_sha256':BASE_PLIST_SHA,'base_manifest_sha256':BASE_MANIFEST_SHA,'base_process':process,'manifest':mref,'candidate_plist_sha256':sha(new),'source_sha256':source_identity(),'delta':delta,'preserved_count':len(preserved),'preserved_sha256':t.inventory_digest(preserved),'smoke':result,'natural_daily':'NOT_RUN',**FLAGS}
 ref=write_json(T/'preparation.json',receipt);print(json.dumps({'status':receipt['status'],'target':str(T),'receipt':ref,'manifest':mref,'preserved_count':len(preserved),'smoke':result},ensure_ascii=False))

def verify(receipt_sha):
 T=target();receipt=json.loads(checked(T/'preparation.json',receipt_sha).read_bytes());t=tools();manifest,before=base_inventory(t);check_delta()
 if receipt['operator_sha256']!=file_sha(__file__) or receipt['source_sha256']!=source_identity():raise ValueError('MAIN_REVIEWED_SOURCE_DRIFT')
 checked(receipt['manifest']['path'],receipt['manifest']['sha256']);candidate=json.loads(Path(receipt['manifest']['path']).read_bytes())
 if candidate['candidate']['root']!=str(T) or t.inventory_tree(T/'app')!=candidate['application_inventory']['entries']:raise ValueError('MAIN_CANDIDATE_INVENTORY_DRIFT')
 checked(T/'config/before.plist',BASE_PLIST_SHA);checked(T/'config/candidate.plist',receipt['candidate_plist_sha256'])
 if (T/'config/candidate.plist').read_bytes()!=new_plist((T/'config/before.plist').read_bytes(),receipt['manifest']['sha256'],T):raise ValueError('MAIN_CANDIDATE_PLIST_DRIFT')
 if smoke(T)!=receipt['smoke']:raise ValueError('MAIN_CANDIDATE_IMPORT_DRIFT')
 return receipt

@contextlib.contextmanager
def locks():
 release=PLIST.with_name('.com.lexi.v4.scheduler.release.lock.mutex');fd=os.open(release,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);opened=[]
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  for name in ('A_LONG.lock','DEFAULT.lock'):
   p=LANES/name;before=p.lstat();lane=os.open(p,os.O_RDONLY|os.O_NOFOLLOW);opened.append(lane);held=os.fstat(lane)
   if (before.st_dev,before.st_ino)!=(held.st_dev,held.st_ino):raise ValueError('MAIN_LANE_LOCK_DRIFT')
   fcntl.flock(lane,fcntl.LOCK_EX|fcntl.LOCK_NB)
  yield
 finally:
  for lane in reversed(opened):os.close(lane)
  os.close(fd)

def require_idle(path,digest,process):
 observation=json.loads(checked(path,digest).read_bytes());now=time.time();observed=observation.get('observed_at_unix')
 if (observation.get('status')!='ROOT_NO_HEALTHY_MAIN_WORK_VERIFIED' or observation.get('healthy_active_work') is not False
     or observation.get('pid')!=process['pid'] or observation.get('plist_sha256')!=file_sha(PLIST)
     or not isinstance(observed,(int,float)) or not 0<=now-observed<=120):raise ValueError('MAIN_FRESH_IDLE_RECEIPT_REQUIRED')
 children=subprocess.run(['pgrep','-P',str(process['pid'])],capture_output=True,text=True)
 if children.returncode not in (0,1) or children.stdout.strip():raise ValueError('MAIN_ACTIVE_CHILDREN_PRESENT')

def unload():
 current=service_state()
 if current is None:return
 result=launch('bootout',JOB)
 if result.returncode:raise RuntimeError('MAIN_BOOTOUT_FAILED:'+result.stderr)
 deadline=time.monotonic()+20
 while time.monotonic()<deadline:
  if service_state() is None:return
  time.sleep(.2)
 raise RuntimeError('MAIN_UNLOAD_TIMEOUT')

def atomic_plist(raw):
 mode=PLIST.stat().st_mode&0o777
 with tempfile.NamedTemporaryFile(dir=PLIST.parent,prefix='.v4-f10-main-',delete=False) as f:
  p=Path(f.name)
  try:f.write(raw);f.flush();os.fsync(f.fileno());p.chmod(mode);os.replace(p,PLIST);sync(PLIST.parent)
  finally:p.unlink(missing_ok=True)

def bootstrap(expected_root,tracking=None):
 result=launch('bootstrap',DOMAIN,str(PLIST))
 if result.returncode:raise RuntimeError('MAIN_BOOTSTRAP_FAILED:'+result.stderr)
 deadline=time.monotonic()+30
 while time.monotonic()<deadline:
  try:process=service_state()
  except (ValueError,subprocess.SubprocessError,OSError):process=None
  if process:
   if process['root']!=str(expected_root):raise ValueError('MAIN_BOOTSTRAP_ROOT_CONFLICT')
   if tracking is not None:tracking(process)
   return process
  time.sleep(.2)
 raise RuntimeError('MAIN_BOOTSTRAP_TIMEOUT')

def recover_previous(previous,desired,expected_process,tracking):
 current=PLIST.read_bytes()
 if current not in (previous,desired):raise ValueError('MAIN_RECOVERY_PLIST_CONFLICT')
 process=service_state()
 if process and current==previous:
  if process!=expected_process:raise ValueError('MAIN_RECOVERY_PREVIOUS_PROCESS_CHANGED')
  return process
 if process:
  if current!=desired or not tracking.get('process') or process!=tracking['process']:raise ValueError('MAIN_RECOVERY_DESIRED_PROCESS_CHANGED')
  unload()
 if PLIST.read_bytes()!=current:raise ValueError('MAIN_RECOVERY_POST_UNLOAD_CAS')
 if current!=previous:atomic_plist(previous)
 return bootstrap(Path(plistlib.loads(previous)['EnvironmentVariables']['V4_APP_ROOT']))

def switch(receipt_sha,idle_path,idle_sha,rollback=False,activation_sha=None):
 T=target()
 with locks():
  receipt=verify(receipt_sha);old=(T/'config/before.plist').read_bytes();new=(T/'config/candidate.plist').read_bytes()
  if rollback:
   active=json.loads(checked(T/'activation.json',activation_sha).read_bytes());expected_sha=receipt['candidate_plist_sha256'];expected_process=active['process']
   if active.get('preparation_sha256')!=receipt_sha:raise ValueError('MAIN_ROLLBACK_RECEIPT_CONFLICT')
  else:
   if (T/'attempt.json').exists() or (T/'activation.json').exists():raise ValueError('MAIN_ATTEMPT_EXISTS_USE_RECOVERY')
   expected_sha=BASE_PLIST_SHA;expected_process=receipt['base_process']
  assert_active(expected_sha,expected_process);require_idle(idle_path,idle_sha,expected_process)
  previous,desired=(new,old) if rollback else (old,new);tracking={};attempt={};capture=None
  if not rollback:
   attempt={'schema':'v4.f10_main_attempt.v1','status':'BEFORE_UNLOAD','preparation_sha256':receipt_sha,'before_process':expected_process,
            'before_plist_sha256':BASE_PLIST_SHA,'candidate_plist_sha256':receipt['candidate_plist_sha256'],'candidate_manifest_sha256':receipt['manifest']['sha256'],'candidate_process':None}
   attempt_ref=write_json(T/'attempt.json',attempt)
   def capture(process):
    tracking['process']=process
    payload={**attempt,'status':'CANDIDATE_PROCESS_CAPTURED','candidate_process':process}
    checked(T/'attempt.json',attempt_ref['sha256']);temp=T/'attempt.captured.json';updated=write_json(temp,payload)
    checked(T/'attempt.json',attempt_ref['sha256']);os.replace(temp,T/'attempt.json');sync(T)
  assert_active(expected_sha,expected_process);require_idle(idle_path,idle_sha,expected_process)
  try:
   unload()
   if file_sha(PLIST)!=expected_sha:raise ValueError('MAIN_POST_UNLOAD_PLIST_CAS')
   atomic_plist(desired);proc=bootstrap(Path(plistlib.loads(desired)['EnvironmentVariables']['V4_APP_ROOT']),tracking=capture if not rollback else lambda p:tracking.update(process=p))
   outcome={'status':'MAIN_ROLLBACK_VERIFIED' if rollback else 'MAIN_ACTIVATED_VERIFIED','preparation_sha256':receipt_sha,'process':proc,'plist_sha256':sha(desired),'natural_daily':'NOT_RUN',**FLAGS}
   ref=write_json(T/('rollback.json' if rollback else 'activation.json'),outcome)
  except BaseException as primary:
   try:recover_previous(previous,desired,expected_process,tracking)
   except BaseException as recovery:raise RuntimeError(f'MAIN_SWITCH_FAILED:{primary!r};RECOVERY_FAILED:{recovery!r}') from primary
   raise RuntimeError(f'MAIN_SWITCH_FAILED:{primary!r};RECOVERY_VERIFIED') from primary
  print(json.dumps({'status':outcome['status'],'receipt':ref,'process':proc}))

def recover(receipt_sha,attempt_sha,idle_path,idle_sha):
 T=target()
 with locks():
  receipt=verify(receipt_sha);attempt=json.loads(checked(T/'attempt.json',attempt_sha).read_bytes())
  if (T/'activation.json').exists():raise ValueError('MAIN_ACTIVATION_EXISTS_USE_ROLLBACK')
  if (attempt.get('preparation_sha256')!=receipt_sha or attempt.get('before_plist_sha256')!=BASE_PLIST_SHA
      or attempt.get('candidate_plist_sha256')!=receipt['candidate_plist_sha256'] or attempt.get('candidate_manifest_sha256')!=receipt['manifest']['sha256']
      or attempt.get('before_process')!=receipt['base_process']):raise ValueError('MAIN_ATTEMPT_IDENTITY_CONFLICT')
  current=service_state()
  if current:require_idle(idle_path,idle_sha,current)
  process=recover_previous((T/'config/before.plist').read_bytes(),(T/'config/candidate.plist').read_bytes(),attempt['before_process'],{'process':attempt.get('candidate_process')})
  ref=write_json(T/'recovery.json',{'status':'MAIN_INTERRUPTED_RECOVERY_VERIFIED','preparation_sha256':receipt_sha,'attempt_sha256':attempt_sha,'process':process,**FLAGS});print(json.dumps(ref))

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','check','activate','rollback','recover'));p.add_argument('--receipt-sha256');p.add_argument('--idle-receipt');p.add_argument('--idle-sha256');p.add_argument('--activation-sha256');p.add_argument('--attempt-sha256');a=p.parse_args()
 if a.action=='prepare':prepare();return
 if a.action=='check':
  r=verify(a.receipt_sha256);assert_active(BASE_PLIST_SHA,r['base_process']);print(json.dumps({'status':'MAIN_PREPARED_PREFLIGHT_PASS','manifest':r['manifest']}));return
 if not a.idle_receipt or not a.idle_sha256:raise ValueError('MAIN_IDLE_RECEIPT_REQUIRED')
 if a.action=='recover':recover(a.receipt_sha256,a.attempt_sha256,a.idle_receipt,a.idle_sha256)
 else:switch(a.receipt_sha256,a.idle_receipt,a.idle_sha256,a.action=='rollback',a.activation_sha256)
if __name__=='__main__':main()
