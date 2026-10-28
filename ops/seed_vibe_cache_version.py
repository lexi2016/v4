"""Seed one fresh V4 Vibe version from its pinned migrated-cache inventory.

This is a one-off migration helper for an explicitly approved destination. It
does not collect data, select a version, or read any credential.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import uuid
from typing import Callable, Mapping

from domains.research_review_generation._owned_io import BoundaryError


MANIFEST_PATH = Path(__file__).resolve().parents[1] / "domains/research_review_generation/HISTORICAL_CACHE_MANIFEST.json"
MANIFEST_SHA256 = "92720cc3a6346afaba0efa995452da1304848ed0a52345c667682cd1775ed54d"
MANIFEST_SCHEMA = "v4.vibe_cache_inventory.v1"
_ALLOWED_FAMILIES = (
    "cache/market_facts/",
    "cache/zt_summary/",
    "cache/prev_pool/",
    "cache/breadth/",
    "cache/zt_reasons/",
    "leaders/",
    "reflections/",
)
_MAX_FILE_BYTES = 32 * 1024 * 1024
_MAX_TOTAL_BYTES = 512 * 1024 * 1024


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _explicit_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or "~" in path.parts:
        raise BoundaryError("CACHE_SEED_PATH_INVALID")
    return path


def _validate_relative_name(name: object) -> str:
    if not isinstance(name, str) or not name or "\\" in name:
        raise BoundaryError("CACHE_SEED_MANIFEST_PATH_INVALID")
    rel = PurePosixPath(name)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise BoundaryError("CACHE_SEED_MANIFEST_PATH_INVALID")
    if not name.endswith(".json") or not name.startswith(_ALLOWED_FAMILIES):
        raise BoundaryError("CACHE_SEED_MANIFEST_PATH_INVALID")
    family = next(prefix for prefix in _ALLOWED_FAMILIES if name.startswith(prefix))
    tail = name[len(family) :]
    if not tail or "/" in tail:
        raise BoundaryError("CACHE_SEED_MANIFEST_PATH_INVALID")
    return name


def _validated_entries(manifest: object, *, require_pinned_inventory: bool) -> dict[str, dict]:
    if not isinstance(manifest, dict) or set(manifest) != {"schema", "source", "files"}:
        raise BoundaryError("CACHE_SEED_MANIFEST_INVALID")
    if manifest.get("schema") != MANIFEST_SCHEMA or not isinstance(manifest.get("files"), dict):
        raise BoundaryError("CACHE_SEED_MANIFEST_INVALID")
    entries: dict[str, dict] = {}
    family_counts = {prefix: 0 for prefix in _ALLOWED_FAMILIES}
    total = 0
    for raw_name, info in manifest["files"].items():
        name = _validate_relative_name(raw_name)
        if name in entries or not isinstance(info, dict) or set(info) != {"bytes", "sha256"}:
            raise BoundaryError("CACHE_SEED_MANIFEST_INVALID")
        size, digest = info.get("bytes"), info.get("sha256")
        if type(size) is not int or size < 0 or size > _MAX_FILE_BYTES:
            raise BoundaryError("CACHE_SEED_MANIFEST_INVALID")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise BoundaryError("CACHE_SEED_MANIFEST_INVALID")
        entries[name] = {"bytes": size, "sha256": digest}
        total += size
        family_counts[next(prefix for prefix in _ALLOWED_FAMILIES if name.startswith(prefix))] += 1
    if not entries:
        raise BoundaryError("CACHE_SEED_MANIFEST_EMPTY")
    if total > _MAX_TOTAL_BYTES:
        raise BoundaryError("CACHE_SEED_MANIFEST_TOO_LARGE")
    if require_pinned_inventory and (
        len(entries) != 80
        or family_counts["leaders/"] != 10
        or family_counts["reflections/"] != 8
        or sum(family_counts[p] for p in _ALLOWED_FAMILIES if p.startswith("cache/")) != 62
    ):
        raise BoundaryError("CACHE_SEED_PINNED_INVENTORY_SHAPE_INVALID")
    if "cache/zt_reasons/2026-09-24.json" in entries or ".ownership/generated-cache.json" in entries:
        raise BoundaryError("CACHE_SEED_FORBIDDEN_GENERATED_ENTRY")
    return entries


def _load_pinned_manifest() -> dict[str, dict]:
    try:
        raw = MANIFEST_PATH.read_bytes()
    except OSError:
        raise BoundaryError("CACHE_SEED_MANIFEST_UNAVAILABLE") from None
    if _digest(raw) != MANIFEST_SHA256:
        raise BoundaryError("CACHE_SEED_MANIFEST_SHA_MISMATCH")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise BoundaryError("CACHE_SEED_MANIFEST_INVALID") from None
    return _validated_entries(value, require_pinned_inventory=True)


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags)


def _read_source_file(root_fd: int, name: str, expected: Mapping[str, object]) -> bytes:
    parts = PurePosixPath(name).parts
    parent_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            os.close(parent_fd)
            parent_fd = next_fd
        fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size != expected["bytes"]:
                raise BoundaryError("CACHE_SEED_SOURCE_FILE_INVALID")
            if info.st_size > _MAX_FILE_BYTES:
                raise BoundaryError("CACHE_SEED_SOURCE_FILE_TOO_LARGE")
            chunks: list[bytes] = []
            remaining = _MAX_FILE_BYTES + 1
            while remaining:
                block = os.read(fd, min(1024 * 1024, remaining))
                if not block:
                    break
                chunks.append(block)
                remaining -= len(block)
            raw = b"".join(chunks)
        finally:
            os.close(fd)
    except BoundaryError:
        raise
    except OSError:
        raise BoundaryError("CACHE_SEED_SOURCE_FILE_UNSAFE_OR_MISSING") from None
    finally:
        os.close(parent_fd)
    if len(raw) != expected["bytes"] or _digest(raw) != expected["sha256"]:
        raise BoundaryError("CACHE_SEED_SOURCE_FILE_SHA_MISMATCH")
    return raw


def _write_stage_file(stage: Path, name: str, raw: bytes) -> None:
    destination = stage / "cache_store" / Path(*PurePosixPath(name).parts)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def _rename_stage_no_replace(stage: Path, destination: Path) -> None:
    """Atomically publish the staged directory only if its name is still absent.

    macOS exposes RENAME_EXCL through renameatx_np; ordinary os.rename may
    replace a directory created after the last lexists check. Unsupported
    platforms or filesystems must fail closed rather than fall back to rename.
    """
    if sys.platform != "darwin" or not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise BoundaryError("CACHE_SEED_ATOMIC_COMMIT_UNAVAILABLE")
    try:
        library = ctypes.CDLL(None, use_errno=True)
        renameatx_np = library.renameatx_np
    except (AttributeError, OSError):
        raise BoundaryError("CACHE_SEED_ATOMIC_COMMIT_UNAVAILABLE") from None
    renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameatx_np.restype = ctypes.c_int
    try:
        parent_fd = os.open(stage.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise BoundaryError("CACHE_SEED_ATOMIC_COMMIT_PARENT_UNAVAILABLE") from None
    try:
        result = renameatx_np(
            parent_fd,
            os.fsencode(stage.name),
            parent_fd,
            os.fsencode(destination.name),
            0x00000004,  # RENAME_EXCL from the macOS SDK's sys/stdio.h.
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise BoundaryError("CACHE_SEED_DESTINATION_NOT_ABSENT")
        unsupported = {
            errno.EINVAL,
            errno.ENOTSUP,
            getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
            getattr(errno, "ENOSYS", errno.ENOTSUP),
        }
        if error_number in unsupported:
            raise BoundaryError("CACHE_SEED_ATOMIC_COMMIT_UNAVAILABLE")
        raise BoundaryError("CACHE_SEED_ATOMIC_COMMIT_FAILED:" + str(error_number))
    finally:
        os.close(parent_fd)


def _seed_from_entries(
    source_cache_root: str | Path,
    destination_state_root: str | Path,
    entries: Mapping[str, Mapping[str, object]],
    *,
    manifest_sha256: str | None = None,
    _after_copy: Callable[[str], None] | None = None,
) -> dict:
    """Private testable transaction; callers cannot choose a production manifest."""
    source = _explicit_path(source_cache_root)
    destination = _explicit_path(destination_state_root)
    if source == destination or source in destination.parents or destination in source.parents:
        raise BoundaryError("CACHE_SEED_ROOTS_OVERLAP")
    try:
        if source.is_symlink() or not source.is_dir() or source.resolve(strict=True) != source:
            raise BoundaryError("CACHE_SEED_SOURCE_ROOT_UNSAFE")
        if os.path.lexists(destination):
            raise BoundaryError("CACHE_SEED_DESTINATION_NOT_ABSENT")
    except BoundaryError:
        raise
    except OSError:
        raise BoundaryError("CACHE_SEED_SOURCE_ROOT_UNAVAILABLE") from None

    normalized = _validated_entries(
        {"schema": MANIFEST_SCHEMA, "source": "testable-pinned-entry-map", "files": dict(entries)},
        require_pinned_inventory=False,
    )
    try:
        source_fd = _open_directory(source)
    except OSError:
        raise BoundaryError("CACHE_SEED_SOURCE_ROOT_UNSAFE") from None
    try:
        # Validate every listed source byte before creating any output path.
        source_bytes = {name: _read_source_file(source_fd, name, info) for name, info in normalized.items()}
    finally:
        os.close(source_fd)

    parent = destination.parent
    try:
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if parent.is_symlink() or not parent.is_dir() or parent.resolve(strict=True) != parent:
            raise BoundaryError("CACHE_SEED_DESTINATION_PARENT_UNSAFE")
    except BoundaryError:
        raise
    except OSError:
        raise BoundaryError("CACHE_SEED_DESTINATION_PARENT_UNAVAILABLE") from None

    lock_path = parent / ("." + destination.name + ".seed.lock")
    stage = parent / ("." + destination.name + ".seed-stage-" + uuid.uuid4().hex)
    lock_fd = None
    stage_created = False
    try:
        lock_fd = os.open(
            lock_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.write(lock_fd, b"v4-vibe-cache-seed\n")
        os.fsync(lock_fd)
        if os.path.lexists(destination):
            raise BoundaryError("CACHE_SEED_DESTINATION_NOT_ABSENT")
        stage.mkdir(mode=0o700)
        stage_created = True
        (stage / "cache_store").mkdir(mode=0o700)
        for name, raw in source_bytes.items():
            _write_stage_file(stage, name, raw)
            if _after_copy is not None:
                _after_copy(name)
        for name, info in normalized.items():
            copied = (stage / "cache_store" / Path(*PurePosixPath(name).parts)).read_bytes()
            if len(copied) != info["bytes"] or _digest(copied) != info["sha256"]:
                raise BoundaryError("CACHE_SEED_STAGED_FILE_SHA_MISMATCH")
        if os.path.lexists(destination):
            raise BoundaryError("CACHE_SEED_DESTINATION_NOT_ABSENT")
        _rename_stage_no_replace(stage, destination)
        stage_created = False
    except FileExistsError:
        raise BoundaryError("CACHE_SEED_ALREADY_RUNNING") from None
    except BoundaryError as error:
        if stage_created:
            quarantine = parent / ("." + destination.name + ".seed-quarantine-" + uuid.uuid4().hex)
            try:
                os.rename(stage, quarantine)
            except OSError:
                quarantine = stage
            raise BoundaryError(str(error) + ";STAGING_QUARANTINED:" + str(quarantine)) from None
        raise
    except Exception:
        if stage_created:
            quarantine = parent / ("." + destination.name + ".seed-quarantine-" + uuid.uuid4().hex)
            try:
                os.rename(stage, quarantine)
            except OSError:
                quarantine = stage
            raise BoundaryError("CACHE_SEED_COPY_FAILED;STAGING_QUARANTINED:" + str(quarantine)) from None
        raise BoundaryError("CACHE_SEED_FAILED") from None
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
    return {
        "status": "SEEDED_UNSELECTED_VERSION",
        "destination_state_root": str(destination),
        "cache_root": str(destination / "cache_store"),
        "cache_files": len(normalized),
        "manifest_sha256": manifest_sha256,
        "generated_cache_ledger_created": False,
    }


def seed_cache_version(source_cache_root: str | Path, destination_state_root: str | Path) -> dict:
    """Run only with explicit authorization to create the absent version root."""
    entries = _load_pinned_manifest()
    return _seed_from_entries(
        source_cache_root,
        destination_state_root,
        entries,
        manifest_sha256=MANIFEST_SHA256,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cache-root", required=True)
    parser.add_argument("--destination-state-root", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = seed_cache_version(args.source_cache_root, args.destination_state_root)
    except BoundaryError as exc:
        result = {"status": "CANNOT_CONFIRM", "reason": str(exc)}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
