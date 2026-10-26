"""Fixed-label external root ACK bridge; root never executes this Python module."""
from pathlib import Path
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess

ROOT=Path(__file__).resolve().parent
LEGACY=ROOT.parent/'main_guard_r4'
LOCK_PATH=ROOT.parent/'main_guard_r3'/'service.owner.lock'
EXPECTED_LOCK_INODE=60384679
SERVICE='gui/501/com.lexi.v35.scheduler'
COMMAND=['/bin/launchctl','debug',SERVICE,'--program','/bin/sleep','--','618518']
LEGACY_COMMAND=['/bin/launchctl','debug',SERVICE,'--program','/bin/sleep','--','/bin/sleep','618518']
FAILED_OPERATION='4f408df63c1b40b78e2487a48e6f7f7b'
FAILED_CHECKPOINT_SHA='6a7ee6c2d6b6496b03a84b015efe2b403166ff2812eb6b48140f1844c711254f'
FAILED_MARKER_SHA='8058ccade3edb39069f8e4ed209d639aa14ee0e5f6ca662abb1fbb934258e5c2'
FAILED_ROOT_ACK_SHA='b6393ee53f7ea59d60c79c119b2a4bacecbfbcd0678875b2a8f3cf1f2c269f87'
CONTROLLER_FAILURE_SHA='296814ca2630e9368fd8acc103b70b69364b9bfac6d4a90824fff703a891782f'

class BridgeStop(RuntimeError):pass

def digest(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def fixed_read(path):
    path=Path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size>1024*1024:raise BridgeStop('BRIDGE_REGULAR_BOUNDED_FILE_REQUIRED')
        return os.read(fd,1024*1024+1)
    finally:os.close(fd)

def legacy_consumed_failure():
    """Known consumed R4 failure only, while holding the original lock inode.

    Preserve R4 armed=true/DRAINING history. This is not an unarmed rewrite
    or a retry of an unknown debug outcome; R5 gets a new operation/ACK.
    """
    raw=fixed_read(LEGACY/'owned-checkpoint.json');marker=fixed_read(LEGACY/'service-owned-operation.json')
    if digest(raw)!=FAILED_CHECKPOINT_SHA or digest(marker)!=FAILED_MARKER_SHA:
        raise BridgeStop('LEGACY_FAILURE_HISTORY_CHANGED')
    cp=json.loads(raw);owner=json.loads(marker)
    if (cp['operation_id']!=FAILED_OPERATION or owner['operation_id']!=FAILED_OPERATION
            or cp['phase']!='DRAINING' or cp['armed'] is not True
            or cp.get('last_error')!='StopOwned:UNEXPECTED_REPLACEMENT_OWNER_NO_SIGNAL'
            or cp.get('term_delivered') is not True
            or [a['intent'] for a in cp['actions']]!=[
                'launchctl debug next invocation /bin/sleep','SIGTERM exact original main PID only']):
        raise BridgeStop('LEGACY_NOT_KNOWN_CONSUMED_FAILURE')
    request=json.loads(fixed_read(LEGACY/'admin-request.json'))
    ack_path=Path(cp['admin_ack_path'])
    if (str(ack_path)!=str(ack_directory(request)/'result.json')
            or digest(fixed_read(ack_path))!=FAILED_ROOT_ACK_SHA):
        raise BridgeStop('LEGACY_ROOT_ACK_CHANGED')
    ack=trusted_root_ack(ack_path)
    if (ack!=cp['admin_ack'] or type(ack.get('rc')) is not int or ack['rc']!=0
            or ack['operation_id']!=FAILED_OPERATION or ack['old']!=cp['old']
            or ack['plan_sha256']!=cp['plan_sha256']
            or ack['request_sha256']!=digest(canonical(request))
            or ack['command']!=LEGACY_COMMAND or request['command']!=LEGACY_COMMAND):
        raise BridgeStop('LEGACY_ROOT_ACK_BINDING_MISMATCH')
    # No PID is displaced. A reused former PID also stops this new operation.
    for pid in (cp['executor_pid'],cp['old']['pid']):
        result=subprocess.run(['/bin/ps','-p',str(pid),'-o','pid='],capture_output=True,text=True,check=False)
        if result.stdout.strip():raise BridgeStop('LEGACY_EXECUTOR_OR_OLD_PID_PRESENT_NO_TAKEOVER')
    closure=json.loads(fixed_read(ROOT/'CONSUMED_R4_CLOSURE.json'))
    if (closure['checkpoint_sha256']!=FAILED_CHECKPOINT_SHA
            or closure['marker_sha256']!=FAILED_MARKER_SHA
            or closure['operation_id']!=FAILED_OPERATION
            or closure['root_ack_sha256']!=FAILED_ROOT_ACK_SHA
            or closure['classification']!='CONSUMED_FAILED_SLEEP_ARGUMENT'
            or closure['historical_armed_flag'] is not True
            or closure['observed_last_exit_code']!=1 or closure['observed_runs']!=4
            or closure['stable_lock_inode']!=EXPECTED_LOCK_INODE
            or os.stat(LOCK_PATH,follow_symlinks=False).st_ino!=EXPECTED_LOCK_INODE):
        raise BridgeStop('LEGACY_CONSUMED_CLOSURE_OR_LOCK_BINDING_MISMATCH')
    snapshot=ROOT/'FAILED_R4'
    proof_raw=fixed_read(snapshot/'CONTROLLER_FIRST_FAILURE.json')
    if digest(proof_raw)!=CONTROLLER_FAILURE_SHA:raise BridgeStop('CONTROLLER_FAILURE_PROOF_CHANGED')
    proof=json.loads(proof_raw)
    if (proof['operation_id']!=FAILED_OPERATION or proof['checkpoint_sha256']!=FAILED_CHECKPOINT_SHA
            or proof['root_ack_sha256']!=FAILED_ROOT_ACK_SHA
            or proof['original_main_absent'] is not True
            or proof['bootout_CAS_bootstrap_performed'] is not False
            or 'sleep: invalid time interval: /bin/sleep' not in proof['native_stderr_lines']):
        raise BridgeStop('CONTROLLER_FAILURE_PROOF_MISMATCH')
    for name in ('fresh-loaded.txt','fresh-owners.json','stderr-tail.bin','root-stdout.txt','root-stderr.txt','CONTROLLER_FIRST_FAILURE.json'):
        if digest(fixed_read(snapshot/name))!=closure['evidence_files'][name]:
            raise BridgeStop('LEGACY_CONSUMPTION_EVIDENCE_CHANGED')
    loaded=fixed_read(snapshot/'fresh-loaded.txt').decode()
    if (not re.search(r'^\s*last exit code = 1\s*$',loaded,re.M)
            or not re.search(r'^\s*runs = 4\s*$',loaded,re.M)
            or not re.search(r'^\s*pid = 87709\s*$',loaded,re.M)
            or b'sleep: invalid time interval: /bin/sleep' not in fixed_read(snapshot/'stderr-tail.bin')
            or b'Service configured for next launch.' not in fixed_read(snapshot/'root-stderr.txt')):
        raise BridgeStop('LEGACY_CONSUMPTION_OBSERVATIONS_MISMATCH')
    return {'classification':'CONSUMED_FAILED_SLEEP_ARGUMENT','operation_id':FAILED_OPERATION,
       'checkpoint_sha256':FAILED_CHECKPOINT_SHA,'marker_sha256':FAILED_MARKER_SHA,
       'root_ack_sha256':FAILED_ROOT_ACK_SHA}

def ack_directory(request):
    op=request['operation_id']
    if not re.fullmatch('[a-f0-9]{32}',op):raise BridgeStop('OPERATION_ID_FORMAT')
    return Path('/private/var/tmp')/('v4-main-guard-'+op)

def render_helper(request):
    """No arbitrary program, label, argument or root-interpreter input."""
    if request['service']!=SERVICE or request['command']!=COMMAND:raise BridgeStop('FIXED_ADMIN_COMMAND_ONLY')
    old=request['old'];pid=old['pid']
    if not isinstance(pid,int) or pid<=1:raise BridgeStop('OLD_PID_FORMAT')
    out=ack_directory(request)
    ack={'schema':'v4.main_guard.root_debug_ack.v1','request_sha256':digest(canonical(request)),
         'operation_id':request['operation_id'],'plan_sha256':request['plan_sha256'],
         'old':old,'service':SERVICE,'program':'/bin/sleep','command':COMMAND}
    prefix=json.dumps(ack,ensure_ascii=False,separators=(',',':'))[:-1]+',"rc":'
    q=shlex.quote
    # mkdir is deliberately before the command; any existing BEGIN/ACK/unknown
    # outcome refuses another root debug attempt. Only result.json rc0 is usable.
    return f'''#!/bin/sh
set -eu
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH LC_ALL=C
[ "$#" -eq 0 ] || {{ echo NO_ARGUMENTS_ALLOWED >&2; exit 2; }}
[ "$(/usr/bin/id -u)" = 0 ] || {{ echo ROOT_REQUIRED >&2; exit 2; }}
[ "$(/bin/ps -ww -p {pid} -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk '{{print $1}}')" = {q(request['old_ps_sha256'])} ] || {{ echo OLD_PID_START_COMMAND_CHANGED >&2; exit 2; }}
service_pid=$(/bin/launchctl print {q(SERVICE)} | /usr/bin/awk '$1 == "pid" && $2 == "=" {{print $3}}')
[ "$service_pid" = {pid} ] || {{ echo LABEL_OWNER_CHANGED >&2; exit 2; }}
[ "$(/usr/bin/shasum -a 256 /bin/sleep | /usr/bin/awk '{{print $1}}')" = {q(request['sleep_sha256'])} ] || {{ echo APPLE_SLEEP_CHANGED >&2; exit 2; }}
/usr/bin/codesign -v -R='anchor apple' /bin/sleep
umask 022
/bin/mkdir -m 755 {q(str(out))} || {{ echo EXISTING_ADMIN_INTENT_NO_RETRY >&2; exit 2; }}
printf '%s\\n' {q(digest(canonical(request)))} > {q(str(out/'BEGIN.request_sha256'))}
set +e
/bin/launchctl debug gui/501/com.lexi.v35.scheduler --program /bin/sleep -- 618518 > {q(str(out/'stdout.txt'))} 2> {q(str(out/'stderr.txt'))}
result=$?
set -e
printf '%s%s%s\\n' {q(prefix)} "$result" '}}' > {q(str(out/'result.tmp'))}
/bin/mv {q(str(out/'result.tmp'))} {q(str(out/'result.json'))}
printf 'DEBUG_RC=%s ACK=%s\\n' "$result" {q(str(out/'result.json'))}
exit "$result"
'''

def prepare(journal,ops):
    data=journal.data
    if data.get('admin_request_sha256'):raise BridgeStop('ADMIN_REQUEST_EXISTS_NO_REPREPARE')
    if data['phase']!='ARM_REQUESTED' or data.get('armed'):raise BridgeStop('ADMIN_REQUEST_PHASE')
    # No root debug is attempted by the ordinary controller.
    ops.check_old(data['old'])
    raw=ops.command(['/bin/ps','-ww','-p',str(data['old']['pid']),'-o','lstart=,command=']).stdout.encode()
    request={'schema':'v4.main_guard.admin_request.v1','operation_id':data['operation_id'],
       'plan_sha256':data['plan_sha256'],'old':data['old'],'old_ps_sha256':digest(raw),
       'service':SERVICE,'program':'/bin/sleep','command':COMMAND,
       'sleep_sha256':ops.p['guard_program_sha256'],'legacy_consumed_failure':legacy_consumed_failure()}
    if ops.p['service']!=SERVICE or ops.p['guard_seconds']!=618518:raise BridgeStop('FIXED_ADMIN_COMMAND_ONLY')
    req=ROOT/'admin-request.json';helper=ROOT/'admin-debug-once.sh'
    if req.exists() or helper.exists():raise BridgeStop('EXISTING_ADMIN_FILES_NO_OVERWRITE')
    # The reviewed generator and journal hash bind this concrete helper.
    from guard_recipe import atomic_json
    atomic_json(req,request)
    helper.write_text(render_helper(request));helper.chmod(0o500)
    journal.save(admin_request_sha256=digest(canonical(request)),admin_helper_sha256=digest(fixed_read(helper)),
       admin_ack_path=str(ack_directory(request)/'result.json'),
       admin_wait='HUMAN_TERMINAL_SUDO_FIXED_DEBUG_ONLY')
    raise BridgeStop('ADMIN_ACK_REQUIRED_NO_TERM_SENT')

def trusted_root_ack(path):
    directory=path.parent
    info=directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
        raise BridgeStop('ADMIN_ACK_DIRECTORY_NOT_ROOT_OWNED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_size>1024*1024:
            raise BridgeStop('ADMIN_ACK_NOT_TRUSTED_ROOT_FILE')
        return json.loads(os.read(fd,1024*1024+1))
    finally:os.close(fd)

def accept(journal,ops):
    data=journal.data
    if data['phase']!='ARM_REQUESTED' or data.get('armed'):raise BridgeStop('ADMIN_ACK_PHASE')
    request=json.loads(fixed_read(ROOT/'admin-request.json'))
    if (digest(canonical(request))!=data.get('admin_request_sha256')
            or request['operation_id']!=data['operation_id'] or request['plan_sha256']!=data['plan_sha256']
            or request['old']!=data['old'] or request['service']!=SERVICE or request['command']!=COMMAND):
        raise BridgeStop('ADMIN_REQUEST_BINDING_MISMATCH')
    helper=fixed_read(ROOT/'admin-debug-once.sh')
    if helper!=render_helper(request).encode() or digest(helper)!=data['admin_helper_sha256']:
        raise BridgeStop('ADMIN_HELPER_BYTES_CHANGED')
    path=ack_directory(request)/'result.json'
    if str(path)!=data['admin_ack_path']:raise BridgeStop('ADMIN_ACK_PATH_MISMATCH')
    try:ack=trusted_root_ack(path)
    except FileNotFoundError as error:raise BridgeStop('ADMIN_ACK_MISSING_UNKNOWN_NO_DEBUG_OR_TERM_RETRY') from error
    required={'schema':'v4.main_guard.root_debug_ack.v1','request_sha256':digest(canonical(request)),
       'operation_id':data['operation_id'],'plan_sha256':data['plan_sha256'],'old':data['old'],
       'service':SERVICE,'program':'/bin/sleep','command':COMMAND,'rc':0}
    if ack!=required or type(ack.get('rc')) is not int:raise BridgeStop('ADMIN_ACK_MISMATCH_OR_NONZERO_NO_TERM')
    # Keep root preparation separate from the normal-user lifecycle. The existing
    # ARMED branch rechecks current owner/PDF boundary before main-only SIGTERM.
    ops.verify_package()
    journal.save('ARMED',armed=True,arm_ack='ROOT_OWNED_FIXED_DEBUG_RC0',admin_ack=ack)
