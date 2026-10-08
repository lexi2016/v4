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
    from .api_release_integration import verify_api_release_candidate
except ImportError:
    try:
        from api_release_integration import verify_api_release_candidate
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
        verify_api_release_candidate = _integration_module.verify_api_release_candidate


SCHEMA_VERSION = "v4.api_only_cutover_plan.v1"
DEFAULT_FORMAL_RELEASE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases"
)
DEFAULT_MANAGER_STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/manager_auto_research"
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
