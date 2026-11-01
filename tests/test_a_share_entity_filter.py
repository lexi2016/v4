"""Read-side quarantine at each of the three consumer boundaries.

The pools are published evidence and stay untouched: a row that carries a date
where a code belongs is kept on disk and withheld from consumers.  The three
boundaries are independent, so each one gets its own assertions.
"""
from __future__ import annotations

from pathlib import Path

from contracts.a_share_entity_filter import (
    FILTER_RULE_VERSION,
    filter_pool_rows,
    invalid_a_share_symbols,
    quarantine_invalid_a_rows,
)


def _row(code, rank, name, pool_id="a_share_research_recommendation_pool", market="A"):
    return {
        "pool_id": pool_id,
        "pool_rank": rank,
        "code": code,
        "symbol": f"{market}.{code}" if market != "A" else f"A.{code}",
        "stock_name": name,
        "market": market,
        "trade_date": "20261030",
        "target_date": "20261030",
        "signal_date": "20261030",
        "article_count": 128,
        "pool_score": 1.0,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
        "write_performed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _pool(rows, pool_id="a_share_research_recommendation_pool", market="A"):
    return {
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": market,
        "status": "READY",
        "source_path": "source.json",
        "source_sha256": "a" * 64,
        "trade_date": "20261030",
        "signal_date": "20261030",
        "target_date": "20261030",
        "rows": rows,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


# --- boundary 1: preselection pool API -------------------------------------


def test_pool_api_quarantines_the_invalid_entity():
    from apps.api.v4_api.preselection_service import _preselection_response_from_pools

    pools = [_pool([
        _row("261029", 1, "申昊科技"),
        _row("600519", 2, "贵州茅台"),
        _row("002539", 3, "云图控股"),
    ])]
    response = _preselection_response_from_pools(
        pools, trade_date="20261030", limit=50, offset=0, apply_review_sources=False
    )

    assert response["original_row_count"] == 3
    assert response["effective_row_count"] == 2
    assert response["quarantined_row_count"] == 1
    assert response["original_row_count"] == (
        response["effective_row_count"] + response["quarantined_row_count"]
    )
    assert response["filter_rule_version"] == FILTER_RULE_VERSION
    assert [row["code"] for row in response["rows"]] == ["600519", "002539"]
    # Ranks are published values; filtering must not renumber them.
    assert [row["pool_rank"] for row in response["rows"]] == [2, 3]
    assert response["quarantined"][0]["code"] == "261029"
    assert response["quarantined"][0]["stock_name"] == "申昊科技"


def test_pool_api_reports_original_count_separately_from_the_returned_rows():
    from apps.api.v4_api.preselection_service import _preselection_response_from_pools

    pools = [_pool([_row("261029", 1, "申昊科技"), _row("600519", 2, "贵州茅台")])]
    response = _preselection_response_from_pools(
        pools, trade_date="20261030", limit=50, offset=0, apply_review_sources=False
    )
    assert response["row_count"] == response["effective_row_count"] == len(response["rows"]) == 1
    assert response["original_row_count"] == 2


def test_pool_api_is_unchanged_when_every_row_is_valid():
    from apps.api.v4_api.preselection_service import _preselection_response_from_pools

    pools = [_pool([_row("600519", 1, "贵州茅台"), _row("002539", 2, "云图控股")])]
    response = _preselection_response_from_pools(
        pools, trade_date="20261030", limit=50, offset=0, apply_review_sources=False
    )
    assert response["quarantined_row_count"] == 0
    assert response["effective_row_count"] == response["original_row_count"] == 2
    assert [row["pool_rank"] for row in response["rows"]] == [1, 2]


# --- boundary 2: research decision board -----------------------------------


def test_decision_board_drops_the_invalid_stock():
    from domains.research import build_research_archive

    source = {
        "trade_date": "20261030",
        "stock_research_timeline": [{
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "source_title": "白酒行业跟踪",
            "source_type": "REPORT",
            "event_time": "20261030T100000+08:00",
        }],
        "stock_research_daily": [
            {"stock_code": "261029", "stock_name": "申昊科技", "research_score": 9.0},
            {"stock_code": "600519", "stock_name": "贵州茅台", "research_score": 5.0},
        ],
        "research_pool_bridge": [],
        "source_manifest": {"generated_at": "20261030T150000+08:00"},
    }
    payload = build_research_archive(source, source_input_sha256="0" * 64)

    assert [row["stock_code"] for row in payload["stock_pool"]] == ["600519"]
    assert payload["quarantined_row_count"] == 1
    assert payload["stock_pool_original_count"] == 2
    assert payload["stock_pool_quarantined"][0]["stock_code"] == "261029"
    assert any(reason.startswith("A_SHARE_ENTITY_QUARANTINED")
               for reason in payload["cannot_confirm"])


# --- boundary 3: saved stage results are annotated, never recomputed -------


def test_saved_stage_result_annotates_the_invalid_symbol_without_touching_rows():
    from stage_center.consumer import _project_market

    envelope = {
        "trade_date": "20261030",
        "stage_id": "D1_PREMARKET",
        "market": "A_SHARE",
        "selection_status": "READY",
        "selected_rows": 1,
        "rows": [{"code": "A.600519", "rank": 1}],
        "missing_symbols": ["SZ.261029", "SZ.000001"],
        "cannot_confirm": [],
        "source_evidence": [],
    }
    projected = _project_market(
        "A_SHARE", envelope, trade_date="20261030", stage_id="D1_PREMARKET"
    )

    # The saved result keeps every row and every symbol it was published with.
    assert projected["missing_symbols"] == ["SZ.261029", "SZ.000001"]
    assert projected["historical_invalid_entity_count"] == 1
    assert projected["historical_invalid_entities"] == ["SZ.261029"]
    assert "含 1 条历史非法实体记录" == projected["display_note"]
    assert "HISTORICAL_INVALID_A_SHARE_ENTITY:1" in projected["cannot_confirm"]


def test_saved_stage_result_without_invalid_entities_is_quiet():
    from stage_center.consumer import _project_market

    envelope = {
        "trade_date": "20261030",
        "stage_id": "D1_PREMARKET",
        "market": "A_SHARE",
        "selection_status": "READY",
        "selected_rows": 1,
        "rows": [{"code": "A.600519", "rank": 1}],
        "missing_symbols": ["SZ.000001"],
        "cannot_confirm": [],
        "source_evidence": [],
    }
    projected = _project_market(
        "A_SHARE", envelope, trade_date="20261030", stage_id="D1_PREMARKET"
    )
    assert projected["historical_invalid_entity_count"] == 0
    assert "display_note" not in projected


# --- filter unit behaviour -------------------------------------------------


def test_hk_rows_are_never_quarantined():
    rows = [_row("00700", 1, "腾讯控股", pool_id="hkconnect_d1_top100", market="HK")]
    kept, dropped = quarantine_invalid_a_rows(rows)
    assert dropped == []
    assert kept == rows


def test_filtering_preserves_pool_order_and_marks_original_size():
    pools = [
        _pool([_row("261029", 1, "申昊科技"), _row("600519", 2, "贵州茅台")]),
        _pool([], pool_id="hkconnect_d1_top100", market="HK"),
    ]
    kept, dropped = filter_pool_rows(pools)
    assert [pool["pool_id"] for pool in kept] == [
        "a_share_research_recommendation_pool", "hkconnect_d1_top100"
    ]
    assert kept[0]["original_pool_size"] == 2
    assert kept[0]["quarantined_row_count"] == 1
    assert len(kept[0]["rows"]) == 1
    # The input stays exactly as the store returned it.
    assert len(pools[0]["rows"]) == 2
    assert len(dropped) == 1


def test_invalid_symbol_detection_is_market_aware():
    assert invalid_a_share_symbols(["HK.00700", "A.600519", "600519", "SZ.000001"]) == []
    assert invalid_a_share_symbols(["SZ.261029", "SH.600519.SH"]) == ["SZ.261029", "SH.600519.SH"]


# --- regressions found in review of the first implementation ----------------


def test_decision_board_keeps_a_hong_kong_row_in_a_mixed_input():
    from domains.research import build_research_archive

    source = {
        "trade_date": "20261030",
        "stock_research_timeline": [{
            "stock_code": "600519", "stock_name": "贵州茅台", "source_title": "白酒跟踪",
            "source_type": "REPORT", "event_time": "20261030T100000+08:00",
        }],
        "stock_research_daily": [
            {"stock_code": "HK.00700", "stock_name": "腾讯控股", "market": "HK", "research_score": 8.0},
            {"stock_code": "261029", "stock_name": "申昊科技", "research_score": 9.0},
            {"stock_code": "600519", "stock_name": "贵州茅台", "research_score": 5.0},
        ],
        "research_pool_bridge": [],
        "source_manifest": {"generated_at": "20261030T150000+08:00"},
    }
    payload = build_research_archive(source, source_input_sha256="0" * 64)

    assert [row["stock_code"] for row in payload["stock_pool"]] == ["HK.00700", "600519"]
    assert [item["stock_code"] for item in payload["stock_pool_quarantined"]] == ["261029"]


def test_decision_board_keeps_a_hong_kong_row_marked_only_by_its_symbol():
    from contracts.a_share_entity_filter import quarantine_research_stock_rows

    kept, dropped = quarantine_research_stock_rows([{"stock_code": "HK.00700"}])
    assert kept == [{"stock_code": "HK.00700"}]
    assert dropped == []


def test_the_ordinary_read_path_filters_the_served_rows():
    """The router reads through preselection(), not through the projection helper."""
    from domains._preselection_parts.pool_assembly import _preselection_body

    pools = [_pool([
        _row("261029", 1, "申昊科技"),
        _row("600519", 2, "贵州茅台"),
        _row("00700", 1, "腾讯控股", pool_id="hkconnect_d1_top100", market="HK"),
    ], pool_id="a_share_research_recommendation_pool")]

    class _Store:
        root = Path("/nonexistent-v4-test-root")

    class _PoolStore:
        def __init__(self, root):
            self.root = root

        def read_all(self, date):
            return pools

    response = _preselection_body(
        _Store(), "20261030", 300, offset=0,
        allow_legacy_flat=False, pool_store_class=_PoolStore,
    )

    assert response["data_status"] == "PARTIAL_WITH_ROWS"
    assert [row["code"] for row in response["rows"]] == ["600519", "00700"]
    assert response["original_row_count"] == 3
    assert response["effective_row_count"] == 2
    assert response["quarantined_row_count"] == 1
    assert response["quarantined"][0]["code"] == "261029"
    assert response["filter_rule_version"] == FILTER_RULE_VERSION


def test_the_ordinary_read_path_reports_an_all_quarantined_set():
    from domains._preselection_parts.pool_assembly import _preselection_body

    pools = [_pool([_row("261029", 1, "申昊科技")])]

    class _Store:
        root = Path("/nonexistent-v4-test-root")

    class _PoolStore:
        def __init__(self, root):
            self.root = root

        def read_all(self, date):
            return pools

    response = _preselection_body(
        _Store(), "20261030", 300, offset=0,
        allow_legacy_flat=False, pool_store_class=_PoolStore,
    )

    assert response["ok"] is True
    assert response["data_status"] == "ALL_ROWS_QUARANTINED"
    assert response["rows"] == []
    assert response["original_row_count"] == 1
    assert response["effective_row_count"] == 0
    assert response["quarantined_row_count"] == 1
    assert "ALL_ROWS_QUARANTINED_AS_INVALID_A_SHARE" in response["blocking_reasons"]


def test_the_projection_helper_reports_an_all_quarantined_set():
    from apps.api.v4_api.preselection_service import _preselection_response_from_pools

    pools = [_pool([_row("261029", 1, "申昊科技")])]
    response = _preselection_response_from_pools(
        pools, trade_date="20261030", limit=50, offset=0, apply_review_sources=False
    )
    assert response["data_status"] == "ALL_ROWS_QUARANTINED"
    assert response["effective_row_count"] == 0
    assert response["original_row_count"] == 1
    assert response["quarantined_row_count"] == 1


def test_the_lane_response_quarantines_saved_archive_rows():
    from apps.api.v4_api.research_lane_router import _lane_response

    archive = {
        "articles": [],
        "stock_pool": [
            {"stock_code": "261029", "stock_name": "申昊科技"},
            {"stock_code": "600519", "stock_name": "贵州茅台"},
        ],
        "stock_pool_count": 2,
        "cannot_confirm": [],
        "source_schema_version": "v3_5.research_archive.v1",
        "source_generated_at": "20261030T150000+08:00",
        "source_counts": {},
        "article_count": 0,
    }
    response = _lane_response(
        archive, research_date="20261030", endpoint_mode="EXACT"
    )

    assert [row["stock_code"] for row in response["stock_research_daily"]] == ["600519"]
    assert response["stock_pool_original_count"] == 2
    assert response["quarantined_row_count"] == 1
    assert response["stock_pool_quarantined"][0]["stock_code"] == "261029"


def test_the_hourly_response_quarantines_source_rows():
    from apps.api.v4_api.research_router import _hourly_response

    response = _hourly_response(
        {
            "evidence_rows": [],
            "stock_research_daily": [{"stock_code": "261029", "stock_name": "申昊科技"}],
        },
        endpoint_mode="EXACT",
        archive_date="20261030",
        slot="1500",
    )
    assert response["stock_pool"] == []
    assert response["stock_count"] == 0
    assert response["quarantined_row_count"] == 1
