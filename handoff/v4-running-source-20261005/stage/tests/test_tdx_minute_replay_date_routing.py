from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest

import infrastructure.tdx_minute_replay_provider as replay_module
from infrastructure.tdx_minute_replay_provider import AuctionReplayError, TdxMinuteReplayProvider
from stage_center.live_collectors import collect_a_share_auction


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "stage_20260924_a0925_recovery"
CANARY_PATH = FIXTURE_ROOT / "readonly_quote_canary_20260924T114702_CST.json"
PAGING_PATH = FIXTURE_ROOT / "readonly_quote_paging_probe_20260924T114847_CST.json"
CANARY_SHA256 = "5bc6a8ec06f43abc2a2ab9169eff5acea1f47e3ee024d732462fd0bc1a4ac4a4"
PAGING_SHA256 = "e6853cd18627c02f5c72adc62ea9c9d4520e5a83948a84cfd15c5e759b9c246f"


def _read_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected_sha256
    return json.loads(raw)


def _real_transaction_rows(code: str, *, page: int) -> list[dict[str, Any]]:
    canary = _read_json(CANARY_PATH, CANARY_SHA256)
    observations = canary["a_share"]["observations"]
    item = next(row for row in observations if row["code"] == code)
    if page == 0:
        return item["methods"]["transaction_today_page0"]["raw_return"]
    if code == "300750" and page == 1800:
        paging = _read_json(PAGING_PATH, PAGING_SHA256)
        response = next(
            call for call in paging["calls"]
            if call["label"] == "transaction_today_page1_start1800"
        )
        return response["raw_return"]
    return []


def _real_same_day_history_rows(code: str) -> list[dict[str, Any]]:
    canary = _read_json(CANARY_PATH, CANARY_SHA256)
    item = next(row for row in canary["a_share"]["observations"] if row["code"] == code)
    response = item["methods"]["history_transaction_today_page0"]
    assert response["summary"]["row_count"] == 0
    return response["raw_return"]


class FrozenEvidenceApi:
    """SDK double populated only from the captured 2026-09-24 canaries."""

    def __init__(self) -> None:
        self.transaction_calls: list[tuple[int, str, int, int]] = []
        self.history_calls: list[tuple[int, str, int, int, int]] = []
        self.disconnected = False

    def get_transaction_data(self, market: int, code: str, start: int, count: int):
        self.transaction_calls.append((market, code, start, count))
        if count != 1800:
            raise AssertionError("same-day transaction page size changed")
        return _real_transaction_rows(code, page=start)

    def get_history_transaction_data(
        self, market: int, code: str, start: int, count: int, trade_date: int
    ):
        self.history_calls.append((market, code, start, count, trade_date))
        if trade_date == 20260924:
            return _real_same_day_history_rows(code)
        return [
            {"time": "09:25", "price": 7.25, "vol": 500, "buyorsell": 2}
        ]  # Deterministic SDK contract fixture for historical routing.

    def get_security_bars(self, category: int, market: int, code: str, start: int, count: int):
        return []

    def disconnect(self) -> None:
        self.disconnected = True


def _freeze_provider_clock(monkeypatch: pytest.MonkeyPatch, *values: str) -> None:
    class FrozenDateTime(datetime):
        _queue = iter(datetime.fromisoformat(value) for value in values)

        @classmethod
        def now(cls, tz=None):
            value = next(cls._queue)
            return value.astimezone(tz) if tz is not None else value

    monkeypatch.setattr(replay_module, "datetime", FrozenDateTime)


def test_same_day_recovery_uses_frozen_current_transaction_pages_and_real_capture_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FrozenEvidenceApi()
    _freeze_provider_clock(
        monkeypatch,
        "2026-09-24T11:49:00+08:00",
        "2026-09-24T11:49:03+08:00",
    )
    provider = TdxMinuteReplayProvider(api_factory=lambda: api)

    payload = provider.snapshot(
        ["A.000166", "A.300750"],
        trade_date="20260924",
        stage_id="STAGE_0925",
        cutoff_at="2026-09-24T09:25:05",
    )

    assert api.history_calls == []
    assert api.transaction_calls == [
        (0, "000166", 0, 1800),
        (0, "300750", 0, 1800),
        (0, "300750", 1800, 1800),
    ]
    assert api.disconnected is True
    assert payload["captured_at"] == "2026-09-24T11:49:03+08:00"
    assert payload["market_cutoff_at"] == "2026-09-24T09:25:05+08:00"
    assert payload["capture_mode"] == "RECOVERY"
    assert payload["temporal_cutoff_safe"] is True
    assert payload["source"] == "PYTDX_A_SHARE_0925_CURRENT_TRANSACTION"
    assert payload["source_method"] == "pytdx.hq.get_transaction_data"
    assert {
        row["symbol"]: (row["last_price"], row["volume"], row["source_last_tick_time"])
        for row in payload["rows"]
    } == {
        "A.000166": (4.47, 1065.0, "09:25:00"),
        "A.300750": (300.0, 2077.0, "09:25:00"),
    }
    assert {row["source_method"] for row in payload["rows"]} == {
        "pytdx.hq.get_transaction_data"
    }
    assert all(flag is False for flag in (
        payload["production_allowed"], payload["buy_gate_updated"], payload["orders_sent"]
    ))


def test_completed_date_uses_history_transaction_api_with_requested_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FrozenEvidenceApi()
    _freeze_provider_clock(
        monkeypatch,
        "2026-09-24T11:49:00+08:00",
        "2026-09-24T11:49:01+08:00",
    )
    provider = TdxMinuteReplayProvider(api_factory=lambda: api)

    payload = provider.snapshot(
        ["A.000001"], trade_date="20260923", stage_id="STAGE_0925",
        cutoff_at="2026-09-23T09:25:05",
    )

    assert api.transaction_calls == []
    assert api.history_calls == [(0, "000001", 0, 1800, 20260923)]
    assert payload["capture_mode"] == "RECOVERY"
    assert payload["captured_at"] == "2026-09-24T11:49:01+08:00"
    assert payload["market_cutoff_at"] == "2026-09-23T09:25:05+08:00"
    assert payload["rows"][0]["source_method"] == "pytdx.hq.get_history_transaction_data"


def test_future_trade_date_is_rejected_before_opening_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    api_factory_calls = 0

    def factory():
        nonlocal api_factory_calls
        api_factory_calls += 1
        raise AssertionError("future trade date must fail before network setup")

    _freeze_provider_clock(monkeypatch, "2026-09-24T11:49:00+08:00")
    provider = TdxMinuteReplayProvider(api_factory=factory)
    with pytest.raises(ValueError, match="future"):
        provider.snapshot(
            ["A.000001"], trade_date="20260925", stage_id="STAGE_0925",
            cutoff_at="2026-09-25T09:25:05",
        )
    assert api_factory_calls == 0


def test_current_api_uses_asia_shanghai_request_date_at_utc_day_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FrozenEvidenceApi()
    _freeze_provider_clock(
        monkeypatch,
        "2026-09-24T16:30:00+00:00",
        "2026-09-24T16:30:01+00:00",
    )
    provider = TdxMinuteReplayProvider(api_factory=lambda: api)

    with pytest.raises(AuctionReplayError):
        provider.snapshot(
            ["A.000001"], trade_date="20260925", stage_id="STAGE_0925",
            cutoff_at="2026-09-25T09:25:05",
        )

    assert api.history_calls == []
    assert api.transaction_calls == [(0, "000001", 0, 1800)]


def test_same_day_none_is_a_read_error_and_page_walk_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoneApi(FrozenEvidenceApi):
        def get_transaction_data(self, market: int, code: str, start: int, count: int):
            self.transaction_calls.append((market, code, start, count))
            return None

    none_api = NoneApi()
    _freeze_provider_clock(
        monkeypatch,
        "2026-09-24T11:49:00+08:00",
        "2026-09-24T11:49:01+08:00",
    )
    none_provider = TdxMinuteReplayProvider(api_factory=lambda: none_api)
    with pytest.raises(AuctionReplayError, match="PYTDX_TRANSACTION_RETURNED_NONE") as error:
        none_provider.snapshot(
            ["A.000001"], trade_date="20260924", stage_id="STAGE_0925",
            cutoff_at="2026-09-24T09:25:05",
        )
    assert error.value.diagnostics["read_error_count"] == 1
    assert error.value.diagnostics["pages_read"] == 1
    assert error.value.diagnostics["stop_reasons"] == {"READ_ERROR": 1}
    assert error.value.diagnostics["read_error_codes"] == ["PYTDX_TRANSACTION_RETURNED_NONE"]
    assert error.value.diagnostics["symbols"][0]["error_code"] == "PYTDX_TRANSACTION_RETURNED_NONE"

    class LongApi(FrozenEvidenceApi):
        def get_transaction_data(self, market: int, code: str, start: int, count: int):
            self.transaction_calls.append((market, code, start, count))
            return [{"time": "09:30", "price": 10.0, "vol": 100}]

    long_api = LongApi()
    _freeze_provider_clock(
        monkeypatch,
        "2026-09-24T11:49:00+08:00",
        "2026-09-24T11:49:01+08:00",
    )
    long_provider = TdxMinuteReplayProvider(api_factory=lambda: long_api)
    with pytest.raises(AuctionReplayError) as bounded_error:
        long_provider.snapshot(
            ["A.000001"], trade_date="20260924", stage_id="STAGE_0925",
            cutoff_at="2026-09-24T09:25:05",
        )
    assert bounded_error.value.diagnostics["pages_read"] == 16
    assert bounded_error.value.diagnostics["stop_reasons"] == {"PAGE_LIMIT": 1}
    assert [call[2] for call in long_api.transaction_calls] == list(range(0, 16 * 1800, 1800))
    assert {call[3] for call in long_api.transaction_calls} == {1800}


def test_today_tick_filter_requires_positive_exact_0925_and_matching_source_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MixedApi(FrozenEvidenceApi):
        def get_transaction_data(self, market: int, code: str, start: int, count: int):
            self.transaction_calls.append((market, code, start, count))
            return [
                {"time": "09:24", "price": 10.0, "vol": 500},
                {"time": "09:25", "price": 10.5, "vol": 0},
                {"time": "09:25", "price": 10.6, "vol": 100},
                {"time": "09:26", "price": 10.7, "vol": 200},
            ]

    api = MixedApi()
    _freeze_provider_clock(
        monkeypatch,
        "2026-09-24T11:49:00+08:00",
        "2026-09-24T11:49:01+08:00",
    )
    payload = TdxMinuteReplayProvider(api_factory=lambda: api).snapshot(
        ["A.000001"], trade_date="20260924", stage_id="STAGE_0925",
        cutoff_at="2026-09-24T09:25:05",
    )
    assert payload["rows"][0]["source_tick_count"] == 1
    assert payload["rows"][0]["volume"] == 100.0
    assert payload["rows"][0]["last_price"] == 10.6

    class BoundaryApi(FrozenEvidenceApi):
        def get_transaction_data(self, market: int, code: str, start: int, count: int):
            self.transaction_calls.append((market, code, start, count))
            if start == 0:
                return [{"time": "09:25", "price": 10.0, "vol": 0}]
            if start == 1800:
                return [{"time": "09:25", "price": 10.5, "vol": 100}]
            return []

    boundary_api = BoundaryApi()
    _freeze_provider_clock(
        monkeypatch,
        "2026-09-24T11:49:00+08:00",
        "2026-09-24T11:49:01+08:00",
    )
    boundary_payload = TdxMinuteReplayProvider(api_factory=lambda: boundary_api).snapshot(
        ["A.000001"], trade_date="20260924", stage_id="STAGE_0925",
        cutoff_at="2026-09-24T09:25:05",
    )
    assert boundary_api.transaction_calls == [
        (0, "000001", 0, 1800),
        (0, "000001", 1800, 1800),
    ]
    assert boundary_payload["rows"][0]["last_price"] == 10.5

    class CrossDateApi(MixedApi):
        def get_transaction_data(self, market: int, code: str, start: int, count: int):
            self.transaction_calls.append((market, code, start, count))
            return [{
                "time": "09:25", "datetime": "2026-09-23 09:25:00",
                "price": 10.6, "vol": 100,
            }]

    cross_date_api = CrossDateApi()
    _freeze_provider_clock(
        monkeypatch,
        "2026-09-24T11:49:00+08:00",
        "2026-09-24T11:49:01+08:00",
    )
    cross_date_provider = TdxMinuteReplayProvider(api_factory=lambda: cross_date_api)
    with pytest.raises(AuctionReplayError):
        cross_date_provider.snapshot(
            ["A.000001"], trade_date="20260924", stage_id="STAGE_0925",
            cutoff_at="2026-09-24T09:25:05",
        )


def _collector_payload(*, tick_time: str = "2026-09-24 09:25:00") -> dict[str, Any]:
    return {
        "schema_version": "v3_5.read_only_quote_batch.v1",
        "trade_date": "20260924",
        "stage_id": "STAGE_0925",
        "captured_at": "2026-09-24T11:49:03+08:00",
        "market_cutoff_at": "2026-09-24T09:25:05+08:00",
        "capture_mode": "RECOVERY",
        "source": "PYTDX_A_SHARE_0925_CURRENT_TRANSACTION",
        "source_method": "pytdx.hq.get_transaction_data",
        "temporal_cutoff_safe": True,
        "rows": [{
            "symbol": "A.000166",
            "open_price": 4.47,
            "last_price": 4.47,
            "high_price": 4.47,
            "low_price": 4.47,
            "prev_close_price": 4.40,
            "turnover": 4_764_150.0,
            "volume": 1065.0,
            "source_tick_count": 1,
            "source_last_tick_time": tick_time,
            "source_method": "pytdx.hq.get_transaction_data",
        }],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


class FrozenReplayProvider:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str):
        assert tuple(symbols) == ("A.000166",)
        assert (trade_date, stage_id, cutoff_at) == (
            "20260924", "STAGE_0925", "2026-09-24T09:25:05"
        )
        return self.payload


def _collect_replay(tmp_path: Path, payload: dict[str, Any]):
    return collect_a_share_auction(
        SimpleNamespace(trade_date="20260924", stage_id="STAGE_0925"),
        codes=("A.000166",),
        python_path=sys.executable,
        shared_root=tmp_path,
        replay_provider=FrozenReplayProvider(payload),
    )


def test_collector_accepts_explicit_recovery_but_keeps_actual_capture_and_0925_pit_time(
    tmp_path: Path,
) -> None:
    result = _collect_replay(tmp_path, _collector_payload())

    assert result.status == "READY"
    assert result.rows[0]["update_time"] == "2026-09-24 09:25:00"
    assert result.rows[0]["time"] == "2026-09-24 09:25:00"
    assert "replay_captured_at=2026-09-24T11:49:03+08:00" in result.source_evidence
    assert "replay_capture_mode=RECOVERY" in result.source_evidence
    assert "replay_market_cutoff_at=2026-09-24T09:25:05+08:00" in result.source_evidence
    assert "CANNOT_CONFIRM_NATURAL_0925_CAPTURE_RECOVERY_ONLY" in result.cannot_confirm


def test_collector_method_evidence_uses_consistent_row_method_when_envelope_omits_it(
    tmp_path: Path,
) -> None:
    payload = _collector_payload()
    payload.pop("source_method")

    result = _collect_replay(tmp_path, payload)

    assert result.status == "READY"
    assert "replay_method=pytdx.hq.get_transaction_data" in result.source_evidence


def test_collector_does_not_infer_history_method_when_row_and_envelope_omit_it(
    tmp_path: Path,
) -> None:
    payload = _collector_payload()
    payload.pop("source_method")
    payload["rows"][0].pop("source_method")

    result = _collect_replay(tmp_path, payload)

    assert result.status == "CANNOT_CONFIRM"
    assert not result.rows
    assert "replay_method=UNKNOWN" in result.source_evidence


def test_collector_rejects_recovery_rows_outside_exact_0925_and_unmarked_late_capture(
    tmp_path: Path,
) -> None:
    wrong_tick = _collect_replay(tmp_path, _collector_payload(tick_time="2026-09-24 09:24:00"))
    assert wrong_tick.status == "CANNOT_CONFIRM"
    assert not wrong_tick.rows

    unmarked = _collector_payload()
    unmarked["capture_mode"] = "NATURAL"
    unmarked_result = _collect_replay(tmp_path, unmarked)
    assert unmarked_result.status == "CANNOT_CONFIRM"
    assert not unmarked_result.rows

    unbound_cutoff = _collector_payload()
    unbound_cutoff.pop("market_cutoff_at")
    unbound_result = _collect_replay(tmp_path, unbound_cutoff)
    assert unbound_result.status == "CANNOT_CONFIRM"
    assert not unbound_result.rows

    wrong_method = _collector_payload()
    wrong_method["source_method"] = "pytdx.hq.get_security_quotes"
    wrong_method_result = _collect_replay(tmp_path, wrong_method)
    assert wrong_method_result.status == "CANNOT_CONFIRM"
    assert not wrong_method_result.rows
