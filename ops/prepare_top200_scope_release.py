"""Bounded Top200 API release plus same-identity Main policy reference.

Stage is a protected dependency, never a service-control target. Business data,
old packets, Main apps/manifests and external workbench assets remain intact.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import plistlib
import subprocess
import time
from urllib.request import urlopen

from ops import activate_daily_materials_release as service_ops
from ops.api_release_integration import inventory_digest, validate_api_manifest_shape
from ops.prepare_daily_materials_release import clone_release, frozen_inventory, seal_manifest, sha, homepage_smoke
from ops.prepare_v192_group_release import overlay, save

ROLES = ('api', 'main')
POLICY_ENV = {'V4_RESEARCH_RETENTION_POLICY', 'V4_RESEARCH_RETENTION_POLICY_SHA256'}


def record(path):
    path = Path(path)
    return {'path': str(path), 'sha256': sha(path)}


def checked(reference):
    path = Path(reference['path'])
    if path.is_symlink() or path.resolve() != path or sha(path) != reference['sha256']:
        raise ValueError('FROZEN_REFERENCE_DRIFT:' + str(path))
    return path


def assert_main_policy_only(before, after):
    before, after = deepcopy(before), deepcopy(after)
    old_env, new_env = before.pop('EnvironmentVariables'), after.pop('EnvironmentVariables')
    if before != after or {k: v for k, v in old_env.items() if k not in POLICY_ENV} != {
            k: v for k, v in new_env.items() if k not in POLICY_ENV}:
        raise ValueError('MAIN_CHANGE_OUTSIDE_TWO_POLICY_REFERENCES')


def _service(plist_path):
    plist_path = Path(plist_path)
    payload = plistlib.loads(plist_path.read_bytes())
    env = payload['EnvironmentVariables']
    manifest = Path(env['V4_RELEASE_MANIFEST_PATH'])
    if sha(manifest) != env['V4_RELEASE_MANIFEST_SHA256']:
        raise ValueError('BASELINE_MANIFEST_PIN_DRIFT')
    return dict(live_plist=str(plist_path), before_sha256=sha(plist_path), label=payload['Label'],
        old_app_root=env['V4_APP_ROOT'], old_manifest_sha256=env['V4_RELEASE_MANIFEST_SHA256'],
        app_root=env['V4_APP_ROOT'], manifest=str(manifest), manifest_sha256=sha(manifest),
        release_id=env['V4_RELEASE_ID'], baseline_payload=payload)


def prepare(delta_path: Path, output: Path):
    approved = Path.home() / 'Library/Application Support/com.lexi.v4.local/candidates'
    if (not output.is_absolute() or not output.is_relative_to(approved) or output == approved
            or output.resolve() != output or output.exists()):
        raise ValueError('NEW_LIBRARY_CANDIDATE_REQUIRED')
    delta = json.loads(delta_path.read_text())
    entries = delta.get('entries')
    if entries is None:
        entries = [dict(item, target=item['target_relative'], scope='api') for item in delta['changes']]
    if any(item.get('scope', 'api') != 'api' for item in entries):
        raise ValueError('API_INTERNAL_SOURCE_AND_FRONTEND_DELTA_ONLY')
    if len({item['target'] for item in entries}) != len(entries):
        raise ValueError('DUPLICATE_DELTA_TARGET')
    home = Path.home() / 'Library/LaunchAgents'
    api = _service(home / 'com.lexi.v4.api.plist')
    main = _service(home / 'com.lexi.v4.scheduler.plist')
    stage = _service(home / 'com.lexi.stage-center.scheduler.plist')
    if api['release_id'] != 'v4-v192-assets-20261109-r1-api':
        raise ValueError('EXACT_CURRENT_API_RELEASE_REQUIRED')
    if api['manifest_sha256'] != '446e8e7b606d035dd277264adcd912f330f7aae58fb9037ca1f27dd33ac82f5e':
        raise ValueError('EXACT_CURRENT_API_MANIFEST_REQUIRED')
    if delta.get('active_api_root', api['app_root']) != api['app_root'] or delta.get('deletions'):
        raise ValueError('EXACT_BASELINE_AND_NO_DELETIONS_REQUIRED')
    output.mkdir()
    old_app = Path(api['app_root'])
    rid = output.name + '-api'
    release = output / rid
    release.mkdir()
    app = release / 'app'
    manifest = json.loads(Path(api['manifest']).read_text())
    clone_release(old_app, app, manifest)
    changed = set()
    for item in entries:
        overlay(app, item)
        changed.add(item['target'])
    updated = seal_manifest(manifest, app=app, release_id=rid, role='api', delta_paths=changed,
                            base_manifest=Path(api['manifest']))
    manifest_path = release / 'release-manifest.json'
    save(manifest_path, updated)
    api_payload = deepcopy(api['baseline_payload'])
    api_payload['WorkingDirectory'] = str(app)
    api_payload['EnvironmentVariables'].update(V4_APP_ROOT=str(app), V4_RELEASE_ID=rid,
        V4_RELEASE_MANIFEST_PATH=str(manifest_path), V4_RELEASE_MANIFEST_SHA256=sha(manifest_path))
    api_draft = output / 'API_CANDIDATE.plist'
    api_draft.write_bytes(plistlib.dumps(api_payload, sort_keys=True))
    api_draft.chmod(0o600)
    api.update(app_root=str(app), release_id=rid, manifest=str(manifest_path),
               manifest_sha256=sha(manifest_path), draft_plist=str(api_draft), draft_plist_sha256=sha(api_draft))
    old_policy = Path(main['baseline_payload']['EnvironmentVariables']['V4_RESEARCH_RETENTION_POLICY'])
    old_policy_sha = main['baseline_payload']['EnvironmentVariables']['V4_RESEARCH_RETENTION_POLICY_SHA256']
    if sha(old_policy) != old_policy_sha:
        raise ValueError('LIVE_POLICY_PIN_DRIFT')
    policy = json.loads(old_policy.read_text())
    old_pins = checked(policy['managed_pin_inventory'])
    pins = json.loads(old_pins.read_text())
    if any(ref['path'] == main['live_plist'] for ref in pins['source_bindings']):
        raise ValueError('MAIN_PLIST_REVERSE_PIN_WOULD_CREATE_CYCLE')
    for ref in pins['source_bindings']:
        if ref['path'] == api['live_plist']:
            ref['sha256'] = sha(api_draft)
        elif ref['path'].startswith(str(old_app) + '/'):
            ref['path'] = str(app) + ref['path'][len(str(old_app)):]
            ref['sha256'] = sha(Path(ref['path']))
        elif sha(Path(ref['path'])) != ref['sha256']:
            raise ValueError('UNRELATED_SOURCE_BINDING_DRIFT:' + ref['path'])
    pins_path = output / 'research_storage_pins.json'
    save(pins_path, pins)
    policy['managed_pin_inventory'] = record(pins_path)
    policy_path = output / 'research_storage_policy.json'
    save(policy_path, policy)
    main_payload = deepcopy(main['baseline_payload'])
    main_payload['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=str(policy_path),
        V4_RESEARCH_RETENTION_POLICY_SHA256=sha(policy_path))
    assert_main_policy_only(main['baseline_payload'], main_payload)
    main_draft = output / 'MAIN_POLICY_CANDIDATE.plist'
    main_draft.write_bytes(plistlib.dumps(main_payload, sort_keys=True))
    main_draft.chmod(0o600)
    main.update(draft_plist=str(main_draft), draft_plist_sha256=sha(main_draft))
    frozen = output / 'FROZEN_DELTA.json'
    frozen.write_bytes(delta_path.read_bytes())
    protected = [record(stage['live_plist']), record(stage['manifest']), record(main['manifest']),
                 record(api['baseline_payload']['EnvironmentVariables']['V4_RELEASE_MANIFEST_PATH']),
                 record(stage['baseline_payload']['EnvironmentVariables']['STAGE_CENTER_CONFIG']),
                 record(old_policy), record(old_pins)]
    if delta.get('build_input_manifest'):
        protected.append(dict(delta['build_input_manifest']))
    # External workbench/static/data bindings remain inherited at their actual
    # R1 addresses. Only the native Vue dist inside the API app is updated.
    for key in ('V4_RESEARCH_PANEL_ASSET_MANIFEST', 'V4_WORKBENCH_HOST_BINDING'):
        if api['baseline_payload']['EnvironmentVariables'].get(key):
            protected.append(record(api['baseline_payload']['EnvironmentVariables'][key]))
    source_root = Path(__file__).resolve().parents[1]
    packet = dict(schema='v4.top200_scope_api_release.v1', status='PREPARED_NOT_ACTIVATED',
        root=str(output), services={'api': api, 'main': main}, stage=stage,
        protected_references=protected, delta=record(frozen), policy=record(policy_path), pins=record(pins_path),
        old_policy=record(old_policy), old_pins=record(old_pins),
        scheduler_lane_lock_root=str(Path.home() / 'Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners'),
        tool_source_files=[record(path) for path in (Path(__file__),
            source_root / 'ops/activate_daily_materials_release.py',
            source_root / 'ops/prepare_daily_materials_release.py', source_root / 'ops/prepare_v192_group_release.py')],
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    save(output / 'PACKET.json', packet)
    result = validate(packet)
    save(output / 'DEPENDENCY_CHECK.json', result)
    return {'packet': str(output / 'PACKET.json'), 'packet_sha256': sha(output / 'PACKET.json'), 'check': result}


def _inventory(service):
    path = Path(service['manifest'])
    if sha(path) != service['manifest_sha256']:
        raise ValueError('MANIFEST_DRIFT')
    manifest = json.loads(path.read_text())
    inv = manifest['application_inventory']
    if (inv['entry_count'] != len(inv['entries']) or inventory_digest(inv['entries']) != inv['aggregate_sha256']
            or frozen_inventory(Path(service['app_root']), inv['entries']) != inv['entries']):
        raise ValueError('FROZEN_APPLICATION_DRIFT')
    identity = manifest['candidate'] if manifest['schema_version'] == 'v4.release_candidate.v1' else manifest
    if identity.get('app_root') != service['app_root'] or identity.get('release_id') != service['release_id']:
        raise ValueError('MANIFEST_IDENTITY_DRIFT')
    return manifest


def loaded_environment_check(service):
    state, pid = service_ops.loaded(service['label'])
    env = plistlib.loads(Path(service['live_plist']).read_bytes())['EnvironmentVariables']
    names = ('V4_APP_ROOT', 'V4_RELEASE_ID', 'V4_RELEASE_MANIFEST_SHA256')
    if service['label'] == 'com.lexi.v4.scheduler':
        names += tuple(sorted(POLICY_ENV))
    if not pid or 'state = running' not in state.stdout or any(env[name] not in state.stdout for name in names):
        raise ValueError('LOADED_ENVIRONMENT_PIN_DRIFT:' + service['label'])
    return pid


def exact_homepage(service, *, rollback=False):
    env = service['baseline_payload']['EnvironmentVariables'] if rollback else plistlib.loads(
        Path(service['draft_plist']).read_bytes())['EnvironmentVariables']
    deadline = time.monotonic() + 60
    while True:
        try:
            with urlopen('http://127.0.0.1:8873/api/v1/runs/date-list', timeout=30) as response:
                dates = json.load(response)
            with urlopen('http://127.0.0.1:8873/api/v4/runtime-graph/frontend-build', timeout=30) as response:
                front = json.load(response)
            identity = dates['runtime_identity']
            if (identity['status'] != 'MANIFEST_EXECUTION_FILES_VERIFIED'
                    or identity['release_id'] != env['V4_RELEASE_ID']
                    or identity['manifest_sha256'] != env['V4_RELEASE_MANIFEST_SHA256']
                    or front['status'] != 'VERIFIED' or front['api_release_id'] != env['V4_RELEASE_ID']
                    or front['api_manifest_sha256'] != env['V4_RELEASE_MANIFEST_SHA256']):
                raise ValueError('SERVING_API_IDENTITY_DOES_NOT_MATCH_CUTOVER')
            return {'runtime_identity': identity, 'frontend_build': front}
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.3)


def validate(packet, *, installed=False, restored=False):
    root = Path(packet['root'])
    approved = Path.home() / 'Library/Application Support/com.lexi.v4.local/candidates'
    if not root.is_relative_to(approved) or root.resolve() != root:
        raise ValueError('LIBRARY_CANDIDATE_ROOT_REQUIRED')
    for ref in packet['tool_source_files'] + packet['protected_references'] + [packet['delta']]:
        checked(ref)
    substitutes = {}
    for role in ROLES:
        service = packet['services'][role]
        checked({'path': service['draft_plist'], 'sha256': service['draft_plist_sha256']})
        expected = service['before_sha256'] if restored or not installed else service['draft_plist_sha256']
        if sha(Path(service['live_plist'])) != expected:
            raise ValueError('LIVE_CAS_DRIFT:' + role)
        path = Path(service['live_plist']) if installed or restored else Path(service['draft_plist'])
        substitutes[service['live_plist']] = path
    if restored:
        return {'status': 'RESTORED_ORIGINAL_API_AND_MAIN_POLICY_TUPLE_STAGE_UNCHANGED'}
    main = packet['services']['main']
    assert_main_policy_only(main['baseline_payload'], plistlib.loads(substitutes[main['live_plist']].read_bytes()))
    if main['app_root'] != main['old_app_root'] or main['manifest_sha256'] != main['old_manifest_sha256']:
        raise ValueError('MAIN_IDENTITY_MUST_REMAIN_UNCHANGED')
    _inventory(main)
    _inventory(packet['stage'])
    api = packet['services']['api']
    base_env = api['baseline_payload']['EnvironmentVariables']
    _inventory(dict(api, app_root=api['old_app_root'], manifest=base_env['V4_RELEASE_MANIFEST_PATH'],
                    manifest_sha256=api['old_manifest_sha256'], release_id=base_env['V4_RELEASE_ID']))
    validate_api_manifest_shape(_inventory(api))
    ap = plistlib.loads(substitutes[api['live_plist']].read_bytes())
    env = ap['EnvironmentVariables']
    if (ap['WorkingDirectory'] != api['app_root'] or any(env[k] != api[v] for k, v in (
            ('V4_APP_ROOT', 'app_root'), ('V4_RELEASE_ID', 'release_id'),
            ('V4_RELEASE_MANIFEST_PATH', 'manifest'), ('V4_RELEASE_MANIFEST_SHA256', 'manifest_sha256')))):
        raise ValueError('API_PLIST_IDENTITY_DRIFT')
    baseline = deepcopy(api['baseline_payload'])
    expected_api = deepcopy(baseline)
    expected_api['WorkingDirectory'] = api['app_root']
    expected_api['EnvironmentVariables'].update(V4_APP_ROOT=api['app_root'], V4_RELEASE_ID=api['release_id'],
        V4_RELEASE_MANIFEST_PATH=api['manifest'], V4_RELEASE_MANIFEST_SHA256=api['manifest_sha256'])
    if ap != expected_api:
        raise ValueError('API_ENV_OR_BINDING_CHANGE_OUTSIDE_RELEASE_IDENTITY')
    main_env = plistlib.loads(substitutes[main['live_plist']].read_bytes())['EnvironmentVariables']
    policy_path = checked(packet['policy'])
    if (main_env['V4_RESEARCH_RETENTION_POLICY'] != str(policy_path)
            or main_env['V4_RESEARCH_RETENTION_POLICY_SHA256'] != packet['policy']['sha256']):
        raise ValueError('MAIN_POLICY_ENV_DRIFT')
    policy = json.loads(policy_path.read_text())
    old = json.loads(checked(packet['old_policy']).read_text())
    compare = deepcopy(policy)
    compare['managed_pin_inventory'] = old['managed_pin_inventory']
    if compare != old:
        raise ValueError('POLICY_PROTECTION_OR_PARAMETER_CHANGED')
    if policy['managed_pin_inventory'] != packet['pins']:
        raise ValueError('POLICY_PINS_REFERENCE_DRIFT')
    pins = json.loads(checked(packet['pins']).read_text())
    expected_pins = json.loads(checked(packet['old_pins']).read_text())
    for ref in expected_pins['source_bindings']:
        if ref['path'] == api['live_plist']:
            ref['sha256'] = api['draft_plist_sha256']
        elif ref['path'].startswith(api['old_app_root'] + '/'):
            ref['path'] = api['app_root'] + ref['path'][len(api['old_app_root']):]
            ref['sha256'] = sha(Path(ref['path']))
    if pins != expected_pins:
        raise ValueError('PIN_PROTECTION_CHANGED_OUTSIDE_API_DEPENDENCY_MIGRATION')
    if pins['expected_main_app_root'] != main['app_root']:
        raise ValueError('PINNED_MAIN_ROOT_CHANGED')
    for ref in pins['source_bindings']:
        actual = substitutes.get(ref['path'], Path(ref['path']))
        if sha(actual) != ref['sha256']:
            raise ValueError('REVERSE_REFERENCE_DRIFT:' + ref['path'])
    return {'status': 'PASS_API_AND_SAME_IDENTITY_MAIN_DEPENDENCY_TUPLE_STAGE_UNCHANGED',
            'source_bindings_checked': len(pins['source_bindings']),
            'mode': 'INSTALLED' if installed else 'DRAFT_PLIST_SUBSTITUTION_ONLY'}


def cutover(packet_path, review_path, *, rollback=False):
    packet = json.loads(packet_path.read_text())
    review = json.loads(review_path.read_text())
    if review.get('verdict') not in {'PASS', 'REVIEWED/PASS'} or review.get('packet_sha256') != sha(packet_path):
        raise ValueError('INDEPENDENT_REVIEW_PACKET_BINDING_REQUIRED')
    validate(packet, installed=rollback)
    services = packet['services']
    backup = packet_path.parent / 'api-main-backup'
    backup.mkdir(exist_ok=True)
    held, stopped, changed = [], [], []
    state = dict(status='PRECHECK', rollback_requested=rollback, stopped=stopped, changed=changed,
                 stage_service_operation=False, business_data_written=False)
    try:
        if rollback:
            service_ops.require_previous_backups(services, backup)
        else:
            for role, service in services.items():
                path = backup / (role + '.plist')
                live = Path(service['live_plist'])
                if path.exists() and path.read_bytes() != live.read_bytes():
                    raise ValueError('EXISTING_BACKUP_DIFFERENT')
                path.write_bytes(live.read_bytes())
                path.chmod(0o600)
        for name in ('DEFAULT.lock', 'A_LONG.lock'):
            stream = (Path(packet['scheduler_lane_lock_root']) / name).open('a+')
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(stream)
        service_ops.require_idle_main(services['main'])
        for role in ('main', 'api'):
            s = services[role]
            current, pid = service_ops.loaded(s['label'])
            expected = s['app_root'] if rollback else s['old_app_root']
            expected_sha = s['manifest_sha256'] if rollback else s['old_manifest_sha256']
            if (current.returncode != 0 or not pid or 'state = running' not in current.stdout
                    or expected not in current.stdout or expected_sha not in current.stdout):
                raise ValueError('LOADED_SERVICE_IDENTITY_DRIFT:' + role)
            tracked = service_ops.descendants(pid)
            response = service_ops.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{s["label"]}'])
            response.check_returncode()
            stopped.append(role)
            service_ops.wait_drained(s['label'], tracked, api=role == 'api')
        for role in ROLES:
            s = services[role]
            source = backup / (role + '.plist') if rollback else Path(s['draft_plist'])
            expected = s['draft_plist_sha256'] if rollback else s['before_sha256']
            service_ops.replace_cas(Path(s['live_plist']), source, expected)
            changed.append(role)
        validate(packet, installed=not rollback, restored=rollback)
        for role in ROLES:
            s = services[role]
            service_ops.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', s['live_plist']]).check_returncode()
            expected = dict(s, app_root=s['old_app_root'], manifest_sha256=s['old_manifest_sha256']) if rollback else s
            service_ops.wait_running(expected)
            loaded_environment_check(s)
        state['homepage'] = exact_homepage(services['api'], rollback=rollback)
        validate(packet, installed=not rollback, restored=rollback)
        state['status'] = 'RESTORED_ORIGINAL_API_MAIN_STAGE_UNCHANGED' if rollback else 'ACTIVATED_API_AND_SAME_IDENTITY_MAIN_STAGE_UNCHANGED'
    except BaseException as error:
        state.update(status='FAILED', error=type(error).__name__ + ':' + str(error))
        if not rollback and stopped:
            try:
                state['recovery'] = service_ops.restore_services(services, backup, stopped)
                validate(packet, restored=True)
                for role in stopped:
                    loaded_environment_check(services[role])
                state['recovery']['exact_homepage'] = exact_homepage(services['api'], rollback=True)
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
    p = argparse.ArgumentParser()
    p.add_argument('operation', choices=['prepare', 'validate', 'activate', 'rollback'])
    p.add_argument('--delta', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--packet', type=Path)
    p.add_argument('--review', type=Path)
    p.add_argument('--installed', action='store_true')
    a = p.parse_args()
    if a.operation == 'prepare':
        result = prepare(a.delta, a.output)
    elif a.operation == 'validate':
        result = validate(json.loads(a.packet.read_text()), installed=a.installed)
    else:
        result = cutover(a.packet, a.review, rollback=a.operation == 'rollback')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
