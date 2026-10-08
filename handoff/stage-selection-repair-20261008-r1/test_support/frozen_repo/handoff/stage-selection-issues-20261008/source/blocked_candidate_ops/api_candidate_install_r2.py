#!/usr/bin/env python3
"""R3-pinned R2 candidate verifier and guarded API plist CAS installer.

`verify` is read-only. `preflight` is read-only and is intended only after the
exact API launchd label has been stopped. `install` never calls launchctl; it
requires an independently reviewed, hash-pinned exact scope and uses the
reviewed no-clobber plist primitive. Baseline recovery is owned by
api_candidate_recovery.py.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


E = Path('/Users/lexi/Desktop/学习/agents调试/V4_A_POOL_SOURCE_FIX_20261008')
R2 = E / 'r2'
R3 = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r3-api')
CANDIDATE = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-preselection-source-r2-20261008-api')
ACTIVE = Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
BASELINE = R2 / 'r3_active_plist_baseline.plist'
IDENTITY = R2 / 'r2_candidate_identity.json'
STAGED = R2 / 'r2_candidate_api_only.plist'
CANARY = R2 / 'r2_candidate_canary.json'
SOURCE_MAP = E / '全证据/preselection_20261008_source_sha256.json'
SOURCE_DIFF = R2 / 'r2_source_diff.patch'
PLAN = R2 / 'r2_candidate_finalplan.json'
REVIEW_SCOPE = R2 / 'r2_candidate_review_scope.json'
RECOVERY = R2 / 'api_candidate_recovery.py'
RECOVERY_TESTS = R2 / 'test_api_candidate_recovery.py'
CANARY_SCRIPT = R2 / 'r2_candidate_canary.py'
GATE_RECEIPT = R2 / 'r2_gate_reviewer_receipt.json'
GUARD = Path('/Users/lexi/Desktop/学习/agents调试/V4_HK_CLOSE_DAILY_20261007/hk_market_calendar/hk_calendar_candidate_cutover.py')
ACTIVE_LABEL = 'com.lexi.v35.api-only'
DOMAIN = 'gui/501'
ALLOWED_ENV_DELTA = frozenset({
    'V35_APP_ROOT', 'V35_RELEASE_ID', 'PYTHONPATH',
    'V35_RELEASE_MANIFEST_PATH', 'V35_RELEASE_MANIFEST_SHA256',
})
EXPECTED = {
    'active_plist_sha256': '72050bf4c7f00c8271cf9226ea866683a8e9e459d2875547b08f69fad30bfdf5',
    'active_manifest_sha256': '946c49b9c34bd09fbca04644556de3acba1635eb240fa9293f6391e9d46b40e9',
    'active_app_sha256': '90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7',
    'candidate_manifest_sha256': '92b0b97b5900da3f2bcb6537d218a49ea05188bb009237e1d229fca9633d0328',
    'candidate_app_sha256': '435dcedd3beb43bf4a0ccb35ff6fc033ba536a940990c36f5f23358f5492b590',
    'candidate_plist_sha256': '1d1eb54eb88f21109d3639a51f2e42a7e9b9a6988c68a1215ce70fa2fffefea4',
    'candidate_id_sha256': '5adf4e982adb884db09410c97d6e5b7452cc49b682c2b76cd3782670d4c6362b',
    'candidate_canary_sha256': '1d64c77c2d99d9260f5fc72e85174cb02d10bdb1aa02aacb353aeecc12affa48',
    'source_diff_sha256': '2b9fffe209b19353ca03ea7a6fe6154acfde1cdaccaada1641963ee3d205b2cc',
    'source_map_sha256': '7dd0c78ea60f188f2deea09a7bbc62d2fb1435f70934b020d24e6608fc469382',
    'gate_receipt_sha256': 'b3ca3da42baec0ded8cd5b0d46750e7364a23124706a290af83459896547f7b0',
    'manager_code_sha256': 'b60b8c0c663b203d2ece5a5b451eb41ca296396b2db3630dff4a92a8566f373f',
    'manager_binding_sha256': 'f3b7cbfa1709b2b27816d294e599cb1ae82ff918ba41ec148644f1a1751f5fd6',
    'release_id': 'a-preselection-source-r2-20261008-api',
    'manager_binding_path': '/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/staged_config/manager-plan-binding-c1.disabled.final-d1-r2.json',
}


class InstallError(RuntimeError):
    pass


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise InstallError(f'expected JSON object: {path}')
    return value


def inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        files.sort()
        kept: list[str] = []
        for name in dirs:
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                rows.append({'path': rel, 'kind': 'symlink', 'target': os.readlink(path), 'target_exists': path.exists()})
            else:
                kept.append(name)
        dirs[:] = kept
        for name in files:
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                rows.append({'path': rel, 'kind': 'symlink', 'target': os.readlink(path), 'target_exists': path.exists()})
            elif stat.S_ISREG(mode):
                rows.append({'path': rel, 'kind': 'file', 'sha256': sha(path), 'mode': f'{stat.S_IMODE(mode):04o}', 'size': path.stat().st_size})
            else:
                raise InstallError(f'unsupported inventory entry: {path}')
    return sorted(rows, key=lambda row: row['path'])


def plist_env(value: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in value.get('ProgramArguments', []):
        if isinstance(item, str) and '=' in item:
            key, data = item.split('=', 1)
            out[key] = data
    for key, data in (value.get('EnvironmentVariables') or {}).items():
        if isinstance(key, str) and isinstance(data, (str, int, float, bool)):
            out[key] = str(data)
    return out


def env_occurrences(value: dict[str, Any]) -> dict[str, int]:
    keys = set()
    for item in value.get('ProgramArguments', []):
        if isinstance(item, str) and '=' in item:
            keys.add(item.split('=', 1)[0])
    keys.update((value.get('EnvironmentVariables') or {}).keys())
    counts: dict[str, int] = {}
    for key in keys:
        counts[key] = sum(
            isinstance(item, str) and item.startswith(str(key) + '=')
            for item in value.get('ProgramArguments', [])
        ) + int(key in (value.get('EnvironmentVariables') or {}))
    return counts


def validate_plist_delta(baseline_raw: bytes, candidate_raw: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline = plistlib.loads(baseline_raw)
    candidate = plistlib.loads(candidate_raw)
    if baseline.get('Label') != ACTIVE_LABEL or candidate.get('Label') != ACTIVE_LABEL:
        raise InstallError('API plist label mismatch')
    baseline_env, candidate_env = plist_env(baseline), plist_env(candidate)
    changed = {key for key in baseline_env.keys() | candidate_env.keys() if baseline_env.get(key) != candidate_env.get(key)}
    if changed != ALLOWED_ENV_DELTA:
        raise InstallError('unexpected candidate plist environment delta: ' + repr(sorted(changed)))
    for key in ALLOWED_ENV_DELTA:
        if env_occurrences(baseline).get(key) != 1 or env_occurrences(candidate).get(key) != 1:
            raise InstallError('candidate plist identity key must occur exactly once: ' + key)
    old_normalized, new_normalized = copy.deepcopy(baseline), copy.deepcopy(candidate)
    for value in (old_normalized, new_normalized):
        args = []
        for item in value.get('ProgramArguments', []):
            if isinstance(item, str) and '=' in item and item.split('=', 1)[0] in ALLOWED_ENV_DELTA:
                key = item.split('=', 1)[0]
                args.append(key + '=<approved>')
            else:
                args.append(item)
        value['ProgramArguments'] = args
        env = value.get('EnvironmentVariables')
        if isinstance(env, dict):
            for key in ALLOWED_ENV_DELTA:
                if key in env:
                    env[key] = '<approved>'
        value['WorkingDirectory'] = '<approved>'
    if old_normalized != new_normalized:
        raise InstallError('candidate plist has a non-approved structural change')
    return baseline, candidate


def verify_package(*, require_active_baseline: bool = True) -> dict[str, Any]:
    identity = load_json(IDENTITY)
    if sha(IDENTITY) != EXPECTED['candidate_id_sha256']:
        raise InstallError('frozen R2 candidate identity SHA drift')
    if sha(BASELINE) != EXPECTED['active_plist_sha256'] or identity.get('baseline_sha256') != EXPECTED['active_plist_sha256']:
        raise InstallError('R3 baseline plist pin drift')
    manifest_path = CANDIDATE / 'release-manifest.json'
    app_path = CANDIDATE / 'app/apps/api/v35_api/app.py'
    if sha(manifest_path) != EXPECTED['candidate_manifest_sha256']:
        raise InstallError('candidate manifest SHA drift')
    manifest = load_json(manifest_path)
    if manifest.get('candidate_status') != 'READY_FOR_INDEPENDENT_REVIEW':
        raise InstallError('candidate is not frozen for independent review')
    if manifest.get('activation_status') != 'NOT_ACTIVATED' or manifest.get('deployment_status') != 'NOT_DEPLOYED':
        raise InstallError('candidate is already activated or deployed')
    safety = manifest.get('safety')
    if not isinstance(safety, dict) or safety.get('RESEARCH_ONLY') is not True or any(
        safety.get(key) is not False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent')
    ):
        raise InstallError('candidate manifest safety flags are not false')
    candidate_identity = manifest.get('candidate')
    if not isinstance(candidate_identity, dict) or candidate_identity.get('release_id') != EXPECTED['release_id'] or candidate_identity.get('app_root') != str(CANDIDATE / 'app'):
        raise InstallError('candidate manifest release identity mismatch')
    source_fix = manifest.get('source', {}).get('a_pool_preselection_source_fix')
    if not isinstance(source_fix, dict) or any((
        source_fix.get('base_manifest_sha256') != EXPECTED['active_manifest_sha256'],
        source_fix.get('base_sha256') != EXPECTED['active_app_sha256'],
        source_fix.get('result_sha256') != EXPECTED['candidate_app_sha256'],
        source_fix.get('patch_sha256') != EXPECTED['source_diff_sha256'],
        source_fix.get('hunks') != 2,
        source_fix.get('changed_app_paths') != ['apps/api/v35_api/app.py'],
        source_fix.get('review_status') != 'PENDING_INDEPENDENT_REVIEW',
    )):
        raise InstallError('candidate source overlay metadata mismatch')
    if sha(app_path) != EXPECTED['candidate_app_sha256']:
        raise InstallError('candidate API source SHA drift')
    candidate_rows = inventory(CANDIDATE / 'app')
    if candidate_rows != manifest.get('application_inventory', {}).get('entries'):
        raise InstallError('candidate application inventory differs from manifest')
    base_rows, new_rows = inventory(R3 / 'app'), candidate_rows
    before = {row['path']: row for row in base_rows}
    after = {row['path']: row for row in new_rows}
    changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    if changed != ['apps/api/v35_api/app.py']:
        raise InstallError('candidate app tree has changes beyond the single allowed file: ' + repr(changed))
    if sha(R3 / 'release-manifest.json') != EXPECTED['active_manifest_sha256']:
        raise InstallError('R3 release manifest SHA drift')
    if sha(R3 / 'app/apps/api/v35_api/app.py') != EXPECTED['active_app_sha256']:
        raise InstallError('R3 API source SHA drift')
    if sha(R3 / 'app/v4/manager_research/announcement_analysis.py') != EXPECTED['manager_code_sha256']:
        raise InstallError('R3 manager source SHA drift')
    if sha(Path(EXPECTED['manager_binding_path'])) != EXPECTED['manager_binding_sha256']:
        raise InstallError('manager plan binding SHA drift')
    if sha(SOURCE_DIFF) != EXPECTED['source_diff_sha256'] or sha(SOURCE_MAP) != EXPECTED['source_map_sha256']:
        raise InstallError('candidate source patch or canary input map SHA drift')
    canary = load_json(CANARY)
    if sha(CANARY) != EXPECTED['candidate_canary_sha256'] or canary.get('status') != 'PASS_ISOLATED_CANDIDATE_API_CANARY':
        raise InstallError('candidate isolated API canary receipt drift or not PASS')
    observed = canary.get('observed')
    if not isinstance(observed, dict) or observed != canary.get('oracle'):
        raise InstallError('candidate canary does not match its frozen oracle')
    if canary.get('candidate', {}).get('manifest_sha256') != EXPECTED['candidate_manifest_sha256']:
        raise InstallError('candidate canary manifest binding mismatch')
    gate = load_json(GATE_RECEIPT)
    if sha(GATE_RECEIPT) != EXPECTED['gate_receipt_sha256'] or gate.get('status', {}).get('REVIEWED') != 'PASS':
        raise InstallError('R2 review-gate module independent review receipt failed its pin/status')
    candidate_raw = STAGED.read_bytes()
    if sha_bytes(candidate_raw) != EXPECTED['candidate_plist_sha256']:
        raise InstallError('staged candidate plist SHA drift')
    baseline_plist, candidate_plist = validate_plist_delta(BASELINE.read_bytes(), candidate_raw)
    base_env, candidate_env = plist_env(baseline_plist), plist_env(candidate_plist)
    if candidate_env.get('V35_RELEASE_ID') != EXPECTED['release_id']:
        raise InstallError('staged candidate release ID mismatch')
    if candidate_env.get('V35_APP_ROOT') != str(CANDIDATE / 'app'):
        raise InstallError('staged candidate app root mismatch')
    if candidate_env.get('V35_RELEASE_MANIFEST_PATH') != str(manifest_path) or candidate_env.get('V35_RELEASE_MANIFEST_SHA256') != EXPECTED['candidate_manifest_sha256']:
        raise InstallError('staged candidate manifest binding mismatch')
    for key in ('production_allowed', 'PRODUCTION_ALLOWED', 'buy_gate_updated', 'BUY_GATE_UPDATED', 'orders_sent', 'ORDERS_SENT'):
        if candidate_env.get(key) != 'false':
            raise InstallError('staged candidate safety pin changed: ' + key)
    if candidate_env.get('V4_MANAGER_PLAN_OWNER_BINDING_PATH') != EXPECTED['manager_binding_path']:
        raise InstallError('manager plan binding path was not retained')
    if base_env.get('V4_MANAGER_PLAN_OWNER_BINDING_PATH') != EXPECTED['manager_binding_path']:
        raise InstallError('R3 baseline manager plan binding path mismatch')
    if identity.get('candidate_sha256') != EXPECTED['candidate_plist_sha256'] or identity.get('candidate_manifest_sha256') != EXPECTED['candidate_manifest_sha256']:
        raise InstallError('recovery identity does not match frozen candidate')
    if require_active_baseline and ACTIVE.read_bytes() != BASELINE.read_bytes():
        raise InstallError('active plist is no longer the exact frozen R3 baseline')
    return {
        'status': 'R2_CANDIDATE_PACKAGE_VERIFY_PASS',
        'release_id': EXPECTED['release_id'],
        'candidate_manifest_sha256': EXPECTED['candidate_manifest_sha256'],
        'candidate_app_sha256': EXPECTED['candidate_app_sha256'],
        'staged_plist_sha256': EXPECTED['candidate_plist_sha256'],
        'changed_app_paths_vs_r3': changed,
        'candidate_app_inventory_entries': len(candidate_rows),
        'candidate_behavior': canary.get('status'),
        'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False,
        'active_plist_sha256': sha(ACTIVE),
        'service_operation_performed': False,
    }


def verify_exact_review_receipt(receipt_path: Path, receipt_sha256: str, expected_scope: dict[str, Any]) -> dict[str, Any]:
    from api_candidate_recovery import RecoveryError, verify_reviewer_receipt

    try:
        value = verify_reviewer_receipt(receipt_path, receipt_sha256, expected_scope)
    except (OSError, ValueError, KeyError, RecoveryError) as exc:
        raise InstallError(str(exc)) from exc
    if value.get('scope') != expected_scope:
        raise InstallError('reviewer receipt scope is not an exact match to the frozen scope')
    return value


def verify_review_receipt(receipt_path: Path, receipt_sha256: str) -> dict[str, Any]:
    plan = load_json(PLAN)
    if plan.get('plan_status') != 'READY_FOR_INDEPENDENT_REVIEW':
        raise InstallError('final plan is not frozen for independent review')
    if plan.get('candidate', {}).get('manifest_sha256') != EXPECTED['candidate_manifest_sha256']:
        raise InstallError('final plan candidate manifest pin mismatch')
    if plan.get('writer_artifacts', {}).get('install_helper_sha256') != sha(Path(__file__)):
        raise InstallError('installer helper hash differs from frozen plan')
    if plan.get('writer_artifacts', {}).get('recovery_helper_sha256') != sha(RECOVERY):
        raise InstallError('recovery helper hash differs from frozen plan')
    if plan.get('writer_artifacts', {}).get('install_tests_sha256') != sha(R2 / 'test_api_candidate_install_r2.py'):
        raise InstallError('installer test hash differs from frozen plan')
    expected_scope = {
        'plan_sha256': sha(PLAN),
        'install_helper_sha256': sha(Path(__file__)),
        'install_tests_sha256': sha(R2 / 'test_api_candidate_install_r2.py'),
        'recovery_helper_sha256': sha(RECOVERY),
        'recovery_tests_sha256': sha(RECOVERY_TESTS),
        'canary_script_sha256': sha(CANARY_SCRIPT),
        'canary_receipt_sha256': sha(CANARY),
        'candidate_manifest_sha256': sha(CANDIDATE / 'release-manifest.json'),
        'candidate_app_sha256': sha(CANDIDATE / 'app/apps/api/v35_api/app.py'),
        'candidate_app_inventory_sha256': load_json(CANDIDATE / 'release-manifest.json')['application_inventory']['aggregate_sha256'],
        'staged_plist_sha256': sha(STAGED),
        'recovery_identity_sha256': sha(IDENTITY),
        'baseline_plist_sha256': sha(BASELINE),
        'baseline_manifest_sha256': EXPECTED['active_manifest_sha256'],
        'source_diff_sha256': sha(SOURCE_DIFF),
        'source_map_sha256': sha(SOURCE_MAP),
        'r2_gate_reviewer_receipt_sha256': sha(GATE_RECEIPT),
        'manager_source_sha256': sha(R3 / 'app/v4/manager_research/announcement_analysis.py'),
        'manager_binding_sha256': sha(Path(EXPECTED['manager_binding_path'])),
    }
    scope = load_json(REVIEW_SCOPE)
    if scope != expected_scope:
        raise InstallError('frozen review scope file does not match current plan/package bytes')
    value = verify_exact_review_receipt(receipt_path, receipt_sha256, expected_scope)
    return value


def import_guard():
    spec = importlib.util.spec_from_file_location('v4_reviewed_api_cutover_guard_r2', GUARD)
    if spec is None or spec.loader is None:
        raise InstallError('reviewed no-clobber cutover guard unavailable')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.EVIDENCE_ROOT = R2
    return module


def require_install_slot() -> None:
    from api_candidate_recovery import RecoveryError, SystemRecoveryOps, RecoveryIdentity

    identity = RecoveryIdentity.from_json(IDENTITY)
    ops = SystemRecoveryOps(identity)
    try:
        status = ops.launchd_status()
        if status is not None:
            raise InstallError('exact API launchd label must be absent before plist install')
        ops.require_port_free()
    except RecoveryError as exc:
        raise InstallError(str(exc)) from exc


def preflight() -> dict[str, Any]:
    package = verify_package(require_active_baseline=True)
    require_install_slot()
    return {**package, 'status': 'R2_CANDIDATE_INSTALL_PREFLIGHT_PASS', 'exact_label_absent': True, 'port_8873_free': True}


def self_test_cas() -> dict[str, Any]:
    guard = import_guard()
    with tempfile.TemporaryDirectory(prefix='api-r2-cas-selftest-', dir=R2) as temp:
        root = Path(temp)
        target = root / 'active.plist'
        target.write_bytes(b'frozen-baseline-bytes')
        os.chmod(target, 0o640)
        claim = guard.atomic_write_no_clobber(
            'api', target, b'frozen-candidate-bytes',
            expected_current_sha256=sha_bytes(b'frozen-baseline-bytes'),
            phase='API_R2_CAS_SELF_TEST',
        )
        if target.read_bytes() != b'frozen-candidate-bytes' or claim.read_bytes() != b'frozen-baseline-bytes':
            raise InstallError('R2 CAS self-test did not preserve the exact prior bytes')
        if stat.S_IMODE(target.stat().st_mode) != 0o640:
            raise InstallError('R2 CAS self-test did not preserve the target mode')
        return {
            'status': 'R2_CAS_SELF_TEST_PASS',
            'active_or_service_paths_touched': False,
            'temporary_root': str(root),
            'candidate_bytes_installed': True,
            'baseline_claim_preserved': True,
            'mode_preserved': True,
        }


def install(args: argparse.Namespace) -> dict[str, Any]:
    if args.confirm != 'INSTALL_API_PRESELECTION_SOURCE_R2_20261008':
        raise InstallError('exact R2 install confirmation string is required')
    receipt = verify_review_receipt(args.reviewer_receipt, args.reviewer_sha256)
    package = verify_package(require_active_baseline=True)
    require_install_slot()
    guard = import_guard()
    try:
        claim = guard.atomic_write_no_clobber(
            'api', ACTIVE, STAGED.read_bytes(),
            expected_current_sha256=EXPECTED['active_plist_sha256'],
            phase='API_PRESELECTION_R2_INSTALL',
        )
    except Exception as exc:
        raise InstallError(f'R2 candidate plist CAS install failed: {exc}') from exc
    if sha(ACTIVE) != EXPECTED['candidate_plist_sha256']:
        raise InstallError('candidate plist CAS did not read back at its frozen SHA')
    return {
        'status': 'R2_CANDIDATE_PLIST_INSTALLED_NOT_BOOTSTRAPPED',
        'active_plist_sha256': sha(ACTIVE), 'baseline_claim_path': str(claim),
        'reviewer_receipt_sha256': sha(args.reviewer_receipt),
        'review_identity': receipt['review_identity'],
        'service_operation_performed': False, 'launchd_action_performed': False,
        'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False,
        'package_verify': package,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('verify')
    sub.add_parser('preflight')
    sub.add_parser('self-test-cas')
    check = sub.add_parser('review-check')
    check.add_argument('--reviewer-receipt', type=Path, required=True)
    check.add_argument('--reviewer-sha256', required=True)
    apply = sub.add_parser('install')
    apply.add_argument('--reviewer-receipt', type=Path, required=True)
    apply.add_argument('--reviewer-sha256', required=True)
    apply.add_argument('--confirm', required=True)
    args = parser.parse_args()
    if args.action == 'verify':
        result = verify_package()
    elif args.action == 'preflight':
        result = preflight()
    elif args.action == 'self-test-cas':
        result = self_test_cas()
    elif args.action == 'review-check':
        value = verify_review_receipt(args.reviewer_receipt, args.reviewer_sha256)
        result = {'status': 'INDEPENDENT_REVIEW_PASS_FOR_EXACT_R2_PLAN_AND_CANDIDATE', 'review_identity': value['review_identity'], 'reviewer_receipt_sha256': sha(args.reviewer_receipt)}
    else:
        result = install(args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, InstallError) as exc:
        print(json.dumps({'status': 'STOP_CANNOT_CONFIRM', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
