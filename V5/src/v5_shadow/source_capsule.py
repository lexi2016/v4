"""Byte provenance validation. This does not attest a source import closure."""
import hashlib
import json
import platform
import re
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from .contracts import SourceCapsule, SourceEntry


def _entries_digest(entries):
    return hashlib.sha256(json.dumps([asdict(e) for e in entries], sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def checked_path(root: Path, relative: str) -> Path:
    p = PurePosixPath(relative)
    if not relative or p.is_absolute() or '\\' in relative or any(x in ('', '.', '..') for x in relative.split('/')):
        raise ValueError('SOURCE_PATH_INVALID')
    root = Path(root).absolute()
    # Reject symlinks in root as well as all descendant components.
    for component in (root, *root.parents):
        if component.is_symlink():
            raise ValueError('SOURCE_PATH_INVALID')
    target = root.joinpath(*p.parts)
    for component in (target, *target.parents):
        if component == root.parent:
            break
        if component.is_symlink():
            raise ValueError('SOURCE_PATH_INVALID')
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('SOURCE_PATH_INVALID')
    return target


def inspect_capsule(capsule_root: Path, entries: tuple[SourceEntry, ...]) -> SourceCapsule:
    entries = tuple(entries)
    paths = set()
    if not entries:
        raise ValueError('SOURCE_CLOSURE_INCOMPLETE')
    for entry in entries:
        checked_path(capsule_root, entry.relative_path)
        if entry.relative_path in paths:
            raise ValueError('SOURCE_DUPLICATE')
        paths.add(entry.relative_path)
        for value, size in ((entry.commit,40),(entry.git_blob_sha,40),(entry.sha256,64)):
            if not isinstance(value,str) or re.fullmatch('[0-9a-f]{'+str(size)+'}',value) is None:
                raise ValueError('SOURCE_IDENTITY_INVALID')
        if entry.variant != 'api' or entry.repository != 'lexi2016/v4':
            raise ValueError('SOURCE_VARIANT_INVALID')
    lock = Path(capsule_root) / 'dependencies.lock'
    lock_sha = hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() and not lock.is_symlink() else ''
    return SourceCapsule(entries, _entries_digest(entries), platform.python_version(), lock_sha)


def verify_capsule(capsule: SourceCapsule, root: Path) -> tuple[str, ...]:
    errors = set()
    if capsule.manifest_sha256 != _entries_digest(capsule.entries):
        errors.add('SOURCE_MANIFEST_MISMATCH')
    declared = {e.relative_path for e in capsule.entries}
    for entry in capsule.entries:
        try:
            path = checked_path(root, entry.relative_path)
        except ValueError:
            errors.add('SOURCE_PATH_INVALID')
            continue
        if not path.is_file():
            errors.add('SOURCE_MISSING')
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry.sha256:
            errors.add('SOURCE_SHA_MISMATCH')
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != entry.git_blob_sha:
            errors.add('SOURCE_BLOB_MISMATCH')
    for path in Path(root).rglob('*'):
        if path.is_symlink():
            errors.add('SOURCE_PATH_INVALID')
        elif path.is_file() and path.relative_to(root).as_posix() not in declared:
            errors.add('SOURCE_UNDECLARED')
    return tuple(sorted(errors))
