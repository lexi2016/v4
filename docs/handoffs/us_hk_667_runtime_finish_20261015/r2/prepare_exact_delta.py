"""Prepare a sealed-identity candidate from a supplied frozen delta receipt.

No launchctl, live-plist mutation, source-directory copy, data mutation or scheduler work.
The source Writer must supply the exact reviewed delta receipt before this runs.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import plistlib

from ops.api_release_integration import (
    build_integrated_app, inventory_tree, inventory_digest,
    read_active_release, verify_api_release_candidate,
)
from ops.prepare_api_only_cutover import rewrite_api_only_plist

BASE = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
PLIST = Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
EXPECTED_PLIST_SHA = '0f9118056d12804846ed70ab99a4cc0896363d435a4b753a5709182ef3348543'
CANDIDATE = BASE / 'releases/us-hk-mapping-finish-20261015-r2'
OUT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--frozen-delta-receipt', type=Path, required=True)
    parser.add_argument('--frozen-delta-sha256', required=True)
    parser.add_argument('--include-untracked-path', action='append', default=[])
    args = parser.parse_args()
    if sha(PLIST) != EXPECTED_PLIST_SHA:
        raise RuntimeError('ACTIVE_PLIST_CHANGED_REBASE_REQUIRED')
    if sha(args.frozen_delta_receipt) != args.frozen_delta_sha256:
        raise RuntimeError('FROZEN_DELTA_RECEIPT_CHANGED')
    config_path = BASE / 'config/manager-workbench-v9.json'
    config = json.loads(config_path.read_text())
    if config['relation_root'] != str(CANDIDATE / 'app'):
        raise RuntimeError('V8_RELATION_ROOT_NOT_BOUND_TO_CANDIDATE')
    active = read_active_release(PLIST, role='gateway')
    if active['release_id'] != 'us-close-recovery-api-20261015-r1':
        raise RuntimeError('ACTIVE_RELEASE_CHANGED_REBASE_REQUIRED')
    CANDIDATE.mkdir(exist_ok=False)
    integration = build_integrated_app(active_api_plist_path=PLIST,
        source_root=args.source_root, candidate_root=CANDIDATE,
        delta_receipt_path=args.frozen_delta_receipt,
        explicit_untracked_paths=args.include_untracked_path, role='gateway', base_role='gateway')
    inventory = inventory_tree(CANDIDATE / 'app')
    manifest = deepcopy(active['manifest'])
    manifest.update(generated_at=datetime.now(timezone.utc).isoformat(), candidate_status='READY_FOR_REVIEW',
        activation_status='NOT_ACTIVATED', deployment_status='CANNOT_CONFIRM', api_integration=integration)
    manifest['candidate'].update(root=str(CANDIDATE), app_root=str(CANDIDATE / 'app'),
        release_id=CANDIDATE.name, module_role='gateway', module_contract_sha256=None,
        data_copy_performed=False, runtime_venv_copied=False, ignored_runtime_data_copied=False)
    manifest['application_inventory'] = dict(entry_count=len(inventory),
        aggregate_sha256=inventory_digest(inventory), entries=inventory)
    manifest['source'] = dict(active_role_plist=str(PLIST), active_release_bytes_copied=True,
        source_workspace_full_tree_copied=False, api_integration_delta_receipt=str(args.frozen_delta_receipt))
    manifest['verification_gaps'] = ['Independent candidate review pending', 'Live API/UI not activated',
        'Controlled late capture is not natural-slot evidence', 'US factor paired identity gap remains']
    manifest_path = CANDIDATE / 'release-manifest.json'
    write(manifest_path, manifest)
    digest = sha(manifest_path)
    verification = verify_api_release_candidate(candidate_root=CANDIDATE, active_api_plist_path=PLIST,
        expected_manifest_sha256=digest, active_pointer='base', role='gateway', base_role='gateway')
    original = plistlib.loads(PLIST.read_bytes())
    staged = rewrite_api_only_plist(original, candidate_app_root=CANDIDATE / 'app', release_id=CANDIDATE.name,
        manifest_path=manifest_path, manifest_sha256=digest, candidate_manager_state_root=None)
    # The sole extra runtime change is the pre-existing manager config selector.
    environment = staged.setdefault('EnvironmentVariables', {})
    environment['V4_MANAGER_WORKBENCH_CONFIG_PATH'] = str(config_path)
    staged['ProgramArguments'] = [
        'V4_MANAGER_WORKBENCH_CONFIG_PATH=' + str(config_path)
        if isinstance(arg, str) and arg.startswith('V4_MANAGER_WORKBENCH_CONFIG_PATH=') else arg
        for arg in staged['ProgramArguments']]
    config_dir = CANDIDATE / 'config'
    config_dir.mkdir()
    staged_path = config_dir / 'com.lexi.v35.api-only.plist'
    with staged_path.open('xb') as handle:
        plistlib.dump(staged, handle, fmt=plistlib.FMT_XML, sort_keys=True)
    plan = dict(activation_status='NOT_ACTIVATED', launchctl_called=False,
        source_plist_sha256=sha(PLIST), candidate_manifest_sha256=digest,
        staged_plist=str(staged_path), staged_plist_sha256=sha(staged_path),
        config_path=str(config_path), config_sha256=sha(config_path),
        verification=verification, shared_manager_state_preserved=True,
        activation_commands=['Independent REVIEWED/BEHAVIOR_VERIFIED receipt required before execution',
            'launchctl bootout gui/$(id -u)/com.lexi.v35.api-only',
            'Copy staged plist to the active plist path under the existing shared release lock',
            'launchctl bootstrap gui/$(id -u) /Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist'],
        rollback_plist=str(OUT / 'preimage/active-us-close-api.plist'), rollback_sha256=EXPECTED_PLIST_SHA,
        rollback_commands=['launchctl bootout gui/$(id -u)/com.lexi.v35.api-only',
            'Restore the exact preimage active-api.plist to the active plist path under the shared release lock',
            'launchctl bootstrap gui/$(id -u) /Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist'])
    write(config_dir / 'cutover-plan.json', plan)
    write(OUT / 'candidate-preparation-receipt.json', plan)
    print(json.dumps({'status':'PREPARED_NOT_ACTIVATED','candidate_root':str(CANDIDATE),
        'manifest_sha256':digest,'delta_paths':[entry['path'] for entry in integration['delta_entries']]}, indent=2))


if __name__ == '__main__':
    main()
