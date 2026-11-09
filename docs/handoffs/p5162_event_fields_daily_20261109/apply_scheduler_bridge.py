"""Apply the reviewed scheduler bridge to an isolated candidate copy only."""
from __future__ import annotations
import hashlib
from pathlib import Path
import subprocess
import sys

BEFORE = '6f848524e991ccb3631cb56927d3beb7361f6ee8882a2eceea5b8a58903bcf4f'
AFTER = '70b5483c0ca012f6a0293e06ae67436d2f370c38cda55b72f82d97fbd9d7b185'
PATCH_SHA = 'e33cadbfe3bcbd23b37a6911f59c6e62bf7974686916df87e687503df4cbc7c1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def apply(candidate_root):
    root = Path(candidate_root)
    if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True) != root:
        raise ValueError('BRIDGE_CANDIDATE_ROOT_INVALID')
    live = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
    if root == live or root.is_relative_to(live):
        raise ValueError('BRIDGE_LIVE_RUNTIME_FORBIDDEN')
    target = root/'infrastructure/scheduling/executor_registry.py'
    if target.is_symlink() or target.resolve(strict=True) != target or sha(target) != BEFORE:
        raise ValueError('BRIDGE_BASE_SHA_DRIFT')
    patch = Path(__file__).with_name('scheduler_runtime_bridge.patch')
    if sha(patch) != PATCH_SHA:
        raise ValueError('BRIDGE_PATCH_SHA_DRIFT')
    subprocess.run(['git','apply','--check',str(patch)],cwd=root,check=True)
    if sha(target) != BEFORE:
        raise ValueError('BRIDGE_BASE_MOVED')
    subprocess.run(['git','apply',str(patch)],cwd=root,check=True)
    if sha(target) != AFTER:
        raise ValueError('BRIDGE_RESULT_SHA_CONFLICT')
    return {'before':BEFORE,'after':AFTER,'patch_sha256':PATCH_SHA}


if __name__ == '__main__':
    if len(sys.argv)!=2:
        raise SystemExit('usage: apply_scheduler_bridge.py /absolute/isolated/candidate/root')
    print(apply(sys.argv[1]))
