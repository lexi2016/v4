"""Offline release-P1 tests. Every filesystem mutation stays in a temp fixture.

RELEASE_SOURCE_ROOT selects the unmodified or candidate source slice. The only
subprocess interface used by recovery is the in-process ServiceRunner below.
"""
from __future__ import annotations

import dataclasses
import errno
import hashlib
import importlib.util
import inspect
import json
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TEST_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = Path(os.environ.get('RELEASE_SOURCE_ROOT', TEST_ROOT.parent / 'source')).resolve()
OPS_ROOT = SOURCE_ROOT / 'blocked_candidate_ops'
GUARD_PATH = SOURCE_ROOT / 'external_guard_reference/hk_calendar_candidate_cutover.py'
sys.path.insert(0, str(OPS_ROOT))
import api_candidate_install_r2 as installer
import api_candidate_recovery as recovery


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_guard():
    spec = importlib.util.spec_from_file_location('release_p1_test_guard', GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def plist(release: str) -> bytes:
    return plistlib.dumps({
        'Label': 'com.lexi.v35.api-only',
        'ProgramArguments': ['/usr/bin/env', f'V35_APP_ROOT=/releases/{release}/app',
                             f'V35_RELEASE_ID={release}',
                             'V35_RELEASE_MANIFEST_SHA256=' + ('b' if release == 'baseline' else 'c') * 64],
    })


class ServiceRunner:
    """Exact protocol fake; no subprocess or service call reaches the host."""
    def __init__(self, fixture):
        self.fixture = fixture
        self.loaded = False
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        target = 'gui/501/com.lexi.v35.api-only'
        if argv == ['/bin/launchctl', 'print', target]:
            if self.loaded:
                return subprocess.CompletedProcess(argv, 0,
                    'state = running\npid = 123\n/releases/baseline/app\nbaseline\n' + 'b' * 64, '')
            return subprocess.CompletedProcess(argv, 113, '',
                'Could not find service "com.lexi.v35.api-only" in domain for user gui: 501')
        if argv == ['/usr/sbin/lsof', '-nP', '-iTCP:8873', '-sTCP:LISTEN']:
            return subprocess.CompletedProcess(argv, 1, '', '')
        if argv == ['/bin/launchctl', 'bootstrap', 'gui/501', str(self.fixture.active)]:
            if self.fixture.active.read_bytes() != self.fixture.baseline_raw:
                raise AssertionError('attempted bootstrap with non-baseline bytes')
            self.loaded = True
            return subprocess.CompletedProcess(argv, 0, '', '')
        raise AssertionError('unexpected service command: ' + repr(argv))


class ReleaseP1Tests(unittest.TestCase):
    def setUp(self):
        temp_root = TEST_ROOT / 'tmp'
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='release-p1-', dir=temp_root)
        self.root = Path(self.temp.name)
        self.active = self.root / 'active.plist'
        self.baseline = self.root / 'baseline.plist'
        self.candidate = self.root / 'candidate.plist'
        self.baseline_raw, self.candidate_raw = plist('baseline'), plist('candidate')
        self.baseline.write_bytes(self.baseline_raw)
        self.candidate.write_bytes(self.candidate_raw)
        self.active.write_bytes(self.baseline_raw)
        self.active.chmod(0o640)
        self.guard = load_guard()
        self.guard.EVIDENCE_ROOT = self.root
        self.runner = ServiceRunner(self)

    def tearDown(self):
        self.temp.cleanup()

    def identity(self, guard_path=GUARD_PATH):
        value = dict(active_plist=self.active, baseline_backup=self.baseline,
                     candidate_plist=self.candidate, evidence_root=self.root,
                     label='com.lexi.v35.api-only', domain='gui/501',
                     baseline_sha256=digest(self.baseline_raw),
                     candidate_sha256=digest(self.candidate_raw), guard_path=guard_path)
        if 'guard_sha256' in {field.name for field in dataclasses.fields(recovery.RecoveryIdentity)}:
            value['guard_sha256'] = digest(GUARD_PATH.read_bytes())
        return recovery.RecoveryIdentity(**value)

    def double_failure(self):
        prior_claims = set(self.root.glob('.active.plist.claim-*/before.plist'))
        with patch.object(self.guard.os, 'link', side_effect=OSError(errno.EIO, 'injected link failure')):
            try:
                self.guard.atomic_write_no_clobber('api', self.active, self.candidate_raw,
                    expected_current_sha256=digest(self.baseline_raw), phase='API_PRESELECTION_R2_INSTALL')
            except Exception as exc:
                error = exc
            else:
                self.fail('injected install/restore double failure was accepted')
        self.assertFalse(os.path.lexists(self.active))
        claims = list(set(self.root.glob('.active.plist.claim-*/before.plist')) - prior_claims)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].read_bytes(), self.baseline_raw)
        return error, claims[0]

    def claim_receipt(self, error):
        details = getattr(error, 'recovery', {})
        self.assertTrue(details.get('claim_receipt_path'),
                        'double link failure did not return its claim path and drift receipt')
        return Path(details['claim_receipt_path']), details['claim_receipt_sha256']

    def recover_claim(self, receipt_path, receipt_sha, *, runner=None):
        identity = self.identity()
        ops = recovery.SystemRecoveryOps(identity, runner=runner or self.runner)
        # Baseline has no receipt interface; exercising it still proves the
        # observed failure is "active plist is missing", not a test TypeError.
        options = {}
        if 'claim_receipt_path' in inspect.signature(recovery.recover_baseline).parameters:
            options = dict(claim_receipt_path=receipt_path, claim_receipt_sha256=receipt_sha)
        return recovery.recover_baseline(identity, ops, **options)

    def test_installer_rejects_guard_drift_before_module_side_effect(self):
        marker = self.root / 'unreviewed-module-ran'
        bad = self.root / 'unreviewed.py'
        bad.write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n')
        with patch.object(installer, 'GUARD', bad), patch.dict(installer.EXPECTED, {'guard_sha256': digest(GUARD_PATH.read_bytes())}):
            try:
                installer.import_guard()
            except installer.InstallError as exc:
                self.assertRegex(str(exc), 'guard.*SHA|guard.*pin')
            else:
                self.fail('installer executed an unpinned external guard')
        self.assertFalse(marker.exists())
        self.assertEqual(self.active.read_bytes(), self.baseline_raw)

    def test_recovery_rejects_guard_drift_before_module_side_effect(self):
        marker = self.root / 'unreviewed-module-ran'
        bad = self.root / 'unreviewed.py'
        bad.write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n'
                       'def atomic_write_no_clobber(*args, **kwargs): pass\n')
        ops = recovery.SystemRecoveryOps(self.identity(bad), runner=self.runner)
        try:
            ops.atomic_restore(self.baseline_raw)
        except recovery.RecoveryError as exc:
            self.assertRegex(str(exc), 'guard.*SHA|guard.*pin')
        else:
            self.fail('recovery executed an unpinned external guard')
        self.assertFalse(marker.exists())
        self.assertEqual(self.active.read_bytes(), self.baseline_raw)

    def test_legacy_recovery_identity_without_guard_pin_is_rejected(self):
        value = {key: str(val) if isinstance(val, Path) else val
                 for key, val in dataclasses.asdict(self.identity()).items()}
        value.pop('guard_sha256', None)
        path = self.root / 'identity.json'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(recovery.RecoveryError, 'guard'):
            recovery.RecoveryIdentity.from_json(path)

    def test_recovery_identity_cannot_approve_a_different_guard_by_rehashing_it(self):
        value = {key: str(val) if isinstance(val, Path) else val
                 for key, val in dataclasses.asdict(self.identity()).items()}
        bad = self.root / 'self-approved-guard.py'
        bad.write_text('raise RuntimeError("must never run")\n')
        value.update(guard_path=str(bad), guard_sha256=digest(bad.read_bytes()))
        path = self.root / 'identity.json'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(recovery.RecoveryError, 'guard'):
            recovery.RecoveryIdentity.from_json(path)

    def test_review_receipt_without_guard_binding_is_rejected(self):
        scope = {'candidate_manifest_sha256': 'a' * 64, 'staged_plist_sha256': 'b' * 64}
        path = self.root / 'old-review.json'
        path.write_text(json.dumps({
            'review_identity': 'offline-fixture-reviewer', 'scope': scope,
            'status': {'REVIEWED': 'PASS', 'BEHAVIOR_VERIFIED': 'PASS_FIXTURE', 'DEPLOYABLE': 'READY'},
            'findings': {'P0': [], 'P1': [], 'P2': []},
        }))
        with self.assertRaisesRegex(recovery.RecoveryError, 'guard'):
            recovery.verify_reviewer_receipt(path, digest(path.read_bytes()), scope)

    def test_double_link_failure_returns_claim_and_bound_drift_receipt(self):
        error, claim = self.double_failure()
        receipt, receipt_sha = self.claim_receipt(error)
        self.assertEqual(digest(receipt.read_bytes()), receipt_sha)
        value = json.loads(receipt.read_text())
        self.assertEqual(value['path'], str(self.active))
        self.assertEqual(value['expected_sha256'], digest(self.baseline_raw))
        self.assertEqual(value['details']['claim_path'], str(claim))
        self.assertEqual(value['details']['claim_sha256'], digest(self.baseline_raw))
        self.assertIn(str(claim), str(error))

    def test_missing_active_recovers_exact_claim_then_bootstraps_baseline(self):
        error, claim = self.double_failure()
        # Give baseline a literal claim receipt too: it must still fail because
        # the recovery state machine refuses a missing active path.
        if not getattr(error, 'recovery', {}):
            receipt = self.root / 'baseline-red-receipt.json'
            receipt.write_text('{}')
            receipt_sha = digest(receipt.read_bytes())
        else:
            receipt, receipt_sha = self.claim_receipt(error)
        try:
            result = self.recover_claim(receipt, receipt_sha)
        except Exception as exc:
            self.fail(f'no usable claim recovery path: {type(exc).__name__}: {exc}')
        self.assertEqual(result['status'], 'CLAIM_RESTORED_BASELINE_BOOTSTRAPPED')
        self.assertEqual(self.active.read_bytes(), self.baseline_raw)
        self.assertEqual(stat.S_IMODE(self.active.stat().st_mode), 0o640)
        self.assertEqual(claim.read_bytes(), self.baseline_raw)
        self.assertTrue(self.runner.loaded)
        self.assertEqual(result['claim_recovery']['claim_path'], str(claim))

    def test_claim_recovery_preserves_intervening_path_and_does_not_bootstrap(self):
        error, claim = self.double_failure()
        receipt, receipt_sha = self.claim_receipt(error)
        real_link = os.link

        def intrude(source, target, *args, **kwargs):
            if Path(target) == self.active:
                self.active.write_bytes(b'parallel-owner')
            return real_link(source, target, *args, **kwargs)

        with patch('os.link', side_effect=intrude):
            with self.assertRaises(recovery.RecoveryError):
                self.recover_claim(receipt, receipt_sha)
        self.assertEqual(self.active.read_bytes(), b'parallel-owner')
        self.assertEqual(claim.read_bytes(), self.baseline_raw)
        self.assertFalse(self.runner.loaded)

    def test_claim_recovery_rejects_modified_receipt_before_service_access(self):
        error, claim = self.double_failure()
        receipt, receipt_sha = self.claim_receipt(error)
        receipt.write_text(receipt.read_text() + ' ')
        with self.assertRaisesRegex(recovery.RecoveryError, 'receipt.*SHA'):
            self.recover_claim(receipt, receipt_sha)
        self.assertFalse(os.path.lexists(self.active))
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(claim.read_bytes(), self.baseline_raw)

    def test_claim_recovery_rejects_drifted_claim_before_service_access(self):
        error, claim = self.double_failure()
        receipt, receipt_sha = self.claim_receipt(error)
        claim.write_bytes(b'not-the-baseline')
        with self.assertRaisesRegex(recovery.RecoveryError, 'claim.*SHA'):
            self.recover_claim(receipt, receipt_sha)
        self.assertFalse(os.path.lexists(self.active))
        self.assertEqual(self.runner.calls, [])

    def test_claim_recovery_rejects_symlink_claim_without_touching_target(self):
        error, claim = self.double_failure()
        receipt, receipt_sha = self.claim_receipt(error)
        claim.unlink()
        claim.symlink_to(self.baseline)
        with self.assertRaises(recovery.RecoveryError):
            self.recover_claim(receipt, receipt_sha)
        self.assertFalse(os.path.lexists(self.active))
        self.assertEqual(self.baseline.read_bytes(), self.baseline_raw)
        self.assertEqual(self.runner.calls, [])

    def test_claim_recovery_rejects_redirected_claim_even_with_rehashed_receipt(self):
        error, claim = self.double_failure()
        receipt, _ = self.claim_receipt(error)
        value = json.loads(receipt.read_text())
        value['details']['claim_path'] = str(self.baseline)
        receipt.write_text(json.dumps(value))
        with self.assertRaisesRegex(recovery.RecoveryError, 'claim.*path|claim.*directory'):
            self.recover_claim(receipt, digest(receipt.read_bytes()))
        self.assertFalse(os.path.lexists(self.active))
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(claim.read_bytes(), self.baseline_raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
