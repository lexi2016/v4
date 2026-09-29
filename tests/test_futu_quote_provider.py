from __future__ import annotations

from datetime import datetime

from infrastructure.futu_quote_provider import FutuQuoteProvider, to_futu_symbol


class FakeFrame:
    def to_dict(self, *, orient: str):
        assert orient == "records"
        return [
            {
                "code": "SZ.000001",
                "open_price": 11,
                "last_price": 11.2,
                "prev_close_price": 10,
                "high_price": 11.3,
                "low_price": 10.8,
                "turnover": 200_000_000,
                "volume": 1000,
                "bid_price": [11.1],
                "ask_price": [11.2],
                "bid_vol": [600],
                "ask_vol": [400],
            },
            {
                "code": "HK.00001",
                "open_price": 10.5,
                "last_price": 11.2,
                "prev_close_price": 10,
                "high_price": 11.4,
                "low_price": 10.4,
                "turnover": 50_000_000,
                "volume": 2000,
                "bid_price": [11.1],
                "ask_price": [11.2],
                "bid_vol": [500],
                "ask_vol": [500],
            },
        ]


class FakeQuoteContext:
    def __init__(self) -> None:
        self.requested = []
        self.closed = False

    def get_market_snapshot(self, symbols):
        self.requested.append(symbols)
        return 0, FakeFrame()

    def close(self):
        self.closed = True


def test_futu_symbol_mapping_is_explicit_and_read_only() -> None:
    assert to_futu_symbol("A.000001") == "SZ.000001"
    assert to_futu_symbol("A.600000") == "SH.600000"
    assert to_futu_symbol("HK.00001") == "HK.00001"


def test_futu_provider_emits_cutoff_safe_normalized_quote_batch() -> None:
    context = FakeQuoteContext()
    provider = FutuQuoteProvider(
        context_factory=lambda: context,
        now=lambda: datetime.fromisoformat("2026-07-30T09:25:00"),
    )

    payload = provider.snapshot(
        ["A.000001", "HK.00001"],
        trade_date="20260730",
        stage_id="STAGE_0925",
        cutoff_at="2026-07-30T09:25:05",
    )

    assert context.requested == [["SZ.000001", "HK.00001"]]
    assert context.closed is True
    assert payload["temporal_cutoff_safe"] is True
    assert [row["symbol"] for row in payload["rows"]] == ["A.000001", "HK.00001"]
    assert payload["rows"][0]["bid_vol1"] == 600
    assert payload["production_allowed"] is False
    assert payload["orders_sent"] is False


def test_futu_provider_marks_late_snapshot_not_cutoff_safe() -> None:
    context = FakeQuoteContext()
    provider = FutuQuoteProvider(
        context_factory=lambda: context,
        now=lambda: datetime.fromisoformat("2026-07-30T09:25:06"),
    )

    payload = provider.snapshot(
        ["A.000001"],
        trade_date="20260730",
        stage_id="STAGE_0925",
        cutoff_at="2026-07-30T09:25:05",
    )

    assert payload["temporal_cutoff_safe"] is False
