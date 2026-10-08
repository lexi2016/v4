"""Independent-review regression: no unverified recovery-helper execution.

RELEASE_INSTALLER_SOURCE can select the rejected first candidate for red tests.
All files, marker side effects, and package fixtures are temporary. No services.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_release_regressions as common
from run_original_suites import InstallFixture, load_module


class RecoveryLoadOrderTests(unittest.TestCase):
    def setUp(self):
        temp_root = common.TEST_ROOT / 'tmp'
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='recovery-load-order-', dir=temp_root)
        self.root = Path(self.temp.name).resolve()
        source = Path(os.environ.get('RELEASE_INSTALLER_SOURCE', common.OPS_ROOT / 'api_candidate_install_r2.py')).resolve()
        self.installer = load_module('load_order_installer', source)
        InstallFixture(self.installer, common.recovery, self.root / 'package')
        self.marker = self.root / 'unreviewed-helper-executed'
        self.shadow = self.root / 'shadow'
        self.shadow.mkdir()
        self.bad_helper = self.shadow / 'api_candidate_recovery.py'
        self.bad_helper.write_text(
            'from pathlib import Path\n'
            f'Path({str(self.marker)!r}).write_text("unreviewed top-level code ran")\n'
            'class RecoveryError(RuntimeError): pass\n'
            'def reviewed_guard_bytes(*args): return b""\n'
            'def verify_reviewer_receipt(path, sha, scope):\n'
            '    return {"scope": scope, "review_identity": "unreviewed"}\n'
        )
        self.scope = json.loads(self.installer.REVIEW_SCOPE.read_text())
        self.receipt = self.root / 'review-fixture.json'
        self.receipt.write_text(json.dumps({
            'review_identity': 'pinned-offline-fixture', 'scope': self.scope,
            'status': {'REVIEWED': 'PASS', 'BEHAVIOR_VERIFIED': 'PASS_FIXTURE', 'DEPLOYABLE': 'READY'},
            'findings': {'P0': [], 'P1': [], 'P2': []},
        }))
        self.receipt_sha = common.digest(self.receipt.read_bytes())
        self.subprocess_block = patch('subprocess.run', side_effect=AssertionError('real subprocess/service access is forbidden'))
        self.subprocess_block.start()

    def tearDown(self):
        self.subprocess_block.stop()
        self.temp.cleanup()

    @contextlib.contextmanager
    def shadow_import(self):
        old_module = sys.modules.pop('api_candidate_recovery', None)
        sys.path.insert(0, str(self.shadow))
        try:
            yield
        finally:
            sys.path.remove(str(self.shadow))
            sys.modules.pop('api_candidate_recovery', None)
            if old_module is not None:
                sys.modules['api_candidate_recovery'] = old_module

    def test_review_check_rejects_helper_drift_before_top_level_code(self):
        self.installer.RECOVERY = self.bad_helper
        error = None
        with self.shadow_import():
            try:
                self.installer.verify_review_receipt(self.receipt, self.receipt_sha)
            except Exception as exc:
                error = exc
        self.assertFalse(self.marker.exists(), 'drifted recovery helper executed before its pin rejection')
        self.assertIsInstance(error, self.installer.InstallError)
        self.assertRegex(str(error), 'recovery.*SHA|recovery.*hash')

    def test_package_guard_verification_does_not_import_recovery_helper(self):
        self.installer.RECOVERY = self.bad_helper
        with self.shadow_import():
            result = self.installer.verify_package()
        self.assertEqual(result['status'], 'R2_CANDIDATE_PACKAGE_VERIFY_PASS')
        self.assertFalse(self.marker.exists(), 'raw guard verification imported unverified recovery code')

    def test_direct_receipt_check_also_pins_recovery_helper(self):
        self.installer.RECOVERY = self.bad_helper
        error = None
        with self.shadow_import():
            try:
                self.installer.verify_exact_review_receipt(self.receipt, self.receipt_sha, self.scope)
            except Exception as exc:
                error = exc
        self.assertFalse(self.marker.exists(), 'direct review check executed an unverified helper')
        self.assertIsInstance(error, self.installer.InstallError)

    def test_pinned_helper_path_ignores_import_search_path_and_cache(self):
        with self.shadow_import():
            value = self.installer.verify_exact_review_receipt(self.receipt, self.receipt_sha, self.scope)
        self.assertFalse(self.marker.exists(), 'installer used the unreviewed import-path shadow')
        self.assertEqual(value['review_identity'], 'pinned-offline-fixture')

    def test_helper_path_swap_after_check_executes_only_checked_bytes(self):
        loader = getattr(self.installer, 'import_recovery', None)
        self.assertTrue(callable(loader), 'installer lacks a byte-pinned recovery loader')
        # Copy the reviewed helper to an isolated path; never mutate source.
        helper = self.root / 'checked-helper.py'
        helper.write_bytes(self.installer.RECOVERY.read_bytes())
        self.installer.RECOVERY = helper
        original_reader = self.installer._read_pinned_source
        checked_paths = []
        def replace_after_check(path, expected, name):
            checked = original_reader(path, expected, name)
            checked_paths.append(path)
            path.write_bytes(self.bad_helper.read_bytes())
            return checked
        with patch.object(self.installer, '_read_pinned_source', side_effect=replace_after_check):
            module = loader()
        self.assertEqual(checked_paths, [helper])
        self.assertFalse(self.marker.exists(), 'path replacement after the SHA check executed')
        self.assertEqual(module.REVIEWED_GUARD_SHA256, self.installer.EXPECTED['guard_sha256'])
        with self.assertRaises(self.installer.InstallError):
            loader()
        self.assertFalse(self.marker.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
