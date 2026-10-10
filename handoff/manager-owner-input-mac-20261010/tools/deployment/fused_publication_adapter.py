#!/usr/bin/env python3
"""Prepare or publish the exact reviewed Stage R4 + manager source union.

This task-local adapter uses the Stage R5 wrapper for its read-only research,
history, static, and runtime checks. It replaces only the wrapper's single-
module candidate verifier with a validator for the frozen Stage+manager union.
The publication transaction remains the pinned Issue32 publisher's lock, CAS,
launch, and rollback implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import stat
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1")
FUSED_RELEASE_ROOT = ROOT / "candidate/stage_r4_manager_r2_owner_input_r1_fused_r1"
APP_ROOT = FUSED_RELEASE_ROOT / "app"
PLAN_ROOT = ROOT / "deployment"
PLAN_PATH = PLAN_ROOT / "verified-publication-plan.json"
DELTA_PATH = FUSED_RELEASE_ROOT / "fused-stage-manager-delta-receipt.json"
MANIFEST_PATH = FUSED_RELEASE_ROOT / "release-manifest.json"
STAGED_PLIST_PATH = PLAN_ROOT / "com.lexi.v35.api-only.plist"
ACCEPTANCE_RECEIPT = ROOT / "evidence/owner_input_r1/fused_candidate_acceptance_receipt.json"
FUSION_RECEIPT = ROOT / "evidence/owner_input_r1/stage_r4_fused_source_receipt.json"
FUSION_PLAN = ROOT / "candidate/stage_r4_manager_r2_owner_input_r1_fusion_preflight/integration_plan.json"
STAGE_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009")
STAGE_RELEASE_ROOT = STAGE_ROOT / "candidate/mac_apply_20261010_r4_fix_01/integration/candidate/stage-research-r4-20261009"
STAGE_MANIFEST_PATH = STAGE_RELEASE_ROOT / "release-manifest.json"
CURRENT_STAGE_RELEASE_ROOT = STAGE_ROOT / "candidate/mac_apply_20261010_r5_02/integration/candidate/stage-research-r4-20261009"
CURRENT_STAGE_APP_ROOT = CURRENT_STAGE_RELEASE_ROOT / "app"
CURRENT_STAGE_MANIFEST_PATH = CURRENT_STAGE_RELEASE_ROOT / "release-manifest.json"
CURRENT_STAGE_MANIFEST_SHA256 = "a162a878c01b89f6769710f83bc0907467a05bf18d6e5838b760c7c83efe72d6"
CURRENT_STAGE_ACTIVE_PLIST_SHA256 = "6cb00de89be004b8bba2981be437d241c3d2abf431965593ac37589f991a99a3"
CURRENT_STAGE_INVENTORY_SHA256 = "7a93420049f0558c4efda2feb05cd5831e4efc5a15b92fb2b445eb46a30dafe8"
ISSUE32_PREVIOUS_PLAN_SHA256 = "f00d7150a8accbb50176e0315478aa6a5ce9ff00e1165f50577dccc8e2e79f4f"
ISSUE32_PREVIOUS_ADAPTER_SHA256 = "1715eec7e05074bec4939c7ff065a6a198410e342bb1cb657e37c86ebd82abba"
ISSUE32_PRESERVED_PLAN = ROOT / "evidence/review/verified_publication_plan.issue32_base.json"
ISSUE32_PRESERVED_STAGED_PLIST = ROOT / "evidence/review/staged_api_plist.issue32_base.plist"
ISSUE32_PRESERVED_DELTA = ROOT / "evidence/review/fused_delta_receipt.issue32_base.json"
ISSUE32_PRESERVED_MANIFEST = ROOT / "evidence/review/fused_release_manifest.issue32_base.json"
R5_REBASE_RECEIPT = ROOT / "evidence/review/fused_publication_stage_r5_rebase_receipt.json"
STAGE_PREPARATION = STAGE_ROOT / "candidate/mac_apply_20261010_r4_fix_01/integration/PREPARATION_RECEIPT.json"
STAGE_PRESERVED_PLAN = STAGE_ROOT / "candidate/mac_apply_20261010_r4_fix_01/integration/stage-publication/api-only-preserved-plan.json"
R2_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_DEPLOY_20261009")
R2_DELTA_PATH = R2_ROOT / "evidence/validator_r1/r2_delta_receipt.json"
R1_DELTA_PATH = ROOT / "evidence/owner_input_r1/candidate_delta_receipt.json"
R5_PACKAGE = STAGE_ROOT / "local_fix/r4_mac_fix_20261010_r5"
WRAPPER_PATH = R5_PACKAGE / "tools/stage_api_release.py"
EXPECTED_WRAPPER_SHA256 = "f9aee4ff7770174d6671df7cdf9e5815fcf184c41788bb13d3c6e76b111b1f02"
PUBLISHER_PATH = R5_PACKAGE / "test_support/publication/api_only_cutover_issue32_r4.py"
GUARD_PATH = R5_PACKAGE / "release_tools/after/ops/api_release_integration.py"
REVIEW_SCHEMA = "v4.fused_stage_manager_independent_publication_review.v1"
RELEASE_ID = FUSED_RELEASE_ROOT.name
CONFIRM_EXECUTE = "SWITCH_API_ONLY_TO_FUSED_STAGE_R4_MANAGER_R2_OWNER_INPUT_R1"

EXPECTED_STAGE_REVIEWED_PATHS = frozenset({
    "apps/api/v35_api/app.py",
    "apps/web/src/App.vue",
    "apps/web/src/components/review/StageExecutionEvidencePanel.vue",
    "apps/web/src/contracts/runtime.ts",
    "stage_center/approved_research_read.json",
    "stage_center/approved_research_read.sha256",
    "stage_center/consumer.py",
    "stage_center/execution_evidence.py",
    "stage_center/research_read_binding.py",
})


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError(f"EXACT_JSON_FILE_REQUIRED:{path}")
    raw = path.read_bytes()
    value = json.loads(raw, object_pairs_hook=_unique_pairs,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError("JSON_NONFINITE")))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON_DUPLICATE_KEY:" + key)
        result[key] = value
    return result


def _load_pinned(path: Path, digest: str, name: str):
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError(f"PINNED_SOURCE_NOT_EXACT_FILE:{path}")
    raw = path.read_bytes()
    if _sha(raw) != digest:
        raise ValueError(f"PINNED_SOURCE_SHA_MISMATCH:{path.name}")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def _write_once(path: Path, raw: bytes, writer) -> None:
    if os.path.lexists(path):
        raise FileExistsError(f"REFUSE_EXISTING_OUTPUT:{path}")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    writer._write_exclusive(path, raw, mode=0o444)
    if path.read_bytes() != raw:
        raise ValueError(f"OUTPUT_WRITEBACK_MISMATCH:{path}")


def _replace_from_preserved_preimage(path: Path, raw: bytes, writer, wrapper,
                                     expected_sha256: str, preserved_path: Path) -> None:
    current_raw = wrapper._read(path)
    if _sha(current_raw) != expected_sha256:
        raise ValueError(f"REBASE_PREIMAGE_SHA_MISMATCH:{path}")
    preserved_raw = wrapper._read(preserved_path)
    if preserved_raw != current_raw or _sha(preserved_raw) != expected_sha256:
        raise ValueError(f"REBASE_PREIMAGE_ARCHIVE_MISMATCH:{preserved_path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    temporary = path.with_name(path.name + ".stage-r5-rebase.tmp")
    if os.path.lexists(temporary):
        raise FileExistsError(f"REFUSE_EXISTING_REBASE_TEMPORARY:{temporary}")
    writer._write_exclusive(temporary, raw, mode=mode)
    try:
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)
    if wrapper._read(path) != raw:
        raise ValueError(f"REBASE_WRITEBACK_MISMATCH:{path}")


def _stage_manager_source_sets(stage_manifest: Mapping[str, Any], fusion_receipt: Mapping[str, Any],
                               r2_delta: Mapping[str, Any], r1_delta: Mapping[str, Any],
                               acceptance: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    integration = stage_manifest.get("api_integration")
    if not isinstance(integration, dict) or not isinstance(integration.get("delta_entries"), list):
        raise ValueError("STAGE_DELTA_RECEIPT_MISSING")
    stage_paths = {row.get("path") for row in integration["delta_entries"]
                   if isinstance(row, dict) and not str(row.get("path", "")).startswith("apps/web/dist/")}
    reviewed = {row.get("path") for row in acceptance.get("provenance", {}).get("stage_reviewed_source_paths_preserved", [])
                if isinstance(row, dict)}
    if stage_paths != EXPECTED_STAGE_REVIEWED_PATHS or reviewed != EXPECTED_STAGE_REVIEWED_PATHS:
        raise ValueError("STAGE_SOURCE_PATH_SET_MISMATCH")

    r2_paths = {row.get("path") for row in r2_delta.get("entries", []) if isinstance(row, dict)
                and not str(row.get("path", "")).startswith("apps/web/dist/")}
    r1_paths = {row.get("path") for row in r1_delta.get("changed_paths", []) if isinstance(row, dict)}
    if len(r2_paths) != 15 or len(r1_paths) != 2:
        raise ValueError("MANAGER_R2_R1_SOURCE_COUNTS_MISMATCH")
    overlap = r2_paths & r1_paths
    if overlap != {"v4/manager_research/workspace.py"}:
        raise ValueError("MANAGER_R2_R1_OVERRIDE_SET_MISMATCH")
    manager_paths = r2_paths | r1_paths
    if len(manager_paths) != 16:
        raise ValueError("MANAGER_SOURCE_UNION_COUNT_MISMATCH")

    operations = fusion_receipt.get("source_operations")
    final_changes = fusion_receipt.get("source_changes_vs_stage_base")
    if not isinstance(operations, list) or not isinstance(final_changes, list):
        raise ValueError("FUSION_SOURCE_RECEIPT_INCOMPLETE")
    operation_paths = {row.get("path") for row in operations if isinstance(row, dict)}
    operation_r2 = {row.get("path") for row in operations if isinstance(row, dict)
                    and row.get("category") == "R2_SOURCE"}
    operation_r1 = {row.get("path") for row in operations if isinstance(row, dict)
                    and row.get("category") == "OWNER_INPUT_R1_SOURCE"}
    final_paths = {row.get("path") for row in final_changes if isinstance(row, dict)}
    if (operation_paths != manager_paths or final_paths != manager_paths
            or operation_r2 != r2_paths
            or operation_r1 != r1_paths - {"v4/manager_research/workspace.py"}):
        raise ValueError("FUSION_FINAL_SOURCE_PATH_SET_MISMATCH")
    r1_by_path = {row["path"]: row for row in r1_delta["changed_paths"]}
    final_by_path = {row["path"]: row for row in final_changes}
    for path in r1_paths:
        if final_by_path[path]["after"].get("sha256") != r1_by_path[path].get("after_sha256"):
            raise ValueError("R1_FINAL_SOURCE_SHA_MISMATCH:" + path)
    # R2 workspace is an intermediate operation; R1's final bytes are authoritative.
    return stage_paths, manager_paths


def _validate_receipts(writer, guard, stage_manifest: dict[str, Any], fusion_receipt: dict[str, Any],
                       acceptance: dict[str, Any], fusion_plan: dict[str, Any],
                       r2_delta: dict[str, Any], r1_delta: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if stage_manifest.get("candidate", {}).get("release_id") != "stage-research-r4-20261009":
        raise ValueError("STAGE_RELEASE_ID_MISMATCH")
    if stage_manifest.get("activation_status") != "NOT_ACTIVATED" or stage_manifest.get("deployment_status") not in (False, "CANNOT_CONFIRM"):
        raise ValueError("STAGE_BASE_NOT_CANDIDATE")
    if fusion_receipt.get("status") != "PASS" or fusion_receipt.get("service_or_live_state_changed") is not False:
        raise ValueError("FUSION_RECEIPT_NOT_PASS")
    if acceptance.get("candidate_disposition") != "LOCAL_CANDIDATE_ONLY":
        raise ValueError("FUSED_CANDIDATE_DISPOSITION_INVALID")
    for key, expected in (("RESEARCH_ONLY", True), ("production_allowed", False),
                          ("buy_gate_updated", False), ("orders_sent", False)):
        if fusion_receipt.get("research_only_flags", {}).get(key) is not expected:
            raise ValueError("FUSION_SAFETY_FLAGS_INVALID:" + key)
    input_rows = fusion_plan.get("inputs", {})
    if (input_rows.get("r2_release_manifest_sha256") != fusion_receipt.get("r2_release_manifest_sha256")
            or input_rows.get("r2_delta_receipt_sha256") != fusion_receipt.get("r2_delta_receipt_sha256")
            or input_rows.get("r1_source_delta_receipt_sha256") != fusion_receipt.get("r1_delta_receipt_sha256")):
        raise ValueError("FUSION_INPUT_RECEIPT_BINDING_MISMATCH")
    if (fusion_receipt.get("plan_path") != str(FUSION_PLAN)
            or fusion_receipt.get("plan_sha256") != _sha(FUSION_PLAN.read_bytes())):
        raise ValueError("FUSION_PLAN_SHA_MISMATCH")
    r2_manifest_path = Path(input_rows.get("r2_release_root", "")) / "release-manifest.json"
    if (not r2_manifest_path.is_file()
            or _sha(r2_manifest_path.read_bytes()) != input_rows.get("r2_release_manifest_sha256")):
        raise ValueError("R2_RELEASE_MANIFEST_SHA_MISMATCH")
    acceptance_fusion = acceptance.get("provenance", {}).get("source_fusion_receipt", {})
    if (acceptance_fusion.get("path") != str(FUSION_RECEIPT)
            or acceptance_fusion.get("sha256") != _sha(FUSION_RECEIPT.read_bytes())):
        raise ValueError("ACCEPTANCE_FUSION_RECEIPT_BINDING_MISMATCH")
    if (input_rows.get("r2_delta_receipt") != str(R2_DELTA_PATH)
            or input_rows.get("r1_source_delta_receipt") != str(R1_DELTA_PATH)
            or _sha(R2_DELTA_PATH.read_bytes()) != input_rows.get("r2_delta_receipt_sha256")
            or _sha(R1_DELTA_PATH.read_bytes()) != input_rows.get("r1_source_delta_receipt_sha256")):
        raise ValueError("R1_R2_SOURCE_RECEIPT_SHA_MISMATCH")
    r1_review_path = Path(input_rows.get("r1_independent_review_receipt", ""))
    if (not r1_review_path.is_file()
            or _sha(r1_review_path.read_bytes()) != input_rows.get("r1_independent_review_sha256")
            or input_rows.get("r1_independent_verdict", {}).get("REVIEWED") != "PASS_CORRECTED_RUN_EVIDENCE"):
        raise ValueError("R1_INDEPENDENT_REVIEW_PIN_MISMATCH")
    if (r2_delta.get("schema_version") != "v4.api_release_delta_receipt.v1"
            or r2_delta.get("base", {}).get("release_id") != "issue32_preselection_api_actual_r4"
            or r2_delta.get("base", {}).get("release_manifest_sha256") != input_rows.get("r2_base_manifest_sha256")
            or r1_delta.get("schema_version") != "owner_input_r2_candidate_delta.v1"
            or r1_delta.get("base_root") != input_rows.get("r2_app_root")
            or r1_delta.get("candidate_root") != input_rows.get("r1_candidate_app_root")):
        raise ValueError("MANAGER_SOURCE_DELTA_BASE_BINDING_MISMATCH")
    stage_paths, manager_paths = _stage_manager_source_sets(
        stage_manifest, fusion_receipt, r2_delta, r1_delta, acceptance)
    candidate_by_path = {row["path"]: row for row in guard.inventory_tree(APP_ROOT)}
    stage_integration = stage_manifest.get("api_integration", {})
    stage_expected = {row["path"]: row.get("after_sha256") for row in stage_integration["delta_entries"]
                      if isinstance(row, dict) and row.get("path") in stage_paths}
    manager_expected = {row["path"]: row.get("after", {}).get("sha256") for row in fusion_receipt["source_changes_vs_stage_base"]
                        if isinstance(row, dict) and row.get("path") in manager_paths}
    if set(stage_expected) != stage_paths or set(manager_expected) != manager_paths:
        raise ValueError("SOURCE_FINAL_SHA_ROWS_INCOMPLETE")
    for owner, expected_rows in (("stage", stage_expected), ("manager", manager_expected)):
        for path, digest in expected_rows.items():
            if candidate_by_path.get(path, {}).get("sha256") != digest:
                raise ValueError(f"FINAL_SOURCE_SHA_MISMATCH:{owner}:{path}")
    accepted_inventory = acceptance.get("final_candidate_inventory", {})
    if (accepted_inventory.get("entry_count") != len(candidate_by_path)
            or accepted_inventory.get("inventory_sha256") != guard.inventory_digest(list(candidate_by_path.values()))):
        raise ValueError("FINAL_ACCEPTED_CANDIDATE_INVENTORY_MISMATCH")
    active = guard.read_active_release(writer.ACTIVE_API_PLIST)
    base_record = guard._base_binding(active)
    current_base_manifest = _read_json(CURRENT_STAGE_MANIFEST_PATH)
    if _sha(CURRENT_STAGE_MANIFEST_PATH.read_bytes()) != CURRENT_STAGE_MANIFEST_SHA256:
        raise ValueError("CURRENT_STAGE_MANIFEST_SHA_MISMATCH")
    current_candidate = current_base_manifest.get("candidate", {})
    current_inventory_record = current_base_manifest.get("application_inventory", {})
    current_inventory = guard.inventory_tree(CURRENT_STAGE_APP_ROOT)
    current_inventory_sha = guard.inventory_digest(current_inventory)
    if (current_candidate.get("release_id") != "stage-research-r4-20261009"
            or current_candidate.get("root") != str(CURRENT_STAGE_RELEASE_ROOT)
            or current_candidate.get("app_root") != str(CURRENT_STAGE_APP_ROOT)
            or current_inventory_record.get("entry_count") != len(current_inventory)
            or current_inventory_record.get("aggregate_sha256") != CURRENT_STAGE_INVENTORY_SHA256
            or current_inventory_sha != CURRENT_STAGE_INVENTORY_SHA256):
        raise ValueError("CURRENT_STAGE_MANIFEST_INVENTORY_BINDING_MISMATCH")
    frozen_stage_inventory = guard.inventory_tree(STAGE_RELEASE_ROOT / "app")
    if (len(frozen_stage_inventory) != len(current_inventory)
            or guard.inventory_digest(frozen_stage_inventory) != current_inventory_sha):
        raise ValueError("CURRENT_STAGE_DIFFERS_FROM_FROZEN_STAGE_SOURCE_BASE")
    expected_current_base = {
        "api_plist_path": str(writer.ACTIVE_API_PLIST),
        "api_plist_sha256": CURRENT_STAGE_ACTIVE_PLIST_SHA256,
        "app_root": str(CURRENT_STAGE_APP_ROOT),
        "application_inventory_entry_count": len(current_inventory),
        "application_inventory_sha256": current_inventory_sha,
        "release_id": current_candidate["release_id"],
        "release_manifest_path": str(CURRENT_STAGE_MANIFEST_PATH),
        "release_manifest_sha256": CURRENT_STAGE_MANIFEST_SHA256,
        "release_root": str(CURRENT_STAGE_RELEASE_ROOT),
    }
    if base_record != expected_current_base:
        raise ValueError("ACTIVE_API_POINTER_NOT_CURRENT_STAGE_R5_BASE")
    current_by_path = {row["path"]: row for row in current_inventory}
    for path, digest in stage_expected.items():
        if current_by_path.get(path, {}).get("sha256") != digest:
            raise ValueError("CURRENT_STAGE_REVIEWED_SOURCE_SHA_MISMATCH:" + path)
    base_manifest = _read_json(STAGE_MANIFEST_PATH)
    if _sha(STAGE_MANIFEST_PATH.read_bytes()) != fusion_receipt.get("stage_release_manifest_sha256"):
        raise ValueError("STAGE_MANIFEST_SHA_MISMATCH")
    if _sha(STAGE_MANIFEST_PATH.read_bytes()) != acceptance.get("provenance", {}).get("stage_release_manifest", {}).get("sha256"):
        raise ValueError("ACCEPTANCE_STAGE_MANIFEST_SHA_MISMATCH")
    stage_delta_path = STAGE_RELEASE_ROOT / str(stage_manifest["api_integration"].get("delta_receipt_file", ""))
    if (_sha(stage_delta_path.read_bytes()) != stage_manifest["api_integration"].get("delta_receipt_sha256")
            or stage_manifest["api_integration"].get("module_scope", {}).get("module") != "stage"):
        raise ValueError("STAGE_SOURCE_DELTA_RECEIPT_SHA_MISMATCH")
    if fusion_receipt.get("stage_release_root") != str(STAGE_RELEASE_ROOT):
        raise ValueError("STAGE_ROOT_MISMATCH")
    if not isinstance(base_manifest.get("api_integration"), dict):
        raise ValueError("STAGE_MANIFEST_INTEGRATION_INVALID")
    return active, sorted(stage_paths), {"stage": sorted(stage_paths), "manager": sorted(manager_paths)}


def _composite_delta(writer, guard, active: Mapping[str, Any], owners: Mapping[str, list[str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    base_app = Path(active["app_root"])
    base_inventory = guard._inventory_snapshot(base_app)["entries"]
    candidate_inventory = guard._inventory_snapshot(APP_ROOT)["entries"]
    base_by = {row["path"]: row for row in base_inventory}
    after_by = {row["path"]: row for row in candidate_inventory}
    stage_reviewed_paths = set(owners["stage"])
    stage_changed_paths = {path for path in stage_reviewed_paths if base_by.get(path) != after_by.get(path)}
    manager_paths = set(owners["manager"])
    source_paths = stage_changed_paths | manager_paths
    static_before = guard.static_inventory_record(base_inventory)
    static_after = guard.static_inventory_record(candidate_inventory)
    static_paths = {path for path in set(base_by) | set(after_by)
                    if path.startswith(guard.STATIC_ROOT + "/") and base_by.get(path) != after_by.get(path)}
    expected = source_paths | static_paths
    actual_changed = {path for path in set(base_by) | set(after_by) if base_by.get(path) != after_by.get(path)}
    if expected != actual_changed:
        extras = sorted(actual_changed - expected)
        missing = sorted(expected - actual_changed)
        raise ValueError(f"FUSED_EXACT_DELTA_SET_MISMATCH:extra={extras[:5]}:missing={missing[:5]}")
    entries: list[dict[str, Any]] = []
    for path in sorted(expected):
        before = base_by.get(path); after = after_by.get(path)
        before_path = base_app / path; after_path = APP_ROOT / path
        before_raw = before_path.read_bytes() if before is not None else None
        after_raw = after_path.read_bytes() if after is not None else None
        diff_sha = hunk_count = None
        if before_raw is not None:
            diff_sha, hunk_count = guard._diff_proof(before_raw, after_raw if after_raw is not None else b"")
        entries.append({
            "path": path,
            "before_sha256": before.get("sha256") if before else None,
            "after_sha256": after.get("sha256") if after else None,
            "before_mode": before.get("mode") if before else None,
            "after_mode": after.get("mode") if after else None,
            "unified_diff_sha256": diff_sha,
            "unified_diff_hunk_count": hunk_count,
            "owner": ("stage" if path in stage_changed_paths else "manager"
                      if path in manager_paths else "rebuilt_static"),
        })
    proof = {"schema_version": guard.STATIC_SCHEMA_VERSION, "root": guard.STATIC_ROOT,
             "before": static_before, "after": static_after}
    standard_entries = [{key: row[key] for key in (
        "path", "before_sha256", "after_sha256", "before_mode", "after_mode",
        "unified_diff_sha256", "unified_diff_hunk_count") } for row in entries]
    records, preserved = guard._verify_delta_files(
        base_app=base_app, candidate_app=APP_ROOT,
        entries=standard_entries, static_tree=proof)
    directories = guard._directory_preservation(
        guard._inventory_snapshot(base_app), guard._inventory_snapshot(APP_ROOT), standard_entries)
    receipt = {
        "schema_version": "v4.api_release_fused_stage_manager_delta.v1",
        "base": guard._base_binding(active),
        "source_receipts": {
            "stage_manifest": {"path": str(STAGE_MANIFEST_PATH), "sha256": _sha(STAGE_MANIFEST_PATH.read_bytes())},
            "current_stage_base_manifest": {"path": str(CURRENT_STAGE_MANIFEST_PATH),
                "sha256": _sha(CURRENT_STAGE_MANIFEST_PATH.read_bytes())},
            "stage_delta_receipt": {"path": str(STAGE_RELEASE_ROOT / str(
                _read_json(STAGE_MANIFEST_PATH)["api_integration"]["delta_receipt_file"])),
                "sha256": _sha((STAGE_RELEASE_ROOT / str(
                    _read_json(STAGE_MANIFEST_PATH)["api_integration"]["delta_receipt_file"])).read_bytes())},
            "manager_fusion_receipt": {"path": str(FUSION_RECEIPT), "sha256": _sha(FUSION_RECEIPT.read_bytes())},
            "manager_fusion_plan": {"path": str(FUSION_PLAN), "sha256": _sha(FUSION_PLAN.read_bytes())},
            "r2_delta_receipt": {"path": str(R2_DELTA_PATH), "sha256": _sha(R2_DELTA_PATH.read_bytes())},
            "r1_delta_receipt": {"path": str(R1_DELTA_PATH), "sha256": _sha(R1_DELTA_PATH.read_bytes())},
        },
        "stage_source_count": len(stage_changed_paths),
        "stage_reviewed_source_path_count": len(stage_reviewed_paths),
        "stage_reviewed_source_paths_preserved": sorted(stage_reviewed_paths),
        "stage_source_paths_changed": sorted(stage_changed_paths),
        "manager_source_count": len(manager_paths),
        "rebuilt_static_count": len(static_paths),
        "entries": entries,
        "static_tree": proof,
        "directory_preservation": directories,
        "non_delta_active_release_bytes_preserved": True,
        "non_delta_entry_count": len(preserved),
        "non_delta_inventory_sha256": guard.inventory_digest(preserved),
        "application_inventory_sha256": guard.inventory_digest(candidate_inventory),
        "research_only_flags": {"RESEARCH_ONLY": True, "production_allowed": False,
            "buy_gate_updated": False, "orders_sent": False},
    }
    integration = {
        "schema_version": "v4.api_release_fused_stage_manager_integration.v1",
        "status": "PASS", "base": guard._base_binding(active),
        "candidate": {"release_id": RELEASE_ID, "release_root": str(FUSED_RELEASE_ROOT),
            "app_root": str(APP_ROOT), "manifest_path": str(MANIFEST_PATH),
            "application_inventory_sha256": guard.inventory_digest(candidate_inventory),
            "application_inventory_entry_count": len(candidate_inventory)},
        "active_api_plist_sha256": active["api_plist_sha256"], "active_pointer": "base",
        "shared_lock_path": str(writer.ACTIVE_API_PLIST.with_name(".com.lexi.v35.api-only.release.lock")),
        "delta_receipt_file": DELTA_PATH.name, "delta_receipt_sha256": _sha(_json_bytes(receipt)),
        "delta_paths": sorted(expected), "delta_entries": records,
        "module_source_paths": {"stage": sorted(stage_changed_paths), "manager": sorted(manager_paths)},
        "preserved_module_source_paths": {"stage": sorted(stage_reviewed_paths)},
        "rebuilt_static_paths": sorted(static_paths),
        "directory_preservation": directories,
        "non_delta_active_release_bytes_preserved": True,
        "non_delta_entry_count": len(preserved),
        "non_delta_inventory_sha256": guard.inventory_digest(preserved),
        "static_tree": proof,
    }
    return receipt, integration


def _candidate_manifest(guard, integration: Mapping[str, Any], delta: Mapping[str, Any]) -> dict[str, Any]:
    inventory = guard.inventory_tree(APP_ROOT)
    return {
        "schema_version": "v4.release_candidate.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_status": "READY_FOR_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": False,
        "candidate": {"root": str(FUSED_RELEASE_ROOT), "app_root": str(APP_ROOT),
            "release_id": RELEASE_ID, "formal_release_root": None,
            "data_copy_performed": False, "ignored_runtime_data_copied": False},
        "application_inventory": {"entry_count": len(inventory),
            "aggregate_sha256": guard.inventory_digest(inventory), "entries": inventory},
        "api_integration": integration,
        "composite_delta_receipt": {"path": str(DELTA_PATH), "sha256": _sha(_json_bytes(delta))},
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
            "buy_gate_updated": False, "orders_sent": False},
        "natural_verified": False, "execution_verified": False,
        "source": {"stage_manifest_sha256": _sha(STAGE_MANIFEST_PATH.read_bytes()),
            "current_stage_base_manifest_sha256": _sha(CURRENT_STAGE_MANIFEST_PATH.read_bytes()),
            "manager_fusion_receipt_sha256": _sha(FUSION_RECEIPT.read_bytes())},
    }


def _integration_for_pointer(writer, wrapper, guard, plan, pointer: str, lease=None) -> dict[str, Any]:
    if lease is not None:
        writer._require_release_lock(lease)
    manifest = _read_json(MANIFEST_PATH)
    manifest_sha = _sha(MANIFEST_PATH.read_bytes())
    active = guard.read_active_release(writer.ACTIVE_API_PLIST)
    base_record = manifest.get("api_integration", {}).get("base")
    guard.verify_recorded_base(base_record)
    if pointer == "base":
        if guard._base_binding(active) != base_record:
            raise ValueError("ACTIVE_POINTER_NOT_RECORDED_BASE")
    elif pointer == "candidate":
        candidate = guard._candidate_identity(manifest, FUSED_RELEASE_ROOT, manifest_sha)
        if any(active.get(key) != candidate.get(key) for key in (
                "release_root", "app_root", "release_id", "release_manifest_sha256", "application_inventory_sha256")):
            raise ValueError("ACTIVE_POINTER_NOT_FUSED_CANDIDATE")
    else:
        raise ValueError("ACTIVE_POINTER_MODE_INVALID")
    delta = _read_json(DELTA_PATH)
    expected_delta_sha = plan["api_release_integration"]["delta_receipt_sha256"]
    if _sha(DELTA_PATH.read_bytes()) != expected_delta_sha:
        raise ValueError("FUSED_DELTA_RECEIPT_CHANGED")
    if delta.get("base") != base_record or delta.get("application_inventory_sha256") != manifest.get("application_inventory", {}).get("aggregate_sha256"):
        raise ValueError("FUSED_DELTA_BINDING_INVALID")
    if manifest.get("api_integration") != plan["api_release_integration"]:
        raise ValueError("FUSED_MANIFEST_INTEGRATION_DIFFERS_FROM_PLAN")
    manifest_candidate = guard._candidate_identity(manifest, FUSED_RELEASE_ROOT, manifest_sha)
    if manifest_candidate.get("application_inventory_sha256") != plan["target"]["application_inventory_sha256"]:
        raise ValueError("FUSED_MANIFEST_CANDIDATE_INVENTORY_MISMATCH")
    entries = [{key: row[key] for key in (
        "path", "before_sha256", "after_sha256", "before_mode", "after_mode",
        "unified_diff_sha256", "unified_diff_hunk_count") } for row in delta["entries"]]
    current_inventory = guard._inventory_snapshot(APP_ROOT)["entries"]
    if current_inventory != manifest["application_inventory"]["entries"]:
        raise ValueError("FUSED_CANDIDATE_INVENTORY_CHANGED")
    guard._verify_delta_files(base_app=Path(base_record["app_root"]), candidate_app=APP_ROOT,
                              entries=entries, static_tree=delta["static_tree"])
    if lease is not None:
        writer._require_release_lock(lease)
    active_sha = active["api_plist_sha256"]
    return {**plan["api_release_integration"], "active_pointer": pointer,
            "active_api_plist_sha256": active_sha}


def _new_plan(writer, wrapper, guard, publisher, stage_manifest: dict[str, Any],
              fusion_receipt: dict[str, Any], acceptance: dict[str, Any], fusion_plan: dict[str, Any],
              r2_delta: dict[str, Any], r1_delta: dict[str, Any], delta: dict[str, Any], integration: dict[str, Any],
              manifest_sha256: str | None = None) -> dict[str, Any]:
    before_raw = wrapper._read(writer.ACTIVE_API_PLIST)
    active = guard.read_active_release(writer.ACTIVE_API_PLIST)
    history_root, manager_root = wrapper._roots(publisher, before_raw)
    observed = publisher._observe_loaded()
    if observed.get("state") != "LOADED" or not observed.get("identity", {}).get("pid"):
        raise ValueError("CURRENT_API_RUNTIME_IDENTITY_UNVERIFIED")
    if publisher._identity_from_plist(before_raw) != {key: observed["identity"].get(key) for key in (
            "V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256")}:
        raise ValueError("CURRENT_API_RUNTIME_DOES_NOT_MATCH_PLIST")
    target = {"release_root": str(FUSED_RELEASE_ROOT), "app_root": str(APP_ROOT),
        "release_id": RELEASE_ID, "release_manifest_sha256": manifest_sha256 or _sha(MANIFEST_PATH.read_bytes()),
        "staged_api_plist_path": str(STAGED_PLIST_PATH), "staged_api_plist_sha256": None,
        "application_inventory_sha256": integration["candidate"]["application_inventory_sha256"]}
    staged = plistlib.dumps(wrapper._preserved_plist(publisher, before_raw, target), fmt=plistlib.FMT_XML, sort_keys=False)
    target["staged_api_plist_sha256"] = _sha(staged)
    guards = {"disabled_binding_path": str(publisher.DISABLED_BINDING_PATH),
              "disabled_binding_sha256": _sha(wrapper._read(publisher.DISABLED_BINDING_PATH))}
    plan = {"schema_version": wrapper.SCHEMA, "activation_status": "NOT_ACTIVATED",
        "automatic_activation": False, "plan_path": str(PLAN_PATH),
        "publication_root": str(PLAN_ROOT), "operation_root": str(PLAN_ROOT / "operations"),
        "source": {"publisher_path": str(PUBLISHER_PATH), "publisher_sha256": wrapper.PUBLISHER_SHA256,
            "stage_guard_path": str(GUARD_PATH), "stage_guard_sha256": wrapper.STAGE_GUARD_SHA256,
            "preparation_receipt_path": str(STAGE_PREPARATION), "preparation_receipt_sha256": _sha(STAGE_PREPARATION.read_bytes()),
            "preserving_plan_path": str(STAGE_PRESERVED_PLAN), "preserving_plan_sha256": _sha(STAGE_PRESERVED_PLAN.read_bytes()),
            "coordinator_path": str(R5_PACKAGE / "tools/prepare_live_release.py"),
            "binding_helper_path": str(R5_PACKAGE / "tools/prepare_research_binding.py"),
            "wrapper_sha256": wrapper._SELF_SHA256},
        "target": target, "manager_state_root": str(manager_root),
        "history": wrapper._history(history_root),
        "before": {"active_api_plist_path": str(publisher.ACTIVE_API_PLIST),
            "active_api_plist_sha256": _sha(before_raw),
            "active_api_plist_metadata": publisher._file_metadata(publisher.ACTIVE_API_PLIST),
            "loaded_identity": observed["identity"],
            "scheduler_plist_sha256": _sha(wrapper._read(publisher.ACTIVE_SCHEDULER_PLIST)),
            "stage_center_scheduler_plist_sha256": _sha(wrapper._read(publisher.STAGE_CENTER_SCHEDULER_PLIST))},
        "guards": guards, "api_release_integration": integration,
        "natural_verified": False, "execution_verified": False,
        "RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False}
    plan["research_binding"] = wrapper._binding(publisher, plan)
    plan["static_http"] = wrapper._static(guard, APP_ROOT)
    plan["historical_http"] = wrapper._history_http(publisher, plan["history"])
    plan["adapter_sha256"] = _sha(Path(__file__).read_bytes())
    plan["review_gate"] = {"schema_version": REVIEW_SCHEMA,
        "receipt_path": str(ROOT / "review/fused_publication_plan_review.json"),
        "status_required": "PASS", "plan_sha256_bound": True}
    return plan


def _load_runtime():
    wrapper_sha = _sha(WRAPPER_PATH.read_bytes())
    if wrapper_sha != EXPECTED_WRAPPER_SHA256:
        raise ValueError("STAGE_R5_WRAPPER_SHA_MISMATCH")
    wrapper = _load_pinned(WRAPPER_PATH, wrapper_sha, "_fused_stage_wrapper")
    publisher = wrapper._load_publisher(PUBLISHER_PATH)
    guard = wrapper._module(GUARD_PATH, wrapper.STAGE_GUARD_SHA256, "_fused_stage_guard")
    wrapper._pinned(R5_PACKAGE / "tools/prepare_live_release.py", wrapper.COORDINATOR_SHA256)
    wrapper._pinned(R5_PACKAGE / "tools/prepare_research_binding.py", wrapper.BINDING_HELPER_SHA256)
    wrapper._pinned(STAGE_PREPARATION, _sha(STAGE_PREPARATION.read_bytes()))
    wrapper._pinned(STAGE_PRESERVED_PLAN, _sha(STAGE_PRESERVED_PLAN.read_bytes()))
    return wrapper, publisher, guard


def prepare(rebase_existing: bool = False) -> dict[str, Any]:
    wrapper, publisher, guard = _load_runtime()
    previous_plan = None
    previous_plan_sha = None
    if rebase_existing:
        previous_plan_raw = wrapper._read(PLAN_PATH)
        previous_plan_sha = _sha(previous_plan_raw)
        if previous_plan_sha != ISSUE32_PREVIOUS_PLAN_SHA256:
            raise ValueError("ISSUE32_PREVIOUS_PLAN_SHA_MISMATCH")
        previous_plan = wrapper._plan(PLAN_PATH, previous_plan_sha)
        if (previous_plan.get("adapter_sha256") != ISSUE32_PREVIOUS_ADAPTER_SHA256
                or previous_plan.get("api_release_integration", {}).get("base", {}).get("release_id")
                   != "issue32_preselection_api_actual_r4"):
            raise ValueError("ISSUE32_PREVIOUS_PLAN_IDENTITY_MISMATCH")
        prior_artifacts = (
            (DELTA_PATH, ISSUE32_PRESERVED_DELTA,
             previous_plan["api_release_integration"]["delta_receipt_sha256"]),
            (MANIFEST_PATH, ISSUE32_PRESERVED_MANIFEST,
             previous_plan["target"]["release_manifest_sha256"]),
            (STAGED_PLIST_PATH, ISSUE32_PRESERVED_STAGED_PLIST,
             previous_plan["target"]["staged_api_plist_sha256"]),
            (PLAN_PATH, ISSUE32_PRESERVED_PLAN, previous_plan_sha),
        )
        for path, preserved_path, expected_sha in prior_artifacts:
            current_raw = wrapper._read(path)
            preserved_raw = wrapper._read(preserved_path)
            if (current_raw != preserved_raw or _sha(current_raw) != expected_sha
                    or _sha(preserved_raw) != expected_sha):
                raise ValueError(f"ISSUE32_PRIOR_ARTIFACT_BINDING_MISMATCH:{path.name}")
    stage_manifest = _read_json(STAGE_MANIFEST_PATH)
    fusion_receipt = _read_json(FUSION_RECEIPT)
    acceptance = _read_json(ACCEPTANCE_RECEIPT)
    fusion_plan = _read_json(FUSION_PLAN)
    r2_delta = _read_json(R2_DELTA_PATH)
    r1_delta = _read_json(R1_DELTA_PATH)
    _, _, owners = _validate_receipts(writer=publisher, guard=guard,
        stage_manifest=stage_manifest, fusion_receipt=fusion_receipt, acceptance=acceptance,
        fusion_plan=fusion_plan, r2_delta=r2_delta, r1_delta=r1_delta)
    active = guard.read_active_release(publisher.ACTIVE_API_PLIST)
    delta, integration = _composite_delta(publisher, guard, active, owners)
    delta_raw = _json_bytes(delta)
    manifest = _candidate_manifest(guard, integration, delta)
    manifest_raw = _json_bytes(manifest)
    staged_target = {"release_root": str(FUSED_RELEASE_ROOT), "app_root": str(APP_ROOT),
        "release_id": RELEASE_ID, "release_manifest_sha256": _sha(manifest_raw),
        "staged_api_plist_path": str(STAGED_PLIST_PATH), "staged_api_plist_sha256": "0" * 64}
    before_raw = wrapper._read(publisher.ACTIVE_API_PLIST)
    staged_obj = wrapper._preserved_plist(publisher, before_raw, staged_target)
    staged_raw = plistlib.dumps(staged_obj, fmt=plistlib.FMT_XML, sort_keys=False)
    staged_target["staged_api_plist_sha256"] = _sha(staged_raw)
    # Build the integration/plan with the final staged pointer identity.
    integration = {**integration, "active_pointer": "base",
                   "active_api_plist_sha256": _sha(before_raw),
                   "delta_receipt_sha256": _sha(delta_raw)}
    plan = _new_plan(publisher, wrapper, guard, publisher, stage_manifest,
        fusion_receipt, acceptance, fusion_plan, r2_delta, r1_delta, delta, integration,
        manifest_sha256=_sha(manifest_raw))
    # `_new_plan` re-derives target and staged bytes, so its result is the source of truth.
    if plan["target"]["staged_api_plist_sha256"] != _sha(staged_raw):
        raise ValueError("STAGED_PLIST_PREPARATION_CHANGED")
    plan_raw = _json_bytes(plan)
    if rebase_existing:
        assert previous_plan is not None and previous_plan_sha is not None
        _replace_from_preserved_preimage(DELTA_PATH, delta_raw, publisher, wrapper,
            previous_plan["api_release_integration"]["delta_receipt_sha256"], ISSUE32_PRESERVED_DELTA)
        _replace_from_preserved_preimage(MANIFEST_PATH, manifest_raw, publisher, wrapper,
            previous_plan["target"]["release_manifest_sha256"], ISSUE32_PRESERVED_MANIFEST)
        _replace_from_preserved_preimage(STAGED_PLIST_PATH, staged_raw, publisher, wrapper,
            previous_plan["target"]["staged_api_plist_sha256"], ISSUE32_PRESERVED_STAGED_PLIST)
        _replace_from_preserved_preimage(PLAN_PATH, plan_raw, publisher, wrapper,
            previous_plan_sha, ISSUE32_PRESERVED_PLAN)
    else:
        _write_once(DELTA_PATH, delta_raw, publisher)
        _write_once(MANIFEST_PATH, manifest_raw, publisher)
        _write_once(STAGED_PLIST_PATH, staged_raw, publisher)
        _write_once(PLAN_PATH, plan_raw, publisher)
    wrapper._stage_verify = lambda pub, grd, value, *, lease=None, active_pointer="base": _custom_stage_verify(
        wrapper, pub, grd, value, lease=lease, active_pointer=active_pointer)
    wrapper._preflight(plan, PLAN_PATH, _sha(plan_raw))
    result = {"status": "FUSED_PUBLICATION_PLAN_REBASED_TO_STAGE_R5_NOT_DEPLOYED"
              if rebase_existing else "FUSED_PUBLICATION_PLAN_PREPARED_NOT_DEPLOYED",
        "plan_path": str(PLAN_PATH), "plan_sha256": _sha(plan_raw),
        "adapter_sha256": plan["adapter_sha256"], "manifest_sha256": _sha(manifest_raw),
        "delta_receipt_sha256": _sha(delta_raw), "active_plist_sha256": plan["before"]["active_api_plist_sha256"],
        "staged_plist_sha256": plan["target"]["staged_api_plist_sha256"], "deployed": False}
    if rebase_existing:
        receipt = {
            "schema_version": "v4.fused_publication_stage_r5_rebase.v1",
            "status": result["status"],
            "prior_issue32_plan_sha256": previous_plan_sha,
            "prior_candidate_manifest_sha256": previous_plan["target"]["release_manifest_sha256"],
            "prior_composite_delta_sha256": previous_plan["api_release_integration"]["delta_receipt_sha256"],
            "new_plan_sha256": result["plan_sha256"],
            "new_adapter_sha256": result["adapter_sha256"],
            "new_candidate_manifest_sha256": result["manifest_sha256"],
            "new_composite_delta_sha256": result["delta_receipt_sha256"],
            "new_active_api_plist_sha256": result["active_plist_sha256"],
            "new_staged_api_plist_sha256": result["staged_plist_sha256"],
            "new_base": plan["api_release_integration"]["base"],
            "stage_r4_source_tree_sha256": CURRENT_STAGE_INVENTORY_SHA256,
            "stage_r5_active_manifest_sha256": CURRENT_STAGE_MANIFEST_SHA256,
            "stage_reviewed_source_paths_preserved": delta["stage_reviewed_source_paths_preserved"],
            "stage_source_delta_count": delta["stage_source_count"],
            "manager_source_delta_count": delta["manager_source_count"],
            "rebuilt_static_delta_count": delta["rebuilt_static_count"],
            "exact_delta_paths": [row["path"] for row in delta["entries"]],
            "preserved_issue32_artifacts": {
                "plan": str(ISSUE32_PRESERVED_PLAN),
                "manifest": str(ISSUE32_PRESERVED_MANIFEST),
                "delta": str(ISSUE32_PRESERVED_DELTA),
                "staged_api_plist": str(ISSUE32_PRESERVED_STAGED_PLIST),
            },
            "deployed": False,
            "natural_verified": False,
            "research_only_flags": {"RESEARCH_ONLY": True, "production_allowed": False,
                "buy_gate_updated": False, "orders_sent": False},
        }
        receipt_raw = _json_bytes(receipt)
        _write_once(R5_REBASE_RECEIPT, receipt_raw, publisher)
        result["rebase_receipt_path"] = str(R5_REBASE_RECEIPT)
        result["rebase_receipt_sha256"] = _sha(receipt_raw)
    return result


def _custom_stage_verify(wrapper, publisher, guard, plan, *, lease=None, active_pointer="base"):
    if lease is not None:
        publisher._require_release_lock(lease)
    result = _integration_for_pointer(publisher, wrapper, guard, plan, active_pointer, lease)
    if active_pointer == "base" and result != plan["api_release_integration"]:
        raise ValueError("FUSED_API_INTEGRATION_PLAN_MISMATCH")
    if active_pointer == "base" and result["active_api_plist_sha256"] != plan["before"]["active_api_plist_sha256"]:
        raise ValueError("BASE_API_PLIST_SHA_MISMATCH")
    if active_pointer == "candidate" and result["active_api_plist_sha256"] != plan["target"]["staged_api_plist_sha256"]:
        raise ValueError("CANDIDATE_API_PLIST_SHA_MISMATCH")
    return result


def _require_review(plan: Mapping[str, Any], plan_sha: str, receipt_path: Path, receipt_sha: str) -> None:
    if receipt_path.is_symlink() or not receipt_path.is_file() or receipt_path.resolve(strict=True) != receipt_path:
        raise ValueError("INDEPENDENT_REVIEW_RECEIPT_REQUIRED")
    raw = receipt_path.read_bytes()
    if _sha(raw) != receipt_sha:
        raise ValueError("INDEPENDENT_REVIEW_RECEIPT_SHA_MISMATCH")
    review = json.loads(raw, object_pairs_hook=_unique_pairs)
    required = {"schema_version": REVIEW_SCHEMA, "decision": "PASS",
        "plan_path": str(PLAN_PATH), "plan_sha256": plan_sha,
        "adapter_path": str(Path(__file__).resolve()), "adapter_sha256": plan["adapter_sha256"],
        "candidate_inventory_sha256": plan["target"]["application_inventory_sha256"]}
    if not isinstance(review, dict) or any(review.get(key) != value for key, value in required.items()):
        raise ValueError("INDEPENDENT_REVIEW_RECEIPT_BINDING_MISMATCH")
    if not isinstance(review.get("reviewer_identity"), str) or not review["reviewer_identity"]:
        raise ValueError("INDEPENDENT_REVIEWER_IDENTITY_REQUIRED")


def execute(plan_sha: str, current_sha: str, staged_sha: str,
            review_path: Path, review_sha: str, confirmation: str) -> dict[str, Any]:
    wrapper, publisher, guard = _load_runtime()
    if confirmation != CONFIRM_EXECUTE:
        raise ValueError("EXPLICIT_FUSED_PUBLICATION_CONFIRMATION_REQUIRED")
    raw = wrapper._read(PLAN_PATH)
    if _sha(raw) != plan_sha:
        raise ValueError("FUSED_PLAN_SHA_MISMATCH")
    plan = wrapper._plan(PLAN_PATH, plan_sha)
    if _sha(Path(__file__).read_bytes()) != plan.get("adapter_sha256"):
        raise ValueError("FUSED_ADAPTER_SHA_MISMATCH")
    _require_review(plan, plan_sha, review_path, review_sha)
    if current_sha != plan["before"]["active_api_plist_sha256"] or staged_sha != plan["target"]["staged_api_plist_sha256"]:
        raise ValueError("FUSED_EXPECTED_POINTER_SHA_MISMATCH")
    wrapper._stage_verify = lambda pub, grd, value, *, lease=None, active_pointer="base": _custom_stage_verify(
        wrapper, pub, grd, value, lease=lease, active_pointer=active_pointer)
    return wrapper.execute_stage_publication(plan_path=PLAN_PATH, expected_plan_sha256=plan_sha,
        confirmation=wrapper.CONFIRM_EXECUTE, expected_current_sha256=current_sha,
        expected_staged_sha256=staged_sha)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    sub.add_parser("rebase")
    run = sub.add_parser("execute")
    run.add_argument("--plan-sha256", required=True)
    run.add_argument("--current-plist-sha256", required=True)
    run.add_argument("--staged-plist-sha256", required=True)
    run.add_argument("--review-receipt", type=Path, required=True)
    run.add_argument("--review-receipt-sha256", required=True)
    run.add_argument("--confirmation", required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        result = prepare()
    elif args.command == "rebase":
        result = prepare(rebase_existing=True)
    else:
        result = execute(args.plan_sha256, args.current_plist_sha256, args.staged_plist_sha256,
                         args.review_receipt, args.review_receipt_sha256, args.confirmation)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
