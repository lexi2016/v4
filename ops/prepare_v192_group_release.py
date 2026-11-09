"""Prepare one inactive V1.9.2 API/static delta on the installed R4 tuple.

Main and Stage app/manifest identities are reused exactly. No service control,
producer execution, publication, or write to the installed tuple occurs.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import plistlib
import shutil
import stat

from ops.prepare_daily_materials_release import (
    clone_release, seal_manifest, sha, validate_dependency_packet,
)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


def overlay(root, item):
    relative = Path(item['target'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('DELTA_RELATIVE_PATH_REQUIRED')
    target, source = root / relative, Path(item['source'])
    if sha(source) != item['after_sha256']:
        raise ValueError('DELTA_SOURCE_DRIFT:' + str(relative))
    if target.is_symlink() or any(parent.is_symlink() for parent in target.parents):
        raise ValueError('DELTA_SYMLINK_REFUSED')
    if target.exists():
        if sha(target) != item['before_sha256']:
            raise ValueError('DELTA_PREIMAGE_DRIFT:' + str(relative))
        mode = stat.S_IMODE(target.stat().st_mode)
    else:
        if item['before_sha256'] is not None:
            raise ValueError('DELTA_MISSING:' + str(relative))
        mode = stat.S_IMODE(source.stat().st_mode)
    parents = []
    try:
        for parent in target.parents:
            if parent == root:
                break
            if parent.exists() and not parent.stat().st_mode & stat.S_IWUSR:
                original = stat.S_IMODE(parent.stat().st_mode)
                parent.chmod(original | stat.S_IWUSR)
                parents.append((parent, original))
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.chmod(mode | stat.S_IWUSR)
        target.write_bytes(source.read_bytes())
        target.chmod(mode)
    finally:
        if target.exists():
            target.chmod(mode)
        for parent, original in reversed(parents):
            parent.chmod(original)


def prepare(*, delta_path: Path, output: Path, r4_packet: Path):
    approved = Path.home() / 'Library/Application Support/com.lexi.v4.local/candidates'
    if (not output.is_absolute() or not output.is_relative_to(approved) or output == approved
            or output.resolve() != output):
        raise ValueError('LIBRARY_CANDIDATE_ROOT_REQUIRED')
    if output.exists():
        raise FileExistsError('inactive output already exists; preserve and inspect it')
    delta = json.loads(delta_path.read_text())
    entries = delta['entries']
    if any(item.get('scope') not in {'api', 'research_panel'} for item in entries):
        raise ValueError('API_STATIC_DELTA_ONLY')
    targets = [(item['scope'], item['target']) for item in entries]
    if len(targets) != len(set(targets)):
        raise ValueError('DUPLICATE_DELTA_TARGET')
    baseline = json.loads(r4_packet.read_text())
    current = {}
    for role, base in baseline['services'].items():
        live = Path(base['live_plist'])
        payload = plistlib.loads(live.read_bytes())
        env = payload['EnvironmentVariables']
        if sha(live) != base['draft_plist_sha256'] or any(env[key] != base[field] for key, field in (
                ('V4_APP_ROOT', 'app_root'), ('V4_RELEASE_ID', 'release_id'),
                ('V4_RELEASE_MANIFEST_PATH', 'manifest'), ('V4_RELEASE_MANIFEST_SHA256', 'manifest_sha256'))):
            raise ValueError('INSTALLED_R4_BASELINE_DRIFT:' + role)
        current[role] = dict(base=base, live=live, plist=payload, env=env)
    main_env = current['main']['env']
    reader = Path(main_env['V4_SHARED_PACKAGE_ROOT']) / 'shared_data/v192_selector.py'
    expected_v192_environment = {
        'V4_WORKBENCH_V192_SHARED_ROOT': main_env['V4_SHARED_DATA_ROOT'],
        'V4_WORKBENCH_V192_SHARED_PACKAGE_ROOT': main_env['V4_SHARED_PACKAGE_ROOT'],
        'V4_WORKBENCH_V192_READER_SHA256': sha(reader),
    }
    if delta.get('api_environment') != expected_v192_environment:
        raise ValueError('EXACT_EXISTING_MAIN_V192_SOURCE_BINDING_REQUIRED')
    output.mkdir()
    api = current['api']
    api_id = output.name + '-api'
    api_root = output / api_id
    api_root.mkdir()
    app = api_root / 'app'
    old_app = Path(api['env']['V4_APP_ROOT'])
    old_manifest = Path(api['env']['V4_RELEASE_MANIFEST_PATH'])
    manifest = json.loads(old_manifest.read_text())
    clone_release(old_app, app, manifest)
    api_paths = set()
    for item in entries:
        if item['scope'] == 'api':
            overlay(app, item)
            api_paths.add(item['target'])
    manifest = seal_manifest(manifest, app=app, release_id=api_id, role='api',
                             delta_paths=api_paths, base_manifest=old_manifest)
    manifest_path = api_root / 'release-manifest.json'
    save(manifest_path, manifest)
    old_static = Path(api['env']['V4_RESEARCH_PANEL_ROOT'])
    old_assets = Path(api['env']['V4_RESEARCH_PANEL_ASSET_MANIFEST'])
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
        env = item['env']
        payload = deepcopy(item['plist'])
        if role == 'api':
            payload['WorkingDirectory'] = str(app)
            payload['EnvironmentVariables'].update(V4_APP_ROOT=str(app), V4_RELEASE_ID=api_id,
                V4_RELEASE_MANIFEST_PATH=str(manifest_path), V4_RELEASE_MANIFEST_SHA256=sha(manifest_path),
                V4_RESEARCH_PANEL_ROOT=str(static), V4_RESEARCH_PANEL_ASSET_MANIFEST=str(asset_path))
            payload['EnvironmentVariables'].update(expected_v192_environment)
        draft = output / (role.upper() + '_CANDIDATE.plist')
        draft.write_bytes(plistlib.dumps(payload, sort_keys=True))
        draft.chmod(0o600)
        new_env = payload['EnvironmentVariables']
        services[role] = dict(kind=role, label=payload['Label'], live_plist=str(item['live']),
            before_sha256=sha(item['live']), draft_plist=str(draft), draft_plist_sha256=sha(draft),
            old_app_root=env['V4_APP_ROOT'], old_manifest_sha256=env['V4_RELEASE_MANIFEST_SHA256'],
            app_root=new_env['V4_APP_ROOT'], release_id=new_env['V4_RELEASE_ID'],
            manifest=new_env['V4_RELEASE_MANIFEST_PATH'], manifest_sha256=new_env['V4_RELEASE_MANIFEST_SHA256'])
    policy = json.loads(Path(current['main']['env']['V4_RESEARCH_RETENTION_POLICY']).read_text())
    pins = json.loads(Path(policy['managed_pin_inventory']['path']).read_text())
    for ref in pins['source_bindings']:
        if ref['path'] == services['api']['live_plist']:
            ref['sha256'] = services['api']['draft_plist_sha256']
        elif ref['path'] == str(old_assets):
            ref.update(path=str(asset_path), sha256=sha(asset_path))
        elif ref['path'].startswith(str(old_app) + '/'):
            ref['path'] = str(app) + ref['path'][len(str(old_app)):]
            ref['sha256'] = sha(Path(ref['path']))
        elif sha(Path(ref['path'])) != ref['sha256']:
            raise ValueError('UNRELATED_SOURCE_BINDING_DRIFT:' + ref['path'])
    pins_path = output / 'research_storage_pins.json'
    save(pins_path, pins)
    policy['managed_pin_inventory'] = dict(path=str(pins_path), sha256=sha(pins_path))
    policy_path = output / 'research_storage_policy.json'
    save(policy_path, policy)
    main_path = Path(services['main']['draft_plist'])
    main_plist = plistlib.loads(main_path.read_bytes())
    main_plist['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=str(policy_path),
        V4_RESEARCH_RETENTION_POLICY_SHA256=sha(policy_path))
    main_path.write_bytes(plistlib.dumps(main_plist, sort_keys=True))
    services['main']['draft_plist_sha256'] = sha(main_path)
    frozen_delta = output / 'FROZEN_DELTA.json'
    frozen_delta.write_bytes(delta_path.read_bytes())
    source_root = Path(__file__).resolve().parents[1]
    packet = dict(schema='v4.daily_materials_dependency_packet.v1', status='PREPARED_NOT_ACTIVATED',
        runtime_candidate_root=str(output), preserved_service_roles=['main', 'stage'], services=services,
        static=dict(root=str(static), manifest=str(asset_path), manifest_sha256=sha(asset_path),
                    delta_paths=sorted(static_paths)),
        pins=dict(path=str(pins_path), sha256=sha(pins_path)), policy=dict(path=str(policy_path), sha256=sha(policy_path)),
        company_score_delta=dict(path=str(frozen_delta), sha256=sha(frozen_delta)),
        scheduler_lane_lock_root=str(Path.home() / 'Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners'),
        baseline_packet=dict(path=str(r4_packet), sha256=sha(r4_packet)),
        v192_environment_binding=expected_v192_environment,
        v192_reader_source=dict(path=str(reader), sha256=sha(reader)),
        tool_source_files=[dict(path=str(path), sha256=sha(path)) for path in (
            Path(__file__), source_root / 'ops/prepare_daily_materials_release.py',
            source_root / 'ops/activate_daily_materials_release.py')],
        scope='V192_API_STATIC_GROUP_ONLY_MAIN_STAGE_BUSINESS_IDENTITIES_PRESERVED',
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
    parser.add_argument('--r4-packet', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(delta_path=args.delta, output=args.output, r4_packet=args.r4_packet)))


if __name__ == '__main__':
    main()
