"""Run the 9 original install and 17 recovery tests on temporary byte fixtures.

No frozen production package is present in the source slice. This harness
redirects original absolute paths, constructs real minimal plist/manifest files,
and rebinds EXPECTED to those fixture hashes. It never mocks package checks,
guard imports, inventory, CAS, or original behavioral assertions. A synthetic
REVIEWED=FAIL receipt stands in for the unavailable old failed receipt. Candidate
test edits only add newly mandatory guard fields to two passing review scopes.
This is offline code regression, not the old full-package/canary acceptance.
"""
from __future__ import annotations

import dataclasses
import functools
import hashlib
import importlib.util
import json
import os
import plistlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = Path(os.environ.get('RELEASE_SOURCE_ROOT', TEST_ROOT.parent / 'source')).resolve()
OPS_ROOT = SOURCE_ROOT / 'blocked_candidate_ops'
GUARD_SOURCE = SOURCE_ROOT / 'external_guard_reference/hk_calendar_candidate_cutover.py'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    return sha(path)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class InstallFixture:
    def __init__(self, install, recovery, root):
        self.root = root
        r3, candidate, ops = root / 'r3', root / 'candidate', root / 'ops'
        attrs = dict(E=root, R2=ops, R3=r3, CANDIDATE=candidate,
                     ACTIVE=root / 'active.plist', BASELINE=ops / 'baseline.plist',
                     IDENTITY=ops / 'identity.json', STAGED=ops / 'candidate.plist',
                     CANARY=ops / 'canary.json', SOURCE_MAP=ops / 'source-map.json',
                     SOURCE_DIFF=ops / 'source.patch', PLAN=ops / 'plan.json',
                     REVIEW_SCOPE=ops / 'scope.json', RECOVERY=OPS_ROOT / 'api_candidate_recovery.py',
                     RECOVERY_TESTS=OPS_ROOT / 'test_api_candidate_recovery.py',
                     CANARY_SCRIPT=ops / 'canary.py', GATE_RECEIPT=ops / 'gate.json',
                     GUARD=ops / 'hk_calendar_candidate_cutover.py')
        for key, value in attrs.items():
            setattr(install, key, value)
        ops.mkdir(parents=True)
        shutil.copy2(GUARD_SOURCE, install.GUARD)
        shutil.copy2(OPS_ROOT / 'test_api_candidate_install_r2.py', ops / 'test_api_candidate_install_r2.py')
        install.CANARY_SCRIPT.write_text('# Offline fixture; no API server is started.\n')
        manager = 'v4/manager_research/announcement_analysis.py'
        api = 'apps/api/v35_api/app.py'
        for owner, api_bytes in ((r3, b'# original API fixture\n'), (candidate, b'# changed API fixture\n')):
            for relative, raw in ((manager, b'# same manager fixture\n'), (api, api_bytes)):
                path = owner / 'app' / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
        binding = ops / 'manager-binding.json'
        save_json(binding, {'fixture_only': True, 'enabled': False})
        base_manifest = save_json(r3 / 'release-manifest.json', {'fixture_only': True, 'release': 'r3'})
        install.SOURCE_DIFF.write_text('# synthetic two-hunk fixture identity; not a product patch\n')
        save_json(install.SOURCE_MAP, {'fixture_only': True, 'sources': []})
        changed = install.inventory(candidate / 'app')
        inventory_sha = hashlib.sha256(json.dumps(changed, sort_keys=True).encode()).hexdigest()
        candidate_manifest = save_json(candidate / 'release-manifest.json', {
            'fixture_only': True, 'candidate_status': 'READY_FOR_INDEPENDENT_REVIEW',
            'activation_status': 'NOT_ACTIVATED', 'deployment_status': 'NOT_DEPLOYED',
            'safety': {'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False},
            'candidate': {'release_id': install.EXPECTED['release_id'], 'app_root': str(candidate / 'app')},
            'source': {'a_pool_preselection_source_fix': {
                'base_manifest_sha256': base_manifest, 'base_sha256': sha(r3 / 'app' / api),
                'result_sha256': sha(candidate / 'app' / api), 'patch_sha256': sha(install.SOURCE_DIFF),
                'hunks': 2, 'changed_app_paths': [api], 'review_status': 'PENDING_INDEPENDENT_REVIEW'}},
            'application_inventory': {'aggregate_sha256': inventory_sha, 'entries': changed},
        })
        def plist(root, release_id, manifest_sha):
            env = {
                'V35_APP_ROOT': str(root / 'app'), 'V35_RELEASE_ID': release_id,
                'PYTHONPATH': str(root / 'app'),
                'V35_RELEASE_MANIFEST_PATH': str(root / 'release-manifest.json'),
                'V35_RELEASE_MANIFEST_SHA256': manifest_sha,
                'V4_MANAGER_PLAN_OWNER_BINDING_PATH': str(binding),
            }
            env.update({key: 'false' for key in ('production_allowed', 'PRODUCTION_ALLOWED', 'buy_gate_updated', 'BUY_GATE_UPDATED', 'orders_sent', 'ORDERS_SENT')})
            return plistlib.dumps({'Label': install.ACTIVE_LABEL, 'WorkingDirectory': str(root / 'app'),
                                   'ProgramArguments': ['/usr/bin/env'] + [k + '=' + v for k, v in env.items()] + ['python', 'server.py']})
        install.BASELINE.write_bytes(plist(r3, 'manager-daily-chain-20261008-r3-api', base_manifest))
        install.STAGED.write_bytes(plist(candidate, install.EXPECTED['release_id'], candidate_manifest))
        install.ACTIVE.write_bytes(install.BASELINE.read_bytes())
        save_json(install.CANARY, {'fixture_only': True, 'status': 'PASS_ISOLATED_CANDIDATE_API_CANARY',
                                'observed': {'fixture_rows': 1}, 'oracle': {'fixture_rows': 1},
                                'candidate': {'manifest_sha256': candidate_manifest}})
        save_json(install.GATE_RECEIPT, {'fixture_only': True, 'status': {'REVIEWED': 'PASS'}})
        save_json(install.IDENTITY, {
            'fixture_only': True, 'active_plist': str(install.ACTIVE),
            'baseline_backup': str(install.BASELINE), 'candidate_plist': str(install.STAGED),
            'evidence_root': str(ops), 'label': install.ACTIVE_LABEL, 'domain': install.DOMAIN,
            'baseline_sha256': sha(install.BASELINE), 'candidate_sha256': sha(install.STAGED),
            'candidate_manifest_sha256': candidate_manifest,
            'guard_path': str(install.GUARD), 'guard_sha256': sha(install.GUARD),
        })
        install.EXPECTED.update({
            'active_plist_sha256': sha(install.BASELINE), 'active_manifest_sha256': base_manifest,
            'active_app_sha256': sha(r3 / 'app' / api), 'candidate_manifest_sha256': candidate_manifest,
            'candidate_app_sha256': sha(candidate / 'app' / api), 'candidate_plist_sha256': sha(install.STAGED),
            'candidate_id_sha256': sha(install.IDENTITY), 'candidate_canary_sha256': sha(install.CANARY),
            'source_diff_sha256': sha(install.SOURCE_DIFF), 'source_map_sha256': sha(install.SOURCE_MAP),
            'gate_receipt_sha256': sha(install.GATE_RECEIPT), 'manager_code_sha256': sha(r3 / 'app' / manager),
            'manager_binding_path': str(binding), 'manager_binding_sha256': sha(binding),
        })
        pinned = hasattr(recovery, 'REVIEWED_GUARD_SHA256')
        if pinned:
            assert recovery.REVIEWED_GUARD_SHA256 == sha(install.GUARD)
            assert install.EXPECTED['guard_sha256'] == sha(install.GUARD)
        save_json(install.PLAN, {
            'fixture_only': True, 'plan_status': 'READY_FOR_INDEPENDENT_REVIEW',
            'candidate': {'manifest_sha256': candidate_manifest},
            'writer_artifacts': {'install_helper_sha256': sha(install.__file__),
                                 'recovery_helper_sha256': sha(install.RECOVERY),
                                 'install_tests_sha256': sha(ops / 'test_api_candidate_install_r2.py'),
                                 'guard_path': str(install.GUARD), 'guard_sha256': sha(install.GUARD)},
        })
        scope = {
            'plan_sha256': sha(install.PLAN), 'install_helper_sha256': sha(install.__file__),
            'install_tests_sha256': sha(ops / 'test_api_candidate_install_r2.py'),
            'recovery_helper_sha256': sha(install.RECOVERY), 'recovery_tests_sha256': sha(install.RECOVERY_TESTS),
            'canary_script_sha256': sha(install.CANARY_SCRIPT), 'canary_receipt_sha256': sha(install.CANARY),
            'candidate_manifest_sha256': candidate_manifest, 'candidate_app_sha256': sha(candidate / 'app' / api),
            'candidate_app_inventory_sha256': inventory_sha, 'staged_plist_sha256': sha(install.STAGED),
            'recovery_identity_sha256': sha(install.IDENTITY), 'baseline_plist_sha256': sha(install.BASELINE),
            'baseline_manifest_sha256': base_manifest, 'source_diff_sha256': sha(install.SOURCE_DIFF),
            'source_map_sha256': sha(install.SOURCE_MAP), 'r2_gate_reviewer_receipt_sha256': sha(install.GATE_RECEIPT),
            'manager_source_sha256': sha(r3 / 'app' / manager), 'manager_binding_sha256': sha(binding),
        }
        if pinned:
            scope.update(guard_path=str(install.GUARD), guard_sha256=sha(install.GUARD))
        save_json(install.REVIEW_SCOPE, scope)


def main():
    temp_root = TEST_ROOT / 'tmp'
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='original-release-suites-', dir=temp_root) as temp:
        root = Path(temp).resolve()
        with patch('subprocess.run', side_effect=AssertionError('real subprocess/service access is forbidden')):
            sys.path.insert(0, str(OPS_ROOT))
            recovery = load_module('api_candidate_recovery', OPS_ROOT / 'api_candidate_recovery.py')
            install = load_module('api_candidate_install_r2', OPS_ROOT / 'api_candidate_install_r2.py')
            fixture = InstallFixture(install, recovery, root)
            recovery.DEFAULT_GUARD = install.GUARD
            tests_install = load_module('original_install_tests', OPS_ROOT / 'test_api_candidate_install_r2.py')
            tests_recovery = load_module('original_recovery_tests', OPS_ROOT / 'test_api_candidate_recovery.py')
            tests_recovery.E = root
            guard_fields = {'guard_path': install.GUARD}
            if 'guard_sha256' in {f.name for f in dataclasses.fields(recovery.RecoveryIdentity)}:
                guard_fields['guard_sha256'] = sha(install.GUARD)
            tests_recovery.RecoveryIdentity = functools.partial(recovery.RecoveryIdentity, **guard_fields)
            save_json(root / '全证据/api_candidate_review_receipt.json', {
                'fixture_only': True, 'status': {'REVIEWED': 'FAIL'}, 'scope': {'fixture_only': True},
            })
            suite = unittest.TestSuite([
                unittest.defaultTestLoader.loadTestsFromModule(tests_install),
                unittest.defaultTestLoader.loadTestsFromModule(tests_recovery),
            ])
            result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
