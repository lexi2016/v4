#!/usr/bin/env python3
"""Guarded active-owner import of the saved 2026-10-06 HK catalog refs.

The default invocation is a read-only preflight. Import and rollback require
separate explicit flags and a reviewer-produced approval receipt. This file
is task-local preparation; it was not run with either mutating flag.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
import plistlib
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_DAILY_REPAIR_20261007")
STATE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research")
EXPECTED_PID: int | None = None
DEFAULT_ACTIVE_RELEASE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-daily-pool-recovery-r1-20261007-api-candidate/app")
LAUNCHD_LABEL = "com.lexi.v35.api-only"
LAUNCHD_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
TARGET_DATE = "20261007"
PUBLICATION_DATE = "20261006"
API_TARGET_DATE = TARGET_DATE
API_PUBLICATION_DATE = "2026-10-06"
EXPECTED_AGGREGATE = "b5ea2c12b3c0ad380f308fd7fffc849383bbe9656ea44e0b2f9f8bbcd0f06d49"
EXPECTED_CATALOG_RUN_ID = "028ce0e6bdc448248c21f1da3cf1b2f6"
EXPECTED_CATALOG_PRODUCT_SHA256 = "0cc10a09e8a06514a1981d2dad0642ac2e294e67ace71e8843f1afcd0de2df7e"
SOURCE_RECORDS = {
    "v4/manager_research/announcement_catalog.py": "25b07260dbe6591a6b26c3560d1873fe2e01fd76edd07a55d977bb80b0696a68",
    "v4/manager_research/workspace_announcements.py": "0916a0191568e32aee6dd1bd5e17bcdc6a32ae7dbe733a6ce25d5388eacbd9e4",
    "v4/manager_research/announcement_analysis.py": "29cedc701bc94ca1b8e12106432b85639c990bf98a74445dac2144ba05e64903",
    "v4/manager_research/service.py": "195ad063124a785ec61b828018f7fc12706bf39dbde4898a031187ef4976b5b0",
}
CANARY_STATE = TASK_ROOT / "daily_runs/20261007_20261006/candidate_state"
SAVED_CATALOG = CANARY_STATE / "manager/workspace_announcements/20261007/eastmoney_date_catalog/20261006/latest.json"
OPS_ROOT = TASK_ROOT / "daily_runs/20261007_20261006/active_import"
ATTEMPT_FILE = OPS_ROOT / "import_attempt.json"
RECEIPT_FILE = OPS_ROOT / "import_receipt.json"
ROLLBACK_ATTEMPT_FILE = OPS_ROOT / "rollback_attempt.json"
ROLLBACK_RECEIPT_FILE = OPS_ROOT / "rollback_receipt.json"
APPROVAL_FILE = TASK_ROOT / "OPS_REVIEW_APPROVAL.json"
LEGACY_OWNER = STATE_ROOT / "workspace_announcements/20260930/eastmoney_date_catalog/20260929/analysis.v1.json"
EXPECTED_LEGACY_OWNER_SHA = "61d8d33acba85bf4f10fa8efedfbe6e391a74cb5ae57277decf28514bb6fa465"
API_BASE = "http://127.0.0.1:8873/api/v4/manager/research/announcements"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def candidate_source_check() -> dict[str, Any]:
    receipt = read_json(TASK_ROOT / "CANDIDATE_SOURCE_RECEIPT_R2_P2.json")
    if receipt.get("candidate_source_test_aggregate_sha256") != EXPECTED_AGGREGATE:
        raise ValueError("FROZEN_SOURCE_RECEIPT_AGGREGATE_MISMATCH")
    observed: dict[str, str] = {}
    for rel, expected in SOURCE_RECORDS.items():
        observed[rel] = digest((TASK_ROOT / "candidate" / rel).read_bytes())
        if observed[rel] != expected:
            raise ValueError("FROZEN_SOURCE_FILE_HASH_MISMATCH:" + rel)
    return {"aggregate_sha256": EXPECTED_AGGREGATE, "source_sha256": observed}


def _process_field(pid: int, field: str) -> str:
    result = subprocess.run(["ps", "-p", str(pid), "-o", field + "="], capture_output=True, text=True, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return ""
    return result.stdout.strip()


def process_identity(pid: int) -> dict[str, Any]:
    command = _process_field(pid, "command")
    if not command:
        raise ValueError("ACTIVE_API_PROCESS_NOT_FOUND")
    env_out = subprocess.run(["ps", "eww", "-p", str(pid)], capture_output=True, text=True, check=False)
    if env_out.returncode != 0:
        raise ValueError("ACTIVE_API_PROCESS_ENV_UNREADABLE")
    line = " ".join(env_out.stdout.splitlines())
    env: dict[str, str | None] = {}
    for key in ("V4_MANAGER_RESEARCH_STATE_ROOT", "V35_DATA_ROOT", "V35_APP_ROOT",
                "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256",
                "V35_STAGE_CENTER_SELECTION_ROOT", "RESEARCH_ONLY", "production_allowed",
                "PRODUCTION_ALLOWED", "buy_gate_updated", "BUY_GATE_UPDATED",
                "orders_sent", "ORDERS_SENT"):
        match = re.search(r"(?:^|\s)" + re.escape(key) + r"=(.*?)(?=\s[A-Za-z_][A-Za-z0-9_]*=|$)", line)
        env[key] = match.group(1).strip() if match else None
    cwd_out = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True, check=False)
    cwd = next((row[1:] for row in cwd_out.stdout.splitlines() if row.startswith("n")), None)
    if "apps.api.v35_api.run" not in command or "--port 8873" not in command:
        raise ValueError("ACTIVE_PROCESS_IS_NOT_EXPECTED_LOCAL_V35_API")
    if not cwd:
        raise ValueError("ACTIVE_API_PROCESS_CWD_UNAVAILABLE")
    return {"pid": pid, "command": command, "cwd": cwd, "env": env}


def _program_environment(plist_value: dict[str, Any]) -> dict[str, str]:
    args = plist_value.get("ProgramArguments")
    if not isinstance(args, list) or not args or args[0] != "/usr/bin/env":
        raise ValueError("LAUNCHD_API_PROGRAM_ARGUMENTS_UNSUPPORTED")
    values: dict[str, str] = {}
    for item in args[1:]:
        if not isinstance(item, str):
            raise ValueError("LAUNCHD_API_PROGRAM_ARGUMENT_INVALID")
        if "=" not in item:
            break
        key, value = item.split("=", 1)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value
    return values


def launchd_owner_identity(expected_root: Path | None = None,
                           expected_pid: int | None = None) -> dict[str, Any]:
    """Resolve the live API from its existing LaunchAgent, never a saved PID."""
    plist_path = LAUNCHD_PLIST.resolve()
    try:
        raw_plist = plist_path.read_bytes()
        payload = plistlib.loads(raw_plist)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise ValueError("LIVE_API_LAUNCHAGENT_UNAVAILABLE") from exc
    if payload.get("Label") != LAUNCHD_LABEL or payload.get("KeepAlive") is not True:
        raise ValueError("LIVE_API_LAUNCHAGENT_IDENTITY_MISMATCH")
    program_env = _program_environment(payload)
    if ("apps.api.v35_api.run" not in payload.get("ProgramArguments", [])
            or "--port" not in payload.get("ProgramArguments", [])
            or payload.get("ProgramArguments", [])[payload["ProgramArguments"].index("--port") + 1] != "8873"):
        raise ValueError("LIVE_API_LAUNCHAGENT_COMMAND_MISMATCH")
    working = Path(str(payload.get("WorkingDirectory", ""))).resolve()
    declared_root = Path(str(program_env.get("V35_APP_ROOT", ""))).resolve()
    if not working.is_dir() or declared_root != working:
        raise ValueError("LIVE_API_LAUNCHAGENT_ROOT_MISMATCH")
    if expected_root is not None and working != expected_root.expanduser().resolve():
        raise ValueError("LIVE_API_LAUNCHAGENT_ACTIVE_ROOT_DRIFT")
    target = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"
    listing = subprocess.run(["launchctl", "print", target], capture_output=True, text=True, check=False)
    if listing.returncode != 0:
        raise ValueError("LIVE_API_LAUNCHD_SERVICE_NOT_LOADED")
    output = listing.stdout
    loaded_path_match = re.search(r"(?m)^\s*path\s*=\s*(.+?)\s*$", output)
    pid_match = re.search(r"(?m)^\s*pid\s*=\s*(\d+)\s*$", output)
    state_match = re.search(r"(?m)^\s*state\s*=\s*(\S+)\s*$", output)
    if (not loaded_path_match or Path(loaded_path_match.group(1)).resolve() != plist_path
            or not pid_match or not state_match or state_match.group(1) != "running"):
        raise ValueError("LIVE_API_LAUNCHD_RUNTIME_NOT_RUNNING")
    pid = int(pid_match.group(1))
    if expected_pid is not None and pid != expected_pid:
        raise ValueError("LIVE_API_PID_DOES_NOT_MATCH_LAUNCHD_OWNER")
    process = process_identity(pid)
    if (Path(process["cwd"]).resolve() != working
            or Path(process["env"].get("V35_APP_ROOT") or "").resolve() != working
            or Path(process["env"].get("V4_MANAGER_RESEARCH_STATE_ROOT") or "").resolve() != STATE_ROOT.resolve()
            or Path(process["env"].get("V35_DATA_ROOT") or "").resolve() != Path(
                "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data").resolve()):
        raise ValueError("LIVE_API_PROCESS_LAUNCHD_BINDING_MISMATCH")
    for key, expected in (("RESEARCH_ONLY", "1"), ("production_allowed", "false"),
                          ("PRODUCTION_ALLOWED", "false"), ("buy_gate_updated", "false"),
                          ("BUY_GATE_UPDATED", "false"), ("orders_sent", "false"),
                          ("ORDERS_SENT", "false")):
        if program_env.get(key) != expected:
            raise ValueError("LIVE_API_SAFETY_BINDING_DRIFT:" + key)
    return {"pid": pid, "service_target": target, "label": LAUNCHD_LABEL,
            "plist_path": str(plist_path), "plist_sha256": digest(raw_plist),
            "plist_payload": payload, "program_environment": program_env,
            "active_root": str(working), "process": process}


def release_source_hashes(release_root: Path) -> dict[str, str]:
    result = {}
    for rel in SOURCE_RECORDS:
        path = release_root / rel
        if not path.is_file():
            raise ValueError("RELEASE_SOURCE_FILE_MISSING:" + rel)
        result[rel] = digest(path.read_bytes())
    return result


def api_get(path: str) -> tuple[int, bytes, dict[str, Any]]:
    request = urllib.request.Request(API_BASE + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read()
        return response.status, raw, json.loads(raw.decode("utf-8"))


def legacy_readback() -> dict[str, Any]:
    query = urllib.parse.urlencode({"date": "20260930", "publication_date": "20260929"})
    status, raw, body = api_get("/analysis?" + query)
    analysis = body.get("analysis") or {}
    stock_selection = analysis.get("stock_selection") or {}
    source_catalog = body.get("source_catalog") or {}
    result = {
        "http_status": status,
        "raw_sha256_observed": digest(raw),
        "analysis_status": analysis.get("status"),
        "source_status": source_catalog.get("status"),
        "manager_announcement_count": source_catalog.get("manager_announcement_count"),
        "manager_issuer_count": source_catalog.get("manager_issuer_count"),
        "stock_count": stock_selection.get("stock_count"),
        "selected_stock_count": stock_selection.get("selected_stock_count"),
        "safety": {key: body.get(key) for key in ("RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent")},
    }
    if not (
        status == 200
        and analysis.get("status") == "VERIFIED"
        and source_catalog.get("status") == "COMPLETE"
        and source_catalog.get("manager_announcement_count") == 234
        and source_catalog.get("manager_issuer_count") == 140
        and stock_selection.get("stock_count") == 140
        and stock_selection.get("selected_stock_count") == 23
        and body.get("RESEARCH_ONLY") is True
        and body.get("production_allowed") is False
        and body.get("buy_gate_updated") is False
        and body.get("orders_sent") is False
    ):
        raise ValueError("LEGACY_20260929_CONTRACT_DRIFT")
    if not LEGACY_OWNER.is_file() or digest(LEGACY_OWNER.read_bytes()) != EXPECTED_LEGACY_OWNER_SHA:
        raise ValueError("LEGACY_OWNER_BYTES_DRIFT")
    result["legacy_owner_sha256"] = digest(LEGACY_OWNER.read_bytes())
    return result


def target_analysis_baseline() -> dict[str, Any]:
    query = urllib.parse.urlencode({"date": TARGET_DATE, "publication_date": PUBLICATION_DATE})
    status, raw, body = api_get("/analysis?" + query)
    analysis = body.get("analysis") or {}
    source = body.get("source_catalog") or {}
    selection = analysis.get("stock_selection") or {}
    target_date = body.get("target_trade_date")
    publication_date = body.get("publication_date")
    date_binding_verified = (
        target_date == API_TARGET_DATE
        and publication_date == API_PUBLICATION_DATE
        and (analysis.get("target_trade_date") is None or analysis.get("target_trade_date") == API_TARGET_DATE)
        and (analysis.get("publication_date") is None or analysis.get("publication_date") == API_PUBLICATION_DATE)
    )
    expected_preimport = (
        status == 200
        and date_binding_verified
        and analysis.get("status") == "NOT_IMPORTED"
        and source.get("status") == "NOT_RUN"
        and source.get("catalog_run_id") is None
        and source.get("catalog_product_sha256") is None
        and selection.get("status") == "NOT_ASSESSED"
        and selection.get("stock_count") is None
        and selection.get("selected_stock_count") is None
    )
    return {
        "http_status": status, "raw_sha256_observed": digest(raw),
        "target_trade_date": target_date, "publication_date": publication_date,
        "date_binding_verified": date_binding_verified,
        "analysis_status": analysis.get("status"), "source_status": source.get("status"),
        "source_run_id": source.get("catalog_run_id"), "source_product_sha256": source.get("catalog_product_sha256"),
        "selection_status": selection.get("status"), "selection_stock_count": selection.get("stock_count"),
        "selected_stock_count": selection.get("selected_stock_count"),
        "expected_preimport_state": expected_preimport,
    }


def saved_catalog_check() -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    product = read_json(SAVED_CATALOG)
    if (product.get("status") != "COMPLETE" or product.get("target_trade_date") != TARGET_DATE
            or product.get("publication_date") != "2026-10-06"
            or product.get("run_id") != EXPECTED_CATALOG_RUN_ID
            or product.get("sha256") != EXPECTED_CATALOG_PRODUCT_SHA256
            or product.get("source_scope") != "EASTMONEY_HK_DATE_CATALOG"
            or product.get("connect_eligibility_status") != "NOT_ASSESSED"
            or product.get("manager_consumer_row_count") != 580
            or product.get("manager_source_identity_count") != 584
            or len(product.get("manager_source_codes", [])) != 524
            or product.get("manager_issuer_count") is not None
            or product.get("hkex_first_publication_verified") is not False):
        raise ValueError("SAVED_CATALOG_ACCEPTANCE_CONTRACT_MISMATCH")
    receipts = product.get("page_receipts")
    if not isinstance(receipts, list) or len(receipts) != product.get("captured_page_count"):
        raise ValueError("SAVED_CATALOG_PAGE_RECEIPTS_INCOMPLETE")
    refs: dict[int, dict[str, Any]] = {}
    for page in receipts:
        index, ref = page.get("page_index"), page.get("source_ref")
        if type(index) is not int or not isinstance(ref, dict) or index in refs:
            raise ValueError("SAVED_CATALOG_PAGE_REF_INVALID")
        refs[index] = ref
    if sorted(refs) != list(range(1, product["captured_page_count"] + 1)):
        raise ValueError("SAVED_CATALOG_PAGE_SEQUENCE_INCOMPLETE")
    return product, refs


def assert_exact_catalog_identity(observed: dict[str, Any], expected_product: dict[str, Any], *,
                                  context: str) -> None:
    """Bind owner/API readback to this exact saved run, not just matching counts."""
    expected = {
        "target_trade_date": TARGET_DATE,
        "publication_date": "2026-10-06",
        "source_scope": "EASTMONEY_HK_DATE_CATALOG",
        "source_identity_basis": "EASTMONEY_116_H_SOURCE_REFERENCE",
        "run_id": EXPECTED_CATALOG_RUN_ID,
        "sha256": EXPECTED_CATALOG_PRODUCT_SHA256,
        "manager_consumer_row_count": 580,
        "manager_source_identity_count": 584,
        "manager_source_codes": expected_product.get("manager_source_codes"),
        "manager_issuer_count": None,
        "connect_eligibility_status": "NOT_ASSESSED",
    }
    if (expected["manager_source_codes"] != expected_product.get("manager_source_codes")
            or not isinstance(expected["manager_source_codes"], list)
            or len(expected["manager_source_codes"]) != 524):
        raise ValueError("SAVED_CATALOG_SOURCE_IDENTITY_INVALID")
    observed_sha = observed.get("sha256", observed.get("product_sha256"))
    for key, value in expected.items():
        current = observed_sha if key == "sha256" else observed.get(key)
        if current != value:
            raise ValueError(context + "_SOURCE_IDENTITY_MISMATCH:" + key)


def approval_check(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if TASK_ROOT.resolve() not in resolved.parents:
        raise ValueError("OPS_REVIEW_APPROVAL_OUTSIDE_TASK_ROOT")
    value = read_json(resolved)
    if (value.get("status") != "REVIEWED_PASS"
            or value.get("candidate_source_test_aggregate_sha256") != EXPECTED_AGGREGATE
            or value.get("scope") != "active_saved_announcement_catalog_import_and_rollback_only"
            or not isinstance(value.get("reviewer_identity"), str)
            or not value.get("reviewer_identity")
            or not isinstance(value.get("review_id"), str)
            or not value.get("review_id")):
        raise ValueError("OPS_REVIEW_APPROVAL_RECEIPT_MISSING_OR_INVALID")
    return value


def load_runtime(release_root: Path):
    root = release_root.resolve()
    sys.path.insert(0, str(root))
    runtime_app = importlib.import_module("apps.api.v35_api.app")
    service_cls, store_cls, _, material_cls = runtime_app._load_manager_research_components()
    return service_cls, store_cls, material_cls


def ref_envelope(material_store: Any, ref: dict[str, Any]) -> bytes:
    if not isinstance(ref.get("blob_sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", ref["blob_sha256"]):
        raise ValueError("SAVED_REF_BLOB_HASH_INVALID")
    raw = material_store._io.read_bytes(material_store._blob_relative(ref["blob_sha256"]), max_bytes=48 * 1024 * 1024)
    if digest(raw) != ref["blob_sha256"]:
        raise ValueError("SAVED_REF_BLOB_CONTENT_HASH_MISMATCH")
    return raw


def transfer_materials(active_material: Any, source_material: Any,
                       refs: dict[int, dict[str, Any]], changed_index: list[dict[str, Any]],
                       new_blobs: list[dict[str, Any]], journal: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    for index, ref in sorted(refs.items()):
        request = ref.get("request") or {}
        source_key, url = ref.get("source_key"), request.get("url")
        if not isinstance(source_key, str) or not isinstance(url, str):
            raise ValueError("SAVED_REF_SOURCE_IDENTITY_INVALID")
        raw_body = __import__("_v4_manager_research_runtime.announcement_source", fromlist=["read_eastmoney_response"]).read_eastmoney_response(source_material, ref)
        envelope = ref_envelope(source_material, ref)
        before = active_material.stat_source(source_key)
        if before is not None:
            if any(before.get(key) != value for key, value in {
                "sha256": ref["blob_sha256"], "url": url, "retrieved_at": ref.get("retrieved_at")
            }.items()):
                raise ValueError("ACTIVE_MATERIAL_INDEX_CONFLICT_PAGE_" + str(index))
            raw = __import__("_v4_manager_research_runtime.announcement_source", fromlist=["read_eastmoney_response"]).read_eastmoney_response(active_material, ref)
            if raw != raw_body:
                raise ValueError("ACTIVE_MATERIAL_BYTES_CONFLICT_PAGE_" + str(index))
            continue
        blob_relative = active_material._blob_relative(ref["blob_sha256"])
        try:
            old_blob = active_material._io.read_bytes(blob_relative, max_bytes=48 * 1024 * 1024)
            if digest(old_blob) != ref["blob_sha256"] or old_blob != envelope:
                raise ValueError("ACTIVE_MATERIAL_BLOB_CONFLICT_PAGE_" + str(index))
            blob_preexisted = True
        except FileNotFoundError:
            blob_preexisted = False
        planned = {"page_index": index, "source_key": source_key,
                   "index_path": active_material._index_relative(source_key),
                   "index_sha256": None, "blob_sha256": ref["blob_sha256"],
                   "blob_preexisted": blob_preexisted, "status": "WRITE_INTENDED"}
        changed_index.append(planned)
        if not blob_preexisted:
            new_blobs.append({"sha256": ref["blob_sha256"], "path": blob_relative,
                              "status": "WRITE_INTENDED"})
        journal()
        transport = lambda _url, envelope=envelope, ref=ref: {
            "body": envelope,
            "content_type": "application/vnd.v4.source-envelope+json",
            "retrieved_at": ref["retrieved_at"],
        }
        material = active_material.fetch(source_key, url=url, ttl_seconds=None, transport=transport, force=False)
        if material.sha256 != ref["blob_sha256"] or material.body != envelope:
            raise ValueError("ACTIVE_MATERIAL_IMPORT_SHA_MISMATCH_PAGE_" + str(index))
        entry = active_material.stat_source(source_key)
        if not entry or any(entry.get(key) != value for key, value in {
            "sha256": ref["blob_sha256"], "url": url, "retrieved_at": ref.get("retrieved_at")
        }.items()):
            raise ValueError("ACTIVE_MATERIAL_IMPORT_INDEX_READBACK_FAILED_PAGE_" + str(index))
        planned["index_sha256"] = digest(active_material._io.read_bytes(active_material._index_relative(source_key)))
        planned["status"] = "CAPTURED_AND_INDEX_VERIFIED"
        if not blob_preexisted:
            new_blobs[-1]["status"] = "CAPTURED_HASH_VERIFIED"
        journal()
    return changed_index, new_blobs


def owner_files(target_root: Path) -> list[dict[str, Any]]:
    out = []
    if target_root.exists():
        for path in sorted(p for p in target_root.rglob("*") if p.is_file()):
            out.append({"path": str(path), "sha256": digest(path.read_bytes()), "bytes": path.stat().st_size})
    return out


def active_catalog_api() -> dict[str, Any]:
    q = urllib.parse.urlencode({"date": TARGET_DATE, "source_scope": "EASTMONEY_HK_DATE_CATALOG",
                                "publication_date": PUBLICATION_DATE})
    status, raw, body = api_get("?" + q)
    catalog = body.get("catalog") or {}
    expected = {
        "status": catalog.get("status"), "readback_status": body.get("readback_status"),
        "target_trade_date": catalog.get("target_trade_date"), "publication_date": catalog.get("publication_date"),
        "manager_consumer_row_count": catalog.get("manager_consumer_row_count"),
        "manager_source_identity_count": catalog.get("manager_source_identity_count"),
        "manager_source_code_count": len(catalog.get("manager_source_codes", [])),
        "manager_source_codes": catalog.get("manager_source_codes"),
        "manager_issuer_count": catalog.get("manager_issuer_count"),
        "connect_eligibility_status": catalog.get("connect_eligibility_status"),
        "source_identity_basis": catalog.get("source_identity_basis"),
        "run_id": catalog.get("run_id"), "product_sha256": catalog.get("sha256"),
        "raw_sha256": digest(raw), "http_status": status,
        "target_trade_date": catalog.get("target_trade_date"),
        "publication_date": catalog.get("publication_date"),
        "source_scope": catalog.get("source_scope"),
    }
    return expected


def preflight(release_root: Path, pid: int | None = None) -> dict[str, Any]:
    frozen = candidate_source_check()
    import guarded_announcement_release as release_ops
    owner = launchd_owner_identity(release_root, pid)
    pid = owner["pid"]
    process = owner["process"]
    active_hashes = release_source_hashes(release_root)
    expected_hash_match = active_hashes == SOURCE_RECORDS
    active_frontend_hashes = {relative: digest((release_root / relative).read_bytes())
        for relative in release_ops.FRONTEND_SOURCE_RECORDS}
    frontend_hash_match = active_frontend_hashes == release_ops.FRONTEND_SOURCE_RECORDS
    active_dist = release_ops.tree_manifest(release_root / "apps/web/dist")
    dist_hash_match = (active_dist["file_count"] == 11 and active_dist["bytes_total"] == 798364
        and active_dist["aggregate_sha256"] == release_ops.EXPECTED_DIST_AGGREGATE)
    legacy = legacy_readback()
    target_analysis = target_analysis_baseline()
    product, refs = saved_catalog_check()
    target_product = STATE_ROOT / "workspace_announcements/20261007/eastmoney_date_catalog/20261006"
    target_runs = STATE_ROOT / "workspace_announcement_runs/20261007/eastmoney_date_catalog/20261006"
    report = {
        "schema": "v4.manager_research.announcement_active_import_preflight.v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "task_root": str(TASK_ROOT), "candidate": frozen,
        "active_process": process, "requested_release_root": str(release_root.resolve()),
        "active_launchd_owner": {key: owner[key] for key in ("label", "plist_path", "plist_sha256", "service_target")},
        "active_release_source_sha256": active_hashes,
        "active_frontend_source_sha256": active_frontend_hashes,
        "active_frontend_dist": active_dist,
        "accepted_backend_source_hashes_match": expected_hash_match,
        "accepted_frontend_source_hashes_match": frontend_hash_match,
        "accepted_frontend_dist_hash_matches": dist_hash_match,
        "active_manager_state_root": process["env"].get("V4_MANAGER_RESEARCH_STATE_ROOT"),
        "expected_manager_state_root": str(STATE_ROOT),
        "legacy_20260929_readback": legacy,
        "target_20261007_preimport_readback": target_analysis,
        "legacy_owner_sha256": digest(LEGACY_OWNER.read_bytes()),
        "saved_catalog": {"run_id": product.get("run_id"), "sha256": product.get("sha256"),
                          "status": product.get("status"), "page_ref_count": len(refs),
                          "article_rows": product.get("manager_consumer_row_count"),
                          "source_associations": product.get("manager_source_identity_count"),
                          "distinct_source_codes": len(product.get("manager_source_codes", [])),
                          "issuer_count": product.get("manager_issuer_count"),
                          "connect_eligibility_status": product.get("connect_eligibility_status")},
        "target_owner_product_path_exists": target_product.exists(),
        "target_owner_run_path_exists": target_runs.exists(),
        "gate": "READY_FOR_REVIEWED_IMPORT" if (expected_hash_match and frontend_hash_match and dist_hash_match
            and Path(process["cwd"]).resolve() == release_root.resolve()
            and Path(process["env"].get("V4_MANAGER_RESEARCH_STATE_ROOT") or "").resolve() == STATE_ROOT.resolve()
            and target_analysis["expected_preimport_state"]
            and not target_product.exists() and not target_runs.exists()) else "BLOCKED_RUNTIME_OR_TARGET_DRIFT",
        "live_actions_performed": False,
    }
    return report


def apply_import(release_root: Path, pid: int | None, approval_path: Path) -> dict[str, Any]:
    approval = approval_check(approval_path)
    report = preflight(release_root, pid)
    if report["gate"] != "READY_FOR_REVIEWED_IMPORT":
        raise ValueError("IMPORT_PREFLIGHT_BLOCKED")
    if ATTEMPT_FILE.exists() or RECEIPT_FILE.exists():
        raise ValueError("IMPORT_PRIOR_ATTEMPT_OR_RECEIPT_EXISTS_NO_RETRY")
    product, refs = saved_catalog_check()
    service_cls, store_cls, material_cls = load_runtime(release_root)
    active_store = store_cls(STATE_ROOT)
    active_material = material_cls(STATE_ROOT / "materials")
    source_material = material_cls(CANARY_STATE / "materials")
    pid = report["active_process"]["pid"]
    attempt = {"schema": "v4.manager_research.announcement_active_import_attempt.v1",
               "created_at_utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
               "release_root": str(release_root.resolve()), "approval": approval,
               "target_trade_date": TARGET_DATE, "publication_date": PUBLICATION_DATE,
               "source_run_id": product["run_id"], "source_catalog_sha256": product["sha256"],
               "page_ref_count": len(refs), "one_attempt_only": True}
    atomic_json(ATTEMPT_FILE, attempt)
    result: dict[str, Any] = {"schema": "v4.manager_research.announcement_active_import_receipt.v1",
                              "attempt": str(ATTEMPT_FILE), "status": "IMPORT_INDETERMINATE"}
    service = None
    try:
        changed_index: list[dict[str, Any]] = []
        new_blobs: list[dict[str, Any]] = []
        def material_journal() -> None:
            attempt["material_index_progress"] = copy.deepcopy(changed_index)
            attempt["new_blob_progress"] = copy.deepcopy(new_blobs)
            atomic_json(ATTEMPT_FILE, attempt)
        transfer_materials(active_material, source_material, refs, changed_index, new_blobs, material_journal)
        service = service_cls(active_store, None, None, material_store=active_material)
        owner = service.accept_saved_date_catalog_refs(TARGET_DATE, PUBLICATION_DATE, refs)
        readback = service.get_announcement_date_catalog(TARGET_DATE, PUBLICATION_DATE)
        catalog = readback.get("catalog") or {}
        if (owner.get("status") != "COMPLETE" or readback.get("status") != "COMPLETE"
                or readback.get("readback_status") != "VERIFIED"
                or catalog.get("manager_consumer_row_count") != 580
                or catalog.get("manager_source_identity_count") != 584
                or len(catalog.get("manager_source_codes", [])) != 524
                or catalog.get("manager_issuer_count") is not None
                or catalog.get("connect_eligibility_status") != "NOT_ASSESSED"):
            raise ValueError("ACTIVE_OWNER_CATALOG_READBACK_CONTRACT_FAILED")
        assert_exact_catalog_identity(catalog, product, context="ACTIVE_OWNER")
        api = active_catalog_api()
        if (api["http_status"] != 200 or api["status"] != "COMPLETE"
                or api["readback_status"] != "VERIFIED"
                or api["manager_consumer_row_count"] != 580
                or api["manager_source_identity_count"] != 584
                or api["manager_source_code_count"] != 524
                or api["manager_issuer_count"] is not None
                or api["connect_eligibility_status"] != "NOT_ASSESSED"):
            raise ValueError("ACTIVE_API_CATALOG_READBACK_CONTRACT_FAILED")
        assert_exact_catalog_identity(api, product, context="ACTIVE_API")
        target_owner = STATE_ROOT / "workspace_announcements/20261007/eastmoney_date_catalog/20261006"
        target_runs = STATE_ROOT / "workspace_announcement_runs/20261007/eastmoney_date_catalog/20261006"
        result.update(status="PASS_ACTIVE_OWNER_AND_API_READBACK", run_id=catalog.get("run_id"),
                      product_sha256=catalog.get("sha256"),
                      manager_readback={"status": readback.get("status"),
                          "readback_status": readback.get("readback_status"),
                          "catalog_run_id": catalog.get("run_id"), "catalog_sha256": catalog.get("sha256"),
                          "manager_consumer_row_count": catalog.get("manager_consumer_row_count"),
                          "manager_source_identity_count": catalog.get("manager_source_identity_count"),
                          "manager_source_code_count": len(catalog.get("manager_source_codes", [])),
                          "manager_issuer_count": catalog.get("manager_issuer_count"),
                          "connect_eligibility_status": catalog.get("connect_eligibility_status")},
                      api_readback=api, created_owner_files=owner_files(target_owner) + owner_files(target_runs),
                      created_material_index=changed_index, created_material_blobs=new_blobs,
                      preflight=report, terminal_at_utc=datetime.now(timezone.utc).isoformat())
        atomic_json(RECEIPT_FILE, result)
        return result
    except Exception as exc:
        result.update(status="IMPORT_INDETERMINATE_NO_RETRY", error=f"{type(exc).__name__}:{exc}",
                      created_material_index=locals().get("changed_index", []),
                      created_material_blobs=locals().get("new_blobs", []),
                      current_target_owner_files=owner_files(STATE_ROOT / "workspace_announcements/20261007/eastmoney_date_catalog/20261006")
                          + owner_files(STATE_ROOT / "workspace_announcement_runs/20261007/eastmoney_date_catalog/20261006"),
                      terminal_at_utc=datetime.now(timezone.utc).isoformat())
        atomic_json(RECEIPT_FILE, result)
        raise
    finally:
        if service is not None:
            service.close()


def rollback_import(release_root: Path, pid: int | None, approval_path: Path) -> dict[str, Any]:
    approval = approval_check(approval_path)
    if ROLLBACK_ATTEMPT_FILE.exists() or ROLLBACK_RECEIPT_FILE.exists():
        raise ValueError("PRIOR_ROLLBACK_ATTEMPT_OR_RECEIPT_EXISTS_NO_RETRY")
    if not RECEIPT_FILE.is_file():
        raise ValueError("IMPORT_SUCCESS_RECEIPT_MISSING_NO_ROLLBACK")
    receipt = read_json(RECEIPT_FILE)
    if (receipt.get("status") != "PASS_ACTIVE_OWNER_AND_API_READBACK"
            or receipt.get("preflight", {}).get("candidate", {}).get("aggregate_sha256") != EXPECTED_AGGREGATE
            or not receipt.get("run_id") or not receipt.get("product_sha256")):
        raise ValueError("IMPORT_SUCCESS_RECEIPT_INVALID_NO_ROLLBACK")
    owner = launchd_owner_identity(release_root, pid)
    pid = owner["pid"]
    process = owner["process"]
    if (Path(process["cwd"]).resolve() != release_root.resolve()
            or Path(process["env"].get("V4_MANAGER_RESEARCH_STATE_ROOT") or "").resolve() != STATE_ROOT.resolve()
            or release_source_hashes(release_root) != SOURCE_RECORDS):
        raise ValueError("ACTIVE_RUNTIME_DRIFT_BLOCKS_ROLLBACK")
    import guarded_announcement_release as release_ops
    if ({relative: digest((release_root / relative).read_bytes()) for relative in release_ops.FRONTEND_SOURCE_RECORDS}
            != release_ops.FRONTEND_SOURCE_RECORDS
            or release_ops.tree_manifest(release_root / "apps/web/dist").get("aggregate_sha256")
            != release_ops.EXPECTED_DIST_AGGREGATE):
        raise ValueError("ACTIVE_FRONTEND_RUNTIME_DRIFT_BLOCKS_ROLLBACK")
    legacy = legacy_readback()
    api = active_catalog_api()
    if (api.get("http_status") != 200 or api.get("run_id") != receipt["run_id"]
            or api.get("product_sha256") != receipt["product_sha256"]
            or api.get("status") != "COMPLETE" or api.get("readback_status") != "VERIFIED"):
        raise ValueError("ACTIVE_TARGET_PRODUCT_DRIFT_BLOCKS_ROLLBACK")
    material_root = STATE_ROOT / "materials"
    owner_paths = {
        (STATE_ROOT / "workspace_announcements/20261007/eastmoney_date_catalog/20261006").resolve(),
        (STATE_ROOT / "workspace_announcement_runs/20261007/eastmoney_date_catalog/20261006").resolve(),
    }
    expected_owner_files = receipt.get("created_owner_files")
    if not isinstance(expected_owner_files, list):
        raise ValueError("ROLLBACK_OWNER_FILE_MANIFEST_MISSING")
    actual_owner = []
    for root in owner_paths:
        actual_owner.extend(owner_files(root))
    expected_by_path = {Path(item["path"]).resolve(): item for item in expected_owner_files}
    actual_by_path = {Path(item["path"]).resolve(): item for item in actual_owner}
    if actual_by_path != expected_by_path:
        raise ValueError("ROLLBACK_TARGET_OWNER_FILES_DRIFT")
    index_files = receipt.get("created_material_index") or []
    for item in index_files:
        path = (material_root / item["index_path"]).resolve()
        if material_root.resolve() not in path.parents or not path.is_file() or digest(path.read_bytes()) != item["index_sha256"]:
            raise ValueError("ROLLBACK_MATERIAL_INDEX_DRIFT")
    # Content-addressed blobs are intentionally retained as harmless orphaned
    # cache bytes. Removing the owner product and its index entries restores
    # prior reads without risking a blob shared by another cached source.
    if digest(LEGACY_OWNER.read_bytes()) != EXPECTED_LEGACY_OWNER_SHA:
        raise ValueError("ROLLBACK_LEGACY_OWNER_DRIFT")
    target_before = target_analysis_baseline()
    if not (
        target_before.get("http_status") == 200
        and target_before.get("analysis_status") == "NOT_IMPORTED"
        and target_before.get("source_status") == "COMPLETE"
        and target_before.get("source_run_id") == receipt["run_id"]
        and target_before.get("source_product_sha256") == receipt["product_sha256"]
        and target_before.get("selection_status") == "NOT_ASSESSED"
        and target_before.get("selection_stock_count") is None
        and target_before.get("selected_stock_count") is None
    ):
        raise ValueError("ROLLBACK_TARGET_ANALYSIS_READBACK_DRIFT")
    atomic_json(ROLLBACK_ATTEMPT_FILE, {
        "schema": "v4.manager_research.announcement_active_import_rollback_attempt.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "approval": approval,
        "run_id": receipt["run_id"],
        "product_sha256": receipt["product_sha256"],
        "target_api_before_rollback": target_before,
        "owner_file_manifest": expected_owner_files,
        "material_index_manifest": index_files,
        "one_attempt_only": True,
    })
    try:
        for item in expected_owner_files:
            path = Path(item["path"]).resolve()
            if not any(root == path or root in path.parents for root in owner_paths):
                raise ValueError("ROLLBACK_OWNER_PATH_OUTSIDE_TARGET")
            path.unlink()
        for item in index_files:
            path = (material_root / item["index_path"]).resolve()
            path.unlink()
        target_after = target_analysis_baseline()
        if not target_after.get("expected_preimport_state"):
            raise ValueError("ROLLBACK_TARGET_PREIMPORT_API_READBACK_FAILED")
    except Exception as exc:
        atomic_json(ROLLBACK_RECEIPT_FILE, {
            "schema": "v4.manager_research.announcement_active_import_rollback_receipt.v1",
            "status": "ROLLBACK_INDETERMINATE_NO_RETRY",
            "error": f"{type(exc).__name__}:{exc}",
            "approval": approval,
            "rolled_back_run_id": receipt["run_id"],
            "target_api_before_rollback": target_before,
            "target_api_after_rollback": locals().get("target_after"),
            "terminal_at_utc": datetime.now(timezone.utc).isoformat(),
        })
        raise
    value = {
        "schema": "v4.manager_research.announcement_active_import_rollback_receipt.v1",
        "status": "ROLLED_BACK_OWNED_ANNOUNCEMENT_ARTIFACTS",
        "approval": approval,
        "rolled_back_run_id": receipt["run_id"],
        "removed_owner_file_count": len(expected_owner_files),
        "removed_material_index_count": len(index_files),
        "retained_content_addressed_blob_count": len(receipt.get("created_material_blobs") or []),
        "legacy_20260929_readback": legacy,
        "legacy_owner_sha256": digest(LEGACY_OWNER.read_bytes()),
        "target_api_after_rollback": target_after,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(ROLLBACK_RECEIPT_FILE, value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, default=DEFAULT_ACTIVE_RELEASE)
    parser.add_argument("--pid", type=int, help="Optional guard; must match the PID resolved from the existing LaunchAgent.")
    parser.add_argument("--preflight", action="store_true", help="Read-only runtime/catalog/API preflight (default).")
    parser.add_argument("--apply", action="store_true", help="Import saved refs via the active owner; requires reviewer receipt and --confirm-apply.")
    parser.add_argument("--confirm-apply", action="store_true")
    parser.add_argument("--rollback", action="store_true", help="Remove only exact files created by a receipted import; requires --confirm-rollback.")
    parser.add_argument("--confirm-rollback", action="store_true")
    parser.add_argument("--approval", type=Path, default=APPROVAL_FILE)
    args = parser.parse_args()
    if args.apply and args.rollback:
        parser.error("--apply and --rollback are mutually exclusive")
    if args.apply and not args.confirm_apply:
        parser.error("--apply requires --confirm-apply")
    if args.rollback and not args.confirm_rollback:
        parser.error("--rollback requires --confirm-rollback")
    if args.apply:
        value = apply_import(args.release_root, args.pid, args.approval)
        print(json.dumps({"status": value["status"], "receipt": str(RECEIPT_FILE),
                          "run_id": value.get("run_id"), "product_sha256": value.get("product_sha256")}, indent=2))
        return 0
    if args.rollback:
        value = rollback_import(args.release_root, args.pid, args.approval)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    value = preflight(args.release_root, args.pid)
    OPS_ROOT.mkdir(parents=True, exist_ok=True)
    atomic_json(OPS_ROOT / "preflight.json", value)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if value["gate"] == "READY_FOR_REVIEWED_IMPORT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
