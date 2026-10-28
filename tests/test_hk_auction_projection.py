"""Auction source evidence must survive the production selection builder."""
from types import SimpleNamespace

import pytest

from stage_center.acquisition import SourceResult
from stage_center.live_collectors import production_selection_builders
from stage_center.selection import SelectionError


def build(target_date="20261013", score=82.0):
    source = SourceResult("futu", "READY", rows=({
        "code": "HK.01196", "name": "sample", "rank": 7,
        "auction_score": score, "target_date": target_date,
        "signal_date": "20261012", "candidate_lanes": ["PREOPEN_AUCTION_CONTINUATION"],
        "last_price": 3.63, "prev_close_price": 3.625,
        "open_price": 3.63, "high_price": 3.63, "low_price": 3.63,
        "update_time": "2026-10-13 09:19:49",
    },), requested_rows=1)
    plan = SimpleNamespace(stage_id="STAGE_0925", trade_date="20261013")
    raw = dict(status="READY", artifact_sha256="a" * 64, requested_rows=1,
               missing_symbols=(), cannot_confirm=(), source_evidence=(), cutoff_at="09:20")
    return production_selection_builders(plan.stage_id)["HK_CONNECT"](source, plan, raw)


@pytest.mark.parametrize("score", [82.0, 0.0])
def test_source_score_and_previous_close_change_survive(score):
    result = build(score=score)
    row = result["rows"][0]
    assert row["score"] == score and row["rank"] == 1
    assert row["current_change_pct"] == pytest.approx(0.1379)
    assert row["action_level"] == "NO_BUY" and row["formal_eligible"] is False


def test_wrong_target_date_is_not_lost_in_projection():
    with pytest.raises(SelectionError, match="target_date drift"):
        build(target_date="20261012")
