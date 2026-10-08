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
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol


DEFAULT_GUARD = Path('/Users/lexi/Desktop/学习/agents调试/V4_HK_CLOSE_DAILY_20261007/hk_market_calendar/hk_calendar_candidate_cutover.py')
RECOVER_CONFIRMATION = 'RECOVER_API_CANDIDATE_TO_BASELINE_R2'
ALLOWED_DEPLOYABLE_STATUSES = frozenset({'READY'})
REQUIRED_REVIEW_SCOPE_IDENTITY_KEYS = ('candidate_manifest_sha256', 'staged_plist_sha256')


class RecoveryError(RuntimeError):
    pass


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
    lsof_path: Path = Path('/usr/sbin/lsof')

    @classmethod
    def from_json(cls, path: Path) -> 'RecoveryIdentity':
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise RecoveryError('recovery identity must be a JSON object')
        required = (
            'active_plist', 'baseline_backup', 'candidate_plist', 'evidence_root',
            'label', 'domain', 'baseline_sha256', 'candidate_sha256',
        )
        missing = [key for key in required if not value.get(key)]
        if missing:
            raise RecoveryError('recovery identity missing: ' + ', '.join(missing))
        return cls(
            active_plist=Path(value['active_plist']),
            baseline_backup=Path(value['baseline_backup']),
            candidate_plist=Path(value['candidate_plist']),
            evidence_root=Path(value['evidence_root']),
            label=str(value['label']),
            domain=str(value['domain']),
            baseline_sha256=str(value['baseline_sha256']),
            candidate_sha256=str(value['candidate_sha256']),
            guard_path=Path(value.get('guard_path', DEFAULT_GUARD)),
            lsof_path=Path(value.get('lsof_path', '/usr/sbin/lsof')),
        )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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
    baseline = identity.baseline_backup.read_bytes()
    candidate = identity.candidate_plist.read_bytes()
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
    if sha256_file(path) != expected_sha256:
        raise RecoveryError('independent reviewer receipt SHA mismatch')
    value = json.loads(path.read_text(encoding='utf-8'))
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
    scope = value.get('scope')
    if not isinstance(scope, dict):
        raise RecoveryError('independent reviewer candidate scope is missing')
    mismatches = [key for key, expected in expected_scope.items() if key not in scope or scope[key] != expected]
    if mismatches:
        raise RecoveryError('independent reviewer receipt does not match frozen candidate: ' + ', '.join(mismatches))
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


def recover_baseline(identity: RecoveryIdentity, ops: RecoveryOps) -> dict[str, Any]:
    baseline, candidate, baseline_tokens, candidate_tokens = _validate_pins(identity)
    if not identity.active_plist.is_file():
        raise RecoveryError('active plist is missing')
    active = identity.active_plist.read_bytes()
    if active not in (baseline, candidate):
        raise RecoveryError('active plist is neither exact frozen baseline nor exact candidate; refusing recovery')
    status = ops.launchd_status()

    if active == baseline:
        if status is None:
            ops.require_port_free()
            ops.bootstrap()
            loaded = ops.wait_for_baseline(baseline_tokens)
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
    if identity.active_plist.read_bytes() != candidate:
        raise RecoveryError('active plist changed before candidate-to-baseline restore')
    if ops.launchd_status() is not None:
        raise RecoveryError('exact launchd label is not absent before plist restore')
    ops.require_port_free()
    ops.atomic_restore(baseline)
    if identity.active_plist.read_bytes() != baseline:
        raise RecoveryError('baseline plist bytes did not read back after atomic restore')
    if ops.launchd_status() is not None:
        raise RecoveryError('exact launchd label reappeared before baseline bootstrap')
    ops.require_port_free()
    ops.bootstrap()
    loaded = ops.wait_for_baseline(baseline_tokens)
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
        spec = importlib.util.spec_from_file_location('reviewed_api_cutover_guard_r2', self.identity.guard_path)
        if spec is None or spec.loader is None:
            raise RecoveryError('reviewed atomic cutover guard is unavailable')
        guard = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = guard
        spec.loader.exec_module(guard)
        guard.EVIDENCE_ROOT = self.identity.evidence_root
        guard.atomic_write_no_clobber('api', self.identity.active_plist, baseline_bytes, expected_current_sha256=self.identity.candidate_sha256, phase='API_R2_ROLLBACK_RESTORE')

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
    args = parser.parse_args()
    if args.action == 'review-check':
        expected_scope = json.loads(args.expected_scope_json.read_text(encoding='utf-8'))
        value = verify_reviewer_receipt(args.receipt, args.sha256, expected_scope)
        print(json.dumps({'status': 'INDEPENDENT_REVIEW_PASS_FOR_PINNED_CANDIDATE', 'review_identity': value['review_identity']}, ensure_ascii=False, indent=2))
        return 0
    if args.confirm != RECOVER_CONFIRMATION:
        raise RecoveryError('exact r2 recovery confirmation string is required')
    identity = RecoveryIdentity.from_json(args.identity_json)
    result = recover_baseline(identity, SystemRecoveryOps(identity))
    print(json.dumps({**result, 'service_operation_performed': True, 'other_service_touched': False, 'data_root_touched': False, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RecoveryError) as exc:
        print(json.dumps({'status': 'STOP_CANNOT_CONFIRM', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
