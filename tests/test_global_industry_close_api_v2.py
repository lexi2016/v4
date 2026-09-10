"""Focused consumer checks for the controlled-late US close projection."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from apps.api.v35_api.research_lane_router import (
    GLOBAL_INDUSTRY_MAPPING_VERSION,
    GLOBAL_INDUSTRY_SCHEMA_VERSION,
    MARKET_SNAPSHOT_SCHEMA_VERSION,
    _global_industry_missing,
    _project_global_industries,
    _verifiable_market_snapshot_dates,
)
from infrastructure.research_peripheral_store import (
    CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP,
)


TARGET_DATE = "20260909"
SESSION_DATE = "20260908"
LATE_MODE = "CONTROLLED_LATE_POST_CLOSE"
LATE_REASON = "NATURAL_SLOT_MISSED_CONTROLLED_RECOVERY"


class _FakeStore:
    def __init__(self, root: Path, payload: dict) -> None:
        self.root = root
        self.payload = payload

    def read_exact(self, trade_date: str, source: str) -> dict:
        assert (trade_date, source) == (TARGET_DATE, "external_finance")
        return deepcopy(self.payload)


class _DateListStore:
    def __init__(self, payloads: dict[str, dict | None], root: Path) -> None:
        self.payloads = payloads
        self.root = root

    def list_dates(self, source: str) -> list[str]:
        assert source == "external_finance"
        return list(self.payloads)

    def read_exact(self, trade_date: str, source: str) -> dict | None:
        assert source == "external_finance"
        payload = self.payloads.get(trade_date)
        return deepcopy(payload)


def _rows() -> list[dict]:
    rows = []
    for index, mapping in enumerate(CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP):
        rows.append(
            {
                "label": mapping["label"],
                "group": mapping["group"],
                "mapping_type": mapping["mapping_type"],
                "proxy_symbols": list(mapping["proxy_symbols"]),
                "available_symbols": list(mapping["proxy_symbols"]),
                "missing_symbols": [],
                "requested_symbol_count": len(mapping["proxy_symbols"]),
                "available_symbol_count": len(mapping["proxy_symbols"]),
                "coverage": {
                    "available": len(mapping["proxy_symbols"]),
                    "requested": len(mapping["proxy_symbols"]),
                },
                "coverage_pct": 100.0,
                "change_pct": float(index + 1) / 10,
                "pct_change": float(index + 1) / 10,
                "direction": "UP",
                "status": "PARTIAL",
                "quote_session_dates": [SESSION_DATE],
                "quote_session_times": ["16:15:00"],
                "cannot_confirm": [],
            }
        )
    return rows


def _capture(*, session_date: str, late: bool = True) -> dict:
    capture = {
        "us_session_date": session_date,
        "capture_phase": "POST_CLOSE",
        "capture_id": "capture-v2-1",
        "run_id": "run-v2-1",
        "capture_origin": "ORIGINAL_TIME_CAPTURE",
        "original_time_capture": True,
        "late": late,
    }
    if late:
        capture.update(
            {
                "capture_mode": LATE_MODE,
                "reason": LATE_REASON,
                "capture_reason": LATE_REASON,
            }
        )
    return capture


def _payload(*, session_date: str = SESSION_DATE, late: bool = True) -> dict:
    capture = _capture(session_date=session_date, late=late)
    snapshot = {
        "schema_version": MARKET_SNAPSHOT_SCHEMA_VERSION,
        "status": "PARTIAL",
        "source": "qt",
        "provider": "Tencent qt.gtimg.cn",
        "source_response_sha256": "",
        "capture_phase": "POST_CLOSE",
        "capture_session_date": session_date,
        "captured_at": "2026-09-08T23:50:22Z",
        "generated_at": "2026-09-08T23:50:22Z",
        "mapping_version": GLOBAL_INDUSTRY_MAPPING_VERSION,
        "requested_symbol_count": 33,
        "available_symbol_count": 33,
        "provider_session_dates": [session_date],
        "provider_session_times": ["16:15:00"],
        "quotes": [],
        "rows": _rows(),
        "cannot_confirm": ["MARKET_SNAPSHOT_INCOMPLETE"],
        "recommendation_status": "RESEARCH_ONLY",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "late": late,
    }
    if late:
        snapshot.update(
            {
                "capture_mode": LATE_MODE,
                "reason": LATE_REASON,
                "capture_reason": LATE_REASON,
            }
        )
    return {
        "trade_date": TARGET_DATE,
        "status": "CANNOT_CONFIRM" if late else "READY",
        "cannot_confirm": ["MARKET_SNAPSHOT_INCOMPLETE"] if late else [],
        "market_snapshot": snapshot,
        "us_session_captures": [capture],
        "capture_origin": "ORIGINAL_TIME_CAPTURE",
        "original_time_capture": True,
        "late": late,
        **(
            {
                "capture_mode": LATE_MODE,
                "reason": LATE_REASON,
                "capture_reason": LATE_REASON,
            }
            if late
            else {}
        ),
    }


def test_late_cross_date_projection_accepts_bound_capture_and_preserves_rows(
    tmp_path: Path,
) -> None:
    result = _project_global_industries(
        store=_FakeStore(tmp_path, _payload()), research_date=TARGET_DATE
    )

    assert result["status"] == "PARTIAL"
    assert result["target_trade_date"] == TARGET_DATE
    assert result["target_date"] == TARGET_DATE
    assert result["research_date"] == TARGET_DATE
    assert result["artifact_trade_date"] == TARGET_DATE
    assert result["source_date"] == SESSION_DATE
    assert result["us_session_date"] == SESSION_DATE
    assert result["capture_session_date"] == SESSION_DATE
    assert result["capture_phase"] == "POST_CLOSE"
    assert result["capture_id"] == "capture-v2-1"
    assert result["run_id"] == "run-v2-1"
    assert result["late"] is True
    assert result["capture_mode"] == LATE_MODE
    assert result["reason"] == LATE_REASON
    assert len(result["rows"]) == 24
    assert result["rows"][0]["change_pct"] == 0.1
    assert result["rows"][-1]["change_pct"] == 2.4
    assert result["RESEARCH_ONLY"] is True
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def test_same_date_post_close_projection_remains_compatible(tmp_path: Path) -> None:
    payload = _payload(session_date=TARGET_DATE, late=False)
    result = _project_global_industries(
        store=_FakeStore(tmp_path, payload), research_date=TARGET_DATE
    )

    assert result["status"] == "PARTIAL"
    assert result["target_trade_date"] == TARGET_DATE
    assert result["source_date"] == TARGET_DATE
    assert result["us_session_date"] == TARGET_DATE
    assert result["capture_session_date"] == TARGET_DATE
    assert result["late"] is False
    assert result["rows"][3]["change_pct"] == 0.4


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            lambda payload: payload["market_snapshot"].update(
                {"capture_id": "wrong-capture-id"}
            ),
            "MARKET_SNAPSHOT_CAPTURE_IDENTITY_AMBIGUOUS_OR_UNBOUND",
        ),
        (
            lambda payload: payload.pop("us_session_captures"),
            "MARKET_SNAPSHOT_CAPTURE_IDENTITY_UNBOUND",
        ),
        (
            lambda payload: (
                payload["market_snapshot"].update(
                    {
                        "capture_session_date": "20260907",
                        "provider_session_dates": ["20260907"],
                    }
                ),
                payload["us_session_captures"][0].update(
                    {"us_session_date": "20260907"}
                ),
            ),
            "MARKET_SNAPSHOT_CAPTURE_DATE_NOT_BOUND_TO_TARGET",
        ),
    ],
)
def test_cross_date_identity_failures_remain_cannot_confirm(
    tmp_path: Path, mutation, expected_reason: str
) -> None:
    payload = _payload()
    mutation(payload)
    result = _project_global_industries(
        store=_FakeStore(tmp_path, payload), research_date=TARGET_DATE
    )

    assert result["status"] == "CANNOT_CONFIRM"
    assert expected_reason in result["cannot_confirm"]
    assert len(result["rows"]) == 24
    assert all(row["change_pct"] is None for row in result["rows"])


def test_missing_projection_keeps_target_and_session_fields() -> None:
    result = _global_industry_missing(
        research_date=TARGET_DATE, reason="EXACT_EXTERNAL_FINANCE_NOT_MATERIALIZED"
    )

    assert result["target_trade_date"] == TARGET_DATE
    assert result["research_date"] == TARGET_DATE
    assert result["us_session_date"] == ""


def test_market_snapshot_dates_filter_generic_missing_wrong_session_and_no_source(
    tmp_path: Path,
) -> None:
    valid = _payload()
    valid["market_snapshot"]["source_response_sha256"] = "a" * 64

    generic = {"trade_date": "20260910", "cannot_confirm": []}

    missing_snapshot = _payload(session_date="20260908", late=False)
    missing_snapshot.pop("market_snapshot")

    wrong_session = _payload(session_date="20260905")
    wrong_session["market_snapshot"]["source_response_sha256"] = "b" * 64

    no_source_evidence = _payload(session_date="20260908", late=False)

    store = _DateListStore(
        {
            "20260910": generic,
            "20260909": valid,
            "20260908": missing_snapshot,
            "20260907": wrong_session,
            "20260906": no_source_evidence,
        },
        tmp_path,
    )

    dates = _verifiable_market_snapshot_dates(store)

    assert dates == ["20260909"]
    assert list(store.payloads) == [
        "20260910",
        "20260909",
        "20260908",
        "20260907",
        "20260906",
    ]
    missing_result = _project_global_industries(
        store=store, research_date="20260910"
    )
    assert missing_result["status"] == "CANNOT_CONFIRM"
    assert "MARKET_SNAPSHOT_NOT_MATERIALIZED" in missing_result["cannot_confirm"]


def test_market_snapshot_dates_keep_partial_close_with_provider_evidence(
    tmp_path: Path,
) -> None:
    partial = _payload()
    partial["market_snapshot"]["source_response_sha256"] = "c" * 64
    partial["market_snapshot"]["status"] = "PARTIAL"
    partial["market_snapshot"]["cannot_confirm"] = ["QUOTE_SESSION_TIME_MISSING"]

    dates = _verifiable_market_snapshot_dates(
        _DateListStore({"20260909": partial}, tmp_path)
    )

    assert dates == ["20260909"]
