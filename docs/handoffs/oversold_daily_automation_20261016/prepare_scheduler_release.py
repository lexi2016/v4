#!/usr/bin/env python3
"""Prepare and verify the isolated scheduler release; never activates it."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


DOC_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DOC_ROOT.parents[2]
BASE_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
CANDIDATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "oversold-daily-auto-20261016-r1"
)
RELEASE_ID = CANDIDATE_ROOT.name
DELTA_PATH = DOC_ROOT / "runtime_exact_delta.json"
PATCH_PATH = DOC_ROOT / "runtime_exact_delta.patch"
SOURCE_REVIEW = DOC_ROOT / "INDEPENDENT_REVIEW_R2.md"
SOURCE_REVIEW_SHA256 = "fc706b6ab88fabcbf8ba551ff7993e08a70990a599f6fa904ccfc1501eed23e5"
PREIMAGE_PATH = DOC_ROOT / "active_scheduler_plist.preimage"
RECEIPT_PATH = DOC_ROOT / "scheduler_release_preparation_receipt.json"
LOCK_NAMES = (".com.lexi.v35.scheduler.release.lock", "com.lexi.v35.scheduler.release.lock")
EXPECTED_LANES = ["US_MAPPING", "OVERSOLD"]
DELTA_KEYS = (
    "v4/manager_workbench/scheduler.py",
    "v4/manager_workbench/inputs/source_bindings.py",
    "v4/manager_workbench/service.py",
    "v4/manager_workbench/store.py",
    "v4/manager_workbench/oversold_daily.py",
    "upstreams/v3_shared_data/shared_data/hk_daily_supplement.py",
)
MODULES = (
    "ops.run_v35_macos_scheduler_daemon",
    "v4.manager_workbench.scheduler",
    "v4.manager_workbench.inputs.source_bindings",
    "v4.manager_workbench.service",
    "v4.manager_workbench.store",
    "v4.manager_workbench.oversold_daily",
    "upstreams.v3_shared_data.shared_data.hk_daily_supplement",
)


class PreparationError(RuntimeError):
    pass


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(rows: list[dict[str, Any]]) -> str:
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha_bytes(raw)


def safe_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PreparationError(f"INVALID_JSON:{path}") from error
    if not isinstance(value, dict):
        raise PreparationError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def exact_path(path: Path, label: str, *, directory: bool = False) -> Path:
    if path.is_symlink():
        raise PreparationError(f"{label}_SYMLINK")
    resolved = path.resolve(strict=True)
    if resolved != path:
        raise PreparationError(f"{label}_ALIAS")
    if directory and not path.is_dir():
        raise PreparationError(f"{label}_NOT_DIRECTORY")
    if not directory and not path.is_file():
        raise PreparationError(f"{label}_NOT_FILE")
    return resolved


def _physical_inventory(root: Path) -> list[dict[str, Any]]:
    """Include source, bytecode and directory modes; the root row is excluded."""
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        mode = f"{stat.S_IMODE(info.st_mode):04o}"
        if stat.S_ISDIR(info.st_mode):
            rows.append({"kind": "directory", "mode": mode, "path": relative})
        elif stat.S_ISREG(info.st_mode):
            rows.append({
                "kind": "file", "mode": mode, "path": relative,
                "sha256": sha_file(path), "size": info.st_size,
            })
        elif stat.S_ISLNK(info.st_mode):
            rows.append({"kind": "symlink", "mode": mode, "path": relative, "target": os.readlink(path)})
        else:
            raise PreparationError(f"UNSUPPORTED_FILESYSTEM_ENTRY:{relative}")
    return rows


def _launchctl_snapshot(label: str) -> dict[str, Any]:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise PreparationError(f"LAUNCHD_LABEL_NOT_LOADED:{result.returncode}")
    state_match = re.search(r"^\s*state = ([^\r\n]+)", result.stdout, re.MULTILINE)
    pid_match = re.search(r"^\s*pid = (\d+)", result.stdout, re.MULTILINE)
    if state_match is None or pid_match is None:
        raise PreparationError("LAUNCHD_RUNNING_IDENTITY_INCOMPLETE")
    return {"label": label, "state": state_match.group(1).strip(), "pid": int(pid_match.group(1))}


def _load_delta() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = safe_json(DELTA_PATH)
    if manifest.get("status") != "PREPARED_NOT_DEPLOYED":
        raise PreparationError("SOURCE_DELTA_NOT_FROZEN")
    if sha_file(PATCH_PATH) != manifest.get("patch", {}).get("sha256"):
        raise PreparationError("SOURCE_DELTA_PATCH_SHA_MISMATCH")
    rows = manifest.get("files")
    if not isinstance(rows, list) or tuple(row.get("path") for row in rows) != DELTA_KEYS:
        raise PreparationError("SOURCE_DELTA_PATH_SET_MISMATCH")
    if sha_file(SOURCE_REVIEW) != SOURCE_REVIEW_SHA256:
        raise PreparationError("SOURCE_REVIEW_R2_SHA_MISMATCH")
    if not any(token in SOURCE_REVIEW.read_text(encoding="utf-8") for token in ("REVIEWED=PASS_CANDIDATE", "REVIEWED=PASS")):
        raise PreparationError("SOURCE_REVIEW_R2_NOT_PASS")
    for row in rows:
        artifact = DOC_ROOT / row["candidate_artifact"]
        if not artifact.is_file() or sha_file(artifact) != row["candidate_sha256"]:
            raise PreparationError(f"SOURCE_CANDIDATE_SHA_MISMATCH:{row['path']}")
    return manifest, rows


def _snapshot_base(*, require_absent_candidate: bool) -> dict[str, Any]:
    exact_path(BASE_PLIST, "ACTIVE_SCHEDULER_PLIST")
    plist_raw = BASE_PLIST.read_bytes()
    plist = plistlib.loads(plist_raw)
    env = plist.get("EnvironmentVariables")
    args = plist.get("ProgramArguments")
    if not isinstance(env, dict) or not isinstance(args, list) or len(args) != 2:
        raise PreparationError("ACTIVE_SCHEDULER_PLIST_SHAPE_INVALID")
    if plist.get("Label") != "com.lexi.v35.scheduler":
        raise PreparationError("ACTIVE_SCHEDULER_LABEL_CHANGED")
    if args[0] != "/bin/bash" or Path(str(args[1])).name != "launch_v35_macos_scheduler.sh":
        raise PreparationError("ACTIVE_SCHEDULER_LAUNCHER_CHANGED")
    required = (
        "V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH",
        "V35_RELEASE_MANIFEST_SHA256", "V35_RUNTIME_ROOT", "V4_MANAGER_WORKBENCH_CONFIG_PATH",
    )
    if any(not isinstance(env.get(key), str) or not env[key] for key in required):
        raise PreparationError("ACTIVE_SCHEDULER_RELEASE_BINDING_INCOMPLETE")
    base_app = exact_path(Path(env["V35_APP_ROOT"]), "ACTIVE_APP_ROOT", directory=True)
    base_root = exact_path(base_app.parent, "ACTIVE_RELEASE_ROOT", directory=True)
    if Path(str(args[1])).resolve(strict=True) != base_app / "ops/launch_v35_macos_scheduler.sh":
        raise PreparationError("ACTIVE_LAUNCHER_APP_BINDING_MISMATCH")
    if Path(str(plist.get("WorkingDirectory", ""))).resolve(strict=True) != base_app:
        raise PreparationError("ACTIVE_WORKING_DIRECTORY_MISMATCH")
    if base_root.name != env["V35_RELEASE_ID"] or base_app != base_root / "app":
        raise PreparationError("ACTIVE_RELEASE_ID_PATH_MISMATCH")
    if require_absent_candidate and CANDIDATE_ROOT.exists():
        raise PreparationError("CANDIDATE_RELEASE_ROOT_ALREADY_EXISTS")
    manifest_path = exact_path(Path(env["V35_RELEASE_MANIFEST_PATH"]), "ACTIVE_RELEASE_MANIFEST")
    manifest_raw = manifest_path.read_bytes()
    manifest_sha = sha_bytes(manifest_raw)
    if manifest_sha != env["V35_RELEASE_MANIFEST_SHA256"] or manifest_path != base_root / "release-manifest.json":
        raise PreparationError("ACTIVE_RELEASE_MANIFEST_BINDING_MISMATCH")
    base_manifest = json.loads(manifest_raw)
    candidate = base_manifest.get("candidate", {})
    if (
        candidate.get("release_id") != env["V35_RELEASE_ID"]
        or candidate.get("app_root") != str(base_app)
        or candidate.get("root") != str(base_root)
    ):
        raise PreparationError("ACTIVE_RELEASE_MANIFEST_IDENTITY_MISMATCH")
    from ops.api_release_integration import inventory_digest, inventory_tree
    canonical_inventory = inventory_tree(base_app)
    if canonical_inventory != base_manifest.get("application_inventory", {}).get("entries"):
        raise PreparationError("ACTIVE_RELEASE_MANIFEST_INVENTORY_DRIFT")
    if inventory_digest(canonical_inventory) != base_manifest["application_inventory"].get("aggregate_sha256"):
        raise PreparationError("ACTIVE_RELEASE_MANIFEST_INVENTORY_SHA_MISMATCH")
    config_path = exact_path(Path(env["V4_MANAGER_WORKBENCH_CONFIG_PATH"]), "ACTIVE_MANAGER_CONFIG")
    config_raw = config_path.read_bytes()
    config = json.loads(config_raw)
    if not isinstance(config, dict) or config.get("scheduled_lanes") != EXPECTED_LANES:
        raise PreparationError("ACTIVE_MANAGER_CONFIG_LANES_CHANGED")
    process = _launchctl_snapshot(str(plist["Label"]))
    if process["state"] != "running":
        raise PreparationError("ACTIVE_SCHEDULER_NOT_RUNNING")
    safety = {
        key: env.get(key)
        for key in ("PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT", "production_allowed", "buy_gate_updated", "orders_sent")
        if key in env
    }
    if any(str(value).lower() not in {"false", "0"} for value in safety.values()):
        raise PreparationError("ACTIVE_SAFETY_FLAG_NOT_FALSE")
    runtime_root = Path(env["V35_RUNTIME_ROOT"])
    if not runtime_root.exists() or not runtime_root.is_dir():
        raise PreparationError("ACTIVE_RUNTIME_ROOT_UNAVAILABLE")
    python_bin = runtime_root / "venvs/v3.5-mac/bin/python"
    site_packages = runtime_root / "venvs/v3.5-mac/lib/python3.14/site-packages"
    if not python_bin.is_file() or not os.access(python_bin, os.X_OK) or not site_packages.is_dir():
        raise PreparationError("ACTIVE_SCHEDULER_PYTHON_UNAVAILABLE")
    if require_absent_candidate and CANDIDATE_ROOT.parent.resolve(strict=True) != CANDIDATE_ROOT.parent:
        raise PreparationError("CANDIDATE_RELEASE_PARENT_ALIAS")
    return {
        "plist_raw": plist_raw,
        "plist": plist,
        "plist_sha256": sha_bytes(plist_raw),
        "plist_mode": stat.S_IMODE(BASE_PLIST.stat().st_mode),
        "base_root": base_root,
        "base_app": base_app,
        "base_release_id": env["V35_RELEASE_ID"],
        "base_manifest_path": manifest_path,
        "base_manifest_sha256": manifest_sha,
        "base_manifest": base_manifest,
        "base_inventory": _physical_inventory(base_app),
        "base_application_inventory": canonical_inventory,
        "config_path": config_path,
        "config_sha256": sha_bytes(config_raw),
        "config": config,
        "process": process,
        "env": dict(env),
        "runtime_python": python_bin,
        "runtime_root": runtime_root,
        "runtime_root_resolved": runtime_root.resolve(strict=True),
        "site_packages": site_packages,
        "safety": safety,
    }


def _source_preimage_checks(base_app: Path, delta_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    observed: dict[str, dict[str, Any]] = {}
    for row in delta_rows:
        path = base_app / row["path"]
        if row["runtime_preimage_sha256"] is None:
            if path.exists() or path.is_symlink():
                raise PreparationError(f"DELTA_NEW_FILE_ALREADY_EXISTS:{row['path']}")
            mode = None
            before = None
        else:
            if not path.is_file() or sha_file(path) != row["runtime_preimage_sha256"]:
                raise PreparationError(f"DELTA_ACTIVE_PREIMAGE_MISMATCH:{row['path']}")
            mode = stat.S_IMODE(path.stat().st_mode)
            before = row["runtime_preimage_sha256"]
        candidate = DOC_ROOT / row["candidate_artifact"]
        observed[row["path"]] = {
            "before_sha256": before,
            "before_mode": mode,
            "candidate_sha256": row["candidate_sha256"],
            "candidate_mode": stat.S_IMODE(candidate.stat().st_mode),
        }
    return observed


def _run_import_probe(snapshot: dict[str, Any], candidate_app: Path) -> dict[str, Any]:
    env = dict(snapshot["env"])
    env.update({
        "V35_APP_ROOT": str(candidate_app),
        "PYTHONPATH": f"{candidate_app / 'upstreams'}:{candidate_app}:{snapshot['site_packages']}",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    manifest_path = CANDIDATE_ROOT / "release-manifest.json"
    manifest_sha = sha_file(manifest_path)
    env["V35_RELEASE_ID"] = RELEASE_ID
    env["V35_RELEASE_MANIFEST_PATH"] = str(manifest_path)
    env["V35_RELEASE_MANIFEST_SHA256"] = manifest_sha
    code = r'''import hashlib, importlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve(strict=True)
names = json.loads(sys.argv[2])
result = {"python": sys.executable, "version": sys.version.split()[0], "modules": {}}
for name in names:
    module = importlib.import_module(name)
    path = pathlib.Path(module.__file__).resolve(strict=True)
    path.relative_to(root)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result["modules"][name] = {"path": str(path), "sha256": digest}
print(json.dumps(result, sort_keys=True))
'''
    result = subprocess.run(
        [str(snapshot["runtime_python"]), "-S", "-c", code, str(candidate_app), json.dumps(list(MODULES))],
        cwd=candidate_app, env=env, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        # Do not expose arbitrary environment or interpreter output in a receipt.
        raise PreparationError(f"ACTUAL_RUNTIME_IMPORT_PROBE_FAILED:{result.returncode}:{result.stderr[-1200:]}")
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    if Path(payload.get("python", "")).resolve(strict=True) != snapshot["runtime_python"].resolve(strict=True):
        raise PreparationError("ACTUAL_RUNTIME_INTERPRETER_IDENTITY_MISMATCH")
    expected_module_paths = {
        "ops.run_v35_macos_scheduler_daemon": "ops/run_v35_macos_scheduler_daemon.py",
        "v4.manager_workbench.scheduler": "v4/manager_workbench/scheduler.py",
        "v4.manager_workbench.inputs.source_bindings": "v4/manager_workbench/inputs/source_bindings.py",
        "v4.manager_workbench.service": "v4/manager_workbench/service.py",
        "v4.manager_workbench.store": "v4/manager_workbench/store.py",
        "v4.manager_workbench.oversold_daily": "v4/manager_workbench/oversold_daily.py",
        "upstreams.v3_shared_data.shared_data.hk_daily_supplement": "upstreams/v3_shared_data/shared_data/hk_daily_supplement.py",
    }
    for name, relative in expected_module_paths.items():
        expected = candidate_app / relative
        record = payload["modules"].get(name)
        if record is None or Path(record["path"]) != expected or record["sha256"] != sha_file(expected):
            raise PreparationError(f"ACTUAL_RUNTIME_IMPORT_ROOT_MISMATCH:{name}")
    return payload


def _render_manifest(snapshot: dict[str, Any], delta: dict[str, Any], delta_rows: list[dict[str, Any]],
                     candidate_app: Path, candidate_inventory: list[dict[str, Any]],
                     canonical_inventory: list[dict[str, Any]], non_delta_digest: str,
                     non_delta_count: int, import_probe: dict[str, Any]) -> dict[str, Any]:
    patch_sha = sha_file(PATCH_PATH)
    records = []
    for row in delta_rows:
        relative = row["path"]
        base_record = next((item for item in snapshot["base_inventory"] if item["path"] == relative), None)
        cand_record = next((item for item in candidate_inventory if item["path"] == relative), None)
        if cand_record is None:
            raise PreparationError(f"CANDIDATE_DELTA_FILE_MISSING:{relative}")
        records.append({
            "path": relative,
            "change": row["change"],
            "before_sha256": base_record.get("sha256") if base_record else None,
            "before_mode": base_record.get("mode") if base_record else None,
            "after_sha256": cand_record.get("sha256"),
            "after_mode": cand_record.get("mode"),
            "source_candidate_sha256": row["candidate_sha256"],
            "patch_sha256": patch_sha,
        })
    app_entries = canonical_inventory
    from ops.api_release_integration import inventory_digest
    return {
        "schema_version": "v4.oversold_daily_scheduler_release_candidate.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_status": "PREPARED_FOR_INDEPENDENT_RUNTIME_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "role": "scheduler",
        "release_id": RELEASE_ID,
        "base": {
            "release_id": snapshot["base_release_id"],
            "root": str(snapshot["base_root"]),
            "app_root": str(snapshot["base_app"]),
            "manifest_path": str(snapshot["base_manifest_path"]),
            "manifest_sha256": snapshot["base_manifest_sha256"],
            "application_inventory_sha256": inventory_digest(snapshot["base_application_inventory"]),
            "physical_inventory_sha256": canonical_digest(snapshot["base_inventory"]),
        },
        "candidate": {
            "root": str(CANDIDATE_ROOT),
            "app_root": str(candidate_app),
            "release_id": RELEASE_ID,
            "manifest_path": str(CANDIDATE_ROOT / "release-manifest.json"),
            "manifest_self_hash_excluded": True,
            "staged_plist_path": str(CANDIDATE_ROOT / "config/com.lexi.v35.scheduler.plist"),
            "staged_plist_hash_is_in_preparation_receipt": True,
        },
        "source": {
            "active_plist_path": str(BASE_PLIST),
            "active_plist_preimage_sha256": snapshot["plist_sha256"],
            "active_plist_preimage_mode": f"{snapshot['plist_mode']:04o}",
            "active_process": snapshot["process"],
            "manager_config_path": str(snapshot["config_path"]),
            "manager_config_sha256": snapshot["config_sha256"],
            "manager_config_copied_or_changed": False,
            "scheduled_lanes": snapshot["config"].get("scheduled_lanes"),
            "source_review_path": str(SOURCE_REVIEW),
            "source_review_sha256": SOURCE_REVIEW_SHA256,
            "source_delta_manifest_path": str(DELTA_PATH),
            "source_delta_manifest_sha256": sha_file(DELTA_PATH),
            "source_delta_patch_sha256": patch_sha,
            "active_release_copied": True,
            "source_workspace_full_tree_copied": False,
            "runtime_state_copied": False,
        },
        "delta_entries": records,
        "application_inventory": {
            "entry_count": len(app_entries),
            "aggregate_sha256": inventory_digest(app_entries),
            "entries": app_entries,
            "rule": "existing API release application inventory; excludes generated __pycache__ bytes",
        },
        "physical_inventory": {
            "entry_count": len(candidate_inventory),
            "aggregate_sha256": canonical_digest(candidate_inventory),
            "entries": candidate_inventory,
            "rule": "all app files including generated bytecode, plus directories; excludes app root row",
        },
        "base_physical_inventory": {
            "entry_count": len(snapshot["base_inventory"]),
            "aggregate_sha256": canonical_digest(snapshot["base_inventory"]),
            "entries": snapshot["base_inventory"],
            "rule": "same physical rule as candidate inventory",
        },
        "non_delta_preservation": {
            "all_equal": True,
            "entry_count": non_delta_count,
            "aggregate_sha256": non_delta_digest,
            "excluded_delta_paths": list(DELTA_KEYS),
        },
        "actual_runtime_import_probe": import_probe,
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "other_lanes_and_schedule_parameters_changed": False,
        },
        "verification_gaps": [
            "candidate is not installed or activated",
            "no live TDX recovery or formal OVERSOLD run was performed",
            "API, UI and natural scheduled behavior remain unverified",
            "runtime release independent review and explicit activation authorization remain required",
        ],
    }


def _assert_active_cas(snapshot: dict[str, Any]) -> None:
    if sha_file(BASE_PLIST) != snapshot["plist_sha256"]:
        raise PreparationError("ACTIVE_SCHEDULER_PLIST_CAS_DRIFT")
    if sha_file(snapshot["config_path"]) != snapshot["config_sha256"]:
        raise PreparationError("ACTIVE_MANAGER_CONFIG_CAS_DRIFT")
    if sha_file(snapshot["base_manifest_path"]) != snapshot["base_manifest_sha256"]:
        raise PreparationError("ACTIVE_RELEASE_MANIFEST_CAS_DRIFT")
    from ops.api_release_integration import inventory_digest, inventory_tree
    if inventory_tree(snapshot["base_app"]) != snapshot["base_application_inventory"]:
        raise PreparationError("ACTIVE_BASE_APPLICATION_INVENTORY_CAS_DRIFT")
    if canonical_digest(_physical_inventory(snapshot["base_app"])) != canonical_digest(snapshot["base_inventory"]):
        raise PreparationError("ACTIVE_BASE_PHYSICAL_INVENTORY_CAS_DRIFT")
    if inventory_digest(snapshot["base_application_inventory"]) != snapshot["base_manifest"]["application_inventory"]["aggregate_sha256"]:
        raise PreparationError("ACTIVE_BASE_MANIFEST_INVENTORY_CAS_DRIFT")


def _prepare() -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT))
    from infrastructure.interprocess_lock import owned_interprocess_lock
    from ops.build_release_candidate_stage import _stage_scheduler_identity
    from ops.api_release_integration import inventory_digest, inventory_tree

    with ExitStack() as stack:
        leases = []
        for name in LOCK_NAMES:
            leases.append(stack.enter_context(owned_interprocess_lock(
                BASE_PLIST.with_name(name), timeout_seconds=3.0,
                timeout_message="SCHEDULER_RELEASE_LOCK_BUSY",
            )))
        snapshot = _snapshot_base(require_absent_candidate=True)
        delta, delta_rows = _load_delta()
        source_records = _source_preimage_checks(snapshot["base_app"], delta_rows)
        if not DELTA_PATH.is_file() or delta.get("patch", {}).get("path") != "runtime_exact_delta.patch":
            raise PreparationError("SOURCE_DELTA_IDENTITY_INVALID")

        # The original plist is retained byte-for-byte for a future exact rollback.
        if PREIMAGE_PATH.exists():
            if PREIMAGE_PATH.read_bytes() != snapshot["plist_raw"]:
                raise PreparationError("SAVED_ACTIVE_PLIST_PREIMAGE_CONFLICT")
        else:
            PREIMAGE_PATH.write_bytes(snapshot["plist_raw"])
            PREIMAGE_PATH.chmod(0o600)

        shutil.copytree(snapshot["base_root"], CANDIDATE_ROOT, copy_function=shutil.copy2, symlinks=True)
        candidate_app = CANDIDATE_ROOT / "app"
        patch_result = subprocess.run(
            ["patch", "-N", "-f", "-p1", "-i", str(PATCH_PATH)],
            cwd=candidate_app, capture_output=True, text=True, check=False,
        )
        if patch_result.returncode != 0:
            raise PreparationError(f"EXACT_DELTA_APPLY_FAILED:{patch_result.returncode}:{patch_result.stderr[-1200:]}")

        for row in delta_rows:
            path = candidate_app / row["path"]
            candidate_artifact = DOC_ROOT / row["candidate_artifact"]
            if not path.is_file() or sha_file(path) != row["candidate_sha256"]:
                raise PreparationError(f"EXACT_DELTA_OUTPUT_SHA_MISMATCH:{row['path']}")
            expected_mode = stat.S_IMODE(candidate_artifact.stat().st_mode)
            if row["runtime_preimage_sha256"] is not None:
                expected_mode = source_records[row["path"]]["before_mode"]
            os.chmod(path, expected_mode)
            if sha_file(path) != row["candidate_sha256"] or stat.S_IMODE(path.stat().st_mode) != expected_mode:
                raise PreparationError(f"EXACT_DELTA_OUTPUT_MODE_OR_SHA_MISMATCH:{row['path']}")

        base_rows = snapshot["base_inventory"]
        candidate_rows = _physical_inventory(candidate_app)
        base_map = {row["path"]: row for row in base_rows}
        candidate_map = {row["path"]: row for row in candidate_rows}
        changed = sorted(path for path in set(base_map) | set(candidate_map) if base_map.get(path) != candidate_map.get(path))
        if changed != sorted(DELTA_KEYS):
            raise PreparationError("CANDIDATE_APP_DELTA_SET_MISMATCH:" + ",".join(changed))
        base_non_delta = [row for row in base_rows if row["path"] not in DELTA_KEYS]
        candidate_non_delta = [row for row in candidate_rows if row["path"] not in DELTA_KEYS]
        if base_non_delta != candidate_non_delta:
            raise PreparationError("CANDIDATE_NON_DELTA_SHA_OR_MODE_DRIFT")
        non_delta_digest = canonical_digest(base_non_delta)
        canonical_candidate = inventory_tree(candidate_app)
        base_root_entries = {entry.name for entry in snapshot["base_root"].iterdir()}
        if base_root_entries != {"app", "release-manifest.json"}:
            raise PreparationError("ACTIVE_RELEASE_ROOT_HAS_UNEXPECTED_ENTRIES")
        if set(CANDIDATE_ROOT.iterdir()) != {candidate_app, CANDIDATE_ROOT / "release-manifest.json"}:
            raise PreparationError("COPIED_RELEASE_ROOT_HAS_UNEXPECTED_ENTRIES")
        if sha_file(snapshot["config_path"]) != snapshot["config_sha256"]:
            raise PreparationError("ACTIVE_MANAGER_CONFIG_CHANGED_DURING_PREPARATION")
        _assert_active_cas(snapshot)
        import_probe = _run_import_probe(snapshot, candidate_app)
        release_manifest = _render_manifest(
            snapshot, delta, delta_rows, candidate_app, candidate_rows,
            canonical_candidate, non_delta_digest, len(base_non_delta), import_probe,
        )
        manifest_path = CANDIDATE_ROOT / "release-manifest.json"
        manifest_mode = stat.S_IMODE(manifest_path.stat().st_mode)
        manifest_bytes = (json.dumps(release_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        manifest_path.write_bytes(manifest_bytes)
        os.chmod(manifest_path, manifest_mode)
        manifest_sha = sha_bytes(manifest_bytes)
        staged = _stage_scheduler_identity(
            source_plist=BASE_PLIST,
            candidate_root=CANDIDATE_ROOT,
            release_id=RELEASE_ID,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha,
        )
        staged_plist = Path(str(staged["path"]))
        if staged["missing_rebound_paths"]:
            raise PreparationError("CANDIDATE_PLIST_REBOUND_PATH_MISSING")
        staged_payload = plistlib.loads(staged_plist.read_bytes())
        _verify_staged_plist(snapshot, staged_payload, manifest_sha)
        _assert_active_cas(snapshot)
        from infrastructure.interprocess_lock import assert_owned_interprocess_lock
        # Check lock leases immediately before recording the prepared result.
        for lease, name in zip(leases, LOCK_NAMES):
            assert_owned_interprocess_lock(lease, BASE_PLIST.with_name(name))

        receipt = {
            "schema_version": "v4.oversold_daily_scheduler_release_preparation_receipt.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "PREPARED_NOT_ACTIVATED",
            "candidate_release_id": RELEASE_ID,
            "candidate_root": str(CANDIDATE_ROOT),
            "candidate_app_root": str(candidate_app),
            "candidate_release_manifest_path": str(manifest_path),
            "candidate_release_manifest_sha256": manifest_sha,
            "candidate_staged_plist_path": str(staged_plist),
            "candidate_staged_plist_sha256": sha_file(staged_plist),
            "candidate_application_inventory_sha256": inventory_digest(canonical_candidate),
            "candidate_physical_inventory_sha256": canonical_digest(candidate_rows),
            "base_release_root": str(snapshot["base_root"]),
            "base_release_id": snapshot["base_release_id"],
            "base_release_manifest_sha256": snapshot["base_manifest_sha256"],
            "base_plist_path": str(BASE_PLIST),
            "base_plist_preimage_sha256": snapshot["plist_sha256"],
            "base_plist_preimage_mode": f"{snapshot['plist_mode']:04o}",
            "base_plist_preimage_copy": str(PREIMAGE_PATH),
            "base_plist_preimage_copy_mode": "0600",
            "base_manager_config_path": str(snapshot["config_path"]),
            "base_manager_config_sha256": snapshot["config_sha256"],
            "base_scheduled_lanes": snapshot["config"].get("scheduled_lanes"),
            "base_running_process": snapshot["process"],
            "base_physical_inventory_sha256": canonical_digest(base_rows),
            "non_delta_entry_count": len(base_non_delta),
            "non_delta_inventory_sha256": non_delta_digest,
            "exact_delta_paths": list(DELTA_KEYS),
            "source_delta_patch_sha256": sha_file(PATCH_PATH),
            "source_review_path": str(SOURCE_REVIEW),
            "source_review_sha256": SOURCE_REVIEW_SHA256,
            "source_review_status": "PASS_CANDIDATE; P2 repair reviewed; source candidate remains NOT_DEPLOYED",
            "actual_runtime_import_probe": import_probe,
            "scheduler_release_locks": [str(BASE_PLIST.with_name(name)) for name in LOCK_NAMES],
            "active_plist_changed": False,
            "active_config_changed": False,
            "launchctl_called_for_mutation": False,
            "runtime_installed": False,
            "activation_status": "NOT_ACTIVATED",
            "deployment_status": "CANNOT_CONFIRM",
        }
        RECEIPT_PATH.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        RECEIPT_PATH.chmod(0o600)
        _write_markdown_receipt(receipt, staged)
        return receipt


def _resume_existing_candidate() -> dict[str, Any]:
    """Record a receipt for the already-built candidate without writing into it."""
    sys.path.insert(0, str(REPO_ROOT))
    from infrastructure.interprocess_lock import owned_interprocess_lock, assert_owned_interprocess_lock
    from ops.api_release_integration import inventory_digest, inventory_tree

    with ExitStack() as stack:
        leases = []
        for name in LOCK_NAMES:
            leases.append(stack.enter_context(owned_interprocess_lock(
                BASE_PLIST.with_name(name), timeout_seconds=3.0,
                timeout_message="SCHEDULER_RELEASE_LOCK_BUSY",
            )))
        snapshot = _snapshot_base(require_absent_candidate=False)
        delta, delta_rows = _load_delta()
        if not PREIMAGE_PATH.is_file() or PREIMAGE_PATH.read_bytes() != snapshot["plist_raw"]:
            raise PreparationError("SAVED_ACTIVE_PLIST_PREIMAGE_MISMATCH")
        if stat.S_IMODE(PREIMAGE_PATH.stat().st_mode) != 0o600:
            raise PreparationError("SAVED_ACTIVE_PLIST_PREIMAGE_MODE_MISMATCH")
        if CANDIDATE_ROOT.is_symlink() or not CANDIDATE_ROOT.is_dir() or CANDIDATE_ROOT.resolve(strict=True) != CANDIDATE_ROOT:
            raise PreparationError("PARTIAL_CANDIDATE_ROOT_UNAVAILABLE_OR_ALIAS")
        candidate_app = CANDIDATE_ROOT / "app"
        manifest_path = CANDIDATE_ROOT / "release-manifest.json"
        staged_path = CANDIDATE_ROOT / "config/com.lexi.v35.scheduler.plist"
        if set(CANDIDATE_ROOT.iterdir()) != {candidate_app, manifest_path, CANDIDATE_ROOT / "config"}:
            raise PreparationError("PARTIAL_CANDIDATE_ROOT_ENTRY_SET_MISMATCH")
        if (candidate_app.is_symlink() or not candidate_app.is_dir()
                or manifest_path.is_symlink() or not manifest_path.is_file()
                or staged_path.is_symlink() or not staged_path.is_file()):
            raise PreparationError("PARTIAL_CANDIDATE_REQUIRED_OUTPUT_MISSING")
        if candidate_app.resolve(strict=True) != candidate_app or manifest_path.resolve(strict=True) != manifest_path:
            raise PreparationError("PARTIAL_CANDIDATE_OUTPUT_ALIAS")
        if staged_path.parent.is_symlink() or staged_path.parent.resolve(strict=True) != staged_path.parent:
            raise PreparationError("PARTIAL_CANDIDATE_CONFIG_DIRECTORY_ALIAS")

        source_records = _source_preimage_checks(snapshot["base_app"], delta_rows)
        base_rows = snapshot["base_inventory"]
        candidate_rows = _physical_inventory(candidate_app)
        base_map = {row["path"]: row for row in base_rows}
        candidate_map = {row["path"]: row for row in candidate_rows}
        changed = sorted(path for path in set(base_map) | set(candidate_map) if base_map.get(path) != candidate_map.get(path))
        if changed != sorted(DELTA_KEYS):
            raise PreparationError("PARTIAL_CANDIDATE_APP_DELTA_SET_MISMATCH")
        non_delta = [row for row in base_rows if row["path"] not in DELTA_KEYS]
        if non_delta != [row for row in candidate_rows if row["path"] not in DELTA_KEYS]:
            raise PreparationError("PARTIAL_CANDIDATE_NON_DELTA_SHA_OR_MODE_DRIFT")
        for row in delta_rows:
            actual = candidate_map.get(row["path"])
            if actual is None or actual.get("sha256") != row["candidate_sha256"]:
                raise PreparationError(f"PARTIAL_CANDIDATE_DELTA_SHA_MISMATCH:{row['path']}")
            expected_mode = source_records[row["path"]]["before_mode"]
            if expected_mode is None:
                expected_mode = source_records[row["path"]]["candidate_mode"]
            if actual.get("mode") != f"{expected_mode:04o}":
                raise PreparationError(f"PARTIAL_CANDIDATE_DELTA_MODE_MISMATCH:{row['path']}")

        manifest = safe_json(manifest_path)
        canonical_candidate = inventory_tree(candidate_app)
        from ops.api_release_integration import inventory_digest
        patch_sha = sha_file(PATCH_PATH)
        if (manifest.get("candidate_status") != "PREPARED_FOR_INDEPENDENT_RUNTIME_REVIEW"
                or manifest.get("activation_status") != "NOT_ACTIVATED"
                or manifest.get("release_id") != RELEASE_ID
                or manifest.get("candidate", {}).get("root") != str(CANDIDATE_ROOT)
                or manifest.get("candidate", {}).get("app_root") != str(candidate_app)
                or manifest.get("candidate", {}).get("manifest_path") != str(manifest_path)
                or manifest.get("candidate", {}).get("staged_plist_path") != str(staged_path)):
            raise PreparationError("PARTIAL_CANDIDATE_MANIFEST_IDENTITY_MISMATCH")
        manifest_base = manifest.get("base", {})
        if (manifest_base.get("release_id") != snapshot["base_release_id"]
                or manifest_base.get("root") != str(snapshot["base_root"])
                or manifest_base.get("app_root") != str(snapshot["base_app"])
                or manifest_base.get("manifest_sha256") != snapshot["base_manifest_sha256"]
                or manifest_base.get("physical_inventory_sha256") != canonical_digest(base_rows)):
            raise PreparationError("PARTIAL_CANDIDATE_MANIFEST_BASE_MISMATCH")
        physical = manifest.get("physical_inventory", {})
        if (physical.get("entries") != candidate_rows or physical.get("entry_count") != len(candidate_rows)
                or physical.get("aggregate_sha256") != canonical_digest(candidate_rows)):
            raise PreparationError("PARTIAL_CANDIDATE_MANIFEST_PHYSICAL_INVENTORY_MISMATCH")
        base_physical = manifest.get("base_physical_inventory", {})
        if (base_physical.get("entries") != base_rows or base_physical.get("entry_count") != len(base_rows)
                or base_physical.get("aggregate_sha256") != canonical_digest(base_rows)):
            raise PreparationError("PARTIAL_CANDIDATE_MANIFEST_BASE_INVENTORY_MISMATCH")
        app_inventory = manifest.get("application_inventory", {})
        if (app_inventory.get("entries") != canonical_candidate
                or app_inventory.get("entry_count") != len(canonical_candidate)
                or app_inventory.get("aggregate_sha256") != inventory_digest(canonical_candidate)):
            raise PreparationError("PARTIAL_CANDIDATE_MANIFEST_APPLICATION_INVENTORY_MISMATCH")
        if (manifest.get("non_delta_preservation", {}).get("all_equal") is not True
                or manifest.get("non_delta_preservation", {}).get("entry_count") != len(non_delta)
                or manifest.get("non_delta_preservation", {}).get("aggregate_sha256") != canonical_digest(non_delta)):
            raise PreparationError("PARTIAL_CANDIDATE_MANIFEST_NON_DELTA_MISMATCH")
        source_manifest = manifest.get("source", {})
        if (source_manifest.get("active_plist_path") != str(BASE_PLIST)
                or source_manifest.get("active_plist_preimage_sha256") != snapshot["plist_sha256"]
                or source_manifest.get("active_plist_preimage_mode") != f"{snapshot['plist_mode']:04o}"
                or source_manifest.get("manager_config_path") != str(snapshot["config_path"])
                or source_manifest.get("manager_config_sha256") != snapshot["config_sha256"]
                or source_manifest.get("scheduled_lanes") != EXPECTED_LANES
                or source_manifest.get("source_review_path") != str(SOURCE_REVIEW)
                or source_manifest.get("source_review_sha256") != SOURCE_REVIEW_SHA256
                or source_manifest.get("source_delta_manifest_sha256") != sha_file(DELTA_PATH)
                or source_manifest.get("source_delta_patch_sha256") != patch_sha
                or source_manifest.get("manager_config_copied_or_changed") is not False
                or source_manifest.get("source_workspace_full_tree_copied") is not False
                or source_manifest.get("runtime_state_copied") is not False):
            raise PreparationError("PARTIAL_CANDIDATE_MANIFEST_SOURCE_BINDING_MISMATCH")
        expected_delta_records = []
        for row in delta_rows:
            base_record = base_map.get(row["path"])
            candidate_record = candidate_map[row["path"]]
            expected_delta_records.append({
                "path": row["path"],
                "change": row["change"],
                "before_sha256": base_record.get("sha256") if base_record else None,
                "before_mode": base_record.get("mode") if base_record else None,
                "after_sha256": candidate_record.get("sha256"),
                "after_mode": candidate_record.get("mode"),
                "source_candidate_sha256": row["candidate_sha256"],
                "patch_sha256": patch_sha,
            })
        if manifest.get("delta_entries") != expected_delta_records:
            raise PreparationError("PARTIAL_CANDIDATE_MANIFEST_DELTA_MISMATCH")

        manifest_sha = sha_file(manifest_path)
        import_probe = _run_import_probe(snapshot, candidate_app)
        staged_payload = plistlib.loads(staged_path.read_bytes())
        _verify_staged_plist(snapshot, staged_payload, manifest_sha)
        if manifest.get("actual_runtime_import_probe", {}).get("modules") != import_probe.get("modules"):
            raise PreparationError("PARTIAL_CANDIDATE_MANIFEST_RUNTIME_PROBE_MISMATCH")
        _assert_active_cas(snapshot)
        for lease, name in zip(leases, LOCK_NAMES):
            assert_owned_interprocess_lock(lease, BASE_PLIST.with_name(name))

        receipt = {
            "schema_version": "v4.oversold_daily_scheduler_release_preparation_receipt.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "PREPARED_NOT_ACTIVATED",
            "candidate_release_id": RELEASE_ID,
            "candidate_root": str(CANDIDATE_ROOT),
            "candidate_app_root": str(candidate_app),
            "candidate_release_manifest_path": str(manifest_path),
            "candidate_release_manifest_sha256": manifest_sha,
            "candidate_staged_plist_path": str(staged_path),
            "candidate_staged_plist_sha256": sha_file(staged_path),
            "candidate_application_inventory_sha256": inventory_digest(canonical_candidate),
            "candidate_physical_inventory_sha256": canonical_digest(candidate_rows),
            "base_release_root": str(snapshot["base_root"]),
            "base_release_id": snapshot["base_release_id"],
            "base_release_manifest_sha256": snapshot["base_manifest_sha256"],
            "base_plist_path": str(BASE_PLIST),
            "base_plist_preimage_sha256": snapshot["plist_sha256"],
            "base_plist_preimage_mode": f"{snapshot['plist_mode']:04o}",
            "base_plist_preimage_copy": str(PREIMAGE_PATH),
            "base_plist_preimage_copy_mode": "0600",
            "base_manager_config_path": str(snapshot["config_path"]),
            "base_manager_config_sha256": snapshot["config_sha256"],
            "base_scheduled_lanes": snapshot["config"].get("scheduled_lanes"),
            "base_running_process": snapshot["process"],
            "base_physical_inventory_sha256": canonical_digest(base_rows),
            "non_delta_entry_count": len(non_delta),
            "non_delta_inventory_sha256": canonical_digest(non_delta),
            "exact_delta_paths": list(DELTA_KEYS),
            "source_delta_patch_sha256": patch_sha,
            "source_review_path": str(SOURCE_REVIEW),
            "source_review_sha256": SOURCE_REVIEW_SHA256,
            "source_review_status": "PASS_CANDIDATE; P2 repair reviewed; source candidate remains NOT_DEPLOYED",
            "actual_runtime_import_probe": import_probe,
            "scheduler_release_locks": [str(BASE_PLIST.with_name(name)) for name in LOCK_NAMES],
            "candidate_resume_validation": "existing candidate outputs verified in place; no candidate file rewritten",
            "active_plist_changed": False,
            "active_config_changed": False,
            "launchctl_called_for_mutation": False,
            "runtime_installed": False,
            "activation_status": "NOT_ACTIVATED",
            "deployment_status": "CANNOT_CONFIRM",
        }
        RECEIPT_PATH.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        RECEIPT_PATH.chmod(0o600)
        _write_markdown_receipt(receipt, staged_payload)
        return receipt


def _verify_staged_plist(snapshot: dict[str, Any], staged: dict[str, Any], manifest_sha: str) -> None:
    source = snapshot["plist"]
    if staged.get("Label") != source.get("Label"):
        raise PreparationError("CANDIDATE_PLIST_LABEL_CHANGED")
    source_env = source["EnvironmentVariables"]
    candidate_env = staged.get("EnvironmentVariables")
    if not isinstance(candidate_env, dict):
        raise PreparationError("CANDIDATE_PLIST_ENV_INVALID")
    expected_values = {
        "V35_APP_ROOT": str(CANDIDATE_ROOT / "app"),
        "V35_RELEASE_ID": RELEASE_ID,
        "V35_RELEASE_MANIFEST_PATH": str(CANDIDATE_ROOT / "release-manifest.json"),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
        "PYTHONPATH": f"{CANDIDATE_ROOT / 'app' / 'upstreams'}:{CANDIDATE_ROOT / 'app'}",
    }
    changed_keys = {key for key in set(source_env) | set(candidate_env) if source_env.get(key) != candidate_env.get(key)}
    if changed_keys != set(expected_values):
        raise PreparationError("CANDIDATE_PLIST_ENV_CHANGE_SET_MISMATCH:" + ",".join(sorted(changed_keys)))
    for key, expected in expected_values.items():
        if candidate_env.get(key) != expected:
            raise PreparationError(f"CANDIDATE_PLIST_SELECTOR_MISMATCH:{key}")
    for key, value in candidate_env.items():
        if key.lower() in {"production_allowed", "buy_gate_updated", "orders_sent"} and str(value).lower() not in {"false", "0"}:
            raise PreparationError("CANDIDATE_PLIST_SAFETY_FLAG_NOT_FALSE")
    expected_launcher = str(CANDIDATE_ROOT / "app/ops/launch_v35_macos_scheduler.sh")
    if staged.get("ProgramArguments") != ["/bin/bash", expected_launcher]:
        raise PreparationError("CANDIDATE_PLIST_PROGRAM_ARGUMENTS_MISMATCH")
    if staged.get("WorkingDirectory") != str(CANDIDATE_ROOT / "app"):
        raise PreparationError("CANDIDATE_PLIST_WORKING_DIRECTORY_MISMATCH")
    for key in ("KeepAlive", "RunAtLoad"):
        if staged.get(key) != source.get(key):
            raise PreparationError(f"CANDIDATE_PLIST_LAUNCH_POLICY_CHANGED:{key}")
    source_projection = deepcopy(source)
    candidate_projection = deepcopy(staged)
    candidate_projection["EnvironmentVariables"] = dict(candidate_env)
    for key in expected_values:
        candidate_projection["EnvironmentVariables"][key] = source_env.get(key)
    source_projection["ProgramArguments"] = staged.get("ProgramArguments")
    source_projection["WorkingDirectory"] = staged.get("WorkingDirectory")
    if candidate_projection != source_projection:
        raise PreparationError("CANDIDATE_PLIST_NON_SELECTOR_FIELD_CHANGED")


def _write_markdown_receipt(receipt: dict[str, Any], staged: dict[str, Any]) -> None:
    lines = [
        "# OVERSOLD scheduler release preparation",
        "",
        "Status: `PREPARED_NOT_ACTIVATED`; runtime installation and launchd activation were not performed.",
        "",
        f"Candidate release: `{receipt['candidate_release_id']}` at `{receipt['candidate_root']}`.",
        f"Candidate release-manifest SHA-256: `{receipt['candidate_release_manifest_sha256']}`.",
        f"Candidate staged plist SHA-256: `{receipt['candidate_staged_plist_sha256']}`.",
        f"Active scheduler plist preimage SHA-256: `{receipt['base_plist_preimage_sha256']}`.",
        f"Active manager config SHA-256: `{receipt['base_manager_config_sha256']}`; the existing config remains the binding, with scheduled lanes `{receipt['base_scheduled_lanes']}`.",
        f"Base app physical inventory SHA-256: `{receipt['base_physical_inventory_sha256']}`; candidate app physical inventory SHA-256: `{receipt['candidate_physical_inventory_sha256']}`.",
        f"Non-delta entries preserved: `{receipt['non_delta_entry_count']}`; inventory SHA-256 `{receipt['non_delta_inventory_sha256']}`.",
        "",
        "The candidate app was copied from the release selected by the fresh LaunchAgent plist. The recorded six-file patch was applied to that copy; complete base and candidate SHA/mode inventories are in the candidate `release-manifest.json`. The staged LaunchAgent changes only the release selectors (`V35_APP_ROOT`, release id/manifest path/hash, `PYTHONPATH`), `ProgramArguments`, and `WorkingDirectory`; manager config, external roots, schedule, KeepAlive/RunAtLoad, and safety flags remain the same.",
        "",
        f"The actual scheduler interpreter `{receipt['actual_runtime_import_probe']['python']}` imported the daemon and all six candidate modules from the candidate app root. Detailed module paths and SHAs are in the machine receipt.",
        "",
        f"Independent source review: R2 PASS_CANDIDATE, source review SHA-256 `{receipt['source_review_sha256']}`. This review did not approve activation.",
        "",
        "Activation must remain blocked until a separate runtime-release review and explicit authorization are recorded. The prepared activation helper waits for the old PID to exit, the launchd label to disappear, and a settle interval before bootstrapping the candidate; rollback is CAS-bound to the exact candidate plist and restores the saved byte-for-byte active preimage.",
        "",
        "The no-action activation, rollback, and recovery plans are in `SCHEDULER_CUTOVER_PLAN.json`. `activate_scheduler_release.py` and `rollback_scheduler_release.py` print `PREPARED_ONLY` unless their explicit action flag is supplied; activation also requires a separate runtime review receipt bound to the candidate-manifest SHA and an authorization reference. The recovery helper's default `--plan` was run without service imports, network access, or a formal run. Its future `--run` path is limited to the existing `oversold_daily_20261015_20261016` cursor, requires the target to remain the current Hong Kong date, uses the actual current time, and uses the existing exact-date owner/cache path. Actual per-security cache hits remain `CANNOT_CONFIRM` until row-level capture-record readback; no existing plan or manual work is deleted.",
        "",
        "Runtime review receipt contract for the activation helper: JSON schema `v4.oversold_daily_scheduler_runtime_review.v1`, `status=PASS_RUNTIME_RELEASE`, `behavior_verified=PASS`, `candidate_release_manifest_sha256` equal to the candidate SHA above, `writer_identity=oversold_daily_writer`, and a distinct non-empty `reviewer_identity`.",
        "",
        "`CANNOT_CONFIRM`: the current active scheduler process still runs the base release; no candidate process was started. No live TDX refresh, formal scheduled recovery, API/UI readback, or natural slot was performed. The import probe establishes only that the configured scheduler interpreter resolves the frozen modules from the isolated candidate.",
        "",
        "Research safety remains `RESEARCH_ONLY=true`, `PRODUCTION_ALLOWED=false`, `BUY_GATE_UPDATED=false`, `ORDERS_SENT=false`.",
    ]
    path = DOC_ROOT / "RUNTIME_PREPARED_RECEIPT.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _check() -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT))
    receipt = safe_json(RECEIPT_PATH)
    if receipt.get("status") != "PREPARED_NOT_ACTIVATED":
        raise PreparationError("PREPARATION_RECEIPT_STATUS_INVALID")
    snapshot = _snapshot_base(require_absent_candidate=False)
    if snapshot["plist_sha256"] != receipt.get("base_plist_preimage_sha256"):
        raise PreparationError("ACTIVE_SCHEDULER_PLIST_CAS_DRIFT")
    if snapshot["config_sha256"] != receipt.get("base_manager_config_sha256"):
        raise PreparationError("ACTIVE_MANAGER_CONFIG_CAS_DRIFT")
    if snapshot["base_manifest_sha256"] != receipt.get("base_release_manifest_sha256"):
        raise PreparationError("ACTIVE_BASE_MANIFEST_CAS_DRIFT")
    if not PREIMAGE_PATH.is_file() or PREIMAGE_PATH.read_bytes() != snapshot["plist_raw"]:
        raise PreparationError("SAVED_ACTIVE_PLIST_PREIMAGE_MISMATCH")
    if stat.S_IMODE(PREIMAGE_PATH.stat().st_mode) != 0o600:
        raise PreparationError("SAVED_ACTIVE_PLIST_PREIMAGE_MODE_MISMATCH")
    if canonical_digest(snapshot["base_inventory"]) != receipt.get("base_physical_inventory_sha256"):
        raise PreparationError("ACTIVE_BASE_INVENTORY_CAS_DRIFT")
    if not CANDIDATE_ROOT.is_dir() or CANDIDATE_ROOT.resolve(strict=True) != CANDIDATE_ROOT:
        raise PreparationError("CANDIDATE_ROOT_UNAVAILABLE_OR_ALIAS")
    manifest_path = CANDIDATE_ROOT / "release-manifest.json"
    staged_path = CANDIDATE_ROOT / "config/com.lexi.v35.scheduler.plist"
    if sha_file(manifest_path) != receipt.get("candidate_release_manifest_sha256"):
        raise PreparationError("CANDIDATE_RELEASE_MANIFEST_SHA_MISMATCH")
    if sha_file(staged_path) != receipt.get("candidate_staged_plist_sha256"):
        raise PreparationError("CANDIDATE_STAGED_PLIST_SHA_MISMATCH")
    delta, delta_rows = _load_delta()
    base_app = snapshot["base_app"]
    candidate_app = CANDIDATE_ROOT / "app"
    source_records = _source_preimage_checks(base_app, delta_rows)
    for row in delta_rows:
        candidate = candidate_app / row["path"]
        if not candidate.is_file() or sha_file(candidate) != row["candidate_sha256"]:
            raise PreparationError(f"CANDIDATE_DELTA_SHA_MISMATCH:{row['path']}")
    base_rows = snapshot["base_inventory"]
    candidate_rows = _physical_inventory(candidate_app)
    base_map = {row["path"]: row for row in base_rows}
    candidate_map = {row["path"]: row for row in candidate_rows}
    changed = sorted(path for path in set(base_map) | set(candidate_map) if base_map.get(path) != candidate_map.get(path))
    if changed != sorted(DELTA_KEYS):
        raise PreparationError("CANDIDATE_APP_DELTA_SET_DRIFT")
    non_delta = [row for row in base_rows if row["path"] not in DELTA_KEYS]
    if non_delta != [row for row in candidate_rows if row["path"] not in DELTA_KEYS]:
        raise PreparationError("CANDIDATE_NON_DELTA_SHA_OR_MODE_DRIFT")
    manifest = safe_json(manifest_path)
    if manifest.get("physical_inventory", {}).get("entries") != candidate_rows:
        raise PreparationError("CANDIDATE_MANIFEST_PHYSICAL_INVENTORY_MISMATCH")
    if manifest.get("base_physical_inventory", {}).get("entries") != base_rows:
        raise PreparationError("CANDIDATE_MANIFEST_BASE_INVENTORY_MISMATCH")
    import_probe = _run_import_probe(snapshot, candidate_app)
    staged_payload = plistlib.loads(staged_path.read_bytes())
    _verify_staged_plist(snapshot, staged_payload, sha_file(manifest_path))
    print(json.dumps({
        "status": "SCHEDULER_RELEASE_PREPARED_CHECK_PASS",
        "activation_status": "NOT_ACTIVATED",
        "candidate_release_id": RELEASE_ID,
        "candidate_manifest_sha256": sha_file(manifest_path),
        "candidate_plist_sha256": sha_file(staged_path),
        "active_plist_sha256": snapshot["plist_sha256"],
        "active_manager_config_sha256": snapshot["config_sha256"],
        "base_process": snapshot["process"],
        "runtime_python": str(snapshot["runtime_python"]),
        "imported_module_count": len(import_probe["modules"]),
        "changed_paths": changed,
        "non_delta_entry_count": len(non_delta),
        "non_delta_inventory_sha256": canonical_digest(non_delta),
        "active_plist_changed": False,
        "active_config_changed": False,
        "launchctl_called_for_mutation": False,
    }, ensure_ascii=False, sort_keys=True))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true", help="create the isolated release and receipts")
    group.add_argument("--resume-existing", action="store_true", help="verify an existing candidate in place and record its receipt")
    group.add_argument("--check", action="store_true", help="read-only CAS and inventory check")
    args = parser.parse_args()
    try:
        if args.prepare:
            receipt = _prepare()
            print(json.dumps({
                "status": receipt["status"],
                "candidate_release_id": receipt["candidate_release_id"],
                "candidate_manifest_sha256": receipt["candidate_release_manifest_sha256"],
                "candidate_plist_sha256": receipt["candidate_staged_plist_sha256"],
                "active_plist_changed": False,
                "active_config_changed": False,
                "launchctl_called_for_mutation": False,
            }, ensure_ascii=False, sort_keys=True))
        elif args.resume_existing:
            receipt = _resume_existing_candidate()
            print(json.dumps({
                "status": receipt["status"],
                "candidate_release_id": receipt["candidate_release_id"],
                "candidate_manifest_sha256": receipt["candidate_release_manifest_sha256"],
                "candidate_plist_sha256": receipt["candidate_staged_plist_sha256"],
                "candidate_resume_validation": receipt["candidate_resume_validation"],
                "active_plist_changed": False,
                "active_config_changed": False,
                "launchctl_called_for_mutation": False,
            }, ensure_ascii=False, sort_keys=True))
        else:
            _check()
    except (PreparationError, OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"PREPARATION_BLOCKED: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
