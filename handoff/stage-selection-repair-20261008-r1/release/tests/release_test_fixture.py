"""Synthetic package for the supplied 17+9 unit tests; never a deploy package.

All PASS/READY receipt strings here are parser fixtures. The context is removed
when the test finishes; it contains no real business data or host configuration.
"""
from __future__ import annotations

import contextlib
import difflib
import hashlib
import json
import plistlib
import shutil
from pathlib import Path
from unittest.mock import patch


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


@contextlib.contextmanager
def synthetic_package(install, source_root, root):
    r2 = root / 'synthetic-r2'
    r2.mkdir()
    base = root / 'synthetic-r3'
    candidate = root / 'synthetic-candidate'
    for path in (base, candidate):
        (path / 'app/apps/api/v35_api').mkdir(parents=True)
        (path / 'app/v4/manager_research').mkdir(parents=True)
        (path / 'app/v4/manager_research/announcement_analysis.py').write_text('# unchanged synthetic manager\n')
    old = 'first = "old"\n' + '# fixture context\n' * 20 + 'second = "old"\n'
    new = old.replace('"old"', '"new"')
    (base / 'app/apps/api/v35_api/app.py').write_text(old)
    (candidate / 'app/apps/api/v35_api/app.py').write_text(new)
    mapping = {
        'E': root, 'R2': r2, 'R3': base, 'CANDIDATE': candidate,
        'ACTIVE': root / 'active.plist', 'BASELINE': r2 / 'baseline.plist',
        'IDENTITY': r2 / 'identity.json', 'STAGED': r2 / 'candidate.plist',
        'CANARY': r2 / 'canary.json', 'SOURCE_MAP': r2 / 'source-map.json',
        'SOURCE_DIFF': r2 / 'source.diff', 'PLAN': r2 / 'plan.json',
        'REVIEW_SCOPE': r2 / 'scope.json',
        'RECOVERY': source_root / 'blocked_candidate_ops/api_candidate_recovery.py',
        'RECOVERY_TESTS': source_root / 'blocked_candidate_ops/test_api_candidate_recovery.py',
        'CANARY_SCRIPT': r2 / 'canary.py', 'GATE_RECEIPT': r2 / 'gate.json',
        'GUARD': source_root / 'external_guard_reference/hk_calendar_candidate_cutover.py',
    }
    expected = dict(install.EXPECTED)
    expected['manager_binding_path'] = str(root / 'synthetic-manager-binding.json')
    write_json(Path(expected['manager_binding_path']), {'synthetic_fixture': True})
    mapping['SOURCE_DIFF'].write_text(''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile='before.py', tofile='after.py')))
    write_json(mapping['SOURCE_MAP'], {'synthetic_fixture': True})
    mapping['CANARY_SCRIPT'].write_text('# synthetic hash-only canary fixture; never executed\n')
    write_json(mapping['GATE_RECEIPT'], {'status': {'REVIEWED': 'PASS'}, 'synthetic_fixture': True})
    write_json(base / 'release-manifest.json', {'synthetic_fixture': True, 'version': 'base'})
    expected.update(
        active_manifest_sha256=sha(base / 'release-manifest.json'),
        active_app_sha256=sha(base / 'app/apps/api/v35_api/app.py'),
        candidate_app_sha256=sha(candidate / 'app/apps/api/v35_api/app.py'),
        manager_code_sha256=sha(base / 'app/v4/manager_research/announcement_analysis.py'),
        manager_binding_sha256=sha(Path(expected['manager_binding_path'])),
        source_diff_sha256=sha(mapping['SOURCE_DIFF']), source_map_sha256=sha(mapping['SOURCE_MAP']),
        gate_receipt_sha256=sha(mapping['GATE_RECEIPT']),
    )
    rows = install.inventory(candidate / 'app')
    aggregate = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    write_json(candidate / 'release-manifest.json', {
        'synthetic_fixture': True,
        'candidate_status': 'READY_FOR_INDEPENDENT_REVIEW', 'activation_status': 'NOT_ACTIVATED',
        'deployment_status': 'NOT_DEPLOYED',
        'safety': {'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False},
        'candidate': {'release_id': expected['release_id'], 'app_root': str(candidate / 'app')},
        'source': {'a_pool_preselection_source_fix': {
            'base_manifest_sha256': expected['active_manifest_sha256'],
            'base_sha256': expected['active_app_sha256'], 'result_sha256': expected['candidate_app_sha256'],
            'patch_sha256': expected['source_diff_sha256'], 'hunks': 2,
            'changed_app_paths': ['apps/api/v35_api/app.py'], 'review_status': 'PENDING_INDEPENDENT_REVIEW',
        }},
        'application_inventory': {'entries': rows, 'aggregate_sha256': aggregate},
    })
    expected['candidate_manifest_sha256'] = sha(candidate / 'release-manifest.json')
    for output, release, release_id, manifest_sha in (
        (mapping['BASELINE'], base, 'manager-daily-chain-20261008-r3-api', expected['active_manifest_sha256']),
        (mapping['STAGED'], candidate, expected['release_id'], expected['candidate_manifest_sha256']),
    ):
        env = {
            'V35_APP_ROOT': str(release / 'app'), 'V35_RELEASE_ID': release_id,
            'PYTHONPATH': str(release / 'app'),
            'V35_RELEASE_MANIFEST_PATH': str(release / 'release-manifest.json'),
            'V35_RELEASE_MANIFEST_SHA256': manifest_sha,
            'V4_MANAGER_PLAN_OWNER_BINDING_PATH': expected['manager_binding_path'],
            **{key: 'false' for key in ('production_allowed', 'PRODUCTION_ALLOWED', 'buy_gate_updated', 'BUY_GATE_UPDATED', 'orders_sent', 'ORDERS_SENT')},
        }
        output.write_bytes(plistlib.dumps({'Label': 'com.lexi.v35.api-only',
            'WorkingDirectory': str(release / 'app'),
            'ProgramArguments': ['/usr/bin/env', *(f'{key}={value}' for key, value in env.items()), '/python', '-B', '-m', 'apps.api.v35_api.run'],
        }))
    mapping['ACTIVE'].write_bytes(mapping['BASELINE'].read_bytes())
    expected['active_plist_sha256'], expected['candidate_plist_sha256'] = sha(mapping['BASELINE']), sha(mapping['STAGED'])
    write_json(mapping['IDENTITY'], {
        'active_plist': str(mapping['ACTIVE']), 'baseline_backup': str(mapping['BASELINE']),
        'candidate_plist': str(mapping['STAGED']), 'evidence_root': str(r2),
        'label': 'com.lexi.v35.api-only', 'domain': 'gui/501',
        'baseline_sha256': expected['active_plist_sha256'], 'candidate_sha256': expected['candidate_plist_sha256'],
        'candidate_manifest_sha256': expected['candidate_manifest_sha256'],
        'guard_path': str(mapping['GUARD']), 'guard_sha256': sha(mapping['GUARD']),
    })
    expected['candidate_id_sha256'] = sha(mapping['IDENTITY'])
    write_json(mapping['CANARY'], {
        'synthetic_fixture': True, 'status': 'PASS_ISOLATED_CANDIDATE_API_CANARY',
        'observed': {'synthetic_rows': 1}, 'oracle': {'synthetic_rows': 1},
        'candidate': {'manifest_sha256': expected['candidate_manifest_sha256']},
    })
    expected['candidate_canary_sha256'] = sha(mapping['CANARY'])
    shutil.copyfile(source_root / 'blocked_candidate_ops/test_api_candidate_install_r2.py', r2 / 'test_api_candidate_install_r2.py')
    writer = {'install_helper_sha256': sha(Path(install.__file__)),
              'recovery_helper_sha256': sha(mapping['RECOVERY']),
              'install_tests_sha256': sha(r2 / 'test_api_candidate_install_r2.py')}
    guard_scope = ({'guard_path': str(mapping['GUARD']), 'guard_sha256': sha(mapping['GUARD'])}
                   if 'guard_sha256' in expected else {})
    write_json(mapping['PLAN'], {
        'plan_status': 'READY_FOR_INDEPENDENT_REVIEW',
        'candidate': {'manifest_sha256': expected['candidate_manifest_sha256']},
        'writer_artifacts': {**writer, **guard_scope},
    })
    scope = {
        'plan_sha256': sha(mapping['PLAN']), **writer, **guard_scope,
        'recovery_tests_sha256': sha(mapping['RECOVERY_TESTS']),
        'canary_script_sha256': sha(mapping['CANARY_SCRIPT']), 'canary_receipt_sha256': sha(mapping['CANARY']),
        'candidate_manifest_sha256': expected['candidate_manifest_sha256'],
        'candidate_app_sha256': expected['candidate_app_sha256'], 'candidate_app_inventory_sha256': aggregate,
        'staged_plist_sha256': expected['candidate_plist_sha256'], 'recovery_identity_sha256': sha(mapping['IDENTITY']),
        'baseline_plist_sha256': expected['active_plist_sha256'], 'baseline_manifest_sha256': expected['active_manifest_sha256'],
        'source_diff_sha256': expected['source_diff_sha256'], 'source_map_sha256': expected['source_map_sha256'],
        'r2_gate_reviewer_receipt_sha256': expected['gate_receipt_sha256'],
        'manager_source_sha256': expected['manager_code_sha256'], 'manager_binding_sha256': expected['manager_binding_sha256'],
    }
    write_json(mapping['REVIEW_SCOPE'], scope)
    write_json(root / '全证据/api_candidate_review_receipt.json', {
        'synthetic_fixture': True, 'status': {'REVIEWED': 'FAIL'}, 'scope': scope,
    })
    with patch.multiple(install, **mapping), patch.object(install, 'EXPECTED', expected):
        yield scope
