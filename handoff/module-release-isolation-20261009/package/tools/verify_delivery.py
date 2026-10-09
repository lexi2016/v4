#!/usr/bin/env python3
"""Verify the self-contained delivery package and optional ZIP byte-for-byte."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def fail(message: str) -> None:
    raise ValueError(message)


def extract_router_routes(path: Path) -> list[dict[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prefixes: set[str] = set()
    router_found = False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "router" for target in targets):
            continue
        value = node.value
        if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Name) or value.func.id != "APIRouter":
            continue
        router_found = True
        prefix_found = False
        for keyword in value.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                prefixes.add(keyword.value.value)
                prefix_found = True
        if not prefix_found:
            prefixes.add("")
    if not router_found or len(prefixes) != 1:
        fail(f"expected one literal APIRouter prefix in {path}")
    prefix = next(iter(prefixes)).rstrip("/")
    routes: list[dict[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "router":
                continue
            if decorator.func.attr.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant) or not isinstance(decorator.args[0].value, str):
                fail(f"non-literal router path in {path}:{node.lineno}")
            subpath = decorator.args[0].value
            full_path = prefix if not subpath else prefix + "/" + subpath.lstrip("/")
            routes.append({"method": decorator.func.attr.upper(), "path": full_path, "handler": node.name})
    return sorted(routes, key=lambda row: (row["method"], row["path"], row["handler"]))


def extract_app_route(path: Path, *, method: str, route_path: str, handler: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != handler:
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "app":
                continue
            if decorator.func.attr.upper() != method or not decorator.args:
                continue
            if isinstance(decorator.args[0], ast.Constant) and decorator.args[0].value == route_path:
                return True
    return False


def extract_app_routes(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    routes: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute)
                    or not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "app"
                    or decorator.func.attr.lower() not in {"get", "post", "put", "patch", "delete"}
                    or not decorator.args or not isinstance(decorator.args[0], ast.Constant)
                    or not isinstance(decorator.args[0].value, str)):
                continue
            routes.append((decorator.func.attr.upper(), decorator.args[0].value))
    return routes


def verify_source_snapshot(root: Path, contract: dict[str, Any]) -> tuple[list[str], int]:
    """Verify portable source preimages and the frozen route AST inventory."""
    errors: list[str] = []
    manifest_path = root / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "v4.module_release_isolation.source_snapshot.v1":
        errors.append("source snapshot manifest schema mismatch")
    if manifest.get("portable_bytes_included") is not True:
        errors.append("source snapshot is not marked portable")
    if manifest.get("fixed_git_remote_ref", "").startswith("CANNOT_CONFIRM") is not True:
        errors.append("source snapshot must preserve the unavailable fixed Git ref status")

    entries = manifest.get("entries")
    if not isinstance(entries, list):
        fail("source snapshot entries must be a list")
    archive_names: list[str] = []
    entry_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    checked = 0
    for record in entries:
        name = str(record.get("archive_path") or "")
        relative = Path(name)
        if (not name or relative.is_absolute() or ".." in relative.parts
                or not name.startswith("source_snapshot/")):
            errors.append(f"invalid source snapshot path: {name!r}")
            continue
        archive_names.append(name)
        identity = (str(record.get("source_id", "")), str(record.get("relativepath", "")))
        if identity in entry_by_identity:
            errors.append(f"duplicate source identity: {identity}")
        entry_by_identity[identity] = record
        path = root / relative
        try:
            data = path.read_bytes()
            checked += 1
        except OSError as exc:
            errors.append(f"missing source preimage {name}: {exc}")
            continue
        if record.get("status") != "SNAPSHOT":
            errors.append(f"source preimage is not marked SNAPSHOT: {name}")
        if len(data) != record.get("size_bytes"):
            errors.append(f"source preimage size mismatch: {name}")
        if sha256(data) != record.get("sha256"):
            errors.append(f"source preimage SHA-256 mismatch: {name}")
        if git_blob_sha1(data) != record.get("git_blob_sha1"):
            errors.append(f"source preimage Git blob SHA-1 mismatch: {name}")
    if len(archive_names) != len(set(archive_names)):
        errors.append("duplicate source snapshot archive paths")
    actual_snapshot_files = {
        path.relative_to(root).as_posix()
        for path in (root / "source_snapshot").rglob("*")
        if path.is_file()
    }
    if set(archive_names) != actual_snapshot_files:
        errors.append(
            "source snapshot closure mismatch: "
            f"missing={sorted(set(archive_names)-actual_snapshot_files)}, "
            f"extra={sorted(actual_snapshot_files-set(archive_names))}"
        )

    expected_active = {
        ("live_api_issue32_candidate", "apps/api/v35_api/app.py"),
        ("live_api_issue32_candidate", "apps/api/v35_api/manager_research_router.py"),
        ("live_api_issue32_candidate", "apps/api/v35_api/manager_workbench_router.py"),
    }
    if not expected_active.issubset(entry_by_identity):
        errors.append("active API route source snapshot inventory is incomplete")

    planned = manifest.get("planned_preimages")
    if not isinstance(planned, list):
        fail("planned_preimages must be a list")
    absent = {"deployment/com.lexi.v4.manager-api.plist", "deployment/com.lexi.v4.stage-api.plist"}
    absent_rows = {str(row.get("relativepath")): row for row in planned if isinstance(row, dict)}
    if set(absent_rows) != absent:
        errors.append("planned ABSENT preimage inventory changed")
    for name, row in absent_rows.items():
        if (row.get("status") != "ABSENT" or row.get("archive_path") is not None
                or any(row.get(key) is not None for key in ("sha256", "size_bytes", "git_blob_sha1"))):
            errors.append(f"planned preimage must remain explicitly ABSENT: {name}")

    parallel = manifest.get("parallel_implementation_in_progress")
    expected_parallel = {
        "apps/api/v35_api/module_proxy.py",
        "deployment/api_module_contracts.json",
    }
    if not isinstance(parallel, list):
        fail("parallel_implementation_in_progress must be a list")
    parallel_rows = {str(row.get("relativepath")): row for row in parallel if isinstance(row, dict)}
    if set(parallel_rows) != expected_parallel:
        errors.append("parallel implementation status inventory changed")
    for name, row in parallel_rows.items():
        if (row.get("status") != "PARALLEL_IMPLEMENTATION_IN_PROGRESS/NOT_BASELINE"
                or row.get("archive_path") is not None
                or any(row.get(key) is not None for key in ("sha256", "size_bytes", "git_blob_sha1"))
                or row.get("historical_design_preimage") != "ABSENT when architect authored original design plan; current in-progress bytes are not a stable baseline"):
            errors.append(f"parallel implementation must remain NOT_BASELINE: {name}")
        if any(Path(entry_name).name == Path(name).name for entry_name in archive_names):
            errors.append(f"parallel implementation was incorrectly frozen: {name}")

    sources = contract.get("sources", {})
    active_map = {
        "manager_research_router": ("apps/api/v35_api/manager_research_router.py", "manager_research_routes"),
        "manager_workbench_router": ("apps/api/v35_api/manager_workbench_router.py", None),
    }
    for source_key, (relative, routes_key) in active_map.items():
        source = sources.get(source_key, {})
        record = entry_by_identity.get(("live_api_issue32_candidate", relative))
        if record is None:
            errors.append(f"source snapshot route file unavailable: {relative}")
            continue
        if record.get("sha256") != source.get("sha256"):
            errors.append(f"route contract SHA differs from source snapshot: {source_key}")
            continue
        path = root / str(record["archive_path"])
        actual_routes = extract_router_routes(path)
        if routes_key is None:
            expected_routes = [row for row in contract.get("manager_other_routes", [])
                               if row.get("handler") == "read_workbench_research"]
        else:
            expected_routes = contract.get(routes_key, [])
        normalized_expected = sorted(
            [{"method": row["method"], "path": row["path"], "handler": row["handler"]}
             for row in expected_routes],
            key=lambda row: (row["method"], row["path"], row["handler"]),
        )
        if actual_routes != normalized_expected:
            errors.append(f"route AST differs from frozen {source_key} inventory")
    research = contract.get("manager_research_routes", [])
    if len(research) != 17:
        errors.append("manager research route inventory is not 17 endpoints")

    app_source = sources.get("manager_stage_selection_route", {})
    app_record = entry_by_identity.get(("live_api_issue32_candidate", "apps/api/v35_api/app.py"))
    preselection_record = entry_by_identity.get(("live_api_issue32_candidate", "apps/api/v35_api/preselection_router.py"))
    if not app_record:
        errors.append("manager stage-selection app source snapshot unavailable")
    elif app_record.get("sha256") != app_source.get("sha256"):
        errors.append("route contract SHA differs from stage-selection source snapshot")
    else:
        manager_route = next((row for row in contract.get("manager_other_routes", [])
                              if row.get("handler") == "manager_stage_selection"), None)
        app_path = root / str(app_record["archive_path"])
        if (not manager_route or not extract_app_route(
                app_path, method=manager_route["method"], route_path=manager_route["path"],
                handler=manager_route["handler"])):
            errors.append("manager stage-selection route differs from frozen app.py inventory")
        if not preselection_record:
            errors.append("preselection router source snapshot unavailable for Stage route inventory")
        else:
            expected_stage = {(row.get("method"), row.get("path"))
                              for row in contract.get("stage_routes", [])}
            stage_routes = set(extract_app_routes(app_path))
            stage_routes.update((row["method"], row["path"])
                                for row in extract_router_routes(root / str(preselection_record["archive_path"])))
            if not expected_stage.issubset(stage_routes):
                errors.append("Stage route AST differs from frozen six-route inventory")

    return errors, checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--verify-source-provenance", action="store_true",
                        help="also verify source files referenced by absolute provenance paths")
    args = parser.parse_args()
    root = args.package_root.resolve()
    errors: list[str] = []
    checked = 0
    source_checked = 0
    try:
        manifest_path = root / "package_manifest.json"
        manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != "v4.module_release_isolation.delivery.v1":
            fail("package manifest schema mismatch")
        records = manifest.get("files")
        if not isinstance(records, list):
            fail("package manifest files must be a list")
        if manifest.get("file_count") != len(records):
            errors.append("package manifest file_count does not match files list")
        if (manifest.get("architecture_status") != "DESIGN_ONLY"
                or manifest.get("implementation_status") != "NOT_RUN"
                or manifest.get("deployment_status") != "NOT_RUN"):
            errors.append("package manifest promotes design/implementation/deployment status")
        names: list[str] = []
        for record in records:
            name = str(record.get("path", ""))
            rel = Path(name)
            if not name or rel.is_absolute() or ".." in rel.parts or name == "package_manifest.json":
                errors.append(f"invalid package path: {name!r}")
                continue
            names.append(name)
            path = root / rel
            try:
                actual = sha256(path.read_bytes())
                checked += 1
                if actual != record.get("sha256"):
                    errors.append(f"SHA mismatch: {name}")
            except OSError as exc:
                errors.append(f"missing package file {name}: {exc}")
        if len(names) != len(set(names)):
            errors.append("duplicate file paths in package manifest")
        disk_files = {
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and p != manifest_path
        }
        if set(names) != disk_files:
            errors.append(f"manifest closure mismatch: missing={sorted(set(names)-disk_files)}, extra={sorted(disk_files-set(names))}")

        receipt = json.loads((root / "ARCHITECTURE_RECEIPT.json").read_text(encoding="utf-8"))
        arch_bytes = (root / "ARCHITECTURE_HANDOFF.md").read_bytes()
        if sha256(arch_bytes) != receipt.get("sha256"):
            errors.append("architect handoff SHA does not match receipt")
        if receipt.get("status") != "DESIGN_ONLY" or receipt.get("implementation") != "NOT_RUN" or receipt.get("deployment") != "NOT_RUN":
            errors.append("architecture receipt must remain DESIGN_ONLY / NOT_RUN")

        contract = json.loads((root / "route_contract.json").read_text(encoding="utf-8"))
        snapshot_errors, source_checked = verify_source_snapshot(root, contract)
        errors.extend(snapshot_errors)
        stage = contract.get("stage_routes", [])
        research = contract.get("manager_research_routes", [])
        manager_other = contract.get("manager_other_routes", [])
        if len(stage) != 6 or len(research) != 17 or len(manager_other) != 2:
            errors.append("route inventory counts changed from frozen scope (6 Stage, 17 research, 2 Manager other)")
        route_keys = [(r.get("method"), r.get("path")) for r in [*stage, *research, *manager_other]]
        if len(route_keys) != len(set(route_keys)):
            errors.append("duplicate method/path in route contract")
        proxy = contract.get("proxy_policy", {})
        if proxy.get("fixed_loopback_upstreams_only") is not True or proxy.get("retry_post") is not False or proxy.get("fallback_to_old_handler") is not False:
            errors.append("proxy safety contract changed")

        current = json.loads((root / "manager_evidence/current_runtime_identity.json").read_text(encoding="utf-8"))
        r3 = json.loads((root / "manager_evidence/r3_candidate_summary.json").read_text(encoding="utf-8"))
        services = {row.get("label"): row for row in current.get("services", [])}
        if set(services) != {"com.lexi.v35.api-only", "com.lexi.v35.scheduler", "com.lexi.stage-center.scheduler"}:
            errors.append("current service identity inventory changed")
        for label, row in services.items():
            if label == "com.lexi.v35.api-only":
                flags = row.get("safety_flags", {})
            elif label == "com.lexi.v35.scheduler":
                flags = row.get("manager_binding", {})
            else:
                env = row.get("environment", {})
                flags = {
                    "research_only": env.get("RESEARCH_ONLY", "").lower() in {"1", "true"},
                    "production_allowed": env.get("PRODUCTION_ALLOWED", "").lower() == "true",
                    "buy_gate_updated": env.get("BUY_GATE_UPDATED", "").lower() == "true",
                    "orders_sent": env.get("ORDERS_SENT", "").lower() == "true",
                }
            if flags.get("research_only") is not True or flags.get("production_allowed") is not False or flags.get("buy_gate_updated") is not False or flags.get("orders_sent") is not False:
                errors.append(f"unsafe or missing flags in {label}")
        if services.get("com.lexi.stage-center.scheduler", {}).get("launchctl_state") != "not running":
            errors.append("Stage scheduler status was changed or misrepresented")
        if r3.get("flags") != {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}:
            errors.append("R3 safety flags changed")
        if r3.get("runtime_and_review", {}).get("independent_review") != "PENDING" or r3.get("runtime_and_review", {}).get("shared_release") != "NOT_RUN":
            errors.append("R3 status was promoted beyond its receipt")

        if args.verify_source_provenance:
            result = subprocess.run(
                [sys.executable, str(root / "tools/verify_manager_evidence.py"), "--root", str(root)],
                text=True, capture_output=True, check=False,
            )
            if result.returncode != 0:
                errors.append("external source provenance verification failed: " + (result.stderr or result.stdout).strip())
            else:
                print(result.stdout.strip())
            source_manifest = json.loads((root / "source_manifest.json").read_text(encoding="utf-8"))
            for record in source_manifest.get("entries", []):
                external = Path(str(record.get("source_root", ""))) / str(record.get("relativepath", ""))
                if not external.is_file():
                    errors.append(f"source preimage unavailable at provenance path: {external}")
                    continue
                data = external.read_bytes()
                if (sha256(data) != record.get("sha256")
                        or len(data) != record.get("size_bytes")
                        or git_blob_sha1(data) != record.get("git_blob_sha1")):
                    errors.append(f"source preimage differs from portable snapshot: {external}")
            sources = contract.get("sources", {})
            for source_key, routes_key in (("manager_research_router", "manager_research_routes"),
                                           ("manager_workbench_router", None)):
                source = sources.get(source_key, {})
                path = Path(str(source.get("path", "")))
                if not path.is_file():
                    errors.append(f"source route file unavailable: {path}")
                    continue
                if sha256(path.read_bytes()) != source.get("sha256"):
                    errors.append(f"source route SHA mismatch: {path}")
                    continue
                actual_routes = extract_router_routes(path)
                if routes_key is None:
                    expected_routes = [row for row in manager_other if row.get("handler") == "read_workbench_research"]
                else:
                    expected_routes = contract.get(routes_key, [])
                normalized_expected = sorted(
                    [{"method": row["method"], "path": row["path"], "handler": row["handler"]}
                     for row in expected_routes],
                    key=lambda row: (row["method"], row["path"], row["handler"]),
                )
                if actual_routes != normalized_expected:
                    errors.append(f"route AST differs from frozen {source_key} inventory")
            app_source = sources.get("manager_stage_selection_route", {})
            app_path = Path(str(app_source.get("path", "")))
            if not app_path.is_file():
                errors.append(f"manager stage-selection app source unavailable: {app_path}")
            elif sha256(app_path.read_bytes()) != app_source.get("sha256"):
                errors.append(f"manager stage-selection app SHA mismatch: {app_path}")
            else:
                row = next((r for r in manager_other if r.get("handler") == "manager_stage_selection"), None)
                if not row or not extract_app_route(app_path, method=row["method"], route_path=row["path"], handler=row["handler"]):
                    errors.append("manager stage-selection route differs from frozen app.py inventory")

        if args.zip:
            archive_path = args.zip.resolve()
            if not archive_path.is_file():
                errors.append(f"ZIP missing: {archive_path}")
            else:
                with zipfile.ZipFile(archive_path) as archive:
                    broken = archive.testzip()
                    if broken:
                        errors.append(f"ZIP CRC failed at {broken}")
                    expected = set(names) | {"package_manifest.json"}
                    actual = set(archive.namelist())
                    if expected != actual:
                        errors.append(f"ZIP inventory mismatch: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
                    for name in sorted(expected & actual):
                        data = archive.read(name)
                        disk = (root / name).read_bytes() if name != "package_manifest.json" else manifest_path.read_bytes()
                        if data != disk:
                            errors.append(f"ZIP content differs from package source: {name}")
                sidecar = archive_path.with_suffix(archive_path.suffix + ".sha256")
                if not sidecar.is_file():
                    errors.append(f"ZIP SHA sidecar missing: {sidecar}")
                else:
                    expected_sha = sidecar.read_text(encoding="utf-8").split()[0]
                    if sha256(archive_path.read_bytes()) != expected_sha:
                        errors.append("ZIP SHA does not match sidecar")

    except (OSError, json.JSONDecodeError, zipfile.BadZipFile, ValueError, KeyError) as exc:
        errors.append(str(exc))

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: package manifest, route/safety contracts, {checked} package hashes, "
          f"and {source_checked} portable source preimages verified"
          + ("; ZIP inventory and bytes verified" if args.zip else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
