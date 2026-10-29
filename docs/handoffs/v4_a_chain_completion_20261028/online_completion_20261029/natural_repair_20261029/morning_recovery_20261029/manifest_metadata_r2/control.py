"""Fixed metadata correction: two idle calendar labels, three exact CAS files."""
from pathlib import Path
from datetime import datetime
import argparse,hashlib,importlib.util,json,os,re,subprocess,sys,time
HERE=Path(__file__).resolve().parent
P=json.loads((HERE/'PLAN.json').read_bytes())
def digest(raw):return hashlib.sha256(raw).hexdigest()
def module(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
assert digest(Path(P['base_plan']).read_bytes())==P['base_plan_sha256']
assert digest((Path(P['base_control'])/'four_role_control.py').read_bytes())==P['base_controller_sha256']
assert digest((Path(P['base_control'])/'abort_guardian.py').read_bytes())==P['base_guardian_sha256']
C=module(Path(P['base_control'])/'four_role_control.py','metadata_original_control')
G=module(Path(P['base_control'])/'abort_guardian.py','metadata_original_guardian')
BASE=json.loads(C.read(P['base_plan']));LABELS={'stage':'com.lexi.stage-center.scheduler','precapture':'com.lexi.stage-center.a-opening-precapture'}

def validate(p):
 if p['schema']!='v4.stage.manifest_metadata_correction.v1' or p['labels']!=LABELS or [r['role'] for r in p['files']]!=['manifest','stage','precapture']:raise C.Stop('EXACT_METADATA_SCOPE')
 if p['app_root']!='/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-native-window-20261029-r1-stage/app' or p['release_id']!='a-native-window-20261029-r1-stage':raise C.Stop('SAME_STAGE_IDENTITY')
 a=json.loads(C.pin(p['files'][0]['before_file'],p['files'][0]['before_sha256']));b=json.loads(C.pin(p['files'][0]['after_file'],p['files'][0]['after_sha256']))
 rows=a['application_inventory']['entries'];expected=[dict(r,kind='file') for r in rows];fixed=json.loads(json.dumps(a));fixed['application_inventory']['entries']=expected;fixed['application_inventory']['aggregate_sha256']=C.sha(C.canonical(expected));fixed['app_files']=expected
 if b!=fixed or len(rows)!=984 or any('kind' in r for r in rows):raise C.Stop('KIND_ONLY_MANIFEST_DELTA')
 for r in p['files']:
  if Path(r['before_file']).parent!=HERE or Path(r['after_file']).parent!=HERE or C.metadata.digest(r['plist_metadata'])!=r['plist_metadata_sha256']:raise C.Stop('PREIMAGE_METADATA_SCOPE')
  C.pin(r['before_file'],r['before_sha256']);C.pin(r['after_file'],r['after_sha256'])
  if r['role']=='manifest':
   if r['plist']!=str(Path(p['app_root']).parent/'release-manifest.json'):raise C.Stop('MANIFEST_TARGET')
  else:
   if r['label']!=LABELS[r['role']] or r['plist']!='/Users/lexi/Library/LaunchAgents/'+r['label']+'.plist':raise C.Stop('PLIST_TARGET')
   old=__import__('plistlib').loads(C.read(r['before_file']));new=__import__('plistlib').loads(C.read(r['after_file']));old['EnvironmentVariables']['V4_RELEASE_MANIFEST_SHA256']=p['files'][0]['after_sha256']
   if old!=new or new.get('KeepAlive') or new.get('RunAtLoad'):raise C.Stop('PLIST_SHA_ONLY_CALENDAR_IDLE')
 return True

def fresh(h):
 C.handoff(BASE,h,False)
 if not 0<h['expires_epoch']-h['observed_epoch']<=90 or h['expires_epoch']>=datetime.fromisoformat(P['latest_expiry_exclusive']).timestamp():raise C.Stop('TTL_OR_1454_MARGIN_STOP')
 if time.time()>h['expires_epoch']:raise C.Stop('EXPIRED_NO_ACTION')
 if any(x['path'] in {r['plist'] for r in P['files']} for x in h['data_pins']):raise C.Stop('CAS_TARGET_CANNOT_BE_STATIC_PIN')

class Ops(C.r7.Live):
 def __init__(self):super().__init__({'operations':P['files']})
 def state(self,role):
  if role not in LABELS:raise C.Stop('NO_OTHER_SERVICE_ACTION')
  v=self.cmd(['/bin/launchctl','print','gui/501/'+LABELS[role]],True)
  if v.returncode==113 and 'Could not find service' in v.stderr:return {'loaded':False,'pid':None}
  if v.returncode:raise C.Stop('LOADED_UNKNOWN')
  m=re.search(r'^\s*pid = (\d+)$',v.stdout,re.M)
  return {'loaded':True,'pid':int(m[1]) if m else None,'text':v.stdout}
 def absent(self,role=None):
  if any(self.state(x)['loaded'] for x in LABELS):raise C.Stop('BOTH_LABELS_MUST_BE_ABSENT')
 def loaded(self,role,side):
  r=next(r for r in P['files'] if r['role']==role);v=self.state(role)
  if not v['loaded'] or v['pid']:raise C.Stop('CALENDAR_LABEL_NOT_IDLE')
  d=__import__('plistlib').loads(C.pin(r[side+'_file'],r[side+'_sha256']));text=v['text']
  for key,value in [('path',r['plist']),('working directory',d['WorkingDirectory']),('program',d['ProgramArguments'][0])]:
   if not re.search(r'^\t'+re.escape(key)+' = '+re.escape(value)+r'$',text,re.M):raise C.Stop('EXACT_LOADED_DEFINITION')
  match=re.search(r'^\targuments = \{\n(.*?)^\t\}',text,re.M|re.S)
  if not match or [v.strip() for v in match[1].splitlines() if v.strip()]!=d['ProgramArguments']:raise C.Stop('LOADED_ARGV')
  for key,value in d['EnvironmentVariables'].items():
   if not re.search(r'^\s*'+re.escape(key)+' => '+re.escape(str(value))+r'$',text,re.M):raise C.Stop('LOADED_ENV')
  if 'controller-supplied arguments' in text:raise C.Stop('FOREIGN_DEBUG_OVERRIDE')
 def action(self,action,role):
  if action not in ('bootout','bootstrap') or role not in LABELS:raise C.Stop('FIXED_COMMAND_ONLY')
  if action=='bootout':
   if not self.state(role)['loaded'] or self.state(role)['pid']:raise C.Stop('NO_HEALTHY_PROCESS_BOOTOUT')
   args=['/bin/launchctl','bootout','gui/501/'+LABELS[role]]
  else:
   if self.state(role)['loaded']:raise C.Stop('BOOTSTRAP_ABSENT_ONLY')
   args=['/bin/launchctl','bootstrap','gui/501','/Users/lexi/Library/LaunchAgents/'+LABELS[role]+'.plist']
  return self.cmd(args)

def run(a):
 validate(P)
 if not a.execute:print(json.dumps({'status':'VALIDATED_NO_ACTION'}));return
 if os.getuid()!=501:raise C.Stop('UID501_ONLY')
 review=json.loads(C.pin(a.review,a.review_sha256));freeze=json.loads(C.read(HERE/'FROZEN_CONTROL.json'))
 if review.get('verdict')!='PASS' or review.get('frozen_control_sha256')!=C.sha(C.read(HERE/'FROZEN_CONTROL.json')) or freeze['plan_sha256']!=C.sha(C.canonical(P)):raise C.Stop('INDEPENDENT_REVIEW_REQUIRED')
 for name,sha in freeze['files'].items():C.pin(HERE/name,sha)
 h=json.loads(C.pin(a.handoff,a.handoff_sha256));fresh(h);baseops=C.Live(BASE);ops=Ops();side='after' if a.inverse else 'before';target='before' if a.inverse else 'after'
 baseops.pdf_boundary();baseops.initial_main_idle(BASE['main_readonly']['identity'])
 with G.proof_locks(BASE,h,baseops):
  fresh(h);baseops.main_unchanged()
  for role in LABELS:ops.loaded(role,side)
  for r in P['files']:C.pin(r['plist'],r[side+'_sha256']);C.metadata.require(r['plist'],r['plist_metadata'])
  statepath=HERE/('operation-'+h['operation_id']+'.json')
  if statepath.exists():raise C.Stop('NO_OPERATION_REPLAY')
  state={'operation_id':h['operation_id'],'direction':'inverse_to_failed_preimage' if a.inverse else 'forward','steps':[],'status':'STARTED'}
  def intent(step):
   fresh(h);state['steps'].append({'step':step,'status':'INTENT','at':time.time()});C.save(statepath,state)
  def done():state['steps'][-1]['status']='DONE';C.save(statepath,state)
  try:
   for role in LABELS:
    intent('bootout_'+role);ops.action('bootout',role)
    if ops.state(role)['loaded']:raise C.Stop('BOOTOUT_UNKNOWN_NO_REPLAY')
    done()
   ops.absent()
   for r in P['files']:
    intent('CAS_'+r['role']);ops.cas(r['role'],reverse=a.inverse);done()
   for role in LABELS:
    intent('bootstrap_'+role);ops.action('bootstrap',role);ops.loaded(role,target);done()
   baseops.main_unchanged()
   for r in P['files']:C.pin(r['plist'],r[target+'_sha256']);C.metadata.require(r['plist'],r['plist_metadata'])
   if not a.inverse:
    v=subprocess.run([sys.executable,'-B',str(HERE/'probe_reader.py')],capture_output=True,text=True,timeout=15,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'});state['reader_probe']=json.loads(v.stdout) if v.returncode==0 else {'error':v.stderr};
    if v.returncode:raise C.Stop('ACTUAL_READER_FAILED_NEEDS_FRESH_INVERSE')
   state.update(status='METADATA_CORRECTION_READBACK_PASS' if not a.inverse else 'EXACT_FAILED_PREIMAGE_RESTORED_NOT_HEALTHY_PASS',finished_at=time.time());C.save(statepath,state);print(json.dumps(state))
  except BaseException as error:
   state.update(status='STOP_UNKNOWN_NO_AUTOMATIC_ACTION',error=str(error),reconcile='Retain locks until this return; inspect exact3 file SHAs and both loaded/PID states. No replay of unknown launchctl. Use fresh reviewed inverse only if all exactafter and idle, otherwise parent bounded reconciliation. Healthy process is never signalled.');C.save(statepath,state);raise

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');parser.add_argument('--inverse',action='store_true');parser.add_argument('--review',type=Path);parser.add_argument('--review-sha256');parser.add_argument('--handoff',type=Path);parser.add_argument('--handoff-sha256');run(parser.parse_args())
