import json
import asyncio
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import FastAPI
from apps.api.v35_api.manager_research_router import create_manager_research_router
from v4.manager_research.announcement_autorun import _official_market_window, policy_due
from v4.manager_research.announcement_source import (
    CaptureBudget,
    collect_official_market_batch,
    verify_official_market_directory,
)
from v4.manager_research.hkex_provider import HkexOfficialProvider
from v4.manager_research.materials import MaterialStore
from v4.manager_research.ports import SourceResponse
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS
from upstreams.v3_shared_data.shared_data.hk_security_master import publish_hk_security_master


HKEX_PDF = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/2026101200006_c.pdf"
TARGET_ID = "12369250"
PDF_BODY = b"%PDF-1.4 bounded fixture"


def _row(news_id, release, code="02665", *, url=HKEX_PDF, title="公告"):
    return {
        "NEWS_ID": news_id,
        "STOCK_CODE": code,
        "STOCK_NAME": "圖達通" if code == "02665" else "示例公司",
        "DATE_TIME": release,
        "TITLE": title,
        "FILE_TYPE": "PDF",
        "FILE_INFO": "PDF",
        "FILE_LINK": url.split("www1.hkexnews.hk", 1)[-1],
    }


class _MarketTransport:
    def __init__(self, rows, retrieved_at, *, fail_status=None, pdf_status=None,
                 pdf_status_by_url=None, drift=False, truncate=False, raise_error=False):
        self.rows = rows
        self.retrieved_at = retrieved_at
        self.fail_status = fail_status
        self.pdf_status = pdf_status
        self.pdf_status_by_url = pdf_status_by_url or {}
        self.drift = drift
        self.truncate = truncate
        self.raise_error = raise_error
        self.calls = []

    def __call__(self, url, *, timeout, method="GET", body=None, headers=None):
        self.calls.append((url, method))
        if url.startswith("https://www1.hkexnews.hk/search/titleSearchServlet.do?"):
            row_range = int(parse_qs(urlsplit(url).query)["rowRange"][0])
            if self.raise_error:
                raise RuntimeError("transport unavailable")
            if self.fail_status is not None:
                return SourceResponse(url, self.fail_status, b"upstream unavailable", {}, self.retrieved_at)
            visible = list(self.rows[:row_range])
            if self.truncate and row_range == 100:
                visible = visible[:-1]
            if self.drift and row_range > 100 and visible:
                visible[0] = dict(visible[0], NEWS_ID="99999999")
            payload = {
                "recordCnt": len(self.rows),
                "loadedRecord": len(visible),
                "rowRange": row_range,
                "hasNextRow": len(visible) < len(self.rows),
                "result": visible,
            }
            return SourceResponse(url, 200, json.dumps(payload, ensure_ascii=False).encode(),
                                  {"content-type": "application/json"}, self.retrieved_at)
        if url.startswith("https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/") and url.lower().endswith(".pdf"):
            status=self.pdf_status_by_url.get(url, self.pdf_status) or 200
            body=PDF_BODY if status==200 else b"upstream unavailable"
            return SourceResponse(url, status, body, {"content-type": "application/pdf"}, self.retrieved_at)
        raise AssertionError(f"unexpected URL: {url}")


def _run(tmp_path, rows, cutoff, retrieved_at, *, fail_status=None, drift=False, truncate=False,
         raise_error=False, max_documents=0, target_date="20261012", from_date="20261009",
         publication_start="2026-10-09T16:00:00+08:00"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    transport = _MarketTransport(rows, retrieved_at, fail_status=fail_status, drift=drift,
                                 truncate=truncate, raise_error=raise_error)
    store = MaterialStore(tmp_path / "materials")
    provider = HkexOfficialProvider(transport=transport, material_store=store)
    result = collect_official_market_batch(
        provider,
        context={"plan_trade_date": target_date, "research_cutoff": cutoff},
        from_date=from_date,
        to_date=datetime.fromisoformat(cutoff).strftime("%Y%m%d"),
        publication_window_start=publication_start,
        window_mode="FALLBACK_PREVIOUS_HK_SESSION_CLOSE",
        priority_codes=["HK.02665"],
        max_documents=max_documents,
        budget=CaptureBudget(seconds=10, max_requests=10, interval=0),
    )
    generated_at = (max(datetime.fromisoformat(cutoff), datetime.fromisoformat(retrieved_at))
                    + timedelta(seconds=1)).isoformat()
    assert verify_official_market_directory(store, result["market_directory"], owner_generated_at=generated_at), \
        json.dumps(result["market_directory"], ensure_ascii=False, sort_keys=True)
    return result, transport, store


def test_official_cumulative_pages_validate_counts_and_keep_02665(tmp_path):
    rows = [_row(TARGET_ID, "12/10/2026 06:05", title="自願性公告 未經審核之二零二六年第三季度激光雷達出貨量")]
    rows.extend(_row(str(12369300 + i), "12/10/2026 05:59", code="09999") for i in range(100))

    result, transport, _store = _run(
        tmp_path,
        rows,
        "2026-10-12T06:55:00+08:00",
        "2026-10-12T06:54:00+08:00",
        max_documents=1,
    )
    market = result["market_directory"]

    assert market["status"] == "COMPLETE"
    assert market["directory_exhaustion"] == "VERIFIED"
    assert market["record_count"] == 101
    assert market["loaded_record"] == 101
    assert market["captured_page_count"] == 2
    assert [page["requested_row_range"] for page in market["pages"]] == [100, 200]
    assert [row["news_id"] for row in market["rows"] if row["news_id"] == TARGET_ID] == [TARGET_ID]
    assert result["market_documents"][0]["news_id"] == TARGET_ID
    assert result["market_documents"][0]["body_ref"]["body_sha256"]
    directory_queries = [parse_qs(urlsplit(url).query, keep_blank_values=True) for url, _method in transport.calls
                         if "titleSearchServlet.do" in url]
    assert directory_queries and all(query.get("stockId") == [""] for query in directory_queries)
    assert FLAGS["RESEARCH_ONLY"] is True
    assert FLAGS["production_allowed"] is False
    assert FLAGS["buy_gate_updated"] is False
    assert FLAGS["orders_sent"] is False


def test_publication_cutoff_keeps_0605_and_excludes_later_rows(tmp_path):
    rows = [
        _row("12369252", "12/10/2026 07:01", code="08888"),
        _row("12369251", "12/10/2026 06:58", code="09999"),
        _row(TARGET_ID, "12/10/2026 06:05"),
    ]
    at_0655, _transport, _store = _run(
        tmp_path / "0655", rows, "2026-10-12T06:55:00+08:00", "2026-10-12T07:05:00+08:00")
    at_0700, _transport, _store = _run(
        tmp_path / "0700", rows, "2026-10-12T07:00:00+08:00", "2026-10-12T07:05:00+08:00")

    assert policy_due(datetime.fromisoformat("2026-10-12T06:55:00+08:00"), "BALANCED_V1")
    assert policy_due(datetime.fromisoformat("2026-10-12T07:00:00+08:00"), "BALANCED_V1")
    assert [row["news_id"] for row in at_0655["market_pending_documents"]] == [TARGET_ID]
    assert [row["news_id"] for row in at_0700["market_pending_documents"]] == [TARGET_ID, "12369251"]


def test_page_identity_drift_and_http_failure_remain_partial(tmp_path):
    rows = [_row(str(12369400 + i), "12/10/2026 06:05") for i in range(101)]
    drifted, _transport, _store = _run(
        tmp_path / "drift", rows, "2026-10-12T06:55:00+08:00", "2026-10-12T06:54:00+08:00", drift=True)
    drift_market = drifted["market_directory"]
    assert drift_market["status"] == "PARTIAL"
    assert drift_market["directory_exhaustion"] == "UNVERIFIED"
    assert "HKEX_MARKET_DIRECTORY_PAGE_IDENTITY_DRIFT" in drift_market["gaps"]
    assert drift_market["accepted_page_number"] == 1

    failed, _transport, _store = _run(
        tmp_path / "http-failure", rows, "2026-10-12T06:55:00+08:00", "2026-10-12T06:54:00+08:00", fail_status=503)
    failed_market = failed["market_directory"]
    assert failed_market["status"] == "PARTIAL"
    assert failed_market["directory_exhaustion"] == "UNVERIFIED"
    assert "HKEX_MARKET_DIRECTORY_HTTP_FAILED" in failed_market["gaps"]
    assert failed_market["record_count"] is None


def test_duplicate_rows_missing_cumulative_rows_and_transport_failure_stay_unverified(tmp_path):
    duplicate_rows = [_row("12369500", "12/10/2026 06:05"), _row("12369500", "12/10/2026 06:04")]
    duplicate, _transport, _store = _run(
        tmp_path / "duplicate", duplicate_rows, "2026-10-12T06:55:00+08:00", "2026-10-12T06:54:00+08:00")
    duplicate_market = duplicate["market_directory"]
    assert duplicate_market["status"] == "PARTIAL"
    assert duplicate_market["rows"] == []
    assert "HKEX_MARKET_DIRECTORY_DUPLICATE_NEWS_ID" in duplicate_market["gaps"]

    rows = [_row(str(12369600 + i), "12/10/2026 06:05") for i in range(101)]
    missing, _transport, _store = _run(
        tmp_path / "missing", rows, "2026-10-12T06:55:00+08:00", "2026-10-12T06:54:00+08:00", truncate=True)
    missing_market = missing["market_directory"]
    assert missing_market["status"] == "PARTIAL"
    assert missing_market["directory_exhaustion"] == "UNVERIFIED"
    assert "HKEX_MARKET_DIRECTORY_PAGE_SIZE_OR_COMPLETENESS_MISMATCH" in missing_market["gaps"]
    assert missing_market["captured_row_count"] == 0

    transport_error, _transport, _store = _run(
        tmp_path / "transport", rows, "2026-10-12T06:55:00+08:00", "2026-10-12T06:54:00+08:00", raise_error=True)
    error_market = transport_error["market_directory"]
    assert error_market["status"] == "PARTIAL"
    assert error_market["directory_exhaustion"] == "UNVERIFIED"
    assert error_market["pages"][0]["source_ref"] is None


def test_fallback_window_uses_friday_close_for_monday_preopen(monkeypatch):
    from v4.manager_research import announcement_autorun, workspace_announcements

    actual = {
        "targeted_source_window": {
            "start": "2026-10-09T16:00:00+08:00",
            "source_dates": ["20261009", "20261012"],
        }
    }
    monkeypatch.setattr(workspace_announcements, "_targeted_hkex_context", lambda *_args, **_kwargs: (actual, {}))
    start, mode, from_date = _official_market_window(
        object(), "20261012", {"research_cutoff": "2026-10-12T06:55:00+08:00"}, {"runs": {}})

    assert start == "2026-10-09T16:00:00+08:00"
    assert mode == "FALLBACK_PREVIOUS_HK_SESSION_CLOSE"
    assert from_date == "20261009"
    assert start <= "2026-10-12T06:55:00+08:00"


def test_future_plan_night_window_ends_at_actual_cutoff_then_resumes_next_preopen(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from v4.manager_research import announcement_autorun, workspace_announcements
    from v4.manager_research import announcement_source

    target13_night = {
        "targeted_source_window": {
            "start": "2026-10-12T16:10:00+08:00",
            "source_dates": ["20261012", "20261013"],
        }
    }
    monkeypatch.setattr(workspace_announcements, "_targeted_hkex_context",
                        lambda *_args, **_kwargs: (target13_night, {}))
    night_start, night_mode, night_from = _official_market_window(
        object(), "20261013", {"research_cutoff": "2026-10-12T23:00:00+08:00"}, {"runs": {}})
    assert (night_start, night_mode, night_from) == (
        "2026-10-12T16:10:00+08:00", "FALLBACK_PREVIOUS_HK_SESSION_CLOSE", "20261012")

    night_rows = [_row("12369700", "12/10/2026 20:00", code="09999")]
    night, _transport, _store = _run(
        tmp_path / "night", night_rows, "2026-10-12T23:00:00+08:00", "2026-10-12T22:59:00+08:00",
        target_date="20261013", from_date=night_from, publication_start=night_start)
    assert [row["news_id"] for row in night["market_pending_documents"]] == ["12369700"]
    assert night["market_directory"]["to_date"] == "20261012"

    previous = {
        "generated_at": "2026-10-12T23:00:00+08:00",
        "market_directory": {
            "status": "COMPLETE",
            "directory_exhaustion": "VERIFIED",
            "query_cutoff": "2026-10-12T23:00:00+08:00",
        },
    }
    monkeypatch.setattr(announcement_autorun, "_ordered_products", lambda *_args: [previous])
    monkeypatch.setattr(workspace_announcements, "_check_sources", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(announcement_source, "verify_official_market_directory", lambda *_args, **_kwargs: True)
    morning_start, morning_mode, morning_from = _official_market_window(
        SimpleNamespace(_material_store=object()), "20261013",
        {"research_cutoff": "2026-10-13T06:55:00+08:00"}, {"runs": {"night-run": {}}})
    assert (morning_start, morning_mode, morning_from) == (
        "2026-10-12T22:59:00+08:00", "LAST_TRUSTED_COMPLETE_CURSOR_MINUS_1M", "20261012")
    morning_rows = [
        _row("12369701", "13/10/2026 06:05"),
        _row("12369700", "12/10/2026 20:00", code="09999"),
    ]
    morning, _transport, _store = _run(
        tmp_path / "morning", morning_rows, "2026-10-13T06:55:00+08:00", "2026-10-13T06:54:00+08:00",
        target_date="20261013", from_date=morning_from, publication_start=morning_start)
    assert [row["news_id"] for row in morning["market_pending_documents"]] == ["12369701"]
    assert morning["market_directory"]["to_date"] == "20261013"


def test_scheduled_retry_keeps_daily_row_reuses_success_and_exposes_original_refs(tmp_path, monkeypatch):
    from v4.manager_research import workspace_announcements
    from v4.manager_research import announcement_autorun

    now={"value":"2026-10-12T06:55:00+08:00"}
    monkeypatch.setattr(workspace_announcements,"_now",lambda:now["value"])
    master=tmp_path/"master"
    publish_hk_security_master(master,trade_date="20261009",
        rows=[dict(code="HK.02665",name="圖達通")],universe_codes_sha256="a"*64,
        captured_at="2026-10-09T16:10:00+08:00")
    state=tmp_path/"state";materials=MaterialStore(state/"materials")
    pending_urls=[HKEX_PDF.rsplit("/",1)[0]+f"/{12369260+i}.pdf" for i in range(8)]
    pending_rows=[
        _row(str(12369260+i),
             f"12/10/2026 {5+(57+i)//60:02d}:{(57+i)%60:02d}",code="09999",url=pending_urls[i])
        for i in range(8)
    ]
    rows=[_row(TARGET_ID,"12/10/2026 06:05"),*pending_rows]
    body_urls={HKEX_PDF,*pending_urls}
    transport=_MarketTransport(rows,"2026-10-12T06:54:00+08:00",pdf_status_by_url={HKEX_PDF:503})
    provider=HkexOfficialProvider(transport=transport,material_store=materials)
    # The fixture isolates the full-market lane; issuer-specific transport is
    # not part of this regression. Scheduled owner, store, pagination, body
    # capture and default reader remain the actual candidate implementations.
    provider.collect_announcement_batch=lambda **_kwargs:dict(queries=[],documents=[],pending_documents=[])
    service=ManagerResearchJobService(ManagerResearchStore(state),None,provider,
        material_store=materials,workspace_security_master_root=master)

    service.refresh_announcements("20261012",schedule={"policy":"BALANCED_V1","now":now["value"]})
    first=service.get_announcements("20261012")
    attempt=service.store._read(state/"workspace_announcement_runs"/"20261012"/"latest.json")
    assert attempt["input_coverage"]["market_directory"]["directory_exhaustion"]=="VERIFIED"
    assert attempt["state"]=="PARTIAL"  # fixture omits the selected issuer query
    assert "OFFICIAL_DIRECTORY_EXHAUSTION_UNVERIFIED" not in attempt["failure_reasons"]
    assert "ANNOUNCEMENT_BATCH_INCOMPLETE" in attempt["failure_reasons"]
    failed=next(row for row in first["official_documents"] if row["news_id"]==TARGET_ID)
    first_state=service.store._read(state/"workspace_announcements"/"20261012"/"autorun.json")
    first_products=announcement_autorun._ordered_products(
        service,"20261012",announcement_autorun._valid_state(first_state,"20261012"))
    assert len(first_products[-1]["market_pending_documents"])==5
    retry_queue=announcement_autorun._market_body_retry_queue(service,first_products)
    scheduled_ids=[doc["news_id"] for doc in retry_queue[:4]]
    assert TARGET_ID in scheduled_ids
    assert len([news_id for news_id in scheduled_ids if news_id!=TARGET_ID])==3
    first_directory=failed["first_directory_ref"]
    assert failed["published_at"]=="2026-10-12T06:05+08:00"
    assert failed["body_status"]=="BODY_FETCH_FAILED"
    assert failed["document_sha256"] is None
    assert failed["semantic_status"]=="NOT_REVIEWED"

    now["value"]="2026-10-12T07:02:00+08:00"
    transport.retrieved_at="2026-10-12T07:01:30+08:00";transport.pdf_status_by_url[HKEX_PDF]=200
    service.refresh_announcements("20261012",schedule={"policy":"BALANCED_V1","now":now["value"]})
    second=service.get_announcements("20261012")
    captured=next(row for row in second["official_documents"] if row["news_id"]==TARGET_ID)
    assert captured["body_status"]=="BODY_CAPTURED_UNASSESSED"
    assert captured["document_sha256"]
    assert captured["published_at"]==failed["published_at"]
    assert captured["first_directory_ref"]==first_directory
    assert captured["directory_ref"]["retrieved_at"]=="2026-10-12T07:01:30+08:00"
    assert captured["body_observed_at"]=="2026-10-12T07:01:30+08:00"
    assert captured["late_acquisition"] is True
    body_refs=[ref for ref in captured["source_refs"] if ref.get("request",{}).get("url")==HKEX_PDF]
    assert len(body_refs)==2
    assert body_refs[0]["request"]==dict(url=HKEX_PDF,method="GET")
    assert body_refs[1]["request"]["retry_identity"]=="2026-10-12T07:02:00+08:00"
    assert body_refs[1]["request"]["news_id"]==TARGET_ID


    assert len([url for url,_method in transport.calls if url in body_urls])==8
    assert sum(url==HKEX_PDF for url,_method in transport.calls)==2

    now["value"]="2026-10-12T07:05:00+08:00"
    transport.retrieved_at="2026-10-12T07:04:30+08:00"
    service.refresh_announcements("20261012",schedule={"policy":"BALANCED_V1","now":now["value"]})
    third=service.get_announcements("20261012")
    retained=next(row for row in third["official_documents"] if row["news_id"]==TARGET_ID)
    assert retained["body_status"]=="BODY_CAPTURED_UNASSESSED"
    assert retained["first_directory_ref"]==first_directory
    assert retained["body_observed_at"]=="2026-10-12T07:01:30+08:00"
    assert sum(url==HKEX_PDF for url,_method in transport.calls)==2
    assert all(value is expected for key,expected in FLAGS.items() for value in [retained[key]])

    app=FastAPI();app.include_router(create_manager_research_router(service))
    async def get_daily():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            return await client.get("/api/v4/manager/research/announcements?date=20261012")
    response=asyncio.run(get_daily())
    assert response.status_code==200
    api_row=next(row for row in response.json()["official_documents"] if row["news_id"]==TARGET_ID)
    assert api_row["body_status"]=="BODY_CAPTURED_UNASSESSED"
    assert api_row["document_sha256"]==retained["document_sha256"]
    assert api_row["first_directory_ref"]==first_directory


def test_bound_preopen_hook_uses_existing_scheduled_full_market_owner(tmp_path, monkeypatch):
    from v4.manager_research import announcement_autorun, plan_owner_dispatch, workspace_announcements

    now_text = "2026-10-12T09:27:30+08:00"
    now = datetime.fromisoformat(now_text)
    monkeypatch.setattr(plan_owner_dispatch, "clock_now", lambda: now)
    monkeypatch.setattr(workspace_announcements, "_now", lambda: now_text)

    master = tmp_path / "master"
    publish_hk_security_master(
        master, trade_date="20261009",
        rows=[dict(code="HK.00001", name="Fixture Company")],
        universe_codes_sha256="a" * 64, captured_at="2026-10-09T16:10:00+08:00",
    )
    url = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/00001-fixture.pdf"
    rows = [_row("9988776655", "12/10/2026 06:05", code="00001", url=url, title="Fixture notice")]
    transport = _MarketTransport(rows, "2026-10-12T09:27:00+08:00")
    materials = MaterialStore(tmp_path / "state" / "materials")
    provider = HkexOfficialProvider(transport=transport, material_store=materials)
    provider.collect_announcement_batch = lambda **_kwargs: {
        "queries": [], "documents": [], "pending_documents": [],
    }
    state = tmp_path / "state"
    service = ManagerResearchJobService(
        ManagerResearchStore(state), None, provider,
        material_store=materials, workspace_security_master_root=master,
    )
    binding = {
        "policy": "BALANCED_V1", "priority_codes": [],
        "preopen_plan": {"enabled": True, "lead_seconds": 180, "status": "PROPOSAL_ONLY"},
    }
    identity = {
        "source_trade_date": "20261012", "target_trade_date": "20261012",
        "branch": "PREOPEN", "binding_sha256": "b" * 64, "trigger_id": "c" * 64,
    }

    result = plan_owner_dispatch._refresh_bound_hkex_announcements(
        service, binding, identity, daily_mode=False,
    )

    assert result["capture_target_date"] == "20261012"
    assert result["plan_target_date"] == "20261012"
    assert result["owner_execution_status"] == "OWNER_RESPONSE_RECEIVED"
    attempt = service.store._read(state / "workspace_announcement_runs" / "20261012" / "latest.json")
    assert attempt["execution_kind"] == "SCHEDULED_REFRESH"
    assert attempt["execution_identity"] == {
        "source_trade_date": "20261012", "plan_target_date": "20261012",
        "plan_branch": "PREOPEN", "plan_trigger_id": "c" * 64,
        "plan_binding_sha256": "b" * 64,
    }
    assert attempt["input_coverage"]["market_directory"]["directory_exhaustion"] == "VERIFIED"
    products = announcement_autorun._ordered_products(
        service, "20261012", announcement_autorun._valid_state(
            service.store._read(state / "workspace_announcements" / "20261012" / "autorun.json"),
            "20261012",
        ),
    )
    market = products[-1]["market_directory"]
    assert market["status"] == "COMPLETE"
    assert [row["news_id"] for row in market["rows"]] == ["9988776655"]
    assert products[-1]["market_documents"][0]["body_status"] == "BODY_CAPTURED_UNASSESSED"
    directory_calls = [
        url for url, _method in transport.calls if "titleSearchServlet.do" in url
    ]
    assert directory_calls
    assert all(parse_qs(urlsplit(url).query, keep_blank_values=True).get("stockId") == [""]
               for url in directory_calls)
    assert service.get_announcements("20261012")["status"] == "PARTIAL"
    service.close()
