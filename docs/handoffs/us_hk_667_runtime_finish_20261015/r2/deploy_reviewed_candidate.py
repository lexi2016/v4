"""Activate the independently reviewed bytes, with lock/CAS and rollback."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import time
import urllib.request

from ops.api_release_integration import shared_api_release_lock, verify_api_release_candidate

BASE = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
OUT = Path(__file__).resolve().parent
PLIST = Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
CANDIDATE = BASE / 'releases/us-hk-mapping-finish-20261015-r2'
PLAN = json.loads((OUT / 'candidate-preparation-receipt.json').read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_install(raw, mode):
    fd, temporary = tempfile.mkstemp(prefix='.com.lexi.v35.api-only.catalog-', dir=PLIST.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, PLIST)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def launch(*args, check=True):
    result = subprocess.run(['/bin/launchctl', *args], capture_output=True, text=True, timeout=30)
    row = dict(command=['launchctl', *args], exit_code=result.returncode,
               stdout=result.stdout, stderr=result.stderr)
    RECEIPT['commands'].append(row)
    if check and result.returncode:
        raise RuntimeError('LAUNCHCTL_FAILED:' + args[0])


def bootout_and_wait(target, label, check=True):
    pid_result = subprocess.run(['/usr/sbin/lsof', '-t', '-nP', '-iTCP:8873', '-sTCP:LISTEN'],
                                capture_output=True, text=True)
    old_pids = [int(value) for value in pid_result.stdout.split() if value.isdecimal()]
    launch('bootout', target + '/' + label, check=check)
    for attempt in range(20):
        state = subprocess.run(['/bin/launchctl', 'print', target + '/' + label], capture_output=True, text=True)
        alive = [pid for pid in old_pids if subprocess.run(['/bin/kill', '-0', str(pid)],
                  capture_output=True).returncode == 0]
        if state.returncode and not alive:
            # bootout acknowledgement precedes completion of launchd removal.
            # The first attempt raced that window; allow the detached job's
            # asynchronous removal to settle before the one bootstrap call.
            time.sleep(2)
            RECEIPT.setdefault('detach_checks', []).append(dict(old_pids=old_pids,
                old_pids_exited=True, label_absent=True, settle_seconds=2))
            return
        time.sleep(0.5)
    raise RuntimeError('SERVICE_DETACH_NOT_CONFIRMED')


RECEIPT = dict(started_at=datetime.now(timezone.utc).isoformat(), status='PRECHECK',
    commands=[], rollback_performed=False, candidate_manifest_sha256=PLAN['candidate_manifest_sha256'])


def main():
    target = 'gui/' + str(os.getuid())
    label = 'com.lexi.v35.api-only'
    staged = Path(PLAN['staged_plist'])
    review = OUT.parents[1] / 'us_hk_667_finish_review_20261015/R2_RUNTIME_REVIEW_RECEIPT.md'
    assert 'REVIEWED=PASS' in review.read_text()
    RECEIPT['review_receipt'] = str(review)
    RECEIPT['review_receipt_sha256'] = sha(review)
    with shared_api_release_lock(PLIST, timeout_seconds=5, role='gateway') as lease:
        if sha(PLIST) != PLAN['source_plist_sha256']:
            raise RuntimeError('ACTIVE_PLIST_CAS_CHANGED_REBASE_REQUIRED')
        if sha(BASE / 'config/manager-workbench-v7.json') != '65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca':
            raise RuntimeError('SOURCE_CONFIG_CAS_CHANGED_REBASE_REQUIRED')
        if sha(Path(PLAN['config_path'])) != PLAN['config_sha256'] or sha(staged) != PLAN['staged_plist_sha256']:
            raise RuntimeError('REVIEWED_CONFIG_OR_PLIST_CHANGED')
        RECEIPT['preflight'] = verify_api_release_candidate(candidate_root=CANDIDATE,
            active_api_plist_path=PLIST, expected_manifest_sha256=PLAN['candidate_manifest_sha256'],
            active_pointer='base', require_shared_lock=True, lock_lease=lease)
        original = PLIST.read_bytes()
        if original != Path(PLAN['rollback_plist']).read_bytes():
            raise RuntimeError('ROLLBACK_PREIMAGE_CAS_MISMATCH')
        mode = PLIST.stat().st_mode & 0o777
        try:
            bootout_and_wait(target, label)
            atomic_install(staged.read_bytes(), mode)
            launch('bootstrap', target, str(PLIST))
            last_error = None
            for attempt in range(20):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8873/api/v4/manager-workbench/mapping-catalog', timeout=3) as response:
                        raw = response.read()
                        data = json.loads(raw)['data']
                    if len(raw) != 611266 or data['total'] != 667 or data['review_progress']['source_reviewed_relations'] != 220:
                        raise RuntimeError('LIVE_CATALOG_IDENTITY_MISMATCH')
                    RECEIPT['live_first_read'] = dict(response_bytes=len(raw), total=data['total'], progress=data['review_progress'])
                    break
                except Exception as exc:
                    last_error = str(exc)
                    if attempt == 19:
                        raise RuntimeError('LIVE_API_READBACK_FAILED:' + last_error)
                    time.sleep(1)
            RECEIPT['postflight'] = verify_api_release_candidate(candidate_root=CANDIDATE,
                active_api_plist_path=PLIST, expected_manifest_sha256=PLAN['candidate_manifest_sha256'],
                active_pointer='candidate', require_shared_lock=True, lock_lease=lease)
            RECEIPT['status'] = 'DEPLOYED_API_READBACK_OK'
            RECEIPT['active_plist_sha256'] = sha(PLIST)
            RECEIPT['active_working_directory'] = plistlib.loads(PLIST.read_bytes())['WorkingDirectory']
        except Exception:
            bootout_and_wait(target, label, check=False)
            atomic_install(original, mode)
            RECEIPT['rollback_performed'] = True
            RECEIPT['status'] = 'FAILED_ROLLED_BACK'
            launch('bootstrap', target, str(PLIST))
            raise


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        RECEIPT['error'] = dict(type=type(exc).__name__, message=str(exc))
        raise
    finally:
        RECEIPT['finished_at'] = datetime.now(timezone.utc).isoformat()
        with (OUT / 'activation-receipt-attempt2.json').open('x') as handle:
            json.dump(RECEIPT, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write('\n')
        print(json.dumps({k:v for k,v in RECEIPT.items() if k not in ('preflight','postflight')}, ensure_ascii=False, indent=2))
