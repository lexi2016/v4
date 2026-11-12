"""Fixed PyTDX ExHQ market-71/category-7 minute probe.

This is a clean extraction of V3's existing HK minute-history provider.  It
reads the full requested HK universe, preserves per-code request coverage and
does not synthesize rows for a suspended/no-trade code.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from typing import Any, Callable

from .contracts import STAGE_WINDOWS

MARKER = "__PYTDX_EXHQ_MINUTE_JSON__"
SOURCE_HOSTS = (
    ("119.97.142.130", 7721),
    ("101.227.73.20", 7709),
    ("119.147.212.81", 7727),
)
MARKET_HK = 71
CATEGORY_1MIN = 7
BAR_COUNT = 400


def _connect_first_available() -> tuple[Any, str]:
    from pytdx.exhq import TdxExHq_API

    errors: list[str] = []
    for host, port in SOURCE_HOSTS:
        api = TdxExHq_API(heartbeat=True, auto_retry=True, raise_exception=True)
        try:
            if api.connect(host, port, time_out=2.0):
                return api, f"{host}:{port}"
        except Exception as exc:  # pragma: no cover - live network boundary
            errors.append(f"{host}:{port} {type(exc).__name__}: {exc}")
        try:
            api.disconnect()
        except Exception:
            pass
    raise ConnectionError("no TDXPy ExHQ host available; " + " | ".join(errors))


def _parse_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"invalid TDXPy bar datetime: {text!r}")


def _float(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc


def _raw_rows_for_code(
    code: str,
    source_rows: list[dict[str, Any]],
    trade_date: str,
    stage_id: str,
) -> list[dict[str, Any]]:
    trade_day = datetime.strptime(trade_date, "%Y%m%d").date()
    window_start, window_end, _cutoff = STAGE_WINDOWS[stage_id]
    lower = datetime.combine(
        trade_day, datetime.strptime(window_start, "%H:%M:%S").time()
    ) + timedelta(minutes=1)
    upper = datetime.combine(
        trade_day, datetime.strptime(window_end, "%H:%M:%S").time()
    )
    parsed = sorted(
        ((_parse_datetime(row.get("datetime")), row) for row in source_rows),
        key=lambda item: item[0],
    )
    prior = [item for item in parsed if item[0].date() < trade_day]
    if not prior:
        raise ValueError("prior close unavailable")
    previous_close = _float(prior[-1][1].get("close"), "prior close")
    in_window = [item for item in parsed if lower <= item[0] < upper]
    raw_rows: list[dict[str, Any]] = []
    for bar_time, row in in_window:
        raw_rows.append({
            "code": code,
            "name": code,
            "time_key": bar_time.strftime("%Y-%m-%d %H:%M:%S"),
            "open": _float(row.get("open"), "open"),
            "high": _float(row.get("high"), "high"),
            "low": _float(row.get("low"), "low"),
            "close": _float(row.get("close"), "close"),
            "volume": _float(
                row.get("vol", row.get("volume", row.get("trade"))), "volume"
            ),
            "turnover": _float(row.get("amount"), "amount"),
            "last_close": previous_close,
        })
    return raw_rows


def collect_payload(
    payload: dict[str, Any],
    *,
    connector: Callable[[], tuple[Any, str]] = _connect_first_available,
) -> dict[str, Any]:
    trade_date = str(payload.get("trade_date") or "")
    stage_id = str(payload.get("stage_id") or "")
    codes = payload.get("codes")
    datetime.strptime(trade_date, "%Y%m%d")
    if stage_id not in STAGE_WINDOWS:
        raise ValueError(f"unknown stage {stage_id!r}")
    if not isinstance(codes, list) or not codes:
        raise ValueError("codes must be a nonempty list")
    if len(set(codes)) != len(codes) or any(
        not isinstance(code, str) or not code.startswith("HK.") or len(code) != 8
        for code in codes
    ):
        raise ValueError("codes must be unique HK.##### symbols")

    api, source_host = connector()
    raw_rows: list[dict[str, Any]] = []
    no_data_codes: list[str] = []
    errors: list[dict[str, str]] = []
    completed = 0
    try:
        for code in codes:
            try:
                source_rows = api.get_instrument_bars(
                    CATEGORY_1MIN, MARKET_HK, code.split(".", 1)[1], 0, BAR_COUNT
                ) or []
                if not source_rows:
                    raise ValueError("no TDXPy minute bars")
                normalized = _raw_rows_for_code(code, source_rows, trade_date, stage_id)
                raw_rows.extend(normalized)
                if not normalized:
                    no_data_codes.append(code)
                completed += 1
            except Exception as exc:
                errors.append({"code": code, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        api.disconnect()
    return {
        "requested_code_count": len(codes),
        "completed_code_count": completed,
        "raw_rows": raw_rows,
        "no_data_codes": no_data_codes,
        "errors": errors,
        "source_host": source_host,
    }


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        result = collect_payload(payload)
        print(MARKER + json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(
            MARKER
            + json.dumps(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

