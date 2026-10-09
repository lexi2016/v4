"""Provider-free daily rebound invocation for the existing Mac dispatcher.

No scheduler is installed here. Successful numeric observations are reused by
input/code/environment identity; that success never means admitted selection.
Interrupted claims require explicit readback reconciliation, not blind reruns.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import platform
import stat
import uuid

from . import rebound_observation as observation
from . import rebound_owner as owner
from .contracts import aware
from .digests import canonical_bytes, sha256_json
from .module_api import _read_at
from .module_artifacts import _directory, _write_once
from .rebound_recovery import build_recovery_plan


def _identity():
    return dict(observation=observation._identity(),
        daily_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        recovery_sha256=hashlib.sha256(Path(__file__).with_name('rebound_recovery.py').read_bytes()).hexdigest(),
        capsule_sha256=observation.PIN, python=platform.python_version(),
        dependencies=owner.observe_dependencies(owner.BASE / 'uv.lock'))


def _prepare(request, *, reconciliation=False):
    request = observation._request(request)
    if request['data_kind'] != 'RECORDED_INPUT_CURRENT':
        raise ValueError('REBOUND_DAILY_CURRENT_RECORDED_INPUT_REQUIRED')
    if not reconciliation and request['target_date'] != datetime.now(observation.HK).strftime('%Y%m%d'):
        raise ValueError('REBOUND_DAILY_CURRENT_TARGET_REQUIRED')
    # Do not let a reusable receipt conceal changed bytes at the bound source.
    for path, digest in request['files'].items():
        if owner._file(Path(request['input_root']), path)['sha256'] != digest:
            raise ValueError('REBOUND_DAILY_INPUT_CHANGED')
    observation._capsule()
    identity = _identity()
    key = sha256_json(dict(request=request, identity=identity))
    return request, identity, key


@contextmanager
def _locked(output_root, key, input_root):
    root, fd = observation._output(output_root)
    day = lock = None
    try:
        source = Path(input_root)
        if root.is_relative_to(source) or source.is_relative_to(root):
            raise ValueError('REBOUND_DAILY_ROOT_OVERLAP')
        daily = _directory(fd, 'daily')
        try: day = _directory(daily, key)
        finally: os.close(daily)
        lock = os.open('.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=day)
        if not stat.S_ISREG(os.fstat(lock).st_mode): raise ValueError('REBOUND_DAILY_LOCK_TYPE')
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise ValueError('REBOUND_DAILY_BUSY') from error
        yield root, day
    finally:
        if lock is not None: os.close(lock)
        if day is not None: os.close(day)
        os.close(fd)


def _read(directory, name):
    try: return owner._json(_read_at(directory, None, name))
    except FileNotFoundError: return None


def _match(artifact, request, identity):
    if (artifact['request'] != request or artifact['implementation_identity'] != identity['observation']
            or artifact['source_capsule_sha256'] != identity['capsule_sha256']
            or artifact.get('dependencies') != identity['dependencies']):
        raise ValueError('REBOUND_DAILY_OWNER_READBACK_IDENTITY')


def _result(artifact, reference, key, reused):
    ready = artifact['computation_status'] == 'NATIVE_VALUES_OBSERVED'
    return dict(schema_version='v5.rebound_daily_result.v1', daily_key=key, reused=reused,
        reference=reference, computation_status=artifact['computation_status'],
        selection_status='CANNOT_CONFIRM',
        numeric_counts=artifact.get('counts'),
        recovery_plan=build_recovery_plan(artifact) if ready else None,
        reason_codes=list(artifact['reason_codes']), scheduler_installed=False,
        **observation.SAFETY)


def _completed(root, directory, request, identity, key):
    record = _read(directory, 'completed.json')
    if record is None: return None
    if (record.get('schema_version') != 'v5.rebound_daily_commit.v1'
            or record.get('daily_key') != key or record.get('identity') != identity
            or record.get('request_sha256') != sha256_json(request)):
        raise ValueError('REBOUND_DAILY_COMMIT_IDENTITY')
    artifact = observation.read_rebound_observation(root, record['reference'])
    _match(artifact, request, identity)
    if artifact['computation_status'] != 'NATIVE_VALUES_OBSERVED':
        raise ValueError('REBOUND_DAILY_COMMIT_NOT_SUCCESSFUL')
    return _result(artifact, record['reference'], key, True)


def _commit(directory, request, identity, key, reference):
    _write_once(directory, 'completed.json', canonical_bytes(dict(
        schema_version='v5.rebound_daily_commit.v1', daily_key=key,
        request_sha256=sha256_json(request), identity=identity, reference=reference)))


def run_rebound_daily(request, output_root):
    """Call after the existing dispatcher resolves today's exact owner files.

    No clock override and no inferred schedule slot. The original calculator
    selects the prior completed full HK session; evening-next-day is unsupported.
    """
    request, identity, key = _prepare(request)
    with _locked(output_root, key, request['input_root']) as (root, directory):
        completed = _completed(root, directory, request, identity, key)
        if completed is not None: return completed
        if _read(directory, 'inflight.json') is not None:
            raise ValueError('REBOUND_DAILY_INTERRUPTED_RECONCILIATION_REQUIRED')
        attempt = uuid.uuid4().hex
        claim = dict(schema_version='v5.rebound_daily_claim.v1', attempt_id=attempt,
            daily_key=key, request_sha256=sha256_json(request), identity=identity,
            started_at=datetime.now(timezone.utc).isoformat())
        _write_once(directory, 'inflight.json', canonical_bytes(claim))
        # Unexpected exceptions leave the claim intact. A process interruption
        # must not silently cause a duplicate product calculation after restart.
        result = observation.run_rebound_observation(request, root)
        reference = result['reference']
        artifact = observation.read_rebound_observation(root, reference)
        if _identity() != identity: raise ValueError('REBOUND_DAILY_IMPLEMENTATION_CHANGED')
        if artifact['request'] != request: raise ValueError('REBOUND_DAILY_REQUEST_CHANGED')
        if not aware(claim['started_at']) <= aware(artifact['started_at']) <= aware(artifact['finished_at']):
            raise ValueError('REBOUND_DAILY_ATTEMPT_CLOCK')
        success = artifact['computation_status'] == 'NATIVE_VALUES_OBSERVED'
        if success: _match(artifact, request, identity)
        _write_once(directory, 'attempt-'+attempt+'.json', canonical_bytes(dict(claim,
            reference=reference, computation_status=artifact['computation_status'],
            finished_at=datetime.now(timezone.utc).isoformat())))
        if success: _commit(directory, request, identity, key, reference)
        os.unlink('inflight.json', dir_fd=directory)
        os.fsync(directory)
        return _result(artifact, reference, key, False)


def reconcile_rebound_daily(request, output_root, reference):
    """Bind a committed terminal run after an interrupted invocation.

    The reference comes from the original run's trio. No new computation and no
    automatic deletion of an unknown claim. Failed attempts remain inspectable.
    """
    request, identity, key = _prepare(request, reconciliation=True)
    with _locked(output_root, key, request['input_root']) as (root, directory):
        completed = _completed(root, directory, request, identity, key)
        if completed is not None: return completed
        artifact = observation.read_rebound_observation(root, reference)
        retired = _read(directory, 'reconciled-'+artifact['run_id']+'.json')
        if retired is not None and (retired.get('reference') != reference
                or retired.get('computation_status') != artifact['computation_status']):
            raise ValueError('REBOUND_DAILY_RECONCILIATION_RECEIPT')
        claim = _read(directory, 'inflight.json')
        if retired is not None: claim = retired.get('claim')
        if (claim is None or claim.get('schema_version') != 'v5.rebound_daily_claim.v1'
                or claim.get('daily_key') != key or claim.get('identity') != identity
                or claim.get('request_sha256') != sha256_json(request)):
            raise ValueError('REBOUND_DAILY_RECONCILIATION_CLAIM')
        if (artifact['request'] != request or artifact['implementation_identity'] != identity['observation']
                or artifact['source_capsule_sha256'] != identity['capsule_sha256']
                or artifact['computation_status'] not in ('NATIVE_VALUES_OBSERVED', 'CANNOT_CONFIRM')
                or not aware(claim['started_at']) <= aware(artifact['started_at']) <= aware(artifact['finished_at'])
                or aware(artifact['finished_at']) > datetime.now(timezone.utc)):
            raise ValueError('REBOUND_DAILY_RECONCILIATION_RUN')
        success = artifact['computation_status'] == 'NATIVE_VALUES_OBSERVED'
        if retired is not None: return _result(artifact, reference, key, True)
        if success:
            _match(artifact, request, identity)
            _commit(directory, request, identity, key, reference)
        _write_once(directory, 'reconciled-'+reference['run_id']+'.json', canonical_bytes(dict(
            claim=claim, reference=reference, computation_status=artifact['computation_status'])))
        os.unlink('inflight.json', dir_fd=directory); os.fsync(directory)
        return _result(artifact, reference, key, True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--reconcile-reference', type=Path)
    args = parser.parse_args()
    request = owner._json(args.request.read_bytes())
    if args.reconcile_reference:
        return reconcile_rebound_daily(request, args.output_root, owner._json(args.reconcile_reference.read_bytes()))
    return run_rebound_daily(request, args.output_root)


if __name__ == '__main__':
    print(canonical_bytes(main()).decode())
