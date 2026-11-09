"""Apply the reviewed scheduler bridge to an isolated candidate copy only."""
from __future__ import annotations
import hashlib
from pathlib import Path
import subprocess
import sys

BEFORE = '6f848524e991ccb3631cb56927d3beb7361f6ee8882a2eceea5b8a58903bcf4f'
AFTER = 'e2cff40fa0daa3f2670539067fc9790ba0f6a47f3cbee3731cc97accbc6e7d3e'
PATCH_SHA = '9ac4054346e3eb973675782c17007d025d26ba399c7311a926d7f14b63b75227'


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
