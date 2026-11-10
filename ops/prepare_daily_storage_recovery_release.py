"""Bounded raw-storage repair release: Main + Stage; API stays installed.

Reuse the accepted release inventory, sealing, DAG, CAS and idle/drain/rollback
helpers. No business producer is invoked by preparation or validation.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import plistlib
from types import FunctionType
from ops import prepare_a925_mainclosure_release as prior
from ops.prepare_a925_mainclosure_release import (expected_plist, migrated_pins, LABELS,
    _service, _inventory, checked, record, sha, save, overlay, clone_release,
    seal_manifest, validate_api_manifest_shape)

BASELINES = {
    'api': 'dec319be02f69095d5e53b6a4fc96c69b2731ecd32ba8ee31d5b7259acaa57b6',
    'main': 'ef1fe8701ca953eab207428a0913813340588989f1fb34552efb22473a8f0d29',
    'stage': '813d595dd27c2af31007e5ee9d3ddf56cadde21170f17221320db4f944c563bc',
}
EXPECTED_DELTA = [('main', 'ops/research_storage_governance.py'),
                  ('stage', 'infrastructure/manager_input_attestation.py')]

def stage_config_for_main(old_config, main, release_id):
    config = deepcopy(old_config)
    previous = dict(app_root=main['old_app_root'],
        release_id=main['baseline_payload']['EnvironmentVariables']['V4_RELEASE_ID'],
        manifest_path=main['baseline_payload']['EnvironmentVariables']['V4_RELEASE_MANIFEST_PATH'],
        manifest_sha256=main['old_manifest_sha256'])
    if config['research_owner_binding'] != previous or len(config['research_historical_owner_bindings']) != 7:
        raise ValueError('EXACT_PREVIOUS_MAIN_AND_SEVEN_HISTORY_REQUIRED')
    if any(item['app_root'] == previous['app_root'] for item in config['research_historical_owner_bindings']):
        raise ValueError('PREVIOUS_MAIN_ALREADY_HISTORICAL')
    config['release_id'] = release_id
    config['research_owner_binding'] = dict(app_root=main['app_root'], release_id=main['release_id'],
        manifest_path=main['manifest'], manifest_sha256=main['manifest_sha256'])
    config['research_historical_owner_bindings'].append(previous)
    return config


def prepare(delta_path, output):
    approved = Path.home() / 'Library/Application Support/com.lexi.v4.local/candidates'
    if (not output.is_absolute() or not output.is_relative_to(approved) or output == approved
            or output.resolve() != output or output.exists()):
        raise ValueError('NEW_LIBRARY_CANDIDATE_REQUIRED')
    delta = json.loads(delta_path.read_text())
    entries = delta['entries']
    if ([(e['scope'], e['target']) for e in entries] != EXPECTED_DELTA
            or delta.get('deletions')):
        raise ValueError('EXACT_STORAGE_AND_STAGE_HISTORY_DELTA_REQUIRED')
    home = Path.home() / 'Library/LaunchAgents'
    services = {role: _service(home / (label + '.plist')) for role, label in LABELS.items()}
    if any(s['manifest_sha256'] != BASELINES[role] for role, s in services.items()):
        raise ValueError('EXACT_LIVE_BASELINE_REQUIRED')
    output.mkdir()
    old_config = Path(services['stage']['app_root']) / 'stage_center_tick_config.json'
    old_config_value = json.loads(old_config.read_text())
    for role in ('main', 'stage', 'api'):
        service = services[role]
        changes = [e for e in entries if e['scope'] == role]
        if changes:
            rid = output.name + '-' + role
            app = output / rid / 'app'
            app.parent.mkdir()
            base_manifest = Path(service['manifest'])
            manifest = json.loads(base_manifest.read_text())
            clone_release(Path(service['app_root']), app, manifest)
            changed = set()
            for entry in changes:
                overlay(app, entry)
                changed.add(entry['target'])
            if role == 'stage':
                config = deepcopy(old_config_value)
                config = stage_config_for_main(old_config_value, services['main'], rid)
                save(app / 'stage_center_tick_config.json', config)
                changed.add('stage_center_tick_config.json')
            final = seal_manifest(manifest, app=app, release_id=rid, role=role,
                                  delta_paths=changed, base_manifest=base_manifest)
            manifest_path = app.parent / 'release-manifest.json'
            save(manifest_path, final)
            service.update(app_root=str(app), release_id=rid, manifest=str(manifest_path),
                           manifest_sha256=sha(manifest_path))
        draft = output / (role.upper() + '_CANDIDATE.plist')
        draft.write_bytes(Path(service['live_plist']).read_bytes() if role == 'api' else plistlib.dumps(expected_plist(service, role), sort_keys=True))
        draft.chmod(0o600)
        service.update(draft_plist=str(draft), draft_plist_sha256=sha(draft))
    main = services['main']
    old_policy = Path(main['baseline_payload']['EnvironmentVariables']['V4_RESEARCH_RETENTION_POLICY'])
    if sha(old_policy) != main['baseline_payload']['EnvironmentVariables']['V4_RESEARCH_RETENTION_POLICY_SHA256']:
        raise ValueError('BASELINE_POLICY_SHA_DRIFT')
    policy = json.loads(old_policy.read_text())
    old_pins = checked(policy['managed_pin_inventory'])
    pins_path = output / 'research_storage_pins.json'
    save(pins_path, migrated_pins(json.loads(old_pins.read_text()), services))
    policy['managed_pin_inventory'] = record(pins_path)
    policy_path = output / 'research_storage_policy.json'
    save(policy_path, policy)
    payload = expected_plist(main, 'main')
    payload['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=str(policy_path),
        V4_RESEARCH_RETENTION_POLICY_SHA256=sha(policy_path))
    draft = output / 'MAIN_POLICY_CANDIDATE.plist'
    draft.write_bytes(plistlib.dumps(payload, sort_keys=True))
    draft.chmod(0o600)
    main.update(draft_plist=str(draft), draft_plist_sha256=sha(draft))
    frozen = output / 'FROZEN_DELTA.json'
    frozen.write_bytes(delta_path.read_bytes())
    protected = [record(old_policy), record(old_pins), record(old_config)]
    for reference in delta.get('input_bindings', []):
        checked(reference)
        protected.append(dict(reference))
    for s in services.values():
        protected.append(record(s['baseline_payload']['EnvironmentVariables']['V4_RELEASE_MANIFEST_PATH']))
    api_env = services['api']['baseline_payload']['EnvironmentVariables']
    for key in ('V4_RESEARCH_PANEL_ASSET_MANIFEST', 'V4_WORKBENCH_HOST_BINDING'):
        protected.append(record(api_env[key]))
    root = Path(__file__).resolve().parents[1]
    tool_paths = [Path(__file__), root / 'ops/prepare_a925_mainclosure_release.py', root / 'ops/prepare_top200_scope_release.py',
        root / 'ops/activate_daily_materials_release.py', root / 'ops/prepare_daily_materials_release.py',
        root / 'ops/prepare_v192_group_release.py', root / 'ops/api_release_integration.py']
    roles = ['main', 'stage']
    packet = dict(schema='v4.daily_storage_recovery_release.v1', status='PREPARED_NOT_ACTIVATED',
        root=str(output), services=services, control_roles=roles,
        protected_references=protected, delta=record(frozen), policy=record(policy_path),
        pins=record(pins_path), old_policy=record(old_policy), old_pins=record(old_pins),
        stage_config_before=record(old_config),
        tool_source_files=[record(path) for path in tool_paths],
        scheduler_lane_lock_root=str(Path.home() / 'Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners'),
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    save(output / 'PACKET.json', packet)
    result = validate(packet)
    save(output / 'DEPENDENCY_CHECK.json', result)
    return dict(packet=str(output / 'PACKET.json'), packet_sha256=sha(output / 'PACKET.json'), check=result)


def validate(packet, *, installed=False, restored=False):
    root = Path(packet['root'])
    approved = Path.home() / 'Library/Application Support/com.lexi.v4.local/candidates'
    if root.resolve() != root or not root.is_relative_to(approved) or root == approved:
        raise ValueError('LIBRARY_CANDIDATE_REQUIRED')
    for ref in packet['tool_source_files'] + packet['protected_references'] + [packet['delta']]:
        checked(ref)
    services = packet['services']
    substitutions = {}
    for role, s in services.items():
        checked(dict(path=s['draft_plist'], sha256=s['draft_plist_sha256']))
        expected = s['before_sha256'] if restored or not installed else s['draft_plist_sha256']
        if sha(Path(s['live_plist'])) != expected:
            raise ValueError('LIVE_PLIST_CAS_DRIFT:' + role)
        substitutions[s['live_plist']] = Path(s['live_plist']) if installed or restored else Path(s['draft_plist'])
    if restored:
        return dict(status='RESTORED_EXACT_BASELINE_TUPLE_NO_DATA_CHANGE')
    delta = json.loads(checked(packet['delta']).read_text())
    expected_roles = ['main', 'stage']
    if packet['control_roles'] != expected_roles:
        raise ValueError('SERVICE_CONTROL_SCOPE_DRIFT')
    for role, service in services.items():
        base_env = service['baseline_payload']['EnvironmentVariables']
        _inventory(dict(service, app_root=service['old_app_root'], manifest=base_env['V4_RELEASE_MANIFEST_PATH'],
            manifest_sha256=service['old_manifest_sha256'], release_id=base_env['V4_RELEASE_ID']))
        current = _inventory(service)
        if role == 'api':
            validate_api_manifest_shape(current)
        payload = plistlib.loads(substitutions[service['live_plist']].read_bytes())
        expected_payload = expected_plist(service, role)
        if role == 'main':
            expected_payload['EnvironmentVariables'].update(
                V4_RESEARCH_RETENTION_POLICY=packet['policy']['path'],
                V4_RESEARCH_RETENTION_POLICY_SHA256=packet['policy']['sha256'])
        if payload != expected_payload:
            raise ValueError('RELEASE_PLIST_CHANGE_OUTSIDE_IDENTITY_AND_MAIN_POLICY:' + role)
    if [(e['scope'],e['target']) for e in delta['entries']] != EXPECTED_DELTA or delta.get('deletions'):
        raise ValueError('DELTA_SCOPE_DRIFT')
    for role in ('main', 'stage'):
        service = services[role]
        old_manifest = json.loads(Path(service['baseline_payload']['EnvironmentVariables']['V4_RELEASE_MANIFEST_PATH']).read_text())
        new_manifest = json.loads(Path(service['manifest']).read_text())
        # Strict inventory was checked above; confirm every non-delta byte hash.
        before = {item['path']: item for item in old_manifest['app_files']}
        after = {item['path']: item for item in new_manifest['app_files']}
        allowed = {e['target'] for e in delta['entries'] if e['scope'] == role}
        if role == 'stage':allowed.add('stage_center_tick_config.json')
        if set(before) != set(after) or any(before[k] != after[k] for k in before if k not in allowed):
            raise ValueError('NON_DELTA_INVENTORY_DRIFT:' + role)
        for entry in (e for e in delta['entries'] if e['scope'] == role):
            checked(dict(path=entry['source'],sha256=entry['after_sha256']))
            if sha(Path(service['app_root'])/entry['target']) != entry['after_sha256']:
                raise ValueError('CANDIDATE_DELTA_BYTES_DRIFT')
    api = services['api']
    if (api['app_root'] != api['old_app_root'] or api['manifest_sha256'] != api['old_manifest_sha256']
            or Path(api['draft_plist']).read_bytes() != Path(api['live_plist']).read_bytes()):
        raise ValueError('API_MUST_REMAIN_EXACTLY_INSTALLED')
    stage = services['stage']
    old_config = json.loads(checked(packet['stage_config_before']).read_text())
    main = services['main']
    expected_config = stage_config_for_main(old_config, main, stage['release_id'])
    if json.loads((Path(stage['app_root']) / 'stage_center_tick_config.json').read_text()) != expected_config:
        raise ValueError('STAGE_CONFIG_CHANGE_OUTSIDE_OWNER_REPIN_AND_EXACT_HISTORY')
    policy_path = checked(packet['policy'])
    env = plistlib.loads(substitutions[main['live_plist']].read_bytes())['EnvironmentVariables']
    if (env['V4_RESEARCH_RETENTION_POLICY'] != str(policy_path)
            or env['V4_RESEARCH_RETENTION_POLICY_SHA256'] != packet['policy']['sha256']):
        raise ValueError('MAIN_POLICY_REFERENCE_DRIFT')
    old = json.loads(checked(packet['old_policy']).read_text())
    policy = json.loads(policy_path.read_text())
    expected = dict(old, managed_pin_inventory=packet['pins'])
    if policy != expected or policy['auto_gc_enabled'] is not False or policy['dry_run'] is not True:
        raise ValueError('POLICY_PROTECTION_DRIFT')
    pins = json.loads(checked(packet['pins']).read_text())
    if pins != migrated_pins(json.loads(checked(packet['old_pins']).read_text()), services):
        raise ValueError('PIN_PROTECTION_DRIFT')
    if pins['expected_main_app_root'] != main['app_root']:
        raise ValueError('PINS_MAIN_ROOT_DRIFT')
    for ref in pins['source_bindings']:
        if sha(substitutions.get(ref['path'], Path(ref['path']))) != ref['sha256']:
            raise ValueError('REVERSE_SOURCE_HASH_DRIFT:' + ref['path'])
    return dict(status='PASS_STORAGE_MAIN_STAGE_AND_UNCHANGED_API_TUPLE',
        source_bindings_checked=len(pins['source_bindings']),
        mode='INSTALLED' if installed else 'DRAFT_PLIST_SUBSTITUTION_ONLY',
        main_delta_scope='EXACT_RAW_SERIALIZER_BYTE_ACCOUNTING', original_seven_history_and_transition_preserved=True)




def cutover(packet_path, review_path, *, rollback=False):
    # Reuse the exact accepted transaction, with this packet's validation and
    # two-role control scope. Globals are copied, never patched in prior tools.
    transaction = FunctionType(prior.cutover.__code__,
        dict(prior.cutover.__globals__, validate=validate), 'cutover')
    return transaction(packet_path, review_path, rollback=rollback)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['prepare','validate','activate','rollback'])
    parser.add_argument('--delta', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--packet', type=Path)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--installed', action='store_true')
    args = parser.parse_args()
    if args.operation == 'prepare':result = prepare(args.delta,args.output)
    elif args.operation == 'validate':result = validate(json.loads(args.packet.read_text()),installed=args.installed)
    else:result = cutover(args.packet,args.review,rollback=args.operation=='rollback')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':main()
