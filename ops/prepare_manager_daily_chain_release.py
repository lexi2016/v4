#!/usr/bin/env python3
"""Stage a split-root ManagerResearch release candidate without activation.

The API and scheduler trees are already copied from their exact active release
roots. This helper pins them to one disabled binding and writes candidate-only
LaunchAgent plist copies, manifests, and rollback identities. It never calls
launchctl and never writes to the live state/configuration roots.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import plistlib
from pathlib import Path
import re
from typing import Any, Mapping

from infrastructure.scheduling.manager_announcement_supervisor import (
    BINDING_SCHEMA, binding_inventory, validate_binding,
)
from ops.prepare_api_only_cutover import (
    _replace_assignments, extract_environment, rewrite_api_only_plist,
)

ACTIVE_BASES = {
    "api": "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-research-calendar-all-r1-20261007-api/app",
    "scheduler": "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/hk-research-calendar-all-r1-20261007-scheduler/app",
}
ACTIVE_PLISTS = {
    "api": "/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist",
    "scheduler": "/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist",
}
C1_SOURCE_DELTA = {
    "api": {
        "apps/api/v35_api/manager_research_router.py",
        "docs/manager_daily_research.md",
        "infrastructure/scheduling/manager_announcement_supervisor.py",
        "ops/manager_announcement_body_batch.py",
        "ops/run_manager_daily_announcement.py",
        "ops/prepare_manager_daily_chain_release.py",
        "release-manifest.c1-candidate.json",
        "release-manifest.c1-candidate-r2.json",
        "release-manifest.c1-final.json",
        "release-manifest.c1-final2.json",
        "tests/test_manager_announcement_supervisor.py",
        "v4/manager_research/workspace_announcements.py",
    },
    "scheduler": {"ops/run_v35_macos_scheduler_daemon.py"},
}
C1_SOURCE_DELTA["scheduler"].update({
    "release-manifest.c1-candidate.json",
    "release-manifest.c1-candidate-r2.json",
    "release-manifest.c1-final.json",
    "release-manifest.c1-final2.json",
})


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def _write_or_verify(path: Path, raw: bytes) -> None:
    """Finish a previously interrupted manifest write without replacing bytes."""
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise ValueError("C1_EXISTING_CANDIDATE_MANIFEST_MISMATCH:" + str(path))
        return
    _write_exclusive(path, raw)


def _file_inventory(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for current, dirs, names in os.walk(root, followlinks=False):
        base = Path(current)
        retained_dirs = []
        for directory in sorted(dirs):
            path = base / directory
            if directory in {"__pycache__", ".pytest_cache"}:
                continue
            if path.is_symlink():
                relative = path.relative_to(root).as_posix()
                result[relative] = "SYMLINK:" + os.readlink(path)
                continue
            retained_dirs.append(directory)
        dirs[:] = retained_dirs
        for name in sorted(names):
            path = base / name
            if path.suffix == ".pyc" or name == ".DS_Store":
                continue
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative] = "SYMLINK:" + os.readlink(path)
            elif path.is_file():
                result[relative] = _sha(path.read_bytes())
    return result


def _assert_base_delta(base: Mapping[str, Any], root_key: str, app_root: Path,
                       current: Mapping[str, str]) -> None:
    base_info = base.get("bases", {}).get(root_key)
    if not isinstance(base_info, Mapping) or base_info.get("path") != ACTIVE_BASES[root_key]:
        raise ValueError("C1_ACTIVE_BASE_IDENTITY_MISMATCH")
    base_files = {}
    for item in base_info.get("files", []):
        if not isinstance(item, Mapping):
            continue
        if str(item.get("path", "")).endswith(".pyc") or item.get("path", "").split("/")[-2:-1] == ["__pycache__"]:
            continue
        if item.get("kind") == "file":
            base_files[item["path"]] = item.get("sha256")
        elif item.get("kind") == "symlink":
            base_files[item["path"]] = "SYMLINK:" + str(item.get("target"))
    overlay_prefix = "release/" + ("api_app/" if root_key == "api" else "scheduler_app/")
    b2_paths = set()
    for item in base.get("b2_overlay", []):
        rel = item.get("path") if isinstance(item, Mapping) else None
        if isinstance(rel, str) and rel.startswith(overlay_prefix):
            b2_paths.add(rel[len(overlay_prefix):])
    allowed = b2_paths | C1_SOURCE_DELTA[root_key]
    if not set(base_files).issubset(current):
        raise ValueError("C1_BASE_RELEASE_FILE_MISSING")
    for rel, expected in base_files.items():
        if current[rel] != expected and rel not in allowed:
            raise ValueError("C1_UNAUTHORIZED_BASE_FILE_DELTA:" + rel)
    for rel in set(current) - set(base_files):
        if rel not in allowed:
            raise ValueError("C1_UNAUTHORIZED_NEW_RELEASE_FILE:" + rel)


def _digest_json(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha(raw)


def _safe_stage_suffix(value: str) -> str:
    """Restrict generated stage names to one portable path component."""
    if not isinstance(value, str) or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?", value) is None:
        raise ValueError("C1_STAGE_SUFFIX_INVALID")
    return value


def _stage_artifact_paths(root: Path, suffix: str) -> dict[str, Path | str]:
    token = _safe_stage_suffix(suffix)
    config = root / "staged_config"
    api_root = root / "release/api_app"
    scheduler_root = root / "release/scheduler_app"
    return {
        "binding": config / f"manager-plan-binding-c1.disabled.{token}.json",
        "proposed": config / f"manager-plan-binding-c1.proposed-enabled.blocked.{token}.json",
        "receipt": config / f"manager_daily_chain_c1_release_receipt.{token}.json",
        "api_plist": config / f"com.lexi.v35.api-only.c1-{token}.plist",
        "scheduler_plist": config / f"com.lexi.v35.scheduler.c1-{token}.plist",
        "api_manifest": api_root / f"release-manifest.c1-{token}.json",
        "scheduler_manifest": scheduler_root / f"release-manifest.c1-{token}.json",
        "api_release_id": f"v4-manager-daily-chain-c1-api-{token}-candidate",
        "scheduler_release_id": f"v4-manager-daily-chain-c1-scheduler-{token}-candidate",
    }


def _stage_scheduler_plist(source: dict[str, Any], *, source_path: Path,
                           scheduler_root: Path, api_root: Path,
                           release_id: str,
                           manifest_path: Path, manifest_sha: str,
                           binding_path: Path, state_root: Path,
                           api_cycle_sha: str, python: Path) -> dict[str, Any]:
    env = source.get("EnvironmentVariables")
    args = source.get("ProgramArguments")
    if (not isinstance(env, dict) or not isinstance(args, list) or len(args) != 2
            or args[0] != "/bin/bash" or Path(str(args[1])).name != "launch_v35_macos_scheduler.sh"):
        raise ValueError("C1_SCHEDULER_PLIST_SOURCE_CONTRACT_INVALID")
    old_root = Path(str(env.get("V35_APP_ROOT", "")))
    if not old_root.is_absolute() or not old_root.is_dir():
        raise ValueError("C1_SCHEDULER_APP_ROOT_UNVERIFIED")
    staged = copy.deepcopy(source)
    new_env = staged["EnvironmentVariables"]
    for key, value in list(new_env.items()):
        if not isinstance(value, str) or not Path(value).is_absolute():
            continue
        try:
            relative = Path(value).relative_to(old_root)
        except ValueError:
            continue
        new_env[key] = str(scheduler_root / relative)
    new_env.update({
        "V35_APP_ROOT": str(scheduler_root),
        "V35_RELEASE_ID": release_id,
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
        "PYTHONPATH": str(scheduler_root / "upstreams") + ":" + str(scheduler_root),
        "V4_MANAGER_RESEARCH_STATE_ROOT": str(state_root),
        "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(binding_path),
        "V4_MANAGER_ANNOUNCEMENT_BINDING": str(binding_path),
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": str(api_root),
        "V4_MANAGER_ANNOUNCEMENT_PYTHON": str(python),
        "V4_MANAGER_ANNOUNCEMENT_PYTHON_SHA256": _sha(python.resolve(strict=True).read_bytes()),
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": api_cycle_sha,
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": "",
    })
    for key in ("production_allowed", "buy_gate_updated", "orders_sent",
                "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT"):
        if key in new_env and str(new_env[key]).lower() not in {"false", "0"}:
            raise ValueError("C1_SCHEDULER_SOURCE_SAFETY_FLAG_UNSAFE")
        new_env[key] = "false"
    staged["ProgramArguments"] = ["/bin/bash", str(scheduler_root / "ops/launch_v35_macos_scheduler.sh")]
    staged["WorkingDirectory"] = str(scheduler_root)
    return staged


def stage(*, candidate_root: Path, api_plist_path: Path, scheduler_plist_path: Path,
          security_master_root: Path, python: Path, stage_suffix: str = "final2",
          supersedes_suffix: str | None = None,
          superseded_stage_receipt: Path | None = None) -> dict[str, Any]:
    root = candidate_root.expanduser().resolve(strict=True)
    stage_suffix = _safe_stage_suffix(stage_suffix)
    if supersedes_suffix is not None:
        supersedes_suffix = _safe_stage_suffix(supersedes_suffix)
        if supersedes_suffix == stage_suffix:
            raise ValueError("C1_SUPERSEDED_STAGE_SUFFIX_MUST_DIFFER")
        if superseded_stage_receipt is None:
            raise ValueError("C1_SUPERSEDED_STAGE_RECEIPT_REQUIRED")
        superseded_stage_receipt = superseded_stage_receipt.expanduser().resolve(strict=True)
        expected_receipt_name = f"manager_daily_chain_c1_release_receipt.{supersedes_suffix}.json"
        if (superseded_stage_receipt.name != expected_receipt_name
                or not superseded_stage_receipt.is_file()):
            raise ValueError("C1_SUPERSEDED_STAGE_RECEIPT_IDENTITY_MISMATCH")
    elif superseded_stage_receipt is not None:
        raise ValueError("C1_SUPERSEDED_STAGE_SUFFIX_REQUIRED")
    api_root = (root / "release/api_app").resolve(strict=True)
    scheduler_root = (root / "release/scheduler_app").resolve(strict=True)
    if api_root == scheduler_root or api_root in scheduler_root.parents or scheduler_root in api_root.parents:
        raise ValueError("C1_SPLIT_RELEASE_ROOTS_OVERLAP")
    api_plist_path = api_plist_path.expanduser().resolve(strict=True)
    scheduler_plist_path = scheduler_plist_path.expanduser().resolve(strict=True)
    if (str(api_plist_path) != ACTIVE_PLISTS["api"]
            or str(scheduler_plist_path) != ACTIVE_PLISTS["scheduler"]):
        raise ValueError("C1_ACTIVE_PLIST_IDENTITY_MISMATCH")
    api_source = plistlib.loads(api_plist_path.read_bytes())
    scheduler_source = plistlib.loads(scheduler_plist_path.read_bytes())
    api_source_env = extract_environment(api_source)
    scheduler_source_env = extract_environment(scheduler_source)
    security_master = security_master_root.expanduser().resolve(strict=True)
    if not security_master.is_dir():
        raise ValueError("C1_SECURITY_MASTER_ROOT_UNAVAILABLE")
    py = python.expanduser()
    resolved_py = py.resolve(strict=True)
    source_python = Path(scheduler_source_env.get("V4_MANAGER_ANNOUNCEMENT_PYTHON", "")).resolve(strict=True)
    if (api_source_env.get("V35_APP_ROOT") != ACTIVE_BASES["api"]
            or scheduler_source_env.get("V35_APP_ROOT") != ACTIVE_BASES["scheduler"]
            or Path(api_source_env.get("V4_MANAGER_SECURITY_MASTER_ROOT", "")).resolve(strict=True)
                != security_master
            or source_python != resolved_py
            or api_source_env.get("V4_MANAGER_RESEARCH_STATE_ROOT")
                != scheduler_source_env.get("V4_MANAGER_RESEARCH_STATE_ROOT")):
        raise ValueError("C1_SOURCE_RUNTIME_IDENTITY_MISMATCH")
    base = _json_file(root / "manifests/base_inventory.json")
    api_current = _file_inventory(api_root)
    scheduler_current = _file_inventory(scheduler_root)
    _assert_base_delta(base, "api", api_root, api_current)
    _assert_base_delta(base, "scheduler", scheduler_root, scheduler_current)
    state_root = root / "state/manager_auto_research"
    config = root / "staged_config"
    artifacts = _stage_artifact_paths(root, stage_suffix)
    binding_path = artifacts["binding"]
    proposed_path = artifacts["proposed"]
    receipt_path = artifacts["receipt"]
    api_manifest_path = artifacts["api_manifest"]
    scheduler_manifest_path = artifacts["scheduler_manifest"]
    output_paths = (binding_path, artifacts["api_plist"], artifacts["scheduler_plist"],
        receipt_path, proposed_path, api_manifest_path, scheduler_manifest_path)
    for path in output_paths:
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
    api_release_id = artifacts["api_release_id"]
    scheduler_release_id = artifacts["scheduler_release_id"]

    def make_release_manifest(release_id: str, app_root: Path, inventory: dict[str, str],
                              base_key: str) -> dict[str, Any]:
        value = {
            "schema_version": "v4.manager_research.split_release_candidate.v1",
            "release_id": release_id, "status": "CANDIDATE_NOT_ACTIVATED",
            "app_root": str(app_root),
            "base_inventory_sha256": _digest_json(base.get("bases", {}).get(base_key, {})),
            "app_file_sha256": inventory,
            "superseded_candidate_manifest": {
                "path": str(app_root / "release-manifest.c1-candidate.json"),
                "sha256": _sha((app_root / "release-manifest.c1-candidate.json").read_bytes()),
                "status": "UNREFERENCED_PARTIAL_WRITER_ARTIFACT",
            } if (app_root / "release-manifest.c1-candidate.json").is_file() else None,
            "superseded_candidate_manifest_r2": {
                "path": str(app_root / "release-manifest.c1-candidate-r2.json"),
                "sha256": _sha((app_root / "release-manifest.c1-candidate-r2.json").read_bytes()),
                "status": "UNREFERENCED_PREVIOUS_WRITER_STAGE",
            } if (app_root / "release-manifest.c1-candidate-r2.json").is_file() else None,
            "superseded_candidate_manifest_final": {
                "path": str(app_root / "release-manifest.c1-final.json"),
                "sha256": _sha((app_root / "release-manifest.c1-final.json").read_bytes()),
                "status": "UNREFERENCED_PREVIOUS_WRITER_STAGE",
            } if (app_root / "release-manifest.c1-final.json").is_file() else None,
            "stage_dependency_sha256": {
                name: sha for name, sha in inventory.items()
                if name.startswith("stage_center/") and name.endswith((".py", ".json"))
            },
            "RESEARCH_ONLY": True, "production_allowed": False,
            "buy_gate_updated": False, "orders_sent": False,
        }
        if supersedes_suffix is not None:
            superseded_manifest = app_root / f"release-manifest.c1-{supersedes_suffix}.json"
            if not superseded_manifest.is_file() or superseded_manifest.is_symlink():
                raise ValueError("C1_SUPERSEDED_RELEASE_MANIFEST_MISSING")
            value[f"superseded_candidate_manifest_{supersedes_suffix}"] = {
                "path": str(superseded_manifest),
                "sha256": _sha(superseded_manifest.read_bytes()),
                "status": "SUPERSEDED_BY_CANDIDATE_STAGE",
            }
        value["sha256"] = _digest_json(value)
        return value

    api_manifest = make_release_manifest(api_release_id, api_root, api_current, "api")
    scheduler_manifest = make_release_manifest(scheduler_release_id, scheduler_root, scheduler_current, "scheduler")
    _write_or_verify(api_manifest_path, (json.dumps(api_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    _write_or_verify(scheduler_manifest_path, (json.dumps(scheduler_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    api_manifest_sha = _sha(api_manifest_path.read_bytes())
    scheduler_manifest_sha = _sha(scheduler_manifest_path.read_bytes())

    api_staged = rewrite_api_only_plist(api_source, candidate_app_root=api_root,
        release_id=api_release_id, manifest_path=api_manifest_path,
        manifest_sha256=api_manifest_sha, candidate_manager_state_root=state_root)
    api_assignments = api_staged.get("ProgramArguments")
    if not isinstance(api_assignments, list):
        raise ValueError("C1_API_PLIST_ARGUMENTS_INVALID")
    api_staged["ProgramArguments"] = _replace_assignments(api_assignments, {
        "V35_APP_ROOT": str(api_root),
        "V35_RELEASE_ID": api_release_id,
        "PYTHONPATH": f"{api_root / 'upstreams'}:{api_root}",
        "V35_RELEASE_MANIFEST_PATH": str(api_manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": api_manifest_sha,
        "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(binding_path),
    })
    api_cycle_sha = _sha((api_root / "ops/run_manager_announcement_cycle.py").read_bytes())
    binding = {
        "schema_version": BINDING_SCHEMA, "enabled": False,
        "policy_status": "PROPOSAL_ONLY", "policy": "BALANCED_V1",
        "research_only": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
        "app_root": str(api_root), "manager_state_root": str(state_root),
        "security_master_root": str(security_master), "python": str(py),
        "python_resolved": str(resolved_py), "python_sha256": _sha(resolved_py.read_bytes()),
        "priority_codes": [], "preopen_plan": {"enabled": True, "lead_seconds": 180, "status": "PROPOSAL_ONLY"},
        "plan_material_refresh_only": False, "announcement_collection_enabled": False,
        "announcement_execution_owner": {
            "execution_owner": "HEARTBEAT", "ownership_status": "HEARTBEAT_OWNED",
            "automation_ref": "automation-3", "scheduler_hook_enabled": False,
            "latest_execution_status": "NOT_RUN", "latest_success_status": "CANNOT_CONFIRM",
            "latest_gap_status": "CANNOT_CONFIRM", "latest_receipt_status": "NOT_OBSERVED",
        },
        "files": binding_inventory(api_root),
    }
    validate_binding(binding, api_root)
    _write_exclusive(binding_path, (json.dumps(binding, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    binding_sha = _sha(binding_path.read_bytes())
    proposed_enabled = copy.deepcopy(binding)
    proposed_enabled.update({
        "enabled": True,
        "activation_status": "BLOCKED_OWNER_CANARY_REQUIRED",
        "required_activation_evidence": "owner activation canary receipt",
    })
    # This file is a proposal only; validate_binding must reject it until an
    # actual owner canary receipt is attached. Neither staged plist references it.
    _write_exclusive(proposed_path, (json.dumps(proposed_enabled, ensure_ascii=False,
        sort_keys=True, indent=2) + "\n").encode())

    scheduler_staged = _stage_scheduler_plist(scheduler_source, source_path=scheduler_plist_path,
        scheduler_root=scheduler_root, api_root=api_root, release_id=scheduler_release_id,
        manifest_path=scheduler_manifest_path,
        manifest_sha=scheduler_manifest_sha, binding_path=binding_path, state_root=state_root,
        api_cycle_sha=api_cycle_sha, python=py)
    api_path = artifacts["api_plist"]
    scheduler_path = artifacts["scheduler_plist"]
    _write_exclusive(api_path, plistlib.dumps(api_staged, fmt=plistlib.FMT_XML, sort_keys=True))
    _write_exclusive(scheduler_path, plistlib.dumps(scheduler_staged, fmt=plistlib.FMT_XML, sort_keys=True))
    api_env = extract_environment(api_staged)
    scheduler_env = dict(scheduler_staged["EnvironmentVariables"])
    for env in (api_env, scheduler_env):
        if (env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH") != str(binding_path)
                or env.get("V4_MANAGER_RESEARCH_STATE_ROOT") != str(state_root)):
            raise ValueError("C1_STAGED_RUNTIME_BINDING_MISMATCH")
    if scheduler_env.get("V4_MANAGER_ANNOUNCEMENT_BINDING") != api_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH"):
        raise ValueError("C1_STAGED_SHARED_BINDING_MISMATCH")
    source_api_env = extract_environment(api_source)
    source_scheduler_env = scheduler_source_env
    receipt = {
        "schema_version": "manager_daily_chain.c1_release_stage.v1",
        "status": "CANDIDATE_STAGED_NOT_ACTIVATED", "activation_status": "NOT_ACTIVATED",
        "launchctl_called": False, "candidate_root": str(root),
        "source_api": {"path": str(api_plist_path), "sha256": _sha(api_plist_path.read_bytes()),
                       "label": api_source.get("Label"), "release_id": source_api_env.get("V35_RELEASE_ID")},
        "source_scheduler": {"path": str(scheduler_plist_path), "sha256": _sha(scheduler_plist_path.read_bytes()),
                              "label": scheduler_source.get("Label"),
                              "release_id": source_scheduler_env.get("V35_RELEASE_ID")},
        "candidate_api": {"root": str(api_root), "manifest_path": str(api_manifest_path),
                           "manifest_sha256": api_manifest_sha, "plist_path": str(api_path),
                           "plist_sha256": _sha(api_path.read_bytes())},
        "candidate_scheduler": {"root": str(scheduler_root), "manifest_path": str(scheduler_manifest_path),
                                "manifest_sha256": scheduler_manifest_sha, "plist_path": str(scheduler_path),
                                "plist_sha256": _sha(scheduler_path.read_bytes())},
        "shared_binding": {"path": str(binding_path), "sha256": binding_sha, "enabled": False,
                           "announcement_collection_enabled": False, "manager_state_root": str(state_root)},
        "proposed_enabled_config": {
            "status": "BLOCKED_NOT_RENDERABLE_WITHOUT_OWNER_CANARY",
            "path": str(proposed_path), "sha256": _sha(proposed_path.read_bytes()),
            "activation_receipt": "CANNOT_CONFIRM", "enabled": True,
            "announcement_collection_enabled": False,
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        },
        "superseded_writer_stage_receipt": {
            "path": str(config / "manager_daily_chain_c1_release_receipt.json"),
            "sha256": _sha((config / "manager_daily_chain_c1_release_receipt.json").read_bytes()),
            "status": "UNREFERENCED_PREVIOUS_CANDIDATE_STAGE",
        } if (config / "manager_daily_chain_c1_release_receipt.json").is_file() else None,
        "superseded_final_stage_receipt": {
            "path": str(config / "manager_daily_chain_c1_release_receipt.final.json"),
            "sha256": _sha((config / "manager_daily_chain_c1_release_receipt.final.json").read_bytes()),
            "status": "UNREFERENCED_PREVIOUS_CANDIDATE_STAGE",
        } if (config / "manager_daily_chain_c1_release_receipt.final.json").is_file() else None,
        "superseded_prior_stage_receipt": {
            "path": str(superseded_stage_receipt),
            "sha256": _sha(superseded_stage_receipt.read_bytes()),
            "status": "SUPERSEDED_BY_CANDIDATE_STAGE",
        } if superseded_stage_receipt is not None else None,
        "rollback": {
            "status": "IDENTITY_ONLY_NO_ACTIVATION",
            "api_original_path": str(api_plist_path), "api_original_sha256": _sha(api_plist_path.read_bytes()),
            "scheduler_original_path": str(scheduler_plist_path), "scheduler_original_sha256": _sha(scheduler_plist_path.read_bytes()),
            "old_api_root": api_source_env.get("V35_APP_ROOT"),
            "old_scheduler_root": source_scheduler_env.get("V35_APP_ROOT"),
            "old_manager_state_root": api_source_env.get("V4_MANAGER_RESEARCH_STATE_ROOT"),
            "guard": "No original plist or state path was changed; rollback identity points to current source plists.",
        },
        "dependency_inventory": {"api_stage_files": len(api_manifest["stage_dependency_sha256"]),
            "scheduler_stage_files": len(scheduler_manifest["stage_dependency_sha256"]),
            "api_file_count": len(api_current), "scheduler_file_count": len(scheduler_current),
            "base_inventory_sha256": _digest_json(base)},
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    _write_exclusive(receipt_path, (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--api-plist", type=Path, required=True)
    parser.add_argument("--scheduler-plist", type=Path, required=True)
    parser.add_argument("--security-master-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--stage-suffix", default="final2")
    parser.add_argument("--supersedes-stage-suffix")
    parser.add_argument("--superseded-stage-receipt", type=Path)
    args = parser.parse_args(argv)
    result = stage(candidate_root=args.candidate_root, api_plist_path=args.api_plist,
        scheduler_plist_path=args.scheduler_plist, security_master_root=args.security_master_root,
        python=args.python, stage_suffix=args.stage_suffix,
        supersedes_suffix=args.supersedes_stage_suffix,
        superseded_stage_receipt=args.superseded_stage_receipt)
    print(json.dumps({"status": result["status"], "candidate_root": result["candidate_root"],
        "shared_binding": result["shared_binding"], "activation_status": result["activation_status"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
