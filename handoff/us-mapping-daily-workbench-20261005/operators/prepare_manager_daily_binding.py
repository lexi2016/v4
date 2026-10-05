#!/usr/bin/env python3
"""Prepare a plan-only binding from the final app's Manager API owner.

This operator uses FastAPI TestClient (in-process ASGI), not the running
127.0.0.1 service. It creates an owner service from --app-root and points it
at the explicitly supplied data, Manager state, and security-master roots.
POST /workspace/refresh persists a research plan to --manager-state-root, so
the script requires --execute-owner-write. It never edits a scheduler/plist or
installs the generated binding into a live configuration.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


BASE = "http://127.0.0.1:8873"
OWNER = "ManagerResearchJobService.refresh_workspace_plan"
HK = __import__("zoneinfo").ZoneInfo("Asia/Hong_Kong")
OWNER_ROOT_ENV_WHITELIST = (
    "V35_APP_ROOT",
    "V35_RUNTIME_ROOT",
    "V35_DATA_ROOT",
    "V35_SHARED_DATA_ROOT",
    "V35_DISPATCH_LEDGER_ROOT",
    "V35_RESEARCH_DATA_ROOT",
    "V35_PRESELECTION_SOURCE_ROOT",
    "V35_STAGE_CENTER_SELECTION_ROOT",
    "V35_RELEASE_MANIFEST_PATH",
    "V4_DAILY_REVIEW_ROOT",
    "V4_REVIEW_GENERATION_BINDINGS_PATH",
    "V4_INTRADAY_RESEARCH_ROOT",
    "V4_MANAGER_RESEARCH_STATE_ROOT",
    "V35_REVIEW_CORE_PACKAGE_ROOT",
    "V35_REVIEW_CORE_RUNTIME_ROOT",
    "V35_REVIEW_CORE_FUPAN_STORE_ROOT",
    "V35_REVIEW_CORE_STAGE7_STORE_ROOT",
    "REVIEW_CORE_PACKAGE_ROOT",
    "REVIEW_CORE_DATA_ROOT",
    "REVIEW_CORE_FUPAN_POOL_ROOT",
    "REVIEW_CORE_STAGE7_POOL_ROOT",
    "V4_MANAGER_NEWS_DATA_ROOT",
    "V4_MANAGER_NEWS_OWNER_ROOT",
    "V4_MANAGER_SCREEN_AUTHORITY_ROOT",
    "V4_MANAGER_SECURITY_MASTER_ROOT",
    "V35_REVIEW_CORE_CLOSE_ROOT",
    "V4_CLOSE_REBOUND_AUTHORITY_ROOT",
    "V35_MORNING_NEWS_DATA_ROOT",
    "V4_MANAGER_VIBE_BINDING",
    "V4_MANAGER_UNIVERSE_OWNER_ROOT",
    "V4_MANAGER_UNIVERSE_ROOT",
    "V4_MANAGER_PLAN_OWNER_BINDING_PATH",
    "V4_WECHAT_ARCHIVE_ROOT",
)

CLI_ROOT_ENV_OVERRIDES = (
    "V35_APP_ROOT",
    "V35_DATA_ROOT",
    "V35_SHARED_DATA_ROOT",
    "V4_MANAGER_RESEARCH_STATE_ROOT",
    "V4_MANAGER_SECURITY_MASTER_ROOT",
    "V4_MANAGER_SCREEN_AUTHORITY_ROOT",
    "V35_RESEARCH_DATA_ROOT",
)


def owner_root_environment_snapshot() -> dict[str, str | None]:
    """Capture only named owner-root settings; never serialize the full process environment."""
    return {key: os.environ.get(key) for key in OWNER_ROOT_ENV_WHITELIST}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def exact_root(text: str, name: str) -> Path:
    value = Path(text).expanduser()
    if not value.is_absolute() or ".." in value.parts or value.resolve() != value:
        raise ValueError(f"{name}_MUST_BE_EXACT_ABSOLUTE_PATH")
    return value


def disjoint(path: Path, others: list[Path], label: str) -> None:
    for other in others:
        if path == other or path in other.parents or other in path.parents:
            raise ValueError(f"{label}_PATHS_OVERLAP")


def response_receipt(*, method: str, endpoint: str, response: Any,
                     response_path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    raw = response.content
    response_path.write_bytes(raw)
    return {
        "schema_version": "manager_daily_chain.owner_http_receipt.v1",
        "http_status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "request": {"method": method, "url": BASE + endpoint},
        "response": {"path": str(response_path), "bytes": len(raw), "sha256": sha(raw)},
        "readback": summary,
    }


def save_json(path: Path, value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return sha(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", required=True, help="Frozen final release app root")
    parser.add_argument("--data-root", required=True, help="Existing owner data root, including US peripheral files")
    parser.add_argument("--shared-data-root", required=True,
                        help="Exact V35_SHARED_DATA_ROOT; kept separate from the Manager security master")
    parser.add_argument("--manager-state-root", required=True, help="Exact ManagerResearchStore state root")
    parser.add_argument("--security-master-root", required=True, help="Exact owner security-master root")
    parser.add_argument("--research-data-root", required=True, help="Existing ResearchLaneSource root")
    parser.add_argument("--screen-authority-root", help="Exact Manager screen-authority root; defaults to the security master")
    parser.add_argument("--research-ledger-root", help="Exact research ledger root; default is research-root.parent/dispatcher")
    parser.add_argument("--workspace-ledger-root", help="Optional Manager workspace ledger; omitted when live default is None")
    parser.add_argument("--target-date", required=True, help="Explicit YYYYMMDD target date")
    parser.add_argument("--evidence-dir", required=True, help="New, empty task evidence directory outside owned roots")
    parser.add_argument("--execute-owner-write", action="store_true",
                        help="Acknowledge that the real API owner's MANUAL_REFRESH writes one research plan")
    args = parser.parse_args()
    if not args.execute_owner_write:
        parser.error("owner POST writes a plan; pass --execute-owner-write only under root-controlled authorization")

    app = exact_root(args.app_root, "APP_ROOT")
    data = exact_root(args.data_root, "DATA_ROOT")
    shared = exact_root(args.shared_data_root, "SHARED_DATA_ROOT")
    state = exact_root(args.manager_state_root, "MANAGER_STATE_ROOT")
    master = exact_root(args.security_master_root, "SECURITY_MASTER_ROOT")
    research = exact_root(args.research_data_root, "RESEARCH_DATA_ROOT")
    stage_selection_value = os.environ.get("V35_STAGE_CENTER_SELECTION_ROOT", "").strip()
    if not stage_selection_value:
        raise ValueError("STAGE_CENTER_SELECTION_ROOT_REQUIRED")
    stage_selection = exact_root(stage_selection_value, "STAGE_CENTER_SELECTION_ROOT")
    screen = exact_root(args.screen_authority_root, "SCREEN_AUTHORITY_ROOT") if args.screen_authority_root else master
    research_ledger = exact_root(args.research_ledger_root, "RESEARCH_LEDGER_ROOT") if args.research_ledger_root else None
    workspace_ledger = exact_root(args.workspace_ledger_root, "WORKSPACE_LEDGER_ROOT") if args.workspace_ledger_root else None
    resolved_research_ledger = research_ledger or (research.parent / "dispatcher").resolve()
    output = exact_root(args.evidence_dir, "EVIDENCE_DIR")
    required_roots = [("APP_ROOT", app), ("DATA_ROOT", data), ("SHARED_DATA_ROOT", shared),
                      ("MANAGER_STATE_ROOT", state), ("SECURITY_MASTER_ROOT", master),
                      ("SCREEN_AUTHORITY_ROOT", screen), ("RESEARCH_DATA_ROOT", research),
                      ("STAGE_CENTER_SELECTION_ROOT", stage_selection)]
    required_roots.extend((label, path) for label, path in (
        ("RESEARCH_LEDGER_ROOT", research_ledger), ("WORKSPACE_LEDGER_ROOT", workspace_ledger)) if path is not None)
    for label, path in required_roots:
        if not path.is_dir():
            raise ValueError(f"{label}_MISSING")
    if not (app / "apps/api/v35_api/app.py").is_file():
        raise ValueError("FINAL_RELEASE_API_APP_MISSING")
    if shared == master:
        raise ValueError("SHARED_DATA_AND_SECURITY_MASTER_MUST_BE_SEPARATE")
    owned_roots = [app, data, shared, master, screen, research, stage_selection, resolved_research_ledger]
    if workspace_ledger is not None:
        owned_roots.append(workspace_ledger)
    disjoint(state, owned_roots, "OWNER_STATE")
    disjoint(output, owned_roots + [state], "EVIDENCE")
    target = args.target_date
    if len(target) != 8 or not target.isdigit():
        raise ValueError("TARGET_DATE_INVALID")
    datetime.strptime(target, "%Y%m%d")
    if output.exists():
        raise ValueError("EVIDENCE_DIR_MUST_NOT_EXIST")

    output.mkdir(parents=True)
    evidence = output / "owner_http_evidence"
    evidence.mkdir()
    sys.path.insert(0, str(app))
    from fastapi.testclient import TestClient
    from apps.api.v35_api.app import create_app
    from infrastructure.scheduling.manager_announcement_supervisor import binding_inventory, validate_binding
    from v4.manager_research import workspace

    inherited_owner_root_environment = owner_root_environment_snapshot()
    # The explicit CLI roots are authoritative for this owner instance. Preserve
    # every other inherited R17 owner-root setting for the lifetime of POST/GET.
    effective_root_values = {
        "V35_APP_ROOT": str(app),
        "V35_DATA_ROOT": str(data),
        "V35_SHARED_DATA_ROOT": str(shared),
        "V4_MANAGER_RESEARCH_STATE_ROOT": str(state),
        "V4_MANAGER_SECURITY_MASTER_ROOT": str(master),
        "V4_MANAGER_SCREEN_AUTHORITY_ROOT": str(screen),
        "V35_RESEARCH_DATA_ROOT": str(research),
    }
    os.environ.update(effective_root_values)
    effective_owner_root_environment = owner_root_environment_snapshot()
    api = create_app(data_root=data, shared_data_root=shared, manager_research_state_root=state,
                     research_data_root=research, research_ledger_root=research_ledger,
                     ledger_root=workspace_ledger, stage_center_selection_root=stage_selection)
    service = api.state.manager_research_service
    resolved_roots = {
        "api_app_root": str(app),
        "api_data_root": str(data),
        "v35_shared_data_root": str(shared),
        "manager_state_root": str(Path(service.store.root).resolve()),
        "manager_security_master_root": str(Path(service._workspace_security_master_root).resolve()),
        "manager_screen_authority_root": str(Path(service._workspace_screen_authority_root).resolve()),
        "research_data_root": str(Path(service._existing_research_source.data_root).resolve()),
        "research_ledger_root": str(Path(service._existing_research_source.ledger_root).resolve()),
        "stage_center_selection_root": str(stage_selection),
        "workspace_ledger_root": (str(Path(service._workspace_ledger_root).resolve())
                                  if service._workspace_ledger_root is not None else None),
        "us_peripheral_owner_root": str(Path(service._workspace_us_market_reader.root).resolve()),
    }
    expected_roots = {
        "api_app_root": str(app), "api_data_root": str(data), "v35_shared_data_root": str(shared),
        "manager_state_root": str(state), "manager_security_master_root": str(master),
        "manager_screen_authority_root": str(screen), "research_data_root": str(research),
        "research_ledger_root": str(resolved_research_ledger),
        "stage_center_selection_root": str(stage_selection),
        "workspace_ledger_root": str(workspace_ledger) if workspace_ledger is not None else None,
        "us_peripheral_owner_root": str(data),
    }
    if resolved_roots != expected_roots:
        service.close()
        raise ValueError("API_OWNER_RESOLVED_ROOTS_DIFFER_FROM_ARGUMENTS")
    observation = service.observation_reader.read(target)
    observation_markets = observation.get("selection_markets")
    if (observation.get("response_source") != "SHARED_STAGE_CENTER"
            or observation.get("trade_date") != target
            or observation.get("stage_id") != "STAGE_0935_0940"
            or not isinstance(observation_markets, dict)
            or "HK_CONNECT" not in observation_markets
            or "SHARED_STAGE_CENTER_NOT_CONFIGURED" in (observation.get("cannot_confirm") or [])):
        service.close()
        raise ValueError("SHARED_STAGE_SELECTION_OBSERVATION_READER_NOT_CONFIGURED")
    observation_receipt = {
        "root": str(stage_selection),
        "response_source": observation.get("response_source"),
        "trade_date": observation.get("trade_date"),
        "stage_id": observation.get("stage_id"),
        "status": observation.get("status"),
        "hk_connect_market_present": True,
        "write_performed": observation.get("write_performed"),
        "sha256": sha(json.dumps(observation, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")).encode()),
    }
    post_path = f"/api/v4/manager/research/workspace/refresh?date={target}"
    get_path = f"/api/v4/manager/research/workspace?date={target}"
    try:
        with TestClient(api, base_url=BASE) as client:
            post = client.post(post_path)
            post_raw = post.content
            post_value = post.json() if post.headers.get("content-type", "").startswith("application/json") else {}
            if post.status_code != 200 or not isinstance(post_value, dict):
                raise ValueError(f"OWNER_POST_FAILED:{post.status_code}")
            saved = workspace._read_plan(service.store, target)
            get = client.get(get_path)
            get_value = get.json() if get.headers.get("content-type", "").startswith("application/json") else {}
            if get.status_code != 200 or not isinstance(get_value, dict):
                raise ValueError(f"OWNER_GET_FAILED:{get.status_code}")
        if not isinstance(saved, dict):
            raise ValueError("PERSISTED_PLAN_MISSING_AFTER_POST")
        product = post_value.get("plan_product")
        attempt = post_value.get("workspace_plan_attempt")
        get_product = get_value.get("plan_product")
        if (not isinstance(product, dict) or not isinstance(attempt, dict) or not isinstance(get_product, dict)
                or product.get("status") != "CURRENT" or get_product.get("status") != "CURRENT"
                or product.get("run_id") != saved.get("run_id") or get_product.get("run_id") != saved.get("run_id")
                or product.get("sha256") != saved.get("sha256") or get_product.get("sha256") != saved.get("sha256")
                or saved.get("target_trade_date") != target or saved.get("execution_kind") != "MANUAL_REFRESH"
                or saved.get("owner") != OWNER or attempt.get("state") not in {"SUCCEEDED", "PARTIAL"}):
            raise ValueError("OWNER_POST_GET_PERSISTED_IDENTITY_MISMATCH")
        if (saved.get("RESEARCH_ONLY") is not True or saved.get("production_allowed") is not False
                or saved.get("buy_gate_updated") is not False or saved.get("orders_sent") is not False):
            raise ValueError("OWNER_SAFETY_BOUNDARY_INVALID")
        summary = post_value.get("summary")
        if not isinstance(summary, dict) or summary.get("formal_recommendation_count") != 0:
            raise ValueError("FORMAL_RECOMMENDATION_COUNT_NOT_ZERO")

        post_summary = {
            "target_trade_date": target,
            "plan_product": {"status": "CURRENT", "run_id": saved["run_id"],
                             "sha256": saved["sha256"], "original_owner": OWNER},
            "persisted_store": {"target_trade_date": target, "run_id": saved["run_id"],
                                "product_sha256": saved["sha256"], "execution_kind": "MANUAL_REFRESH",
                                "owner": OWNER, **{k: saved[k] for k in (
                                    "RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent")}},
            "store_latest_matches_http_plan_product": True,
            "workspace_plan_attempt": {"execution_kind": attempt["execution_kind"], "state": attempt["state"]},
            "safety": {k: saved[k] for k in ("RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent")},
        }
        get_summary = {"target_trade_date": target,
                       "plan_product": {"status": "CURRENT", "run_id": saved["run_id"],
                                        "sha256": saved["sha256"], "original_owner": OWNER}}
        post_receipt = response_receipt(method="POST", endpoint=post_path, response=post,
            response_path=evidence / "refresh-response.bin", summary=post_summary)
        get_receipt = response_receipt(method="GET", endpoint=get_path, response=get,
            response_path=evidence / "readback-response.bin", summary=get_summary)
        if any(r["http_status"] != 200 or not r["content_type"].startswith("application/json")
               for r in (post_receipt, get_receipt)):
            raise ValueError("OWNER_HTTP_RECEIPT_INVALID")
        post_receipt_sha = save_json(evidence / "refresh-receipt.json", post_receipt)
        get_receipt_sha = save_json(evidence / "readback-receipt.json", get_receipt)

        canary = {
            "schema_version": "manager_daily_chain.plan_refresh_owner_evidence.v2",
            "status": "PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING",
            "scope": "NEXT_HK_SESSION_MANUAL_REFRESH_WITH_HTTP_READBACK",
            "policy_status": "PROPOSAL_ONLY", "plan_material_refresh_only": True,
            "execution_mode": "HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK",
            "transport": "ASGI_TESTCLIENT_IN_PROCESS_NOT_LIVE_HTTP",
            "hook_executed": False, "app_root": str(app), "candidate_binding_app_root": str(app),
            "owner_execution_app_root": str(app), "manager_state_root": str(state),
            "target_trade_date": target, "run_id": saved["run_id"], "product_sha256": saved["sha256"],
            "input_identity": saved["input_identity"], "execution_kind": "MANUAL_REFRESH", "owner": OWNER,
            "owner_attempt_state": attempt["state"], "formal_recommendation_count": 0,
            "stage_selection_observation": observation_receipt,
            "owner_evidence": {
                "refresh": {"path": str(evidence / "refresh-receipt.json"), "sha256": post_receipt_sha},
                "readback": {"path": str(evidence / "readback-receipt.json"), "sha256": get_receipt_sha},
            },
            "announcement_collection_enabled": False, "announcement_network_requests": 0,
            "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        }
        canary_path = output / "plan_refresh_owner_evidence.v2.json"
        canary_sha = save_json(canary_path, canary)
        interpreter = Path(sys.executable)
        binding = {
            "schema_version": "v4.manager_research.announcement_binding.v1",
            "enabled": True, "policy": "BALANCED_V1", "policy_status": "PROPOSAL_ONLY",
            "app_root": str(app), "manager_state_root": str(state), "security_master_root": str(master),
            "python": str(interpreter), "python_resolved": str(interpreter.resolve()),
            "python_sha256": sha(interpreter.read_bytes()), "files": binding_inventory(app), "priority_codes": [],
            "plan_material_refresh_only": True, "announcement_collection_enabled": False,
            "plan_material_refresh": {"enabled": True, "start_local": "16:00", "end_local": "23:00",
                                      "max_attempts_per_target_date": 3, "retry_backoff_seconds": 600,
                                      "status": "PROPOSAL_ONLY"},
            "preopen_plan": {"enabled": True, "lead_seconds": 180, "status": "PROPOSAL_ONLY"},
            "activation_receipt": None,
            "plan_activation_receipt": {"path": str(canary_path), "sha256": canary_sha},
            "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        }
        validate_binding(binding, expected_app=app)
        binding_path = output / "candidate_manager_plan_binding.json"
        binding_sha = save_json(binding_path, binding)
        receipt = {
            "schema_version": "manager_daily_chain.binding_preparation_receipt.v2",
            "transport": "ASGI_TESTCLIENT_IN_PROCESS_NOT_LIVE_HTTP",
            "owner_root_environment": {
                "whitelist": list(OWNER_ROOT_ENV_WHITELIST),
                "inherited": inherited_owner_root_environment,
                "effective": effective_owner_root_environment,
                "cli_overridden": list(CLI_ROOT_ENV_OVERRIDES),
            },
            "resolved_roots": resolved_roots,
            "stage_selection_observation": observation_receipt,
            "target_trade_date": target, "canary_path": str(canary_path), "canary_sha256": canary_sha,
            "binding_path": str(binding_path), "binding_sha256": binding_sha,
            "inventory_file_count": len(binding["files"]), "validation": "PASS",
            "owner_attempt_state": attempt["state"], "formal_recommendation_count": 0,
            "owner_http_evidence": {
                "POST": post_receipt["response"], "POST_status": post_receipt["http_status"],
                "POST_content_type": post_receipt["content_type"],
                "GET": get_receipt["response"], "GET_status": get_receipt["http_status"],
                "GET_content_type": get_receipt["content_type"],
            },
            "safety": {k: saved[k] for k in ("RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent")},
            "live_binding_installed": False,
        }
        save_json(output / "preparation_receipt.json", receipt)
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
