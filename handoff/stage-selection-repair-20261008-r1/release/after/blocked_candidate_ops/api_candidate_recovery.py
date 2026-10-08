#!/usr/bin/env python3
"""R2 API-only fail-closed rollback/recovery helpers.

The candidate identity is supplied by a separately frozen JSON file only after
the active release stabilizes. This module is not an activation command and is
not run against the live service while preparing the candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol


DEFAULT_GUARD = Path(__file__).resolve().with_name('hk_calendar_candidate_cutover.py')
REVIEWED_GUARD_SHA256 = '932c1d1e4d6111faba8cee92f9a3ed0014018f71f986c4237346974260e5e69d'
RECOVER_CONFIRMATION = 'RECOVER_API_CANDIDATE_TO_BASELINE_R2'
ALLOWED_DEPLOYABLE_STATUSES = frozenset({'READY'})
REQUIRED_REVIEW_SCOPE_IDENTITY_KEYS = ('candidate_manifest_sha256', 'staged_plist_sha256')


class RecoveryError(RuntimeError):
    def __init__(self, message: str, *, recovery: dict[str, Any] | None = None) -> None:
        self.recovery = recovery
        super().__init__(message)


@dataclass(frozen=True)
class LaunchdStatus:
    pid: int
    state: str | None
    output: str


@dataclass(frozen=True)
class RecoveryIdentity:
    active_plist: Path
    baseline_backup: Path
    candidate_plist: Path
    evidence_root: Path
    label: str
    domain: str
    baseline_sha256: str
    candidate_sha256: str
    guard_path: Path = DEFAULT_GUARD
    guard_sha256: str = REVIEWED_GUARD_SHA256
    lsof_path: Path = Path('/usr/sbin/lsof')

    @classmethod
    def from_json(cls, path: Path) -> 'RecoveryIdentity':
        value = json.loads(_read_regular_bytes(path, 'recovery identity'))
        if not isinstance(value, dict):
            raise RecoveryError('recovery identity must be a JSON object')
        required = (
            'active_plist', 'baseline_backup', 'candidate_plist', 'evidence_root',
            'label', 'domain', 'baseline_sha256', 'candidate_sha256', 'guard_path', 'guard_sha256',
        )
        missing = [key for key in required if not value.get(key)]
        if missing:
            raise RecoveryError('recovery identity missing: ' + ', '.join(missing))
        if value['guard_sha256'] != REVIEWED_GUARD_SHA256:
            raise RecoveryError('recovery identity guard SHA pin is not the reviewed guard')
        if not isinstance(value['guard_path'], str) or not Path(value['guard_path']).is_absolute():
            raise RecoveryError('recovery identity guard path must be absolute')
        return cls(
            active_plist=Path(value['active_plist']),
            baseline_backup=Path(value['baseline_backup']),
            candidate_plist=Path(value['candidate_plist']),
            evidence_root=Path(value['evidence_root']),
            label=str(value['label']),
            domain=str(value['domain']),
            baseline_sha256=str(value['baseline_sha256']),
            candidate_sha256=str(value['candidate_sha256']),
            guard_path=Path(value['guard_path']),
            guard_sha256=value['guard_sha256'],
            lsof_path=Path(value.get('lsof_path', '/usr/sbin/lsof')),
        )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _read_regular_bytes(path: Path, name: str) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise RecoveryError(f'{name} must be a regular file')
            return handle.read()
    except OSError as exc:
        raise RecoveryError(f'{name} cannot be read as a regular file: {path}') from exc


def reviewed_guard_bytes(path: Path, expected_sha256: str) -> bytes:
    if expected_sha256 != REVIEWED_GUARD_SHA256:
        raise RecoveryError('guard SHA pin is not the reviewed guard')
    raw = _read_regular_bytes(path, 'guard')
    if sha256_bytes(raw) != expected_sha256:
        raise RecoveryError('guard SHA drift; refusing to execute external code')
    return raw


def import_reviewed_guard(path: Path, expected_sha256: str, evidence_root: Path):
    raw = reviewed_guard_bytes(path, expected_sha256)
    spec = importlib.util.spec_from_file_location('reviewed_api_cutover_guard_r2', path)
    if spec is None:
        raise RecoveryError('reviewed atomic cutover guard is unavailable')
    guard = importlib.util.module_from_spec(spec)
    # Compile the exact bytes that passed the SHA check. exec_module would
    # reopen the external path (or use cached bytecode) after verification.
    exec(compile(raw, str(path), 'exec'), guard.__dict__)
    guard.EVIDENCE_ROOT = evidence_root
    return guard


def _plist_identity(raw: bytes, *, expected_label: str, name: str) -> tuple[dict[str, Any], tuple[str, str, str]]:
    import plistlib

    try:
        value = plistlib.loads(raw)
    except Exception as exc:
        raise RecoveryError(f'{name} plist cannot be parsed') from exc
    if value.get('Label') != expected_label:
        raise RecoveryError(f'{name} plist label mismatch')
    env: dict[str, str] = {}
    for item in value.get('ProgramArguments', []):
        if isinstance(item, str) and '=' in item:
            key, data = item.split('=', 1)
            env[key] = data
    for key, data in (value.get('EnvironmentVariables') or {}).items():
        if isinstance(key, str) and isinstance(data, (str, int, float, bool)):
            env[key] = str(data)
    tokens = tuple(env.get(key, '') for key in ('V35_APP_ROOT', 'V35_RELEASE_ID', 'V35_RELEASE_MANIFEST_SHA256'))
    if any(not token for token in tokens):
        raise RecoveryError(f'{name} plist lacks release identity pins')
    return value, tokens  # type: ignore[return-value]


def _validate_pins(identity: RecoveryIdentity) -> tuple[bytes, bytes, tuple[str, str, str], tuple[str, str, str]]:
    baseline = _read_regular_bytes(identity.baseline_backup, 'baseline backup')
    candidate = _read_regular_bytes(identity.candidate_plist, 'staged candidate')
    if sha256_bytes(baseline) != identity.baseline_sha256:
        raise RecoveryError('baseline plist backup SHA mismatch')
    if sha256_bytes(candidate) != identity.candidate_sha256:
        raise RecoveryError('staged candidate plist SHA mismatch')
    if baseline == candidate:
        raise RecoveryError('baseline and candidate plist bytes must differ')
    _, baseline_tokens = _plist_identity(baseline, expected_label=identity.label, name='baseline')
    _, candidate_tokens = _plist_identity(candidate, expected_label=identity.label, name='candidate')
    return baseline, candidate, baseline_tokens, candidate_tokens


def parse_launchctl_status(result: Any, *, label: str, domain: str) -> LaunchdStatus | None:
    output = '\n'.join((getattr(result, 'stdout', '') or '', getattr(result, 'stderr', '') or '')).strip()
    if result.returncode != 0:
        uid = domain.split('/', 1)[1] if '/' in domain else ''
        expected_absence = rf'Could not find service "{re.escape(label)}" in domain for user gui: {re.escape(uid)}'
        if uid and re.search(expected_absence, output, re.IGNORECASE):
            return None
        raise RecoveryError(f'cannot prove exact launchd label absence: {output or "empty diagnostic"}')
    match = re.search(r'\bpid\s*=\s*(\d+)\b', result.stdout or '', re.IGNORECASE)
    if not match:
        raise RecoveryError('launchctl output has no PID field')
    state_match = re.search(r'(?im)^\s*state\s*=\s*([^\r\n]+)', result.stdout or '')
    state = state_match.group(1).strip().lower() if state_match else None
    return LaunchdStatus(pid=int(match.group(1)), state=state, output=result.stdout or '')


def verify_reviewer_receipt(path: Path, expected_sha256: str, expected_scope: dict[str, Any]) -> dict[str, Any]:
    raw = _read_regular_bytes(path, 'independent reviewer receipt')
    if sha256_bytes(raw) != expected_sha256:
        raise RecoveryError('independent reviewer receipt SHA mismatch')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RecoveryError('independent reviewer receipt must be a JSON object')
    status = value.get('status')
    if not isinstance(status, dict) or status.get('REVIEWED') != 'PASS':
        raise RecoveryError('independent review is not formal REVIEWED=PASS')
    behavior = status.get('BEHAVIOR_VERIFIED')
    if not isinstance(behavior, str) or not behavior.startswith('PASS'):
        raise RecoveryError('independent review lacks passing BEHAVIOR_VERIFIED')
    deployable = status.get('DEPLOYABLE')
    if not isinstance(deployable, str) or deployable not in ALLOWED_DEPLOYABLE_STATUSES:
        raise RecoveryError('independent reviewer DEPLOYABLE status is not explicitly allowed')
    findings = value.get('findings')
    required_findings = {'P0', 'P1', 'P2'}
    if not isinstance(findings, dict) or set(findings) != required_findings or any(
        not isinstance(findings[severity], list) for severity in required_findings
    ):
        raise RecoveryError('independent reviewer findings must contain complete P0/P1/P2 lists')
    for severity in ('P0', 'P1'):
        if findings[severity] != []:
            raise RecoveryError(f'independent reviewer reported {severity} findings')
    if not isinstance(expected_scope, dict) or not expected_scope:
        raise RecoveryError('expected scope must be a nonempty frozen candidate scope')
    invalid_scope_keys = [key for key in expected_scope if not isinstance(key, str) or not key.strip()]
    if invalid_scope_keys:
        raise RecoveryError('expected scope contains an empty or invalid key')
    invalid_identity_pins = [
        key for key in REQUIRED_REVIEW_SCOPE_IDENTITY_KEYS
        if not isinstance(expected_scope.get(key), str)
        or re.fullmatch(r'[0-9a-fA-F]{64}', expected_scope[key]) is None
    ]
    if invalid_identity_pins:
        raise RecoveryError('expected scope lacks required nonempty candidate identity pins: ' + ', '.join(invalid_identity_pins))
    if (expected_scope.get('guard_sha256') != REVIEWED_GUARD_SHA256
            or not isinstance(expected_scope.get('guard_path'), str)
            or not Path(expected_scope['guard_path']).is_absolute()):
        raise RecoveryError('expected scope lacks the exact reviewed guard path and SHA pin')
    scope = value.get('scope')
    if not isinstance(scope, dict):
        raise RecoveryError('independent reviewer candidate scope is missing')
    mismatches = [key for key, expected in expected_scope.items() if key not in scope or scope[key] != expected]
    if mismatches:
        raise RecoveryError('independent reviewer receipt does not match frozen candidate: ' + ', '.join(mismatches))
    if scope != expected_scope:
        raise RecoveryError('reviewer receipt scope is not an exact match to the frozen scope')
    identity = value.get('review_identity')
    if not isinstance(identity, str) or not identity.strip():
        raise RecoveryError('independent reviewer identity is missing')
    return value


class RecoveryOps(Protocol):
    def launchd_status(self) -> LaunchdStatus | None: ...
    def require_port_free(self) -> None: ...
    def bootout(self) -> None: ...
    def wait_for_absence(self, owner_tokens: tuple[str, str, str]) -> None: ...
    def atomic_restore(self, baseline_bytes: bytes) -> None: ...
    def bootstrap(self) -> None: ...
    def wait_for_baseline(self, baseline_tokens: tuple[str, str, str]) -> dict[str, Any]: ...


def _require_owned_status(status: LaunchdStatus, owner_tokens: tuple[str, str, str], owner: str) -> None:
    if status.pid > 0:
        missing = [token for token in owner_tokens if token not in status.output]
        if missing:
            raise RecoveryError(f'positive launchd PID identity drift; refusing {owner} rollback')
        return
    if status.pid != 0 or status.state != 'waiting':
        raise RecoveryError(f'launchd state is not an owned waiting/pid=0 state for {owner}')


def validate_claim_receipt(identity: RecoveryIdentity, guard: Any, path: Path, expected_sha256: str) -> dict[str, Any]:
    if (not path.is_absolute() or path != Path(os.path.abspath(path))
            or path.parent != identity.evidence_root):
        raise RecoveryError('claim receipt path must be in the frozen evidence directory')
    raw = _read_regular_bytes(path, 'claim receipt')
    if sha256_bytes(raw) != expected_sha256:
        raise RecoveryError('claim receipt SHA mismatch')
    value = json.loads(raw)
    phases = {
        base + suffix: pins
        for base, pins in (
            ('API_PRESELECTION_R2_INSTALL', (identity.baseline_sha256, identity.candidate_sha256)),
            ('API_R2_ROLLBACK_RESTORE', (identity.candidate_sha256, identity.baseline_sha256)),
        )
        for suffix in ('_CLAIM_RESERVED', '_INSTALL_FAILURE_RESTORE_FAILED', '_NO_CLOBBER_CONFLICT')
    }
    if not isinstance(value, dict) or value.get('phase') not in phases:
        raise RecoveryError('claim receipt is not an approved failed API CAS recovery phase')
    claim_sha, intended_sha = phases[value['phase']]
    if (value.get('schema_version') != 'v4.hk_calendar_cutover_drift.v1'
            or value.get('service') != 'api' or value.get('path') != str(identity.active_plist)
            or value.get('expected_sha256') != claim_sha
            or value.get('service_action_performed_by_recording') is not False):
        raise RecoveryError('claim receipt does not bind the exact active plist and frozen identity')
    details = value.get('details')
    if (not isinstance(details, dict) or details.get('claim_sha256') != claim_sha
            or details.get('candidate_sha256') != intended_sha
            or not isinstance(details.get('claim_path'), str)):
        raise RecoveryError('claim receipt does not bind the exact claim and intended plist SHA')
    claim_path = Path(details['claim_path'])
    try:
        guard.read_claim(identity.active_plist, claim_path, claim_sha)
    except (OSError, guard.GateError) as exc:
        raise RecoveryError(str(exc)) from exc
    return {'claim_path': str(claim_path), 'claim_sha256': claim_sha,
            'claim_receipt_path': str(path), 'claim_receipt_sha256': expected_sha256}


def recover_baseline(identity: RecoveryIdentity, ops: RecoveryOps, *, claim_receipt_path: Path | None = None, claim_receipt_sha256: str | None = None) -> dict[str, Any]:
    baseline, candidate, baseline_tokens, candidate_tokens = _validate_pins(identity)
    reviewed_guard_bytes(identity.guard_path, identity.guard_sha256)
    if (claim_receipt_path is None) != (claim_receipt_sha256 is None):
        raise RecoveryError('claim receipt path and exact SHA must be supplied together')
    claim_recovery = None
    if claim_receipt_path is not None:
        guard = import_reviewed_guard(identity.guard_path, identity.guard_sha256, identity.evidence_root)
        claim_recovery = validate_claim_receipt(identity, guard, claim_receipt_path, claim_receipt_sha256)
        if os.path.lexists(identity.active_plist):
            raise RecoveryError('claim recovery requires a missing active path; parallel path preserved')
        if ops.launchd_status() is not None:
            raise RecoveryError('exact launchd label must be absent before claim restore')
        ops.require_port_free()
        try:
            restore_receipt = guard.restore_claim_no_clobber('api', identity.active_plist,
                Path(claim_recovery['claim_path']), expected_claim_sha256=claim_recovery['claim_sha256'],
                phase='API_R2_CLAIM_RECOVERY')
        except (OSError, guard.GateError) as exc:
            raise RecoveryError(str(exc), recovery=getattr(exc, 'recovery', None)) from exc
        if sha256_bytes(_read_regular_bytes(identity.active_plist, 'restored active plist')) != claim_recovery['claim_sha256']:
            raise RecoveryError('claim restore active plist SHA drift; refusing bootstrap')
        claim_recovery.update(restore_receipt_path=str(restore_receipt), restore_receipt_sha256=sha256_file(restore_receipt))
    if not identity.active_plist.is_file():
        raise RecoveryError('active plist is missing')
    active = _read_regular_bytes(identity.active_plist, 'active plist')
    if active not in (baseline, candidate):
        raise RecoveryError('active plist is neither exact frozen baseline nor exact candidate; refusing recovery')
    status = ops.launchd_status()

    if active == baseline:
        if status is None:
            ops.require_port_free()
            if _read_regular_bytes(identity.active_plist, 'active plist') != baseline:
                raise RecoveryError('baseline plist drift before bootstrap')
            ops.bootstrap()
            loaded = ops.wait_for_baseline(baseline_tokens)
            if claim_recovery is not None:
                return {'status': 'CLAIM_RESTORED_BASELINE_BOOTSTRAPPED', 'plist_sha256': identity.baseline_sha256,
                        'loaded_identity': loaded, 'claim_recovery': claim_recovery}
            return {'status': 'BASELINE_REBOOTSTRAPPED', 'plist_sha256': identity.baseline_sha256, 'loaded_identity': loaded}
        _require_owned_status(status, baseline_tokens, 'baseline')
        loaded = ops.wait_for_baseline(baseline_tokens)
        return {'status': 'BASELINE_ALREADY_OWNED', 'plist_sha256': identity.baseline_sha256, 'loaded_identity': loaded}

    if status is not None:
        _require_owned_status(status, candidate_tokens, 'candidate')
        try:
            ops.bootout()
        except RecoveryError:
            # The old accepted wrapper tolerates bootout returning an error
            # only when a fresh exact-label query proves it is already absent.
            if ops.launchd_status() is not None:
                raise
    ops.wait_for_absence(candidate_tokens)
    if _read_regular_bytes(identity.active_plist, 'active plist') != candidate:
        raise RecoveryError('active plist changed before candidate-to-baseline restore')
    if ops.launchd_status() is not None:
        raise RecoveryError('exact launchd label is not absent before plist restore')
    ops.require_port_free()
    ops.atomic_restore(baseline)
    if _read_regular_bytes(identity.active_plist, 'active plist') != baseline:
        raise RecoveryError('baseline plist bytes did not read back after atomic restore')
    if ops.launchd_status() is not None:
        raise RecoveryError('exact launchd label reappeared before baseline bootstrap')
    ops.require_port_free()
    if _read_regular_bytes(identity.active_plist, 'active plist') != baseline:
        raise RecoveryError('baseline plist drift before bootstrap')
    ops.bootstrap()
    loaded = ops.wait_for_baseline(baseline_tokens)
    if claim_recovery is not None:
        return {'status': 'CLAIM_RESTORED_BASELINE_BOOTSTRAPPED', 'plist_sha256': identity.baseline_sha256,
                'loaded_identity': loaded, 'claim_recovery': claim_recovery}
    return {'status': 'CANDIDATE_ROLLED_BACK_BASELINE_BOOTSTRAPPED', 'plist_sha256': identity.baseline_sha256, 'loaded_identity': loaded}


class SystemRecoveryOps:
    def __init__(self, identity: RecoveryIdentity, *, runner: Callable[..., Any] = subprocess.run, timeout_seconds: float = 30.0, poll_interval_seconds: float = 0.25) -> None:
        self.identity = identity
        self.runner = runner
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    @property
    def service_target(self) -> str:
        return f'{self.identity.domain}/{self.identity.label}'

    def launchd_status(self) -> LaunchdStatus | None:
        result = self.runner(['/bin/launchctl', 'print', self.service_target], capture_output=True, text=True, check=False)
        return parse_launchctl_status(result, label=self.identity.label, domain=self.identity.domain)

    def require_port_free(self) -> None:
        result = self.runner([str(self.identity.lsof_path), '-nP', '-iTCP:8873', '-sTCP:LISTEN'], capture_output=True, text=True, check=False)
        stdout = (result.stdout or '').strip()
        stderr = (result.stderr or '').strip()
        if result.returncode == 1 and not stdout and not stderr:
            return
        if result.returncode == 0 and stdout:
            raise RecoveryError('port 8873 is occupied')
        raise RecoveryError(f'cannot prove port 8873 is free (lsof rc={result.returncode}, stdout={stdout!r}, stderr={stderr!r})')

    def bootout(self) -> None:
        result = self.runner(['/bin/launchctl', 'bootout', self.service_target], capture_output=True, text=True, check=False)
        if result.returncode:
            raise RecoveryError(f'launchctl bootout failed: {(result.stderr or result.stdout or "").strip()}')

    def wait_for_absence(self, owner_tokens: tuple[str, str, str]) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            status = self.launchd_status()
            if status is None:
                return
            _require_owned_status(status, owner_tokens, 'candidate shutdown')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RecoveryError('candidate launchd label did not become absent before timeout')
            time.sleep(min(self.poll_interval_seconds, remaining))

    def atomic_restore(self, baseline_bytes: bytes) -> None:
        guard = import_reviewed_guard(self.identity.guard_path, self.identity.guard_sha256, self.identity.evidence_root)
        try:
            guard.atomic_write_no_clobber('api', self.identity.active_plist, baseline_bytes, expected_current_sha256=self.identity.candidate_sha256, phase='API_R2_ROLLBACK_RESTORE')
        except (OSError, guard.GateError) as exc:
            raise RecoveryError(str(exc), recovery=getattr(exc, 'recovery', None)) from exc

    def bootstrap(self) -> None:
        result = self.runner(['/bin/launchctl', 'bootstrap', self.identity.domain, str(self.identity.active_plist)], capture_output=True, text=True, check=False)
        if result.returncode:
            raise RecoveryError(f'launchctl bootstrap baseline failed: {(result.stderr or result.stdout or "").strip()}')

    def wait_for_baseline(self, baseline_tokens: tuple[str, str, str]) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            status = self.launchd_status()
            if status is None:
                raise RecoveryError('baseline launchd label is absent after bootstrap/readiness wait')
            if status.pid > 0:
                missing = [token for token in baseline_tokens if token not in status.output]
                if missing:
                    raise RecoveryError('positive baseline PID identity drift; refusing to claim recovery')
                return {'pid': status.pid, 'launchd_output_sha256': sha256_bytes(status.output.encode()), 'release_id': baseline_tokens[1]}
            if status.pid != 0 or status.state != 'waiting':
                raise RecoveryError('baseline launchd state is not waiting/pid=0')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RecoveryError('baseline remained waiting/pid=0 beyond readiness timeout')
            time.sleep(min(self.poll_interval_seconds, remaining))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    check = sub.add_parser('review-check')
    check.add_argument('--receipt', type=Path, required=True)
    check.add_argument('--sha256', required=True)
    check.add_argument('--expected-scope-json', type=Path, required=True)
    recover = sub.add_parser('recover-baseline')
    recover.add_argument('--identity-json', type=Path, required=True)
    recover.add_argument('--confirm', required=True)
    recover.add_argument('--claim-receipt-path', type=Path)
    recover.add_argument('--claim-receipt-sha256')
    args = parser.parse_args()
    if args.action == 'review-check':
        expected_scope = json.loads(args.expected_scope_json.read_text(encoding='utf-8'))
        value = verify_reviewer_receipt(args.receipt, args.sha256, expected_scope)
        print(json.dumps({'status': 'INDEPENDENT_REVIEW_PASS_FOR_PINNED_CANDIDATE', 'review_identity': value['review_identity']}, ensure_ascii=False, indent=2))
        return 0
    if args.confirm != RECOVER_CONFIRMATION:
        raise RecoveryError('exact r2 recovery confirmation string is required')
    identity = RecoveryIdentity.from_json(args.identity_json)
    result = recover_baseline(identity, SystemRecoveryOps(identity),
                             claim_receipt_path=args.claim_receipt_path, claim_receipt_sha256=args.claim_receipt_sha256)
    print(json.dumps({**result, 'service_operation_performed': True, 'other_service_touched': False, 'data_root_touched': False, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RecoveryError) as exc:
        print(json.dumps({'status': 'STOP_CANNOT_CONFIRM', 'error': str(exc),
                          'claim_recovery': getattr(exc, 'recovery', None)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
