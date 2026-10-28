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
from ops import manager_announcement_body_batch as body_batch
from ops import run_manager_daily_announcement as daily_runner
from v4.manager_research import announcement_analysis
from v4.manager_research import announcement_selection
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.announcement_processing import (
    _source_publication_time, build_incremental_processing, process_saved_window, read_preopen_window,
    validate_preopen_window,
)
from v4.manager_research.workspace_announcements import (
    _analysis_time_refs, _same_calendar_publication_day,
)
from v4.manager_research.workspace_projection import FLAGS, digest


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


def test_hkex_directory_retrieval_counts_as_source_time_without_using_publication_time():
    product = {"records": [{
        "analysis_kind": "COMPLETE_HKEX_OFFICIAL_PDF_BODY",
        "body_status": "COMPLETE_HKEX_OFFICIAL_PDF_BODY",
        "listing_source": {
            "published_at": "2026-10-12T06:05+08:00",
            "directory_source_ref": {
                "retrieved_at": "2026-10-12T13:21:32+00:00",
            },
        },
        "body_page_citations": [{
            "source_ref": {"retrieved_at": "2026-10-12T09:59:23+00:00"},
        }],
    }]}

    times, sources_complete = _analysis_time_refs(product)

    assert sources_complete is True
    assert {time.isoformat() for time in times} == {
        "2026-10-12T21:21:32+08:00",
        "2026-10-12T17:59:23+08:00",
    }

    no_acquisition_ref = {"records": [{
        "analysis_kind": "TEXT_INSUFFICIENT_UNASSESSED",
        "body_status": "TEXT_INSUFFICIENT_UNASSESSED",
        "listing_source": {"published_at": "2026-10-12T06:05+08:00"},
        "body_page_citations": [],
    }]}
    times, sources_complete = _analysis_time_refs(no_acquisition_ref)
    assert sources_complete is False
    assert times == []
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


def test_catalog_source_identity_preserves_documented_eastmoney_applicant_key():
    identity = {"code": "H2762", "source_stock_code": "H2762", "market_code": "116",
        "ann_type": "H", "name": "北京九章云极科技"}

    assert announcement_analysis._valid_eastmoney_hk_source_identity(identity)
    assert identity["code"] == "H2762"
    assert not announcement_analysis._valid_eastmoney_hk_source_identity(
        {**identity, "source_stock_code": "02762"})
    assert not announcement_analysis._valid_eastmoney_hk_source_identity(
        {**identity, "market_code": "999"})
    assert not announcement_analysis._valid_eastmoney_hk_source_identity(
        {**identity, "code": "H27625"})


def test_multi_source_product_validator_accepts_exact_eastmoney_h2762_source_key():
    # Reuse the existing source-bound builder fixture without changing its
    # owning test module. H2762 remains an Eastmoney source identifier, not a
    # canonical HK ticker or Stock Connect code.
    from test_manager_announcement_analysis import _multi_source_fixture

    _product, catalog_read, semantic, body, terminal, descriptors = _multi_source_fixture()
    catalog = catalog_read["catalog"]
    identity = {"code": "H2762", "source_stock_code": "H2762", "market_code": "116",
        "ann_type": "H", "name": "北京九章云极科技"}
    excluded_listing = dict(catalog["manager_consumer_rows"][0])
    excluded_listing.update(art_code="AN2026101200000002", title="Unqualified applicant row",
        item_index=2, source_issuer_codes=[identity])
    catalog["manager_consumer_rows"].append(excluded_listing)
    catalog["manager_consumer_row_count"] = 2
    catalog["manager_source_identity_count"] = 2
    catalog["manager_source_codes"] = ["H2762", "HK.02665"]

    product = announcement_analysis.build_product(semantic, body, catalog_read,
        semantic_sha256=descriptors[0]["sha256"], body_sha256=descriptors[1]["sha256"],
        verified_inputs=descriptors, target_trade_date="20261012",
        publication_date="2026-10-12", terminal_body_capture=terminal)
    validated = announcement_analysis.validate_product(product, target_trade_date="20261012",
        publication_date="2026-10-12", catalog=catalog)

    eastmoney_row = next(row for row in validated["records"] if row.get("art_code") == "AN2026101200000001")
    assert eastmoney_row["issuer_codes"][0]["code"] == "HK.02665"
    assert "AN2026101200000002" not in {row.get("art_code") for row in validated["records"]}
    assert "H2762" in catalog["manager_source_codes"]
    assert validated["source_manifest"]["manager_source_identity_association_count"] == 2
    assert validated["source_manifest"]["distinct_manager_source_code_count"] == 2
    assert "H2762" not in body["monthly_connect_eligibility"]["codes"]


def test_selection_projection_preserves_exact_code_source_name_aliases_with_provenance():
    manifest = {
        "target_trade_date": "20261012", "publication_date": "2026-10-12",
        "source_scope": "EASTMONEY_HK_DATE_CATALOG", "catalog_run_id": "a" * 32,
        "catalog_product_sha256": "b" * 64, "semantic_catalog_sha256": "c" * 64,
        "body_corpus_sha256": "d" * 64,
    }
    records = [
        {"art_code": "AN202610120001", "title": "Eastmoney row",
            "issuer_codes": [{"code": "HK.02665", "name": "图达通"}],
            "listing_source": {"source_ref": _ref("https://example.test/em", "1")},
            "security_scope": "ISSUER_EQUITY", "semantic_record_sha256": "1" * 64,
            "body_record_sha256": "2" * 64},
        {"source_variant_id": "HKEX:12345678", "title": "HKEX row",
            "issuer_codes": [{"code": "HK.02665", "name": "圖達通"}],
            "listing_source": {"source": "HKEX_OFFICIAL",
                "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
                "directory_source_ref": _ref("https://www1.hkexnews.hk/directory", "2")},
            "security_scope": "ISSUER_EQUITY", "semantic_record_sha256": "3" * 64,
            "body_record_sha256": "4" * 64},
        {"source_variant_id": "HKEX:12345679", "title": "HKEX row without issuer name",
            "issuer_codes": [{"code": "HK.02665", "name": None}],
            "listing_source": {"source": "HKEX_OFFICIAL",
                "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
                "directory_source_ref": _ref("https://www1.hkexnews.hk/directory/2", "3")},
            "security_scope": "ISSUER_EQUITY", "semantic_record_sha256": "5" * 64,
            "body_record_sha256": "6" * 64},
        {"art_code": "AN202610120002", "title": "Different security",
            "issuer_codes": [{"code": "HK.09999", "name": "图达通"}],
            "listing_source": {"source_ref": _ref("https://example.test/em/2", "4")},
            "security_scope": "ISSUER_EQUITY", "semantic_record_sha256": "7" * 64,
            "body_record_sha256": "8" * 64},
    ]
    product = {"schema_version": "test.analysis.v1", "status": "VERIFIED",
        "target_trade_date": "20261012", "publication_date": "2026-10-12",
        "source_manifest": manifest, "source_manifest_sha256": digest(manifest),
        "records": records}
    product["sha256"] = digest(product)
    decisions = []
    for record in records:
        identity = {key: record[key] for key in ("art_code", "source_variant_id") if key in record}
        decisions.append({**identity,
            "issuer_codes": [issuer["code"] for issuer in record["issuer_codes"]],
            "security_scope": record["security_scope"],
            "semantic_record_sha256": record["semantic_record_sha256"],
            "body_record_sha256": record["body_record_sha256"],
            "disposition": "SELECTED_EVENT", "selection_basis": "OPERATING_EVENT",
            "reason": "Exact source-bound fixture decision.", "risk_notes": []})

    extension = announcement_selection.make_extension(product, decisions)
    projection = announcement_selection.read_projection(
        announcement_selection.attach_extension(product, extension))

    same_code = next(row for row in projection["stocks"] if row["stock_code"] == "HK.02665")
    assert same_code["stock_name"] == "图达通"
    assert same_code["stock_name_status"] == "SOURCE_NAME_ALIASES_PRESENT"
    assert {row["name"] for row in same_code["source_name_aliases"]} == {"图达通", "圖達通"}
    assert same_code["stock_name_source"]["source_identity"] == {"art_code": "AN202610120001"}
    assert len(same_code["source_name_gaps"]) == 1
    assert same_code["source_name_gaps"][0]["source_identity"] == {
        "source_variant_id": "HKEX:12345679"}
    different_code = next(row for row in projection["stocks"] if row["stock_code"] == "HK.09999")
    assert different_code["source_name_aliases"][0]["name"] == "图达通"
    assert different_code["stock_name_source"]["source_identity"] == {"art_code": "AN202610120002"}


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
    directory_ref = {"url": "https://www1.hkexnews.hk/search/titleSearchServlet.do?date=20261012",
        "blob_sha256": "b" * 64, "body_sha256": "a" * 64,
        "retrieved_at": "2026-10-12T13:21:32+00:00"}
    record = {"source": "HKEX_OFFICIAL", "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
        "source_variant_id": "HKEX:12345678", "news_id": "12345678", "listing_source": {
        "source": "HKEX_OFFICIAL", "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
        "source_variant_id": "HKEX:12345678", "news_id": "12345678",
        "publication_date": "20261012", "published_at": "2026-10-12T08:50:00+08:00",
        "directory_raw_body_sha256": "a" * 64, "directory_source_ref": directory_ref}}
    as_of = datetime.fromisoformat("2026-10-12T09:20:00+08:00")

    exact, basis = _source_publication_time(record, "HKEX_OFFICIAL", "2026-10-12", as_of)
    unbound, unbound_basis = _source_publication_time({**record,
        "listing_source": {**record["listing_source"], "directory_source_ref": None}},
        "HKEX_OFFICIAL", "2026-10-12", as_of)
    date_only, date_basis = _source_publication_time({**record,
        "listing_source": {**record["listing_source"], "published_at": "2026-10-12"}},
        "HKEX_OFFICIAL", "2026-10-12", as_of)
    naive, naive_basis = _source_publication_time({**record,
        "listing_source": {**record["listing_source"], "published_at": "2026-10-12T08:50:00"}},
        "HKEX_OFFICIAL", "2026-10-12", as_of)
    cross_day, cross_day_basis = _source_publication_time({**record,
        "listing_source": {**record["listing_source"], "published_at": "2026-10-12T16:05:00Z"}},
        "HKEX_OFFICIAL", "2026-10-12", as_of)
    misbound, misbound_basis = _source_publication_time({**record,
        "source_scope": "OTHER_SCOPE"}, "HKEX_OFFICIAL", "2026-10-12", as_of)
    after_cutoff, after_cutoff_basis = _source_publication_time({**record,
        "listing_source": {**record["listing_source"], "published_at": "2026-10-12T09:21:00+08:00"}},
        "HKEX_OFFICIAL", "2026-10-12", as_of)

    assert exact == as_of.replace(hour=8, minute=50)
    assert basis == "EXACT_HKEX_PUBLISHED_AT"
    assert unbound is None and unbound_basis == "HKEX_PUBLICATION_SOURCE_REF_UNVERIFIED"
    assert date_only is None and date_basis == "HKEX_PUBLICATION_TIME_NOT_EXACT"
    assert naive is None and naive_basis == "HKEX_PUBLICATION_TIME_NOT_AWARE"
    assert cross_day is None and cross_day_basis == "HKEX_PUBLISHED_AT_DATE_MISMATCH"
    assert misbound is None and misbound_basis == "HKEX_PUBLICATION_SOURCE_REF_UNVERIFIED"
    assert after_cutoff is not None and after_cutoff > as_of
    assert after_cutoff_basis == "EXACT_HKEX_PUBLISHED_AT"


def test_native_hkex_directory_publication_time_is_retrospective_not_cutoff_availability(tmp_path):
    publication = "2026-10-12"
    source_id = "HKEX:12369250"
    source_sha = "a" * 64
    text_sha = sha256(b"Captured official filing text").hexdigest()
    semantic_record = {"source_variant_id": source_id, "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
        "title": "Official filing", "classification": "BUSINESS_EVENT",
        "factual_summary": "Saved official business fact", "why_useful": "RESEARCH_CONTEXT",
        "issuer_codes": [{"code": "HK.02665"}], "date_semantics": {
            "first_hkex_publication_time": "CANNOT_CONFIRM",
            "original_point_in_time_availability": "CANNOT_CONFIRM"},
        "evidence": {"exact_excerpt": "Exact saved excerpt"}}
    semantic_path = tmp_path / "native-hkex-semantic.json"
    semantic_ref = _write_json(semantic_path, {"records": [semantic_record]})
    body_row = {"source_variant_id": source_id, "body_text_sha256": text_sha}
    body_path = tmp_path / "native-hkex-body.json"
    body_ref = _write_json(body_path, {"rows": [], "source_variants": [body_row]})
    directory_ref = {"url": "https://www1.hkexnews.hk/search/titleSearchServlet.do?date=20261012",
        "blob_sha256": "b" * 64, "body_sha256": "c" * 64,
        "retrieved_at": "2026-10-12T13:21:32+00:00"}
    analysis_record = {"source_variant_id": source_id, "source": "HKEX_OFFICIAL",
        "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1", "news_id": "12369250",
        "title": "Official filing", "issuer_codes": [{"code": "HK.02665"}],
        "classification": "BUSINESS_EVENT", "factual_summary": "Saved official business fact",
        "why_useful": "RESEARCH_CONTEXT", "analysis_kind": "COMPLETE_HKEX_OFFICIAL_PDF_BODY",
        "body_status": "COMPLETE_HKEX_OFFICIAL_PDF_BODY", "body_text_sha256": text_sha,
        "body_record_sha256": digest(body_row), "semantic_record_sha256": digest(semantic_record),
        "first_hkex_publication_time": "CANNOT_CONFIRM", "date_semantics": {
            "first_hkex_publication_time": "CANNOT_CONFIRM",
            "original_point_in_time_availability": "CANNOT_CONFIRM"},
        "listing_source": {"source": "HKEX_OFFICIAL", "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
            "source_variant_id": source_id, "news_id": "12369250", "publication_date": publication,
            "published_at": "2026-10-12T06:05+08:00", "directory_raw_body_sha256": "c" * 64,
            "directory_source_ref": directory_ref}}
    product_manifest = {"semantic_catalog_sha256": semantic_ref["sha256"], "verified_inputs": [
        {"name": "semantic_catalog", "sha256": semantic_ref["sha256"]},
        {"name": "body_corpus", "sha256": body_ref["sha256"]}]}
    product = {"schema_version": "v4.manager_research.eastmoney_hk_announcement_analysis.v2",
        "status": "VERIFIED", "target_trade_date": "20261012", "publication_date": publication,
        "source_manifest": product_manifest, "source_manifest_sha256": digest(product_manifest),
        "records": [analysis_record]}
    product["sha256"] = digest(product)
    product_ref = _write_json(tmp_path / "native-hkex-product.json", product)
    review_record = {"source_variant_id": source_id, "source_record_sha256": digest(semantic_record),
        "body_text_sha256": text_sha, "disposition": "SELECTED_EVENT", "selection_basis": "OPERATING_EVENT",
        "direction": "POSITIVE", "evidence_sufficiency": "VERIFIED_EXISTING_FACTS",
        "reason": "Reviewed source fact.", "risk_notes": []}
    review = {"schema_version": "v4.manager_research.announcement_rule_review.v1",
        "rule_version": "POSITIVE_OPERATING_RESEARCH_V1", "status": "PASS", "target_trade_date": "20261012",
        "publication_date": publication, "semantic_catalog_sha256": semantic_ref["sha256"],
        "reader_identity": "reader", "records": [review_record]}
    review_ref = _write_json(tmp_path / "native-hkex-review.json", review)
    receipt = {"schema_version": "v4.manager_research.announcement_rule_review_receipt.v1",
        "review_conclusion": "PASS", "target_trade_date": "20261012", "publication_date": publication,
        "rule_version": "POSITIVE_OPERATING_RESEARCH_V1", "semantic_catalog_sha256": semantic_ref["sha256"],
        "records_sha256": digest(review["records"]), "reader_identity": "reader", "reviewer_identity": "reviewer",
        "reviewed_at": "2026-10-12T08:00:00+08:00"}
    receipt_ref = _write_json(tmp_path / "native-hkex-receipt.json", receipt)
    inputs = {"schema_version": "v4.manager_research.announcement_preopen_window_inputs.v1",
        "target_trade_date": "20261012", "window_start": "2026-10-09T00:00:00+08:00",
        "as_of": "2026-10-12T09:20:00+08:00", "missing_dates": ["20261010", "20261011"],
        "sources": [{"publication_date": "20261012", "source_family": "HKEX_OFFICIAL",
            "product_readiness": "DERIVED_DRAFT_UNREGISTERED", "analysis_product": product_ref,
            "semantic_catalog": semantic_ref, "body_corpus": body_ref,
            "rule_review": review_ref, "rule_review_receipt": receipt_ref,
            "availability": {"source_available_at": "2026-10-12T13:21:32+00:00",
                "qualification_available_at": None, "owner_available_at": None}}]}

    result = process_saved_window(inputs, base_dir=tmp_path)

    assert result["retrospective_research"]["candidate_count"] == 1
    candidate = result["retrospective_research"]["candidates"][0]
    assert candidate["source_identity"] == {"kind": "source_variant_id", "id": source_id}
    assert candidate["publication_time"] == "2026-10-12T06:05:00+08:00"
    assert candidate["publication_time_basis"] == "EXACT_HKEX_PUBLISHED_AT"
    assert result["actual_preopen"]["status"] == "CANNOT_CONFIRM"
    assert result["actual_preopen"]["positive_candidates"] == []
    assert product["records"][0]["first_hkex_publication_time"] == "CANNOT_CONFIRM"


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


def test_unimported_preopen_window_read_returns_cannot_confirm(tmp_path):
    service = ManagerResearchJobService(ManagerResearchStore(tmp_path), None, None)
    app = FastAPI()
    app.include_router(create_manager_research_router(service))
    with TestClient(app) as client:
        response = client.get(
            "/api/v4/manager/research/announcements/analysis",
            params={"date": "20261012", "publication_date": "20261012",
                "window_start": "2026-10-09T00:00:00+08:00",
                "as_of": "2026-10-12T09:20:00+08:00"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis"]["status"] == "NOT_IMPORTED"
    assert payload["consumption_validation"]["validation_status"] == "NOT_IMPORTED"
    assert payload["preopen_window_readback"] == {
        "status": "CANNOT_CONFIRM", "reason": "REGISTERED_WINDOW_NOT_VERIFIED",
        "window_start": "2026-10-09T00:00:00+08:00",
        "as_of": "2026-10-12T09:20:00+08:00"}


def test_terminal_capture_failure_keeps_bound_optional_page_counts():
    code = "AN202610091830265966"
    receipt_sha = "f" * 64
    failure = {"art_code": code, "error_code": "BODY_CAPTURE_FAILED:ValueError",
        "receipt_sha256": receipt_sha, "content_api_page_total": 15,
        "content_api_pages_captured": 8}
    terminal = {"schema_version": "v4.manager_research.announcement_terminal_body_capture.v1",
        "status": "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS", "article_count": 1,
        "body_status_counts": {"BODY_CAPTURE_FAILED": 1}, "input_identity_sha256": "a" * 64,
        "body_corpus_sha256": "b" * 64, "body_corpus_manifest_sha256": "c" * 64,
        "body_batch_receipt_sha256": "d" * 64, "capture_receipt_sha256": "e" * 64,
        "failed_articles": [failure]}
    body_rows = {code: {"body_status": "BODY_CAPTURE_FAILED", "pages": [],
        "content_page_count": None, "body_text": None, "body_text_sha256": None,
        "pdf_sha256": None, "capture_receipt_sha256": receipt_sha}}

    _checked, bindings = announcement_analysis._validated_terminal_body_capture(
        terminal, body_rows, {code})
    expected_failure = {"status": "BODY_CAPTURE_FAILED",
        "error_code": "BODY_CAPTURE_FAILED:ValueError", "receipt_sha256": receipt_sha,
        "content_api_page_total": 15, "content_api_pages_captured": 8}
    assert bindings[code] == {key: expected_failure[key]
        for key in ("error_code", "receipt_sha256", "content_api_page_total", "content_api_pages_captured")}
    assert announcement_analysis._body_capture_failure_projection_matches(
        expected_failure, expected_failure)
    assert announcement_analysis._body_capture_failure_projection_matches(
        {key: value for key, value in expected_failure.items()
            if key not in {"content_api_page_total", "content_api_pages_captured"}},
        expected_failure)
    assert not announcement_analysis._body_capture_failure_projection_matches(
        {**expected_failure, "content_api_pages_captured": 7}, expected_failure)
    assert not announcement_analysis._body_capture_failure_projection_matches(
        {**expected_failure, "content_api_pages_captured": True}, expected_failure)
    assert not announcement_analysis._body_capture_failure_projection_matches(
        {**expected_failure, "unbound_field": "ignored"}, expected_failure)

    malformed = {**terminal, "failed_articles": [{**failure, "content_api_pages_captured": -1}]}
    with pytest.raises(ValueError, match="ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_TERMINAL_INVALID"):
        announcement_analysis._validated_terminal_body_capture(malformed, body_rows, {code})
    unknown = {**terminal, "failed_articles": [{**failure, "unbound_field": "ignored"}]}
    with pytest.raises(ValueError, match="ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_TERMINAL_INVALID"):
        announcement_analysis._validated_terminal_body_capture(unknown, body_rows, {code})


def test_register_handoff_cli_loads_body_for_full_incremental_projection(tmp_path, monkeypatch, capsys):
    target = "20261012"
    publication = "2026-10-12"
    run_id = "d" * 32
    art_code = "AN202610120001"
    title = "Fixture notice"
    issuer = {"code": "HK.02665", "name": "Fixture issuer",
        "source_stock_code": "02665", "market_code": "116", "ann_type": "H"}
    source_ref = {"request": {"source": "EASTMONEY_HK", "method": "GET",
            "url": f"https://np-anotice-stock.eastmoney.com/notice?art_code={art_code}"},
        "blob_sha256": "a" * 64, "body_sha256": "b" * 64,
        "retrieved_at": "2026-10-12T08:00:00+08:00"}

    state_root = tmp_path / "research-state"
    evidence = state_root / "announcement_agent_runs" / run_id / "evidence"
    evidence.mkdir(parents=True)
    catalog = {"target_trade_date": target, "publication_date": publication,
        "source_scope": "EASTMONEY_HK_DATE_CATALOG", "status": "COMPLETE",
        "run_id": "c" * 32, "captured_row_count": 1, "captured_page_count": 1,
        "manager_consumer_row_count": 1, "manager_source_identity_count": 1,
        "connect_eligibility_status": "NOT_ASSESSED", "hkex_first_publication_verified": False,
        "manager_source_codes": ["HK.02665"],
        "manager_consumer_rows": [{"art_code": art_code, "title": title,
            "notice_date": publication + " 08:00:00", "page_index": 1, "item_index": 1,
            "raw_body_sha256": source_ref["body_sha256"], "source_ref": source_ref,
            "source_issuer_codes": [issuer]}]}
    catalog["sha256"] = digest(catalog)
    catalog_read = {"schema_version": "v4.manager_research.eastmoney_hk_date_catalog_read.v1",
        "target_trade_date": target, "publication_date": publication,
        "source_scope": "EASTMONEY_HK_DATE_CATALOG", "status": "COMPLETE",
        "readback_status": "VERIFIED", "catalog": catalog}
    catalog_ref = _write_json(evidence / "catalog_read.json", catalog_read)

    semantic_record = {"art_code": art_code, "title": title,
        "issuer_codes": [{"code": "HK.02665"}], "factual_summary": "Saved fixture fact",
        "classification": "BUSINESS_EVENT", "evidence": {"exact_excerpt": "Fixture excerpt"}}
    semantic = {"schema": "v4.announcement-semantic-catalog.v2",
        "status": "PASS_FIXTURE_READER_FACTS", "target_research_date": target,
        "target_notice_date": publication, "row_count": 1, "records": [semantic_record]}
    semantic_input = tmp_path / "semantic-input.json"
    semantic_ref = _write_json(semantic_input, semantic)

    input_identity_material = {"target_trade_date": target, "publication_date": publication,
        "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
        "article_ids": [art_code], "listing_body_sha256s": [source_ref["body_sha256"]]}
    input_identity_sha = sha256(body_batch.json_bytes(input_identity_material)).hexdigest()
    body_file = {"schema": "v4.manager_research.source_bound_announcement_body.v1",
        "art_code": art_code, "title": title, "target_trade_date": target,
        "publication_date": publication, "listing_source_ref": source_ref,
        "listing_raw_body_sha256": source_ref["body_sha256"], "source_issuer_codes": [issuer],
        "content_api_pages": [], "body_status": "BODY_CAPTURE_FAILED", "body_text": None,
        "body_text_sha256": None, "pdf": None, "semantic_status": "NOT_REVIEWED",
        "first_hkex_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM"}
    artifact_path = evidence / "body_batch" / "bodies" / f"{art_code}.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_ref = _write_json(artifact_path, body_file)
    body_row = {"art_code": art_code, "title": title,
        "source_issuer_codes": [issuer], "listing_source_ref": source_ref,
        "listing_raw_body_sha256": source_ref["body_sha256"], "attachment_url": None,
        "body_status": "BODY_CAPTURE_FAILED", "transport_body_status": "BODY_CAPTURE_FAILED",
        "transport_first_hkex_publication_time": "CANNOT_CONFIRM",
        "transport_pit_status": "CANNOT_CONFIRM", "transport_semantic_status": "NOT_REVIEWED",
        "body_text": None, "body_text_sha256": None, "content_page_count": None,
        "pages": [], "pdf_sha256": None, "capture_receipt_sha256": artifact_ref["sha256"]}
    article_receipt = {"art_code": art_code, "title": title, "target_trade_date": target,
        "publication_date": publication, "source_issuer_codes": [issuer],
        "listing_source_ref": source_ref, "listing_raw_body_sha256": source_ref["body_sha256"],
        "status": "BODY_CAPTURE_FAILED", "body_status": "BODY_CAPTURE_FAILED",
        "semantic_status": "NOT_REVIEWED", "body_path": f"bodies/{art_code}.json",
        "body_file_sha256": artifact_ref["sha256"], "content_api_pages_captured": 0,
        "error_code": "FIXTURE_CAPTURE_FAILURE", "first_hkex_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM"}
    body_status_counts = {"BODY_CAPTURE_FAILED": 1}
    body_manifest = {"schema": "v4.manager_research.source_bound_announcement_body_corpus.v1",
        "target_trade_date": target, "publication_date": publication,
        "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
        "input_identity_sha256": input_identity_sha, "body_status_counts": body_status_counts,
        "semantic_status": "NOT_REVIEWED", "article_receipts": [article_receipt],
        "article_index_shard_count": 1}
    body_manifest_ref = _write_json(evidence / "body_corpus_manifest.json", body_manifest)
    body_corpus = {"schema": "v4.manager_research.eastmoney_hk_announcement_body_corpus.v3",
        "target_notice_date": publication, "article_count": 1,
        "transport_complete_body_count": 0, "rows": [body_row],
        "source_manifest_artifact": "body_corpus_manifest.json",
        "source_manifest_sha256": body_manifest_ref["sha256"],
        "semantic_status": "NOT_REVIEWED", "input_identity_sha256": input_identity_sha}
    body_ref = _write_json(evidence / "body_corpus.json", body_corpus)
    batch = {"schema": "v4.manager_research.announcement_body_batch_receipt.v1",
        "status": "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS",
        "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
        "target_trade_date": target, "publication_date": publication,
        "input_identity_sha256": input_identity_sha, "article_rows": 1,
        "terminal_article_receipts": 1, "body_status_counts": body_status_counts,
        "body_corpus": "body_corpus.json", "body_corpus_sha256": body_ref["sha256"],
        "body_corpus_manifest": "body_corpus_manifest.json",
        "body_corpus_manifest_sha256": body_manifest_ref["sha256"]}
    batch_ref = _write_json(evidence / "body_batch_receipt.json", batch)
    capture = {"schema_version": "v4.manager_research.announcement_daily_capture.v1",
        "status": batch["status"], "evidence_run_id": run_id,
        "target_trade_date": target, "publication_date": publication,
        "catalog_run_id": catalog["run_id"], "catalog_product_sha256": catalog["sha256"],
        "catalog_read_file_sha256": catalog_ref["sha256"],
        "body_corpus_file_sha256": body_ref["sha256"],
        "body_corpus_manifest_file_sha256": body_manifest_ref["sha256"],
        "body_batch_receipt_sha256": batch_ref["sha256"], **FLAGS}
    _write_json(evidence / "capture_receipt.json", capture)

    decision = {"art_code": art_code, "issuer_codes": ["HK.02665"],
        "security_scope": None, "semantic_record_sha256": digest(semantic_record),
        "body_record_sha256": digest(body_row), "disposition": "NOT_ASSESSED",
        "selection_basis": "NOT_ASSESSED", "reason": "Fixture body capture is unavailable.",
        "risk_notes": []}
    decisions_input = tmp_path / "decisions-input.json"
    _write_json(decisions_input, {"article_decisions": [decision]})
    reviewer = {"schema_version": "v4.manager_research.announcement_agent_review.v1",
        "review_conclusion": "PASS", "target_trade_date": target,
        "publication_date": publication, "evidence_run_id": run_id,
        "decision_status": "EXPLICIT_DISPOSITIONS",
        "decision_payload_sha256": digest([decision]), "reader_identity": "fixture_reader",
        "reviewer_identity": "fixture_reviewer", "reviewed_at": "2026-10-12T08:05:00+08:00",
        "catalog_product_sha256": catalog["sha256"],
        "semantic_catalog_sha256": semantic_ref["sha256"], "body_corpus_sha256": body_ref["sha256"]}
    reviewer_input = tmp_path / "reviewer-input.json"
    _write_json(reviewer_input, reviewer)

    monkeypatch.setattr(daily_runner.sys, "argv", ["run_manager_daily_announcement.py",
        "register-handoff", "--evidence-run-id", run_id,
        "--research-state-root", str(state_root), "--target-date", target,
        "--publication-date", publication, "--semantic-catalog", str(semantic_input),
        "--reviewer-output", str(reviewer_input), "--decisions", str(decisions_input),
        "--parent-task-id", "incremental-register-regression",
        "--reader-identity", "fixture_reader", "--reviewer-identity", "fixture_reviewer"])

    assert daily_runner.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "OUTPUT_BOUND_HANDOFF_REGISTERED"
    assert output["incremental_processing_counts"]["structured_events"] == 1
    assert output["incremental_processing_counts"]["pending_analysis_or_disposition"] == 1
    product = json.loads((evidence / "analysis_product.json").read_text(encoding="utf-8"))
    incremental = product["source_manifest"]["incremental_processing"]
    assert incremental["reuse"]["body_input_sha256"] == body_ref["sha256"]
    assert incremental["counts"]["structured_events"] == 1
