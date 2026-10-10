#!/usr/bin/env python3
"""Seal the local Stage R4 + manager source fusion evidence for review."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


E = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1")
APP = E / "candidate/stage_r4_manager_r2_owner_input_r1_fused_r1/app"
EVIDENCE = E / "evidence/owner_input_r1"
SOURCE_RECEIPT_PATH = EVIDENCE / "stage_r4_fused_source_receipt.json"
BUILD_RECEIPT_PATH = EVIDENCE / "fusion_build/vite_build_receipt.json"
TARGETED_RECEIPT_PATH = EVIDENCE / "fused_targeted_checks_20261010_r1_retry4/fused_targeted_checks_receipt.json"
UI_LOG = EVIDENCE / "fused_targeted_checks_20261010_r1_retry4/logs/manager_selection_and_daily_automation_vitest.log"
PYTHON_JUNIT = EVIDENCE / "fused_targeted_checks_20261010_r1_retry4/logs/pytest_manager_app_plan_and_hk_wiring/junit.xml"
MATRIX_PATH = EVIDENCE / "full_matrix_comparison.json"
INVENTORY_PATH = EVIDENCE / "fused_candidate_acceptance_inventory.json"
RECEIPT_PATH = EVIDENCE / "fused_candidate_acceptance_receipt.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def evidence_ref(path: Path) -> dict[str, object]:
    return {"path": str(path), "sha256": sha256(path)}


def main() -> int:
    for path in (APP, SOURCE_RECEIPT_PATH, BUILD_RECEIPT_PATH, TARGETED_RECEIPT_PATH,
                 UI_LOG, PYTHON_JUNIT, MATRIX_PATH):
        if not path.exists():
            raise SystemExit(f"MISSING_ACCEPTANCE_INPUT:{path}")
    for output in (INVENTORY_PATH, RECEIPT_PATH):
        if output.exists():
            raise SystemExit(f"REFUSE_EXISTING_ACCEPTANCE_OUTPUT:{output}")

    source = load_json(SOURCE_RECEIPT_PATH)
    build = load_json(BUILD_RECEIPT_PATH)
    targeted = load_json(TARGETED_RECEIPT_PATH)
    matrix = load_json(MATRIX_PATH)

    stage_root = Path(str(source["stage_release_root"]))
    stage_manifest = stage_root / "release-manifest.json"
    if not stage_manifest.is_file():
        raise SystemExit(f"MISSING_STAGE_RELEASE_MANIFEST:{stage_manifest}")
    stage_manifest_sha = sha256(stage_manifest)
    if stage_manifest_sha != source["stage_release_manifest_sha256"]:
        raise SystemExit("STAGE_RELEASE_MANIFEST_SHA_MISMATCH")
    if source["status"] != "PASS" or source["stage_copy_inventory_exact"] is not True:
        raise SystemExit("SOURCE_FUSION_RECEIPT_NOT_PASS")
    if source["manager_source_operation_count"] != 16 or source["stage_reviewed_source_count"] != 9:
        raise SystemExit("SOURCE_FUSION_PATH_COUNT_MISMATCH")
    if source["stage_manager_source_path_overlap"]:
        raise SystemExit("SOURCE_FUSION_STAGE_PATH_OVERLAP")
    if len(source["stage_reviewed_source_paths_preserved"]) != 9:
        raise SystemExit("STAGE_REVIEWED_SOURCE_PATH_COUNT_MISMATCH")

    if build["exit_code"] != 0 or build["source_unchanged_during_build"] is not True:
        raise SystemExit("FUSED_WEB_BUILD_NOT_PASS")
    if build["dependency_link_removed_after_build"] is not True:
        raise SystemExit("BUILD_DEPENDENCY_LINK_REMAINS")
    if build["canonical_dependency_cache_unchanged"] is not True or build["canonical_vite_temp_cache_unchanged"] is not True:
        raise SystemExit("CANONICAL_WEB_CACHE_CHANGED")
    if build["all_expected_entrypoints_and_assets_present"] is not True:
        raise SystemExit("FUSED_WEB_BUILD_ASSET_CHECK_FAILED")

    if targeted["status"] != "PASS" or targeted["all_command_exit_codes_zero"] is not True:
        raise SystemExit("FUSED_TARGETED_CHECKS_NOT_PASS")
    if targeted["candidate_tree_unchanged_during_checks"] is not True:
        raise SystemExit("CANDIDATE_TREE_CHANGED_DURING_CHECKS")
    if targeted["ui_test_source_bindings_valid"] is not True:
        raise SystemExit("FUSED_UI_SOURCE_BINDINGS_INVALID")
    if targeted["ui_harness_dependency_link"]["removed"] is not True:
        raise SystemExit("UI_HARNESS_DEPENDENCY_LINK_REMAINS")
    if targeted["temporary_dependency_link"]["removed"] is not True:
        raise SystemExit("CANDIDATE_DEPENDENCY_LINK_REMAINS")

    ui_text = UI_LOG.read_text(encoding="utf-8")
    ui_match = re.search(r"Tests\s+(\d+)\s+passed(?:\s*\|\s*(\d+)\s+failed)?", ui_text)
    if not ui_match or int(ui_match.group(1)) != 25 or int(ui_match.group(2) or 0) != 0:
        raise SystemExit("UI_TEST_RESULT_MISMATCH")
    py_result = targeted["commands"][-1]["junit"]
    if not isinstance(py_result, dict) or py_result.get("tests") != 19 or py_result.get("failures") != 0 or py_result.get("errors") != 0:
        raise SystemExit("PYTHON_TEST_RESULT_MISMATCH")

    sys.path.insert(0, str(APP.resolve()))
    from ops.build_release_candidate import inventory_digest, inventory_tree

    inventory = inventory_tree(APP)
    inventory_sha = inventory_digest(inventory)
    inventory_payload = {
        "schema_version": "fused_candidate_release_inventory.v1",
        "candidate_app_root": str(APP),
        "entry_count": len(inventory),
        "inventory_sha256": inventory_sha,
        "entries": inventory,
    }
    INVENTORY_PATH.write_text(json.dumps(inventory_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    prior_matrix = {
        "path": str(MATRIX_PATH),
        "sha256": sha256(MATRIX_PATH),
        "scope": "pre_fusion_manager_candidate_only_not_replayed_on_fused_candidate",
        "status": matrix.get("status"),
        "candidate_passed": matrix.get("candidate_total_passed"),
        "candidate_failures": matrix.get("candidate_total_failures"),
        "focused_20": matrix.get("groups", {}).get("focused_20"),
    }

    receipt = {
        "schema_version": "stage_r4_manager_r2_owner_input_r1_fused_candidate_acceptance.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "READY_FOR_INDEPENDENT_REVIEW",
        "candidate_disposition": "LOCAL_CANDIDATE_ONLY",
        "candidate_app_root": str(APP),
        "provenance": {
            "stage_release_id": source["stage_release_id"],
            "stage_release_root": str(stage_root),
            "stage_release_manifest": {"path": str(stage_manifest), "sha256": stage_manifest_sha},
            "stage_app_inventory_count": source["stage_app_inventory_count"],
            "stage_app_inventory_sha256": source["stage_app_inventory_sha256"],
            "stage_reviewed_source_count": source["stage_reviewed_source_count"],
            "stage_reviewed_source_paths_preserved": source["stage_reviewed_source_paths_preserved"],
            "manager_source_operation_count": source["manager_source_operation_count"],
            "manager_stage_path_overlap": source["stage_manager_source_path_overlap"],
            "source_fusion_receipt": evidence_ref(SOURCE_RECEIPT_PATH),
            "r1_delta_receipt_sha256": source["r1_delta_receipt_sha256"],
            "r2_delta_receipt_sha256": source["r2_delta_receipt_sha256"],
            "r2_release_manifest_sha256": source["r2_release_manifest_sha256"],
        },
        "final_candidate_inventory": {
            **evidence_ref(INVENTORY_PATH),
            "entry_count": len(inventory),
            "inventory_sha256": inventory_sha,
            "targeted_check_inventory_sha256": targeted["candidate_tree_inventory_sha256_after"],
        },
        "build": {
            "receipt": evidence_ref(BUILD_RECEIPT_PATH),
            "exit_code": build["exit_code"],
            "vite_version": build["vite_version"],
            "manager_workspace_sha256": build["manager_workspace_sha256"],
            "daily_channels_sha256": build["daily_channels_sha256"],
            "dist_after_count": build["dist_after_count"],
            "dist_inventory_sha256": build["dist_after_inventory_sha256"],
            "entrypoints_and_assets_present": build["all_expected_entrypoints_and_assets_present"],
        },
        "targeted_checks": {
            "receipt": evidence_ref(TARGETED_RECEIPT_PATH),
            "status": targeted["status"],
            "candidate_imports_loaded_from_candidate": targeted["import_identity"]["all_modules_loaded_from_candidate"],
            "commands": [
                {"name": row["name"], "exit_code": row["exit_code"], "log_path": row["log_path"], "log_sha256": row["log_sha256"], "junit": row["junit"]}
                for row in targeted["commands"]
            ],
            "ui_tests": {"files_passed": 2, "tests_passed": int(ui_match.group(1)), "tests_failed": int(ui_match.group(2) or 0), "log": evidence_ref(UI_LOG)},
            "python_tests": {"tests": py_result["tests"], "failures": py_result["failures"], "errors": py_result["errors"], "junit": evidence_ref(PYTHON_JUNIT)},
            "ui_test_source_bindings": targeted["ui_test_source_bindings"],
            "candidate_tree_unchanged_during_checks": targeted["candidate_tree_unchanged_during_checks"],
            "dependency_links_removed": {
                "candidate_web": targeted["temporary_dependency_link"]["removed"],
                "ui_harness": targeted["ui_harness_dependency_link"]["removed"],
            },
        },
        "prior_manager_matrix_context": prior_matrix,
        "release_gate": {
            "status": "CANNOT_CONFIRM",
            "reason": "Parent Stage publisher historical-result-protection validation remains unresolved. Parent reported 59 date-by-stage historical rows whose only delta was RESEARCH_ONLY=true; this writer did not widen the validator allowance or claim publisher acceptance.",
            "deployment_performed": False,
        },
        "scope_claims": {
            "service_or_launchagent_changed": False,
            "business_state_changed": False,
            "live_api_verified": False,
            "ui_verified_against_running_service": False,
            "real_owner_refresh_performed": False,
            "natural_run_verified": False,
            "research_only": True,
        },
    }
    RECEIPT_PATH.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": receipt["status"],
        "candidate_inventory_count": len(inventory),
        "candidate_inventory_sha256": inventory_sha,
        "ui_tests": receipt["targeted_checks"]["ui_tests"],
        "python_tests": receipt["targeted_checks"]["python_tests"],
        "release_gate": receipt["release_gate"]["status"],
        "inventory_receipt": str(INVENTORY_PATH),
        "acceptance_receipt": str(RECEIPT_PATH),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
