"""Finite same-operation continuation after independently accepted Main recovery.

No default actions. Imports the fixed reviewed recipe; never dispatches Main.
Private plans, identities and per-run nonces are supplied separately.
"""
from __future__ import annotations
import argparse, fcntl, hashlib, importlib.util, json, os, plistlib, re, shlex, stat, sys, time
from pathlib import Path

CONTROL_SHA='a1a73b71b065702fb4cd201d95fc4be2710a3231627482c3216265ea92276e58'
REMAINING=('api','collector','stage','precapture','stage-deadline','review-daily','us')
HERE=Path(__file__).resolve().parent

def load_control(root):
 root=Path(root)
 if root.resolve()!=root:raise RuntimeError('CONTROL_ALIAS')
 raw=(root/'retirement_control.py').read_bytes()
 if hashlib.sha256(raw).hexdigest()!=CONTROL_SHA:raise RuntimeError('CONTROL_SHA_DRIFT')
 spec=importlib.util.spec_from_file_location('recovery_fixed_control',root/'retirement_control.py')
 c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c);return c

def validate(c,p,l):
 if l.get('schema')!='v4.retirement.remaining_lease.r1' or not re.fullmatch('[0-9a-f]{32}',l.get('nonce','')):raise c.Stop('LEASE_SCOPE')
 if set(l['identities'])!=set(REMAINING) or set(l['checkpoint_sha256'])!=set(REMAINING):raise c.Stop('EXACT_REMAINING_SEVEN')
 observation=l.get('prearmed_collector')
 if not isinstance(observation,dict) or set(observation)!={'guard','original_checkpoint_sha256'} or l['identities']['collector'] is not None or observation['original_checkpoint_sha256']!=l['checkpoint_sha256']['collector']:raise c.Stop('EXACT_PREARMED_COLLECTOR_OBSERVATION')
 guard=observation['guard']
 if not isinstance(guard,dict) or set(guard)!={'pid','ps_sha256','ps_text'} or type(guard['pid']) is not int or guard['pid']<=1 or not re.fullmatch('[0-9a-f]{64}',str(guard['ps_sha256'])) or not isinstance(guard['ps_text'],str) or c.sha(guard['ps_text'].encode())!=guard['ps_sha256'] or not re.search(r'(?:^|\s)/bin/sleep 604800\s*$',guard['ps_text']):raise c.Stop('COLLECTOR_GUARD_IDENTITY_SCHEMA')
 if l['main']['phase']!='DONE' or not l['main'].get('new_identity'):raise c.Stop('MAIN_DONE_REQUIRED')
 if l['root_ack_dir']!='/private/var/tmp/v4-retirement-renew-'+l['operation_id']+'-'+l['nonce']:raise c.Stop('LEASE_ACK_SCOPE')
 # All entries describe current reality: Main is the completed new owner.
 # Main's immutable old identity remains only in its original checkpoint.
 h={**l,'identities':{'main':l['main']['new_identity'],**l['identities']},'role_observations':{'main':{'phase':'DONE','current_identity':l['main']['new_identity'],'disposition':'COMPLETED'},**{r:{'phase':'WAITING_ROOT_ACK','current_identity':l['identities'][r],'disposition':'ORIGINAL_UNTOUCHED'} for r in REMAINING}},'root_ack_dir':'/private/var/tmp/v4-retirement-nextspawn-'+l['operation_id'],'reverse':False}
 h['role_observations']['collector']={'phase':'WAITING_ROOT_ACK','current_identity':guard,'disposition':'IN_PROGRESS'}
 c.handoff(p,h,False)
 original_arm_proof(c,p,l)
 return {**h,'recovery_root_ack_dir':l['root_ack_dir']}

def original_arm_proof(c,p,l):
 ref=l.get('original_arm_proof',{})
 if ref.get('path')!=str(HERE/'ORIGINAL_ARM_PROOF.private.json'):raise c.Stop('ORIGINAL_ARM_PROOF_SCOPE')
 proof=json.loads(c.pin(ref['path'],ref.get('sha256')))
 op=l['operation_id'];root='/private/var/tmp/v4-retirement-nextspawn-'+op
 if proof.get('schema')!='v4.retirement.original_arms_proof.r1' or proof.get('operation_id')!=op or proof.get('plan_sha256')!=c.sha(c.canonical(p)) or proof.get('root_ack_dir')!=root:raise c.Stop('ORIGINAL_ARM_PROOF_IDENTITY')
 for key,name in [('helper','owned-admin-'+op+'.sh'),('request','owned-request-'+op+'.json')]:
  if proof[key]['path']!=str(c.HERE/name):raise c.Stop('ORIGINAL_ARM_SOURCE_SCOPE')
  c.pin(proof[key]['path'],proof[key]['sha256'])
 request=json.loads(c.read(proof['request']['path']))
 expected_handoff=c.HERE.parents[1]/'controller'/('LIVE_HANDOFF_'+op+'.json')
 if proof['handoff']['path']!=str(expected_handoff) or request.get('handoff_sha256')!=proof['handoff']['sha256'] or request.get('operation_id')!=op or request.get('plan_sha256')!=proof['plan_sha256']:raise c.Stop('ORIGINAL_REQUEST_HANDOFF_IDENTITY')
 old=json.loads(c.pin(proof['handoff']['path'],proof['handoff']['sha256']))
 if old.get('operation_id')!=op or old.get('plan_sha256')!=proof['plan_sha256'] or any(old['identities'][role]!=l['identities'][role] for role in REMAINING):raise c.Stop('ORIGINAL_HANDOFF_REMAINING_IDENTITIES')
 if c.sha(c.root_helper(p,old,request['coordinator'],proof['request']['sha256']).encode())!=proof['helper']['sha256']:raise c.Stop('ORIGINAL_REVIEWED_HELPER_RECONSTRUCTION')
 expected={'plan_sha256','COMPLETE',*[role+'.rc' for role in c.ROLES]}
 if set(proof['root_files'])!=expected:raise c.Stop('ORIGINAL_ARM_ACK_SET')
 for name,want in proof['root_files'].items():c.pin(Path(root)/name,want)
 c.Live(p).ack({'root_ack_dir':root})
 return proof

def pending_guard(c,p,o,role):
 """Strict host-specific print readback; unknown format fails closed, not portable."""
 if role not in REMAINING or role=='collector':raise c.Stop('PENDING_ARM_ROLE_SCOPE')
 row=c.row(p,role);c.pin(row['plist'],row['before_sha256']);c.metadata.require(row['plist'],row['plist_metadata'])
 before=plistlib.loads(c.pin(row['before_file'],row['before_sha256']))
 text=o.service(role).get('text','')
 programs=re.findall(r'^\tprogram = (.*)\n\t\t[+] /bin/sleep\n',text,re.M)
 if programs!=[before['ProgramArguments'][0]] or len(re.findall(r'^\s*[+] ',text,re.M))!=1:raise c.Stop('ORIGINAL_PENDING_PROGRAM_NOT_VERIFIED:'+role)
 for field,want in [('path',row['plist']),('working directory',before['WorkingDirectory'])]:
  if re.findall(r'^\t'+re.escape(field)+r' = (.*)$',text,re.M)!=[want]:raise c.Stop('ORIGINAL_LOADED_BINDING_NOT_VERIFIED:'+role)
 arguments=re.findall(r'^\targuments = \{\n(.*?)^\t\}',text,re.M|re.S)
 if len(arguments)!=1 or [v.strip() for v in arguments[0].splitlines() if v.strip()]!=before['ProgramArguments']:raise c.Stop('ORIGINAL_LOADED_ARGV_NOT_VERIFIED:'+role)
 environments=re.findall(r'^\tenvironment = \{\n(.*?)^\t\}',text,re.M|re.S)
 env=dict(re.findall(r'^\s*([^\s]+) => (.*)$',environments[0],re.M)) if len(environments)==1 else {}
 if any(env.get(k)!=str(v) for k,v in before['EnvironmentVariables'].items()):raise c.Stop('ORIGINAL_LOADED_ENV_NOT_VERIFIED:'+role)
 blocks=re.findall(r'^\tcontroller-supplied arguments = \{\n(.*?)^\t\}',text,re.M|re.S)
 if len(blocks)!=1 or [v.strip() for v in blocks[0].splitlines() if v.strip()]!=['/bin/sleep','604800']:raise c.Stop('ORIGINAL_PENDING_ARGUMENTS_NOT_VERIFIED:'+role)

def collector_guard(c,p,l,o):
 """Only the consumed original collector nextspawn; immutable identity stays None."""
 r=c.row(p,'collector');expected=l['prearmed_collector']['guard']
 c.pin(r['plist'],r['before_sha256']);c.metadata.require(r['plist'],r['plist_metadata'])
 if o.disabled(c.OLD['collector'])!=r['old_disabled_before'] or o.service_label(c.NEW['collector'])['loaded']:raise c.Stop('COLLECTOR_BINDING_DRIFT')
 actual=o.guard('collector',None)
 if actual!=expected:raise c.Stop('COLLECTOR_PREARMED_GUARD_DRIFT')
 cwd=o.cmd(['/usr/sbin/lsof','-a','-p',str(actual['pid']),'-d','cwd','-Fn']).stdout
 if [v[1:] for v in cwd.splitlines() if v.startswith('n')]!=[r['old_working_directory']]:raise c.Stop('COLLECTOR_GUARD_CWD')
 return actual

def states(c,p,l,o,run):
 main_path=run/'owned-main.checkpoint.json';m=json.loads(c.pin(main_path,l['main']['checkpoint_sha256']))
 if m.get('phase')!='DONE' or m.get('operation_id')!=l['operation_id'] or m.get('plan_sha256')!=c.sha(c.canonical(p)) or m.get('new')!=l['main']['new_identity']:raise c.Stop('MAIN_CHECKPOINT_DRIFT')
 o.completed('main',m['new']);out={};paths={}
 for role in REMAINING:
  path=run/('owned-'+role+'.checkpoint.json');s=json.loads(c.pin(path,l['checkpoint_sha256'][role]))
  if s.get('schema')!='v4.retirement.role.v1' or s.get('phase')!='WAITING_ROOT_ACK' or s.get('operation_id')!=l['operation_id'] or s.get('plan_sha256')!=c.sha(c.canonical(p)) or s.get('original_identity')!=l['identities'][role] or s.get('term_sent') or s.get('children')!={}:raise c.Stop('UNTOUCHED_CHECKPOINT_REQUIRED')
  if role=='collector':collector_guard(c,p,l,o)
  else:o.original(role,s['original_identity']);pending_guard(c,p,o,role)
  out[role]=s;paths[role]=path
 return out,paths

def helper(c,p,l,coordinator,request,request_sha,finish):
 """Reuses verified original arms. Only one fixed new-API rollback arm exists."""
 q=shlex.quote;target=l['root_ack_dir'];expiry=int(l['expires_epoch']);op=l['operation_id']
 alive=f'[ "$(/bin/ps -ww -p {coordinator["pid"]} -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk \'{{print $1}}\')" = {coordinator["ps_sha256"]} ]'
 lines=['#!/bin/sh','set -eu','PATH=/usr/bin:/bin:/usr/sbin:/sbin','export PATH LC_ALL=C','[ "$#" -eq 0 ] && [ "$(/usr/bin/id -u)" = 0 ] || exit 2',f'[ "$(/bin/date +%s)" -le {expiry} ] || exit 2',alive+' || exit 2',f'[ "$(/usr/bin/shasum -a 256 {q(str(request))} | /usr/bin/awk \'{{print $1}}\')" = {request_sha} ] || exit 2',f'[ "$(/usr/bin/shasum -a 256 /bin/sleep | /usr/bin/awk \'{{print $1}}\')" = {p["guard_program_sha256"]} ] || exit 2',"/usr/bin/codesign -v -R='anchor apple' /bin/sleep"]
 for role in REMAINING:
  r=c.row(p,role);i=l['prearmed_collector']['guard'] if role=='collector' else l['identities'][role];label=c.OLD[role]
  lines += [f'[ "$(/usr/bin/shasum -a 256 {q(r["plist"])} | /usr/bin/awk \'{{print $1}}\')" = {r["before_sha256"]} ] || exit 2']
  if i:lines += [f'[ "$(/bin/ps -ww -p {i["pid"]} -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk \'{{print $1}}\')" = {i["ps_sha256"]} ] || exit 2',f'[ "$(/bin/launchctl print gui/501/{label} | /usr/bin/awk \'$1 == "pid" && $2 == "=" {{print $3}}\')" = {i["pid"]} ] || exit 2']
  else:lines += [f'[ -z "$(/bin/launchctl print gui/501/{label} | /usr/bin/awk \'$1 == "pid" && $2 == "=" {{print $3}}\')" ] || exit 2']
  if role!='collector':
   lines += [f'pending=$(/bin/launchctl print gui/501/{label})',"printf '%s\\n' \"$pending\" | /usr/bin/grep -Eq '^[[:space:]]*[+] /bin/sleep[[:space:]]*$' || exit 2",'''[ "$(printf '%s\\n' "$pending" | /usr/bin/awk '/controller-supplied arguments = [{]/{on=1;next} on && /^[[:space:]]*[}]/{exit} on{gsub(/^[[:space:]]+|[[:space:]]+$/,"");print}')" = "$(printf '%s\\n' /bin/sleep 604800)" ] || exit 2''']
 proof=json.loads(c.pin(l['original_arm_proof']['path'],l['original_arm_proof']['sha256']))
 for item in [proof['helper'],proof['request'],proof['handoff']]:lines += [f'[ "$(/usr/bin/shasum -a 256 {q(item["path"])} | /usr/bin/awk \'{{print $1}}\')" = {item["sha256"]} ] || exit 2']
 old_ack='/private/var/tmp/v4-retirement-nextspawn-'+op
 lines += [f'[ "$(/usr/bin/stat -f %u {old_ack})" = 0 ] || exit 2']
 for name,want in [('plan_sha256',c.sha(c.canonical(p))),('COMPLETE','COMPLETE'),*[(role+'.rc','0') for role in c.ROLES]]:
  lines += [f'[ "$(/usr/bin/stat -f %u {old_ack}/{name})" = 0 ] || exit 2',f'[ "$(/bin/cat {old_ack}/{name})" = {q(want)} ] || exit 2']
  lines += [f'[ "$(/usr/bin/shasum -a 256 {old_ack}/{name} | /usr/bin/awk \'{{print $1}}\')" = {proof["root_files"][name]} ] || exit 2']
 lines += ['umask 022',f'/bin/mkdir -m 755 {target} || exit 2']
 for name,value in [('operation_id',op),('nonce',l['nonce']),('plan_sha256',c.sha(c.canonical(p))),('request_sha256',request_sha)]:lines += [f"printf '%s\\n' {q(value)} > {target}/{name}"]
 lines += [f'printf \'%s\\n\' "$$" > {target}/helper_pid',f'/bin/ps -ww -p $$ -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk \'{{print $1}}\' > {target}/helper_ps_sha256']
 lines += [f"printf '%s\\n' PREARMED_GUARD_VERIFIED_NO_ARM > {target}/collector.observation",f"printf '%s\\n' {l['prearmed_collector']['guard']['ps_sha256']} > {target}/collector.guard_sha256",f"printf '%s\\n' ORIGINAL8_ACK_AND_CURRENT_PENDING_GUARDS_VERIFIED > {target}/original-arm-reuse",f"printf '%s\\n' {l['original_arm_proof']['sha256']} > {target}/original_arm_proof_sha256"]
 lines += [f"printf '%s\\n' COMPLETE > {target}/COMPLETE"]
 rollback=c.HERE/('owned-api-rollback-'+op+'.json');r=c.row(p,'api');label=c.NEW['api']
 lines += [f'while [ "$(/bin/date +%s)" -le {expiry} ]; do',alive+' || exit 2',f' [ ! -e {q(str(finish))} ] || exit 0',f' /bin/date +%s > {target}/.heartbeat',f' /bin/mv -f {target}/.heartbeat {target}/heartbeat',f' if [ -f {q(str(rollback))} ] && [ ! -L {q(str(rollback))} ]; then',f' [ "$(/usr/bin/stat -f %u {q(str(rollback))})" = 501 ] || exit 2',f' [ "$(/usr/bin/plutil -extract operation_id raw {q(str(rollback))})" = {op} ] || exit 2',f' [ "$(/usr/bin/plutil -extract plan_sha256 raw {q(str(rollback))})" = {c.sha(c.canonical(p))} ] || exit 2',f' pid=$(/usr/bin/plutil -extract pid raw {q(str(rollback))})',f' identity=$(/usr/bin/plutil -extract ps_sha256 raw {q(str(rollback))})',' case "$pid" in *[!0-9]*|"") exit 2;; esac',' if [ "$pid" -eq 0 ]; then',' [ "$identity" = NONE ] || exit 2',f' [ -z "$(/bin/launchctl print gui/501/{label} | /usr/bin/awk \'$1 == "pid" && $2 == "=" {{print $3}}\')" ] || exit 2',f' /bin/launchctl print gui/501/{label} > /dev/null',' else',' case "$identity" in *[!0-9a-f]*|"") exit 2;; esac',' [ "${#identity}" = 64 ] || exit 2',f' [ "$(/bin/launchctl print gui/501/{label} | /usr/bin/awk \'$1 == "pid" && $2 == "=" {{print $3}}\')" = "$pid" ] || exit 2',' [ "$(/bin/ps -ww -p "$pid" -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk \'{print $1}\')" = "$identity" ] || exit 2',' fi',f' [ "$(/usr/bin/shasum -a 256 {q(r["new_plist"])} | /usr/bin/awk \'{{print $1}}\')" = {r["after_sha256"]} ] || exit 2',f' /bin/mkdir -m 755 {target}/rollback-api || exit 2',' set +e',f' /bin/launchctl debug gui/501/{label} --program /bin/sleep -- 604800 > {target}/rollback-api/stdout 2> {target}/rollback-api/stderr',' result=$?',' set -e',f' printf \'%s\\n\' "$result" > {target}/rollback-api/rc',' [ "$result" -eq 0 ] || exit "$result"',f" printf '%s\\n' {op} > {target}/rollback-api/COMPLETE",' exit 0',' fi',' /bin/sleep 1','done','exit 0']
 return '\n'.join(lines)+'\n'

def lease_ack(c,p,l,o,request_sha):
 root=Path(l['root_ack_dir']);s=root.lstat()
 if root.parent!=Path('/private/var/tmp') or s.st_uid!=0 or not stat.S_ISDIR(s.st_mode) or s.st_mode&0o022:raise c.Stop('LEASE_ROOT_DIRECTORY')
 def value(name):
  f=root/name;s=f.lstat()
  if s.st_uid!=0 or not stat.S_ISREG(s.st_mode) or s.st_mode&0o022:raise c.Stop('LEASE_ROOT_FILE')
  return c.read(f).decode().strip()
 for name,want in [('operation_id',l['operation_id']),('nonce',l['nonce']),('plan_sha256',c.sha(c.canonical(p))),('request_sha256',request_sha),('COMPLETE','COMPLETE'),('collector.observation','PREARMED_GUARD_VERIFIED_NO_ARM'),('collector.guard_sha256',l['prearmed_collector']['guard']['ps_sha256']),('original-arm-reuse','ORIGINAL8_ACK_AND_CURRENT_PENDING_GUARDS_VERIFIED'),('original_arm_proof_sha256',l['original_arm_proof']['sha256'])]:
  if value(name)!=want:raise c.Stop('LEASE_ACK_DRIFT')
 lease_alive(c,l,o,value)

def lease_alive(c,l,o,value):
 now=time.time()
 if not l['observed_epoch']<=now<=l['expires_epoch'] or not 0<=now-int(value('heartbeat'))<=4:raise c.Stop('LEASE_NOT_ALIVE')
 i=o.identity(int(value('helper_pid')))
 if i is None or i['ps_sha256']!=value('helper_ps_sha256'):raise c.Stop('LEASE_HELPER_EXITED')

def reconcile_collector(c,p,h,l,o,ss,paths,capsule):
 actual=collector_guard(c,p,l,o);s=ss['collector']
 if s['phase']!='WAITING_ROOT_ACK' or s['original_identity'] is not None:raise c.Stop('COLLECTOR_RECONCILE_SCOPE')
 before=c.sha(c.read(paths['collector']))
 if before!=l['checkpoint_sha256']['collector']:raise c.Stop('COLLECTOR_CHECKPOINT_DRIFT')
 record=capsule/'collector-prearmed-reconciliation.json'
 if record.exists():raise c.Stop('COLLECTOR_RECONCILIATION_EXISTS_NO_RETRY')
 c.save(record,{'operation_id':l['operation_id'],'plan_sha256':l['plan_sha256'],'nonce':l['nonce'],'checkpoint_before_sha256':before,'original_identity':None,'current_guard':actual,'source':'ORIGINAL_ROOT_ACK_AND_CURRENT_GUARD_PID_SHA_CWD_PLIST_VERIFIED','advance_to':'AUX_WAIT_IDLE','repeat_arm':False,'repeat_kick':False})
 c.Recipe(p,h,o,s,paths['collector']).record('AUX_WAIT_IDLE',prearmed_reconciliation={'path':str(record),'sha256':c.sha(c.read(record))})

def continue_roles(c,p,h,o,ss,paths):
 for role in REMAINING:
  recipe=c.Recipe(p,h,o,ss[role],paths[role])
  try:
   while not recipe.step(role):time.sleep(1)
  except c.Stop as failure:
   if str(failure)=='API_HEALTH_FAILED_REQUIRES_GUARDED_ROLLBACK':
    c.auto_api_rollback(p,{**h,'root_ack_dir':h['recovery_root_ack_dir']},o,ss[role],paths[role]);raise c.Stop('API_HEALTH_FAILED_ROLLED_BACK_BATCH_STOPPED') from failure
   raise

def cli():
 ap=argparse.ArgumentParser();ap.add_argument('--control-dir',type=Path,required=True);ap.add_argument('--lease',type=Path,required=True);ap.add_argument('--lease-sha256',required=True);ap.add_argument('--review',type=Path);ap.add_argument('--review-sha256');ap.add_argument('--execute-reviewed',action='store_true');a=ap.parse_args()
 c=load_control(a.control_dir);p=json.loads(c.read(c.HERE/'PLAN.json'));c.scope(p);l=json.loads(c.pin(a.lease,a.lease_sha256));h=validate(c,p,l);run=c.HERE/('owned-run-'+l['operation_id'])
 if not a.execute_reviewed:print(json.dumps({'status':'LEASE_VALID_NO_ACTION','roles':REMAINING}));return
 if os.getuid()!=501 or not a.review or not a.review_sha256:raise c.Stop('UID501_REVIEW_REQUIRED')
 receipt=json.loads(c.pin(a.review,a.review_sha256));freeze=json.loads(c.read(HERE/'RECOVERY_FREEZE.json'))
 if receipt.get('verdict')!='PASS' or receipt.get('recovery_freeze_sha256')!=c.sha(c.read(HERE/'RECOVERY_FREEZE.json')):raise c.Stop('INDEPENDENT_RECOVERY_REVIEW_REQUIRED')
 for name,want in freeze['files'].items():c.pin(HERE/name,want)
 for name,want in freeze['control_dependencies'].items():c.pin(c.HERE/name,want)
 if freeze['plan_sha256']!=c.sha(c.canonical(p)):raise c.Stop('REVIEW_PLAN_DRIFT')
 g=p['owner_guard'];fd=os.open(g['path'],os.O_RDWR|os.O_NOFOLLOW)
 try:
  s=os.fstat(fd)
  if (s.st_dev,s.st_ino)!=(g['device'],g['inode']):raise c.Stop('ORIGINAL_GUARD_IDENTITY')
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  base=c.Live(p);base.protection(h);base.pdf_boundary();c.installed(p)
  base.ack({'root_ack_dir':'/private/var/tmp/v4-retirement-nextspawn-'+l['operation_id']})
  ss,paths=states(c,p,l,base,run)
  if (c.HERE/('owned-api-rollback-'+l['operation_id']+'.json')).exists():raise c.Stop('OLD_ROLLBACK_REQUEST_EXISTS')
  capsule=HERE/('owned-renew-'+l['nonce']);capsule.mkdir()
  ready=capsule/'request.json';admin=capsule/'admin.sh';finish=capsule/'finish.json';own=base.identity(os.getpid())
  c.save(ready,{'operation_id':l['operation_id'],'nonce':l['nonce'],'plan_sha256':c.sha(c.canonical(p)),'lease_sha256':a.lease_sha256,'coordinator':own,'main_checkpoint_sha256':l['main']['checkpoint_sha256'],'checkpoint_sha256':l['checkpoint_sha256']})
  request_sha=c.sha(c.read(ready));raw=helper(c,p,l,own,ready,request_sha,finish)
  f=os.open(admin,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(f,'w') as out:out.write(raw);out.flush();os.fsync(out.fileno())
  class RenewLive(c.Live):
   def ack(self,ignored):
    lease_ack(c,p,l,self,request_sha)
    if ss['api']['phase'] in ('WAITING_ROOT_ACK','ARMED') and l['expires_epoch']-time.time()<120:raise c.Stop('API_ROLLBACK_LEASE_BUDGET')
   def protection(self,hh):
    super().protection(hh)
    c.pin(run/'owned-main.checkpoint.json',l['main']['checkpoint_sha256']);self.completed('main',l['main']['new_identity'])
    for role in REMAINING:
     if role!='collector' and ss[role]['phase'] in ('WAITING_ROOT_ACK','ARMED'):pending_guard(c,p,self,role)
    # The finite helper exits after successfully arming the failed API. Its
    # root-owned consumed acknowledgement replaces its heartbeat for that wait.
    if ss['api']['phase']=='HEALTH_FAILED' and (Path(l['root_ack_dir'])/'rollback-api/COMPLETE').exists():c.rollback_ack(p,{**hh,'root_ack_dir':l['root_ack_dir']})
    else:lease_ack(c,p,l,self,request_sha)
  print(json.dumps({'status':'WAITING_ONE_TIME_ADMIN_AUTH','helper':str(admin),'sha256':c.sha(raw.encode()),'expires_epoch':l['expires_epoch'],'operation_id':l['operation_id'],'nonce':l['nonce']}),flush=True)
  while not (Path(l['root_ack_dir'])/'heartbeat').exists():
   if time.time()>l['expires_epoch']:raise c.Stop('LEASE_EXPIRED_NO_SIGNAL')
   time.sleep(1)
  validate(c,p,l);states(c,p,l,base,run);o=RenewLive(p);o.protection(h)
  reconcile_collector(c,p,h,l,o,ss,paths,capsule)
  continue_roles(c,p,h,o,ss,paths)
  c.pin(run/'owned-main.checkpoint.json',l['main']['checkpoint_sha256']);o.completed('main',l['main']['new_identity'])
  c.save(finish,{'operation_id':l['operation_id'],'nonce':l['nonce'],'status':'ALL_EIGHT_BOUND_REQUIRES_TARGET_AND_NATURAL_READBACK','main_lifecycle_repeated':False})
  print(json.dumps({'status':'ALL_EIGHT_BOUND_REQUIRES_TARGET_AND_NATURAL_READBACK','receipt':str(finish)}))
 finally:os.close(fd)

if __name__=='__main__':
 try:cli()
 except Exception as failure:print('STOP:'+str(failure),file=sys.stderr);raise SystemExit(2)
