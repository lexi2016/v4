from __future__ import annotations

import argparse
import errno
import hashlib
import importlib
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

_DATE_RE = re.compile(r"^\d{8}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_ALLOWED_POOLS = frozenset({
    "a_d1_premarket_pool",
    "a_d1_fupan_watchlist_pool",
    "a_d1_stage7_fenshi_review_pool",
    "a_share_research_recommendation_pool",
    "a_share_baimao_research_map",
    "hkconnect_d1_top100",
    "wechat_public_account_v3_preselect",
})


class SnapshotCanaryError(ValueError):
    pass


class _Store(Protocol):
    def read_pool_snapshot(self, trade_date: str, pool_id: str) -> Mapping[str, Any]: ...


def _fail(code: str, message: str) -> None:
    raise SnapshotCanaryError(f"{code}: {message}")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolved(path: Path | str) -> Path:
    # Check the lexical path before resolve(); resolving first would erase the
    # very symlink evidence this fail-closed canary is meant to reject.
    lexical = Path(path).expanduser()
    if not lexical.is_absolute():
        lexical = Path.cwd() / lexical
    lexical = Path(os.path.abspath(os.fspath(lexical)))
    if lexical.is_symlink() or any(parent.is_symlink() for parent in lexical.parents):
        _fail("SYMLINK_REJECTED", str(lexical))
    return lexical.resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_identity(
    trade_date: str, pool_id: str, run_id: str, *, allowed_pool_ids: frozenset[str] = _ALLOWED_POOLS
) -> None:
    if not _DATE_RE.fullmatch(trade_date):
        _fail("TRADE_DATE_INVALID", trade_date)
    if pool_id not in allowed_pool_ids:
        _fail("POOL_ID_INVALID", pool_id)
    if not _RUN_ID_RE.fullmatch(run_id):
        _fail("RUN_ID_INVALID", run_id)


def _validate_pool_rows(snapshot: Mapping[str, Any], pool_id: str) -> tuple[int, str]:
    artifact = snapshot.get("artifact")
    if not isinstance(artifact, Mapping):
        _fail("POOL_ARTIFACT_INVALID", "artifact missing from owner store snapshot")
    rows = artifact.get("rows")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, Mapping) for row in rows):
        _fail("POOL_ROWS_INVALID", pool_id)
    codes: list[str] = []
    for row in rows:
        code = str(row.get("code") or row.get("code_norm") or row.get("symbol") or "").strip()
        if not code:
            _fail("POOL_CODE_MISSING", pool_id)
        codes.append(code)
    if len(set(codes)) != len(codes):
        _fail("DUPLICATE_POOL_CODE", pool_id)
    if pool_id == "hkconnect_d1_top100" and len(rows) != 100:
        _fail("HK_D1_ROW_COUNT_INVALID", f"expected=100 actual={len(rows)}")
    return len(rows), hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest()


def _reject_symlink_descendants(path: Path, stop_root: Path) -> None:
    current = path
    while current != stop_root and _is_relative_to(current, stop_root):
        if current.is_symlink():
            _fail("SYMLINK_REJECTED", str(current))
        current = current.parent


def _directory_open_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None or os.open not in os.supports_dir_fd:
        _fail("SECURE_PATH_API_UNAVAILABLE", "directory-relative O_NOFOLLOW open is required")
    return os.O_RDONLY | directory | nofollow


def _output_directory_error(parent_fd: int, name: str, error: OSError) -> None:
    try:
        item = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        item = None
    if item is not None and stat.S_ISLNK(item.st_mode):
        _fail("SYMLINK_REJECTED", name)
    if error.errno == errno.ENOENT:
        _fail("OUTPUT_PARENT_MISSING", name)
    if error.errno in (errno.ELOOP, errno.ENOTDIR):
        _fail("OUTPUT_PARENT_INVALID", name)
    raise error


def _open_directory_child(parent_fd: int, name: str, *, create: bool) -> int:
    if not name or name in (".", "..") or "/" in name:
        _fail("PATH_ESCAPE", name)
    flags = _directory_open_flags()
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError as error:
        if not create:
            _output_directory_error(parent_fd, name, error)
        try:
            os.mkdir(name, 0o777, dir_fd=parent_fd)
        except FileExistsError:
            pass
        try:
            return os.open(name, flags, dir_fd=parent_fd)
        except OSError as open_error:
            _output_directory_error(parent_fd, name, open_error)
    except OSError as error:
        _output_directory_error(parent_fd, name, error)


def _open_absolute_directory(path: Path, *, create: bool) -> int:
    absolute = Path(os.path.abspath(os.fspath(path)))
    if not absolute.is_absolute():
        _fail("OUTPUT_ROOT_INVALID", str(absolute))
    flags = _directory_open_flags()
    try:
        current_fd = os.open(absolute.anchor, flags)
    except OSError as error:
        _fail("OUTPUT_ROOT_INVALID", f"{absolute.anchor}: {error}")
    try:
        for component in absolute.parts[1:]:
            next_fd = _open_directory_child(current_fd, component, create=create)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _fd_identity(fd: int) -> tuple[int, int]:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def _open_output_parent(
    staging_root: Path,
    run_root: Path,
    destination: Path,
    *,
    create: bool,
) -> tuple[int, str, tuple[tuple[int, int], tuple[int, int], tuple[int, int]]]:
    staging = Path(os.path.abspath(os.fspath(staging_root)))
    run = Path(os.path.abspath(os.fspath(run_root)))
    target = Path(os.path.abspath(os.fspath(destination)))
    if run.parent != staging or run == staging:
        _fail("PATH_ESCAPE", str(run_root))
    try:
        relative = target.relative_to(run)
    except ValueError:
        _fail("PATH_ESCAPE", str(destination))
    if not relative.parts:
        _fail("PATH_ESCAPE", str(destination))

    opened: list[int] = []
    try:
        staging_fd = _open_absolute_directory(staging, create=create)
        opened.append(staging_fd)
        run_fd = _open_directory_child(staging_fd, run.name, create=create)
        opened.append(run_fd)
        parent_fd = run_fd
        for component in relative.parts[:-1]:
            parent_fd = _open_directory_child(parent_fd, component, create=create)
            opened.append(parent_fd)
        identities = (
            _fd_identity(staging_fd),
            _fd_identity(run_fd),
            _fd_identity(parent_fd),
        )
        name = relative.parts[-1]
        for fd in opened:
            if fd != parent_fd:
                os.close(fd)
        return parent_fd, name, identities
    except BaseException:
        for fd in opened:
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def _verify_output_parent_binding(
    staging_root: Path,
    run_root: Path,
    destination: Path,
    expected: tuple[tuple[int, int], tuple[int, int], tuple[int, int]],
) -> None:
    parent_fd, _name, observed = _open_output_parent(
        staging_root, run_root, destination, create=False
    )
    try:
        if observed != expected:
            _fail("OUTPUT_PATH_RACE", str(destination))
    finally:
        os.close(parent_fd)


def _existing_regular_bytes(parent_fd: int, name: str) -> bytes | None:
    if os.stat not in os.supports_dir_fd or os.stat not in os.supports_follow_symlinks:
        _fail("SECURE_PATH_API_UNAVAILABLE", "directory-relative no-follow stat is required")
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(before.st_mode):
        _fail("SYMLINK_REJECTED", name)
    if not stat.S_ISREG(before.st_mode):
        _fail("OUTPUT_PATH_INVALID", name)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None or os.open not in os.supports_dir_fd:
        _fail("SECURE_PATH_API_UNAVAILABLE", "directory-relative O_NOFOLLOW open is required")
    try:
        file_fd = os.open(name, os.O_RDONLY | nofollow, dir_fd=parent_fd)
    except OSError as error:
        _fail("OUTPUT_PATH_RACE", f"{name}: {error}")
    try:
        opened = os.fstat(file_fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            _fail("OUTPUT_PATH_RACE", name)
        with os.fdopen(file_fd, "rb") as handle:
            file_fd = -1
            data = handle.read()
        after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if stat.S_ISLNK(after.st_mode) or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            _fail("OUTPUT_PATH_RACE", name)
        return data
    finally:
        if file_fd >= 0:
            os.close(file_fd)


def _remove_if_owned(parent_fd: int, name: str, identity: tuple[int, int]) -> None:
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as error:
        _fail("OUTPUT_ROLLBACK_FAILED", f"{name}: {error}")
    if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == identity:
        try:
            os.unlink(name, dir_fd=parent_fd)
        except OSError as error:
            _fail("OUTPUT_ROLLBACK_FAILED", f"{name}: {error}")


def _read_output_bytes(
    destination: Path,
    *,
    staging_root: Path,
    run_root: Path,
) -> bytes:
    parent_fd, name, identities = _open_output_parent(
        staging_root, run_root, destination, create=False
    )
    try:
        data = _existing_regular_bytes(parent_fd, name)
        if data is None:
            _fail("OUTPUT_PATH_MISSING", str(destination))
        _verify_output_parent_binding(staging_root, run_root, destination, identities)
        return data
    finally:
        os.close(parent_fd)


def _copied_output_bindings(
    staging_root: Path,
    run_root: Path,
    copied: list[Mapping[str, Any]],
) -> dict[str, tuple[tuple[tuple[str, tuple[int, int]], ...], tuple[int, int], str]]:
    """Read each copied file through no-follow directory FDs and bind its path.

    The returned record includes every directory below the staging root and the
    final regular file identity. Repeating this check around the store readback
    detects an inner-directory replacement even when run_root itself is stable.
    """
    if os.stat not in os.supports_dir_fd or os.stat not in os.supports_follow_symlinks:
        _fail("SECURE_PATH_API_UNAVAILABLE", "directory-relative no-follow stat is required")

    staging = Path(os.path.abspath(os.fspath(staging_root)))
    run = Path(os.path.abspath(os.fspath(run_root)))
    if run.parent != staging or run == staging:
        _fail("PATH_ESCAPE", str(run_root))

    bindings: dict[
        str, tuple[tuple[tuple[str, tuple[int, int]], ...], tuple[int, int], str]
    ] = {}
    for item in copied:
        relative = Path(str(item.get("relative_path") or ""))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            _fail("PATH_ESCAPE", str(relative))
        digest_expected = str(item.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest_expected):
            _fail("COPY_SHA_INVALID", str(relative))

        opened: list[int] = []
        try:
            staging_fd = _open_absolute_directory(staging, create=False)
            opened.append(staging_fd)
            directories: list[tuple[str, tuple[int, int]]] = [
                ("<staging>", _fd_identity(staging_fd))
            ]
            parent_fd = staging_fd
            run_fd = _open_directory_child(parent_fd, run.name, create=False)
            opened.append(run_fd)
            parent_fd = run_fd
            directories.append((run.name, _fd_identity(run_fd)))

            for component in relative.parts[:-1]:
                child_fd = _open_directory_child(parent_fd, component, create=False)
                opened.append(child_fd)
                parent_fd = child_fd
                directories.append((component, _fd_identity(child_fd)))

            name = relative.parts[-1]
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                _fail("SYMLINK_REJECTED", str(relative))
            if not stat.S_ISREG(before.st_mode):
                _fail("OUTPUT_PATH_INVALID", str(relative))
            data = _existing_regular_bytes(parent_fd, name)
            if data is None:
                _fail("OUTPUT_PATH_MISSING", str(relative))
            after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            before_identity = (before.st_dev, before.st_ino)
            after_identity = (after.st_dev, after.st_ino)
            if (
                stat.S_ISLNK(after.st_mode)
                or not stat.S_ISREG(after.st_mode)
                or before_identity != after_identity
            ):
                _fail("OUTPUT_PATH_RACE", str(relative))

            digest_actual = _sha256_bytes(data)
            if digest_actual != digest_expected:
                _fail("COPY_SHA_MISMATCH", str(relative))
            bindings[str(relative)] = (
                tuple(directories),
                after_identity,
                digest_actual,
            )
        finally:
            for fd in reversed(opened):
                os.close(fd)
    return bindings


def _verify_copied_output_bindings(
    staging_root: Path,
    run_root: Path,
    copied: list[Mapping[str, Any]],
    expected: dict[str, tuple[tuple[tuple[str, tuple[int, int]], ...], tuple[int, int], str]],
) -> None:
    observed = _copied_output_bindings(staging_root, run_root, copied)
    if observed != expected:
        _fail("OUTPUT_PATH_RACE", "copied pool paths or file identities changed")


def _write_bytes_no_replace(
    destination: Path,
    data: bytes,
    *,
    conflict_code: str,
    staging_root: Path,
    run_root: Path,
) -> bool:
    """Install bytes atomically without ever replacing an existing path.

    Returns True only when an existing regular file already had identical bytes.
    The hard-link install makes the final name appear atomically and fails if a
    concurrent writer wins the name between our checks.
    """
    if (
        os.mkdir not in os.supports_dir_fd
        or os.link not in os.supports_dir_fd
        or os.link not in os.supports_follow_symlinks
        or os.unlink not in os.supports_dir_fd
    ):
        _fail("SECURE_PATH_API_UNAVAILABLE", "directory-relative no-replace install is required")
    parent_fd, name, identities = _open_output_parent(
        staging_root, run_root, destination, create=True
    )
    tmp_name: str | None = None
    tmp_fd: int | None = None
    installed_identity: tuple[int, int] | None = None
    installed = False
    try:
        existing = _existing_regular_bytes(parent_fd, name)
        if existing is not None:
            if existing != data:
                _fail(conflict_code, str(destination))
            _verify_output_parent_binding(staging_root, run_root, destination, identities)
            return True

        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            _fail("SECURE_PATH_API_UNAVAILABLE", "O_NOFOLLOW is required")
        for _attempt in range(8):
            candidate_name = f".{name}.{secrets.token_hex(12)}.tmp"
            try:
                tmp_fd = os.open(
                    candidate_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                    0o600,
                    dir_fd=parent_fd,
                )
                tmp_name = candidate_name
                break
            except FileExistsError:
                continue
        if tmp_fd is None or tmp_name is None:
            _fail("TEMP_PATH_CONFLICT", str(destination))
        view = memoryview(data)
        while view:
            written = os.write(tmp_fd, view)
            if written <= 0:
                raise OSError(errno.EIO, "short write while staging immutable output")
            view = view[written:]
        os.fsync(tmp_fd)
        staged_info = os.fstat(tmp_fd)
        installed_identity = (staged_info.st_dev, staged_info.st_ino)
        os.close(tmp_fd)
        tmp_fd = None
        _verify_output_parent_binding(staging_root, run_root, destination, identities)
        try:
            os.link(
                tmp_name,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            _fail("OUTPUT_PATH_RACE", str(destination))
        installed = True
        os.fsync(parent_fd)
        _verify_output_parent_binding(staging_root, run_root, destination, identities)
        installed_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(installed_info.st_mode)
            or (installed_info.st_dev, installed_info.st_ino) != installed_identity
        ):
            _fail("OUTPUT_PATH_RACE", str(destination))
        return False
    except BaseException:
        if installed and installed_identity is not None:
            _remove_if_owned(parent_fd, name, installed_identity)
        raise
    finally:
        if tmp_fd is not None:
            os.close(tmp_fd)
        if tmp_name is not None:
            try:
                os.unlink(tmp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def _copy_exact(
    source: Path,
    destination: Path,
    *,
    staging_root: Path,
    run_root: Path,
) -> tuple[str, bool]:
    if not source.is_file() or source.is_symlink():
        _fail("SOURCE_FILE_INVALID", str(source))
    data = source.read_bytes()
    digest = _sha256_bytes(data)
    reused = _write_bytes_no_replace(
        destination,
        data,
        conflict_code="STAGING_CONFLICT",
        staging_root=staging_root,
        run_root=run_root,
    )
    staged_data = _read_output_bytes(
        destination,
        staging_root=staging_root,
        run_root=run_root,
    )
    if _sha256_bytes(staged_data) != digest:
        _fail("COPY_SHA_MISMATCH", str(destination))
    return digest, reused


def _atomic_json(
    path: Path,
    payload: Mapping[str, Any],
    *,
    staging_root: Path,
    run_root: Path,
) -> None:
    content = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _write_bytes_no_replace(
        path,
        content,
        conflict_code="RECEIPT_CONFLICT",
        staging_root=staging_root,
        run_root=run_root,
    )

def snapshot_pool(
    *,
    source_root: Path | str,
    staging_root: Path | str,
    trade_date: str,
    pool_id: str,
    run_id: str,
    store_factory: Callable[[Path], _Store],
    owner_module_sha256: str | None = None,
    allowed_pool_ids: frozenset[str] = _ALLOWED_POOLS,
) -> dict[str, Any]:
    """Copy one exact-date pool trio into an isolated, run-scoped staging root.

    This is deliberately not a writer migration. It never writes the source root,
    never writes a canonical V4 data root, and never changes a scheduler or pointer.
    """
    _validate_identity(trade_date, pool_id, run_id, allowed_pool_ids=allowed_pool_ids)
    source = _resolved(source_root)
    staging = _resolved(staging_root)
    if source == staging or _is_relative_to(staging, source) or _is_relative_to(source, staging):
        _fail("ROOT_OVERLAP", f"source={source} staging={staging}")
    if not source.is_dir():
        _fail("SOURCE_ROOT_MISSING", str(source))

    source_store = store_factory(source)
    source_snapshot = dict(source_store.read_pool_snapshot(trade_date, pool_id))
    row_count, code_set_sha256 = _validate_pool_rows(source_snapshot, pool_id)
    required_rel = ("artifact_relative", "manifest_relative", "receipt_relative")
    for key in required_rel:
        rel = str(source_snapshot.get(key) or "")
        if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            _fail("SOURCE_SNAPSHOT_PATH_INVALID", f"{key}={rel}")

    run_root = staging / run_id
    _reject_symlink_descendants(run_root, staging)
    if run_root.exists() and run_root.is_symlink():
        _fail("SYMLINK_REJECTED", str(run_root))
    copied: list[dict[str, Any]] = []
    reused_count = 0
    for key in required_rel:
        rel = Path(str(source_snapshot[key]))
        lexical_src = source / rel
        lexical_dst = run_root / rel
        _reject_symlink_descendants(lexical_src, source)
        _reject_symlink_descendants(lexical_dst, staging)
        src = lexical_src.resolve()
        dst = lexical_dst.resolve()
        resolved_run_root = run_root.resolve()
        if not _is_relative_to(src, source) or not _is_relative_to(dst, resolved_run_root):
            _fail("PATH_ESCAPE", str(rel))
        digest, reused = _copy_exact(
            src,
            lexical_dst,
            staging_root=staging,
            run_root=run_root,
        )
        reused_count += int(reused)
        copied.append({"role": key.removesuffix("_relative"), "relative_path": str(rel), "sha256": digest, "bytes": src.stat().st_size, "reused": reused})

    copied_output_binding = _copied_output_bindings(staging, run_root, copied)
    root_probe = run_root / ".snapshot-root-binding"
    root_fd, _root_name, run_root_binding = _open_output_parent(
        staging, run_root, root_probe, create=False
    )
    os.close(root_fd)
    staged_store = store_factory(run_root)
    _verify_output_parent_binding(
        staging,
        run_root,
        root_probe,
        run_root_binding,
    )
    _verify_copied_output_bindings(
        staging,
        run_root,
        copied,
        copied_output_binding,
    )
    staged_snapshot = dict(staged_store.read_pool_snapshot(trade_date, pool_id))
    _verify_copied_output_bindings(
        staging,
        run_root,
        copied,
        copied_output_binding,
    )
    _verify_output_parent_binding(
        staging,
        run_root,
        root_probe,
        run_root_binding,
    )
    compared_fields = ("pool_sha256", "artifact_raw_sha256", "manifest_raw_sha256", "receipt_raw_sha256")
    mismatches = [field for field in compared_fields if source_snapshot.get(field) != staged_snapshot.get(field)]
    if mismatches:
        _fail("STORE_READBACK_MISMATCH", ",".join(mismatches))

    # Re-read the source after the copy and staged semantic readback.  A writer
    # that changed the source during this interval invalidates the canary even
    # when the staged bytes are internally self-consistent.
    source_after = dict(source_store.read_pool_snapshot(trade_date, pool_id))
    source_changed = [field for field in compared_fields if source_snapshot.get(field) != source_after.get(field)]
    if source_changed:
        _fail("SOURCE_CHANGED_DURING_SNAPSHOT", ",".join(source_changed))
    after_count, after_code_set_sha256 = _validate_pool_rows(source_after, pool_id)
    if after_count != row_count or after_code_set_sha256 != code_set_sha256:
        _fail("SOURCE_CHANGED_DURING_SNAPSHOT", "row_identity_changed")

    receipt = {
        "schema_version": "v4.migration.preselection_pool_snapshot_canary.v2",
        "status": "SNAPSHOT_VERIFIED",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "run_id": run_id,
        "source_root": str(source),
        "staging_run_root": str(run_root),
        "owner_store_module_sha256": owner_module_sha256,
        "owner_runtime_python": sys.executable,
        "owner_runtime_prefix": sys.prefix,
        "owner_runtime_python_version": ".".join(map(str, sys.version_info[:3])),
        "scope": "SINGLE_POOL_PARTIAL_STORE",
        "row_count": row_count,
        "unique_code_count": row_count,
        "code_set_sha256": code_set_sha256,
        "source_stability_readback": "PASS",
        "copied_files": copied,
        "source_target_bytes_equal": True,
        "store_semantics_readback": "PASS",
        "reused_file_count": reused_count,
        "writer_fenced": False,
        "writer_migrated": False,
        "cutover_eligible": False,
        "authority_promoted": False,
        "canonical_root_changed": False,
        "scheduler_changed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    _atomic_json(
        run_root / "migration_receipts" / trade_date / f"{pool_id}.json",
        receipt,
        staging_root=staging,
        run_root=run_root,
    )
    return receipt


def _load_store_factory(owner_app_root: Path | str):
    root = _resolved(owner_app_root)
    module_path = root / "infrastructure" / "preselection_pool_store.py"
    if not module_path.is_file() or module_path.is_symlink():
        _fail("OWNER_STORE_MODULE_MISSING", str(module_path))
    module_sha = hashlib.sha256(module_path.read_bytes()).hexdigest()
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module("infrastructure.preselection_pool_store")
    finally:
        if sys.path and sys.path[0] == str(root):
            sys.path.pop(0)
    loaded_path = Path(str(getattr(module, "__file__", ""))).resolve()
    if loaded_path != module_path.resolve():
        _fail("OWNER_STORE_MODULE_ORIGIN_MISMATCH", f"expected={module_path} loaded={loaded_path}")
    factory = getattr(module, "PreselectionPoolStore", None)
    if factory is None:
        _fail("OWNER_STORE_CLASS_MISSING", str(module_path))
    pool_order = getattr(module, "POOL_ORDER", None)
    if not isinstance(pool_order, (tuple, list)) or not pool_order or any(not isinstance(item, str) for item in pool_order):
        _fail("OWNER_POOL_ORDER_MISSING", str(module_path))
    return factory, module_sha, frozenset(pool_order)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify one V35 preselection pool in isolated immutable staging")
    parser.add_argument("--source-data-root", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--owner-app-root", type=Path, required=True)
    parser.add_argument("--owner-runtime-prefix", type=Path, required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--pool-id", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        expected_prefix = Path(args.owner_runtime_prefix).expanduser().resolve()
        actual_prefix = Path(sys.prefix).resolve()
        if actual_prefix != expected_prefix:
            _fail("OWNER_RUNTIME_PREFIX_MISMATCH", f"expected={expected_prefix} actual={actual_prefix}")
        factory, module_sha, allowed_pool_ids = _load_store_factory(args.owner_app_root)
        result = snapshot_pool(
            source_root=args.source_data_root,
            staging_root=args.staging_root,
            trade_date=args.trade_date,
            pool_id=args.pool_id,
            run_id=args.run_id,
            store_factory=factory,
            owner_module_sha256=module_sha,
            allowed_pool_ids=allowed_pool_ids,
        )
    except (SnapshotCanaryError, OSError, ValueError, ImportError) as error:
        print(json.dumps({"status": "REJECTED", "error": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
