#!/usr/bin/env python3
"""Rebuild a research-only Friday US snapshot observation from frozen local inputs."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
HANDOFF = HERE.parent
ROOT = Path(__file__).resolve().parents[4]
MAPPING_PATH = ROOT / "docs/handoffs/us_hk_mapping_today_20261016/mapping_input_snapshot.json"
CAPTURE_PATH = HANDOFF / "evidence/futu_snapshot_full_capture.json"
CANARY_PATH = HANDOFF / "evidence/futu_snapshot_canary.json"
REPORT_PATH = HANDOFF / "reports/REPORT.md"
RESULTS_PATH = HANDOFF / "reports/results.json"
SYMBOLS_PATH = HANDOFF / "reports/us_stock_coverage.csv"
TOP_US_PATH = HANDOFF / "reports/top20_us_observations.csv"
ALL_RELATIONS_PATH = HANDOFF / "reports/all_relation_coverage.csv"
POSITIVE_RELATIONS_PATH = HANDOFF / "reports/positive_relation_observations.csv"
CANDIDATES_PATH = HANDOFF / "reports/candidate_stocks.csv"
TARGET_SESSION = "2026-10-16"
TARGET_HK_DATE = "20261020"
EXPECTED = {
    "mapping_file_sha256": "f819ca2f036953d0989a2a28127072d41ac7e051f209087a38953299251a0df3",
    "mapping_snapshot_sha256": "3228f28fdc34cfe36202fa7e5bce1720fe34115a334b77bc6a4468a6013eb1cc",
    "overlay_sha256": "3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c",
    "capture_universe_count": 448,
}
SAFETY = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
BUCKETS = ("positive", "flat-negative", "missing", "open", "excluded")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def update_time_state(value: Any) -> str:
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return "CANNOT_CONFIRM_UPDATE_TIME"
    if timestamp.date().isoformat() != TARGET_SESSION:
        return "UPDATE_DATE_MISMATCH"
    if timestamp.time() < dt.time(16, 0):
        return "TARGET_SESSION_BEFORE_REGULAR_CLOSE"
    return "AFTER_CLOSE_TARGET_SESSION_TIMESTAMP"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def excerpt(values: Any, count: int = 1, limit: int = 72) -> str:
    if not isinstance(values, list) or not values:
        return "未列明"
    value = str(values[0])
    if len(value) > limit:
        value = value[: limit - 1] + "…"
    if len(values) > count:
        return value + f"（另有 {len(values) - count} 项）"
    return value


def load_mapping() -> tuple[dict[str, Any], str]:
    raw_bytes = MAPPING_PATH.read_bytes()
    actual_file_sha = hashlib.sha256(raw_bytes).hexdigest()
    if actual_file_sha != EXPECTED["mapping_file_sha256"]:
        raise SystemExit(f"FAIL: mapping source file SHA changed: {actual_file_sha}")
    mapping = json.loads(raw_bytes.decode("utf-8"))
    body = dict(mapping)
    recorded = body.pop("snapshot_sha256", None)
    if recorded != canonical_sha256(body) or recorded != EXPECTED["mapping_snapshot_sha256"]:
        raise SystemExit("FAIL: mapping input snapshot canonical SHA does not match")
    source = mapping.get("sources", {}).get("mapping", {})
    if source.get("recovery_overlay_sha256") != EXPECTED["overlay_sha256"]:
        raise SystemExit("FAIL: mapping recovery overlay SHA changed")
    if len(mapping.get("stocks", [])) != 667 or len(mapping.get("relations", [])) != 1003:
        raise SystemExit("FAIL: mapping snapshot is not 667 stocks / 1003 relations")
    if len({row.get("relation_id") for row in mapping["relations"]}) != 1003:
        raise SystemExit("FAIL: mapping relation IDs are missing or duplicated")
    closure_counts = Counter(row.get("closure_status") for row in mapping["relations"])
    if closure_counts != Counter({"CLOSED_RESEARCH_SCOPE": 757, "CLOSED_EXCLUDED_SCOPE": 25, "OPEN": 221}):
        raise SystemExit(f"FAIL: frozen mapping closure counts changed: {dict(closure_counts)}")
    for key, expected in SAFETY.items():
        if mapping.get("safety", {}).get(key) != expected:
            raise SystemExit(f"FAIL: frozen mapping safety flag changed: {key}")
    return mapping, actual_file_sha


def load_capture() -> tuple[dict[str, Any], dict[str, dict[str, Any]], str]:
    raw_bytes = CAPTURE_PATH.read_bytes()
    capture_sha = hashlib.sha256(raw_bytes).hexdigest()
    capture = json.loads(raw_bytes.decode("utf-8"))
    body = dict(capture)
    recorded = body.pop("payload_sha256", None)
    if recorded != canonical_sha256(body):
        raise SystemExit("FAIL: Futu snapshot capture payload SHA does not match")
    if capture.get("provider") != "Futu OpenAPI Python SDK via local OpenD" or capture.get("api") != "OpenQuoteContext.get_market_snapshot":
        raise SystemExit("FAIL: quote capture provider/API identity changed")
    if capture.get("target_us_session") != TARGET_SESSION:
        raise SystemExit("FAIL: quote capture target session differs from 2026-10-16")
    contract = capture.get("request_contract", {})
    if contract.get("historical_kline_requested") is not False or contract.get("subscription_requested") is not False or contract.get("refresh_requested") is not False:
        raise SystemExit("FAIL: capture contract includes a disallowed API action")
    codes = capture.get("requested_codes")
    raw_by_code = capture.get("snapshot_rows_by_code")
    if not isinstance(codes, list) or len(codes) != EXPECTED["capture_universe_count"] or len(set(codes)) != len(codes):
        raise SystemExit("FAIL: capture universe is not the frozen set of 448 unique symbols")
    if capture.get("universe_count") != len(codes) or capture.get("returned_code_count") != len(raw_by_code):
        raise SystemExit("FAIL: capture coverage counters do not reconcile")
    if not isinstance(raw_by_code, dict) or any(code not in codes for code in raw_by_code):
        raise SystemExit("FAIL: returned quote rows do not bind to requested codes")
    return capture, raw_by_code, capture_sha


def quote_projection(capture: dict[str, Any], raw_by_code: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, int]]:
    terminal = capture.get("terminal_status_by_code") or {}
    symbol_rows: list[dict[str, Any]] = []
    by_symbol: dict[str, dict[str, Any]] = {}
    counts = Counter()
    for code in capture["requested_codes"]:
        symbol = code.removeprefix("US.")
        raw = raw_by_code.get(code) or {}
        query_status = (terminal.get(code) or {}).get("status", "NOT_RETURNED")
        timestamp_state = update_time_state(raw.get("update_time"))
        last_price = finite_positive(raw.get("last_price"))
        previous_close = finite_positive(raw.get("prev_close_price"))
        valid = query_status == "SNAPSHOT_ROW_RETURNED" and timestamp_state == "AFTER_CLOSE_TARGET_SESSION_TIMESTAMP" and last_price is not None and previous_close is not None
        change_pct = (last_price / previous_close - 1.0) * 100.0 if valid else None
        status = "READY_AFTER_CLOSE_SNAPSHOT" if valid else timestamp_state if raw else query_status
        if raw and timestamp_state == "AFTER_CLOSE_TARGET_SESSION_TIMESTAMP" and (last_price is None or previous_close is None):
            status = "MISSING_OR_INVALID_LAST_OR_PREV_CLOSE"
        counts["requested"] += 1
        if raw:
            counts["returned"] += 1
        if valid:
            counts["valid_after_close"] += 1
        else:
            counts["cannot_confirm"] += 1
        row = {
            "futu_code": code,
            "us_symbol": symbol,
            "us_name": raw.get("name") or "",
            "query_status": query_status,
            "observation_status": status,
            "update_time_et": raw.get("update_time"),
            "last_price": last_price,
            "prev_close_price": previous_close,
            "snapshot_change_pct": change_pct,
            "pre_price": finite_positive(raw.get("pre_price")),
            "pre_change_rate": raw.get("pre_change_rate"),
            "after_price": finite_positive(raw.get("after_price")),
            "after_change_rate": raw.get("after_change_rate"),
            "overnight_price": finite_positive(raw.get("overnight_price")),
            "overnight_change_rate": raw.get("overnight_change_rate"),
            "volume": raw.get("volume"),
            "turnover": raw.get("turnover"),
            "sec_status": raw.get("sec_status"),
            "metric_definition": "(last_price / prev_close_price - 1) * 100" if valid else "",
        }
        symbol_rows.append(row)
        if valid:
            by_symbol[symbol] = row
    return symbol_rows, by_symbol, dict(counts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="rebuild outputs from the frozen local inputs")
    parser.parse_args()

    mapping, mapping_file_sha = load_mapping()
    capture, raw_by_code, capture_sha = load_capture()
    canary_sha = sha256_file(CANARY_PATH)
    canary = json.loads(CANARY_PATH.read_text(encoding="utf-8"))
    if canary.get("target_us_session") != TARGET_SESSION or canary.get("ret_ok") is not True or canary.get("response_row_count") != 3:
        raise SystemExit("FAIL: the three-symbol Futu canary is not valid for the target session")
    canary_codes = {row.get("code") for row in canary.get("response_rows", [])}
    if canary_codes != {"US.DASH", "US.NTES", "US.UBER"}:
        raise SystemExit("FAIL: canary code coverage changed")

    symbols, quotes_by_symbol, quote_counts = quote_projection(capture, raw_by_code)
    relations = mapping["relations"]
    stocks_by_code = {str(row["hk_code"]).zfill(5): row for row in mapping["stocks"]}
    if len(stocks_by_code) != 667:
        raise SystemExit("FAIL: mapped stock codes are missing or duplicated")

    relation_rows: list[dict[str, Any]] = []
    buckets = Counter({key: 0 for key in BUCKETS})
    mapped_quotes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    positive_rows: list[dict[str, Any]] = []
    for relation in relations:
        symbol = str(relation.get("us_symbol") or "").strip()
        quote = quotes_by_symbol.get(symbol)
        closure = relation.get("closure_status")
        if closure == "CLOSED_EXCLUDED_SCOPE":
            bucket = "excluded"
        elif closure == "OPEN":
            bucket = "open"
        elif closure == "CLOSED_RESEARCH_SCOPE":
            if quote is None:
                bucket = "missing"
            elif float(quote["snapshot_change_pct"]) > 0:
                bucket = "positive"
            else:
                bucket = "flat-negative"
        else:
            raise SystemExit(f"FAIL: unknown closure state for {relation.get('relation_id')}")
        buckets[bucket] += 1
        row = {
            "source_row": relation.get("source_row"),
            "relation_id": relation.get("relation_id"),
            "hk_code": str(relation.get("hk_code") or "").zfill(5),
            "hk_name": relation.get("hk_name") or stocks_by_code.get(str(relation.get("hk_code") or "").zfill(5), {}).get("name", ""),
            "us_symbol": symbol,
            "us_name": relation.get("us_name") or (quote or {}).get("us_name", ""),
            "relation_type": relation.get("relation_type") or "",
            "snapshot_change_pct": quote.get("snapshot_change_pct") if quote else None,
            "quote_update_time_et": quote.get("update_time_et") if quote else None,
            "last_price": quote.get("last_price") if quote else None,
            "prev_close_price": quote.get("prev_close_price") if quote else None,
            "pre_price": quote.get("pre_price") if quote else None,
            "after_price": quote.get("after_price") if quote else None,
            "quote_observation_status": quote.get("observation_status") if quote else "NO_VALID_TARGET_SESSION_SNAPSHOT",
            "bucket": bucket,
            "current_use_scope": relation.get("current_use_scope") or "CANNOT_CONFIRM_CURRENT_USE_SCOPE_ABSENT",
            "closure_status": closure,
            "research_status": relation.get("research_status") or "CANNOT_CONFIRM_CURRENT_APPLICABILITY_STATE_ABSENT",
            "evidence_ids_json": compact_json(relation.get("evidence_ids") or []),
            "remaining_gaps_json": compact_json(relation.get("remaining_gaps") or []),
            "next_key_evidence_json": compact_json(relation.get("next_key_evidence") or []),
            "delivery_acceptance": relation.get("delivery_acceptance") or "",
            "company_independent_acceptance": relation.get("company_independent_acceptance"),
            "prediction": relation.get("prediction") or "UNTESTED",
            "historical_PIT": relation.get("historical_PIT") or "NOT_VALIDATED",
            "event_and_data_tests": relation.get("event_and_data_tests") or "NOT_RUN",
            "effective_research_file": relation.get("effective_research_file") or "",
            "effective_research_sha256": relation.get("effective_research_sha256") or "",
        }
        relation_rows.append(row)
        if bucket == "positive":
            positive_rows.append(row)
        if quote is not None:
            mapped_quotes[symbol].append(row)

    if len(relation_rows) != 1003 or len({row["relation_id"] for row in relation_rows}) != 1003 or sum(buckets.values()) != 1003:
        raise SystemExit("FAIL: relation identity or bucket conservation failed")
    if buckets["open"] != 221 or buckets["excluded"] != 25:
        raise SystemExit(f"FAIL: open/excluded boundary changed: {dict(buckets)}")

    positive_relations_by_hk: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in positive_rows:
        positive_relations_by_hk[row["hk_code"]].append(row)
    candidates: list[dict[str, Any]] = []
    for code, rows in positive_relations_by_hk.items():
        ordered = sorted(rows, key=lambda row: (-float(row["snapshot_change_pct"]), row["us_symbol"], row["relation_id"]))
        stock = stocks_by_code.get(code, {})
        candidates.append({
            "hk_code": code,
            "hk_name": stock.get("name") or ordered[0]["hk_name"],
            "best_change_pct": float(ordered[0]["snapshot_change_pct"]),
            "best_us_symbol": ordered[0]["us_symbol"],
            "best_us_name": ordered[0]["us_name"],
            "positive_relation_count": len(ordered),
            "positive_relations": ordered,
        })
    candidates.sort(key=lambda item: (-item["best_change_pct"], item["hk_code"]))
    for rank, candidate in enumerate(candidates, 1):
        candidate["rank"] = rank

    us_observations: list[dict[str, Any]] = []
    all_symbols = sorted(set(row["us_symbol"] for row in relations))
    for symbol in all_symbols:
        relation_set = [row for row in relations if row.get("us_symbol") == symbol]
        quote = quotes_by_symbol.get(symbol)
        positive_relations = [row for row in relation_rows if row["us_symbol"] == symbol and row["bucket"] == "positive"]
        closed_count = sum(row.get("closure_status") == "CLOSED_RESEARCH_SCOPE" for row in relation_set)
        all_count = len(relation_set)
        status = quote.get("observation_status") if quote else "CANNOT_CONFIRM_NO_VALID_TARGET_SESSION_SNAPSHOT"
        us_observations.append({
            "us_symbol": symbol,
            "us_name": (quote or {}).get("us_name") or next((row.get("us_name") or "" for row in relation_set), ""),
            "observation_status": status,
            "snapshot_change_pct": quote.get("snapshot_change_pct") if quote else None,
            "update_time_et": quote.get("update_time_et") if quote else None,
            "last_price": quote.get("last_price") if quote else None,
            "prev_close_price": quote.get("prev_close_price") if quote else None,
            "pre_price": quote.get("pre_price") if quote else None,
            "after_price": quote.get("after_price") if quote else None,
            "mapping_relation_count": all_count,
            "closed_research_relation_count": closed_count,
            "positive_relation_count": len(positive_relations),
            "linked_hk_codes_json": compact_json(sorted({row.get("hk_code") for row in relation_set})),
            "positive_relation_ids_json": compact_json(sorted(row["relation_id"] for row in positive_relations)),
            "research_eligible_positive_observation": bool(quote and closed_count > 0 and float(quote["snapshot_change_pct"]) > 0),
        })
    us_observations.sort(key=lambda row: (row["snapshot_change_pct"] is None, -(row["snapshot_change_pct"] or 0.0), row["us_symbol"]))
    top_us = [row for row in us_observations if row["research_eligible_positive_observation"]]
    for rank, row in enumerate(top_us, 1):
        row["rank"] = rank

    quote_symbols = set(capture["requested_codes"])
    mapping_symbols = set(all_symbols)
    valid_quote_symbols = set(quotes_by_symbol)
    closure_count = Counter(row.get("closure_status") for row in relations)
    summary = {
        "schema_version": "v4.us_hk_friday_snapshot_observation.v1",
        "target_us_session": TARGET_SESSION,
        "target_hk_trade_date": TARGET_HK_DATE,
        "observation_semantics": "Futu after-close snapshot; metric uses last_price versus prev_close_price; pre_price and after_price are preserved separately",
        "exact_official_daily_close_confirmed": False,
        "exact_daily_bar_requested": False,
        "source": {
            "provider": capture["provider"],
            "api": capture["api"],
            "capture_started_at_local": capture.get("started_at_local"),
            "capture_completed_at_local": capture.get("completed_at_local"),
            "sdk_version": capture.get("sdk_version"),
            "capture_path": str(CAPTURE_PATH),
            "capture_file_sha256": capture_sha,
            "capture_payload_sha256": capture.get("payload_sha256"),
            "canary_path": str(CANARY_PATH),
            "canary_file_sha256": canary_sha,
            "requested_symbols": len(quote_symbols),
            "returned_symbols": len(raw_by_code),
            "valid_after_close_symbols": quote_counts.get("valid_after_close", 0),
            "cannot_confirm_symbols": quote_counts.get("cannot_confirm", 0),
            "requested_codes_sha256": capture.get("universe_codes_sha256"),
        },
        "mapping": {
            "snapshot_path": str(MAPPING_PATH),
            "snapshot_file_sha256": mapping_file_sha,
            "snapshot_sha256": mapping.get("snapshot_sha256"),
            "catalog_id": mapping.get("sources", {}).get("mapping", {}).get("catalog_id"),
            "catalog_integrity_sha256": mapping.get("sources", {}).get("mapping", {}).get("catalog_integrity_sha256"),
            "recovery_overlay_path": mapping.get("sources", {}).get("mapping", {}).get("recovery_overlay_file"),
            "recovery_overlay_sha256": mapping.get("sources", {}).get("mapping", {}).get("recovery_overlay_sha256"),
            "recovery_overlay_integrity_sha256": mapping.get("sources", {}).get("mapping", {}).get("recovery_overlay_integrity_sha256"),
            "stock_count": len(mapping["stocks"]),
            "relation_count": len(relations),
            "closure_counts": dict(closure_count),
        },
        "counts": {
            "relation_buckets": dict(buckets),
            "bucket_total": sum(buckets.values()),
            "valid_quote_symbols": len(valid_quote_symbols),
            "requested_quote_symbols": len(quote_symbols),
            "valid_mapping_quote_symbols": len(valid_quote_symbols & mapping_symbols),
            "mapping_quote_relation_rows": sum(1 for row in relation_rows if row["us_symbol"] in valid_quote_symbols),
            "positive_us_symbols_with_closed_relations": len(top_us),
            "positive_relation_count": len(positive_rows),
            "positive_hk_code_count": len(candidates),
            "mapped_symbols_absent_from_futu_universe": len(mapping_symbols - {code.removeprefix("US.") for code in quote_symbols}),
            "futu_symbols_absent_from_mapping": len({code.removeprefix("US.") for code in quote_symbols} - mapping_symbols),
        },
        "safety": {
            **SAFETY,
            "prediction_validation": "UNTESTED",
            "historical_PIT": "NOT_VALIDATED",
            "event_and_data_tests": "NOT_RUN",
            "company_independent_acceptance": 0,
        },
    }

    symbol_fields = ["us_symbol", "us_name", "observation_status", "snapshot_change_pct", "update_time_et", "last_price", "prev_close_price", "pre_price", "pre_change_rate", "after_price", "after_change_rate", "overnight_price", "overnight_change_rate", "volume", "turnover", "sec_status", "query_status", "metric_definition"]
    write_csv(SYMBOLS_PATH, symbol_fields, symbols)
    top_us_fields = ["rank", "us_symbol", "us_name", "snapshot_change_pct", "update_time_et", "last_price", "prev_close_price", "positive_relation_count", "closed_research_relation_count", "mapping_relation_count", "linked_hk_codes_json", "positive_relation_ids_json"]
    write_csv(TOP_US_PATH, top_us_fields, top_us[:20])
    relation_fields = list(relation_rows[0].keys())
    write_csv(ALL_RELATIONS_PATH, relation_fields, relation_rows)
    ordered_positive = sorted(positive_rows, key=lambda row: (-float(row["snapshot_change_pct"]), row["hk_code"], row["relation_id"]))
    write_csv(POSITIVE_RELATIONS_PATH, ["rank_by_relation_change"] + relation_fields, [dict(rank_by_relation_change=rank, **row) for rank, row in enumerate(ordered_positive, 1)])
    candidate_rows = []
    for candidate in candidates:
        links = candidate["positive_relations"]
        candidate_rows.append({
            "rank": candidate["rank"],
            "hk_code": candidate["hk_code"],
            "hk_name": candidate["hk_name"],
            "best_us_symbol": candidate["best_us_symbol"],
            "best_us_name": candidate["best_us_name"],
            "best_change_pct": candidate["best_change_pct"],
            "positive_relation_count": candidate["positive_relation_count"],
            "positive_relation_ids": ";".join(row["relation_id"] for row in links),
            "positive_relation_sources_json": compact_json([{
                "relation_id": row["relation_id"],
                "us_symbol": row["us_symbol"],
                "change_pct": row["snapshot_change_pct"],
                "current_use_scope": row["current_use_scope"],
                "research_status": row["research_status"],
                "evidence_ids_json": row["evidence_ids_json"],
                "remaining_gaps_json": row["remaining_gaps_json"],
            } for row in links]),
        })
    write_csv(CANDIDATES_PATH, ["rank", "hk_code", "hk_name", "best_us_symbol", "best_us_name", "best_change_pct", "positive_relation_count", "positive_relation_ids", "positive_relation_sources_json"], candidate_rows)
    write_json(RESULTS_PATH, summary)
    write_report(summary, buckets, quote_counts, top_us, candidates)
    print(json.dumps({"relation_buckets": dict(buckets), "source_quote_counts": quote_counts, "top20_us": top_us[:20], "top20_hk": candidates[:20], "results": str(RESULTS_PATH), "report": str(REPORT_PATH)}, ensure_ascii=False, default=str, sort_keys=True))
    return 0


def write_report(summary: dict[str, Any], buckets: Counter[str], quote_counts: dict[str, int], top_us: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> None:
    source = summary["source"]
    mapping = summary["mapping"]
    bucket_counts = summary["counts"]["relation_buckets"]
    us_lines = [
        "|序|美股代码|名称|Futu快照涨幅|更新时间（美东）|正涨映射关系数|关联港股代码|",
        "|---:|---|---|---:|---|---:|---|",
    ]
    for rank, row in enumerate(top_us[:20], 1):
        linked = ", ".join(json.loads(row["linked_hk_codes_json"]))
        us_lines.append("|{}|{}|{}|{:+.3f}%|{}|{}|{}|".format(
            rank, md_cell(row["us_symbol"]), md_cell(row["us_name"]), float(row["snapshot_change_pct"]),
            md_cell(row["update_time_et"]), row["positive_relation_count"], md_cell(linked),
        ))
    hk_lines = [
        "|序|港股代码 / 名称|涨幅最高的关联美股（快照涨幅，关系）|正涨闭环关系数|用途范围|研究状态|待补要点|",
        "|---:|---|---|---:|---|---|---|",
    ]
    for candidate in candidates[:20]:
        links = candidate["positive_relations"]
        linked = "；".join(f"{row['us_symbol']} ({float(row['snapshot_change_pct']):+.3f}%, {row['relation_id']})" for row in links)
        scopes = "；".join(sorted({row["current_use_scope"] for row in links}))
        statuses = "；".join(sorted({row["research_status"] for row in links}))
        gaps = "；".join(excerpt(json.loads(row["remaining_gaps_json"])) for row in links[:2])
        hk_lines.append("|{}|{} {}|{}|{}|{}|{}|{}|".format(
            candidate["rank"], candidate["hk_code"], md_cell(candidate["hk_name"]), md_cell(linked),
            candidate["positive_relation_count"], md_cell(scopes), md_cell(statuses), md_cell(gaps),
        ))
    lines = [
        "# 2026-10-16 美股收盘后观察名单",
        "",
        "本结果是 2026-10-17 23:10 HKT 通过 Futu OpenAPI `get_market_snapshot` 取得的收盘后快照观察。Futu 文档说明美股 `update_time` 使用美东时间；`last_price`、`prev_close_price`、`pre_price` 和 `after_price` 分别保留。涨幅按 `(last_price / prev_close_price - 1) × 100` 计算，盘前和盘后价格不进入公式。该数据不是独立核验的官方日 K 收盘 bar，不代表预测、因果影响、买入建议或交易授权。参考：[Futu 官方快照字段说明](https://openapi.futunn.com/futu-api-doc/quote/get-market-snapshot.html)。",
        "",
        f"- 目标美股交易日：`{TARGET_SESSION}`；对应下一港股交易日：`{TARGET_HK_DATE}`。HKEX 2026 日历列明 2026-10-19 休市，故目标不是周一；[HKEX 2026 日历](https://www.hkex.com.hk/-/media/HKEX-Market/Mutual-Market/Stock-Connect/Reference-Materials/Trading-Hour%2C-Trading-and-Settlement-Calendar/2026-Calendar_pdf_e.pdf)。",
        f"- Futu 对既有 448 个非 OTC 美股代码请求并返回 {source['returned_symbols']} 行；{source['valid_after_close_symbols']} 行的更新时间为 10/16 美东 16:00 或以后且价格字段有效，{source['cannot_confirm_symbols']} 行缺少有效日期时间或价格，保留为 `CANNOT_CONFIRM`，不补值。采集时间 `{source['capture_started_at_local']}` 至 `{source['capture_completed_at_local']}`。映射库证券范围包含基金等非普通股标的；关联用途和证券类别按现有关系保留。",
        f"- 映射：667 只港股、1,003 条关系；overlay SHA-256 `{mapping['recovery_overlay_sha256']}`。闭环研究范围 757 条、OPEN 221 条、排除 25 条。",
        f"- 关系分桶守恒：positive {bucket_counts['positive']}、flat-negative {bucket_counts['flat-negative']}、missing {bucket_counts['missing']}、open {bucket_counts['open']}、excluded {bucket_counts['excluded']}，合计 {summary['counts']['bucket_total']}。OPEN/排除优先于行情方向并且不入观察候选。",
        f"- 正涨且至少有一条闭环研究关系的美股共 {summary['counts']['positive_us_symbols_with_closed_relations']} 个；这些代码按快照涨幅排序，映射关系仅表示已有研究用途，不能解释为全部直接业务或股票联动。",
        "",
        "## 美股正涨观察前 20",
        "",
        "排序只反映 Futu 快照 `last_price` 相对 `prev_close_price` 的变化；完整 448 代码覆盖见 `us_stock_coverage.csv`。",
        "",
        *us_lines,
        "",
        "## 映射港股观察前 20",
        "",
        "按每只港股最高一条正涨闭环关系的快照涨幅降序展示；所有正涨关系、用途、状态、证据 ID 和待补要点见完整 CSV。研究状态不因本次价格变化升级。",
        "",
        *hk_lines,
        "",
        "## 来源与可复现性",
        "",
        f"- 快照 capture SHA-256：`{source['capture_file_sha256']}`；capture payload SHA-256：`{source['capture_payload_sha256']}`；canary 文件 SHA-256：`{source['canary_file_sha256']}`。",
        f"- 映射快照文件 SHA-256：`{mapping['snapshot_file_sha256']}`；canonical snapshot SHA-256：`{mapping['snapshot_sha256']}`；目录完整性 SHA-256：`{mapping['catalog_integrity_sha256']}`。",
        f"- 精确日 K close：`CANNOT_CONFIRM`（本次只请求快照接口，未请求历史 K 线）。历史 PIT：`NOT_VALIDATED`；预测：`UNTESTED`；事件/数据检验：`NOT_RUN`。",
        "- 闭环范围、可证关系用途和当前状态沿用映射文件；positive 表示观察筛选结果，非证据独立验收、预测或交易信号。",
        "- 金融安全：`RESEARCH_ONLY=true`; `production_allowed=false`; `buy_gate_updated=false`; `orders_sent=false`。",
        "",
        "复算：`'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_hk_friday_close_20261017/scripts/build_friday_us_observations.py --verify`",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
