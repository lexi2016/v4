from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from apps.api.v35_api.review_router import create_review_router
from infrastructure.review_store import ReviewStore


def _reference(trade_date: str, *, status: str = "MODEL_REVIEW_READY") -> dict:
    close_top20 = [
        {"rank": rank, "code": f"HK.{rank:05d}"}
        for rank in range(1, 21)
    ]
    return {
        "schema_version": "v3_5.close_review_reference.v1",
        "trade_date": trade_date,
        "status": status,
        "primary_kpi": "全港股通收盘涨幅Top20覆盖率",
        "models": {
            "0.2_prob_active": {
                "evidence_status": "READY" if status == "MODEL_REVIEW_READY" else "CANNOT_CONFIRM",
                "selected_count": 100 if status == "MODEL_REVIEW_READY" else 0,
                "hit_count": 15 if status == "MODEL_REVIEW_READY" else None,
            }
        },
        "stages": {},
        "stage_union": {
            "evidence_status": "READY" if status == "MODEL_REVIEW_READY" else "CANNOT_CONFIRM",
            "selected_count": 70 if status == "MODEL_REVIEW_READY" else 0,
            "hit_count": 10 if status == "MODEL_REVIEW_READY" else None,
        },
        "kpi": {},
        "row_counts": {
            "hkconnect_universe": 691,
            "close_top20": 20,
            "model_0_2": 100 if status == "MODEL_REVIEW_READY" else 0,
            "stage_rows": 70 if status == "MODEL_REVIEW_READY" else 0,
        },
        "close_top20": close_top20,
        "model_rows": [],
        "stage_rows": [],
        "top20_attribution": [],
        "missing_stages": [] if status == "MODEL_REVIEW_READY" else ["STAGE_EVIDENCE_MISSING"],
        "cannot_confirm": [] if status == "MODEL_REVIEW_READY" else ["MODEL_AND_STAGE_INPUTS_MISSING"],
        "reference_snapshot": True,
        "write_policy": "review_only_read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _review_client(data_root, *, hk_close_root=None) -> TestClient:
    app = FastAPI()
    app.include_router(create_review_router(data_root, hk_close_root=hk_close_root))
    return TestClient(app)


def _hk_review(client: TestClient, trade_date: str) -> dict:
    response = client.get("/api/v3/review", params={"date": trade_date})
    assert response.status_code == 200
    return response.json()["market_reviews"]["HK"]["model_selection_review"]


def test_explicit_hk_close_root_reads_exact_date_without_changing_default_root(tmp_path):
    default_store = ReviewStore(tmp_path / "default-data")
    close_store = ReviewStore(tmp_path / "v35-close-data")
    default_store.import_reference(_reference("20260930"))
    close_store.import_reference(_reference("20260930", status="MODEL_0_2_SOURCE_MISSING"))

    review = _hk_review(
        _review_client(default_store.root, hk_close_root=close_store.root),
        "20260930",
    )
    assert review["status"] == "MODEL_0_2_SOURCE_MISSING"
    assert review["row_counts"] == {
        "hkconnect_universe": 691,
        "close_top20": 20,
        "model_0_2": 0,
        "stage_rows": 0,
    }
    assert len(review["close_top20"]) == 20
    assert review["cannot_confirm"] == ["MODEL_AND_STAGE_INPUTS_MISSING"]

    default_review = _hk_review(_review_client(default_store.root), "20260930")
    assert default_review["status"] == "MODEL_REVIEW_READY"
    assert default_review["row_counts"]["stage_rows"] == 70


def test_hk_securities_open_while_connect_is_closed_keeps_missing_evidence_explicit(tmp_path):
    client = _review_client(tmp_path / "default-data", hk_close_root=tmp_path / "v35-close-data")

    review = _hk_review(client, "20261002")

    assert review["status"] == "CANNOT_CONFIRM"
    assert review["cannot_confirm"] == ["CLOSE_REVIEW_ARTIFACT_MISSING"]
    assert review["calendar"] == {"market": "HK_SECURITIES", "status": "FULL_TRADING_DAY"}
    assert review["close_top20"] == []
    assert review["row_counts"] == {}


def test_hk_securities_holiday_skips_and_unknown_calendar_fails_closed(tmp_path):
    client = _review_client(tmp_path / "default-data", hk_close_root=tmp_path / "v35-close-data")

    holiday = _hk_review(client, "20261001")
    assert holiday["status"] == "NON_TRADING_DAY"
    assert holiday["calendar"] == {"market": "HK_SECURITIES", "status": "NON_TRADING_DAY"}
    assert holiday["close_top20"] == []
    assert holiday["row_counts"] == {}

    unknown = _hk_review(client, "20270102")
    assert unknown["status"] == "CANNOT_CONFIRM"
    assert unknown["cannot_confirm"] == ["HK_SECURITIES_CALENDAR_UNKNOWN"]
    assert unknown["calendar"] == {"market": "HK_SECURITIES", "status": "UNKNOWN"}
    assert unknown["close_top20"] == []
    assert unknown["row_counts"] == {}


def test_valid_hk_connect_day_without_reference_is_cannot_confirm_and_does_not_fallback(tmp_path):
    default_store = ReviewStore(tmp_path / "default-data")
    default_store.import_reference(_reference("20260929"))
    explicit_store = ReviewStore(tmp_path / "v35-close-data")

    review = _hk_review(
        _review_client(default_store.root, hk_close_root=explicit_store.root),
        "20260929",
    )

    assert review["status"] == "CANNOT_CONFIRM"
    assert review["cannot_confirm"] == ["CLOSE_REVIEW_ARTIFACT_MISSING"]
    assert review["calendar"] == {"market": "HK_SECURITIES", "status": "FULL_TRADING_DAY"}
    assert review["close_top20"] == []
    assert review["row_counts"] == {}


def test_invalid_explicit_reference_does_not_fall_back_to_default_root(tmp_path):
    default_store = ReviewStore(tmp_path / "default-data")
    default_store.import_reference(_reference("20260911"))
    explicit_store = ReviewStore(tmp_path / "v35-close-data")
    explicit_store.import_reference(_reference("20260911"))
    (explicit_store.root / "close_reviews" / "20260911.json").write_text("{", encoding="utf-8")

    review = _hk_review(
        _review_client(default_store.root, hk_close_root=explicit_store.root),
        "20260911",
    )

    assert review["status"] == "CANNOT_CONFIRM"
    assert review["cannot_confirm"][0].startswith("V35_NATIVE_CLOSE_REVIEW_INVALID:")
    assert review["close_top20"] == []
    assert review["row_counts"] == {}


def test_create_app_binds_configured_hk_close_root_and_preserves_default(tmp_path, monkeypatch):
    default_store = ReviewStore(tmp_path / "default-data")
    close_store = ReviewStore(tmp_path / "v35-close-data")
    default_store.import_reference(_reference("20260930"))
    close_store.import_reference(_reference("20260930", status="MODEL_0_2_SOURCE_MISSING"))
    monkeypatch.setenv("V35_REVIEW_CORE_CLOSE_ROOT", str(close_store.root))

    app = create_app(data_root=default_store.root)
    with TestClient(app) as client:
        response = client.get("/api/v3/review", params={"date": "20260930"})
    assert response.status_code == 200
    review = response.json()["market_reviews"]["HK"]["model_selection_review"]
    assert review["status"] == "MODEL_0_2_SOURCE_MISSING"
    assert review["row_counts"]["close_top20"] == 20
    assert review["row_counts"]["hkconnect_universe"] == 691

    monkeypatch.delenv("V35_REVIEW_CORE_CLOSE_ROOT")
    with TestClient(create_app(data_root=default_store.root)) as client:
        default_response = client.get("/api/v3/review", params={"date": "20260930"})
    default_review = default_response.json()["market_reviews"]["HK"]["model_selection_review"]
    assert default_review["status"] == "MODEL_REVIEW_READY"


def test_create_app_open_missing_and_invalid_explicit_artifact_never_falls_back(
    tmp_path, monkeypatch
):
    default_store = ReviewStore(tmp_path / "default-data")
    close_store = ReviewStore(tmp_path / "v35-close-data")
    default_store.import_reference(_reference("20261002"))
    monkeypatch.setenv("V35_REVIEW_CORE_CLOSE_ROOT", str(close_store.root))

    with TestClient(create_app(data_root=default_store.root)) as client:
        missing_response = client.get("/api/v3/review", params={"date": "20261002"})
    missing_review = missing_response.json()["market_reviews"]["HK"]["model_selection_review"]
    assert missing_review["status"] == "CANNOT_CONFIRM"
    assert missing_review["cannot_confirm"] == ["CLOSE_REVIEW_ARTIFACT_MISSING"]
    assert missing_review["calendar"] == {"market": "HK_SECURITIES", "status": "FULL_TRADING_DAY"}
    assert missing_review["close_top20"] == []
    assert missing_review["row_counts"] == {}

    close_store.import_reference(_reference("20261002"))
    artifact = close_store.root / "close_reviews" / "20261002.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["status"] = "MODEL_REVIEW_READY_TAMPERED"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    with TestClient(create_app(data_root=default_store.root)) as client:
        invalid_response = client.get("/api/v3/review", params={"date": "20261002"})
    invalid_review = invalid_response.json()["market_reviews"]["HK"]["model_selection_review"]
    assert invalid_review["status"] == "CANNOT_CONFIRM"
    assert invalid_review["cannot_confirm"][0].startswith("V35_NATIVE_CLOSE_REVIEW_INVALID:")
    assert invalid_review["close_top20"] == []


def test_valid_911_reference_keeps_exact_artifact_sha_and_ready_status(tmp_path, monkeypatch):
    store = ReviewStore(tmp_path / "v35-close-data")
    reference = _reference("20260911")
    imported = store.import_reference(reference)
    monkeypatch.setenv("V35_REVIEW_CORE_CLOSE_ROOT", str(store.root))

    with TestClient(create_app(data_root=tmp_path / "default-data")) as client:
        response = client.get("/api/v3/review", params={"date": "20260911"})

    assert response.status_code == 200
    hk_parent = response.json()["market_reviews"]["HK"]
    review = hk_parent["model_selection_review"]
    assert review["status"] == "MODEL_REVIEW_READY"
    assert len(review["close_top20"]) == 20
    assert review["row_counts"] == {
        "hkconnect_universe": 691,
        "close_top20": 20,
        "model_0_2": 100,
        "stage_rows": 70,
    }
    assert review["models"]["0.2_prob_active"]["hit_count"] == 15
    assert review["stage_union"]["hit_count"] == 10
    assert hk_parent["artifact_sha256"] == imported["sha256"]
