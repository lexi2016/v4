"""The original native append uses a per-directory CAS lock and atomic replace.

This does not claim exclusion of unrelated programs that ignore this lock.
"""
from __future__ import annotations
import hashlib, os, stat, tempfile
from pathlib import Path
from infrastructure.interprocess_lock import owned_interprocess_lock


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def commit(scope, path, *, suffix, expected=Ellipsis):
    path = Path(path)
    if scope['_local_path_failure'](path):
        raise ValueError('A_SYNC_SOURCE_PATH_REJECTED')
    path.parent.mkdir(parents=True,exist_ok=True)
    lock = path.parent / '.a_share_native_write'
    with owned_interprocess_lock(lock,timeout_seconds=5.0,timeout_message='A native writer already active'):
        failure = scope['_local_path_failure'](path)
        if failure:
            raise ValueError('A_SYNC_SOURCE_PATH_REJECTED:'+failure)
        before = path.read_bytes() if path.exists() else None
        digest = _sha(before) if before is not None else None
        if expected is not Ellipsis and digest != expected:
            raise ValueError('A_SYNC_SOURCE_CAS_MOVED')
        after = (before or b'') + suffix
        if after==before:
            return dict(path=str(path),before_sha256=digest,after_sha256=digest,
                lock=str(lock),cooperating_paths_only=True,
                prefix_unchanged=True,no_op=True)
        if len(after)%32:
            raise ValueError('A_SYNC_NATIVE_SHAPE_INVALID')
        fd, raw = tempfile.mkstemp(prefix='.'+path.name+'.',suffix='.tmp',dir=path.parent)
        temporary = Path(raw)
        try:
            if path.exists():os.fchmod(fd,stat.S_IMODE(path.stat().st_mode))
            with os.fdopen(fd,'wb') as handle:
                handle.write(after);handle.flush();os.fsync(handle.fileno())
            if (path.read_bytes() if path.exists() else None) != before:
                raise ValueError('A_SYNC_SOURCE_CAS_MOVED_BEFORE_REPLACE')
            os.replace(temporary,path)
            directory = os.open(path.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
            if path.read_bytes()!=after:
                raise ValueError('A_SYNC_NATIVE_READBACK_CONFLICT')
        finally:
            temporary.unlink(missing_ok=True)
        return dict(path=str(path),before_sha256=digest,after_sha256=_sha(after),
                    lock=str(lock),
                    cooperating_paths_only=True,prefix_unchanged=True)
