"""Prepared four-role same-label native-window adaptation of the reviewed R7 drain recipe.
Default validates only. No producer calls, SIGKILL, busy bootout, or unknown retries.
"""
from __future__ import annotations
import argparse, contextlib, importlib.util, fcntl, hashlib, json, os, plistlib, re, shlex, signal, stat, sys, tempfile, time
from pathlib import Path
import types
_base=Path(__file__).resolve().with_name('reviewed_r7.py')
if _base.resolve()!=_base or _base.is_symlink():raise RuntimeError('REVIEWED_BASE_ALIAS')
_raw=_base.read_bytes()
if hashlib.sha256(_raw).hexdigest()!='44c65823ed11d6819939b3ac10388a74c3c879379a5b615249b170f81239c80e':raise RuntimeError('REVIEWED_BASE_SHA_DRIFT')
r7=types.ModuleType('retirement_reviewed_r7');r7.__file__=str(_base)
exec(compile(_raw,str(_base),'exec'),r7.__dict__)
Stop=r7.Stop;read=r7.read;pin=r7.pin;sha=r7.sha;canonical=r7.canonical;save=r7.save;metadata=r7.metadata
HERE=Path(__file__).resolve().parent
ROLES=('api','collector','stage','precapture')
OLD={'api':'com.lexi.v4.api','collector':'com.lexi.v4.runtime-graph','stage':'com.lexi.stage-center.scheduler','precapture':'com.lexi.stage-center.a-opening-precapture'}
NEW=dict(OLD)
CONTINUOUS={'api'}
PREFIX=Path('/Users/lexi/Library/LaunchAgents')
_support=HERE/'recovery_support.py'
_spec=importlib.util.spec_from_file_location('a_chain_recovery_support',_support)
recovery=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(recovery)

def require_role(role):
 if role not in ROLES:raise Stop('MAIN_AND_UNKNOWN_ROLE_ACTION_FORBIDDEN')
 return role
def row(p,role):
 require_role(role)
 return next(x for x in p['operations'] if x['role']==role)
def original_disabled(r,reverse=False):return r['new_disabled_before'] if reverse else r['old_disabled_before']
def destination_disabled(r,reverse=False):return r['old_disabled_before'] if reverse else r['new_disabled_before']
def labels(role,reverse=False):
 require_role(role)
 return (NEW[role],OLD[role]) if reverse else (OLD[role],NEW[role])
def definition(r,which,reverse=False):return r[('after' if which=='before' else 'before')+'_file'] if reverse else r[which+'_file']
def digest(r,which,reverse=False):return r[('after' if which=='before' else 'before')+'_sha256'] if reverse else r[which+'_sha256']
def expected_definition(p,x,before):
 after=json.loads(json.dumps(before))
 role=x['role']
 if role in ('stage','precapture'):
  release=next(r for r in p['releases'] if r['role']==('stage' if role=='precapture' else role))
  old=str(Path(x['old_app_root']).parent);new=str(Path(release['app_root']).parent)
  oldsha=sha(read(release['baseline_manifest']))
  def rec(v):
   if isinstance(v,str):return v.replace(old,new).replace(oldsha,release['manifest_sha256'])
   if isinstance(v,list):return [rec(q) for q in v]
   if isinstance(v,dict):return {k:rec(q) for k,q in v.items()}
   return v
  after=rec(after);after['EnvironmentVariables']['V4_RELEASE_ID']=release['release_id']
 elif role=='api':after['EnvironmentVariables']['V4_RUNTIME_GRAPH_CONFIG']=p['graph']['final']
 elif role=='collector':
  if after['ProgramArguments'].count('--config')!=1:raise Stop('CONFIG_ARGUMENT_SCOPE')
  i=after['ProgramArguments'].index('--config');after['ProgramArguments'][i+1]=p['graph']['final']
 else:raise Stop('UNAPPROVED_ROLE')
 return after

def expected_graph(p):
 # Baseline must already be the UI owner's final API-bound graph. Only Stage
 # caller paths change; all API/Main/business/provenance values stay exact.
 graph=json.loads(pin(p['graph']['baseline'],p['graph']['baseline_sha256']))
 stage=next(r for r in p['releases'] if r['role']=='stage')
 if graph['main']['app_root']!=p['main_readonly']['app_root']:raise Stop('MAIN_GRAPH_READONLY_BINDING')
 api=graph['entry_sources']['MANAGER_WORKBENCH_API']
 if not api['module_file'].startswith(p['api_app_root']+'/'):raise Stop('FINAL_UI_API_GRAPH_BINDING_REQUIRED')
 pin(api['module_file'],api['module_sha256'])
 for owner in ('STAGE_CENTER','STAGE_PREP','STAGE_PRECAPTURE'):
  bound=graph['entry_sources'][owner];relative=bound['module_file'].split('/app/',1)[1]
  pin(Path(stage['candidate_app'])/relative,bound['module_sha256'])
  bound['module_file']=str(Path(stage['app_root'])/relative)
 graph['stage_catalog_source']['module_file']=str(Path(stage['app_root'])/'ops/run_stage_center_nodes.py')
 pin(Path(stage['candidate_app'])/'ops/run_stage_center_nodes.py',graph['stage_catalog_source']['module_sha256'])
 return graph


def scope(p):
 if p.get('schema')!='v4.native.four_same_label_control.v1' or p.get('status')!='FINAL_FROZEN_EXECUTABLE' or tuple(x['role'] for x in p.get('operations',[]))!=ROLES:raise Stop('EXACT_FOUR_FINAL_SCOPE')
 if p.get('RESEARCH_ONLY') is not True or any(p.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):raise Stop('SAFETY')
 snapshot=json.loads(pin(p['baseline_snapshot']['path'],'821d45141fbb07a32b3158b484e7cc724b55e712ed8ceba655dfff73f15ef5b9'))
 if p['baseline_snapshot']['sha256']!='821d45141fbb07a32b3158b484e7cc724b55e712ed8ceba655dfff73f15ef5b9':raise Stop('FINAL_UI_SNAPSHOT_PIN')
 m=p['main_readonly'];main=snapshot['roles']['main']
 if any(m.get(k)!=main[k] for k in ('label','app_root','manifest','manifest_sha256','plist','plist_sha256')) or m['identity']['pid']!=73799 or m['manifest_sha256']!='528a7413168931473a2f418f394efaa0ad640356a3c9d6f68ef455b238e71176':raise Stop('MAIN_READONLY_EXACT_BINDING')
 pin(m['manifest'],m['manifest_sha256']);pin(m['plist'],m['plist_sha256'])
 if p.get('guard_program')!='/bin/sleep' or p.get('guard_seconds')!=604800 or p.get('calendar_margin_seconds')!=300:raise Stop('GUARD_SCOPE')
 r=p['recovery']
 if r.get('cleanup_grace_seconds')!=60 or r.get('guardian_reconcile_seconds')!=300 or r.get('guard_argv')!=['/bin/sleep','604800'] or r.get('normal_program_argv_restore_only') is not True or r.get('guardian_script')!=str(HERE/'abort_guardian.py'):raise Stop('FIXED_RECOVERY_CAPABILITY')
 if r.get('cli_timeout_seconds')!=3 or r.get('cli_wrapper')!=str(HERE/'bounded_launchctl') or sha(read(HERE/'bounded_launchctl'))!=r.get('cli_wrapper_sha256'):raise Stop('FIXED_LAUNCHCTL_WRAPPER')
 recovery.validate_argv_abi(p);pin('/bin/sleep',p['guard_program_sha256'])
 api=snapshot['roles']['api']
 if p['api_app_root']!=api['app_root'] or p['api_release_id']!='v4-a-share-empty-state-20261029-r1-api' or p['api_manifest_sha256']!=api['manifest_sha256']:raise Stop('CURRENT_UI_API_REQUIRED')
 api_module_contract_binding(p)
 for x in p['operations']:
  role=x['role'];observed=snapshot['roles'][role]
  if x['old_label']!=OLD[role] or x['new_label']!=OLD[role] or x['label']!=OLD[role] or x['plist']!=str(PREFIX/(OLD[role]+'.plist')) or x['new_plist']!=x['plist'] or x['before_sha256']!=observed['plist_sha256'] or x['old_app_root']!=observed['app_root']:raise Stop('EXACT_CURRENT_PLIST_SCOPE')
  if x['old_disabled_before'] is not False or x['new_disabled_before'] is not False:raise Stop('DISABLED_SCOPE')
  if any(Path(x[k]).parent!=HERE for k in ('before_file','after_file')):raise Stop('OWNED_DEFINITION_PATH')
  before=plistlib.loads(pin(x['before_file'],x['before_sha256']));after=plistlib.loads(pin(x['after_file'],x['after_sha256']))
  if before!=observed['definition'] or before.get('Label')!=OLD[role] or after!=expected_definition(p,x,before):raise Stop('EXACT_BINDING_DELTA')
  if metadata.digest(x['plist_metadata'])!=x['plist_metadata_sha256']:raise Stop('METADATA_DIGEST')
  if sha(canonical(after))!=x['after_definition_sha256'] or before['WorkingDirectory']!=x['old_working_directory'] or after['WorkingDirectory']!=x['new_working_directory']:raise Stop('DEFINITION_IDENTITY')
 if tuple(v['role'] for v in p['releases'])!=('stage',):raise Stop('STAGE_ONLY_RELEASE')
 release=p['releases'][0];release_root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases');target=release_root/'a-native-window-20261029-r1-stage'
 if release['release_id']!=target.name or release['app_root']!=str(target/'app') or release['manifest']!=str(target/'release-manifest.json') or release['baseline_manifest']!=snapshot['roles']['stage']['manifest'] or release['baseline_manifest_sha256']!=snapshot['roles']['stage']['manifest_sha256']:raise Stop('FROZEN_STAGE_RELEASE')
 manifest=json.loads(pin(release['candidate_manifest'],release['manifest_sha256']));baseline=json.loads(pin(release['baseline_manifest'],release['baseline_manifest_sha256']));app=Path(release['candidate_app'])
 if manifest.get('schema_version')!='v4.runtime_graph_repair_release.v1' or manifest['app_root']!=release['app_root'] or manifest['release_id']!=release['release_id'] or manifest.get('RESEARCH_ONLY') is not True or manifest['candidate']['app_root']!=release['app_root'] or manifest['candidate']['root']!=str(target):raise Stop('STAGE_MANIFEST_IDENTITY')
 rows=manifest['application_inventory']['entries'];old={v['path']:v['sha256'] for v in baseline['application_inventory']['entries']}
 if len(rows)!=manifest['application_inventory']['entry_count'] or sha(canonical(rows))!=manifest['application_inventory']['aggregate_sha256'] or manifest['app_files']!=rows:raise Stop('INVENTORY_DIGEST')
 if len({v['path'] for v in rows})!=len(rows) or {v['path'] for v in rows}!=set(old) or any(v.is_symlink() for v in app.rglob('*')) or {str(v.relative_to(app)) for v in app.rglob('*') if v.is_file()}!=set(old):raise Stop('EXACT_INVENTORY_SET')
 delta={v['path']:v['sha256'] for v in rows if v['sha256']!=old[v['path']]}
 if delta!=release['delta'] or set(delta)!={'infrastructure/stage_quote_provider.py','stage_center_tick_config.json'} or delta['infrastructure/stage_quote_provider.py']!='1e8166771b2194629574d0073f058d4a138909f9553519e7843a536b0f82289c':raise Stop('EXACT_NATIVE_DELTA')
 pin(p['native_frozen']['path'],'7e787049c630d7604b25c87c7261dff8180cf76ff314129dc1cd24b8e64b8880')
 for v in rows:
  if Path(v['path']).is_absolute() or '..' in Path(v['path']).parts:raise Stop('INVENTORY_ESCAPE')
  f=app/v['path'];pin(f,v['sha256'])
  if f'{stat.S_IMODE(f.stat().st_mode):04o}'!=v['mode'] or f.stat().st_size!=v['size']:raise Stop('INVENTORY_METADATA')
 old_cfg=json.loads(read(Path(release['baseline_manifest']).parent/'app/stage_center_tick_config.json'));new_cfg=json.loads(read(app/'stage_center_tick_config.json'));old_cfg['release_id']=release['release_id']
 if old_cfg!=new_cfg or new_cfg['research_owner_binding']!={'app_root':m['app_root'],'release_id':m['release_id'],'manifest_sha256':m['manifest_sha256']}:raise Stop('STAGE_CONFIG_MAIN_HISTORY_PRESERVED')
 if p['graph']['baseline']!=snapshot['graph']['path'] or p['graph']['baseline_sha256']!=snapshot['graph']['sha256'] or p['graph']['final']!=str(release_root/'a-native-window-20261029-r1-graph/runtime-graph-config.json') or p['graph']['final_binding_manifest']!=str(release_root/'a-native-window-20261029-r1-graph/binding-manifest.json'):raise Stop('VERSIONED_GRAPH_SCOPE')
 if json.loads(pin(p['graph']['candidate'],p['graph']['sha256']))!=expected_graph(p):raise Stop('GRAPH_STAGE_ONLY_DELTA')
 pin(p['api_integration']['path'],p['api_integration']['sha256'])
 return True

def require_executable(p):
 if p.get('status')!='FINAL_FROZEN_EXECUTABLE':raise Stop('FINAL_FROZEN_SCOPE_REQUIRED')


def handoff(p,h,reverse=False):
 if h.get('main_readonly_identity')!=p['main_readonly']['identity']:raise Stop('FRESH_MAIN_READONLY_IDENTITY_REQUIRED')
 if not re.fullmatch('[0-9a-f]{32}',h.get('operation_id','')) or h.get('plan_sha256')!=sha(canonical(p)):raise Stop('HANDOFF_SCOPE')
 if h.get('reverse') is not reverse or h.get('root_ack_dir')!='/private/var/tmp/v4-a-chain-nextspawn-'+h['operation_id']:raise Stop('HANDOFF_DIRECTION')
 if not h['observed_epoch']<=time.time()<=h['expires_epoch'] or not 0<h['expires_epoch']-h['observed_epoch']<=300:raise Stop('FRESH_HANDOFF')
 # Reuse the reviewed Stage timer-window premise for the fixed calendar owners.
 from datetime import datetime,timedelta
 from zoneinfo import ZoneInfo
 start=datetime.fromtimestamp(h['observed_epoch'],ZoneInfo('Asia/Shanghai'));end=datetime.fromtimestamp(h['expires_epoch'],ZoneInfo('Asia/Shanghai'))
 for role in ('stage','precapture'):
  d=plistlib.loads(pin(row(p,role)['before_file'],row(p,role)['before_sha256']));margin=300
  intervals=d.get('StartCalendarInterval',[]);intervals=[intervals] if isinstance(intervals,dict) else intervals
  for interval in intervals:
   if set(interval)!={'Hour','Minute'}:raise Stop('UNKNOWN_AUXILIARY_CALENDAR')
   for offset in (-1,0,1):
    due=(start+timedelta(days=offset)).replace(hour=interval['Hour'],minute=interval['Minute'],second=0,microsecond=0)
    if start.timestamp()-margin<=due.timestamp()<=end.timestamp()+margin:raise Stop('CALENDAR_WINDOW_CONFLICT:'+role)
 # Preserve the Main admission margin as well as calendar-owner margins.
 catalog=json.loads(pin(p['main_catalog']['path'],p['main_catalog']['sha256']))
 for workload in catalog['workloads']:
  for slot in workload.get('slots',[]):
   if not re.fullmatch(r'\d{4}',slot):raise Stop('UNKNOWN_MAIN_SLOT')
   for offset in (-1,0,1):
    due=(start+timedelta(days=offset)).replace(hour=int(slot[:2]),minute=int(slot[2:]),second=0,microsecond=0)
    if start.timestamp()-300<=due.timestamp()<=end.timestamp()+300:raise Stop('MAIN_WINDOW_CONFLICT')
 for k in ('legitimate_daily_producer_complete','all_daily_descendants_absent','no_active_dependent_api_query','api_brief_new_connection_gap_coordinated','pdf_admission_disabled_by_existing_time_window','no_live_pdf_child','no_parallel_lifecycle_owner','all_current_main_children_and_jobs_finished','all_accepted_manual_jobs_finished','scheduler_queue_empty_or_original_observations_durable','all_auxiliary_jobs_naturally_finished'):
  if h.get(k) is not True:raise Stop('FRESH_PROOF_REQUIRED:'+k)
 if reverse and h.get('scheduler_queue_empty') is not True:raise Stop('ROLLBACK_QUEUE_MUST_BE_EMPTY')
 for role,i in h['identities'].items():
  if i is None:
   if role in CONTINUOUS:raise Stop('CONTINUOUS_IDENTITY_REQUIRED')
  elif not isinstance(i,dict) or set(i)!={'pid','ps_sha256','ps_text'} or type(i['pid']) is not int or i['pid']<=1 or not isinstance(i['ps_text'],str) or sha(i['ps_text'].encode())!=i['ps_sha256']:raise Stop('HANDOFF_IDENTITY_SCHEMA')
 if not h.get('data_pins') or not h.get('data_stats') or set(h['identities'])!=set(ROLES) or set(h['role_observations'])!=set(ROLES):raise Stop('HANDOFF_COMPLETENESS')
 return True

class Live(r7.Live):
 def __init__(self,p,reverse=False):super().__init__(p);self.reverse=reverse
 def cmd(self,args,*a,**k):
  if len(args)>2 and args[0]=='/bin/launchctl' and args[2]=='gui/501/com.lexi.v4.scheduler' and args[1]!='print':raise Stop('MAIN_LIFECYCLE_ACTION_FORBIDDEN')
  return super().cmd(args,*a,**k)
 def main_unchanged(self):
  m=self.p['main_readonly'];pin(m['manifest'],m['manifest_sha256']);pin(m['plist'],m['plist_sha256'])
  if self.identity(m['identity']['pid'])!=m['identity']:raise Stop('READONLY_MAIN_IDENTITY_CHANGED')
  service=self.service_label(m['label'])
  if not service['loaded'] or service['pid']!=m['identity']['pid']:raise Stop('READONLY_MAIN_LOADED_IDENTITY_CHANGED')
 def protection(self,h):
  super().protection(h);self.main_unchanged()
 def service_label(self,label):
  v=self.cmd(['/bin/launchctl','print','gui/501/'+label],True)
  if v.returncode:
   if v.returncode==113 and 'Could not find service' in v.stderr:return {'loaded':False,'pid':None}
   raise Stop('SERVICE_STATE_UNKNOWN')
  pid=re.search(r'^\s*pid = (\d+)$',v.stdout,re.M)
  return {'loaded':True,'pid':int(pid[1]) if pid else None,'text':v.stdout}
 def service(self,role):return self.service_label(labels(role,self.reverse)[0])
 def disabled(self,label):
  out=self.cmd(['/bin/launchctl','print-disabled','gui/501']).stdout
  body=re.fullmatch(r'\s*disabled services = \{\s*\n(.*?)\n\s*\}\s*',out,re.S)
  if body is None:raise Stop('DISABLED_STATE_UNKNOWN')
  entries=[]
  for line in body[1].splitlines():
   if not line.strip():continue
   entry=re.fullmatch(r'\s*"([^"\n]+)"\s*=>\s*(disabled|enabled|true|false)\s*',line)
   if entry is None:raise Stop('DISABLED_STATE_UNKNOWN')
   entries.append((entry[1],entry[2]))
  matches=[value for key,value in entries if key==label]
  if len(matches)>1:raise Stop('AMBIGUOUS_DISABLED')
  return bool(matches and matches[0] in ('disabled','true'))
 def set_disabled(self,label,want):
  if label not in OLD.values():raise Stop('MAIN_AND_UNKNOWN_LABEL_ACTION_FORBIDDEN')
  if self.service_label(label)['loaded']:raise Stop('DISABLE_ONLY_AFTER_UNLOAD')
  self.cmd(['/bin/launchctl','disable' if want else 'enable','gui/501/'+label])
  if self.disabled(label)!=want:raise Stop('DISABLED_READBACK')
 def original(self,role,i):
  x=row(self.p,role);path=x['new_plist'] if self.reverse else x['plist'];pin(path,digest(x,'before',self.reverse));metadata.require(path,x['plist_metadata'])
  service=self.service(role)
  if not service['loaded'] or service['pid']!=(i or {}).get('pid'):raise Stop('ORIGINAL_OWNER_CHANGED')
  if self.disabled(labels(role,self.reverse)[0])!=original_disabled(x,self.reverse):raise Stop('ORIGINAL_DISABLED_DRIFT')
  if i is not None:
   if self.identity(i['pid'])!=i:raise Stop('ORIGINAL_PID_DRIFT')
   cwd=self.cmd(['/usr/sbin/lsof','-a','-p',str(i['pid']),'-d','cwd','-Fn']).stdout
   if [v[1:] for v in cwd.splitlines() if v.startswith('n')]!=[x['new_working_directory'] if self.reverse else x['old_working_directory']]:raise Stop('ORIGINAL_CWD')
  elif role in CONTINUOUS and not (role=='api' and self.reverse and getattr(self,'allow_empty_api',False)):raise Stop('CONTINUOUS_OWNER_MISSING')
  if OLD[role]!=NEW[role] and self.service_label(labels(role,self.reverse)[1])['loaded']:raise Stop('DESTINATION_ALREADY_LOADED')
 def no_old_root_processes(self,role):
  x=row(self.p,role);root=x['new_app_root'] if self.reverse else x['old_app_root']
  if any(root+'/' in v['command'] for v in self.rows().values()):raise Stop('OLD_RELEASE_PROCESS_STILL_RUNNING')
 def ack(self,h):
  root=Path(h['root_ack_dir']);s=root.lstat()
  if root.parent!=Path('/private/var/tmp') or s.st_uid!=0 or not stat.S_ISDIR(s.st_mode) or s.st_mode&0o022:raise Stop('ROOT_ACK_DIRECTORY')
  for name,want in [('plan_sha256',sha(canonical(self.p))),*[(role+'.rc','0') for role in ROLES],('COMPLETE','COMPLETE')]:
   f=root/name;s=f.lstat()
   if s.st_uid!=0 or not stat.S_ISREG(s.st_mode) or s.st_mode&0o022 or read(f).decode().strip()!=want:raise Stop('ROOT_ACK_INVALID')
 def term(self,role,i):
  if role not in CONTINUOUS:raise Stop('NO_AUXILIARY_TERM')
  self.pdf_boundary();self.original(role,i);os.kill(i['pid'],signal.SIGTERM)
 def kick_guard(self,role):
  if role in CONTINUOUS and not (role=='api' and self.reverse and getattr(self,'allow_empty_api',False)):raise Stop('NO_CONTINUOUS_KICK')
  # No -k: macOS kickstart returns the existing process if a trigger raced.
  self.cmd(['/bin/launchctl','kickstart','gui/501/'+labels(role,self.reverse)[0]])
 def guard(self,role,old):
  s=self.service(role)
  if not s['loaded'] or not s['pid'] or s['pid']==(old or {}).get('pid'):raise Stop('NEXTSPAWN_GUARD_NOT_CONFIRMED')
  i=self.identity(s['pid'])
  if not i or not re.search(r'(?:^|\s)/bin/sleep '+str(self.p['guard_seconds'])+r'\s*$',i['ps_text']):raise Stop('UNEXPECTED_REPLACEMENT_NO_SIGNAL')
  return i
 def bootout_guard(self,role,guard,old):
  if (old and self.identity(old['pid']) is not None) or self.guard(role,old)!=guard:raise Stop('ORIGINAL_OR_GUARD_CHANGED_NO_BOOTOUT')
  self.cmd(['/bin/launchctl','bootout','gui/501/'+labels(role,self.reverse)[0]])
 def absent(self,role):
  if any(self.service_label(label)['loaded'] for label in set(labels(role,self.reverse))):raise Stop('SERVICE_NOT_ABSENT')
 def cas(self,role):
  x=row(self.p,role);self.absent(role)
  if OLD[role]==NEW[role]:return super().cas(role,reverse=self.reverse)
  origin=Path(x['new_plist'] if self.reverse else x['plist']);dest=Path(x['plist'] if self.reverse else x['new_plist'])
  pin(origin,digest(x,'before',self.reverse));metadata.require(origin,x['plist_metadata'])
  raw=pin(definition(x,'after',self.reverse),digest(x,'after',self.reverse))
  if self.reverse:
   # Original bytes were deliberately retained, never overwritten/quarantined.
   pin(dest,digest(x,'after',True));metadata.require(dest,x['plist_metadata']);return
  if dest.exists() or dest.is_symlink():raise Stop('DESTINATION_EXISTS_NO_OVERWRITE')
  if dest.parent.resolve()!=dest.parent:raise Stop('ANCESTOR_ALIAS')
  fd,t=tempfile.mkstemp(prefix='.'+dest.name+'.retirement.',dir=dest.parent)
  try:
   with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno());metadata.apply_fd(f.fileno(),x['plist_metadata'])
   pin(t,x['after_sha256']);metadata.require(t,x['plist_metadata']);pin(origin,x['before_sha256']);self.absent(role)
   os.link(t,dest,follow_symlinks=False)  # atomic publish, fails if anyone won the name
   d=os.open(dest.parent,os.O_RDONLY)
   try:os.fsync(d)
   finally:os.close(d)
  finally:
   if os.path.exists(t):os.unlink(t)
  pin(dest,x['after_sha256']);metadata.require(dest,x['plist_metadata'])
 def cas_confirmed(self,role):
  x=row(self.p,role);dest=x['plist'] if self.reverse else x['new_plist'];pin(dest,digest(x,'after',self.reverse));metadata.require(dest,x['plist_metadata']);self.absent(role)
 def disable_origin(self,role):
  self.absent(role)
 def enable_destination(self,role):
  self.absent(role)
  if self.disabled(OLD[role]):raise Stop('DISABLED_STATE_DRIFT_NO_ENABLE')
 def bootstrap(self,role):
  self.absent(role);x=row(self.p,role);p=x['plist'] if self.reverse else x['new_plist'];pin(p,digest(x,'after',self.reverse));metadata.require(p,x['plist_metadata']);self.cmd(['/bin/launchctl','bootstrap','gui/501',p])
 def new(self,role):
  x=row(self.p,role);old,label=labels(role,self.reverse);s=self.service_label(label);d=plistlib.loads(pin(definition(x,'after',self.reverse),digest(x,'after',self.reverse)))
  if not s['loaded']:raise Stop('NEW_OWNER_NOT_LOADED')
  text=s['text'];path=x['plist'] if self.reverse else x['new_plist']
  def field(k):
   m=re.search(r'^\t'+re.escape(k)+r' = (.*)$',text,re.M);return m[1] if m else None
  if field('path')!=path or field('working directory')!=d['WorkingDirectory'] or field('program')!=d['ProgramArguments'][0]:raise Stop('NEW_LOADED_BINDING')
  m=re.search(r'^\targuments = \{\n(.*?)^\t\}',text,re.M|re.S)
  if not m or [v.strip() for v in m[1].splitlines() if v.strip()]!=d['ProgramArguments']:raise Stop('NEW_LOADED_ARGV')
  m=re.search(r'^\tenvironment = \{\n(.*?)^\t\}',text,re.M|re.S);env=dict(re.findall(r'^\s*([^\s]+) => (.*)$',m[1],re.M)) if m else {}
  if any(env.get(k)!=str(v) for k,v in d['EnvironmentVariables'].items()):raise Stop('NEW_LOADED_ENV')
  if old!=label and (self.service_label(old)['loaded'] or not self.disabled(old)):raise Stop('OLD_LABEL_LOGIN_PROTECTION')
  if role in CONTINUOUS and not s['pid']:
   if role=='api':return None
   raise Stop('NEW_CONTINUOUS_PID')
  if not s['pid']:return None
  identity=self.identity(s['pid'])
  if identity is None:
   if role=='api':return None
   raise Stop('NEW_OWNER_EXITED')
  cwd=self.cmd(['/usr/sbin/lsof','-a','-p',str(s['pid']),'-d','cwd','-Fn'],True)
  if cwd.returncode and role=='api' and self.identity(s['pid']) is None:return None
  if cwd.returncode or [v[1:] for v in cwd.stdout.splitlines() if v.startswith('n')]!=[d['WorkingDirectory']]:raise Stop('NEW_PROCESS_CWD')
  return identity
 def completed(self,role,expected):
  current=self.new(role)
  if role in CONTINUOUS and current!=expected:raise Stop('COMPLETED_OWNER_CHANGED')
 def health(self,deadline=None):
  import urllib.request
  try:
   deadline=deadline if deadline is not None else time.time()+30
   def get(url):
    remaining=deadline-time.time()
    if remaining<=0:raise ValueError('API_HEALTH_DEADLINE')
    with urllib.request.urlopen(url,timeout=remaining) as response:return json.load(response)
   health=get('http://127.0.0.1:8873/healthz')
   d=get('http://127.0.0.1:8873/api/v1/runs/date-list')
   frontend=get('http://127.0.0.1:8873/api/v4/runtime-graph/frontend-build')
   identity=d.get('runtime_identity',{})
   expected=row(self.p,'api')['new_release_id']
   return time.time()<=deadline and health.get('status')=='ok' and identity.get('status')=='MANIFEST_EXECUTION_FILES_VERIFIED' and identity.get('release_id')==expected and frontend.get('status')=='VERIFIED' and frontend.get('api_release_id')==expected
  except (OSError,ValueError):return False


class Recipe:
 """R7 phase boundaries, with rename persistence and bounded API health readback."""
 def __init__(self,p,h,o,s,path):self.p=p;self.h=h;self.o=o;self.s=s;self.path=path
 def record(self,phase,**kw):self.s.update(phase=phase,**kw);save(self.path,self.s)
 def step(self,role):
  require_role(role)
  o=self.o;s=self.s;phase=s['phase'];old=s['original_identity'];o.protection(self.h)
  recovery.ensure_guardian(sys.modules[__name__],self.p,self.h,HERE)
  if phase in ('ARMED','GUARD_CONFIRMED','WAIT_GUARD_GONE','CAS_INTENT','PLIST_APPLIED','OLD_DISABLED','DEST_ENABLED'):handoff(self.p,self.h,o.reverse)
  if phase=='WAITING_ROOT_ACK':o.ack(self.h);o.original(role,old);self.record('ARMED')
  elif phase=='ARMED':
   if self.h.get('api_health_rollback'):
    if role!='api' or not o.reverse:raise Stop('ROLLBACK_ROLE_SCOPE')
    rollback_ack(self.p,self.h)
   else:handoff(self.p,self.h,o.reverse);o.ack(self.h)
   o.pdf_boundary();o.original(role,old)
   if role in CONTINUOUS and old is not None:
    self.record('TERM_INTENT',children=o.descendants(old['pid']));o.term(role,old);self.record('DRAINING',term_sent=True)
   else:self.record('AUX_WAIT_IDLE',children={})
  elif phase=='TERM_INTENT':
   if o.identity(old['pid']) is not None:raise Stop('TERM_OUTCOME_UNKNOWN_NO_REPEAT')
   self.record('DRAINING',term_sent='UNKNOWN_ORIGINAL_EXIT_CONFIRMED')
  elif phase=='DRAINING':
   i=o.identity(old['pid'])
   if i is not None:
    if i!=old or o.service(role)['pid']!=old['pid']:raise Stop('OWNER_CHANGED_DURING_DRAIN')
    s['children'].update(o.descendants(old['pid']));self.record('DRAINING');return False
   for pid,i in s['children'].items():
    if o.identity(int(pid))==i:return False
   service=o.service(role)
   if service['loaded'] and service['pid'] is None:return False
   o.no_old_root_processes(role);self.record('GUARD_CONFIRMED',guard=o.guard(role,old))
  elif phase=='AUX_WAIT_IDLE':
   service=o.service(role)
   if not service['loaded']:raise Stop('AUX_UNEXPECTED_UNLOAD')
   if service['pid']:
    try:g=o.guard(role,old)
    except Stop as failure:
     if str(failure)!='UNEXPECTED_REPLACEMENT_NO_SIGNAL':raise
     # A trigger can race arming. It finishes naturally; it is never signalled.
     s['children'].update(o.descendants(service['pid']));self.record('AUX_WAIT_IDLE',observed_aux=o.identity(service['pid']));return False
    for pid,i in s['children'].items():
     if o.identity(int(pid))==i:return False
    self.record('GUARD_CONFIRMED',guard=g)
   else:
    o.no_old_root_processes(role);self.record('AUX_KICK_INTENT');o.kick_guard(role);self.record('AUX_WAIT_IDLE',kick_completed=True)
  elif phase=='AUX_KICK_INTENT':raise Stop('KICK_OUTCOME_UNKNOWN_NO_REPEAT')
  elif phase=='GUARD_CONFIRMED':self.record('GUARD_BOOTOUT_INTENT');o.bootout_guard(role,s['guard'],old);self.record('WAIT_GUARD_GONE')
  elif phase=='GUARD_BOOTOUT_INTENT':o.absent(role);self.record('WAIT_GUARD_GONE')
  elif phase=='WAIT_GUARD_GONE':
   o.absent(role);o.no_old_root_processes(role)
   if o.identity(s['guard']['pid'])==s['guard']:return False
   self.record('CAS_INTENT');o.cas(role);self.record('PLIST_APPLIED')
  elif phase=='CAS_INTENT':
   # No second publish. An unknown CAS can only reconcile the exact after state.
   o.cas_confirmed(role);self.record('PLIST_APPLIED')
  elif phase=='PLIST_APPLIED':self.record('OLD_DISABLE_INTENT');o.disable_origin(role);self.record('OLD_DISABLED')
  elif phase=='OLD_DISABLE_INTENT':
   a,b=labels(role,o.reverse)
   if a!=b and not o.disabled(a):raise Stop('DISABLE_OUTCOME_UNKNOWN_NO_REPEAT')
   o.absent(role);self.record('OLD_DISABLED')
  elif phase=='OLD_DISABLED':self.record('DEST_ENABLE_INTENT');o.enable_destination(role);self.record('DEST_ENABLED')
  elif phase=='DEST_ENABLE_INTENT':
   wanted=destination_disabled(row(self.p,role),True) if o.reverse else False
   if o.disabled(labels(role,o.reverse)[1])!=wanted:raise Stop('ENABLE_OUTCOME_UNKNOWN_NO_REPEAT')
   o.absent(role);self.record('DEST_ENABLED')
  elif phase=='DEST_ENABLED':self.record('BOOTSTRAP_INTENT');o.bootstrap(role);self.record('READBACK')
  elif phase=='BOOTSTRAP_INTENT':raise Stop('BOOTSTRAP_OUTCOME_UNKNOWN_NO_REPEAT')
  elif phase=='READBACK':
   current=o.new(role)
   if role=='api':self.record('HEALTH',new=current,health_started_epoch=time.time())
   else:self.record('DONE',new=current);return True
  elif phase=='HEALTH':
   current=o.new(role)
   if current!=s.get('new'):self.record('HEALTH',new=current)
   deadline=s['health_started_epoch']+30
   if current is not None and time.time()<deadline and o.health(deadline):self.record('DONE');return True
   if time.time()>=deadline:self.record('HEALTH_FAILED',failure='API_HEALTH_30_SECONDS');raise Stop('API_HEALTH_FAILED_REQUIRES_GUARDED_ROLLBACK')
   return False
  elif phase=='DONE':o.completed(role,s['new']);return True
  else:raise Stop('UNKNOWN_PHASE:'+phase)
  return False

def root_helper(p,h,coordinator,ready_sha):
 return recovery.root_helper(p,h,coordinator,ready_sha,HERE)

def rollback_ack(p,h):
 root=Path(h['root_ack_dir'])/'rollback-api'
 for name,want in [('rc','0'),('COMPLETE',h['operation_id'])]:
  path=root/name;s=path.lstat()
  if s.st_uid!=0 or not stat.S_ISREG(s.st_mode) or s.st_mode&0o022 or read(path).decode().strip()!=want:raise Stop('ROLLBACK_ACK_UNKNOWN_NO_RETRY')

def auto_api_rollback(p,h,ops,state,checkpoint):
 """Only the exact failed replacement API; Main and auxiliary jobs stay intact."""
 if state.get('phase')!='HEALTH_FAILED' or state.get('failure')!='API_HEALTH_30_SECONDS' or ops.reverse:raise Stop('ROLLBACK_SCOPE')
 current=ops.new('api')
 if current!=state['new']:raise Stop('FAILED_API_OWNER_DRIFT')
 request=HERE/('owned-api-rollback-'+h['operation_id']+'.json')
 if request.exists():raise Stop('EXISTING_ROLLBACK_REQUEST_NO_RETRY')
 save(request,{'operation_id':h['operation_id'],'plan_sha256':sha(canonical(p)),'pid':current['pid'] if current else 0,'ps_sha256':current['ps_sha256'] if current else 'NONE'})
 deadline=min(h['expires_epoch'],time.time()+60)
 while not (Path(h['root_ack_dir'])/'rollback-api/COMPLETE').exists():
  ops.protection(h)
  if time.time()>deadline:raise Stop('ROLLBACK_ADMIN_ACK_EXPIRED_OR_UNKNOWN_NO_SIGNAL')
  time.sleep(1)
 rollback_ack(p,h);reverse=Live(p,True);reverse.allow_empty_api=current is None;back={**h,'reverse':True,'api_health_rollback':True,'identities':{**h['identities'],'api':current}}
 path=checkpoint.with_name('owned-api-health-rollback.checkpoint.json')
 if path.exists():raise Stop('ROLLBACK_CHECKPOINT_EXISTS_RESUME_WITH_PARENT')
 s={'schema':'v4.native.four_role.v1','phase':'ARMED','operation_id':h['operation_id'],'plan_sha256':sha(canonical(p)),'original_identity':current,'children':{},'direction':'API_HEALTH_ROLLBACK'};save(path,s)
 recipe=Recipe(p,back,reverse,s,path)
 while not recipe.step('api'):time.sleep(1)
 state.update(phase='ROLLED_BACK',rollback_checkpoint=str(path));save(checkpoint,state)
 return s

def installed(p):
 pin(p['graph']['final'],p['graph']['sha256'])
 pin(p['graph']['final_binding_manifest'],sha(read(p['graph']['binding_manifest'])))
 for release in p['releases']:
  pin(release['manifest'],release['manifest_sha256']);m=json.loads(read(release['manifest']));root=Path(release['app_root']);expected={v['path'] for v in m['application_inventory']['entries']}
  if any(v.is_symlink() for v in root.rglob('*')) or {str(v.relative_to(root)) for v in root.rglob('*') if v.is_file()}!=expected:raise Stop('INSTALLED_INVENTORY_SET')
  for v in m['application_inventory']['entries']:
   f=root/v['path'];pin(f,v['sha256'])
   if f'{stat.S_IMODE(f.stat().st_mode):04o}'!=v['mode']:raise Stop('INSTALLED_MODE')

def api_module_contract_binding(p):
 """Use only the external contract already sealed by this exact API release."""
 manifest_path=Path(p['api_app_root']).parent/'release-manifest.json'
 manifest=json.loads(pin(manifest_path,p['api_manifest_sha256']))
 authoritative=manifest.get('external_module_contract') or {}
 ref=p.get('api_module_contract')
 if not isinstance(ref,dict) or set(ref)!={'path','sha256'} or ref!={k:authoritative.get(k) for k in ('path','sha256')}:raise Stop('API_MODULE_CONTRACT_MANIFEST_BINDING')
 raw=pin(ref['path'],ref['sha256']);contract=json.loads(raw)
 gateway=(contract.get('roles') or {}).get('gateway') or {}
 if contract.get('schema_version')!='v4.api_module_contracts.v1' or any(gateway.get(k)!=v for k,v in {'label':OLD['api'],'plist_name':OLD['api']+'.plist','lock_name':'.com.lexi.v4.api.release.lock','host':'127.0.0.1','port':8873}.items()):raise Stop('API_MODULE_CONTRACT_GATEWAY_IDENTITY')
 return ref,contract

def load_api_integration(p):
 contract_ref,contract=api_module_contract_binding(p)
 ref=p['api_integration'];pin(ref['path'],ref['sha256'])
 sys.path.insert(0,p['api_app_root'])
 spec=importlib.util.spec_from_file_location('a_chain_current_api_integration',ref['path'])
 module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
 # The existing publisher uses this same external MODULE_CONTRACT_PATH binding.
 # Keep the original schema parser and all original lock functions unchanged.
 contract_path=Path(contract_ref['path']);module.MODULE_CONTRACT_PATH=contract_path
 original_contract=module.module_role_contract
 def pinned_contract():
  if module.MODULE_CONTRACT_PATH!=contract_path:raise Stop('API_MODULE_CONTRACT_PATH_DRIFT')
  pin(contract_path,contract_ref['sha256'])
  value=original_contract()
  if canonical(value)!=canonical(contract):raise Stop('API_MODULE_CONTRACT_READ_DRIFT')
  return value
 module.module_role_contract=pinned_contract
 module.module_role_contract()  # Fail before any guard acquisition.
 return module

def install_candidates(p):
 """Explicit reviewed immutable staging only; no service action or data copy."""
 import shutil
 roots=[Path(r['app_root']).parent for r in p['releases']]+[Path(p['graph']['final']).parent]
 if any(root.exists() or root.is_symlink() for root in roots):raise Stop('EXISTING_RELEASE_NO_RETRY')
 for release in p['releases']:
  root=Path(release['app_root']).parent
  if root.parent!=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases'):raise Stop('RELEASE_DESTINATION_SCOPE')
  root.mkdir();shutil.copytree(release['candidate_app'],root/'app');shutil.copy2(release['candidate_manifest'],root/'release-manifest.json')
 root=Path(p['graph']['final']).parent;root.mkdir()
 shutil.copy2(p['graph']['candidate'],root/'runtime-graph-config.json');shutil.copy2(p['graph']['binding_manifest'],root/'binding-manifest.json')
 installed(p)

def verify_review(path,want,p):
 receipt=json.loads(pin(path,want));freeze=json.loads(read(HERE/'FROZEN_CONTROL.json'))
 if receipt.get('verdict')!='PASS' or receipt.get('frozen_control_sha256')!=sha(read(HERE/'FROZEN_CONTROL.json')) or freeze['plan_sha256']!=sha(canonical(p)):raise Stop('INDEPENDENT_CONTROL_REVIEW_REQUIRED')
 for name,digest in freeze['files'].items():pin(HERE/name,digest)

def resume_states(p,h,o,run):
 states={};paths={}
 for role in ROLES:
  path=run/('owned-'+role+'.checkpoint.json');state=json.loads(read(path));observation=h['role_observations'][role]
  if state.get('schema')!='v4.native.four_role.v1' or state.get('operation_id')!=h['operation_id'] or state.get('plan_sha256')!=sha(canonical(p)) or state.get('original_identity')!=h['identities'][role]:raise Stop('CHECKPOINT_IMMUTABLE_SCOPE')
  if not isinstance(observation,dict) or set(observation)!={'phase','current_identity','disposition'} or observation['phase']!=state['phase']:raise Stop('EXPLICIT_RESUME_OBSERVATION_REQUIRED')
  phase=state['phase']
  if phase=='DONE':
   if observation['disposition']!='COMPLETED' or observation['current_identity']!=state['new']:raise Stop('COMPLETED_OBSERVATION')
   o.completed(role,state['new'])
  elif phase in ('WAITING_ROOT_ACK','ARMED'):
   if observation['disposition']!='ORIGINAL_UNTOUCHED' or observation['current_identity']!=state['original_identity'] or state.get('term_sent'):raise Stop('AMBIGUOUS_UNTOUCHED')
   o.original(role,state['original_identity'])
  elif phase in ('TERM_INTENT','DRAINING','AUX_WAIT_IDLE','AUX_KICK_INTENT','GUARD_CONFIRMED','GUARD_BOOTOUT_INTENT','WAIT_GUARD_GONE','CAS_INTENT','PLIST_APPLIED','OLD_DISABLE_INTENT','OLD_DISABLED','DEST_ENABLE_INTENT','DEST_ENABLED','BOOTSTRAP_INTENT','READBACK','HEALTH'):
   if observation['disposition']!='IN_PROGRESS':raise Stop('RESUME_DISPOSITION')
   labels_to_check=set(labels(role,o.reverse));identities=[]
   for label in labels_to_check:
    service=o.service_label(label)
    if service['loaded']:identities.append(o.identity(service['pid']) if service['pid'] else None)
   if len(identities)>1 or (identities[0] if identities else None)!=observation['current_identity']:raise Stop('RESUME_CURRENT_OWNER_DRIFT')
  else:raise Stop('STOPPED_OUTCOME_REQUIRES_PARENT_RECONCILIATION')
  states[role]=state;paths[role]=path
 return states,paths

def cli():
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,default=HERE/'PLAN.json');ap.add_argument('--execute-reviewed',action='store_true');ap.add_argument('--stage-reviewed',action='store_true');ap.add_argument('--reverse',action='store_true');ap.add_argument('--resume',action='store_true');ap.add_argument('--handoff',type=Path);ap.add_argument('--handoff-sha256');ap.add_argument('--review',type=Path);ap.add_argument('--review-sha256');a=ap.parse_args();p=json.loads(read(a.plan));scope(p)
 if a.execute_reviewed or a.stage_reviewed or a.reverse or a.resume:require_executable(p)
 if a.execute_reviewed and a.stage_reviewed:raise Stop('ONE_ACTION_ONLY')
 if not a.execute_reviewed and not a.stage_reviewed:print(json.dumps({'status':'PLAN_VALID_NO_ACTION','roles':ROLES}));return
 if os.getuid()!=501 or not all((a.review,a.review_sha256)):raise Stop('UID501_REVIEW_REQUIRED')
 if p['recovery'].get('normal_restore_argv_policy')!='PROGRAM_PREPENDED':raise Stop('PLATFORM_ARGV_ABI_UNVERIFIED_NO_ACTION')
 if a.stage_reviewed:
  verify_review(a.review,a.review_sha256,p);install_candidates(p);print(json.dumps({'status':'IMMUTABLE_RELEASES_STAGED_NO_LIFECYCLE'}));return
 if not a.handoff or not a.handoff_sha256:raise Stop('FRESH_HANDOFF_REQUIRED')
 verify_review(a.review,a.review_sha256,p);h=json.loads(pin(a.handoff,a.handoff_sha256));handoff(p,h,a.reverse);o=Live(p,a.reverse)
 if a.resume:raise Stop('GUARDIAN_RECONCILIATION_REQUIRED_BEFORE_NEW_COORDINATOR_RESUME')
 installed(p)
 recovery.start_guardian(sys.modules[__name__],p,h,a,HERE)
 try:
  recovery.ensure_guardian(sys.modules[__name__],p,h,HERE)
  o.protection(h);o.pdf_boundary()
  if not a.resume:o.initial_main_idle(h['main_readonly_identity'])
  states={};paths={};op=h['operation_id'];run=HERE/('owned-run-'+op)
  if a.resume:
   states,paths=resume_states(p,h,o,run)
  else:
   run.mkdir()  # no resume inference, no duplicate operation
   for role in ROLES:
    o.original(role,h['identities'][role]);path=run/('owned-'+role+'.checkpoint.json');paths[role]=path
    state={'schema':'v4.native.four_role.v1','phase':'WAITING_ROOT_ACK','operation_id':op,'plan_sha256':sha(canonical(p)),'original_identity':h['identities'][role],'children':{}};save(path,state);states[role]=state
   ready=HERE/('owned-request-'+op+'.json');helper=HERE/('owned-admin-'+op+'.sh')
   if ready.exists() or helper.exists():raise Stop('EXISTING_ADMIN_REQUEST_NO_RETRY')
   own=o.identity(os.getpid());save(ready,{'operation_id':op,'plan_sha256':sha(canonical(p)),'coordinator':own,'handoff_sha256':a.handoff_sha256,'guardian':h['guardian'],'checkpoints':{k:sha(read(v)) for k,v in paths.items()}})
   raw=root_helper(p,h,own,sha(read(ready)));fd2=os.open(helper,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
   with os.fdopen(fd2,'w') as f:f.write(raw);f.flush();os.fsync(f.fileno())
   print(json.dumps({'status':'WAITING_ONE_TIME_ADMIN_AUTH','helper':str(helper),'sha256':sha(raw.encode()),'expires_epoch':h['expires_epoch']}),flush=True)
   while not (Path(h['root_ack_dir'])/'COMPLETE').exists():
    recovery.ensure_guardian(sys.modules[__name__],p,h,HERE)
    if time.time()>h['expires_epoch']:raise Stop('ADMIN_REQUEST_EXPIRED_NO_SIGNAL')
    time.sleep(1)
  o.ack(h)
  for role in ROLES:
   recipe=Recipe(p,h,o,states[role],paths[role])
   try:
    while not recipe.step(role):time.sleep(1)
   except Stop as failure:
    if str(failure)=='API_HEALTH_FAILED_REQUIRES_GUARDED_ROLLBACK' and not a.reverse:
     auto_api_rollback(p,h,o,states[role],paths[role]);raise Stop('API_HEALTH_FAILED_ROLLED_BACK_BATCH_STOPPED') from failure
    raise
  save(HERE/('owned-finish-'+op+'.json'),{'operation_id':op,'status':'BOUND_REQUIRES_TARGET_AND_NATURAL_READBACK'})
  deadline=time.monotonic()+p['recovery']['cleanup_grace_seconds']+10
  outcome=recovery.outcome_path(HERE,op)
  while not outcome.exists():
   if time.monotonic()>deadline:raise Stop('GUARDIAN_DISCHARGE_UNCONFIRMED')
   time.sleep(.2)
  discharged=json.loads(read(outcome))
  if discharged.get('status')!='NORMAL_DONE_ALL_GUARDS_DISCHARGED':raise Stop('GUARDIAN_NORMAL_DISCHARGE_FAILED')
  print(json.dumps({'status':'BOUND_REQUIRES_TARGET_AND_NATURAL_READBACK','run':str(run),'reverse':a.reverse,'guardian':discharged}))
 except BaseException as failure:
  recovery.request_abort(sys.modules[__name__],h,HERE,str(failure));raise
 finally:
  if not (HERE/('owned-finish-'+h['operation_id']+'.json')).exists():
   recovery.request_abort(sys.modules[__name__],h,HERE,'COORDINATOR_EXIT_WITHOUT_DONE')
if __name__=='__main__':
 try:cli()
 except Exception as failure:print('STOP:'+str(failure),file=sys.stderr);raise SystemExit(2)
