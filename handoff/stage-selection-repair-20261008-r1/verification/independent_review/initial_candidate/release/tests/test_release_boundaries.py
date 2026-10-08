"""Focused boundaries of the two Issue #28 release failures; temp files only."""
from __future__ import annotations

import argparse
import errno
import json
import os
import stat
import unittest
from pathlib import Path
from unittest.mock import patch

import test_release_regressions as common
from run_original_suites import InstallFixture, load_module

recovery, installer, digest = common.recovery, common.installer, common.digest


class ReleaseBoundaryTests(unittest.TestCase):
    setUp = common.ReleaseP1Tests.setUp
    tearDown = common.ReleaseP1Tests.tearDown
    identity = common.ReleaseP1Tests.identity
    double_failure = common.ReleaseP1Tests.double_failure
    claim_receipt = common.ReleaseP1Tests.claim_receipt
    recover_claim = common.ReleaseP1Tests.recover_claim

    def fixture_installer(self):
        module = load_module('boundary_fixture_installer', common.OPS_ROOT / 'api_candidate_install_r2.py')
        InstallFixture(module, recovery, self.root / 'package')
        return module

    def passing_receipt(self, module):
        scope = json.loads(module.REVIEW_SCOPE.read_text())
        path = module.R2 / 'review-fixture.json'
        path.write_text(json.dumps({'review_identity': 'offline-boundary-fixture', 'scope': scope,
            'status': {'REVIEWED': 'PASS', 'BEHAVIOR_VERIFIED': 'PASS_FIXTURE', 'DEPLOYABLE': 'READY'},
            'findings': {'P0': [], 'P1': [], 'P2': []}}))
        return path, digest(path.read_bytes())

    def test_install_plan_requires_guard_path_and_sha(self):
        module = self.fixture_installer()
        receipt, receipt_sha = self.passing_receipt(module)
        self.assertEqual(module.verify_review_receipt(receipt, receipt_sha)['status']['REVIEWED'], 'PASS')
        original = json.loads(module.PLAN.read_text())
        for key in ('guard_path', 'guard_sha256'):
            value = json.loads(json.dumps(original))
            del value['writer_artifacts'][key]
            module.PLAN.write_text(json.dumps(value))
            with self.subTest(key=key), self.assertRaisesRegex(module.InstallError, 'guard'):
                module.verify_review_receipt(receipt, receipt_sha)

    def test_install_identity_requires_same_guard_as_plan(self):
        module = self.fixture_installer()
        original = json.loads(module.IDENTITY.read_text())
        for key, value in (('guard_path', '/unreviewed/guard.py'), ('guard_sha256', '0' * 64)):
            edited = {**original, key: value}
            module.IDENTITY.write_text(json.dumps(edited))
            with self.subTest(key=key), self.assertRaisesRegex(module.InstallError, 'guard'):
                module.verify_package()

    def test_guard_source_replaced_after_sha_check_never_executes_new_bytes(self):
        guard_path = self.root / 'guard.py'
        marker = self.root / 'unreviewed-module-ran'
        raw = common.GUARD_PATH.read_bytes()
        original_reader = recovery.reviewed_guard_bytes
        def replace_after_check(path, expected):
            checked = original_reader(path, expected)
            path.write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("bad")\n')
            return checked
        for owner in ('install', 'recovery'):
            guard_path.write_bytes(raw)
            self.active.write_bytes(self.candidate_raw)
            with self.subTest(owner=owner), patch.object(recovery, 'reviewed_guard_bytes', side_effect=replace_after_check):
                if owner == 'install':
                    with patch.object(installer, 'GUARD', guard_path):
                        loaded = installer.import_guard()
                    self.assertTrue(callable(loaded.atomic_write_no_clobber))
                else:
                    recovery.SystemRecoveryOps(self.identity(guard_path), runner=self.runner).atomic_restore(self.baseline_raw)
                    self.assertEqual(self.active.read_bytes(), self.baseline_raw)
            self.assertFalse(marker.exists())
        self.assertEqual(self.runner.calls, [])

    def test_recovery_guard_drift_stops_before_any_service_query(self):
        guard_path = self.root / 'changed-guard.py'
        guard_path.write_bytes(common.GUARD_PATH.read_bytes() + b'\n# changed\n')
        identity = self.identity(guard_path)
        with self.assertRaisesRegex(recovery.RecoveryError, 'guard.*SHA'):
            recovery.recover_baseline(identity, recovery.SystemRecoveryOps(identity, runner=self.runner))
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.active.read_bytes(), self.baseline_raw)

    def test_installer_rechecks_staged_snapshot_before_cas(self):
        module = self.fixture_installer()
        receipt, receipt_sha = self.passing_receipt(module)
        import_guard = module.import_guard
        def drift_after_package_check():
            guard = import_guard()
            module.STAGED.write_bytes(b'drift-after-package-verification')
            return guard
        args = argparse.Namespace(confirm='INSTALL_API_PRESELECTION_SOURCE_R2_20261008',
                                  reviewer_receipt=receipt, reviewer_sha256=receipt_sha)
        with patch.object(module, 'require_install_slot'), patch.object(module, 'import_guard', side_effect=drift_after_package_check):
            with self.assertRaisesRegex(module.InstallError, 'staged.*SHA drift'):
                module.install(args)
        self.assertEqual(module.ACTIVE.read_bytes(), module.BASELINE.read_bytes())
        self.assertEqual(list(module.ACTIVE.parent.glob('.active.plist.claim-*/before.plist')), [])

    def test_preclaim_receipt_write_failure_preserves_active_path(self):
        with patch.object(self.guard, 'drift', side_effect=OSError(errno.ENOSPC, 'injected receipt failure')):
            with self.assertRaises(OSError):
                self.guard.atomic_write_no_clobber('api', self.active, self.candidate_raw,
                    expected_current_sha256=digest(self.baseline_raw), phase='API_PRESELECTION_R2_INSTALL')
        self.assertEqual(self.active.read_bytes(), self.baseline_raw)
        self.assertEqual(list(self.root.glob('.active.plist.claim-*/before.plist')), [])

    def test_later_receipt_failure_retains_preclaim_recovery_witness(self):
        real_drift = self.guard.drift
        def fail_after_reservation(**kwargs):
            if kwargs['phase'].endswith('_CLAIM_RESERVED'):
                return real_drift(**kwargs)
            raise OSError(errno.ENOSPC, 'injected later receipt failure')
        with patch.object(self.guard, 'drift', side_effect=fail_after_reservation):
            error, claim = self.double_failure()
        receipt, receipt_sha = self.claim_receipt(error)
        self.assertTrue(json.loads(receipt.read_text())['phase'].endswith('_CLAIM_RESERVED'))
        self.assertIn('receipt_error', error.recovery)
        self.assertEqual(self.recover_claim(receipt, receipt_sha)['status'], 'CLAIM_RESTORED_BASELINE_BOOTSTRAPPED')
        self.assertEqual(claim.read_bytes(), self.baseline_raw)

    @unittest.skipUnless(hasattr(os, 'fork'), 'requires POSIX process interruption fixture')
    def test_process_exit_immediately_after_claim_has_recoverable_receipt(self):
        pid = os.fork()
        if pid == 0:
            real_rename = os.rename
            def exit_after_rename(source, target, *args, **kwargs):
                real_rename(source, target, *args, **kwargs)
                os._exit(73)
            try:
                with patch.object(self.guard.os, 'rename', side_effect=exit_after_rename):
                    self.guard.atomic_write_no_clobber('api', self.active, self.candidate_raw,
                        expected_current_sha256=digest(self.baseline_raw), phase='API_PRESELECTION_R2_INSTALL')
            except BaseException:
                os._exit(74)
            os._exit(75)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 73)
        self.assertFalse(os.path.lexists(self.active))
        receipts = list(self.root.glob('cutover-drift-api-*.json'))
        self.assertEqual(len(receipts), 1)
        receipt = receipts[0]
        value = json.loads(receipt.read_text())
        self.assertTrue(value['phase'].endswith('_CLAIM_RESERVED'))
        claim = Path(value['details']['claim_path'])
        self.assertEqual(claim.read_bytes(), self.baseline_raw)
        result = self.recover_claim(receipt, digest(receipt.read_bytes()))
        self.assertEqual(result['status'], 'CLAIM_RESTORED_BASELINE_BOOTSTRAPPED')
        self.assertEqual(claim.read_bytes(), self.baseline_raw)

    def test_double_link_failure_during_rollback_recovers_candidate_claim_then_baseline(self):
        self.active.write_bytes(self.candidate_raw)
        with patch.object(self.guard.os, 'link', side_effect=OSError(errno.EIO, 'injected two rollback link failures')):
            with self.assertRaises(self.guard.ClaimRecoveryError) as caught:
                self.guard.atomic_write_no_clobber('api', self.active, self.baseline_raw,
                    expected_current_sha256=digest(self.candidate_raw), phase='API_R2_ROLLBACK_RESTORE')
        receipt, receipt_sha = self.claim_receipt(caught.exception)
        claim = Path(caught.exception.recovery['claim_path'])
        self.assertEqual(claim.read_bytes(), self.candidate_raw)
        self.assertFalse(os.path.lexists(self.active))
        result = self.recover_claim(receipt, receipt_sha)
        self.assertEqual(result['status'], 'CLAIM_RESTORED_BASELINE_BOOTSTRAPPED')
        self.assertEqual(self.active.read_bytes(), self.baseline_raw)
        self.assertEqual(claim.read_bytes(), self.candidate_raw)
        self.assertTrue(self.runner.loaded)

    def test_single_link_failure_restores_original_snapshot_and_mode(self):
        real_link = os.link
        count = 0
        def fail_install(source, target, *args, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                raise OSError(errno.EIO, 'injected candidate link failure')
            return real_link(source, target, *args, **kwargs)
        with patch.object(self.guard.os, 'link', side_effect=fail_install):
            with self.assertRaisesRegex(self.guard.GateError, 'exact original bytes were restored'):
                self.guard.atomic_write_no_clobber('api', self.active, self.candidate_raw,
                    expected_current_sha256=digest(self.baseline_raw), phase='API_PRESELECTION_R2_INSTALL')
        self.assertEqual(count, 2)
        self.assertEqual(self.active.read_bytes(), self.baseline_raw)
        self.assertEqual(stat.S_IMODE(self.active.stat().st_mode), 0o640)

    def test_claim_recovery_rejects_any_existing_path_without_service_access(self):
        error, claim = self.double_failure()
        receipt, receipt_sha = self.claim_receipt(error)
        unrelated = self.root / 'unrelated.plist'
        unrelated.write_bytes(b'unrelated-owner')
        for kind in ('regular', 'symlink', 'dangling_symlink', 'directory'):
            if kind == 'regular':
                self.active.write_bytes(b'parallel-owner')
            elif kind == 'directory':
                self.active.mkdir()
            else:
                self.active.symlink_to(unrelated if kind == 'symlink' else self.root / 'missing-owner')
            before = self.active.lstat()
            with self.subTest(kind=kind), self.assertRaisesRegex(recovery.RecoveryError, 'parallel path preserved'):
                self.recover_claim(receipt, receipt_sha)
            self.assertEqual(self.active.lstat().st_ino, before.st_ino)
            self.assertEqual(unrelated.read_bytes(), b'unrelated-owner')
            self.assertEqual(self.runner.calls, [])
            if kind == 'directory':
                self.active.rmdir()
            else:
                self.active.unlink()
        self.assertEqual(claim.read_bytes(), self.baseline_raw)

    def test_claim_recovery_preserves_a_dangling_symlink_inserted_at_link(self):
        error, claim = self.double_failure()
        receipt, receipt_sha = self.claim_receipt(error)
        real_link = os.link
        foreign = self.root / 'foreign-missing-path'
        def intervene(source, target, *args, **kwargs):
            if Path(target) == self.active:
                self.active.symlink_to(foreign)
            return real_link(source, target, *args, **kwargs)
        with patch('os.link', side_effect=intervene):
            with self.assertRaises(recovery.RecoveryError):
                self.recover_claim(receipt, receipt_sha)
        self.assertTrue(self.active.is_symlink())
        self.assertEqual(os.readlink(self.active), str(foreign))
        self.assertFalse(foreign.exists())
        self.assertFalse(self.runner.loaded)
        self.assertEqual(claim.read_bytes(), self.baseline_raw)

    def test_claim_directory_symlink_is_rejected_before_service_access(self):
        error, claim = self.double_failure()
        receipt, receipt_sha = self.claim_receipt(error)
        original = claim.parent.with_name('retained-original-directory')
        claim.parent.rename(original)
        claim.parent.symlink_to(original, target_is_directory=True)
        with self.assertRaises(recovery.RecoveryError):
            self.recover_claim(receipt, receipt_sha)
        self.assertFalse(os.path.lexists(self.active))
        self.assertEqual((original / 'before.plist').read_bytes(), self.baseline_raw)
        self.assertEqual(self.runner.calls, [])

    def test_claim_fifo_is_rejected_without_blocking(self):
        error, claim = self.double_failure()
        receipt, receipt_sha = self.claim_receipt(error)
        claim.unlink()
        os.mkfifo(claim)
        with self.assertRaisesRegex(recovery.RecoveryError, 'claim.*regular'):
            self.recover_claim(receipt, receipt_sha)
        self.assertFalse(os.path.lexists(self.active))
        self.assertEqual(self.runner.calls, [])

    def test_claim_receipt_wrong_identity_or_path_is_rejected_even_when_rehashed(self):
        error, claim = self.double_failure()
        receipt, _ = self.claim_receipt(error)
        original = json.loads(receipt.read_text())
        for key, replacement in (('service', 'scheduler'), ('path', str(self.root / 'different-active.plist')),
                                 ('phase', 'UNREVIEWED_RECOVERY_PHASE')):
            value = {**original, key: replacement}
            receipt.write_text(json.dumps(value))
            with self.subTest(key=key), self.assertRaises(recovery.RecoveryError):
                self.recover_claim(receipt, digest(receipt.read_bytes()))
            self.assertFalse(os.path.lexists(self.active))
            self.assertEqual(self.runner.calls, [])
        value = json.loads(json.dumps(original))
        value['details']['claim_path'] = str(claim.parent / '..' / claim.parent.name / 'before.plist')
        receipt.write_text(json.dumps(value))
        with self.assertRaises(recovery.RecoveryError):
            self.recover_claim(receipt, digest(receipt.read_bytes()))

    def test_active_symlink_is_rejected_before_claim(self):
        self.active.unlink()
        self.active.symlink_to(self.baseline)
        with self.assertRaises((OSError, self.guard.GateError)):
            self.guard.atomic_write_no_clobber('api', self.active, self.candidate_raw,
                expected_current_sha256=digest(self.baseline_raw), phase='API_PRESELECTION_R2_INSTALL')
        self.assertTrue(self.active.is_symlink())
        self.assertEqual(self.baseline.read_bytes(), self.baseline_raw)
        self.assertEqual(list(self.root.glob('.active.plist.claim-*/before.plist')), [])

    def test_symlink_parent_is_rejected(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(self.guard.GateError, 'symlink parents'):
            self.guard.atomic_write_no_clobber('api', alias / self.active.name, self.candidate_raw,
                expected_current_sha256=digest(self.baseline_raw), phase='API_PRESELECTION_R2_INSTALL')
        self.assertEqual(self.active.read_bytes(), self.baseline_raw)

    def test_intervening_writer_before_claim_is_restored_without_publishing_candidate(self):
        real_rename = os.rename
        def change_then_claim(source, target, *args, **kwargs):
            self.active.write_bytes(b'parallel-owner-before-claim')
            return real_rename(source, target, *args, **kwargs)
        with patch.object(self.guard.os, 'rename', side_effect=change_then_claim):
            with self.assertRaisesRegex(self.guard.GateError, 'invalid claim restored'):
                self.guard.atomic_write_no_clobber('api', self.active, self.candidate_raw,
                    expected_current_sha256=digest(self.baseline_raw), phase='API_PRESELECTION_R2_INSTALL')
        self.assertEqual(self.active.read_bytes(), b'parallel-owner-before-claim')
        self.assertEqual(self.baseline.read_bytes(), self.baseline_raw)

    def test_claim_publication_uses_checked_snapshot_after_source_changes(self):
        error, claim = self.double_failure()
        receipt, receipt_sha = self.claim_receipt(error)
        real_link = os.link
        def change_source_at_publication(source, target, *args, **kwargs):
            claim.write_bytes(b'parallel-mutation-of-retained-source')
            return real_link(source, target, *args, **kwargs)
        with patch('os.link', side_effect=change_source_at_publication):
            result = self.recover_claim(receipt, receipt_sha)
        self.assertEqual(result['status'], 'CLAIM_RESTORED_BASELINE_BOOTSTRAPPED')
        self.assertEqual(self.active.read_bytes(), self.baseline_raw)
        self.assertEqual(claim.read_bytes(), b'parallel-mutation-of-retained-source')

    def test_repeated_failed_attempts_keep_every_claim_and_receipt(self):
        first_error, first_claim = self.double_failure()
        first_receipt, first_sha = self.claim_receipt(first_error)
        self.recover_claim(first_receipt, first_sha)
        self.runner.loaded = False
        second_error, second_claim = self.double_failure()
        second_receipt, second_sha = self.claim_receipt(second_error)
        self.assertNotEqual(first_claim, second_claim)
        self.assertNotEqual(first_receipt, second_receipt)
        self.assertEqual(digest(first_receipt.read_bytes()), first_sha)
        self.assertEqual(digest(second_receipt.read_bytes()), second_sha)
        self.assertEqual(first_claim.read_bytes(), self.baseline_raw)
        self.assertEqual(second_claim.read_bytes(), self.baseline_raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
