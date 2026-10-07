from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from infrastructure.data_store import _sha256
from infrastructure.review_store import ReviewStore


def _reference(trade_date: str) -> dict:
    return {
        "schema_version": "v3_5.close_review_reference.v1",
        "trade_date": trade_date,
        "status": "MODEL_REVIEW_READY",
        "models": {},
        "stages": {},
        "stage_union": {},
        "kpi": {},
        "row_counts": {},
        "close_top20": [],
        "model_rows": [],
        "stage_rows": [],
        "top20_attribution": [],
        "missing_stages": [],
        "cannot_confirm": [],
        "reference_snapshot": True,
        "write_policy": "review_only_read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _hk_review(client: TestClient, trade_date: str) -> dict:
    response = client.get("/api/v3/review", params={"date": trade_date})
    assert response.status_code == 200
    return response.json()["market_reviews"]["HK"]


def test_hk_close_calendar_skips_holiday_and_fails_closed_for_missing_or_unknown(tmp_path, monkeypatch):
    root = tmp_path / "default"
    monkeypatch.delenv("V35_REVIEW_CORE_CLOSE_ROOT", raising=False)

    holiday = _hk_review(TestClient(create_app(data_root=root)), "20261001")
    holiday_review = holiday["model_selection_review"]
    assert holiday["status"] == "NON_TRADING_DAY"
    assert holiday_review["status"] == "NON_TRADING_DAY"
    assert holiday["calendar"] == {
        "market": "HK_SECURITIES",
        "state": "NON_TRADING_DAY",
        "source": "HK_SECURITIES_TRADING_CALENDAR",
    }
    assert holiday_review["row_counts"] == {}
    assert holiday_review["close_top20"] == []

    missing = _hk_review(TestClient(create_app(data_root=root)), "20261002")
    missing_review = missing["model_selection_review"]
    assert missing["status"] == "CANNOT_CONFIRM"
    assert missing_review["status"] == "CANNOT_CONFIRM"
    assert missing_review["cannot_confirm"] == ["CLOSE_REVIEW_ARTIFACT_MISSING"]
    assert missing_review["calendar"]["state"] == "FULL_TRADING_DAY"
    assert missing_review["close_top20"] == []

    unknown = _hk_review(TestClient(create_app(data_root=root)), "20270102")
    unknown_review = unknown["model_selection_review"]
    assert unknown["status"] == "CANNOT_CONFIRM"
    assert unknown_review["cannot_confirm"] == ["HK_SECURITIES_CALENDAR_UNKNOWN"]
    assert unknown_review["calendar"]["state"] == "UNKNOWN"


def test_create_app_uses_explicit_hk_root_then_preserves_default_and_never_falls_back(tmp_path, monkeypatch):
    default_root = tmp_path / "default"
    explicit_root = tmp_path / "explicit"
    default_ref = _reference("20260911")
    explicit_ref = _reference("20260911")
    explicit_ref["row_counts"] = {"candidate_marker": 9}
    ReviewStore(default_root).import_reference(default_ref)
    ReviewStore(explicit_root).import_reference(explicit_ref)

    monkeypatch.setenv("V35_REVIEW_CORE_CLOSE_ROOT", str(explicit_root))
    explicit = _hk_review(TestClient(create_app(data_root=default_root)), "20260911")
    assert explicit["model_selection_review"]["artifact_sha256"] == _sha256(explicit_ref)

    monkeypatch.delenv("V35_REVIEW_CORE_CLOSE_ROOT", raising=False)
    default = _hk_review(TestClient(create_app(data_root=default_root)), "20260911")
    assert default["model_selection_review"]["artifact_sha256"] == _sha256(default_ref)

    monkeypatch.setenv("V35_REVIEW_CORE_CLOSE_ROOT", str(tmp_path / "missing-explicit"))
    missing = _hk_review(TestClient(create_app(data_root=default_root)), "20260911")
    assert missing["status"] == "CANNOT_CONFIRM"
    assert missing["model_selection_review"]["cannot_confirm"] == ["CLOSE_REVIEW_ARTIFACT_MISSING"]
