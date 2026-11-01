#!/usr/bin/env python3
"""Prepare the exact F10/Stage binding repair; no activation or data writes."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess

from ops.prepare_stage_four_repairs import no_alias, write, dump

LOCAL = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
SOURCE_BASELINE = 'ca20c4edf4f715cf075da0eb9c309aec055bf0d7'
ROLE_PINS = {
    'main': ('com.lexi.v4.scheduler', LOCAL/'candidates/f10-daily-20261101-c94609b4e5fff848-main/app',
             '3f9a184c28884411bfc79872b44e6b2189cd33a44bc8413da0f79b9644a83388'),
    'stage': ('com.lexi.stage-center.scheduler', LOCAL/'candidates/stage-four-repairs-20261101-r3/stage-four-repairs-20261101-r3-stage/app',
              'ff62078ab7fb5d05318233fbfab18bd34408a0fc5b162359080c080633ee4115'),
    'api': ('com.lexi.v4.api', LOCAL/'candidates/junda-single-20261101-52b837fa7688cb5d/app',
            '0e142b6ae23ee825182893653df24f1bfb48c76d384d69507a9e4c5fd025d341'),
}
MANUAL_REL = 'config/api-v4_manual_collection_stage_config.json'
ATTESTATION = 'infrastructure/manager_input_attestation.py'
IDENTITY = ('V4_APP_ROOT', 'V4_RELEASE_ID', 'V4_RELEASE_MANIFEST_PATH', 'V4_RELEASE_MANIFEST_SHA256')
EXPECTED_HISTORY = ['a-daily-name-zoom-20261030-r1-main', 'a-daily-sop-closure-20261029-r1-main']


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def loaded_role(label, app, pin):
    path = Path.home()/'Library/LaunchAgents'/f'{label}.plist'
    raw = path.read_bytes()
    disk = plistlib.loads(raw)
    env = disk['EnvironmentVariables']
    printed = subprocess.check_output(['launchctl', 'print', f'gui/{os.getuid()}/{label}'], text=True)
    loaded = {}
    for line in printed.splitlines():
        if '=>' in line:
            key, value = line.strip().split('=>', 1)
            if key.strip() in env:
                loaded[key.strip()] = value.strip()
    expected = dict(zip(IDENTITY, (str(app), app.parent.name, str(app.parent/'release-manifest.json'), pin)))
    if any(env.get(k) != v or loaded.get(k) != v for k, v in expected.items()):
        raise ValueError('LOADED_ROLE_IDENTITY_CHANGED:'+label)
    # Do not rebase away another task's current panel/config environment.
    if any(loaded.get(k) != env[k] for k in env if k.startswith('V4_')):
        raise ValueError('LOADED_ROLE_ENVIRONMENT_DIFFERS_FROM_PLIST:'+label)
    return {'label': label, 'plist_path': str(path), 'plist_sha256': sha(raw),
            'environment': env, 'program_arguments': disk['ProgramArguments'],
            'working_directory': disk['WorkingDirectory']}


def inventory_tools(app):
    spec = importlib.util.spec_from_file_location('f10_official_inventory', app/'ops/api_release_integration.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verified_baseline(app, pin, tools):
    no_alias(app)
    raw = (app.parent/'release-manifest.json').read_bytes()
    if sha(raw) != pin:
        raise ValueError('BASE_MANIFEST_CAS_CHANGED:'+str(app))
    manifest = json.loads(raw)
    entries = tools.inventory_tree(app)
    if manifest['application_inventory'] != {'entries': entries, 'entry_count': len(entries),
                                            'aggregate_sha256': tools.inventory_digest(entries)}:
        raise ValueError('BASE_INVENTORY_DRIFT:'+str(app))
    return manifest, entries



def release_proposals(output, receipt):
    """Review-only preimages and plist bytes, following the existing staged shape."""
    directory = output/'release-proposal'; directory.mkdir()
    proposals = {}
    for role in ('stage', 'api'):
        before = receipt['actual_role_baselines'][role]
        raw = Path(before['plist_path']).read_bytes()
        if sha(raw) != before['plist_sha256']:
            raise ValueError('PLIST_PREIMAGE_CHANGED:'+role)
        payload = plistlib.loads(raw); after = copy.deepcopy(payload)
        new = receipt['roles'][role]['app_root']; old = before['environment']['V4_APP_ROOT']
        after['WorkingDirectory'] = new
        if role == 'stage':
            after['ProgramArguments'] = [s.replace(old, new) for s in after['ProgramArguments']]
        after['EnvironmentVariables'] = receipt['proposed_environment'][role]
        staged = plistlib.dumps(after, sort_keys=True)
        (directory/(role+'.original.plist')).write_bytes(raw)
        (directory/(role+'.proposed.plist')).write_bytes(staged)
        proposals[role] = {'status': 'PROPOSAL_ONLY_NOT_APPLIED', 'label': before['label'],
            'original_plist_path': before['plist_path'], 'original_sha256': sha(raw),
            'copied_preimage': str(directory/(role+'.original.plist')),
            'proposed_plist': str(directory/(role+'.proposed.plist')), 'proposed_sha256': sha(staged),
            'cwd': new, 'argv': after['ProgramArguments'],
            'changed_environment_keys': [k for k, v in after['EnvironmentVariables'].items()
                                         if before['environment'].get(k) != v]}
    dump(output/'release-proposal.json', proposals)
    return proposals


def prepare(output, source):
    no_alias(output); no_alias(source)
    if output.parent != LOCAL/'candidates' or output.exists():
        raise ValueError('NEW_ISOLATED_CANDIDATE_ROOT_REQUIRED')
    roles = {role: loaded_role(*values) for role, values in ROLE_PINS.items()}
    tools = inventory_tools(ROLE_PINS['api'][1])
    baselines = {role: verified_baseline(app, pin, tools) for role, (_, app, pin) in ROLE_PINS.items()}
    stage_base = ROLE_PINS['stage'][1]
    cfg = json.loads((stage_base/'stage_center_tick_config.json').read_bytes())
    if (cfg['research_owner_binding']['release_id'] != 'workbench-daily-chain-20261031-r6-main'
        or [r['release_id'] for r in cfg['research_historical_owner_bindings']] != EXPECTED_HISTORY):
        raise ValueError('STAGE_BASE_BINDINGS_CHANGED')
    active_attestation = (stage_base/ATTESTATION).read_bytes()
    patched = (source/ATTESTATION).read_bytes()
    if active_attestation.count(b'len(historical) > 2') != 1 or patched != active_attestation.replace(b'len(historical) > 2', b'len(historical) > 3'):
        raise ValueError('ATTESTATION_DELTA_NOT_EXACT_ACTIVE_MAX3')
    manual_path = Path(roles['api']['environment']['V4_MANUAL_COLLECTION_STAGE_CONFIG'])
    no_alias(manual_path)
    manual_raw = manual_path.read_bytes(); manual = json.loads(manual_raw)
    if manual['stage_owner_root'] != str(stage_base):
        raise ValueError('CURRENT_MANUAL_STAGE_OWNER_CHANGED')
    panel_env = {key: value for key, value in roles['api']['environment'].items()
                 if key.startswith(('V4_RESEARCH_PANEL_', 'V4_WORKBENCH_'))}
    external = {}
    for key in ('V4_RESEARCH_PANEL_ASSET_MANIFEST', 'V4_WORKBENCH_HOST_BINDING'):
        path = Path(panel_env[key]); no_alias(path)
        external[key] = {'path': str(path), 'sha256': sha(path.read_bytes())}
    if external['V4_WORKBENCH_HOST_BINDING']['sha256'] != panel_env['V4_WORKBENCH_HOST_BINDING_SHA256']:
        raise ValueError('HOST_BINDING_SHA_CHANGED')
    panel_entries = tools.inventory_tree(Path(panel_env['V4_RESEARCH_PANEL_ROOT']))
    external['panel_inventory'] = {'entry_count': len(panel_entries), 'aggregate_sha256': tools.inventory_digest(panel_entries)}
    output.mkdir(); results = {}
    for role in ('stage', 'api'):
        base = ROLE_PINS[role][1]; root = output/(output.name+'-'+role); app = root/'app'
        shutil.copytree(base, app, symlinks=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
        if role == 'stage':
            cfg['release_id'] = root.name
            cfg['research_historical_owner_bindings'] = [copy.deepcopy(cfg['research_owner_binding']), *cfg['research_historical_owner_bindings']]
            cfg['research_owner_binding'] = {'app_root': str(ROLE_PINS['main'][1]),
                'release_id': ROLE_PINS['main'][1].parent.name, 'manifest_sha256': ROLE_PINS['main'][2]}
            write(app, ATTESTATION, patched)
            write(app, 'stage_center_tick_config.json', (json.dumps(cfg, ensure_ascii=False, indent=2, sort_keys=True)+'\n').encode())
            allowed = {ATTESTATION, 'stage_center_tick_config.json'}
        else:
            manual['stage_owner_root'] = results['stage']['app_root']
            write(app, MANUAL_REL, (json.dumps(manual, ensure_ascii=False, indent=2, sort_keys=True)+'\n').encode())
            allowed = {MANUAL_REL}
        original = baselines[role][1]; actual = tools.inventory_tree(app)
        if any('__pycache__' in r['path'].split('/') or r['path'].endswith(('.pyc', '.pyo')) for r in actual):
            raise ValueError('BYTECODE_CACHE_IN_CANDIDATE')
        before = {r['path']: r for r in original}; after = {r['path']: r for r in actual}
        delta = [p for p in sorted(set(before)|set(after)) if before.get(p) != after.get(p)]
        cache_omissions = [p for p in delta if '__pycache__' in Path(p).parts
                           and p.endswith(('.pyc', '.pyo')) and p in before and p not in after]
        if set(delta) != allowed | set(cache_omissions):
            raise ValueError('EXACT_ALLOWLIST_DELTA_REQUIRED:'+role+':'+repr(delta))
        manifest = copy.deepcopy(baselines[role][0])
        manifest.update(app_root=str(app), release_id=root.name,
                        activation_status='PREPARED_NOT_ACTIVATED', deployment_status='NOT_DEPLOYED')
        if 'candidate' in manifest:
            manifest['candidate'].update(root=str(root), app_root=str(app), release_id=root.name)
        manifest['application_inventory'] = {'entries': actual, 'entry_count': len(actual), 'aggregate_sha256': tools.inventory_digest(actual)}
        if 'app_files' in manifest: manifest['app_files'] = actual
        manifest['f10_stage_binding_repair'] = {'source_baseline': SOURCE_BASELINE, 'source_root': str(source),
            'base_app': str(base), 'base_manifest_sha256': ROLE_PINS[role][2],
            'delta': [{'path': p, 'before': before.get(p), 'after': after.get(p)} for p in delta],
            'configuration_mode': 'PREPARED_RUNTIME_NOT_EXECUTED',
            'main_binding': cfg['research_owner_binding'], 'historical_bindings': cfg['research_historical_owner_bindings']}
        dump(root/'release-manifest.json', manifest)
        results[role] = {'app_root': str(app), 'release_id': root.name,
            'manifest_sha256': sha((root/'release-manifest.json').read_bytes()),
            'inventory_sha256': tools.inventory_digest(actual), 'delta': delta,
            'protected_files_unchanged': len(actual)-len(allowed),
            'generated_cache_omissions': [{'path': p, 'before': before[p]} for p in cache_omissions]}
    # CAS recheck: no concurrent activation may be silently folded into this build.
    for role, values in ROLE_PINS.items():
        if loaded_role(*values) != roles[role]: raise ValueError('ROLE_CHANGED_DURING_BUILD:'+role)
        verified_baseline(values[1], values[2], tools)
    if any(sha(Path(ref['path']).read_bytes()) != ref['sha256'] for key, ref in external.items() if key != 'panel_inventory'):
        raise ValueError('EXTERNAL_BINDING_CHANGED_DURING_BUILD')
    if tools.inventory_digest(tools.inventory_tree(Path(panel_env['V4_RESEARCH_PANEL_ROOT']))) != external['panel_inventory']['aggregate_sha256']:
        raise ValueError('EXTERNAL_PANEL_CHANGED_DURING_BUILD')
    if manual_path.read_bytes() != manual_raw: raise ValueError('MANUAL_SOURCE_CHANGED_DURING_BUILD')
    environments = {}
    for role, row in results.items():
        env = copy.deepcopy(roles[role]['environment'])
        env.update(dict(zip(IDENTITY, (row['app_root'], row['release_id'], str(Path(row['app_root']).parent/'release-manifest.json'), row['manifest_sha256']))))
        if role == 'stage':
            env['STAGE_CENTER_CONFIG'] = str(Path(row['app_root'])/'stage_center_tick_config.json')
            env['PYTHONPATH'] = env['PYTHONPATH'].replace(str(ROLE_PINS['stage'][1]), row['app_root'])
        else: env['V4_MANUAL_COLLECTION_STAGE_CONFIG'] = str(Path(row['app_root'])/MANUAL_REL)
        environments[role] = env
    receipt = {'schema_version': 'v4.f10_stage_binding_candidate.v1', 'status': 'PREPARED_NOT_ACTIVATED',
        'source_baseline': SOURCE_BASELINE, 'source_root': str(source), 'roles': results,
        'actual_role_baselines': roles, 'proposed_environment': environments,
        'preserved_panel_environment': panel_env, 'protected_external': external,
        'manual_source': {'path': str(manual_path), 'sha256': sha(manual_raw)},
        'main_not_rebuilt': True, 'a_precapture_not_rebuilt': True,
        'production_data_written': False, 'activated': False,
        'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
    receipt['release_proposal'] = release_proposals(output, receipt)
    dump(output/'candidate_receipt.json', receipt)
    dump(output/'candidates.json', results)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    receipt = prepare(args.output, args.source)
    print(json.dumps({'status': receipt['status'], 'roles': receipt['roles']}, ensure_ascii=False))


if __name__ == '__main__': main()
