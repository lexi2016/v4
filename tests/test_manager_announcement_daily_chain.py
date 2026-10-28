"""Owner-level source-order and exact HK calendar-day regressions."""
from datetime import datetime, timedelta
from hashlib import sha256
import hashlib
import json
import os
from pathlib import Path
import shutil
from urllib.parse import parse_qs, urlsplit
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from announcement_autorun_fixtures import HK, OwnerFixture
from ops.run_manager_announcement_cycle import _daily_announcement_capture_schedule
from ops import run_manager_daily_announcement as daily_runner
from v4.manager_research import workspace_announcements as owner
from v4.manager_research import announcement_autorun
from v4.manager_research.ports import SourceResponse
from ops import manager_announcement_body_batch as body_batch
from v4.manager_research.workspace_projection import digest


def test_daily_worker_schedule_requests_full_calendar_day():
    value = {"policy": "BALANCED_V1", "priority_codes": ["HK.02665"],
             "files": {"announcement_autorun.py": "a" * 64}, "python_sha256": "b" * 64}
    now = datetime(2026, 10, 12, 9, 30, tzinfo=HK)

    schedule = _daily_announcement_capture_schedule(value, now)

    assert schedule["capture_mode"] == "HK_CALENDAR_DAY_V1"
    assert schedule["policy"] == "BALANCED_V1"
    assert schedule["priority_codes"] == ["HK.02665"]
    assert schedule["now"] == now.isoformat()
    assert schedule["execution_identity"]["status"] == "BOUND_WORKER"


def test_full_day_hkex_refresh_uses_bounded_directory_timeout(monkeypatch):
    seen = []
    monkeypatch.setattr(daily_runner, "_request",
        lambda base, path, **kwargs: seen.append((base, path, kwargs)) or {"status": "ok"})

    result = daily_runner._refresh_hkex_daily_directory("http://127.0.0.1:8873",
        "/api/v4/manager/research/announcements/refresh?date=20261012")

    assert result == {"status": "ok"}
    assert seen == [("http://127.0.0.1:8873",
        "/api/v4/manager/research/announcements/refresh?date=20261012",
        {"method": "POST", "timeout_seconds": 120})]


def test_calendar_day_scheduled_invocation_always_forces_fresh_eastmoney(monkeypatch, tmp_path):
    fixture = OwnerFixture(tmp_path, monkeypatch, ("HK.02665",))
    fixture.now = datetime(2026, 9, 24, 10, 0, tzinfo=HK)
    observed = []

    def capture(_service, date, publication_date, *, resume=False, force_fresh=False, **_kwargs):
        observed.append((date, publication_date, resume, force_fresh))
        return {"run_id": "fresh"}

    monkeypatch.setattr(owner, "refresh_eastmoney_date_catalog", capture)
    monkeypatch.setattr(announcement_autorun, "_scheduled_refresh",
        lambda _service, _date, _schedule, **kwargs: {"catalog": kwargs["catalog"]})
    result = announcement_autorun.scheduled_refresh(fixture.service, "20260924", {
        "policy": "BALANCED_V1", "now": fixture.now.isoformat(),
        "capture_mode": "HK_CALENDAR_DAY_V1"})

    assert observed == [("20260924", "20260924", False, True)]
    assert result["catalog"] == {"run_id": "fresh"}
    fixture.service.close()


def test_daily_directory_repeats_inside_policy_interval_but_preopen_remains_throttled(
        tmp_path, monkeypatch):
    fixture = OwnerFixture(tmp_path, monkeypatch, ("HK.02665",))
    fixture.now = datetime(2026, 9, 24, 10, 0, tzinfo=HK)
    events = []
    catalog_runs = []
    pdf_url = fixture.add("HK.02665", minute=0, slug="daily-chain")
    page_rows = [{
        "NEWS_ID": "12345678", "STOCK_CODE": "02665", "STOCK_NAME": "Fixture 02665",
        "DATE_TIME": "24/09/2026 07:30", "TITLE": "Fixture notice",
        "FILE_TYPE": "PDF", "FILE_INFO": "PDF",
        "FILE_LINK": urlsplit(pdf_url).path,
    }]

    def catalog_capture(_service, date, publication_date, *, resume=False, force_fresh=False, **_kwargs):
        assert (date, publication_date, resume, force_fresh) == ("20260924", "20260924", False, True)
        catalog_runs.append(len(catalog_runs) + 1)
        return {"target_trade_date": date, "publication_date": "2026-09-24",
            "readback_status": "VERIFIED", "catalog": {
                "target_trade_date": date, "publication_date": "2026-09-24",
                "source_scope": "EASTMONEY_HK_DATE_CATALOG", "status": "COMPLETE",
                "run_id": f"{len(catalog_runs):032x}", "sha256": "b" * 64,
                "captured_page_count": 1, "total_hits": 1}}

    def market_transport(url, *, timeout, method="GET", body=None, headers=None):
        assert method == "GET"
        if url == pdf_url:
            return SourceResponse(url, 200, fixture.pdfs[url], {"content-type": "application/pdf"},
                                  fixture.now.isoformat())
        query = parse_qs(urlsplit(url).query, keep_blank_values=True)
        assert query.get("fromDate") == ["20260924"]
        assert query.get("toDate") == ["20260924"]
        assert query.get("stockId") == [""]
        events.append(url)
        row_range = int(query["rowRange"][0])
        payload = {"recordCnt": 1, "loadedRecord": 1, "rowRange": row_range,
                   "hasNextRow": False, "result": page_rows}
        return SourceResponse(url, 200, json.dumps(payload, ensure_ascii=False).encode(),
                              {"content-type": "application/json"}, fixture.now.isoformat())

    monkeypatch.setattr(owner, "refresh_eastmoney_date_catalog", catalog_capture)
    fixture.provider._material_transport._transport = market_transport

    class DailyProjectionResponseService:
        """Exercise the registered route with the actual owner daily projection shape."""
        def __init__(self, service):
            self._service = service
            self.last_capture_partition = None

        def __getattr__(self, name):
            return getattr(self._service, name)

        def refresh_announcements(self, target_trade_date, **kwargs):
            self.last_capture_partition = self._service.refresh_announcements(target_trade_date, **kwargs)
            return self._service.get_announcements(target_trade_date)

    from apps.api.v35_api.manager_research_router import create_manager_research_router
    app = FastAPI()
    route_service = DailyProjectionResponseService(fixture.service)
    app.include_router(create_manager_research_router(route_service))
    with TestClient(app) as client:
        before_first = client.get("/api/v4/manager/research/announcements",
            params={"date": "20260924"}).json()
        first_response = client.post("/api/v4/manager/research/announcements/refresh",
            params={"date": "20260924", "source_scope": "HKEX_OFFICIAL_FULL_DAY_DIRECTORY"})
        assert first_response.status_code == 200
        first = first_response.json()
        first_readback = client.get("/api/v4/manager/research/announcements",
            params={"date": "20260924"}).json()
    assert "market_directory_document_sets" in first["coverage"]
    assert "market_directory_products" in first["coverage"]
    _first_ids, _first_docs, first_bound_run_id = daily_runner._bind_fresh_hkex_daily_directory(
        before_first, first, first_readback, "20260924", "2026-09-24")
    first_attempt = first["attempt"]["input_coverage"]["market_directory"]
    first_run_id = first_attempt["product_run_id"]
    assert first_bound_run_id == first_run_id
    assert first_attempt["status"] == "COMPLETE"
    assert first_attempt["product_sha256"]
    assert len(events) == 1
    before_readback = first_readback
    first_ids, first_docs = body_batch._verified_hkex_directory_readback(
        before_readback, "20260924", "2026-09-24")
    assert first_ids == {first_run_id}
    assert [doc["capture_run_id"] for doc in first_docs] == [first_run_id]

    fixture.now += timedelta(seconds=5)
    with TestClient(app) as client:
        second_response = client.post("/api/v4/manager/research/announcements/refresh",
            params={"date": "20260924", "source_scope": "HKEX_OFFICIAL_FULL_DAY_DIRECTORY"})
        assert second_response.status_code == 200
        second = second_response.json()
        automatic_refresh = route_service.last_capture_partition
        after_readback = client.get("/api/v4/manager/research/announcements",
            params={"date": "20260924"}).json()
    second_attempt = second["attempt"]["input_coverage"]["market_directory"]
    second_run_id = second_attempt["product_run_id"]
    assert second_attempt["status"] == "COMPLETE"
    assert second_run_id != first_run_id
    assert len(events) == 2
    assert len(catalog_runs) == 2
    run_ids, selected_docs = body_batch._verified_hkex_directory_readback(
        after_readback, "20260924", "2026-09-24")
    assert run_ids == {first_run_id, second_run_id}
    assert [doc["capture_run_id"] for doc in selected_docs] == [second_run_id]
    assert [item["product_run_id"] for item in
        after_readback["coverage"]["market_directory_document_sets"]] == [first_run_id, second_run_id]
    truncated_readback = json.loads(json.dumps(after_readback))
    truncated_readback["coverage"]["market_directory_document_sets"][0]["official_documents"] = []
    with pytest.raises(ValueError, match="HKEX_DAILY_DIRECTORY_DOCUMENT_SET_COUNT_MISMATCH"):
        body_batch._verified_hkex_directory_readback(
            truncated_readback, "20260924", "2026-09-24")
    _run_ids, bound_docs, fresh_run_id = daily_runner._bind_fresh_hkex_daily_directory(
        before_readback, second, after_readback, "20260924", "2026-09-24")
    assert fresh_run_id == second_run_id
    assert [doc["capture_run_id"] for doc in bound_docs] == [second_run_id]
    _automatic_ids, automatic_docs, automatic_run_id = daily_runner._bind_fresh_hkex_daily_directory(
        before_readback, automatic_refresh, after_readback, "20260924", "2026-09-24")
    assert automatic_run_id == second_run_id
    assert [doc["capture_run_id"] for doc in automatic_docs] == [second_run_id]

    # Continue through the existing body producer and terminal validator using
    # the actual service GET projection, including both immutable source runs.
    evidence = tmp_path / "state" / "announcement_agent_runs" / ("d" * 32) / "evidence"
    evidence.mkdir(parents=True)
    catalog_read = {"schema_version": "v4.manager_research.eastmoney_hk_date_catalog_read.v1",
        "target_trade_date": "20260924", "publication_date": "2026-09-24",
        "source_scope": "EASTMONEY_HK_DATE_CATALOG", "status": "COMPLETE",
        "readback_status": "VERIFIED", "catalog": {
            "target_trade_date": "20260924", "publication_date": "2026-09-24",
            "source_scope": "EASTMONEY_HK_DATE_CATALOG", "status": "COMPLETE",
            "run_id": "c" * 32, "sha256": "e" * 64,
            "connect_eligibility_status": "NOT_ASSESSED",
            "hkex_first_publication_verified": False}}
    monthly_root = tmp_path / "monthly-authority"
    monthly_root.mkdir()
    authority_refs = {"artifact_ref": "artifact.json", "manifest_ref": "manifest.json",
        "receipt_ref": "receipt.json", "current_ref": "current.json",
        "capture_ref": "capture.json", "publication_ref": "publication.json"}
    authority_hashes = {}
    for ref_name, ref in authority_refs.items():
        data = ("fixture-authority:" + ref_name).encode()
        (monthly_root / ref).write_bytes(data)
        authority_hashes[ref_name] = hashlib.sha256(data).hexdigest()
    monthly = {"schema_version": "v4.manager_research.hk_connect_monthly_eligibility.v1",
        "status": "VERIFIED", "policy": "CALENDAR_MONTH_LATEST_VERIFIED_V2", "month": "202609",
        "target_trade_date": "20260924", "source_date": "20260901",
        "capture_cutoff_at": "2026-09-24T08:00:00+00:00",
        "source": {"market": "HK_CONNECT", "role": "HK_CONNECT_FULL_MARKET_AUTHORITY",
            "source_date": "20260901", "available_at": "2026-09-01T09:00:00+08:00",
            **authority_refs, "sha256": "1" * 64, "capture_sha256": "2" * 64,
            "source_sha256": "3" * 64},
        "authority_file_sha256s": authority_hashes, "code_count": 1,
        "codes_sha256": digest(["HK.02665"]), "codes": ["HK.02665"],
        "invalid_newer_candidates": [], "RESEARCH_ONLY": True,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    monthly["identity_sha256"] = digest(monthly)
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_ROOT", str(monthly_root))
    catalog_path = evidence / "catalog_read.json"
    catalog_path.write_text(json.dumps(catalog_read, ensure_ascii=False), encoding="utf-8")
    hkex_path = evidence / "hkex_directory_read.json"
    hkex_path.write_bytes(body_batch.json_bytes(after_readback))
    eligibility_path = evidence / "monthly_connect_eligibility.json"
    eligibility_path.write_bytes(body_batch.json_bytes(monthly))
    monkeypatch.setattr(body_batch, "_validate_catalog", lambda *_args: [])
    real_imports = body_batch.imports
    monkeypatch.setattr(body_batch, "imports", lambda: {
        **real_imports(), "HkexOfficialProvider": lambda **_kwargs: fixture.provider})
    body_output = evidence / "body_batch"
    batch = body_batch.run_capture(catalog_read, fixture.materials.root, body_output,
        "20260924", "2026-09-24", hkex_directory_readback=after_readback,
        monthly_connect_eligibility=monthly)
    for name in ("body_corpus.json", "body_corpus_manifest.json"):
        shutil.copyfile(body_output / name, evidence / name)
    shutil.copyfile(body_output / "batch_receipt.json", evidence / "body_batch_receipt.json")
    capture_receipt = {"schema_version": "v4.manager_research.announcement_daily_capture.v1",
        "status": batch["status"], "evidence_run_id": "d" * 32,
        "target_trade_date": "20260924", "publication_date": "2026-09-24",
        "catalog_run_id": catalog_read["catalog"]["run_id"],
        "catalog_product_sha256": catalog_read["catalog"]["sha256"],
        "catalog_read_file_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "body_corpus_file_sha256": hashlib.sha256((evidence / "body_corpus.json").read_bytes()).hexdigest(),
        "body_corpus_manifest_file_sha256": hashlib.sha256((evidence / "body_corpus_manifest.json").read_bytes()).hexdigest(),
        "body_batch_receipt_sha256": hashlib.sha256((evidence / "body_batch_receipt.json").read_bytes()).hexdigest(),
        "hkex_directory_read_file_sha256": hashlib.sha256(hkex_path.read_bytes()).hexdigest(),
        "hkex_directory_run_ids": sorted(run_ids), "hkex_directory_capture_mode": "FRESH_OWNER_CAPTURE",
        "hkex_prior_directory_run_ids": [first_run_id], "hkex_fresh_directory_run_id": second_run_id,
        "hkex_directory_document_count": 1,
        "hkex_directory_readback_sha256": body_batch.digest(body_batch.json_bytes(after_readback)),
        "hkex_body_coverage_status": batch["hkex_official_supplement"]["body_coverage_status"],
        "hkex_eligible_document_count": batch["hkex_official_supplement"]["eligible_document_count"],
        "hkex_excluded_document_count": batch["hkex_official_supplement"]["excluded_document_count"],
        "hkex_unresolved_document_count": batch["hkex_official_supplement"]["unresolved_document_count"],
        "monthly_connect_eligibility_file_sha256": hashlib.sha256(eligibility_path.read_bytes()).hexdigest(),
        "monthly_connect_eligibility_identity_sha256": monthly["identity_sha256"],
        "monthly_connect_source_date": monthly["source_date"],
        "monthly_connect_authority_file_sha256s": authority_hashes,
        "eastmoney_directory_coverage": batch["eastmoney_directory_coverage"], **owner.FLAGS}
    (evidence / "capture_receipt.json").write_text(
        json.dumps(capture_receipt, ensure_ascii=False), encoding="utf-8")
    terminal = owner.validate_terminal_body_capture(evidence, catalog_read, "20260924", "2026-09-24",
        expected_run_id="d" * 32)
    assert terminal["hkex_directory_run_ids"] == sorted(run_ids)
    assert terminal["status"] == batch["status"]

    # The ordinary preopen lane keeps its existing same-interval throttle.
    fixture.now += timedelta(seconds=5)
    preopen = announcement_autorun.scheduled_refresh(fixture.service, "20260924", {
        "policy": "BALANCED_V1", "now": fixture.now.isoformat()})
    assert preopen["attempt"]["input_coverage"]["market_directory"]["product_run_id"] == second_run_id
    assert len(events) == 2
    fixture.service.close()


def test_daily_capture_rejects_reused_hkex_directory_product_run_id():
    run_id = "a" * 32
    target = "20261012"
    before = {"status": "NOT_RUN", "target_trade_date": target,
        "daily_publication_date": target, "publication_timezone": "Asia/Hong_Kong", "coverage": {}}
    market = {"status": "COMPLETE", "directory_exhaustion": "VERIFIED",
        "from_date": target, "to_date": target, "window_mode": "HK_CALENDAR_DAY_V1",
        "publication_window_start": "2026-10-12T00:00:00+08:00",
        "query_cutoff": "2026-10-12T08:00:00+08:00", "record_count": 0,
        "loaded_record": 0, "captured_page_count": 1, "captured_row_count": 0,
        "unique_news_id_count": 0, "body_documents_captured": 0,
        "pending_document_count": 0, "gaps": [], "body_gaps": [],
        "product_run_id": run_id, "product_sha256": "b" * 64}
    product = {"source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
        "from_date": target, "to_date": target, "window_mode": "HK_CALENDAR_DAY_V1",
        "publication_window_start": "2026-10-12T00:00:00+08:00",
        "query_cutoff": "2026-10-12T08:00:00+08:00",
        "status": "COMPLETE", "directory_exhaustion": "VERIFIED", "record_count": 0,
        "loaded_record": 0, "captured_page_count": 1, "captured_row_count": 0,
        "unique_news_id_count": 0, "body_document_count": 0, "pending_document_count": 0,
        "gaps": [], "body_gaps": [],
        "product_run_id": run_id, "product_sha256": "b" * 64}
    unsigned_attempt = {"run_id": "c" * 32, "target_trade_date": target,
        "execution_kind": "SCHEDULED_REFRESH", "state": "SUCCEEDED",
        "started_at": "2026-10-12T07:59:00+08:00", "finished_at": "2026-10-12T08:00:01+08:00",
        "input_coverage": {"source_order": ["EASTMONEY_HK_DATE_CATALOG",
            "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY"], "market_directory": market}}
    attempt = {**unsigned_attempt, "sha256": digest(unsigned_attempt)}
    after = {"status": "PARTIAL", "target_trade_date": target,
        "daily_publication_date": target, "publication_timezone": "Asia/Hong_Kong",
        "attempt": attempt, "coverage": {"market_directory_products": [product],
            "market_directory_document_sets": [{"product_run_id": run_id,
                "product_capture_cutoff": "2026-10-12T08:00:00+08:00", "official_documents": []}]},
        "official_documents": []}
    refresh = dict(after)
    refresh["coverage"] = {"market_directory_products": [product],
        "market_directory_document_sets": [{"product_run_id": run_id,
            "product_capture_cutoff": "2026-10-12T08:00:00+08:00", "official_documents": []}]}

    assert daily_runner._bind_fresh_hkex_daily_directory(
        before, refresh, after, target, "2026-10-12")[2] == run_id
    with pytest.raises(ValueError, match="ANNOUNCEMENT_DAILY_HKEX_FRESH_DIRECTORY_RUN_REQUIRED"):
        daily_runner._bind_fresh_hkex_daily_directory(after, refresh, after, target, "2026-10-12")
    invalid_attempt = dict(refresh, attempt={**attempt, "sha256": "0" * 64})
    with pytest.raises(ValueError, match="ANNOUNCEMENT_DAILY_HKEX_CURRENT_ATTEMPT_PRODUCT_BINDING_INVALID"):
        daily_runner._bind_fresh_hkex_daily_directory(
            before, invalid_attempt, after, target, "2026-10-12")


def test_terminal_hkex_capture_receipt_binds_exact_fresh_directory_run():
    old_run, fresh_run = "a" * 32, "b" * 32
    capture = {"hkex_directory_capture_mode": "FRESH_OWNER_CAPTURE",
        "hkex_prior_directory_run_ids": [old_run], "hkex_fresh_directory_run_id": fresh_run}
    assert owner._validated_hkex_directory_capture_proof(capture, {old_run, fresh_run}) == fresh_run
    with pytest.raises(ValueError, match="ANNOUNCEMENT_BODY_CAPTURE_HKEX_FRESH_RUN_BINDING_INVALID"):
        owner._validated_hkex_directory_capture_proof(capture, {old_run})
    with pytest.raises(ValueError, match="ANNOUNCEMENT_BODY_CAPTURE_HKEX_FRESH_RUN_BINDING_INVALID"):
        owner._validated_hkex_directory_capture_proof(
            dict(capture, hkex_prior_directory_run_ids=[old_run, fresh_run]), {old_run, fresh_run})
    assert owner._validated_hkex_directory_capture_proof(
        {"hkex_directory_capture_mode": "RESUMED_SAVED_DIRECTORY_READBACK"}, {old_run}) is None


def test_daily_directory_scope_captures_eastmoney_then_exact_day_hkex(tmp_path, monkeypatch):
    fixture = OwnerFixture(tmp_path, monkeypatch, ("HK.02665",))
    events = []
    page_rows = [{
        "NEWS_ID": "12345678", "STOCK_CODE": "02665", "STOCK_NAME": "Fixture 02665",
        "DATE_TIME": "24/09/2026 07:30", "TITLE": "Fixture notice",
        "FILE_TYPE": "HTML", "FILE_INFO": "HTML",
        "FILE_LINK": "/listedco/listconews/sehk/2026/0924/02665-fixture.htm",
    }]

    def catalog_capture(_service, date, publication_date, *, resume=False, **_kwargs):
        assert (date, publication_date) == ("20260924", "20260924")
        events.append("EASTMONEY_DATE_CATALOG")
        return {
            "target_trade_date": date, "publication_date": "2026-09-24",
            "readback_status": "VERIFIED",
            "catalog": {
                "target_trade_date": date, "publication_date": "2026-09-24",
                "source_scope": "EASTMONEY_HK_DATE_CATALOG", "status": "COMPLETE",
                "run_id": "a" * 32, "sha256": "b" * 64,
                "captured_page_count": 1, "total_hits": 1,
            },
        }

    def market_transport(url, *, timeout, method="GET", body=None, headers=None):
        assert method == "GET"
        assert url.startswith("https://www1.hkexnews.hk/search/titleSearchServlet.do?")
        query = parse_qs(urlsplit(url).query, keep_blank_values=True)
        assert query.get("fromDate") == ["20260924"]
        assert query.get("toDate") == ["20260924"]
        assert query.get("stockId") == [""]
        assert query.get("lang") == ["ZH"]
        events.append("HKEX_FULL_MARKET_PAGE")
        row_range = int(query["rowRange"][0])
        payload = {"recordCnt": 1, "loadedRecord": 1, "rowRange": row_range,
                   "hasNextRow": False, "result": page_rows}
        return SourceResponse(url, 200, json.dumps(payload, ensure_ascii=False).encode(),
                              {"content-type": "application/json"}, fixture.now.isoformat())

    monkeypatch.setattr(owner, "refresh_eastmoney_date_catalog", catalog_capture)
    fixture.provider._material_transport._transport = market_transport

    result = fixture.service.refresh_announcements(
        "20260924", source_scope="HKEX_OFFICIAL_FULL_DAY_DIRECTORY")

    assert events == ["EASTMONEY_DATE_CATALOG", "HKEX_FULL_MARKET_PAGE"]
    coverage = result["attempt"]["input_coverage"]
    assert coverage["source_order"] == [
        "EASTMONEY_HK_DATE_CATALOG", "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY"]
    market = coverage["market_directory"]
    assert market["from_date"] == market["to_date"] == "20260924"
    assert market["publication_window_start"] == "2026-09-24T00:00:00+08:00"
    assert market["window_mode"] == "HK_CALENDAR_DAY_V1"
    assert market["directory_exhaustion"] == "VERIFIED"
    assert result["official_documents"][0]["news_id"] == "12345678"
    fixture.service.close()


def test_hkex_official_body_variant_keeps_news_id_and_official_provenance(tmp_path):
    raw_directory = b"official-directory-page"
    raw_pdf = b"%PDF-official-body"
    directory_ref = {"request": {"url": "https://www1.hkexnews.hk/search/titleSearchServlet.do?date=20261012",
        "method": "GET"}, "blob_sha256": sha256(raw_directory).hexdigest(),
        "body_sha256": sha256(raw_directory).hexdigest(), "http_status": 200,
        "retrieved_at": "2026-10-12T10:00:00+00:00"}
    body_ref = {"request": {"url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/02665-example.pdf",
        "method": "GET"}, "blob_sha256": sha256(raw_pdf).hexdigest(),
        "body_sha256": sha256(raw_pdf).hexdigest(), "http_status": 200,
        "retrieved_at": "2026-10-12T10:01:00+00:00", "from_cache": False}
    doc = {"source": "HKEX_OFFICIAL",
        "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1", "news_id": "12345678",
        "event_id": "event-1", "symbol": "HK.02665", "name": "Fixture 02665",
        "title": "Official result announcement", "publication_date": "20261012",
        "published_at": "2026-10-12T07:30:00+08:00", "available_at": "2026-10-12T10:00:00+00:00",
        "source_url": body_ref["request"]["url"], "directory_ref": directory_ref,
        "source_refs": [directory_ref, body_ref], "capture_run_id": "a" * 32,
        "capture_revision": 1, "target_trade_date": "20261012", "capture_trade_date": "20261012",
        "body_status": "BODY_CAPTURED_UNASSESSED", "document_sha256": body_ref["body_sha256"]}
    readback = {"target_trade_date": "20261012", "daily_publication_date": "20261012",
        "publication_timezone": "Asia/Hong_Kong", "coverage": {"market_directory_products": [{
            "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1", "from_date": "20261012",
            "to_date": "20261012", "window_mode": "HK_CALENDAR_DAY_V1", "status": "COMPLETE",
            "directory_exhaustion": "VERIFIED", "record_count": 1, "loaded_record": 1,
            "captured_row_count": 1, "unique_news_id_count": 1, "product_run_id": "a" * 32,
            "product_sha256": "b" * 64}]}, "official_documents": [doc]}
    run_ids, docs = body_batch._verified_hkex_directory_readback(readback, "20261012", "2026-10-12")
    assert run_ids == {"a" * 32}
    assert docs == [doc]

    api = {"read_response": lambda _store, ref: raw_directory if ref is directory_ref else raw_pdf,
        "extract_pdf_pages": lambda *_args, **_kwargs: [{"text": "Official source text"}],
        "safe_reason": lambda exc, _fallback: str(exc)}
    gate = body_batch.SharedCaptureGate(seconds=10, max_requests=10, max_bytes=1024, interval=0)
    gate.set_response_limits(per_response=1024, total=1024)
    result = body_batch._capture_hkex_variant(api, object(), object(), gate, doc,
        tmp_path, "20261012", "2026-10-12")

    assert result["source_variant_id"] == "HKEX:12345678"
    assert "art_code" not in result
    assert result["source_scope"] == "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1"
    assert result["cross_source_link_status"] == "NOT_ASSESSED"
    assert result["body_status"] == "COMPLETE_HKEX_OFFICIAL_PDF_BODY"
    assert result["body_text"] == "Official source text"
    assert result["body_source_ref"] == body_ref
    assert result["directory_source_ref"] == directory_ref


def test_hkex_directory_readback_rejects_self_reported_complete_but_truncated_documents():
    directory_ref = {"request": {"url": "https://www1.hkexnews.hk/search/titleSearchServlet.do?date=20261012",
        "method": "GET"}, "blob_sha256": "d" * 64, "body_sha256": "d" * 64,
        "http_status": 200, "retrieved_at": "2026-10-12T10:00:00+00:00"}
    doc = {"source": "HKEX_OFFICIAL", "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
        "news_id": "12345678", "publication_date": "20261012", "capture_run_id": "a" * 32,
        "capture_trade_date": "20261012", "target_trade_date": "20261012",
        "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/02665-example.pdf",
        "directory_ref": directory_ref}
    readback = {"target_trade_date": "20261012", "daily_publication_date": "20261012",
        "publication_timezone": "Asia/Hong_Kong", "coverage": {"market_directory_products": [{
            "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1", "from_date": "20261012",
            "to_date": "20261012", "window_mode": "HK_CALENDAR_DAY_V1", "status": "COMPLETE",
            "directory_exhaustion": "VERIFIED", "record_count": 2, "loaded_record": 2,
            "captured_row_count": 2, "unique_news_id_count": 2, "product_run_id": "a" * 32,
            "product_sha256": "b" * 64}]}, "official_documents": [doc]}

    try:
        body_batch._verified_hkex_directory_readback(readback, "20261012", "2026-10-12")
    except ValueError as exc:
        assert str(exc) == "HKEX_DAILY_DIRECTORY_DOCUMENT_SET_COUNT_MISMATCH"
    else:
        raise AssertionError("truncated official document list must not satisfy complete directory coverage")


def test_monthly_connect_filter_uses_exact_codes_and_keeps_source_identity():
    codes = {"HK.02665"}
    identity = "c" * 64
    eastmoney_rows = [
        {"art_code": "AN202610121", "source_issuer_codes": [{"code": "HK.02665", "source_stock_code": "02665"}],
         "source_ref": {"body_sha256": "a" * 64}, "raw_body_sha256": "a" * 64},
        {"art_code": "AN202610122", "source_issuer_codes": [{"code": "HK.09690", "source_stock_code": "09690"}],
         "source_ref": {"body_sha256": "b" * 64}, "raw_body_sha256": "b" * 64},
    ]
    hkex_documents = [
        {"news_id": "12345678", "symbol": "HK.02665", "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
         "directory_ref": {"body_sha256": "d" * 64}},
        {"news_id": "22345678", "symbol": "HK.09690", "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
         "directory_ref": {"body_sha256": "e" * 64}},
        {"news_id": "32345678", "symbol": None, "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
         "directory_ref": {"body_sha256": "f" * 64}},
    ]

    rows, em_coverage, hkex_eligible, hkex_coverage = body_batch._apply_monthly_connect_eligibility(
        eastmoney_rows, hkex_documents, codes, identity)

    assert [row["art_code"] for row in rows] == ["AN202610121"]
    assert rows[0]["source_issuer_codes"] == eastmoney_rows[0]["source_issuer_codes"]
    assert rows[0]["connect_eligibility_identity_sha256"] == identity
    assert [row["status"] for row in em_coverage] == ["ELIGIBLE", "NOT_ELIGIBLE"]
    assert [doc["news_id"] for doc in hkex_eligible] == ["12345678"]
    assert [row["status"] for row in hkex_coverage] == ["ELIGIBLE", "NOT_ELIGIBLE", "UNRESOLVED"]
    assert hkex_coverage[0]["directory_source_ref"] == hkex_documents[0]["directory_ref"]


def test_daily_body_batch_fetches_only_exact_month_eligible_source_rows(tmp_path, monkeypatch):
    def source_ref(url, marker):
        raw_sha = marker * 64
        return {"request": {"url": url, "method": "GET"}, "blob_sha256": raw_sha,
            "body_sha256": raw_sha, "http_status": 200, "retrieved_at": "2026-10-12T08:00:00+00:00"}

    dir_ref = source_ref("https://www1.hkexnews.hk/search/titleSearchServlet.do?date=20261012", "d")
    docs = [
        {"source": "HKEX_OFFICIAL", "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
         "news_id": "12345678", "symbol": "HK.02665", "title": "Eligible official doc",
         "publication_date": "20261012", "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/02665-a.pdf",
         "directory_ref": dir_ref, "capture_run_id": "a" * 32,
         "capture_trade_date": "20261012", "target_trade_date": "20261012"},
        {"source": "HKEX_OFFICIAL", "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
         "news_id": "22345678", "symbol": "HK.09690", "title": "Excluded official doc",
         "publication_date": "20261012", "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/09690-a.pdf",
         "directory_ref": dir_ref, "capture_run_id": "a" * 32,
         "capture_trade_date": "20261012", "target_trade_date": "20261012"},
        {"source": "HKEX_OFFICIAL", "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
         "news_id": "32345678", "symbol": None, "title": "Unresolved official doc",
         "publication_date": "20261012", "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/unknown.pdf",
         "directory_ref": dir_ref, "capture_run_id": "a" * 32,
         "capture_trade_date": "20261012", "target_trade_date": "20261012"},
    ]
    readback = {"target_trade_date": "20261012", "daily_publication_date": "20261012",
        "publication_timezone": "Asia/Hong_Kong", "coverage": {"market_directory_products": [{
            "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1", "from_date": "20261012",
            "to_date": "20261012", "window_mode": "HK_CALENDAR_DAY_V1", "status": "COMPLETE",
            "directory_exhaustion": "VERIFIED", "record_count": 3, "loaded_record": 3,
            "captured_row_count": 3, "unique_news_id_count": 3,
            "product_run_id": "a" * 32, "product_sha256": "b" * 64}]}, "official_documents": docs}
    source = {"source_date": "20261005", "market": "HK_CONNECT",
        "role": "HK_CONNECT_FULL_MARKET_AUTHORITY", "available_at": "2026-10-05T09:00:00+08:00",
        "artifact_ref": "universes/20261005/HK_CONNECT_FULL_MARKET.json",
        "manifest_ref": "universes/20261005/HK_CONNECT_FULL_MARKET.authority/run/manifest.json",
        "receipt_ref": "universes/20261005/HK_CONNECT_FULL_MARKET.authority/run/receipt.json",
        "current_ref": "universes/20261005/HK_CONNECT_FULL_MARKET.authority/current.json",
        "capture_ref": "universes/20261005/HK_CONNECT_FULL_MARKET.authority/run/capture.json",
        "publication_ref": "universes/20261005/HK_CONNECT_FULL_MARKET.authority/run/publication.json",
        "sha256": "1" * 64, "capture_sha256": "2" * 64, "source_sha256": "3" * 64}
    ref_keys = ("artifact_ref", "manifest_ref", "receipt_ref", "current_ref", "capture_ref", "publication_ref")
    monthly = {"schema_version": "v4.manager_research.hk_connect_monthly_eligibility.v1",
        "status": "VERIFIED", "policy": "CALENDAR_MONTH_LATEST_VERIFIED_V2", "month": "202610",
        "target_trade_date": "20261012", "source_date": "20261005",
        "capture_cutoff_at": "2026-10-12T08:00:00+00:00", "source": source,
        "authority_file_sha256s": {key: "4" * 64 for key in ref_keys},
        "code_count": 1, "codes_sha256": digest(["HK.02665"]), "codes": ["HK.02665"],
        "invalid_newer_candidates": [], "RESEARCH_ONLY": True,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    monthly["identity_sha256"] = digest(monthly)
    rows = [
        {"art_code": "AN202610121234", "source_issuer_codes": [{"market_code": "116", "ann_type": "H",
             "source_stock_code": "02665", "code": "HK.02665"}], "source_ref": {"body_sha256": "5" * 64},
         "raw_body_sha256": "5" * 64, "title": "Eligible EM notice"},
        {"art_code": "AN202610129999", "source_issuer_codes": [{"market_code": "116", "ann_type": "H",
             "source_stock_code": "09690", "code": "HK.09690"}], "source_ref": {"body_sha256": "6" * 64},
         "raw_body_sha256": "6" * 64, "title": "Excluded EM notice"},
    ]
    fetched_em, fetched_hkex = [], []
    monkeypatch.setattr(body_batch, "_validate_catalog", lambda *_args: rows)

    def capture_em(_api, _store, _provider, _gate, row, output, target, publication):
        fetched_em.append(row["art_code"])
        path = output / "eligible-em.json"
        body_file = {"art_code": row["art_code"], "title": row["title"],
            "body_status": "COMPLETE_CONTENT_API_BODY", "content_api_pages": [],
            "body_text": "eligible body", "body_text_sha256": "7" * 64}
        body_batch.atomic_json(path, body_file)
        return {"art_code": row["art_code"], "target_trade_date": target,
            "publication_date": publication, "body_status": "COMPLETE_CONTENT_API_BODY",
            "status": "COMPLETE_CONTENT_API_BODY", "body_path": path.name,
            "body_file_sha256": "8" * 64}

    def capture_hkex(_api, _store, _provider, _gate, doc, _output, _target, _publication):
        fetched_hkex.append(doc["news_id"])
        return {"source_variant_id": "HKEX:" + doc["news_id"], "news_id": doc["news_id"],
            "source": "HKEX_OFFICIAL", "source_scope": doc["source_scope"],
            "body_status": "COMPLETE_HKEX_OFFICIAL_PDF_BODY", "body_source_ref": None,
            "directory_source_ref": doc["directory_ref"], "body_text": "eligible official text",
            "pages": [], "semantic_status": "NOT_REVIEWED"}

    monkeypatch.setattr(body_batch, "_capture_article", capture_em)
    monkeypatch.setattr(body_batch, "_capture_hkex_variant", capture_hkex)
    catalog = {"run_id": "c" * 32, "sha256": "e" * 64, "manager_consumer_row_count": 2}
    catalog_read = {"readback_status": "VERIFIED", "target_trade_date": "20261012",
        "publication_date": "2026-10-12", "catalog": catalog}
    result = body_batch.run_capture(catalog_read, tmp_path / "materials", tmp_path / "out",
        "20261012", "2026-10-12", hkex_directory_readback=readback,
        monthly_connect_eligibility=monthly)

    corpus = body_batch.read_json(tmp_path / "out/body_corpus.json")
    manifest = body_batch.read_json(tmp_path / "out/body_corpus_manifest.json")
    assert fetched_em == ["AN202610121234"]
    assert fetched_hkex == ["12345678"]
    assert [row["art_code"] for row in corpus["rows"]] == ["AN202610121234"]
    assert [row["source_variant_id"] for row in corpus["source_variants"]] == ["HKEX:12345678"]
    assert "art_code" not in corpus["source_variants"][0]
    assert manifest["monthly_connect_eligibility"]["excluded_eastmoney_row_count"] == 1
    unresolved_only = dict(readback, coverage={"market_directory_products": [dict(
        readback["coverage"]["market_directory_products"][0], record_count=1, loaded_record=1,
        captured_row_count=1, unique_news_id_count=1)]}, official_documents=[docs[2]])
    second = body_batch.run_capture(catalog_read, tmp_path / "materials", tmp_path / "out-unresolved",
        "20261012", "2026-10-12", hkex_directory_readback=unresolved_only,
        monthly_connect_eligibility=monthly)
    assert second["hkex_official_supplement"]["body_coverage_status"] == "UNASSESSED_SOURCE_IDENTITY_GAPS"
    assert second["hkex_official_supplement"]["unresolved_document_count"] == 1
    assert manifest["hkex_official_supplement"]["directory_document_count"] == 3
    assert manifest["hkex_official_supplement"]["eligible_document_count"] == 1
    assert manifest["hkex_official_supplement"]["unresolved_document_count"] == 1
    assert result["hkex_official_supplement"]["body_coverage_status"] == "COMPLETE"
