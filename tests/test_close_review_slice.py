from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from infrastructure.review_store import ReviewStore
from ops.import_close_review_reference import normalize_review_reference


def _authority_export(trade_date: str = "20260729") -> dict:
    review = {
        "schema_version": "v3_hkconnect_review_manifest.v2",
        "status": "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE",
        "trade_date": trade_date,
        "primary_kpi": "全港股通收盘涨幅Top20覆盖率",
        "models": {
            "0.2_prob_active": {
                "evidence_status": "READY",
                "selected_count": 100,
                "hit_count": 3,
                "coverage_pct": 15.0,
                "precision_pct": 3.0,
                "selected_codes": ["HK.00325"],
            }
        },
        "stages": {
            "STAGE_0930_0935": {
                "evidence_status": "READY",
                "selected_count": 9,
                "hit_count": 1,
                "coverage_pct": 5.0,
                "precision_pct": 11.111,
                "selected_codes": ["HK.01810"],
            }
        },
        "stage_union": {
            "evidence_status": "READY",
            "selected_count": 17,
            "hit_count": 2,
            "coverage_pct": 10.0,
            "precision_pct": 11.765,
            "selected_codes": ["HK.01810", "HK.02367"],
        },
        "kpi": {"model_0_2_close_top20_hits": 3, "stage_union_close_top20_hits": 2},
        "row_counts": {"hkconnect_universe": 648, "close_top20": 20, "model_0_2": 100, "stage_rows": 17},
        "close_top20": [
            {
                "rank": 1,
                "code": "HK.00325",
                "name": "布鲁可",
                "pct_chg_close": 15.9343,
                "close": 54.35,
                "amount": 164235451,
                "source_path": r"C:\legacy\close.csv",
            }
        ],
        "model_rows": [
            {
                "rank": 1,
                "code": "HK.00325",
                "name": "布鲁可",
                "strategy": "prob_active",
                "pool_version": "0.2",
                "hit_top20": True,
            }
        ],
        "stage_rows": [
            {
                "stage_id": "STAGE_0930_0935",
                "stage_rank": 1,
                "code": "HK.01810",
                "name": "小米集团-W",
                "hit_top20": True,
            }
        ],
        "top20_attribution": [
            {
                "rank": 1,
                "code": "HK.00325",
                "name": "布鲁可",
                "pct_chg_close": 15.9343,
                "model_0_2_hit": True,
                "stage_union_hit": False,
                "classification": "model_only",
                "all_stages": [],
            }
        ],
        "missing_stages": ["STAGE_0925"],
        "cannot_confirm": ["MISSING_STAGE_0925"],
        "source_path": r"C:\Users\huang\Desktop\学习\v3_system\港股复盘",
        "production_allowed": True,
        "buy_gate_updated": True,
        "orders_sent": True,
    }
    return {
        "trade_date": trade_date,
        "market_reviews": {"HK": {"model_selection_review": review}},
    }


def test_review_reference_normalizer_keeps_metrics_and_removes_legacy_paths() -> None:
    payload = normalize_review_reference(_authority_export())

    assert payload["schema_version"] == "v3_5.close_review_reference.v1"
    assert payload["trade_date"] == "20260729"
    assert payload["models"]["0.2_prob_active"]["selected_count"] == 100
    assert payload["stage_union"]["hit_count"] == 2
    assert payload["close_top20"][0]["name"] == "布鲁可"
    assert payload["top20_attribution"][0]["classification"] == "model_only"
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False
    assert "v3_system" not in json.dumps(payload, ensure_ascii=False)
    assert "source_path" not in json.dumps(payload, ensure_ascii=False)


def test_review_reference_is_served_by_date_without_old_runtime_dependency(tmp_path) -> None:
    payload = normalize_review_reference(_authority_export())
    store = ReviewStore(tmp_path / "data")
    store.import_reference(payload)

    response = TestClient(create_app(data_root=store.root)).get(
        "/api/v3/review",
        params={"date": "20260729"},
    )

    assert response.status_code == 200
    body = response.json()
    review = body["market_reviews"]["HK"]["model_selection_review"]
    assert body["trade_date"] == "20260729"
    assert body["reference_snapshot"] is True
    assert review["status"] == "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE"
    assert len(review["close_top20"]) == 1
    assert review["production_allowed"] is False
    assert "v3_system" not in response.text

    dates = TestClient(create_app(data_root=store.root)).get("/api/v1/runs/date-list").json()
    assert dates["review_dates"] == ["20260729"]


def test_missing_review_reference_is_explicitly_unavailable(tmp_path) -> None:
    response = TestClient(create_app(data_root=tmp_path / "data")).get(
        "/api/v3/review",
        params={"date": "20260730"},
    )

    assert response.status_code == 200
    review = response.json()["market_reviews"]["HK"]["model_selection_review"]
    assert review["status"] == "REFERENCE_NOT_IMPORTED"
    assert review["close_top20"] == []
    assert review["cannot_confirm"] == ["CLOSE_REVIEW_REFERENCE_NOT_IMPORTED"]
