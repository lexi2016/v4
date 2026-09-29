from __future__ import annotations

from infrastructure.stage_quote_provider import StageQuoteProvider


class LatePrimary:
    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str):
        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "captured_at": "2026-07-30T22:00:00",
            "temporal_cutoff_safe": False,
            "source": "FUTU_OPEND_READ_ONLY_SNAPSHOT",
            "rows": [{"symbol": symbol, "last_price": 999} for symbol in symbols],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }


class AReplay:
    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str):
        assert symbols == ["A.000001"]
        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "captured_at": cutoff_at,
            "temporal_cutoff_safe": True,
            "source": "PYTDX_A_SHARE_1MIN_REPLAY",
            "data_level": "STAGE_RTDATA_LATE_REPLAY",
            "rows": [
                {
                    "symbol": "A.000001",
                    "open_price": 10,
                    "last_price": 10.2,
                    "turnover": 1_000_000,
                    "data_level": "STAGE_RTDATA_LATE_REPLAY",
                    "recommendation_status": "WATCH_ONLY",
                }
            ],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }


class References:
    def read_reference_workbench(self, trade_date: str, stage_id: str):
        return {
            "trade_date": trade_date,
            "stage": {"stage_id": stage_id},
            "unified_rows": [
                {
                    "code": "HK.00001",
                    "market": "HK",
                    "current_change_pct": 3.2,
                    "support_primary_price": 10.1,
                    "pressure_price": 10.8,
                    "invalidation_price": 9.9,
                    "recommendation_status": "WATCH_ONLY",
                }
                ,
                {
                    "code": "HK.00002",
                    "market": "HK",
                    "current_change_pct": 2.1,
                    "recommendation_status": "WATCH_ONLY",
                },
            ],
        }


class BatchedPunctualPrimary:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str):
        self.batch_sizes.append(len(symbols))
        assert 1 <= len(symbols) <= 220
        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "captured_at": cutoff_at,
            "temporal_cutoff_safe": True,
            "source": "FUTU_OPEND_READ_ONLY_SNAPSHOT",
            "rows": [{"symbol": symbol, "last_price": 10} for symbol in symbols],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }


class Forbidden0925Primary(BatchedPunctualPrimary):
    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str):
        raise AssertionError("09:25 A-share data must use the locked tdxpy lane")


def test_primary_quotes_are_batched_without_exceeding_futu_limit() -> None:
    primary = BatchedPunctualPrimary()
    symbols = [f"A.{index:06d}" for index in range(221)] + ["HK.00001"]
    provider = StageQuoteProvider(
        primary=primary,
        a_replay=AReplay(),
        references=References(),
    )

    payload = provider.snapshot(
        symbols,
        trade_date="20260730",
        stage_id="STAGE_0930_0935",
        cutoff_at="2026-07-30T09:35:00",
    )

    assert primary.batch_sizes == [220, 2]
    assert payload["temporal_cutoff_safe"] is True
    assert payload["source"] == "FUTU_OPEND_READ_ONLY_SNAPSHOT"
    assert len(payload["rows"]) == 222
    assert payload["production_allowed"] is False
    assert payload["orders_sent"] is False


def test_0925_uses_tdxpy_for_a_shares_without_calling_futu() -> None:
    provider = StageQuoteProvider(
        primary=Forbidden0925Primary(),
        a_replay=AReplay(),
        references=References(),
    )

    payload = provider.snapshot(
        ["A.000001", "HK.00001"],
        trade_date="20260730",
        stage_id="STAGE_0925",
        cutoff_at="2026-07-30T09:25:05",
    )

    assert payload["source"] == "V3_5_TDXPY_0925_COMPOSITE"
    assert payload["component_sources"] == [
        "PYTDX_A_SHARE_1MIN_REPLAY",
        "V3_5_MIGRATED_REFERENCE_SNAPSHOT",
    ]
    assert [row["symbol"] for row in payload["rows"]] == [
        "A.000001",
        "HK.00001",
        "HK.00002",
    ]


def test_late_primary_is_replaced_by_cutoff_safe_a_replay_and_local_hk_reference() -> None:
    provider = StageQuoteProvider(
        primary=LatePrimary(),
        a_replay=AReplay(),
        references=References(),
    )

    payload = provider.snapshot(
        ["A.000001", "HK.00001"],
        trade_date="20260730",
        stage_id="STAGE_1445_1500",
        cutoff_at="2026-07-30T15:00:00",
    )

    assert payload["temporal_cutoff_safe"] is True
    assert payload["source"] == "V3_5_CUTOFF_SAFE_COMPOSITE"
    assert [row["symbol"] for row in payload["rows"]] == [
        "A.000001",
        "HK.00001",
        "HK.00002",
    ]
    assert payload["rows"][0]["last_price"] == 10.2
    assert payload["rows"][1]["pct_chg"] == 3.2
    assert payload["rows"][1]["support_primary_price"] == 10.1
    assert payload["rows"][1]["data_level"] == "MIGRATED_REFERENCE_WORKBENCH"
    assert all(row.get("last_price") != 999 for row in payload["rows"])
    assert payload["production_allowed"] is False
    assert payload["orders_sent"] is False
