"""Manager lifecycle hardening regressions (audit F04/F06/F09/F10/F14).

Self-contained versions of the independent audit probes R05/R06/R09/R10/
R11/R12: symlinked write roots are rejected, tampered exact caches are
never READY, cross-instance conflicting writes fail closed, a failed
receipt keeps READY unobservable, and a cancel wins over a late publish.
(F08 event-vs-financial ordering is covered on this base by
``tests/optimization/test_manager_transactions.py::
test_event_refresh_merges_into_latest_financial_product``.)
"""
from __future__ import annotations

import json
import time
from typing import Any

import pytest

from infrastructure.data_store import NativeDataStore
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore, StoreConflict, StoreError


def _fact() -> dict[str, Any]:
    return {
        "statement_cn": "财务表：收入 120；上期 100。",
        "fact_kind": "financial",
        "locator": "PDF page 1",
        "page": 1,
        "source_excerpt": "Revenue 120; prior period 100.",
        "fields": {
            "label": "Revenue",
            "label_cn": "收入",
            "period_label": "Year ended December 31, 2026",
            "currency": "HKD",
            "unit": "million",
            "values": [{"column": "2026", "raw": "120"}, {"column": "2025", "raw": "100"}],
        },
    }


def _observation() -> dict[str, Any]:
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


def _collect_result() -> dict[str, Any]:
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
        "facts": [_fact()],
    }


def _event_batch(code: str) -> dict[str, Any]:
    event = {
        "event_id": "event-1",
        "event_type": "COOPERATION",
        "source_kind": "MEDIA",
        "source_id": "media-fixture",
        "evidence_level": "MEDIA",
        "official_confirmation_status": "PENDING",
        "code": code,
        "name": "海光芯正",
        "counterparty": "格罗方德",
        "catalyst": "推进6.4T NPO工程落地与规模化量产",
        "why_might_affect_business": "可能影响产品和制造推进；报道不等于已量产。",
        "realization_conditions": ["官方确认合作范围"],
        "financial_counterevidence": ["订单与收入未确认"],
        "market_confirmation_gap": ["MEDIA_ONLY_OFFICIAL_CONFIRMATION_PENDING"],
        "source_url": "https://example.invalid/news-1",
        "publisher_timestamp": "2026-09-08T08:45:00+08:00",
        "first_seen_at": "2026-09-08T09:00:00+08:00",
    }
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
        "current_event_as_of": "2026-09-08T10:00:00+08:00",
        "market_confirmation_gap": event["market_confirmation_gap"],
    }
    return {
        "schema_version": "v4.manager_research.catalyst_result.v1",
        "status": "READY",
        "rows": {code: row},
        "source_counts": [{"source_id": "media-fixture", "status": "READY"}],
        "coverage": {"event_count": 1, "current_event_count": 1, "historical_event_count": 0, "completeness": "BOUNDED_SOURCES_ONLY"},
        "current_event_as_of": "2026-09-08T10:00:00+08:00",
    }


class _Provider:
    provider_id = "fixture-provider"

    def __init__(self) -> None:
        self.collect_calls = 0

    def collect(self, **_: Any) -> dict[str, Any]:
        self.collect_calls += 1
        return _collect_result()

    def collect_events(self, **kwargs: Any) -> dict[str, Any]:
        return _event_batch(str(kwargs["observations"][0]["code"]))


def _wait_terminal(service: ManagerResearchJobService, job_id: str, date: str) -> dict[str, Any]:
    for _ in range(200):
        job = service.job(job_id, date)
        assert job is not None
        if job.get("status") not in {"QUEUED", "RUNNING"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def _service(tmp_path: Any) -> tuple[ManagerResearchJobService, dict[str, Any]]:
    raw_input = {
        "target_trade_date": "20260908",
        "stage_id": "STAGE_0935_0940",
        "market": "HK_CONNECT",
        "status": "READY",
        "rows": [_observation()],
    }
    service = ManagerResearchJobService(
        ManagerResearchStore(tmp_path),
        lambda _date: raw_input,
        _Provider(),
        row_timeout_seconds=2,
    )
    return service, raw_input


# ---------------------------------------------------------------------------
# F04: symlinked write roots are rejected
# ---------------------------------------------------------------------------


def test_native_store_rejects_symlinked_component(tmp_path: Any) -> None:
    root = tmp_path / "data"
    (root / "receipts").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "evil").symlink_to(outside, target_is_directory=True)
    store = NativeDataStore(root)

    # The dir-fd boundary refuses to traverse the symlinked component
    # (ValueError from the path guard, NotADirectoryError from O_NOFOLLOW).
    with pytest.raises((ValueError, OSError)):
        store._write("evil/x.json", {"a": 1})
    assert not (outside / "x.json").exists()
    with pytest.raises((ValueError, OSError)):
        store._read("evil/x.json")


def test_manager_store_rejects_symlinked_date_dir(tmp_path: Any) -> None:
    store = ManagerResearchStore(tmp_path / "manager")
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.products_root / "20260908").symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError, StoreError)):
        store.write_product({"target_trade_date": "20260908", "input_identity": "abc", "status": "READY"})
    assert not list(outside.glob("*.json"))


def test_manager_store_rejects_symlinked_receipts_dir(tmp_path: Any) -> None:
    store = ManagerResearchStore(tmp_path / "manager")
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.receipts_root / "20260908").symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError, StoreError)):
        store.write_receipt("20260908", "job-1", {"status": "READY"})
    assert not list(outside.glob("*.json"))


# ---------------------------------------------------------------------------
# F06/F03: a tampered exact cache is never READY
# ---------------------------------------------------------------------------


def test_tampered_exact_cache_is_never_ready(tmp_path: Any) -> None:
    service, raw_input = _service(tmp_path)
    try:
        input_data = service._read_input("20260908")
        product = ManagerResearchJobService._build_product(
            input_data,
            [_observation()],
            {"HK.01191": _collect_result()},
        )
        service.store.write_product(product)
        path = service.store._product_path("20260908", input_data["input_identity"])
        tampered = json.loads(path.read_text(encoding="utf-8"))
        tampered["target_trade_date"] = "20260907"
        service.store._write_atomic(path, tampered)

        envelope = service.get("20260908")

        assert envelope["status"] != "READY"
        assert envelope["product"] is None
        assert envelope["status"] in {"NOT_MATERIALIZED", "CANNOT_CONFIRM"}
    finally:
        service.close()


# ---------------------------------------------------------------------------
# F07: cross-instance conflicting writes fail closed
# ---------------------------------------------------------------------------


def test_cross_instance_conflicting_product_write_fails_closed(tmp_path: Any) -> None:

    first_store = ManagerResearchStore(tmp_path)
    second_store = ManagerResearchStore(tmp_path)
    base = {"target_trade_date": "20260908", "input_identity": "same", "status": "READY"}
    first_store.write_product({**base, "marker": "A"})
    with pytest.raises(StoreConflict):
        second_store.write_product({**base, "marker": "B"})
    assert first_store.read_product("20260908", "same")["marker"] == "A"
    second_store.write_product({**base, "marker": "A"})  # same bytes stay idempotent


# ---------------------------------------------------------------------------
# F09: a failed receipt write keeps READY unobservable
# ---------------------------------------------------------------------------


def test_receipt_failure_keeps_product_out_of_ready(tmp_path: Any, monkeypatch: Any) -> None:
    service, _raw = _service(tmp_path)
    try:
        def boom(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(service.store, "write_receipt", boom)
        queued = service.ensure("20260908")
        job_id = queued["job"]["job_id"]
        terminal = _wait_terminal(service, job_id, "20260908")
        assert terminal["status"] == "FAILED"
        envelope = service.get("20260908")
        assert envelope["status"] != "READY"
        assert envelope["product"] is None
    finally:
        service.close()


# ---------------------------------------------------------------------------
# F10: a cancel that lands before publish is sustained
# ---------------------------------------------------------------------------


def test_cancel_before_publish_is_sustained(tmp_path: Any, monkeypatch: Any) -> None:
    service, _raw = _service(tmp_path)
    try:
        original_build = ManagerResearchJobService._build_product

        def build_then_cancel(input_data, observations, results, *, event_batch=None):
            product = original_build(input_data, observations, results, event_batch=event_batch)
            service.cancel(
                service._job_id(input_data),
                str(input_data["target_trade_date"]),
            )
            return product

        monkeypatch.setattr(ManagerResearchJobService, "_build_product", staticmethod(build_then_cancel))
        queued = service.ensure("20260908")
        job_id = queued["job"]["job_id"]
        terminal = _wait_terminal(service, job_id, "20260908")
        assert terminal["status"] == "CANCELLED"
        envelope = service.get("20260908")
        assert envelope["status"] != "READY"
        assert envelope["product"] is None
    finally:
        service.close()


# ---------------------------------------------------------------------------
# F08 event-vs-financial ordering: covered by
# tests/optimization/test_manager_transactions.py::
# test_event_refresh_merges_into_latest_financial_product.
