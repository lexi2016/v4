"""Trading-day-gated owner for the HK 09:15-09:20 shared capture."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.hk_auction_0920 import run_capture
from shared_data.market_calendar import evaluate_a_share_trade_date
from shared_data.store import StoreError
from scripts.acquire_stage_raw import resolve_futu_python

TASK_NAME = "V3Shared_Acquire_HK_AUCTION_0920"
_SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def run_scheduled_hk_auction(
    root: Path,
    trade_date: str,
    *,
    now: datetime | None = None,
    python_path: Path | None = None,
    capture_runner: Callable[..., dict[str, Any]] = run_capture,
) -> dict[str, Any]:
    root = Path(root)
    now = now or datetime.now().astimezone()
    calendar = evaluate_a_share_trade_date(trade_date)
    capture: dict[str, Any] | None = None
    error = ""
    if not calendar.get("eligible"):
        ok = str(calendar.get("status")) in {
            "SKIPPED_NON_TRADING_DAY_WEEKEND",
            "SKIPPED_NON_TRADING_DAY_HOLIDAY",
        }
        status = "SKIPPED_NON_TRADING_DAY" if ok else "FAILED"
        if not ok:
            error = str(calendar.get("status") or "calendar rejected date")
    else:
        try:
            executable = Path(python_path) if python_path is not None else resolve_futu_python()
            capture = capture_runner(
                root,
                trade_date,
                executable,
                sleeper=time.sleep,
            )
            ok = bool(capture.get("ok"))
            status = str(capture.get("status") or ("READY" if ok else "FAILED"))
            error = str(capture.get("error") or "")
        except (OSError, StoreError, ValueError) as exc:
            ok = False
            status = "FAILED"
            error = str(exc)
    receipt = {
        "schema_version": "v3_shared_data.scheduled_hk_auction_0920_receipt.v1",
        "ok": ok,
        "status": status,
        "task_name": TASK_NAME,
        "trade_date": trade_date,
        "capture_window": "09:15:00-09:19:59",
        "publication_time": "09:20:00",
        "generated_at": now.isoformat(timespec="seconds"),
        "calendar": calendar,
        "capture": capture,
        "error": error,
        **_SAFETY,
    }
    receipt_path = root / "scheduler" / "hk_auction_0920" / trade_date / "receipt.json"
    latest_path = root / "scheduler" / "hk_auction_0920" / "latest.json"
    _write_json_atomic(receipt_path, receipt)
    _write_json_atomic(latest_path, receipt)
    return {**receipt, "receipt_path": str(receipt_path), "latest_path": str(latest_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trade-date", default="auto")
    args = parser.parse_args(argv)
    root_text = str(os.environ.get("V3_SHARED_DATA_STORE_ROOT") or "").strip()
    if not root_text:
        print(json.dumps({"ok": False, "status": "FAILED", "error": "V3_SHARED_DATA_STORE_ROOT missing"}))
        return 1
    now = datetime.now().astimezone()
    trade_date = now.strftime("%Y%m%d") if args.trade_date == "auto" else str(args.trade_date)
    result = run_scheduled_hk_auction(Path(root_text), trade_date, now=now)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
