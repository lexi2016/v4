"""Inactive Main/Stage/API packet for the bounded missing-V192-asset hooks.

Only reviewed source deltas are copied. Historical owner pins remain read-only;
no producer, publication, service control, or installed-file mutation occurs.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import plistlib
import shutil

from ops.prepare_daily_materials_release import clone_release, seal_manifest, sha, validate_dependency_packet
from ops.prepare_v192_group_release import overlay, save


def extend_stage_history(source: str) -> str:
    old = "not isinstance(historical, list) or len(historical) > 5"
    if source.count(old) != 1:
        raise ValueError('EXACT_FIVE_OWNER_STAGE_PREIMAGE_REQUIRED')
    return source.replace(old, "not isinstance(historical, list) or len(historical) > 6", 1)


def prepare(*, delta_path: Path, output: Path, baseline_packet: Path):
    approved = Path.home() / 'Library/Application Support/com.lexi.v4.local/candidates'
    if (not output.is_absolute() or not output.is_relative_to(approved) or output == approved
            or output.resolve() != output or output.exists()):
        raise ValueError('NEW_EXACT_LIBRARY_CANDIDATE_REQUIRED')
    delta = json.loads(delta_path.read_text())
    entries = delta['entries']
    if any(item.get('scope') not in {'main', 'api', 'research_panel'} for item in entries):
        raise ValueError('ONLY_REVIEWED_MAIN_API_STATIC_DELTA_ALLOWED')
    targets = [(item['scope'], item['target']) for item in entries]
    if len(targets) != len(set(targets)):
        raise ValueError('DUPLICATE_DELTA_TARGET')
    baseline = json.loads(baseline_packet.read_text())
    current = {}
    for role, base in baseline['services'].items():
        live = Path(base['live_plist'])
        payload = plistlib.loads(live.read_bytes())
        env = payload['EnvironmentVariables']
        if sha(live) != base['draft_plist_sha256'] or any(env[key] != base[field] for key, field in (
                ('V4_APP_ROOT', 'app_root'), ('V4_RELEASE_ID', 'release_id'),
                ('V4_RELEASE_MANIFEST_PATH', 'manifest'), ('V4_RELEASE_MANIFEST_SHA256', 'manifest_sha256'))):
            raise ValueError('DEPLOYED_BASELINE_DRIFT:' + role)
        current[role] = dict(base=base, live=live, plist=payload, env=env)
    main_env = current['main']['env']
    reader = Path(main_env['V4_SHARED_PACKAGE_ROOT']) / 'shared_data/v192_selector.py'
    bindings = {'V4_WORKBENCH_V192_SHARED_ROOT': main_env['V4_SHARED_DATA_ROOT'],
                'V4_WORKBENCH_V192_SHARED_PACKAGE_ROOT': main_env['V4_SHARED_PACKAGE_ROOT'],
                'V4_WORKBENCH_V192_READER_SHA256': sha(reader)}
    if delta.get('api_environment') != bindings:
        raise ValueError('EXISTING_MAIN_V192_BINDING_REQUIRED')
    output.mkdir()

    def build_app(role):
        item = current[role]
        item['release_id'] = output.name + '-' + role
        item['release_root'] = output / item['release_id']
        item['release_root'].mkdir()
        item['app'] = item['release_root'] / 'app'
        item['old_manifest'] = Path(item['env']['V4_RELEASE_MANIFEST_PATH'])
        item['manifest_object'] = json.loads(item['old_manifest'].read_text())
        clone_release(Path(item['env']['V4_APP_ROOT']), item['app'], item['manifest_object'])
        changed = set()
        for entry in entries:
            if entry['scope'] == role:
                overlay(item['app'], entry)
                changed.add(entry['target'])
        return item, changed

    def seal(item, role, changed):
        manifest = seal_manifest(item['manifest_object'], app=item['app'], release_id=item['release_id'],
                                 role=role, delta_paths=changed, base_manifest=item['old_manifest'])
        item['manifest'] = item['release_root'] / 'release-manifest.json'
        save(item['manifest'], manifest)

    main, changed = build_app('main')
    if not changed:
        raise ValueError('MAIN_HOOK_DELTA_REQUIRED_FOR_THIS_PACKET')
    seal(main, 'main', changed)
    stage, stage_changes = build_app('stage')
    if stage_changes:
        raise ValueError('BUSINESS_WRITER_CANNOT_SUPPLY_STAGE_DELTA')
    attestation = stage['app'] / 'infrastructure/manager_input_attestation.py'
    attestation.write_text(extend_stage_history(attestation.read_text()))
    config_path = stage['app'] / 'stage_center_tick_config.json'
    config = json.loads(config_path.read_text())
    previous_owner = deepcopy(config['research_owner_binding'])
    if previous_owner != dict(app_root=main_env['V4_APP_ROOT'], release_id=main_env['V4_RELEASE_ID'],
                              manifest_sha256=main_env['V4_RELEASE_MANIFEST_SHA256'],
                              manifest_path=main_env['V4_RELEASE_MANIFEST_PATH']):
        raise ValueError('STAGE_BASELINE_OWNER_MISMATCH')
    if len(config['research_historical_owner_bindings']) != 5:
        raise ValueError('EXACT_EXISTING_FIVE_HISTORY_REQUIRED')
    config['research_historical_owner_bindings'].append(previous_owner)
    config['research_owner_binding'] = dict(app_root=str(main['app']), release_id=main['release_id'],
        manifest_sha256=sha(main['manifest']), manifest_path=str(main['manifest']))
    save(config_path, config)
    seal(stage, 'stage', {'infrastructure/manager_input_attestation.py', 'stage_center_tick_config.json'})
    api, changed = build_app('api')
    seal(api, 'api', changed)

    old_static = Path(current['api']['env']['V4_RESEARCH_PANEL_ROOT'])
    old_assets = Path(current['api']['env']['V4_RESEARCH_PANEL_ASSET_MANIFEST'])
    assets = json.loads(old_assets.read_text())
    if any(sha(old_static / item['path']) != item['sha256'] for item in assets['files']):
        raise ValueError('INSTALLED_STATIC_BASELINE_DRIFT')
    static = output / 'research-panel'
    shutil.copytree(old_static, static, symlinks=True)
    static_paths = set()
    for original in entries:
        if original['scope'] != 'research_panel':
            continue
        item = deepcopy(original)
        if Path(item['target']).is_absolute():
            item['target'] = str(Path(item['target']).relative_to(old_static))
        overlay(static, item)
        static_paths.add(item['target'])
    listed = {item['path'] for item in assets['files']}
    for item in assets['files']:
        observed = sha(static / item['path'])
        if observed != item['sha256'] and item['path'] not in static_paths:
            raise ValueError('UNLISTED_STATIC_CHANGE')
        item['sha256'] = observed
    for relative in sorted(static_paths - listed):
        assets['files'].append(dict(path=relative, sha256=sha(static / relative)))
    asset_path = output / 'research-panel-assets.json'
    save(asset_path, assets)

    services = {}
    for role, item in current.items():
        payload = deepcopy(item['plist'])
        old_app, new_app = item['env']['V4_APP_ROOT'], str(item['app'])
        def rewrite(value):
            if isinstance(value, str):
                return value.replace(old_app, new_app)
            if isinstance(value, list):
                return [rewrite(part) for part in value]
            if isinstance(value, dict):
                return {key: rewrite(part) for key, part in value.items()}
            return value
        payload = rewrite(payload)
        payload['WorkingDirectory'] = new_app
        payload['EnvironmentVariables'].update(V4_APP_ROOT=new_app, V4_RELEASE_ID=item['release_id'],
            V4_RELEASE_MANIFEST_PATH=str(item['manifest']), V4_RELEASE_MANIFEST_SHA256=sha(item['manifest']))
        if role == 'api':
            payload['EnvironmentVariables'].update(bindings)
            payload['EnvironmentVariables'].update(V4_RESEARCH_PANEL_ROOT=str(static),
                                                    V4_RESEARCH_PANEL_ASSET_MANIFEST=str(asset_path))
        draft = output / (role.upper() + '_CANDIDATE.plist')
        draft.write_bytes(plistlib.dumps(payload, sort_keys=True))
        draft.chmod(0o600)
        services[role] = dict(kind=role, label=payload['Label'], live_plist=str(item['live']),
            before_sha256=sha(item['live']), draft_plist=str(draft), draft_plist_sha256=sha(draft),
            old_app_root=old_app, old_manifest_sha256=item['env']['V4_RELEASE_MANIFEST_SHA256'],
            app_root=new_app, release_id=item['release_id'], manifest=str(item['manifest']),
            manifest_sha256=sha(item['manifest']))

    policy = json.loads(Path(main_env['V4_RESEARCH_RETENTION_POLICY']).read_text())
    pins = json.loads(Path(policy['managed_pin_inventory']['path']).read_text())
    for ref in pins['source_bindings']:
        if ref['path'] in {services[role]['live_plist'] for role in ('api', 'stage')}:
            role = next(role for role in ('api', 'stage') if services[role]['live_plist'] == ref['path'])
            ref['sha256'] = services[role]['draft_plist_sha256']
        elif ref['path'] == str(old_assets):
            ref.update(path=str(asset_path), sha256=sha(asset_path))
        else:
            for role in ('main', 'api'):
                old_app = current[role]['env']['V4_APP_ROOT']
                if ref['path'].startswith(old_app + '/'):
                    ref['path'] = str(current[role]['app']) + ref['path'][len(old_app):]
                    ref['sha256'] = sha(Path(ref['path']))
                    break
            else:
                if sha(Path(ref['path'])) != ref['sha256']:
                    raise ValueError('UNRELATED_SOURCE_BINDING_DRIFT')
    pins['expected_main_app_root'] = str(main['app'])
    pins_path = output / 'research_storage_pins.json'
    save(pins_path, pins)
    policy['managed_pin_inventory'] = dict(path=str(pins_path), sha256=sha(pins_path))
    policy_path = output / 'research_storage_policy.json'
    save(policy_path, policy)
    main_path = Path(services['main']['draft_plist'])
    payload = plistlib.loads(main_path.read_bytes())
    payload['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=str(policy_path),
                                           V4_RESEARCH_RETENTION_POLICY_SHA256=sha(policy_path))
    main_path.write_bytes(plistlib.dumps(payload, sort_keys=True))
    services['main']['draft_plist_sha256'] = sha(main_path)
    frozen_delta = output / 'FROZEN_DELTA.json'
    frozen_delta.write_bytes(delta_path.read_bytes())
    source_root = Path(__file__).resolve().parents[1]
    packet = dict(schema='v4.daily_materials_dependency_packet.v1', status='PREPARED_NOT_ACTIVATED',
        runtime_candidate_root=str(output), services=services,
        static=dict(root=str(static), manifest=str(asset_path), manifest_sha256=sha(asset_path),
                    delta_paths=sorted(static_paths)),
        pins=dict(path=str(pins_path), sha256=sha(pins_path)), policy=dict(path=str(policy_path), sha256=sha(policy_path)),
        company_score_delta=dict(path=str(frozen_delta), sha256=sha(frozen_delta)),
        scheduler_lane_lock_root=str(Path.home() / 'Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners'),
        baseline_packet=dict(path=str(baseline_packet), sha256=sha(baseline_packet)),
        v192_environment_binding=bindings, v192_reader_source=dict(path=str(reader), sha256=sha(reader)),
        tool_source_files=[dict(path=str(path), sha256=sha(path)) for path in (
            Path(__file__), source_root / 'ops/prepare_v192_group_release.py',
            source_root / 'ops/prepare_daily_materials_release.py', source_root / 'ops/activate_daily_materials_release.py')],
        scope='EXISTING_V192_MISSING_ASSETS_ONLY_NO_ORIGINAL371_OR_RULE_CHANGE',
        main_manifest_policy='HISTORICAL_PROVENANCE_ONLY_RUNTIME_POLICY_AUTHORITY_IS_PLIST_ENV',
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False,
        natural_execution_verified=False)
    save(output / 'PACKET.json', packet)
    result = validate_dependency_packet(packet)
    save(output / 'DEPENDENCY_CHECK.json', result)
    return dict(packet=str(output / 'PACKET.json'), packet_sha256=sha(output / 'PACKET.json'), result=result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--delta', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--baseline-packet', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(delta_path=args.delta, output=args.output, baseline_packet=args.baseline_packet)))


if __name__ == '__main__':
    main()
