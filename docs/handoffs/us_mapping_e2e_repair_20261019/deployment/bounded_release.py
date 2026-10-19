#!/usr/bin/env python3
"""One-task release overlay. Never writes business inputs or calls business POST."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
WT = HERE.parents[3]
SCOPE = json.loads((HERE / 'SCOPE.json').read_text())
OLD = Path(SCOPE['rollback']['preimage_release'])
NEW = OLD.parent / 'us-mapping-e2e-repair-20261019-r1'
PLIST = Path(SCOPE['active_api']['plist_path'])
LOCAL = HERE / 'local_only'
BACKUP = LOCAL / 'original-api.plist'
NEXT = LOCAL / 'candidate-api.plist'
RECEIPT = HERE / 'PREPARED.json'
LABEL = 'com.lexi.v35.api-only'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')

def helper():
    spec = importlib.util.spec_from_file_location('retained_release_inventory', OLD / 'app/ops/api_release_integration.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def precheck():
    assert sha(PLIST) == SCOPE['active_api']['plist_sha256'], 'active plist drift'
    assert sha(OLD / 'release-manifest.json') == SCOPE['active_api']['manifest_sha256'], 'active manifest drift'
    cfg = SCOPE['existing_inputs']['manager_config']
    assert sha(cfg['path']) == cfg['sha256'], 'config drift'
    for row in SCOPE['source_delta']:
        assert sha(OLD / 'app' / row['path']) == row['active_preimage_sha256'], row['path'] + ' active drift'
        assert sha(WT / row['path']) == row['candidate_source_sha256'], row['path'] + ' candidate drift'
    for row in SCOPE['byte_identical_active_sources']:
        assert sha(OLD / 'app' / row['path']) == row['sha256'] == sha(WT / row['path'])
    mod = helper()
    entries = mod.inventory_tree(OLD / 'app')
    manifest = json.loads((OLD / 'release-manifest.json').read_text())
    assert entries == manifest['application_inventory']['entries'], 'active full inventory drift'
    return mod, entries

def replace_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    shutil.copy2(source, target)

def prepare():
    assert not NEW.exists(), 'candidate already exists: stop and inspect identity'
    assert not RECEIPT.exists() and not BACKUP.exists(), 'preparation evidence already exists'
    mod, before = precheck()
    LOCAL.mkdir(exist_ok=True)
    BACKUP.write_bytes(PLIST.read_bytes())
    build = LOCAL / 'frontend-build'
    assert not build.exists()
    shutil.copytree(OLD / 'app/apps/web', build, symlinks=True, ignore=shutil.ignore_patterns('dist', 'node_modules'))
    assert sha(build / 'package-lock.json') == sha(WT / 'apps/web/package-lock.json'), 'dependency lock mismatch'
    (build / 'node_modules').symlink_to(WT / 'apps/web/node_modules', target_is_directory=True)
    for row in SCOPE['source_delta']:
        if row['path'].startswith('apps/web/'):
            replace_file(WT / row['path'], build / Path(row['path']).relative_to('apps/web'))
    with (LOCAL / 'frontend-build.log').open('w') as log:
        subprocess.run(['npm', 'run', 'build'], cwd=build, stdout=log, stderr=subprocess.STDOUT, check=True)
    shutil.copytree(OLD / 'app', NEW / 'app', symlinks=True)
    for row in SCOPE['source_delta']:
        replace_file(WT / row['path'], NEW / 'app' / row['path'])
    entry = 'manager-selection/index.html'
    dist = build / 'dist'
    required = set()
    def collect(rel):
        for match in re.findall(r'(?:/|[\"\x27])assets/([^\"\x27\s<>]+)', (dist / rel).read_text()):
            asset = 'assets/' + match
            assert '..' not in asset and (dist / asset).is_file(), asset
            if asset not in required:
                required.add(asset)
                if asset.endswith(('.js', '.css')):
                    collect(asset)
    collect(entry)
    # Vite imports may be relative to another asset rather than /assets/.
    todo = list(required)
    while todo:
        rel = todo.pop()
        if rel.endswith(('.js', '.css')):
            for match in re.findall(r'[\"\x27](?:\./)?([^/\"\x27]+\.(?:js|css))[\"\x27]', (dist / rel).read_text()):
                dep = 'assets/' + match
                if (dist / dep).exists() and dep not in required:
                    required.add(dep)
                    todo.append(dep)
    replace_file(dist / entry, NEW / 'app/apps/web/dist' / entry)
    added_assets = []
    for rel in sorted(required):
        target = NEW / 'app/apps/web/dist' / rel
        if target.exists():
            assert sha(target) == sha(dist / rel), 'existing hash asset collision: ' + rel
        else:
            shutil.copy2(dist / rel, target)
            added_assets.append('apps/web/dist/' + rel)
    after = mod.inventory_tree(NEW / 'app')
    a = {x['path']: x for x in before}
    b = {x['path']: x for x in after}
    changed = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
    allowed = {x['path'] for x in SCOPE['source_delta']} | {'apps/web/dist/' + entry} | set(added_assets)
    assert set(changed) <= allowed and not (a.keys() - b.keys()), changed
    assert set(x['path'] for x in SCOPE['source_delta']) <= set(changed)
    for key in a.keys() - allowed:
        assert a[key] == b[key], key
    old_manifest = json.loads((OLD / 'release-manifest.json').read_text())
    manifest = {'schema_version': 'v4.release_candidate.v1', 'activation_status': 'PREPARED',
        'candidate': {'root': str(NEW), 'app_root': str(NEW / 'app'), 'release_id': NEW.name,
            'module_role': 'gateway', 'module_contract_sha256': None, 'formal_release_root': str(NEW)},
        'application_inventory': {'entries': after, 'entry_count': len(after), 'aggregate_sha256': mod.inventory_digest(after)},
        'task_overlay': {'base_release': str(OLD), 'base_manifest_sha256': sha(OLD / 'release-manifest.json'),
            'source_worktree': str(WT), 'source_commit': SCOPE['repository']['head'],
            'source_scope_sha256': SCOPE['repository']['source_scope_sha256'],
            'full_worktree_equivalence_claimed': False,
            'retained_base_integration': old_manifest.get('api_integration'),
            'delta': [{'path': k, 'before': a.get(k), 'after': b.get(k)} for k in changed],
            'non_delta_preserved': True, 'existing_assets_preserved': True}}
    write_json(NEW / 'release-manifest.json', manifest)
    original = plistlib.loads(BACKUP.read_bytes())
    def rebound(value):
        if isinstance(value, str):
            return value.replace(str(OLD), str(NEW)).replace(OLD.name, NEW.name).replace(SCOPE['active_api']['manifest_sha256'], sha(NEW / 'release-manifest.json'))
        if isinstance(value, list):
            return [rebound(x) for x in value]
        if isinstance(value, dict):
            return {k: rebound(v) for k, v in value.items()}
        return value
    NEXT.write_bytes(plistlib.dumps(rebound(original), sort_keys=False))
    write_json(RECEIPT, {'state': 'PREPARED', 'source_commit': SCOPE['repository']['head'],
        'old_release': str(OLD), 'candidate': str(NEW), 'manifest_sha256': sha(NEW / 'release-manifest.json'),
        'old_inventory_sha256': mod.inventory_digest(before), 'candidate_inventory_sha256': mod.inventory_digest(after),
        'changed_paths': changed, 'required_assets': sorted(required), 'non_delta_preserved': True,
        'original_plist_sha256': sha(BACKUP), 'candidate_plist_sha256': sha(NEXT),
        'build_command': 'npm run build (isolated active frontend source plus two accepted patches)',
        'activation_executed': False, 'business_post_count': 0,
        'rollback_command': 'python3 ' + str(Path(__file__).resolve()) + ' rollback'})
    print(json.dumps({'state': 'PREPARED', 'changed_paths': changed, 'receipt': str(RECEIPT)}))

def reload_api():
    domain = 'gui/' + str(os.getuid())
    target = domain + '/' + LABEL
    state = subprocess.run(['/bin/launchctl', 'print', target], capture_output=True, text=True)
    if state.returncode == 0 and 'state = SIGTERMed' not in state.stdout:
        subprocess.run(['/bin/launchctl', 'bootout', target], check=True)
    elif state.returncode not in (0, 113):
        raise RuntimeError('Unexpected launchctl state: ' + state.stderr)
    # bootout can return before launchd removes the terminating job. Wait for
    # that exact lifecycle transition, without sending another bootout.
    for _ in range(16):
        state = subprocess.run(['/bin/launchctl', 'print', target], capture_output=True, text=True)
        if state.returncode == 113:
            break
        assert state.returncode == 0 and 'state = SIGTERMed' in state.stdout, 'unexpected unloading state'
        time.sleep(1)
    else:
        raise RuntimeError('API unload not completed within bounded lifecycle wait')
    subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(PLIST)], check=True)
    subprocess.run(['/bin/launchctl', 'kickstart', target], check=True)

def activate():
    mod, _before = precheck()
    receipt = json.loads(RECEIPT.read_text())
    assert sha(NEW / 'release-manifest.json') == receipt['manifest_sha256']
    assert mod.inventory_digest(mod.inventory_tree(NEW / 'app')) == receipt['candidate_inventory_sha256']
    assert sha(NEXT) == receipt['candidate_plist_sha256']
    assert sha(BACKUP) == receipt['original_plist_sha256']
    PLIST.write_bytes(NEXT.read_bytes())
    reload_api()
    write_json(HERE / 'ACTIVATED.json', {'state': 'ACTIVATED_PENDING_VERIFICATION', 'candidate': str(NEW),
        'manifest_sha256': sha(NEW / 'release-manifest.json'), 'plist_sha256': sha(PLIST), 'business_post_count': 0})
    print('ACTIVATED_PENDING_VERIFICATION')

def rollback():
    receipt = json.loads(RECEIPT.read_text())
    assert sha(PLIST) == receipt['candidate_plist_sha256'], 'plist drift, do not overwrite'
    assert sha(BACKUP) == receipt['original_plist_sha256']
    PLIST.write_bytes(BACKUP.read_bytes())
    reload_api()
    write_json(HERE / 'ROLLED_BACK.json', {'state': 'ROLLED_BACK_PENDING_VERIFICATION', 'release': str(OLD), 'plist_sha256': sha(PLIST)})
    print('ROLLED_BACK_PENDING_VERIFICATION')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'activate', 'rollback'])
    args = parser.parse_args()
    globals()[args.action]()
