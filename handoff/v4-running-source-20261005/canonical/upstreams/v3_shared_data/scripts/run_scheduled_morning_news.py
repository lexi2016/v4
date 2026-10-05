"""Trading-day-gated single owner for shared 韭研公社 morning news."""
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
from shared_data.morning_news import publish_morning_news, read_morning_news
from shared_data.public_morning_news import (
    collect_public_morning_news,
    load_shared_candidate_registry,
)

_SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def run(root: Path, trade_date: str) -> dict[str, Any]:
    calendar = evaluate_a_share_trade_date(trade_date)
    if not calendar.get("eligible"):
        ok = str(calendar.get("status")) in {
            "SKIPPED_NON_TRADING_DAY_WEEKEND",
            "SKIPPED_NON_TRADING_DAY_HOLIDAY",
        }
        capture: dict[str, Any] | None = None
        status = "SKIPPED_NON_TRADING_DAY" if ok else "FAILED"
    else:
        try:
            existing = read_morning_news(root, trade_date)
        except ValueError as error:
            if "slot missing" not in str(error):
                capture = {"ok": False, "error": str(error)}
                ok = False
                status = "FAILED"
            else:
                try:
                    candidate_registry = load_shared_candidate_registry(root, trade_date)
                    if candidate_registry:
                        payload = collect_public_morning_news(
                            trade_date,
                            candidate_registry=candidate_registry,
                        )
                    else:
                        payload = collect_public_morning_news(trade_date)
                    published = publish_morning_news(root, payload)
                    capture = {"ok": True, **published}
                    ok = True
                    status = str(payload["status"])
                except (OSError, ValueError) as collect_error:
                    capture = {"ok": False, "error": str(collect_error)}
                    ok = False
                    status = "NOT_READY_RETRY_ALLOWED"
        else:
            capture = {
                "ok": True,
                "already_exists": True,
                "article_count": existing["article_count"],
                "mention_count": existing["mention_count"],
            }
            ok = True
            status = str(existing["status"])
    receipt = {
        "schema_version": "v3_shared_data.scheduled_morning_news_receipt.v1",
        "ok": ok,
        "status": status,
        "trade_date": trade_date,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "calendar": calendar,
        "capture": capture,
        **_SAFETY,
    }
    path = root / "morning_news" / "scheduler" / trade_date / "receipt.json"
    _write(path, receipt)
    _write(root / "morning_news" / "scheduler" / "latest.json", receipt)
    return {**receipt, "receipt_path": str(path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", default="auto")
    args = parser.parse_args(argv)
    root_text = str(os.environ.get("V3_SHARED_DATA_STORE_ROOT") or "").strip()
    if not root_text:
        print(json.dumps({"ok": False, "error": "V3_SHARED_DATA_STORE_ROOT missing"}))
        return 1
    trade_date = datetime.now().strftime("%Y%m%d") if args.trade_date == "auto" else args.trade_date
    result = run(Path(root_text), trade_date)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
