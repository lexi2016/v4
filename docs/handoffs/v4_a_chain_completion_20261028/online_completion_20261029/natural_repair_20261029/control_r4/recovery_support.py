"""Bounded operation guardian protocol and fixed root argv restoration generator.

No import side effects. The guardian owns all three locks directly; no inherited
flock or lease token is treated as a cross-process ownership transfer.
"""
import hashlib,json,os,plistlib,re,shlex,subprocess,time
from pathlib import Path


def digest(raw):return hashlib.sha256(raw).hexdigest()
def ready_path(here,op):return Path(here)/('owned-guardian-'+op+'.ready.json')
def abort_path(here,op):return Path(here)/('owned-abort-'+op+'.json')
def outcome_path(here,op):return Path(here)/('owned-guardian-'+op+'.outcome.json')


def ensure_guardian(c,p,h,here):
    g=h.get('guardian') or {};ready=ready_path(here,h['operation_id'])
    if abort_path(here,h['operation_id']).exists():raise c.Stop('ABORT_RECONCILIATION_IN_PROGRESS_NO_NEW_ACTION')
    if not g or c.sha(c.read(ready))!=g['ready_sha256'] or c.Live(p).identity(g['pid'])!={k:g[k] for k in ('pid','ps_sha256','ps_text')}:
        raise c.Stop('GUARDIAN_LEASE_NOT_ALIVE_NO_NEW_ACTION')
    if outcome_path(here,h['operation_id']).exists():raise c.Stop('GUARDIAN_ALREADY_DISCHARGED_NO_NEW_ACTION')


def start_guardian(c,p,h,a,here):
    op=h['operation_id'];ready=ready_path(here,op)
    if ready.exists() or outcome_path(here,op).exists():raise c.Stop('EXISTING_GUARDIAN_RECONCILE_REQUIRED')
    parent=c.Live(p).identity(os.getpid())
    script=Path(p['recovery']['guardian_script'])
    args=[os.sys.executable,'-B',str(script),'watch','--plan',str(a.plan),'--review',str(a.review),
          '--review-sha256',a.review_sha256,'--handoff',str(a.handoff),
          '--handoff-sha256',a.handoff_sha256,'--parent-pid',str(parent['pid']),
          '--parent-ps-sha256',parent['ps_sha256']]
    log=Path(here)/('owned-guardian-'+op+'.log')
    with log.open('xb') as stream:
        child=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,
                               start_new_session=True,close_fds=True)
    deadline=time.monotonic()+20
    while not ready.exists():
        if child.poll() is not None or time.monotonic()>deadline:
            raise c.Stop('GUARDIAN_START_FAILED_OR_UNKNOWN_NO_ARM')
        time.sleep(.1)
    proof=json.loads(c.read(ready))
    if proof.get('operation_id')!=op or proof.get('plan_sha256')!=c.sha(c.canonical(p)) or proof.get('parent')!=parent:
        raise c.Stop('GUARDIAN_READY_PROOF_MISMATCH')
    h['guardian']={**proof['guardian'],'ready_sha256':c.sha(c.read(ready))}
    ensure_guardian(c,p,h,here)
    return h['guardian']


def request_abort(c,h,here,reason):
    path=abort_path(here,h['operation_id'])
    if not path.exists():c.save(path,{'operation_id':h['operation_id'],'reason':str(reason),'requested_at':time.time()})



def validate_argv_abi(p):
    if p['recovery'].get('normal_restore_argv_policy')!='PROGRAM_PREPENDED':
        raise ValueError('PLATFORM_ARGV_ABI_UNVERIFIED_NO_HELPER')
    ref=p['recovery']['argv_abi_evidence'];path=Path(ref['path']);raw=path.read_bytes()
    if digest(raw)!=ref['sha256']:raise ValueError('ARGV_CANARY_RECEIPT_SHA_MISMATCH')
    proof=json.loads(raw);expected='CANARY_FORMAT=[ARG_ONE]\nCANARY_FORMAT=[ARG_TWO]\n'
    stdout=(path.parent/'stdout.txt').read_bytes()
    pending=Path(ref['pending_loaded_path']).read_bytes()
    if (proof.get('program_prepended_to_debug_args') is not True
        or proof.get('actual_canary_invocations')!=1 or proof.get('own_canary_unloaded') is not True
        or proof.get('production_service_actions')!=0 or proof.get('stock_data_writes') is not False
        or stdout!=expected.encode() or proof.get('stdout_text')!=expected
        or digest(stdout)!=proof.get('stdout_sha256') or digest(pending)!=ref['pending_loaded_sha256']):
        raise ValueError('ARGV_CANARY_BOUNDARY_OR_OUTPUT_MISMATCH')
    return 'PROGRAM_PREPENDED'


def root_helper(p,h,coordinator,ready_sha,here):
    """Root capability: fixed sleep arming OR exact frozen normal argv restore.

    Root signals only the wrapper-created unreaped launchctl CLI child PID.
    No service PID/group signals, bootout/bootstrap, Python or data writes.
    Traps cover partial arming and coordinator failure. SIGKILL cannot be trapped;
    durable restore intents cause explicit UNKNOWN reconciliation, never replay.
    """
    q=shlex.quote;here=Path(here);op=h['operation_id'];target=h['root_ack_dir']
    wrapper=Path(p['recovery']['cli_wrapper']);wrapper_sha=p['recovery']['cli_wrapper_sha256']
    if wrapper!=here/'bounded_launchctl' or digest(wrapper.read_bytes())!=wrapper_sha:
        raise ValueError('FIXED_LAUNCHCTL_WRAPPER_SHA')
    policy=validate_argv_abi(p)
    if not re.fullmatch('[0-9a-f]{32}',op) or target!='/private/var/tmp/v4-a-chain-nextspawn-'+op:
        raise ValueError('ROOT_OPERATION_SCOPE')
    if not re.fullmatch('[0-9a-f]{64}',ready_sha):raise ValueError('ROOT_READY_SHA')
    roles=('main','api','collector','stage','precapture')
    sleep_argv_sha=digest(b'/bin/sleep\n604800\n')
    g=h['guardian'];expiry=int(h['expires_epoch']);cleanup_deadline=expiry+p['recovery']['cleanup_grace_seconds']
    ready=here/('owned-request-'+op+'.json');finish=here/('owned-finish-'+op+'.json')
    abort=abort_path(here,op);rollback=here/('owned-api-rollback-'+op+'.json')
    discharge=here/('owned-guardian-'+op+'.discharge.json')
    alive=lambda i: '[ "$(/bin/ps -ww -p '+str(i['pid'])+' -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk \'{print $1}\')" = '+i['ps_sha256']+' ]'
    lines=['#!/bin/sh','set -eu','PATH=/usr/bin:/bin:/usr/sbin:/sbin','export PATH LC_ALL=C',
           '[ "$#" -eq 0 ] || exit 2','[ "$(/usr/bin/id -u)" = 0 ] || exit 2',
           f'[ "$(/bin/date +%s)" -le {expiry} ] || exit 2',alive(coordinator)+' || exit 2',
           alive(g)+' || exit 2',f'[ "$(/usr/bin/shasum -a 256 {q(str(ready))} | /usr/bin/awk \'{{print $1}}\')" = {ready_sha} ] || exit 2',
           f'[ "$(/usr/bin/shasum -a 256 {q(str(ready_path(here,op)))} | /usr/bin/awk \'{{print $1}}\')" = {g["ready_sha256"]} ] || exit 2',
           f'[ "$(/usr/bin/shasum -a 256 /bin/sleep | /usr/bin/awk \'{{print $1}}\')" = {p["guard_program_sha256"]} ] || exit 2',
           "/usr/bin/codesign -v -R='anchor apple' /bin/sleep",'umask 022',
           f'/bin/mkdir -m 755 {target} || exit 2',f"printf '%s\\n' {digest(json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())} > {target}/plan_sha256",
           'normal=0',
           f"[ \"$(/usr/bin/shasum -a 256 {q(str(wrapper))} | /usr/bin/awk '{{print $1}}')\" = {wrapper_sha} ] || exit 2",
           f'bounded_cli() {{ {q(str(wrapper))} "$1" "$2" {target}; }}']
    # Root checks the exact loaded definition, not only the on-disk plist.
    for row in p['operations']:
        role=row['role'];label=row['label']
        for side in ('before','after'):
            definition=plistlib.loads(Path(row[side+'_file']).read_bytes())
            args=definition['ProgramArguments'];argv_sha=digest(('\n'.join(args)+'\n').encode())
            lines += [f'match_{role}_{side}() {{',
                f' [ "$current_sha" = {row[side+"_sha256"]} ] || return 1',
                f' [ "$(/usr/bin/awk \'/^\\tpath = / {{sub(/^\\tpath = /, "");print}}\' {target}/{role}.loaded)" = {q(row["plist"])} ] || return 1',
                f' [ "$(/usr/bin/awk \'/^\\tworking directory = / {{sub(/^\\tworking directory = /, "");print}}\' {target}/{role}.loaded)" = {q(definition["WorkingDirectory"])} ] || return 1',
                f' [ "$(/usr/bin/awk \'/^\\tprogram = / {{sub(/^\\tprogram = /, "");print}}\' {target}/{role}.loaded)" = {q(args[0])} ] || return 1',
                f' [ "$(/usr/bin/awk \'/^\\targuments = \\{{/ {{on=1;next}} on && /^\\t\\}}/ {{exit}} on {{sub(/^[ \\t]+/, "");sub(/[ \\t]+$/, "");if(length($0)) print}}\' {target}/{role}.loaded | /usr/bin/shasum -a 256 | /usr/bin/awk \'{{print $1}}\')" = {argv_sha} ] || return 1']
            for key,value in definition.get('EnvironmentVariables',{}).items():
                lines += [f' [ "$(/usr/bin/awk -v k={q(key)} \'{{sub(/^[ \\t]*/, "");if(index($0,k" => ")==1) print substr($0,length(k)+5)}}\' {target}/{role}.loaded)" = {q(str(value))} ] || return 1']
            lines += [' return 0','}']
    lines += ['cleanup() {',' trap - EXIT HUP INT TERM',' set +e',
              f' if [ "$normal" -eq 1 ]; then printf "%s\\n" DISCHARGED > {target}/HELPER_DONE; return; fi',
              f' printf "%s\\n" ABORT_RESTORE > {target}/HELPER_ABORT']
    for row in p['operations']:
        role=row['role'];label=row['label']
        lines += [f' if [ -f {target}/{role}.intent ]; then',
            f'  if [ -f {target}/{role}.cli.UNKNOWN ]; then printf "%s\\n" CLI_OUTCOME_UNKNOWN_NO_AUTOMATIC_RESTORE > {target}/{role}.restore.status',
            f'  elif [ "$(/bin/date +%s)" -gt {cleanup_deadline} ]; then printf "%s\\n" EXPIRED_UNKNOWN > {target}/{role}.restore.status',
            '  else',f'   current_sha=$(/usr/bin/shasum -a 256 {q(row["plist"])} | /usr/bin/awk \'{{print $1}}\')',
            f'   bounded_cli {role}_cleanup_print {cleanup_deadline} > {target}/{role}.loaded 2> {target}/{role}.loaded.stderr',
            '   loaded_rc=$?',
            f'   if [ "$loaded_rc" -eq 113 ]; then printf "%s\\n" UNLOADED_NO_PENDING_INSTANCE > {target}/{role}.restore.status',
            f'   elif [ "$loaded_rc" -ne 0 ]; then printf "%s\\n" UNKNOWN_LOADED_OWNER > {target}/{role}.restore.status',
            '   else',
            f'    pid=$(/usr/bin/awk \'$1=="pid" && $2=="=" {{print $3}}\' {target}/{role}.loaded)',
            '    identity_ok=0',
            '    if [ -z "$pid" ]; then identity_ok=1; else',
            '     case "$pid" in *[!0-9]*|"") ;; *)',
            f'      /bin/ps -ww -p "$pid" -o lstart=,command= > {target}/{role}.ps',
            f'      if /usr/bin/grep -Eq \'(^|[[:space:]])/bin/sleep 604800[[:space:]]*$\' {target}/{role}.ps; then identity_ok=1; fi']
        initial=h['identities'][role]
        if initial:
            lines += [f'      if [ "$pid" = {initial["pid"]} ] && [ "$(/usr/bin/shasum -a 256 {target}/{role}.ps | /usr/bin/awk \'{{print $1}}\')" = {initial["ps_sha256"]} ]; then identity_ok=1; fi']
        checkpoint=here/('owned-run-'+op)/('owned-'+role+'.checkpoint.json')
        for side in ('before','after'):
            normal=plistlib.loads(Path(row[side+'_file']).read_bytes())['ProgramArguments']
            normal_command=' '.join(normal)
            lines += [f'      if [ "$(/bin/ps -ww -p "$pid" -o command=)" = {q(normal_command)} ]; then identity_ok=1; fi']
        lines += [f'      known_pid=$(/usr/bin/plutil -extract new.pid raw {q(str(checkpoint))} 2>/dev/null)',
            f'      known_sha=$(/usr/bin/plutil -extract new.ps_sha256 raw {q(str(checkpoint))} 2>/dev/null)',
            f'      if [ "$pid" = "$known_pid" ] && [ "$(/usr/bin/shasum -a 256 {target}/{role}.ps | /usr/bin/awk \'{{print $1}}\')" = "$known_sha" ]; then identity_ok=1; fi',
            '     ;; esac','    fi',
            f'    if [ "$identity_ok" -eq 1 ] && [ -n "$pid" ]; then /usr/bin/shasum -a 256 {target}/{role}.ps | /usr/bin/awk \'{{print $1}}\' > {target}/{role}.restore.ps_sha256; fi',
            f"    if /usr/bin/grep -Fq 'controller-supplied arguments = {{' {target}/{role}.loaded; then",
            f'     pending_sha=$(/usr/bin/awk \'/^[ \\t]*controller-supplied arguments = \\{{/ {{on=1;next}} on && /^\\t\\}}/ {{exit}} on {{sub(/^[ \\t]+/, "");sub(/[ \\t]+$/, "");if(length($0)) print}}\' {target}/{role}.loaded | /usr/bin/shasum -a 256 | /usr/bin/awk \'{{print $1}}\')',
            f'     [ "$pending_sha" = {sleep_argv_sha} ] || identity_ok=2',
            '    fi',
            f'    if [ "$identity_ok" -eq 2 ]; then printf "%s\\n" FOREIGN_PENDING_ARGV_NO_ACTION > {target}/{role}.restore.status',
            f'    elif [ "$identity_ok" -ne 1 ]; then printf "%s\\n" UNKNOWN_IDENTITY_NO_ACTION > {target}/{role}.restore.status']
        for i,side in enumerate(('before','after')):
            definition=plistlib.loads(Path(row[side+'_file']).read_bytes());args=definition['ProgramArguments']
            debug_args=args[1:]  # Current-host empirical ABI; never duplicate argv0.
            lines += [f'    elif match_{role}_{side}; then',
                f'     printf "%s\\n" {row[side+"_sha256"]} > {target}/{role}.restore.definition_sha256',
                f'     printf "%s\\n" INTENT > {target}/{role}.restore.intent',
                f'     bounded_cli {role}_restore_{side} {cleanup_deadline} > {target}/{role}.restore.stdout 2> {target}/{role}.restore.stderr',
                '     restore_rc=$?',f'     printf "%s\\n" "$restore_rc" > {target}/{role}.restore.rc',
                f'     if [ "$restore_rc" -eq 0 ]; then printf "%s\\n" RESTORED_NORMAL_ARGV > {target}/{role}.restore.status; else printf "%s\\n" RESTORE_OUTCOME_UNKNOWN_NO_RETRY > {target}/{role}.restore.status; fi']
        lines += [f'    else printf "%s\\n" UNKNOWN_DEFINITION_NO_ACTION > {target}/{role}.restore.status','    fi','   fi','  fi',' fi']
    lines += [f' printf "%s\\n" COMPLETE > {target}/RESTORE_COMPLETE','}',
              "trap 'cleanup' EXIT","trap 'exit 2' HUP INT TERM"]
    # Preserve the actual previously successful sleep syntax; normal argv policy
    # is separately bound to the controller-owned one-shot current-host canary.
    for row in p['operations']:
        role=row['role'];label=row['label']
        lines += [alive(coordinator)+' || exit 2',alive(g)+' || exit 2',
            f'[ ! -e {q(str(abort))} ] || exit 2',f'[ "$(/bin/date +%s)" -le {expiry} ] || exit 2',
            f'[ "$(/usr/bin/shasum -a 256 {q(row["plist"])} | /usr/bin/awk \'{{print $1}}\')" = {row["before_sha256"]} ] || exit 2',
            f'current_sha=$(/usr/bin/shasum -a 256 {q(row["plist"])} | /usr/bin/awk \'{{print $1}}\')',
            f'bounded_cli {role}_arm_print {expiry} > {target}/{role}.loaded',
            f'match_{role}_before || exit 2',
            f"if /usr/bin/grep -Fq 'controller-supplied arguments = {{' {target}/{role}.loaded; then exit 2; fi"]
        initial=h['identities'][role]
        if initial:
            lines += [alive(initial)+' || exit 2',f'[ "$(/usr/bin/awk \'$1=="pid" && $2=="=" {{print $3}}\' {target}/{role}.loaded)" = {initial["pid"]} ] || exit 2']
        else:
            lines += [f'[ -z "$(/usr/bin/awk \'$1=="pid" && $2=="=" {{print $3}}\' {target}/{role}.loaded)" ] || exit 2']
        lines += [f"printf '%s\\n' INTENT > {target}/{role}.intent",'set +e',
            f'bounded_cli {role}_arm_debug {expiry} > {target}/{role}.stdout 2> {target}/{role}.stderr',
            'result=$?','set -e',f"printf '%s\\n' \"$result\" > {target}/{role}.rc",'[ "$result" -eq 0 ] || exit "$result"']
    lines += [f"printf '%s\\n' COMPLETE > {target}/COMPLETE",'rollback_armed=0',
        f'while [ "$(/bin/date +%s)" -le {expiry} ]; do',alive(coordinator)+' || exit 2',alive(g)+' || exit 2',
        f' [ ! -e {q(str(abort))} ] || exit 2',
        f' if [ -f {q(str(discharge))} ] && [ "$(/usr/bin/plutil -extract operation_id raw {q(str(discharge))})" = {op} ]; then normal=1; exit 0; fi']
    # API-only health rollback remains one-shot and stays watched until discharge.
    api=next(r for r in p['operations'] if r['role']=='api')
    if not h['reverse']:
        lines += [f' if [ "$rollback_armed" -eq 0 ] && [ -f {q(str(rollback))} ] && [ ! -L {q(str(rollback))} ]; then',
            f'  [ "$(/usr/bin/plutil -extract operation_id raw {q(str(rollback))})" = {op} ] || exit 2',
            f'  [ "$(/usr/bin/plutil -extract plan_sha256 raw {q(str(rollback))})" = {digest(json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode())} ] || exit 2',
            f'  pid=$(/usr/bin/plutil -extract pid raw {q(str(rollback))})',
            f'  expected=$(/usr/bin/plutil -extract ps_sha256 raw {q(str(rollback))})',
            '  case "$pid" in *[!0-9]*|"") exit 2;; esac',
            f'  bounded_cli api_rollback_print {expiry} > {target}/api.rollback.loaded || exit 2',
            f"  actual=$(/usr/bin/awk '$1==\"pid\" && $2==\"=\" {{print $3}}' {target}/api.rollback.loaded)",
            '  if [ "$pid" -eq 0 ]; then [ -z "$actual" ] && [ "$expected" = NONE ] || exit 2;',
            '  else [ "$actual" = "$pid" ] || exit 2;',
            '   [ "$(/bin/ps -ww -p "$pid" -o lstart=,command= | /usr/bin/shasum -a 256 | /usr/bin/awk \'{print $1}\')" = "$expected" ] || exit 2; fi',
            f'  [ "$(/usr/bin/shasum -a 256 {q(api["plist"])} | /usr/bin/awk \'{{print $1}}\')" = {api["after_sha256"]} ] || exit 2',
            f'  /bin/mkdir -m 755 {target}/rollback-api || exit 2',
            f'  printf "%s\\n" INTENT > {target}/rollback-api/intent','  set +e',
            f'  bounded_cli api_rollback_debug {expiry} > {target}/rollback-api/stdout 2> {target}/rollback-api/stderr',
            '  rc=$?','  set -e',f'  printf "%s\\n" "$rc" > {target}/rollback-api/rc','  [ "$rc" -eq 0 ] || exit "$rc"',
            f'  printf "%s\\n" {op} > {target}/rollback-api/COMPLETE','  rollback_armed=1',' fi']
    lines += [' /bin/sleep 1','done','exit 2']
    return '\n'.join(lines)+'\n'
