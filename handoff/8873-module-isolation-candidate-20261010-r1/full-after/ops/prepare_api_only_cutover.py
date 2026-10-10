#!/usr/bin/env python3
"""Prepare (but never activate) an api-only LaunchAgent cutover.

This module deliberately has a narrow write surface.  It reads the existing
api-only plist, renders a candidate plist below a candidate release directory,
and writes a rollback plan.  It does not call ``launchctl`` and it refuses
paths in the source checkout or the formal release directory.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import plistlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

try:
    from .api_release_integration import (
        api_release_lock_path, module_role_contract, read_active_release,
        verify_api_release_candidate,
    )
except ImportError:
    try:
        from api_release_integration import (
            api_release_lock_path, module_role_contract, read_active_release,
            verify_api_release_candidate,
        )
    except ImportError:
        _integration_path = Path(__file__).with_name("api_release_integration.py")
        _integration_spec = importlib.util.spec_from_file_location(
            "_v4_api_release_integration", _integration_path
        )
        if _integration_spec is None or _integration_spec.loader is None:
            raise ImportError("cannot load adjacent API release integration guard")
        _integration_module = importlib.util.module_from_spec(_integration_spec)
        sys.modules[_integration_spec.name] = _integration_module
        _integration_spec.loader.exec_module(_integration_module)
        api_release_lock_path = _integration_module.api_release_lock_path
        module_role_contract = _integration_module.module_role_contract
        read_active_release = _integration_module.read_active_release
        verify_api_release_candidate = _integration_module.verify_api_release_candidate


SCHEMA_VERSION = "v4.api_only_cutover_plan.v1"
DEFAULT_FORMAL_RELEASE_ROOT = Path(
    "/REDACTED_LOCAL_HOME/Library/Application Support/com.lexi.v35.local/releases"
)
DEFAULT_MANAGER_STATE_ROOT = Path(
    "/REDACTED_LOCAL_HOME/Library/Application Support/com.lexi.v35.local/state/manager_auto_research"
)
SENSITIVE_KEY_RE = re.compile(
    r"(?:TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|PROXY)", re.IGNORECASE
)
REWRITE_KEYS = {
    "V35_APP_ROOT",
    "V35_RELEASE_ID",
    "PYTHONPATH",
    "V35_RELEASE_MANIFEST_PATH",
    "V35_RELEASE_MANIFEST_SHA256",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(root))
    except ValueError:
        return False
    return True


def assert_safe_candidate_path(
    candidate_root: Path,
    *,
    source_root: Path | None = None,
    formal_release_root: Path = DEFAULT_FORMAL_RELEASE_ROOT,
) -> None:
    """Reject a candidate path that could overwrite an app or formal release."""

    candidate = _resolved(candidate_root)
    if source_root is not None and (
        _is_within(candidate, source_root) or _is_within(source_root, candidate)
    ):
        raise ValueError("candidate root must be separate from the source checkout")
    if _is_within(candidate, formal_release_root):
        raise ValueError("candidate root must not be inside the formal release root")


def _parse_assignment(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str) or "=" not in value:
        return None
    key, item = value.split("=", 1)
    if not key or any(char.isspace() for char in key):
        return None
    return key, item


def extract_environment(plist: Mapping[str, Any]) -> dict[str, str]:
    """Collect env assignments from both plist forms without importing them."""

    values: dict[str, str] = {}
    arguments = plist.get("ProgramArguments", [])
    if isinstance(arguments, list):
        for item in arguments:
            parsed = _parse_assignment(item)
            if parsed is not None:
                values[parsed[0]] = parsed[1]
    environment = plist.get("EnvironmentVariables", {})
    if isinstance(environment, Mapping):
        for key, value in environment.items():
            if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
                values[key] = str(value)
    return values


def _replace_assignments(arguments: Sequence[Any], replacements: Mapping[str, str]) -> list[Any]:
    if not arguments or _parse_assignment(arguments[0]) is not None:
        raise ValueError("api-only ProgramArguments must start with an executable")
    result: list[Any] = []
    seen: set[str] = set()
    for item in arguments:
        parsed = _parse_assignment(item)
        if parsed is None or parsed[0] not in replacements:
            result.append(item)
            continue
        key = parsed[0]
        result.append(f"{key}={replacements[key]}")
        seen.add(key)
    # The five release identity values are part of the existing plist
    # contract.  A manager state override is intentionally additive: the
    # current api-only plist has no such variable.  For the current
    # ``/usr/bin/env`` wrapper contract, insert it after argv0 and the
    # existing assignments, immediately before the wrapped executable.  An
    # assignment before argv0 would make launchd try to execute the variable
    # string itself.
    missing = set(REWRITE_KEYS) - seen
    if missing:
        raise ValueError(
            "api-only plist is missing required ProgramArguments keys: "
            + ", ".join(sorted(missing))
        )
    additional = [
        f"{key}={replacements[key]}"
        for key in sorted(set(replacements) - seen)
    ]
    if additional:
        first_assignment_after_argv0 = next(
            (
                index
                for index in range(1, len(result))
                if _parse_assignment(result[index]) is None
            ),
            len(result),
        )
        result[first_assignment_after_argv0:first_assignment_after_argv0] = additional
    return result


def rewrite_api_only_plist(
    plist: MutableMapping[str, Any],
    *,
    candidate_app_root: Path,
    release_id: str,
    manifest_path: Path,
    manifest_sha256: str,
    candidate_manager_state_root: Path | None = None,
) -> MutableMapping[str, Any]:
    """Return a staged plist preserving runtime roots and safety flags."""

    app_root = _resolved(candidate_app_root)
    manifest = _resolved(manifest_path)
    replacements = {
        "V35_APP_ROOT": str(app_root),
        "V35_RELEASE_ID": release_id,
        "PYTHONPATH": f"{app_root / 'upstreams'}:{app_root}",
        "V35_RELEASE_MANIFEST_PATH": str(manifest),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha256,
    }
    if candidate_manager_state_root is not None:
        replacements["V4_MANAGER_RESEARCH_STATE_ROOT"] = str(
            _resolved(candidate_manager_state_root)
        )
    staged: MutableMapping[str, Any] = dict(plist)
    arguments = plist.get("ProgramArguments")
    if not isinstance(arguments, list):
        raise ValueError("api-only plist must contain ProgramArguments")
    staged["ProgramArguments"] = _replace_assignments(arguments, replacements)

    environment = plist.get("EnvironmentVariables")
    if isinstance(environment, Mapping):
        updated_environment = dict(environment)
        # A variable may be represented in ProgramArguments, as in the
        # current api-only plist.  Only rewrite EnvironmentVariables keys that
        # are present; never invent a second environment producer.
        for key in replacements:
            if key in updated_environment:
                updated_environment[key] = replacements[key]
        if candidate_manager_state_root is not None:
            updated_environment.setdefault(
                "V4_MANAGER_RESEARCH_STATE_ROOT",
                replacements["V4_MANAGER_RESEARCH_STATE_ROOT"],
            )
        staged["EnvironmentVariables"] = updated_environment

    if "WorkingDirectory" not in plist:
        raise ValueError("api-only plist must contain WorkingDirectory")
    staged["WorkingDirectory"] = str(app_root)
    return staged


def rewrite_module_plist(
    source_plist: Mapping[str, Any], *, role: str, base_role: str = "gateway", candidate_app_root: Path,
    release_id: str, manifest_path: Path, manifest_sha256: str,
) -> dict[str, Any]:
    """Create one fixed-role LaunchAgent from the current gateway binding."""
    contract = module_role_contract()
    roles = contract["roles"]
    if role not in {"gateway", "stage", "manager"} or base_role not in {"gateway", "stage", "manager"}:
        raise ValueError("API_MODULE_ROLE_INVALID")
    base = roles[base_role]
    target = roles[role]
    if source_plist.get("Label") != base["label"]:
        raise ValueError("API_MODULE_SOURCE_ROLE_LABEL_MISMATCH")
    staged = rewrite_api_only_plist(
        dict(source_plist), candidate_app_root=candidate_app_root,
        release_id=release_id, manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
    )
    arguments = staged.get("ProgramArguments")
    if not isinstance(arguments, list) or not arguments or arguments[0] != "/usr/bin/env":
        raise ValueError("API_MODULE_LAUNCHAGENT_ENV_WRAPPER_REQUIRED")
    if not any(arguments[index:index + 2] == ["-m", "apps.api.v35_api.run"]
               for index in range(len(arguments) - 1)):
        raise ValueError("API_MODULE_LAUNCHAGENT_RUN_ENTRYPOINT_MISMATCH")
    result: list[Any] = []
    port_flags = 0
    for index, value in enumerate(arguments):
        if value == "--port":
            port_flags += 1
            result.extend((value, str(target["port"])))
            if index + 1 >= len(arguments):
                raise ValueError("API_MODULE_LAUNCHAGENT_PORT_VALUE_MISSING")
        elif index > 0 and arguments[index - 1] == "--port":
            continue
        else:
            result.append(value)
    if port_flags != 1:
        raise ValueError("API_MODULE_LAUNCHAGENT_PORT_FLAG_INVALID")
    if result.count("--host") != 1:
        raise ValueError("API_MODULE_LAUNCHAGENT_HOST_FLAG_INVALID")
    host_index = result.index("--host")
    if host_index + 1 >= len(result) or result[host_index + 1] != "127.0.0.1":
        raise ValueError("API_MODULE_LAUNCHAGENT_HOST_NOT_LOOPBACK")
    # Role identity travels in the wrapper environment; the Python entrypoint
    # independently validates that any port agrees with the checked-in role.
    result = [item for index, item in enumerate(result)
              if not (isinstance(item, str) and item.partition("=")[0] in {"V35_API_ROLE", "V35_API_PORT"})]
    insert_at = next((index for index in range(1, len(result))
                      if _parse_assignment(result[index]) is None), len(result))
    result[insert_at:insert_at] = [
        f"V35_API_ROLE={role}", f"V35_API_PORT={target['port']}",
    ]
    staged["ProgramArguments"] = result
    staged["Label"] = target["label"]
    environment = staged.get("EnvironmentVariables")
    if isinstance(environment, Mapping):
        updated = dict(environment)
        updated["V35_API_ROLE"] = role
        updated["V35_API_PORT"] = str(target["port"])
        staged["EnvironmentVariables"] = updated
    return staged


def render_module_cutover(
    *, source_active_plist_path: Path, candidate_root: Path, release_id: str,
    manifest_path: Path, manifest_sha256: str, role: str, source_root: Path,
    base_role: str = "gateway",
    formal_release_root: Path = DEFAULT_FORMAL_RELEASE_ROOT,
    module_id: str | None = None, lock_lease: object | None = None,
) -> dict[str, object]:
    """Prepare a role-bound plist and plan; never alter an active LaunchAgent."""
    api = sys.modules[verify_api_release_candidate.__module__]
    if module_id is not None:
        if role != "gateway" or base_role != "gateway":
            raise ValueError("API_BUSINESS_SAME_GATEWAY_REQUIRED")
        source_active_plist_path = api._exact_path(
            source_active_plist_path, kind="file", label="API_RELEASE_ACTIVE_PLIST"
        )
        candidate_root = api._exact_path(candidate_root, kind="directory", label="API_RELEASE_CANDIDATE_ROOT")
        if lock_lease is None:
            with api.shared_api_release_lock(source_active_plist_path) as lease:
                return render_module_cutover(
                    source_active_plist_path=source_active_plist_path,
                    candidate_root=candidate_root, release_id=release_id,
                    manifest_path=manifest_path, manifest_sha256=manifest_sha256,
                    role=role, source_root=source_root, base_role=base_role,
                    formal_release_root=formal_release_root, module_id=module_id, lock_lease=lease,
                )
        api.assert_api_release_lock(lock_lease, source_active_plist_path)
    source_active_plist_path = _resolved(source_active_plist_path)
    candidate_root = _resolved(candidate_root)
    role_contract = module_role_contract()
    role_config = role_contract["roles"].get(role)
    base_config = role_contract["roles"].get(base_role)
    if not isinstance(role_config, Mapping) or not isinstance(base_config, Mapping):
        raise ValueError("API_MODULE_ROLE_INVALID")
    assert_safe_candidate_path(
        candidate_root, source_root=source_root, formal_release_root=formal_release_root
    )
    role_release_root = _resolved(Path(str(role_config["release_root"])))
    if _is_within(candidate_root, role_release_root) or _is_within(role_release_root, candidate_root):
        raise ValueError("API_MODULE_CANDIDATE_OVERLAPS_FORMAL_ROLE_ROOT")
    if not source_active_plist_path.is_file() or source_active_plist_path.is_symlink():
        raise FileNotFoundError(source_active_plist_path)
    manifest_path = _resolved(manifest_path)
    if not _is_within(manifest_path, candidate_root) or not manifest_path.is_file():
        raise ValueError("API_MODULE_MANIFEST_PATH_INVALID")
    actual_manifest_sha = sha256_file(manifest_path)
    if actual_manifest_sha != manifest_sha256:
        raise ValueError("API_RELEASE_INTEGRATION_MANIFEST_SHA_MISMATCH")
    target_plist_path = source_active_plist_path.with_name(str(role_config["plist_name"]))
    verified = verify_api_release_candidate(
        candidate_root=candidate_root,
        active_api_plist_path=source_active_plist_path,
        expected_manifest_sha256=manifest_sha256,
        active_pointer="base",
        role=role,
        base_role=base_role,
        lock_plist_path=target_plist_path,
        lock_lease=lock_lease if module_id is not None else None,
        require_shared_lock=module_id is not None,
        require_business_module=module_id is not None,
    )
    if module_id is not None and verified["business_module"]["module_id"] != module_id:
        raise ValueError("API_BUSINESS_MODULE_ID_BINDING_MISMATCH")
    if module_id is None and verified.get("business_module") is not None:
        raise ValueError("API_BUSINESS_MODULE_ID_REQUIRED")
    with source_active_plist_path.open("rb") as handle:
        source_plist = plistlib.load(handle)
    if module_id is not None:
        staged = rewrite_api_only_plist(
            source_plist, candidate_app_root=candidate_root / "app", release_id=release_id,
            manifest_path=manifest_path, manifest_sha256=manifest_sha256,
        )
    else:
        staged = rewrite_module_plist(
            source_plist, role=role, base_role=base_role, candidate_app_root=candidate_root / "app",
            release_id=release_id, manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
        )
    config_dir = candidate_root / "config"
    if module_id is not None:
        api.assert_business_output_boundary(candidate_root, api.read_active_release(source_active_plist_path))
        if config_dir.exists() or config_dir.is_symlink():
            api._exact_path(config_dir, kind="directory", label="API_BUSINESS_CONFIG")
    config_dir.mkdir(exist_ok=True)
    staged_path = config_dir / str(role_config["plist_name"])
    plan_path = config_dir / "api-module-cutover-plan.json"
    if staged_path.exists() or staged_path.is_symlink() or plan_path.exists() or plan_path.is_symlink():
        raise FileExistsError("refusing to overwrite staged module configuration")
    with staged_path.open("xb") as handle:
        plistlib.dump(staged, handle, fmt=plistlib.FMT_XML, sort_keys=True)
    staged_sha = sha256_file(staged_path)
    lock_path = api_release_lock_path(target_plist_path, role=role)
    source_identity = read_active_release(source_active_plist_path, role=base_role)
    if target_plist_path.is_symlink():
        raise ValueError("API_MODULE_TARGET_PLIST_SYMLINK")
    if target_plist_path.is_file():
        target_identity = (
            source_identity if base_role == role and target_plist_path == source_active_plist_path
            else read_active_release(target_plist_path, role=role)
        )
        target_preimage: dict[str, object] = {
            "status": "PRESENT",
            "path": str(target_plist_path),
            "sha256": sha256_file(target_plist_path),
            "release_id": target_identity["release_id"],
            "manifest_sha256": target_identity["release_manifest_sha256"],
        }
    else:
        target_preimage = {"status": "ABSENT", "path": str(target_plist_path), "sha256": "ABSENT"}
    previous_role_binding = target_preimage if target_preimage["status"] == "PRESENT" else None
    plan: dict[str, object] = {
        "schema_version": "v4.api_module_cutover_plan.v1",
        "target_role": role,
        "module_id": module_id,
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "source_active_plist": {
            "role": base_role,
            "path": str(source_active_plist_path),
            "sha256": sha256_file(source_active_plist_path),
            "label": base_config["label"],
        },
        "candidate_manifest": {"path": str(manifest_path), "sha256": manifest_sha256},
        "candidate_plist": {
            "path": str(staged_path), "sha256": staged_sha,
            "install_path": str(target_plist_path), "label": role_config["label"],
            "port": role_config["port"],
        },
        "target_plist_preimage": target_preimage,
        "module_release": verified,
        "release_lock": {"path": str(lock_path), "independent_by_role": True},
        "port_check": {"status": "NOT_RUN", "must_repeat_before_activation": True},
        "manager_state": {"copied": False, "roots_inherited_from_base_role_plist": True},
        "gateway_static_assets": {
            "module_role_owns_static_assets": role_config["owns_static_assets"],
            "module_release_writes_gateway_bundle": False,
        },
        "rollback": {
            "mode": "REVERSE_DELTA_ON_CURRENT_ACTIVE" if module_id is not None else "ROLE_ONLY",
            "previous_role_plist": previous_role_binding,
            "base_role_plist_unchanged": str(source_active_plist_path),
            "bootstrap_rollback_requires_coordinated_pre_split_gateway_restore": (
                base_role == "gateway" and role != "gateway"
            ),
        },
        "future_actions": {
            "activation": "CANNOT_RUN_UNTIL_INDEPENDENT_REVIEW_AND_PORT_CHECK",
            "required_protocol": "role-bound CAS, independent role lock, before/after pointer readback and role-local rollback",
            "active_plist_changed": False,
            "launchctl_called": False,
        },
    }
    if module_id is not None:
        plan["rollback"] = {"mode": "REVERSE_DELTA_ON_CURRENT_ACTIVE", "whole_release_restore_for_module_rollback": False,
                            "entrypoint": "ops.api_release_integration.prepare_module_rollback",
                            "module_id": module_id, "must_rebind_current_active": True}
        plan["release_lock"] = {"path": str(lock_path), "shared_by_all_gateway_business_modules": True}
        plan["gateway_static_assets"]["non_target_bytes_preserved"] = True
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    plan["plan_path"] = str(plan_path)
    return plan


def _safe_json_value(key: str, value: str) -> str:
    if SENSITIVE_KEY_RE.search(key):
        return "<redacted>"
    return value


def _path_probe(value: str) -> dict[str, object] | None:
    """Describe a path-like env value without reading directory contents."""

    candidate = value
    if ":" in value and not value.startswith("/"):
        return None
    if ":" in value and value.startswith("/"):
        # PYTHONPATH-like values are handled as individual roots.
        return None
    if not (value.startswith("/") or value.startswith("~")):
        return None
    path = Path(value).expanduser()
    result: dict[str, object] = {
        "path": value,
        "exists": path.exists() or path.is_symlink(),
        "is_symlink": path.is_symlink(),
    }
    if path.is_symlink():
        result["link_target"] = os.readlink(path)
    resolved = _resolved(path)
    result["resolved_target"] = str(resolved)
    result["resolved_exists"] = resolved.exists()
    if resolved.exists():
        if resolved.is_dir():
            result["kind"] = "directory"
        elif resolved.is_file():
            result["kind"] = "file"
            result["code_sha256"] = sha256_file(resolved)
        else:
            result["kind"] = "other"
    else:
        result["kind"] = "missing"
    return result


def describe_preserved_environment(plist: Mapping[str, Any]) -> dict[str, object]:
    values = extract_environment(plist)
    records: dict[str, object] = {}
    for key in sorted(values):
        value = _safe_json_value(key, values[key])
        record: dict[str, object] = {"value": value}
        probe = _path_probe(values[key])
        if probe is not None:
            record["path_probe"] = probe
        records[key] = record
    safety = {
        key: values.get(key)
        for key in sorted(values)
        if key.lower() in {
            "research_only",
            "production_allowed",
            "buy_gate_updated",
            "orders_sent",
        }
        or key in {"RESEARCH_ONLY", "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT"}
    }
    return {"variables": records, "safety_flags": safety}


def render_cutover(
    *,
    source_plist_path: Path,
    candidate_root: Path,
    release_id: str,
    manifest_path: Path,
    manifest_sha256: str,
    backup_plist_path: Path | None = None,
    current_manager_state_root: Path = DEFAULT_MANAGER_STATE_ROOT,
    candidate_manager_state_root: Path | None = None,
    formal_release_root: Path = DEFAULT_FORMAL_RELEASE_ROOT,
    source_root: Path,
) -> dict[str, object]:
    """Write staged plist and rollback plan below ``candidate_root`` only."""

    source_plist_path = _resolved(source_plist_path)
    candidate_root = _resolved(candidate_root)
    assert_safe_candidate_path(
        candidate_root, source_root=source_root, formal_release_root=formal_release_root
    )
    if not source_plist_path.is_file():
        raise FileNotFoundError(source_plist_path)
    if not candidate_root.is_dir():
        raise FileNotFoundError(f"candidate root does not exist: {candidate_root}")
    manifest_path = _resolved(manifest_path)
    if not _is_within(manifest_path, candidate_root):
        raise ValueError("manifest path must be below candidate root")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"candidate manifest does not exist: {manifest_path}")
    manifest_actual_sha = sha256_file(manifest_path)
    if manifest_actual_sha != manifest_sha256:
        raise ValueError("API_RELEASE_INTEGRATION_MANIFEST_SHA_MISMATCH")
    api_integration = verify_api_release_candidate(
        candidate_root=candidate_root,
        active_api_plist_path=source_plist_path,
        expected_manifest_sha256=manifest_sha256,
        active_pointer="base",
    )
    if api_integration.get("business_module") is not None:
        raise ValueError("API_BUSINESS_MODULE_ENTRY_REQUIRED: use render_module_cutover")

    current_manager_state_root = _resolved(current_manager_state_root)
    candidate_manager_state_root = _resolved(
        candidate_manager_state_root or (candidate_root / "state" / "manager_auto_research")
    )
    if _is_within(candidate_manager_state_root, current_manager_state_root) or _is_within(
        current_manager_state_root, candidate_manager_state_root
    ):
        raise ValueError("candidate manager state root must be isolated from the current root")
    if candidate_manager_state_root == candidate_root or not _is_within(
        candidate_manager_state_root, candidate_root
    ):
        raise ValueError("candidate manager state root must be below candidate root")
    if not current_manager_state_root.exists() and not current_manager_state_root.is_symlink():
        raise FileNotFoundError(
            f"current manager state root is unavailable: {current_manager_state_root}"
        )
    candidate_manager_state_root.mkdir(parents=True, exist_ok=True)
    (candidate_manager_state_root / ".commits").mkdir(exist_ok=True)

    config_dir = candidate_root / "config"
    config_dir.mkdir(exist_ok=True)
    staged_path = config_dir / "com.lexi.v35.api-only.plist"
    plan_path = config_dir / "api-only-cutover-plan.json"
    if staged_path.exists() or staged_path.is_symlink() or plan_path.exists() or plan_path.is_symlink():
        raise FileExistsError("refusing to overwrite staged api-only configuration")

    with source_plist_path.open("rb") as handle:
        source_plist = plistlib.load(handle)
    staged = rewrite_api_only_plist(
        source_plist,
        candidate_app_root=candidate_root / "app",
        release_id=release_id,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        candidate_manager_state_root=candidate_manager_state_root,
    )
    with staged_path.open("wb") as handle:
        plistlib.dump(staged, handle, fmt=plistlib.FMT_XML, sort_keys=True)
    staged_sha = sha256_file(staged_path)
    current_sha = sha256_file(source_plist_path)
    backup_sha = None
    if backup_plist_path is not None:
        backup = _resolved(backup_plist_path)
        if backup.is_file():
            backup_sha = sha256_file(backup)
        else:
            backup = None
    else:
        backup = None

    label = str(source_plist.get("Label", "com.lexi.v35.api-only"))
    current_path = str(source_plist_path)
    staged_str = str(staged_path)
    rollback_source = str(backup or source_plist_path)
    plan: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "activation_status": "NOT_ACTIVATED",
        "launchctl_called": False,
        "source_plist": {"path": current_path, "sha256": current_sha, "label": label},
        "candidate_plist": {"path": staged_str, "sha256": staged_sha},
        "candidate_manifest": {"path": str(manifest_path), "sha256": manifest_sha256},
        "api_release_integration": {
            **api_integration,
            "preflight_revalidation_required_under_shared_lock": True,
            "shared_lock_protocol": "infrastructure.owned_interprocess_lock; lock file adjacent to active API plist",
        },
        "manager_state": {
            "current_root": str(current_manager_state_root),
            "candidate_root": str(candidate_manager_state_root),
            "roots_are_distinct": True,
            "authority_layout": ".commits/<YYYYMMDD>/<input_identity>.json",
            "candidate_state_copied": False,
            "shared_writer_guard": "Old and new writers must never run concurrently against one manager root.",
        },
        "rollback_backup": (
            {"path": rollback_source, "sha256": backup_sha}
            if backup is not None
            else {"path": rollback_source, "sha256": current_sha, "kind": "current_source_fallback"}
        ),
        "preserved_environment": describe_preserved_environment(source_plist),
        "future_commands": {
            "activate_candidate": [
                f"launchctl bootout gui/$(id -u)/{label}",
                f"launchctl bootstrap gui/$(id -u) {staged_str!r}",
            ],
            "rollback": [
                f"launchctl bootout gui/$(id -u)/{label}",
                f"cp {rollback_source!r} {current_path!r}",
                f"launchctl bootstrap gui/$(id -u) {current_path!r}",
            ],
        },
        "guard": "This plan is descriptive. No service, plist in Library, or scheduled task was changed.",
    }
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-plist", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--backup-plist", type=Path)
    parser.add_argument("--current-manager-state-root", type=Path, default=DEFAULT_MANAGER_STATE_ROOT)
    parser.add_argument("--candidate-manager-state-root", type=Path)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--formal-release-root", type=Path, default=DEFAULT_FORMAL_RELEASE_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        plan = render_cutover(
            source_plist_path=args.source_plist,
            candidate_root=args.candidate_root,
            release_id=args.release_id,
            manifest_path=args.manifest_path,
            manifest_sha256=args.manifest_sha256,
            backup_plist_path=args.backup_plist,
            current_manager_state_root=args.current_manager_state_root,
            candidate_manager_state_root=args.candidate_manager_state_root,
            source_root=args.source_root,
            formal_release_root=args.formal_release_root,
        )
    except (FileExistsError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"cutover preparation refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
