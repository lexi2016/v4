"""Collect the same-day full HK Connect final-close snapshot into V4."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from infrastructure.hkconnect_close_store import (
    CloseSnapshotStore,
    futu_close_capture_time_gap,
    parse_futu_update_time,
)


HKCONNECT_PLATE_CODES = ("HK.GangGuTong", "HK.LIST1922")
FINAL_CLOSE_CUTOFF = "16:10:00"
_TIMEZONE_NAME = "Asia/Shanghai"
_TIMEZONE = ZoneInfo(_TIMEZONE_NAME)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _compact_date(value: Any) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _query_time(value: datetime | None) -> datetime:
    current = value or datetime.now(_TIMEZONE)
    if current.tzinfo is None or current.utcoffset() is None:
        return current.replace(tzinfo=_TIMEZONE)
    return current.astimezone(_TIMEZONE)


def _default_quote_context_factory():
    from futu import OpenQuoteContext, ft_logger

    ft_logger.logger._console_level = logging.CRITICAL + 1
    ft_logger.logger.console_logger.setLevel(logging.CRITICAL + 1)
    ft_logger.logger.consoleHandler.setLevel(logging.CRITICAL + 1)
    return OpenQuoteContext(host="127.0.0.1", port=11111)


def _reusable_snapshot(
    payload: Any,
    *,
    trade_date: str,
    min_universe_count: int,
    required_coverage_ratio: float,
) -> bool:
    if not isinstance(payload, dict):
        return False
    rows = payload.get("rows")
    if (
        payload.get("trade_date") != trade_date
        or payload.get("status") != "READY"
        or not isinstance(rows, list)
        or any(payload.get(flag) is not False for flag in (
            "production_allowed", "buy_gate_updated", "orders_sent",
        ))
    ):
        return False
    universe_count = payload.get("universe_count")
    same_date_count = payload.get("same_date_row_count")
    try:
        coverage = float(payload.get("coverage_ratio"))
    except (TypeError, ValueError):
        return False
    return (
        isinstance(universe_count, int)
        and not isinstance(universe_count, bool)
        and universe_count >= int(min_universe_count)
        and same_date_count == len(rows)
        and coverage + 1e-12 >= float(required_coverage_ratio)
        and (
            payload.get("source_mode") != "FUTU_FULL_HKCONNECT_CLOSE_SNAPSHOT"
            or futu_close_capture_time_gap(payload, trade_date) is None
        )
    )


def collect_close_snapshot(
    trade_date: str,
    *,
    data_root: Path,
    quote_context_factory: Callable[[], Any] | None = None,
    now: datetime | None = None,
    min_universe_count: int = 600,
    required_coverage_ratio: float = 1.0,
    batch_size: int = 200,
) -> dict[str, Any]:
    current = _query_time(now)
    target = _compact_date(trade_date)
    if len(target) != 8:
        raise ValueError("invalid trade date")
    snapshot_store = CloseSnapshotStore(data_root)
    try:
        existing, existing_sha = snapshot_store.read_snapshot(target)
    except FileNotFoundError as error:
        expected_missing = f"hkconnect_close_snapshots/{target}.json"
        if error.filename is not None or error.args != (expected_missing,):
            raise
        existing = None
        existing_sha = ""
    if existing is not None:
        if existing.get("source_mode") == "FUTU_FULL_HKCONNECT_CLOSE_SNAPSHOT":
            capture_gap = futu_close_capture_time_gap(existing, target)
            if capture_gap is not None:
                raise ValueError(capture_gap)
    if _reusable_snapshot(
        existing,
        trade_date=target,
        min_universe_count=min_universe_count,
        required_coverage_ratio=required_coverage_ratio,
    ):
        return {
            "snapshot": existing,
            "publication": {
                "status": "IDEMPOTENT_REUSE",
                "trade_date": target,
                "payload_path": f"hkconnect_close_snapshots/{target}.json",
                "sha256": existing_sha,
                "reused_existing_snapshot": True,
                "write_performed": False,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        }
    today = current.strftime("%Y%m%d")
    if target != today:
        raise ValueError("Futu snapshot collection is restricted to the current trade date")
    if existing is not None:
        raise ValueError("HK_CLOSE_SNAPSHOT_NOT_REUSABLE_IMMUTABLE")
    if current.strftime("%H:%M:%S") < FINAL_CLOSE_CUTOFF:
        raise ValueError(f"final close cutoff not reached: {FINAL_CLOSE_CUTOFF}")

    context = (quote_context_factory or _default_quote_context_factory)()
    try:
        universe: dict[str, str] = {}
        for plate_code in HKCONNECT_PLATE_CODES:
            return_code, frame = context.get_plate_stock(plate_code)
            if return_code != 0:
                raise RuntimeError(f"FUTU_GET_PLATE_STOCK_FAILED:{plate_code}:{frame}")
            for row in frame.to_dict(orient="records"):
                code = str(row.get("code") or "").strip().upper()
                if code.startswith("HK."):
                    universe[code] = str(row.get("stock_name") or row.get("name") or "").strip()
        codes = sorted(universe)
        snapshots: dict[str, dict[str, Any]] = {}
        step = max(1, int(batch_size))
        for offset in range(0, len(codes), step):
            return_code, frame = context.get_market_snapshot(codes[offset : offset + step])
            if return_code != 0:
                raise RuntimeError(f"FUTU_GET_MARKET_SNAPSHOT_FAILED:{offset}:{frame}")
            for row in frame.to_dict(orient="records"):
                code = str(row.get("code") or "").strip().upper()
                if code in universe:
                    snapshots[code] = row
    finally:
        context.close()

    rows: list[dict[str, Any]] = []
    for code in codes:
        source = snapshots.get(code) or {}
        raw_update_time = source.get("update_time")
        source_update_time = parse_futu_update_time(raw_update_time)
        if source_update_time is None:
            raise ValueError(f"HK_CLOSE_SOURCE_TIME_MISSING_OR_INVALID:{code}")
        if source_update_time.strftime("%Y%m%d") != target:
            raise ValueError(f"HK_CLOSE_SOURCE_TIME_DATE_MISMATCH:{code}")
        # update_time is the current price's update time, not the query time.
        # The same-day query is already required to be after final close.
        close = _number(source.get("last_price"))
        pre_close = _number(source.get("prev_close_price"))
        if close is None or pre_close is None or close <= 0 or pre_close <= 0:
            continue
        amount = _number(source.get("turnover")) or 0.0
        rows.append(
            {
                "trade_date": target,
                "code": code,
                "name": str(source.get("name") or universe.get(code) or "").strip(),
                "close": close,
                "pre_close": pre_close,
                "amount": amount,
                "pct_chg_close": round((close / pre_close - 1.0) * 100.0, 8),
                "source": "FUTU_FULL_HKCONNECT_CLOSE_SNAPSHOT",
                "update_time": raw_update_time,
                "source_update_time": source_update_time.isoformat(timespec="seconds"),
                "source_timezone": _TIMEZONE_NAME,
            }
        )
    coverage = len(rows) / len(codes) if codes else 0.0
    if len(codes) < int(min_universe_count) or coverage + 1e-12 < float(required_coverage_ratio):
        raise ValueError(
            "full HK Connect coverage required: "
            f"universe={len(codes)},same_date={len(rows)},coverage={coverage:.8f}"
        )
    parsed_times = [parse_futu_update_time(row["update_time"]) for row in rows]
    if not parsed_times or any(value is None for value in parsed_times):
        raise ValueError("HK_CLOSE_SOURCE_TIME_MISSING_OR_INVALID")
    source_capture = {
        "provider": "FUTU_OPENAPI",
        "api": "get_market_snapshot",
        "timestamp_field": "update_time",
        "timezone": _TIMEZONE_NAME,
        "queried_at": current.isoformat(timespec="seconds"),
        "source_time_min": min(parsed_times).isoformat(timespec="seconds"),
        "source_time_max": max(parsed_times).isoformat(timespec="seconds"),
        "plate_codes": list(HKCONNECT_PLATE_CODES),
    }
    source_bytes = json.dumps(
        {
            "trade_date": target,
            "plate_codes": HKCONNECT_PLATE_CODES,
            "rows": rows,
            "source_capture": source_capture,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    payload = {
        "schema_version": "v3_5.hkconnect_close_snapshot.v1",
        "trade_date": target,
        "status": "READY",
        "source_mode": "FUTU_FULL_HKCONNECT_CLOSE_SNAPSHOT",
        "source_input_sha256": source_sha256,
        "source_capture": {**source_capture, "source_sha256": source_sha256},
        "universe_count": len(codes),
        "same_date_row_count": len(rows),
        "coverage_ratio": round(coverage, 8),
        "rows": rows,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    publication = snapshot_store.import_snapshot(payload)
    return {"snapshot": payload, "publication": publication}


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect the V4 HK Connect final-close snapshot")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--min-universe-count", type=int, default=600)
    parser.add_argument("--required-coverage-ratio", type=float, default=1.0)
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()
    result = collect_close_snapshot(
        args.date,
        data_root=args.data_root,
        min_universe_count=args.min_universe_count,
        required_coverage_ratio=args.required_coverage_ratio,
        batch_size=args.batch_size,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
