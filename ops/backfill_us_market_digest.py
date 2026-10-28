"""Run an explicitly allowlisted development-only US RSS backfill."""
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from infrastructure.data_store import _date
from ops.us_market_digest import materialize_us_historical_backfill


def _date_range(start: str, end: str) -> list[str]:
    first = date.fromisoformat(f"{_date(start)[:4]}-{_date(start)[4:6]}-{_date(start)[6:]}")
    last = date.fromisoformat(f"{_date(end)[:4]}-{_date(end)[4:6]}-{_date(end)[6:]}")
    if last < first:
        raise ValueError("historical backfill end date precedes start date")
    return [
        (first + timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range((last - first).days + 1)
    ]


def load_development_dates(path: Path) -> set[str]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, Mapping):
        value = value.get("dates")
    if not isinstance(value, list):
        raise ValueError("development date allowlist must be a JSON list")
    try:
        return {_date(str(item)) for item in value}
    except (TypeError, ValueError) as error:
        raise ValueError("development date allowlist is invalid") from error


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--development-dates-file", type=Path, required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--timeout", type=int, default=20)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        allowlist = load_development_dates(args.development_dates_file)
        requested = _date_range(args.start_date, args.end_date)
        selected = [trade_date for trade_date in requested if trade_date in allowlist]
        skipped = [trade_date for trade_date in requested if trade_date not in allowlist]
        outputs: list[dict[str, Any]] = []
        for trade_date in selected:
            result = materialize_us_historical_backfill(
                data_root=args.data_root,
                trade_date=trade_date,
                development_dates=allowlist,
                timeout=args.timeout,
            )
            outputs.append(
                {
                    "trade_date": trade_date,
                    "status": result["payload"]["status"],
                    "payload_path": result["payload_path"],
                    "payload_sha256": result["payload_sha256"],
                }
            )
        status = "READY" if all(row["status"] in {"READY", "READY_EMPTY"} for row in outputs) else "CANNOT_CONFIRM"
        if not selected:
            status = "CANNOT_CONFIRM"
        print(json.dumps({
            "status": status,
            "requested_count": len(requested),
            "materialized_count": len(outputs),
            "skipped_not_allowlisted": skipped,
            "outputs": outputs,
            "capture_origin": "HISTORICAL_BACKFILL",
            "original_time_capture": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ensure_ascii=False, sort_keys=True))
        return 0 if status == "READY" else 2
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({
            "status": "CANNOT_CONFIRM",
            "reason": f"{type(error).__name__}:{error}",
            "capture_origin": "HISTORICAL_BACKFILL",
            "original_time_capture": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["load_development_dates", "main", "parse_args"]
