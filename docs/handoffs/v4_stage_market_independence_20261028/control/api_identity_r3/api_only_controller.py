"""API-only immutable identity-metadata successor. Default read-only.
Reuse SHA-pinned R7 drain/CAS/recovery primitives; no Main lifecycle capability.
"""
from pathlib import Path
import argparse,fcntl,importlib.util,json,os,plistlib,re,shlex,signal,stat,sys,time,urllib.request,urllib.error
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
BASE_SHA='44c65823ed11d6819939b3ac10388a74c3c879379a5b615249b170f81239c80e'
import hashlib
if hashlib.sha256((BASE/'main_api_controller.py').read_bytes()).hexdigest()!=BASE_SHA:raise RuntimeError('PINNED_BASE_DRIFT')
spec=importlib.util.spec_from_file_location('r7_api_identity_base',BASE/'main_api_controller.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
ROLE='api';LABEL='com.lexi.v35.api-only'
read,pin,load,save,sha,canonical,Stop=b.read,b.pin,b.load,b.save,b.sha,b.canonical,b.Stop

def scope(p):
 if p['schema']!='v4.api_identity_successor_r3.v1' or len(p['operations'])!=1 or p['operations'][0]['label']!=LABEL:raise Stop('API_ONLY_SCOPE')
 r=p['operations'][0];release=p['releases'][0];wanted='stage-market-independence-20261028-r7-api-identity-r3';root='/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/'+wanted
 if r['plist']!='/Users/lexi/Library/LaunchAgents/'+LABEL+'.plist' or r['role']!='api' or p['expected_original_pids']!={'api':67002} or release['release_id']!=wanted or release['app_root']!=root+'/app' or release['manifest']!=root+'/release-manifest.json':raise Stop('FIXED_API_ONLY_IDENTITY')
 before=plistlib.loads(pin(r['before_file'],r['before_sha256']));after=plistlib.loads(pin(r['after_file'],r['after_sha256']));oldroot=str(Path(before['WorkingDirectory']).parent);newroot=root;oldsha=before['EnvironmentVariables']['V35_RELEASE_MANIFEST_SHA256']
 def rewrite(v):
  if isinstance(v,str):return v.replace(oldroot,newroot).replace(oldsha,release['manifest_sha256']).replace('V35_RELEASE_ID=mac-panel-r5-rebound-20261028-r1-api','V35_RELEASE_ID='+wanted)
  if isinstance(v,list):return [rewrite(x) for x in v]
  if isinstance(v,dict):return {k:rewrite(x) for k,x in v.items()}
  return v
 expected=rewrite(before);expected['EnvironmentVariables']['V35_RELEASE_ID']=wanted
 if expected!=after:raise Stop('NON_BINDING_CHANGE')
 m=load(release['candidate_manifest']);baseline=load(Path(r['old_app_root']).parent/'release-manifest.json')
 if sha(read(release['candidate_manifest']))!=release['manifest_sha256'] or m['schema_version']!='v4.release_candidate.v1' or m['candidate']!={'root':root,'app_root':root+'/app','release_id':wanted,'module_role':'gateway'}:raise Stop('CANONICAL_API_METADATA')
 for key in ('app_files','application_inventory','files'):
  if m[key]!=baseline[key]:raise Stop('APP_SOURCE_INVENTORY_CHANGED')
 for key,value in baseline.items():
  if key.startswith('external_') and m[key]!=value:raise Stop('DEPENDENCY_CHANGED')
 if p['protected_main_identity']['pid']!=66933 or p['guard_seconds']!=604800 or p['base_source_sha256']!=BASE_SHA:raise Stop('PROTECTION_SCOPE')
 if b.metadata.digest(r['plist_metadata'])!=r['plist_metadata_sha256']:raise Stop('METADATA_DIGEST')
 if p['RESEARCH_ONLY'] is not True or any(p[k] is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):raise Stop('SAFETY')
 return True

def handoff(p,h):
 if not re.fullmatch('[a-f0-9]{32}',str(h.get('operation_id',''))) or h.get('root_ack_dir')!='/private/var/tmp/v4-api-id-r3-'+h['operation_id']:raise Stop('OPERATION_SCOPE')
 if h.get('plan_sha256')!=sha(canonical(p)) or h.get('identities')!={'api':p['expected_api_identity']}:raise Stop('HANDOFF_IDENTITY')
 if not h['observed_epoch']<=time.time()<h['expires_epoch'] or h['expires_epoch']-h['observed_epoch']>300:raise Stop('EXPIRED_HANDOFF')
 if any(h.get(k) is not True for k in ('no_parallel_lifecycle_owner','no_active_dependent_api_query','api_brief_new_connection_gap_coordinated')):raise Stop('API_COORDINATION')
 if h.get('data_pins')!=p['data_pins'] or h.get('data_stats')!=p['data_stats']:raise Stop('DATA31_BINDING_CHANGED')
 return True

def root_helper(p,h,coordinator,ready_sha):
 op=h['operation_id'];q=shlex.quote;root=h['root_ack_dir'];r=p['operations'][0];old=p['expected_api_identity'];ready=HERE/('request-'+op+'.json')
 checks=[('[ "$(/usr/bin/id -u)" = 0 ]','ROOT_REQUIRED'),(f'[ "$(/bin/date +%s)" -le {int(h["expires_epoch"])} ]','EXPIRED'),(f'[ "$(/bin/ps -ww -p {coordinator["pid"]} -o lstart=,command= | /usr/bin/shasum -a256 | /usr/bin/awk \'{{print $1}}\')" = {coordinator["ps_sha256"]} ]','COORDINATOR_GONE'),(f'[ "$(/usr/bin/shasum -a256 {q(str(ready))} | /usr/bin/awk \'{{print $1}}\')" = {ready_sha} ]','READY_CHANGED'),(f'[ "$(/bin/ps -ww -p {old["pid"]} -o lstart=,command= | /usr/bin/shasum -a256 | /usr/bin/awk \'{{print $1}}\')" = {old["ps_sha256"]} ]','API_CHANGED'),(f'[ "$(/bin/launchctl print gui/501/{LABEL} | /usr/bin/awk \'$1 == "pid" && $2 == "=" {{print $3}}\')" = {old["pid"]} ]','LABEL_CHANGED'),(f'[ "$(/usr/bin/shasum -a256 {q(r["plist"])} | /usr/bin/awk \'{{print $1}}\')" = {r["before_sha256"]} ]','PLIST_CHANGED'),(f'[ "$(/usr/bin/shasum -a256 /bin/sleep | /usr/bin/awk \'{{print $1}}\')" = {p["guard_program_sha256"]} ]','SLEEP_CHANGED')]
 lines=['#!/bin/sh','set -eu','PATH=/usr/bin:/bin:/usr/sbin:/sbin','export PATH LC_ALL=C','[ "$#" -eq 0 ] || exit 2']+[f'{check} || {{ echo {reason} >&2; exit 2; }}' for check,reason in checks]
 lines += ["/usr/bin/codesign -v -R='anchor apple' /bin/sleep",'umask 022',f'/bin/mkdir -m755 {root} || {{ echo EXISTING_INTENT_NO_RETRY >&2; exit 2; }}',f"printf '%s\\n' {sha(canonical(p))} > {root}/plan_sha256",f"printf '%s\\n' INTENT > {root}/api.intent",'set +e',f'/bin/launchctl debug gui/501/{LABEL} --program /bin/sleep -- 604800 > {root}/api.stdout 2> {root}/api.stderr','result=$?','set -e',f"printf '%s\\n' \"$result\" > {root}/api.rc",'[ "$result" -eq 0 ] || exit "$result"',f"printf '%s\\n' COMPLETE > {root}/COMPLETE"]
 return '\n'.join(lines)+'\n'

class ApiLive(b.Live):
 def cmd(self,args,missing=False):
  if args[0]=='/bin/launchctl' and args[1] in ('bootout','bootstrap','debug','disable','kickstart'):
   allowed=(args==['/bin/launchctl','bootout','gui/501/'+LABEL] or args==['/bin/launchctl','bootstrap','gui/501',self.p['operations'][0]['plist']])
   if not allowed:raise Stop('ONLY_API_GUARD_BOOTOUT_OR_API_BOOTSTRAP')
  return super().cmd(args,missing)
 def protection(self,h):
  super().protection(h)
  release=self.p['releases'][0];pin(release['manifest'],release['manifest_sha256'])
  i=self.p['protected_main_identity']
  if self.identity(i['pid'])!=i:raise Stop('PROTECTED_MAIN_CHANGED')
  s=self.cmd(['/bin/launchctl','print','gui/501/com.lexi.v35.scheduler']).stdout
  if not re.search(r'^\s*pid = '+str(i['pid'])+r'\s*$',s,re.M):raise Stop('PROTECTED_MAIN_LABEL_CHANGED')
 def pdf_boundary(self):pass # API owns HTTP/lifespan, no Main PDF hook.
 def term(self,role,i):
  if role!='api' or i!=self.p['expected_api_identity']:raise Stop('ONLY_ORIGINAL_API_TERM')
  self.original(role,i);os.kill(i['pid'],signal.SIGTERM)
 def ack(self,h):
  root=Path(h['root_ack_dir']);s=root.lstat()
  if root.parent!=Path('/private/var/tmp') or root.name!='v4-api-id-r3-'+h['operation_id'] or not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise Stop('ROOT_ACK_DIRECTORY')
  for name,want in [('plan_sha256',sha(canonical(self.p))),('api.rc','0'),('COMPLETE','COMPLETE')]:
   f=root/name;s=f.lstat()
   if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022 or read(f).decode().strip()!=want:raise Stop('ROOT_ACK_INVALID')
 def frontend(self,identity):
  deadline=time.monotonic()+15
  while True:
   try:
    with urllib.request.urlopen('http://127.0.0.1:8873/api/v3/runtime-graph/frontend-build',timeout=3) as response:front=json.loads(response.read())
    with urllib.request.urlopen('http://127.0.0.1:8873/api/v3/runtime-graph/status',timeout=5) as response:runtime=json.loads(response.read())['runtime_identity']
    break
   except (urllib.error.URLError,TimeoutError):
    if time.monotonic()>=deadline:raise Stop('NEW_API_READBACK_UNAVAILABLE')
    time.sleep(.25)
  expected=self.p['frontend_expected']
  if front.get('status')!='VERIFIED' or any(front.get(k)!=v for k,v in expected.items()):raise Stop('FRONTEND_BUILD_IDENTITY_NOT_VERIFIED')
  if runtime.get('pid')!=identity['pid'] or runtime.get('release_id_declared')!=expected['api_release_id'] or runtime.get('release_manifest_sha256_declared')!=expected['api_manifest_sha256'] or runtime.get('cwd')!=self.p['releases'][0]['app_root']:raise Stop('ACTUAL_EFFECTIVE_API_OWNER_MISMATCH')
  if self.identity(identity['pid'])!=identity:raise Stop('API_OWNER_CHANGED_DURING_FRONTEND_READBACK')
  save(HERE/'FRONTEND_EFFECTIVE_READBACK.json',{'frontend_build':front,'api_identity':identity,'effective_runtime_fields':{k:runtime.get(k) for k in ('pid','cwd','release_id_declared','release_manifest_sha256_declared','app_root','release_id_status')},'health200_is_not_oracle':True})
 def new(self,role):
  i=super().new(role);self.frontend(i);return i

class ApiRecipe(b.Recipe):
 def step(self,role):
  if role!='api':raise Stop('API_ONLY_RECIPE')
  if self.s['phase']=='ARMED':
   self.o.protection(self.h);handoff(self.p,self.h);self.o.ack(self.h);self.o.original(role,self.h['identities'][role]);children=self.o.descendants(self.h['identities'][role]['pid']);self.record('TERM_INTENT',children=children);self.o.term(role,self.h['identities'][role]);self.record('DRAINING',term_sent=True);return False
  return super().step(role)

def cli():
 ap=argparse.ArgumentParser();ap.add_argument('--execute-reviewed',action='store_true');ap.add_argument('--handoff');ap.add_argument('--handoff-sha256');ap.add_argument('--review');ap.add_argument('--review-sha256');ap.add_argument('--resume',action='store_true');a=ap.parse_args();p=load(HERE/'PLAN.json');scope(p)
 if not a.execute_reviewed:print('API_IDENTITY_SUCCESSOR_PLAN_VALID_NO_ACTION');return
 if os.getuid()!=501 or not all((a.handoff,a.handoff_sha256,a.review,a.review_sha256)):raise Stop('UID501_HANDOFF_REVIEW_REQUIRED')
 frozen=read(HERE/'FREEZE.json');review=json.loads(pin(a.review,a.review_sha256))
 if review.get('verdict')!='PASS' or review.get('frozen_control_sha256')!=sha(frozen):raise Stop('EXACT_INDEPENDENT_PASS_REQUIRED')
 for name,digest in json.loads(frozen)['files'].items():pin(HERE/name,digest)
 h=json.loads(pin(a.handoff,a.handoff_sha256));handoff(p,h);ops=ApiLive(p);g=p['owner_guard'];fd=os.open(g['path'],os.O_RDWR|os.O_NOFOLLOW)
 try:
  s=os.fstat(fd)
  if (s.st_dev,s.st_ino)!=(g['device'],g['inode']):raise Stop('OWNER_GUARD_INODE')
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);ops.protection(h);checkpoint=HERE/'owned-api.checkpoint.json'
  if not a.resume:
   ops.original('api',h['identities']['api'])
   if checkpoint.exists():raise Stop('EXISTING_CHECKPOINT_RESUME_REQUIRED')
   state=dict(phase='WAITING_ROOT_ACK',operation_id=h['operation_id'],plan_sha256=sha(canonical(p)),original_identity=h['identities']['api'],children={});save(checkpoint,state)
   ready=HERE/('request-'+h['operation_id']+'.json');helper=HERE/('admin-'+h['operation_id']+'.sh')
   if ready.exists() or helper.exists():raise Stop('EXISTING_REQUEST_NO_RETRY')
   owner=ops.identity(os.getpid());save(ready,dict(operation_id=h['operation_id'],coordinator=owner,plan_sha256=sha(canonical(p)),checkpoint_sha256=sha(read(checkpoint)),handoff_sha256=a.handoff_sha256,expires_epoch=h['expires_epoch']));raw=root_helper(p,h,owner,sha(read(ready)));fd2=os.open(helper,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
   with os.fdopen(fd2,'w') as f:f.write(raw);f.flush();os.fsync(f.fileno())
   print(json.dumps({'status':'WAITING_ONE_API_TERMINAL_AUTH','helper':str(helper),'sha256':sha(raw.encode()),'expires_epoch':h['expires_epoch']}),flush=True)
   while not (Path(h['root_ack_dir'])/'COMPLETE').exists():
    if time.time()>h['expires_epoch']:raise Stop('REQUEST_EXPIRED_NO_TERM')
    time.sleep(1)
  else:
   state=load(checkpoint)
   if state.get('operation_id')!=h['operation_id'] or state.get('plan_sha256')!=sha(canonical(p)) or state.get('original_identity')!=h['identities']['api']:raise Stop('RESUME_SCOPE')
  ops.ack(h);recipe=ApiRecipe(p,h,ops,state,checkpoint)
  while not recipe.step('api'):time.sleep(.25)
  ops.protection(h);print(json.dumps({'status':'API_EFFECTIVE_RELEASE_AND_FRONTEND_VERIFIED','identity':state['new']}))
 finally:os.close(fd)
if __name__=='__main__':
 try:cli()
 except Exception as e:print('STOP:'+str(e),file=sys.stderr);raise SystemExit(2)
