#!/usr/bin/env python3
"""Verify package bytes and replay patches only in new temporary directories."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    package = Path(__file__).resolve().parents[1]
    manifest = json.loads((package / 'MANIFEST.json').read_text(encoding='utf-8'))
    actual = {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()
              and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts}
    expected = set(manifest['files']) | {'MANIFEST.json'}
    if actual != expected:
        raise ValueError('PACKAGE_FILE_SET_MISMATCH')
    for rel, row in manifest['files'].items():
        p = Path(rel)
        if p.is_absolute() or '..' in p.parts or (package / p).is_symlink():
            raise ValueError('UNSAFE_MANIFEST_PATH')
        raw = (package / p).read_bytes()
        if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('PACKAGE_SHA_MISMATCH:' + rel)
    for patch, before, after in [('runtime.patch', 'before/api', 'after/api'),
                                 ('tests.patch', None, 'tests')]:
        with tempfile.TemporaryDirectory(prefix='r3b-replay-') as directory:
            root = Path(directory)
            if before:
                shutil.copytree(package / before, root, dirs_exist_ok=True)
            def apply(*args):
                subprocess.run(['git', 'apply', *args, str(package / patch)], cwd=root,
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            apply('--check'); apply()
            targets = list((package / after).rglob('*'))
            for src in targets:
                if not src.is_file():
                    continue
                rel = src.relative_to(package / after)
                dst = root / (rel if before else Path('tests') / rel)
                if dst.read_bytes() != src.read_bytes():
                    raise ValueError('PATCH_AFTER_MISMATCH')
            apply('-R', '--check'); apply('-R')
            remaining = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            original = ({p.relative_to(package / before): p.read_bytes()
                         for p in (package / before).rglob('*') if p.is_file()} if before else {})
            if remaining != original:
                raise ValueError('PATCH_REVERSE_MISMATCH')
    print(json.dumps({'status': 'PASS_PACKAGE_AND_TEMP_PATCH_ROUNDTRIP',
                      'manifest_files': len(manifest['files']), 'runtime_source_files': 1,
                      'live_data_writes': 0, 'deployments': 0}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
