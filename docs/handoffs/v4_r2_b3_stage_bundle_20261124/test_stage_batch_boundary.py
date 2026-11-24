"""Exercise the Stage batch route through its normal FastAPI entrypoint."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v4_api.routes import RouteContext, register_routes
from contracts.stages import FROZEN_STAGE_IDS, STAGE_MARKET_SCOPES


def test_stage_batch_counts_a7_separately_from_cross8():
    vk = {"status": "PARTIAL_WITH_ROWS", "selection_manifest_receipt_verified": True}
    unknown = {"status": "CANNOT_CONFIRM", "selection_manifest_receipt_verified": False}
    a_and_hk = {stage for stage, markets in STAGE_MARKET_SCOPES.items() if "A" in markets}
    close_hk = FROZEN_STAGE_IDS[-1]

    def read(_date, stage, _limit):
        has_a = stage in a_and_hk
        has_hk = stage == close_hk
        return {
            "markets": {"A": vk if has_a else unknown, "HK": vk if has_hk else unknown},
            "selected_a_rows": 10 if has_a else None, "selected_hk_rows": 10 if has_hk else None,
        }

    def bounded(fn, ordered, **_options):
        return dict(map(fn, ordered))

    app = FastAPI()
    register_routes(RouteContext(
        app, lambda: {"default_date": "20261123"}, str, None, None, None, None, None,
        read, lambda summary: summary, bounded, 8,
    ))
    client = TestClient(app)
    payload = client.get("/api/v4/workbench/stage-batch?date=20261123").json()
    a7, cross8 = (payload["coverage"][scope] for scope in ("a7", "cross8"))
    assert (a7["with_verified_rows"], a7["expected"]) == (7, 7)
    assert a7["all_required_stages_have_verified_rows"] is True
    assert (cross8["with_verified_rows"], cross8["expected"]) == (1, 8)
    assert cross8["with_verified_rows_stage_ids"] == [close_hk]
    assert set(cross8["incomplete_stage_ids"]) == a_and_hk
    assert payload["write_performed"] is payload["buy_gate_updated"] is payload["orders_sent"] is False

    condensed = client.get(f"/api/v4/workbench/stage-batch?stages={close_hk}").json()
    assert condensed["coverage"]["a7"]["with_verified_rows"] == 0
    assert set(condensed["coverage"]["a7"]["not_requested_stage_ids"]) == a_and_hk
    assert condensed["coverage"]["a7"]["incomplete_stage_ids"] == []
