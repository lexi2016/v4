from __future__ import annotations

from collections import OrderedDict

import pytest

from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider


def _minute_rows() -> list[OrderedDict[str, float]]:
    return [
        OrderedDict(price=10.0, vol=100),
        OrderedDict(price=10.2, vol=200),
        OrderedDict(price=10.1, vol=300),
    ]


class FakeTdxApi:
    def __init__(self, rows=None) -> None:
        self.rows = _minute_rows() if rows is None else rows
        self.calls: list[tuple[int, str, int]] = []
        self.transaction_calls: list[tuple[int, str, int, int, int]] = []
        self.daily_calls: list[tuple[int, int, str, int, int]] = []
        self.disconnected = False

    def get_history_minute_time_data(self, market: int, code: str, trade_date: int):
        self.calls.append((market, code, trade_date))
        return self.rows

    def get_history_transaction_data(
        self,
        market: int,
        code: str,
        start: int,
        count: int,
        trade_date: int,
    ):
        self.transaction_calls.append((market, code, start, count, trade_date))
        return [
            OrderedDict(time="09:25", price=10.5, vol=0, buyorsell=8),
            OrderedDict(time="09:25", price=10.5, vol=1200, buyorsell=2),
            OrderedDict(time="09:30", price=10.8, vol=800, buyorsell=1),
        ]

    def get_security_bars(
        self,
        category: int,
        market: int,
        code: str,
        start: int,
        count: int,
    ):
        self.daily_calls.append((category, market, code, start, count))
        return [
            {"year": 2026, "month": 7, "day": 29, "close": 10.0},
            {"year": 2026, "month": 7, "day": 30, "close": 10.5},
        ]

    def disconnect(self) -> None:
        self.disconnected = True


class PartialTdxApi(FakeTdxApi):
    def get_history_minute_time_data(self, market: int, code: str, trade_date: int):
        self.calls.append((market, code, trade_date))
        return [] if code == "000002" else self.rows


class PagedAuctionTdxApi(FakeTdxApi):
    def get_history_transaction_data(
        self,
        market: int,
        code: str,
        start: int,
        count: int,
        trade_date: int,
    ):
        self.transaction_calls.append((market, code, start, count, trade_date))
        if start == 0:
            return [OrderedDict(time="13:00", price=11.0, vol=100, buyorsell=1)]
        return [OrderedDict(time="09:25", price=10.5, vol=1200, buyorsell=2)]


@pytest.mark.parametrize(("stage_id", "cutoff", "count", "window", "last_time"), [
    ("STAGE_0930_0935", "09:35:05", 5, "09:31:00-09:35:00", "09:35:00"),
    ("STAGE_0935_0940", "09:40:05", 5, "09:36:00-09:40:00", "09:40:00"),
    ("STAGE_0940_0945", "09:45:05", 5, "09:41:00-09:45:00", "09:45:00"),
    ("STAGE_0945_1030", "10:30:00", 45, "09:46:00-10:30:00", "10:30:00"),
    ("STAGE_1300_1315", "13:15:00", 15, "13:01:00-13:15:00", "13:15:00"),
    ("STAGE_1445_1500", "15:00:00", 15, "14:46:00-15:00:00", "15:00:00"),
])
def test_tdx_replay_uses_the_exact_legacy_window_for_each_a_stage(
    stage_id: str, cutoff: str, count: int, window: str, last_time: str,
) -> None:
    rows = [OrderedDict(price=10 + index / 100, vol=1) for index in range(240)]
    payload = TdxMinuteReplayProvider(
        api_factory=lambda: FakeTdxApi(rows=rows)
    ).snapshot(
        ["A.000001"], trade_date="20260730", stage_id=stage_id,
        cutoff_at=f"2026-07-30T{cutoff}",
    )
    row = payload["rows"][0]
    assert row["source_bar_count"] == count
    assert row["expected_bar_count"] == count
    assert row["stage_window_complete"] is True
    assert row["stage_window"] == window
    assert row["source_last_bar_time"] == last_time


def test_tdx_replay_truncates_rows_at_declared_stage_cutoff() -> None:
    api = FakeTdxApi()
    provider = TdxMinuteReplayProvider(api_factory=lambda: api)

    payload = provider.snapshot(
        ["A.000001"],
        trade_date="20260730",
        stage_id="STAGE_0930_0935",
        cutoff_at="2026-07-30T09:35:05",
    )

    assert api.calls == [(0, "000001", 20260730)]
    assert api.disconnected is True
    assert payload["captured_at"] == "2026-07-30T09:35:05"
    assert payload["temporal_cutoff_safe"] is True
    assert payload["source"] == "PYTDX_A_SHARE_1MIN_REPLAY"
    assert payload["data_level"] == "STAGE_RTDATA_LATE_REPLAY"
    assert payload["rows"] == [
        {
            "symbol": "A.000001",
            "open_price": 10.0,
            "last_price": 10.1,
            "high_price": 10.2,
            "low_price": 10.0,
            "turnover": 607000.0,
            "volume": 600.0,
            "bid_price1": None,
            "ask_price1": None,
            "bid_vol1": None,
            "ask_vol1": None,
            "source_bar_count": 3,
            "expected_bar_count": 5,
            "stage_window_complete": False,
            "stage_window": "09:31:00-09:35:00",
            "source_last_bar_time": "09:33:00",
            "data_level": "DATA_PARTIAL_PYTDX_1MIN_BAR",
            "recommendation_status": "WATCH_ONLY",
        }
    ]
    assert payload["cannot_confirm"] == ["PYTDX_STAGE_WINDOW_PARTIAL: A.000001"]
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


def test_tdx_replay_reads_exact_date_0925_auction_transactions() -> None:
    api = FakeTdxApi()
    provider = TdxMinuteReplayProvider(api_factory=lambda: api)

    payload = provider.snapshot(
        ["A.000001"],
        trade_date="20260730",
        stage_id="STAGE_0925",
        cutoff_at="2026-07-30T09:25:05",
    )

    assert api.calls == []
    assert api.transaction_calls == [(0, "000001", 0, 2000, 20260730)]
    assert api.daily_calls == [(9, 0, "000001", 0, 80)]
    assert payload["source"] == "PYTDX_A_SHARE_0925_HISTORY_TRANSACTION"
    assert payload["temporal_cutoff_safe"] is True
    assert payload["rows"] == [
        {
            "symbol": "A.000001",
            "open_price": 10.5,
            "last_price": 10.5,
            "high_price": 10.5,
            "low_price": 10.5,
            "prev_close_price": 10.0,
            "turnover": 1_260_000.0,
            "volume": 1200.0,
            "bid_price1": None,
            "ask_price1": None,
            "bid_vol1": None,
            "ask_vol1": None,
            "source_tick_count": 1,
            "source_last_tick_time": "09:25:00",
            "source_method": "pytdx.hq.get_history_transaction_data",
            "previous_close_source_method": "pytdx.hq.get_security_bars.daily",
            "data_level": "PYTDX_A_SHARE_0925_HISTORY_TRANSACTION_L0",
            "recommendation_status": "WATCH_ONLY",
        }
    ]
    assert payload["cannot_confirm"] == [
        "PYTDX_0925_HISTORY_TRANSACTION_L0_NO_ORDER_BOOK"
    ]


def test_tdx_0925_replay_pages_back_to_the_auction_minute() -> None:
    api = PagedAuctionTdxApi()

    payload = TdxMinuteReplayProvider(api_factory=lambda: api).snapshot(
        ["A.000001"],
        trade_date="20260730",
        stage_id="STAGE_0925",
        cutoff_at="2026-07-30T09:25:05",
    )

    assert api.transaction_calls == [
        (0, "000001", 0, 2000, 20260730),
        (0, "000001", 2000, 2000, 20260730),
    ]
    assert payload["rows"][0]["source_last_tick_time"] == "09:25:00"


def test_tdx_replay_rejects_hk_symbols_and_fails_explicitly_on_empty_source() -> None:
    with pytest.raises(ValueError, match="A-share"):
        TdxMinuteReplayProvider(api_factory=FakeTdxApi).snapshot(
            ["HK.00001"],
            trade_date="20260730",
            stage_id="STAGE_1445_1500",
            cutoff_at="2026-07-30T15:00:00",
        )


def test_tdx_replay_keeps_good_symbols_when_one_symbol_has_no_rows() -> None:
    payload = TdxMinuteReplayProvider(api_factory=PartialTdxApi).snapshot(
        ["A.000001", "A.000002"],
        trade_date="20260730",
        stage_id="STAGE_0930_0935",
        cutoff_at="2026-07-30T09:35:05",
    )

    assert [row["symbol"] for row in payload["rows"]] == ["A.000001"]
    assert payload["cannot_confirm"] == [
        "PYTDX_MINUTE_ROWS_MISSING: A.000002",
        "PYTDX_STAGE_WINDOW_PARTIAL: A.000001",
    ]

    with pytest.raises(ValueError, match="no minute rows"):
        TdxMinuteReplayProvider(api_factory=lambda: FakeTdxApi(rows=[])).snapshot(
            ["A.000001"],
            trade_date="20260730",
            stage_id="STAGE_0930_0935",
            cutoff_at="2026-07-30T09:35:05",
        )
