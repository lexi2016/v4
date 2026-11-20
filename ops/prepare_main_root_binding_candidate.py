"""Prepare and verify an offline Main release-binding candidate.

This module only reads the copied Main app tree and exact input snapshots. It
writes a new, private candidate bundle and never edits a launchd job, release,
policy, pin inventory, registry, or live service.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ops.api_release_integration import inventory_digest, inventory_tree


SCHEMA = "v4.main_root_binding_candidate.v1"
REVIEW_SCHEMA = "v4.main_source_binding_review.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONFIG_ROLES = {
    "manifest": Path("release-manifest.json"),
    "policy": Path("control/policy.json"),
    "pins": Path("control/managed-pins.json"),
    "plist": Path("launchd.plist"),
}
_PREIMAGE_FILES = {
    "manifest": "release-manifest.preimage",
    "policy": "policy.preimage",
    "pins": "managed-pins.preimage",
    "plist": "launchd.preimage",
}
_ENV_KEYS = (
    "V4_APP_ROOT",
    "V4_RELEASE_ID",
    "V4_RELEASE_MANIFEST_PATH",
    "V4_RELEASE_MANIFEST_SHA256",
    "V4_RESEARCH_RETENTION_POLICY",
    "V4_RESEARCH_RETENTION_POLICY_SHA256",
)
_LAUNCHER_RELATIVE = Path("ops/launch_v4_macos_scheduler.sh")
# Darwin's _CS_DARWIN_USER_TEMP_DIR value (not exposed by every Python
# version in os.confstr_names); resolve through os.confstr, never TMPDIR.
_DARWIN_USER_TEMP_DIR_CONFSTR = 65537

# This remediation only permits refreshing the two reviewed freshness leaves.
# Tests replace this mapping with temporary Stage/API LaunchAgent paths.
REVIEWABLE_PIN_PATHS: dict[str, dict[str, str]] = {
    "/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist": {
        "scope_id": "stage",
        "launchd_label": "com.lexi.stage-center.scheduler",
    },
    "/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist": {
        "scope_id": "api",
        "launchd_label": "com.lexi.v4.api",
    },
}


class CandidateError(ValueError):
    """A precondition or candidate binding did not match the frozen scope."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _sha256(raw)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CandidateError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise CandidateError("JSON_NONFINITE_NUMBER")


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateError(label + "_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise CandidateError(label + "_JSON_OBJECT_REQUIRED")
    return value, raw


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        rendered = json.dumps(
            value, ensure_ascii=False, sort_keys=True, indent=2,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CandidateError("CANDIDATE_JSON_NOT_SERIALIZABLE") from exc
    return (rendered + "\n").encode("utf-8")


def _absolute_path(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise CandidateError(label + "_ABSOLUTE_PATH_REQUIRED")
    return path


def _regular_file(path: str | Path, label: str) -> Path:
    value = _absolute_path(path, label)
    try:
        info = value.lstat()
    except OSError as exc:
        raise CandidateError(label + "_MISSING") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise CandidateError(label + "_NOT_REGULAR_FILE")
    if value.resolve(strict=True) != value:
        raise CandidateError(label + "_PATH_ALIAS")
    return value


def _directory(path: str | Path, label: str) -> Path:
    value = _absolute_path(path, label)
    try:
        info = value.lstat()
    except OSError as exc:
        raise CandidateError(label + "_MISSING") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise CandidateError(label + "_NOT_DIRECTORY")
    if value.resolve(strict=True) != value:
        raise CandidateError(label + "_PATH_ALIAS")
    return value


def _allowed_temp_roots() -> tuple[Path, ...]:
    """Resolve system temp roots without consulting caller-controlled TMPDIR."""
    roots: list[Path] = []
    try:
        roots.append(Path("/tmp").resolve(strict=True))
    except OSError:
        pass
    if sys.platform == "darwin":
        try:
            value = os.confstr(_DARWIN_USER_TEMP_DIR_CONFSTR)
        except (OSError, ValueError):
            value = None
        if value:
            try:
                roots.append(Path(value).resolve(strict=True))
            except OSError:
                pass
    return tuple(dict.fromkeys(roots))


def _fenced_temp_path(value: str | Path, label: str, *, must_exist: bool) -> Path:
    """Return a canonical path under /tmp or Darwin's system user temp root."""
    path = _absolute_path(value, label)
    if must_exist:
        path = _directory(path, label)
        resolved = path.resolve(strict=True)
    else:
        if path.exists() or path.is_symlink():
            raise CandidateError(label + "_MUST_NOT_EXIST")
        resolved = path.resolve(strict=False)
        if not resolved.parent.is_dir():
            raise CandidateError(label + "_PARENT_MISSING")
    roots = _allowed_temp_roots()
    if not any(resolved != root and resolved.is_relative_to(root) for root in roots):
        raise CandidateError(label + "_OUTSIDE_SYSTEM_TEMP_ROOT")
    return resolved


def _resolved_pinned_file(value: str, label: str) -> Path:
    path = _absolute_path(value, label)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CandidateError(label + "_MISSING") from exc
    if not resolved.is_file() or not stat.S_ISREG(resolved.stat().st_mode):
        raise CandidateError(label + "_NOT_REGULAR_FILE")
    return resolved


def _hash_file(path: Path) -> str:
    return _sha256(path.read_bytes())


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value))


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not value or ".." in path.parts or path == Path("."):
        raise CandidateError("UNSAFE_CANDIDATE_RELATIVE_PATH")
    return path


def _plist_environment(plist: Mapping[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    arguments = plist.get("ProgramArguments", [])
    if not isinstance(arguments, list):
        raise CandidateError("LAUNCHD_PROGRAM_ARGUMENTS_INVALID")
    for item in arguments:
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            if key in _ENV_KEYS:
                if key in values and values[key] != value:
                    raise CandidateError("LAUNCHD_ENV_BINDING_CONFLICT")
                values[key] = value
    environment = plist.get("EnvironmentVariables", {})
    if not isinstance(environment, dict):
        raise CandidateError("LAUNCHD_ENVIRONMENT_INVALID")
    for key in _ENV_KEYS:
        if key in environment:
            value = environment[key]
            if not isinstance(value, str):
                raise CandidateError("LAUNCHD_ENV_BINDING_NOT_STRING")
            if key in values and values[key] != value:
                raise CandidateError("LAUNCHD_ENV_BINDING_CONFLICT")
            values[key] = value
    return values


def _set_env_value(plist: dict[str, Any], key: str, value: str) -> None:
    environment = plist.setdefault("EnvironmentVariables", {})
    if not isinstance(environment, dict):
        raise CandidateError("LAUNCHD_ENVIRONMENT_INVALID")
    found = key in environment
    if found:
        environment[key] = value
    arguments = plist.get("ProgramArguments")
    if not isinstance(arguments, list):
        raise CandidateError("LAUNCHD_PROGRAM_ARGUMENTS_INVALID")
    rewritten: list[Any] = []
    for item in arguments:
        if isinstance(item, str) and item.startswith(key + "="):
            rewritten.append(key + "=" + value)
            found = True
        else:
            rewritten.append(item)
    plist["ProgramArguments"] = rewritten
    if not found:
        environment[key] = value


def _launcher_argument(plist: Mapping[str, Any], old_app_root: Path) -> int:
    arguments = plist.get("ProgramArguments")
    if not isinstance(arguments, list) or len(arguments) < 2:
        raise CandidateError("LAUNCHD_MAIN_LAUNCHER_MISSING")
    matches: list[int] = []
    for index, item in enumerate(arguments):
        if not isinstance(item, str) or not item.startswith("/"):
            continue
        path = Path(item)
        try:
            relative = path.relative_to(old_app_root)
        except ValueError:
            continue
        if relative == _LAUNCHER_RELATIVE:
            matches.append(index)
    if len(matches) != 1:
        raise CandidateError("LAUNCHD_MAIN_LAUNCHER_BINDING_FAILED")
    return matches[0]


def _inventory_for_app(app_root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    try:
        entries = inventory_tree(app_root)
    except (OSError, ValueError, TypeError) as exc:
        raise CandidateError("MAIN_APP_INVENTORY_FAILED") from exc
    files = [
        {"path": entry["path"], "sha256": entry["sha256"], "size": entry["size"]}
        for entry in entries
    ]
    return files, entries


def _verify_manifest_app_bytes(manifest: Mapping[str, Any], app_root: Path) -> list[dict[str, object]]:
    files, entries = _inventory_for_app(app_root)
    if manifest.get("app_files") != files:
        raise CandidateError("MAIN_APP_SOURCE_BYTES_DRIFT")
    expected_inventory = manifest.get("application_inventory")
    actual_inventory = {
        "entry_count": len(entries),
        "aggregate_sha256": inventory_digest(entries),
        "entries": entries,
    }
    if expected_inventory != actual_inventory:
        raise CandidateError("MAIN_APP_INVENTORY_DRIFT")
    return entries


def _validate_source_binding_review(
    pins: Mapping[str, Any], review_path: Path | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    bindings = pins.get("source_bindings")
    scopes = pins.get("consumer_scopes")
    if not isinstance(bindings, list) or not bindings or not isinstance(scopes, dict):
        raise CandidateError("MANAGED_PIN_INVENTORY_SCOPE_INVALID")
    if review_path is None:
        return {}, None
    review_path = _regular_file(review_path, "SOURCE_REVIEW")
    review, raw = _load_json(review_path, "SOURCE_REVIEW")
    if review.get("schema_version") != REVIEW_SCHEMA or review.get("status") != "PASS_SCOPE_PRESERVED":
        raise CandidateError("SOURCE_BINDING_REVIEW_NOT_PASS")
    if review.get("consumer_scopes_sha256") != _canonical_sha256(scopes):
        raise CandidateError("SOURCE_BINDING_SCOPE_REVIEW_MISMATCH")
    replacements = review.get("replacements")
    if not isinstance(replacements, list):
        raise CandidateError("SOURCE_BINDING_REVIEW_REPLACEMENTS_INVALID")
    ref_map: dict[str, dict[str, Any]] = {}
    for row in bindings:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str) or not _is_sha(row.get("sha256")):
            raise CandidateError("TYPED_SOURCE_BINDING_INVALID")
        path = row["path"]
        prior = ref_map.get(path)
        if prior and prior["sha256"] != row["sha256"]:
            raise CandidateError("TYPED_SOURCE_BINDING_HASH_CONFLICT")
        ref_map[path] = row
    result: dict[str, dict[str, Any]] = {}
    seen_scopes: set[str] = set()
    for item in replacements:
        if not isinstance(item, dict):
            raise CandidateError("SOURCE_BINDING_REVIEW_ENTRY_INVALID")
        old_path = item.get("old_path")
        old_sha = item.get("old_sha256")
        new_path = item.get("new_path")
        new_sha = item.get("new_sha256")
        old_preimage = item.get("old_preimage_path")
        if (not isinstance(old_path, str) or not _is_sha(old_sha)
                or not isinstance(new_path, str) or not _is_sha(new_sha)
                or not isinstance(old_preimage, str)
                or item.get("scope_preserved") is not True):
            raise CandidateError("SOURCE_BINDING_REVIEW_ENTRY_INVALID")
        current = ref_map.get(old_path)
        if current is None or current["sha256"] != old_sha:
            raise CandidateError("SOURCE_BINDING_REVIEW_OLD_REF_MISMATCH")
        if old_path in result:
            raise CandidateError("SOURCE_BINDING_REVIEW_DUPLICATE_PATH")
        allowed = REVIEWABLE_PIN_PATHS.get(old_path)
        if allowed is None:
            raise CandidateError("SOURCE_BINDING_REVIEW_PATH_NOT_ALLOWLISTED")
        if item.get("scope_id") != allowed["scope_id"]:
            raise CandidateError("SOURCE_BINDING_REVIEW_SCOPE_MISMATCH")
        if allowed["scope_id"] in seen_scopes:
            raise CandidateError("SOURCE_BINDING_REVIEW_DUPLICATE_SCOPE")
        seen_scopes.add(allowed["scope_id"])
        if pins["consumer_scopes"].get(allowed["scope_id"]) != "PINNED":
            raise CandidateError("SOURCE_BINDING_REVIEW_SCOPE_NOT_PINNED")
        if new_path != old_path:
            raise CandidateError("SOURCE_BINDING_REVIEW_RETARGET_PROHIBITED")
        old_file = _resolved_pinned_file(old_preimage, "SOURCE_OLD_PREIMAGE")
        if _hash_file(old_file) != old_sha:
            raise CandidateError("SOURCE_BINDING_OLD_PREIMAGE_HASH_MISMATCH")
        new_file = _resolved_pinned_file(new_path, "SOURCE_NEW_FILE")
        if old_file == new_file:
            raise CandidateError("SOURCE_BINDING_OLD_PREIMAGE_NOT_SEPARATE")
        if _hash_file(new_file) != new_sha:
            raise CandidateError("SOURCE_BINDING_NEW_FILE_HASH_MISMATCH")
        if _launchd_label(old_file) != allowed["launchd_label"]:
            raise CandidateError("SOURCE_BINDING_OLD_LAUNCHD_LABEL_MISMATCH")
        if _launchd_label(new_file) != allowed["launchd_label"]:
            raise CandidateError("SOURCE_BINDING_NEW_LAUNCHD_LABEL_MISMATCH")
        result[old_path] = {
            "path": new_path,
            "sha256": new_sha,
            "old_path": old_path,
            "old_sha256": old_sha,
            "old_preimage_path": str(old_file),
            "new_path": new_path,
            "new_sha256": new_sha,
            "scope_id": item.get("scope_id"),
            "scope_preserved": True,
        }
    return result, {
        "path": str(review_path),
        "sha256": _sha256(raw),
        "replacement_count": len(result),
        "consumer_scopes_sha256": review["consumer_scopes_sha256"],
    }


def _verify_all_source_bindings(
    pins: Mapping[str, Any], replacements: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, str]]:
    bindings = pins.get("source_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise CandidateError("MANAGED_PIN_SOURCE_BINDINGS_MISSING")
    verified: list[dict[str, str]] = []
    for row in bindings:
        if not isinstance(row, dict):
            raise CandidateError("TYPED_SOURCE_BINDING_INVALID")
        path_value, expected = row.get("path"), row.get("sha256")
        if not isinstance(path_value, str) or not _is_sha(expected):
            raise CandidateError("TYPED_SOURCE_BINDING_INVALID")
        replacement = replacements.get(path_value)
        check_path = replacement["new_path"] if replacement else path_value
        check_sha = replacement["new_sha256"] if replacement else expected
        resolved = _resolved_pinned_file(check_path, "SOURCE_BINDING")
        actual = _hash_file(resolved)
        if actual != check_sha:
            raise CandidateError("SOURCE_BINDING_DRIFT_UNREVIEWED")
        verified.append({"path": check_path, "sha256": actual})
    return verified


def _launchd_label(path: Path) -> str | None:
    try:
        value = plistlib.loads(path.read_bytes())
    except (plistlib.InvalidFileException, ValueError, TypeError) as exc:
        raise CandidateError("SOURCE_BINDING_LAUNCHD_PLIST_INVALID") from exc
    if not isinstance(value, dict):
        raise CandidateError("SOURCE_BINDING_LAUNCHD_PLIST_INVALID")
    label = value.get("Label")
    return label if isinstance(label, str) else None


def _input_chain(
    manifest: Mapping[str, Any], policy: Mapping[str, Any], pins: Mapping[str, Any],
    plist: Mapping[str, Any], manifest_raw: bytes, policy_raw: bytes,
    pins_raw: bytes, target_app_root: Path,
) -> tuple[Path, str, int]:
    old_app_value = manifest.get("app_root")
    release_id = manifest.get("release_id")
    if not isinstance(old_app_value, str) or not Path(old_app_value).is_absolute():
        raise CandidateError("MAIN_MANIFEST_APP_ROOT_INVALID")
    if not isinstance(release_id, str) or not release_id:
        raise CandidateError("MAIN_MANIFEST_RELEASE_ID_INVALID")
    old_app_root = Path(old_app_value)
    old_release_root = old_app_root.parent
    environment = _plist_environment(plist)
    expected_paths = {
        "V4_APP_ROOT": str(old_app_root),
        "V4_RELEASE_ID": release_id,
        "V4_RELEASE_MANIFEST_PATH": str(old_release_root / "release-manifest.json"),
        "V4_RELEASE_MANIFEST_SHA256": _sha256(manifest_raw),
        "V4_RESEARCH_RETENTION_POLICY": str(old_release_root / "control/policy.json"),
        "V4_RESEARCH_RETENTION_POLICY_SHA256": _sha256(policy_raw),
    }
    if any(environment.get(key) != value for key, value in expected_paths.items()):
        raise CandidateError("MAIN_INPUT_PLIST_BINDING_FAILED")
    workdir = plist.get("WorkingDirectory")
    if workdir != str(old_app_root):
        raise CandidateError("MAIN_INPUT_WORKDIR_BINDING_FAILED")
    launcher_index = _launcher_argument(plist, old_app_root)
    launch_args = plist.get("ProgramArguments", [])
    if Path(launch_args[launcher_index]).resolve(strict=False) != old_app_root / _LAUNCHER_RELATIVE:
        raise CandidateError("MAIN_INPUT_LAUNCHER_BINDING_FAILED")
    pin_ref = policy.get("managed_pin_inventory")
    expected_pin_path = str(old_release_root / "control/managed-pins.json")
    if (not isinstance(pin_ref, dict)
            or pin_ref.get("path") != expected_pin_path
            or pin_ref.get("sha256") != _sha256(pins_raw)):
        raise CandidateError("MAIN_INPUT_POLICY_PIN_BINDING_FAILED")
    expected_pin_root = pins.get("expected_main_app_root")
    if expected_pin_root not in {str(old_app_root), str(target_app_root)}:
        raise CandidateError("MAIN_ROOT_PREIMAGE_UNEXPECTED")
    return old_app_root, release_id, launcher_index


def _write_new(path: Path, raw: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        raise CandidateError("CANDIDATE_OUTPUT_EXISTS")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    os.chmod(path, mode)


def _file_record(path: Path, raw: bytes | None = None) -> dict[str, Any]:
    info = path.lstat()
    content = path.read_bytes() if raw is None else raw
    return {
        "path": str(path),
        "sha256": _sha256(content),
        "bytes": len(content),
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "device": info.st_dev,
        "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
    }


def _ensure_output_disjoint(
    output: Path, inputs: Sequence[Path], app_root: Path, release_root: Path,
) -> None:
    if output.exists() or output.is_symlink():
        raise CandidateError("CANDIDATE_OUTPUT_MUST_NOT_EXIST")
    parent = _directory(output.parent, "CANDIDATE_OUTPUT_PARENT")
    output = parent / output.name
    forbidden = [app_root, release_root]
    for path in forbidden:
        if output == path or output.is_relative_to(path) or path.is_relative_to(output):
            raise CandidateError("CANDIDATE_OUTPUT_OVERLAPS_INPUT_OR_TARGET")
    for input_path in inputs:
        if output == input_path or input_path.is_relative_to(output):
            raise CandidateError("CANDIDATE_OUTPUT_OVERLAPS_INPUT_OR_TARGET")


def prepare_candidate(
    *, source_app_root: Path, target_release_root: Path,
    manifest_path: Path, policy_path: Path, pins_path: Path, plist_path: Path,
    output_dir: Path, review_path: Path | None = None,
) -> dict[str, Any]:
    """Compile an offline candidate bundle from exact snapshots.

    ``source_app_root`` must be the already copied source tree at
    ``target_release_root/app``. The function never writes below either path.
    """
    source_app_root = _directory(source_app_root, "MAIN_COPIED_APP")
    target_release_root = _absolute_path(target_release_root, "TARGET_RELEASE_ROOT")
    if target_release_root.resolve(strict=False) != target_release_root:
        raise CandidateError("TARGET_RELEASE_ROOT_PATH_ALIAS")
    target_app_root = target_release_root / "app"
    if source_app_root != target_app_root:
        raise CandidateError("MAIN_COPIED_APP_ROOT_MISMATCH")
    if source_app_root.is_symlink() or not (source_app_root / _LAUNCHER_RELATIVE).is_file():
        raise CandidateError("MAIN_COPIED_LAUNCHER_MISSING")
    input_paths = [
        _regular_file(manifest_path, "INPUT_MANIFEST"),
        _regular_file(policy_path, "INPUT_POLICY"),
        _regular_file(pins_path, "INPUT_PINS"),
        _regular_file(plist_path, "INPUT_PLIST"),
    ]
    if review_path is not None:
        review_path = _regular_file(review_path, "SOURCE_REVIEW")
        input_paths.append(review_path)
    output_dir = _fenced_temp_path(output_dir, "CANDIDATE_OUTPUT", must_exist=False)
    _ensure_output_disjoint(output_dir, input_paths, source_app_root, target_release_root)

    manifest, manifest_raw = _load_json(input_paths[0], "INPUT_MANIFEST")
    policy, policy_raw = _load_json(input_paths[1], "INPUT_POLICY")
    pins, pins_raw = _load_json(input_paths[2], "INPUT_PINS")
    try:
        plist = plistlib.loads(input_paths[3].read_bytes())
    except (plistlib.InvalidFileException, ValueError, TypeError) as exc:
        raise CandidateError("INPUT_PLIST_INVALID") from exc
    if not isinstance(plist, dict):
        raise CandidateError("INPUT_PLIST_OBJECT_REQUIRED")

    entries = _verify_manifest_app_bytes(manifest, source_app_root)
    old_app_root, old_release_id, launcher_index = _input_chain(
        manifest, policy, pins, plist, manifest_raw, policy_raw, pins_raw,
        target_app_root,
    )
    replacements, review_record = _validate_source_binding_review(pins, review_path)
    verified_sources = _verify_all_source_bindings(pins, replacements)

    release_id = target_release_root.name
    if not release_id:
        raise CandidateError("TARGET_RELEASE_ID_INVALID")
    candidate_manifest = copy.deepcopy(manifest)
    candidate_manifest["app_root"] = str(target_app_root)
    candidate_manifest["release_id"] = release_id
    if isinstance(candidate_manifest.get("role_release_candidate"), dict):
        candidate_manifest["role_release_candidate"]["app_root"] = str(target_app_root)
        candidate_manifest["role_release_candidate"]["candidate_root"] = str(target_release_root)
    candidate_manifest["app_files"] = [
        {"path": entry["path"], "sha256": entry["sha256"], "size": entry["size"]}
        for entry in entries
    ]
    candidate_manifest["application_inventory"] = {
        "entry_count": len(entries),
        "aggregate_sha256": inventory_digest(entries),
        "entries": entries,
    }

    candidate_pins = copy.deepcopy(pins)
    candidate_pins["expected_main_app_root"] = str(target_app_root)
    for row in candidate_pins["source_bindings"]:
        replacement = replacements.get(row["path"])
        if replacement:
            row["path"] = replacement["path"]
            row["sha256"] = replacement["sha256"]
    pins_bytes = _json_bytes(candidate_pins)

    candidate_policy = copy.deepcopy(policy)
    candidate_policy["managed_pin_inventory"] = {
        "path": str(target_release_root / "control/managed-pins.json"),
        "sha256": _sha256(pins_bytes),
    }
    policy_bytes = _json_bytes(candidate_policy)
    candidate_manifest["main_storage_binding"] = {
        "schema_version": "v4.main_storage_binding.v1",
        "app_root": str(target_app_root),
        "policy_path": str(target_release_root / "control/policy.json"),
        "policy_sha256": _sha256(policy_bytes),
        "managed_pin_inventory_path": str(target_release_root / "control/managed-pins.json"),
        "managed_pin_inventory_sha256": _sha256(pins_bytes),
    }
    manifest_bytes = _json_bytes(candidate_manifest)

    candidate_plist = copy.deepcopy(plist)
    arguments = candidate_plist["ProgramArguments"]
    arguments[launcher_index] = str(target_app_root / _LAUNCHER_RELATIVE)
    candidate_plist["WorkingDirectory"] = str(target_app_root)
    values = {
        "V4_APP_ROOT": str(target_app_root),
        "V4_RELEASE_ID": release_id,
        "V4_RELEASE_MANIFEST_PATH": str(target_release_root / "release-manifest.json"),
        "V4_RELEASE_MANIFEST_SHA256": _sha256(manifest_bytes),
        "V4_RESEARCH_RETENTION_POLICY": str(target_release_root / "control/policy.json"),
        "V4_RESEARCH_RETENTION_POLICY_SHA256": _sha256(policy_bytes),
    }
    for key, value in values.items():
        _set_env_value(candidate_plist, key, value)
    plist_bytes = plistlib.dumps(candidate_plist, fmt=plistlib.FMT_XML, sort_keys=True)

    output_dir.mkdir(mode=0o700)
    os.chmod(output_dir, 0o700)
    preimage_root = output_dir / "preimages"
    candidate_root = output_dir / "candidate"
    preimage_root.mkdir(mode=0o700)
    candidate_root.mkdir(mode=0o700)

    input_by_role = dict(zip(("manifest", "policy", "pins", "plist"), input_paths[:4]))
    raw_by_role = dict(zip(("manifest", "policy", "pins", "plist"),
                           (manifest_raw, policy_raw, pins_raw, input_paths[3].read_bytes())))
    preimages: dict[str, Any] = {}
    for role, path in input_by_role.items():
        raw = raw_by_role[role]
        preimage_path = preimage_root / _PREIMAGE_FILES[role]
        _write_new(preimage_path, raw, mode=0o400)
        source_record = _file_record(path, raw)
        preimages[role] = {
            "source": source_record,
            "copy_path": str(preimage_path),
            "copy_sha256": _sha256(preimage_path.read_bytes()),
            "copy_bytes": preimage_path.stat().st_size,
        }
    if review_path is not None:
        review_raw = review_path.read_bytes()
        review_copy = preimage_root / "source-binding-review.preimage"
        _write_new(review_copy, review_raw, mode=0o400)
        preimages["source_binding_review"] = {
            "source": _file_record(review_path, review_raw),
            "copy_path": str(review_copy),
            "copy_sha256": _sha256(review_raw),
            "copy_bytes": len(review_raw),
        }

    preimage_manifest = {
        "schema_version": "v4.main_root_binding_preimages.v1",
        "status": "READ_ONLY_EXACT_PREIMAGES",
        "files": preimages,
    }
    preimage_manifest_path = output_dir / "PREIMAGE_MANIFEST.json"
    preimage_manifest_raw = _json_bytes(preimage_manifest)
    _write_new(preimage_manifest_path, preimage_manifest_raw, mode=0o400)

    candidate_files = {
        "manifest": (candidate_root / _CONFIG_ROLES["manifest"], manifest_bytes),
        "policy": (candidate_root / _CONFIG_ROLES["policy"], policy_bytes),
        "pins": (candidate_root / _CONFIG_ROLES["pins"], pins_bytes),
        "plist": (candidate_root / _CONFIG_ROLES["plist"], plist_bytes),
    }
    outputs: dict[str, Any] = {}
    for role, (path, raw) in candidate_files.items():
        _write_new(path, raw)
        outputs[role] = {
            "staged_path": str(path),
            "target_path": str(target_release_root / _CONFIG_ROLES[role]),
            "sha256": _sha256(raw),
            "bytes": len(raw),
            "mode": "0600",
        }

    change_rows = [
        {"path": old_path, **dict(value)}
        for old_path, value in sorted(replacements.items())
    ]
    receipt = {
        "schema_version": SCHEMA,
        "status": "READY_FOR_REVIEW",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_root": str(target_release_root),
        "candidate_app_root": str(target_app_root),
        "candidate_release_id": release_id,
        "source_app_inventory_sha256": inventory_digest(entries),
        "source_app_entry_count": len(entries),
        "source_app_root_matches_target": source_app_root == target_app_root,
        "previous_main_app_root": str(old_app_root),
        "previous_release_id": old_release_id,
        "source_bindings_verified": len(verified_sources),
        "source_binding_review": review_record,
        "source_binding_changes": change_rows,
        "preimages": preimages,
        "preimage_manifest": {
            "path": str(preimage_manifest_path),
            "sha256": _sha256(preimage_manifest_raw),
            "mode": "0400",
        },
        "candidate_files": outputs,
        "protected_policy_values_sha256": _canonical_sha256({
            key: value for key, value in policy.items() if key != "managed_pin_inventory"
        }),
        "protected_pin_scope_sha256": _canonical_sha256({
            key: value for key, value in pins.items()
            if key not in {"expected_main_app_root", "source_bindings"}
        }),
        "rollback": {
            "status": "PLANNED_NOT_APPLIED",
            "scope": "candidate bundle only",
            "preimage_copies_mode": "0400",
            "rollback_sandbox": str(output_dir / "rollback-sandbox"),
            "apply_to_live": False,
            "launchctl_called": False,
            "steps": [
                "copy each candidate file into rollback-sandbox at its relative path",
                "call rollback_candidate_sandbox; it CAS-checks candidate SHA before restoring exact preimage bytes and mode",
                "compare restored SHA and mode to preimage records",
            ],
        },
        "deployment_status": "NOT_RUN",
        "natural_schedule_status": "NOT_RUN",
        "formal_api_status": "NOT_RUN",
    }
    receipt_path = output_dir / "CANDIDATE_CHAIN_RECEIPT.json"
    _write_new(receipt_path, _json_bytes(receipt), mode=0o400)
    return receipt


def validate_candidate_payload(
    *, config_dir: Path, app_root: Path, release_root: Path,
    require_manifest_storage_binding: bool = True,
) -> dict[str, Any]:
    """Verify the staged manifest→policy→pins→launchd candidate chain."""
    config_dir = _directory(config_dir, "CANDIDATE_CONFIG")
    app_root = _directory(app_root, "CANDIDATE_APP")
    release_root = _absolute_path(release_root, "CANDIDATE_RELEASE_ROOT")
    if release_root.resolve(strict=False) != release_root or app_root != release_root / "app":
        raise CandidateError("MAIN_APP_ROOT_BINDING_FAILED")
    manifest_path = _regular_file(config_dir / _CONFIG_ROLES["manifest"], "CANDIDATE_MANIFEST")
    policy_path = _regular_file(config_dir / _CONFIG_ROLES["policy"], "CANDIDATE_POLICY")
    pins_path = _regular_file(config_dir / _CONFIG_ROLES["pins"], "CANDIDATE_PINS")
    plist_path = _regular_file(config_dir / _CONFIG_ROLES["plist"], "CANDIDATE_PLIST")
    manifest, manifest_raw = _load_json(manifest_path, "CANDIDATE_MANIFEST")
    policy, policy_raw = _load_json(policy_path, "CANDIDATE_POLICY")
    pins, pins_raw = _load_json(pins_path, "CANDIDATE_PINS")
    try:
        plist = plistlib.loads(plist_path.read_bytes())
    except (plistlib.InvalidFileException, ValueError, TypeError) as exc:
        raise CandidateError("CANDIDATE_PLIST_INVALID") from exc
    if not isinstance(plist, dict):
        raise CandidateError("CANDIDATE_PLIST_OBJECT_REQUIRED")

    if manifest.get("app_root") != str(app_root) or manifest.get("release_id") != release_root.name:
        raise CandidateError("MAIN_MANIFEST_ROOT_BINDING_FAILED")
    _verify_manifest_app_bytes(manifest, app_root)
    manifest_binding = manifest.get("main_storage_binding")
    if manifest_binding is None and not require_manifest_storage_binding:
        pass
    elif (not isinstance(manifest_binding, dict)
          or manifest_binding.get("schema_version") != "v4.main_storage_binding.v1"
          or manifest_binding.get("app_root") != str(app_root)
          or manifest_binding.get("policy_path") != str(release_root / "control/policy.json")
          or manifest_binding.get("policy_sha256") != _sha256(policy_raw)
          or manifest_binding.get("managed_pin_inventory_path") != str(release_root / "control/managed-pins.json")
          or manifest_binding.get("managed_pin_inventory_sha256") != _sha256(pins_raw)):
        raise CandidateError("MANIFEST_STORAGE_BINDING_FAILED")
    if pins.get("expected_main_app_root") != str(app_root):
        raise CandidateError("MAIN_APP_ROOT_BINDING_FAILED")
    _verify_all_source_bindings(pins, {})
    pin_ref = policy.get("managed_pin_inventory")
    if (not isinstance(pin_ref, dict)
            or pin_ref.get("path") != str(release_root / "control/managed-pins.json")
            or pin_ref.get("sha256") != _sha256(pins_raw)):
        raise CandidateError("MANAGED_PIN_INVENTORY_BINDING_FAILED")
    environment = _plist_environment(plist)
    expected_env = {
        "V4_APP_ROOT": str(app_root),
        "V4_RELEASE_ID": release_root.name,
        "V4_RELEASE_MANIFEST_PATH": str(release_root / "release-manifest.json"),
        "V4_RELEASE_MANIFEST_SHA256": _sha256(manifest_raw),
        "V4_RESEARCH_RETENTION_POLICY": str(release_root / "control/policy.json"),
        "V4_RESEARCH_RETENTION_POLICY_SHA256": _sha256(policy_raw),
    }
    if any(environment.get(key) != value for key, value in expected_env.items()):
        raise CandidateError("MAIN_LAUNCHD_BINDING_FAILED")
    if plist.get("WorkingDirectory") != str(app_root):
        raise CandidateError("MAIN_LAUNCHD_WORKDIR_BINDING_FAILED")
    args = plist.get("ProgramArguments")
    if (not isinstance(args, list) or len(args) < 2
            or args[0] != "/bin/bash"
            or args[1] != str(app_root / _LAUNCHER_RELATIVE)):
        raise CandidateError("MAIN_LAUNCHD_EXECUTABLE_BINDING_FAILED")
    launcher = _regular_file(app_root / _LAUNCHER_RELATIVE, "CANDIDATE_LAUNCHER")
    if launcher.resolve(strict=True) != app_root / _LAUNCHER_RELATIVE:
        raise CandidateError("MAIN_LAUNCHD_EXECUTABLE_PATH_ALIAS")
    return {
        "status": "PASS_MAIN_ROOT_BINDING_CHAIN",
        "candidate_app_root": str(app_root),
        "candidate_release_id": release_root.name,
        "manifest_sha256": _sha256(manifest_raw),
        "policy_sha256": _sha256(policy_raw),
        "pins_sha256": _sha256(pins_raw),
        "launchd_plist_sha256": _sha256(plist_path.read_bytes()),
        "app_inventory_sha256": manifest["application_inventory"]["aggregate_sha256"],
        "launchctl_called": False,
    }


def rollback_candidate_sandbox(output_dir: Path) -> dict[str, Any]:
    """Restore a simulated activation below ``output_dir`` using exact CAS.

    This test-only rollback surface refuses paths outside the private candidate
    bundle; it cannot restore a live app or LaunchAgent.
    """
    output_dir = _fenced_temp_path(output_dir, "CANDIDATE_OUTPUT", must_exist=True)
    sandbox = output_dir / "rollback-sandbox"
    sandbox = _directory(sandbox, "ROLLBACK_SANDBOX")
    if sandbox.parent != output_dir:
        raise CandidateError("ROLLBACK_SANDBOX_OUTSIDE_CANDIDATE")
    receipt, _ = _load_json(output_dir / "CANDIDATE_CHAIN_RECEIPT.json", "CANDIDATE_RECEIPT")
    roles = receipt.get("candidate_files")
    preimage_manifest_ref = receipt.get("preimage_manifest")
    if not isinstance(preimage_manifest_ref, dict):
        raise CandidateError("ROLLBACK_PREIMAGE_MANIFEST_MISSING")
    preimage_manifest_path = _regular_file(
        preimage_manifest_ref.get("path", ""), "ROLLBACK_PREIMAGE_MANIFEST"
    )
    preimage_manifest_raw = preimage_manifest_path.read_bytes()
    if _sha256(preimage_manifest_raw) != preimage_manifest_ref.get("sha256"):
        raise CandidateError("ROLLBACK_PREIMAGE_MANIFEST_HASH_MISMATCH")
    preimage_manifest, _ = _load_json(preimage_manifest_path, "ROLLBACK_PREIMAGE_MANIFEST")
    if preimage_manifest.get("status") != "READ_ONLY_EXACT_PREIMAGES":
        raise CandidateError("ROLLBACK_PREIMAGE_MANIFEST_INVALID")
    preimages = preimage_manifest.get("files")
    if not isinstance(roles, dict) or not isinstance(preimages, dict):
        raise CandidateError("ROLLBACK_PLAN_INVALID")
    prepared: list[tuple[Path, bytes, str, str]] = []
    for role, relative in _CONFIG_ROLES.items():
        output_record, preimage_record = roles.get(role), preimages.get(role)
        if not isinstance(output_record, dict) or not isinstance(preimage_record, dict):
            raise CandidateError("ROLLBACK_PLAN_INVALID")
        target = sandbox / relative
        if target.is_symlink() or not target.is_file() or target.resolve(strict=True) != target:
            raise CandidateError("ROLLBACK_TARGET_NOT_REGULAR")
        current_sha = _hash_file(target)
        if current_sha != output_record.get("sha256"):
            raise CandidateError("ROLLBACK_CAS_MISMATCH")
        preimage_path = _regular_file(preimage_record.get("copy_path", ""), "ROLLBACK_PREIMAGE")
        preimage_raw = preimage_path.read_bytes()
        if (_sha256(preimage_raw) != preimage_record.get("copy_sha256")
                or _sha256(preimage_raw) != preimage_record["source"].get("sha256")):
            raise CandidateError("ROLLBACK_PREIMAGE_HASH_MISMATCH")
        mode = preimage_record["source"].get("mode")
        if not isinstance(mode, str) or not re.fullmatch(r"[0-7]{4}", mode):
            raise CandidateError("ROLLBACK_PREIMAGE_MODE_INVALID")
        prepared.append((target, preimage_raw, _sha256(preimage_raw), mode))

    temp_paths: list[Path] = []
    try:
        for target, raw, _sha, mode in prepared:
            fd, name = tempfile.mkstemp(prefix=".rollback-", dir=target.parent)
            temp_path = Path(name)
            temp_paths.append(temp_path)
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, int(mode, 8))
        for temp_path, (target, _raw, _sha, _mode) in zip(temp_paths, prepared):
            os.replace(temp_path, target)
        if any(_hash_file(target) != expected for target, _raw, expected, _mode in prepared):
            raise CandidateError("ROLLBACK_RESTORE_HASH_MISMATCH")
        if any(f"{stat.S_IMODE(target.stat().st_mode):04o}" != mode
               for target, _raw, _sha, mode in prepared):
            raise CandidateError("ROLLBACK_RESTORE_MODE_MISMATCH")
    finally:
        for path in temp_paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    return {
        "status": "PASS_EXACT_SANDBOX_ROLLBACK",
        "restored_roles": len(prepared),
        "live_files_touched": False,
        "launchctl_called": False,
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-app-root", type=Path, required=True)
    parser.add_argument("--target-release-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    parser.add_argument("--plist", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reviewed-source-bindings", type=Path)
    args = parser.parse_args()
    receipt = prepare_candidate(
        source_app_root=args.source_app_root,
        target_release_root=args.target_release_root,
        manifest_path=args.manifest,
        policy_path=args.policy,
        pins_path=args.pins,
        plist_path=args.plist,
        output_dir=args.output_dir,
        review_path=args.reviewed_source_bindings,
    )
    print(json.dumps({
        "status": receipt["status"],
        "receipt": str(args.output_dir / "CANDIDATE_CHAIN_RECEIPT.json"),
        "candidate_app_root": receipt["candidate_app_root"],
        "source_bindings_verified": receipt["source_bindings_verified"],
        "source_binding_changes": len(receipt["source_binding_changes"]),
        "deployment_status": receipt["deployment_status"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
