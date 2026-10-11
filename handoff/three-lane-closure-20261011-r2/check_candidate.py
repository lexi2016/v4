#!/usr/bin/env python3
"""Read-only patch byte verification. Never deploys, imports owners or writes target."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys

MAX_SOURCE_BYTES = 4 * 1024 * 1024


def read_regular(root: Path, relative: str) -> bytes | None:
    if not isinstance(relative, str):
        raise ValueError('UNSAFE_RELATIVE_PATH')
    token = PurePosixPath(relative)
    if (token.is_absolute() or '..' in token.parts
            or not token.parts or str(token) != relative):
        raise ValueError('UNSAFE_RELATIVE_PATH')
    root_info = root.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise ValueError('ROOT_MUST_BE_NON_SYMLINK_DIRECTORY')
    current = root
    for part in token.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            raise ValueError('SYMLINK_PATH_REJECTED:' + relative)
    info = current.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SOURCE_BYTES:
        raise ValueError('SOURCE_NOT_BOUNDED_REGULAR_FILE:' + relative)
    with current.open('rb') as stream:
        data = stream.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError('SOURCE_BYTES_LIMIT:' + relative)
    return data


def sha256(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def verify(package: Path, target: Path | None, phase: str) -> dict:
    manifest_bytes = read_regular(package, 'BEFORE_AFTER_SHA256.json')
    if manifest_bytes is None:
        raise ValueError('PATCH_MANIFEST_MISSING')
    manifest = json.loads(manifest_bytes.decode('utf-8'))
    if not isinstance(manifest, dict):
        raise ValueError('PATCH_MANIFEST_NOT_OBJECT')
    files = manifest.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= 64:
        raise ValueError('PATCH_MANIFEST_FILE_COUNT_INVALID')
    if any(not isinstance(row, dict) for row in files):
        raise ValueError('PATCH_MANIFEST_ROW_NOT_OBJECT')
    names = [row.get('path') for row in files]
    if any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
        raise ValueError('PATCH_MANIFEST_PATHS_INVALID')
    results = []
    for row in files:
        if any(key not in row for key in ('path', 'change', 'before_sha256', 'before_bytes',
                'after_sha256', 'after_bytes')):
            raise ValueError('PATCH_MANIFEST_BYTE_FIELDS_MISSING')
        relative = row['path']
        change = row['change']
        if (change not in ('modified', 'added_test')
                or (change == 'modified' and row['before_sha256'] is None)
                or (change == 'added_test' and (row['before_sha256'] is not None
                    or row['before_bytes'] is not None))):
            raise ValueError('PATCH_MANIFEST_CHANGE_IDENTITY_INVALID:' + relative)
        for label in ('before', 'after'):
            expected_sha = row.get(label + '_sha256')
            expected_bytes = row.get(label + '_bytes')
            if expected_sha is None:
                if label != 'before' or expected_bytes is not None:
                    raise ValueError('PATCH_MANIFEST_NULL_IDENTITY_INVALID:' + relative)
            elif (not isinstance(expected_sha, str) or len(expected_sha) != 64
                    or any(char not in '0123456789abcdef' for char in expected_sha)
                    or type(expected_bytes) is not int
                    or not 0 <= expected_bytes <= MAX_SOURCE_BYTES):
                raise ValueError('PATCH_MANIFEST_BYTE_IDENTITY_INVALID:' + relative)
        patch_data = read_regular(package / 'after', relative)
        if (patch_data is None or sha256(patch_data) != row['after_sha256']
                or len(patch_data) != row['after_bytes']):
            raise ValueError('PATCH_AFTER_BYTES_MISMATCH:' + relative)
        before_data = read_regular(package / 'before', relative)
        before_bytes = len(before_data) if before_data is not None else None
        if sha256(before_data) != row['before_sha256'] or before_bytes != row['before_bytes']:
            raise ValueError('PATCH_BEFORE_BYTES_MISMATCH:' + relative)
        result = {'path': relative, 'before_artifact_verified': True, 'after_artifact_verified': True}
        if target is not None:
            data = read_regular(target, relative)
            expected = row[phase + '_sha256']
            expected_bytes = row[phase + '_bytes']
            observed_bytes = len(data) if data is not None else None
            matches = sha256(data) == expected and observed_bytes == expected_bytes
            result.update(expected_sha256=expected, observed_sha256=sha256(data),
                expected_bytes=expected_bytes, observed_bytes=observed_bytes,
                matches=matches,
                status='MATCH' if matches else phase.upper() + '_MISMATCH')
        results.append(result)
    matched = target is None or all(row['matches'] for row in results)
    return {'schema_version': 'three_lane.read_only_byte_check.v1',
        'status': 'BYTES_MATCH' if matched else 'CANNOT_CONFIRM',
        'phase': phase, 'target_root': str(target) if target is not None else None,
        'files': results, 'read_only': True, 'target_writes': 0,
        'full_application_verified': False, 'owner_run_verified': False,
        'api_or_ui_verified': False, 'natural_run_verified': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, help='Existing isolated source root to compare')
    parser.add_argument('--phase', choices=['before', 'after'], default='before')
    args = parser.parse_args()
    try:
        target = args.target
        if target is not None:
            if target.is_symlink() or not target.is_dir():
                raise ValueError('TARGET_MUST_BE_AN_EXISTING_NON_SYMLINK_DIRECTORY')
            target = target.resolve(strict=True)
        result = verify(Path(__file__).resolve().parent, target, args.phase)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'BYTES_MATCH' else 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'CANNOT_CONFIRM', 'error': str(exc),
            'read_only': True, 'target_writes': 0}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
