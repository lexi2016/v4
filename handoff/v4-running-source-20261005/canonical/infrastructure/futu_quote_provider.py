"""Read-only Futu OpenD quote adapter for V3.5 stage inputs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Sequence


def to_futu_symbol(symbol: str) -> str:
    text = str(symbol or "").strip().upper()
    if text.startswith("HK.") and text[3:].isdigit():
        return f"HK.{text[3:].zfill(5)}"
    if not text.startswith("A.") or not text[2:].isdigit():
        raise ValueError(f"unsupported market symbol: {symbol}")
    code = text[2:].zfill(6)
    prefix = "SH" if code.startswith(("5", "6", "9")) else "SZ"
    return f"{prefix}.{code}"


def _native_symbol(futu_symbol: str) -> str:
    market, code = futu_symbol.upper().split(".", 1)
    if market == "HK":
        return f"HK.{code.zfill(5)}"
    if market in {"SH", "SZ"}:
        return f"A.{code.zfill(6)}"
    raise ValueError(f"unsupported Futu market: {market}")


def _first(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    try:
        return value[0] if not isinstance(value, (str, bytes, dict)) else value
    except (IndexError, KeyError, TypeError):
        return value


class FutuQuoteProvider:
    def __init__(
        self,
        *,
        context_factory: Callable[[], Any] | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._context_factory = context_factory or _default_context
        self._now = now

    def snapshot(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> dict[str, Any]:
        if not symbols or len(symbols) > 220:
            raise ValueError("Futu stage snapshot requires between 1 and 220 symbols")
        requested = [to_futu_symbol(symbol) for symbol in symbols]
        context = self._context_factory()
        try:
            return_code, frame = context.get_market_snapshot(requested)
            if return_code != 0:
                raise ValueError(f"Futu read-only snapshot failed: {frame}")
            records = frame.to_dict(orient="records")
        finally:
            context.close()
        captured = self._now()
        cutoff = datetime.fromisoformat(cutoff_at)
        rows = [self._normalize(row) for row in records]
        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "captured_at": captured.isoformat(timespec="seconds"),
            "temporal_cutoff_safe": captured.date() == cutoff.date() and captured <= cutoff,
            "source": "FUTU_OPEND_READ_ONLY_SNAPSHOT",
            "rows": rows,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @staticmethod
    def _normalize(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": _native_symbol(str(row.get("code") or "")),
            "open_price": row.get("open_price"),
            "last_price": row.get("last_price"),
            "prev_close_price": row.get("prev_close_price"),
            "high_price": row.get("high_price"),
            "low_price": row.get("low_price"),
            "turnover": row.get("turnover"),
            "volume": row.get("volume"),
            "bid_price1": _first(row.get("bid_price")),
            "ask_price1": _first(row.get("ask_price")),
            "bid_vol1": _first(row.get("bid_vol")),
            "ask_vol1": _first(row.get("ask_vol")),
            "recommendation_status": "WATCH_ONLY",
        }


def _default_context() -> Any:
    import futu as ft

    return ft.OpenQuoteContext(host="127.0.0.1", port=11111)
