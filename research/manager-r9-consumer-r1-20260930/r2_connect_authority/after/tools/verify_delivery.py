#!/usr/bin/env python3
"""Check the package and replay patches ONLY in disposable isolated directories."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    manifest=json.loads((ROOT/'MANIFEST.json').read_text())
    actual={str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file()}
    expected={r['path'] for r in manifest['files']}|{'MANIFEST.json'}
    if actual!=expected:raise ValueError('PACKAGE_FILE_SET_MISMATCH')
    for r in manifest['files']:
        p=ROOT/r['path']
        if p.is_symlink() or '..' in Path(r['path']).parts or not p.resolve().is_relative_to(ROOT):
            raise ValueError('PACKAGE_UNSAFE_PATH')
        if p.stat().st_size!=r['bytes'] or sha(p)!=r['sha256']:
            raise ValueError('PACKAGE_FILE_IDENTITY_MISMATCH:'+r['path'])
    pin=json.loads((ROOT/'SOURCE_PINS.json').read_text())['runtime_files'][0]
    before=ROOT/pin['before_path'];after=ROOT/pin['after_path']
    if sha(before)!=pin['before_sha256'] or sha(after)!=pin['after_sha256']:
        raise ValueError('RUNTIME_PIN_MISMATCH')
    with tempfile.TemporaryDirectory(prefix='v4-r2-patch-check-') as temp:
        base=Path(temp);app=base/'app';app.mkdir()
        target=app/pin['target_path'];target.parent.mkdir(parents=True);shutil.copyfile(before,target)
        def apply(root,name,reverse=False):
            args=['git','apply']+(['--reverse'] if reverse else [])
            subprocess.run([*args,'--check',str(ROOT/name)],cwd=root,check=True,capture_output=True)
            subprocess.run([*args,str(ROOT/name)],cwd=root,check=True,capture_output=True)
        apply(app,'runtime.patch')
        if target.read_bytes()!=after.read_bytes():raise ValueError('FORWARD_PATCH_MISMATCH')
        apply(app,'runtime.patch',True)
        if target.read_bytes()!=before.read_bytes():raise ValueError('REVERSE_PATCH_MISMATCH')
        support=base/'support';support.mkdir()
        for name in ('tests.patch','tools.patch'):apply(support,name)
        for row in json.loads((ROOT/'SOURCE_PINS.json').read_text())['support_files']:
            if (support/row['target_path']).read_bytes()!=(ROOT/row['after_path']).read_bytes():
                raise ValueError('SUPPORT_PATCH_MISMATCH')
        for name in ('tools.patch','tests.patch'):apply(support,name,True)
        if any(p.is_file() for p in support.rglob('*')):raise ValueError('SUPPORT_REVERSE_NOT_EMPTY')
    print(json.dumps(dict(status='PACKAGE_AND_ISOLATED_PATCH_REPLAY_VERIFIED',
        checked_files=len(manifest['files']),runtime_files=1,active_runtime_touched=False)))

if __name__=='__main__':main()
