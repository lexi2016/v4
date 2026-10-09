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
from pathlib import Path
import stat
from typing import Any, Sequence

if __package__:
    from . import api_release_integration as integration
else:
    import api_release_integration as integration

if Path(integration.__file__).resolve() != Path(__file__).resolve().with_name('api_release_integration.py'):
    raise ImportError('API_MODULE_DELTA_ADJACENT_GUARD_REQUIRED')

CHANGE_SET_SCHEMA = 'v4.api_module_change_set.v1'
FILE_KEYS = {'path', 'before_sha256', 'after_sha256', 'before_mode', 'after_mode'}


def create_module_delta(*, active_api_plist_path: Path, after_root: Path,
                        change_set_path: Path, output_path: Path) -> dict[str, Any]:
    after_root = integration._exact_path(after_root, kind='directory', label='API_MODULE_DELTA_AFTER_ROOT')
    change_set_path = integration._exact_path(change_set_path, kind='file', label='API_MODULE_DELTA_CHANGE_SET')
    raw, change_token = integration._read_file(change_set_path)
    changes = integration._json_object(raw, 'API_MODULE_DELTA_CHANGE_SET')
    if (set(changes) != {'schema_version', 'module', 'shared_paths', 'files'}
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
        after_path = integration._safe_child(after_root, relative, allow_missing=False)
        after_raw, after_token = integration._read_file(after_path)
        after_sha = hashlib.sha256(after_raw).hexdigest()
        after_mode = f'{stat.S_IMODE(after_token[1][2]):04o}'
        if after_sha != change['after_sha256'] or after_mode != change['after_mode']:
            raise ValueError('API_MODULE_DELTA_REVIEWED_AFTER_MISMATCH:' + relative)
        after_snapshots.append((after_path, after_sha, after_token))
        proof, hunks = (None, None) if before_raw is None else integration._diff_proof(before_raw, after_raw)
        entries.append({**change, 'unified_diff_sha256': proof, 'unified_diff_hunk_count': hunks})
    if paths != sorted(set(paths)):
        raise ValueError('API_MODULE_DELTA_PATHS_MUST_BE_UNIQUE_AND_SORTED')
    receipt = {'schema_version': integration.DELTA_SCHEMA_VERSION,
        'base': integration._base_binding(active), 'module_scope': scope, 'entries': entries}
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
    args = parser.parse_args(argv)
    try:
        result = create_module_delta(active_api_plist_path=args.active_api_plist,
            after_root=args.after_root, change_set_path=args.change_set, output_path=args.output)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        import sys
        print('API_MODULE_DELTA_REJECTED: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
