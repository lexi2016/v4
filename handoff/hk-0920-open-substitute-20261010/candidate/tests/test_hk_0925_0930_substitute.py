from __future__ import annotations

from stage_center.selection import (
    ALGORITHM_SHA256,
    select_hk_0925_0930_substitute,
    select_hk_four_lane,
)

RAW_SHA = "e" * 64
SOURCE_EVIDENCE = (
    "substitute_kind=HK_0930_0935_FOR_HK_0925",
    "substitute_label=09:30-09:35开盘数据替代补算",
    "source_stage_id=STAGE_0930_0935",
    "source_window=09:30-09:35",
    "source_last_bar_time=2026-10-09 09:35:00",
    "source_manifest_temporal_cutoff_safe=false",
    "target_stage_temporal_cutoff_safe=false",
    "d1_membership_status=RECONSTRUCTED_ASOF_CANDIDATE_PIT_UNVERIFIED",
    "source_raw_run_id=verified-stage0930-run",
    "source_raw_artifact_sha256=" + RAW_SHA,
    "d1_ranked_rows_sha256=" + ("d" * 64),
)


def _source_row(index: int) -> dict[str, object]:
    code = f"HK.{index:05d}"
    close = 100.0 + index
    return {
        "trade_date": "20261009",
        "code": code,
        "name": f"名称{index}",
        "stock_name": f"名称{index}",
        "candidate_lanes": [],
        "update_time": "2026-10-09 09:35:00",
        "open_price": 100.0,
        "last_price": close,
        "high_price": close + 1.0,
        "low_price": 99.0,
        "prev_close_price": 100.0,
        "turnover": 10_000_000.0 + index,
        "volume": 1_000.0,
        "window_start": "2026-10-09 09:31:00",
        "window_end": "2026-10-09 09:35:00",
        "bar_time": "09:35:00",
        "bar_count": 5,
        "d1_status": "RECONSTRUCTED_ASOF_CANDIDATE_PIT_UNVERIFIED",
        "d1_model_id": "prob_active",
        "d1_prob_active": 0.5,
        "d1_rank": index,
        "d1_score": 0.5,
        "d1_source_evidence": ["d1_membership=RECONSTRUCTED_ASOF_CANDIDATE_PIT_UNVERIFIED"],
    }


def _source(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "trade_date": "20261009",
        "stage_id": "STAGE_0925",
        "source_stage_id": "STAGE_0930_0935",
        "raw_artifact_sha256": RAW_SHA,
        "requested_rows": 100,
        "source_rows": len(rows),
        "rows": rows,
        "missing_symbols": (),
        "source_status": "PARTIAL_WITH_ROWS",
        "cannot_confirm": ("HK_0920_EXACT_AUCTION_UNAVAILABLE",),
        "source_evidence": SOURCE_EVIDENCE,
        "source_temporal_cutoff_safe": False,
    }


def _legacy_selector_input(source_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    out = []
    for source in source_rows:
        last = float(source["last_price"])
        previous = float(source["prev_close_price"])
        out.append({
            "code": source["code"],
            "name": source["name"],
            "stock_name": source["stock_name"],
            "candidate_lanes": [],
            "candidate_bucket": "",
            "trade_status_contract": "",
            "pct_chg": (last - previous) / previous * 100.0,
            "turnover": source["turnover"],
            "turnover_hkd": source["turnover"],
            "volume_ratio": None,
            "turnover_rate": None,
            "platform_circular_market_cap_hkd_yi": None,
            "offer_float_market_cap_hkd_yi": None,
            "stage_window_change_pct": None,
            "open_price": source["open_price"],
            "last_price": source["last_price"],
            "high_price": source["high_price"],
            "low_price": source["low_price"],
            "update_time": source["update_time"],
            "next_validation_time": "09:35:05",
            "stage_id": "STAGE_0930_0935",
            "d1_status": source["d1_status"],
            "d1_model_id": source["d1_model_id"],
            "d1_prob_active": source["d1_prob_active"],
            "d1_rank": source["d1_rank"],
            "d1_score": source["d1_score"],
            "d1_source_evidence": source["d1_source_evidence"],
        })
    return out


def test_substitute_reuses_stage0930_ranking_and_keeps_real_source_time() -> None:
    source_rows = [_source_row(index) for index in range(1, 101)]
    actual = select_hk_0925_0930_substitute(_source(source_rows), "20261009", raw_artifact_sha256=RAW_SHA)
    expected = select_hk_four_lane(
        _legacy_selector_input(source_rows),
        "20261009",
        "STAGE_0930_0935",
        RAW_SHA,
        source_status="PARTIAL_WITH_ROWS",
        requested_rows=100,
        cannot_confirm=("HK_0920_EXACT_AUCTION_UNAVAILABLE",),
        source_evidence=(
            *SOURCE_EVIDENCE,
            "selection_contract=V3_TOP10_RECOMMENDATION",
            "stage0925_score_source=UNCHANGED_STAGE_0930_0935_FOUR_LANE_SELECTOR",
        ),
    )

    assert actual["stage_id"] == "STAGE_0925"
    assert actual["source_status"] == "PARTIAL_WITH_ROWS"
    assert actual["selection_status"] == "PARTIAL_WITH_ROWS"
    assert actual["source_rows"] == 100
    assert actual["requested_rows"] == 100
    assert actual["missing_symbols"] == []
    assert actual["algorithm_sha256"] == ALGORITHM_SHA256 == "fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506"
    assert [(row["code"], row["score"]) for row in actual["rows"]] == [
        (row["code"], row["score"]) for row in expected["rows"]
    ]
    assert all(row["source_last_bar_time"] == "2026-10-09 09:35:00" for row in actual["rows"])
    assert all(row["source_mode"] == "HK_CONNECT_0930_0935_SUBSTITUTE_STAGE_0925" for row in actual["rows"])
    assert all(row["substitute_label"] == "09:30-09:35开盘数据替代补算；实际数据截止09:35" for row in actual["rows"])
    assert all(row["formal_eligible"] is False and row["action_level"] == "NO_BUY" for row in actual["rows"])
    assert actual["production_allowed"] is False
    assert actual["buy_gate_updated"] is False
    assert actual["orders_sent"] is False


def test_invalid_substitute_rows_are_isolated_without_blocking_available_members() -> None:
    source_rows = [_source_row(index) for index in range(1, 101)]
    source_rows[0]["update_time"] = "2026-10-09 09:36:00"
    source_rows[1]["trade_date"] = "20261008"

    actual = select_hk_0925_0930_substitute(_source(source_rows), "20261009", raw_artifact_sha256=RAW_SHA)

    assert actual["source_status"] == "PARTIAL_WITH_ROWS"
    assert actual["selection_status"] == "PARTIAL_WITH_ROWS"
    assert actual["source_rows"] == 98
    assert set(actual["missing_symbols"]) == {"HK.00001", "HK.00002"}
    assert len(actual["rows"]) == 10
    assert all(row["code"] not in {"HK.00001", "HK.00002"} for row in actual["rows"])


def test_substitute_rejects_unbound_date_and_safe_cutoff_claim() -> None:
    source = _source([_source_row(index) for index in range(1, 11)])
    source["trade_date"] = "20261010"
    try:
        select_hk_0925_0930_substitute(source, "20261010", raw_artifact_sha256=RAW_SHA)
    except ValueError as error:
        assert "restricted" in str(error)
    else:
        raise AssertionError("a different trade date must not use the one-date substitute")

    source = _source([_source_row(index) for index in range(1, 11)])
    source["source_temporal_cutoff_safe"] = True
    try:
        select_hk_0925_0930_substitute(source, "20261009", raw_artifact_sha256=RAW_SHA)
    except ValueError as error:
        assert "unsafe target cutoff" in str(error)
    else:
        raise AssertionError("the post-open source must not claim safe 09:20 timing")
