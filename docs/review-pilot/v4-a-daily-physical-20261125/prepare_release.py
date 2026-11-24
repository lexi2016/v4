"""Stage exact Main daily changes and the dependent Stage owner pin."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import runpy
import subprocess
import sys
from urllib.request import urlopen

from ops import switch_reviewed_v4_release as release
from ops.api_release_integration import inventory_digest, inventory_tree

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ACTIVE = release.ROOT / 'state/release-activation/v4-r2-rollup-20261124'
STAGE_ATTESTATION = 'infrastructure/manager_input_attestation.py'
STAGE_CONFIG = 'stage_center_tick_config.json'
HISTORICAL_LIMIT_BEFORE = b'if not isinstance(historical, list) or len(historical) > 25:'
HISTORICAL_LIMIT_AFTER = b'if not isinstance(historical, list) or len(historical) > 26:'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reference(path):
    return {"path": str(path), "sha256": digest(path)}


def write(path, raw):
    with Path(path).open('xb') as file:
        file.write(raw)
        file.flush()
        os.fsync(file.fileno())
    return reference(path)


def read(path):
    return json.loads(Path(path).read_bytes())


def file_rows(entries):
    return {row["path"]: row for row in entries}


def manifest_value(before, app, commit, changes, entries):
    return {**before, "app_root": str(app), "source_root": str(REPO), "source_commit": commit,
            "source_base_commit": before["source_commit"], "parent_release_root": before["app_root"],
            "release_id": app.parent.name, "generated_at": release.now(),
            "activation_status": "STARTUP_SEAL", "deployment_status": "STARTUP_SEAL",
            "candidate": {"app_root": str(app), "root": str(app.parent), "release_id": app.parent.name},
            "application_inventory": {"entries": entries, "entry_count": len(entries),
                                      "aggregate_sha256": inventory_digest(entries)},
            "app_files": [{k: row[k] for k in ("path", "sha256", "size")} for row in entries if row["kind"] == "file"],
            "source_delta": changes}


def update_stage(app, config, previous_main, next_main):
    old = config['research_owner_binding']
    assert old == previous_main
    historical = config['research_historical_owner_bindings']
    assert len(historical) == 25 and len({row['app_root'] for row in historical}) == 25
    assert all(row['app_root'] != old['app_root'] for row in historical)
    config['research_historical_owner_bindings'] = [*historical, old]
    config['research_owner_binding'] = next_main
    config['release_id'] = app.parent.name
    (app / STAGE_CONFIG).write_bytes(release.encode(config))
    target = app / STAGE_ATTESTATION
    old_code = target.read_bytes()
    assert release.digest(old_code) == 'de7df7e274a21136fd1e52d287a4d0e341f8af80b68af12a83297096084ea7fd'
    assert old_code.count(HISTORICAL_LIMIT_BEFORE) == 1
    target.write_bytes(old_code.replace(HISTORICAL_LIMIT_BEFORE, HISTORICAL_LIMIT_AFTER))


def app_pin(app, manifest):
    return {"app_root": str(app), "manifest_path": manifest['path'],
            "manifest_sha256": manifest['sha256'], "release_id": app.parent.name}


def relocate(cfg, role, old_app, app, manifest):
    cfg['WorkingDirectory'] = str(app)
    cfg['ProgramArguments'] = [str(app) + arg[len(str(old_app)):] if arg.startswith(str(old_app) + '/') else arg
                               for arg in cfg['ProgramArguments']]
    env = cfg['EnvironmentVariables']
    env.update(V4_APP_ROOT=str(app), V4_RELEASE_ID=app.parent.name,
               V4_RELEASE_MANIFEST_PATH=manifest['path'], V4_RELEASE_MANIFEST_SHA256=manifest['sha256'])
    if role == 'main':
        binding, policy, pins = release.policy_binding(cfg, old_app)
        assert binding['app_root'] == str(old_app) and pins['expected_main_app_root'] == str(old_app)
        assert env[release.A_SYNC_SCRIPT] == str(old_app / release.A_SYNC_ENTRY)
        env[release.A_SYNC_SCRIPT] = str(app / release.A_SYNC_ENTRY)
        # Other Main tasks still use the original policy and their original data roots.
        control = app.parent / 'control'
        control.mkdir()
        pins = write(control / 'managed-pins.json', release.encode({**pins, 'expected_main_app_root': str(app)}))
        policy = write(control / 'policy.json', release.encode({**policy, 'managed_pin_inventory': pins}))
        env[release.POLICY_PATH], env[release.POLICY_SHA] = policy['path'], policy['sha256']
    else:
        env['STAGE_CENTER_CONFIG'] = str(app / STAGE_CONFIG)
    return cfg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--audited-switch', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    args = parser.parse_args()
    case = args.case.resolve(strict=True)
    os.umask(0o077)
    audited = reference(args.audited_switch.resolve(strict=True))
    probe = reference(args.probe.resolve(strict=True))
    commit = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    patch = HERE / 'active-main.patch'
    baseline = read(HERE / 'base_source_manifest.json')
    assert subprocess.check_output(['git', '-C', str(REPO), 'show',
                                    f'{commit}:{patch.relative_to(REPO)}']) == patch.read_bytes()
    assert digest(patch) == baseline['patch_sha256']
    prior = release.active_record(ACTIVE)
    group = read(ACTIVE / prior['target'] / 'group-manifest.json')
    api = group['roles']['api']
    api_identity = read(Path(api['path']))
    api_plist = Path(api_identity['plist_path'])
    api_loaded = release.load_audited_switch(audited)['verify_loaded'](
        'api', api_identity['app_root'], api_plist, api_identity['startup_manifest']['sha256'])
    roles, approvals = [], {}
    for role in ('main', 'stage'):
        active = read(Path(group['roles'][role]['path']))
        live = Path(active['plist_path'])
        before = release.checked(live, active['plist_sha256'])
        cfg = plistlib.loads(before)
        old_app, old_manifest, old_data = release.startup(cfg, active['startup_manifest']['sha256'], candidate=True)
        app = release.CANDIDATES / f'v4-r2-20261125-{role}-daily-physical/app'
        app.parent.mkdir()
        subprocess.run(['/bin/cp', '-cRp', str(old_app), str(app)], check=True)
        base_entries = file_rows(inventory_tree(app))
        assert base_entries == file_rows(old_data['application_inventory']['entries'])
        if role == 'main':
            assert digest(old_manifest) == baseline['active_release_manifest_sha256']
            stat = subprocess.check_output(['git', 'apply', '--numstat', str(patch)], cwd=app, text=True)
            expected = {row.split('\t')[-1] for row in stat.splitlines()}
            assert expected == baseline['files'].keys()
            assert all(base_entries.get(name, {}).get('sha256') == baseline['files'][name]['before_sha256']
                       for name in expected)
            subprocess.run(['git', 'apply', '--check', str(patch)], check=True, cwd=app)
            subprocess.run(['git', 'apply', str(patch)], check=True, cwd=app)
        else:
            expected = {STAGE_CONFIG, STAGE_ATTESTATION}
            stage_cfg = read(app / STAGE_CONFIG)
            stage_prior_sha = digest(app / STAGE_CONFIG)
            update_stage(app, stage_cfg, previous_main, next_main)
        entries = inventory_tree(app)
        after = file_rows(entries)
        changed = {name for name in set(base_entries) | set(after) if base_entries.get(name) != after.get(name)}
        # A newly added file may add its containing directory to the inventory.
        changed_files = {name for name in changed if after.get(name, base_entries.get(name))['kind'] != 'directory'}
        assert changed_files == expected and not (set(base_entries) - set(after)), (changed_files, expected)
        changes = [{"path": name, "before_sha256": base_entries.get(name, {}).get('sha256'),
                    "after_sha256": after[name]['sha256']} for name in sorted(changed_files)]
        ref = write(app.parent / 'startup-manifest.json', release.encode(manifest_value(old_data, app, commit, changes, entries)))
        if role == 'main':
            assert all(after[name]['sha256'] == baseline['files'][name]['after_sha256'] for name in expected)
            previous_main = app_pin(old_app, reference(old_manifest))
            next_main = app_pin(app, ref)
        (app.parent / 'release-manifest.json').symlink_to(ACTIVE / 'active' / app.parent.name / 'release-manifest.json')
        forward = write(app.parent / 'forward.plist', plistlib.dumps(relocate(cfg, role, old_app, app, ref)))
        subprocess.run(['/usr/bin/plutil', '-lint', forward['path']], check=True)
        rollback = write(case / f'{role}.rollback.plist', before)
        row = {"role": role, "rollback_plist": rollback['path'], "current_plist_sha256": rollback['sha256'],
               "current_manifest_sha256": active['startup_manifest']['sha256'], "candidate_release_id": app.parent.name,
               "candidate_plist": forward['path'], "candidate_plist_sha256": forward['sha256'],
               "candidate_manifest_sha256": ref['sha256']}
        roles.append(row)
        approvals[role] = {**row, "source_commit": commit,
                           "delta_files": [reference(app / name) for name in sorted(changed_files)]}
    draft = {"transaction_kind": release.MAIN_STAGE_REFRESH, "activation_directory": str(ACTIVE),
             "prior_active_sha256": prior['sha256'], "prior_stage_config_sha256": stage_prior_sha,
             "carried_api_pid": api_loaded['pid'], "audited_switch": audited, "roles": roles,
             "verification_command": [sys.executable, '-B', '-c',
                 "import hashlib,pathlib,sys; p=pathlib.Path(sys.argv[1]); b=p.read_bytes(); "
                 "assert hashlib.sha256(b).hexdigest()==sys.argv[2]; sys.argv=[str(p),sys.argv[3]]; "
                 "exec(compile(b,str(p),'exec'),{'__file__':str(p),'__name__':'__main__'})",
                 probe['path'], probe['sha256'], str(case / 'RELEASE_PLAN.json')]}
    record = {"plan": draft, "review_inputs": approvals, "carried_api_identity": api_identity,
              "source_commit": commit}
    print(json.dumps(write(case / 'RELEASE_DRAFT.json', release.encode(record)), ensure_ascii=False))


if __name__ == '__main__':
    main()
