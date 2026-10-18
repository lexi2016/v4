"""Fail-closed active-base and explicit-delta checks for API releases."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import difflib
import fcntl
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import plistlib
import re
import shutil
import stat
import sys
from typing import Any, Iterator, Mapping, Sequence


SCHEMA_VERSION = "v4.api_release_integration.v1"
DELTA_SCHEMA_VERSION = "v4.api_release_delta_receipt.v1"
DELTA_RECEIPT_NAME = "api-integration-delta-receipt.json"
REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_CONTRACT_PATH = REPO_ROOT / "deployment" / "api_module_contracts.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _exact_path(path: Path, *, kind: str, label: str) -> Path:
    path = Path(os.path.abspath(Path(path).expanduser()))
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
    return path


def _normalise_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("API_RELEASE_DELTA_PATH_INVALID")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.drive or windows.root or any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError("API_RELEASE_DELTA_PATH_INVALID")
    normalized = posix.as_posix()
    if normalized != value:
        raise ValueError("API_RELEASE_DELTA_PATH_NOT_CANONICAL")
    return normalized


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


@contextmanager
def _candidate_parent_writable(candidate_app: Path, relative: str) -> Iterator[Path]:
    """Temporarily open candidate-only parent directories for a new delta file."""
    candidate_app = _exact_path(candidate_app, kind="directory", label="API_RELEASE_CANDIDATE_APP")
    relative = _normalise_relative(relative)
    target = candidate_app / relative
    try:
        target.relative_to(candidate_app)
    except ValueError as exc:
        raise ValueError("API_RELEASE_CANDIDATE_PARENT_ESCAPE") from exc
    changed: list[tuple[Path, int]] = []
    current = candidate_app
    try:
        for part in PurePosixPath(relative).parts[:-1]:
            mode = stat.S_IMODE(current.stat().st_mode)
            if not mode & stat.S_IWUSR:
                changed.append((current, mode))
                current.chmod(mode | stat.S_IWUSR)
            child = current / part
            if child.is_symlink():
                raise ValueError("API_RELEASE_CANDIDATE_PARENT_SYMLINK:" + relative)
            if not child.exists():
                child.mkdir()
            current = child
        mode = stat.S_IMODE(current.stat().st_mode)
        if not mode & stat.S_IWUSR:
            changed.append((current, mode))
            current.chmod(mode | stat.S_IWUSR)
        yield target
    finally:
        for path, mode in reversed(changed):
            path.chmod(mode)


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
        "sha256": sha256_bytes(path.read_bytes()),
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "size": info.st_size,
    }


_GENERATED_CPYTHON_314_CACHE_NAME = re.compile(r"^.+\.cpython-314\.pyc$")


def _is_generated_cpython_314_cache_file(root: Path, relative: str) -> bool:
    """Recognize only regular, direct children of a __pycache__ directory."""
    path = root / relative
    parts = PurePosixPath(relative).parts
    if len(parts) < 2 or parts[-2] != "__pycache__" or not _GENERATED_CPYTHON_314_CACHE_NAME.fullmatch(parts[-1]):
        return False
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def _inventory_tree_with_generated_cache(root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    root = _exact_path(root, kind="directory", label="API_RELEASE_INVENTORY_ROOT")
    paths: list[str] = []
    excluded_cache_paths: list[str] = []
    for directory, directories, filenames in os.walk(root, followlinks=False):
        directories.sort()
        filenames.sort()
        safe_directories: list[str] = []
        for name in directories:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                paths.append(relative)
            else:
                safe_directories.append(name)
        directories[:] = safe_directories
        for name in filenames:
            relative = (Path(directory) / name).relative_to(root).as_posix()
            if _is_generated_cpython_314_cache_file(root, relative):
                excluded_cache_paths.append(relative)
            else:
                paths.append(relative)
    entries = [_entry_for_path(root, relative) for relative in sorted(paths)]
    excluded = []
    for relative in sorted(excluded_cache_paths):
        path = root / relative
        info = path.lstat()
        excluded.append({
            "path": relative,
            "kind": "generated_python_bytecode_cache",
            "sha256": sha256_bytes(path.read_bytes()),
            "mode": f"{stat.S_IMODE(info.st_mode):04o}",
            "size": info.st_size,
        })
    return entries, excluded


def inventory_tree(root: Path) -> list[dict[str, object]]:
    entries, _excluded = _inventory_tree_with_generated_cache(root)
    return entries


def inventory_digest(entries: Sequence[Mapping[str, object]]) -> str:
    raw = json.dumps(list(entries), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    raw = _exact_path(path, kind="file", label=label).read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(label + "_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise ValueError(label + "_JSON_OBJECT_REQUIRED")
    return value, raw


def module_role_contract() -> dict[str, Any]:
    value, _ = _read_json(MODULE_CONTRACT_PATH, "API_MODULE_CONTRACT")
    if value.get("schema_version") != "v4.api_module_contracts.v1":
        raise ValueError("API_MODULE_CONTRACT_SCHEMA_INVALID")
    roles = value.get("roles")
    if not isinstance(roles, dict) or not {"gateway", "stage", "manager"} <= roles.keys():
        raise ValueError("API_MODULE_CONTRACT_ROLES_INVALID")
    return value


def _module_role(value: object) -> str:
    if value not in {"gateway", "stage", "manager"}:
        raise ValueError("API_RELEASE_MODULE_ROLE_INVALID")
    return str(value)


def _assert_role_delta_paths(paths: Sequence[str], *, role: str, bootstrap: bool) -> None:
    contract = module_role_contract()
    patterns = contract.get("bootstrap_delta_allowlist") if bootstrap else contract["roles"][role].get("delta_allowlist")
    if not isinstance(patterns, list) or not patterns:
        raise ValueError("API_RELEASE_MODULE_DELTA_ALLOWLIST_MISSING")
    rejected = [path for path in paths
                if not any(isinstance(pattern, str) and fnmatch.fnmatchcase(path, pattern)
                           for pattern in patterns)]
    if rejected:
        raise ValueError("API_RELEASE_MODULE_DELTA_PATH_REJECTED:" + ",".join(rejected[:8]))


def _module_manifest_identity(app_root: Path, candidate: Mapping[str, Any]) -> tuple[str, str | None]:
    role = str(candidate.get("module_role") or "gateway")
    _module_role(role)
    contract_sha = candidate.get("module_contract_sha256")
    if contract_sha is not None:
        if not isinstance(contract_sha, str) or len(contract_sha) != 64:
            raise ValueError("API_RELEASE_MODULE_CONTRACT_SHA_INVALID")
        contract_path = _safe_child(app_root, "deployment/api_module_contracts.json", allow_missing=False)
        if sha256_bytes(contract_path.read_bytes()) != contract_sha:
            raise ValueError("API_RELEASE_MODULE_CONTRACT_SHA_MISMATCH")
    elif role != "gateway":
        raise ValueError("API_RELEASE_MODULE_CONTRACT_SHA_REQUIRED")
    return role, contract_sha


def _plist_environment(payload: Mapping[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    arguments = payload.get("ProgramArguments")
    if not isinstance(arguments, list):
        raise ValueError("API_RELEASE_ACTIVE_PLIST_ARGUMENTS_INVALID")
    for item in arguments:
        if not isinstance(item, str) or "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key in {"V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256", "V35_API_ROLE", "V35_API_PORT"}:
            if key in values and values[key] != value:
                raise ValueError("API_RELEASE_ACTIVE_PLIST_IDENTITY_DUPLICATE:" + key)
            values[key] = value
    environment = payload.get("EnvironmentVariables")
    if isinstance(environment, Mapping):
        for key in ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256", "V35_API_ROLE", "V35_API_PORT"):
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
    manifest_raw = manifest_path.read_bytes()
    observed_manifest_sha = sha256_bytes(manifest_raw)
    if observed_manifest_sha != manifest_sha256:
        raise ValueError("API_RELEASE_MANIFEST_SHA_MISMATCH")
    try:
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("API_RELEASE_MANIFEST_JSON_INVALID") from exc
    if not isinstance(manifest, dict):
        raise ValueError("API_RELEASE_MANIFEST_OBJECT_REQUIRED")
    if manifest.get("schema_version") != "v4.release_candidate.v1":
        raise ValueError("API_RELEASE_MANIFEST_SCHEMA_UNSUPPORTED")
    candidate = manifest.get("candidate")
    inventory = manifest.get("application_inventory")
    if not isinstance(candidate, dict) or not isinstance(inventory, dict):
        raise ValueError("API_RELEASE_MANIFEST_IDENTITY_OR_INVENTORY_MISSING")
    if candidate.get("release_id") != release_id or candidate.get("app_root") != str(app_root):
        raise ValueError("API_RELEASE_MANIFEST_IDENTITY_MISMATCH")
    entries = inventory.get("entries")
    aggregate = inventory.get("aggregate_sha256")
    if not isinstance(entries, list) or inventory_digest(entries) != aggregate:
        raise ValueError("API_RELEASE_MANIFEST_INVENTORY_DIGEST_MISMATCH")
    actual, excluded_cache = _inventory_tree_with_generated_cache(app_root)
    if actual != entries:
        raise ValueError("API_RELEASE_ACTIVE_APPLICATION_INVENTORY_DRIFT")
    if application_inventory_sha256 is not None and aggregate != application_inventory_sha256:
        raise ValueError("API_RELEASE_MANIFEST_INVENTORY_BINDING_MISMATCH")
    module_role, module_contract_sha = _module_manifest_identity(app_root, candidate)
    return {
        "release_root": str(release_root),
        "app_root": str(app_root),
        "release_id": release_id,
        "release_manifest_path": str(manifest_path),
        "release_manifest_sha256": observed_manifest_sha,
        "application_inventory_sha256": aggregate,
        "application_inventory_entry_count": len(entries),
        "generated_bytecode_cache_exclusions": excluded_cache,
        "generated_bytecode_cache_exclusion_sha256": inventory_digest(excluded_cache),
        "module_role": module_role,
        "module_contract_sha256": module_contract_sha,
        "manifest": manifest,
        "inventory": actual,
    }


def read_active_release(api_plist_path: Path, *, role: str = "gateway") -> dict[str, Any]:
    role = _module_role(role)
    role_config = module_role_contract()["roles"][role]
    api_plist_path = _exact_path(api_plist_path, kind="file", label="API_RELEASE_ACTIVE_PLIST")
    try:
        payload = plistlib.loads(api_plist_path.read_bytes())
    except (plistlib.InvalidFileException, ValueError) as exc:
        raise ValueError("API_RELEASE_ACTIVE_PLIST_INVALID") from exc
    if not isinstance(payload, dict) or api_plist_path.name != role_config["plist_name"]:
        raise ValueError("API_RELEASE_ACTIVE_PLIST_ROLE_PATH_MISMATCH")
    if payload.get("Label") != role_config["label"]:
        raise ValueError("API_RELEASE_ACTIVE_PLIST_LABEL_MISMATCH")
    values = _plist_environment(payload)
    declared_role = values.get("V35_API_ROLE")
    if role != "gateway" and declared_role != role:
        raise ValueError("API_RELEASE_ACTIVE_PLIST_ROLE_MISMATCH")
    if declared_role is not None and declared_role != role:
        raise ValueError("API_RELEASE_ACTIVE_PLIST_ROLE_MISMATCH")
    raw_port = values.get("V35_API_PORT")
    if role != "gateway" and raw_port != str(role_config["port"]):
        raise ValueError("API_RELEASE_ACTIVE_PLIST_PORT_MISMATCH")
    if raw_port is not None and raw_port != str(role_config["port"]):
        raise ValueError("API_RELEASE_ACTIVE_PLIST_PORT_MISMATCH")
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
    if identity.get("module_role") != role:
        raise ValueError("API_RELEASE_ACTIVE_MANIFEST_ROLE_MISMATCH")
    identity["api_plist_path"] = str(api_plist_path)
    identity["api_plist_sha256"] = sha256_bytes(api_plist_path.read_bytes())
    identity["identity_from_plist"] = {key: values[key] for key in sorted(values)}
    return identity


def _base_binding(identity: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: identity[key]
        for key in (
            "release_root", "app_root", "release_id", "release_manifest_path",
            "release_manifest_sha256", "application_inventory_sha256",
            "application_inventory_entry_count",
        )
    }


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
    if receipt.get("base") != _base_binding(base_identity):
        raise ValueError("API_RELEASE_DELTA_BASE_IDENTITY_MISMATCH")
    raw_entries = receipt.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("API_RELEASE_DELTA_ENTRIES_REQUIRED")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise ValueError("API_RELEASE_DELTA_ENTRY_INVALID")
        relative = _normalise_relative(raw.get("path"))
        if relative in seen:
            raise ValueError("API_RELEASE_DELTA_PATH_DUPLICATE:" + relative)
        seen.add(relative)
        before_sha = raw.get("before_sha256")
        after_sha = raw.get("after_sha256")
        if before_sha is not None and (not isinstance(before_sha, str) or len(before_sha) != 64):
            raise ValueError("API_RELEASE_DELTA_BEFORE_SHA_INVALID:" + relative)
        if not isinstance(after_sha, str) or len(after_sha) != 64:
            raise ValueError("API_RELEASE_DELTA_AFTER_SHA_REQUIRED:" + relative)
        if before_sha == after_sha:
            raise ValueError("API_RELEASE_DELTA_HAS_NO_CHANGE:" + relative)
        proof_sha = raw.get("unified_diff_sha256")
        hunk_count = raw.get("unified_diff_hunk_count")
        if before_sha is None:
            if proof_sha is not None or hunk_count is not None:
                raise ValueError("API_RELEASE_DELTA_ADDITION_PROOF_INVALID:" + relative)
        elif (not isinstance(proof_sha, str) or len(proof_sha) != 64
              or not isinstance(hunk_count, int) or isinstance(hunk_count, bool) or hunk_count < 0):
            raise ValueError("API_RELEASE_DELTA_DIFF_PROOF_REQUIRED:" + relative)
        entries.append(dict(raw, path=relative))
    if [entry["path"] for entry in entries] != sorted(entry["path"] for entry in entries):
        raise ValueError("API_RELEASE_DELTA_ENTRIES_NOT_SORTED")
    return entries


def _verify_delta_files(
    *, base_app: Path, candidate_app: Path, entries: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    base_inventory = inventory_tree(base_app)
    candidate_inventory = inventory_tree(candidate_app)
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
        before_sha = sha256_bytes(before_path.read_bytes()) if before_path.exists() else None
        after_sha = sha256_bytes(after_path.read_bytes())
        if before_sha != entry.get("before_sha256") or after_sha != entry.get("after_sha256"):
            raise ValueError("API_RELEASE_INTEGRATION_DELTA_SHA_MISMATCH:" + relative)
        diff_sha = None
        hunk_count = None
        if before_sha is not None:
            diff_sha, hunk_count = _diff_proof(before_path.read_bytes(), after_path.read_bytes())
            if (diff_sha != entry.get("unified_diff_sha256")
                    or hunk_count != entry.get("unified_diff_hunk_count")):
                raise ValueError("API_RELEASE_INTEGRATION_DELTA_DIFF_MISMATCH:" + relative)
        delta_records.append({
            "path": relative,
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "unified_diff_sha256": diff_sha,
            "unified_diff_hunk_count": hunk_count,
        })
    preserved = [base_by_path[path] for path in sorted(base_by_path) if path not in delta_paths]
    preserved_candidate = [candidate_by_path[path] for path in sorted(base_by_path) if path not in delta_paths]
    if preserved != preserved_candidate:
        raise ValueError("API_RELEASE_INTEGRATION_NON_DELTA_BYTES_CHANGED")
    return delta_records, preserved


def build_integrated_app(
    *, active_api_plist_path: Path, source_root: Path, candidate_root: Path,
    delta_receipt_path: Path, explicit_untracked_paths: Sequence[str] = (),
    role: str = "gateway", base_role: str | None = None,
    bootstrap_transition: bool = False,
) -> dict[str, Any]:
    role = _module_role(role)
    base_role = _module_role(base_role or role)
    active = read_active_release(active_api_plist_path, role=base_role)
    source_root = _exact_path(source_root, kind="directory", label="API_RELEASE_DELTA_SOURCE_ROOT")
    candidate_root = _exact_path(candidate_root, kind="directory", label="API_RELEASE_CANDIDATE_ROOT")
    receipt, receipt_raw = _read_json(delta_receipt_path, "API_RELEASE_DELTA_RECEIPT")
    entries = _validate_delta_receipt(receipt, base_identity=active)
    if role != "gateway" or bootstrap_transition:
        bootstrap = bootstrap_transition or (role != base_role and base_role == "gateway")
        if base_role not in {role, "gateway"}:
            raise ValueError("API_RELEASE_CROSS_ROLE_BASE_REJECTED")
        if receipt.get("target_role") != role or receipt.get("base_role") != base_role:
            raise ValueError("API_RELEASE_DELTA_ROLE_BINDING_MISMATCH")
        _assert_role_delta_paths(
            [str(entry["path"]) for entry in entries], role=role, bootstrap=bootstrap
        )
    added = {str(entry["path"]) for entry in entries if entry.get("before_sha256") is None}
    if added != set(explicit_untracked_paths):
        raise ValueError("API_RELEASE_DELTA_ADDED_PATHS_REQUIRE_EXACT_UNTRACKED_APPROVAL")
    candidate_app = candidate_root / "app"
    if candidate_app.exists() or candidate_app.is_symlink():
        raise FileExistsError("refusing to overwrite API integration candidate app")
    shutil.copytree(active["app_root"], candidate_app, symlinks=True)
    if inventory_tree(candidate_app) != active["inventory"]:
        raise ValueError("API_RELEASE_ACTIVE_BASE_COPY_DRIFT")
    for entry in entries:
        relative = str(entry["path"])
        source = _safe_child(source_root, relative, allow_missing=False)
        source_raw = source.read_bytes()
        if sha256_bytes(source_raw) != entry.get("after_sha256"):
            raise ValueError("API_RELEASE_DELTA_SOURCE_SHA_MISMATCH:" + relative)
        base_path = _safe_child(Path(active["app_root"]), relative, allow_missing=True)
        base_raw = base_path.read_bytes() if base_path.exists() else None
        before_sha = sha256_bytes(base_raw) if base_raw is not None else None
        if before_sha != entry.get("before_sha256"):
            raise ValueError("API_RELEASE_DELTA_BEFORE_SHA_MISMATCH:" + relative)
        if base_raw is not None:
            diff_sha, hunk_count = _diff_proof(base_raw, source_raw)
            if (diff_sha != entry.get("unified_diff_sha256")
                    or hunk_count != entry.get("unified_diff_hunk_count")):
                raise ValueError("API_RELEASE_DELTA_SOURCE_DIFF_MISMATCH:" + relative)
        target = _safe_child(candidate_app, relative, allow_missing=True)
        if target.exists():
            # Active releases are immutable snapshots.  The integration
            # target is a private candidate copy, so grant owner write only
            # while replacing it; copy2 then restores the declared source mode.
            target.chmod(stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)
            shutil.copy2(source, target, follow_symlinks=False)
        else:
            with _candidate_parent_writable(candidate_app, relative) as writable_target:
                shutil.copy2(source, writable_target, follow_symlinks=False)
    records, preserved = _verify_delta_files(
        base_app=Path(active["app_root"]), candidate_app=candidate_app, entries=entries
    )
    receipt_copy = candidate_root / DELTA_RECEIPT_NAME
    with receipt_copy.open("xb") as handle:
        handle.write(receipt_raw)
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "schema_version": SCHEMA_VERSION,
        "base": _base_binding(active),
        "target_role": role,
        "base_role": base_role,
        "bootstrap_transition": bootstrap_transition or (role != base_role and base_role == "gateway"),
        "delta_receipt_source_path": str(Path(delta_receipt_path).expanduser().absolute()),
        "delta_receipt_file": DELTA_RECEIPT_NAME,
        "delta_receipt_sha256": sha256_bytes(receipt_raw),
        "delta_entries": records,
        "non_delta_active_release_bytes_preserved": True,
        "non_delta_entry_count": len(preserved),
        "non_delta_inventory_sha256": inventory_digest(preserved),
        "active_application_inventory_sha256": active["application_inventory_sha256"],
        "source_workspace_full_tree_copied": False,
    }


def _candidate_identity(manifest: Mapping[str, Any], candidate_root: Path, manifest_sha: str) -> dict[str, Any]:
    candidate = manifest.get("candidate")
    inventory = manifest.get("application_inventory")
    if not isinstance(candidate, Mapping) or not isinstance(inventory, Mapping):
        raise ValueError("API_RELEASE_INTEGRATION_CANDIDATE_IDENTITY_MISSING")
    app_root = _exact_path(candidate_root / "app", kind="directory", label="API_RELEASE_CANDIDATE_APP")
    if candidate.get("root") != str(candidate_root) or candidate.get("app_root") != str(app_root):
        raise ValueError("API_RELEASE_INTEGRATION_CANDIDATE_ROOT_MISMATCH")
    entries = inventory.get("entries")
    if not isinstance(entries, list):
        raise ValueError("API_RELEASE_INTEGRATION_CANDIDATE_INVENTORY_MISSING")
    actual = inventory_tree(app_root)
    digest = inventory_digest(actual)
    if actual != entries or inventory.get("aggregate_sha256") != digest:
        raise ValueError("API_RELEASE_INTEGRATION_CANDIDATE_INVENTORY_DRIFT")
    module_role, module_contract_sha = _module_manifest_identity(app_root, candidate)
    return {
        "release_root": str(candidate_root),
        "app_root": str(app_root),
        "release_id": candidate.get("release_id"),
        "release_manifest_path": str(candidate_root / "release-manifest.json"),
        "release_manifest_sha256": manifest_sha,
        "application_inventory_sha256": digest,
        "application_inventory_entry_count": len(actual),
        "module_role": module_role,
        "module_contract_sha256": module_contract_sha,
    }


def verify_api_release_candidate(
    *, candidate_root: Path, active_api_plist_path: Path,
    expected_manifest_sha256: str | None = None, active_pointer: str = "base",
    lock_lease: object | None = None, require_shared_lock: bool = False,
    role: str | None = None, base_role: str | None = None,
    lock_plist_path: Path | None = None,
) -> dict[str, Any]:
    candidate_root = _exact_path(candidate_root, kind="directory", label="API_RELEASE_CANDIDATE_ROOT")
    manifest_path = _exact_path(candidate_root / "release-manifest.json", kind="file", label="API_RELEASE_CANDIDATE_MANIFEST")
    manifest, manifest_raw = _read_json(manifest_path, "API_RELEASE_CANDIDATE_MANIFEST")
    manifest_sha = sha256_bytes(manifest_raw)
    if expected_manifest_sha256 is not None and expected_manifest_sha256 != manifest_sha:
        raise ValueError("API_RELEASE_INTEGRATION_MANIFEST_SHA_MISMATCH")
    if manifest.get("schema_version") != "v4.release_candidate.v1":
        raise ValueError("API_RELEASE_INTEGRATION_LEGACY_PACKAGE_REJECTED")
    integration = manifest.get("api_integration")
    if not isinstance(integration, dict) or integration.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("API_RELEASE_INTEGRATION_BASE_AND_DELTA_REQUIRED")
    candidate_record = manifest.get("candidate")
    inferred_role = (integration.get("target_role")
                     or (candidate_record.get("module_role") if isinstance(candidate_record, Mapping) else None)
                     or "gateway")
    inferred_base_role = integration.get("base_role") or inferred_role
    role = _module_role(role or inferred_role)
    base_role = _module_role(base_role or inferred_base_role)
    if inferred_role != role or inferred_base_role != base_role:
        raise ValueError("API_RELEASE_INTEGRATION_ROLE_BINDING_MISMATCH")
    if isinstance(candidate_record, Mapping) and str(candidate_record.get("module_role") or "gateway") != role:
        raise ValueError("API_RELEASE_CANDIDATE_ROLE_MISMATCH")
    base = integration.get("base")
    if not isinstance(base, dict):
        raise ValueError("API_RELEASE_INTEGRATION_BASE_MISSING")
    base_identity = _release_identity(
        release_root=Path(str(base.get("release_root", ""))),
        app_root=Path(str(base.get("app_root", ""))),
        release_id=str(base.get("release_id", "")),
        manifest_path=Path(str(base.get("release_manifest_path", ""))),
        manifest_sha256=str(base.get("release_manifest_sha256", "")),
        application_inventory_sha256=str(base.get("application_inventory_sha256", "")),
    )
    if _base_binding(base_identity) != base:
        raise ValueError("API_RELEASE_INTEGRATION_BASE_RECORD_MISMATCH")
    if base_identity.get("module_role") != base_role:
        raise ValueError("API_RELEASE_INTEGRATION_BASE_ROLE_MISMATCH")
    pointer_role = role if active_pointer == "candidate" else base_role
    current = read_active_release(active_api_plist_path, role=pointer_role)
    candidate_identity = _candidate_identity(manifest, candidate_root, manifest_sha)
    if candidate_identity.get("module_role") != role:
        raise ValueError("API_RELEASE_CANDIDATE_ROLE_MISMATCH")
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
    if require_shared_lock and lock_lease is None:
        raise ValueError("API_RELEASE_SHARED_LOCK_REQUIRED")
    lock_role = role if active_pointer == "candidate" or lock_plist_path is not None else base_role
    lock_path_source = lock_plist_path or active_api_plist_path
    if lock_lease is not None:
        assert_api_release_lock(lock_lease, lock_path_source, role=lock_role)

    receipt_relative = integration.get("delta_receipt_file")
    if receipt_relative != DELTA_RECEIPT_NAME:
        raise ValueError("API_RELEASE_INTEGRATION_DELTA_RECEIPT_PATH_INVALID")
    receipt_path = _exact_path(candidate_root / DELTA_RECEIPT_NAME, kind="file", label="API_RELEASE_DELTA_RECEIPT_COPY")
    receipt, receipt_raw = _read_json(receipt_path, "API_RELEASE_DELTA_RECEIPT_COPY")
    if sha256_bytes(receipt_raw) != integration.get("delta_receipt_sha256"):
        raise ValueError("API_RELEASE_INTEGRATION_DELTA_RECEIPT_SHA_MISMATCH")
    entries = _validate_delta_receipt(receipt, base_identity=base_identity)
    bootstrap = integration.get("bootstrap_transition", False)
    if not isinstance(bootstrap, bool):
        raise ValueError("API_RELEASE_INTEGRATION_BOOTSTRAP_FLAG_INVALID")
    if bootstrap and base_role != "gateway":
        raise ValueError("API_RELEASE_INTEGRATION_BOOTSTRAP_BASE_ROLE_INVALID")
    if role != "gateway" or bootstrap:
        if base_role not in {role, "gateway"}:
            raise ValueError("API_RELEASE_CROSS_ROLE_BASE_REJECTED")
        _assert_role_delta_paths(
            [str(entry["path"]) for entry in entries], role=role, bootstrap=bootstrap
        )
    records, preserved = _verify_delta_files(
        base_app=Path(base_identity["app_root"]),
        candidate_app=Path(candidate_identity["app_root"]),
        entries=entries,
    )
    if records != integration.get("delta_entries"):
        raise ValueError("API_RELEASE_INTEGRATION_DELTA_RECORD_MISMATCH")
    if (integration.get("non_delta_active_release_bytes_preserved") is not True
            or integration.get("non_delta_entry_count") != len(preserved)
            or integration.get("non_delta_inventory_sha256") != inventory_digest(preserved)):
        raise ValueError("API_RELEASE_INTEGRATION_NON_DELTA_PROOF_MISMATCH")
    return {
        "status": "PASS",
        "active_pointer": active_pointer,
        "active_api_plist_sha256": current["api_plist_sha256"],
        "base": _base_binding(base_identity),
        "candidate": candidate_identity,
        "delta_receipt_sha256": integration["delta_receipt_sha256"],
        "delta_paths": [row["path"] for row in records],
        "non_delta_entry_count": len(preserved),
        "non_delta_inventory_sha256": inventory_digest(preserved),
        "non_delta_active_release_bytes_preserved": True,
        "shared_lock_path": str(api_release_lock_path(lock_path_source, role=lock_role)),
    }


def api_release_lock_path(active_api_plist_path: Path, *, role: str = "gateway") -> Path:
    role = _module_role(role)
    role_config = module_role_contract()["roles"][role]
    api_plist = Path(os.path.abspath(Path(active_api_plist_path).expanduser()))
    if api_plist.name != role_config["plist_name"]:
        raise ValueError("API_RELEASE_LOCK_POINTER_PATH_INVALID")
    if api_plist.parent.is_symlink() or api_plist.parent.resolve(strict=True) != api_plist.parent:
        raise ValueError("API_RELEASE_LOCK_PARENT_PATH_INVALID")
    return api_plist.with_name(str(role_config["lock_name"]))


@contextmanager
def shared_api_release_lock(
    active_api_plist_path: Path, *, timeout_seconds: float = 2.0, role: str = "gateway",
) -> Iterator[object]:
    from infrastructure.interprocess_lock import owned_interprocess_lock

    lock_path = api_release_lock_path(active_api_plist_path, role=role)
    with owned_interprocess_lock(
        lock_path,
        timeout_seconds=timeout_seconds,
        timeout_message="API_RELEASE_SHARED_LOCK_BUSY",
    ) as lease:
        yield lease


def assert_api_release_lock(lease: object, active_api_plist_path: Path, *, role: str = "gateway") -> None:
    from infrastructure.interprocess_lock import assert_owned_interprocess_lock

    assert_owned_interprocess_lock(lease, api_release_lock_path(active_api_plist_path, role=role))


ANNOUNCEMENT_SUBMIT_LOCK_KEY = "announcement_flash_submit"
ANNOUNCEMENT_CUTOVER_GUARD_SCHEMA = "v4.api_release_announcement_cutover_guard.v1"
ANNOUNCEMENT_CUTOVER_FROZEN_ORPHAN = {
    "source_job_id": "07bfabf09f144360ab8869214aeecea8",
    "source_input_sha256": "8b7e3d6a2c7feda69859bb2574053fcb2a15e80959c1e8f2012c832f0913987f",
    "target_date": "20261016",
    "idempotency_key": "53bb028986b0ed9016fb3e7e56909edddc97e4d189eca40b53ece08dee952254",
    "payload_sha256": "a80cdf0063c99046565e8ca37ce432c69a3c2e04b48087e3aeab4963ea74c3bd",
    "model_id": "qwen3_8_flash_next",
}


def _normalise_cutover_orphan_binding(
    source_job_id: str | None, idempotency_key: str | None, payload_sha256: str | None,
) -> dict[str, str] | None:
    supplied = (source_job_id, idempotency_key, payload_sha256)
    if all(value is None for value in supplied):
        return None
    expected = ANNOUNCEMENT_CUTOVER_FROZEN_ORPHAN
    if (source_job_id != expected["source_job_id"]
            or idempotency_key != expected["idempotency_key"]
            or payload_sha256 != expected["payload_sha256"]):
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_BINDING_INVALID")
    return dict(expected)


@contextmanager
def _hold_existing_announcement_model_lock(queue_root: Path, model_id: str) -> Iterator[None]:
    """Hold an already-existing queue model lock without creating or changing files."""
    queue_root = _exact_path(queue_root, kind="directory", label="ANNOUNCEMENT_QUEUE_ROOT")
    lock_root = queue_root / "locks"
    if lock_root.is_symlink() or not lock_root.is_dir():
        raise ValueError("API_RELEASE_ANNOUNCEMENT_MODEL_LOCK_MISSING")
    lock_path = lock_root / ("model-" + sha256_bytes(model_id.encode("utf-8")) + ".lock")
    if lock_path.is_symlink():
        raise ValueError("API_RELEASE_ANNOUNCEMENT_MODEL_LOCK_INVALID")
    try:
        fd = os.open(lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError as exc:
        raise ValueError("API_RELEASE_ANNOUNCEMENT_MODEL_LOCK_MISSING") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("API_RELEASE_ANNOUNCEMENT_MODEL_LOCK_INVALID")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("API_RELEASE_ANNOUNCEMENT_MODEL_LOCK_BUSY") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _validate_cutover_orphan(
    io: Any, queue_root: Path, key: str, item: Mapping[str, Any], binding: Mapping[str, str],
) -> None:
    if (key != binding["idempotency_key"]
            or item.get("idempotency_key") != binding["idempotency_key"]
            or item.get("queue_id") != "v4-manager-flash-incremental"
            or item.get("status") != "RUNNING"
            or type(item.get("attempt_count")) is not int
            or item.get("attempt_count") != 1
            or item.get("model_id") != binding["model_id"]
            or item.get("payload_sha256") != binding["payload_sha256"]
            or item.get("input_path") != f"jobs/{key}/input.json"
            or item.get("validated_path") is not None
            or item.get("validated_sha256") is not None):
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_BINDING_MISMATCH")
    owner_fields = ("owner", "owner_pid", "execution_ref", "started_at", "lease_owner", "lease_pid")
    if any(item.get(field) not in (None, "") for field in owner_fields):
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_OWNER_PRESENT")
    attempts = item.get("attempts")
    if (not isinstance(attempts, list) or len(attempts) != 1
            or not isinstance(attempts[0], Mapping)
            or attempts[0].get("number") != 1
            or attempts[0].get("status") != "RUNNING"):
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_ATTEMPT_INVALID")
    attempt_result_fields = ("raw_path", "raw_sha256", "raw_length_bytes", "validated_path", "validated_sha256")
    if any(attempts[0].get(field) is not None for field in attempt_result_fields):
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_RESULT_PRESENT")
    identity = item.get("identity")
    if not isinstance(identity, Mapping):
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_IDENTITY_INVALID")
    queue_input = io.read_bytes("announcement_flash/queue/" + item["input_path"], max_bytes=64 * 1024 * 1024)
    if sha256_bytes(queue_input) != binding["payload_sha256"]:
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_PAYLOAD_SHA_MISMATCH")
    try:
        payload = json.loads(queue_input.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_PAYLOAD_INVALID") from exc
    identity_fields = (
        "date", "market", "article_id", "source_sha256", "body_sha256", "prompt_sha256",
        "model_id", "configuration_sha256", "rules", "role", "stage",
    )
    if (not isinstance(payload, Mapping)
            or payload.get("model_id") != binding["model_id"]
            or identity.get("model_id") != binding["model_id"]
            or any(identity.get(field) != payload.get(field) for field in identity_fields)):
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_PAYLOAD_IDENTITY_MISMATCH")

    source_job_id = binding["source_job_id"]
    source_base = f"announcement_flash/jobs/{source_job_id}"
    source_input = io.read_bytes(source_base + "/input.json", max_bytes=1024 * 1024)
    if sha256_bytes(source_input) != binding["source_input_sha256"]:
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_SOURCE_SHA_MISMATCH")
    try:
        source = json.loads(source_input.decode("utf-8"))
        attempt = json.loads(io.read_bytes(f"attempts/{source_job_id}.json", max_bytes=8 * 1024 * 1024).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_SOURCE_INVALID") from exc
    context = attempt.get("context") if isinstance(attempt, dict) else None
    scope_refs = context.get("scope_refs") if isinstance(context, dict) else None
    if (not isinstance(source, dict)
            or source.get("schema") != "v4.manager_workbench.announcement_flash_input.v1"
            or source.get("job_id") != source_job_id
            or source.get("target_date") != binding["target_date"]
            or not isinstance(attempt, dict)
            or attempt.get("job_id") != source_job_id
            or attempt.get("state") != "INTERRUPTED"
            or not isinstance(context, dict)
            or context.get("target_date") != binding["target_date"]
            or not isinstance(scope_refs, dict)
            or scope_refs.get("capture_operation") != "ANNOUNCEMENT_FLASH_INCREMENTAL"):
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_SOURCE_NOT_INTERRUPTED")
    try:
        io.read_bytes(source_base + "/result.json", max_bytes=64 * 1024 * 1024)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_SOURCE_RESULT_UNREADABLE") from exc
    else:
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_SOURCE_RESULT_PRESENT")


def _announcement_activity_snapshot(
    workbench_root: Path, *, allowed_orphan: Mapping[str, str] | None = None,
    model_lock_held: bool = False,
) -> dict[str, Any]:
    """Fail closed when any dated Flash task or queue worker can be interrupted."""
    from infrastructure.owned_io import SafeRoot

    root = _exact_path(Path(workbench_root), kind="directory", label="ANNOUNCEMENT_WORKBENCH_ROOT")
    io = SafeRoot(root)
    active_attempts: list[dict[str, Any]] = []
    try:
        attempt_names = io.files("attempts")
    except (OSError, ValueError) as exc:
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ATTEMPT_SCAN_FAILED") from exc
    for name in attempt_names:
        try:
            raw = io.read_bytes("attempts/" + name, max_bytes=8 * 1024 * 1024)
            record = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("API_RELEASE_ANNOUNCEMENT_ATTEMPT_READ_FAILED") from exc
        if not isinstance(record, dict):
            raise ValueError("API_RELEASE_ANNOUNCEMENT_ATTEMPT_SCHEMA_INVALID")
        context = record.get("context")
        scope_refs = context.get("scope_refs") if isinstance(context, dict) else None
        operation = scope_refs.get("capture_operation") if isinstance(scope_refs, dict) else None
        if not isinstance(operation, str) or not operation.startswith("ANNOUNCEMENT_FLASH"):
            continue
        state = record.get("state")
        if state in {"QUEUED", "RUNNING"}:
            target_date = context.get("target_date") if isinstance(context, dict) else None
            active_attempts.append({
                "job_id": record.get("job_id") if isinstance(record.get("job_id"), str) else name[:-5],
                "target_date": target_date if isinstance(target_date, str) else "CANNOT_CONFIRM",
                "state": state,
                "capture_operation": operation,
            })

    queue_state = None
    queue_ref = "announcement_flash/queue/queue-state.json"
    try:
        queue_raw = io.read_bytes(queue_ref, max_bytes=64 * 1024 * 1024)
    except FileNotFoundError:
        queue_raw = None
    except (OSError, ValueError) as exc:
        raise ValueError("API_RELEASE_ANNOUNCEMENT_QUEUE_READ_FAILED") from exc
    if queue_raw is not None:
        try:
            queue_state = json.loads(queue_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("API_RELEASE_ANNOUNCEMENT_QUEUE_INVALID") from exc
        if (not isinstance(queue_state, dict)
                or queue_state.get("schema") != "v4.announcement-engine-queue/v1"
                or not isinstance(queue_state.get("jobs"), dict)):
            raise ValueError("API_RELEASE_ANNOUNCEMENT_QUEUE_INVALID")
    running_queue = []
    running_queue_records: list[tuple[str, dict[str, Any]]] = []
    if isinstance(queue_state, dict):
        for key, item in queue_state["jobs"].items():
            if isinstance(item, dict) and item.get("status") == "RUNNING":
                identity = item.get("identity") if isinstance(item.get("identity"), dict) else {}
                running_queue.append({
                    "idempotency_key": key if isinstance(key, str) else "CANNOT_CONFIRM",
                    "queue_id": item.get("queue_id") if isinstance(item.get("queue_id"), str) else "CANNOT_CONFIRM",
                    "article_id": identity.get("article_id") if isinstance(identity.get("article_id"), str) else "CANNOT_CONFIRM",
                })
                running_queue_records.append((key, item))
    allowed_running_orphan = None
    if allowed_orphan is not None:
        if len(running_queue_records) != 1 or not model_lock_held:
            raise ValueError("API_RELEASE_ANNOUNCEMENT_ORPHAN_NOT_UNIQUE_OR_LOCKED")
        orphan_key, orphan_item = running_queue_records[0]
        _validate_cutover_orphan(io, root / "announcement_flash" / "queue", orphan_key,
                                 orphan_item, allowed_orphan)
        allowed_running_orphan = {
            "source_job_id": allowed_orphan["source_job_id"],
            "target_date": allowed_orphan["target_date"],
            "idempotency_key": orphan_key,
            "payload_sha256": allowed_orphan["payload_sha256"],
            "owner_clear": True,
            "model_lock_held": True,
            "source_result_absent": True,
            "validated_result_absent": True,
        }
    if active_attempts or (running_queue and allowed_running_orphan is None):
        raise ValueError("API_RELEASE_ANNOUNCEMENT_ACTIVITY_BUSY")
    receipt = {
        "schema": ANNOUNCEMENT_CUTOVER_GUARD_SCHEMA,
        "status": "PASS",
        "active_attempts": active_attempts,
        "running_queue_items": running_queue,
        "all_target_dates_checked": True,
    }
    if allowed_running_orphan is not None:
        receipt["allowed_running_orphan"] = allowed_running_orphan
    return receipt


@contextmanager
def announcement_flash_cutover_guard(
    workbench_root: Path, *, timeout_seconds: float = 10.0,
    allow_orphan_source_job_id: str | None = None,
    allow_orphan_idempotency_key: str | None = None,
    allow_orphan_payload_sha256: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Hold the same submission lock as every API Flash entry point through cutover.

    ``workbench_root`` is WorkbenchStore.root, not its parent state-root setting.
    Acquire this before the all-date scan, keep the context open through API
    rebind and readback, and release only after success or completed rollback.
    """
    from infrastructure.owned_io import SafeRoot, LockAcquireTimeout

    root = _exact_path(Path(workbench_root), kind="directory", label="ANNOUNCEMENT_WORKBENCH_ROOT")
    io = SafeRoot(root)
    allowed_orphan = _normalise_cutover_orphan_binding(
        allow_orphan_source_job_id, allow_orphan_idempotency_key, allow_orphan_payload_sha256)
    lock_name = hashlib.sha256(ANNOUNCEMENT_SUBMIT_LOCK_KEY.encode("utf-8")).hexdigest()
    try:
        with io.kernel_lock(f"locks/{lock_name}.lock", timeout=timeout_seconds):
            if allowed_orphan is None:
                yield _announcement_activity_snapshot(root)
            else:
                queue_root = root / "announcement_flash" / "queue"
                with _hold_existing_announcement_model_lock(queue_root, allowed_orphan["model_id"]):
                    yield _announcement_activity_snapshot(
                        root, allowed_orphan=allowed_orphan, model_lock_held=True)
    except LockAcquireTimeout as exc:
        raise ValueError("API_RELEASE_ANNOUNCEMENT_SUBMIT_LOCK_BUSY") from exc


def _hold_announcement_cutover_cli(
    workbench_root: Path, timeout_seconds: float, *, allow_orphan_source_job_id: str | None = None,
    allow_orphan_idempotency_key: str | None = None, allow_orphan_payload_sha256: str | None = None,
) -> int:
    with announcement_flash_cutover_guard(
        workbench_root, timeout_seconds=timeout_seconds,
        allow_orphan_source_job_id=allow_orphan_source_job_id,
        allow_orphan_idempotency_key=allow_orphan_idempotency_key,
        allow_orphan_payload_sha256=allow_orphan_payload_sha256,
    ) as receipt:
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True), flush=True)
        # Keep the OS lock alive while the operator follows the activation or
        # rollback commands in another terminal. EOF releases it on process exit.
        sys.stdin.readline()
    print(json.dumps({"schema": ANNOUNCEMENT_CUTOVER_GUARD_SCHEMA, "status": "RELEASED"}), flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    hold = subparsers.add_parser("hold-announcement-cutover")
    hold.add_argument("--workbench-root", required=True)
    hold.add_argument("--timeout-seconds", type=float, default=10.0)
    hold.add_argument("--allow-orphan-source-job-id")
    hold.add_argument("--allow-orphan-idempotency-key")
    hold.add_argument("--allow-orphan-payload-sha256")
    args = parser.parse_args(argv)
    if args.command == "hold-announcement-cutover":
        try:
            return _hold_announcement_cutover_cli(
                Path(args.workbench_root), args.timeout_seconds,
                allow_orphan_source_job_id=args.allow_orphan_source_job_id,
                allow_orphan_idempotency_key=args.allow_orphan_idempotency_key,
                allow_orphan_payload_sha256=args.allow_orphan_payload_sha256,
            )
        except (OSError, ValueError) as exc:
            code = str(exc) if str(exc).startswith("API_RELEASE_") else "API_RELEASE_ANNOUNCEMENT_PREFLIGHT_FAILED"
            print(json.dumps({"schema": ANNOUNCEMENT_CUTOVER_GUARD_SCHEMA, "status": "BLOCKED", "code": code}),
                  file=sys.stderr, flush=True)
            return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
