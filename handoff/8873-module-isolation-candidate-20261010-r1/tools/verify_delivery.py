#!/usr/bin/env python3
"""Read-only package verification plus patch replay in a new temporary tree."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entries(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path)
            for path in sorted(root.rglob('*')) if path.is_file() and '.git' not in path.relative_to(root).parts}


def run(*command: str, cwd: Path):
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f'{command!r}: exit={result.returncode}\n{result.stdout}\n{result.stderr}')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, help='Optional new external JSON receipt; parent must exist.')
    args = parser.parse_args()
    sums = ROOT / 'PACKAGE_SHA256SUMS.txt'
    expected = {}
    for line in sums.read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or name in expected:
            raise ValueError('PACKAGE_MANIFEST_PATH_INVALID')
        expected[name] = digest
    actual = {name: digest for name, digest in entries(ROOT).items() if name != sums.name}
    if set(actual) != set(expected):
        raise ValueError(f'PACKAGE_FILE_SET_MISMATCH missing={sorted(set(expected)-set(actual))} extra={sorted(set(actual)-set(expected))}')
    for name, digest in expected.items():
        if actual[name] != digest:
            raise ValueError('PACKAGE_SHA_MISMATCH:' + name)
    for path in ROOT.rglob('*'):
        if path.is_symlink():
            raise ValueError('PACKAGE_SYMLINK:' + str(path))
        if path.is_file() and path.suffix == '.json':
            json.loads(path.read_text())
        if path.is_file() and path.suffix == '.py':
            ast.parse(path.read_text(), filename=str(path))
    before = entries(ROOT / 'before')
    after = entries(ROOT / 'full-after')
    with tempfile.TemporaryDirectory(prefix='v4-issue30-patch-replay-') as temporary:
        trial = Path(temporary) / 'trial'
        shutil.copytree(ROOT / 'before', trial)
        run('git', 'init', '-q', cwd=trial)
        for name in ('runtime.patch', 'native-reference.patch'):
            run('git', 'apply', '--check', str(ROOT / name), cwd=trial)
            run('git', 'apply', str(ROOT / name), cwd=trial)
        if entries(trial) != after:
            raise ValueError('FORWARD_PATCH_AFTER_MISMATCH')
        run('git', 'apply', '--check', str(ROOT / 'reverse.patch'), cwd=trial)
        run('git', 'apply', str(ROOT / 'reverse.patch'), cwd=trial)
        if entries(trial) != before:
            raise ValueError('REVERSE_PATCH_BEFORE_MISMATCH')
    report = {'status': 'PASS', 'package_files': len(expected) + 1,
              'before_files': len(before), 'after_files': len(after),
              'all_sha_verified': True, 'json_python_syntax_verified': True,
              'forward_patch_exact_after': True, 'reverse_patch_exact_before': True,
              'service_actions': False, 'writes': 'new temporary replay tree only'}
    if args.receipt:
        target = args.receipt.absolute()
        if target.is_relative_to(ROOT) or not target.parent.is_dir():
            raise ValueError('RECEIPT_MUST_HAVE_EXISTING_EXTERNAL_PARENT')
        with target.open('x') as handle:
            json.dump(report, handle, indent=2, sort_keys=True); handle.write('\n')
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
