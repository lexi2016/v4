#!/usr/bin/env python3
"""Read-only receipt cross-checks; never imports app or owner code.

Reads the supplied package and writes only receipt_crosschecks.json beside this
script. These checks cannot establish live API, UI, owner, or repair behavior.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "input_snapshot/package"
EVIDENCE = PACKAGE / "evidence"
OUTPUT = Path(__file__).resolve().parent / "receipt_crosschecks.json"
checks: list[dict] = []


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check(name: str, condition: bool) -> None:
    checks.append({"name": name, "pass": bool(condition)})


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


source = read_json(PACKAGE / "SOURCE_SNAPSHOT_MANIFEST.json")
refs = read_json(EVIDENCE / "SOURCE_REFERENCES.json")
projection = read_json(EVIDENCE / "live_ui_api_problem_projection.json")
runtime = read_json(EVIDENCE / "post_publication_runtime_review_20261010.json")
handoff = read_json(EVIDENCE / "fused_publication_api_handoff_20261010.json")
counter = read_json(EVIDENCE / "global_manifest_identity_counterfactual_receipt.json")
isolated = read_json(EVIDENCE / "isolated_real_owner_acceptance_receipt.json")
corrected = read_json(EVIDENCE / "corrected_isolated_owner_run_review_20261010.json")
ui = read_json(EVIDENCE / "UI_VISUAL_INSPECTION_20261010.json")
frontend = read_json(EVIDENCE / "frontend_boundary_receipt_20261010.json")
app = PACKAGE / "code/current_fused_app"

fixed = [row for row in source["files"] if row["source_type"] == "fixed_16_source_reference"]
check("fixed_reference_count", len(fixed) == len(refs["sources"]) == 16)
reference_results = []
for row in refs["sources"]:
    path = app / row["runtime_relative_path"]
    data = path.read_bytes()
    git_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    ok = hashlib.sha256(data).hexdigest() == row["sha256"] and git_blob == row["git_blob_sha"]
    reference_results.append({"path": row["runtime_relative_path"], "sha256_and_git_blob_match": ok})
    check("fixed_source_bytes:" + row["runtime_relative_path"], ok)
check("fixed_reference_commit_consistency", all(row["commit"] == source["candidate"]["fixed_commit"] for row in refs["sources"]))

calls = runtime["writer_readback"]["calls"]
later = runtime["independent_live_get"]
live_plan = later["plan_product"]
immediate = projection["immediate_owner_refresh_and_readbacks"]
check("immediate_request_order_and_status", [row["method"] for row in calls] == ["POST", "GET", "GET"] and all(row["http_status"] == 200 and row["plan_status"] == "CURRENT" for row in calls))
check("immediate_and_later_run_product_date_agree", all(row["run_id"] == live_plan["run_id"] == immediate["run_id"] and row["product_sha256"] == live_plan["product_sha256"] == immediate["product_sha256"] and row["date_bindings"] == later["current_date_bindings"] == later["saved_date_bindings"] == immediate["date_bindings"] for row in calls))
check("later_stale_and_identity_diff", live_plan["status"] == "STALE_INPUTS_CHANGED" and live_plan["consumed"] is False and later["current_input_identity"] != later["saved_input_identity"])
check("later_semantic_version_and_cutoff_equal", later["current_semantic_version"] == later["saved_semantic_version"] and later["current_research_cutoff"] == later["saved_research_cutoff"])
check("live_saved_file_and_counterfactual_same_plan_bytes", later["saved_plan_file_sha256_before_get"] == later["saved_plan_file_sha256_after_get"] == counter["plan_sha256"] == counter["expected_plan_sha256"])
check("handoff_plan_identity_agrees", handoff["owner_refresh"]["plan_identity"]["run_id"] == live_plan["run_id"] and handoff["owner_refresh"]["plan_identity"]["product_sha256"] == live_plan["product_sha256"])
check("deployed_channel_projection_agrees", handoff["owner_refresh"]["channels"] == list(projection["deployed_channel_summary"].values()))

leaves = counter["current_leaf_comparison"]
check("counterfactual_40_unique_leaf_metadata_pairs", len(leaves) == len({(r["payload_path"], r["receipt_path"]) for r in leaves}) == counter["unique_payload_receipt_pairs"] == 40)
check("counterfactual_leaf_entry_payload_equality", all(r["current_manifest_entry_sha256"] == r["payload_sha256_saved_and_current"] and r["saved_global_manifest_sha256"] == counter["saved_global_manifest_sha256"] and all(re.fullmatch(r"[0-9a-f]{64}", r[k]) for k in ["current_manifest_entry_sha256", "payload_sha256_saved_and_current", "receipt_sha256_saved_and_current"]) for r in leaves))
check("counterfactual_1970_count_claims_agree", counter["saved_material_count"] == counter["source_ref_count"] == counter["counterfactual"]["changed_source_ref_count"] == projection["backend_identity_review"]["source_ref_count"] == 1970)
check("counterfactual_identity_claims_agree", counter["counterfactual"]["base_input_identity"] == projection["backend_identity_review"]["counterfactual_base_input_identity"] and counter["counterfactual"]["counterfactual_input_identity"] == projection["backend_identity_review"]["counterfactual_input_identity"] and counter["counterfactual"]["base_input_identity"] != counter["counterfactual"]["counterfactual_input_identity"])
check("counterfactual_is_distinct_from_live_identity", counter["counterfactual"]["base_input_identity"] != later["saved_input_identity"] and counter["counterfactual"]["counterfactual_input_identity"] != later["current_input_identity"])
check("counterfactual_unique_live_cause_unconfirmed", counter["old_global_manifest_raw_bytes_retained"] is False and counter["old_manifest_semantic_delta_scope"] == "CANNOT_CONFIRM" and projection["backend_identity_review"]["live_stale_unique_cause"] == "CANNOT_CONFIRM")

check("corrected_isolated_run_distinct", isolated["owner_product"]["run_id"] == corrected["date_and_execution"]["plan_run_id"] == projection["corrected_isolated_owner_run"]["plan_run_id"] != live_plan["run_id"])
check("corrected_isolated_product_agrees", isolated["owner_product"]["product_sha256"] == corrected["owner_product"]["internal_sha256"] == projection["corrected_isolated_owner_run"]["product_sha256"])
check("corrected_isolated_stays_partial", corrected["owner_product"]["status"] == "PARTIAL" and corrected["owner_product"]["stock_count"] == 0 and corrected["same_app_readback"]["read_count"] == 2 and corrected["date_and_execution"]["natural_run_verified"] is False)
check("corrected_isolated_us_finance_ready_without_snapshot", isolated["actual_owner_inputs"]["external_finance_20261009"]["owner_payload_status"] == "READY" and isolated["actual_owner_inputs"]["external_finance_20261009"]["has_market_snapshot"] is False and isolated["four_channel_results"]["us_market"]["status"] == "CANNOT_CONFIRM")
check("corrected_screen_pending_gaps_and_units", corrected["behavior"]["history_pending"] == 693 and corrected["behavior"]["market_screen_gap_count"] == 695 and corrected["behavior"]["volume_unit_status"] == "NOT_PROVEN" and corrected["behavior"]["volume_source_finality"] == "NOT_ATTESTED_BY_PROVIDER")

check("visual_receipt_runtime_source_sha", ui["root_cause"]["receipt_sha256"] == sha256(EVIDENCE / "post_publication_runtime_review_20261010.json"))
check("three_screenshot_hashes", len(ui["screenshots"]) == 3 and all(sha256(EVIDENCE / row["filename"]) == row["sha256"] for row in ui["screenshots"]))
check("frontend_loaded_browser_bundle_unconfirmed", frontend["evidence"]["loaded_browser_bundle_sha256"] == projection["frontend_boundary_review"]["loaded_browser_bundle_sha256"] == "CANNOT_CONFIRM")
check("frontend_historical_synthetic_not_mount_acceptance", frontend["synthetic_helper_render"]["status"] == "PASS" and frontend["focused_regression_tests"]["status"] == "NOT_RUN" and frontend["current_ui_behavior"] == "FAIL")
check("research_safety_receipt_consistency", handoff["research_only_flags"] == corrected["owner_product"]["safety_flags"] == projection["deployed_release"]["safety_flags"] == {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False})

missing_imports: dict[str, set[str]] = defaultdict(set)
local_roots = {"apps", "v4", "infrastructure", "application", "domain", "shared_data", "upstreams"}
for path in app.rglob("*.py"):
    relative = path.relative_to(app)
    package_parts = list(relative.with_suffix("").parts[:-1])
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[:len(package_parts) - node.level + 1]
                modules = [".".join(base + (node.module.split(".") if node.module else []))]
            elif node.module:
                modules = [node.module]
        for module in modules:
            if module.split(".")[0] not in local_roots:
                continue
            target = app.joinpath(*module.split("."))
            if not target.with_suffix(".py").is_file() and not target.is_dir():
                missing_imports[module].add(relative.as_posix())

identity_paths = ["infrastructure/research_lane_source.py", "v4/manager_research/existing_materials.py", "v4/manager_research/workspace_projection.py", "v4/manager_research/workspace.py"]
identity_sources = [{"path": path, "present_in_supplied_package": (app / path).is_file(), "receipt_sha256": counter["candidate_source_sha256"][Path(path).name], "supplied_sha256": sha256(app / path) if (app / path).is_file() else None} for path in identity_paths]
recovery_manifest = ROOT / "recovery_sources/RECOVERY_MANIFEST.json"
recovered_identity_sources = []
if recovery_manifest.is_file():
    recovered = read_json(recovery_manifest)
    for item in identity_sources:
        if item["present_in_supplied_package"]:
            continue
        matches = [row for row in recovered if row["repository_path"].endswith(item["path"]) and row["sha256"] == item["receipt_sha256"]]
        for row in matches:
            data = Path(row["local_path"]).read_bytes()
            valid = hashlib.sha256(data).hexdigest() == item["receipt_sha256"] and hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == row["git_blob_sha"]
            recovered_identity_sources.append({"runtime_path": item["path"], "repository_path": row["repository_path"], "commit": row["commit"], "git_blob_sha": row["git_blob_sha"], "sha256": row["sha256"], "actual_bytes_match_both_hashes": valid})
        check("recovered_identity_exact_bytes:" + item["path"], len(matches) == 1 and recovered_identity_sources[-1]["actual_bytes_match_both_hashes"])
report = (EVIDENCE / "root_cause_report_20261010.md").read_text(encoding="utf-8")
projection_citation = re.search(r"live_ui_api_problem_projection\.json` \(SHA256 `([0-9a-f]+)`", report)
old_projection_sha = projection_citation.group(1) if projection_citation else None
short_hashes = [m.group(1) for m in re.finditer(r"`([0-9a-f]{40,})`", report) if len(m.group(1)) != 64]

result = {
    "status": "PASS_PACKAGE_RECEIPT_CROSSCHECKS" if all(row["pass"] for row in checks) else "FAIL_PACKAGE_RECEIPT_CROSSCHECKS",
    "execution_boundary": "RECEIPT_METADATA_AND_SOURCE_BYTES_ONLY; PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN",
    "checks": checks,
    "source_counts": {"total": len(source["files"]), "by_type": dict(Counter(row["source_type"] for row in source["files"])), "current_fused_app": sum(row["bundle_path"].startswith("code/current_fused_app/") for row in source["files"])},
    "fixed_reference_checks": reference_results,
    "identity_source_presence": identity_sources,
    "recovered_identity_source_checks": recovered_identity_sources,
    "recovery_manifest_sha256_at_audit": sha256(recovery_manifest) if recovery_manifest.is_file() else None,
    "missing_direct_local_imports": {module: sorted(paths) for module, paths in sorted(missing_imports.items())},
    "missing_direct_local_import_count": len(missing_imports),
    "package_limitations": ["No saved 1,970-material plan/raw source_rows array", "No original payload/receipt bytes for the 40 bound artifacts", "No previous global manifest bytes", "No 15,037,791-byte live GET body or digest", "No browser-loaded bundle bytes/digest", "No full runtime dependency tree or original package/build lockfiles"],
    "historical_report_caveats": {"root_cause_report_projection_cited_sha256": old_projection_sha, "packaged_projection_sha256": sha256(EVIDENCE / "live_ui_api_problem_projection.json"), "cited_projection_matches_current_file": old_projection_sha == sha256(EVIDENCE / "live_ui_api_problem_projection.json"), "non_sha256_length_hex_citations": short_hashes, "machine_receipt_first_leaf_receipt_sha256": leaves[0]["receipt_sha256_saved_and_current"]},
    "warnings": ["Receipt agreement does not recompute historical raw owner bytes or reproduce the historical live mismatch.", "Git blob ID equality binds bytes to the supplied reference metadata; this audit did not independently contact GitHub to verify commit reachability.", "The supplied reproduction script records EXPECTED_PLAN_SHA but does not assert it; its archived receipt's actual and expected hashes agree. It was inspected, not executed."],
}
OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": result["status"], "checks": len(checks), "failures": [row["name"] for row in checks if not row["pass"]], "missing_direct_local_import_count": len(missing_imports), "output": str(OUTPUT)}, ensure_ascii=False))
raise SystemExit(0 if all(row["pass"] for row in checks) else 1)
