from __future__ import annotations

import hashlib
import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path

import api_candidate_recovery as recovery

from api_candidate_recovery import (
    LaunchdStatus,
    RecoveryError,
    RecoveryIdentity,
    SystemRecoveryOps,
    recover_baseline,
    verify_reviewer_receipt,
)


E = Path('/Users/lexi/Desktop/学习/agents调试/V4_A_POOL_SOURCE_FIX_20261008')


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def make_plist(label: str, app_root: str, release_id: str, manifest_sha: str) -> bytes:
    return plistlib.dumps({
        'Label': label,
        'WorkingDirectory': app_root,
        'ProgramArguments': [
            '/usr/bin/env',
            f'V35_APP_ROOT={app_root}',
            f'V35_RELEASE_ID={release_id}',
            f'V35_RELEASE_MANIFEST_SHA256={manifest_sha}',
            '/python', '-B', '-m', 'apps.api.v35_api.run', '--port', '8873',
        ],
    })


class FakeOps:
    def __init__(self, identity: RecoveryIdentity, initial_status: LaunchdStatus | None, *, port_free: bool = True, bootout_error_after_absence: bool = False) -> None:
        self.identity = identity
        self.status = initial_status
        self.port_free = port_free
        self.bootout_error_after_absence = bootout_error_after_absence
        self.calls: list[str] = []
        base = plistlib.loads(identity.baseline_backup.read_bytes())
        self.base_tokens = (base['ProgramArguments'][1].split('=', 1)[1], base['ProgramArguments'][2].split('=', 1)[1], base['ProgramArguments'][3].split('=', 1)[1])

    def launchd_status(self) -> LaunchdStatus | None:
        self.calls.append('status')
        return self.status

    def require_port_free(self) -> None:
        self.calls.append('port_free')
        if not self.port_free:
            raise RecoveryError('port 8873 is occupied')

    def bootout(self) -> None:
        self.calls.append('bootout')
        self.status = None
        if self.bootout_error_after_absence:
            raise RecoveryError('simulated bootout error after exact label disappearance')

    def wait_for_absence(self, owner_tokens: tuple[str, str, str]) -> None:
        self.calls.append('wait_absent')
        if self.status is not None:
            raise RecoveryError('fake label did not become absent')

    def atomic_restore(self, baseline_bytes: bytes) -> None:
        self.calls.append('atomic_restore')
        if self.identity.active_plist.read_bytes() != self.identity.candidate_plist.read_bytes():
            raise RecoveryError('active plist changed before fake CAS restore')
        self.identity.active_plist.write_bytes(baseline_bytes)

    def bootstrap(self) -> None:
        self.calls.append('bootstrap')
        self.status = LaunchdStatus(pid=777, state='running', output='pid = 777\n' + '\n'.join(self.base_tokens))

    def wait_for_baseline(self, baseline_tokens: tuple[str, str, str]) -> dict:
        self.calls.append('wait_baseline')
        if self.status is None or self.status.pid <= 0 or any(token not in self.status.output for token in baseline_tokens):
            raise RecoveryError('fake baseline process identity mismatch')
        return {'pid': self.status.pid, 'release_id': baseline_tokens[1]}


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix='api-r2-recovery-', dir=E)
        self.root = Path(self.temp.name)
        self.active = self.root / 'active.plist'
        self.backup = self.root / 'baseline.plist'
        self.candidate = self.root / 'candidate.plist'
        self.base_raw = make_plist('com.lexi.v35.api-only', '/releases/base/app', 'base-r2', 'b' * 64)
        self.candidate_raw = make_plist('com.lexi.v35.api-only', '/releases/candidate/app', 'candidate-r2', 'c' * 64)
        self.backup.write_bytes(self.base_raw)
        self.candidate.write_bytes(self.candidate_raw)
        self.active.write_bytes(self.base_raw)
        self.identity = RecoveryIdentity(
            active_plist=self.active,
            baseline_backup=self.backup,
            candidate_plist=self.candidate,
            evidence_root=self.root,
            label='com.lexi.v35.api-only',
            domain='gui/501',
            baseline_sha256=sha(self.base_raw),
            candidate_sha256=sha(self.candidate_raw),
        )
        self.base_tokens = ('/releases/base/app', 'base-r2', 'b' * 64)
        self.candidate_tokens = ('/releases/candidate/app', 'candidate-r2', 'c' * 64)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_install_failed_after_bootout_restores_baseline_service_without_plist_swap(self) -> None:
        ops = FakeOps(self.identity, None)
        result = recover_baseline(self.identity, ops)
        self.assertEqual(result['status'], 'BASELINE_REBOOTSTRAPPED')
        self.assertEqual(self.active.read_bytes(), self.base_raw)
        self.assertNotIn('atomic_restore', ops.calls)
        self.assertEqual(ops.calls.count('bootstrap'), 1)

    def test_candidate_with_exact_absent_label_restores_and_bootstraps_baseline(self) -> None:
        self.active.write_bytes(self.candidate_raw)
        ops = FakeOps(self.identity, None)
        result = recover_baseline(self.identity, ops)
        self.assertEqual(result['status'], 'CANDIDATE_ROLLED_BACK_BASELINE_BOOTSTRAPPED')
        self.assertEqual(self.active.read_bytes(), self.base_raw)
        self.assertNotIn('bootout', ops.calls)
        self.assertIn('atomic_restore', ops.calls)
        self.assertIn('bootstrap', ops.calls)

    def test_candidate_waiting_pid_zero_is_recovered(self) -> None:
        self.active.write_bytes(self.candidate_raw)
        ops = FakeOps(self.identity, LaunchdStatus(pid=0, state='waiting', output='state = waiting\npid = 0'))
        result = recover_baseline(self.identity, ops)
        self.assertEqual(result['status'], 'CANDIDATE_ROLLED_BACK_BASELINE_BOOTSTRAPPED')
        self.assertLess(ops.calls.index('bootout'), ops.calls.index('atomic_restore'))

    def test_candidate_bootout_error_after_exact_label_disappears_continues_recovery(self) -> None:
        self.active.write_bytes(self.candidate_raw)
        ops = FakeOps(self.identity, LaunchdStatus(pid=0, state='waiting', output='state = waiting\npid = 0'), bootout_error_after_absence=True)
        result = recover_baseline(self.identity, ops)
        self.assertEqual(result['status'], 'CANDIDATE_ROLLED_BACK_BASELINE_BOOTSTRAPPED')
        self.assertEqual(self.active.read_bytes(), self.base_raw)

    def test_positive_pid_identity_drift_stops_before_bootout_or_restore(self) -> None:
        self.active.write_bytes(self.candidate_raw)
        ops = FakeOps(self.identity, LaunchdStatus(pid=123, state='running', output='pid = 123\n/external/app\nother-release'))
        with self.assertRaisesRegex(RecoveryError, 'positive launchd PID identity drift'):
            recover_baseline(self.identity, ops)
        self.assertNotIn('bootout', ops.calls)
        self.assertNotIn('atomic_restore', ops.calls)
        self.assertEqual(self.active.read_bytes(), self.candidate_raw)

    def test_baseline_positive_pid_identity_drift_stops(self) -> None:
        ops = FakeOps(self.identity, LaunchdStatus(pid=123, state='running', output='pid = 123\n/external/app\nother-release'))
        with self.assertRaisesRegex(RecoveryError, 'positive launchd PID identity drift'):
            recover_baseline(self.identity, ops)
        self.assertNotIn('bootstrap', ops.calls)

    def test_candidate_restore_refuses_busy_port(self) -> None:
        self.active.write_bytes(self.candidate_raw)
        ops = FakeOps(self.identity, None, port_free=False)
        with self.assertRaisesRegex(RecoveryError, 'port 8873 is occupied'):
            recover_baseline(self.identity, ops)
        self.assertNotIn('atomic_restore', ops.calls)
        self.assertNotIn('bootstrap', ops.calls)

    def test_lsof_rc_zero_empty_output_is_not_treated_as_free(self) -> None:
        ops = SystemRecoveryOps(self.identity, runner=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, '', ''))
        with self.assertRaisesRegex(RecoveryError, 'cannot prove port 8873 is free'):
            ops.require_port_free()

    def test_lsof_rc_one_empty_output_is_free(self) -> None:
        ops = SystemRecoveryOps(self.identity, runner=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, '', ''))
        ops.require_port_free()

    def test_lsof_rc_one_with_error_output_is_not_free(self) -> None:
        ops = SystemRecoveryOps(self.identity, runner=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, '', 'permission denied'))
        with self.assertRaisesRegex(RecoveryError, 'cannot prove port 8873 is free'):
            ops.require_port_free()

    def test_current_failed_r1_review_receipt_cannot_authorize_candidate(self) -> None:
        path = E / '全证据/api_candidate_review_receipt.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        with self.assertRaisesRegex(RecoveryError, 'formal REVIEWED=PASS'):
            verify_reviewer_receipt(path, sha(path.read_bytes()), value['scope'])

    def test_passing_review_must_match_frozen_candidate_scope(self) -> None:
        path = self.root / 'review.json'
        expected_scope = {
            'candidate_manifest_sha256': 'a' * 64,
            'staged_plist_sha256': 'b' * 64,
            'guard_path': str(recovery.DEFAULT_GUARD),
            'guard_sha256': recovery.REVIEWED_GUARD_SHA256,
        }
        value = {
            'review_identity': 'independent_read_only_reviewer',
            'scope': dict(expected_scope),
            'status': {'REVIEWED': 'PASS', 'BEHAVIOR_VERIFIED': 'PASS_ISOLATED_CANARY', 'DEPLOYABLE': 'READY'},
            'findings': {'P0': [], 'P1': [], 'P2': ['documented coverage gap']},
        }
        raw = (json.dumps(value, sort_keys=True) + '\n').encode()
        path.write_bytes(raw)
        passed = verify_reviewer_receipt(path, sha(raw), expected_scope)
        self.assertEqual(passed['status']['REVIEWED'], 'PASS')
        with self.assertRaisesRegex(RecoveryError, 'does not match frozen candidate'):
            verify_reviewer_receipt(path, sha(raw), {
                **expected_scope,
                'candidate_manifest_sha256': 'c' * 64,
            })

    def test_incomplete_findings_dictionary_is_rejected(self) -> None:
        path = self.root / 'review.json'
        scope = {'candidate_manifest_sha256': 'a' * 64, 'staged_plist_sha256': 'b' * 64}
        for severity in ('P0', 'P1', 'P2'):
            value = {
                'review_identity': 'independent_read_only_reviewer',
                'scope': scope,
                'status': {'REVIEWED': 'PASS', 'BEHAVIOR_VERIFIED': 'PASS_ISOLATED_CANARY', 'DEPLOYABLE': 'READY'},
                'findings': {'P0': [], 'P1': [], 'P2': []},
            }
            del value['findings'][severity]
            raw = (json.dumps(value, sort_keys=True) + '\n').encode()
            path.write_bytes(raw)
            with self.subTest(missing=severity), self.assertRaisesRegex(RecoveryError, 'complete P0/P1/P2'):
                verify_reviewer_receipt(path, sha(raw), scope)

    def test_nonempty_p0_or_p1_findings_is_rejected(self) -> None:
        path = self.root / 'review.json'
        scope = {'candidate_manifest_sha256': 'a' * 64, 'staged_plist_sha256': 'b' * 64}
        for severity in ('P0', 'P1'):
            value = {
                'review_identity': 'independent_read_only_reviewer',
                'scope': scope,
                'status': {'REVIEWED': 'PASS', 'BEHAVIOR_VERIFIED': 'PASS_ISOLATED_CANARY', 'DEPLOYABLE': 'READY'},
                'findings': {'P0': [], 'P1': [], 'P2': []},
            }
            value['findings'][severity] = [{'id': 'open finding'}]
            raw = (json.dumps(value, sort_keys=True) + '\n').encode()
            path.write_bytes(raw)
            with self.subTest(severity=severity), self.assertRaisesRegex(RecoveryError, f'reported {severity} findings'):
                verify_reviewer_receipt(path, sha(raw), scope)

    def test_missing_or_unknown_deployable_status_is_rejected(self) -> None:
        path = self.root / 'review.json'
        scope = {'candidate_manifest_sha256': 'a' * 64, 'staged_plist_sha256': 'b' * 64}
        for deployable in (None, 'NOT_DEPLOYABLE', 'MAYBE_READY'):
            value = {
                'review_identity': 'independent_read_only_reviewer',
                'scope': scope,
                'status': {'REVIEWED': 'PASS', 'BEHAVIOR_VERIFIED': 'PASS_ISOLATED_CANARY'},
                'findings': {'P0': [], 'P1': [], 'P2': []},
            }
            if deployable is not None:
                value['status']['DEPLOYABLE'] = deployable
            raw = (json.dumps(value, sort_keys=True) + '\n').encode()
            path.write_bytes(raw)
            with self.subTest(deployable=deployable), self.assertRaisesRegex(RecoveryError, 'DEPLOYABLE status is not explicitly allowed'):
                verify_reviewer_receipt(path, sha(raw), scope)

    def test_empty_expected_scope_is_rejected(self) -> None:
        path = self.root / 'review.json'
        value = {
            'review_identity': 'independent_read_only_reviewer',
            'scope': {},
            'status': {'REVIEWED': 'PASS', 'BEHAVIOR_VERIFIED': 'PASS_ISOLATED_CANARY', 'DEPLOYABLE': 'READY'},
            'findings': {'P0': [], 'P1': [], 'P2': []},
        }
        raw = (json.dumps(value, sort_keys=True) + '\n').encode()
        path.write_bytes(raw)
        with self.assertRaisesRegex(RecoveryError, 'nonempty frozen candidate scope'):
            verify_reviewer_receipt(path, sha(raw), {})

    def test_frozen_scope_requires_nonempty_candidate_identity_pins(self) -> None:
        path = self.root / 'review.json'
        value = {
            'review_identity': 'independent_read_only_reviewer',
            'scope': {'candidate_manifest_sha256': 'a' * 64, 'staged_plist_sha256': 'b' * 64},
            'status': {'REVIEWED': 'PASS', 'BEHAVIOR_VERIFIED': 'PASS_ISOLATED_CANARY', 'DEPLOYABLE': 'READY'},
            'findings': {'P0': [], 'P1': [], 'P2': []},
        }
        raw = (json.dumps(value, sort_keys=True) + '\n').encode()
        path.write_bytes(raw)
        for expected_scope in (
            {'candidate_manifest_sha256': 'a' * 64},
            {'candidate_manifest_sha256': ' ', 'staged_plist_sha256': 'b' * 64},
            {'candidate_manifest_sha256': 'a' * 64, 'staged_plist_sha256': ''},
        ):
            with self.subTest(expected_scope=expected_scope), self.assertRaisesRegex(RecoveryError, 'candidate identity pins'):
                verify_reviewer_receipt(path, sha(raw), expected_scope)


if __name__ == '__main__':
    unittest.main()
