"""Finite R5: finish existing auxiliary guards, or a distinct API control attempt.
No default actions; immutable failed operation records are never rewritten.
"""
from pathlib import Path
import argparse,fcntl,hashlib,importlib.util,json,os,re,shlex,stat,sys,time
HERE=Path(__file__).resolve().parent
CONTROL_SHA='48b826e23c7ae88020e29837a731d7113b0f028a29d3a7186e7fa7537ea39bac'
PRIOR_SHA='228fdcbd77a6bf22901ebeee74c7838c45024c439c209bc087fb277856c3a4e6'
AUX=('collector','stage','precapture','stage-deadline','review-daily','us')

def module(path,name,want):
 raw=path.read_bytes()
 if path.resolve()!=path or path.is_symlink() or hashlib.sha256(raw).hexdigest()!=want:raise RuntimeError('PINNED_SOURCE_DRIFT')
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def failures(c,p,h):
 old=h['prior_operation_id']
 if not re.fullmatch('[0-9a-f]{32}',old):raise c.Stop('PRIOR_OPERATION_SCOPE')
 root=c.HERE/('owned-run-'+old);names=('owned-api.checkpoint.json','owned-api-health-rollback.checkpoint.json')
 if set(h['failed_api_checkpoints'])!=set(names):raise c.Stop('EXACT_TWO_FAILURE_PINS')
 records=[json.loads(c.pin(root/n,h['failed_api_checkpoints'][n])) for n in names]
 if any(s.get('phase')!='HEALTH_FAILED' or s.get('operation_id')!=old or s.get('plan_sha256')!=c.sha(c.canonical(p)) for s in records) or records[0]['new']!=records[1]['original_identity']:raise c.Stop('FAILED_CHAIN_DRIFT')
 return root,records

def main_done(c,p,h,o,run):
 s=json.loads(c.pin(run/'owned-main.checkpoint.json',h['main_checkpoint_sha256']))
 if s.get('phase')!='DONE' or s['new']!=h['identities']['main']:raise c.Stop('MAIN_DONE_DRIFT')
 o.completed('main',s['new'])

def restored(c,p,h,run,capsule):
 _,records=failures(c,p,h);o=c.Live(p,True);identity=o.new('api')
 if identity!=records[1]['new'] or identity!=h['identities']['api']:raise c.Stop('RESTORED_API_IDENTITY_DRIFT')
 if not o.health(time.time()+30) or o.new('api')!=identity:raise c.Stop('RESTORED_API_BASELINE_NOT_MATCHED')
 path=capsule/'late-inverse-baseline-reconciliation.json'
 if path.exists():raise c.Stop('EXISTING_RECONCILIATION_NO_RETRY')
 c.save(path,{'status':'LATE_RESTORED_BASELINE_OBSERVED','prior_operation_id':h['prior_operation_id'],'failed_checkpoint_sha256':h['failed_api_checkpoints'],'identity':identity,'health_runtime_frontend_exact_baseline':True,'observed_epoch':time.time(),'prior_HEALTH_FAILED_preserved':True,'retroactive_30_second_pass':False})
 failures(c,p,h);return identity

def aux_states(c,p,h,o,prior,run):
 out={};paths={}
 if set(h['aux_checkpoint_sha256'])!=set(AUX):raise c.Stop('EXACT_SIX_AUX_PINS')
 for role in AUX:
  path=run/('owned-'+role+'.checkpoint.json');s=json.loads(c.pin(path,h['aux_checkpoint_sha256'][role]));wanted='AUX_WAIT_IDLE' if role=='collector' else 'WAITING_ROOT_ACK'
  if s.get('phase')!=wanted or s.get('operation_id')!=h['prior_operation_id'] or s.get('plan_sha256')!=c.sha(c.canonical(p)) or s.get('original_identity') is not None or s.get('children')!={}:raise c.Stop('AUX_CHECKPOINT_SCOPE')
  if role=='collector':
   ref=s['prearmed_reconciliation'];d=json.loads(c.pin(ref['path'],ref['sha256']))
   if d['current_guard']!=h['prearmed_collector']['guard'] or d['original_identity'] is not None:raise c.Stop('COLLECTOR_RECONCILIATION_DRIFT')
   prior.collector_guard(c,p,h,o)
  else:o.original(role,None);prior.pending_guard(c,p,o,role)
  out[role]=s;paths[role]=path
 return out,paths

def historical_aux_arm_proof(c,p,h,prior):
 ref=h['original_arm_proof'];proof=json.loads(c.pin(ref['path'],ref['sha256']));old=json.loads(c.pin(proof['handoff']['path'],proof['handoff']['sha256']))
 if old.get('operation_id')!=h['prior_operation_id'] or old.get('plan_sha256')!=c.sha(c.canonical(p)):raise c.Stop('HISTORICAL_AUX_ARM_SCOPE')
 # Historical proof context only; never passed as a fresh/current handoff.
 return prior.original_arm_proof(c,p,{**old,'original_arm_proof':ref})

def no_api_pending(c,p,o,expected):
 o.original('api',expected)
 text=o.service('api').get('text','')
 if re.search(r'^\s*[+] ',text,re.M) or 'controller-supplied arguments = {' in text:raise c.Stop('OLD_API_PENDING_OVERRIDE_NOT_EMPTY')

def api_helper(c,p,h,coordinator,ready,ready_sha,finish):
 """One fresh old-API arm; one finite new-API rollback arm. No other owner."""
 q=shlex.quote;r=c.row(p,'api');i=h['identities']['api'];op=h['operation_id'];target=h['root_ack_dir'];expiry=int(h['expires_epoch'])
 alive=f'[ "$(/bin/ps -ww -p {coordinator["pid"]} -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk \'{{print $1}}\')" = {coordinator["ps_sha256"]} ]'
 lines=['#!/bin/sh','set -eu','PATH=/usr/bin:/bin:/usr/sbin:/sbin','export PATH LC_ALL=C','[ "$#" -eq 0 ] && [ "$(/usr/bin/id -u)" = 0 ] || exit 2',f'[ "$(/bin/date +%s)" -le {expiry} ] || exit 2',alive+' || exit 2',f'[ "$(/usr/bin/shasum -a 256 {q(str(ready))} | /usr/bin/awk \'{{print $1}}\')" = {ready_sha} ] || exit 2',f'[ "$(/usr/bin/shasum -a 256 /bin/sleep | /usr/bin/awk \'{{print $1}}\')" = {p["guard_program_sha256"]} ] || exit 2',"/usr/bin/codesign -v -R='anchor apple' /bin/sleep",f'[ "$(/usr/bin/shasum -a 256 {q(r["plist"])} | /usr/bin/awk \'{{print $1}}\')" = {r["before_sha256"]} ] || exit 2',f'[ "$(/bin/ps -ww -p {i["pid"]} -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk \'{{print $1}}\')" = {i["ps_sha256"]} ] || exit 2',f'current=$(/bin/launchctl print gui/501/{c.OLD["api"]})',f'[ "$(printf \'%s\\n\' "$current" | /usr/bin/awk \'$1 == "pid" && $2 == "=" {{print $3}}\')" = {i["pid"]} ] || exit 2',"if printf '%s\\n' \"$current\" | /usr/bin/grep -Eq '^[[:space:]]*[+] |controller-supplied arguments = [{]'; then exit 2; fi",'umask 022',f'/bin/mkdir -m 755 {target} || exit 2']
 for name,value in [('operation_id',op),('nonce',h['nonce']),('plan_sha256',c.sha(c.canonical(p))),('request_sha256',ready_sha)]:lines += [f"printf '%s\\n' {q(value)} > {target}/{name}"]
 lines += [f'printf \'%s\\n\' "$$" > {target}/helper_pid',f'/bin/ps -ww -p $$ -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk \'{{print $1}}\' > {target}/helper_ps_sha256',f"printf '%s\\n' INTENT > {target}/api.intent",'set +e',f'/bin/launchctl debug gui/501/{c.OLD["api"]} --program /bin/sleep -- 604800 > {target}/api.stdout 2> {target}/api.stderr','result=$?','set -e',f'printf \'%s\\n\' "$result" > {target}/api.rc','[ "$result" -eq 0 ] || exit "$result"',f"printf '%s\\n' COMPLETE > {target}/COMPLETE"]
 rollback=c.HERE/('owned-api-rollback-'+op+'.json');label=c.NEW['api']
 lines += [f'while [ "$(/bin/date +%s)" -le {expiry} ]; do',alive+' || exit 2',f' [ ! -e {q(str(finish))} ] || exit 0',f' /bin/date +%s > {target}/.heartbeat',f' /bin/mv -f {target}/.heartbeat {target}/heartbeat',f' if [ -f {q(str(rollback))} ] && [ ! -L {q(str(rollback))} ]; then',f' [ "$(/usr/bin/stat -f %u {q(str(rollback))})" = 501 ] || exit 2',f' [ "$(/usr/bin/plutil -extract operation_id raw {q(str(rollback))})" = {op} ] || exit 2',f' [ "$(/usr/bin/plutil -extract plan_sha256 raw {q(str(rollback))})" = {c.sha(c.canonical(p))} ] || exit 2',f' pid=$(/usr/bin/plutil -extract pid raw {q(str(rollback))})',f' identity=$(/usr/bin/plutil -extract ps_sha256 raw {q(str(rollback))})',' case "$pid" in *[!0-9]*|"") exit 2;; esac',' if [ "$pid" -eq 0 ]; then',' [ "$identity" = NONE ] || exit 2',f' [ -z "$(/bin/launchctl print gui/501/{label} | /usr/bin/awk \'$1 == "pid" && $2 == "=" {{print $3}}\')" ] || exit 2',f' /bin/launchctl print gui/501/{label} > /dev/null',' else',' case "$identity" in *[!0-9a-f]*|"") exit 2;; esac',' [ "${#identity}" = 64 ] || exit 2',f' [ "$(/bin/launchctl print gui/501/{label} | /usr/bin/awk \'$1 == "pid" && $2 == "=" {{print $3}}\')" = "$pid" ] || exit 2',' [ "$(/bin/ps -ww -p "$pid" -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk \'{print $1}\')" = "$identity" ] || exit 2',' fi',f' [ "$(/usr/bin/shasum -a 256 {q(r["new_plist"])} | /usr/bin/awk \'{{print $1}}\')" = {r["after_sha256"]} ] || exit 2',f' /bin/mkdir -m 755 {target}/rollback-api || exit 2',' set +e',f' /bin/launchctl debug gui/501/{label} --program /bin/sleep -- 604800 > {target}/rollback-api/stdout 2> {target}/rollback-api/stderr',' result=$?',' set -e',f' printf \'%s\\n\' "$result" > {target}/rollback-api/rc',' [ "$result" -eq 0 ] || exit "$result"',f" printf '%s\\n' {op} > {target}/rollback-api/COMPLETE",' exit 0',' fi',' /bin/sleep 1','done','exit 0']
 return '\n'.join(lines)+'\n'

def api_ack(c,p,h,o,request_sha,prior):
 root=Path(h['root_ack_dir']);s=root.lstat()
 if root.parent!=Path('/private/var/tmp') or s.st_uid!=0 or not stat.S_ISDIR(s.st_mode) or s.st_mode&0o022:raise c.Stop('API_ROOT_ACK_DIRECTORY')
 def value(name):
  f=root/name;s=f.lstat()
  if s.st_uid!=0 or not stat.S_ISREG(s.st_mode) or s.st_mode&0o022:raise c.Stop('API_ROOT_ACK_FILE')
  return c.read(f).decode().strip()
 for name,want in [('operation_id',h['operation_id']),('nonce',h['nonce']),('plan_sha256',c.sha(c.canonical(p))),('request_sha256',request_sha),('api.rc','0'),('COMPLETE','COMPLETE')]:
  if value(name)!=want:raise c.Stop('API_ROOT_ACK_DRIFT')
 prior.lease_alive(c,h,o,value)

def reuse_api_plist(c,p,o,capsule):
 o.absent('api');r=c.row(p,'api')
 for key,want in [('plist','before_sha256'),('new_plist','after_sha256')]:c.pin(r[key],r[want]);c.metadata.require(r[key],r['plist_metadata'])
 o.cas_confirmed('api')
 path=capsule/'api-existing-plist-reconciliation.json'
 if path.exists():raise c.Stop('PLIST_RECONCILIATION_EXISTS_NO_RETRY')
 c.save(path,{'status':'EXACT_PRIOR_PUBLICATION_REUSED_WITHOUT_WRITE','before_sha256':r['before_sha256'],'after_sha256':r['after_sha256'],'new_label_unloaded':True,'old_label_unloaded':True,'observed_epoch':time.time()})

def finish_aux(c,p,h,o,ss,paths):
 for role in AUX:
  recipe=c.Recipe(p,h,o,ss[role],paths[role])
  while not recipe.step(role):time.sleep(1)

def api_state(c,p,h):
 if h['operation_id']==h['prior_operation_id'] or h['operation_id']!=h['nonce']:raise c.Stop('DISTINCT_API_STATE_REQUIRED')
 return {'schema':'v4.retirement.role.v1','phase':'WAITING_ROOT_ACK','operation_id':h['operation_id'],'prior_operation_id':h['prior_operation_id'],'failed_api_checkpoints':h['failed_api_checkpoints'],'plan_sha256':c.sha(c.canonical(p)),'original_identity':h['identities']['api'],'children':{}}

def cli():
 ap=argparse.ArgumentParser();ap.add_argument('--mode',choices=('aux','api'),required=True);ap.add_argument('--control-dir',type=Path,required=True);ap.add_argument('--prior-dir',type=Path,required=True);ap.add_argument('--handoff',type=Path,required=True);ap.add_argument('--handoff-sha256',required=True);ap.add_argument('--review',type=Path);ap.add_argument('--review-sha256');ap.add_argument('--execute-reviewed',action='store_true');a=ap.parse_args()
 c=module(a.control_dir/'retirement_control.py','r5_fixed_control',CONTROL_SHA);prior=module(a.prior_dir/'recover_remaining.py','r5_prior_readers',PRIOR_SHA);p=json.loads(c.read(c.HERE/'PLAN.json'));c.scope(p);h=json.loads(c.pin(a.handoff,a.handoff_sha256));c.handoff(p,h,False)
 if not re.fullmatch('[0-9a-f]{32}',h.get('nonce','')) or h['mode']!=a.mode:raise c.Stop('R5_MODE_NONCE')
 run,old=failures(c,p,h)
 if a.mode=='aux' and h['operation_id']!=h['prior_operation_id']:raise c.Stop('AUX_ORIGINAL_OPERATION_REQUIRED')
 if a.mode=='api' and (h['operation_id']!=h['nonce'] or h['operation_id']==h['prior_operation_id']):raise c.Stop('DISTINCT_NEW_API_CONTROL_ATTEMPT_REQUIRED')
 if not a.execute_reviewed:print(json.dumps({'status':'R5_INPUTS_VALID_NO_ACTION','mode':a.mode}));return
 if os.getuid()!=501 or not a.review or not a.review_sha256:raise c.Stop('UID501_REVIEW_REQUIRED')
 receipt=json.loads(c.pin(a.review,a.review_sha256));freeze=json.loads(c.read(HERE/'RECOVERY_FREEZE.json'))
 if receipt.get('verdict')!='PASS' or receipt.get('recovery_freeze_sha256')!=c.sha(c.read(HERE/'RECOVERY_FREEZE.json')) or freeze['plan_sha256']!=c.sha(c.canonical(p)):raise c.Stop('R5_INDEPENDENT_REVIEW_REQUIRED')
 for name,want in freeze['files'].items():c.pin(HERE/name,want)
 for name,want in freeze['control_dependencies'].items():c.pin(c.HERE/name,want)
 g=p['owner_guard'];fd=os.open(g['path'],os.O_RDWR|os.O_NOFOLLOW)
 try:
  s=os.fstat(fd)
  if (s.st_dev,s.st_ino)!=(g['device'],g['inode']):raise c.Stop('OWNER_FLOCK_IDENTITY')
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);base=c.Live(p);base.protection(h);base.pdf_boundary();c.installed(p);main_done(c,p,h,base,run)
  capsule=HERE/('owned-'+a.mode+'-'+h['nonce']);capsule.mkdir();restored(c,p,h,run,capsule)
  if a.mode=='aux':
   base.ack({'root_ack_dir':'/private/var/tmp/v4-retirement-nextspawn-'+h['prior_operation_id']});historical_aux_arm_proof(c,p,h,prior);ss,paths=aux_states(c,p,h,base,prior,run)
   class AuxLive(c.Live):
    def protection(self,hh):
     super().protection(hh);failures(c,p,h);main_done(c,p,h,self,run)
     if c.Live(p,True).new('api')!=h['identities']['api']:raise c.Stop('RESTORED_API_CHANGED_DURING_AUX')
     for role in AUX:
      if role!='collector' and ss[role]['phase'] in ('WAITING_ROOT_ACK','ARMED'):prior.pending_guard(c,p,self,role)
   o=AuxLive(p)
   finish_aux(c,p,h,o,ss,paths)
   failures(c,p,h);c.save(capsule/'finish.json',{'status':'SIX_AUX_BOUND_API_AND_MAIN_UNTOUCHED','prior_operation_id':h['prior_operation_id'],'nonce':h['nonce'],'natural_acceptance':'NOT_RUN'})
  else:
   no_api_pending(c,p,base,h['identities']['api']);r=c.row(p,'api');c.pin(r['new_plist'],r['after_sha256']);c.metadata.require(r['new_plist'],r['plist_metadata'])
   if (c.HERE/('owned-api-rollback-'+h['operation_id']+'.json')).exists():raise c.Stop('NEW_API_ROLLBACK_REQUEST_EXISTS')
   path=capsule/'owned-api.checkpoint.json';state=api_state(c,p,h);c.save(path,state)
   ready=capsule/'request.json';admin=capsule/'admin.sh';finish=capsule/'finish.json';coordinator=base.identity(os.getpid());c.save(ready,{'operation_id':h['operation_id'],'prior_operation_id':h['prior_operation_id'],'nonce':h['nonce'],'plan_sha256':c.sha(c.canonical(p)),'coordinator':coordinator,'handoff_sha256':a.handoff_sha256,'failed_api_checkpoints':h['failed_api_checkpoints']});request_sha=c.sha(c.read(ready));raw=api_helper(c,p,h,coordinator,ready,request_sha,finish)
   f=os.open(admin,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
   with os.fdopen(f,'w') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
   class ApiLive(c.Live):
    def ack(self,hh):
     api_ack(c,p,h,self,request_sha,prior)
     if state['phase'] in ('WAITING_ROOT_ACK','ARMED') and h['expires_epoch']-time.time()<120:raise c.Stop('API_ROLLBACK_LEASE_BUDGET')
    def protection(self,hh):
     super().protection(hh);failures(c,p,h);main_done(c,p,h,self,run)
     if state['phase']=='HEALTH_FAILED' and (Path(h['root_ack_dir'])/'rollback-api/COMPLETE').exists():c.rollback_ack(p,h)
     else:api_ack(c,p,h,self,request_sha,prior)
     if state['phase'] in ('WAITING_ROOT_ACK','ARMED'):prior.pending_guard(c,p,self,'api')
    def cas(self,role):
     if role!='api':raise c.Stop('API_ONLY_RECONCILE_SCOPE')
     reuse_api_plist(c,p,self,capsule)
   print(json.dumps({'status':'WAITING_ONE_TIME_API_ADMIN','helper':str(admin),'sha256':c.sha(raw.encode()),'operation_id':h['operation_id'],'prior_operation_id':h['prior_operation_id'],'expires_epoch':h['expires_epoch']}),flush=True)
   while not (Path(h['root_ack_dir'])/'heartbeat').exists():
    if time.time()>h['expires_epoch']:raise c.Stop('API_ADMIN_EXPIRED_NO_SIGNAL')
    time.sleep(1)
   c.handoff(p,h,False);o=ApiLive(p);recipe=c.Recipe(p,h,o,state,path)
   try:
    while not recipe.step('api'):time.sleep(1)
   except c.Stop as failure:
    if str(failure)=='API_HEALTH_FAILED_REQUIRES_GUARDED_ROLLBACK':c.auto_api_rollback(p,h,o,state,path);raise c.Stop('NEW_API_ATTEMPT_ROLLED_BACK_BATCH_STOPPED') from failure
    raise
   failures(c,p,h);c.save(finish,{'status':'NEW_API_ATTEMPT_BOUND_REQUIRES_TARGET_AND_NATURAL_READBACK','operation_id':h['operation_id'],'prior_operation_id':h['prior_operation_id'],'failed_records_preserved':True})
  print(json.dumps({'status':'R5_MODE_COMPLETE','mode':a.mode,'capsule':str(capsule)}))
 finally:os.close(fd)
if __name__=='__main__':
 try:cli()
 except Exception as failure:print('STOP:'+str(failure),file=sys.stderr);raise SystemExit(2)
