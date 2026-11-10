"""Close A09:25 algorithm identity across Stage, API and Main consumers.

A new Main carries only its explicit compatibility delta. Stage preserves old
Main authority as exact historical provenance; no business jobs are replayed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import plistlib

from ops import activate_daily_materials_release as svc
from ops.api_release_integration import validate_api_manifest_shape
from ops.prepare_daily_materials_release import clone_release, seal_manifest, sha
from ops.prepare_top200_scope_release import (
    _inventory, _service, checked, exact_homepage,
    loaded_environment_check, record,
)
from ops.prepare_v192_group_release import overlay, save


BASELINES = {
    'api': '4d24d947cfbae389f38bfb7f0a65800abd3f34ac50bceff3dabafc0076a8a618',
    'main': '29ac5b4f0b5330085b97058a74b3a2f49a822a555e0c5f65537a98bffd2bebdf',
    'stage': 'ac6813892f098aae57c3c0edcc4ff4ce595f7c6bcac2954a2b6f8edbc0f721f0',
}
LABELS = {'api': 'com.lexi.v4.api', 'main': 'com.lexi.v4.scheduler',
          'stage': 'com.lexi.stage-center.scheduler'}


def expected_plist(service, role):
    payload = deepcopy(service['baseline_payload'])
    payload['WorkingDirectory'] = service['app_root']
    payload['EnvironmentVariables'].update(V4_APP_ROOT=service['app_root'],
        V4_RELEASE_ID=service['release_id'], V4_RELEASE_MANIFEST_PATH=service['manifest'],
        V4_RELEASE_MANIFEST_SHA256=service['manifest_sha256'])
    if role in {'main', 'stage'}:
        old = service['old_app_root']
        payload['ProgramArguments'] = [service['app_root'] + v[len(old):]
            if v.startswith(old + '/') else v for v in payload['ProgramArguments']]
    if role == 'stage':
        old = service['old_app_root']
        payload['EnvironmentVariables']['STAGE_CENTER_CONFIG'] = str(
            Path(service['app_root']) / 'stage_center_tick_config.json')
        pythonpath = payload['EnvironmentVariables']['PYTHONPATH'].split(os.pathsep)
        if pythonpath[0] != old + '/upstreams' or any(old in item for item in pythonpath[1:]):
            raise ValueError('STAGE_PYTHONPATH_BASELINE_BINDING_DRIFT')
        pythonpath[0] = service['app_root'] + '/upstreams'
        payload['EnvironmentVariables']['PYTHONPATH'] = os.pathsep.join(pythonpath)
    return payload


def stage_config_for_main(old_config, main, release_id):
    config = deepcopy(old_config)
    previous = dict(app_root=main['old_app_root'],
        release_id=main['baseline_payload']['EnvironmentVariables']['V4_RELEASE_ID'],
        manifest_path=main['baseline_payload']['EnvironmentVariables']['V4_RELEASE_MANIFEST_PATH'],
        manifest_sha256=main['old_manifest_sha256'])
    if config['research_owner_binding'] != previous or len(config['research_historical_owner_bindings']) != 6:
        raise ValueError('EXACT_PREVIOUS_MAIN_AND_SIX_HISTORY_REQUIRED')
    if any(item['app_root'] == previous['app_root'] for item in config['research_historical_owner_bindings']):
        raise ValueError('PREVIOUS_MAIN_ALREADY_HISTORICAL')
    config['release_id'] = release_id
    config['research_owner_binding'] = dict(app_root=main['app_root'], release_id=main['release_id'],
        manifest_path=main['manifest'], manifest_sha256=main['manifest_sha256'])
    config['research_historical_owner_bindings'].append(previous)
    return config


def migrated_pins(old_pins, services):
    pins = deepcopy(old_pins)
    main = services['main']
    if any(r['path'] == main['live_plist'] for r in pins['source_bindings']):
        raise ValueError('MAIN_PLIST_REVERSE_PIN_CYCLE')
    pins['expected_main_app_root'] = main['app_root']
    for ref in pins['source_bindings']:
        for role in ('api', 'main', 'stage'):
            service = services[role]
            if ref['path'] == service['live_plist']:
                ref['sha256'] = service['draft_plist_sha256']
            elif ref['path'].startswith(service['old_app_root'] + '/'):
                ref['path'] = service['app_root'] + ref['path'][len(service['old_app_root']):]
                ref['sha256'] = sha(Path(ref['path']))
    return pins


def prepare(delta_path, output):
    approved = Path.home() / 'Library/Application Support/com.lexi.v4.local/candidates'
    if (not output.is_absolute() or not output.is_relative_to(approved) or output == approved
            or output.resolve() != output or output.exists()):
        raise ValueError('NEW_LIBRARY_CANDIDATE_REQUIRED')
    delta = json.loads(delta_path.read_text())
    entries = delta['entries']
    if (not entries or any(e['scope'] not in {'api', 'main', 'stage'} for e in entries)
            or {e['scope'] for e in entries} != {'api', 'main', 'stage'} or delta.get('deletions')
            or [(e['scope'],e['target'])for e in entries if e['scope']=='main'] != [('main','stage_center/selection.py')]
            or len({(e['scope'], e['target']) for e in entries}) != len(entries)
            or any(e['target'] == 'stage_center_tick_config.json' for e in entries)):
        raise ValueError('EXPLICIT_THREE_CONSUMER_SOURCE_DELTA_ONLY')
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
        draft.write_bytes(plistlib.dumps(expected_plist(service, role), sort_keys=True))
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
    tool_paths = [Path(__file__), root / 'ops/prepare_top200_scope_release.py',
        root / 'ops/activate_daily_materials_release.py', root / 'ops/prepare_daily_materials_release.py',
        root / 'ops/prepare_v192_group_release.py', root / 'ops/api_release_integration.py']
    roles = ['api', 'main', 'stage']
    packet = dict(schema='v4.a925_main_consumer_closure_release.v1', status='PREPARED_NOT_ACTIVATED',
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
    expected_roles = ['api', 'main', 'stage']
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
    return dict(status='PASS_ALL_THREE_ALGORITHM_CONSUMERS_AND_EXACT_OWNER_HISTORY_TUPLE',
        source_bindings_checked=len(pins['source_bindings']),
        mode='INSTALLED' if installed else 'DRAFT_PLIST_SUBSTITUTION_ONLY',
        main_delta_scope='ONE_EXPLICIT_COMPATIBILITY_SOURCE', original_six_history_and_transition_preserved=True)


def require_idle_stage(service):
    state, pid = svc.loaded(service['label'])
    if state.returncode != 0 or pid or 'state = running' in state.stdout:
        raise RuntimeError('STAGE_NOT_CALENDAR_IDLE_NO_CUTOVER')


def stage_loaded_environment(service):
    state, _ = svc.loaded(service['label'])
    env = plistlib.loads(Path(service['live_plist']).read_bytes())['EnvironmentVariables']
    names = ('V4_APP_ROOT', 'V4_RELEASE_ID', 'V4_RELEASE_MANIFEST_SHA256', 'STAGE_CENTER_CONFIG')
    if state.returncode != 0 or any(env[name] not in state.stdout for name in names):
        raise RuntimeError('STAGE_LOADED_IDENTITY_DRIFT')


def cutover(packet_path, review_path, *, rollback=False):
    packet = json.loads(packet_path.read_text())
    review = json.loads(review_path.read_text())
    if review.get('verdict') not in {'PASS', 'REVIEWED/PASS'} or review.get('packet_sha256') != sha(packet_path):
        raise ValueError('INDEPENDENT_REVIEW_PACKET_BINDING_REQUIRED')
    validate(packet, installed=rollback)
    services = packet['services']
    controlled = {r: services[r] for r in packet['control_roles']}
    held, stopped, changed = [], [], []
    backup = packet_path.parent / 'cutover-backup'
    backup.mkdir(exist_ok=True)
    state = dict(status='PRECHECK', rollback_requested=rollback, stopped=stopped, changed=changed,
                 business_data_written=False, historical_receipts_replayed=False)
    try:
        if rollback:
            svc.require_previous_backups(controlled, backup)
        for name in ('DEFAULT.lock', 'A_LONG.lock'):
            stream = (Path(packet['scheduler_lane_lock_root']) / name).open('a+')
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(stream)
        svc.require_idle_main(services['main'])
        require_idle_stage(services['stage'])
        for role in packet['control_roles']:
            s = services[role]
            current, pid = svc.loaded(s['label'])
            expected_root = s['app_root'] if rollback else s['old_app_root']
            expected_sha = s['manifest_sha256'] if rollback else s['old_manifest_sha256']
            if (current.returncode != 0 or expected_root not in current.stdout or expected_sha not in current.stdout
                    or role != 'stage' and (not pid or 'state = running' not in current.stdout)):
                raise RuntimeError('LOADED_SERVICE_IDENTITY_DRIFT:' + role)
            if not rollback:
                destination = backup / (role + '.plist')
                live = Path(s['live_plist'])
                if destination.exists() and destination.read_bytes() != live.read_bytes():
                    raise RuntimeError('PREVIOUS_BACKUP_DIFFERENT:' + role)
                destination.write_bytes(live.read_bytes())
                destination.chmod(0o600)
        # Stage is checked again immediately before bootout so a newly started
        # calendar run is never killed merely to install a candidate.
        for role in ('stage', 'main', 'api'):
            if role not in controlled:
                continue
            s = services[role]
            if role == 'stage':
                require_idle_stage(s)
            current, pid = svc.loaded(s['label'])
            tracked = svc.descendants(pid)
            svc.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{s["label"]}']).check_returncode()
            stopped.append(role)
            svc.wait_drained(s['label'], tracked, api=role == 'api')
        for role in packet['control_roles']:
            s = services[role]
            source = backup / (role + '.plist') if rollback else Path(s['draft_plist'])
            expected = s['draft_plist_sha256'] if rollback else s['before_sha256']
            svc.replace_cas(Path(s['live_plist']), source, expected)
            changed.append(role)
        validate(packet, installed=not rollback, restored=rollback)
        for role in ('api', 'main', 'stage'):
            if role not in controlled:
                continue
            s = services[role]
            svc.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', s['live_plist']]).check_returncode()
            if role == 'stage':
                stage_loaded_environment(s)
            else:
                expected = dict(s, app_root=s['old_app_root'], manifest_sha256=s['old_manifest_sha256']) if rollback else s
                svc.wait_running(expected)
                loaded_environment_check(s)
        state['homepage'] = exact_homepage(services['api'], rollback=rollback)
        validate(packet, installed=not rollback, restored=rollback)
        state['status'] = 'RESTORED_BASELINE_TUPLE' if rollback else 'ACTIVATED_STAGE_API_MAIN_COMPATIBILITY_AND_OWNER_CLOSURE'
    except BaseException as error:
        state.update(status='FAILED', error=type(error).__name__ + ':' + str(error))
        if not rollback and stopped:
            try:
                state['recovery'] = svc.restore_services(controlled, backup, stopped)
                validate(packet, restored=True)
                for role in stopped:
                    stage_loaded_environment(services[role]) if role == 'stage' else loaded_environment_check(services[role])
                state['recovery']['homepage'] = exact_homepage(services['api'], rollback=True)
            except BaseException as recovery:
                state['recovery'] = dict(status='CANNOT_CONFIRM_REQUIRES_CONTROLLER', error=str(recovery))
        raise
    finally:
        save(packet_path.parent / 'ACTIVATION_RECEIPT.json', state)
        for stream in reversed(held):
            fcntl.flock(stream, fcntl.LOCK_UN)
            stream.close()
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['prepare', 'validate', 'activate', 'rollback'])
    parser.add_argument('--delta', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--packet', type=Path)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--installed', action='store_true')
    args = parser.parse_args()
    if args.operation == 'prepare':
        result = prepare(args.delta, args.output)
    elif args.operation == 'validate':
        result = validate(json.loads(args.packet.read_text()), installed=args.installed)
    else:
        result = cutover(args.packet, args.review, rollback=args.operation == 'rollback')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
