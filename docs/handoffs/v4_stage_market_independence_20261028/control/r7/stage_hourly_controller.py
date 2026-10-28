"""REVIEW_ONLY. Exact two-label, bounded trigger-empty window; never disable/kill.
Default validates a frozen plan only. No unknown-outcome retries/auto rollback.
"""
from __future__ import annotations
import argparse,contextlib,fcntl,hashlib,json,os,plistlib,re,stat,subprocess,time,types
from datetime import datetime
from pathlib import Path
LABELS=('com.lexi.stage-center.scheduler','com.lexi.stage-center.a-opening-precapture')
PREFIX=Path('/Users/lexi/Library/LaunchAgents')
class Stop(RuntimeError):pass
def sha(b):return hashlib.sha256(b).hexdigest()
def read(path):
 p=Path(path)
 if p.resolve()!=p.absolute():raise Stop('SYMLINK_OR_ESCAPE')
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  if not stat.S_ISREG(os.fstat(fd).st_mode):raise Stop('NOT_REGULAR')
  with os.fdopen(fd,'rb',closefd=False) as f:return f.read()
 finally:os.close(fd)
def pin(path,h):
 b=read(path)
 if sha(b)!=h:raise Stop('SHA_DRIFT:'+str(path))
 return b

# Execute only these frozen helper bytes; do not import mutable unverified code.
_METADATA_HELPER=Path(__file__).resolve().with_name('plist_metadata.py')
_METADATA_HELPER_SHA256='0c486cb4a52294f155e99a00465c9db38fbba0b6b282223f6f92f6061f204c98'
metadata=types.ModuleType('r4_plist_metadata')
exec(compile(pin(_METADATA_HELPER,_METADATA_HELPER_SHA256),str(_METADATA_HELPER),'exec'),metadata.__dict__)

def metadata_pin(row):
 expected=row['plist_metadata']
 if metadata.digest(expected)!=row['plist_metadata_sha256']:raise Stop('FROZEN_METADATA_DIGEST')
 metadata.require(row['plist'],expected)

def scope(p):
 if p.get('state')!='READY_FRESH_PARENT_HANDOFF':raise Stop('STAGE_TEMPLATE_NOT_EXECUTABLE')
 if p.get('schema')!='stage_only_control_r4.v1' or tuple(r['label'] for r in p['operations'])!=LABELS:raise Stop('EXACT_TWO_LABELS')
 for r in p['operations']:
  if r['plist']!=str(PREFIX/(r['label']+'.plist')):raise Stop('PLIST_SCOPE')
  metadata_pin(r)
  b=plistlib.loads(pin(r['before_file'],r['before_sha256']));a=plistlib.loads(pin(r['after_file'],r['after_sha256']))
  if b['Label']!=r['label'] or a['Label']!=r['label'] or set(a)!=set(b):raise Stop('PLIST_IDENTITY_KEYS')
  for k in ('RunAtLoad','StartCalendarInterval','StandardErrorPath','StandardOutPath','ProcessType'):
   if b.get(k)!=a.get(k):raise Stop('NON_BINDING_PLIST_DRIFT')
  if b.get('RunAtLoad') is not False or set(b)-{'Label','EnvironmentVariables','ProgramArguments','WorkingDirectory','RunAtLoad','StartCalendarInterval','StandardErrorPath','StandardOutPath','ProcessType'}:raise Stop('UNKNOWN_TRIGGER')
 if any(p.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):raise Stop('SAFETY_FLAGS')
 if p.get('coordinated_no_other_stage_cli') is not True or p.get('window_premise_review')!='KNOWN_CALENDAR_ONLY_NO_PENDING_CATCHUP_ACCEPTED':raise Stop('UNREVIEWED_WINDOW_PREMISE')
 if not p.get('owner_guard') or not p.get('protected_pins') or not p.get('protected_services'):raise Stop('MISSING_GUARD_OR_PROTECTIONS')
 begin=datetime.fromisoformat(p['not_before']);end=datetime.fromisoformat(p['deadline'])
 if begin.tzinfo is None or end.tzinfo is None or end<=begin or not 0<p['budget_seconds']<=300:raise Stop('INVALID_WINDOW_BUDGET')
 for row in p['operations']:
  d=plistlib.loads(read(row['before_file']))
  for t in d['StartCalendarInterval']:
   due=begin.replace(hour=t['Hour'],minute=t['Minute'],second=0,microsecond=0)
   if begin.timestamp()-300<=due.timestamp()<=end.timestamp()+300:raise Stop('CALENDAR_MARGIN_CONFLICT')
  b=plistlib.loads(read(row['before_file']));a=plistlib.loads(read(row['after_file']))
  old_release=str(Path(b['WorkingDirectory']).parent);new_release=str(Path(p['release']['app_root']).parent)
  def rewrite(v):
   if isinstance(v,str):return v.replace(old_release,new_release)
   if isinstance(v,list):return [rewrite(x) for x in v]
   if isinstance(v,dict):return {k:rewrite(x) for k,x in v.items()}
   return v
  expected=rewrite(b);expected['EnvironmentVariables']['PYTHONPATH']=p['release']['app_root']+'/upstreams:'+p['release']['app_root'];expected['EnvironmentVariables']['V35_RELEASE_MANIFEST_SHA256']=p['release']['manifest_sha256'];expected['EnvironmentVariables']['V35_RELEASE_ID']=p['release']['release_id']
  if expected!=a:raise Stop('UNEXPECTED_AFTER_BINDING')
  if p['target_process_roots']!=[b['WorkingDirectory'],p['release']['app_root']]:raise Stop('PROCESS_ROOT_SCOPE')
  if p['release']['manifest']!=str(Path(p['release']['app_root']).parent/'release-manifest.json'):raise Stop('MANIFEST_PATH_SCOPE')

def loaded(text,d,path):
 def field(k):
  m=re.search(r'^\t'+re.escape(k)+r' = (.*)$',text,re.M);return m.group(1) if m else None
 def block(k):
  m=re.search(r'^\t'+re.escape(k)+r' = \{\n(.*?)^\t\}',text,re.M|re.S)
  if not m:raise Stop('MISSING_LOADED_BLOCK:'+k)
  return m.group(1)
 if field('path')!=path or field('type')!='LaunchAgent' or field('program')!=d['ProgramArguments'][0] or field('working directory')!=d['WorkingDirectory']:raise Stop('LOADED_IDENTITY')
 if [x.strip() for x in block('arguments').splitlines() if x.strip()]!=d['ProgramArguments']:raise Stop('LOADED_ARGV')
 env=dict(re.findall(r'^\s*([^\s]+) => (.*)$',block('environment'),re.M))
 if any(env.get(k)!=str(v) for k,v in d['EnvironmentVariables'].items()):raise Stop('LOADED_ENV')
 t=block('event triggers');streams=re.findall(r'^\s*stream = (.*)$',t,re.M);keeps=re.findall(r'^\s*keepalive = (.*)$',t,re.M);observed=[]
 for x in re.findall(r'descriptor = \{(.*?)\}',t,re.S):
  v=dict(re.findall(r'"(\w+)" => (\d+)',x))
  if set(v)!={'Hour','Minute'}:raise Stop('UNKNOWN_CALENDAR_FIELD')
  observed.append((int(v['Hour']),int(v['Minute'])))
 expected=sorted((int(x['Hour']),int(x['Minute'])) for x in d['StartCalendarInterval'])
 if sorted(observed)!=expected or streams!=['com.apple.launchd.calendarinterval']*len(expected) or keeps!=['0']*len(expected):raise Stop('LOADED_TRIGGER_DRIFT')
 if field('active count')!='0' or field('state')!='not running' or field('pid') is not None:raise Stop('ACTIVE_OR_UNKNOWN')
 return True

@contextlib.contextmanager
def original_guard(r):
 fd=os.open(r['path'],os.O_RDWR|os.O_NOFOLLOW)
 try:
  s=os.fstat(fd)
  if not stat.S_ISREG(s.st_mode) or (s.st_dev,s.st_ino)!=(r['device'],r['inode']):raise Stop('ORIGINAL_LOCK_INODE_DRIFT')
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);yield fd
 finally:os.close(fd)

class Live:
 def __init__(self,p,journal):self.p=p;self.journal=journal;self.caf=None
 def record(self,event,**kw):
  with open(self.journal,'a') as f:f.write(json.dumps({'at':datetime.now().astimezone().isoformat(),'event':event,**kw})+'\n');f.flush();os.fsync(f.fileno())
 def command(self,args,missing=False):
  self.record('INTENT',argv=args)
  try:r=subprocess.run(args,text=True,capture_output=True,timeout=8)
  except subprocess.TimeoutExpired as e:raise Stop('UNKNOWN_TIMEOUT_NO_RETRY') from e
  self.record('RESULT',argv=args,rc=r.returncode)
  if r.returncode and not missing:raise Stop('COMMAND_FAILED_NO_RETRY:'+str(r.returncode))
  return r
 def start(self):
  self.t0=time.monotonic();self.w0=time.time();self.wake=self.command(['/usr/sbin/sysctl','kern.waketime','kern.boottime']).stdout
  self.caf=subprocess.Popen(['/usr/bin/caffeinate','-i','-s','-w',str(os.getpid())],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE);time.sleep(.05);self.check()
 def close(self):
  if self.caf is not None and self.caf.poll() is None:self.caf.terminate();self.caf.wait(timeout=3)
 def check(self):
  if self.caf is None or self.caf.poll() is not None:raise Stop('CAFFEINATE_LOST')
  w=time.time();m=time.monotonic()
  if abs(w-self.w0-(m-self.t0))>.5:raise Stop('CLOCK_SLEEP_DRIFT')
  if self.command(['/usr/sbin/sysctl','kern.waketime','kern.boottime']).stdout!=self.wake:raise Stop('WAKE_DETECTED')
  end=datetime.fromisoformat(self.p['deadline']).timestamp()
  if not datetime.fromisoformat(self.p['not_before']).timestamp()<=w or w+10>=end or m-self.t0>self.p['budget_seconds']:raise Stop('WINDOW_EXPIRED')
  g=self.p.get('owner_guard')
  if g:
   v=Path(g['path']).lstat()
   if not stat.S_ISREG(v.st_mode) or (v.st_dev,v.st_ino)!=(g['device'],g['inode']):raise Stop('HELD_GUARD_PATH_DRIFT')
 def protection(self):
  for r in self.p['protected_pins']:pin(r['path'],r['sha256'])
  for r in self.p.get('protected_stats',[]):
   f=Path(r['path']);v=f.lstat()
   if f.is_symlink() or (v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns)!=(r['device'],r['inode'],r['size'],r['mtime_ns']):raise Stop('PROTECTED_STAT_DRIFT')
  for r in self.p['protected_services']:
   x=self.command(['/bin/launchctl','print','gui/501/'+r['label']])
   m=re.search(r'^\tpid = (\d+)$',x.stdout,re.M);pid=int(m.group(1)) if m else None
   if pid!=r['pid']:raise Stop('PROTECTED_SERVICE_PID_DRIFT')
  r=self.p['owner_guard'];v=json.loads(pin(r['marker'],r['marker_sha256']))
  if v.get('active') is not False or v.get('phase')!='DONE':raise Stop('OWNER_NOT_RELEASED')
 def package(self):
  x=self.p['release'];m=json.loads(pin(x['manifest'],x['manifest_sha256']));app=Path(x['app_root'])
  if m['app_root']!=str(app) or m['release_id']!=x['release_id']:raise Stop('RELEASE_IDENTITY')
  inventory=m['application_inventory'];entries=inventory['entries']
  if inventory['entry_count']!=len(entries) or sha(json.dumps(entries,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())!=inventory['aggregate_sha256']:raise Stop('INVENTORY_AGGREGATE')
  by={r['path']:r['sha256'] for r in m['app_files']}
  if {r['path']:r['sha256'] for r in entries}!=by or len(entries)!=len(by):raise Stop('INVENTORY_REPRESENTATION_DRIFT')
  if any(f.is_symlink() for f in app.rglob('*')):raise Stop('PACKAGE_SYMLINK')
  if len(by)!=len(m['app_files']) or {str(f.relative_to(app)) for f in app.rglob('*') if f.is_file()}!=set(by):raise Stop('INVENTORY_SET')
  for rel,h in by.items():
   if Path(rel).is_absolute() or '..' in Path(rel).parts:raise Stop('INVENTORY_ESCAPE')
   pin(app/rel,h)
  base=json.loads(pin(self.p['baseline_manifest']['path'],self.p['baseline_manifest']['sha256']))
  old={r['path']:r['sha256'] for r in base['app_files']}
  if set(old)-set(by):raise Stop('NON_DELTA_PATH_SET')
  expected={'infrastructure/research_source_evidence.py': '874db5c59efbc9813f93bc0b82fec1210d5db37bc687d76abe79bf46f0ac4b47', 'infrastructure/manager_input_attestation.py': '3b759d8a3507e4ac74b8e401752459d97869ffd65b27699d04858f5839d6412a', 'domains/research_source_validation.py': '9b32f97e3cbf043cb7b8163885240099d268fc5c4be40594705c93c2f7086844', 'stage_center/research_context.py': 'cad28b7005bbaa227de17c241a73999ea7a0220c9be1db871942a2112fb26b77', 'stage_center_tick_config.json': '5056408d41de3109a723ea4afa13abbcae74c312c6b19bb7914584f0ea553361'}
  delta={rel:h for rel,h in by.items() if h!=old.get(rel)}
  if delta!=expected:raise Stop('NON_DELTA_BYTES_CHANGED')
  for rel,h in old.items():pin(Path(base['app_root'])/rel,h)
 def idle(self,r,d):
  v=self.command(['/bin/launchctl','print','gui/501/'+r['label']],True)
  if v.returncode:raise Stop('LOADED_UNKNOWN')
  loaded(v.stdout,d,r['plist'])
  self.no_processes()
 def no_processes(self):
  rows=self.command(['/bin/ps','-axo','pid=,ppid=,command=']).stdout.splitlines();procs={}
  for s in rows:
   f=s.strip().split(None,2)
   if len(f)==3:procs[int(f[0])]=(int(f[1]),f[2])
  active={i for i,(_,cmd) in procs.items() if any(root+'/' in cmd for root in self.p['target_process_roots'])}
  while True:
   children={i for i,(parent,_) in procs.items() if parent in active}
   if children<=active:break
   active|=children
  if active:raise Stop('STAGE_OR_DESCENDANT_ACTIVE')
 def ensure_original(self,r,definition):
  self.check();self.protection();pin(r['plist'],r['before_sha256']);metadata_pin(r)
  x=self.command(['/bin/launchctl','print','gui/501/'+r['label']],True)
  if x.returncode==0:loaded(x.stdout,definition,r['plist']);self.no_processes();return
  if x.returncode!=113 or 'Could not find service' not in x.stderr:raise Stop('ORIGINAL_LOAD_STATE_UNKNOWN')
  self.no_processes();self.load(r);self.idle(r,definition)
 def absent(self,r):
  x=self.command(['/bin/launchctl','print','gui/501/'+r['label']],True)
  if x.returncode!=113 or 'Could not find service' not in x.stderr:raise Stop('NOT_CONFIRMED_ABSENT')
 def unload(self,r,d):
  self.check();self.protection();metadata_pin(r);self.idle(r,d);self.check()
  self.command(['/bin/launchctl','bootout','gui/501/'+r['label']]);self.absent(r)
 def replace(self,r,current,target,raw):
  self.check();self.protection();self.absent(r);pin(r['plist'],current);metadata_pin(r)
  self.record('CAS_INTENT',path=r['plist'],before=current,after=target,metadata_sha256=r['plist_metadata_sha256'])
  p=Path(r['plist']);s=p.stat();tmp=p.with_name('.'+p.name+'.stage-r4-'+str(os.getpid()))
  fd=os.open(tmp,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,r['plist_metadata']['mode'])
  try:
   with os.fdopen(fd,'w+b') as f:
    f.write(raw);f.flush();os.fsync(f.fileno())
    metadata.apply_fd(f.fileno(),r['plist_metadata'])
    if metadata.snapshot_fd(f.fileno())!=r['plist_metadata']:raise Stop('TEMP_METADATA_NOT_PRESERVED')
   pin(tmp,target);pin(p,current);metadata_pin(r)
   os.replace(tmp,p);d=os.open(p.parent,os.O_RDONLY)
   try:os.fsync(d)
   finally:os.close(d)
  finally:
   if tmp.exists():tmp.unlink()
  pin(p,target);metadata_pin(r);self.record('CAS_RESULT',path=r['plist'],sha256=target,metadata_sha256=r['plist_metadata_sha256'])
 def load(self,r):
  self.check();self.protection();metadata_pin(r);self.absent(r);self.command(['/bin/launchctl','bootstrap','gui/501',r['plist']])

def switch(p,ops,reverse=False):
 try:
  ops.start()
  ops.check();ops.protection();ops.package()
  for r in p['operations']:
   h=sha(read(r['plist']));metadata_pin(r)
   allowed={r['before_sha256'],r['after_sha256']} if reverse else {r['before_sha256']}
   if h not in allowed:raise Stop('PRECHECK_THIRD_STATE')
  for r in p['operations']:
   b=pin(r['before_file'],r['before_sha256']);a=pin(r['after_file'],r['after_sha256'])
   if reverse and sha(read(r['plist']))==r['before_sha256']:
    ops.ensure_original(r,plistlib.loads(b));ops.record('ORIGINAL_PREIMAGE_PRESERVED',label=r['label']);continue
   current,target,raw,definition=(r['after_sha256'],r['before_sha256'],b,plistlib.loads(a)) if reverse else (r['before_sha256'],r['after_sha256'],a,plistlib.loads(b))
   pin(r['plist'],current);ops.unload(r,definition);ops.replace(r,current,target,raw);ops.load(r);ops.idle(r,plistlib.loads(raw));ops.record('BOUND',label=r['label'])
  ops.check();ops.protection();ops.record('TWO_LABELS_BOUND',reverse=reverse)
 finally:ops.close()

def execution_handoff(path,expected,plan_sha,controller_sha):
 h=json.loads(pin(path,expected));now=time.time()
 if h.get('plan_sha256')!=plan_sha or h.get('controller_sha256')!=controller_sha or h.get('reviewer_verdict')!='PASS':raise Stop('HANDOFF_REVIEW_BINDING')
 if h.get('coordinated_no_other_stage_cli') is not True or h.get('protected_dependencies_confirmed') is not True:raise Stop('HANDOFF_COORDINATION')
 issued_dt=datetime.fromisoformat(h['issued_at']);expires_dt=datetime.fromisoformat(h['expires_at'])
 if issued_dt.tzinfo is None or expires_dt.tzinfo is None:raise Stop('HANDOFF_AWARE_TIME_REQUIRED')
 issued=issued_dt.timestamp();expires=expires_dt.timestamp()
 if not issued<=now<expires or now-issued>60 or expires-issued>300:raise Stop('HANDOFF_NOT_FRESH')
 return h

def main():
 a=argparse.ArgumentParser();a.add_argument('--plan',required=True);a.add_argument('--plan-sha256',required=True);a.add_argument('--execute',action='store_true');a.add_argument('--reverse',action='store_true');a.add_argument('--journal');a.add_argument('--handoff');a.add_argument('--handoff-sha256');n=a.parse_args();p=json.loads(pin(n.plan,n.plan_sha256));scope(p)
 if not n.execute:print('PLAN_VALID_ONLY; NOT_EXECUTED');return
 if not n.journal or not n.handoff or not n.handoff_sha256:raise Stop('UNIQUE_JOURNAL_AND_FRESH_HANDOFF_REQUIRED')
 h=execution_handoff(n.handoff,n.handoff_sha256,n.plan_sha256,sha(read(Path(__file__).resolve())))
 if datetime.fromisoformat(h['expires_at']).timestamp()>datetime.fromisoformat(p['deadline']).timestamp()-10:raise Stop('HANDOFF_EXCEEDS_WINDOW')
 journal=Path(n.journal)
 allowed=Path(__file__).resolve().parent/'owned_runs'
 if journal.parent.resolve()!=allowed or not re.fullmatch(r'[a-zA-Z0-9_-]+\.jsonl',journal.name):raise Stop('JOURNAL_OUTSIDE_OWNED_RUNS')
 fd=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
 with original_guard(p['owner_guard']):switch(p,Live(p,n.journal),n.reverse)
if __name__=='__main__':main()
