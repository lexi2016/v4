"""Exact-date route regression against the frozen r21 read-only overlay inputs."""
from importlib.util import module_from_spec, spec_from_file_location
import os
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from v4_core.api.app import create_app
from v4_core.config import V4Config


@pytest.fixture
def review_routes(tmp_path, monkeypatch):
    raw_root = os.environ.get("V4_R21_OVERLAY_ROOT")
    if raw_root is None:
        pytest.skip("V4_R21_OVERLAY_ROOT must point to the frozen isolated r21 inputs")
    root = Path(raw_root)
    mirror = Path(__file__).resolve().parents[1] / "candidate/content_projection/read_overlay.py"
    monkeypatch.syspath_prepend(str(root))
    from content_projection.read_overlay import ContentProjection as FrozenProjection

    spec = spec_from_file_location("content_projection.d29_review_overlay", mirror)
    proposed = module_from_spec(spec)
    spec.loader.exec_module(proposed)
    app = create_app(config=V4Config.from_env(tmp_path))
    data, dist = root / "home/data", root / "frontend/dist"
    return (TestClient(FrozenProjection(app, data, dist)),
            TestClient(proposed.ContentProjection(app, data, dist)))


def test_exact_date_review_market_envelope_does_not_fabricate_or_erase_data(review_routes):
    baseline, candidate = review_routes

    def review(client, date):
        response = client.get("/api/v4/review", params={"date": date})
        assert response.status_code == 200
        return response.json()

    for date in ("20261124", "20261125", "20261129", "20261130", "2026-11-30"):
        original = review(baseline, date)
        result = review(candidate, date)
        assert set(result["market_reviews"]) == {"A", "HK"}
        assert result["status"] == "NOT_MATERIALIZED" and result["trade_date"] == date
        assert result["data"] == original["data"] == {} and result["plan_run_id"] is None
        ashare, hk = result["market_reviews"]["A"], result["market_reviews"]["HK"]
        assert ashare["status"] == "NOT_MATERIALIZED" and ashare["trade_date"] == date
        assert all(ashare[field] == [] for field in ("big_picture", "mainlines", "core_stocks",
                                                    "observation_pool", "next_day_trigger_tree", "quality_gate"))
        assert ashare["cannot_confirm"] == ["A_SHARE_REVIEW_NOT_MATERIALIZED"]
        assert hk["model_selection_review"] == {"trade_date": date, "status": "REFERENCE_NOT_IMPORTED",
                                                "cannot_confirm": ["CLOSE_REVIEW_REFERENCE_NOT_IMPORTED"]}
        assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))
        assert result["RESEARCH_ONLY"] is True
        # Any separately projected same-date evidence and gaps are immutable.
        assert all(result[key] == value for key, value in original.items() if key != "market_reviews")

    for date in ("20261126", "20261127", "20261128"):
        original = review(baseline, date)
        assert set(original["market_reviews"]) == {"A", "HK"}
        assert review(candidate, date) == original
