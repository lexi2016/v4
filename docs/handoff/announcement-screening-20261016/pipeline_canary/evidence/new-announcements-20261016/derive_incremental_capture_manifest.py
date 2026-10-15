"""Offline manifest and unseen input derivation from the captured 10/15 product."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent
SOURCE_EVIDENCE = Path("/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/pipeline_canary/evidence/recent-day-20261014")
STATE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench_capture")
LEASE_FILE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench_source_leases/leases/EASTMONEY_HK.json")
PRODUCT_SHA = "0f473ec38e13744895973cdb04530f159420e0fc651056f24f803c33c11ce4ae"
PRODUCT_PATH = STATE_ROOT / "products" / f"{PRODUCT_SHA}.json"
OWNER = "v4.manager_workbench.capture_announcements"
SOURCE = "EASTMONEY_HK"
LEFT = datetime.fromisoformat("2026-10-14T21:43:25+08:00")
RIGHT = datetime.fromisoformat("2026-10-16T00:14:26+08:00")
KNOWN_DATES = ("20261014", "20261015", "20261016")
QUEUE_STATES = (
    SOURCE_EVIDENCE / "candidate-172/ready-v2/queue-state/recent-day-20261014-172-fbfa1f6bd4e1e1e58947/queue-state.json",
    SOURCE_EVIDENCE / "candidate-172/recovery-balanced-v1/queue-state/recent-day-20261014-172-recovery-ba29d61e4f608ab73b35/queue-state.json",
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("EVIDENCE_MODULE_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def actual_prior_model_ids() -> tuple[set[str], list[dict]]:
    seen: set[str] = set()
    queues = []
    for state_path in QUEUE_STATES:
        state = read_json(state_path)
        report = {"state_path": str(state_path), "state_sha256": file_sha(state_path), "job_count": len(state.get("jobs", {})), "attempt_count": 0, "attempted_article_ids": 0}
        queue_seen = set()
        for key, job in state.get("jobs", {}).items():
            count = int(job.get("attempt_count", 0))
            report["attempt_count"] += count
            if count < 1:
                continue
            request_path = state_path.parent / "jobs" / key / "input.json"
            request = read_json(request_path)
            article_id = request.get("article_id")
            if not isinstance(article_id, str) or not article_id.startswith("EASTMONEY:"):
                raise RuntimeError("PRIOR_MODEL_REQUEST_ID_INVALID")
            code = article_id.split(":", 1)[1]
            queue_seen.add(code)
            seen.add(code)
            raw_body = request.get("article_body")
            if not isinstance(raw_body, str) or sha(raw_body.encode("utf-8")) != request.get("body_sha256"):
                raise RuntimeError("PRIOR_MODEL_REQUEST_BODY_HASH_MISMATCH")
            raw_paths = list((request_path.parent).glob("attempt-*.raw"))
            if len(raw_paths) < count:
                raise RuntimeError("PRIOR_MODEL_RAW_RESPONSE_MISSING")
        report["attempted_article_ids"] = len(queue_seen)
        queues.append(report)
    return seen, queues


def main() -> int:
    product_raw = PRODUCT_PATH.read_bytes()
    if sha(product_raw) != PRODUCT_SHA:
        raise RuntimeError("CAPTURE_PRODUCT_SHA_MISMATCH")
    product = json.loads(product_raw)
    if product.get("owner") != OWNER or product.get("source") != SOURCE or product.get("run_id") != "5b8d2d3b77e3454c87a7306ec6f4c55d":
        raise RuntimeError("CAPTURE_PRODUCT_IDENTITY_MISMATCH")

    runner = load_module("capture_runner", OUT / "execute_incremental_capture.py")
    sys.path.insert(0, "/Users/lexi/Desktop/学习/v4_app")
    from v4.manager_workbench.inputs.capture_store import CaptureStore
    store = CaptureStore(STATE_ROOT, source=SOURCE, lease_root=LEASE_FILE.parent.parent)
    runtime_product = {**product, "saved_ref": {"artifact_ref": f"products/{PRODUCT_SHA}.json", "sha256": PRODUCT_SHA}}
    verified = runner.readback_product(store, runtime_product)
    records_path = SOURCE_EVIDENCE / "source-window-records.jsonl"
    records_sha = file_sha(records_path)
    previous_rows = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    previous_codes = {str(row["art_code"]) for row in previous_rows}
    if len(previous_codes) != len(previous_rows):
        raise RuntimeError("PRIOR_ARTICLE_ID_DUPLICATE")
    seen_model_codes, queue_reports = actual_prior_model_ids()

    router = load_module("frozen_announcement_triage", SOURCE_EVIDENCE / "recent_day_freeze.py")
    retained = []
    route_counts = Counter()
    dedup_prior_count = 0
    outside_count = 0
    for row in verified.get("rows", []):
        display = datetime.fromisoformat(row["display_time"])
        if not LEFT <= display <= RIGHT:
            outside_count += 1
            continue
        code = row["art_code"]
        if code in previous_codes:
            dedup_prior_count += 1
            continue
        body_status, computed_body_sha = router._body_status(row)
        route, _reason_unused, route_bucket = router._triage(row, body_status)
        route_counts[route_bucket or route] += 1
        retained.append({
            "article_id": f"EASTMONEY:{code}",
            "art_code": code,
            "title": row.get("title"),
            "publication_date": row.get("publication_date"),
            "display_time": row.get("display_time"),
            "source_issuer_codes": row.get("source_issuer_codes", []),
            "body_status": body_status,
            "body_complete": row.get("body_complete") is True and body_status == "COMPLETE_HASH_VERIFIED",
            "body_text_sha256": row.get("body_text_sha256"),
            "computed_body_text_sha256": computed_body_sha,
            "source_sha256": row.get("source_sha256"),
            "body_artifact_ref": row.get("body_artifact_ref"),
            "listing_source_ref": row.get("listing_source_ref"),
            "available_at": row.get("available_at"),
            "first_hkex_publication_time": row.get("first_hkex_publication_time", "CANNOT_CONFIRM"),
            "original_point_in_time_availability": row.get("original_point_in_time_availability", "CANNOT_CONFIRM"),
            "gaps": row.get("gaps", []),
            "coarse_route": route,
            "route_bucket": route_bucket,
            "model_seen_in_prior_actual_request_queues": code in seen_model_codes,
        })
    retained.sort(key=lambda row: (datetime.fromisoformat(row["display_time"]), row["art_code"]))
    if len({row["article_id"] for row in retained}) != len(retained):
        raise RuntimeError("INCREMENTAL_ARTICLE_ID_DUPLICATE")

    eligible = [row for row in retained if row["body_complete"] and row["route_bucket"] in {"operating_review", "risk_review", "corporate_action_review"} and not row["model_seen_in_prior_actual_request_queues"]]
    if not eligible:
        raise RuntimeError("UNSEEN_COMPLETE_NONROUTINE_SAMPLE_NOT_FOUND")
    candidate = next((row for row in eligible if row["route_bucket"] == "operating_review"), eligible[0])
    source_row = next(row for row in verified["rows"] if row["art_code"] == candidate["art_code"])
    page_refs = [page.get("source_ref", {}) for page in source_row.get("pages", []) if isinstance(page, dict)]
    availability = [ref.get("available_at") for ref in page_refs if ref.get("available_at")]
    input_row = {
        "article_id": candidate["article_id"],
        "market": "HK",
        "target_date": "20261016",
        "source": SOURCE,
        "publication_date": candidate["publication_date"],
        "source_display_time": candidate["display_time"],
        "title": candidate["title"],
        "article_body": source_row["body_text"],
        "issuer_codes": [
            {"code": item.get("code"), "name": item.get("name"), "source_stock_code": item.get("source_stock_code")}
            for item in source_row.get("source_issuer_codes", [])
        ],
        "source_evidence": {
            "owner": OWNER,
            "source_sha256": candidate["source_sha256"],
            "body_sha256": candidate["body_text_sha256"],
            "body_artifact_ref": candidate["body_artifact_ref"],
            "listing_source_ref": candidate["listing_source_ref"],
            "body_page_evidence": [
                {key: ref.get(key) for key in ("evidence_id", "role", "sha256", "available_at", "source_url", "artifact_ref", "verification")}
                for ref in page_refs
            ],
            "available_at": max(availability) if availability else None,
            "first_hkex_publication_time": "CANNOT_CONFIRM",
            "original_point_in_time_availability": "CANNOT_CONFIRM",
        },
    }
    input_raw = (json.dumps(input_row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    input_path = OUT / "nonroutine-unseen-sample-input.jsonl"
    input_path.write_bytes(input_raw)
    forbidden = {"route", "route_bucket", "classification", "answer", "summary", "judgment", "previous_model_evidence", "model_seen_in_prior_actual_request_queues"}
    if forbidden & set(input_row):
        raise RuntimeError("UNSEEN_INPUT_HAS_LABEL_OR_ANSWER")

    lease_raw = LEASE_FILE.read_bytes()
    lease = json.loads(lease_raw)
    if lease.get("enabled") is not False or lease.get("owner") != OWNER or lease.get("source") != SOURCE:
        raise RuntimeError("FINAL_LEASE_STATE_NOT_REVOKED")

    manifest = {
        "schema_version": "v4.announcement.incremental_capture_manifest.v1",
        "status": "PARTIAL_STOP_AFTER_20261015_CANARY",
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "source": SOURCE,
        "owner": OWNER,
        "source_product": {"path": str(PRODUCT_PATH), "artifact_ref": f"products/{PRODUCT_SHA}.json", "sha256": PRODUCT_SHA, "run_id": verified["run_id"], "rows": len(verified.get("rows", [])), "coverage_status": verified.get("coverage_status")},
        "requested_publication_dates": list(KNOWN_DATES),
        "executed_publication_dates": ["20261015"],
        "not_attempted_after_canary_stop": ["20261014", "20261016"],
        "incremental_display_window": {"left_inclusive": LEFT.isoformat(), "right_inclusive": RIGHT.isoformat(), "field": "display_time", "deduplicate_by": "EASTMONEY:{art_code}"},
        "previous_frozen_window": {"path": str(records_path), "sha256": records_sha, "article_count": len(previous_codes)},
        "actual_prior_model_request_inventory": {"union_article_count": len(seen_model_codes), "queues": queue_reports},
        "coverage": {
            "20261014": {"status": "NOT_CAPTURED_CANARY_STOP", "scope_count": None, "observed_count": None, "body_complete_count": None, "body_gap_count": None},
            "20261015": {"status": "CATALOGUE_COMPLETE_BODY_PARTIAL", "scope_count": verified.get("scope_count"), "observed_count": len(verified.get("rows", [])), "catalogue": verified.get("catalogues", [None])[0], "body_complete_count": sum(row.get("body_complete") is True for row in verified.get("rows", [])), "body_gap_count": sum(row.get("body_complete") is not True for row in verified.get("rows", [])), "body_gap_codes": dict(Counter(g for row in verified.get("rows", []) for g in row.get("gaps", []))), "http_status_code": "CANNOT_CONFIRM", "post_cutoff_availability": "CANNOT_CONFIRM for original PIT; captured availability is retained"},
            "20261016": {"status": "NOT_CAPTURED_CANARY_STOP", "scope_count": None, "observed_count": None, "body_complete_count": None, "body_gap_count": None},
        },
        "incremental_unique_row_count": len(retained),
        "prior_duplicate_rows_removed": dedup_prior_count,
        "outside_inclusive_window_rows_excluded": outside_count,
        "coarse_route_counts": dict(route_counts),
        "rows": retained,
        "unseen_nonroutine_sample": {"article_id": candidate["article_id"], "title": candidate["title"], "route_bucket": candidate["route_bucket"], "body_status": candidate["body_status"], "body_sha256": candidate["body_text_sha256"], "source_sha256": candidate["source_sha256"], "body_artifact_ref": candidate["body_artifact_ref"], "model_seen_in_prior_actual_request_queues": False, "sample_input_path": str(input_path), "sample_input_sha256": sha(input_raw), "model_inference_performed": False},
        "semantic_assessment": "NOT_RUN",
        "hkex_first_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM",
        "capture_quality_stop_reason": "199 of 392 rows lacked complete body; 198 CAPTURE_HTTP_STATUS_NOT_200 and one BODY_PAGE_TOTAL_INVALID; remaining publication dates and retries stopped.",
    }
    manifest_path = OUT / "incremental-capture-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    coverage_path = OUT / "incremental-capture-coverage.json"
    coverage = {
        "schema_version": "v4.announcement.incremental_coverage.v1",
        "status": manifest["status"],
        "manifest_path": str(manifest_path),
        "manifest_sha256": file_sha(manifest_path),
        "requested_publication_dates": list(KNOWN_DATES),
        "captured_dates": ["20261015"],
        "not_attempted_after_canary_stop": ["20261014", "20261016"],
        "total_catalogue_rows": len(verified.get("rows", [])),
        "incremental_rows_after_window_and_prior_id_dedup": len(retained),
        "prior_duplicate_rows_removed": dedup_prior_count,
        "body_complete_rows": sum(row.get("body_complete") is True for row in verified.get("rows", [])),
        "body_incomplete_rows": sum(row.get("body_complete") is not True for row in verified.get("rows", [])),
        "body_gap_codes": dict(Counter(g for row in verified.get("rows", []) for g in row.get("gaps", []))),
        "http_status_code": "CANNOT_CONFIRM",
        "unseen_nonroutine_sample": manifest["unseen_nonroutine_sample"],
        "lease_enabled": lease.get("enabled"),
        "lease_file_sha256": sha(lease_raw),
        "model_inference_performed": False,
    }
    coverage_path.write_text(json.dumps(coverage, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": file_sha(manifest_path), "coverage": str(coverage_path), "coverage_sha256": file_sha(coverage_path), "sample_input": str(input_path), "sample_input_sha256": sha(input_raw), "incremental_rows": len(retained), "prior_dedup_removed": dedup_prior_count, "body_complete_rows": sum(row.get("body_complete") is True for row in verified.get("rows", [])), "body_incomplete_rows": sum(row.get("body_complete") is not True for row in verified.get("rows", [])), "route_counts": dict(route_counts), "unseen_candidate_id": candidate["article_id"], "candidate_route": candidate["route_bucket"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
