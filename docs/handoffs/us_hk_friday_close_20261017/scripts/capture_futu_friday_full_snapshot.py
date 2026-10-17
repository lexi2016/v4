#!/usr/bin/env python3
"""One read-only Futu snapshot capture for the existing 448-code US universe."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
HANDOFF = HERE.parent
PREVIOUS = Path(__file__).resolve().parents[2] / "us_hk_mapping_today_20261016" / "futu_r1"
UNIVERSE_SOURCE = PREVIOUS / "snapshot_capture.json"
OUTPUT = HANDOFF / "evidence" / "futu_snapshot_full_capture.json"
TARGET_US_SESSION = "2026-10-16"
HOST = "127.0.0.1"
PORT = 11111
BATCH_SIZE = 400
MAX_SPLIT_DEPTH = 8
MAX_ATTEMPTS_PER_ROOT = 64


def now_local() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def split_pair(values: list[str]) -> tuple[list[str], list[str]]:
    middle = len(values) // 2
    return values[:middle], values[middle:]


def looks_global(error: str) -> bool:
    lowered = error.lower()
    return any(token in lowered for token in (
        "login", "connect", "connection", "opend", "timeout", "permission",
        "authoriz", "network", "disconnected", "session expired", "not connected",
    ))


def load_universe() -> list[str]:
    raw = json.loads(UNIVERSE_SOURCE.read_text(encoding="utf-8"))
    codes = raw.get("requested_codes")
    if not isinstance(codes, list) or len(codes) != 448 or len(set(codes)) != 448:
        raise RuntimeError("frozen Futu universe must contain 448 unique requested codes")
    if not {"US.DASH", "US.NTES", "US.UBER"}.issubset(set(codes)):
        raise RuntimeError("the three completed canary symbols are absent from the frozen universe")
    if any(not isinstance(code, str) or not code.startswith("US.") for code in codes):
        raise RuntimeError("frozen Futu universe contains a non-US code")
    return sorted(codes)


def main() -> int:
    from futu import OpenQuoteContext, RET_OK, __version__

    codes = load_universe()
    code_set_sha = hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest()
    capture: dict[str, Any] = {
        "schema_version": "futu-read-only-full-snapshot-v1",
        "target_us_session": TARGET_US_SESSION,
        "provider": "Futu OpenAPI Python SDK via local OpenD",
        "api": "OpenQuoteContext.get_market_snapshot",
        "host": HOST,
        "port": PORT,
        "sdk_version": __version__,
        "universe_source_file": str(UNIVERSE_SOURCE),
        "universe_source_sha256": sha256_file(UNIVERSE_SOURCE),
        "universe_count": len(codes),
        "universe_codes_sha256": code_set_sha,
        "requested_codes": codes,
        "request_contract": {
            "calls": ["get_market_snapshot"],
            "historical_kline_requested": False,
            "subscription_requested": False,
            "refresh_requested": False,
            "max_codes_per_call": BATCH_SIZE,
            "split_on_non_global_batch_failure": True,
            "max_split_depth": MAX_SPLIT_DEPTH,
            "max_attempts_per_initial_batch": MAX_ATTEMPTS_PER_ROOT,
        },
        "started_at_local": now_local(),
        "started_at_utc": now_utc(),
    }
    attempts: list[dict[str, Any]] = []
    raw_by_code: dict[str, dict[str, Any]] = {}
    terminal_by_code: dict[str, dict[str, Any]] = {}
    fatal_error: dict[str, str] | None = None
    global_stop = False
    context = None

    try:
        context = OpenQuoteContext(host=HOST, port=PORT)
        roots = [codes[index:index + BATCH_SIZE] for index in range(0, len(codes), BATCH_SIZE)]
        for root_index, root_codes in enumerate(roots, start=1):
            attempts_at_root = 0

            def query_group(group: list[str], depth: int, parent_id: str | None = None) -> None:
                nonlocal attempts_at_root, global_stop
                if not group:
                    return
                if attempts_at_root >= MAX_ATTEMPTS_PER_ROOT:
                    for code in group:
                        terminal_by_code[code] = {"status": "SPLIT_ATTEMPT_LIMIT", "parent_attempt_id": parent_id}
                    return
                if depth > MAX_SPLIT_DEPTH:
                    for code in group:
                        terminal_by_code[code] = {"status": "SPLIT_DEPTH_LIMIT", "parent_attempt_id": parent_id}
                    return

                attempts_at_root += 1
                attempt_id = f"B{root_index:02d}-A{attempts_at_root:03d}"
                attempt: dict[str, Any] = {
                    "attempt_id": attempt_id,
                    "parent_attempt_id": parent_id,
                    "root_batch_index": root_index,
                    "split_depth": depth,
                    "requested_at_local": now_local(),
                    "requested_at_utc": now_utc(),
                    "codes": group,
                }
                attempts.append(attempt)
                try:
                    ret, data = context.get_market_snapshot(group)
                    response = clean(data)
                    rows = [response] if isinstance(response, dict) else response if isinstance(response, list) else []
                    rows = [row for row in rows if isinstance(row, dict)]
                    attempt.update({"ret": int(ret), "response_rows": rows, "completed_at_local": now_local(), "completed_at_utc": now_utc()})
                    if int(ret) != int(RET_OK):
                        error = json.dumps(response, ensure_ascii=False, sort_keys=True)
                        attempt["error"] = error
                        if looks_global(error):
                            attempt["split_decision"] = "STOP_GLOBAL_ERROR"
                            global_stop = True
                            for code in group:
                                terminal_by_code[code] = {"status": "GLOBAL_OPENAPI_ERROR", "attempt_id": attempt_id, "error": error}
                            return
                        if len(group) == 1:
                            terminal_by_code[group[0]] = {"status": "QUERY_FAILED_SINGLETON", "attempt_id": attempt_id, "error": error}
                            return
                        attempt["split_decision"] = "SPLIT_NON_RET_OK"
                        left, right = split_pair(group)
                        query_group(left, depth + 1, attempt_id)
                        query_group(right, depth + 1, attempt_id)
                        return

                    rows_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
                    unexpected = []
                    for row in rows:
                        response_code = str(row.get("code") or "").strip()
                        if response_code not in group:
                            unexpected.append(row)
                        else:
                            rows_by_code[response_code].append(row)
                    duplicates = sorted(code for code, found in rows_by_code.items() if len(found) != 1)
                    for code, found in rows_by_code.items():
                        if len(found) == 1:
                            raw_by_code[code] = found[0]
                            terminal_by_code[code] = {"status": "SNAPSHOT_ROW_RETURNED", "attempt_id": attempt_id}
                    missing_or_ambiguous = sorted(set(group) - {code for code, found in rows_by_code.items() if len(found) == 1})
                    if unexpected or duplicates:
                        attempt["split_decision"] = "SPLIT_RESPONSE_IDENTITY_AMBIGUITY"
                    elif missing_or_ambiguous:
                        attempt["split_decision"] = "SPLIT_MISSING_CODES"
                    else:
                        attempt["split_decision"] = "COMPLETE"
                    attempt["unexpected_rows"] = unexpected
                    attempt["duplicate_codes"] = duplicates
                    if len(missing_or_ambiguous) == 1:
                        query_group(missing_or_ambiguous, depth + 1, attempt_id)
                    elif len(missing_or_ambiguous) > 1:
                        left, right = split_pair(missing_or_ambiguous)
                        query_group(left, depth + 1, attempt_id)
                        query_group(right, depth + 1, attempt_id)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    attempt.update({"ret": None, "error": error, "completed_at_local": now_local(), "completed_at_utc": now_utc()})
                    if looks_global(error):
                        attempt["split_decision"] = "STOP_GLOBAL_EXCEPTION"
                        global_stop = True
                        for code in group:
                            terminal_by_code[code] = {"status": "GLOBAL_OPENAPI_EXCEPTION", "attempt_id": attempt_id, "error": error}
                        return
                    if len(group) == 1:
                        terminal_by_code[group[0]] = {"status": "QUERY_EXCEPTION_SINGLETON", "attempt_id": attempt_id, "error": error}
                        return
                    attempt["split_decision"] = "SPLIT_EXCEPTION"
                    left, right = split_pair(group)
                    query_group(left, depth + 1, attempt_id)
                    query_group(right, depth + 1, attempt_id)

            query_group(root_codes, 0)
            if global_stop:
                break
    except Exception as exc:
        fatal_error = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if context is not None:
            context.close()

    for code in codes:
        terminal_by_code.setdefault(code, {"status": "NOT_ATTEMPTED_AFTER_GLOBAL_STOP"})
    capture.update({
        "completed_at_local": now_local(),
        "completed_at_utc": now_utc(),
        "attempts": attempts,
        "terminal_status_by_code": terminal_by_code,
        "snapshot_rows_by_code": raw_by_code,
        "fatal_error": fatal_error,
        "returned_code_count": len(raw_by_code),
        "terminal_code_count": len(terminal_by_code),
        "capture_complete": len(raw_by_code) == len(codes) and fatal_error is None,
    })
    capture["payload_sha256"] = hashlib.sha256(
        json.dumps(capture, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(capture, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "output_sha256": sha256_file(OUTPUT),
        "requested_code_count": len(codes),
        "returned_code_count": len(raw_by_code),
        "terminal_code_count": len(terminal_by_code),
        "attempt_count": len(attempts),
        "capture_complete": capture["capture_complete"],
        "fatal_error": fatal_error,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if raw_by_code else 2


if __name__ == "__main__":
    raise SystemExit(main())
