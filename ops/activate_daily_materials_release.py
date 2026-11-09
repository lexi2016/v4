"""Controller-invoked CAS cutover for one frozen three-service packet.

There is deliberately no import-time action. The Writer prepares the packet;
the controller supplies an independent review receipt and invokes main.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import tempfile
import time


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=20)


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def loaded(label: str):
    response = run(['launchctl', 'print', f'gui/{os.getuid()}/{label}'])
    pid = next((int(line.strip().split(' = ')[1]) for line in response.stdout.splitlines()
                if line.strip().startswith('pid = ')), None)
    return response, pid


def listener_open() -> bool:
    try:
        with socket.create_connection(('127.0.0.1', 8873), timeout=.25):
            return True
    except OSError:
        return False


def wait_drained(label, pids, *, api=False, timeout=45):
    """A free port alone never permits a second API process to start."""
    deadline = time.monotonic() + timeout
    while True:
        state, _ = loaded(label)
        if state.returncode != 0 and not any(alive(pid) for pid in pids) and (not api or not listener_open()):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('OLD_PROCESS_NOT_DRAINED_NO_DUPLICATE:' + label)
        time.sleep(.15)


def descendants(pid):
    if not pid:
        return []
    result = run(['ps', '-axo', 'pid=,ppid='])
    result.check_returncode()
    edges = [tuple(map(int, row.split())) for row in result.stdout.splitlines() if row.strip()]
    selected = {pid}
    while True:
        expanded = selected | {child for child, parent in edges if parent in selected}
        if expanded == selected:
            return sorted(selected)
        selected = expanded


def replace_cas(target: Path, source: Path, before: str):
    if digest(target) != before:
        raise RuntimeError('CONCURRENT_CHANGE_NO_OVERWRITE:' + str(target))
    raw = source.read_bytes()
    fd, temporary = tempfile.mkstemp(prefix='.' + target.name + '.cutover-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, target.stat().st_mode & 0o777)
        if digest(target) != before:
            raise RuntimeError('CONCURRENT_CHANGE_NO_OVERWRITE:' + str(target))
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def wait_running(service, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state, pid = loaded(service['label'])
        if (pid and 'state = running' in state.stdout
                and service['app_root'] in state.stdout and service['manifest_sha256'] in state.stdout):
            return pid
        time.sleep(.25)
    raise RuntimeError('SERVICE_READY_TIMEOUT:' + service['label'])


def restore_services(services, backup, stopped):
    """Restore a complete previous tuple after any partial installation.

    Precheck every live byte before stopping anything. A concurrent third
    party change is never overwritten, even during recovery.
    """
    for role in stopped:
        service = services[role]
        if digest(Path(service['live_plist'])) not in {service['before_sha256'], service['draft_plist_sha256']}:
            raise RuntimeError('ROLLBACK_CONCURRENT_CHANGE_NO_OVERWRITE:' + role)
        if digest(backup / (role + '.plist')) != service['before_sha256']:
            raise RuntimeError('ROLLBACK_BACKUP_DRIFT:' + role)
    for role in stopped:
        service = services[role]
        current, pid = loaded(service['label'])
        tracked = descendants(pid)
        if current.returncode == 0:
            response = run(['launchctl', 'bootout', f'gui/{os.getuid()}/{service["label"]}'])
            response.check_returncode()
        wait_drained(service['label'], tracked, api=role == 'api')
    for role in stopped:
        service = services[role]
        target = Path(service['live_plist'])
        if digest(target) == service['draft_plist_sha256']:
            replace_cas(target, backup / (role + '.plist'), service['draft_plist_sha256'])
    # Only start after every previous file is restored, including the Main
    # policy locator which selects the original pins and the old Stage tuple.
    for role in ('api', 'main', 'stage'):
        if role in stopped:
            response = run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', services[role]['live_plist']])
            response.check_returncode()
            if role != 'stage':
                previous = dict(services[role], app_root=services[role]['old_app_root'],
                                manifest_sha256=services[role]['old_manifest_sha256'])
                wait_running(previous)
    return {'status': 'RESTORED_EXACT_PREVIOUS_TUPLE', 'roles': stopped}


def cutover(packet_path: Path, review_path: Path, *, rollback: bool = False):
    packet = json.loads(packet_path.read_text())
    review = json.loads(review_path.read_text())
    if review.get('verdict') not in {'PASS', 'REVIEWED/PASS'} or review.get('packet_sha256') != digest(packet_path):
        raise ValueError('INDEPENDENT_REVIEW_PACKET_BINDING_REQUIRED')
    # Same prepare validator is used before any service change and after install.
    from ops.prepare_daily_materials_release import validate_dependency_packet, homepage_smoke
    validate_dependency_packet(packet, installed=rollback)
    services = packet['services']
    held, stopped, changed = [], [], []
    state = {'status': 'PRECHECK', 'rollback_requested': rollback, 'steps': [],
             'natural_execution_verified': False, 'business_jobs_replayed': False}
    backup = packet_path.parent / 'cutover-backup'
    backup.mkdir(exist_ok=True)
    try:
        for name in ('DEFAULT.lock', 'A_LONG.lock'):
            path = Path(packet['scheduler_lane_lock_root']) / name
            stream = path.open('a+')
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(stream)
        for role in ('stage', 'main', 'api'):
            service = services[role]
            live = Path(service['live_plist'])
            expected = service['draft_plist_sha256'] if rollback else service['before_sha256']
            if digest(live) != expected:
                raise RuntimeError('LIVE_PLIST_CAS_FAILED:' + role)
            if not rollback:
                destination = backup / (role + '.plist')
                if destination.exists() and destination.read_bytes() != live.read_bytes():
                    raise RuntimeError('BACKUP_ALREADY_DIFFERENT:' + role)
                destination.write_bytes(live.read_bytes())
                destination.chmod(0o600)
            old_state, pid = loaded(service['label'])
            tracked = descendants(pid)
            if old_state.returncode == 0:
                response = run(['launchctl', 'bootout', f'gui/{os.getuid()}/{service["label"]}'])
                response.check_returncode()
            stopped.append(role)
            wait_drained(service['label'], tracked, api=role == 'api')
            state['steps'].append({'role': role, 'drained_pids': tracked})
        # All consumers are stopped; write the full dependency tuple before any
        # bootstrap, so no consumer observes a partly installed combination.
        for role in ('stage', 'api', 'main'):
            service = services[role]
            source = backup / (role + '.plist') if rollback else Path(service['draft_plist'])
            expected = service['draft_plist_sha256'] if rollback else service['before_sha256']
            replace_cas(Path(service['live_plist']), source, expected)
            changed.append(role)
        validate_dependency_packet(packet, installed=not rollback, old=rollback)
        for role in ('api', 'main', 'stage'):
            service = services[role]
            response = run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', service['live_plist']])
            response.check_returncode()
            if role != 'stage' and not rollback:
                wait_running(service)
        if not rollback:
            deadline = time.monotonic() + 60
            while True:
                try:
                    state['homepage_gets'] = homepage_smoke('http://127.0.0.1:8873')
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.3)
        state['status'] = 'ROLLED_BACK_EXACT_PREVIOUS' if rollback else 'ACTIVATED_API_GET_VERIFIED_NATURAL_PENDING'
    except BaseException as error:
        state.update(status='FAILED', error=type(error).__name__ + ':' + str(error), stopped=stopped, changed=changed)
        if not rollback and stopped:
            try:
                state['rollback'] = restore_services(services, backup, stopped)
            except BaseException as recovery_error:
                state['rollback'] = {'status': 'CANNOT_CONFIRM_REQUIRES_CONTROLLER',
                                     'error': type(recovery_error).__name__ + ':' + str(recovery_error)}
        raise
    finally:
        (packet_path.parent / 'ACTIVATION_RECEIPT.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
        for stream in reversed(held):
            fcntl.flock(stream, fcntl.LOCK_UN)
            stream.close()
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    print(json.dumps(cutover(args.packet, args.review, rollback=args.rollback), ensure_ascii=False))


if __name__ == '__main__':
    main()
