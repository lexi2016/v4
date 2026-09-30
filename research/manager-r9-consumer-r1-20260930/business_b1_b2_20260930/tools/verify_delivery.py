#!/usr/bin/env python3
"""Check delivery identities and replay patches only in a new temporary tree."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile


def main():
    package=Path(__file__).resolve().parents[1]
    manifest=json.loads((package/'MANIFEST.json').read_text())
    for row in manifest['files']:
        rel=Path(row['path'])
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('MANIFEST_PATH_INVALID')
        path=package/rel
        raw=path.read_bytes()
        if len(raw)!=row['bytes'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:
            raise ValueError('PACKAGE_IDENTITY_MISMATCH:'+row['path'])
    pins=json.loads((package/'SOURCE_PINS.json').read_text())
    with tempfile.TemporaryDirectory(prefix='issue8-business-patch-') as directory:
        root=Path(directory)
        for surface in ('api','snapshot_20260929'):
            shutil.copytree(package/'before'/surface,root,dirs_exist_ok=True)
        for patch in ('runtime.patch','cycle_snapshot.patch','tests.patch'):
            subprocess.run(['git','apply','--check',str(package/patch)],cwd=root,check=True)
            subprocess.run(['git','apply',str(package/patch)],cwd=root,check=True)
        for row in pins['files']:
            if (root/row['path']).read_bytes()!=(package/'after'/row['surface']/row['path']).read_bytes():
                raise ValueError('PATCH_AFTER_MISMATCH:'+row['path'])
        for patch in ('tests.patch','cycle_snapshot.patch','runtime.patch'):
            subprocess.run(['git','apply','-R',str(package/patch)],cwd=root,check=True)
        for row in pins['files']:
            path=root/row['path']
            if row['before_sha256'] is None:
                if path.exists():raise ValueError('ROLLBACK_NEW_FILE_REMAINED')
            elif hashlib.sha256(path.read_bytes()).hexdigest()!=row['before_sha256']:
                raise ValueError('ROLLBACK_BEFORE_MISMATCH')
    print('PASS: package identities; exact forward/reverse patch replay; no active app touched.')

if __name__=='__main__':main()
