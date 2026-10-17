#!/usr/bin/env python3
"""One read-only Futu get_market_snapshot canary for the 2026-10-16 US close."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
OUTPUT = HERE.parent / "evidence" / "futu_snapshot_canary.json"
HOST = "127.0.0.1"
PORT = 11111
REQUESTED_CODES = ["US.DASH", "US.NTES", "US.UBER"]
TARGET_US_SESSION = "2026-10-16"


def clean(value: Any) -> Any:
    if hasattr(value, "to_dict") and not isinstance(value, dict):
        try:
            return clean(value.to_dict(orient="records"))
        except TypeError:
            return clean(value.to_dict())
    if hasattr(value, "item") and not isinstance(value, (str, bytes, dict, list, tuple)):
        try:
            return clean(value.item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now_local() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main() -> int:
    from futu import OpenQuoteContext, RET_OK, __version__

    context = None
    capture: dict[str, Any] = {
        "schema_version": "futu-read-only-snapshot-canary-v1",
        "target_us_session": TARGET_US_SESSION,
        "provider": "Futu OpenAPI Python SDK via local OpenD",
        "api": "OpenQuoteContext.get_market_snapshot",
        "host": HOST,
        "port": PORT,
        "sdk_version": __version__,
        "requested_codes": REQUESTED_CODES,
        "requested_at_local": now_local(),
        "requested_at_utc": now_utc(),
        "request_contract": {
            "calls": ["get_market_snapshot"],
            "historical_kline_requested": False,
            "subscription_requested": False,
            "refresh_requested": False,
        },
    }
    try:
        context = OpenQuoteContext(host=HOST, port=PORT)
        capture["response_received_at_local"] = now_local()
        capture["response_received_at_utc"] = now_utc()
        ret, data = context.get_market_snapshot(REQUESTED_CODES)
        response = clean(data)
        if isinstance(response, dict):
            rows = [response]
        elif isinstance(response, list):
            rows = [row for row in response if isinstance(row, dict)]
        else:
            rows = []
        capture.update({
            "ret": int(ret),
            "ret_ok": int(ret) == int(RET_OK),
            "response_row_count": len(rows),
            "response_rows": rows,
        })
        if int(ret) != int(RET_OK):
            capture["provider_error"] = json.dumps(response, ensure_ascii=False, sort_keys=True)
    except Exception as exc:
        capture.update({
            "ret": None,
            "ret_ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
    finally:
        if context is not None:
            context.close()

    capture["source_capture_sha256"] = hashlib.sha256(
        json.dumps(capture, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(capture, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "output_sha256": sha256_file(OUTPUT),
        "ret": capture.get("ret"),
        "ret_ok": capture.get("ret_ok"),
        "response_row_count": capture.get("response_row_count"),
        "codes": [row.get("code") for row in capture.get("response_rows", [])],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if capture.get("ret_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
