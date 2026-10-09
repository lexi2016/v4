#!/usr/bin/env python3
"""Bind a reviewed module change set to the current API release.

Reads the active pointer/app and reviewed after files. Writes one new delta
receipt; does not build a full app, activate a service, or change business data.
The receipt is an integrity contract, not deployment authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, Sequence

if __package__:
    from . import api_release_integration as integration
else:
    import api_release_integration as integration

if Path(integration.__file__).resolve() != Path(__file__).resolve().with_name('api_release_integration.py'):
    raise ImportError('API_MODULE_DELTA_ADJACENT_GUARD_REQUIRED')

CHANGE_SET_SCHEMA = 'v4.api_module_change_set.v1'
FILE_KEYS = {'path', 'before_sha256', 'after_sha256', 'before_mode', 'after_mode'}


def prepare_stage_source(*, active_api_plist_path: Path, after_root: Path,
                         change_set_path: Path, built_dist_root: Path,
                         expected_static_inventory_sha256: str, source_root: Path,
                         output_change_set_path: Path) -> dict[str, Any]:
    """Prepare a new local Git source from reviewed code and a pinned full build.

    Existing inputs are read only. Only listed source files are committed;
    generated dist files remain local, explicitly untracked inputs. No remote
    is configured. The ordinary delta and candidate interfaces consume this
    source, so the active app need not be a Git checkout.
    """
    after_root = integration._exact_path(after_root, kind='directory', label='API_STAGE_AFTER_ROOT')
    built_dist_root = integration._exact_path(built_dist_root, kind='directory', label='API_STAGE_BUILT_DIST')
    change_set_path = integration._exact_path(change_set_path, kind='file', label='API_STAGE_CHANGE_SET')
    raw, change_token = integration._read_file(change_set_path)
    changes = integration._json_object(raw, 'API_STAGE_CHANGE_SET')
    if (set(changes) != {'schema_version', 'module', 'shared_paths', 'files'}
            or changes['schema_version'] != CHANGE_SET_SCHEMA or changes['module'] != 'stage'
            or not isinstance(changes['files'], list) or not changes['files']):
        raise ValueError('API_STAGE_REVIEWED_CODE_CHANGE_SET_REQUIRED')
    scope = integration.module_scope(changes['module'], changes['shared_paths'])
    active = integration.read_active_release(active_api_plist_path)
    source_root = integration._absolute_path(source_root)
    source_parent = integration._exact_path(source_root.parent, kind='directory', label='API_STAGE_SOURCE_PARENT')
    output = integration._absolute_path(output_change_set_path)
    output_parent = integration._exact_path(output.parent, kind='directory', label='API_STAGE_OUTPUT_PARENT')
    for protected in (Path(active['release_root']), after_root, built_dist_root):
        if source_root.is_relative_to(protected) or protected.is_relative_to(source_root):
            raise ValueError('API_STAGE_SOURCE_OVERLAPS_INPUT')
        if output.is_relative_to(protected):
            raise ValueError('API_STAGE_OUTPUT_INSIDE_INPUT')
    if output.is_relative_to(source_root):
        raise ValueError('API_STAGE_OUTPUT_INSIDE_SOURCE')
    if source_root.exists() or source_root.is_symlink():
        raise FileExistsError('API_STAGE_SOURCE_ALREADY_EXISTS')
    if output.exists() or output.is_symlink():
        raise FileExistsError('API_STAGE_OUTPUT_ALREADY_EXISTS')
    base = {row['path']: row for row in active['inventory']}
    source_bytes = {}
    source_snapshots = []
    entries = []
    paths = []
    for row in changes['files']:
        if not isinstance(row, dict) or set(row) != FILE_KEYS:
            raise ValueError('API_STAGE_FILE_FIELDS_INVALID')
        relative = integration._normalise_relative(row['path'])
        if integration._is_static_path(relative) or row['after_sha256'] is None:
            raise ValueError('API_STAGE_REVIEWED_CODE_PATH_REQUIRED')
        paths.append(relative)
        old = base.get(relative)
        if ((old is not None and old.get('kind') != 'file')
                or row['before_sha256'] != (old or {}).get('sha256')
                or row['before_mode'] != (old or {}).get('mode')):
            raise ValueError('API_STAGE_REVIEWED_BEFORE_MISMATCH:' + relative)
        before_raw = integration._read_file(Path(active['app_root']) / relative)[0] if old else None
        source = integration._safe_child(after_root, relative, allow_missing=False)
        after_raw, token = integration._read_file(source)
        if integration.sha256_bytes(after_raw) != row['after_sha256']:
            raise ValueError('API_STAGE_REVIEWED_AFTER_MISMATCH:' + relative)
        proof, hunks = (None, None) if before_raw is None else integration._diff_proof(before_raw, after_raw)
        entries.append({**row, 'unified_diff_sha256':proof, 'unified_diff_hunk_count':hunks})
        source_bytes[relative] = (after_raw, row['after_mode'])
        source_snapshots.append((source, row['after_sha256'], token))
    if paths != sorted(set(paths)):
        raise ValueError('API_STAGE_CODE_PATHS_MUST_BE_UNIQUE_AND_SORTED')
    integration._validate_module_scope(scope, paths)
    static_snapshot = integration._inventory_snapshot(built_dist_root)
    after_static = [dict(row, path=integration.STATIC_ROOT + '/' + row['path'])
                    for row in static_snapshot['entries']]
    static_tree = {'schema_version':integration.STATIC_SCHEMA_VERSION, 'root':integration.STATIC_ROOT,
        'before':integration.static_inventory_record(active['inventory']),
        'after':integration.static_inventory_record(after_static)}
    if (not integration._is_sha(expected_static_inventory_sha256)
            or static_tree['after']['aggregate_sha256'] != expected_static_inventory_sha256):
        raise ValueError('API_STAGE_BUILT_DIST_SHA_MISMATCH')
    previous = {row['path']:row for row in static_tree['before']['entries']}
    generated = {row['path']:row for row in after_static}
    for relative in sorted(set(previous) | set(generated)):
        old, new = previous.get(relative), generated.get(relative)
        if old == new:
            continue
        if any(row is not None and row.get('kind') != 'file' for row in (old,new)):
            raise ValueError('API_STAGE_STATIC_REGULAR_FILES_REQUIRED')
        before_raw = integration._read_file(Path(active['app_root']) / relative)[0] if old else None
        after_raw = integration._read_file(built_dist_root / relative[len(integration.STATIC_ROOT)+1:])[0] if new else b''
        proof, hunks = (None,None) if before_raw is None else integration._diff_proof(before_raw,after_raw)
        entries.append({'path':relative, 'before_sha256':(old or {}).get('sha256'),
            'after_sha256':(new or {}).get('sha256'), 'before_mode':(old or {}).get('mode'),
            'after_mode':(new or {}).get('mode'), 'unified_diff_sha256':proof,
            'unified_diff_hunk_count':hunks})
    entries.sort(key=lambda row:row['path'])
    provisional = {'schema_version':integration.DELTA_SCHEMA_VERSION, 'base':integration._base_binding(active),
                   'module_scope':scope, 'entries':entries, 'static_tree':static_tree}
    integration._validate_delta_receipt(provisional, base_identity=active)
    for row in after_static:
        original = built_dist_root / row['path'][len(integration.STATIC_ROOT)+1:]
        content, token = integration._read_file(original)
        if integration.sha256_bytes(content) != row['sha256']:
            raise ValueError('API_STAGE_STATIC_BUILD_DRIFT')
        source_bytes[row['path']] = (content, row['mode'])
        source_snapshots.append((original,row['sha256'],token))
    # Reserve one new destination only after every reviewed input passed.
    with integration._directory_fd(source_parent) as parent:
        os.mkdir(source_root.name, mode=0o700, dir_fd=parent)
    source_identity = integration._directory_token(source_root)
    marker = '.stage-source-incomplete'
    integration._write_candidate_bytes(source_root,marker,b'STAGE_SOURCE_PREPARING\n',0o600,exclusive=True)
    for relative, (content, mode) in source_bytes.items():
        integration._write_candidate_bytes(source_root,relative,content,int(mode,8),exclusive=True)
    git_env = {key:value for key,value in os.environ.items() if not key.startswith('GIT_')}
    git_env.update({'GIT_CONFIG_NOSYSTEM':'1', 'GIT_CONFIG_GLOBAL':os.devnull})
    git = ['git','-C',str(source_root),'-c','core.hooksPath='+os.devnull,
           '-c','core.fsmonitor=false','-c','commit.gpgsign=false',
           '-c','user.name=V4 isolated source','-c','user.email=v4-isolated@example.invalid']
    for args in (['init','--template=','--initial-branch=stage-r4-source'], ['add','--',*paths],
                 ['commit','-m','Reviewed Stage R4 source delta; generated static remains untracked']):
        subprocess.run([*git,*args],env=git_env,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    commit = subprocess.check_output([*git,'rev-parse','HEAD'],env=git_env,text=True).strip()
    committed = subprocess.check_output([*git,'ls-tree','-r','--name-only','-z','HEAD'],env=git_env).decode().split('\0')
    tracked = subprocess.check_output([*git,'ls-files','--cached','-z'],env=git_env).decode().split('\0')
    untracked = subprocess.check_output([*git,'ls-files','--others','--exclude-standard','-z'],env=git_env).decode().split('\0')
    if (sorted(filter(None,committed)) != paths or sorted(filter(None,tracked)) != paths
            or set(filter(None,untracked)) != {row['path'] for row in after_static} | {marker}
            or subprocess.check_output([*git,'status','--porcelain=v1','--untracked-files=no'],env=git_env).strip()):
        raise ValueError('API_STAGE_SOURCE_GIT_PROOF_MISMATCH')
    for relative,(content,mode) in source_bytes.items():
        current,token=integration._read_file(source_root/relative)
        if current != content or f'{stat.S_IMODE(token[1][2]):04o}' != mode:
            raise ValueError('API_STAGE_SOURCE_CONTENT_MISMATCH:' + relative)
    completed = {'schema_version':CHANGE_SET_SCHEMA, 'module':'stage', 'shared_paths':scope['shared_paths'],
                 'files':[{key:row[key] for key in FILE_KEYS} for row in entries], 'static_tree':static_tree}
    completed_raw = (json.dumps(completed,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    integration._assert_file_snapshot(change_set_path,integration.sha256_bytes(raw),change_token)
    for path,digest,token in source_snapshots:
        integration._assert_file_snapshot(path,digest,token)
    integration._assert_inventory_snapshot(built_dist_root,static_snapshot)
    integration._assert_active_snapshot(active)
    if integration._directory_token(source_root) != source_identity:
        raise ValueError('API_STAGE_SOURCE_REPLACED')
    integration._write_candidate_bytes(output_parent,output.name,completed_raw,0o600,exclusive=True)
    with integration._directory_fd(source_root) as parent:
        os.unlink(marker,dir_fd=parent)
        os.fsync(parent)
    return {'status':'STAGE_SOURCE_READY_FOR_REVIEW','source_root':str(source_root),
        'source_commit':commit,'change_set_path':str(output),'change_set_sha256':integration.sha256_bytes(completed_raw),
        'reviewed_change_set_path':str(change_set_path),'reviewed_change_set_sha256':integration.sha256_bytes(raw),
        'built_dist_root':str(built_dist_root),'static_inventory_sha256':expected_static_inventory_sha256,
        'include_untracked_paths':[row['path'] for row in entries
            if integration._is_static_path(row['path']) and row['after_sha256'] is not None],
        'base':integration._base_binding(active),'automatic_activation':False,'remote_configured':False}


def create_module_delta(*, active_api_plist_path: Path, after_root: Path,
                        change_set_path: Path, output_path: Path) -> dict[str, Any]:
    after_root = integration._exact_path(after_root, kind='directory', label='API_MODULE_DELTA_AFTER_ROOT')
    change_set_path = integration._exact_path(change_set_path, kind='file', label='API_MODULE_DELTA_CHANGE_SET')
    raw, change_token = integration._read_file(change_set_path)
    changes = integration._json_object(raw, 'API_MODULE_DELTA_CHANGE_SET')
    expected_keys = {'schema_version', 'module', 'shared_paths', 'files'}
    if 'static_tree' in changes:
        expected_keys.add('static_tree')
    if (set(changes) != expected_keys
            or changes['schema_version'] != CHANGE_SET_SCHEMA
            or not isinstance(changes['files'], list) or not changes['files']):
        raise ValueError('API_MODULE_DELTA_CHANGE_SET_INVALID')
    scope = integration.module_scope(changes['module'], changes['shared_paths'])
    active = integration.read_active_release(active_api_plist_path)
    base_app = Path(active['app_root'])
    base_entries = {row['path']: row for row in active['inventory']}
    entries = []
    after_snapshots = []
    paths = []
    for change in changes['files']:
        if not isinstance(change, dict) or set(change) != FILE_KEYS:
            raise ValueError('API_MODULE_DELTA_FILE_FIELDS_INVALID')
        relative = integration._normalise_relative(change['path'])
        paths.append(relative)
        before_entry = base_entries.get(relative)
        if change['before_sha256'] is None:
            if before_entry is not None or change['before_mode'] is not None:
                raise ValueError('API_MODULE_DELTA_ADDITION_ALREADY_EXISTS:' + relative)
            before_raw = None
        else:
            if (before_entry is None or before_entry.get('kind') != 'file'
                    or before_entry.get('sha256') != change['before_sha256']
                    or before_entry.get('mode') != change['before_mode']):
                raise ValueError('API_MODULE_DELTA_REVIEWED_BEFORE_MISMATCH:' + relative)
            before_path = integration._safe_child(base_app, relative, allow_missing=False)
            before_raw, _ = integration._read_file(before_path)
            if hashlib.sha256(before_raw).hexdigest() != change['before_sha256']:
                raise ValueError('API_MODULE_DELTA_BEFORE_CHANGED:' + relative)
        removal = change['after_sha256'] is None
        if removal and (changes['module'] != 'stage' or 'static_tree' not in changes
                        or not integration._is_static_path(relative)):
            raise ValueError('API_MODULE_DELTA_REMOVAL_NOT_ALLOWED:' + relative)
        after_path = integration._safe_child(after_root, relative, allow_missing=removal)
        after_raw, after_token = integration._read_file(after_path) if after_path.exists() else (None, None)
        after_sha = hashlib.sha256(after_raw).hexdigest() if after_raw is not None else None
        after_mode = f'{stat.S_IMODE(after_token[1][2]):04o}' if after_token is not None else None
        if after_sha != change['after_sha256'] or after_mode != change['after_mode']:
            raise ValueError('API_MODULE_DELTA_REVIEWED_AFTER_MISMATCH:' + relative)
        if after_token is not None:
            after_snapshots.append((after_path, after_sha, after_token))
        proof, hunks = (None, None) if before_raw is None else integration._diff_proof(
            before_raw, after_raw if after_raw is not None else b'')
        entries.append({**change, 'unified_diff_sha256': proof, 'unified_diff_hunk_count': hunks})
    if paths != sorted(set(paths)):
        raise ValueError('API_MODULE_DELTA_PATHS_MUST_BE_UNIQUE_AND_SORTED')
    receipt = {'schema_version': integration.DELTA_SCHEMA_VERSION,
        'base': integration._base_binding(active), 'module_scope': scope, 'entries': entries}
    static_snapshot = None
    if 'static_tree' in changes:
        receipt['static_tree'] = changes['static_tree']
        static_snapshot = integration._inventory_snapshot(after_root / integration.STATIC_ROOT)
        static_rows = [dict(row, path=integration.STATIC_ROOT + '/' + row['path'])
                       for row in static_snapshot['entries']]
        integration._validate_static_tree(changes['static_tree'], base_inventory=active['inventory'],
                                           entries=entries, candidate_inventory=static_rows)
    integration._validate_delta_receipt(receipt, base_identity=active)
    output_path = integration._absolute_path(output_path)
    output_parent = integration._exact_path(output_path.parent, kind='directory', label='API_MODULE_DELTA_OUTPUT_PARENT')
    for protected in (Path(active['release_root']), after_root):
        if output_path == protected or protected in output_path.parents:
            raise ValueError('API_MODULE_DELTA_OUTPUT_INSIDE_INPUT_ROOT')
    if output_path.exists() or output_path.is_symlink():
        raise ValueError('API_MODULE_DELTA_OUTPUT_ALREADY_EXISTS')
    integration._assert_file_snapshot(change_set_path, hashlib.sha256(raw).hexdigest(), change_token)
    for path, digest, token in after_snapshots:
        integration._assert_file_snapshot(path, digest, token)
    if static_snapshot is not None:
        integration._assert_inventory_snapshot(after_root / integration.STATIC_ROOT, static_snapshot)
    integration._assert_active_snapshot(active)
    receipt_raw = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    integration._write_candidate_bytes(output_parent, output_path.name, receipt_raw, 0o600, exclusive=True)
    # The builder and actual publisher independently verify the same base again.
    integration._assert_active_snapshot(active)
    return {'status': 'DELTA_READY_FOR_REVIEW', 'module': scope['module'],
        'delta_path': str(output_path), 'delta_sha256': hashlib.sha256(receipt_raw).hexdigest(),
        'file_count': len(entries), 'automatic_activation': False}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--active-api-plist', type=Path, required=True)
    parser.add_argument('--after-root', type=Path, required=True)
    parser.add_argument('--change-set', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare-stage-source', action='store_true')
    parser.add_argument('--built-dist-root', type=Path)
    parser.add_argument('--expected-static-inventory-sha256')
    parser.add_argument('--source-root', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.prepare_stage_source:
            if args.built_dist_root is None or args.expected_static_inventory_sha256 is None or args.source_root is None:
                raise ValueError('Stage preparation requires --built-dist-root, --expected-static-inventory-sha256, --source-root')
            result = prepare_stage_source(active_api_plist_path=args.active_api_plist,
                after_root=args.after_root,change_set_path=args.change_set,built_dist_root=args.built_dist_root,
                expected_static_inventory_sha256=args.expected_static_inventory_sha256,
                source_root=args.source_root,output_change_set_path=args.output)
        else:
            result = create_module_delta(active_api_plist_path=args.active_api_plist,
                after_root=args.after_root, change_set_path=args.change_set, output_path=args.output)
    except (ValueError, OSError, TypeError, KeyError, subprocess.CalledProcessError) as exc:
        import sys
        print('API_MODULE_DELTA_REJECTED: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
