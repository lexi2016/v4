from __future__ import annotations

from apps.api.v35_api import review_router
from apps.api.v35_api.review_router import create_review_router
from infrastructure.stage_store import StageStore


def _publish_stage(store: StageStore, trade_date: str, stage_id: str, index: int) -> None:
    row = {
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": "A",
        "symbol": f"A.6000{index:02d}",
        "name": f"阶段观察{index}",
        "stage_rank": index,
        "recommendation_status": "WATCH_ONLY",
        "data_level": "STAGE_EVIDENCE",
    }
    artifact = {
        "schema_version": "v3_stage_workbench.v2",
        "trade_date": trade_date,
        "stage": {"stage_id": stage_id, "status": "READY_WITH_WATCH_ROWS"},
        "stage_groups": [{"market": "A", "label": "A股", "rows": [row]}],
        "unified_rows": [row],
        "selected_a_rows": 1,
        "selected_hk_rows": 0,
        "selected_total_rows": 1,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
    }
    store.publish(
        trade_date=trade_date,
        stage_id=stage_id,
        run_id=f"stage-{stage_id}",
        input_sha256="1" * 64,
        code_signature="2" * 64,
        output=artifact,
        force=False,
    )


def _review_endpoint(data_root):
    app = create_review_router(data_root)
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", "") == "/api/v3/review"
    )


def test_review_endpoint_exposes_rich_partial_surface_from_exact_stage_rows(tmp_path) -> None:
    trade_date = "20260824"
    store = StageStore(tmp_path)
    _publish_stage(store, trade_date, "STAGE_0925", 1)
    _publish_stage(store, trade_date, "STAGE_0930_0935", 2)

    payload = _review_endpoint(tmp_path)(trade_date)
    review = payload["market_reviews"]["A"]

    assert review["status"] == "PARTIAL_STAGE_EVIDENCE"
    assert review["review_surface"]["tier"] == "V3_RICH_PARTIAL"
    assert review["review_surface"]["status"] == "PARTIAL_STAGE_EVIDENCE"
    assert {item["trade_date"] for item in review["review_surface"]["source_refs"]} == {trade_date}
    assert len(review["stage_validation_rows"]) == 2
    assert all(row["recommendation_status"] == "WATCH_ONLY" for row in review["stage_validation_rows"])
    assert all(row["role_type"] == "stage_validation_anchor" for row in review["stage_validation_rows"])
    assert review["prior_plan_rows"] == []
    assert review["board_rows"] == []
    assert review["mainlines"] == []
    assert review["core_stocks"] == []
    assert "FORMAL_CORE_NOT_MATERIALIZED" in review["cannot_confirm"]
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


def test_review_endpoint_keeps_compact_surface_without_exact_stage_rows(tmp_path) -> None:
    payload = _review_endpoint(tmp_path)("20260824")

    review = payload["market_reviews"]["A"]
    assert review["status"] == "NOT_MATERIALIZED"
    assert review["review_surface"]["tier"] == "COMPACT_NOT_MATERIALIZED"


def test_review_endpoint_reads_shared_stage_workbench_without_producing(monkeypatch, tmp_path) -> None:
    trade_date = "20260824"
    calls: list[tuple[str, str, int]] = []

    def read_workbench(self, selected_date: str, stage_id: str, limit: int = 10):
        calls.append((selected_date, stage_id, limit))
        return {
            "trade_date": trade_date,
            "stage": {"stage_id": stage_id, "status": "PARTIAL_WITH_WATCH_ROWS"},
            "artifact_id": f"artifact-{stage_id}",
            "run_id": f"run-{stage_id}",
            "response_source": "SHARED_STAGE_CENTER",
            "unified_rows": [
                {
                    "trade_date": trade_date,
                    "market": "A",
                    "symbol": "A.600001",
                    "name": "共享阶段观察",
                    "trade_status": "WATCH_ONLY",
                }
            ],
        }

    monkeypatch.setattr(review_router.StageRunner, "read_workbench", read_workbench)

    payload = _review_endpoint(tmp_path)(trade_date)
    review = payload["market_reviews"]["A"]

    assert review["review_surface"]["tier"] == "V3_RICH_PARTIAL"
    assert len(review["stage_validation_rows"]) == len(review_router.FROZEN_STAGE_IDS)
    assert all(row["recommendation_status"] == "WATCH_ONLY" for row in review["stage_validation_rows"])
    refs = review["review_surface"]["source_refs"]
    assert len(refs) == len(review_router.FROZEN_STAGE_IDS)
    assert refs[0]["artifact_id"] == "artifact-STAGE_0925"
    assert refs[0]["run_id"] == "run-STAGE_0925"
    assert refs[0]["source_role"] == "SHARED_STAGE_CENTER"
    assert len(refs[0]["artifact_sha256"]) == 64
    assert calls == [
        (trade_date, stage_id, 50) for stage_id in review_router.FROZEN_STAGE_IDS
    ]
