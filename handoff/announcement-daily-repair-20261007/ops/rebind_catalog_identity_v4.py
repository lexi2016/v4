#!/usr/bin/env python3
"""Prove catalog content equivalence and rebind the frozen v3 product locally.

This script is task-local evidence preparation. It reads the saved candidate,
the owner-created catalog, and the frozen v3 product; it writes only under this
task directory. It does not call a network/API endpoint, import an analysis
product, or modify the active owner state.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = Path("/Users/lexi/Desktop/学习/v4_app")
SAVED_CATALOG_PATH = ROOT / "daily_runs/20261007_20261006/candidate_state/manager/workspace_announcements/20261007/eastmoney_date_catalog/20261006/latest.json"
ACTIVE_CATALOG_PATH = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/workspace_announcements/20261007/eastmoney_date_catalog/20261006/latest.json")
ROOT_API_EVIDENCE_PATH = ROOT / "ROOT_CATALOG_FAILED_IMPORT_READBACK.json"
FAILED_IMPORT_RECEIPT_PATH = ROOT / "daily_runs/20261007_20261006/active_import/import_receipt.json"
V3_PRODUCT_PATH = ROOT / "daily_runs/20261007_20261006/candidate_state_product_v3/manager/workspace_announcements/20261007/eastmoney_date_catalog/20261006/analysis.v1.json"
V3_PRODUCT_RECEIPT_PATH = ROOT / "daily_runs/20261007_20261006/evidence/ANALYSIS_CANDIDATE_PRODUCT_RECEIPT_v3.json"
V3_REVIEW_RECEIPT_PATH = ROOT / "INDEPENDENT_PRODUCT_V3_REVIEW_RECEIPT.json"
OUTPUT_DIR = ROOT / "daily_runs/20261007_20261006/evidence"
OUTPUT_PRODUCT_PATH = OUTPUT_DIR / "analysis_product_20261007_v4.json"
OUTPUT_EQUIVALENCE_PATH = ROOT / "daily_runs/20261007_20261006/active_import/catalog_equivalence_reconciliation_v1.json"
OUTPUT_RECEIPT_PATH = OUTPUT_DIR / "ANALYSIS_CANDIDATE_PRODUCT_RECEIPT_v4.json"

EXPECTED = {
    "target_trade_date": "20261007",
    "publication_date": "2026-10-06",
    "saved_run_id": "028ce0e6bdc448248c21f1da3cf1b2f6",
    "saved_catalog_sha256": "0cc10a09e8a06514a1981d2dad0642ac2e294e67ace71e8843f1afcd0de2df7e",
    "active_run_id": "b640f4477a1c43569f225d139cdf8669",
    "active_catalog_sha256": "b01d28d9c27e511479b7bcdce45c62918895fd6cdaf782631c50eec45361b7a7",
    "v3_product_sha256": "b39925f247affd4bab728457b64e7ac7645c612845d197730d27452b4aca236b",
    "v3_receipt_sha256": "324b9900a73ee762e95f2179e2eac954b6b3b066da60448ff7c6cb1ac9bb2807",
    "source_aggregate_sha256": "b5ea2c12b3c0ad380f308fd7fffc849383bbe9656ea44e0b2f9f8bbcd0f06d49",
    "root_api_evidence_sha256": "ea8b7d298d5fa1d7bed5fba6c6754b0ae6673094660e7f003b5935eea8beaf0e",
    "failed_import_receipt_sha256": "9e14314393045ffabf651b5019ff1a16a8b41d4c8d405909ce7a06a0f27d7610",
    "v3_review_receipt_sha256": "5f85594d35ab43846f5ccce56aa33959b74a364ad0dc792648c1e5a0230f09f0",
}


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                          allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def walk_differences(left: Any, right: Any, path: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if type(left) is not type(right):
        return [{"path": path, "kind": "TYPE", "saved": type(left).__name__,
                 "active": type(right).__name__}]
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else key
            if key not in left:
                out.append({"path": child, "kind": "MISSING_SAVED",
                            "saved": None, "active": right[key]})
            elif key not in right:
                out.append({"path": child, "kind": "MISSING_ACTIVE",
                            "saved": left[key], "active": None})
            else:
                out.extend(walk_differences(left[key], right[key], child))
    elif isinstance(left, list):
        if len(left) != len(right):
            out.append({"path": path, "kind": "LENGTH", "saved": len(left),
                        "active": len(right)})
        for index, (a, b) in enumerate(zip(left, right)):
            out.extend(walk_differences(a, b, f"{path}[{index}]"))
    elif left != right:
        out.append({"path": path, "kind": "VALUE", "saved": left, "active": right})
    return out


def normalized_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(catalog)
    for key in ("generated_at", "run_id", "sha256"):
        value.pop(key, None)
    for page in value.get("page_receipts", []):
        for key in ("run_id", "owner_attempt_path", "owner_receipt_path"):
            page.pop(key, None)
    return value


def require_sha(path: Path, expected: str, label: str) -> None:
    actual = file_sha(path)
    if actual != expected:
        raise ValueError(f"{label}_FILE_SHA_MISMATCH:{actual}")


def counts_for_product(product: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    article_decisions = product["stock_selection"]["article_decisions"]
    article = Counter(row["disposition"] for row in article_decisions)
    sys.path.insert(0, str(ROOT / "candidate"))
    sys.path.insert(1, str(REPO))
    from v4.manager_research.announcement_selection import read_projection
    projection = read_projection(product)
    stocks = {
        "stock_count": projection["stock_count"],
        "selected_stock_count": projection["selected_stock_count"],
        "conditional_watch_count": projection["conditional_watch_count"],
        "not_selected_stock_count": projection["not_selected_stock_count"],
        "not_assessed_stock_count": projection["not_assessed_stock_count"],
    }
    return dict(sorted(article.items())), stocks


def main() -> int:
    for path, sha, label in (
        (ROOT_API_EVIDENCE_PATH, EXPECTED["root_api_evidence_sha256"], "ROOT_API_EVIDENCE"),
        (FAILED_IMPORT_RECEIPT_PATH, EXPECTED["failed_import_receipt_sha256"], "FAILED_IMPORT_RECEIPT"),
        (V3_PRODUCT_RECEIPT_PATH, EXPECTED["v3_receipt_sha256"], "V3_PRODUCT_RECEIPT"),
        (V3_REVIEW_RECEIPT_PATH, EXPECTED["v3_review_receipt_sha256"], "V3_REVIEW_RECEIPT"),
    ):
        require_sha(path, sha, label)
    saved = load(SAVED_CATALOG_PATH)
    active = load(ACTIVE_CATALOG_PATH)
    root_evidence = load(ROOT_API_EVIDENCE_PATH)
    failed = load(FAILED_IMPORT_RECEIPT_PATH)
    v3_receipt = load(V3_PRODUCT_RECEIPT_PATH)
    v3_review = load(V3_REVIEW_RECEIPT_PATH)
    v3 = load(V3_PRODUCT_PATH)

    if (saved.get("run_id") != EXPECTED["saved_run_id"]
            or saved.get("sha256") != EXPECTED["saved_catalog_sha256"]
            or active.get("run_id") != EXPECTED["active_run_id"]
            or active.get("sha256") != EXPECTED["active_catalog_sha256"]):
        raise ValueError("CATALOG_IDENTITY_MISMATCH")
    if file_sha(V3_PRODUCT_PATH) != v3_receipt.get("persisted_product_file_sha256"):
        raise ValueError("V3_PRODUCT_FILE_SHA_MISMATCH")
    if (v3.get("sha256") != EXPECTED["v3_product_sha256"]
            or digest({k: v for k, v in v3.items() if k != "sha256"}) != v3.get("sha256")
            or v3.get("source_manifest", {}).get("catalog_run_id") != EXPECTED["saved_run_id"]
            or v3.get("source_manifest", {}).get("catalog_product_sha256") != EXPECTED["saved_catalog_sha256"]):
        raise ValueError("V3_PRODUCT_SOURCE_BINDING_INVALID")
    if (v3_receipt.get("product_sha256") != v3.get("sha256")
            or v3_review.get("status") != "REVIEWED_PASS"
            or v3_review.get("product_sha256") != v3.get("sha256")
            or v3_review.get("product_receipt_file_sha256") != EXPECTED["v3_receipt_sha256"]):
        raise ValueError("V3_REVIEW_SCOPE_MISMATCH")
    if (failed.get("status") != "IMPORT_INDETERMINATE_NO_RETRY"
            or failed.get("error") != "ValueError:ACTIVE_OWNER_SOURCE_IDENTITY_MISMATCH:run_id"):
        raise ValueError("FAILED_IMPORT_TERMINAL_RECEIPT_MISMATCH")
    api_catalog = root_evidence.get("catalog", {})
    for key, expected in (
        ("status", "COMPLETE"), ("readback_status", "VERIFIED"),
        ("target_trade_date", EXPECTED["target_trade_date"]),
        ("publication_date", EXPECTED["publication_date"]),
        ("manager_consumer_row_count", 580), ("manager_source_identity_count", 584),
        ("manager_source_code_count", 524), ("connect_eligibility_status", "NOT_ASSESSED"),
    ):
        if api_catalog.get(key) != expected:
            raise ValueError(f"ROOT_API_READBACK_IDENTITY_MISMATCH:{key}")
    if (api_catalog.get("run_id") != EXPECTED["active_run_id"]
            or api_catalog.get("product_sha256") != EXPECTED["active_catalog_sha256"]
            or api_catalog.get("manager_source_codes") != active.get("manager_source_codes")
            or api_catalog.get("manager_issuer_count") is not None
            or api_catalog.get("unknown_issuer_count") is not None):
        raise ValueError("ROOT_API_READBACK_SOURCE_IDENTITY_MISMATCH")
    if (active.get("target_trade_date") != EXPECTED["target_trade_date"]
            or active.get("publication_date") != EXPECTED["publication_date"]
            or active.get("status") != "COMPLETE"
            or active.get("connect_eligibility_status") != "NOT_ASSESSED"
            or active.get("manager_issuer_count") is not None
            or active.get("hkex_first_publication_verified") is not False):
        raise ValueError("ACTIVE_CATALOG_SCOPE_OR_SAFETY_MISMATCH")

    differences = walk_differences(saved, active)
    allowed = {"generated_at", "run_id", "sha256"}
    for index in range(30):
        prefix = f"page_receipts[{index}]"
        allowed.update({f"{prefix}.run_id", f"{prefix}.owner_attempt_path",
                        f"{prefix}.owner_receipt_path"})
    if len(differences) != 93 or {row["path"] for row in differences} != allowed:
        raise ValueError("CATALOG_EQUIVALENCE_DIFF_OUTSIDE_RUN_METADATA")
    if digest(normalized_catalog(saved)) != digest(normalized_catalog(active)):
        raise ValueError("CATALOG_NORMALIZED_CONTENT_SHA_MISMATCH")
    if (saved.get("manager_consumer_rows") != active.get("manager_consumer_rows")
            or saved.get("source_rows") != active.get("source_rows")
            or len(saved.get("page_receipts", [])) != 30
            or len(active.get("page_receipts", [])) != 30
            or any(a.get("source_ref") != b.get("source_ref")
                   for a, b in zip(saved["page_receipts"], active["page_receipts"]))):
        raise ValueError("CATALOG_ROW_OR_SOURCE_REF_CONTENT_MISMATCH")
    equivalence = {
        "schema": "v4.manager_research.announcement_catalog_equivalence_reconciliation.v1",
        "status": "PASS_CONTENT_EQUIVALENT_OWNER_RUN_REBIND",
        "scope": "exact date-bound saved-ref owner import; no recapture or content refetch",
        "target_trade_date": EXPECTED["target_trade_date"],
        "publication_date": EXPECTED["publication_date"],
        "source_scope": "EASTMONEY_HK_DATE_CATALOG",
        "saved_catalog": {
            "path": str(SAVED_CATALOG_PATH.relative_to(ROOT)),
            "file_sha256": file_sha(SAVED_CATALOG_PATH),
            "run_id": saved["run_id"], "product_sha256": saved["sha256"],
        },
        "active_owner_catalog": {
            "path": str(ACTIVE_CATALOG_PATH), "file_sha256": file_sha(ACTIVE_CATALOG_PATH),
            "run_id": active["run_id"], "product_sha256": active["sha256"],
            "root_api_readback_artifact": str(ROOT_API_EVIDENCE_PATH.relative_to(ROOT)),
            "root_api_readback_file_sha256": file_sha(ROOT_API_EVIDENCE_PATH),
        },
        "failed_first_import": {
            "path": str(FAILED_IMPORT_RECEIPT_PATH.relative_to(ROOT)),
            "file_sha256": file_sha(FAILED_IMPORT_RECEIPT_PATH),
            "status": failed["status"], "error": failed["error"],
            "preserved": True, "retry_or_rollback_performed": False,
        },
        "invariants": {
            "status": active["status"], "readback_status": api_catalog["readback_status"],
            "manager_articles": active["manager_consumer_row_count"],
            "source_code_associations": active["manager_source_identity_count"],
            "distinct_source_codes": len(active["manager_source_codes"]),
            "manager_issuer_count": None, "issuer_count_status": "CANNOT_CONFIRM",
            "connect_eligibility_status": active["connect_eligibility_status"],
            "hkex_first_publication_verified": active["hkex_first_publication_verified"],
            "captured_pages_including_terminal_empty": active["captured_page_count"],
            "data_pages": active["expected_data_page_count"],
            "rows": active["captured_row_count"],
            "terminal_empty_seen": active["terminal_empty_seen"],
            "all_listing_rows_exact_equal": True,
            "all_source_rows_exact_equal": True,
            "all_30_source_refs_exact_equal": True,
        },
        "comparison": {
            "normalization": "remove only top-level generated_at/run_id/sha256 and each page run_id/owner_attempt_path/owner_receipt_path",
            "saved_normalized_sha256": digest(normalized_catalog(saved)),
            "active_normalized_sha256": digest(normalized_catalog(active)),
            "normalized_sha256_equal": True,
            "changed_path_count": len(differences),
            "changed_paths": differences,
        },
        "active_catalog_sha256_not_equal_saved_catalog_sha256": True,
        "interpretation": "The active catalog is byte-content equivalent at the listing-row, source-row, page-ref, URL, date, and response-hash layers. Its owner run ID, catalog product SHA, generation time, and owner receipt paths are newly generated identity metadata; analysis must bind to the active run/SHA.",
    }
    equivalence_file_sha = write_json(OUTPUT_EQUIVALENCE_PATH, equivalence)

    # Rebuild only the identity-bearing source manifest and selection extension.
    original_extension = v3.get("stock_selection")
    if not isinstance(original_extension, dict):
        raise ValueError("V3_SELECTION_EXTENSION_MISSING")
    old_decisions = copy.deepcopy(original_extension.get("article_decisions"))
    base = copy.deepcopy(v3)
    base.pop("stock_selection", None)
    base["source_manifest"]["catalog_run_id"] = active["run_id"]
    base["source_manifest"]["catalog_product_sha256"] = active["sha256"]
    base["source_manifest_sha256"] = digest(base["source_manifest"])
    base.pop("sha256", None)
    base["sha256"] = digest(base)

    sys.path.insert(0, str(ROOT / "candidate"))
    sys.path.insert(1, str(REPO))
    from v4.manager_research.announcement_analysis import validate_product
    from v4.manager_research.announcement_selection import attach_extension, make_extension, read_projection
    validate_product(base, target_trade_date=EXPECTED["target_trade_date"],
                     publication_date=EXPECTED["publication_date"], catalog=active)
    extension = make_extension(base, old_decisions)
    product = attach_extension(base, extension)
    validate_product(product, target_trade_date=EXPECTED["target_trade_date"],
                     publication_date=EXPECTED["publication_date"], catalog=active)
    if product["records"] != v3["records"]:
        raise ValueError("ARTICLE_FACTS_CHANGED_DURING_REBIND")
    if product["stock_selection"]["article_decisions"] != original_extension["article_decisions"]:
        raise ValueError("ARTICLE_DECISIONS_CHANGED_DURING_REBIND")
    old_projection = read_projection(v3)
    new_projection = read_projection(product)
    if (new_projection["stocks"] != old_projection["stocks"]
            or new_projection["article_decisions"] != old_projection["article_decisions"]
            or any(new_projection[key] != old_projection[key] for key in (
                "stock_count", "article_count", "selected_stock_count",
                "conditional_watch_count", "not_selected_stock_count", "not_assessed_stock_count"))):
        raise ValueError("SELECTION_PROJECTION_CHANGED_DURING_REBIND")
    product_file_sha = write_json(OUTPUT_PRODUCT_PATH, product)
    article_counts, stock_counts = counts_for_product(product)
    receipt = {
        "schema": "v4.manager_research.announcement_daily_analysis_candidate_receipt.v1",
        "status": "LOCAL_CANDIDATE_REBOUND_AND_VALIDATED",
        "target_trade_date": EXPECTED["target_trade_date"],
        "publication_date": EXPECTED["publication_date"],
        "candidate_source_aggregate_sha256": EXPECTED["source_aggregate_sha256"],
        "source_product_receipt": {
            "path": str(V3_PRODUCT_RECEIPT_PATH.relative_to(ROOT)),
            "file_sha256": file_sha(V3_PRODUCT_RECEIPT_PATH),
            "product_sha256": v3["sha256"],
            "review_receipt_path": str(V3_REVIEW_RECEIPT_PATH.relative_to(ROOT)),
            "review_receipt_file_sha256": file_sha(V3_REVIEW_RECEIPT_PATH),
            "review_status": v3_review["status"],
        },
        "catalog_equivalence_reconciliation": {
            "path": str(OUTPUT_EQUIVALENCE_PATH.relative_to(ROOT)),
            "file_sha256": equivalence_file_sha,
            "status": equivalence["status"],
            "active_run_id": active["run_id"],
            "active_catalog_sha256": active["sha256"],
            "normalized_content_sha256": equivalence["comparison"]["active_normalized_sha256"],
        },
        "catalog_run_id": active["run_id"],
        "catalog_sha256": active["sha256"],
        "analysis_product_artifact": str(OUTPUT_PRODUCT_PATH.relative_to(ROOT)),
        "analysis_product_file_sha256": product_file_sha,
        "analysis_product_sha256": product["sha256"],
        "source_manifest_sha256": product["source_manifest_sha256"],
        "source_manifest_rebind_fields_only": ["catalog_run_id", "catalog_product_sha256"],
        "article_records_unchanged": True,
        "article_decisions_unchanged": True,
        "stock_projection_unchanged": True,
        "article_disposition_counts": article_counts,
        "stock_projection_counts": stock_counts,
        "manager_source_identity_associations": 584,
        "distinct_manager_source_codes": 524,
        "manager_issuer_count": None,
        "issuer_count_status": "CANNOT_CONFIRM",
        "connect_eligibility_status": "NOT_ASSESSED",
        "date_pit_boundary": v3_receipt.get("date_pit_boundary"),
        "product_semantic_verdict": "CANDIDATE_AWAITING_INDEPENDENT_PRODUCT_REBIND_REVIEW",
        "analysis_imported": False,
        "isolated_owner_readback": False,
        "api_http_verified": False,
        "ui_verified": False,
        "natural_slot_verified": False,
        "live_state_written": False,
        "trade_or_buy_use": False,
        "orders_sent": False,
    }
    receipt["sha256"] = digest(receipt)
    receipt_file_sha = write_json(OUTPUT_RECEIPT_PATH, receipt)
    print(json.dumps({
        "status": receipt["status"],
        "changed_catalog_path_count": len(differences),
        "normalized_catalog_sha256": equivalence["comparison"]["active_normalized_sha256"],
        "active_run_id": active["run_id"], "active_catalog_sha256": active["sha256"],
        "product_sha256": product["sha256"], "product_file_sha256": product_file_sha,
        "receipt_sha256": receipt_file_sha, "equivalence_file_sha256": equivalence_file_sha,
        "article_counts": article_counts, "stock_counts": stock_counts,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
