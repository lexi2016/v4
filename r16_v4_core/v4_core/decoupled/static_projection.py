"""Read bounded bytes from immutable isolated projection members."""
from functools import lru_cache
import gzip
from hashlib import sha256
from io import BytesIO
import os
import json
from pathlib import Path
import re
import stat


def identity(status):
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns, status.st_ctime_ns


def read_member(root: Path, relative: str, expected: str, limit: int):
    item = Path(relative)
    if (item.is_absolute() or len(item.parts) != 1 or item.name == ".."
            or not item.name.endswith((".json", ".json.gz")) or not re.fullmatch("[0-9a-f]{64}", expected)):
        raise ValueError("PROJECTION_MEMBER_INVALID")
    path = root / item
    status = path.stat(follow_symlinks=False)
    if path.resolve(strict=True) != path or not stat.S_ISREG(status.st_mode) or status.st_size > limit:
        raise ValueError("PROJECTION_MEMBER_UNSAFE")
    observed = identity(status)
    return _small(path, expected, limit, observed) if limit <= 64 * 1024 * 1024 else _open(path, expected, limit, observed)


@lru_cache(maxsize=8)
def _small(path, expected, limit, observed):
    return _open(path, expected, limit, observed)


def _open(path, expected, limit, observed):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if identity(os.fstat(stream.fileno())) != observed:
            raise ValueError("PROJECTION_MEMBER_CHANGED")
        raw = stream.read(limit + 1)
        if identity(os.fstat(stream.fileno())) != observed:
            raise ValueError("PROJECTION_MEMBER_CHANGED")
    if len(raw) > limit or sha256(raw).hexdigest() != expected:
        raise ValueError("PROJECTION_MEMBER_SHA_MISMATCH")
    if path.name.endswith(".json.gz"):
        with gzip.GzipFile(fileobj=BytesIO(raw)) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("PROJECTION_MEMBER_RESPONSE_LIMIT")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("PROJECTION_MEMBER_NOT_OBJECT")
    return result
