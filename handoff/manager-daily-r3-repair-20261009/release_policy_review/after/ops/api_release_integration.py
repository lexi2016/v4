"""Fail-closed active-base and explicit-delta checks for API releases."""
from __future__ import annotations

from contextlib import contextmanager
import difflib
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import plistlib
import re
import secrets
import stat
import threading
import time
from typing import Any, Iterator, Mapping, Sequence


SCHEMA_VERSION = "v4.api_release_integration.v2"
DELTA_SCHEMA_VERSION = "v4.api_release_delta_receipt.v2"
DELTA_RECEIPT_NAME = "api-integration-delta-receipt.json"
DIRECTORY_SCHEMA_VERSION = "v4.api_release_directory_preservation.v1"
NEW_DIRECTORY_MODE = "0755"

# Reviewed ownership is code, not caller-supplied data or an unpinned import.
# Unknown paths require an explicit policy review before a module may ship them.
POLICY = {
    "version": "v4.api_module_ownership.v1",
    "modules": {
        "preselection": {"exact": [
            "apps/api/v35_api/preselection_router.py",
            "apps/api/v35_api/preselection_service.py", "domains/preselection_pools.py",
            "domains/preselection.py",
        ], "prefixes": []},
        "manager": {"exact": [], "prefixes": [
            "domains/manager_research/", "v4/manager_research/", "apps/api/v35_api/manager_",
        ]},
        "research_review": {"exact": [
            "apps/api/v35_api/review_router.py", "domains/daily_research_review.py",
        ], "prefixes": ["domains/research_review_generation/"]},
        "api_platform": {"exact": [], "prefixes": []},
    },
    "shared": {
        "apps/api/v35_api/app.py": ["preselection", "manager", "research_review", "api_platform"],
        "apps/api/v35_api/config.py": ["preselection", "manager", "research_review", "api_platform"],
        "apps/api/v35_api/run.py": ["preselection", "manager", "research_review", "api_platform"],
        "ops/build_release_candidate.py": ["api_platform"],
        "ops/prepare_api_only_cutover.py": ["api_platform"],
        "ops/api_release_integration.py": ["api_platform"],
        "ops/create_api_module_delta.py": ["api_platform"],
        # R3 manager dependencies: exact paths reviewed by the shared API owner.
        "infrastructure/_research_peripheral_store_parts/_namespace.py": ["manager"],
        "infrastructure/scheduling/manager_announcement_supervisor.py": ["manager"],
        "ops/render_manager_announcement_binding.py": ["manager"],
        "ops/run_manager_announcement_cycle.py": ["manager"],
        "v3_shared_data/shared_data/hk_daily_supplement.py": ["manager"],
    },
}
POLICY_SHA256 = hashlib.sha256(json.dumps(
    POLICY, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8")).hexdigest()
_RELEASE_KEYS = (
    "release_root", "app_root", "release_id", "release_manifest_path",
    "release_manifest_sha256", "application_inventory_sha256",
    "application_inventory_entry_count",
)
_BASE_KEYS = (*_RELEASE_KEYS, "api_plist_path", "api_plist_sha256")
_ENTRY_KEYS = {
    "path", "before_sha256", "after_sha256", "before_mode", "after_mode",
    "unified_diff_sha256", "unified_diff_hunk_count",
}


def _absolute_path(path: Path) -> Path:
    supplied = Path(path).expanduser()
    if ".." in supplied.parts:
        raise ValueError("API_RELEASE_PATH_NOT_CANONICAL")
    return Path(os.path.abspath(supplied))


@contextmanager
def _directory_fd(path: Path) -> Iterator[int]:
    """Open every ancestry component without following links."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("API_RELEASE_POSIX_NOFOLLOW_REQUIRED")
    path = _absolute_path(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        raise ValueError("API_RELEASE_DIRECTORY_PATH_UNSAFE") from exc
    finally:
        os.close(fd)


def _file_token(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _directory_token(path: Path) -> tuple[int, int]:
    with _directory_fd(path) as fd:
        info = os.fstat(fd)
        return info.st_dev, info.st_ino


def _read_regular_at(parent: int, name: str) -> tuple[bytes, tuple[int, ...]]:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        raise ValueError("API_RELEASE_FILE_PATH_UNSAFE") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("API_RELEASE_NOT_REGULAR_FILE")
        chunks = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        raw = b"".join(chunks)
        token = _file_token(before)
        if (_file_token(os.fstat(fd)) != token
                or _file_token(os.stat(name, dir_fd=parent, follow_symlinks=False)) != token
                or len(raw) != before.st_size):
            raise ValueError("API_RELEASE_FILE_CHANGED_DURING_READ")
        return raw, token
    finally:
        os.close(fd)


def _read_file(path: Path) -> tuple[bytes, tuple[object, ...]]:
    path = _absolute_path(path)
    with _directory_fd(path.parent) as parent:
        parent_identity = (os.fstat(parent).st_dev, os.fstat(parent).st_ino)
        raw, token = _read_regular_at(parent, path.name)
    if _directory_token(path.parent) != parent_identity:
        raise ValueError("API_RELEASE_FILE_PARENT_REPLACED")
    return raw, (parent_identity, token)


def _assert_file_snapshot(path: Path, sha256: str, token: tuple[object, ...]) -> None:
    raw, current_token = _read_file(path)
    if current_token != token or sha256_bytes(raw) != sha256:
        raise ValueError("API_RELEASE_FILE_SNAPSHOT_CHANGED")


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(label + "_JSON_DUPLICATE_KEY")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(label + "_JSON_CONSTANT_INVALID")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(label + "_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise ValueError(label + "_JSON_OBJECT_REQUIRED")
    return value


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_mode(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-7]{4}", value) is not None


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _exact_path(path: Path, *, kind: str, label: str) -> Path:
    path = _absolute_path(path)
    if path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError(label + "_PATH_SYMLINK_OR_ALIAS")
    if kind == "file" and not path.is_file():
        raise FileNotFoundError(path)
    if kind == "directory" and not path.is_dir():
        raise FileNotFoundError(path)
    info = path.lstat()
    if kind == "file" and not stat.S_ISREG(info.st_mode):
        raise ValueError(label + "_NOT_REGULAR_FILE")
    if kind == "directory" and not stat.S_ISDIR(info.st_mode):
        raise ValueError(label + "_NOT_DIRECTORY")
    if kind == "directory":
        _directory_token(path)
    else:
        with _directory_fd(path.parent):
            pass
    return path


def _normalise_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("API_RELEASE_DELTA_PATH_INVALID")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if not posix.parts or posix.is_absolute() or windows.drive or windows.root or any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError("API_RELEASE_DELTA_PATH_INVALID")
    normalized = posix.as_posix()
    if normalized != value:
        raise ValueError("API_RELEASE_DELTA_PATH_NOT_CANONICAL")
    return normalized


def _path_set(values: Sequence[str], *, label: str) -> set[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError(label + "_LIST_REQUIRED")
    normalized = [_normalise_relative(value) for value in values]
    if len(set(normalized)) != len(normalized):
        raise ValueError(label + "_DUPLICATE_PATH")
    return set(normalized)


def _safe_child(root: Path, relative: str, *, allow_missing: bool) -> Path:
    root = _exact_path(root, kind="directory", label="API_RELEASE_TREE_ROOT")
    relative = _normalise_relative(relative)
    target = root / relative
    current = root
    parts = PurePosixPath(relative).parts
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("API_RELEASE_DELTA_ANCESTOR_SYMLINK:" + relative)
    if target.is_symlink():
        raise ValueError("API_RELEASE_DELTA_TARGET_SYMLINK:" + relative)
    if target.exists():
        if target.resolve(strict=True) != target or not target.is_file():
            raise ValueError("API_RELEASE_DELTA_TARGET_NOT_REGULAR:" + relative)
    elif not allow_missing:
        raise FileNotFoundError(target)
    return target


def _entry_for_path(root: Path, relative: str) -> dict[str, object]:
    relative = _normalise_relative(relative)
    path = root / relative
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return {
            "path": relative,
            "kind": "symlink",
            "target": os.readlink(path),
            "target_exists": path.exists(),
        }
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("API_RELEASE_UNSUPPORTED_ENTRY_TYPE:" + relative)
    return {
        "path": relative,
        "kind": "file",
        "sha256": sha256_bytes(_read_file(path)[0]),
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "size": info.st_size,
    }


def inventory_tree(root: Path) -> list[dict[str, object]]:
    return _inventory_snapshot(root)["entries"]


def _inventory_snapshot(root: Path) -> dict[str, Any]:
    root = _exact_path(root, kind="directory", label="API_RELEASE_INVENTORY_ROOT")
    entries: list[dict[str, object]] = []
    physical: list[tuple[object, ...]] = []

    def walk(directory: int, prefix: str) -> None:
        directory_info = os.fstat(directory)
        names = sorted(os.listdir(directory))
        physical.append((prefix, "directory", directory_info.st_dev, directory_info.st_ino,
                         directory_info.st_mode))
        for name in names:
            relative = _normalise_relative(prefix + name)
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    opened = os.fstat(child)
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise ValueError("API_RELEASE_INVENTORY_DIRECTORY_REPLACED")
                    walk(child, relative + "/")
                finally:
                    os.close(child)
            elif stat.S_ISLNK(info.st_mode):
                target = os.readlink(name, dir_fd=directory)
                entries.append({"path": relative, "kind": "symlink", "target": target,
                                "target_exists": (root / relative).exists()})
                physical.append((relative, "symlink", *_file_token(info), target))
            elif stat.S_ISREG(info.st_mode):
                raw, token = _read_regular_at(directory, name)
                if token != _file_token(info):
                    raise ValueError("API_RELEASE_INVENTORY_FILE_REPLACED")
                entries.append({"path": relative, "kind": "file", "sha256": sha256_bytes(raw),
                                "mode": f"{stat.S_IMODE(info.st_mode):04o}", "size": len(raw)})
                physical.append((relative, "file", *token))
            else:
                raise ValueError("API_RELEASE_UNSUPPORTED_ENTRY_TYPE:" + relative)
            if _file_token(os.stat(name, dir_fd=directory, follow_symlinks=False)) != _file_token(info):
                raise ValueError("API_RELEASE_INVENTORY_ENTRY_CHANGED")
        if sorted(os.listdir(directory)) != names:
            raise ValueError("API_RELEASE_INVENTORY_DIRECTORY_CHANGED")
        after = os.fstat(directory)
        if (after.st_dev, after.st_ino, after.st_mode) != (
                directory_info.st_dev, directory_info.st_ino, directory_info.st_mode):
            raise ValueError("API_RELEASE_INVENTORY_DIRECTORY_CHANGED")

    with _directory_fd(root) as descriptor:
        root_info = os.fstat(descriptor)
        walk(descriptor, "")
    if _directory_token(root) != (root_info.st_dev, root_info.st_ino):
        raise ValueError("API_RELEASE_INVENTORY_ROOT_REPLACED")
    return {"entries": sorted(entries, key=lambda item: str(item["path"])), "physical": physical}


def _assert_inventory_snapshot(root: Path, snapshot: Mapping[str, Any]) -> None:
    if _inventory_snapshot(root) != snapshot:
        raise ValueError("API_RELEASE_APPLICATION_SNAPSHOT_CHANGED")


def inventory_digest(entries: Sequence[Mapping[str, object]]) -> str:
    raw = json.dumps(list(entries), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def _directory_entries(snapshot: Mapping[str, Any]) -> list[dict[str, str]]:
    """Keep directory identity separate from historical file-only inventories."""
    return sorted([
        {"path": row[0].rstrip("/") or ".", "mode": f"{stat.S_IMODE(row[4]):04o}"}
        for row in snapshot["physical"] if row[1] == "directory"
    ], key=lambda row: row["path"])


def _expected_directory_modes(
    base_snapshot: Mapping[str, Any], entries: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    expected = {row["path"]: row["mode"] for row in _directory_entries(base_snapshot)}
    for entry in entries:
        if entry["before_sha256"] is None:
            for parent in PurePosixPath(entry["path"]).parents:
                if parent.as_posix() != ".":
                    expected.setdefault(parent.as_posix(), NEW_DIRECTORY_MODE)
    return expected


def _directory_inventory_record(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    rows = _directory_entries(snapshot)
    return {"entry_count": len(rows), "aggregate_sha256": inventory_digest(rows)}


def _validate_directory_proof(proof: object) -> dict[str, Any]:
    if not isinstance(proof, dict) or set(proof) != {
            "schema_version", "base", "candidate", "added_paths", "new_directory_mode"}:
        raise ValueError("API_RELEASE_DIRECTORY_PROOF_FIELDS_INVALID")
    if (proof["schema_version"] != DIRECTORY_SCHEMA_VERSION
            or proof["new_directory_mode"] != NEW_DIRECTORY_MODE):
        raise ValueError("API_RELEASE_DIRECTORY_PROOF_POLICY_INVALID")
    for owner in ("base", "candidate"):
        record = proof[owner]
        if (not isinstance(record, dict) or set(record) != {"entry_count", "aggregate_sha256"}
                or type(record["entry_count"]) is not int or record["entry_count"] < 1
                or not _is_sha(record["aggregate_sha256"])):
            raise ValueError("API_RELEASE_DIRECTORY_PROOF_INVENTORY_INVALID")
    paths = proof["added_paths"]
    if not isinstance(paths, list) or paths != sorted(_path_set(paths, label="API_RELEASE_DIRECTORY_PROOF")):
        raise ValueError("API_RELEASE_DIRECTORY_PROOF_PATHS_INVALID")
    return proof


def _directory_preservation(
    base_snapshot: Mapping[str, Any], candidate_snapshot: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    base = {row["path"]: row["mode"] for row in _directory_entries(base_snapshot)}
    candidate = {row["path"]: row["mode"] for row in _directory_entries(candidate_snapshot)}
    expected = _expected_directory_modes(base_snapshot, entries)
    removed = sorted(set(expected) - set(candidate))
    if removed:
        raise ValueError("API_RELEASE_INTEGRATION_DIRECTORY_REMOVED:" + ",".join(removed[:8]))
    added_unlisted = sorted(set(candidate) - set(expected))
    if added_unlisted:
        raise ValueError("API_RELEASE_INTEGRATION_UNLISTED_DIRECTORY_ADDED:" + ",".join(added_unlisted[:8]))
    changed_modes = sorted(path for path in expected if expected[path] != candidate[path])
    if changed_modes:
        raise ValueError("API_RELEASE_INTEGRATION_DIRECTORY_MODE_MISMATCH:" + ",".join(changed_modes[:8]))
    return {
        "schema_version": DIRECTORY_SCHEMA_VERSION,
        "base": _directory_inventory_record(base_snapshot),
        "candidate": _directory_inventory_record(candidate_snapshot),
        "added_paths": sorted(set(candidate) - set(base)),
        "new_directory_mode": NEW_DIRECTORY_MODE,
    }


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    raw, _ = _read_file(_exact_path(path, kind="file", label=label))
    return _json_object(raw, label), raw


def _plist_environment(payload: Mapping[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    arguments = payload.get("ProgramArguments")
    if not isinstance(arguments, list):
        raise ValueError("API_RELEASE_ACTIVE_PLIST_ARGUMENTS_INVALID")
    for item in arguments:
        if not isinstance(item, str) or "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key in {"V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256"}:
            if key in values and values[key] != value:
                raise ValueError("API_RELEASE_ACTIVE_PLIST_IDENTITY_DUPLICATE:" + key)
            values[key] = value
    environment = payload.get("EnvironmentVariables")
    if isinstance(environment, Mapping):
        for key in ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256"):
            value = environment.get(key)
            if value is not None:
                if not isinstance(value, str) or (key in values and values[key] != value):
                    raise ValueError("API_RELEASE_ACTIVE_PLIST_IDENTITY_CONFLICT:" + key)
                values[key] = value
    required = {"V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256"}
    if required - values.keys():
        raise ValueError("API_RELEASE_ACTIVE_PLIST_IDENTITY_MISSING")
    return values


def _release_identity(
    *, release_root: Path, app_root: Path, release_id: str,
    manifest_path: Path, manifest_sha256: str,
    application_inventory_sha256: str | None = None,
) -> dict[str, Any]:
    release_root = _exact_path(release_root, kind="directory", label="API_RELEASE_ROOT")
    app_root = _exact_path(app_root, kind="directory", label="API_RELEASE_APP_ROOT")
    manifest_path = _exact_path(manifest_path, kind="file", label="API_RELEASE_MANIFEST")
    if app_root.name != "app" or app_root.parent != release_root or manifest_path != release_root / "release-manifest.json":
        raise ValueError("API_RELEASE_ROOT_BINDING_INVALID")
    if not _is_sha(manifest_sha256):
        raise ValueError("API_RELEASE_MANIFEST_SHA_INVALID")
    if application_inventory_sha256 is not None and not _is_sha(application_inventory_sha256):
        raise ValueError("API_RELEASE_MANIFEST_INVENTORY_SHA_INVALID")
    manifest_raw, manifest_token = _read_file(manifest_path)
    observed_manifest_sha = sha256_bytes(manifest_raw)
    if observed_manifest_sha != manifest_sha256:
        raise ValueError("API_RELEASE_MANIFEST_SHA_MISMATCH")
    manifest = _json_object(manifest_raw, "API_RELEASE_MANIFEST")
    if manifest.get("schema_version") != "v4.release_candidate.v1":
        raise ValueError("API_RELEASE_MANIFEST_SCHEMA_UNSUPPORTED")
    candidate = manifest.get("candidate")
    inventory = manifest.get("application_inventory")
    if not isinstance(candidate, dict) or not isinstance(inventory, dict):
        raise ValueError("API_RELEASE_MANIFEST_IDENTITY_OR_INVENTORY_MISSING")
    if (not isinstance(release_id, str) or not release_id or "/" in release_id or "\\" in release_id
            or candidate.get("release_id") != release_id or candidate.get("app_root") != str(app_root)
            or candidate.get("root") != str(release_root)):
        raise ValueError("API_RELEASE_MANIFEST_IDENTITY_MISMATCH")
    entries = inventory.get("entries")
    aggregate = inventory.get("aggregate_sha256")
    if (not isinstance(entries, list) or not _is_sha(aggregate) or inventory_digest(entries) != aggregate
            or type(inventory.get("entry_count")) is not int or inventory["entry_count"] != len(entries)):
        raise ValueError("API_RELEASE_MANIFEST_INVENTORY_DIGEST_MISMATCH")
    snapshot = _inventory_snapshot(app_root)
    actual = snapshot["entries"]
    if actual != entries:
        raise ValueError("API_RELEASE_ACTIVE_APPLICATION_INVENTORY_DRIFT")
    integration = manifest.get("api_integration")
    if isinstance(integration, dict) and integration.get("schema_version") == SCHEMA_VERSION:
        directories = _validate_directory_proof(integration.get("directory_preservation"))
        if directories["candidate"] != _directory_inventory_record(snapshot):
            raise ValueError("API_RELEASE_ACTIVE_DIRECTORY_INVENTORY_DRIFT")
    if application_inventory_sha256 is not None and aggregate != application_inventory_sha256:
        raise ValueError("API_RELEASE_MANIFEST_INVENTORY_BINDING_MISMATCH")
    _assert_file_snapshot(manifest_path, observed_manifest_sha, manifest_token)
    return {
        "release_root": str(release_root),
        "app_root": str(app_root),
        "release_id": release_id,
        "release_manifest_path": str(manifest_path),
        "release_manifest_sha256": observed_manifest_sha,
        "application_inventory_sha256": aggregate,
        "application_inventory_entry_count": len(entries),
        "manifest": manifest,
        "inventory": actual,
        "_application_snapshot": snapshot,
        "_manifest_token": manifest_token,
    }


def read_active_release(api_plist_path: Path) -> dict[str, Any]:
    api_plist_path = _exact_path(api_plist_path, kind="file", label="API_RELEASE_ACTIVE_PLIST")
    plist_raw, plist_token = _read_file(api_plist_path)
    try:
        payload = plistlib.loads(plist_raw)
    except (plistlib.InvalidFileException, ValueError) as exc:
        raise ValueError("API_RELEASE_ACTIVE_PLIST_INVALID") from exc
    if not isinstance(payload, dict) or payload.get("Label") != "com.lexi.v35.api-only":
        raise ValueError("API_RELEASE_ACTIVE_PLIST_LABEL_MISMATCH")
    values = _plist_environment(payload)
    app_root = _exact_path(Path(values["V35_APP_ROOT"]), kind="directory", label="API_RELEASE_ACTIVE_APP")
    release_root = app_root.parent
    manifest_path = Path(values["V35_RELEASE_MANIFEST_PATH"])
    manifest_expected = values["V35_RELEASE_MANIFEST_SHA256"]
    if release_root.name != values["V35_RELEASE_ID"]:
        raise ValueError("API_RELEASE_ACTIVE_ID_ROOT_MISMATCH")
    identity = _release_identity(
        release_root=release_root,
        app_root=app_root,
        release_id=values["V35_RELEASE_ID"],
        manifest_path=manifest_path,
        manifest_sha256=manifest_expected,
    )
    identity["api_plist_path"] = str(api_plist_path)
    identity["api_plist_sha256"] = sha256_bytes(plist_raw)
    identity["identity_from_plist"] = {key: values[key] for key in sorted(values)}
    identity["_plist_token"] = plist_token
    _assert_release_snapshot(identity)
    _assert_file_snapshot(api_plist_path, identity["api_plist_sha256"], plist_token)
    return identity


def _base_binding(identity: Mapping[str, Any]) -> dict[str, Any]:
    return {key: identity[key] for key in _BASE_KEYS}


def _assert_release_snapshot(identity: Mapping[str, Any]) -> None:
    _assert_inventory_snapshot(Path(identity["app_root"]), identity["_application_snapshot"])
    _assert_file_snapshot(Path(identity["release_manifest_path"]),
                          identity["release_manifest_sha256"], identity["_manifest_token"])


def _assert_active_snapshot(identity: Mapping[str, Any]) -> None:
    _assert_release_snapshot(identity)
    _assert_file_snapshot(Path(identity["api_plist_path"]), identity["api_plist_sha256"],
                          identity["_plist_token"])


def verify_recorded_base(base_record: Mapping[str, Any]) -> dict[str, Any]:
    """Verify immutable recorded base bytes without reading the active pointer.

    A rollback caller may use this while the active pointer is absent or has
    changed. Recorded pointer SHA is syntax-checked only in this function.
    """
    if not isinstance(base_record, Mapping) or set(base_record) != set(_BASE_KEYS):
        raise ValueError("API_RELEASE_INTEGRATION_BASE_RECORD_INVALID")
    for key in ("release_root", "app_root", "release_manifest_path", "api_plist_path"):
        value = base_record[key]
        if not isinstance(value, str) or not value.startswith("/") or str(_absolute_path(Path(value))) != value:
            raise ValueError("API_RELEASE_INTEGRATION_BASE_PATH_INVALID")
    if (not _is_sha(base_record["api_plist_sha256"])
            or type(base_record["application_inventory_entry_count"]) is not int
            or base_record["application_inventory_entry_count"] < 0):
        raise ValueError("API_RELEASE_INTEGRATION_BASE_RECORD_INVALID")
    identity = _release_identity(
        release_root=Path(base_record["release_root"]), app_root=Path(base_record["app_root"]),
        release_id=base_record["release_id"], manifest_path=Path(base_record["release_manifest_path"]),
        manifest_sha256=base_record["release_manifest_sha256"],
        application_inventory_sha256=base_record["application_inventory_sha256"],
    )
    identity.update({key: base_record[key] for key in ("api_plist_path", "api_plist_sha256")})
    if _base_binding(identity) != dict(base_record):
        raise ValueError("API_RELEASE_INTEGRATION_BASE_RECORD_MISMATCH")
    _assert_release_snapshot(identity)
    return identity


def module_scope(module: str, shared_paths: Sequence[str] = ()) -> dict[str, Any]:
    if not isinstance(module, str) or module not in POLICY["modules"]:
        raise ValueError("API_RELEASE_MODULE_UNKNOWN")
    if isinstance(shared_paths, (str, bytes)):
        raise ValueError("API_RELEASE_MODULE_SHARED_PATHS_INVALID")
    paths = [_normalise_relative(value) for value in shared_paths]
    if len(set(paths)) != len(paths):
        raise ValueError("API_RELEASE_MODULE_SHARED_PATH_DUPLICATE")
    if any(module not in POLICY["shared"].get(path, ()) for path in paths):
        raise ValueError("API_RELEASE_MODULE_SHARED_PATH_NOT_ALLOWED")
    return {"module": module, "shared_paths": sorted(paths), "policy_sha256": POLICY_SHA256}


def _validate_module_scope(value: object, paths: Sequence[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"module", "shared_paths", "policy_sha256"}:
        raise ValueError("API_RELEASE_MODULE_SCOPE_REQUIRED")
    if not isinstance(value["shared_paths"], list):
        raise ValueError("API_RELEASE_MODULE_SHARED_PATHS_INVALID")
    expected = module_scope(value["module"], value["shared_paths"])
    if value != expected:
        raise ValueError("API_RELEASE_MODULE_SCOPE_POLICY_MISMATCH")
    shared = sorted(path for path in paths if path in POLICY["shared"])
    if shared != expected["shared_paths"]:
        raise ValueError("API_RELEASE_MODULE_SHARED_PATHS_NOT_EXACT")
    ownership = POLICY["modules"][expected["module"]]
    for path in paths:
        if path in shared:
            continue
        if path not in ownership["exact"] and not any(path.startswith(prefix) for prefix in ownership["prefixes"]):
            raise ValueError("API_RELEASE_MODULE_PATH_NOT_OWNED:" + path)
    return expected


def _diff_proof(before: bytes, after: bytes) -> tuple[str | None, int | None]:
    if b"\x00" in before or b"\x00" in after:
        return None, None
    try:
        before_lines = before.decode("utf-8").splitlines()
        after_lines = after.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None, None
    diff_lines = list(difflib.unified_diff(before_lines, after_lines, fromfile="before", tofile="after", n=0, lineterm=""))
    diff_raw = ("\n".join(diff_lines) + ("\n" if diff_lines else "")).encode("utf-8")
    hunk_count = sum(line.startswith("@@") for line in diff_lines)
    return sha256_bytes(diff_raw), hunk_count


def _validate_delta_receipt(
    receipt: Mapping[str, Any], *, base_identity: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if receipt.get("schema_version") != DELTA_SCHEMA_VERSION:
        raise ValueError("API_RELEASE_DELTA_RECEIPT_SCHEMA_INVALID")
    if set(receipt) != {"schema_version", "base", "module_scope", "entries"}:
        raise ValueError("API_RELEASE_DELTA_RECEIPT_FIELDS_INVALID")
    if receipt.get("base") != _base_binding(base_identity):
        raise ValueError("API_RELEASE_DELTA_BASE_IDENTITY_MISMATCH")
    raw_entries = receipt.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("API_RELEASE_DELTA_ENTRIES_REQUIRED")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict) or set(raw) != _ENTRY_KEYS:
            raise ValueError("API_RELEASE_DELTA_ENTRY_INVALID")
        relative = _normalise_relative(raw.get("path"))
        if relative in seen:
            raise ValueError("API_RELEASE_DELTA_PATH_DUPLICATE:" + relative)
        seen.add(relative)
        before_sha = raw.get("before_sha256")
        after_sha = raw.get("after_sha256")
        if before_sha is not None and not _is_sha(before_sha):
            raise ValueError("API_RELEASE_DELTA_BEFORE_SHA_INVALID:" + relative)
        if not _is_sha(after_sha):
            raise ValueError("API_RELEASE_DELTA_AFTER_SHA_REQUIRED:" + relative)
        if before_sha == after_sha and raw["before_mode"] == raw["after_mode"]:
            raise ValueError("API_RELEASE_DELTA_HAS_NO_CHANGE:" + relative)
        if not _is_mode(raw["after_mode"]):
            raise ValueError("API_RELEASE_DELTA_AFTER_MODE_INVALID:" + relative)
        if (before_sha is None and raw["before_mode"] is not None
                or before_sha is not None and not _is_mode(raw["before_mode"])):
            raise ValueError("API_RELEASE_DELTA_BEFORE_MODE_INVALID:" + relative)
        proof_sha = raw.get("unified_diff_sha256")
        hunk_count = raw.get("unified_diff_hunk_count")
        if before_sha is None:
            if proof_sha is not None or hunk_count is not None:
                raise ValueError("API_RELEASE_DELTA_ADDITION_PROOF_INVALID:" + relative)
        elif (not _is_sha(proof_sha)
              or not isinstance(hunk_count, int) or isinstance(hunk_count, bool) or hunk_count < 0):
            raise ValueError("API_RELEASE_DELTA_DIFF_PROOF_REQUIRED:" + relative)
        entries.append(dict(raw, path=relative))
    if [entry["path"] for entry in entries] != sorted(entry["path"] for entry in entries):
        raise ValueError("API_RELEASE_DELTA_ENTRIES_NOT_SORTED")
    _validate_module_scope(receipt.get("module_scope"), [entry["path"] for entry in entries])
    return entries


def _verify_delta_files(
    *, base_app: Path, candidate_app: Path, entries: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    base_snapshot = _inventory_snapshot(base_app)
    candidate_snapshot = _inventory_snapshot(candidate_app)
    _directory_preservation(base_snapshot, candidate_snapshot, entries)
    base_inventory = base_snapshot["entries"]
    candidate_inventory = candidate_snapshot["entries"]
    base_by_path = {str(item["path"]): item for item in base_inventory}
    candidate_by_path = {str(item["path"]): item for item in candidate_inventory}
    delta_paths = {str(entry["path"]) for entry in entries}
    removed = sorted(set(base_by_path) - set(candidate_by_path))
    if removed:
        raise ValueError("API_RELEASE_INTEGRATION_FILE_REMOVED:" + ",".join(removed[:8]))
    added_unlisted = sorted((set(candidate_by_path) - set(base_by_path)) - delta_paths)
    if added_unlisted:
        raise ValueError("API_RELEASE_INTEGRATION_UNLISTED_FILE_ADDED:" + ",".join(added_unlisted[:8]))
    changed_unlisted = sorted(
        path for path in set(base_by_path) & set(candidate_by_path)
        if path not in delta_paths and base_by_path[path] != candidate_by_path[path]
    )
    if changed_unlisted:
        raise ValueError("API_RELEASE_INTEGRATION_UNLISTED_FILE_CHANGED:" + ",".join(changed_unlisted[:8]))

    delta_records: list[dict[str, object]] = []
    for entry in entries:
        relative = str(entry["path"])
        before_path = _safe_child(base_app, relative, allow_missing=True)
        after_path = _safe_child(candidate_app, relative, allow_missing=False)
        before_raw = _read_file(before_path)[0] if before_path.exists() else None
        after_raw = _read_file(after_path)[0]
        before_sha = sha256_bytes(before_raw) if before_raw is not None else None
        after_sha = sha256_bytes(after_raw)
        if before_sha != entry.get("before_sha256") or after_sha != entry.get("after_sha256"):
            raise ValueError("API_RELEASE_INTEGRATION_DELTA_SHA_MISMATCH:" + relative)
        before_mode = base_by_path.get(relative, {}).get("mode")
        after_mode = candidate_by_path.get(relative, {}).get("mode")
        if before_mode != entry.get("before_mode") or after_mode != entry.get("after_mode"):
            raise ValueError("API_RELEASE_INTEGRATION_DELTA_MODE_MISMATCH:" + relative)
        diff_sha = None
        hunk_count = None
        if before_sha is not None:
            diff_sha, hunk_count = _diff_proof(before_raw, after_raw)
            if (diff_sha != entry.get("unified_diff_sha256")
                    or hunk_count != entry.get("unified_diff_hunk_count")):
                raise ValueError("API_RELEASE_INTEGRATION_DELTA_DIFF_MISMATCH:" + relative)
        delta_records.append({
            "path": relative,
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "before_mode": before_mode,
            "after_mode": after_mode,
            "unified_diff_sha256": diff_sha,
            "unified_diff_hunk_count": hunk_count,
        })
    preserved = [base_by_path[path] for path in sorted(base_by_path) if path not in delta_paths]
    preserved_candidate = [candidate_by_path[path] for path in sorted(base_by_path) if path not in delta_paths]
    if preserved != preserved_candidate:
        raise ValueError("API_RELEASE_INTEGRATION_NON_DELTA_BYTES_CHANGED")
    return delta_records, preserved


@contextmanager
def _child_parent_fd(root: Path, relative: str) -> Iterator[tuple[int, str]]:
    parts = PurePosixPath(_normalise_relative(relative)).parts
    with _directory_fd(root) as root_fd:
        parent = os.dup(root_fd)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            yield parent, parts[-1]
        finally:
            os.close(parent)


def _write_candidate_bytes(root: Path, relative: str, raw: bytes, mode: int, *, exclusive: bool) -> None:
    """Publish checked bytes using one anchored destination directory fd."""
    with _child_parent_fd(root, relative) as (parent, name):
        temporary = ".api-release-" + secrets.token_hex(16)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fchmod(handle.fileno(), mode)
                os.fsync(handle.fileno())
            if exclusive:
                os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            else:
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def _copy_active_app(active: Mapping[str, Any], candidate_root: Path) -> tuple[int, int]:
    with _directory_fd(candidate_root) as parent:
        os.mkdir("app", mode=0o700, dir_fd=parent)
    app = candidate_root / "app"
    app_identity = _directory_token(app)
    # Copy only entries enumerated by the verified baseline. Reading source
    # bytes and creating destination entries both use NOFOLLOW ancestry.
    for entry in active["inventory"]:
        relative = entry["path"]
        if entry["kind"] == "symlink":
            with _child_parent_fd(app, relative) as (parent, name):
                os.symlink(entry["target"], name, dir_fd=parent)
        else:
            raw, _ = _read_file(Path(active["app_root"]) / relative)
            if sha256_bytes(raw) != entry["sha256"]:
                raise ValueError("API_RELEASE_ACTIVE_BASE_COPY_DRIFT")
            _write_candidate_bytes(app, relative, raw, int(entry["mode"], 8), exclusive=True)
    # Empty directories and directory modes are retained too, although the
    # historical manifest's application inventory lists files and links only.
    directories = [row for row in active["_application_snapshot"]["physical"] if row[1] == "directory"]
    for row in sorted(directories, key=lambda item: len(item[0]), reverse=True):
        relative = row[0].rstrip("/")
        if relative:
            with _child_parent_fd(app, relative + "/.directory-reservation"):
                pass
    return app_identity


def _restore_directory_modes(
    active: Mapping[str, Any], candidate_app: Path, entries: Sequence[Mapping[str, Any]],
) -> None:
    expected = _expected_directory_modes(active["_application_snapshot"], entries)
    # Complete writes before restoring read-only baseline ancestors. New
    # directories have a fixed mode; source directory modes are not copied.
    for relative in sorted(expected, key=len, reverse=True):
        with _directory_fd(candidate_app / relative) as descriptor:
            os.fchmod(descriptor, int(expected[relative], 8))


def build_integrated_app(
    *, active_api_plist_path: Path, source_root: Path, candidate_root: Path,
    delta_receipt_path: Path, explicit_untracked_paths: Sequence[str] = (),
    source_path_allowlist: Sequence[str] | None = None,
) -> dict[str, Any]:
    active = read_active_release(active_api_plist_path)
    source_root = _exact_path(source_root, kind="directory", label="API_RELEASE_DELTA_SOURCE_ROOT")
    candidate_root = _exact_path(candidate_root, kind="directory", label="API_RELEASE_CANDIDATE_ROOT")
    for other_root in (source_root, Path(active["release_root"])):
        if candidate_root.is_relative_to(other_root) or other_root.is_relative_to(candidate_root):
            raise ValueError("API_RELEASE_CANDIDATE_OVERLAPS_INPUT_ROOT")
    source_root_token = _directory_token(source_root)
    candidate_token = _directory_token(candidate_root)
    receipt_raw, receipt_token = _read_file(_exact_path(delta_receipt_path, kind="file", label="API_RELEASE_DELTA_RECEIPT"))
    receipt = _json_object(receipt_raw, "API_RELEASE_DELTA_RECEIPT")
    entries = _validate_delta_receipt(receipt, base_identity=active)
    delta_paths = {str(entry["path"]) for entry in entries}
    # A file can be tracked in the source Git repository while absent from the
    # active release. Conversely, source-untracked bytes can replace an active
    # file. The receipt authorizes release changes; the caller classifies Git.
    approved_untracked = _path_set(explicit_untracked_paths, label="API_RELEASE_EXPLICIT_UNTRACKED")
    if not approved_untracked <= delta_paths:
        raise ValueError("API_RELEASE_EXPLICIT_UNTRACKED_PATH_NOT_IN_DELTA")
    if source_path_allowlist is not None:
        source_allowed = _path_set(source_path_allowlist, label="API_RELEASE_SOURCE_ALLOWLIST")
        forbidden = sorted(delta_paths - source_allowed)
        if forbidden:
            raise ValueError("API_RELEASE_DELTA_SOURCE_PATH_NOT_ALLOWED:" + ",".join(forbidden[:8]))
    candidate_app = candidate_root / "app"
    if candidate_app.exists() or candidate_app.is_symlink():
        raise FileExistsError("refusing to overwrite API integration candidate app")
    candidate_app_token = _copy_active_app(active, candidate_root)
    if inventory_tree(candidate_app) != active["inventory"]:
        raise ValueError("API_RELEASE_ACTIVE_BASE_COPY_DRIFT")
    for entry in entries:
        relative = str(entry["path"])
        source = _safe_child(source_root, relative, allow_missing=False)
        source_raw, source_token = _read_file(source)
        if sha256_bytes(source_raw) != entry.get("after_sha256"):
            raise ValueError("API_RELEASE_DELTA_SOURCE_SHA_MISMATCH:" + relative)
        if f"{stat.S_IMODE(source_token[1][2]):04o}" != entry["after_mode"]:
            raise ValueError("API_RELEASE_DELTA_SOURCE_MODE_MISMATCH:" + relative)
        base_path = _safe_child(Path(active["app_root"]), relative, allow_missing=True)
        base_raw = _read_file(base_path)[0] if base_path.exists() else None
        before_sha = sha256_bytes(base_raw) if base_raw is not None else None
        if before_sha != entry.get("before_sha256"):
            raise ValueError("API_RELEASE_DELTA_BEFORE_SHA_MISMATCH:" + relative)
        before_mode = f"{stat.S_IMODE(base_path.lstat().st_mode):04o}" if base_raw is not None else None
        if before_mode != entry["before_mode"]:
            raise ValueError("API_RELEASE_DELTA_BEFORE_MODE_MISMATCH:" + relative)
        if base_raw is not None:
            diff_sha, hunk_count = _diff_proof(base_raw, source_raw)
            if (diff_sha != entry.get("unified_diff_sha256")
                    or hunk_count != entry.get("unified_diff_hunk_count")):
                raise ValueError("API_RELEASE_DELTA_SOURCE_DIFF_MISMATCH:" + relative)
        _safe_child(candidate_app, relative, allow_missing=True)
        _write_candidate_bytes(candidate_app, relative, source_raw, int(entry["after_mode"], 8), exclusive=False)
        _assert_file_snapshot(source, entry["after_sha256"], source_token)
    _restore_directory_modes(active, candidate_app, entries)
    candidate_snapshot = _inventory_snapshot(candidate_app)
    directories = _directory_preservation(active["_application_snapshot"], candidate_snapshot, entries)
    records, preserved = _verify_delta_files(
        base_app=Path(active["app_root"]), candidate_app=candidate_app, entries=entries
    )
    _assert_active_snapshot(active)
    _assert_file_snapshot(delta_receipt_path, sha256_bytes(receipt_raw), receipt_token)
    if (_directory_token(candidate_root) != candidate_token
            or _directory_token(candidate_app) != candidate_app_token
            or _directory_token(source_root) != source_root_token):
        raise ValueError("API_RELEASE_CANDIDATE_ROOT_REPLACED")
    _write_candidate_bytes(candidate_root, DELTA_RECEIPT_NAME, receipt_raw, 0o600, exclusive=True)
    _assert_inventory_snapshot(candidate_app, candidate_snapshot)
    _assert_active_snapshot(active)
    return {
        "schema_version": SCHEMA_VERSION,
        "base": _base_binding(active),
        "module_scope": receipt["module_scope"],
        "delta_receipt_source_path": str(Path(delta_receipt_path).expanduser().absolute()),
        "delta_receipt_file": DELTA_RECEIPT_NAME,
        "delta_receipt_sha256": sha256_bytes(receipt_raw),
        "delta_entries": records,
        "non_delta_active_release_bytes_preserved": True,
        "non_delta_entry_count": len(preserved),
        "non_delta_inventory_sha256": inventory_digest(preserved),
        "active_application_inventory_sha256": active["application_inventory_sha256"],
        "source_workspace_full_tree_copied": False,
        "directory_preservation": directories,
    }


def _candidate_identity(manifest: Mapping[str, Any], candidate_root: Path, manifest_sha: str) -> dict[str, Any]:
    candidate = manifest.get("candidate")
    inventory = manifest.get("application_inventory")
    if not isinstance(candidate, Mapping) or not isinstance(inventory, Mapping):
        raise ValueError("API_RELEASE_INTEGRATION_CANDIDATE_IDENTITY_MISSING")
    app_root = _exact_path(candidate_root / "app", kind="directory", label="API_RELEASE_CANDIDATE_APP")
    if candidate.get("root") != str(candidate_root) or candidate.get("app_root") != str(app_root):
        raise ValueError("API_RELEASE_INTEGRATION_CANDIDATE_ROOT_MISMATCH")
    release_id = candidate.get("release_id")
    if not isinstance(release_id, str) or not release_id or "/" in release_id or "\\" in release_id:
        raise ValueError("API_RELEASE_INTEGRATION_CANDIDATE_RELEASE_ID_INVALID")
    entries = inventory.get("entries")
    if not isinstance(entries, list):
        raise ValueError("API_RELEASE_INTEGRATION_CANDIDATE_INVENTORY_MISSING")
    snapshot = _inventory_snapshot(app_root)
    actual = snapshot["entries"]
    digest = inventory_digest(actual)
    if (actual != entries or inventory.get("aggregate_sha256") != digest
            or type(inventory.get("entry_count")) is not int or inventory["entry_count"] != len(entries)):
        raise ValueError("API_RELEASE_INTEGRATION_CANDIDATE_INVENTORY_DRIFT")
    return {
        "release_root": str(candidate_root),
        "app_root": str(app_root),
        "release_id": candidate.get("release_id"),
        "release_manifest_path": str(candidate_root / "release-manifest.json"),
        "release_manifest_sha256": manifest_sha,
        "application_inventory_sha256": digest,
        "application_inventory_entry_count": len(actual),
        "_application_snapshot": snapshot,
    }


def verify_api_release_candidate(
    *, candidate_root: Path, active_api_plist_path: Path,
    expected_manifest_sha256: str | None = None, active_pointer: str = "base",
    lock_lease: object | None = None, require_shared_lock: bool = False,
) -> dict[str, Any]:
    if require_shared_lock and lock_lease is None:
        raise ValueError("API_RELEASE_SHARED_LOCK_REQUIRED")
    if lock_lease is not None:
        assert_api_release_lock(lock_lease, active_api_plist_path)
    candidate_root = _exact_path(candidate_root, kind="directory", label="API_RELEASE_CANDIDATE_ROOT")
    candidate_root_token = _directory_token(candidate_root)
    manifest_path = _exact_path(candidate_root / "release-manifest.json", kind="file", label="API_RELEASE_CANDIDATE_MANIFEST")
    manifest_raw, manifest_token = _read_file(manifest_path)
    manifest = _json_object(manifest_raw, "API_RELEASE_CANDIDATE_MANIFEST")
    manifest_sha = sha256_bytes(manifest_raw)
    if expected_manifest_sha256 is not None and expected_manifest_sha256 != manifest_sha:
        raise ValueError("API_RELEASE_INTEGRATION_MANIFEST_SHA_MISMATCH")
    if manifest.get("schema_version") != "v4.release_candidate.v1":
        raise ValueError("API_RELEASE_INTEGRATION_LEGACY_PACKAGE_REJECTED")
    if manifest.get("activation_status") != "NOT_ACTIVATED":
        raise ValueError("API_RELEASE_INTEGRATION_CANDIDATE_ACTIVATION_INVALID")
    integration = manifest.get("api_integration")
    if not isinstance(integration, dict) or integration.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("API_RELEASE_INTEGRATION_BASE_AND_DELTA_REQUIRED")
    integration_keys = {
        "schema_version", "base", "module_scope", "delta_receipt_source_path",
        "delta_receipt_file", "delta_receipt_sha256", "delta_entries",
        "non_delta_active_release_bytes_preserved", "non_delta_entry_count",
        "non_delta_inventory_sha256", "active_application_inventory_sha256",
        "source_workspace_full_tree_copied", "directory_preservation",
    }
    if set(integration) != integration_keys:
        raise ValueError("API_RELEASE_INTEGRATION_FIELDS_INVALID")
    base = integration.get("base")
    if not isinstance(base, dict):
        raise ValueError("API_RELEASE_INTEGRATION_BASE_MISSING")
    base_identity = verify_recorded_base(base)
    current = read_active_release(active_api_plist_path)
    if current["api_plist_path"] != base["api_plist_path"]:
        raise ValueError("API_RELEASE_INTEGRATION_ACTIVE_POINTER_PATH_MISMATCH")
    candidate_identity = _candidate_identity(manifest, candidate_root, manifest_sha)
    if active_pointer == "base":
        if _base_binding(current) != base:
            raise ValueError("API_RELEASE_INTEGRATION_ACTIVE_BASE_CHANGED")
    elif active_pointer == "candidate":
        if any(current.get(key) != candidate_identity.get(key) for key in (
            "release_root", "app_root", "release_id", "release_manifest_sha256", "application_inventory_sha256",
        )):
            raise ValueError("API_RELEASE_INTEGRATION_ACTIVE_CANDIDATE_MISMATCH")
    else:
        raise ValueError("API_RELEASE_INTEGRATION_POINTER_MODE_INVALID")

    receipt_relative = integration.get("delta_receipt_file")
    if receipt_relative != DELTA_RECEIPT_NAME:
        raise ValueError("API_RELEASE_INTEGRATION_DELTA_RECEIPT_PATH_INVALID")
    receipt_path = _exact_path(candidate_root / DELTA_RECEIPT_NAME, kind="file", label="API_RELEASE_DELTA_RECEIPT_COPY")
    receipt_raw, receipt_token = _read_file(receipt_path)
    receipt = _json_object(receipt_raw, "API_RELEASE_DELTA_RECEIPT_COPY")
    if sha256_bytes(receipt_raw) != integration.get("delta_receipt_sha256"):
        raise ValueError("API_RELEASE_INTEGRATION_DELTA_RECEIPT_SHA_MISMATCH")
    entries = _validate_delta_receipt(receipt, base_identity=base_identity)
    if integration["module_scope"] != receipt["module_scope"]:
        raise ValueError("API_RELEASE_INTEGRATION_MODULE_SCOPE_MISMATCH")
    directories = _directory_preservation(
        base_identity["_application_snapshot"], candidate_identity["_application_snapshot"], entries,
    )
    if _validate_directory_proof(integration["directory_preservation"]) != directories:
        raise ValueError("API_RELEASE_INTEGRATION_DIRECTORY_PROOF_MISMATCH")
    records, preserved = _verify_delta_files(
        base_app=Path(base_identity["app_root"]),
        candidate_app=Path(candidate_identity["app_root"]),
        entries=entries,
    )
    if records != integration.get("delta_entries"):
        raise ValueError("API_RELEASE_INTEGRATION_DELTA_RECORD_MISMATCH")
    if (integration.get("non_delta_active_release_bytes_preserved") is not True
            or type(integration.get("non_delta_entry_count")) is not int
            or integration.get("non_delta_entry_count") != len(preserved)
            or integration.get("non_delta_inventory_sha256") != inventory_digest(preserved)):
        raise ValueError("API_RELEASE_INTEGRATION_NON_DELTA_PROOF_MISMATCH")
    if (integration["active_application_inventory_sha256"] != base["application_inventory_sha256"]
            or integration["source_workspace_full_tree_copied"] is not False):
        raise ValueError("API_RELEASE_INTEGRATION_COPY_POLICY_INVALID")

    # These are observed snapshots under the caller's shared publication lock,
    # not a claim that later arbitrary filesystem operations are atomic.
    _assert_inventory_snapshot(Path(candidate_identity["app_root"]), candidate_identity["_application_snapshot"])
    _assert_release_snapshot(base_identity)
    _assert_file_snapshot(receipt_path, integration["delta_receipt_sha256"], receipt_token)
    _assert_file_snapshot(manifest_path, manifest_sha, manifest_token)
    if _directory_token(candidate_root) != candidate_root_token:
        raise ValueError("API_RELEASE_CANDIDATE_ROOT_REPLACED")
    _assert_active_snapshot(current)
    if lock_lease is not None:
        assert_api_release_lock(lock_lease, active_api_plist_path)
    return {
        "status": "PASS",
        "active_pointer": active_pointer,
        "active_api_plist_sha256": current["api_plist_sha256"],
        "base": _base_binding(base_identity),
        "candidate": {key: candidate_identity[key] for key in _RELEASE_KEYS},
        "module_scope": receipt["module_scope"],
        "delta_receipt_sha256": integration["delta_receipt_sha256"],
        "delta_paths": [row["path"] for row in records],
        "non_delta_entry_count": len(preserved),
        "non_delta_inventory_sha256": inventory_digest(preserved),
        "non_delta_active_release_bytes_preserved": True,
        "directory_preservation": directories,
        "shared_lock_path": str(api_release_lock_path(active_api_plist_path)),
    }


def api_release_lock_path(active_api_plist_path: Path) -> Path:
    api_plist = _absolute_path(active_api_plist_path)
    if api_plist.name != "com.lexi.v35.api-only.plist":
        raise ValueError("API_RELEASE_LOCK_POINTER_PATH_INVALID")
    if api_plist.parent.is_symlink() or api_plist.parent.resolve(strict=True) != api_plist.parent:
        raise ValueError("API_RELEASE_LOCK_PARENT_PATH_INVALID")
    return api_plist.with_name(".com.lexi.v35.api-only.release.lock")


class _APILockLease:
    __slots__ = ("path", "fd", "identity", "parent_identity", "pid", "thread_id")


_ACTIVE_LEASES: dict[int, _APILockLease] = {}
_LEASE_GUARD = threading.Lock()


def _clear_leases_after_fork() -> None:
    global _ACTIVE_LEASES, _LEASE_GUARD
    _ACTIVE_LEASES = {}
    _LEASE_GUARD = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_clear_leases_after_fork)


@contextmanager
def shared_api_release_lock(
    active_api_plist_path: Path, *, timeout_seconds: float = 2.0,
) -> Iterator[object]:
    """One persistent POSIX lock inode shared by migrated API publishers.

    The file is never unlinked, renamed, or used as an age-based lock. Older
    publishers that do not take this exact lock must be retired by their owner.
    """
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError("API_RELEASE_LOCK_TIMEOUT_INVALID")
    try:
        import fcntl
    except ImportError as exc:
        raise ValueError("API_RELEASE_POSIX_FLOCK_REQUIRED") from exc
    lock_path = api_release_lock_path(active_api_plist_path)
    with _directory_fd(lock_path.parent) as parent:
        try:
            fd = os.open(lock_path.name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                         0o600, dir_fd=parent)
        except OSError as exc:
            raise ValueError("API_RELEASE_LOCK_PATH_UNSAFE") from exc
        acquired = False
        lease = None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("API_RELEASE_LOCK_NOT_EXCLUSIVE_REGULAR_FILE")
            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise ValueError("API_RELEASE_SHARED_LOCK_BUSY") from exc
                    time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
            lease = _APILockLease()
            lease.path = lock_path
            lease.fd = fd
            lease.identity = info.st_dev, info.st_ino
            lease.parent_identity = os.fstat(parent).st_dev, os.fstat(parent).st_ino
            lease.pid = os.getpid()
            lease.thread_id = threading.get_ident()
            with _LEASE_GUARD:
                _ACTIVE_LEASES[id(lease)] = lease
            assert_api_release_lock(lease, active_api_plist_path)
            yield lease
        finally:
            if lease is not None:
                with _LEASE_GUARD:
                    _ACTIVE_LEASES.pop(id(lease), None)
            if acquired:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def assert_api_release_lock(lease: object, active_api_plist_path: Path) -> None:
    if (type(lease) is not _APILockLease or lease.pid != os.getpid()
            or lease.thread_id != threading.get_ident()):
        raise ValueError("API_RELEASE_LOCK_LEASE_NOT_OWNED")
    with _LEASE_GUARD:
        if _ACTIVE_LEASES.get(id(lease)) is not lease:
            raise ValueError("API_RELEASE_LOCK_LEASE_NOT_ACTIVE")
    if lease.path != api_release_lock_path(active_api_plist_path):
        raise ValueError("API_RELEASE_LOCK_LEASE_PATH_MISMATCH")
    try:
        with _directory_fd(lease.path.parent) as parent:
            actual = os.stat(lease.path.name, dir_fd=parent, follow_symlinks=False)
            held = os.fstat(lease.fd)
            if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1
                    or not stat.S_ISREG(held.st_mode) or held.st_nlink != 1
                    or (actual.st_dev, actual.st_ino) != lease.identity
                    or (held.st_dev, held.st_ino) != lease.identity
                    or (os.fstat(parent).st_dev, os.fstat(parent).st_ino) != lease.parent_identity):
                raise ValueError("API_RELEASE_LOCK_LEASE_IDENTITY_CHANGED")
    except OSError as exc:
        raise ValueError("API_RELEASE_LOCK_LEASE_IDENTITY_UNAVAILABLE") from exc
