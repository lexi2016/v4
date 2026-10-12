from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
from datetime import datetime
from threading import Barrier, Lock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v35_api.manager_research_router import create_manager_research_router
from ops.manager_announcement_body_batch import SharedCaptureGate
from v4.manager_research import announcement_analysis
from v4.manager_research.announcement_processing import (
    _source_publication_time, build_incremental_processing, process_saved_window, read_preopen_window,
    validate_preopen_window,
)
from v4.manager_research.workspace_announcements import _same_calendar_publication_day
from v4.manager_research.workspace_projection import digest


def _ref(url: str, index: str) -> dict:
    return {
        "request": {"source": "HKEX_OFFICIAL", "method": "GET", "url": url},
        "blob_sha256": index * 64,
        "body_sha256": ("a" if index == "1" else "b") * 64,
        "retrieved_at": "2026-10-12T08:00:00+08:00",
    }


def _hkex_variant(status: str, *, with_body: bool = False) -> tuple[dict, dict]:
    url = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/report.xlsx"
    directory_ref = _ref("https://www1.hkexnews.hk/search/titleSearchServlet.do?date=20261012", "1")
    variant = {
        "source_variant_id": "HKEX:12345678", "source": "HKEX_OFFICIAL",
        "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1", "news_id": "12345678",
        "symbol": "HK.02665", "name": "Fixture issuer", "title": "Official filing",
        "publication_date": "20261012", "source_url": url,
        "directory_source_ref": directory_ref, "directory_raw_body_sha256": directory_ref["body_sha256"],
        "body_source_ref": None, "body_status": status, "body_text": None,
        "body_text_sha256": None, "pages": [], "cross_source_link_status": "NOT_ASSESSED",
    }
    record = {
        "source_variant_id": "HKEX:12345678", "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
        "title": "Official filing", "issuer_codes": [{"code": "HK.02665"}],
        "classification": "BUSINESS_EVENT", "factual_summary": "Reviewed source fact",
        "why_useful": "RESEARCH_CONTEXT", "date_semantics": {},
        "evidence": {"exact_excerpt": "Source excerpt"},
    }
    if with_body:
        body_ref = _ref(url, "2")
        body_text = "Captured PDF text"
        text_sha = sha256(body_text.encode()).hexdigest()
        variant.update(body_source_ref=body_ref, body_status="COMPLETE_HKEX_OFFICIAL_PDF_BODY",
            body_text=body_text, body_text_sha256=text_sha,
            pages=[{"page_index": 1, "text": body_text, "text_sha256": text_sha,
                "raw_body_sha256": body_ref["body_sha256"], "source_ref": body_ref}])
        record["evidence"]["reader_fact_record"] = {"body_read_complete": False}
    return record, variant


def test_hkex_saved_unsupported_body_is_unassessed_and_rejects_fabricated_text():
    record, variant = _hkex_variant("BODY_FORMAT_UNSUPPORTED")
    projected = announcement_analysis._analysis_hkex_record(record, variant)
    assert projected["body_status"] == "BODY_FORMAT_UNSUPPORTED"
    assert projected["analysis_kind"] == "TEXT_INSUFFICIENT_UNASSESSED"
    assert projected["selection_status"] == "NOT_ASSESSED"
    assert projected["body_page_citations"] == []
    assert projected["body_text_sha256"] is None

    forged = dict(variant, body_text="fabricated", body_text_sha256="f" * 64)
    with pytest.raises(ValueError, match="UNASSESSED_BODY_HAS_TEXT"):
        announcement_analysis._verify_hkex_variant_body(forged, "2026-10-12")


def test_hkex_reader_declared_gap_downgrades_complete_transport_to_not_assessed():
    record, variant = _hkex_variant("COMPLETE_HKEX_OFFICIAL_PDF_BODY", with_body=True)
    projected = announcement_analysis._analysis_hkex_record(record, variant)
    assert projected["body_status"] == "COMPLETE_HKEX_OFFICIAL_PDF_BODY"
    assert projected["analysis_kind"] == "TEXT_INSUFFICIENT_UNASSESSED"
    assert projected["selection_status"] == "NOT_ASSESSED"
    assert projected["date_semantics"]["content_api_semantic_read_status"] == "INCOMPLETE_SOURCE_GAP"


def test_hkex_variant_and_saved_artifact_bind_on_same_calendar_publication_day():
    # The saved corpus variant and its artifact both retain compact producer dates.
    variant_publication = "20261012"
    saved_artifact_publication = "20261012"
    assert _same_calendar_publication_day(variant_publication, "2026-10-12")
    assert _same_calendar_publication_day(saved_artifact_publication, "2026-10-12")
    assert _same_calendar_publication_day("2026-10-12", "2026-10-12")
    assert not _same_calendar_publication_day("20261013", "2026-10-12")
    assert not _same_calendar_publication_day("2026-13-12", "2026-10-12")
    assert not _same_calendar_publication_day("2026-10-12T00:00:00", "2026-10-12")


def test_hkex_variant_body_accepts_both_same_day_encodings_and_rejects_wrong_day():
    _record, variant = _hkex_variant("BODY_FORMAT_UNSUPPORTED")

    announcement_analysis._verify_hkex_variant_body(variant, "2026-10-12")
    variant["publication_date"] = "2026-10-12"
    announcement_analysis._verify_hkex_variant_body(variant, "2026-10-12")
    variant["publication_date"] = "20261013"
    with pytest.raises(ValueError, match="ANNOUNCEMENT_ANALYSIS_HKEX_VARIANT_IDENTITY_INVALID"):
        announcement_analysis._verify_hkex_variant_body(variant, "2026-10-12")


def test_shared_capture_gate_allows_bounded_overlap_and_counts_physical_bytes():
    gate = SharedCaptureGate(seconds=3, max_requests=2, max_bytes=100, interval=0)
    gate.set_response_limits(per_response=10, total=20)
    barrier = Barrier(2)
    lock = Lock()
    active = 0
    max_active = 0

    def request() -> None:
        nonlocal active, max_active
        gate.before_request()
        try:
            with lock:
                active += 1
                max_active = max(max_active, active)
            barrier.wait(timeout=1)
            gate.record_response_bytes(8)
        finally:
            with lock:
                active -= 1
            gate.end_request()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(request) for _ in range(2)]
        for future in futures:
            future.result(timeout=2)

    snapshot = gate.snapshot()
    assert max_active == 2
    assert snapshot["physical_requests"] == 2
    assert snapshot["physical_response_bytes"] == 16


def test_capture_gate_does_not_count_local_cache_bytes_as_http():
    gate = SharedCaptureGate(seconds=3, max_requests=1, max_bytes=100, interval=0)
    gate.record_cache_hit("material")
    gate.record_response_bytes(30)
    snapshot = gate.snapshot()
    assert snapshot["physical_requests"] == 0
    assert snapshot["physical_response_bytes"] == 0
    assert snapshot["material_cache_hits"] == 1


def test_structured_projection_preserves_records_and_reports_exact_reuse():
    record = {
        "art_code": "AN202610120001", "source": "EASTMONEY_HK",
        "analysis_kind": "COMPLETE_API_BODY", "body_status": "COMPLETE_CONTENT_API_BODY",
        "classification": "BUSINESS_EVENT", "factual_summary": "Verified expansion",
        "why_useful": "RESEARCH_CONTEXT", "issuer_codes": [{"code": "HK.02665"}],
        "semantic_record_sha256": "1" * 64,
        "body_text_sha256": "3" * 64,
        "listing_source": {"publication_date": "2026-10-12", "source_ref": {
            "url": "https://np-anotice-stock.eastmoney.com/notice", "body_sha256": "4" * 64}},
    }
    body_row = {"art_code": record["art_code"], "body_status": record["body_status"],
        "body_text_sha256": record["body_text_sha256"]}
    record["body_record_sha256"] = digest(body_row)
    body = {"rows": [body_row], "source_variants": []}
    decision = {"art_code": record["art_code"], "disposition": "SELECTED_EVENT",
        "selection_basis": "OPERATING_EVENT", "reason": "Reviewed expansion", "risk_notes": []}
    product = {"target_trade_date": "20261012", "publication_date": "2026-10-12", "records": [record]}
    projected = build_incremental_processing(product, body, [decision],
        target_trade_date="20261012", publication_date="2026-10-12",
        semantic_sha256="5" * 64, body_sha256="6" * 64,
        decision_sha256="7" * 64, reviewer_sha256="8" * 64)
    assert projected["reuse"]["semantic_status"] == "REUSED_EXACT_REVIEWED_INPUT"
    assert projected["counts"]["structured_events"] == 1
    assert projected["structured_events"][0]["source_identity"] == {
        "kind": "art_code", "id": "AN202610120001"}
    assert projected["structured_events"][0]["decision"]["disposition"] == "SELECTED_EVENT"
    assert projected["counts"]["pending_analysis_or_disposition"] == 0
    assert projected["projection_network_request_count"] == 0
    assert projected["llm_inference_count"] == 0
    misbound_product = {**product, "records": [{**record, "body_record_sha256": "f" * 64}]}
    misbound = build_incremental_processing(misbound_product, body, [decision],
        target_trade_date="20261012", publication_date="2026-10-12",
        semantic_sha256="5" * 64, body_sha256="6" * 64,
        decision_sha256="7" * 64, reviewer_sha256="8" * 64)
    assert misbound["structured_events"][0]["assessment_status"] == "NOT_ASSESSED"
    assert misbound["pending_queue"][0]["reason_codes"] == [
        "SOURCE_CONTENT_NOT_ASSESSED", "BODY_SOURCE_ROW_BINDING_MISMATCH"]


def test_identical_content_without_shared_event_id_remains_an_unmerged_candidate():
    article_id, hkex_id = "AN202610120001", "HKEX:12345678"
    text_hash = "3" * 64
    article_body = {"art_code": article_id, "body_text_sha256": text_hash}
    hkex_body = {"source_variant_id": hkex_id, "body_text_sha256": text_hash}
    records = [
        {"art_code": article_id, "source": "EASTMONEY_HK", "analysis_kind": "COMPLETE_API_BODY",
         "body_status": "COMPLETE_CONTENT_API_BODY", "issuer_codes": [{"code": "HK.02665"}],
         "body_text_sha256": text_hash, "body_record_sha256": digest(article_body),
         "listing_source": {"publication_date": "2026-10-12"}},
        {"source_variant_id": hkex_id, "source": "HKEX_OFFICIAL", "analysis_kind": "COMPLETE_HKEX_OFFICIAL_PDF_BODY",
         "body_status": "COMPLETE_HKEX_OFFICIAL_PDF_BODY", "issuer_codes": [{"code": "HK.02665"}],
         "body_text_sha256": text_hash, "body_record_sha256": digest(hkex_body),
         "listing_source": {"publication_date": "2026-10-12"}},
    ]
    body = {"rows": [article_body], "source_variants": [hkex_body]}
    product = {"target_trade_date": "20261012", "publication_date": "2026-10-12", "records": records}
    projected = build_incremental_processing(product, body, None,
        target_trade_date="20261012", publication_date="2026-10-12",
        semantic_sha256="5" * 64, body_sha256="6" * 64,
        decision_sha256=None, reviewer_sha256="8" * 64)
    assert projected["source_groups"] == []
    assert len(projected["unmerged_exact_content_candidates"]) == 1
    assert len(projected["unmerged_exact_content_candidates"][0]["members"]) == 2


def _write_json(path, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": sha256(raw).hexdigest()}


def _window_source(tmp_path, publication, *, readiness, notice_date, late_qualification=False):
    suffix = publication.replace("-", "")
    identity = f"AN{suffix}0001"
    body_text_sha = sha256(f"body-{publication}".encode()).hexdigest()
    semantic_record = {"art_code": identity, "title": "Reviewed notice",
        "issuer_codes": [{"code": "HK.02665"}], "factual_summary": "Saved disclosed fact"}
    semantic_path = tmp_path / f"{suffix}-semantic.json"
    semantic_ref = _write_json(semantic_path, {"records": [semantic_record]})
    body_path = tmp_path / f"{suffix}-body.json"
    body_row = {"art_code": identity, "body_text_sha256": body_text_sha}
    body_ref = _write_json(body_path, {"rows": [body_row], "source_variants": []})
    analysis_record = {
        "art_code": identity, "source": "EASTMONEY_HK", "title": "Reviewed notice",
        "issuer_codes": [{"code": "HK.02665"}], "classification": "BUSINESS_EVENT",
        "factual_summary": "Saved disclosed fact", "analysis_kind": "COMPLETE_API_BODY",
        "body_status": "COMPLETE_CONTENT_API_BODY", "body_text_sha256": body_text_sha,
        "body_record_sha256": digest(body_row),
        "semantic_record_sha256": digest(semantic_record),
        "listing_source": {"notice_date": notice_date, "publication_date": publication,
            "source_ref": {"url": "https://np-anotice-stock.eastmoney.com/notice",
                "body_sha256": "a" * 64}},
    }
    target = "20261012"
    product_manifest = {"semantic_catalog_sha256": semantic_ref["sha256"],
        "verified_inputs": [
            {"name": "semantic_catalog", "sha256": semantic_ref["sha256"]},
            {"name": "body_corpus", "sha256": body_ref["sha256"]},
        ]}
    product = {"schema_version": "v4.manager_research.eastmoney_hk_announcement_analysis.v2",
        "status": "VERIFIED", "target_trade_date": target,
        "publication_date": publication, "source_manifest": product_manifest,
        "source_manifest_sha256": digest(product_manifest), "records": [analysis_record]}
    product["sha256"] = digest(product)
    product_path = tmp_path / f"{suffix}-product.json"
    product_ref = _write_json(product_path, product)
    review_record = {"art_code": identity, "source_record_sha256": digest(semantic_record),
        "body_text_sha256": body_text_sha, "disposition": "SELECTED_EVENT",
        "selection_basis": "OPERATING_EVENT", "direction": "POSITIVE",
        "evidence_sufficiency": "VERIFIED_EXISTING_FACTS",
        "reason": "Exact saved source fact supports the reviewed event.", "risk_notes": []}
    review = {"schema_version": "v4.manager_research.announcement_rule_review.v1",
        "rule_version": "POSITIVE_OPERATING_RESEARCH_V1", "status": "DRAFT_UNREVIEWED",
        "target_trade_date": target, "publication_date": publication,
        "semantic_catalog_sha256": semantic_ref["sha256"],
        "reader_identity": "reader", "records": [review_record]}
    review_path = tmp_path / f"{suffix}-rule.json"
    review_ref = _write_json(review_path, review)
    receipt = {"schema_version": "v4.manager_research.announcement_rule_review_receipt.v1",
        "review_conclusion": "PASS", "target_trade_date": target,
        "publication_date": publication, "rule_version": "POSITIVE_OPERATING_RESEARCH_V1",
        "semantic_catalog_sha256": semantic_ref["sha256"],
        "records_sha256": digest(review["records"]), "reader_identity": "reader",
        "reviewer_identity": "reviewer", "reviewed_at": "2026-10-12T12:00:00+08:00"}
    receipt_path = tmp_path / f"{suffix}-receipt.json"
    receipt_ref = _write_json(receipt_path, receipt)
    return {
        "publication_date": publication, "source_family": "EASTMONEY_HK",
        "product_readiness": readiness, "analysis_product": product_ref,
        "semantic_catalog": semantic_ref, "body_corpus": body_ref,
        "rule_review": review_ref, "rule_review_receipt": receipt_ref,
        "availability": {
            "source_available_at": "2026-10-09T08:00:00+08:00" if publication.endswith("09") else None,
            "qualification_available_at": "2026-10-12T19:58:00+08:00" if late_qualification else None,
            "owner_available_at": None,
        },
        "decision": {"art_code": identity, "disposition": "SELECTED_EVENT",
            "selection_basis": "OPERATING_EVENT",
            "reason": review_record["reason"], "risk_notes": []},
    }


def test_saved_window_keeps_retrospective_research_and_preopen_eligibility_separate(tmp_path):
    day9 = _window_source(tmp_path, "2026-10-09", readiness="REGISTERED_OWNER_PRODUCT",
        notice_date="2026-10-09", late_qualification=True)
    day12 = _window_source(tmp_path, "2026-10-12", readiness="DERIVED_DRAFT_UNREGISTERED",
        notice_date="2026-10-12")
    inputs = {"schema_version": "v4.manager_research.announcement_preopen_window_inputs.v1",
        "target_trade_date": "20261012", "window_start": "2026-10-09T00:00+08:00",
        "as_of": "2026-10-12T09:20+08:00", "missing_dates": ["20261010", "20261011"],
        "sources": [day9, day12]}

    result = process_saved_window(inputs, base_dir=tmp_path)

    assert result["coverage"]["status"] == "PARTIAL"
    assert result["coverage"]["covered_dates"] == ["20261009", "20261012"]
    assert result["coverage"]["missing_dates"] == ["20261010", "20261011"]
    assert result["retrospective_research"]["candidate_count"] == 1
    assert result["retrospective_research"]["candidates"][0]["publication_time_basis"] == "DATE_ONLY_PRIOR_DAY"
    assert result["retrospective_research"]["pending_count"] == 1
    assert result["retrospective_research"]["pending_queue"][0]["reason_codes"] == [
        "SAME_DAY_PUBLICATION_TIME_UNVERIFIED"]
    assert result["actual_preopen"]["status"] == "CANNOT_CONFIRM"
    assert result["actual_preopen"]["positive_candidate_count"] is None
    assert result["processing"]["physical_http_request_count"] == 0
    assert result["processing"]["llm_inference_count"] == 0

    checked = validate_preopen_window(result, base_dir=tmp_path,
        target_trade_date="20261012", semantic_sha256=day12["semantic_catalog"]["sha256"],
        body_sha256=day12["body_corpus"]["sha256"], decisions=[day12["decision"]])
    assert checked["registered_binding"]["semantic_catalog_sha256"] == day12["semantic_catalog"]["sha256"]


def test_same_day_eastmoney_notice_date_does_not_establish_preopen_time(tmp_path):
    day12 = _window_source(tmp_path, "2026-10-12", readiness="DERIVED_DRAFT_UNREGISTERED",
        notice_date="2026-10-12 00:00:00")
    inputs = {"schema_version": "v4.manager_research.announcement_preopen_window_inputs.v1",
        "target_trade_date": "20261012", "window_start": "2026-10-12T00:00:00+08:00",
        "as_of": "2026-10-12T09:20:00+08:00", "sources": [day12]}

    result = process_saved_window(inputs, base_dir=tmp_path)

    assert result["retrospective_research"]["candidate_count"] == 0
    assert result["retrospective_research"]["pending_queue"][0]["reason_codes"] == [
        "SAME_DAY_PUBLICATION_TIME_UNVERIFIED"]
    assert result["actual_preopen"]["status"] == "CANNOT_CONFIRM"


def test_official_eastmoney_time_must_match_publication_calendar_day():
    record = {"listing_source": {
        "official_publication_time": "2026-10-09T08:00:00+08:00",
        "official_publication_source_ref": {"url": "https://example.test/notice",
            "body_sha256": "a" * 64}}}
    as_of = datetime.fromisoformat("2026-10-12T09:20:00+08:00")

    rejected, rejected_basis = _source_publication_time(
        record, "EASTMONEY_HK", "2026-10-12", as_of)
    record["listing_source"]["official_publication_time"] = "2026-10-12T08:00:00+08:00"
    accepted, accepted_basis = _source_publication_time(
        record, "EASTMONEY_HK", "2026-10-12", as_of)

    assert rejected is None
    assert rejected_basis == "OFFICIAL_PUBLICATION_TIME_DATE_MISMATCH"
    assert accepted is not None and accepted.isoformat() == "2026-10-12T08:00:00+08:00"
    assert accepted_basis == "EXACT_OFFICIAL_PUBLICATION_TIME"


def test_saved_window_rejects_partial_rule_review_even_with_pass_receipt(tmp_path):
    day = _window_source(tmp_path, "2026-10-09", readiness="REGISTERED_OWNER_PRODUCT",
        notice_date="2026-10-09")
    semantic_path = Path(day["semantic_catalog"]["path"])
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    second_semantic = {"art_code": "AN202610090002", "title": "Second notice",
        "issuer_codes": [{"code": "HK.02665"}], "factual_summary": "Second saved fact"}
    semantic["records"].append(second_semantic)
    semantic_ref = _write_json(semantic_path, semantic)
    day["semantic_catalog"] = semantic_ref

    body_path = Path(day["body_corpus"]["path"])
    body = json.loads(body_path.read_text(encoding="utf-8"))
    second_body = {"art_code": "AN202610090002",
        "body_text_sha256": sha256(b"second-body").hexdigest()}
    body["rows"].append(second_body)
    body_ref = _write_json(body_path, body)
    day["body_corpus"] = body_ref

    product_path = Path(day["analysis_product"]["path"])
    product = json.loads(product_path.read_text(encoding="utf-8"))
    manifest = product["source_manifest"]
    manifest["semantic_catalog_sha256"] = semantic_ref["sha256"]
    for verified in manifest["verified_inputs"]:
        if verified["name"] == "semantic_catalog":
            verified["sha256"] = semantic_ref["sha256"]
        elif verified["name"] == "body_corpus":
            verified["sha256"] = body_ref["sha256"]
    second_analysis = dict(product["records"][0])
    second_analysis.update(art_code="AN202610090002", title="Second notice",
        factual_summary="Second saved fact", body_text_sha256=second_body["body_text_sha256"],
        body_record_sha256=digest(second_body), semantic_record_sha256=digest(second_semantic))
    product["records"].append(second_analysis)
    product["source_manifest_sha256"] = digest(manifest)
    product.pop("sha256")
    product["sha256"] = digest(product)
    day["analysis_product"] = _write_json(product_path, product)

    review_path = Path(day["rule_review"]["path"])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["semantic_catalog_sha256"] = semantic_ref["sha256"]
    day["rule_review"] = _write_json(review_path, review)
    receipt_path = Path(day["rule_review_receipt"]["path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["semantic_catalog_sha256"] = semantic_ref["sha256"]
    receipt["records_sha256"] = digest(review["records"])
    day["rule_review_receipt"] = _write_json(receipt_path, receipt)
    inputs = {"schema_version": "v4.manager_research.announcement_preopen_window_inputs.v1",
        "target_trade_date": "20261012", "window_start": "2026-10-09T00:00+08:00",
        "as_of": "2026-10-12T09:20+08:00", "sources": [day]}

    with pytest.raises(ValueError, match="ANNOUNCEMENT_WINDOW_RULE_REVIEW_IDENTITY_MISMATCH"):
        process_saved_window(inputs, base_dir=tmp_path)


def test_cutoff_timestamps_without_bound_native_receipts_stay_unconfirmed(tmp_path):
    day = _window_source(tmp_path, "2026-10-09", readiness="REGISTERED_OWNER_PRODUCT",
        notice_date="2026-10-09")
    day["availability"] = {"source_available_at": "2026-10-09T08:00:00+08:00",
        "qualification_available_at": "2026-10-09T08:01:00+08:00",
        "owner_available_at": "2026-10-09T08:02:00+08:00"}
    receipt_path = Path(day["rule_review_receipt"]["path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["reviewed_at"] = "2026-10-09T08:03:00+08:00"
    day["rule_review_receipt"] = _write_json(receipt_path, receipt)
    inputs = {"schema_version": "v4.manager_research.announcement_preopen_window_inputs.v1",
        "target_trade_date": "20261012", "window_start": "2026-10-09T00:00+08:00",
        "as_of": "2026-10-12T09:20+08:00", "sources": [day]}

    result = process_saved_window(inputs, base_dir=tmp_path)

    assert result["actual_preopen"]["status"] == "CANNOT_CONFIRM"
    assert result["actual_preopen"]["positive_candidate_count"] is None
    evaluation = result["actual_preopen"]["candidate_evaluations"][0]
    assert evaluation["status"] == "CANNOT_CONFIRM"
    assert "AVAILABILITY_EVIDENCE_FILES_INCOMPLETE" in evaluation["reason_codes"]


def test_cutoff_availability_requires_matching_native_receipts(tmp_path):
    day = _window_source(tmp_path, "2026-10-09", readiness="REGISTERED_OWNER_PRODUCT",
        notice_date="2026-10-09")
    product = json.loads(Path(day["analysis_product"]["path"]).read_text(encoding="utf-8"))
    monthly_root = {
        "schema_version": "v4.manager_research.hk_connect_monthly_eligibility.v1",
        "status": "VERIFIED", "policy": "CALENDAR_MONTH_LATEST_VERIFIED_V2",
        "month": "202610", "target_trade_date": "20261009", "source_date": "20261009",
        "capture_cutoff_at": "2026-10-09T08:01:00+08:00",
        "source": {"market": "HK_CONNECT", "role": "HK_CONNECT_FULL_MARKET_AUTHORITY",
            "source_date": "20261009", "available_at": "2026-10-09T07:00:00+08:00",
            "artifact_ref": "artifact.json", "manifest_ref": "manifest.json",
            "receipt_ref": "receipt.json", "current_ref": "current.json",
            "capture_ref": "capture.json", "publication_ref": "publication.json",
            "sha256": "1" * 64, "capture_sha256": "2" * 64, "source_sha256": "3" * 64},
        "authority_file_sha256s": {key: chr(ord("a") + index) * 64 for index, key in enumerate(
            ("artifact_ref", "manifest_ref", "receipt_ref", "current_ref", "capture_ref", "publication_ref"))},
        "codes": ["HK.02665"], "code_count": 1,
        "codes_sha256": digest(["HK.02665"]), "invalid_newer_candidates": [],
        "RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False}
    monthly = {**monthly_root, "identity_sha256": digest(monthly_root)}
    monthly_ref = _write_json(tmp_path / "monthly.json", monthly)
    body_sha = day["body_corpus"]["sha256"]
    batch = {"schema": "v4.manager_research.announcement_body_batch_receipt.v1",
        "status": "PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS", "target_trade_date": "20261009",
        "publication_date": "2026-10-09", "body_corpus_sha256": body_sha,
        "catalog_run_id": "c" * 32, "catalog_sha256": "e" * 64,
        "started_at": "2026-10-09T08:00:00+08:00", "terminal_at": "2026-10-09T08:02:00+08:00"}
    batch_ref = _write_json(tmp_path / "body_batch_receipt.json", batch)
    capture = {"schema_version": "v4.manager_research.announcement_daily_capture.v1",
        "status": batch["status"], "evidence_run_id": "d" * 32,
        "target_trade_date": "20261009", "publication_date": "2026-10-09",
        "catalog_run_id": batch["catalog_run_id"], "catalog_product_sha256": batch["catalog_sha256"],
        "monthly_connect_eligibility_identity_sha256": monthly["identity_sha256"],
        "monthly_connect_eligibility_file_sha256": monthly_ref["sha256"],
        "body_corpus_file_sha256": body_sha,
        "body_batch_receipt_sha256": batch_ref["sha256"]}
    capture_ref = _write_json(tmp_path / "capture.json", capture)
    owner_unsigned = {"schema_version": "v4.manager_research.announcement_analysis_owner_import.v1",
        "status": "VERIFIED", "target_trade_date": "20261012", "publication_date": "2026-10-09",
        "product_sha256": product["sha256"],
        "source_manifest_sha256": product["source_manifest_sha256"],
        "parent_task_id": "task", "parent_run_id": "run",
        "owner": "ManagerResearchJobService.import_announcement_analysis",
        "available_at": "2026-10-09T08:04:00+08:00",
        "RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False}
    owner_receipt = {**owner_unsigned, "sha256": digest(owner_unsigned)}
    owner_ref = _write_json(tmp_path / "owner_import_receipt.json", owner_receipt)
    day["availability"] = {"source_available_at": batch["terminal_at"],
        "qualification_available_at": monthly["capture_cutoff_at"],
        "owner_available_at": owner_receipt["available_at"],
        "files": {"monthly_eligibility": monthly_ref, "capture_receipt": capture_ref,
            "owner_import_receipt": owner_ref}}
    rule_receipt_path = Path(day["rule_review_receipt"]["path"])
    rule_receipt = json.loads(rule_receipt_path.read_text(encoding="utf-8"))
    rule_receipt["reviewed_at"] = "2026-10-09T08:03:00+08:00"
    day["rule_review_receipt"] = _write_json(rule_receipt_path, rule_receipt)
    inputs = {"schema_version": "v4.manager_research.announcement_preopen_window_inputs.v1",
        "target_trade_date": "20261012", "window_start": "2026-10-09T00:00+08:00",
        "as_of": "2026-10-12T09:20+08:00", "sources": [day]}

    result = process_saved_window(inputs, base_dir=tmp_path)

    assert result["actual_preopen"]["status"] == "VERIFIED", result["actual_preopen"]["candidate_evaluations"][0]["reason_codes"]
    assert result["actual_preopen"]["positive_candidate_count"] == 1
    assert result["actual_preopen"]["candidate_evaluations"][0]["status"] == "AVAILABLE_AT_AS_OF"


def test_saved_window_rejects_analysis_facts_not_bound_to_semantic_record(tmp_path):
    day12 = _window_source(tmp_path, "2026-10-12", readiness="DERIVED_DRAFT_UNREGISTERED",
        notice_date="2026-10-12")
    product_path = Path(day12["analysis_product"]["path"])
    product = json.loads(product_path.read_text(encoding="utf-8"))
    product["records"][0]["semantic_record_sha256"] = "f" * 64
    product.pop("sha256")
    product["sha256"] = digest(product)
    product_ref = _write_json(product_path, product)
    day12["analysis_product"] = product_ref
    inputs = {"schema_version": "v4.manager_research.announcement_preopen_window_inputs.v1",
        "target_trade_date": "20261012", "window_start": "2026-10-12T00:00+08:00",
        "as_of": "2026-10-12T09:20+08:00", "sources": [day12]}

    result = process_saved_window(inputs, base_dir=tmp_path)

    assert result["retrospective_research"]["candidate_count"] == 0
    assert result["retrospective_research"]["pending_queue"][0]["reason_codes"] == [
        "SAME_DAY_PUBLICATION_TIME_UNVERIFIED", "SOURCE_PRODUCT_SEMANTIC_SHA_MISMATCH"]
    assert result["actual_preopen"]["status"] == "CANNOT_CONFIRM"


def test_hkex_preopen_timestamp_requires_exact_official_directory_binding():
    record = {"source_variant_id": "HKEX:12345678", "listing_source": {
        "source": "HKEX_OFFICIAL", "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
        "source_variant_id": "HKEX:12345678", "publication_date": "20261012",
        "published_at": "2026-10-12T08:50:00+08:00",
        "directory_source_ref": {"url": "https://www1.hkexnews.hk/search/titlesearch",
            "body_sha256": "a" * 64}}}
    as_of = datetime.fromisoformat("2026-10-12T09:20:00+08:00")

    exact, basis = _source_publication_time(record, "HKEX_OFFICIAL", "2026-10-12", as_of)
    unbound, unbound_basis = _source_publication_time(
        {"source_variant_id": "HKEX:12345678", "listing_source": {
            **record["listing_source"], "directory_source_ref": None}},
        "HKEX_OFFICIAL", "2026-10-12", as_of)
    date_only, date_basis = _source_publication_time(
        {"source_variant_id": "HKEX:12345678", "listing_source": {
            **record["listing_source"], "published_at": "2026-10-12"}},
        "HKEX_OFFICIAL", "2026-10-12", as_of)

    assert exact == as_of.replace(hour=8, minute=50)
    assert basis == "EXACT_HKEX_PUBLISHED_AT"
    assert unbound is None and unbound_basis == "HKEX_PUBLICATION_SOURCE_REF_UNVERIFIED"
    assert date_only is None and date_basis == "HKEX_PUBLICATION_TIME_NOT_EXACT"


def test_registered_window_read_requires_exact_bounds_and_verified_handoff(tmp_path):
    day12 = _window_source(tmp_path, "2026-10-12", readiness="DERIVED_DRAFT_UNREGISTERED",
        notice_date="2026-10-12")
    inputs = {"schema_version": "v4.manager_research.announcement_preopen_window_inputs.v1",
        "target_trade_date": "20261012", "window_start": "2026-10-12T00:00:00+08:00",
        "as_of": "2026-10-12T09:20:00+08:00", "sources": [day12]}
    artifact = process_saved_window(inputs, base_dir=tmp_path)
    binding = {"target_trade_date": "20261012",
        "source_semantic_catalog_sha256": day12["semantic_catalog"]["sha256"],
        "source_body_corpus_file_sha256": day12["body_corpus"]["sha256"],
        "draft_analysis_product_sha256": artifact["source_days"][0]["analysis_product_sha256"],
        "draft_source_manifest_sha256": json.loads(
            Path(day12["analysis_product"]["path"]).read_text())["source_manifest_sha256"]}
    artifact["registered_binding"] = binding
    artifact["registered_fingerprint_sha256"] = digest({
        "input_fingerprint_sha256": artifact["input_fingerprint_sha256"],
        "registered_binding": binding})
    product = {"target_trade_date": "20261012", "source_manifest": {"preopen_window": artifact}}

    exact = read_preopen_window(product, window_start="2026-10-12T00:00+08:00",
        as_of="2026-10-12T09:20+08:00", handoff_verified=True)
    mismatch = read_preopen_window(product, window_start="2026-10-11T00:00+08:00",
        as_of="2026-10-12T09:20+08:00", handoff_verified=True)
    unverified = read_preopen_window(product, window_start="2026-10-12T00:00+08:00",
        as_of="2026-10-12T09:20+08:00", handoff_verified=False)
    tampered_artifact = {**artifact, "registered_fingerprint_sha256": "0" * 64}
    tampered = read_preopen_window(
        {"target_trade_date": "20261012", "source_manifest": {"preopen_window": tampered_artifact}},
        window_start="2026-10-12T00:00+08:00", as_of="2026-10-12T09:20+08:00",
        handoff_verified=True)

    assert exact["status"] == "VERIFIED"
    assert exact["actual_preopen"]["status"] == "CANNOT_CONFIRM"
    assert mismatch["status"] == "CANNOT_CONFIRM"
    assert unverified["status"] == "CANNOT_CONFIRM"
    assert tampered["status"] == "CANNOT_CONFIRM"


def test_window_get_requires_both_exact_bounds_and_aware_timestamps():
    app = FastAPI()
    app.include_router(create_manager_research_router(object()))
    with TestClient(app) as client:
        missing_bound = client.get(
            "/api/v4/manager/research/announcements/analysis",
            params={"date": "20261012", "window_start": "2026-10-09T00:00+08:00"})
        invalid_timestamp = client.get(
            "/api/v4/manager/research/announcements/analysis",
            params={"date": "20261012", "window_start": "2026-10-09T00:00",
                "as_of": "2026-10-12T09:20+08:00"})

    assert missing_bound.status_code == 422
    assert invalid_timestamp.status_code == 422
