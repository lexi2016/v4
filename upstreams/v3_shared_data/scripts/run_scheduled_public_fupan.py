"""Trading-day-gated scheduled owner for the shared public fupan bundle."""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.market_calendar import evaluate_a_share_trade_date
from shared_data.public_fupan import capture_public_fupan

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


def run_scheduled_public_fupan(
    root: Path,
    trade_date: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    calendar = evaluate_a_share_trade_date(trade_date)
    if calendar.get("eligible"):
        try:
            capture = capture_public_fupan(root, trade_date)
        except (OSError, ValueError) as error:
            capture = {"ok": False, "status": "FAILED", "error": str(error)}
        ok = bool(capture.get("ok"))
        status = "READY" if ok else "FAILED"
    else:
        capture = None
        ok = str(calendar.get("status")) in {
            "SKIPPED_NON_TRADING_DAY_WEEKEND",
            "SKIPPED_NON_TRADING_DAY_HOLIDAY",
        }
        status = "SKIPPED_NON_TRADING_DAY" if ok else "FAILED"
    receipt = {
        "schema_version": "v3_shared_data.scheduled_public_fupan_receipt.v1",
        "ok": ok,
        "status": status,
        "trade_date": trade_date,
        "generated_at": now.isoformat(timespec="seconds"),
        "calendar": calendar,
        "capture": capture,
        **_SAFETY,
    }
    receipt_path = root / "public_fupan" / "scheduler" / trade_date / "receipt.json"
    _write_json_atomic(receipt_path, receipt)
    _write_json_atomic(root / "public_fupan" / "scheduler" / "latest.json", receipt)
    return {**receipt, "receipt_path": str(receipt_path)}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", default="auto")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root_text = str(os.environ.get("V3_SHARED_DATA_STORE_ROOT") or "").strip()
    if not root_text:
        print(json.dumps({"ok": False, "status": "FAILED", "error": "V3_SHARED_DATA_STORE_ROOT missing"}))
        return 1
    trade_date = datetime.now().strftime("%Y%m%d") if args.trade_date == "auto" else str(args.trade_date)
    result = run_scheduled_public_fupan(Path(root_text), trade_date)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
