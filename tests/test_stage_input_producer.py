from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest

from contracts.stages import FROZEN_STAGE_IDS
from domains.stage_input_producer import StageInputProducer
from domains.stages import StageRunner
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import POOL_ORDER, PreselectionPoolStore
from infrastructure.stage_store import StageStore


def _preselection(date: str, rows: list[dict], *, complete: bool = True) -> dict:
    lane = "CANONICAL_MAIN" if complete else "NON_CANONICAL_OBSERVATION"
    selector = "READY" if complete else "CANNOT_CONFIRM"
    status = "READY_WITH_ROWS" if complete else "PARTIAL_WITH_ROWS"
    return {
        "schema_version": "v3_preselection_pools.v1",
        "trade_date": date,
        "producer_status": "CANONICAL_COMPLETE" if complete else "PARTIAL",
        "data_status": status,
        "module_id": "unified_preselection_pools",
        "write_policy": "read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
        "canonical_main_pool_confirmed": complete,
        "source_lane": lane,
        "selector_status": selector,
        "strict_0_2_status": "STRICT_0_2_READY" if complete else "CANNOT_CONFIRM",
        "pools": [{"pool_id": "main", "rows": deepcopy(rows)}],
        "unified_rows": deepcopy(rows),
        "a_source_only_rows": [deepcopy(row) for row in rows if row["symbol"].startswith("A.")],
        "a_all_pool_rows": [deepcopy(row) for row in rows if row["symbol"].startswith("A.")],
        "rows": deepcopy(rows),
        "startup_ensure": {},
        "evidence_paths": ["receipts/source.json"],
        "cannot_confirm": [],
    }


class FakeQuotes:
    def __init__(self, captured_at: str = "2026-07-30T09:25:00") -> None:
        self.captured_at = captured_at
        self.calls: list[tuple] = []

    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str) -> dict:
        self.calls.append((tuple(symbols), trade_date, stage_id, cutoff_at))
        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "captured_at": self.captured_at,
            "temporal_cutoff_safe": True,
            "source": "FAKE_READ_ONLY",
            "rows": [
                {
                    "symbol": "A.000001",
                    "open_price": 11,
                    "last_price": 11,
                    "prev_close_price": 10,
                    "turnover": 200_000_000,
                },
                {
                    "symbol": "HK.00001",
                    "last_price": 11.2,
                    "prev_close_price": 10,
                    "turnover": 50_000_000,
                },
            ],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }


class QuotesWithStageUniverse(FakeQuotes):
    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str) -> dict:
        payload = super().snapshot(
            symbols,
            trade_date=trade_date,
            stage_id=stage_id,
            cutoff_at=cutoff_at,
        )
        payload["rows"].append(
            {
                "symbol": "HK.00002",
                "pct_chg": 2.5,
                "data_level": "MIGRATED_REFERENCE_WORKBENCH",
                "recommendation_status": "WATCH_ONLY",
            }
        )
        return payload


class AuctionGapQuotes(FakeQuotes):
    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str) -> dict:
        payload = super().snapshot(
            symbols,
            trade_date=trade_date,
            stage_id=stage_id,
            cutoff_at=cutoff_at,
        )
        payload["rows"] = [
            row for row in payload["rows"] if row["symbol"].startswith("HK.")
        ]
        payload["cannot_confirm"] = [
            "PYTDX_MINUTE_REPLAY_HAS_NO_CALL_AUCTION_EVIDENCE"
        ]
        return payload


class AllStageQuotes:
    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str) -> dict:
        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "captured_at": cutoff_at,
            "temporal_cutoff_safe": True,
            "source": "FROZEN_ALL_STAGE_TEST",
            "rows": [{
                "symbol": symbol, "open_price": 10.0, "last_price": 10.2,
                "prev_close_price": 10.0, "high_price": 10.3, "low_price": 9.9,
                "turnover": 100_000_000, "stage_window_complete": True,
                "recommendation_status": "WATCH_ONLY",
            } for symbol in symbols],
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        }


class QuotesForRequestedSymbols(FakeQuotes):
    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str) -> dict:
        payload = super().snapshot(
            symbols,
            trade_date=trade_date,
            stage_id=stage_id,
            cutoff_at=cutoff_at,
        )
        payload["rows"] = [
            {
                "symbol": symbol,
                "open_price": 11,
                "last_price": 11,
                "prev_close_price": 10,
                "turnover": 200_000_000,
                "stage_window_complete": True,
            }
            for symbol in symbols
        ]
        return payload


def _independent_pool(date: str, pool_id: str, symbols: list[str]) -> dict:
    market = "HK" if pool_id == "hkconnect_d1_top100" else "A"
    return {
        "schema_version": "v3_5.preselection_pool.v1", "trade_date": date,
        "pool_id": pool_id, "display_name": pool_id, "market": market,
        "status": "available" if symbols else "CANNOT_CONFIRM", "producer_id": "TEST",
        "source_role": "RAW_SOURCE" if symbols else "EXPECTED_MISSING",
        "source_path": f"fixtures/{pool_id}.csv" if symbols else "",
        "source_sha256": hashlib.sha256(pool_id.encode()).hexdigest(),
        "rows": [{
            "symbol": symbol, "market": market, "pool_id": pool_id,
            "pool_rank": index, "pool_score": 100 - index,
            "recommendation_status": "WATCH_ONLY",
        } for index, symbol in enumerate(symbols, start=1)],
        "cannot_confirm": [] if symbols else ["EXPECTED_MISSING"],
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }


def test_native_producer_builds_verified_stage_input_from_canonical_pool_and_quotes(tmp_path) -> None:
    data_store = NativeDataStore(tmp_path / "data")
    rows = [
        {"symbol": "A.000001", "pool_score": 100, "recommendation_status": "WATCH_ONLY"},
        {
            "symbol": "HK.00001",
            "circular_market_cap_hkd_yi": 80,
            "source_universe": "LOW_FLOAT_FILTER",
            "recommendation_status": "WATCH_ONLY",
        },
    ]
    data_store.import_payload(_preselection("20260730", rows))
    provider = FakeQuotes()
    stage_store = StageStore(data_store.root)

    produced = StageInputProducer(data_store, stage_store, provider).produce("20260730", "STAGE_0925")

    assert produced["status"] == "STAGE_INPUT_READY"
    assert provider.calls == [
        (("A.000001", "HK.00001"), "20260730", "STAGE_0925", "2026-07-30T09:25:05")
    ]
    workbench = StageRunner(stage_store).ensure("20260730", "STAGE_0925")
    assert workbench["ensure_status"] == "STAGE_RUN_COMPLETE"
    artifact = StageRunner(stage_store).read_workbench("20260730", "STAGE_0925")
    assert artifact["selected_a_rows"] == 1
    assert artifact["selected_hk_rows"] == 1
    assert artifact["selection_mode"] == "V3_5_NATIVE_STAGE_SCORE_V1"


def test_native_producer_aggregates_every_traceable_a_pool_row(tmp_path) -> None:
    data_store = NativeDataStore(tmp_path / "data")
    pool_symbols = {
        "a_d1_premarket_pool": ["A.000001"],
        "a_d1_fupan_watchlist_pool": ["A.000002"],
        "a_d1_stage7_fenshi_review_pool": ["A.000002"],
        "a_share_research_recommendation_pool": ["A.000003"],
        "a_share_baimao_research_map": ["A.000004"],
        "hkconnect_d1_top100": ["HK.00001"],
        "wechat_public_account_v3_preselect": ["A.000005"],
    }
    independent = PreselectionPoolStore(data_store.root)
    for pool_id in POOL_ORDER:
        independent.materialize(_independent_pool("20260730", pool_id, pool_symbols[pool_id]))
    provider = QuotesForRequestedSymbols()

    produced = StageInputProducer(data_store, StageStore(data_store.root), provider).produce(
        "20260730", "STAGE_0925"
    )
    payload, _ = StageStore(data_store.root).read_input("20260730", "STAGE_0925")

    assert provider.calls[0][0] == (
        "A.000001",
        "A.000002",
        "A.000003",
        "A.000004",
        "A.000005",
        "HK.00001",
    )
    assert produced["pool_status"] == "INDEPENDENT_GRAPH_POOLS"
    assert payload["market_status"] == {"A": "READY", "HK": "READY"}
    assert [row["symbol"] for row in payload["rows"]["A"]] == [
        "A.000001",
        "A.000002",
        "A.000003",
        "A.000004",
        "A.000005",
    ]
    assert [row["symbol"] for row in payload["rows"]["HK"]] == ["HK.00001"]
    assert all("preselection_pools/20260730/" in item["path"] for item in payload["source_evidence"][:-1])


def test_quote_coverage_gap_keeps_a_unconfirmed_and_hk_d1_only(tmp_path) -> None:
    data_store = NativeDataStore(tmp_path / "data")
    pool_symbols = {
        "a_d1_premarket_pool": ["A.000001"],
        "a_d1_fupan_watchlist_pool": ["A.000002"],
        "a_d1_stage7_fenshi_review_pool": [],
        "a_share_research_recommendation_pool": ["A.000003"],
        "a_share_baimao_research_map": ["A.000004"],
        "hkconnect_d1_top100": ["HK.00001"],
        "wechat_public_account_v3_preselect": ["A.000005"],
    }
    independent = PreselectionPoolStore(data_store.root)
    for pool_id in POOL_ORDER:
        independent.materialize(_independent_pool("20260730", pool_id, pool_symbols[pool_id]))
    provider = FakeQuotes()
    stage_store = StageStore(data_store.root)

    StageInputProducer(data_store, stage_store, provider).produce("20260730", "STAGE_0925")

    payload, _ = stage_store.read_input("20260730", "STAGE_0925")
    assert provider.calls[0][0] == (
        "A.000001",
        "A.000002",
        "A.000003",
        "A.000004",
        "A.000005",
        "HK.00001",
    )
    assert payload["market_status"]["A"] == "CANNOT_CONFIRM"
    assert payload["source_summary"]["quote_coverage"]["A"] == {
        "requested": 5,
        "returned": 1,
        "missing": 4,
    }
    assert [row["symbol"] for row in payload["rows"]["HK"]] == ["HK.00001"]


def test_valid_traceable_a_rows_survive_missing_sibling_pool(tmp_path) -> None:
    data_store = NativeDataStore(tmp_path / "data")
    independent = PreselectionPoolStore(data_store.root)
    valid = independent.materialize(
        _independent_pool("20260730", "a_d1_premarket_pool", ["A.000001"])
    )
    stage_store = StageStore(data_store.root)
    producer = StageInputProducer(data_store, stage_store, QuotesForRequestedSymbols())

    produced = producer.produce("20260730", "STAGE_0925")
    payload, _ = stage_store.read_input("20260730", "STAGE_0925")

    assert produced["pool_status"] == "PARTIAL"
    assert payload["market_status"]["A"] == "CANNOT_CONFIRM"
    assert [row["symbol"] for row in payload["rows"]["A"]] == ["A.000001"]
    assert any(
        "POOL_ARTIFACT_MISSING:a_share_baimao_research_map" in reason
        for reason in payload["source_summary"]["cannot_confirm"]
    )
    evidence = next(
        item
        for item in payload["source_evidence"]
        if item["path"].endswith("a_d1_premarket_pool.json")
    )
    assert evidence["sha256"] == valid["sha256"]


def test_bad_a_pool_is_quarantined_without_dropping_valid_rows(tmp_path) -> None:
    data_store = NativeDataStore(tmp_path / "data")
    independent = PreselectionPoolStore(data_store.root)
    independent.materialize(
        _independent_pool("20260730", "a_d1_premarket_pool", ["A.000001"])
    )
    bad = independent.materialize(
        _independent_pool("20260730", "a_share_baimao_research_map", ["A.000004"])
    )
    (data_store.root / bad["receipt_path"]).write_text('{"wrong":true}', encoding="utf-8")
    stage_store = StageStore(data_store.root)

    StageInputProducer(data_store, stage_store, QuotesForRequestedSymbols()).produce(
        "20260730", "STAGE_0925"
    )
    payload, _ = stage_store.read_input("20260730", "STAGE_0925")

    assert payload["market_status"]["A"] == "CANNOT_CONFIRM"
    assert [row["symbol"] for row in payload["rows"]["A"]] == ["A.000001"]
    assert any(
        "a_share_baimao_research_map" in reason and "receipt" in reason.lower()
        for reason in payload["source_summary"]["cannot_confirm"]
    )


def test_stage_runner_workbench_keeps_partial_a_as_watch_only(tmp_path) -> None:
    data_store = NativeDataStore(tmp_path / "data")
    independent = PreselectionPoolStore(data_store.root)
    independent.materialize(
        _independent_pool("20260730", "a_d1_premarket_pool", ["A.000001"])
    )
    stage_store = StageStore(data_store.root)
    runner = StageRunner(
        stage_store,
        input_producer=StageInputProducer(
            data_store, stage_store, QuotesForRequestedSymbols()
        ),
    )

    ensured = runner.ensure("20260730", "STAGE_0925")
    workbench = runner.read_workbench("20260730", "STAGE_0925", 50)

    assert ensured["ensure_status"] == "STAGE_RUN_COMPLETE"
    assert workbench["stage"]["status"] == "PARTIAL_WITH_WATCH_ROWS"
    assert workbench["markets"]["A"]["source_status"] == "CANNOT_CONFIRM"
    assert workbench["selected_a_rows"] == 1
    assert workbench["unified_rows"][0]["symbol"] == "A.000001"
    assert workbench["unified_rows"][0]["recommendation_status"] == "WATCH_ONLY"
    assert any(
        "POOL_ARTIFACT_MISSING:a_share_baimao_research_map" in item["reason"]
        for item in workbench["sidebar"]["cannot_confirm_items"]
    )
    assert workbench["startup_ensure"]["source_evidence"]
    assert workbench["production_allowed"] is False
    assert workbench["buy_gate_updated"] is False
    assert workbench["orders_sent"] is False


def test_stage_input_keeps_all_a_candidates_beyond_two_hundred_rows(tmp_path) -> None:
    data_store = NativeDataStore(tmp_path / "data")
    symbols = [f"A.{index:06d}" for index in range(1, 208)]
    counts = (60, 30, 30, 30, 30, 27)
    pool_symbols: dict[str, list[str]] = {}
    offset = 0
    for pool_id, count in zip(
        (
            "a_d1_premarket_pool",
            "a_d1_fupan_watchlist_pool",
            "a_d1_stage7_fenshi_review_pool",
            "a_share_research_recommendation_pool",
            "a_share_baimao_research_map",
            "wechat_public_account_v3_preselect",
        ),
        counts,
    ):
        pool_symbols[pool_id] = symbols[offset : offset + count]
        offset += count
    pool_symbols["hkconnect_d1_top100"] = ["HK.00001"]
    independent = PreselectionPoolStore(data_store.root)
    for pool_id in POOL_ORDER:
        independent.materialize(_independent_pool("20260730", pool_id, pool_symbols[pool_id]))
    provider = QuotesForRequestedSymbols()
    stage_store = StageStore(data_store.root)

    StageInputProducer(data_store, stage_store, provider).produce("20260730", "STAGE_0925")
    payload, _ = stage_store.read_input("20260730", "STAGE_0925")

    assert len(provider.calls[0][0]) == 208
    assert len(payload["rows"]["A"]) == 207
    assert {row["symbol"] for row in payload["rows"]["A"]} == set(symbols)
    assert "A.000151" in {row["symbol"] for row in payload["rows"]["A"]}
    assert "A.000181" in {row["symbol"] for row in payload["rows"]["A"]}
    assert payload["rows"]["HK"][0]["symbol"] == "HK.00001"


def test_independent_graph_pools_materialize_all_eight_stage_identities(tmp_path) -> None:
    data_store = NativeDataStore(tmp_path / "data")
    pool_symbols = {
        "a_d1_premarket_pool": ["A.000001"],
        "a_d1_fupan_watchlist_pool": ["A.000002"],
        "a_d1_stage7_fenshi_review_pool": ["A.000003"],
        "a_share_research_recommendation_pool": [],
        "a_share_baimao_research_map": [],
        "hkconnect_d1_top100": ["HK.00001"],
        "wechat_public_account_v3_preselect": [],
    }
    independent = PreselectionPoolStore(data_store.root)
    for pool_id in POOL_ORDER:
        independent.materialize(_independent_pool("20260730", pool_id, pool_symbols[pool_id]))
    stage_store = StageStore(data_store.root)
    runner = StageRunner(
        stage_store,
        input_producer=StageInputProducer(data_store, stage_store, AllStageQuotes()),
    )

    for stage_id in FROZEN_STAGE_IDS:
        result = runner.ensure("20260730", stage_id)
        page = runner.read_workbench("20260730", stage_id, 50)
        assert result["ensure_status"] == "STAGE_RUN_COMPLETE"
        assert page["stage"]["stage_id"] == stage_id
        assert page["selected_total_rows"] > 0
        assert page["production_allowed"] is False
        assert page["buy_gate_updated"] is False
        assert page["orders_sent"] is False


def test_native_producer_rejects_evidence_after_the_stage_cutoff(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    rows = [{"symbol": "A.000001", "recommendation_status": "WATCH_ONLY"}]
    store.import_payload(_preselection("20260730", rows))
    provider = FakeQuotes(captured_at="2026-07-30T09:25:06")

    with pytest.raises(ValueError, match="cutoff"):
        StageInputProducer(store, StageStore(store.root), provider).produce("20260730", "STAGE_0925")

    assert not (store.root / "stage_inputs" / "20260730" / "STAGE_0925.json").exists()


def test_native_producer_keeps_partial_pool_rows_observable_without_promoting_them(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    rows = [
        {"symbol": "A.000001", "recommendation_status": "WATCH_ONLY"},
        {"symbol": "HK.00001", "recommendation_status": "WATCH_ONLY"},
    ]
    store.import_payload(_preselection("20260730", rows, complete=False))
    provider = FakeQuotes()

    produced = StageInputProducer(store, StageStore(store.root), provider).produce(
        "20260730",
        "STAGE_0925",
    )
    payload, _ = StageStore(store.root).read_input("20260730", "STAGE_0925")

    assert produced["status"] == "STAGE_INPUT_READY_PARTIAL_POOL"
    assert produced["pool_status"] == "PARTIAL"
    assert payload["market_status"] == {"A": "CANNOT_CONFIRM", "HK": "CANNOT_CONFIRM"}
    assert len(payload["rows"]["A"]) == 1
    assert len(payload["rows"]["HK"]) == 1


def test_native_producer_rejects_hk_stage_universe_rows_outside_d1_pool(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    rows = [{"symbol": "A.000001", "recommendation_status": "WATCH_ONLY"}]
    store.import_payload(_preselection("20260730", rows, complete=False))

    StageInputProducer(
        store,
        StageStore(store.root),
        QuotesWithStageUniverse(captured_at="2026-07-30T15:00:00"),
    ).produce("20260730", "STAGE_1445_1500")
    payload, _ = StageStore(store.root).read_input("20260730", "STAGE_1445_1500")

    # Provider-only rows must never expand the frozen D-1 candidate pool.
    assert payload["rows"]["HK"] == []


def test_refresh_supersedes_a_previous_stage_input_with_an_audit_receipt(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_payload(_preselection(
        "20260730",
        [{"symbol": "A.000001", "recommendation_status": "WATCH_ONLY"}],
    ))
    provider = FakeQuotes(captured_at="2026-07-30T15:00:00")
    producer = StageInputProducer(store, StageStore(store.root), provider)
    producer.produce("20260730", "STAGE_1445_1500")
    first, first_sha = StageStore(store.root).read_input(
        "20260730",
        "STAGE_1445_1500",
    )
    assert first["rows"]["A"][0]["last_price"] == 11

    original_snapshot = provider.snapshot

    def changed_snapshot(*args, **kwargs):
        payload = original_snapshot(*args, **kwargs)
        payload["rows"][0]["last_price"] = 12
        return payload

    provider.snapshot = changed_snapshot
    refreshed = producer.refresh("20260730", "STAGE_1445_1500")
    second, second_sha = StageStore(store.root).read_input(
        "20260730",
        "STAGE_1445_1500",
    )

    assert refreshed["status"] == "STAGE_INPUT_REFRESHED"
    assert second["rows"]["A"][0]["last_price"] == 12
    assert second_sha != first_sha
    assert (
        store.root
        / f"receipts/stage_input_supersessions/20260730/STAGE_1445_1500/{first_sha}.json"
    ).is_file()


def test_hk_tail_stage_does_not_request_or_emit_a_share_rows(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_payload(_preselection("20260730", [
        {"symbol": "A.000001", "recommendation_status": "WATCH_ONLY"},
        {"symbol": "HK.00001", "recommendation_status": "WATCH_ONLY"},
    ]))
    provider = FakeQuotes(captured_at="2026-07-30T15:55:00")

    StageInputProducer(store, StageStore(store.root), provider).produce(
        "20260730",
        "STAGE_1545_1555",
    )
    payload, _ = StageStore(store.root).read_input(
        "20260730",
        "STAGE_1545_1555",
    )

    assert provider.calls[0][0] == ("HK.00001",)
    assert payload["rows"]["A"] == []
    assert len(payload["rows"]["HK"]) == 1


def test_auction_gap_is_explained_in_native_workbench_instead_of_generic_empty(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_payload(_preselection("20260730", [
        {"symbol": "A.000001", "recommendation_status": "WATCH_ONLY"},
        {"symbol": "HK.00001", "recommendation_status": "WATCH_ONLY"},
    ], complete=False))
    stage_store = StageStore(store.root)
    producer = StageInputProducer(store, stage_store, AuctionGapQuotes())
    producer.produce("20260730", "STAGE_0925")
    StageRunner(stage_store).ensure("20260730", "STAGE_0925")

    page = StageRunner(stage_store).read_workbench("20260730", "STAGE_0925")

    assert page["markets"]["A"]["requested_rows"] == 1
    assert page["markets"]["A"]["source_rows"] == 0
    assert "pytdx" in page["stage"]["display_status"]
    assert "竞价" in page["stage"]["display_status"]


def test_duplicate_pool_symbols_are_merged_before_stage_scoring(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_payload(_preselection("20260730", [
        {
            "symbol": "A.000001",
            "pool_id": "secondary",
            "pool_score": 90,
            "pool_rank": 20,
            "recommendation_status": "WATCH_ONLY",
        },
        {
            "symbol": "A.000001",
            "pool_id": "primary",
            "pool_score": 120,
            "pool_rank": 3,
            "recommendation_status": "WATCH_ONLY",
        },
        {
            "symbol": "HK.00001",
            "recommendation_status": "WATCH_ONLY",
        },
    ], complete=False))
    provider = FakeQuotes(captured_at="2026-07-30T15:00:00")

    StageInputProducer(store, StageStore(store.root), provider).produce(
        "20260730",
        "STAGE_1445_1500",
    )
    payload, _ = StageStore(store.root).read_input(
        "20260730",
        "STAGE_1445_1500",
    )

    assert len(payload["rows"]["A"]) == 1
    assert payload["rows"]["A"][0]["pool_id"] == "primary"
    assert payload["rows"]["A"][0]["pool_score"] == 120
