"""Fixed Main/API next-spawn drain coordinator. Default is read-only.
A root helper only arms next invocation; all lifecycle remains uid501.
No disable, no original bootout, no second TERM, no timeout kill, no auto rollback.
"""
from __future__ import annotations
import argparse,contextlib,fcntl,hashlib,json,os,plistlib,re,shlex,signal,stat,subprocess,sys,tempfile,time,types
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROLES=('main','api')
LABELS={'main':'com.lexi.v35.scheduler','api':'com.lexi.v35.api-only'}
class Stop(RuntimeError):pass
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(d):return json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def read(p):
 p=Path(p)
 if p.resolve()!=p.absolute():raise Stop('SYMLINK_OR_ESCAPE:'+str(p))
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  if not stat.S_ISREG(os.fstat(fd).st_mode):raise Stop('NOT_REGULAR')
  with os.fdopen(fd,'rb',closefd=False) as f:return f.read()
 finally:os.close(fd)
def pin(p,h):
 b=read(p)
 if sha(b)!=h:raise Stop('SHA_DRIFT:'+str(p))
 return b
def load(p):return json.loads(read(p))
def save(p,d):
 p=Path(p);fd,t=tempfile.mkstemp(prefix='.'+p.name+'.',dir=p.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(json.dumps(d,ensure_ascii=False,indent=2).encode()+b'\n');f.flush();os.fsync(f.fileno())
  os.replace(t,p);fd=os.open(p.parent,os.O_RDONLY)
  try:os.fsync(fd)
  finally:os.close(fd)
 finally:
  if os.path.exists(t):os.unlink(t)
metadata=types.ModuleType('r7_metadata')
exec(compile(pin(HERE/'plist_metadata.py','0c486cb4a52294f155e99a00465c9db38fbba0b6b282223f6f92f6061f204c98'),str(HERE/'plist_metadata.py'),'exec'),metadata.__dict__)
def rewritten(before,release):
 old=str(Path(before['WorkingDirectory']).parent);new=str(Path(release['app_root']).parent);oldsha=before['EnvironmentVariables']['V35_RELEASE_MANIFEST_SHA256']
 def rec(v):
  if isinstance(v,str):return v.replace(old,new).replace(oldsha,release['manifest_sha256'])
  if isinstance(v,list):return [rec(x) for x in v]
  if isinstance(v,dict):return {k:rec(x) for k,x in v.items()}
  return v
 result=rec(before);result['EnvironmentVariables']['V35_RELEASE_ID']=release['release_id'];result['EnvironmentVariables']['V35_RELEASE_MANIFEST_SHA256']=release['manifest_sha256']
 if release['role']=='stage':result['EnvironmentVariables']['PYTHONPATH']=release['app_root']+'/upstreams:'+release['app_root']
 return result
def validate_plan(p):
 if p['schema']!='v4.r7.integrated_control.v1' or [x['label'] for x in p['operations']]!=list(LABELS.values())+['com.lexi.stage-center.scheduler','com.lexi.stage-center.a-opening-precapture']:raise Stop('FIXED_SCOPE')
 if p['RESEARCH_ONLY'] is not True or any(p.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):raise Stop('SAFETY')
 if p['guard_program']!='/bin/sleep' or p['guard_seconds']!=604800:raise Stop('GUARD_SCOPE')
 for r in p['operations']:
  if r['plist']!='/Users/lexi/Library/LaunchAgents/'+r['label']+'.plist':raise Stop('PLIST_PATH')
  for key in ('before_file','after_file'):
   if Path(r[key]).parent!=HERE:raise Stop('OWNED_DEFINITION_PATH')
  b=plistlib.loads(pin(r['before_file'],r['before_sha256']));a=plistlib.loads(pin(r['after_file'],r['after_sha256']));release=next(x for x in p['releases'] if x['role']==r['role'])
  if a!=rewritten(b,release) or b['Label']!=r['label'] or a['Label']!=r['label']:raise Stop('NON_BINDING_CHANGE')
  if metadata.digest(r['plist_metadata'])!=r['plist_metadata_sha256']:raise Stop('METADATA_DIGEST')
 for r in p['releases']:
  m=load(r['candidate_manifest'])
  if sha(read(r['candidate_manifest']))!=r['manifest_sha256'] or m['app_root']!=r['app_root'] or m['release_id']!=r['release_id']:raise Stop('CANDIDATE_MANIFEST')
  rows=m['application_inventory']['entries'];by={x['path']:x['sha256'] for x in rows};app=Path(r['candidate_app'])
  if m['application_inventory']['aggregate_sha256']!=sha(canonical(rows)) or len(by)!=len(rows) or len(rows)!=r['file_count']:raise Stop('INVENTORY')
  if any(x.is_symlink() for x in app.rglob('*')) or {str(x.relative_to(app)) for x in app.rglob('*') if x.is_file()}!=set(by):raise Stop('INVENTORY_SET')
  for row in rows:
   pin(app/row['path'],row['sha256'])
   if f"{stat.S_IMODE((app/row['path']).stat().st_mode):04o}"!=row['mode']:raise Stop('FILE_MODE')
  base=load(r['baseline_manifest']);old={x['path']:x['sha256'] for x in base['app_files']}
  if sha(read(r['baseline_manifest']))!=r['baseline_manifest_sha256'] or set(old)-set(by) or {k:v for k,v in by.items() if v!=old.get(k)}!=r['delta']:raise Stop('EXACT_DELTA')
 return True

def render_root_helper(p,identities,operation_id,expires_epoch,coordinator=None):
 """Return shell text, no execution. Never interpolates executable user input."""
 if not re.fullmatch('[0-9a-f]{32}',operation_id) or not isinstance(expires_epoch,int):raise Stop('REQUEST_ID')
 if set(identities)!=set(ROLES):raise Stop('REQUEST_IDENTITIES')
 target='/private/var/tmp/v4-r7-nextspawn-'+operation_id;q=shlex.quote
 lines=['#!/bin/sh','set -eu','PATH=/usr/bin:/bin:/usr/sbin:/sbin','export PATH LC_ALL=C','[ "$#" -eq 0 ] || exit 2','[ "$(/usr/bin/id -u)" = 0 ] || { echo ROOT_REQUIRED >&2; exit 2; }',f'[ "$(/bin/date +%s)" -le {expires_epoch} ] || {{ echo REQUEST_EXPIRED >&2; exit 2; }}',f'[ "$(/usr/bin/shasum -a 256 /bin/sleep | /usr/bin/awk \'{{print $1}}\')" = {p["guard_program_sha256"]} ] || exit 2',"/usr/bin/codesign -v -R='anchor apple' /bin/sleep"]
 if coordinator is None:
  lines += ['echo NO_ACTIVE_COORDINATOR_REVIEW_EXAMPLE_ONLY >&2','exit 2']
 else:
  if not isinstance(coordinator['pid'],int) or not re.fullmatch('[0-9a-f]{64}',coordinator['ps_sha256']) or not re.fullmatch('[0-9a-f]{64}',coordinator['ready_sha256']):raise Stop('COORDINATOR_IDENTITY')
  ready=HERE/('owned-request-'+operation_id+'.json')
  lines += [f'[ \"$(/bin/ps -ww -p {coordinator["pid"]} -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk \'{{print $1}}\')\" = {coordinator["ps_sha256"]} ] || {{ echo COORDINATOR_NOT_ALIVE >&2; exit 2; }}',f'[ \"$(/usr/bin/shasum -a 256 {q(str(ready))} | /usr/bin/awk \'{{print $1}}\')\" = {coordinator["ready_sha256"]} ] || {{ echo REQUEST_CHECKPOINT_DRIFT >&2; exit 2; }}']
 for role in ROLES:
  i=identities[role];r=next(x for x in p['operations'] if x['role']==role)
  if i['pid']!=p['expected_original_pids'][role] or not re.fullmatch('[0-9a-f]{64}',i['ps_sha256']):raise Stop('REQUEST_ORIGINAL_IDENTITY')
  lines += [f'[ "$(/bin/ps -ww -p {i["pid"]} -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk \'{{print $1}}\')" = {i["ps_sha256"]} ] || {{ echo {role.upper()}_PID_DRIFT >&2; exit 2; }}',f'[ "$(/bin/launchctl print gui/501/{r["label"]} | /usr/bin/awk \'$1 == "pid" && $2 == "=" {{print $3}}\')" = {i["pid"]} ] || exit 2',f'[ "$(/usr/bin/shasum -a 256 {q(r["plist"])} | /usr/bin/awk \'{{print $1}}\')" = {r["before_sha256"]} ] || exit 2']
 lines+=['umask 022',f'/bin/mkdir -m 755 {target} || {{ echo EXISTING_INTENT_NO_RETRY >&2; exit 2; }}',f"printf '%s\\n' {sha(canonical(p))} > {target}/plan_sha256"]
 for role in ROLES:
  label=LABELS[role];lines += [f"printf '%s\\n' INTENT > {target}/{role}.intent",'set +e',f'/bin/launchctl debug gui/501/{label} --program /bin/sleep -- {p["guard_seconds"]} > {target}/{role}.stdout 2> {target}/{role}.stderr','result=$?','set -e',f"printf '%s\\n' \"$result\" > {target}/{role}.rc",'[ "$result" -eq 0 ] || { echo DEBUG_FAILED_NO_RETRY >&2; exit "$result"; }']
 lines += [f"printf '%s\\n' COMPLETE > {target}/COMPLETE",f"printf '%s\\n' {target}"]
 return '\n'.join(lines)+'\n'

def require_handoff(p,h):
 """The parent freezes data only after the real owner finishes; no stale pin reuse."""
 if not re.fullmatch('[0-9a-f]{32}',str(h.get('operation_id',''))) or h.get('root_ack_dir')!='/private/var/tmp/v4-r7-nextspawn-'+h['operation_id']:raise Stop('HANDOFF_OPERATION_SCOPE')
 if h.get('plan_sha256')!=sha(canonical(p)) or h.get('legitimate_daily_producer_complete') is not True or h.get('all_daily_descendants_absent') is not True:raise Stop('DAILY_PRODUCER_NOT_CLOSED')
 if h.get('no_active_dependent_api_query') is not True or h.get('api_brief_new_connection_gap_coordinated') is not True:raise Stop('API_COORDINATION_MISSING')
 if time.time()>h['expires_epoch'] or time.time()<h['observed_epoch'] or h['expires_epoch']-h['observed_epoch']>300:raise Stop('FRESH_HANDOFF_WINDOW')
 if not h.get('data_pins') or not h.get('data_stats') or h.get('pdf_admission_disabled_by_existing_time_window') is not True or h.get('no_live_pdf_child') is not True:raise Stop('MISSING_DATA_OR_PDF_PROOF')
 observations=h.get('role_observations')
 if not isinstance(observations,dict) or set(observations)!=set(ROLES):raise Stop('EXPLICIT_ROLE_OBSERVATIONS_REQUIRED')
 for role,observation in observations.items():
  if not isinstance(observation,dict) or set(observation)!={'disposition','checkpoint_phase','current_identity'} or observation['disposition'] not in ('ORIGINAL_UNTOUCHED','IN_PROGRESS','COMPLETED'):raise Stop('ROLE_OBSERVATION_SCHEMA')
 if observations['main']['disposition']=='ORIGINAL_UNTOUCHED' and h.get('all_current_main_children_and_jobs_finished') is not True:raise Stop('MAIN_INITIAL_IDLE_PROOF_REQUIRED')
 if h.get('no_parallel_lifecycle_owner') is not True:raise Stop('COORDINATION_REQUIRED')
 for role in ROLES:
  if h['identities'][role]['pid']!=p['expected_original_pids'][role]:raise Stop('OWNER_PID_DRIFT')
 return True

def checkpoint_path(root,role):return Path(root)/('owned-'+role+'.checkpoint.json')
def prepare_role_checkpoints(p,h,ops,root=HERE):
 """Both durable role records precede exposing the root helper or any TERM."""
 paths={role:checkpoint_path(root,role) for role in ROLES}
 if any(path.exists() for path in paths.values()):raise Stop('EXISTING_CHECKPOINT_RESUME_REQUIRED')
 for role in ROLES:
  observation=h['role_observations'][role]
  if observation!={'disposition':'ORIGINAL_UNTOUCHED','checkpoint_phase':'WAITING_ROOT_ACK','current_identity':h['identities'][role]}:raise Stop('INITIAL_ROLE_NOT_UNTOUCHED')
  ops.original(role,h['identities'][role])
 states={}
 for role in ROLES:
  state=dict(schema='v4.r7.role_checkpoint.r1',phase='WAITING_ROOT_ACK',operation_id=h['operation_id'],plan_sha256=sha(canonical(p)),original_identity=h['identities'][role],children={})
  save(paths[role],state);states[role]=state
 return states

def resume_role_checkpoints(p,h,ops,root=HERE):
 """Load both before actions; missing/ambiguous state never infers untouched."""
 states={}
 for role in ROLES:
  path=checkpoint_path(root,role)
  if not path.exists():raise Stop('MISSING_ROLE_CHECKPOINT_NO_UNTOUCHED_INFERENCE')
  state=load(path)
  if state.get('schema')!='v4.r7.role_checkpoint.r1' or state.get('operation_id')!=h['operation_id'] or state.get('plan_sha256')!=sha(canonical(p)) or state.get('original_identity')!=h['identities'][role]:raise Stop('CHECKPOINT_IMMUTABLE_SCOPE')
  observation=h['role_observations'][role];phase=state.get('phase')
  if observation['checkpoint_phase']!=phase:raise Stop('OBSERVATION_CHECKPOINT_PHASE')
  if phase=='DONE':
   if observation['disposition']!='COMPLETED' or not state.get('new') or observation['current_identity']!=state['new']:raise Stop('COMPLETED_ROLE_OBSERVATION')
  elif phase in ('WAITING_ROOT_ACK','ARMED'):
   if observation['disposition']!='ORIGINAL_UNTOUCHED' or observation['current_identity']!=state['original_identity'] or state.get('term_sent') or state.get('children'):raise Stop('AMBIGUOUS_UNTOUCHED_ROLE')
   ops.original(role,state['original_identity'])
  else:
   if phase not in ('TERM_INTENT','DRAINING','GUARD_CONFIRMED','GUARD_BOOTOUT_INTENT','WAIT_GUARD_GONE','CAS_INTENT','PLIST_APPLIED','BOOTSTRAP_INTENT','READBACK') or observation['disposition']!='IN_PROGRESS':raise Stop('IN_PROGRESS_ROLE_OBSERVATION')
   service=ops.service(role);current=ops.identity(service['pid']) if service['pid'] else None
   if current!=observation['current_identity']:raise Stop('IN_PROGRESS_OWNER_DRIFT')
  states[role]=state
 return states

class Live:
 def __init__(self,p):self.p=p
 def cmd(self,args,missing=False):
  try:r=subprocess.run(args,capture_output=True,text=True,timeout=15,env={**os.environ,'LC_ALL':'C'})
  except subprocess.TimeoutExpired as e:raise Stop('UNKNOWN_COMMAND_OUTCOME_NO_RETRY') from e
  if r.returncode and not missing:raise Stop('COMMAND_FAILED_NO_RETRY:'+str(args[:3])+':'+str(r.returncode))
  return r
 def identity(self,pid):
  r=self.cmd(['/bin/ps','-ww','-p',str(pid),'-o','lstart=,command='],True)
  if r.returncode==1 and not r.stdout:return None
  if r.returncode:raise Stop('IDENTITY_UNKNOWN')
  return {'pid':pid,'ps_sha256':sha(r.stdout.encode()),'ps_text':r.stdout}
 def service(self,role):
  r=self.cmd(['/bin/launchctl','print','gui/501/'+LABELS[role]],True)
  if r.returncode:
   if r.returncode==113 and 'Could not find service' in r.stderr:return {'loaded':False,'pid':None}
   raise Stop('SERVICE_STATE_UNKNOWN')
  pid=re.search(r'^\s*pid = (\d+)$',r.stdout,re.M)
  return dict(loaded=True,pid=int(pid[1]) if pid else None,text=r.stdout)
 def rows(self):
  out={}
  for line in self.cmd(['/bin/ps','-ww','-axo','pid=,ppid=,command=']).stdout.splitlines():
   a=line.split(None,2)
   if len(a)==3:out[int(a[0])]={'ppid':int(a[1]),'command':a[2]}
  return out
 def descendants(self,pid):
  rows=self.rows();seen=set();parents={pid}
  while parents:
   parents={i for i,r in rows.items() if r['ppid'] in parents and i not in seen};seen|=parents
  return {str(i):self.identity(i) for i in seen}
 def protection(self,h):
  g=self.p['owner_guard'];s=Path(g['path']).lstat()
  if not stat.S_ISREG(s.st_mode) or (s.st_dev,s.st_ino)!=(g['device'],g['inode']):raise Stop('OWNER_LOCK_PATH_DRIFT')
  v=json.loads(pin(g['marker'],g['marker_sha256']))
  if v.get('active') is not False or v.get('phase')!='DONE':raise Stop('ORIGINAL_OWNER_NOT_RELEASED')
  for r in self.p['static_protected_pins']+self.p['drain_source_pins']+self.p['workbench_configs']+h['data_pins']:pin(r['path'],r['sha256'])
  for r in h['data_stats']:
   s=Path(r['path']).lstat()
   if not stat.S_ISREG(s.st_mode) or (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)!=(r['device'],r['inode'],r['size'],r['mtime_ns']):raise Stop('PROTECTED_DATA_STAT_DRIFT')
 def original(self,role,i):
  r=next(x for x in self.p['operations'] if x['role']==role)
  pin(r['plist'],r['before_sha256']);metadata.require(r['plist'],r['plist_metadata'])
  if self.identity(i['pid'])!=i or self.service(role)['pid']!=i['pid']:raise Stop('ORIGINAL_OWNER_CHANGED')
  cwd=self.cmd(['/usr/sbin/lsof','-a','-p',str(i['pid']),'-d','cwd','-Fn']).stdout
  if [x[1:] for x in cwd.splitlines() if x.startswith('n')]!=[r['old_app_root']]:raise Stop('ORIGINAL_CWD')
 def initial_main_idle(self,old):
  if self.descendants(old['pid']):raise Stop('MAIN_CHILDREN_NOT_NATURALLY_FINISHED')
  # Read persisted admission states without acquiring job, lane, model or data locks.
  config=next(x for x in self.p['workbench_configs'] if x['role']=='main')
  if config['capture_enabled'] is not False:raise Stop('CAPTURE_ENABLED_DRAIN_NOT_REVIEWED')
  root=Path(config['state_root'])/'manager_workbench'
  paths=list((root/'attempts').glob('*.json'))+list((root/'cursors').glob('oversold_daily_*.json'))
  if len(paths)>20000:raise Stop('JOB_READ_BOUND')
  for path in paths:
   d=json.loads(read(path))
   if d.get('state') in ('QUEUED','RUNNING'):raise Stop('CURRENT_JOB_NOT_NATURALLY_FINISHED:'+str(path))
 def pdf_boundary(self):
  # Existing PDF admission is local02:00–08:30. Outside it no hook can add a child.
  from datetime import datetime
  from zoneinfo import ZoneInfo
  t=datetime.now(ZoneInfo('Asia/Shanghai'));minute=t.hour*60+t.minute
  if 120<=minute<=510:raise Stop('PDF_ADMISSION_WINDOW')
  if any('--pdf-queue-tick' in r['command'] or 'ops.drain_zsxq_pdf_queue' in r['command'] or 'ops/drain_zsxq_pdf_queue.py' in r['command'] for r in self.rows().values()):raise Stop('LIVE_PDF_CHILD')
 def ack(self,h):
  root=Path(h['root_ack_dir']);s=root.lstat()
  if root.parent!=Path('/private/var/tmp') or root.name!='v4-r7-nextspawn-'+h['operation_id'] or not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise Stop('ROOT_ACK_DIRECTORY')
  for name,want in [('plan_sha256',sha(canonical(self.p))),('main.rc','0'),('api.rc','0'),('COMPLETE','COMPLETE')]:
   f=root/name;s=f.lstat()
   if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022 or read(f).decode().strip()!=want:raise Stop('ROOT_ACK_INVALID')
 def term(self,role,i):
  self.pdf_boundary();self.original(role,i);os.kill(i['pid'],signal.SIGTERM)
 def no_old_root_processes(self,role):
  root=next(x for x in self.p['operations'] if x['role']==role)['old_app_root']
  if any(root+'/' in r['command'] for r in self.rows().values()):raise Stop('OLD_RELEASE_PROCESS_STILL_RUNNING')
 def guard(self,role,old):
  s=self.service(role)
  if not s['loaded'] or not s['pid'] or s['pid']==old['pid']:raise Stop('NEXTSPAWN_GUARD_NOT_CONFIRMED')
  i=self.identity(s['pid'])
  if not i or not re.search(r'(?:^|\s)/bin/sleep '+str(self.p['guard_seconds'])+r'\s*$',i['ps_text']):raise Stop('UNEXPECTED_REPLACEMENT_NO_SIGNAL')
  return i
 def bootout_guard(self,role,guard,old):
  if self.identity(old['pid']) is not None or self.guard(role,old)!=guard:raise Stop('ORIGINAL_OR_GUARD_CHANGED_NO_BOOTOUT')
  self.cmd(['/bin/launchctl','bootout','gui/501/'+LABELS[role]])
 def absent(self,role):
  if self.service(role)['loaded']:raise Stop('SERVICE_NOT_ABSENT')
 def cas(self,role,reverse=False):
  r=next(x for x in self.p['operations'] if x['role']==role);self.absent(role)
  current,target=('after','before') if reverse else ('before','after');a=r[current+'_sha256'];b=r[target+'_sha256'];raw=pin(r[target+'_file'],b)
  pin(r['plist'],a);metadata.require(r['plist'],r['plist_metadata']);p=Path(r['plist']);fd,t=tempfile.mkstemp(prefix='.'+p.name+'.r7.',dir=p.parent)
  try:
   with os.fdopen(fd,'w+b') as f:f.write(raw);f.flush();os.fsync(f.fileno());metadata.apply_fd(f.fileno(),r['plist_metadata'])
   pin(t,b);pin(p,a);metadata.require(p,r['plist_metadata']);self.absent(role);os.replace(t,p);fd=os.open(p.parent,os.O_RDONLY)
   try:os.fsync(fd)
   finally:os.close(fd)
  finally:
   if os.path.exists(t):os.unlink(t)
  pin(p,b);metadata.require(p,r['plist_metadata'])
 def bootstrap(self,role):
  self.absent(role);r=next(x for x in self.p['operations'] if x['role']==role);self.cmd(['/bin/launchctl','bootstrap','gui/501',r['plist']])
 def completed(self,role,expected):
  r=next(x for x in self.p['operations'] if x['role']==role)
  pin(r['plist'],r['after_sha256']);metadata.require(r['plist'],r['plist_metadata'])
  current=self.new(role)
  if not current or current!=expected:raise Stop('COMPLETED_OWNER_CHANGED')
  return current
 def new(self,role):
  s=self.service(role);r=next(x for x in self.p['operations'] if x['role']==role);release=next(x for x in self.p['releases'] if x['role']==role)
  if not s['loaded'] or not s['pid']:raise Stop('NEW_OWNER_NOT_CONFIRMED')
  for k,v in [('V35_APP_ROOT',r['new_app_root']),('V35_RELEASE_ID',release['release_id']),('V35_RELEASE_MANIFEST_SHA256',release['manifest_sha256'])]:
   if not re.search(r'^\s*'+k+' => '+re.escape(v)+r'\s*$',s['text'],re.M):raise Stop('NEW_LOADED_BINDING')
  i=self.identity(s['pid']);cwd=self.cmd(['/usr/sbin/lsof','-a','-p',str(s['pid']),'-d','cwd','-Fn']).stdout
  if [x[1:] for x in cwd.splitlines() if x.startswith('n')]!=[r['new_app_root']]:raise Stop('NEW_CWD')
  return i

class Recipe:
 """One intent per irreversible observation boundary; unknown outcomes stop."""
 def __init__(self,p,h,ops,state,checkpoint):self.p=p;self.h=h;self.o=ops;self.s=state;self.path=checkpoint
 def record(self,phase,**kw):self.s.update(phase=phase,**kw);save(self.path,self.s)
 def step(self,role):
  o=self.o;s=self.s;old=self.h['identities'][role];phase=s['phase'];o.protection(self.h)
  if phase=='WAITING_ROOT_ACK':
   o.ack(self.h);o.original(role,old);self.record('ARMED')
  elif phase=='ARMED':
   require_handoff(self.p,self.h);o.ack(self.h);o.pdf_boundary();o.original(role,old)
   if role=='main':o.initial_main_idle(old)
   children=o.descendants(old['pid']);self.record('TERM_INTENT',children=children)
   o.term(role,old);self.record('DRAINING',term_sent=True)
  elif phase=='TERM_INTENT':
   if o.identity(old['pid']) is not None:raise Stop('TERM_OUTCOME_UNKNOWN_NO_REPEAT')
   self.record('DRAINING',term_sent='UNKNOWN_ORIGINAL_EXIT_CONFIRMED')
  elif phase=='DRAINING':
   i=o.identity(old['pid'])
   if i is not None:
    if i!=old or o.service(role)['pid']!=old['pid']:raise Stop('OWNER_CHANGED_DURING_DRAIN')
    s['children'].update(o.descendants(old['pid']));self.record('DRAINING');return False
   for pid,i in s['children'].items():
    current=o.identity(int(pid))
    if current==i:return False
    # PID reuse is not the original child; never signal it.
   service=o.service(role)
   if service['loaded'] and service['pid'] is None:return False
   o.no_old_root_processes(role);guard=o.guard(role,old);self.record('GUARD_CONFIRMED',guard=guard)
  elif phase=='GUARD_CONFIRMED':
   self.record('GUARD_BOOTOUT_INTENT');o.bootout_guard(role,s['guard'],old);self.record('WAIT_GUARD_GONE')
  elif phase=='GUARD_BOOTOUT_INTENT':
   o.absent(role);self.record('WAIT_GUARD_GONE')
  elif phase=='WAIT_GUARD_GONE':
   o.absent(role);o.no_old_root_processes(role)
   if o.identity(s['guard']['pid'])==s['guard']:return False
   self.record('CAS_INTENT');o.cas(role);self.record('PLIST_APPLIED')
  elif phase=='CAS_INTENT':
   r=next(x for x in self.p['operations'] if x['role']==role);h=sha(read(r['plist']))
   if h==r['before_sha256']:o.cas(role)
   elif h!=r['after_sha256']:raise Stop('UNKNOWN_CAS_STATE')
   metadata.require(r['plist'],r['plist_metadata']);self.record('PLIST_APPLIED')
  elif phase=='PLIST_APPLIED':
   self.record('BOOTSTRAP_INTENT');o.bootstrap(role);self.record('READBACK')
  elif phase=='BOOTSTRAP_INTENT':raise Stop('BOOTSTRAP_OUTCOME_UNKNOWN_NO_REPEAT')
  elif phase=='READBACK':self.record('DONE',new=o.new(role));return True
  elif phase=='DONE':o.completed(role,s['new']);return True
  else:raise Stop('UNKNOWN_PHASE')
  return False

def verify_review(path,h):
 r=json.loads(pin(path,h));frozen=read(HERE/'FROZEN_CONTROL_R7.json');d=json.loads(frozen)
 if r.get('verdict')!='PASS' or r.get('frozen_control_sha256')!=sha(frozen):raise Stop('INDEPENDENT_REVIEW_REQUIRED')
 for name,h in d['files'].items():pin(HERE/name,h)

def cli():
 ap=argparse.ArgumentParser();ap.add_argument('--execute-reviewed',action='store_true');ap.add_argument('--handoff',type=Path);ap.add_argument('--handoff-sha256');ap.add_argument('--review',type=Path);ap.add_argument('--review-sha256');ap.add_argument('--resume',action='store_true');a=ap.parse_args();p=load(HERE/'PLAN_REVIEW_ONLY_R7.json');validate_plan(p)
 if not a.execute_reviewed:print(json.dumps({'status':'PLAN_VALID_NO_ACTION','roles':ROLES}));return
 if os.getuid()!=501 or not a.handoff or not a.handoff_sha256 or not a.review or not a.review_sha256:raise Stop('UID501_FRESH_HANDOFF_REVIEW_REQUIRED')
 verify_review(a.review,a.review_sha256);h=json.loads(pin(a.handoff,a.handoff_sha256))
 # Handoff values are parent-owned fresh observations, not generated from idle assumptions.
 require_handoff(p,h);o=Live(p);g=p['owner_guard'];fd=os.open(g['path'],os.O_RDWR|os.O_NOFOLLOW)
 try:
  s=os.fstat(fd)
  if (s.st_dev,s.st_ino)!=(g['device'],g['inode']):raise Stop('ORIGINAL_GUARD_IDENTITY')
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);o.protection(h)
  # No new app bootstraps until full installed inventory matches reviewed candidate.
  for r in p['releases']:
   m=json.loads(pin(r['manifest'],r['manifest_sha256']));app=Path(r['app_root'])
   expected={x['path'] for x in m['application_inventory']['entries']}
   if any(x.is_symlink() for x in app.rglob('*')) or {str(x.relative_to(app)) for x in app.rglob('*') if x.is_file()}!=expected:raise Stop('INSTALLED_INVENTORY_SET')
   for row in m['application_inventory']['entries']:
    pin(app/row['path'],row['sha256'])
    if f"{stat.S_IMODE((app/row['path']).stat().st_mode):04o}"!=row['mode']:raise Stop('INSTALLED_MODE')
  if not a.resume:
   states=prepare_role_checkpoints(p,h,o,HERE)
   for role in ROLES:o.original(role,h['identities'][role])
   o.pdf_boundary();o.initial_main_idle(h['identities']['main'])
   # Publish one finite request from the actual live coordinator; root helper
   # checks this process identity and exact ready bytes before arming either label.
   ready=HERE/('owned-request-'+h['operation_id']+'.json');helper=HERE/('owned-admin-'+h['operation_id']+'.sh')
   if ready.exists() or helper.exists():raise Stop('EXISTING_REQUEST_NO_REPEAT')
   own=o.identity(os.getpid());request={'phase':'WAITING_ONE_TIME_ADMIN_AUTH','operation_id':h['operation_id'],'plan_sha256':sha(canonical(p)),'coordinator':own,'expires_epoch':h['expires_epoch'],'handoff_sha256':a.handoff_sha256,'role_checkpoint_sha256':{role:sha(read(checkpoint_path(HERE,role))) for role in ROLES}};save(ready,request)
   ci={**own,'ready_sha256':sha(read(ready))};raw=render_root_helper(p,h['identities'],h['operation_id'],int(h['expires_epoch']),ci)
   fd2=os.open(helper,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
   with os.fdopen(fd2,'w') as out:out.write(raw);out.flush();os.fsync(out.fileno())
   print(json.dumps({'status':'WAITING_ONE_TIME_ADMIN_AUTH','helper':str(helper),'sha256':sha(raw.encode()),'expires_epoch':h['expires_epoch']}),flush=True)
   while not (Path(h['root_ack_dir'])/'COMPLETE').exists():
    if time.time()>h['expires_epoch']:raise Stop('ADMIN_REQUEST_EXPIRED_NO_SIGNAL')
    time.sleep(1)
  o.ack(h)
  if a.resume:states=resume_role_checkpoints(p,h,o,HERE)
  for role in ROLES:
   recipe=Recipe(p,h,o,states[role],checkpoint_path(HERE,role))
   while not recipe.step(role):time.sleep(1)
  print(json.dumps({'status':'MAIN_API_BOUND_STILL_REQUIRES_STAGE_AND_TARGET_READBACK','checkpoints':[str(HERE/('owned-'+r+'.checkpoint.json')) for r in ROLES]}))
 finally:os.close(fd)
if __name__=='__main__':
 try:cli()
 except Exception as e:print('STOP:'+str(e),file=sys.stderr);raise SystemExit(2)
