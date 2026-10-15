#!/usr/bin/env python3
"""Prepare an isolated cache-first scheduler release; this tool never activates it."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
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
from typing import Any

DOC_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DOC_ROOT.parents[2]
APP_SUPPORT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local")
ACTIVE_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
CANDIDATE_ROOT = APP_SUPPORT / "releases/oversold-daily-cache-20261016-r1"
CANDIDATE_APP = CANDIDATE_ROOT / "app"
PREIMAGE_PATH = DOC_ROOT / "active_scheduler_plist_cache.preimage"
DELTA_PATH = DOC_ROOT / "runtime_exact_delta_r4.json"
PATCH_PATH = DOC_ROOT / "runtime_exact_delta_r4.patch"
SOURCE_REVIEW_PATH = DOC_ROOT / "CACHE_FIRST_INDEPENDENT_REVIEW.md"
SOURCE_REVIEW_SHA256 = "fcd4541507fd76baa3b49de27d150f01f902e3eb611a78c6a9504786d617cab8"
BASE_RELEASE_ID = "zsxq-pdf-ocr-scheduler-20261016-r4"
BASE_MANIFEST_SHA256 = "4710696eb61e60ac5dbd1ea56aa2e7a3762d9c1f9170d206b4dc0beac4769e91"
CONFIG_PATH_EXPECTED = APP_SUPPORT / "config/manager-workbench-v7.json"
EXPECTED_LANES = ["US_MAPPING", "OVERSOLD"]
LOCK_NAMES = (".com.lexi.v35.scheduler.release.lock", "com.lexi.v35.scheduler.release.lock")
RECEIPT_PATH = DOC_ROOT / "scheduler_cache_release_preparation_receipt.json"
PLAN_PATH = DOC_ROOT / "SCHEDULER_CACHE_CUTOVER_PLAN.json"
BINDING_PATH = DOC_ROOT / "scheduler_cache_release_binding.json"
MARKDOWN_RECEIPT_PATH = DOC_ROOT / "RUNTIME_CACHE_PREPARED_RECEIPT.md"
RUNTIME_REVIEW_SCHEMA = "v4.oversold_daily_scheduler_runtime_review.v1"
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
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def canonical_digest(rows: list[dict[str, Any]]) -> str:
    return sha_bytes(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreparationError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def exact(path: Path, label: str, *, directory: bool = False) -> Path:
    if path.is_symlink() or path.resolve(strict=True) != path:
        raise PreparationError(f"{label}_ALIAS_OR_SYMLINK")
    if directory and not path.is_dir():
        raise PreparationError(f"{label}_NOT_DIRECTORY")
    if not directory and not path.is_file():
        raise PreparationError(f"{label}_NOT_FILE")
    return path


def physical_inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        mode = f"{stat.S_IMODE(info.st_mode):04o}"
        if stat.S_ISDIR(info.st_mode):
            rows.append({"kind": "directory", "mode": mode, "path": relative})
        elif stat.S_ISREG(info.st_mode):
            rows.append({"kind": "file", "mode": mode, "path": relative, "sha256": sha_file(path), "size": info.st_size})
        elif stat.S_ISLNK(info.st_mode):
            rows.append({"kind": "symlink", "mode": mode, "path": relative, "target": os.readlink(path)})
        else:
            raise PreparationError(f"UNSUPPORTED_FILESYSTEM_ENTRY:{relative}")
    return rows


def launchd_snapshot(label: str) -> dict[str, Any]:
    result = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if result.returncode != 0:
        raise PreparationError(f"LAUNCHD_LABEL_NOT_LOADED:{result.returncode}")
    value: dict[str, Any] = {"label": label, "returncode": result.returncode}
    for key, pattern in {
        "plist_path": r"^\s*path = ([^\r\n]+)",
        "program": r"^\s*program = ([^\r\n]+)",
        "working_directory": r"^\s*working directory = ([^\r\n]+)",
        "state": r"^\s*state = ([^\r\n]+)",
        "pid": r"^\s*pid = (\d+)",
    }.items():
        found = re.search(pattern, result.stdout, re.MULTILINE)
        value[key] = (int(found.group(1)) if key == "pid" else found.group(1).strip()) if found else None
    if value.get("state") != "running" or value.get("pid") is None:
        raise PreparationError("ACTIVE_SCHEDULER_NOT_RUNNING")
    return value


def active_snapshot(*, require_absent_candidate: bool) -> dict[str, Any]:
    exact(ACTIVE_PLIST, "ACTIVE_PLIST")
    plist_raw = ACTIVE_PLIST.read_bytes()
    plist = plistlib.loads(plist_raw)
    env = plist.get("EnvironmentVariables")
    args = plist.get("ProgramArguments")
    if (
        not isinstance(env, dict) or not isinstance(args, list) or len(args) != 2
        or plist.get("Label") != "com.lexi.v35.scheduler"
        or args[0] != "/bin/bash" or Path(str(args[1])).name != "launch_v35_macos_scheduler.sh"
    ):
        raise PreparationError("ACTIVE_SCHEDULER_PLIST_SHAPE_MISMATCH")
    required = (
        "V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH",
        "V35_RELEASE_MANIFEST_SHA256", "V35_RUNTIME_ROOT", "V4_MANAGER_WORKBENCH_CONFIG_PATH",
    )
    if any(not isinstance(env.get(key), str) or not env[key] for key in required):
        raise PreparationError("ACTIVE_SCHEDULER_SELECTOR_MISSING")
    app = exact(Path(env["V35_APP_ROOT"]), "ACTIVE_APP_ROOT", directory=True)
    root = exact(app.parent, "ACTIVE_RELEASE_ROOT", directory=True)
    manifest_path = exact(Path(env["V35_RELEASE_MANIFEST_PATH"]), "ACTIVE_MANIFEST")
    if (
        root.name != BASE_RELEASE_ID or app != root / "app" or env["V35_RELEASE_ID"] != BASE_RELEASE_ID
        or Path(str(args[1])).resolve(strict=True) != app / "ops/launch_v35_macos_scheduler.sh"
        or Path(str(plist.get("WorkingDirectory", ""))).resolve(strict=True) != app
        or manifest_path != root / "release-manifest.json"
    ):
        raise PreparationError("ACTIVE_R4_SELECTOR_MISMATCH")
    manifest_raw = manifest_path.read_bytes()
    manifest_sha = sha_bytes(manifest_raw)
    if manifest_sha != BASE_MANIFEST_SHA256 or env["V35_RELEASE_MANIFEST_SHA256"] != manifest_sha:
        raise PreparationError("ACTIVE_R4_MANIFEST_SHA_MISMATCH")
    manifest = json.loads(manifest_raw)
    identity = manifest.get("candidate", {})
    if identity.get("release_id") != BASE_RELEASE_ID or identity.get("root") != str(root) or identity.get("app_root") != str(app):
        raise PreparationError("ACTIVE_R4_MANIFEST_IDENTITY_MISMATCH")
    from ops.api_release_integration import inventory_digest, inventory_tree
    app_inventory = inventory_tree(app)
    declared = manifest.get("application_inventory", {})
    if app_inventory != declared.get("entries") or inventory_digest(app_inventory) != declared.get("aggregate_sha256"):
        raise PreparationError("ACTIVE_R4_APP_INVENTORY_MISMATCH")
    config_path = exact(Path(env["V4_MANAGER_WORKBENCH_CONFIG_PATH"]), "ACTIVE_MANAGER_CONFIG")
    if config_path != CONFIG_PATH_EXPECTED:
        raise PreparationError("ACTIVE_MANAGER_CONFIG_PATH_MISMATCH")
    config_raw = config_path.read_bytes()
    config = json.loads(config_raw)
    if not isinstance(config, dict) or config.get("scheduled_lanes") != EXPECTED_LANES:
        raise PreparationError("ACTIVE_MANAGER_CONFIG_LANES_MISMATCH")
    for key in ("PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT", "production_allowed", "buy_gate_updated", "orders_sent"):
        if key in env and str(env[key]).lower() not in {"false", "0"}:
            raise PreparationError(f"ACTIVE_SAFETY_FLAG_NOT_FALSE:{key}")
    runtime_root = Path(env["V35_RUNTIME_ROOT"])
    python = runtime_root / "venvs/v3.5-mac/bin/python"
    site_packages = runtime_root / "venvs/v3.5-mac/lib/python3.14/site-packages"
    if not runtime_root.is_dir() or not python.is_file() or not os.access(python, os.X_OK) or not site_packages.is_dir():
        raise PreparationError("CONFIGURED_RUNTIME_UNAVAILABLE")
    if require_absent_candidate:
        if CANDIDATE_ROOT.exists() or CANDIDATE_ROOT.is_symlink():
            raise PreparationError("NEW_CANDIDATE_ROOT_ALREADY_EXISTS")
        if CANDIDATE_ROOT.parent.resolve(strict=True) != CANDIDATE_ROOT.parent:
            raise PreparationError("NEW_CANDIDATE_PARENT_ALIAS")
    if {entry.name for entry in root.iterdir()} != {"app", "release-manifest.json"}:
        raise PreparationError("ACTIVE_R4_ROOT_ENTRY_SET_MISMATCH")
    job = launchd_snapshot(str(plist["Label"]))
    if Path(str(job.get("plist_path") or "")).resolve() != ACTIVE_PLIST.resolve():
        raise PreparationError("ACTIVE_LAUNCHD_PLIST_PATH_MISMATCH")
    import docs.handoffs.oversold_daily_automation_20261016.scheduler_release_cutover as cutover
    process_identity = cutover._process_identity_for_root(int(job["pid"]), app, selector_plist=ACTIVE_PLIST, job_snapshot=job)
    return {
        "plist_raw": plist_raw, "plist": plist, "plist_sha256": sha_bytes(plist_raw),
        "plist_mode": f"{stat.S_IMODE(ACTIVE_PLIST.stat().st_mode):04o}",
        "env": dict(env), "base_root": root, "base_app": app, "base_manifest": manifest,
        "base_manifest_path": manifest_path, "base_manifest_sha256": manifest_sha,
        "base_app_inventory": app_inventory, "base_physical_inventory": physical_inventory(app),
        "config_path": config_path, "config": config, "config_sha256": sha_bytes(config_raw),
        "runtime_root": runtime_root, "runtime_python": python, "site_packages": site_packages,
        "launchd": job, "process_identity": process_identity,
    }


def assert_active_cas(snapshot: dict[str, Any]) -> None:
    if sha_file(ACTIVE_PLIST) != snapshot["plist_sha256"]:
        raise PreparationError("ACTIVE_PLIST_CAS_DRIFT")
    if sha_file(snapshot["config_path"]) != snapshot["config_sha256"]:
        raise PreparationError("ACTIVE_MANAGER_CONFIG_CAS_DRIFT")
    if sha_file(snapshot["base_manifest_path"]) != snapshot["base_manifest_sha256"]:
        raise PreparationError("ACTIVE_R4_MANIFEST_CAS_DRIFT")
    from ops.api_release_integration import inventory_digest, inventory_tree
    if inventory_tree(snapshot["base_app"]) != snapshot["base_app_inventory"]:
        raise PreparationError("ACTIVE_R4_APP_INVENTORY_CAS_DRIFT")
    if canonical_digest(physical_inventory(snapshot["base_app"])) != canonical_digest(snapshot["base_physical_inventory"]):
        raise PreparationError("ACTIVE_R4_PHYSICAL_INVENTORY_CAS_DRIFT")
    if inventory_digest(snapshot["base_app_inventory"]) != snapshot["base_manifest"]["application_inventory"]["aggregate_sha256"]:
        raise PreparationError("ACTIVE_R4_MANIFEST_INVENTORY_CAS_DRIFT")
    current = launchd_snapshot(str(snapshot["plist"]["Label"]))
    if current.get("pid") != snapshot["launchd"].get("pid"):
        raise PreparationError("ACTIVE_SCHEDULER_PID_CAS_DRIFT")


def delta_rows() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    delta = read_json(DELTA_PATH)
    rows = delta.get("files")
    expected = (
        "v4/manager_workbench/oversold_daily.py",
        "upstreams/v3_shared_data/shared_data/hk_daily_supplement.py",
    )
    if (
        delta.get("status") != "PREPARED_NOT_DEPLOYED"
        or delta.get("release_id") != BASE_RELEASE_ID
        or delta.get("release_manifest_sha256") != BASE_MANIFEST_SHA256
        or sha_file(SOURCE_REVIEW_PATH) != SOURCE_REVIEW_SHA256
        or "status: PASS_CACHE_FIRST_REPAIR" not in SOURCE_REVIEW_PATH.read_text(encoding="utf-8")
        or "P0 findings: **0**. P1 findings: **0**." not in SOURCE_REVIEW_PATH.read_text(encoding="utf-8")
        or not isinstance(rows, list)
        or tuple(row.get("path") for row in rows) != expected
        or sha_file(PATCH_PATH) != delta.get("patch", {}).get("sha256")
    ):
        raise PreparationError("EXACT_R4_TWO_FILE_DELTA_MISMATCH")
    for row in rows:
        artifact = exact(DOC_ROOT / row["candidate_artifact"], "SOURCE_CANDIDATE")
        if sha_file(artifact) != row["candidate_sha256"]:
            raise PreparationError(f"SOURCE_CANDIDATE_SHA_MISMATCH:{row['path']}")
    return delta, rows


def runtime_probe(snapshot: dict[str, Any], app: Path, manifest: Path, manifest_sha: str) -> dict[str, Any]:
    env = dict(snapshot["env"])
    env.update({
        "V35_APP_ROOT": str(app), "V35_RELEASE_ID": CANDIDATE_ROOT.name,
        "V35_RELEASE_MANIFEST_PATH": str(manifest), "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
        "PYTHONPATH": f"{app / 'upstreams'}:{app}:{snapshot['site_packages']}",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    code = r'''import hashlib, importlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve(strict=True)
names = json.loads(sys.argv[2])
out = {"python": sys.executable, "version": sys.version.split()[0], "modules": {}}
for name in names:
    module = importlib.import_module(name)
    path = pathlib.Path(module.__file__).resolve(strict=True)
    path.relative_to(root)
    out["modules"][name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
print(json.dumps(out, sort_keys=True))
'''
    result = subprocess.run(
        [str(snapshot["runtime_python"]), "-S", "-c", code, str(app), json.dumps(list(MODULES))],
        cwd=app, env=env, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise PreparationError(f"ACTUAL_RUNTIME_IMPORT_PROBE_FAILED:{result.returncode}:{result.stderr[-1000:]}")
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    if Path(payload.get("python", "")).resolve(strict=True) != snapshot["runtime_python"].resolve(strict=True):
        raise PreparationError("ACTUAL_RUNTIME_INTERPRETER_MISMATCH")
    relative = {
        "ops.run_v35_macos_scheduler_daemon": "ops/run_v35_macos_scheduler_daemon.py",
        "v4.manager_workbench.scheduler": "v4/manager_workbench/scheduler.py",
        "v4.manager_workbench.inputs.source_bindings": "v4/manager_workbench/inputs/source_bindings.py",
        "v4.manager_workbench.service": "v4/manager_workbench/service.py",
        "v4.manager_workbench.store": "v4/manager_workbench/store.py",
        "v4.manager_workbench.oversold_daily": "v4/manager_workbench/oversold_daily.py",
        "upstreams.v3_shared_data.shared_data.hk_daily_supplement": "upstreams/v3_shared_data/shared_data/hk_daily_supplement.py",
    }
    for name, path in relative.items():
        record = payload["modules"].get(name)
        expected_path = app / path
        if not isinstance(record, dict) or Path(record.get("path", "")) != expected_path or record.get("sha256") != sha_file(expected_path):
            raise PreparationError(f"ACTUAL_RUNTIME_MODULE_ROOT_MISMATCH:{name}")
    return payload


def write_manifest(snapshot: dict[str, Any], delta: dict[str, Any], rows: list[dict[str, Any]],
                   candidate_rows: list[dict[str, Any]], canonical: list[dict[str, Any]],
                   probe: dict[str, Any]) -> dict[str, Any]:
    from ops.api_release_integration import inventory_digest
    base_map = {row["path"]: row for row in snapshot["base_physical_inventory"]}
    after_map = {row["path"]: row for row in candidate_rows}
    paths = sorted(row["path"] for row in rows)
    deltas = []
    for row in rows:
        before, after = base_map[row["path"]], after_map[row["path"]]
        deltas.append({
            "path": row["path"], "before_sha256": before["sha256"], "before_mode": before["mode"],
            "after_sha256": after["sha256"], "after_mode": after["mode"],
            "source_preimage_sha256": row["runtime_preimage_sha256"],
            "source_candidate_sha256": row["candidate_sha256"],
            "patch_sha256": sha_file(PATCH_PATH),
        })
    non_delta = [row for row in snapshot["base_physical_inventory"] if row["path"] not in paths]
    return {
        "schema_version": "v4.oversold_daily_scheduler_cache_release_candidate.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_status": "PREPARED_FOR_INDEPENDENT_RUNTIME_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "role": "scheduler",
        "release_id": CANDIDATE_ROOT.name,
        "base": {
            "release_id": BASE_RELEASE_ID, "root": str(snapshot["base_root"]),
            "app_root": str(snapshot["base_app"]), "manifest_path": str(snapshot["base_manifest_path"]),
            "manifest_sha256": snapshot["base_manifest_sha256"], "plist_sha256": snapshot["plist_sha256"],
            "application_inventory_sha256": inventory_digest(snapshot["base_app_inventory"]),
            "physical_inventory_sha256": canonical_digest(snapshot["base_physical_inventory"]),
        },
        "candidate": {
            "release_id": CANDIDATE_ROOT.name, "root": str(CANDIDATE_ROOT), "app_root": str(CANDIDATE_APP),
            "manifest_path": str(CANDIDATE_ROOT / "release-manifest.json"),
            "manifest_self_hash_excluded": True,
            "staged_plist_path": str(CANDIDATE_ROOT / "config/com.lexi.v35.scheduler.plist"),
            "staged_plist_hash_is_in_preparation_receipt": True,
        },
        "source": {
            "active_plist_path": str(ACTIVE_PLIST), "active_plist_preimage_sha256": snapshot["plist_sha256"],
            "manager_config_path": str(snapshot["config_path"]), "manager_config_sha256": snapshot["config_sha256"],
            "manager_config_copied_or_changed": False, "scheduled_lanes": snapshot["config"].get("scheduled_lanes"),
            "source_delta_manifest_path": str(DELTA_PATH), "source_delta_manifest_sha256": sha_file(DELTA_PATH),
            "source_delta_patch_path": str(PATCH_PATH), "source_delta_patch_sha256": sha_file(PATCH_PATH),
            "source_review_path": str(SOURCE_REVIEW_PATH),
            "source_review_sha256": SOURCE_REVIEW_SHA256,
            "source_review_status": "PASS_CACHE_FIRST_REPAIR",
            "active_release_copied": True, "source_workspace_full_tree_copied": False, "runtime_state_copied": False,
        },
        "delta_entries": deltas,
        "application_inventory": {
            "entry_count": len(canonical), "aggregate_sha256": inventory_digest(canonical), "entries": canonical,
            "rule": "existing API release application inventory; excludes generated __pycache__ bytes",
        },
        "physical_inventory": {
            "entry_count": len(candidate_rows), "aggregate_sha256": canonical_digest(candidate_rows),
            "entries": candidate_rows, "rule": "all app files including bytecode and directories; excludes app root row",
        },
        "base_physical_inventory": {
            "entry_count": len(snapshot["base_physical_inventory"]),
            "aggregate_sha256": canonical_digest(snapshot["base_physical_inventory"]),
            "entries": snapshot["base_physical_inventory"],
            "rule": "same physical inventory rule as candidate",
        },
        "non_delta_preservation": {
            "all_equal": True, "entry_count": len(non_delta), "aggregate_sha256": canonical_digest(non_delta),
            "excluded_delta_paths": paths,
        },
        "actual_runtime_import_probe": probe,
        "safety": {
            "research_only": True, "production_allowed": False, "buy_gate_updated": False,
            "orders_sent": False, "other_lanes_and_schedule_parameters_changed": False,
        },
        "verification_gaps": [
            "independent runtime release review is pending",
            "candidate is not installed or activated", "no live recovery or TDX request was performed",
            "API, UI, and natural scheduled behavior remain unverified",
        ],
    }


def validate_staged_plist(source: dict[str, Any], staged: dict[str, Any], manifest_sha: str) -> None:
    source_env = source["EnvironmentVariables"]
    env = staged.get("EnvironmentVariables")
    if not isinstance(env, dict) or staged.get("Label") != source.get("Label"):
        raise PreparationError("STAGED_PLIST_LABEL_OR_ENV_INVALID")
    expected = {
        "V35_APP_ROOT": str(CANDIDATE_APP),
        "V35_RELEASE_ID": CANDIDATE_ROOT.name,
        "V35_RELEASE_MANIFEST_PATH": str(CANDIDATE_ROOT / "release-manifest.json"),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
        "PYTHONPATH": f"{CANDIDATE_APP / 'upstreams'}:{CANDIDATE_APP}",
    }
    changed = {key for key in set(source_env) | set(env) if source_env.get(key) != env.get(key)}
    if changed != set(expected) or any(env.get(key) != value for key, value in expected.items()):
        raise PreparationError("STAGED_PLIST_ENV_CHANGE_SET_OR_SELECTOR_MISMATCH")
    if staged.get("ProgramArguments") != ["/bin/bash", str(CANDIDATE_APP / "ops/launch_v35_macos_scheduler.sh")]:
        raise PreparationError("STAGED_PLIST_LAUNCHER_MISMATCH")
    if staged.get("WorkingDirectory") != str(CANDIDATE_APP):
        raise PreparationError("STAGED_PLIST_CWD_MISMATCH")
    for key in ("KeepAlive", "RunAtLoad"):
        if staged.get(key) != source.get(key):
            raise PreparationError(f"STAGED_PLIST_LAUNCH_POLICY_CHANGED:{key}")
    old = deepcopy(source)
    new = deepcopy(staged)
    for key in expected:
        new["EnvironmentVariables"][key] = source_env.get(key)
    old["ProgramArguments"] = staged["ProgramArguments"]
    old["WorkingDirectory"] = staged["WorkingDirectory"]
    if new != old:
        raise PreparationError("STAGED_PLIST_UNEXPECTED_FIELD_CHANGE")


def prepare(*, resume: bool = False) -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT))
    from infrastructure.interprocess_lock import owned_interprocess_lock, assert_owned_interprocess_lock
    from ops.api_release_integration import inventory_digest, inventory_tree
    import docs.handoffs.oversold_daily_automation_20261016.scheduler_release_cutover as cutover

    with ExitStack() as stack:
        leases = [
            stack.enter_context(owned_interprocess_lock(
                ACTIVE_PLIST.with_name(name), timeout_seconds=3.0, timeout_message="SCHEDULER_RELEASE_LOCK_BUSY",
            ))
            for name in LOCK_NAMES
        ]
        snapshot = active_snapshot(require_absent_candidate=not resume)
        delta, rows = delta_rows()
        if delta.get("patch", {}).get("path") != PATCH_PATH.name:
            raise PreparationError("SOURCE_DELTA_PATCH_PATH_MISMATCH")
        base_rows = snapshot["base_physical_inventory"]
        base_map = {row["path"]: row for row in base_rows}
        for row in rows:
            before = base_map.get(row["path"])
            if not before or before.get("sha256") != row["runtime_preimage_sha256"]:
                raise PreparationError(f"ACTIVE_R4_DELTA_PREIMAGE_MISMATCH:{row['path']}")
        if PREIMAGE_PATH.exists():
            if PREIMAGE_PATH.is_symlink() or PREIMAGE_PATH.read_bytes() != snapshot["plist_raw"] or stat.S_IMODE(PREIMAGE_PATH.stat().st_mode) != 0o600:
                raise PreparationError("SAVED_CACHE_RELEASE_PREIMAGE_CONFLICT")
        else:
            with PREIMAGE_PATH.open("xb") as handle:
                handle.write(snapshot["plist_raw"])
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(PREIMAGE_PATH, 0o600)

        manifest_path = CANDIDATE_ROOT / "release-manifest.json"
        staged_path = CANDIDATE_ROOT / "config/com.lexi.v35.scheduler.plist"
        delta_paths = sorted(row["path"] for row in rows)
        if resume:
            exact(CANDIDATE_ROOT, "EXISTING_CANDIDATE_ROOT", directory=True)
            if {entry.name for entry in CANDIDATE_ROOT.iterdir()} != {"app", "release-manifest.json", "config"}:
                raise PreparationError("PARTIAL_CANDIDATE_ROOT_ENTRY_SET_MISMATCH")
            if not (CANDIDATE_ROOT / "config").is_dir() or {
                entry.name for entry in (CANDIDATE_ROOT / "config").iterdir()
            } != {"com.lexi.v35.scheduler.plist"}:
                raise PreparationError("PARTIAL_CANDIDATE_CONFIG_ENTRY_SET_MISMATCH")
            candidate_rows = physical_inventory(CANDIDATE_APP)
            candidate_map = {row["path"]: row for row in candidate_rows}
            changed = sorted(path for path in set(base_map) | set(candidate_map)
                             if base_map.get(path) != candidate_map.get(path))
            if changed != delta_paths:
                raise PreparationError("PARTIAL_CANDIDATE_DELTA_SET_MISMATCH:" + ",".join(changed))
            non_delta = [row for row in base_rows if row["path"] not in delta_paths]
            if non_delta != [row for row in candidate_rows if row["path"] not in delta_paths]:
                raise PreparationError("PARTIAL_CANDIDATE_NON_DELTA_BYTES_OR_MODES_CHANGED")
            canonical = inventory_tree(CANDIDATE_APP)
            manifest_sha = sha_file(manifest_path)
            stored_manifest = read_json(manifest_path)
            final_probe = runtime_probe(snapshot, CANDIDATE_APP, manifest_path, manifest_sha)
            expected_manifest = write_manifest(snapshot, delta, rows, candidate_rows, canonical, final_probe)
            generated_at = stored_manifest.get("generated_at")
            if not isinstance(generated_at, str) or not generated_at.strip():
                raise PreparationError("PARTIAL_CANDIDATE_MANIFEST_GENERATION_TIME_MISSING")
            try:
                datetime.fromisoformat(generated_at)
            except ValueError as error:
                raise PreparationError("PARTIAL_CANDIDATE_MANIFEST_GENERATION_TIME_INVALID") from error
            expected_manifest["generated_at"] = generated_at
            if stored_manifest != expected_manifest:
                raise PreparationError("PARTIAL_CANDIDATE_MANIFEST_CONTENT_MISMATCH")
            if exact(staged_path, "EXISTING_STAGED_PLIST").read_bytes() == b"":
                raise PreparationError("PARTIAL_CANDIDATE_STAGED_PLIST_EMPTY")
            staged_payload = plistlib.loads(staged_path.read_bytes())
            validate_staged_plist(snapshot["plist"], staged_payload, manifest_sha)
            staged_sha = sha_file(staged_path)
        else:
            shutil.copytree(snapshot["base_root"], CANDIDATE_ROOT, copy_function=shutil.copy2, symlinks=True)
            patch_result = subprocess.run(
                ["patch", "-N", "-f", "-p1", "-i", str(PATCH_PATH)],
                cwd=CANDIDATE_APP, capture_output=True, text=True, check=False,
            )
            if patch_result.returncode != 0:
                raise PreparationError(f"EXACT_TWO_FILE_PATCH_FAILED:{patch_result.returncode}:{patch_result.stderr[-1000:]}")
            for row in rows:
                target = CANDIDATE_APP / row["path"]
                if not target.is_file() or sha_file(target) != row["candidate_sha256"]:
                    raise PreparationError(f"CANDIDATE_SOURCE_SHA_MISMATCH:{row['path']}")
                mode = int(base_map[row["path"]]["mode"], 8)
                os.chmod(target, mode)
                if stat.S_IMODE(target.stat().st_mode) != mode:
                    raise PreparationError(f"CANDIDATE_SOURCE_MODE_MISMATCH:{row['path']}")
            candidate_rows = physical_inventory(CANDIDATE_APP)
            candidate_map = {row["path"]: row for row in candidate_rows}
            changed = sorted(path for path in set(base_map) | set(candidate_map)
                             if base_map.get(path) != candidate_map.get(path))
            if changed != delta_paths:
                raise PreparationError("CANDIDATE_PHYSICAL_DELTA_SET_MISMATCH:" + ",".join(changed))
            non_delta = [row for row in base_rows if row["path"] not in delta_paths]
            if non_delta != [row for row in candidate_rows if row["path"] not in delta_paths]:
                raise PreparationError("CANDIDATE_NON_DELTA_BYTES_OR_MODES_CHANGED")
            canonical = inventory_tree(CANDIDATE_APP)
            assert_active_cas(snapshot)
            manifest_mode = stat.S_IMODE(manifest_path.stat().st_mode)
            manifest = write_manifest(snapshot, delta, rows, candidate_rows, canonical, {})
            manifest_path.write_bytes(json_bytes(manifest))
            os.chmod(manifest_path, manifest_mode)
            provisional_sha = sha_file(manifest_path)
            probe = runtime_probe(snapshot, CANDIDATE_APP, manifest_path, provisional_sha)
            manifest["actual_runtime_import_probe"] = probe
            manifest_path.write_bytes(json_bytes(manifest))
            os.chmod(manifest_path, manifest_mode)
            manifest_sha = sha_file(manifest_path)
            final_probe = runtime_probe(snapshot, CANDIDATE_APP, manifest_path, manifest_sha)
            if final_probe != probe:
                raise PreparationError("RUNTIME_IMPORT_PROBE_NOT_STABLE")
            if physical_inventory(CANDIDATE_APP) != candidate_rows or inventory_tree(CANDIDATE_APP) != canonical:
                raise PreparationError("CANDIDATE_APP_CHANGED_DURING_IMPORT_PROBE")
            import ops.build_release_candidate_stage as renderer
            renderer.sha256_file = sha_file
            staged_result = renderer._stage_scheduler_identity(
                source_plist=ACTIVE_PLIST, candidate_root=CANDIDATE_ROOT, release_id=CANDIDATE_ROOT.name,
                manifest_path=manifest_path, manifest_sha256=manifest_sha,
            )
            staged_path = Path(str(staged_result["path"]))
            missing = staged_result.get("missing_rebound_paths") or []
            source_pythonpath = snapshot["env"].get("PYTHONPATH", "")
            try:
                pythonpath_collision = str(CANDIDATE_APP / Path(source_pythonpath).relative_to(snapshot["base_app"]))
            except ValueError:
                pythonpath_collision = None
            if missing and (pythonpath_collision is None or missing != [pythonpath_collision]):
                raise PreparationError("CANDIDATE_STAGED_PATH_MISSING")
            for key, value in snapshot["env"].items():
                if key == "PYTHONPATH" or not isinstance(value, str) or not Path(value).is_absolute():
                    continue
                try:
                    relative = Path(value).relative_to(snapshot["base_app"])
                except ValueError:
                    continue
                if not (CANDIDATE_APP / relative).exists():
                    raise PreparationError(f"CANDIDATE_INTERNAL_BINDING_MISSING:{key}")
            staged_payload = plistlib.loads(staged_path.read_bytes())
            validate_staged_plist(snapshot["plist"], staged_payload, manifest_sha)
            staged_sha = sha_file(staged_path)
        assert_active_cas(snapshot)
        for lease, name in zip(leases, LOCK_NAMES):
            assert_owned_interprocess_lock(lease, ACTIVE_PLIST.with_name(name))

        binding = {
            "schema_version": "v4.oversold_daily_scheduler_cache_binding.v1",
            "candidate_release_id": CANDIDATE_ROOT.name,
            "candidate_root": str(CANDIDATE_ROOT),
            "candidate_app_root": str(CANDIDATE_APP),
            "candidate_manifest_path": str(manifest_path),
            "candidate_manifest_sha256": manifest_sha,
            "candidate_staged_plist_path": str(staged_path),
            "candidate_staged_plist_sha256": staged_sha,
            "candidate_source_sha256": {row["path"]: row["candidate_sha256"] for row in rows},
            "delta_paths": delta_paths,
            "base_release_id": BASE_RELEASE_ID,
            "base_release_root": str(snapshot["base_root"]),
            "base_app_root": str(snapshot["base_app"]),
            "base_manifest_sha256": snapshot["base_manifest_sha256"],
            "base_plist_preimage_path": str(PREIMAGE_PATH),
            "base_plist_preimage_sha256": snapshot["plist_sha256"],
            "base_plist_preimage_mode": snapshot["plist_mode"],
            "active_plist_path": str(ACTIVE_PLIST),
            "manager_config_path": str(snapshot["config_path"]),
            "manager_config_sha256": snapshot["config_sha256"],
            "runtime_root": str(snapshot["runtime_root"]),
            "source_day": "20261015",
            "target_date": "20261016",
            "activation_receipt_path": str(DOC_ROOT / "scheduler_cache_release_activation_receipt.json"),
            "rollback_receipt_path": str(DOC_ROOT / "scheduler_cache_release_rollback_receipt.json"),
            "preparation_receipt_path": str(RECEIPT_PATH),
            "runtime_review_schema": RUNTIME_REVIEW_SCHEMA,
            "writer_identity": "oversold_daily_writer",
            "source_delta_manifest_path": str(DELTA_PATH),
            "source_delta_manifest_sha256": sha_file(DELTA_PATH),
            "source_delta_patch_path": str(PATCH_PATH),
            "source_delta_patch_sha256": sha_file(PATCH_PATH),
            "source_review_path": str(SOURCE_REVIEW_PATH),
            "source_review_sha256": SOURCE_REVIEW_SHA256,
            "cutover_core_path": str(DOC_ROOT / "scheduler_release_cutover.py"),
            "cutover_core_sha256": sha_file(DOC_ROOT / "scheduler_release_cutover.py"),
        }
        binding_raw = json_bytes(binding)
        BINDING_PATH.write_bytes(binding_raw)
        BINDING_PATH.chmod(0o600)

        receipt = {
            "schema_version": "v4.oversold_daily_scheduler_cache_preparation_receipt.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "PREPARED_NOT_ACTIVATED",
            "candidate_release_id": CANDIDATE_ROOT.name,
            "candidate_root": str(CANDIDATE_ROOT),
            "candidate_app_root": str(CANDIDATE_APP),
            "candidate_manifest_path": str(manifest_path),
            "candidate_manifest_sha256": manifest_sha,
            "candidate_release_manifest_sha256": manifest_sha,
            "candidate_staged_plist_path": str(staged_path),
            "candidate_staged_plist_sha256": staged_sha,
            "candidate_application_inventory_sha256": inventory_digest(canonical),
            "candidate_physical_inventory_sha256": canonical_digest(candidate_rows),
            "base_release_id": BASE_RELEASE_ID,
            "base_release_root": str(snapshot["base_root"]),
            "base_manifest_sha256": snapshot["base_manifest_sha256"],
            "base_physical_inventory_sha256": canonical_digest(base_rows),
            "base_plist_path": str(ACTIVE_PLIST),
            "base_plist_preimage_sha256": snapshot["plist_sha256"],
            "base_plist_preimage_mode": snapshot["plist_mode"],
            "base_plist_preimage_copy": str(PREIMAGE_PATH),
            "base_plist_preimage_copy_mode": "0600",
            "manager_config_path": str(snapshot["config_path"]),
            "manager_config_sha256": snapshot["config_sha256"],
            "base_manager_config_sha256": snapshot["config_sha256"],
            "scheduled_lanes": snapshot["config"].get("scheduled_lanes"),
            "base_running_process": snapshot["process_identity"],
            "exact_delta_paths": delta_paths,
            "source_delta_manifest_path": str(DELTA_PATH),
            "source_delta_manifest_sha256": sha_file(DELTA_PATH),
            "source_delta_patch_sha256": sha_file(PATCH_PATH),
            "source_review_status": "PASS_CACHE_FIRST_REPAIR",
            "source_review_path": str(SOURCE_REVIEW_PATH),
            "source_review_sha256": SOURCE_REVIEW_SHA256,
            "non_delta_entry_count": len(non_delta),
            "non_delta_inventory_sha256": canonical_digest(non_delta),
            "runtime_import_probe": final_probe,
            "binding_config_path": str(BINDING_PATH),
            "binding_config_sha256": sha_file(BINDING_PATH),
            "scheduler_release_locks": [str(ACTIVE_PLIST.with_name(name)) for name in LOCK_NAMES],
            "active_plist_changed": False,
            "manager_config_changed": False,
            "launchctl_called_for_mutation": False,
            "service_state_changed": False,
            "candidate_activated": False,
            "recovery_run": False,
            "network_call": False,
            "activation_status": "NOT_ACTIVATED",
            "deployment_status": "CANNOT_CONFIRM",
        }
        receipt_raw = json_bytes(receipt)

        plan = {
            "schema_version": "v4.oversold_daily_scheduler_cache_cutover_plan.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "PREPARED_NOT_ACTIVATED",
            "activation_gate": {
                "status": "NOT_AUTHORIZED",
                "launchctl_called_for_mutation": False,
                "requirements": [
                    "independent two-file source repair review PASS_CACHE_FIRST_REPAIR, pinned by SHA",
                    "independent runtime-release review PASS bound to candidate manifest SHA",
                    "explicit future activation authorization reference",
                    "fresh active plist/config/inventory CAS under both established release locks",
                ],
                "runtime_review_receipt_contract": {
                    "schema_version": RUNTIME_REVIEW_SCHEMA,
                    "status": "PASS_RUNTIME_RELEASE",
                    "behavior_verified": "PASS",
                    "candidate_release_manifest_sha256": manifest_sha,
                    "writer_identity": "oversold_daily_writer",
                    "reviewer_identity": "distinct non-empty independent identity",
                },
                "ordering": [
                    "verify base/candidate inventory, config, and active process identity",
                    "bootout old label; confirm exact PID and label absence, settle, and recheck",
                    "recheck plist/config CAS and lock ownership",
                    "atomically install staged plist",
                    "bootstrap candidate and verify process identity",
                ],
            },
            "base": {
                "release_id": BASE_RELEASE_ID,
                "release_root": str(snapshot["base_root"]),
                "manifest_sha256": snapshot["base_manifest_sha256"],
                "active_plist_path": str(ACTIVE_PLIST),
                "active_plist_preimage_sha256": snapshot["plist_sha256"],
                "active_plist_preimage_path": str(PREIMAGE_PATH),
                "manager_config_path": str(snapshot["config_path"]),
                "manager_config_sha256": snapshot["config_sha256"],
                "scheduled_lanes": snapshot["config"].get("scheduled_lanes"),
                "running_process": snapshot["process_identity"],
            },
            "candidate": {
                "release_id": CANDIDATE_ROOT.name,
                "release_root": str(CANDIDATE_ROOT),
                "app_root": str(CANDIDATE_APP),
                "manifest_path": str(manifest_path),
                "manifest_sha256": manifest_sha,
                "staged_plist_path": str(staged_path),
                "staged_plist_sha256": staged_sha,
                "exact_delta_paths": delta_paths,
                "non_delta_entry_count": len(non_delta),
                "non_delta_inventory_sha256": canonical_digest(non_delta),
            },
            "rollback_gate": {
                "status": "PREPARED_NOT_EXECUTED",
                "requirements": [
                    "explicit future rollback authorization reference",
                    "active plist equals exact candidate staged plist",
                    "manager-v7 config and saved base preimage match receipt",
                    "candidate process identity verified or no scheduler process remains",
                ],
                "exact_preimage_restore": {
                    "path": str(PREIMAGE_PATH),
                    "sha256": snapshot["plist_sha256"],
                    "mode": snapshot["plist_mode"],
                },
            },
            "recovery": {
                "status": "PREPARED_PLAN_ONLY_NOT_RUN",
                "source_day": "20261015",
                "target_date": "20261016",
                "trigger_time": "actual current Asia/Hong_Kong time at future authorized execution",
                "target_date_must_still_be_current_hk_session": True,
                "owner": "existing OversoldDaily driver and exact-date TDX61 cache path",
                "formal_run_performed": False,
                "network_request_performed": False,
                "old_plan_or_manual_work_deleted": False,
                "per_security_cache_hit_claim": "CANNOT_CONFIRM_WITHOUT_CAPTURE_RECORD_READBACK",
            },
            "current_execution": {
                "active_plist_changed": False, "manager_config_changed": False, "service_state_changed": False,
                "launchctl_called_for_mutation": False, "candidate_activated": False, "recovery_run": False,
                "network_call": False, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
            },
            "verification_gaps": [
                "independent runtime release review pending",
                "activation not authorized or performed", "live recovery not run",
                "API/UI and natural scheduled behavior CANNOT_CONFIRM",
            ],
        }
        PLAN_PATH.write_bytes(json_bytes(plan))
        PLAN_PATH.chmod(0o600)
        receipt["plan_path"] = str(PLAN_PATH)
        receipt["plan_sha256"] = sha_file(PLAN_PATH)
        receipt_raw = json_bytes(receipt)
        RECEIPT_PATH.write_bytes(receipt_raw)
        RECEIPT_PATH.chmod(0o600)
        md = "\n".join([
            "# OVERSOLD cache-first scheduler candidate preparation",
            "",
            "Status: PREPARED_NOT_ACTIVATED; source repair review PASS; independent runtime release review is pending.",
            "",
            f"Candidate {CANDIDATE_ROOT.name} manifest SHA-256: {manifest_sha}.",
            f"Staged plist SHA-256: {staged_sha}.",
            f"Fresh active base {BASE_RELEASE_ID} manifest SHA-256: {snapshot['base_manifest_sha256']}.",
            f"Active plist preimage SHA-256: {snapshot['plist_sha256']}; saved at {PREIMAGE_PATH}.",
            f"Manager-v7 config SHA-256: {snapshot['config_sha256']}; existing config binding is unchanged.",
            f"Only these app paths differ: {', '.join(delta_paths)}.",
            f"Non-delta entries preserved byte-for-byte and mode-for-mode: {len(non_delta)}, inventory SHA-256 {canonical_digest(non_delta)}.",
            f"The configured scheduler interpreter imported {len(final_probe['modules'])} modules from the isolated candidate app root.",
            "The staged plist preserves the existing manager-v7 config path, schedule, external roots, launch policy, and false research safety flags.",
            f"CAS plan: {PLAN_PATH}.",
            "",
            f"Source repair review PASS: {SOURCE_REVIEW_PATH.name} SHA-256 {SOURCE_REVIEW_SHA256}.",
            "CANNOT_CONFIRM: independent runtime release review; activation or live recovery; live TDX behavior; API/UI readback; natural scheduled output.",
            "No active plist/config, service, cursor, old plan, API, or UI was changed.",
            "Research safety remains RESEARCH_ONLY=true, PRODUCTION_ALLOWED=false, BUY_GATE_UPDATED=false, ORDERS_SENT=false.",
            "",
        ])
        MARKDOWN_RECEIPT_PATH.write_text(md, encoding="utf-8")
        MARKDOWN_RECEIPT_PATH.chmod(0o600)
        return receipt


def check() -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT))
    from ops.api_release_integration import inventory_digest, inventory_tree
    receipt = read_json(RECEIPT_PATH)
    if receipt.get("status") != "PREPARED_NOT_ACTIVATED":
        raise PreparationError("PREPARATION_RECEIPT_STATUS_INVALID")
    snapshot = active_snapshot(require_absent_candidate=False)
    if receipt.get("base_plist_preimage_sha256") != snapshot["plist_sha256"]:
        raise PreparationError("ACTIVE_PLIST_CAS_CHANGED")
    if receipt.get("manager_config_sha256") != snapshot["config_sha256"]:
        raise PreparationError("ACTIVE_MANAGER_CONFIG_CAS_CHANGED")
    if receipt.get("base_manifest_sha256") != snapshot["base_manifest_sha256"]:
        raise PreparationError("ACTIVE_BASE_MANIFEST_CAS_CHANGED")
    if PREIMAGE_PATH.read_bytes() != snapshot["plist_raw"] or stat.S_IMODE(PREIMAGE_PATH.stat().st_mode) != 0o600:
        raise PreparationError("SAVED_ACTIVE_PLIST_PREIMAGE_MISMATCH")
    manifest_path = CANDIDATE_ROOT / "release-manifest.json"
    staged_path = CANDIDATE_ROOT / "config/com.lexi.v35.scheduler.plist"
    if sha_file(manifest_path) != receipt.get("candidate_manifest_sha256"):
        raise PreparationError("CANDIDATE_MANIFEST_SHA_MISMATCH")
    if sha_file(staged_path) != receipt.get("candidate_staged_plist_sha256"):
        raise PreparationError("CANDIDATE_STAGED_PLIST_SHA_MISMATCH")
    _delta, rows = delta_rows()
    base_rows = snapshot["base_physical_inventory"]
    candidate_rows = physical_inventory(CANDIDATE_APP)
    base_map, candidate_map = ({row["path"]: row for row in records} for records in (base_rows, candidate_rows))
    changed = sorted(path for path in set(base_map) | set(candidate_map) if base_map.get(path) != candidate_map.get(path))
    if changed != sorted(row["path"] for row in rows):
        raise PreparationError("CANDIDATE_DELTA_SET_DRIFT")
    non_delta = [row for row in base_rows if row["path"] not in changed]
    if non_delta != [row for row in candidate_rows if row["path"] not in changed]:
        raise PreparationError("CANDIDATE_NON_DELTA_INVENTORY_DRIFT")
    manifest = read_json(manifest_path)
    canonical = inventory_tree(CANDIDATE_APP)
    inv = manifest.get("application_inventory", {})
    if canonical != inv.get("entries") or inventory_digest(canonical) != inv.get("aggregate_sha256"):
        raise PreparationError("CANDIDATE_APPLICATION_INVENTORY_MISMATCH")
    if candidate_rows != manifest.get("physical_inventory", {}).get("entries"):
        raise PreparationError("CANDIDATE_PHYSICAL_INVENTORY_MISMATCH")
    if sha_file(BINDING_PATH) != receipt.get("binding_config_sha256"):
        raise PreparationError("CANDIDATE_BINDING_CONFIG_SHA_MISMATCH")
    if sha_file(PLAN_PATH) != receipt.get("plan_sha256"):
        raise PreparationError("CANDIDATE_PLAN_SHA_MISMATCH")
    if (receipt.get("source_review_status") != "PASS_CACHE_FIRST_REPAIR"
            or receipt.get("source_review_sha256") != SOURCE_REVIEW_SHA256
            or sha_file(SOURCE_REVIEW_PATH) != SOURCE_REVIEW_SHA256):
        raise PreparationError("SOURCE_REPAIR_REVIEW_RECEIPT_MISMATCH")
    if receipt.get("prepare_script_sha256") != sha_file(Path(__file__).resolve()):
        raise PreparationError("PREPARATION_SCRIPT_RECEIPT_SHA_MISMATCH")
    helper_names = (
        "prepare_scheduler_cache_release.py",
        "scheduler_cache_release_cutover.py",
        "activate_scheduler_cache_release.py",
        "rollback_scheduler_cache_release.py",
        "recover_oversold_cache_20261016.py",
    )
    helper_records = receipt.get("prepared_helper_artifacts")
    plan = read_json(PLAN_PATH)
    if not isinstance(helper_records, list) or helper_records != plan.get("prepared_helper_artifacts"):
        raise PreparationError("PREPARED_HELPER_INVENTORY_RECEIPT_MISMATCH")
    for name in helper_names:
        target = (DOC_ROOT / name).resolve(strict=True)
        matches = [row for row in helper_records if isinstance(row, dict) and Path(row.get("path", "")).resolve() == target]
        if len(matches) != 1 or matches[0].get("sha256") != sha_file(target):
            raise PreparationError(f"PREPARED_HELPER_SHA_MISMATCH:{name}")
    assert_active_cas(snapshot)
    print(json.dumps({
        "status": "CACHE_SCHEDULER_RELEASE_PREPARED_CHECK_PASS",
        "activation_status": "NOT_ACTIVATED",
        "candidate_release_id": CANDIDATE_ROOT.name,
        "candidate_manifest_sha256": sha_file(manifest_path),
        "candidate_staged_plist_sha256": sha_file(staged_path),
        "active_plist_sha256": snapshot["plist_sha256"],
        "manager_config_sha256": snapshot["config_sha256"],
        "base_process": snapshot["process_identity"],
        "changed_paths": changed,
        "non_delta_entry_count": len(non_delta),
        "non_delta_inventory_sha256": canonical_digest(non_delta),
        "active_plist_changed": False,
        "manager_config_changed": False,
        "launchctl_called_for_mutation": False,
    }, ensure_ascii=False, sort_keys=True))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--resume-partial", action="store_true",
                       help="finalize only an existing candidate after exact base/delta/manifest checks")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        receipt = prepare(resume=args.resume_partial) if args.prepare or args.resume_partial else check()
        if args.prepare or args.resume_partial:
            print(json.dumps({
                "status": receipt["status"],
                "candidate_release_id": receipt["candidate_release_id"],
                "candidate_manifest_sha256": receipt["candidate_manifest_sha256"],
                "candidate_staged_plist_sha256": receipt["candidate_staged_plist_sha256"],
                "base_release_id": receipt["base_release_id"],
                "base_manifest_sha256": receipt["base_manifest_sha256"],
                "base_plist_sha256": receipt["base_plist_preimage_sha256"],
                "manager_config_sha256": receipt["manager_config_sha256"],
                "non_delta_entry_count": receipt["non_delta_entry_count"],
                "non_delta_inventory_sha256": receipt["non_delta_inventory_sha256"],
                "runtime_imported_module_count": len(receipt["runtime_import_probe"]["modules"]),
                "active_plist_changed": False,
                "manager_config_changed": False,
                "launchctl_called_for_mutation": False,
                "recovery_run": False,
            }, ensure_ascii=False, sort_keys=True))
    except (PreparationError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(2, f"PREPARATION_BLOCKED:{type(error).__name__}:{str(error)[:300]}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
