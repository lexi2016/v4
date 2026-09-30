from __future__ import annotations

from domains.stage_scoring import (
    rank_a_stage_rows,
    rank_hk_stage_rows,
    score_a_stage,
    score_hk_stage,
)


def test_a_stage_0925_score_matches_frozen_v3_behavior() -> None:
    row = {
        "symbol": "A.000001",
        "open_price": 11.0,
        "last_price": 11.0,
        "prev_close_price": 10.0,
        "high_price": 11.0,
        "low_price": 10.8,
        "turnover": 200_000_000,
        "bid_vol1": 600,
        "ask_vol1": 400,
        "pool_score": 100,
        "recommendation_status": "WATCH_ONLY",
    }

    assert score_a_stage(row, "STAGE_0925") == 158.6


def test_a_intraday_score_and_order_match_frozen_v3_behavior() -> None:
    stronger = {
        "symbol": "A.000001",
        "open_price": 10.0,
        "last_price": 10.5,
        "prev_close_price": 9.8,
        "high_price": 10.8,
        "low_price": 9.9,
        "turnover": 200_000_000,
        "bid_vol1": 600,
        "ask_vol1": 400,
        "pool_score": 100,
        "pool_rank": 2,
        "recommendation_status": "WATCH_ONLY",
    }
    weaker = {
        **stronger,
        "symbol": "A.000002",
        "last_price": 10.1,
        "pool_rank": 1,
    }

    assert score_a_stage(stronger, "STAGE_0930_0935") == 100.0
    assert score_a_stage({
        **stronger,
        "source_bar_count": 3,
        "expected_bar_count": 5,
        "stage_window_complete": False,
    }, "STAGE_0930_0935") == 94.67
    ranked = rank_a_stage_rows([weaker, stronger], "STAGE_0930_0935")
    assert [row["symbol"] for row in ranked] == ["A.000001", "A.000002"]
    assert [row["stage_rank"] for row in ranked] == ["1", "2"]
    assert [row["decision_level"] for row in ranked] == ["WATCH_TOP", "WATCH_TOP"]


def test_hk_stage_score_and_order_match_frozen_v3_behavior() -> None:
    capped = {
        "symbol": "HK.00001",
        "pct_chg": 12,
        "stage_window_change_pct": 2,
        "turnover_hkd_yi": 0.5,
        "circular_market_cap_hkd_yi": 80,
        "stage_close_position": 0.75,
        "source_universe": "OLD_DEMON_MEMORY|NEW_HKCONNECT_BATCH|LOW_FLOAT_FILTER",
        "recommendation_status": "WATCH_ONLY",
    }
    ordinary = {
        "symbol": "HK.00002",
        "pct_chg": 3,
        "stage_window_change_pct": 0,
        "turnover_hkd_yi": 0.1,
        "circular_market_cap_hkd_yi": 300,
        "stage_close_position": 0.5,
        "source_universe": "",
        "recommendation_status": "WATCH_ONLY",
    }

    assert score_hk_stage(capped) == 100.0
    assert score_hk_stage(ordinary) == 48.0
    ranked = rank_hk_stage_rows([ordinary, capped])
    assert [row["symbol"] for row in ranked] == ["HK.00001", "HK.00002"]
    assert ranked[0]["stage_rtdata_score"] == 100.0
    assert ranked[0]["stage_rank"] == "1"


def test_native_rankers_never_promote_trading_semantics() -> None:
    a_rows = rank_a_stage_rows(
        [
            {
                "symbol": "A.000001",
                "open_price": 10,
                "last_price": 10,
                "prev_close_price": 10,
                "recommendation_status": "WATCH_ONLY",
            }
        ],
        "STAGE_0925",
    )
    hk_rows = rank_hk_stage_rows(
        [
            {
                "symbol": "HK.00001",
                "pct_chg": 1,
                "recommendation_status": "WATCH_ONLY",
            }
        ]
    )

    for row in [*a_rows, *hk_rows]:
        assert row["recommendation_status"] == "WATCH_ONLY"
        assert row["production_allowed"] is False
        assert row["buy_gate_updated"] is False
        assert row["orders_sent"] is False
