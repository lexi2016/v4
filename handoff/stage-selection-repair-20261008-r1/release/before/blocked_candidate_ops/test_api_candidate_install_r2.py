from __future__ import annotations

import hashlib
import json
import plistlib
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import api_candidate_install_r2 as install


class CandidateInstallTests(unittest.TestCase):
    def test_frozen_r3_to_r2_package_verifies_read_only(self) -> None:
        result = install.verify_package()
        self.assertEqual(result['status'], 'R2_CANDIDATE_PACKAGE_VERIFY_PASS')
        self.assertEqual(result['changed_app_paths_vs_r3'], ['apps/api/v35_api/app.py'])
        self.assertFalse(result['production_allowed'])
        self.assertFalse(result['buy_gate_updated'])
        self.assertFalse(result['orders_sent'])
        self.assertFalse(result['service_operation_performed'])

    def test_staged_plist_only_changes_five_pinned_api_release_values(self) -> None:
        baseline = install.BASELINE.read_bytes()
        candidate = install.STAGED.read_bytes()
        old, new = install.validate_plist_delta(baseline, candidate)
        self.assertEqual(install.plist_env(old)['V35_RELEASE_ID'], 'manager-daily-chain-20261008-r3-api')
        self.assertEqual(install.plist_env(new)['V35_RELEASE_ID'], install.EXPECTED['release_id'])
        self.assertEqual(install.plist_env(new)['V4_MANAGER_PLAN_OWNER_BINDING_PATH'], install.EXPECTED['manager_binding_path'])

    def test_unexpected_plist_environment_change_is_rejected(self) -> None:
        value = plistlib.loads(install.STAGED.read_bytes())
        args = list(value['ProgramArguments'])
        args.insert(1, 'EXTRA_UNAPPROVED_ROOT=/tmp/other')
        value['ProgramArguments'] = args
        candidate = plistlib.dumps(value, fmt=plistlib.FMT_XML, sort_keys=False)
        with self.assertRaisesRegex(install.InstallError, 'unexpected candidate plist environment delta'):
            install.validate_plist_delta(install.BASELINE.read_bytes(), candidate)

    def test_duplicate_identity_environment_key_is_rejected(self) -> None:
        value = plistlib.loads(install.STAGED.read_bytes())
        args = list(value['ProgramArguments'])
        args.insert(1, args[next(i for i, item in enumerate(args) if item.startswith('V35_RELEASE_ID='))])
        value['ProgramArguments'] = args
        candidate = plistlib.dumps(value, fmt=plistlib.FMT_XML, sort_keys=False)
        with self.assertRaisesRegex(install.InstallError, 'occur exactly once'):
            install.validate_plist_delta(install.BASELINE.read_bytes(), candidate)

    def _review_receipt(self, root: Path, scope: dict) -> tuple[Path, str, bytes]:
        value = {
            'review_identity': 'independent_read_only_reviewer',
            'scope': scope,
            'status': {'REVIEWED': 'PASS', 'BEHAVIOR_VERIFIED': 'PASS_ISOLATED_CANDIDATE_API_CANARY', 'DEPLOYABLE': 'READY'},
            'findings': {'P0': [], 'P1': [], 'P2': []},
        }
        raw = (json.dumps(value, sort_keys=True) + '\n').encode()
        path = root / 'review.json'
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest(), raw

    def test_exact_review_scope_and_hash_are_required(self) -> None:
        scope = {
            'candidate_manifest_sha256': 'a' * 64,
            'staged_plist_sha256': 'b' * 64,
            'plan_sha256': 'c' * 64,
            'install_helper_sha256': 'd' * 64,
        }
        with tempfile.TemporaryDirectory(prefix='api-r2-install-', dir=install.R2) as temp:
            path, digest, _ = self._review_receipt(Path(temp), scope)
            self.assertEqual(install.verify_exact_review_receipt(path, digest, scope)['status']['REVIEWED'], 'PASS')
            with self.assertRaisesRegex(install.InstallError, 'SHA mismatch'):
                install.verify_exact_review_receipt(path, '0' * 64, scope)
            wider_path, wider_digest, _ = self._review_receipt(Path(temp), {**scope, 'extra_pin': 'e' * 64})
            with self.assertRaisesRegex(install.InstallError, 'scope is not an exact match'):
                install.verify_exact_review_receipt(wider_path, wider_digest, scope)

    def test_review_gate_rejects_incomplete_or_unready_receipts(self) -> None:
        scope = {'candidate_manifest_sha256': 'a' * 64, 'staged_plist_sha256': 'b' * 64}
        with tempfile.TemporaryDirectory(prefix='api-r2-install-', dir=install.R2) as temp:
            root = Path(temp)
            path, _, _ = self._review_receipt(root, scope)
            value = json.loads(path.read_text())
            del value['findings']['P1']
            raw = (json.dumps(value, sort_keys=True) + '\n').encode()
            path.write_bytes(raw)
            with self.assertRaisesRegex(install.InstallError, 'complete P0/P1/P2'):
                install.verify_exact_review_receipt(path, hashlib.sha256(raw).hexdigest(), scope)
            value['findings'] = {'P0': [], 'P1': [], 'P2': []}
            value['status']['DEPLOYABLE'] = 'NOT_DEPLOYABLE'
            raw = (json.dumps(value, sort_keys=True) + '\n').encode()
            path.write_bytes(raw)
            with self.assertRaisesRegex(install.InstallError, 'DEPLOYABLE status is not explicitly allowed'):
                install.verify_exact_review_receipt(path, hashlib.sha256(raw).hexdigest(), scope)

    def test_frozen_plan_scope_is_exactly_review_checkable(self) -> None:
        scope = json.loads(install.REVIEW_SCOPE.read_text())
        with tempfile.TemporaryDirectory(prefix='api-r2-install-', dir=install.R2) as temp:
            path, digest, _ = self._review_receipt(Path(temp), scope)
            value = install.verify_review_receipt(path, digest)
            self.assertEqual(value['scope'], scope)
            self.assertEqual(value['status']['REVIEWED'], 'PASS')

    def test_install_cannot_start_without_exact_confirmation(self) -> None:
        args = Namespace(confirm='wrong', reviewer_receipt=Path('/missing'), reviewer_sha256='0' * 64)
        with self.assertRaisesRegex(install.InstallError, 'exact R2 install confirmation'):
            install.install(args)

    def test_guarded_cas_self_test_uses_only_temporary_r2_path(self) -> None:
        result = install.self_test_cas()
        self.assertEqual(result['status'], 'R2_CAS_SELF_TEST_PASS')
        self.assertTrue(result['active_or_service_paths_touched'] is False)
        self.assertTrue(result['baseline_claim_preserved'])
        self.assertTrue(result['mode_preserved'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
