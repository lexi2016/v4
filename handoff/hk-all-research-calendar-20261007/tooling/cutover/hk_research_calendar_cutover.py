#!/usr/bin/env python3
"""Prepare and gate the reviewed HK research-calendar API/scheduler release.

`prepare` copies the already-reviewed application trees into their final,
service-specific release roots and changes only the outer manifest's location
fields. `preflight` is read-only. `apply` and `rollback` delegate to the
previously tested no-clobber cutover implementation and require both its
service-specific confirmation string and a matching independent review
receipt. This file has not executed `apply` or `rollback`.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


EVIDENCE_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_HK_ALL_RESEARCH_CALENDAR_20261007")
BATCH_ID = "hk-research-calendar-all-r1-20261007"
BATCH_ROOT = EVIDENCE_ROOT / "release_candidates" / BATCH_ID
RECEIPT_ROOT = EVIDENCE_ROOT / "receipts" / BATCH_ID
IDENTITY_PATH = RECEIPT_ROOT / "cutover_identity.json"
LOCATION_RECEIPT_PATH = RECEIPT_ROOT / "final_release_location_receipt.json"
REVIEW_RECEIPT = EVIDENCE_ROOT / "review" / "runtime_cutover_independent_review_receipt.json"
READBACK_PATH = RECEIPT_ROOT / "release_verification_receipt.json"
BACKEND_PATH = Path("/Users/lexi/Desktop/学习/agents调试/V4_HK_CLOSE_DAILY_20261007/hk_market_calendar/hk_calendar_candidate_cutover.py")
BACKEND_SHA256 = "264ad2d3f5535e17f6e7471dc12d7e00452104b505795857e9f0637c0a29e816"
PACKAGE_REVIEW_PATH = EVIDENCE_ROOT / "review" / "runtime_package_independent_review_receipt.json"
PACKAGE_REVIEW_SHA256 = "c46d062d8f6f04da2795195c033aba3bec3e2d0f0ab28783570ba08e80f351d2"
BASELINE_RELEASES = {
    "api": {
        "label": "com.lexi.v35.api-only",
        "plist": Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist"),
        "release_root": Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-close-hk-calendar-r2-20261007-api"),
        "manifest_sha256": "46727f049c8bd490804f0a67779321dd4722971e0a027cff3dd61a32cb75101c",
        "release_id": "hk-close-hk-calendar-r2-20261007-api",
        "manifest_candidate_release_id": "hk-close-hk-calendar-r2-20261007-api",
    },
    "scheduler": {
        "label": "com.lexi.v35.scheduler",
        "plist": Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist"),
        "release_root": Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/hk-close-hk-calendar-r2-20261007-scheduler"),
        "manifest_sha256": "2ab5e59af2a381c40fa6553f019c7aecc76af32b6718c4c29fc25f0ce84f818b",
        "release_id": "hk-close-hk-calendar-r2-20261007-scheduler",
        "manifest_candidate_release_id": "r9-hk-child-binding-standard-b1f316ac73f0",
    },
}
RELEASE_IDS = {service: f"{BATCH_ID}-{service}" for service in ("api", "scheduler")}
API_PYTHON = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python")
SAFETY_FIELDS = ("production_allowed", "buy_gate_updated", "orders_sent")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes())


def canonical_sha(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for directory, directories, filenames in os.walk(root, followlinks=False):
        directories.sort()
        filenames.sort()
        kept: list[str] = []
        for name in directories:
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                rows.append({"kind": "symlink", "path": rel, "target": os.readlink(path), "target_exists": path.exists()})
            else:
                kept.append(name)
        directories[:] = kept
        for name in filenames:
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            info = path.lstat()
            if path.is_symlink():
                rows.append({"kind": "symlink", "path": rel, "target": os.readlink(path), "target_exists": path.exists()})
            elif path.is_file():
                import stat
                rows.append({"kind": "file", "mode": f"{stat.S_IMODE(info.st_mode):04o}", "path": rel, "sha256": sha256_file(path), "size": info.st_size})
            else:
                raise ValueError(f"unsupported release entry: {path}")
    return sorted(rows, key=lambda row: row["path"])


def env_from_plist(plist: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in plist.get("ProgramArguments", []):
        if isinstance(token, str) and "=" in token:
            key, value = token.split("=", 1)
            if key and not any(char.isspace() for char in key):
                result[key] = value
    for key, value in (plist.get("EnvironmentVariables") or {}).items():
        if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
            result[key] = str(value)
    return result


def _replace_plist_paths(
    service: str,
    original: dict[str, Any],
    *,
    old_app: Path,
    new_root: Path,
    manifest_sha: str,
) -> dict[str, Any]:
    new = copy.deepcopy(original)
    new_app = new_root / "app"
    env_updates = {
        "V35_APP_ROOT": str(new_app),
        "V35_RELEASE_ID": RELEASE_IDS[service],
        "V35_RELEASE_MANIFEST_PATH": str(new_root / "release-manifest.json"),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
    }
    new["WorkingDirectory"] = str(new_app)
    if service == "api":
        arguments = new.get("ProgramArguments")
        if not isinstance(arguments, list):
            raise ValueError("API plist has no ProgramArguments")
        found: set[str] = set()
        for index, token in enumerate(arguments):
            if not isinstance(token, str) or "=" not in token:
                continue
            key, _value = token.split("=", 1)
            if key in env_updates:
                arguments[index] = f"{key}={env_updates[key]}"
                found.add(key)
            elif key == "PYTHONPATH":
                parts = token.split("=", 1)[1].split(os.pathsep)
                if not any(part == str(old_app) or part.startswith(str(old_app) + os.sep) for part in parts):
                    raise ValueError("API PYTHONPATH does not bind the active app root")
                arguments[index] = f"PYTHONPATH={os.pathsep.join(part.replace(str(old_app), str(new_app), 1) for part in parts)}"
                found.add("PYTHONPATH")
        if found != set(env_updates) | {"PYTHONPATH"}:
            raise ValueError(f"API plist is missing expected environment bindings: {sorted((set(env_updates) | {'PYTHONPATH'}) - found)}")
    elif service == "scheduler":
        environment = new.get("EnvironmentVariables")
        if not isinstance(environment, dict):
            raise ValueError("scheduler plist has no EnvironmentVariables")
        for key, value in env_updates.items():
            if key not in environment:
                raise ValueError(f"scheduler plist is missing {key}")
            environment[key] = value
        arguments = new.get("ProgramArguments")
        if not isinstance(arguments, list) or len(arguments) < 2:
            raise ValueError("scheduler plist has no launcher arguments")
        old_launcher = str(old_app / "ops/launch_v35_macos_scheduler.sh")
        if arguments[1] != old_launcher:
            raise ValueError("scheduler launcher argument differs from the loaded release")
        arguments[1] = str(new_app / "ops/launch_v35_macos_scheduler.sh")
    else:
        raise ValueError(f"unknown service: {service}")
    parsed_env = env_from_plist(new)
    for key, value in env_updates.items():
        if parsed_env.get(key) != value:
            raise ValueError(f"staged {service} plist binding mismatch: {key}")
    if plistlib.loads(plistlib.dumps(new)) != new:
        raise ValueError(f"staged {service} plist does not round-trip")
    return new


def _launchd_snapshot(label: str) -> tuple[str, int]:
    result = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"launchctl print failed for {label}: {(result.stderr or result.stdout).strip()}")
    match = re.search(r"\bpid\s*=\s*(\d+)\b", result.stdout)
    if not match or int(match.group(1)) <= 0:
        raise RuntimeError(f"launchd did not report an active PID for {label}")
    return result.stdout, int(match.group(1))


def _write_exclusive(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _finalize_outer_manifest(service: str, candidate: dict[str, Any], final_root: Path, base_root: Path) -> dict[str, Any]:
    manifest = json.loads(json.dumps(candidate))
    item = manifest["candidate"]
    item["root"] = str(final_root)
    item["app_root"] = str(final_root / "app")
    item["formal_release_root"] = str(final_root.parent)
    item["release_id"] = RELEASE_IDS[service]
    item["activation_status"] = "NOT_ACTIVATED"
    if service == "scheduler":
        item["target_root"] = str(final_root)
        manifest["release_id"] = RELEASE_IDS[service]
    else:
        manifest.pop("release_id", None)
    if manifest.get("activation_status") != "NOT_ACTIVATED" or manifest.get("deployment_status") != "NOT_DEPLOYED":
        raise ValueError(f"{service} candidate is not inactive")
    base = manifest["source"]["hk_research_calendar_release_base"]
    if base.get("active_manifest_sha256") != BASELINE_RELEASES[service]["manifest_sha256"]:
        raise ValueError(f"{service} package lineage does not match current R2 preimage")
    if base.get("active_release_id") != BASELINE_RELEASES[service]["release_id"]:
        raise ValueError(f"{service} package lineage release ID changed")
    if base.get("data_copy_performed") is not False:
        raise ValueError(f"{service} package unexpectedly records data copy")
    for field in SAFETY_FIELDS:
        if manifest.get(field) is not False:
            raise ValueError(f"{service} candidate safety flag must be false: {field}")
    if service == "scheduler" and base.get("active_manifest_candidate_release_id") != BASELINE_RELEASES[service]["manifest_candidate_release_id"]:
        raise ValueError("scheduler R9 source provenance changed")
    return manifest


def _reviewed_candidate(service: str, package_review: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    release = next(row for row in json_object(RECEIPT_ROOT / "release_build_receipt.json")["services"] if row["service"] == service)
    reviewed = package_review["candidate_packages"][service]
    source_root = Path(release["candidate_root"])
    manifest_path = source_root / "release-manifest.json"
    source_manifest_sha = sha256_file(manifest_path)
    source_manifest = json_object(manifest_path)
    if source_manifest_sha != release["candidate_manifest_sha256"] or source_manifest_sha != reviewed["manifest_sha256"]:
        raise ValueError(f"{service} reviewed source manifest drifted")
    if reviewed["application_inventory_sha256"] != release["candidate_app_inventory_sha256"]:
        raise ValueError(f"{service} reviewed app inventory differs from build receipt")
    return source_root, source_manifest


def prepare() -> dict[str, Any]:
    if IDENTITY_PATH.exists() or LOCATION_RECEIPT_PATH.exists():
        raise FileExistsError("cutover identity/location receipt already exists; refusing overwrite")
    if sha256_file(PACKAGE_REVIEW_PATH) != PACKAGE_REVIEW_SHA256:
        raise ValueError("independent runtime-package review receipt SHA changed")
    package_review = json_object(PACKAGE_REVIEW_PATH)
    if package_review.get("findings", {}).get("P0") or package_review.get("findings", {}).get("P1") or package_review.get("findings", {}).get("P2"):
        raise ValueError("runtime-package review has findings")
    if package_review.get("status", {}).get("REVIEWED") != "PASS; exact R2-based app diffs and both package manifests/inventories match the frozen scope":
        raise ValueError("runtime-package review is not PASS")

    staging = BATCH_ROOT / "cutover_staging"
    staging.mkdir(parents=True, exist_ok=True)
    allowed_stage_names = {
        "api_candidate.plist", "scheduler_candidate.plist",
        "api_active_preimage.plist", "scheduler_active_preimage.plist",
    }
    unexpected_staging = [path for path in staging.iterdir() if path.name not in allowed_stage_names]
    if unexpected_staging:
        raise FileExistsError(f"unexpected cutover staging content: {unexpected_staging}")
    services: dict[str, Any] = {}
    baselines: dict[str, str] = {}
    published: list[Path] = []
    temp_roots: list[Path] = []
    try:
        for service in ("api", "scheduler"):
            base = BASELINE_RELEASES[service]
            source_root, source_manifest = _reviewed_candidate(service, package_review)
            final_root = base["release_root"].parent / RELEASE_IDS[service]
            if final_root.exists():
                raise FileExistsError(f"immutable final release path already exists: {final_root}")
            active_plist_raw = base["plist"].read_bytes()
            active_plist_sha = sha256(active_plist_raw)
            active_plist = plistlib.loads(active_plist_raw)
            if active_plist.get("Label") != base["label"]:
                raise ValueError(f"{service} active plist label mismatch")
            active_env = env_from_plist(active_plist)
            if active_env.get("V35_APP_ROOT") != str(base["release_root"] / "app"):
                raise ValueError(f"{service} active plist root differs from frozen R2 release")
            if active_env.get("V35_RELEASE_MANIFEST_SHA256") != base["manifest_sha256"]:
                raise ValueError(f"{service} active plist manifest pin differs from frozen R2 release")
            active_manifest_path = Path(active_env["V35_RELEASE_MANIFEST_PATH"])
            if active_manifest_path != base["release_root"] / "release-manifest.json" or sha256_file(active_manifest_path) != base["manifest_sha256"]:
                raise ValueError(f"{service} loaded outer release manifest differs from frozen R2 identity")
            process_output, active_pid = _launchd_snapshot(base["label"])
            if str(base["release_root"] / "app") not in process_output:
                raise ValueError(f"{service} launchd identity does not include the R2 app root")
            active_manifest = json_object(active_manifest_path)
            active_candidate = active_manifest.get("candidate", {})
            expected_outer_root = active_candidate.get("target_root") if service == "scheduler" else active_candidate.get("root")
            if expected_outer_root != str(base["release_root"]) or active_candidate.get("app_root") != str(base["release_root"] / "app"):
                raise ValueError(f"{service} R2 outer manifest root mismatch")
            if service == "api":
                identity_ok = active_candidate.get("release_id") == base["manifest_candidate_release_id"]
            else:
                identity_ok = active_manifest.get("release_id") == base["release_id"] and active_candidate.get("release_id") == base["manifest_candidate_release_id"]
            if not identity_ok:
                raise ValueError(f"{service} R2 actual/inner release ID provenance mismatch")

            active_entries = inventory(base["release_root"] / "app")
            actual_inventory_sha = canonical_sha(active_entries)
            declared_entries = active_manifest.get("application_inventory", {}).get("entries", [])
            declared_source = [row for row in declared_entries if not (row.get("kind") == "file" and Path(row["path"]).suffix == ".pyc" and "__pycache__" in Path(row["path"]).parts)]
            actual_source = [row for row in active_entries if not (row.get("kind") == "file" and Path(row["path"]).suffix == ".pyc" and "__pycache__" in Path(row["path"]).parts)]
            actual_cache = [row for row in active_entries if row not in actual_source]
            if actual_source != declared_source or canonical_sha(declared_entries) != active_manifest["application_inventory"]["aggregate_sha256"]:
                raise ValueError(f"{service} R2 source inventory differs from outer manifest")
            baseline_receipt = {
                "service": service,
                "release_root": str(base["release_root"]),
                "release_manifest_sha256": base["manifest_sha256"],
                "actual_app_aggregate_sha256": actual_inventory_sha,
                "actual_app_entry_count": len(active_entries),
                "runtime_generated_unmanifested_entries": actual_cache,
                "source_inventory_sha256": canonical_sha(actual_source),
            }
            baseline_path = RECEIPT_ROOT / f"{service}_baseline_application_inventory_20261007.json"
            baseline_bytes = (json.dumps(baseline_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
            if baseline_path.exists():
                if baseline_path.read_bytes() != baseline_bytes:
                    raise ValueError(f"existing {service} baseline inventory receipt differs from current evidence")
            else:
                _write_exclusive(baseline_path, baseline_bytes)
            baseline_sha = sha256_file(baseline_path)
            baselines[service] = baseline_sha

            temp_root = Path(tempfile.mkdtemp(prefix=f".{RELEASE_IDS[service]}-", dir=final_root.parent))
            temp_roots.append(temp_root)
            shutil.copytree(source_root / "app", temp_root / "app", symlinks=True)
            final_manifest = _finalize_outer_manifest(service, source_manifest, final_root, base["release_root"])
            copied_inventory = inventory(temp_root / "app")
            expected_inventory = final_manifest["application_inventory"]["entries"]
            if copied_inventory != expected_inventory or canonical_sha(copied_inventory) != final_manifest["application_inventory"]["aggregate_sha256"]:
                raise ValueError(f"{service} copied app tree differs from independently reviewed inventory")
            outer_manifest_path = temp_root / "release-manifest.json"
            outer_manifest_path.write_text(json.dumps(final_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            manifest_sha = sha256_file(outer_manifest_path)
            os.replace(temp_root, final_root)
            temp_roots.remove(temp_root)
            published.append(final_root)

            candidate_plist = _replace_plist_paths(
                service,
                active_plist,
                old_app=base["release_root"] / "app",
                new_root=final_root,
                manifest_sha=manifest_sha,
            )
            plist_path = staging / f"{service}_candidate.plist"
            candidate_plist_bytes = plistlib.dumps(candidate_plist, fmt=plistlib.FMT_XML, sort_keys=False)
            if plist_path.exists():
                if plist_path.read_bytes() != candidate_plist_bytes:
                    raise ValueError(f"existing staged {service} plist differs from current candidate")
            else:
                _write_exclusive(plist_path, candidate_plist_bytes)
            backup_path = staging / f"{service}_active_preimage.plist"
            if backup_path.exists():
                if backup_path.read_bytes() != active_plist_raw:
                    raise ValueError(f"existing {service} active plist preimage changed")
            else:
                _write_exclusive(backup_path, active_plist_raw)

            candidate_inventory = final_manifest["application_inventory"]
            candidate_app = final_root / "app"
            module_rel = "infrastructure/runtime_graph/service.py"
            module_entry = next(row for row in candidate_inventory["entries"] if row.get("path") == module_rel)
            services[service] = {
                "base_active_label": base["label"],
                "base_active_plist_path": str(base["plist"]),
                "base_active_plist_sha256": active_plist_sha,
                "base_active_pid": active_pid,
                "base_release_root": str(base["release_root"]),
                "base_release_manifest_path": str(active_manifest_path),
                "base_release_manifest_sha256": base["manifest_sha256"],
                "base_manifest_candidate_release_id": base["manifest_candidate_release_id"],
                "base_active_release_id": base["release_id"],
                "base_app_inventory_sha256": actual_inventory_sha,
                "base_baseline_inventory_path": str(baseline_path),
                "base_baseline_inventory_sha256": baseline_sha,
                "candidate_root": str(final_root),
                "candidate_app_root": str(candidate_app),
                "candidate_release_id": RELEASE_IDS[service],
                "candidate_manifest_path": str(final_root / "release-manifest.json"),
                "candidate_manifest_sha256": manifest_sha,
                "candidate_app_inventory_sha256": candidate_inventory["aggregate_sha256"],
                "candidate_app_inventory_entry_count": candidate_inventory["entry_count"],
                "candidate_plist_path": str(plist_path),
                "candidate_plist_sha256": sha256_file(plist_path),
                "candidate_preimage_plist_path": str(backup_path),
                "candidate_preimage_plist_sha256": sha256_file(backup_path),
                "candidate_module_relative_path": module_rel,
                "candidate_module_sha256": module_entry["sha256"],
                "runtime_cache_paths": [row["path"] for row in actual_cache],
            }
            # Validate exactly the required launch bindings and preserved command line.
            env_after = env_from_plist(candidate_plist)
            if candidate_plist.get("Label") != base["label"] or candidate_plist.get("WorkingDirectory") != str(candidate_app):
                raise ValueError(f"{service} candidate launchd label/working directory mismatch")
            if env_after.get("V35_APP_ROOT") != str(candidate_app) or env_after.get("V35_RELEASE_ID") != RELEASE_IDS[service] or env_after.get("V35_RELEASE_MANIFEST_SHA256") != manifest_sha:
                raise ValueError(f"{service} candidate launchd environment does not bind outer manifest")
            if service == "api" and candidate_plist["ProgramArguments"][active_plist["ProgramArguments"].index("--host"):] != active_plist["ProgramArguments"][active_plist["ProgramArguments"].index("--host"):]:
                # API host, port, and selection-root argv must be byte-for-byte preserved.
                raise ValueError("API host/port/stage-selection-root command arguments changed")
            if service == "scheduler" and candidate_plist["ProgramArguments"][0] != active_plist["ProgramArguments"][0]:
                raise ValueError("scheduler launcher executable changed")
            services[service]["candidate_plist_bindings_verified"] = True
            api_host_index = active_plist["ProgramArguments"].index("--host") if service == "api" else None
            services[service]["api_command_args_preserved"] = service != "api" or candidate_plist["ProgramArguments"][api_host_index:] == active_plist["ProgramArguments"][api_host_index:]
            services[service]["scheduler_launcher_args_preserved"] = service != "scheduler" or candidate_plist["ProgramArguments"][0] == active_plist["ProgramArguments"][0]
            services[service]["live_launchd_status_sha256"] = sha256(process_output.encode())

        identity = {
            "schema_version": "v4.hk_research_calendar_cutover_identity.v1",
            "batch_id": BATCH_ID,
            "package_review_receipt_path": str(PACKAGE_REVIEW_PATH),
            "package_review_receipt_sha256": PACKAGE_REVIEW_SHA256,
            "api_readback_path": str(READBACK_PATH),
            "api_readback_sha256": sha256_file(READBACK_PATH),
            "expected_independent_reviewer": "/root/hk_scheduler_reviewer",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "api": services["api"],
            "scheduler": services["scheduler"],
        }
        identity_bytes = (json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        _write_exclusive(IDENTITY_PATH, identity_bytes)
        prepare_receipt = {
            "schema_version": "v4.hk_research_calendar_final_release_location.v1",
            "status": "PREPARED_PENDING_CUTOVER_REVIEW_AND_ROOT_AUTHORIZATION",
            "candidate_services": {name: {key: value for key, value in row.items() if key not in {"runtime_cache_paths"}} for name, row in services.items()},
            "candidate_identity_path": str(IDENTITY_PATH),
            "candidate_identity_sha256": sha256(identity_bytes),
            "backend_path": str(BACKEND_PATH),
            "backend_sha256": BACKEND_SHA256,
            "active_service_action_performed": False,
            "service_action_performed": False,
            "stage_labels_restarted": False,
            "data_root_touched": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        _write_exclusive(LOCATION_RECEIPT_PATH, (json.dumps(prepare_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
        return prepare_receipt
    except BaseException:
        for temp_root in temp_roots:
            if temp_root.exists():
                shutil.rmtree(temp_root)
        # Do not roll back immutable published candidates or receipts here;
        # retain them as evidence and require an explicit disposition.
        raise


def load_backend() -> Any:
    if sha256_file(BACKEND_PATH) != BACKEND_SHA256:
        raise RuntimeError("parallel tested cutover helper changed; re-review before use")
    spec = importlib.util.spec_from_file_location("hk_research_calendar_cutover_backend", BACKEND_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the frozen cutover helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _verify_frozen_active(backend: Any, service: str) -> tuple[dict[str, Any], int]:
    item = backend.service_identity(service)
    active_path = Path(item["base_active_plist_path"])
    backend.require_sha(active_path, item["base_active_plist_sha256"], service=service, phase="VERIFY_ACTIVE_PLIST")
    plist = plistlib.loads(active_path.read_bytes())
    env = backend.plist_environment(plist)
    app_root = Path(item["base_release_root"]) / "app"
    if plist.get("Label") != item["base_active_label"] or env.get("V35_APP_ROOT") != str(app_root):
        raise backend.GateError(f"{service} active plist changed from frozen R2 identity")
    if env.get("V35_RELEASE_MANIFEST_SHA256") != item["base_release_manifest_sha256"]:
        raise backend.GateError(f"{service} active manifest pin changed")
    manifest_path = Path(item["base_release_manifest_path"])
    backend.require_sha(manifest_path, item["base_release_manifest_sha256"], service=service, phase="VERIFY_ACTIVE_MANIFEST")
    manifest = json_object(manifest_path)
    candidate = manifest.get("candidate") or {}
    root_field = candidate.get("target_root") if service == "scheduler" else candidate.get("root")
    if root_field != item["base_release_root"] or candidate.get("app_root") != str(app_root):
        raise backend.GateError(f"{service} R2 outer manifest binding changed")
    if service == "api":
        identity_ok = candidate.get("release_id") == item["base_manifest_candidate_release_id"]
    else:
        identity_ok = manifest.get("release_id") == item["base_active_release_id"] and candidate.get("release_id") == item["base_manifest_candidate_release_id"]
    if not identity_ok:
        raise backend.GateError(f"{service} R2 outer/inner release lineage changed")
    actual_entries = backend.inventory(app_root)
    source_entries, cache_entries = backend.split_runtime_cache(actual_entries)
    declared_entries = (manifest.get("application_inventory") or {}).get("entries")
    if not isinstance(declared_entries, list):
        raise backend.GateError(f"{service} R2 manifest has no application inventory")
    expected_source, _manifest_cache = backend.split_runtime_cache(declared_entries)
    if source_entries != expected_source or backend.inventory_sha256(declared_entries) != manifest["application_inventory"]["aggregate_sha256"]:
        raise backend.GateError(f"{service} R2 active source inventory differs from outer manifest")
    baseline_path = Path(item["base_baseline_inventory_path"])
    backend.require_sha(baseline_path, item["base_baseline_inventory_sha256"], service=service, phase="VERIFY_R2_BASELINE_INVENTORY")
    baseline = json_object(baseline_path)
    expected_cache = baseline.get("runtime_generated_unmanifested_entries")
    if not isinstance(expected_cache, list) or cache_entries != expected_cache:
        raise backend.GateError(f"{service} R2 runtime cache differs from the frozen inventory")
    observed_app_sha = backend.inventory_sha256(actual_entries)
    if observed_app_sha != item["base_app_inventory_sha256"]:
        raise backend.GateError(f"{service} R2 app inventory changed")
    output, pid = backend.launchctl_status(service)
    if pid != item["base_active_pid"] or str(app_root) not in output:
        raise backend.GateError(f"{service} active launchd PID/root changed")
    if baseline.get("actual_app_aggregate_sha256") != observed_app_sha or baseline.get("release_manifest_sha256") != item["base_release_manifest_sha256"]:
        raise backend.GateError(f"{service} baseline receipt is inconsistent")
    plist["_runtime_cache_observed"] = {
        "full_inventory_sha256": observed_app_sha,
        "source_inventory_sha256": backend.inventory_sha256(source_entries),
        "cache_inventory_sha256": backend.inventory_sha256(cache_entries),
        "cache_entry_count": len(cache_entries),
    }
    return plist, pid


def _verify_review_receipt(backend: Any, service: str) -> dict[str, Any]:
    if not REVIEW_RECEIPT.is_file():
        raise backend.GateError(f"independent final-package/cutover review is missing: {REVIEW_RECEIPT}")
    receipt = json_object(REVIEW_RECEIPT)
    identity = backend.frozen_identity()
    expected = {
        "candidate_identity_sha256": backend.EXPECTED_IDENTITY_SHA256,
        "verdict": "PASS",
        "behavior_verified": "PASS",
        "actual_diff_inspected": True,
        "independent_reviewer": identity["expected_independent_reviewer"],
        "api_manifest_sha256": identity["api"]["candidate_manifest_sha256"],
        "api_inventory_sha256": identity["api"]["candidate_app_inventory_sha256"],
        "scheduler_manifest_sha256": identity["scheduler"]["candidate_manifest_sha256"],
        "scheduler_inventory_sha256": identity["scheduler"]["candidate_app_inventory_sha256"],
        "api_readback_sha256": identity["api_readback_sha256"],
    }
    mismatches = [key for key, value in expected.items() if receipt.get(key) != value]
    reviewed = receipt.get("reviewed_services")
    if not isinstance(reviewed, list) or service not in reviewed:
        mismatches.append("reviewed_services")
    if mismatches:
        raise backend.GateError("independent cutover review does not match final packages: " + ", ".join(mismatches))
    return receipt


def _verify_api_runtime(backend: Any, timeout_seconds: int = 30) -> dict[str, Any]:
    identity = backend.service_identity("api")
    expected_module = {
        "path": str(Path(identity["candidate_app_root"]) / identity["candidate_module_relative_path"]),
        "sha256": identity["candidate_module_sha256"],
    }
    url = "http://127.0.0.1:8873/api/v3/runtime-graph/status"
    response: dict[str, Any] | None = None
    response_identity_header: str | None = None
    deadline = backend.time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while backend.time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as handle:
                if handle.status != 200:
                    raise backend.GateError(f"runtime identity endpoint HTTP {handle.status}")
                response_identity_header = handle.headers.get("X-V35-Runtime-Identity-SHA256")
                response = json.load(handle)
            break
        except Exception as exc:
            last_error = exc
            backend.time.sleep(0.5)
    if response is None:
        raise backend.GateError(f"runtime identity endpoint unavailable: {last_error}")
    runtime = response.get("runtime_identity")
    if not isinstance(runtime, dict):
        raise backend.GateError("runtime identity endpoint omitted runtime_identity")
    required_bindings = {
        "app_root": identity["candidate_app_root"],
        "declared_app_root": identity["candidate_app_root"],
        "release_id": identity["candidate_release_id"],
        "release_id_declared": identity["candidate_release_id"],
        "release_manifest_path": identity["candidate_manifest_path"],
        "release_manifest_sha256": identity["candidate_manifest_sha256"],
        "release_manifest_sha256_declared": identity["candidate_manifest_sha256"],
    }
    for field, expected in required_bindings.items():
        if runtime.get(field) != expected:
            raise backend.GateError(f"runtime identity mismatch for {field}: {runtime.get(field)!r}")
    for field in ("app_root_status", "release_manifest_status", "release_manifest_sha_status", "selected_modules_status"):
        if runtime.get(field) != "VERIFIED":
            raise backend.GateError(f"runtime identity component is not VERIFIED: {field}={runtime.get(field)!r}")
    if runtime.get("release_id_status") not in {"VERIFIED", "DECLARED_ONLY"}:
        raise backend.GateError(f"runtime release ID has an unexpected state: {runtime.get('release_id_status')!r}")
    if runtime.get("plist_binding_status") not in {"VERIFIED", "CANNOT_CONFIRM"}:
        raise backend.GateError(f"runtime plist binding has an unexpected state: {runtime.get('plist_binding_status')!r}")
    if response_identity_header != runtime.get("identity_payload_sha256"):
        raise backend.GateError("runtime identity response header/payload SHA mismatch")
    _output, endpoint_pid = backend.launchctl_status("api")
    if runtime.get("pid") != endpoint_pid:
        raise backend.RuntimeIdentityDrift("runtime identity endpoint PID differs from the exact launchd label")
    modules = runtime.get("selected_imported_modules")
    matches = [row for row in modules or [] if isinstance(row, dict) and row.get("module") == "infrastructure.runtime_graph.service"]
    if len(matches) != 1 or matches[0].get("path") != expected_module["path"] or matches[0].get("sha256") != expected_module["sha256"] or matches[0].get("status") != "VERIFIED":
        raise backend.GateError("runtime graph service module identity does not match the reviewed candidate")
    if runtime.get("safety") != {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}:
        raise backend.GateError("runtime identity safety flags changed")

    # The existing HTTP contract has no date-parameterized calendar probe.
    # Verify the exact candidate module hash above, then call its pure calendar
    # helpers locally with bytecode writes disabled.
    behavior_code = (
        "import json; from infrastructure.runtime_graph import service; "
        "print(json.dumps({'hk_20261005':service._calendar_decision('hk_securities_trade_day','20261005'),"
        "'cross_20261005':service._calendar_decision('a_or_hk_securities_trade_day','20261005'),"
        "'connect_20261005':service._calendar_decision('a_or_hk_connect_trade_day','20261005'),"
        "'a_only_20260403':service._calendar_decision('a_or_hk_securities_trade_day','20260403'),"
        "'closed_20261004':service._calendar_decision('a_or_hk_securities_trade_day','20261004'),"
        "'next_after_20261004':service._next_market_trade_date('20261004','hk_securities')}))"
    )
    candidate_plist = plistlib.loads(Path(identity["candidate_plist_path"]).read_bytes())
    env = dict(os.environ)
    env.update(backend.plist_environment(candidate_plist))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join((str(Path(identity["candidate_app_root"]) / "upstreams"), identity["candidate_app_root"]))
    result = subprocess.run([str(API_PYTHON), "-B", "-c", behavior_code], cwd=identity["candidate_app_root"], env=env, capture_output=True, text=True, check=False)
    if result.returncode:
        raise backend.GateError(f"candidate calendar behavior probe failed: {result.stderr[-1200:]}")
    behavior = json.loads(result.stdout.strip().splitlines()[-1])
    if behavior["hk_20261005"].get("should_run") is not True or behavior["cross_20261005"].get("should_run") is not True:
        raise backend.GateError("HK securities calendar did not open the 20261005 target")
    if behavior["connect_20261005"].get("should_run") is not False or behavior["next_after_20261004"] != "20261005":
        raise backend.GateError("HK Connect policy or HK securities next-date behavior changed")
    if behavior["a_only_20260403"].get("should_run") is not True or behavior["closed_20261004"].get("should_run") is not False:
        raise backend.GateError("A-only or closed-day calendar behavior changed")
    return {
        "endpoint": url,
        "http_status": 200,
        "runtime_identity_status": runtime.get("status"),
        "runtime_identity_components": {field: runtime.get(field) for field in ("release_id_status", "plist_binding_status", "runtime_dependency_manifest_status", "runtime_inventory_status", "receipt_status")},
        "runtime_identity_payload_sha256": runtime.get("identity_payload_sha256"),
        "runtime_identity_header_sha256": response_identity_header,
        "runtime_graph_module": expected_module,
        "calendar_behavior": behavior,
        "live_workload_snapshot_status": response.get("status"),
        "safety": runtime["safety"],
        "date_probe_method": "pure candidate package helper bound to the exact module SHA returned by the active API runtime identity endpoint",
    }


def _verify_process_cwd(backend: Any, service: str, loaded: dict[str, Any]) -> dict[str, Any]:
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    if not Path(lsof).is_file():
        raise backend.GateError("lsof is unavailable; cannot verify loaded process cwd")
    result = subprocess.run([lsof, "-a", "-p", str(loaded["pid"]), "-d", "cwd", "-Fn"], capture_output=True, text=True, check=False)
    expected = backend.service_identity(service)["candidate_app_root"]
    if result.returncode or f"n{expected}" not in result.stdout.splitlines():
        raise backend.RuntimeIdentityDrift(f"{service} process cwd is not the candidate app root")
    return {"pid": loaded["pid"], "cwd": expected, "cwd_verified": True}


def configure_backend(backend: Any) -> Any:
    if not IDENTITY_PATH.is_file():
        raise backend.GateError(f"cutover identity is missing; run prepare first: {IDENTITY_PATH}")
    identity_sha = sha256_file(IDENTITY_PATH)
    identity = json_object(IDENTITY_PATH)
    location_receipt = json_object(LOCATION_RECEIPT_PATH)
    if location_receipt.get("candidate_identity_sha256") != identity_sha or location_receipt.get("backend_sha256") != BACKEND_SHA256:
        raise backend.GateError("cutover identity/location receipt binding changed")
    if sha256_file(PACKAGE_REVIEW_PATH) != identity.get("package_review_receipt_sha256") or identity.get("package_review_receipt_sha256") != PACKAGE_REVIEW_SHA256:
        raise backend.GateError("independent runtime-package review receipt changed")
    if sha256_file(READBACK_PATH) != identity.get("api_readback_sha256"):
        raise backend.GateError("frozen release verification receipt changed")
    backend.EVIDENCE_ROOT = RECEIPT_ROOT
    backend.IDENTITY_PATH = IDENTITY_PATH
    backend.EXPECTED_IDENTITY_SHA256 = identity_sha
    backend.READBACK_PATH = READBACK_PATH
    backend.REVIEW_RECEIPT = REVIEW_RECEIPT
    backend.BASELINE_INVENTORY_SHA256 = {name: identity[name]["base_baseline_inventory_sha256"] for name in ("api", "scheduler")}
    backend.CONFIRMATIONS = {"api": "ACTIVATE_HK_RESEARCH_CALENDAR_ALL_API", "scheduler": "ACTIVATE_HK_RESEARCH_CALENDAR_ALL_SCHEDULER"}
    backend.ROLLBACK_CONFIRMATIONS = {"api": "ROLLBACK_HK_RESEARCH_CALENDAR_ALL_API", "scheduler": "ROLLBACK_HK_RESEARCH_CALENDAR_ALL_SCHEDULER"}
    backend.verify_frozen_active = lambda service: _verify_frozen_active(backend, service)
    backend.verify_reviewer_receipt = lambda service: _verify_review_receipt(backend, service)
    backend.verify_api_semantics = lambda timeout_seconds=30: _verify_api_runtime(backend, timeout_seconds)
    original_wait = backend.wait_for_loaded_candidate

    def wait_with_cwd(service: str, **kwargs: Any) -> dict[str, Any]:
        loaded = original_wait(service, **kwargs)
        loaded["process_cwd"] = _verify_process_cwd(backend, service, loaded)
        return loaded

    backend.wait_for_loaded_candidate = wait_with_cwd
    return backend


BATCH_APPLY_CONFIRMATION = "ACTIVATE_HK_RESEARCH_CALENDAR_ALL_API_AND_SCHEDULER"
BATCH_ROLLBACK_CONFIRMATION = "ROLLBACK_HK_RESEARCH_CALENDAR_ALL_API_AND_SCHEDULER"


def _active_release_state(backend: Any, service: str) -> tuple[str, int]:
    item = backend.service_identity(service)
    plist_path = Path(item["base_active_plist_path"])
    observed_plist_sha = sha256_file(plist_path)
    output, pid = backend.launchctl_status(service)
    base_app = str(Path(item["base_release_root"]) / "app")
    candidate_app = item["candidate_app_root"]
    if observed_plist_sha == item["candidate_plist_sha256"] and all(token in output for token in (candidate_app, item["candidate_release_id"], item["candidate_manifest_sha256"])):
        return "candidate", pid
    if observed_plist_sha == item["base_active_plist_sha256"] and base_app in output:
        return "baseline", pid
    raise backend.RuntimeIdentityDrift(f"{service} active plist/process identity is neither frozen baseline nor candidate")


def _has_service_operation_receipt(backend: Any, service: str) -> bool:
    operation_path = getattr(backend, "operation_path", None)
    if not callable(operation_path):
        return False
    return any(
        Path(operation_path(service, action)).is_file()
        for action in ("APPLIED", "AUTO_ROLLED_BACK", "ROLLED_BACK")
    )


def _is_launchd_label_absent(backend: Any, error: BaseException) -> bool:
    error_type = getattr(backend, "LaunchdLabelAbsent", None)
    return isinstance(error_type, type) and isinstance(error, error_type)


def _regular_file_sha256_no_follow(backend: Any, path: Path) -> str | None:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise backend.GateError("platform does not support no-follow plist recovery reads")
    try:
        descriptor = os.open(path, os.O_RDONLY | no_follow)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise backend.GateError(f"cannot safely open recovery file without following links: {path}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise backend.GateError(f"recovery path is not a regular file: {path}")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _active_plist_sha_or_none(backend: Any, active_plist: Path) -> str | None:
    return _regular_file_sha256_no_follow(backend, active_plist)


def _restore_missing_active_plist_from_claim(
    backend: Any,
    active_plist: Path,
    *,
    allowed_shas: set[str],
) -> str:
    if active_plist.is_symlink():
        raise backend.GateError(f"active plist is a symlink; refusing claim recovery: {active_plist}")
    pattern = f".{active_plist.name}.claim-*"
    claims = sorted(active_plist.parent.glob(pattern), key=lambda path: path.name)
    if len(claims) != 1:
        raise backend.GateError(
            f"missing active plist requires exactly one owned claim; found {len(claims)} for {active_plist}"
        )
    claim_dir = claims[0]
    expected_name = rf"\.{re.escape(active_plist.name)}\.claim-[0-9a-f]{{32}}"
    try:
        claim_metadata = claim_dir.lstat()
    except OSError as exc:
        raise backend.GateError(f"cannot inspect cutover claim directory: {claim_dir}") from exc
    if not re.fullmatch(expected_name, claim_dir.name) or not stat.S_ISDIR(claim_metadata.st_mode):
        raise backend.GateError(f"claim entry is not a recognized cutover claim directory: {claim_dir}")
    claim_path = claim_dir / "before.plist"
    try:
        children = sorted(child.name for child in claim_dir.iterdir())
    except OSError as exc:
        raise backend.GateError(f"cannot inspect cutover claim directory: {claim_dir}") from exc
    if children != ["before.plist"]:
        raise backend.GateError(f"claim directory has an unknown or incomplete layout: {claim_dir}")
    claim_sha = _regular_file_sha256_no_follow(backend, claim_path)
    if claim_sha is None:
        raise backend.GateError(f"claimed plist disappeared during recovery: {claim_path}")
    if claim_sha not in allowed_shas:
        raise backend.RuntimeIdentityDrift(
            f"claim bytes do not match the frozen baseline or candidate plist SHA: {claim_path}"
        )
    try:
        # Same-directory hard-link creation is exclusive: a concurrently
        # created active path is preserved and never replaced.
        os.link(claim_path, active_plist, follow_symlinks=False)
    except FileExistsError as exc:
        raise backend.GateError(
            f"active plist appeared during claim recovery; preserved it without overwrite: {active_plist}"
        ) from exc
    except OSError as exc:
        raise backend.GateError(f"could not restore the exact claimed plist without overwrite: {active_plist}") from exc
    restored_sha = _active_plist_sha_or_none(backend, active_plist)
    if restored_sha != claim_sha:
        raise backend.RuntimeIdentityDrift(
            f"active plist changed during claim recovery; expected {claim_sha}, observed {restored_sha}"
        )
    return restored_sha


def _restore_one_service(backend: Any, service: str) -> dict[str, Any]:
    identity = backend.service_identity(service)
    active_plist = Path(identity["base_active_plist_path"])
    allowed_plist_shas = {
        identity["base_active_plist_sha256"],
        identity["candidate_plist_sha256"],
    }
    observed_plist_sha = _active_plist_sha_or_none(backend, active_plist)
    if observed_plist_sha is None:
        observed_plist_sha = _restore_missing_active_plist_from_claim(
            backend,
            active_plist,
            allowed_shas=allowed_plist_shas,
        )
    if observed_plist_sha not in allowed_plist_shas:
        raise backend.RuntimeIdentityDrift(
            f"{service} active plist SHA is neither frozen baseline nor candidate; refusing recovery"
        )
    try:
        state, pid = _active_release_state(backend, service)
    except BaseException as probe_error:
        if not _is_launchd_label_absent(backend, probe_error) or observed_plist_sha not in allowed_plist_shas:
            raise
        # A controlled interruption can land after bootout but before plist
        # replacement/bootstrap. The frozen helper's automatic rollback path
        # handles either exact known plist state and starts the baseline.
        backend.rollback(
            service,
            reviewer=None,
            pid_before=int(identity.get("base_active_pid") or 0),
            automatic=True,
        )
        restored_pid = backend.verify_frozen_active(service)[1]
        return {
            "service": service,
            "state": "ROLLED_BACK_TO_FROZEN_BASELINE",
            "pid": restored_pid,
            "service_action_performed": True,
            "recovery_path": "automatic_restore_after_launchd_label_absent",
        }
    if state == "baseline":
        _active, verified_pid = backend.verify_frozen_active(service)
        return {
            "service": service,
            "state": "BASELINE_PRESENT",
            "pid": verified_pid or pid,
            "service_action_performed": False,
        }
    namespace = argparse.Namespace(service=service, confirm=backend.ROLLBACK_CONFIRMATIONS[service])
    backend.cmd_rollback(namespace)
    restored = backend.verify_frozen_active(service)[1]
    return {"service": service, "state": "ROLLED_BACK_TO_FROZEN_BASELINE", "pid": restored, "service_action_performed": True}


def _write_batch_receipt(
    backend: Any,
    *,
    action: str,
    status: str,
    attempted: list[str],
    restored: list[dict[str, Any]],
    error: str | None,
    interrupted: bool = False,
    failure_type: str | None = None,
    recovery_attempts: list[dict[str, Any]] | None = None,
    recovery_errors: list[dict[str, Any]] | None = None,
    unresolved_services: list[str] | None = None,
) -> Path:
    path = RECEIPT_ROOT / f"api_scheduler_cutover_batch_{action}_operation.json"
    payload = {
        "schema_version": "v4.hk_research_calendar_cutover_batch.v1",
        "status": status,
        "attempted_services": attempted,
        "restored_services": restored,
        "error": error,
        "interrupted": interrupted,
        "failure_type": failure_type,
        "recovery_attempts": recovery_attempts or [],
        "recovery_errors": recovery_errors or [],
        "unresolved_services": unresolved_services or [],
        "service_operation_receipts": {
            service: {
                action: str(backend.operation_path(service, action))
                for action in ("APPLIED", "AUTO_ROLLED_BACK", "ROLLED_BACK")
                if backend.operation_path(service, action).is_file()
            }
            for service in ("api", "scheduler")
        },
        "other_services_touched": False,
        "stage_labels_restarted": False,
        "data_root_touched": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    _write_exclusive(path, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    return path


def _error_detail(error: BaseException) -> str:
    message = str(error).replace("\n", " ")
    return f"{type(error).__name__}: {message[:1000]}"


def _is_controlled_interruption(error: BaseException) -> bool:
    return isinstance(error, (KeyboardInterrupt, SystemExit))


def _interrupted_before_service_touch(
    backend: Any,
    *,
    attempted: list[str],
    completed: list[str],
    error: BaseException,
) -> bool:
    if not _is_controlled_interruption(error) or completed or len(attempted) != 1:
        return False
    service = attempted[0]
    if _has_service_operation_receipt(backend, service):
        return False
    try:
        state, _pid = _active_release_state(backend, service)
    except BaseException:
        return False
    return state == "baseline"


def _recover_services_to_baseline(
    backend: Any,
    services: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    # The caller supplies the frozen recovery order explicitly.
    order = list(services)
    pending = order[:]
    restored_by_service: dict[str, dict[str, Any]] = {}
    attempts: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    unresolved: dict[str, str] = {}
    # A second bounded pass handles one-shot Ctrl-C/SystemExit during recovery.
    for attempt_number in (1, 2):
        retry: list[str] = []
        for service in pending:
            attempts.append({"service": service, "attempt": attempt_number})
            try:
                restored = _restore_one_service(backend, service)
            except BaseException as error:
                detail = _error_detail(error)
                errors.append({
                    "service": service,
                    "attempt": attempt_number,
                    "error": detail,
                    "interrupted": _is_controlled_interruption(error),
                })
                unresolved[service] = detail
                if attempt_number == 1:
                    retry.append(service)
            else:
                restored_by_service[service] = restored
                unresolved.pop(service, None)
        pending = retry
        if not pending:
            break
    restored_rows = [restored_by_service[service] for service in order if service in restored_by_service]
    return restored_rows, attempts, errors, list(unresolved)


def apply_batch(backend: Any, confirm: str) -> int:
    if confirm != BATCH_APPLY_CONFIRMATION:
        raise backend.GateError("batch-specific activation confirmation is required")
    # Verify both immutable candidates, independent review bindings, and both
    # live R2 preimages before touching either service.
    for service in ("api", "scheduler"):
        backend.verify_candidate(service)
        backend.verify_reviewer_receipt(service)
        backend.verify_frozen_active(service)
    attempted: list[str] = []
    completed: list[str] = []
    try:
        for service in ("api", "scheduler"):
            attempted.append(service)
            result = backend.cmd_apply(argparse.Namespace(service=service, confirm=backend.CONFIRMATIONS[service]))
            if result not in (None, 0):
                raise backend.GateError(f"{service} cutover returned nonzero status {result}")
            completed.append(service)
    except BaseException as apply_error:
        if _interrupted_before_service_touch(backend, attempted=attempted, completed=completed, error=apply_error):
            if isinstance(apply_error, KeyboardInterrupt):
                raise
            raise backend.GateError("batch apply exited before service touch; no service was changed") from apply_error
        restored, recovery_attempts, recovery_errors, unresolved = _recover_services_to_baseline(backend, list(reversed(attempted)))
        complete = not unresolved and len(restored) == len(attempted)
        interrupted = _is_controlled_interruption(apply_error)
        if interrupted:
            status = "INTERRUPTED_ALL_BASELINES_RESTORED" if complete else "INTERRUPTED_ROLLBACK_INCOMPLETE"
        else:
            status = "FAILED_ALL_BASELINES_RESTORED" if complete else "FAILED_ROLLBACK_INCOMPLETE"
        recovery_text = "; ".join(
            f"{item['service']} attempt {item['attempt']}: {item['error']}" for item in recovery_errors
        )
        error_text = _error_detail(apply_error)
        if recovery_text:
            error_text += f"; recovery_errors={recovery_text}"
        receipt_path = _write_batch_receipt(
            backend,
            action="apply",
            status=status,
            attempted=attempted,
            restored=restored,
            error=error_text,
            interrupted=interrupted,
            failure_type=type(apply_error).__name__,
            recovery_attempts=recovery_attempts,
            recovery_errors=recovery_errors,
            unresolved_services=unresolved,
        )
        label = "interrupted" if interrupted else "failed"
        raise backend.GateError(f"batch cutover {label}; {status}; receipt={receipt_path}; cause={error_text}") from apply_error
    receipt_path = _write_batch_receipt(backend, action="apply", status="BOTH_CANDIDATES_ACTIVE", attempted=attempted, restored=[], error=None)
    print(json.dumps({"status": "BOTH_CANDIDATES_ACTIVE", "batch_receipt": str(receipt_path), "other_services_touched": False}, ensure_ascii=False, indent=2))
    return 0


def rollback_batch(backend: Any, confirm: str) -> int:
    if confirm != BATCH_ROLLBACK_CONFIRMATION:
        raise backend.GateError("batch-specific rollback confirmation is required")
    states = {service: _active_release_state(backend, service) for service in ("api", "scheduler")}
    if any(state != "candidate" for state, _pid in states.values()):
        raise backend.GateError("batch rollback requires both frozen candidate identities to be active")
    attempted = ["scheduler", "api"]
    restored, recovery_attempts, recovery_errors, unresolved = _recover_services_to_baseline(backend, attempted)
    if recovery_errors:
        interrupted = any(error["interrupted"] for error in recovery_errors)
        complete = not unresolved and len(restored) == len(attempted)
        if interrupted:
            status = "INTERRUPTED_ALL_BASELINES_RESTORED" if complete else "INTERRUPTED_ROLLBACK_INCOMPLETE"
        else:
            status = "FAILED_ALL_BASELINES_RESTORED" if complete else "FAILED_ROLLBACK_INCOMPLETE"
        error_text = "; ".join(
            f"{item['service']} attempt {item['attempt']}: {item['error']}" for item in recovery_errors
        )
        receipt_path = _write_batch_receipt(
            backend,
            action="rollback",
            status=status,
            attempted=attempted,
            restored=restored,
            error=error_text,
            interrupted=interrupted,
            failure_type="KeyboardInterrupt/SystemExit" if interrupted else "RecoveryError",
            recovery_attempts=recovery_attempts,
            recovery_errors=recovery_errors,
            unresolved_services=unresolved,
        )
        label = "interrupted" if interrupted else "failed"
        raise backend.GateError(f"batch rollback {label}; {status}; receipt={receipt_path}; errors={error_text}")
    receipt_path = _write_batch_receipt(backend, action="rollback", status="BOTH_BASELINES_RESTORED", attempted=attempted, restored=restored, error=None, recovery_attempts=recovery_attempts)
    print(json.dumps({"status": "BOTH_BASELINES_RESTORED", "batch_receipt": str(receipt_path), "other_services_touched": False}, ensure_ascii=False, indent=2))
    return 0


def run_backend(args: argparse.Namespace) -> int:
    backend = configure_backend(load_backend())
    sys.argv = [str(BACKEND_PATH), args.action, "--service", args.service]
    if args.action in ("apply", "rollback"):
        sys.argv.extend(["--confirm", args.confirm or ""])
    return backend.main()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("prepare", help="copy reviewed app trees to final inactive release roots and stage exact plists")
    for action in ("preflight", "apply", "rollback"):
        command = subs.add_parser(action)
        command.add_argument("--service", choices=("api", "scheduler"), required=True)
        if action in ("apply", "rollback"):
            command.add_argument("--confirm", default="")
    for action in ("apply-batch", "rollback-batch"):
        command = subs.add_parser(action)
        command.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            print(json.dumps(prepare(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.action == "apply-batch":
            return apply_batch(configure_backend(load_backend()), args.confirm)
        if args.action == "rollback-batch":
            return rollback_batch(configure_backend(load_backend()), args.confirm)
        return run_backend(args)
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError, plistlib.InvalidFileException) as exc:
        print(f"HK research-calendar cutover blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
