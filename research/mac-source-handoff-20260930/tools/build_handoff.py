#!/usr/bin/env python3
"""Build a read-only source/evidence handoff from the current V4 checkout."""

from __future__ import annotations

import ast
import hashlib
import json
import plistlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


HANDOFF = Path(__file__).resolve().parents[1]
REPO = HANDOFF.parents[1]
SOURCE = HANDOFF / "source"
EVIDENCE = HANDOFF / "evidence"
REFERENCES = HANDOFF / "references"

SOURCE_EXTENSIONS = {".py", ".pyi", ".ts", ".tsx", ".vue", ".js", ".jsx", ".css", ".html", ".json", ".sh"}
SECURITY_PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    re.compile(rb"\bsk-[A-Za-z0-9]{48,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(rb"(?i)\bBearer\s+[A-Za-z0-9._-]{24,}"),
]

STAGE_ROOT_MODULES = [
    "ops.run_stage_center_nodes",
    "ops.run_stage_center_tick",
    "ops.run_scheduled_slot",
    "ops.macos_research_panel_daily",
    "ops.run_hkconnect_0915_0920_capture",
    "ops.materialize_stage_acquisition_universe",
    "stage_center.runner",
    "stage_center.selection",
    "stage_center.live_collectors",
    "stage_center.raw_store",
    "stage_center.consumer",
    "stage_center.scheduler",
    "stage_center.candidate_input",
    "stage_center.acquisition",
    "stage_center.hk_universe_preflight",
    "infrastructure.tdx_minute_replay_provider",
    "infrastructure.hkconnect_stage_replay_provider",
    "infrastructure.stage_quote_provider",
    "infrastructure.stage_source_roots",
    "infrastructure.preselection_pool_store",
    "domains.preselection",
    "domains.stages",
    "domains.stage_scoring",
    "upstreams.v3_shared_data.scripts.live_acquisition.pytdx_exhq",
    "upstreams.v3_shared_data.scripts.live_acquisition.futu_minute",
    "upstreams.v3_shared_data.shared_data.collectors",
    "upstreams.v3_shared_data.shared_data.hk_0_2",
    "apps.api.v35_api.app",
    "apps.api.v35_api.review_router",
    "apps.api.v35_api.run",
]

MANAGER_ROOT_MODULES = [
    "ops.run_v35_macos_scheduler",
    "ops.materialize_manager_close_discovery",
    "ops.run_manager_announcement_cycle",
    "ops.refresh_manager_vibe_radar_binding",
    "infrastructure.scheduling.dispatcher",
    "infrastructure.scheduling.executor_registry",
    "infrastructure.scheduling.execution_ledger",
    "infrastructure.scheduling.manager_announcement_supervisor",
    "infrastructure.scheduling.manager_capture_retry",
    "infrastructure.scheduling.manager_close_executor",
    "infrastructure.manager_close_attempt",
    "infrastructure.manager_input_attestation",
    "v4.manager_research.service",
    "v4.manager_research.workspace",
    "v4.manager_research.hkex_provider",
    "v4.manager_research.workspace_plan",
    "v4.manager_research.plan_owner_dispatch",
    "v4.manager_research.workspace_actions",
    "v4.manager_research.workspace_discovery",
    "v4.manager_research.workspace_announcements",
    "v4.manager_research.announcement_source",
    "v4.manager_research.issuer_us_relations",
    "apps.api.v35_api.app",
    "apps.api.v35_api.manager_workbench_router",
    "apps.api.v35_api.manager_research_router",
]

OWNERS = {
    "stage_scheduler": {
        "scope": "stage",
        "label": "com.lexi.stage-center.scheduler",
        "plist": Path("/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist"),
        "app_root": Path("/Users/lexi/Desktop/学习/agents调试/v4_stage_root_hk_fix_20260928/line_fix_r1/today_combined_stage_fix_20260930/candidate/app"),
        "manifest": Path("/Users/lexi/Desktop/学习/agents调试/v4_stage_root_hk_fix_20260928/line_fix_r1/today_combined_stage_fix_20260930/candidate/release-manifest.json"),
    },
    "stage_hk_deadline": {
        "scope": "stage",
        "label": "com.lexi.stage-center.hk-deadline",
        "plist": Path("/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.hk-deadline.plist"),
        "app_root": Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/20260930-hk-deadline-startup-r1/app"),
        "manifest": Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/20260930-hk-deadline-startup-r1/release-manifest.json"),
    },
    "manager_api": {
        "scope": "manager",
        "label": "com.lexi.v35.api-only",
        "plist": Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist"),
        "app_root": Path("/Users/lexi/Desktop/学习/agents调试/v4_stage_root_hk_fix_20260928/line_fix_r1/normal_stage_readback_20260929/deployment_r9/app"),
        "manifest": Path("/Users/lexi/Desktop/学习/agents调试/v4_stage_root_hk_fix_20260928/line_fix_r1/normal_stage_readback_20260929/deployment_r9/release-manifest.json"),
    },
    "manager_scheduler_1555": {
        "scope": "manager",
        "label": "com.lexi.v35.scheduler",
        "plist": Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist"),
        "app_root": Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260929-manager-1555-pytdx-r1/app"),
        "manifest": Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260929-manager-1555-pytdx-r1/release-manifest.json"),
    },
}

SAFE_LAUNCH_KEYS = {
    "PYTHONPATH",
    "V35_APP_ROOT",
    "V35_RELEASE_ID",
    "V35_RELEASE_MANIFEST_PATH",
    "V35_RELEASE_MANIFEST_SHA256",
    "STAGE_CENTER_CONFIG",
    "STAGE_CENTER_RUNTIME_ROOT",
    "REVIEW_CORE_PACKAGE_ROOT",
    "V35_REVIEW_CORE_PACKAGE_ROOT",
    "V4_MANAGER_UNIVERSE_ROOT",
    "V4_MANAGER_SCREEN_AUTHORITY_ROOT",
    "V4_MANAGER_SECURITY_MASTER_ROOT",
}
PATH_LAUNCH_KEYS = {
    "PYTHONPATH",
    "V35_APP_ROOT",
    "V35_RELEASE_MANIFEST_PATH",
    "STAGE_CENTER_CONFIG",
    "STAGE_CENTER_RUNTIME_ROOT",
    "REVIEW_CORE_PACKAGE_ROOT",
    "V35_REVIEW_CORE_PACKAGE_ROOT",
}
SAFETY_ENV_KEYS = {"RESEARCH_ONLY", "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT", "production_allowed", "buy_gate_updated", "orders_sent"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def source_files_under(root: Path, rel_prefix: str) -> set[str]:
    base = root / rel_prefix
    if not base.exists():
        return set()
    return {
        p.relative_to(root).as_posix()
        for p in base.rglob("*")
        if p.is_file() and p.suffix in SOURCE_EXTENSIONS and "__pycache__" not in p.parts
    }


def module_candidates(root: Path, module: str) -> list[Path]:
    parts = module.split(".")
    candidates = []
    roots = [root, root / "upstreams/v3_shared_data", root / "upstreams"]
    for search_root in roots:
        file_path = search_root.joinpath(*parts).with_suffix(".py")
        package_path = search_root.joinpath(*parts, "__init__.py")
        if file_path.is_file():
            candidates.append(file_path.resolve())
        if package_path.is_file():
            candidates.append(package_path.resolve())
    return candidates


def local_imports(path: Path, root: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []
    rel = path.resolve().relative_to(root.resolve())
    module_parts = list(rel.with_suffix("").parts)
    if module_parts[-1] == "__init__":
        package_parts = module_parts[:-1]
    else:
        package_parts = module_parts[:-1]
    package = ".".join(package_parts)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package.split(".") if package else []
                keep = max(0, len(base_parts) - (node.level - 1))
                prefix = ".".join(base_parts[:keep])
                name = ".".join(part for part in (prefix, node.module or "") if part)
            else:
                name = node.module or ""
            if name:
                imports.append(name)
            if node.module is None:
                imports.extend(".".join(part for part in (name, alias.name) if part) for alias in node.names)
    return imports


def import_closure(root: Path, modules: list[str]) -> set[str]:
    found: set[str] = set()
    todo = list(modules)
    while todo:
        module = todo.pop()
        for path in module_candidates(root, module):
            try:
                rel = path.relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            if rel in found:
                continue
            found.add(rel)
            todo.extend(child for child in local_imports(path, root) if module_candidates(root, child))
    return found


def extra_paths(root: Path, scope: str) -> set[str]:
    paths: set[str] = set()
    # UI and API are shared consumer surfaces for both issue groups.
    paths |= source_files_under(root, "apps/api/v35_api")
    paths |= source_files_under(root, "apps/web/src")
    for exact in (
        "apps/web/package.json",
        "apps/web/package-lock.json",
        "apps/web/vite.config.ts",
        "apps/web/tsconfig.json",
        "apps/web/index.html",
        "apps/web/daily-research-command/index.html",
        "apps/web/manager-selection/index.html",
    ):
        if (root / exact).is_file():
            paths.add(exact)

    if scope == "stage":
        paths |= source_files_under(root, "stage_center")
        paths |= source_files_under(root, "ops/_run_stage_center_nodes_parts")
        paths |= source_files_under(root, "ops/_macos_research_panel_daily_parts")
        paths |= source_files_under(root, "upstreams/v3_shared_data/scripts/live_acquisition")
        paths |= source_files_under(root, "upstreams/v3_shared_data/shared_data")
        for exact in (
            "ops/run_stage_center_nodes.py",
            "ops/run_stage_center_tick.py",
            "ops/run_scheduled_slot.py",
            "ops/macos_research_panel_daily.py",
            "ops/run_hkconnect_0915_0920_capture.py",
            "ops/materialize_stage_acquisition_universe.py",
            "infrastructure/tdx_minute_replay_provider.py",
            "infrastructure/hkconnect_stage_replay_provider.py",
            "infrastructure/stage_quote_provider.py",
            "infrastructure/preselection_pool_store.py",
            "domains/preselection.py",
            "domains/stages.py",
            "domains/stage_scoring.py",
            "contracts/research.py",
            "contracts/research_day_product.py",
            "contracts/runtime_tasks.py",
            "contracts/stages.py",
            "contracts/trading_calendar.py",
            "contracts/trading_safety.py",
            "contracts/market_calendar_2026.json",
        ):
            if (root / exact).is_file():
                paths.add(exact)
    elif scope == "manager":
        paths |= source_files_under(root, "v4/manager_research")
        paths |= source_files_under(root, "infrastructure/scheduling")
        paths |= source_files_under(root, "ops/_run_v35_macos_scheduler_parts")
        for exact in (
            "ops/run_v35_macos_scheduler.py",
            "ops/launch_v35_macos_scheduler.sh",
            "ops/materialize_manager_close_discovery.py",
            "ops/run_manager_announcement_cycle.py",
            "ops/refresh_manager_vibe_radar_binding.py",
            "infrastructure/manager_close_attempt.py",
            "infrastructure/manager_input_attestation.py",
            "infrastructure/preselection_pool_store.py",
            "infrastructure/owned_io.py",
            "infrastructure/interprocess_lock.py",
            "infrastructure/scope_gate.py",
            "infrastructure/secure_evidence_fs.py",
            "domains/preselection.py",
            "domains/manager_research_evidence.py",
            "domains/manager_close_discovery.py",
            "contracts/research.py",
            "contracts/runtime_workloads.json",
            "contracts/trading_safety.py",
        ):
            if (root / exact).is_file():
                paths.add(exact)
    return paths


def project_paths(root: Path, scope: str) -> set[str]:
    modules = STAGE_ROOT_MODULES if scope == "stage" else MANAGER_ROOT_MODULES
    paths = import_closure(root, modules) | extra_paths(root, scope)
    return {p for p in paths if Path(p).suffix in SOURCE_EXTENSIONS and "__pycache__" not in Path(p).parts}


def git_state() -> tuple[set[str], dict[str, str]]:
    result = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain=v1", "-z"], check=True, stdout=subprocess.PIPE).stdout
    status: dict[str, str] = {}
    for chunk in result.split(b"\0"):
        if not chunk:
            continue
        line = chunk.decode("utf-8", "replace")
        code, path = line[:2], line[3:]
        status[path] = code
    tracked_result = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], check=True, stdout=subprocess.PIPE).stdout
    tracked = {p.decode("utf-8", "replace") for p in tracked_result.split(b"\0") if p}
    return tracked, status


def status_label(rel: str, tracked: set[str], status: dict[str, str]) -> str:
    code = status.get(rel)
    if code == "??":
        return "untracked"
    if code and "D" in code:
        return "tracked_deleted"
    if code:
        return "tracked_modified"
    if rel in tracked:
        return "tracked_clean"
    return "untracked_or_external"


def security_match(data: bytes) -> bool:
    return any(pattern.search(data) for pattern in SECURITY_PATTERNS)


def copy_bytes(source: Path, destination: Path) -> tuple[bytes, str | None]:
    data = source.read_bytes()
    if security_match(data):
        return data, "high_confidence_secret_pattern"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return data, None


def safe_launch_fields(owner: dict[str, Any], launch_rows: list[str]) -> dict[str, Any]:
    plist_path: Path = owner["plist"]
    if not plist_path.is_file():
        return {"label": owner["label"], "plist_path": str(plist_path), "status": "CANNOT_CONFIRM_PLIST_MISSING"}
    raw = plist_path.read_bytes()
    plist = plistlib.loads(raw)
    args = plist.get("ProgramArguments") or []
    values: dict[str, str] = {}
    for arg in args:
        if isinstance(arg, str) and "=" in arg:
            key, value = arg.split("=", 1)
            if key in SAFE_LAUNCH_KEYS or key in SAFETY_ENV_KEYS:
                values[key] = value
    for key, value in (plist.get("EnvironmentVariables") or {}).items():
        if key in SAFE_LAUNCH_KEYS or key in SAFETY_ENV_KEYS:
            values[str(key)] = str(value)
    filtered = {}
    for key, value in values.items():
        if key in SAFETY_ENV_KEYS:
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes"}:
                filtered[key] = True
            elif normalized in {"0", "false", "no"}:
                filtered[key] = False
            else:
                filtered[key] = "CANNOT_CONFIRM"
        elif key in PATH_LAUNCH_KEYS:
            filtered[key] = value
        elif key.endswith("SHA256") or key == "V35_RELEASE_ID":
            filtered[key] = value
    row = next((r for r in launch_rows if r.split()[-1:] == [owner["label"]]), None)
    fields = {
        "label": owner["label"],
        "plist_path": str(plist_path),
        "plist_raw_sha256": sha256_bytes(raw),
        "program": plist.get("Program"),
        "argv0": args[0] if args else None,
        "working_directory": plist.get("WorkingDirectory"),
        "selected_launch_fields": filtered,
        "selected_key_presence": {key: key in values for key in ("V4_MANAGER_UNIVERSE_ROOT", "V4_MANAGER_SCREEN_AUTHORITY_ROOT", "V4_MANAGER_SECURITY_MASTER_ROOT", "STAGE_CENTER_CONFIG", "V35_RELEASE_MANIFEST_PATH")},
        "launchctl_status_row": row,
    }
    if row:
        cells = row.split()
        pid_text = cells[0] if cells else "-"
        status_text = cells[1] if len(cells) > 1 else "unknown"
        fields["process"] = {"pid": int(pid_text) if pid_text.isdigit() else None, "launchctl_status": status_text}
        if pid_text.isdigit():
            ps = subprocess.run(["ps", "-p", pid_text, "-o", "pid=,comm="], text=True, capture_output=True, check=False).stdout.strip()
            fields["process"]["executable_identity"] = ps
            open_result = subprocess.run(["lsof", "-nP", "-p", pid_text], text=True, capture_output=True, check=False)
            observed = []
            app_root = str(owner["app_root"])
            for line in open_result.stdout.splitlines():
                path = line.split()[-1] if line.split() else ""
                if path.startswith(app_root + "/") and Path(path).suffix in {".py", ".pyc", ".so", ".dylib"}:
                    observed.append(path)
            fields["process"]["open_source_paths"] = sorted(set(observed))
            fields["process"]["loaded_code_bytes"] = "CANNOT_CONFIRM"
            fields["process"]["loaded_code_bytes_reason"] = "filesystem descriptors do not expose Python module bytes retained in process memory"
        else:
            fields["process"]["loaded_code_bytes"] = "CANNOT_CONFIRM_PROCESS_NOT_RUNNING"
    else:
        fields["process"] = {"pid": None, "loaded_code_bytes": "CANNOT_CONFIRM_NO_LAUNCHCTL_STATUS_ROW"}
    return fields


def release_manifest_index(owner: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    manifest_path: Path = owner["manifest"]
    if not manifest_path.is_file():
        return {}, {"path": str(manifest_path), "exists": False, "sha256": None, "entry_count": 0, "historical_build_mapping": "CANNOT_CONFIRM"}
    raw = manifest_path.read_bytes()
    document = json.loads(raw)
    entries = document.get("application_inventory", {}).get("entries", [])
    index = {str(item.get("path")): str(item.get("sha256")) for item in entries if item.get("path") and item.get("sha256")}
    keys = set()
    def collect_keys(value: Any) -> None:
        if isinstance(value, dict):
            keys.update(map(str, value.keys()))
            for child in value.values():
                collect_keys(child)
        elif isinstance(value, list):
            for child in value:
                collect_keys(child)
    collect_keys(document)
    commit_fields = sorted(k for k in keys if any(token in k.lower() for token in ("canonical_commit", "source_commit", "built_from_commit", "git_commit", "source_revision")))
    metadata = {
        "path": str(manifest_path),
        "exists": True,
        "sha256": sha256_bytes(raw),
        "byte_count": len(raw),
        "entry_count": len(entries),
        "declared_release_id": document.get("candidate", {}).get("release_id") or document.get("source", {}).get("release_id"),
        "revision_binding_field_names": commit_fields,
        "historical_build_mapping": "CANNOT_CONFIRM" if not commit_fields else "FIELD_PRESENT_VALUE_NOT_ASSUMED",
    }
    return index, metadata


def copy_scope(owner_name: str, owner: dict[str, Any], canonical_scope: set[str], tracked: set[str], git_status: dict[str, str], security_exclusions: list[dict[str, str]]) -> list[dict[str, Any]]:
    scope = owner["scope"]
    app_root: Path = owner["app_root"]
    runtime_paths = project_paths(app_root, scope) if app_root.is_dir() else set()
    all_paths = sorted(canonical_scope | runtime_paths)
    manifest_index, manifest_meta = release_manifest_index(owner)
    release_rows = []
    for rel in all_paths:
        canonical_path = REPO / rel
        canonical_row: dict[str, Any] = {"path": rel, "status": "missing", "bytes": None, "sha256": None, "git_blob_sha1": None}
        if canonical_path.is_file():
            data, blocked = copy_bytes(canonical_path, SOURCE / "canonical" / rel)
            if blocked:
                security_exclusions.append({"owner": "canonical", "path": rel, "reason": blocked, "sha256": sha256_bytes(data)})
            else:
                canonical_row = {
                    "path": rel,
                    "status": status_label(rel, tracked, git_status),
                    "bytes": len(data),
                    "sha256": sha256_bytes(data),
                    "git_blob_sha1": git_blob_sha1(data),
                }
        if app_root.is_dir() and (app_root / rel).is_file():
            source_path = app_root / rel
            data = source_path.read_bytes()
            blocked = security_match(data)
            row = {
                "owner": owner_name,
                "scope": scope,
                "path": rel,
                "status": "excluded_security_scan" if blocked else "copied",
                "bytes": len(data),
                "sha256": sha256_bytes(data),
                "git_blob_sha1": git_blob_sha1(data),
                "canonical_sha256": canonical_row.get("sha256"),
                "canonical_equal": canonical_row.get("sha256") == sha256_bytes(data) if canonical_row.get("sha256") else None,
                "manifest_sha256": manifest_index.get(rel),
                "manifest_match": (manifest_index.get(rel) == sha256_bytes(data)) if rel in manifest_index else None,
            }
            if blocked:
                security_exclusions.append({"owner": owner_name, "path": rel, "reason": "high_confidence_secret_pattern", "sha256": sha256_bytes(data)})
            else:
                destination = SOURCE / "releases" / owner_name / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            release_rows.append(row)
        else:
            release_rows.append({"owner": owner_name, "scope": scope, "path": rel, "status": "missing_in_configured_release", "bytes": None, "sha256": None, "git_blob_sha1": None, "canonical_sha256": canonical_row.get("sha256"), "manifest_sha256": manifest_index.get(rel), "manifest_match": None})
        release_rows[-1]["canonical_status"] = canonical_row.get("status")
        release_rows[-1]["canonical_git_blob_sha1"] = canonical_row.get("git_blob_sha1")
        release_rows[-1]["canonical_bytes"] = canonical_row.get("bytes")
    owner["manifest_metadata"] = manifest_meta
    owner["copied_source_count"] = sum(r.get("status") == "copied" for r in release_rows)
    owner["missing_source_count"] = sum(r.get("status") == "missing_in_configured_release" for r in release_rows)
    return release_rows


def copy_tests(tracked: set[str], git_status: dict[str, str], security_exclusions: list[dict[str, str]]) -> list[dict[str, Any]]:
    stage_names = ("test_stage", "test_hk", "test_manager_stage_rearm", "test_strict_stage_acquisition_v4", "test_preselection_slice", "test_preselection_optional_pools", "test_review_partial_stage_surface", "test_review_stage_regressions", "test_v4_core_stage_recovery")
    manager_names = ("test_manager", "test_review_manager", "test_preselection", "test_materialize_stage_workbench")
    tests = []
    for p in sorted((REPO / "tests").glob("test_*.py")):
        name = p.name
        scopes = []
        if any(name.startswith(prefix) for prefix in stage_names):
            scopes.append("stage")
        if any(name.startswith(prefix) for prefix in manager_names):
            scopes.append("manager")
        if not scopes:
            continue
        rel = p.relative_to(REPO).as_posix()
        data, blocked = copy_bytes(p, SOURCE / "tests" / rel)
        row = {"path": rel, "scopes": scopes, "status": status_label(rel, tracked, git_status), "bytes": len(data), "sha256": sha256_bytes(data), "git_blob_sha1": git_blob_sha1(data), "copied": not bool(blocked)}
        tests.append(row)
        if blocked:
            security_exclusions.append({"owner": "tests", "path": rel, "reason": blocked, "sha256": sha256_bytes(data)})
    for rel in ("tests/conftest.py", "pytest.ini"):
        p = REPO / rel
        if p.is_file() and rel not in {x["path"] for x in tests}:
            data, blocked = copy_bytes(p, SOURCE / "tests" / rel)
            tests.append({"path": rel, "scopes": ["shared"], "status": status_label(rel, tracked, git_status), "bytes": len(data), "sha256": sha256_bytes(data), "git_blob_sha1": git_blob_sha1(data), "copied": not bool(blocked)})
            if blocked:
                security_exclusions.append({"owner": "tests", "path": rel, "reason": blocked, "sha256": sha256_bytes(data)})
    return tests


def copy_test_dependencies(tracked: set[str], git_status: dict[str, str], security_exclusions: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Copy only the safe synthetic/helper and static contract closure of selected tests."""
    safe_paths = {
        "tests/announcement_autorun_fixtures.py": "synthetic_fixture_helper",
        "tests/fixtures/manager_workbench_b1_simulated.json": "synthetic_manager_fixture",
        "contracts/migration/stage_0925_tdxpy_frozen_regression_v1.json": "test_contract",
        "contracts/migration/v3_graph_baseline_v2.json": "test_contract",
        "contracts/migration/v35_replacement_inventory_v2.json": "test_contract",
    }
    copied_rows = []
    for rel, purpose in sorted(safe_paths.items()):
        source = REPO / rel
        if not source.is_file():
            copied_rows.append({"path": rel, "status": "missing_in_canonical", "copied": False, "purpose": purpose})
            continue
        data, blocked = copy_bytes(source, SOURCE / "test_dependencies" / rel)
        copied_rows.append({
            "path": rel,
            "handoff_path": (SOURCE / "test_dependencies" / rel).relative_to(HANDOFF).as_posix(),
            "status": status_label(rel, tracked, git_status),
            "bytes": len(data),
            "sha256": sha256_bytes(data),
            "git_blob_sha1": git_blob_sha1(data),
            "copied": not bool(blocked),
            "purpose": purpose,
        })
        if blocked:
            security_exclusions.append({"owner": "test_dependencies", "path": rel, "reason": blocked, "sha256": sha256_bytes(data)})

    # These are frozen provider/input row payloads. Retain only their identities and
    # explicitly mark dependent legacy tests non-replayable in this source packet.
    excluded_paths = {
        "tests/fixtures/stage_0925_20260730_tdxpy_input.json": [
            "tests/test_stage_0925_frozen_regression.py",
            "tests/test_stage_0925_vertical_parity.py",
            "tests/test_stage_eight_runs.py",
        ],
        "tests/fixtures/stage_0925_20260730_tdxpy_provider_snapshot.json": [
            "tests/test_stage_0925_vertical_parity.py",
            "tests/test_stage_eight_runs.py",
        ],
    }
    excluded_rows = []
    for rel, dependent_tests in sorted(excluded_paths.items()):
        source = REPO / rel
        if not source.is_file():
            excluded_rows.append({"path": rel, "status": "CANNOT_CONFIRM_SOURCE_MISSING", "content_copied": False, "dependent_tests": dependent_tests})
            continue
        data = source.read_bytes()
        excluded_rows.append({
            "path": rel,
            "status": "CANNOT_CONFIRM_NON_REPLAYABLE_RAW_MARKET_ROWS_EXCLUDED",
            "bytes": len(data),
            "sha256": sha256_bytes(data),
            "git_blob_sha1": git_blob_sha1(data),
            "content_copied": False,
            "reason": "raw quote/provider or stage input rows are excluded from the handoff",
            "dependent_tests": dependent_tests,
        })
    return copied_rows, excluded_rows


def copy_test_import_sources(test_rows: list[dict[str, Any]], test_dependency_rows: list[dict[str, Any]], canonical_rows: list[dict[str, Any]], tracked: set[str], git_status: dict[str, str], security_exclusions: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Copy local Python imports required by the selected test/helper sources."""
    modules = [str(Path(row["path"]).with_suffix("")).replace("/", ".") for row in test_rows if row.get("copied")]
    modules.extend(["tests.announcement_autorun_fixtures"])
    closure = import_closure(REPO, modules)
    already_present = {row.get("path") for row in canonical_rows + test_rows + test_dependency_rows}
    rows = []
    for rel in sorted(closure - already_present):
        source = REPO / rel
        data, blocked = copy_bytes(source, SOURCE / "test_dependencies" / rel)
        rows.append({
            "path": rel,
            "handoff_path": (SOURCE / "test_dependencies" / rel).relative_to(HANDOFF).as_posix(),
            "status": status_label(rel, tracked, git_status),
            "bytes": len(data),
            "sha256": sha256_bytes(data),
            "git_blob_sha1": git_blob_sha1(data),
            "copied": not bool(blocked),
            "purpose": "static_local_import_closure_of_selected_tests",
        })
        if blocked:
            security_exclusions.append({"owner": "test_import_closure", "path": rel, "reason": blocked, "sha256": sha256_bytes(data)})
    return rows


def copy_build_locks(tracked: set[str], git_status: dict[str, str], security_exclusions: list[dict[str, str]]) -> list[dict[str, Any]]:
    paths = ["pyproject.toml", "uv.lock", "apps/web/package.json", "apps/web/package-lock.json", "apps/web/vite.config.ts", "apps/web/tsconfig.json", "apps/web/index.html"]
    rows = []
    for rel in paths:
        p = REPO / rel
        if not p.is_file():
            rows.append({"path": rel, "status": "missing"})
            continue
        data, blocked = copy_bytes(p, SOURCE / "canonical" / rel)
        if blocked:
            security_exclusions.append({"owner": "build_locks", "path": rel, "reason": blocked, "sha256": sha256_bytes(data)})
        rows.append({"path": rel, "status": status_label(rel, tracked, git_status), "bytes": len(data), "sha256": sha256_bytes(data), "git_blob_sha1": git_blob_sha1(data), "copied": not bool(blocked)})
    return rows


def copy_stage14(security_exclusions: list[dict[str, str]]) -> list[dict[str, Any]]:
    source = Path("/Users/lexi/Desktop/学习/agents调试/v4_stage_root_hk_fix_20260928/line_fix_r1/pr12_pr13_mac_review_20260930/evidence_writer")
    payload = source / "publish"
    receipt = source / "PACK_RECEIPT.json"
    manifest = json.loads((payload / "MANIFEST.json").read_text(encoding="utf-8"))
    rels = ["publish/MANIFEST.json", "PACK_RECEIPT.json"] + [str(x["path"]) for x in manifest.get("files", [])]
    rows = []
    for rel in rels:
        src = source / rel
        dst = EVIDENCE / "stage14" / rel
        data, blocked = copy_bytes(src, dst)
        rows.append({"source_path": str(src), "handoff_path": dst.relative_to(HANDOFF).as_posix(), "bytes": len(data), "sha256": sha256_bytes(data), "git_blob_sha1": git_blob_sha1(data), "copied_exact_bytes": not bool(blocked)})
        if blocked:
            security_exclusions.append({"owner": "stage14", "path": rel, "reason": blocked, "sha256": sha256_bytes(data)})
    return rows


def launch_inventory() -> dict[str, Any]:
    rows = subprocess.run(["launchctl", "list"], check=False, text=True, capture_output=True).stdout.splitlines()
    result: dict[str, Any] = {"captured_by": "launchctl list rows and a strict plist field allowlist", "raw_plist_or_environment_copied": False, "owners": {}}
    for name, owner in OWNERS.items():
        fields = safe_launch_fields(owner, rows)
        config_path = fields.get("selected_launch_fields", {}).get("STAGE_CENTER_CONFIG")
        config_identity = None
        if config_path:
            path = Path(config_path)
            if path.is_file():
                config_bytes = path.read_bytes()
                config_identity = {
                    "path": str(path),
                    "bytes": len(config_bytes),
                    "sha256": sha256_bytes(config_bytes),
                    "content_copied": False,
                }
            else:
                config_identity = {"path": str(path), "exists": False, "sha256": None, "content_copied": False}
        manifest_index, manifest_meta = release_manifest_index(owner)
        expected_manifest = fields.get("selected_launch_fields", {}).get("V35_RELEASE_MANIFEST_SHA256")
        fields["configured_app_root"] = str(owner["app_root"])
        fields["configured_manifest_path"] = str(owner["manifest"])
        fields["manifest_disk"] = manifest_meta
        fields["manifest_hash_matches_launch_config"] = (expected_manifest == manifest_meta.get("sha256")) if expected_manifest else None
        fields["manifest_entry_count"] = len(manifest_index)
        fields["runtime_config_identity"] = config_identity
        fields["configured_release_id_hint"] = fields.get("selected_launch_fields", {}).get("V35_RELEASE_ID")
        result["owners"][name] = fields
    result["cross_layer_status"] = {
        "launch_configuration": "captured selected path/id/safety fields plus raw plist SHA only",
        "release_disk": "per-file SHA256/Git blob SHA1 and release-manifest comparison in source_inventory.json",
        "process_loaded_code_bytes": "CANNOT_CONFIRM for all owners; process listings and open file paths do not prove Python source bytes retained in memory",
        "manager_17_20_mapping": "CANNOT_CONFIRM; the 15:55 source receipt has a narrower owner label and does not prove the 17:20 original owner",
    }
    return result


def write_json(rel: str, obj: Any) -> None:
    path = HANDOFF / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    for directory in (SOURCE / "canonical", SOURCE / "releases", EVIDENCE / "stage14"):
        if directory.exists() and any(directory.iterdir()):
            raise SystemExit(f"Refusing to overwrite existing handoff payload: {directory}")
    tracked, git_status = git_state()
    security_exclusions: list[dict[str, str]] = []
    canonical_scopes = {
        "stage": project_paths(REPO, "stage"),
        "manager": project_paths(REPO, "manager"),
    }
    canonical_union = set().union(*canonical_scopes.values())
    canonical_rows = []
    for rel in sorted(canonical_union):
        path = REPO / rel
        if not path.is_file():
            canonical_rows.append({"path": rel, "status": "missing_in_canonical", "scopes": [s for s, paths in canonical_scopes.items() if rel in paths]})
            continue
        data, blocked = copy_bytes(path, SOURCE / "canonical" / rel)
        scopes = [s for s, paths in canonical_scopes.items() if rel in paths]
        row = {"path": rel, "scopes": scopes, "status": status_label(rel, tracked, git_status), "bytes": len(data), "sha256": sha256_bytes(data), "git_blob_sha1": git_blob_sha1(data), "copied": not bool(blocked)}
        canonical_rows.append(row)
        if blocked:
            security_exclusions.append({"owner": "canonical", "path": rel, "reason": blocked, "sha256": sha256_bytes(data)})

    release_rows = []
    for name, owner in OWNERS.items():
        release_rows.extend(copy_scope(name, owner, canonical_scopes[owner["scope"]], tracked, git_status, security_exclusions))

    test_rows = copy_tests(tracked, git_status, security_exclusions)
    test_dependency_rows, non_replayable_test_inputs = copy_test_dependencies(tracked, git_status, security_exclusions)
    test_import_source_rows = copy_test_import_sources(test_rows, test_dependency_rows, canonical_rows, tracked, git_status, security_exclusions)
    build_rows = copy_build_locks(tracked, git_status, security_exclusions)
    stage14_rows = copy_stage14(security_exclusions)
    runtime = launch_inventory()

    status_counts: dict[str, int] = {}
    for rel, status in git_status.items():
        status_counts[status] = status_counts.get(status, 0) + 1
    split_rows = [r for r in canonical_rows if "_parts/" in r.get("path", "")]
    split_counts: dict[str, int] = {}
    for row in split_rows:
        key = row.get("status", "unknown")
        split_counts[key] = split_counts.get(key, 0) + 1

    write_json("source_inventory.json", {
        "schema_version": "mac_source_handoff.source_inventory.v1",
        "repository_root": str(REPO),
        "canonical_head": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], check=True, text=True, capture_output=True).stdout.strip(),
        "canonical_source_rows": canonical_rows,
        "configured_release_rows": release_rows,
        "test_source_rows": test_rows,
        "test_dependency_rows": test_dependency_rows,
        "test_import_source_rows": test_import_source_rows,
        "non_replayable_test_inputs": non_replayable_test_inputs,
        "build_lock_rows": build_rows,
        "stage14_exact_copy_rows": stage14_rows,
        "git_status_counts": status_counts,
        "canonical_split_module_status_counts": split_counts,
        "dependency_method": "AST-resolved Python imports from scoped entrypoints plus complete Stage, manager-research, scheduler, API-router and web source split packages; no application execution",
        "scope_notes": [
            "Historical fixture payloads, local state/data, compiled files, caches, logs, LaunchAgent plists, and raw quote/minute rows are excluded; safe synthetic test helpers, static contract dependencies, and selected-test Python import closure are listed separately.",
            "Every canonical and release row retains its original repository-relative path; missing paths are explicit rows.",
            "Runtime configured release snapshots are separate per owner; no claim is made that disk bytes equal process memory bytes.",
        ],
    })
    write_json("runtime/runtime_inventory.json", runtime)
    write_json("security_scan.json", {
        "schema_version": "mac_source_handoff.security_scan.v1",
        "scope": "all files created under this handoff root at build time",
        "high_confidence_secret_patterns": ["private-key PEM markers", "GitHub tokens", "long OpenAI-style keys", "AWS access-key IDs", "Slack tokens", "long bearer tokens"],
        "source_credentials_modified": False,
        "raw_launchagent_or_environment_values_copied": False,
        "raw_quote_or_minute_rows_copied": False,
        "excluded_files": security_exclusions,
        "security_scan_status": "PASS" if not security_exclusions else "FAIL_REVIEW_REQUIRED",
    })

    write_json("source_build_receipt.json", {
        "schema_version": "mac_source_handoff.copy_receipt.v1",
        "handoff_path": str(HANDOFF),
        "canonical_source_file_count": sum(r.get("copied") is True for r in canonical_rows),
        "configured_release_file_count": sum(r.get("status") == "copied" for r in release_rows),
        "configured_release_missing_path_count": sum(r.get("status") == "missing_in_configured_release" for r in release_rows),
        "test_source_count": sum(r.get("copied") is True for r in test_rows),
        "test_dependency_file_count": sum(r.get("copied") is True for r in test_dependency_rows) + sum(r.get("copied") is True for r in test_import_source_rows),
        "test_import_source_count": sum(r.get("copied") is True for r in test_import_source_rows),
        "non_replayable_test_input_count": sum(r.get("content_copied") is False for r in non_replayable_test_inputs),
        "stage14_exact_file_count": sum(r.get("copied_exact_bytes") is True for r in stage14_rows),
        "security_exclusion_count": len(security_exclusions),
        "business_tests_run": False,
        "business_reruns_or_data_collection_performed": False,
        "copy_hash_verification": "computed from source bytes before writing; independent post-copy verification still required",
        "review_status": "PENDING_INDEPENDENT_REVIEW",
    })


if __name__ == "__main__":
    main()
