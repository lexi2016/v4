#!/usr/bin/env python3
"""Read-only package/source verification; optional patch replay in a temp dir.

This script never applies a patch to the supplied source root, accesses an API,
or opens owner state. The source-image check is an exact SHA precondition.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owned(root: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if rel.is_absolute() or not rel.parts or any(p in {'..', '.'} for p in rel.parts):
        raise ValueError(f'UNSAFE_RELATIVE_PATH:{relative}')
    path = root.joinpath(*rel.parts)
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f'SYMLINK_NOT_ACCEPTED:{relative}')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'PATH_ESCAPES_ROOT:{relative}')
    return path


def check_image(root: Path, rows: list[dict], image: str) -> int:
    for row in rows:
        path = owned(root, row['path'])
        expected = row[f'{image}_sha256']
        if expected is None:
            if path.exists():
                raise ValueError(f'EXPECTED_ABSENT:{row["path"]}')
        elif not path.is_file() or sha256(path) != expected:
            raise ValueError(f'{image.upper()}_SHA_MISMATCH:{row["path"]}')
    return len(rows)


def check_unchanged(root: Path, rows: list[dict], *, packaged: bool) -> int:
    for row in rows:
        relative = row['package_path'] if packaged else row['path']
        path = owned(root, relative)
        if not path.is_file() or sha256(path) != row['sha256']:
            raise ValueError(f'UNCHANGED_PRECONDITION_MISMATCH:{row["path"]}')
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--source-image', choices=('before', 'after'), default='before')
    parser.add_argument('--patch-roundtrip', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    file_manifest = json.loads((root / 'FILE_MANIFEST.json').read_text())
    source_manifest = json.loads((root / 'SOURCE_SHA256.json').read_text())
    rows = source_manifest['files']
    unchanged = source_manifest.get('unchanged_preconditions', [])
    checked = 0
    for row in file_manifest['files']:
        path = owned(root, row['path'])
        if not path.is_file() or path.stat().st_size != row['bytes'] or sha256(path) != row['sha256']:
            raise ValueError(f'PACKAGE_FILE_MISMATCH:{row["path"]}')
        checked += 1
    for image in ('before', 'after'):
        check_image(root / image, rows, image)
    check_unchanged(root, unchanged, packaged=True)
    result = {'status': 'PASS', 'package_files_checked': checked,
              'source_files_checked': len(rows),
              'unchanged_preconditions_checked': len(unchanged), 'live_api_ui': 'NOT_RUN',
              'RESEARCH_ONLY': True, 'production_allowed': False,
              'buy_gate_updated': False, 'orders_sent': False}
    if args.source_root:
        source = args.source_root.expanduser().resolve(strict=True)
        result['source_image_checked'] = args.source_image
        result['source_preconditions_checked'] = check_image(source, rows, args.source_image)
        result['source_owner_validator_preconditions_checked'] = check_unchanged(
            source, unchanged, packaged=False)
    if args.patch_roundtrip:
        patch = root / 'runtime.patch'
        with tempfile.TemporaryDirectory(prefix='v4-manager-patch-review-') as name:
            target = Path(name)
            for row in rows:
                if row['before_sha256'] is not None:
                    dst = owned(target, row['path'])
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(owned(root / 'before', row['path']), dst)
            commands = [
                ['git', 'apply', '--check', str(patch)],
                ['git', 'apply', str(patch)],
            ]
            for cmd in commands:
                subprocess.run(cmd, cwd=target, check=True, capture_output=True, text=True)
            check_image(target, rows, 'after')
            subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)], cwd=target,
                           check=True, capture_output=True, text=True)
            subprocess.run(['git', 'apply', '--reverse', str(patch)], cwd=target,
                           check=True, capture_output=True, text=True)
            check_image(target, rows, 'before')
            result['patch_roundtrip'] = 'PASS_EXACT_BEFORE_AFTER_BEFORE'
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({'status': 'FAIL', 'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
