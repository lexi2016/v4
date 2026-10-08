"""Observed synthetic file identity; not a real-owner read lease or OS snapshot."""
import hashlib
import os
from pathlib import Path
import stat
from .composition import no_symlinks
from .digests import sha256_json

MAX_FILES = 2000
MAX_TOTAL_BYTES = 2 * 1024**3


def snapshot_digest(root: Path) -> str:
    root = no_symlinks(root)
    if not root.is_dir():
        raise ValueError('INPUT_SNAPSHOT_MISSING')
    entries = {}; total = 0
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('INPUT_SNAPSHOT_SYMLINK')
        if path.is_dir():
            continue
        if len(entries) >= MAX_FILES:
            raise ValueError('INPUT_SNAPSHOT_TOO_MANY_FILES')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError('INPUT_SNAPSHOT_NOT_REGULAR')
            total += before.st_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError('INPUT_SNAPSHOT_TOO_LARGE')
            digest = hashlib.sha256(); consumed = 0
            while chunk := os.read(fd, 1024 * 1024):
                consumed += len(chunk)
                if consumed > before.st_size:
                    raise ValueError('INPUT_CHANGED_DURING_READ')
                digest.update(chunk)
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or consumed != before.st_size:
                raise ValueError('INPUT_CHANGED_DURING_READ')
            entries[path.relative_to(root).as_posix()] = digest.hexdigest()
        finally:
            os.close(fd)
    return sha256_json(entries)


def verify_snapshot(root, declared):
    if root is None or snapshot_digest(root) != declared:
        raise ValueError('INPUT_SNAPSHOT_MISMATCH')
