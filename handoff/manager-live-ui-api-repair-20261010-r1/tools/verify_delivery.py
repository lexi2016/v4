#!/usr/bin/env python3
"""Verify delivered bytes and replay the runtime patch only in a temporary tree."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Invalid manifest path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ('', '.', '..') for part in value.split('/')):
        raise ValueError('Manifest path must be a normalized relative path')
    return value


def inventory(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): digest(path)
            for path in sorted(root.rglob('*')) if path.is_file()}


def verify_manifest(root: Path) -> dict[str, object]:
    manifest = json.loads((root / 'FILE_MANIFEST.json').read_text())
    if manifest.get('schema_version') != 'v4.manager_repair.file_manifest.v1':
        raise ValueError('Unknown delivery manifest schema')
    expected = {}
    failures = []
    for row in manifest['files']:
        relative = safe_relative(row['path'])
        if relative == 'FILE_MANIFEST.json' or relative in expected:
            raise ValueError('Duplicate or self-referential manifest path')
        expected[relative] = row
        if not re.fullmatch(r'[0-9a-f]{64}', row['sha256']):
            raise ValueError('Invalid SHA-256 in manifest')
        path = root / relative
        if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
            failures.append({'path': relative, 'reason': 'MISSING_OR_UNSAFE_PATH'})
        elif digest(path) != row['sha256'] or path.stat().st_size != row['bytes']:
            failures.append({'path': relative, 'reason': 'HASH_OR_SIZE_MISMATCH'})
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            failures.append({'path': path.relative_to(root).as_posix(), 'reason': 'SYMLINK'})
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    extras = sorted(actual - set(expected) - {'FILE_MANIFEST.json'})
    if extras:
        failures.append({'reason': 'UNMANIFESTED_FILES', 'paths': extras})
    if failures:
        raise ValueError(json.dumps(failures, ensure_ascii=False))
    return {'status': 'PASS', 'files_checked': len(expected),
            'manifest_sha256': digest(root / 'FILE_MANIFEST.json')}


def run(command: list[str], *, cwd: Path) -> dict[str, object]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(json.dumps({'command': command, 'exit_code': result.returncode,
                                      'stdout': result.stdout, 'stderr': result.stderr}))
    return {'command': command, 'exit_code': result.returncode,
            'stdout': result.stdout.strip()}


def replay_patch(root: Path) -> dict[str, object]:
    manifest = json.loads((root / 'SOURCE_SHA256.json').read_text())
    for row in manifest['modified_files']:
        safe_relative(row['path'])
    for row in manifest['unchanged_prerequisites']:
        safe_relative(row['path'])
    with tempfile.TemporaryDirectory(prefix='v4-manager-patch-verify-') as temporary:
        app = Path(temporary) / 'app'
        shutil.copytree(root / 'test_support/current', app)
        shutil.copytree(root / 'before', app, dirs_exist_ok=True)
        original = inventory(app)
        expected_after = dict(original)
        for row in manifest['modified_files']:
            relative = row['path']
            before_path, after_path = root / 'before' / relative, root / 'after' / relative
            if row['before_sha256'] is None:
                if before_path.exists() or relative in original:
                    raise ValueError('New-file preimage unexpectedly exists: ' + relative)
            elif not before_path.is_file() or digest(before_path) != row['before_sha256']:
                raise ValueError('Preimage mismatch: ' + relative)
            if not after_path.is_file() or digest(after_path) != row['after_sha256']:
                raise ValueError('Postimage mismatch: ' + relative)
            expected_after[relative] = row['after_sha256']
        gate = [sys.executable, str(root / 'tools/verify_source_gate.py'),
                '--app-root', str(app)]
        patch = str(root / 'runtime.patch')
        steps = [run([*gate, '--side', 'before'], cwd=root),
                 run(['git', 'apply', '--check', patch], cwd=app),
                 run(['git', 'apply', patch], cwd=app),
                 run([*gate, '--side', 'after'], cwd=root)]
        if inventory(app) != expected_after:
            raise ValueError('Forward patch changed bytes outside the declared postimages')
        steps += [run(['git', 'apply', '--reverse', '--check', patch], cwd=app),
                  run(['git', 'apply', '--reverse', patch], cwd=app),
                  run([*gate, '--side', 'before'], cwd=root)]
        if inventory(app) != original:
            raise ValueError('Reverse patch did not restore the exact original tree')
        return {'status': 'PASS', 'runtime_files': len(manifest['modified_files']),
                'forward_exact': True, 'reverse_exact': True,
                'temporary_tree_only': True, 'steps': steps}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--report', type=Path,
                        help='Optional JSON output outside the delivered package')
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if args.report and args.report.resolve().is_relative_to(root):
        parser.error('--report must be outside the package to preserve its manifest')
    result: dict[str, object] = {'mode': 'OFFLINE_DELIVERY_INTEGRITY_AND_PATCH_REPLAY',
                                'live_api_ui': 'LIVE_API_UI_NOT_RUN'}
    try:
        result['file_integrity'] = verify_manifest(root)
        result['patch_replay'] = replay_patch(root)
        result['status'] = 'PASS'
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        result.update(status='FAIL_CLOSED', error=str(error))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
