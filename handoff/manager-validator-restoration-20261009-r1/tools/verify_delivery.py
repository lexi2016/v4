#!/usr/bin/env python3
"""Verify the handoff and replay its single-file patch in temporary storage."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--expect', choices=('before', 'after'), default='before')
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[1]
    manifest = json.loads((package / 'MANIFEST.json').read_text())
    for entry in manifest['files']:
        path = package / entry['path']
        if not path.resolve().is_relative_to(package) or not path.is_file():
            raise SystemExit('PACKAGE_PATH_INVALID: ' + entry['path'])
        if path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']:
            raise SystemExit('PACKAGE_FILE_MISMATCH: ' + entry['path'])
    allowed_path = 'apps/web/src/api/managerWorkspace.ts'
    if manifest['production_change']['path'] != allowed_path:
        raise SystemExit('PRODUCTION_PATH_INVALID')
    relative = Path(allowed_path)
    before = package / 'before' / relative
    after = package / 'after' / relative
    if args.source_root is not None:
        root = args.source_root.resolve(strict=True)
        target = root / relative
        if not target.resolve().is_relative_to(root) or not target.is_file():
            raise SystemExit('TARGET_PATH_INVALID')
        wanted = manifest['production_change'][args.expect + '_sha256']
        if digest(target) != wanted:
            raise SystemExit('TARGET_SHA_MISMATCH: ' + str(target))
    with tempfile.TemporaryDirectory(prefix='manager-validator-patch-') as temporary:
        root = Path(temporary)
        target = root / relative
        target.parent.mkdir(parents=True)
        shutil.copyfile(before, target)
        patch = str(package / 'runtime.patch')
        for flags in [('--check',), ()]:
            subprocess.run(['git', 'apply', *flags, patch], cwd=root, check=True)
        if target.read_bytes() != after.read_bytes():
            raise SystemExit('PATCH_AFTER_MISMATCH')
        for flags in [('--reverse', '--check'), ('--reverse',)]:
            subprocess.run(['git', 'apply', *flags, patch], cwd=root, check=True)
        if target.read_bytes() != before.read_bytes():
            raise SystemExit('PATCH_ROLLBACK_MISMATCH')
    print(json.dumps({'status': 'PASS', 'manifest_payloads': len(manifest['files']),
                      'patch_apply': 'PASS', 'patch_rollback': 'PASS',
                      'target_check': args.expect if args.source_root else 'NOT_REQUESTED'}))


if __name__ == '__main__':
    main()
