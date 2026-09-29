from __future__ import annotations

import time
from typing import Any

from v4.manager_research.contracts import cutoff_at
from v4.manager_research.service import ManagerResearchJobService, _financial_counterevidence_for_row
from v4.manager_research.store import ManagerResearchStore


def fact(label: str = "Revenue") -> dict[str, Any]:
    return {
        "statement_cn": "财务表：收入 120；上期 100。",
        "fact_kind": "financial",
        "locator": "PDF page 1",
        "page": 1,
        "source_excerpt": "Revenue 120; prior period 100.",
        "fields": {
            "label": label,
            "label_cn": "收入" if label == "Revenue" else label,
            "period_label": "Year ended December 31, 2026",
            "currency": "HKD",
            "unit": "million",
            "values": [{"column": "2026", "raw": "120"}, {"column": "2025", "raw": "100"}],
        },
    }


def observation() -> dict[str, Any]:
    return {
        "code": "HK.01191",
        "name": "海光芯正",
        "stage_rank": 1,
        "status": "READY",
        "stage_id": "STAGE_0935_0940",
        "source_last_bar_time": "2026-09-08 09:40:00",
        "last_price": 10,
        "support_price": 9,
        "pressure_price": 11,
        "volume": 100,
        "volume_ratio": 1.2,
        "formal_eligible": False,
    }


def wait_terminal(service: ManagerResearchJobService, job_id: str, date: str) -> dict[str, Any]:
    for _ in range(100):
        job = service.job(job_id, date)
        assert job is not None
        if job.get("status") not in {"QUEUED", "RUNNING"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


class Provider:
    provider_id = "fixture-provider"

    def __init__(self) -> None:
        self.collect_calls = 0
        self.event_calls = 0

    def collect(self, **_: Any) -> dict[str, Any]:
        self.collect_calls += 1
        return {
            "status": "READY",
            "reason": "OFFICIAL_PDF_FACTS_EXTRACTED",
            "issuer": "海光芯正",
            "source": {
                "url": "https://www.hkexnews.hk/fixture.pdf",
                "sha256": "a" * 64,
                "published_at": "2026-09-08T08:30:00+08:00",
                "retrieved_at": "2026-09-08T10:00:00+08:00",
            },
            "facts": [fact("Revenue"), fact("Profit for the period")],
        }

    def collect_events(self, **kwargs: Any) -> dict[str, Any]:
        self.event_calls += 1
        observation_rows = kwargs["observations"]
        event = {
            "event_id": f"event-{self.event_calls}",
            "event_type": "COOPERATION",
            "source_kind": "MEDIA",
            "source_id": "media-fixture",
            "evidence_level": "MEDIA",
            "official_confirmation_status": "PENDING",
            "code": "HK.01191",
            "name": "海光芯正",
            "counterparty": "格罗方德",
            "catalyst": "推进6.4T NPO工程落地与规模化量产",
            "why_might_affect_business": "可能影响产品和制造推进；报道不等于已量产。",
            "realization_conditions": ["官方确认合作范围", "观察订单或交付"],
            "financial_counterevidence": ["订单与收入未确认"],
            "market_confirmation_gap": ["MEDIA_ONLY_OFFICIAL_CONFIRMATION_PENDING"],
            "publisher_timestamp": "2026-09-08T13:18:14+08:00",
            "reported_event_date_text": "9月7日",
            "first_seen_at": "2026-09-08T10:00:00+00:00",
            "source_url": "http://www.iccsz.com/article.html",
            "body_parsed": True,
            "as_of_bucket": "current",
        }
        code = observation_rows[0]["code"]
        row = {
            "status": "READY",
            "reason": "EVENT_BODY_PARSED",
            "events": [event],
            "historical_events": [],
            "current_events": [event],
            "catalyst_advice": {
                "status": "OBSERVE",
                "label": "催化观察",
                "priority_rank": 1,
                "priority_reason": "当前有界事件保留为观察。",
                "summary": "官方确认待补。",
            },
            "source_coverage": [{"source_id": "media-fixture", "status": "READY"}],
            "source_receipts": [{"source_id": "media-fixture", "url": event["source_url"]}],
            "coverage": {"current_event_count": 1, "historical_event_count": 0, "completeness": "BOUNDED_SOURCES_ONLY"},
            "current_event_as_of": kwargs.get("current_event_as_of"),
            "market_confirmation_gap": event["market_confirmation_gap"],
        }
        return {
            "schema_version": "v4.manager_research.catalyst_result.v1",
            "status": "READY",
            "rows": {code: row},
            "source_counts": [{"source_id": "media-fixture", "status": "READY"}],
            "coverage": {"event_count": 1, "current_event_count": 1, "historical_event_count": 0, "completeness": "BOUNDED_SOURCES_ONLY"},
            "current_event_as_of": kwargs.get("current_event_as_of"),
        }


class FailedEventProvider(Provider):
    def collect_events(self, **kwargs: Any) -> dict[str, Any]:
        code = kwargs["observations"][0]["code"]
        return {
            "schema_version": "v4.manager_research.catalyst_result.v1",
            "status": "CANNOT_CONFIRM",
            "reason": "ALL_EVENT_SOURCES_FAILED",
            "rows": {
                code: {
                    "status": "CANNOT_CONFIRM",
                    "reason": "MEDIA_DIRECTORY_FAILED;HKEX_EVENT_DIRECTORY_FAILED",
                    "events": [],
                    "source_receipts": [],
                    "source_coverage": [],
                    "coverage": {"event_count": 0, "status": "CANNOT_CONFIRM"},
                    "market_confirmation_gap": ["EVENT_SOURCES_FAILED"],
                }
            },
            "source_counts": [
                {"source_id": "media", "status": "CANNOT_CONFIRM"},
                {"source_id": "hkex", "status": "CANNOT_CONFIRM"},
            ],
            "coverage": {
                "event_count": 0,
                "status": "CANNOT_CONFIRM",
                "all_sources_failed": True,
            },
            "current_event_as_of": kwargs.get("current_event_as_of"),
        }


def test_initial_product_and_event_refresh_preserve_financial_facts(tmp_path: Any) -> None:
    raw_input = {
        "target_trade_date": "20260908",
        "stage_id": "STAGE_0935_0940",
        "market": "HK_CONNECT",
        "status": "READY",
        "rows": [observation()],
    }
    provider = Provider()
    service = ManagerResearchJobService(
        ManagerResearchStore(tmp_path),
        lambda _date: raw_input,
        provider,
        row_timeout_seconds=2,
    )
    try:
        queued = service.ensure("20260908")
        job_id = queued["job"]["job_id"]
        terminal = wait_terminal(service, job_id, "20260908")
        assert terminal["status"] == "READY"
        first = service.get("20260908")["product"]
        assert first is not None
        assert provider.collect_calls == 1
        assert provider.event_calls == 1
        assert first["rows"][0]["catalyst_result"]["events"][0]["catalyst"].startswith("推进")
        facts_before = first["rows"][0]["facts"]
        finance_receipts_before = first["source_receipts"]

        refresh = service.ensure_events("20260908", force=True)
        event_job_id = refresh["job"]["job_id"]
        event_terminal = wait_terminal(service, event_job_id, "20260908")
        assert event_terminal["status"] == "READY"
        after = service.get("20260908")["product"]
        assert after is not None
        assert provider.collect_calls == 1, "event refresh must not recollect financial PDFs"
        assert provider.event_calls == 2
        assert after["rows"][0]["facts"] == facts_before
        assert after["source_receipts"] == finance_receipts_before
        assert after["catalyst_source_receipts"]
        receipt = service.store.read_receipt("20260908", event_job_id)
        assert receipt is not None
        assert receipt["financial_recollection"] is False
    finally:
        service.close()


def test_event_refresh_source_outage_stays_cannot_confirm_and_never_ready(tmp_path: Any) -> None:
    raw_input = {
        "target_trade_date": "20260908",
        "stage_id": "STAGE_0935_0940",
        "market": "HK_CONNECT",
        "status": "READY",
        "rows": [observation()],
    }
    provider = FailedEventProvider()
    service = ManagerResearchJobService(
        ManagerResearchStore(tmp_path),
        lambda _date: raw_input,
        provider,
        row_timeout_seconds=2,
    )
    try:
        initial = service.ensure("20260908")
        terminal = wait_terminal(service, initial["job"]["job_id"], "20260908")
        assert terminal["status"] == "READY"
        # The financial product is still attached so the event refresh can be
        # tested independently of financial collection.
        product = service.get("20260908")["product"]
        assert product is not None
        refresh = service.ensure_events("20260908", force=True)
        event_terminal = wait_terminal(service, refresh["job"]["job_id"], "20260908")
        assert event_terminal["status"] == "CANNOT_CONFIRM"
        assert event_terminal["progress"]["event_rows"] == 0
        after = service.get("20260908")["product"]
        assert after is not None
        assert after["catalyst_status"] == "CANNOT_CONFIRM"
        assert after["catalyst_coverage"]["event_count"] == 0
        assert after["rows"][0]["catalyst_result"]["status"] == "CANNOT_CONFIRM"
    finally:
        service.close()


def test_catalyst_financial_counterevidence_reuses_cached_facts_without_collection() -> None:
    loss = fact("LOSS FOR THE PERIOD")
    loss["fields"]["label_cn"] = "期内亏损"
    loss["fields"]["values"] = [{"column": "2026", "raw": "(118,269)"}, {"column": "2025", "raw": "(34,850)"}]
    cash = fact("Net cash flows used in operating activities")
    cash["fields"]["label_cn"] = "经营活动使用的现金净额"
    cash["fields"]["values"] = [{"column": "2026", "raw": "(73,392)"}, {"column": "2025", "raw": "(17,965)"}]
    source = {"sha256": "b" * 64, "published_at": "2026-08-28T18:59:00+08:00"}
    result = _financial_counterevidence_for_row(
        {
            "facts": [loss, cash],
            "source": source,
            "observation": {"code": "HK.01191", "name": "海光芯正"},
            "source_status": "READY",
            "observation_timing_status": "CURRENT_AFTER_CUTOFF",
        }
    )
    assert any("PROFIT_LOSS" in item and "(118,269)" in item and "(34,850)" in item for item in result["financial_counterevidence"])
    assert any("OPERATING_CASHFLOW" in item and "(73,392)" in item and "(17,965)" in item for item in result["financial_counterevidence"])
    assert result["financial_re_evaluation"]["financial_collection_calls"] == 0
    assert result["financial_re_evaluation"]["from_cached_facts"] is True
    assert {item["dimension"] for item in result["financial_counterevidence_refs"]} == {"PROFIT_LOSS", "OPERATING_CASHFLOW"}
    assert all(ref["fact_refs"][0]["source_sha256"] == "b" * 64 for ref in result["financial_counterevidence_refs"])
