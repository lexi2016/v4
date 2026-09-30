"""Read-only A-share stage replay from pytdx one-minute history."""
from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Callable, Sequence

from contracts.stages import STAGE_BAR_WINDOWS


_TRANSACTION_PAGE_SIZE = 2000
_TRANSACTION_MAX_PAGES = 16


_DIAGNOSTIC_COUNTS = (
    "pages_read", "raw_tick_count", "exact_time_count", "time_mismatch_count",
    "numeric_rejection_count", "accepted_tick_count", "invalid_tick_count",
)


def _auction_diagnostics(symbols: list[dict[str, Any]], accepted_rows: int) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    times: list[str] = []
    for item in symbols:
        reason = str(item.get("stop_reason") or "UNKNOWN")
        reasons[reason] = reasons.get(reason, 0) + 1
        for value in item.get("time_examples", []):
            if value not in times and len(times) < 5:
                times.append(value)
    return {
        "schema_version": "PYTDX_0925_DIAGNOSTICS_V1",
        **{key: sum(item.get(key, 0) for item in symbols) for key in _DIAGNOSTIC_COUNTS},
        "accepted_symbol_count": accepted_rows,
        "read_error_count": reasons.get("READ_ERROR", 0),
        "stop_reasons": reasons, "time_examples": times, "symbols": symbols,
    }


class AuctionReplayError(ValueError):
    """Keep structured zero-row diagnostics; existing ValueError callers still fail closed."""
    def __init__(self, message: str, diagnostics: dict[str, Any]) -> None:
        self.diagnostics = diagnostics
        summary = {key: value for key, value in diagnostics.items() if key != "symbols"}
        super().__init__(message + "; " + json.dumps(summary, ensure_ascii=False, sort_keys=True))


def _minute_times() -> list[str]:
    morning = [
        f"{hour:02d}:{minute:02d}:00"
        for hour in range(9, 12)
        for minute in range(60)
        if (hour == 9 and minute >= 31) or hour in {10, 11}
    ][:120]
    afternoon = [
        f"{hour:02d}:{minute:02d}:00"
        for hour in range(13, 16)
        for minute in range(60)
        if (hour == 13 and minute >= 1) or hour == 14 or (hour == 15 and minute == 0)
    ]
    return [*morning, *afternoon]


def _market_and_code(symbol: str) -> tuple[int, str]:
    text = str(symbol or "").strip().upper()
    if not text.startswith("A.") or not text[2:].isdigit():
        raise ValueError("pytdx minute replay accepts A-share symbols only")
    code = text[2:].zfill(6)
    return (1 if code.startswith(("5", "6", "9")) else 0, code)


class TdxMinuteReplayProvider:
    """Build a cutoff-truncated observation batch; it is never live L1 evidence."""

    def __init__(self, *, api_factory: Callable[[], Any] | None = None) -> None:
        self._api_factory = api_factory or _connected_api

    def snapshot(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> dict[str, Any]:
        if not symbols:
            raise ValueError("pytdx minute replay requires at least one A-share symbol")
        identities = [(symbol, *_market_and_code(symbol)) for symbol in symbols]
        cutoff = datetime.fromisoformat(cutoff_at)
        if cutoff.strftime("%Y%m%d") != trade_date:
            raise ValueError("pytdx replay cutoff date mismatch")
        if stage_id == "STAGE_0925":
            return self._auction_snapshot(identities, trade_date, cutoff)
        if stage_id not in STAGE_BAR_WINDOWS:
            raise ValueError("pytdx replay has no A-share minute window for stage")
        window_start, window_end, expected_bars = STAGE_BAR_WINDOWS[stage_id]
        all_times = _minute_times()
        cutoff_time = cutoff.strftime("%H:%M:%S")
        selected_times = [
            value for value in all_times
            if window_start <= value <= window_end and value <= cutoff_time
        ]
        api = self._api_factory()
        rows: list[dict[str, Any]] = []
        empty_symbols: list[str] = []
        try:
            for symbol, market, code in identities:
                raw_rows = api.get_history_minute_time_data(market, code, int(trade_date)) or []
                if not raw_rows:
                    empty_symbols.append(symbol)
                    continue
                selected_pairs = [
                    (time_value, raw_row)
                    for time_value, raw_row in zip(all_times, raw_rows)
                    if time_value in selected_times
                ]
                selected = [raw_row for _time_value, raw_row in selected_pairs]
                if not selected:
                    continue
                rows.append(self._normalize(
                    symbol,
                    selected,
                    [time_value for time_value, _raw_row in selected_pairs],
                    expected_bars=expected_bars,
                    stage_window=f"{window_start}-{window_end}",
                ))
        finally:
            api.disconnect()
        if empty_symbols and not rows:
            raise ValueError(
                "pytdx returned no minute rows for: " + ", ".join(sorted(empty_symbols))
            )
        cannot_confirm = []
        if empty_symbols:
            cannot_confirm.append(
                "PYTDX_MINUTE_ROWS_MISSING: " + ", ".join(sorted(empty_symbols))
            )
        partial_symbols = [row["symbol"] for row in rows if not row["stage_window_complete"]]
        if partial_symbols:
            cannot_confirm.append("PYTDX_STAGE_WINDOW_PARTIAL: " + ", ".join(partial_symbols))
        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "captured_at": cutoff.isoformat(timespec="seconds"),
            "temporal_cutoff_safe": True,
            "source": "PYTDX_A_SHARE_1MIN_REPLAY",
            "data_level": "STAGE_RTDATA_LATE_REPLAY",
            "rows": rows,
            "cannot_confirm": cannot_confirm,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _auction_snapshot(
        self,
        identities: list[tuple[str, int, str]],
        trade_date: str,
        cutoff: datetime,
    ) -> dict[str, Any]:
        """Restore the V3 tdxpy 09:25 lane from exact-date auction transactions."""
        api = self._api_factory()
        rows: list[dict[str, Any]] = []
        missing_symbols: list[str] = []
        read_errors: list[str] = []
        diagnostics: list[dict[str, Any]] = []
        cutoff_minute = cutoff.strftime("%H:%M")
        try:
            for symbol, market, code in identities:
                diagnostic: dict[str, Any] = {
                    "symbol": symbol, **dict.fromkeys(_DIAGNOSTIC_COUNTS, 0),
                    "time_examples": [], "stop_reason": "UNKNOWN",
                }
                diagnostics.append(diagnostic)
                try:
                    auction_ticks = self._auction_ticks(
                        api,
                        market=market,
                        code=code,
                        trade_date=trade_date,
                        cutoff_minute=cutoff_minute,
                        diagnostic=diagnostic,
                    )
                    if not auction_ticks:
                        missing_symbols.append(symbol)
                        continue
                    previous_close = self._previous_close(
                        api,
                        market=market,
                        code=code,
                        trade_date=trade_date,
                    )
                    rows.append(
                        self._normalize_auction(
                            symbol,
                            auction_ticks,
                            previous_close=previous_close,
                            cutoff_minute=cutoff_minute,
                        )
                    )
                except Exception as error:
                    diagnostic["stop_reason"] = "READ_ERROR"
                    diagnostic["error_type"] = type(error).__name__
                    missing_symbols.append(symbol)
                    read_errors.append(f"{symbol}: {type(error).__name__}: {error}")
        finally:
            api.disconnect()
        replay_diagnostics = _auction_diagnostics(diagnostics, len(rows))
        if not rows:
            raise AuctionReplayError(
                "pytdx returned no exact 09:25 auction transactions for: "
                + ", ".join(sorted(set(missing_symbols))),
                replay_diagnostics,
            )
        cannot_confirm = [
            "PYTDX_0925_HISTORY_TRANSACTION_L0_NO_ORDER_BOOK",
        ]
        if missing_symbols:
            cannot_confirm.append(
                "PYTDX_0925_AUCTION_ROWS_MISSING: "
                + ", ".join(sorted(set(missing_symbols)))
            )
        if missing_symbols:
            cannot_confirm.append("PYTDX_0925_DIAGNOSTICS_V1:" + json.dumps(
                {key: value for key, value in replay_diagnostics.items() if key != "symbols"},
                ensure_ascii=False, sort_keys=True,
            ))
        if read_errors:
            cannot_confirm.append(
                "PYTDX_0925_READ_ERRORS: " + "; ".join(read_errors)[:1000]
            )
        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": "STAGE_0925",
            "captured_at": cutoff.isoformat(timespec="seconds"),
            "temporal_cutoff_safe": True,
            "source": "PYTDX_A_SHARE_0925_HISTORY_TRANSACTION",
            "replay_diagnostics": replay_diagnostics,
            "data_level": "PYTDX_A_SHARE_0925_HISTORY_TRANSACTION_L0",
            "rows": rows,
            "cannot_confirm": cannot_confirm,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @staticmethod
    def _auction_ticks(
        api: Any,
        *,
        market: int,
        code: str,
        trade_date: str,
        cutoff_minute: str,
        diagnostic: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Page backward from the close until the exact auction minute is reached."""
        for page in range(_TRANSACTION_MAX_PAGES):
            if diagnostic is not None:
                diagnostic["pages_read"] += 1
            raw_ticks = api.get_history_transaction_data(
                market,
                code,
                page * _TRANSACTION_PAGE_SIZE,
                _TRANSACTION_PAGE_SIZE,
                int(trade_date),
            ) or []
            if diagnostic is not None:
                diagnostic["raw_tick_count"] += len(raw_ticks)
                for tick in raw_ticks:
                    if not isinstance(tick, dict):
                        diagnostic["invalid_tick_count"] += 1
                        continue  # Original parser below still decides validity.
                    time_value = str(tick.get("time") or "")
                    example = time_value[:32]
                    if example not in diagnostic["time_examples"] and len(diagnostic["time_examples"]) < 5:
                        diagnostic["time_examples"].append(example)
                    if time_value != cutoff_minute:
                        diagnostic["time_mismatch_count"] += 1
                    else:
                        diagnostic["exact_time_count"] += 1
                        if _number(tick.get("price")) in (None, 0) or (_number(tick.get("vol")) or 0) <= 0:
                            diagnostic["numeric_rejection_count"] += 1
            auction_ticks = [
                tick
                for tick in raw_ticks
                if str(tick.get("time") or "") == cutoff_minute
                and _number(tick.get("price")) not in (None, 0)
                and (_number(tick.get("vol")) or 0) > 0
            ]
            if auction_ticks:
                if diagnostic is not None:
                    diagnostic["accepted_tick_count"] = len(auction_ticks)
                    diagnostic["stop_reason"] = "ACCEPTED"
                return auction_ticks
            valid_times = sorted(
                str(tick.get("time") or "")
                for tick in raw_ticks
                if str(tick.get("time") or "")
            )
            if not raw_ticks or (valid_times and valid_times[0] <= cutoff_minute):
                if diagnostic is not None:
                    diagnostic["stop_reason"] = "EMPTY_PAGE" if not raw_ticks else "AT_OR_BEFORE_CUTOFF"
                return []
        if diagnostic is not None:
            diagnostic["stop_reason"] = "PAGE_LIMIT"
        return []

    @staticmethod
    def _previous_close(
        api: Any,
        *,
        market: int,
        code: str,
        trade_date: str,
    ) -> float | None:
        candidates: list[tuple[str, float]] = []
        for bar in api.get_security_bars(9, market, code, 0, 80) or []:
            try:
                bar_date = (
                    f"{int(bar.get('year')):04d}"
                    f"{int(bar.get('month')):02d}"
                    f"{int(bar.get('day')):02d}"
                )
            except (TypeError, ValueError):
                continue
            close = _number(bar.get("close"))
            if bar_date < trade_date and close not in (None, 0):
                candidates.append((bar_date, close))
        return max(candidates, default=("", None), key=lambda item: item[0])[1]

    @staticmethod
    def _normalize_auction(
        symbol: str,
        ticks: list[dict[str, Any]],
        *,
        previous_close: float | None,
        cutoff_minute: str,
    ) -> dict[str, Any]:
        prices = [_number(tick.get("price")) or 0.0 for tick in ticks]
        volumes = [_number(tick.get("vol")) or 0.0 for tick in ticks]
        last_price = prices[-1]
        return {
            "symbol": symbol,
            "open_price": last_price,
            "last_price": last_price,
            "high_price": max(prices),
            "low_price": min(prices),
            "prev_close_price": previous_close,
            "turnover": round(
                sum(price * volume * 100 for price, volume in zip(prices, volumes)),
                4,
            ),
            "volume": sum(volumes),
            "bid_price1": None,
            "ask_price1": None,
            "bid_vol1": None,
            "ask_vol1": None,
            "source_tick_count": len(ticks),
            "source_last_tick_time": f"{cutoff_minute}:00",
            "source_method": "pytdx.hq.get_history_transaction_data",
            "previous_close_source_method": "pytdx.hq.get_security_bars.daily",
            "data_level": "PYTDX_A_SHARE_0925_HISTORY_TRANSACTION_L0",
            "recommendation_status": "WATCH_ONLY",
        }

    @staticmethod
    def _normalize(
        symbol: str,
        raw_rows: list[dict[str, Any]],
        times: list[str],
        *,
        expected_bars: int,
        stage_window: str,
    ) -> dict[str, Any]:
        prices = [float(row["price"]) for row in raw_rows]
        volumes = [float(row.get("vol") or 0) for row in raw_rows]
        complete = len(raw_rows) >= expected_bars
        return {
            "symbol": symbol,
            "open_price": prices[0],
            "last_price": prices[-1],
            "high_price": max(prices),
            "low_price": min(prices),
            "turnover": round(
                sum(price * volume * 100 for price, volume in zip(prices, volumes)),
                4,
            ),
            "volume": sum(volumes),
            "bid_price1": None,
            "ask_price1": None,
            "bid_vol1": None,
            "ask_vol1": None,
            "source_bar_count": len(raw_rows),
            "expected_bar_count": expected_bars,
            "stage_window_complete": complete,
            "stage_window": stage_window,
            "source_last_bar_time": times[len(raw_rows) - 1],
            "data_level": "STAGE_RTDATA_LATE_REPLAY" if complete else "DATA_PARTIAL_PYTDX_1MIN_BAR",
            "recommendation_status": "WATCH_ONLY",
        }


def _connected_api() -> Any:
    from pytdx.config.hosts import hq_hosts
    from pytdx.hq import TdxHq_API

    failures: list[str] = []
    # Match the original Windows V3 lane: use pytdx's maintained host registry
    # and walk the registry instead of pinning a small local IP shortlist.
    for name, host, port in hq_hosts[:80]:
        api = TdxHq_API(heartbeat=False)
        try:
            if api.connect(host, port, time_out=1.5):
                probe = api.get_security_bars(9, 1, "600000", 0, 1) or []
                if probe:
                    return api
                failures.append(f"{name}: connected without A-share bar capability")
            else:
                failures.append(f"{name}: connect returned false")
        except Exception as error:
            failures.append(f"{name}: {type(error).__name__}")
        try:
            api.disconnect()
        except Exception:
            pass
    raise ConnectionError("no pytdx quote host connected: " + "; ".join(failures))


def _number(value: Any) -> float | None:
    try:
        if value in ("", None, "N/A"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
