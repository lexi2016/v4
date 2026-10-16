#!/usr/bin/env python3
"""Read-only Futu snapshot capture and relation-level observation rebuild."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import capture_futu_daily as common


HERE = Path(__file__).resolve().parent
BASELINE_PATH = HERE.parent / "mapping_input_snapshot.json"
PROJECTION_PATH = HERE / "catalog_projection.json"
CANARY_PATH = HERE / "canary.json"
CAPTURE_PATH = HERE / "snapshot_capture.json"
FIRST_ATTEMPT_CAPTURE_PATH = HERE / "snapshot_capture_initial_otc_batch_attempt.json"
RESULTS_PATH = HERE / "results.json"
RELATIONS_CSV_PATH = HERE / "futu_relation_coverage.csv"
SYMBOLS_CSV_PATH = HERE / "futu_symbol_coverage.csv"
CANDIDATES_CSV_PATH = HERE / "candidate_stocks.csv"
POSITIVE_RELATIONS_CSV_PATH = HERE / "positive_relation_observations.csv"
TOP15_CSV_PATH = HERE / "top15_candidates.csv"
KLINE_CSV_PATH = HERE / "exact_daily_kline_subset.csv"
REPORT_PATH = HERE / "REPORT.md"
RECEIPT_PATH = HERE / "WRITER_RECEIPT.json"

CAPTURE_DATE = "2026-10-16"
LATEST_PRIOR_US_SESSION = "2026-10-15"
FUTU_HOST = "127.0.0.1"
FUTU_PORT = 11111
INITIAL_BATCH_SIZE = 400
MAX_ATTEMPTS_PER_INITIAL_BATCH = 64
MAX_SPLIT_DEPTH = 10
SAFETY = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_now() -> str:
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def write_json(path: Path, value: Any) -> None:
    common.write_json(path, value)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list)) else value
                for key, value in row.items()
            })


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def validate_snapshot(row: dict[str, Any] | None, query_status: str) -> dict[str, Any]:
    if not row:
        return {"valid": False, "status": query_status or "NOT_RETURNED"}
    update_time = str(row.get("update_time") or "").strip()
    match = TIME_RE.match(update_time)
    if not match:
        return {"valid": False, "status": "UPDATE_TIME_MISSING_OR_UNPARSEABLE"}
    update_date = match.group(1)
    if update_date < LATEST_PRIOR_US_SESSION:
        return {"valid": False, "status": "STALE_UPDATE_TIME"}
    if update_date > CAPTURE_DATE:
        return {"valid": False, "status": "UPDATE_TIME_AFTER_CAPTURE_DATE"}
    last_price = number(row.get("last_price"))
    previous_close = number(row.get("prev_close_price"))
    if last_price is None or last_price <= 0:
        return {"valid": False, "status": "LAST_PRICE_MISSING_OR_INVALID"}
    if previous_close is None or previous_close <= 0:
        return {"valid": False, "status": "PREV_CLOSE_MISSING_OR_INVALID"}
    metric = (last_price / previous_close - 1.0) * 100.0
    return {
        "valid": True,
        "status": "READY",
        "snapshot_change_pct_vs_prev_close": metric,
        "metric_definition": "(last_price / prev_close_price - 1) * 100",
        "metric_label": "snapshot last price versus API previous close",
        "update_time": update_time,
        "last_price": last_price,
        "prev_close_price": previous_close,
        "pre_price": number(row.get("pre_price")),
        "update_date": update_date,
    }


def split_pair(values: list[str]) -> tuple[list[str], list[str]]:
    middle = len(values) // 2
    return values[:middle], values[middle:]


def looks_like_global_error(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in (
        "login", "connect", "connection", "opend", "timeout", "permission",
        "authoriz", "network", "disconnected", "not connected", "session expired",
    ))


def is_otc_only(symbol: dict[str, Any]) -> bool:
    evidence = [str(value) for value in (symbol.get("exchange_evidence") or [])]
    joined = " | ".join(evidence)
    # Remove explicit negative references such as "非NYSE/Nasdaq" before checking
    # whether the evidence actually names a supported primary exchange.
    positive_scan = re.sub(r"非\s*(?:NYSE|NASDAQ)(?:\s*/\s*(?:NYSE|NASDAQ))*", "", joined, flags=re.IGNORECASE)
    positive_scan = re.sub(r"\b(?:NON|NOT)\s*[- ]?(?:NYSE|NASDAQ)(?:\s*/\s*(?:NYSE|NASDAQ))*", "", positive_scan, flags=re.IGNORECASE)
    has_otc = bool(re.search(r"OTC", joined, flags=re.IGNORECASE))
    has_explicit_exchange = bool(re.search(r"NYSE|NASDAQ", positive_scan, flags=re.IGNORECASE))
    return has_otc and not has_explicit_exchange


def capture_snapshots(projection: dict[str, Any]) -> dict[str, Any]:
    from futu import OpenQuoteContext, RET_OK

    all_active_symbols = [
        row for row in projection["symbols"]
        if row.get("market_class") == "US_LISTED_ACTIVE" and row.get("futu_code")
    ]
    otc_only_symbols = [row for row in all_active_symbols if is_otc_only(row)]
    eligible = sorted(row["futu_code"] for row in all_active_symbols if not is_otc_only(row))
    if len(all_active_symbols) != 493 or len(set(row["futu_code"] for row in all_active_symbols)) != 493:
        raise RuntimeError("active US symbol set changed from the frozen 493-symbol projection")

    prior_capture_sha = common.sha256_file(CAPTURE_PATH) if CAPTURE_PATH.exists() else None
    if prior_capture_sha and not FIRST_ATTEMPT_CAPTURE_PATH.exists():
        shutil.copyfile(CAPTURE_PATH, FIRST_ATTEMPT_CAPTURE_PATH)

    started_utc = utc_now()
    started_local = local_now()
    attempts: list[dict[str, Any]] = []
    per_code: dict[str, dict[str, Any]] = {
        row["futu_code"]: {
            "status": "FUTU_OTC_MARKET_UNSUPPORTED",
            "exchange_evidence": row.get("exchange_evidence"),
            "basis": "Futu returned a market-wide OTC unsupported error during the initial mixed-batch request",
            "initial_error_example": "暂不提供美股 OTC 市场行情 AAGIY",
        }
        for row in otc_only_symbols
    }
    raw_rows: dict[str, dict[str, Any]] = {}
    fatal_context_error: dict[str, str] | None = None
    ctx = None
    try:
        ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
        roots = [eligible[i:i + INITIAL_BATCH_SIZE] for i in range(0, len(eligible), INITIAL_BATCH_SIZE)]
        for root_index, root_codes in enumerate(roots, start=1):
            root_attempts = 0

            def query_group(codes: list[str], depth: int, parent_id: str | None = None) -> None:
                nonlocal root_attempts
                if not codes:
                    return
                if root_attempts >= MAX_ATTEMPTS_PER_INITIAL_BATCH:
                    for code in codes:
                        per_code[code] = {
                            "status": "SPLIT_ATTEMPT_LIMIT",
                            "terminal_parent_attempt_id": parent_id,
                        }
                    return
                if depth > MAX_SPLIT_DEPTH:
                    for code in codes:
                        per_code[code] = {
                            "status": "SPLIT_DEPTH_LIMIT",
                            "terminal_parent_attempt_id": parent_id,
                        }
                    return

                root_attempts += 1
                attempt_id = "B%02d-A%03d" % (root_index, root_attempts)
                requested_at = utc_now()
                attempt: dict[str, Any] = {
                    "attempt_id": attempt_id,
                    "parent_attempt_id": parent_id,
                    "root_batch_index": root_index,
                    "split_depth": depth,
                    "request": {"api": "get_market_snapshot", "code_list": list(codes)},
                    "requested_at_utc": requested_at,
                }
                attempts.append(attempt)
                try:
                    ret, data = ctx.get_market_snapshot(codes)
                    cleaned_data = common.clean(data)
                    rows = cleaned_data
                    if isinstance(rows, dict):
                        rows = [rows]
                    if not isinstance(rows, list):
                        rows = []
                    response_rows = [row for row in rows if isinstance(row, dict)]
                    attempt["ret"] = int(ret)
                    attempt["response_row_count"] = len(response_rows)
                    attempt["response_rows"] = response_rows
                    attempt["response_data"] = cleaned_data
                    attempt["completed_at_utc"] = utc_now()
                    if ret != RET_OK:
                        error_text = json.dumps(cleaned_data, ensure_ascii=False, sort_keys=True)
                        attempt["error"] = error_text or "Futu get_market_snapshot returned non-RET_OK"
                        if looks_like_global_error(attempt["error"]):
                            attempt["split_decision"] = "STOP_GLOBAL_OPENAPI_ERROR"
                            for code in codes:
                                per_code[code] = {
                                    "status": "GLOBAL_OPENAPI_ERROR",
                                    "terminal_parent_attempt_id": attempt_id,
                                    "error": attempt["error"],
                                }
                            return
                        if len(codes) == 1:
                            per_code[codes[0]] = {
                                "status": "QUERY_FAILED_SINGLETON",
                                "terminal_parent_attempt_id": attempt_id,
                                "ret": int(ret),
                                "error": attempt["error"],
                            }
                            return
                        attempt["split_decision"] = "SPLIT_NON_RET_OK"
                        left, right = split_pair(codes)
                        query_group(left, depth + 1, attempt_id)
                        query_group(right, depth + 1, attempt_id)
                        return

                    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
                    unexpected: list[dict[str, Any]] = []
                    for row in response_rows:
                        response_code = str(row.get("code") or "").strip()
                        if response_code not in codes:
                            unexpected.append(row)
                        else:
                            by_code[response_code].append(row)
                    attempt["unexpected_rows"] = unexpected
                    duplicates = sorted(code for code, found in by_code.items() if len(found) != 1)
                    found_codes = sorted(code for code, found in by_code.items() if len(found) == 1)
                    for code in found_codes:
                        raw_rows[code] = by_code[code][0]
                        per_code[code] = {
                            "status": "SNAPSHOT_ROW_RETURNED",
                            "attempt_id": attempt_id,
                            "terminal_parent_attempt_id": attempt_id,
                        }
                    missing = sorted(set(codes) - set(found_codes))
                    if unexpected or duplicates:
                        attempt["split_decision"] = "SPLIT_RESPONSE_IDENTITY_AMBIGUITY"
                        # Returned unique rows are retained; only ambiguous/missing codes are retried.
                        retry = sorted(set(missing) | set(duplicates))
                    else:
                        retry = missing
                        attempt["split_decision"] = "SPLIT_MISSING_CODES" if retry else "COMPLETE"
                    if retry:
                        if len(retry) == 1:
                            # One isolated request distinguishes an omitted row from batch truncation.
                            query_group(retry, depth + 1, attempt_id)
                        else:
                            left, right = split_pair(retry)
                            query_group(left, depth + 1, attempt_id)
                            query_group(right, depth + 1, attempt_id)
                except Exception as exc:
                    attempt["ret"] = None
                    attempt["error"] = "%s: %s" % (type(exc).__name__, str(exc))
                    attempt["completed_at_utc"] = utc_now()
                    if looks_like_global_error(attempt["error"]):
                        attempt["split_decision"] = "STOP_GLOBAL_OPENAPI_ERROR"
                        for code in codes:
                            per_code[code] = {
                                "status": "GLOBAL_OPENAPI_ERROR",
                                "terminal_parent_attempt_id": attempt_id,
                                "error": attempt["error"],
                            }
                        return
                    if len(codes) == 1:
                        per_code[codes[0]] = {
                            "status": "QUERY_EXCEPTION_SINGLETON",
                            "terminal_parent_attempt_id": attempt_id,
                            "error": attempt["error"],
                        }
                        return
                    attempt["split_decision"] = "SPLIT_EXCEPTION"
                    left, right = split_pair(codes)
                    query_group(left, depth + 1, attempt_id)
                    query_group(right, depth + 1, attempt_id)

            query_group(root_codes, 0)
    except Exception as exc:
        fatal_context_error = {"type": type(exc).__name__, "message": str(exc)}
        for code in eligible:
            per_code.setdefault(code, {
                "status": "OPEN_CONTEXT_FAILED",
                "error": "%s: %s" % (type(exc).__name__, str(exc)),
            })
    finally:
        if ctx is not None:
            ctx.close()

    # Preserve an explicit terminal state for every requested symbol, including stopped descendants.
    for code in eligible:
        per_code.setdefault(code, {"status": "NOT_ATTEMPTED_AFTER_OPENAPI_STOP"})
    capture = {
        "schema_version": "futu-r1-snapshot-capture-v1",
        "provider": "Futu OpenAPI Python SDK via local OpenD",
        "api": "OpenQuoteContext.get_market_snapshot",
        "opend_host": FUTU_HOST,
        "opend_port": FUTU_PORT,
        "sdk_version": __import__("futu").__version__,
        "mapping_projection_sha256": projection["projection_sha256"],
        "catalog_identity": projection["source"],
        "capture_date_local": CAPTURE_DATE,
        "started_at_utc": started_utc,
        "started_at_local": started_local,
        "completed_at_utc": utc_now(),
        "completed_at_local": local_now(),
        "request_contract": {
            "initial_batch_size": INITIAL_BATCH_SIZE,
            "documented_snapshot_limit": 400,
            "per_initial_batch_attempt_limit": MAX_ATTEMPTS_PER_INITIAL_BATCH,
            "max_split_depth": MAX_SPLIT_DEPTH,
            "fields_preserved": "all Futu response fields, including update_time, last_price, prev_close_price, and pre_price",
        },
        "requested_codes": eligible,
        "target_codes": sorted(row["futu_code"] for row in all_active_symbols),
        "requested_code_count": len(eligible),
        "target_code_count": len(all_active_symbols),
        "provider_unsupported_codes": sorted(row["futu_code"] for row in otc_only_symbols),
        "prior_mixed_batch_capture_sha256": prior_capture_sha,
        "prior_mixed_batch_capture_file": FIRST_ATTEMPT_CAPTURE_PATH.name if FIRST_ATTEMPT_CAPTURE_PATH.exists() else None,
        "terminal_status_by_code": per_code,
        "snapshot_rows_by_code": raw_rows,
        "attempts": attempts,
        "fatal_context_error": fatal_context_error,
        "capture_complete": len(per_code) == len(all_active_symbols),
        "all_symbols_returned": len(raw_rows) == len(eligible),
    }
    write_json(CAPTURE_PATH, capture)
    return capture


def load_exact_kline_rows() -> list[dict[str, Any]]:
    canary = common.read_json(CANARY_PATH)
    if canary.get("status") != "TESTED" or canary.get("target_us_session_date") != "20261015":
        raise RuntimeError("three-symbol exact daily-K canary is not TESTED for 2026-10-15")
    rows: list[dict[str, Any]] = []
    for capture in canary.get("canary_requests", []):
        request = capture.get("request") or {}
        response = capture.get("response_rows") or []
        code = str(request.get("code") or "")
        exact = [row for row in response if str(row.get("time_key") or "")[:10] == LATEST_PRIOR_US_SESSION]
        if capture.get("ret") != 0 or len(exact) != 1:
            raise RuntimeError("exact daily-K canary row is ambiguous for " + code)
        daily = exact[0]
        close = number(daily.get("close"))
        last_close = number(daily.get("last_close"))
        change_rate = number(daily.get("change_rate"))
        derived = ((close / last_close) - 1.0) * 100.0 if close and last_close and last_close > 0 else None
        if close is None or last_close is None or change_rate is None or derived is None or abs(change_rate - derived) > 0.05:
            raise RuntimeError("exact daily-K values failed close/last_close consistency for " + code)
        rows.append({
            "futu_code": code,
            "us_symbol": code.removeprefix("US."),
            "target_session_date": LATEST_PRIOR_US_SESSION,
            "time_key": daily.get("time_key"),
            "close": close,
            "last_close": last_close,
            "change_rate": change_rate,
            "derived_change_pct": derived,
            "validation_status": "EXACT_2026_10_15_K_DAY_CANARY",
            "request": request,
            "requested_at_utc": capture.get("requested_at_utc"),
            "page_req_key": capture.get("page_req_key"),
            "ret": capture.get("ret"),
        })
    if {row["futu_code"] for row in rows} != {"US.DASH", "US.NTES", "US.UBER"}:
        raise RuntimeError("the exact-date subset must remain the original three K-line canaries")
    return rows


def build_outputs() -> dict[str, Any]:
    projection = common.read_json(PROJECTION_PATH)
    if common.canonical_hash(projection, "projection_sha256") != projection.get("projection_sha256"):
        raise RuntimeError("catalog projection canonical SHA mismatch")
    capture = common.read_json(CAPTURE_PATH)
    if capture.get("mapping_projection_sha256") != projection.get("projection_sha256"):
        raise RuntimeError("snapshot capture belongs to a different catalog projection")
    if capture.get("target_code_count") != 493 or capture.get("requested_code_count") != 448:
        raise RuntimeError("snapshot capture target is not 493 active US symbols with OTC-only symbols isolated")
    baseline = common.verify_baseline()
    if len(baseline.get("relations", [])) != 1003:
        raise RuntimeError("frozen baseline relation count changed")

    status_by_code = capture.get("terminal_status_by_code") or {}
    raw_by_code = capture.get("snapshot_rows_by_code") or {}
    symbol_by_code = {row.get("futu_code"): row for row in projection["symbols"] if row.get("futu_code")}
    symbol_rows: list[dict[str, Any]] = []
    metric_by_code: dict[str, dict[str, Any]] = {}
    for symbol in projection["symbols"]:
        code = symbol.get("futu_code") or ""
        terminal = status_by_code.get(code) or {}
        raw = raw_by_code.get(code)
        query_status = terminal.get("status") or ("NOT_APPLICABLE" if not code else "NOT_ATTEMPTED")
        metric = validate_snapshot(raw, query_status)
        if raw and query_status == "SNAPSHOT_ROW_RETURNED":
            metric_by_code[code] = metric
        row = {
            **symbol,
            "query_status": query_status,
            "observation_status": metric.get("status"),
            "update_time": (raw or {}).get("update_time"),
            "last_price": metric.get("last_price"),
            "prev_close_price": metric.get("prev_close_price"),
            "snapshot_change_pct_vs_prev_close": metric.get("snapshot_change_pct_vs_prev_close"),
            "pre_price": metric.get("pre_price"),
            "attempt_id": terminal.get("attempt_id"),
            "error": terminal.get("error"),
            "raw_snapshot": raw,
        }
        symbol_rows.append(row)

    relations = projection.get("relations") or []
    if len(relations) != 1003 or len({r.get("relation_id") for r in relations}) != 1003:
        raise RuntimeError("catalog projection relation identity is not 1,003 unique rows")
    relation_rows: list[dict[str, Any]] = []
    for relation in relations:
        code = "US." + str(relation.get("us_symbol") or "") if relation.get("us_symbol") in {s.get("us_symbol") for s in projection["symbols"] if s.get("futu_code")} else ""
        meta = symbol_by_code.get(code)
        query_state = status_by_code.get(code) or {}
        raw = raw_by_code.get(code)
        metric = validate_snapshot(raw, query_state.get("status") or "NOT_RETURNED") if meta else {"valid": False, "status": "SYMBOL_NOT_ELIGIBLE_FOR_FUTU"}
        closure = relation.get("closure_status")
        if closure == "OPEN":
            bucket = "open"
        elif closure == "CLOSED_EXCLUDED_SCOPE":
            bucket = "excluded"
        elif closure == "CLOSED_RESEARCH_SCOPE":
            if metric.get("valid"):
                bucket = "positive" if metric["snapshot_change_pct_vs_prev_close"] > 0 else "flat-negative"
            else:
                bucket = "missing"
        else:
            raise RuntimeError("unknown relation closure state for %s: %r" % (relation.get("relation_id"), closure))
        relation_rows.append({
            **relation,
            "market_class": (meta or {}).get("market_class"),
            "futu_code": code,
            "query_status": query_state.get("status") if meta else "SYMBOL_NOT_ELIGIBLE_FOR_FUTU",
            "observation_status": metric.get("status"),
            "update_time": (raw or {}).get("update_time"),
            "last_price": metric.get("last_price"),
            "prev_close_price": metric.get("prev_close_price"),
            "snapshot_change_pct_vs_prev_close": metric.get("snapshot_change_pct_vs_prev_close"),
            "pre_price": metric.get("pre_price"),
            "metric_definition": metric.get("metric_definition"),
            "metric_label": metric.get("metric_label"),
            "bucket": bucket,
            "query_error": query_state.get("error"),
        })
    if len(relation_rows) != 1003 or len({row["relation_id"] for row in relation_rows}) != 1003:
        raise RuntimeError("relation coverage does not conserve all 1,003 relations")

    buckets = Counter(row["bucket"] for row in relation_rows)
    if sum(buckets.values()) != 1003 or set(buckets) - {"positive", "flat-negative", "missing", "open", "excluded"}:
        raise RuntimeError("relation bucket conservation failed")
    positive_rows = [row for row in relation_rows if row["bucket"] == "positive"]
    by_hk: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in positive_rows:
        by_hk[str(row["hk_code"])].append(row)
    candidates: list[dict[str, Any]] = []
    for hk_code, rows in by_hk.items():
        ranked = sorted(rows, key=lambda row: (-float(row["snapshot_change_pct_vs_prev_close"]), row["us_symbol"], row["relation_id"]))
        best = ranked[0]
        candidates.append({
            "hk_code": hk_code,
            "hk_name": best.get("hk_name"),
            "best_us_symbol": best.get("us_symbol"),
            "best_us_name": best.get("us_name"),
            "best_snapshot_change_pct_vs_prev_close": best.get("snapshot_change_pct_vs_prev_close"),
            "best_update_time": best.get("update_time"),
            "best_last_price": best.get("last_price"),
            "best_prev_close_price": best.get("prev_close_price"),
            "best_pre_price_separate": best.get("pre_price"),
            "positive_relation_count": len(ranked),
            "positive_relation_ids": [row["relation_id"] for row in ranked],
            "positive_relations": ranked,
        })
    candidates.sort(key=lambda row: (-float(row["best_snapshot_change_pct_vs_prev_close"]), str(row["hk_code"]), str(row["best_us_symbol"])))
    top15 = candidates[:15]
    positive_rows.sort(key=lambda row: (-float(row["snapshot_change_pct_vs_prev_close"]), str(row["hk_code"]), row["relation_id"]))

    relation_columns = list(dict.fromkeys([*relations[0].keys(), "market_class", "futu_code", "query_status", "observation_status", "update_time", "last_price", "prev_close_price", "snapshot_change_pct_vs_prev_close", "pre_price", "metric_definition", "metric_label", "bucket", "query_error"]))
    symbol_columns = list(dict.fromkeys([*projection["symbols"][0].keys(), "query_status", "observation_status", "update_time", "last_price", "prev_close_price", "snapshot_change_pct_vs_prev_close", "pre_price", "attempt_id", "error", "raw_snapshot"]))
    candidate_columns = ["rank", "hk_code", "hk_name", "best_us_symbol", "best_us_name", "best_snapshot_change_pct_vs_prev_close", "best_update_time", "best_last_price", "best_prev_close_price", "best_pre_price_separate", "positive_relation_count", "positive_relation_ids", "positive_relations"]
    positive_columns = relation_columns
    top15_columns = ["rank"] + candidate_columns

    write_csv(RELATIONS_CSV_PATH, relation_rows, relation_columns)
    write_csv(SYMBOLS_CSV_PATH, symbol_rows, symbol_columns)
    write_csv(POSITIVE_RELATIONS_CSV_PATH, positive_rows, positive_columns)
    candidate_rows = [{"rank": index, **row} for index, row in enumerate(candidates, start=1)]
    top15_rows = [{"rank": index, **row} for index, row in enumerate(top15, start=1)]
    write_csv(CANDIDATES_CSV_PATH, candidate_rows, candidate_columns)
    write_csv(TOP15_CSV_PATH, top15_rows, top15_columns)

    kline_rows = load_exact_kline_rows()
    write_csv(KLINE_CSV_PATH, kline_rows, ["futu_code", "us_symbol", "target_session_date", "time_key", "close", "last_close", "change_rate", "derived_change_pct", "validation_status", "request", "requested_at_utc", "page_req_key", "ret"])

    returned_active = sum(1 for row in symbol_rows if row.get("market_class") == "US_LISTED_ACTIVE" and row.get("query_status") == "SNAPSHOT_ROW_RETURNED")
    valid_active = sum(1 for row in symbol_rows if row.get("market_class") == "US_LISTED_ACTIVE" and row.get("observation_status") == "READY")
    source = projection["source"]
    results = {
        "schema_version": "futu-r1-snapshot-observation-results-v1",
        "created_at_utc": utc_now(),
        "capture_started_at_utc": capture.get("started_at_utc"),
        "capture_completed_at_utc": capture.get("completed_at_utc"),
        "snapshot_observation_date": CAPTURE_DATE,
        "provider": capture.get("provider"),
        "request_contract": {
            "api": "get_market_snapshot",
            "initial_batch_size": INITIAL_BATCH_SIZE,
            "maximum_batch_size": INITIAL_BATCH_SIZE,
            "metric_definition": "(last_price / prev_close_price - 1) * 100",
            "metric_label": "snapshot last price versus API previous close",
            "pre_price_role": "separate field; excluded from snapshot metric and ranking",
            "update_time_required": True,
        },
        "safety": SAFETY,
        "source_identity": source,
        "capture_complete": capture.get("capture_complete"),
        "snapshot_capture_file_sha256": common.sha256_file(CAPTURE_PATH),
        "canary_file_sha256": common.sha256_file(CANARY_PATH),
        "catalog_projection_file_sha256": common.sha256_file(PROJECTION_PATH),
        "symbol_coverage": {
            "catalog_symbols": len(symbol_rows),
            "active_us_eligible_symbols": 493,
            "active_us_symbols_requested_from_futu": capture.get("requested_code_count"),
            "otc_only_symbols_isolated_as_unsupported": len(capture.get("provider_unsupported_codes", [])),
            "snapshot_rows_returned": returned_active,
            "valid_current_observations": valid_active,
            "terminal_status_counts": dict(sorted(Counter(row["query_status"] for row in symbol_rows if row.get("market_class") == "US_LISTED_ACTIVE").items())),
            "observation_status_counts": dict(sorted(Counter(row["observation_status"] for row in symbol_rows if row.get("market_class") == "US_LISTED_ACTIVE").items())),
        },
        "relation_buckets": {key: int(buckets.get(key, 0)) for key in ("positive", "flat-negative", "missing", "open", "excluded")},
        "relation_bucket_conservation": {"expected_relations": 1003, "sum": int(sum(buckets.values())), "pass": len(relation_rows) == 1003 and sum(buckets.values()) == 1003},
        "candidate_rule": {
            "deduplication_key": "hk_code",
            "included_bucket": "positive",
            "positive_threshold": "snapshot_change_pct_vs_prev_close > 0 and observation_status == READY",
            "display_order": "best linked US snapshot change descending, then HK code ascending",
            "candidate_count": len(candidates),
            "full_candidate_table": CANDIDATES_CSV_PATH.name,
            "markdown_display_limit": 15,
        },
        "exact_daily_kline_subset": {
            "date": LATEST_PRIOR_US_SESSION,
            "codes": [row["futu_code"] for row in kline_rows],
            "rows": len(kline_rows),
            "file": KLINE_CSV_PATH.name,
            "used_for_snapshot_ranking": False,
        },
        "cannot_confirm": [
            "Current Futu snapshot is a late 2026-10-16 observation and does not establish availability before the Hong Kong session.",
            "The snapshot last-price versus API previous-close metric is not asserted to be an exact 2026-10-15 session return.",
            "pre_price is preserved separately and is not used to rank observations.",
            "Futu returned an explicit OTC-market-unsupported error in the first mixed batch; 45 OTC-only catalog symbols are isolated as unsupported, with the original response and split attempts retained.",
            "%s returned snapshot rows lacked a parseable update_time and are excluded from positive/flat-negative classification." % sum(1 for row in symbol_rows if row.get("market_class") == "US_LISTED_ACTIVE" and row.get("observation_status") == "UPDATE_TIME_MISSING_OR_UNPARSEABLE"),
            "The three exact 2026-10-15 daily-K canaries are a separate subset and do not provide full-universe daily-K coverage.",
            "Mapping relationships remain research observations; no independent fact acceptance, prediction validation, causal conclusion, or BUY decision is asserted.",
        ],
        "artifact_paths": {
            "snapshot_capture": CAPTURE_PATH.name,
            "initial_mixed_batch_failure_evidence": FIRST_ATTEMPT_CAPTURE_PATH.name if FIRST_ATTEMPT_CAPTURE_PATH.exists() else None,
            "symbol_coverage": SYMBOLS_CSV_PATH.name,
            "relation_coverage": RELATIONS_CSV_PATH.name,
            "candidate_table": CANDIDATES_CSV_PATH.name,
            "positive_relation_observations": POSITIVE_RELATIONS_CSV_PATH.name,
            "top15": TOP15_CSV_PATH.name,
            "exact_daily_kline_subset": KLINE_CSV_PATH.name,
            "report": REPORT_PATH.name,
        },
    }
    write_json(RESULTS_PATH, results)
    REPORT_PATH.write_text(render_report(results, top15, buckets, symbol_rows, kline_rows), encoding="utf-8")
    write_receipt(results)
    return results


def render_report(results: dict[str, Any], top15: list[dict[str, Any]], buckets: Counter[str], symbol_rows: list[dict[str, Any]], kline_rows: list[dict[str, Any]]) -> str:
    coverage = results["symbol_coverage"]
    missing_update_time = coverage["observation_status_counts"].get("UPDATE_TIME_MISSING_OR_UNPARSEABLE", 0)
    lines = [
        "# 2026-10-16 美股 Futu 当前快照观察",
        "",
        "本表使用 Futu OpenAPI `get_market_snapshot` 当前快照字段。观察排序指标为 `(last_price / prev_close_price - 1) * 100`，即快照 `last_price` 相对 API `prev_close_price` 的变化；保留每行 `update_time`，并将 `pre_price` 单独列出。该指标不等同于精确的 2026-10-15 美股收盘涨幅，也不证明该观察在 2026-10-16 港股开盘前可得。",
        "",
        "没有评分、预测、买入建议或交易授权。港美股关系仅为当前目录研究关系，观察涨幅不表示因果或港股方向。",
        "",
        "## 覆盖",
        "",
        f"- 当前 catalog 共 {coverage['catalog_symbols']} 个美股/相关符号，其中 {coverage['active_us_eligible_symbols']} 个经 catalog 交易所证据分类为 active US-listed security。",
        f"- 对排除已证实不提供行情的 OTC-only 市场代码后，Futu 请求 {coverage['active_us_symbols_requested_from_futu']} 个代码，返回 {coverage['snapshot_rows_returned']} 行；其中 {coverage['valid_current_observations']} 行通过时间戳和价格字段校验。另有 {coverage['otc_only_symbols_isolated_as_unsupported']} 个 OTC-only 代码保留为 provider unsupported 缺口，{missing_update_time} 行因 update_time 缺失或无法解析而不进入正/负涨分类。",
        f"- 映射关系完整覆盖 {sum(buckets.values())} 条，按 OPEN/排除优先级分桶：positive {buckets.get('positive', 0)}、flat-negative {buckets.get('flat-negative', 0)}、missing {buckets.get('missing', 0)}、open {buckets.get('open', 0)}、excluded {buckets.get('excluded', 0)}。",
        f"- 正涨关联关系去重后为 {results['candidate_rule']['candidate_count']} 只港股；完整候选见 `{CANDIDATES_CSV_PATH.name}`，完整关系覆盖见 `{RELATIONS_CSV_PATH.name}`。",
        f"- Exact daily-K subset 仅含 {len(kline_rows)} 个 2026-10-15 canary symbols，保存在 `{KLINE_CSV_PATH.name}`；它们没有混入当前 snapshot 排序。",
        "",
        "## 描述性正涨关联观察（前 15）",
        "",
        "|序|港股代码 / 名称|正涨关联美股（快照变化，更新时间）|用途范围|研究状态|待补要点|",
        "|---:|---|---|---|---|---|",
    ]
    relations_by_hk: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # Candidate rows carry relation details, so use them to render full positive links.
    for rank, candidate in enumerate(top15, start=1):
        details = candidate.get("positive_relations") or []
        links = "；".join(
            "%s %s (%.3f%%, %s, %s)" % (
                row.get("us_symbol"), row.get("us_name"),
                float(row.get("snapshot_change_pct_vs_prev_close")), row.get("relation_id"), row.get("update_time") or "update_time missing",
            ) for row in details
        )
        use = "；".join(sorted({str(row.get("current_use_scope") or "") for row in details if row.get("current_use_scope")})) or "CANNOT_CONFIRM"
        status = "；".join(sorted({str(row.get("research_status") or "CANNOT_CONFIRM") for row in details}))
        gaps = "；".join(sorted({str(gap) for row in details for gap in (row.get("remaining_gaps") or [])}))
        lines.append(f"|{rank}|{candidate.get('hk_code')} {candidate.get('hk_name')}|{links}|{use}|{status}|{gaps}|")
    lines.extend([
        "",
        "## 关系覆盖分桶",
        "",
        "|分桶|关系数|口径|",
        "|---|---:|---|",
        f"|positive|{buckets.get('positive', 0)}|CLOSED_RESEARCH_SCOPE 且有效快照指标 > 0|",
        f"|flat-negative|{buckets.get('flat-negative', 0)}|CLOSED_RESEARCH_SCOPE 且有效快照指标 ≤ 0|",
        f"|missing|{buckets.get('missing', 0)}|CLOSED_RESEARCH_SCOPE 且未获得有效快照观察|",
        f"|open|{buckets.get('open', 0)}|OPEN；不进候选|",
        f"|excluded|{buckets.get('excluded', 0)}|CLOSED_EXCLUDED_SCOPE；不进候选|",
        f"|合计|{sum(buckets.values())}|与冻结 R0 的 1,003 条关系守恒|",
        "",
        "## 缺口与解释边界",
        "",
        "- snapshot 更新时点、`last_price`、`prev_close_price` 和 `pre_price` 按 Futu 原始字段保留在 `snapshot_capture.json`、`futu_symbol_coverage.csv` 与关系覆盖表；排名不使用 `pre_price`。",
        "- 各失败批次按确定顺序拆分，达到单代码、深度或每个初始批次的尝试上限后保留原始错误和终态，不将失败解释为无行情。",
        f"- 初次混合批次的 Futu 错误原文示例：`{json.dumps('暂不提供美股 OTC 市场行情 AAGIY', ensure_ascii=False)}`；初次请求和拆分过程保存在 `{FIRST_ATTEMPT_CAPTURE_PATH.name}`。",
        "- OPEN 与排除关系即使有行情，也不会进入候选；候选只是研究观察排序，不证明关联有效、事实独立验收、港股方向、预测能力或经济因果。",
        "- 2026-10-15 exact daily-K canary 仅 3 只，用于绑定当日 K 线字段，不作为这次广覆盖 snapshot 的回报替代或排名来源。",
        "",
        "## 输入与复现",
        "",
        f"- catalog projection SHA-256：`{results['source_identity']['catalog_integrity_sha256']}`；映射 snapshot SHA-256：`{results['source_identity']['baseline_snapshot_sha256']}`。",
        f"- Futu snapshot capture SHA-256：`{results['snapshot_capture_file_sha256']}`；捕获时间（UTC）：`{results['capture_completed_at_utc']}`。",
        "- 复现：`'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_snapshot.py --verify`。",
        "- 原始 2026-10-15 exact K-line canary 已记录于 `canary.json`，历史查询额度不再扩展。",
        "",
    ])
    return "\n".join(lines)


def write_receipt(results: dict[str, Any]) -> None:
    artifact_paths = [
        Path(__file__), HERE / "capture_futu_daily.py", PROJECTION_PATH, CANARY_PATH, CAPTURE_PATH,
        FIRST_ATTEMPT_CAPTURE_PATH,
        RESULTS_PATH, RELATIONS_CSV_PATH, SYMBOLS_CSV_PATH, CANDIDATES_CSV_PATH,
        POSITIVE_RELATIONS_CSV_PATH, TOP15_CSV_PATH, KLINE_CSV_PATH, REPORT_PATH, HERE / "SCOPE_R1.md",
    ]
    receipt = {
        "schema_version": "futu-r1-snapshot-writer-receipt-v1",
        "status": "TESTED",
        "independent_review": "PENDING_DIFFERENT_IDENTITY_LUNA_MAX_REVIEWER",
        "created_at_utc": utc_now(),
        "writer": "/root/today_mapping_observation_writer",
        "scope": "futu_r1/** and top-level REPORT.md pointer only",
        "source_identity": results["source_identity"],
        "request_contract": results["request_contract"],
        "safety": SAFETY,
        "capture_complete": results["capture_complete"],
        "relation_buckets": results["relation_buckets"],
        "relation_bucket_conservation": results["relation_bucket_conservation"],
        "commands_run": [
            "'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -m py_compile docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_daily.py docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_snapshot.py",
            "'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_daily.py --canary (initial three-symbol daily-K capture)",
            "'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_daily.py --canary (saved-canary replay; no history request)",
            "'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_snapshot.py --capture (initial mixed-OTC attempt; preserved as snapshot_capture_initial_otc_batch_attempt.json)",
            "'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_snapshot.py --capture",
            "'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_snapshot.py --rebuild",
            "'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_snapshot.py --verify",
        ],
        "artifact_sha256": {
            str(path.relative_to(HERE)): common.sha256_file(path)
            for path in artifact_paths if path.exists()
        },
        "top_level_report_sha256": common.sha256_file(HERE.parent / "REPORT.md") if (HERE.parent / "REPORT.md").exists() else None,
        "unresolved": results["cannot_confirm"],
    }
    write_json(RECEIPT_PATH, receipt)


def verify_outputs() -> dict[str, Any]:
    projection = common.read_json(PROJECTION_PATH)
    capture = common.read_json(CAPTURE_PATH)
    results = common.read_json(RESULTS_PATH)
    if common.canonical_hash(projection, "projection_sha256") != projection.get("projection_sha256"):
        raise RuntimeError("catalog projection SHA mismatch")
    if capture.get("mapping_projection_sha256") != projection.get("projection_sha256"):
        raise RuntimeError("snapshot capture projection identity mismatch")
    if capture.get("target_code_count") != 493 or len(capture.get("requested_codes", [])) != 448 or len(capture.get("terminal_status_by_code", {})) != 493:
        raise RuntimeError("snapshot capture terminal status does not conserve 493 active codes and 448 provider-requested codes")
    with RELATIONS_CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        relation_rows = list(csv.DictReader(f))
    with SYMBOLS_CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        symbol_rows = list(csv.DictReader(f))
    with CANDIDATES_CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        candidate_rows = list(csv.DictReader(f))
    with POSITIVE_RELATIONS_CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        positive_rows = list(csv.DictReader(f))
    with KLINE_CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        kline_rows = list(csv.DictReader(f))
    if len(relation_rows) != 1003 or len({row["relation_id"] for row in relation_rows}) != 1003:
        raise RuntimeError("relation coverage does not conserve 1,003 unique relation IDs")
    if len(symbol_rows) != 518:
        raise RuntimeError("symbol coverage does not conserve all 518 catalog symbols")
    counts = Counter(row["bucket"] for row in relation_rows)
    expected = results["relation_buckets"]
    if sum(counts.values()) != 1003 or any(counts.get(bucket, 0) != expected.get(bucket, 0) for bucket in ("positive", "flat-negative", "missing", "open", "excluded")):
        raise RuntimeError("relation bucket counts differ from results")
    if len(positive_rows) != expected.get("positive", 0) or len(candidate_rows) != results["candidate_rule"]["candidate_count"]:
        raise RuntimeError("candidate or positive relation count differs from results")
    if len(kline_rows) != 3 or {row["futu_code"] for row in kline_rows} != {"US.DASH", "US.NTES", "US.UBER"}:
        raise RuntimeError("the exact daily-K subset is not the isolated three-symbol canary")
    for row in relation_rows:
        if row["observation_status"] == "READY":
            last_price = float(row["last_price"])
            previous_close = float(row["prev_close_price"])
            actual = float(row["snapshot_change_pct_vs_prev_close"])
            expected_metric = (last_price / previous_close - 1.0) * 100.0
            if abs(actual - expected_metric) > 1e-10:
                raise RuntimeError("snapshot metric does not use last_price/prev_close_price")
    if results.get("snapshot_capture_file_sha256") != common.sha256_file(CAPTURE_PATH):
        raise RuntimeError("results do not bind raw snapshot capture SHA")
    if results.get("safety") != SAFETY:
        raise RuntimeError("research-only safety flags changed")
    receipt = common.read_json(RECEIPT_PATH)
    for relative, digest in receipt.get("artifact_sha256", {}).items():
        if common.sha256_file(HERE / relative) != digest:
            raise RuntimeError("writer receipt SHA mismatch: " + relative)
    top_level_report = HERE.parent / "REPORT.md"
    if receipt.get("top_level_report_sha256") and common.sha256_file(top_level_report) != receipt["top_level_report_sha256"]:
        raise RuntimeError("writer receipt top-level REPORT.md SHA mismatch")
    return {
        "status": "PASS",
        "requested_active_us_symbols": len(capture["requested_codes"]),
        "snapshot_rows_returned": len(capture.get("snapshot_rows_by_code", {})),
        "attempt_count": len(capture.get("attempts", [])),
        "relation_rows": len(relation_rows),
        "symbol_rows": len(symbol_rows),
        "candidate_rows": len(candidate_rows),
        "positive_relation_rows": len(positive_rows),
        "exact_daily_kline_rows": len(kline_rows),
        "bucket_counts": dict(sorted(counts.items())),
        "writer_receipt_status": receipt.get("status"),
        "independent_review": receipt.get("independent_review"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--capture", action="store_true", help="Query current Futu snapshots for eligible active US listings and rebuild outputs")
    group.add_argument("--rebuild", action="store_true", help="Rebuild outputs from the saved raw snapshot response")
    group.add_argument("--verify", action="store_true", help="Verify SHA, coverage conservation, metric, and safety contracts")
    args = parser.parse_args()
    try:
        if args.capture:
            projection = common.read_json(PROJECTION_PATH)
            if common.canonical_hash(projection, "projection_sha256") != projection.get("projection_sha256"):
                raise RuntimeError("catalog projection SHA mismatch")
            capture_snapshots(projection)
            results = build_outputs()
            print(json.dumps({
                "status": "CAPTURED",
                "capture_complete": results["capture_complete"],
                "requested_active_us_symbols": results["symbol_coverage"]["active_us_eligible_symbols"],
                "snapshot_rows_returned": results["symbol_coverage"]["snapshot_rows_returned"],
                "valid_current_observations": results["symbol_coverage"]["valid_current_observations"],
                "relation_buckets": results["relation_buckets"],
                "report": str(REPORT_PATH),
            }, ensure_ascii=False, sort_keys=True))
            return 0 if results["capture_complete"] else 2
        if args.rebuild:
            results = build_outputs()
            print(json.dumps({"status": "BUILT", "relation_buckets": results["relation_buckets"], "candidate_count": results["candidate_rule"]["candidate_count"]}, ensure_ascii=False, sort_keys=True))
            return 0
        print(json.dumps(verify_outputs(), ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print("ERROR: %s: %s" % (type(exc).__name__, str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
