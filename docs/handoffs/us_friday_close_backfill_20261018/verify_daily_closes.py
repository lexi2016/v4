#!/usr/bin/env python3
"""Audit Sina daily closes against the immutable Tencent owner snapshot.

This handoff-only helper is a read-only corroboration tool, not a data producer.
It never writes to the canonical owner store. Raw HTTP bodies are kept under
local_only/sina_daily and must not be uploaded or committed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


OWNER_SHA256 = "bb79cb28341c83e7e4c1b96eb2b1cc411332efd9d96301f226b7845d23d1bd0f"
OWNER_RELATIVE = Path("research/peripherals/20261017/external_finance.json")
EXPECTED_SYMBOLS = 48
SESSIONS = {"20261015": "2026-10-15", "20261016": "2026-10-16"}
MAX_CONCURRENCY = 4
MAX_RAW_BYTES = 20 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
SINA_URL = (
    "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/"
    "var/US_MinKService.getDailyK?symbol={symbol}&num=10"
)
HANDOFF_ROOT = Path(__file__).resolve().parent
RAW_ROOT = HANDOFF_ROOT / "local_only" / "sina_daily"
RESULT_PATH = HANDOFF_ROOT / "PRICE_CORROBORATION.json"
OWNER_PATH = (
    Path.home()
    / "Library/Application Support/com.lexi.v4.local/state/data"
    / OWNER_RELATIVE
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def load_owner() -> tuple[bytes, dict, dict[str, dict]]:
    raw = OWNER_PATH.read_bytes()
    actual_sha = sha256(raw)
    if actual_sha != OWNER_SHA256:
        raise RuntimeError(f"OWNER_SHA_MISMATCH:{actual_sha}")
    owner = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    snapshot = owner.get("market_snapshot")
    if not isinstance(snapshot, dict):
        raise RuntimeError("OWNER_MARKET_SNAPSHOT_INVALID")
    quotes = snapshot.get("quotes")
    if not isinstance(quotes, list) or len(quotes) != EXPECTED_SYMBOLS:
        raise RuntimeError("OWNER_QUOTE_COUNT_INVALID")
    by_symbol: dict[str, dict] = {}
    for quote in quotes:
        if not isinstance(quote, dict):
            raise RuntimeError("OWNER_QUOTE_ROW_INVALID")
        symbol = quote.get("symbol")
        if not isinstance(symbol, str) or not symbol or symbol in by_symbol:
            raise RuntimeError("OWNER_SYMBOL_SET_INVALID")
        if quote.get("session_date") != "20261016":
            raise RuntimeError(f"OWNER_SESSION_DATE_INVALID:{symbol}")
        by_symbol[symbol] = quote
    if len(by_symbol) != EXPECTED_SYMBOLS:
        raise RuntimeError("OWNER_SYMBOL_COUNT_INVALID")
    if (snapshot.get("capture_session_date") != "20261016"
            or snapshot.get("requested_symbol_count") != EXPECTED_SYMBOLS
            or snapshot.get("available_symbol_count") != EXPECTED_SYMBOLS):
        raise RuntimeError("OWNER_SNAPSHOT_COVERAGE_INVALID")
    return raw, owner, by_symbol


def parse_jsonp(body: bytes) -> list[dict]:
    text = body.decode("utf-8-sig")
    open_paren = text.find("(")
    close_paren = text.rfind(")")
    if open_paren < 0 or close_paren <= open_paren:
        raise ValueError("SINA_JSONP_ENVELOPE_INVALID")
    value = json.loads(text[open_paren + 1:close_paren])
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("SINA_DAILY_ROWS_INVALID")
    return value


def daily_close(rows: list[dict], symbol: str) -> dict:
    selected: dict[str, list[dict]] = {date: [] for date in SESSIONS.values()}
    for row in rows:
        date = row.get("d")
        if date in selected:
            selected[date].append(row)
    result: dict[str, str] = {}
    for session, date in SESSIONS.items():
        matches = selected[date]
        if not matches:
            raise ValueError(f"SINA_DAILY_DATE_MISSING:{session}")
        if len(matches) != 1:
            raise ValueError(f"SINA_DAILY_DATE_DUPLICATE:{session}")
        try:
            close = Decimal(str(matches[0]["c"]))
        except (KeyError, InvalidOperation, ValueError) as exc:
            raise ValueError(f"SINA_DAILY_CLOSE_INVALID:{session}") from exc
        if not close.is_finite():
            raise ValueError(f"SINA_DAILY_CLOSE_INVALID:{session}")
        result[session] = format(close, "f")
    result["rows_seen"] = str(len(rows))
    return result


def fetch_one(symbol: str) -> dict:
    requested_at = utc_now()
    url = SINA_URL.format(symbol=urllib.parse.quote(symbol, safe=""))
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; V4ResearchCloseAudit/1.0)"},
        method="GET",
    )
    status = None
    body = b""
    error = None
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = int(response.status)
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                body = body[:MAX_RESPONSE_BYTES]
                error = "SINA_RESPONSE_TOO_LARGE"
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            body = body[:MAX_RESPONSE_BYTES]
            error = "SINA_RESPONSE_TOO_LARGE"
        else:
            error = f"SINA_HTTP_STATUS_{status}"
    except Exception as exc:  # transport errors are retained as typed evidence
        error = f"SINA_TRANSPORT_ERROR:{type(exc).__name__}:{exc}"
    received_at = utc_now()
    return {
        "symbol": symbol,
        "url": url,
        "requested_at": requested_at,
        "received_at": received_at,
        "http_status": status,
        "body": body,
        "error": error,
    }


def persist_body(result: dict, bytes_written: int) -> tuple[dict, int]:
    body = result["body"]
    metadata = {key: value for key, value in result.items() if key != "body"}
    if not body:
        return metadata, bytes_written
    if bytes_written + len(body) > MAX_RAW_BYTES:
        metadata["error"] = "LOCAL_RAW_AGGREGATE_CAP_EXCEEDED"
        metadata["raw_saved"] = False
        return metadata, bytes_written
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    path = RAW_ROOT / f"{result['symbol']}.jsonp"
    if path.exists():
        metadata["error"] = "LOCAL_RAW_EXISTS_REFUSING_OVERWRITE"
        metadata["raw_saved"] = False
        return metadata, bytes_written
    path.write_bytes(body)
    metadata["raw_path"] = path.relative_to(HANDOFF_ROOT).as_posix()
    metadata["raw_bytes"] = len(body)
    metadata["raw_sha256"] = sha256(body)
    metadata["raw_saved"] = True
    metadata["raw_persisted_at_utc"] = file_mtime_utc(path)
    return metadata, bytes_written + len(body)


def run_fetch(symbols: list[str], owner_quotes: dict[str, dict]) -> tuple[list[dict], int]:
    output: dict[str, dict] = {}
    total_raw = 0
    cap_hit = False
    for start in range(0, len(symbols), MAX_CONCURRENCY):
        batch = symbols[start:start + MAX_CONCURRENCY]
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
            futures = {executor.submit(fetch_one, symbol): symbol for symbol in batch}
            for future in concurrent.futures.as_completed(futures):
                symbol = futures[future]
                metadata = {"symbol": symbol}
                try:
                    result = future.result()
                    metadata, total_raw = persist_body(result, total_raw)
                    if metadata.get("error"):
                        cap_hit |= metadata["error"] == "LOCAL_RAW_AGGREGATE_CAP_EXCEEDED"
                        output[symbol] = metadata
                        continue
                    rows = parse_jsonp(result["body"])
                    closes = daily_close(rows, symbol)
                    source = owner_quotes[symbol]
                    close_15 = Decimal(closes["20261015"])
                    close_16 = Decimal(closes["20261016"])
                    previous = Decimal(str(source["previous_close"]))
                    last = Decimal(str(source["last"]))
                    output[symbol] = {
                        **metadata,
                        "daily_row_count": int(closes["rows_seen"]),
                        "us20261015_close": format(close_15, "f"),
                        "us20261015_owner_previous_close": format(previous, "f"),
                        "us20261015_equal": close_15 == previous,
                        "us20261016_close": format(close_16, "f"),
                        "us20261016_owner_last": format(last, "f"),
                        "us20261016_equal": close_16 == last,
                    }
                except Exception as exc:
                    output[symbol] = {
                        **metadata,
                        "error": f"AUDIT_ERROR:{type(exc).__name__}:{exc}",
                    }
        if cap_hit:
            for symbol in symbols[start + len(batch):]:
                output[symbol] = {"symbol": symbol, "error": "LOCAL_RAW_AGGREGATE_CAP_REACHED_NOT_REQUESTED"}
            break
    return [output[symbol] for symbol in symbols], total_raw


def run_verify_existing(symbols: list[str], owner_quotes: dict[str, dict]) -> tuple[list[dict], int]:
    output = []
    total_raw = 0
    for symbol in symbols:
        path = RAW_ROOT / f"{symbol}.jsonp"
        if not path.is_file():
            output.append({"symbol": symbol, "error": "LOCAL_RAW_MISSING"})
            continue
        body = path.read_bytes()
        total_raw += len(body)
        if total_raw > MAX_RAW_BYTES:
            output.append({"symbol": symbol, "error": "LOCAL_RAW_AGGREGATE_CAP_EXCEEDED"})
            break
        try:
            rows = parse_jsonp(body)
            closes = daily_close(rows, symbol)
            source = owner_quotes[symbol]
            close_15 = Decimal(closes["20261015"])
            close_16 = Decimal(closes["20261016"])
            previous = Decimal(str(source["previous_close"]))
            last = Decimal(str(source["last"]))
            output.append({
                "symbol": symbol,
                "raw_path": path.relative_to(HANDOFF_ROOT).as_posix(),
                "raw_bytes": len(body),
                "raw_sha256": sha256(body),
                "raw_saved": True,
                "raw_persisted_at_utc": file_mtime_utc(path),
                "daily_row_count": int(closes["rows_seen"]),
                "us20261015_close": format(close_15, "f"),
                "us20261015_owner_previous_close": format(previous, "f"),
                "us20261015_equal": close_15 == previous,
                "us20261016_close": format(close_16, "f"),
                "us20261016_owner_last": format(last, "f"),
                "us20261016_equal": close_16 == last,
            })
        except Exception as exc:
            output.append({"symbol": symbol, "error": f"AUDIT_ERROR:{type(exc).__name__}:{exc}"})
    return output, total_raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fetch", action="store_true", help="fetch bounded Sina daily K responses")
    mode.add_argument("--verify-existing", action="store_true", help="verify local raw responses without network")
    args = parser.parse_args()

    try:
        owner_bytes_before, owner, owner_quotes = load_owner()
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2

    symbols = sorted(owner_quotes)
    started_at = utc_now()
    if args.fetch:
        results, total_raw = run_fetch(symbols, owner_quotes)
    else:
        results, total_raw = run_verify_existing(symbols, owner_quotes)

    owner_bytes_after = OWNER_PATH.read_bytes()
    owner_unchanged = sha256(owner_bytes_after) == sha256(owner_bytes_before) == OWNER_SHA256
    successful = [row for row in results if not row.get("error")]
    exact_matches = [row for row in successful
                     if row.get("us20261015_equal") is True and row.get("us20261016_equal") is True]
    pass_all = (
        len(results) == EXPECTED_SYMBOLS
        and len(successful) == EXPECTED_SYMBOLS
        and len(exact_matches) == EXPECTED_SYMBOLS
        and total_raw <= MAX_RAW_BYTES
        and owner_unchanged
    )
    result = {
        "schema_version": "v4.us_daily_close_corroboration.v1",
        "status": "PASS" if pass_all else "FAIL",
        "purpose": "read-only cross-provider daily-close corroboration; no owner publication",
        "provider": "Sina US daily K",
        "request_url_template": SINA_URL,
        "mode": "FETCH" if args.fetch else "VERIFY_EXISTING",
        "per_symbol_http_timestamp_status": (
            "RECORDED_AT_RESPONSE_COMPLETION" if args.fetch
            else "CANNOT_CONFIRM_FROM_LOCAL_RAW_FILES"
        ),
        "started_at": started_at,
        "finished_at": utc_now(),
        "sessions": ["20261015", "20261016"],
        "expected_symbol_count": EXPECTED_SYMBOLS,
        "symbols": symbols,
        "max_concurrency": MAX_CONCURRENCY,
        "max_raw_bytes": MAX_RAW_BYTES,
        "raw_bytes_saved_or_read": total_raw,
        "owner_artifact_path": str(OWNER_PATH),
        "owner_artifact_sha256": sha256(owner_bytes_before),
        "owner_artifact_trade_date": owner.get("trade_date"),
        "owner_capture_session_date": owner.get("market_snapshot", {}).get("capture_session_date"),
        "owner_captured_at": owner.get("market_snapshot", {}).get("captured_at"),
        "owner_capture_mode": owner.get("market_snapshot", {}).get("capture_mode"),
        "owner_late": owner.get("market_snapshot", {}).get("late"),
        "owner_unchanged_during_audit": owner_unchanged,
        "exact_match_count_20261015": sum(row.get("us20261015_equal") is True for row in successful),
        "exact_match_count_20261016": sum(row.get("us20261016_equal") is True for row in successful),
        "raw_root": RAW_ROOT.relative_to(HANDOFF_ROOT).as_posix(),
        "official_exchange_close_claim": False,
        "rows": results,
    }
    if args.fetch:
        RESULT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "symbol_count": len(results),
        "success_count": len(successful),
        "exact_match_count_20261015": result["exact_match_count_20261015"],
        "exact_match_count_20261016": result["exact_match_count_20261016"],
        "raw_bytes": total_raw,
        "owner_unchanged": owner_unchanged,
        "result_path": str(RESULT_PATH) if args.fetch else None,
        "errors": [{"symbol": row.get("symbol"), "error": row.get("error")}
                   for row in results if row.get("error")],
    }, indent=2, ensure_ascii=False))
    return 0 if pass_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
