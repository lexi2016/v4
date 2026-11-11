"""R3 only: deployed-cap16 Stage repin + same-new-Main control; no API/data work.

Default preflight is read-only. Controller must explicitly pass --execute after
actual final Main activation and fresh r2 Stage prepare/validation. No kickstart.
"""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import json
import os
import plistlib
import re
import stat
import subprocess
import tempfile
import time

N = Path(__file__).resolve().parent
DOMAIN = 'gui/' + str(os.getuid())
PREVIOUS_STAGE_CURRENT_MAIN = '176b35a86b3e8587f3343b3d960aeed2b5c8584fccbeeafda2767092c909aa0a'
EXPECTED_BEFORE_STAGE_MANIFEST = '5ffcf399b35ee9e9f5c919ee0c8b39fb1f758f85f17cd3319a85b6e904e2ce5b'
STAGE_HELPER_SHA = '63408260062e5f32430a00990ef716d81b103b3090cf93374b4cc6112fdf5b17'
LABELS = {'main': 'com.lexi.v4.scheduler', 'stage': 'com.lexi.stage-center.scheduler'}
LIVE = {role: Path.home() / 'Library/LaunchAgents' / (label + '.plist') for role, label in LABELS.items()}
WAIT_SECONDS = 60
IDENTITY_ENV_KEYS = {'V4_APP_ROOT', 'V4_RELEASE_ID', 'V4_RELEASE_MANIFEST_PATH',
    'V4_RELEASE_MANIFEST_SHA256', 'V4_RESEARCH_RETENTION_POLICY',
    'V4_RESEARCH_RETENTION_POLICY_SHA256', 'STAGE_CENTER_CONFIG'}


def require(value, message):
    if not value: raise RuntimeError(message)
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path): return json.loads(Path(path).read_bytes())
def checked(ref):
    path = Path(ref['path'])
    require(path.is_absolute() and not path.is_symlink() and path.resolve() == path, 'UNSAFE_REFERENCE:' + str(path))
    require(sha(path) == ref['sha256'], 'REFERENCE_SHA_DRIFT:' + str(path))
    return path

def run(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=15)

def job(role):
    result = run('launchctl', 'print', DOMAIN + '/' + LABELS[role])
    if result.returncode:
        require('Could not find service' in result.stderr, 'JOB_STATE_UNKNOWN:' + role + ':' + result.stderr)
        return dict(loaded=False, pid=None, state=None, environment={})
    raw = result.stdout
    pid = re.search(r'^\s*pid = (\d+)', raw, re.M)
    state = re.search(r'^\s*state = ([^\n]+)', raw, re.M)
    env = {k: v.strip().strip('"') for k, v in re.findall(r'^\s*([A-Z][A-Z_0-9]+) => ([^\n]+)', raw, re.M) if k in IDENTITY_ENV_KEYS}
    return dict(loaded=True, pid=int(pid[1]) if pid else None,
                state=state[1].strip() if state else None, environment=env)

def process_start(pid):
    if pid is None: return None
    result = run('ps', '-p', str(pid), '-o', 'lstart=')
    return result.stdout.strip() if result.returncode == 0 else None

def descendants(pid):
    if pid is None: return []
    result = run('ps', '-axo', 'pid=,ppid=,comm=')
    require(result.returncode == 0, 'PROCESS_TREE_UNKNOWN')
    rows = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3: rows.append((int(parts[0]), int(parts[1]), parts[2]))
    found = {pid}; children = []
    while True:
        added = [row for row in rows if row[1] in found and row[0] not in found]
        if not added: return children
        children.extend(added); found.update(row[0] for row in added)

def idle(role):
    state = job(role)
    require(not descendants(state['pid']), 'ACTIVE_DESCENDANTS_KEEP_RUNNING:' + role)
    if role == 'stage': require(state['pid'] is None, 'ACTIVE_STAGE_KEEP_RUNNING')
    return state

def wait_unloaded(roles, old_starts):
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        pending = [role for role in roles if job(role)['loaded'] or
                   (old_starts.get(role) and process_start(old_starts[role][0]) == old_starts[role][1])]
        if not pending: return
        time.sleep(.2)
    raise RuntimeError('OLD_JOB_OR_PROCESS_NOT_EXITED:' + ','.join(pending))

def bootout(role):
    if job(role)['loaded']:
        result = run('launchctl', 'bootout', DOMAIN + '/' + LABELS[role])
        require(result.returncode == 0, 'BOOTOUT_FAILED:' + role + ':' + result.stderr)

def bootstrap(role):
    result = run('launchctl', 'bootstrap', DOMAIN, str(LIVE[role]))
    require(result.returncode == 0, 'BOOTSTRAP_FAILED:' + role + ':' + result.stderr)

def atomic_plist(role, raw, mode):
    path = LIVE[role]
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.stage-control-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, mode); os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if Path(temporary).exists(): Path(temporary).unlink()

def assert_no_active_claim(policy):
    registry = Path(policy['governance']['registry_root']) / 'registry.json'
    if registry.exists():
        tasks = load(registry)['tasks']
        pending = [key for key, row in tasks.items() if row.get('state') in {'RUNNING', 'VALIDATING'}]
        require(not pending, 'ACTIVE_OR_UNRECONCILED_CLAIM_KEEP_RUNNING:' + ','.join(pending))

def validate_window(stage_plist):
    # The existing timer is unchanged. Avoid a natural Stage start inside this
    # bounded maintenance operation rather than interrupting an active node.
    now = datetime.now().astimezone()
    for item in stage_plist.get('StartCalendarInterval', []):
        tick = now.replace(hour=item['Hour'], minute=item['Minute'], second=0, microsecond=0)
        if tick < now: tick += timedelta(days=1)
        require((tick - now).total_seconds() > 150, 'STAGE_TIMER_WITHIN_MAINTENANCE_WINDOW')

def preflight(args):
    root = Path(args.candidate_root)
    prepare = root / 'PREPARE_RECEIPT.json'; validation = root / 'VALIDATION.json'
    require(sha(prepare) == args.expected_prepare_sha256, 'PREPARE_REF_DRIFT')
    require(sha(validation) == args.expected_validation_sha256, 'VALIDATION_REF_DRIFT')
    p, v = load(prepare), load(validation)
    require(p['status'] == 'PREPARED_NOT_ACTIVATED' and v['status'] == 'OFFLINE_SOURCE_IDENTITY_AND_WITNESS_PASS_NOT_ACTIVATED', 'CANDIDATE_NOT_QUALIFIED')
    require(p['main']['manifest']['sha256'] == args.expected_main_manifest_sha256, 'FINAL_MAIN_NOT_ACTUAL_CANDIDATE')
    require(args.expected_main_manifest_sha256 != PREVIOUS_STAGE_CURRENT_MAIN, 'NEW_MAIN_REQUIRED_FOR_R3_REPIN')
    rows = {role: p[role] for role in LABELS}; old = {}; proposed = {}; modes = {}
    for role, row in rows.items():
        require(Path(row['live_plist']) == LIVE[role] and not LIVE[role].is_symlink(), 'ROLE_LIVE_PATH_MISMATCH')
        require(sha(LIVE[role]) == row['before_plist']['sha256'], 'LIVE_BEFORE_CAS_DRIFT:' + role)
        old[role] = plistlib.loads(checked(row['before_plist']).read_bytes())
        proposed[role] = plistlib.loads(checked(row['proposed_plist']).read_bytes())
        require(old[role]['Label'] == proposed[role]['Label'] == LABELS[role], 'LABEL_CHANGE_FORBIDDEN')
        modes[role] = stat.S_IMODE(LIVE[role].stat().st_mode)
        checked(row['manifest'])
    require(old['stage']['EnvironmentVariables']['V4_RELEASE_MANIFEST_SHA256'] == EXPECTED_BEFORE_STAGE_MANIFEST, 'EXPECTED_DEPLOYED_R2_STAGE_BEFORE')
    before_env = old['main']['EnvironmentVariables']; after_env = proposed['main']['EnvironmentVariables']
    require(before_env['V4_RELEASE_MANIFEST_SHA256'] == args.expected_main_manifest_sha256, 'FINAL_MAIN_NOT_YET_ACTIVE')
    for key in ('V4_APP_ROOT', 'V4_RELEASE_ID', 'V4_RELEASE_MANIFEST_PATH', 'V4_RELEASE_MANIFEST_SHA256'):
        require(before_env[key] == after_env[key], 'MAIN_BUSINESS_IDENTITY_CHANGE_FORBIDDEN')
    restored = plistlib.loads(plistlib.dumps(proposed['main']))
    for key in ('V4_RESEARCH_RETENTION_POLICY', 'V4_RESEARCH_RETENTION_POLICY_SHA256'):
        restored['EnvironmentVariables'][key] = before_env[key]
    require(restored == old['main'], 'MAIN_OUTSIDE_TWO_POLICY_ENV_FIELDS_CHANGED')
    for field in ('before_policy', 'proposed_policy', 'before_pins', 'proposed_pins',
                  'before_reader_attestation', 'proposed_reader_attestation'):
        checked(rows['main'][field])
    checked(rows['stage']['helper_after'])
    require(rows['stage']['helper_after']['sha256'] == STAGE_HELPER_SHA, 'STAGE_HELPER_NOT_FROZEN')
    require(old['stage'].get('StartCalendarInterval') == proposed['stage'].get('StartCalendarInterval')
            and proposed['stage'].get('RunAtLoad') is False, 'STAGE_SCHEDULE_OR_RUNATLOAD_CHANGED')
    validate_window(old['stage'])
    states = {role: idle(role) for role in LABELS}
    require(all(x['loaded'] for x in states.values()) and states['main']['pid'], 'EXISTING_JOBS_NOT_NORMALLY_LOADED')
    for role in LABELS:
        keys = ('V4_APP_ROOT', 'V4_RELEASE_ID', 'V4_RELEASE_MANIFEST_SHA256')
        keys += (('V4_RESEARCH_RETENTION_POLICY', 'V4_RESEARCH_RETENTION_POLICY_SHA256')
                 if role == 'main' else ('STAGE_CENTER_CONFIG',))
        for key in keys:
            require(states[role]['environment'].get(key) == old[role]['EnvironmentVariables'][key],
                    'LOADED_BEFORE_IDENTITY_NOT_ACTUAL:' + role + ':' + key)
    assert_no_active_claim(load(rows['main']['before_policy']['path']))
    return p, rows, old, proposed, modes, states

def activate(args):
    p, rows, old, proposed, modes, before = preflight(args)
    starts = {role: (state['pid'], process_start(state['pid'])) for role, state in before.items() if state['pid']}
    record = dict(status='PREFLIGHT_PASS_NO_CHANGES', at=datetime.now(timezone.utc).isoformat(),
        script_sha256=sha(__file__), prepare_sha256=args.expected_prepare_sha256,
        validation_sha256=args.expected_validation_sha256, before=before,
        Main_business_identity_unchanged=True, API_touched=False, direct_producer_invocation=False)
    if not args.execute:
        print(json.dumps(record, ensure_ascii=False)); return
    output = N / ('STAGE_MAIN_CONTROL_ACTIVATION_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%f') + '.json')
    def journal(status, **extra):
        record.update(status=status, **extra)
        output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(dict(status=status, receipt=str(output)), ensure_ascii=False), flush=True)
    changed = False; unloaded = []
    try:
        # Main dispatch stops first. Never bootout a Stage node or Main child.
        for role in ('main', 'stage'):
            idle(role)
            require(sha(LIVE[role]) == rows[role]['before_plist']['sha256'], 'LAST_MOMENT_CAS_DRIFT:' + role)
            bootout(role); unloaded.append(role)
        wait_unloaded(('main', 'stage'), starts)
        journal('BOTH_OLD_JOBS_AND_PROCESSES_UNLOADED')
        for role in LABELS:
            require(sha(LIVE[role]) == rows[role]['before_plist']['sha256'], 'BEFORE_WRITE_CAS_DRIFT:' + role)
        changed = True
        for role in ('stage', 'main'):
            atomic_plist(role, checked(rows[role]['proposed_plist']).read_bytes(), modes[role])
        # Both future pins are on disk before either job reads them. Stage is a
        # non-RunAtLoad timer; no stage node or historical selection is triggered.
        bootstrap('stage'); bootstrap('main')
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline:
            after = {role: job(role) for role in LABELS}
            if after['main']['pid'] and after['stage']['loaded']:
                ok = True
                for role in LABELS:
                    keys = ('V4_APP_ROOT', 'V4_RELEASE_ID', 'V4_RELEASE_MANIFEST_SHA256')
                    if role == 'main': keys += ('V4_RESEARCH_RETENTION_POLICY', 'V4_RESEARCH_RETENTION_POLICY_SHA256')
                    else: keys += ('STAGE_CENTER_CONFIG',)
                    ok &= all(after[role]['environment'].get(key) == proposed[role]['EnvironmentVariables'][key] for key in keys)
                if ok: break
            time.sleep(.2)
        else: raise RuntimeError('NEW_LOADED_IDENTITIES_NOT_CONFIRMED')
        require(after['main']['pid'] != before['main']['pid'], 'OLD_MAIN_PID_RETAINED')
        for role in LABELS:
            require(sha(LIVE[role]) == rows[role]['proposed_plist']['sha256'], 'POST_WRITE_PLIST_DRIFT:' + role)
        journal('STAGE_AND_SAME_MAIN_CONTROL_DEPLOYED_IDENTITY_VERIFIED', after=after,
                normal_Main_RunAtLoad_preserved=True, natural_scheduler_work_not_claimed_as_script_invocation=True)
    except BaseException as error:
        journal('ACTIVATION_FAILED_ROLLBACK_PENDING', error=str(error))
        try:
            # Fail closed instead of killing new natural work or overwriting
            # another operator's plist. Automatic rollback is an idle/CAS action.
            for role in LABELS:
                idle(role)
                require(sha(LIVE[role]) in {rows[role]['before_plist']['sha256'], rows[role]['proposed_plist']['sha256']}, 'ROLLBACK_FOREIGN_PLIST_DRIFT:' + role)
            rollback_starts = {}
            for role in LABELS:
                s = job(role)
                if s['pid']: rollback_starts[role] = (s['pid'], process_start(s['pid']))
                if s['loaded']: bootout(role)
            wait_unloaded(tuple(LABELS), rollback_starts)
            for role in LABELS:
                atomic_plist(role, checked(rows[role]['before_plist']).read_bytes(), modes[role])
            bootstrap('stage'); bootstrap('main')
            require(all(sha(LIVE[role]) == rows[role]['before_plist']['sha256'] for role in LABELS), 'ROLLBACK_PLIST_READBACK_FAILED')
            journal('ROLLED_BACK_BOTH_ORIGINAL_PLISTS', rollback_states={role: job(role) for role in LABELS})
        except BaseException as rollback_error:
            journal('ROLLBACK_BLOCKED_KEEP_CURRENT_STATE_FOR_CONTROLLER', rollback_error=str(rollback_error),
                    states={role: job(role) for role in LABELS})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--expected-prepare-sha256', required=True)
    parser.add_argument('--expected-validation-sha256', required=True)
    parser.add_argument('--expected-main-manifest-sha256', required=True)
    parser.add_argument('--execute', action='store_true')
    activate(parser.parse_args())
