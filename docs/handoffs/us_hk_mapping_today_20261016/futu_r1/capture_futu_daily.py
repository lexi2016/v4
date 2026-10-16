#!/usr/bin/env python3
"""Three-symbol, exact-date Futu daily-K canary for Futu R1."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
HANDOFF = HERE.parent
BASELINE_PATH = HANDOFF / "mapping_input_snapshot.json"
PROJECTION_PATH = HERE / "catalog_projection.json"
CANARY_PATH = HERE / "canary.json"

TARGET_DATE = "2026-10-15"
TARGET_SESSION = "20261015"
EXPECTED_BASELINE_SHA = "3228f28fdc34cfe36202fa7e5bce1720fe34115a334b77bc6a4468a6013eb1cc"
PAGE_LIMIT = 200
FUTU_HOST = "127.0.0.1"
FUTU_PORT = 11111
CANARY_SYMBOLS = ("DASH", "NTES", "UBER")

STALE_MARKERS = (
    "历史", "原NYSE", "原Nasdaq", "原OTC", "已退市", "暂停交易", "已停止交易",
    "当前不可沿用", "计划已终止", "已终止", "非当前独立交易资产", "停止交易",
)
NON_SECURITY_MARKERS = (
    "COMEX", "NYMEX", "CBOT", "CME", "FRED", "Federal Reserve", "不适用",
)
US_SECURITY_MARKERS = ("NYSE", "NASDAQ", "Nasdaq", "OTC", "OTCQX", "OTCID")
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,19}$")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_hash(value: dict[str, Any], hash_key: str) -> str:
    body = dict(value)
    body.pop(hash_key, None)
    return sha256_bytes(canonical_bytes(body))


def write_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def clean(value: Any) -> Any:
    if hasattr(value, "to_dict") and not isinstance(value, dict):
        try:
            return clean(value.to_dict(orient="records"))
        except TypeError:
            try:
                return clean(value.to_dict())
            except Exception:
                pass
    if hasattr(value, "item") and not isinstance(value, (str, bytes, dict, list, tuple)):
        try:
            return clean(value.item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def verify_baseline() -> dict[str, Any]:
    baseline = read_json(BASELINE_PATH)
    recorded = baseline.get("snapshot_sha256")
    computed = canonical_hash(baseline, "snapshot_sha256")
    if recorded != EXPECTED_BASELINE_SHA or computed != recorded:
        raise RuntimeError("frozen R0 mapping_input_snapshot SHA mismatch")
    if len(baseline.get("relations", [])) != 1003 or len({r.get("relation_id") for r in baseline["relations"]}) != 1003:
        raise RuntimeError("frozen R0 snapshot relation count or identity is invalid")
    if baseline.get("safety", {}).get("RESEARCH_ONLY") is not True:
        raise RuntimeError("frozen R0 snapshot is not marked research-only")
    return baseline


def fetch_catalog_pages(endpoint: str, baseline: dict[str, Any]) -> dict[str, Any]:
    relations_by_id = {row["relation_id"]: row for row in baseline["relations"]}
    expected_catalog_sha = baseline["sources"]["mapping"]["catalog_integrity_sha256"]
    expected_catalog_id = baseline["sources"]["mapping"]["catalog_id"]
    expected_member_codes = set(baseline.get("hk_connect_member_codes", []))
    all_stocks: list[dict[str, Any]] = []
    identity = None
    total = None
    for offset in range(0, 667, PAGE_LIMIT):
        query = urllib.parse.urlencode({"limit": PAGE_LIMIT, "offset": offset})
        url = endpoint + "?" + query
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            envelope = json.loads(response.read().decode("utf-8"))
        if envelope.get("state") != "STRUCTURE_VALID" or envelope.get("RESEARCH_ONLY") is not True:
            raise RuntimeError("live catalog page is not STRUCTURE_VALID/RESEARCH_ONLY at offset %s" % offset)
        if envelope.get("production_allowed") is not False or envelope.get("buy_gate_updated") is not False or envelope.get("orders_sent") is not False:
            raise RuntimeError("live catalog safety flags changed at offset %s" % offset)
        data = envelope.get("data") or {}
        page_identity = {
            "catalog_id": data.get("catalog_id"),
            "catalog_integrity_sha256": data.get("catalog_integrity_sha256"),
            "total": data.get("total"),
            "limit": data.get("limit"),
        }
        if identity is None:
            identity = page_identity
            total = data.get("total")
        elif identity != page_identity:
            raise RuntimeError("live catalog identity changed across pages")
        if data.get("offset") != offset or data.get("limit") != PAGE_LIMIT or data.get("total") != 667:
            raise RuntimeError("live catalog pagination metadata mismatch at offset %s" % offset)
        all_stocks.extend(data.get("items") or [])
    if identity is None or len(all_stocks) != 667 or total != 667:
        raise RuntimeError("live catalog stock count is not 667")
    if identity.get("catalog_id") != expected_catalog_id or identity.get("catalog_integrity_sha256") != expected_catalog_sha:
        raise RuntimeError("live catalog identity differs from frozen R0 source identity")

    api_relations: dict[str, dict[str, Any]] = {}
    stocks_projection: list[dict[str, Any]] = []
    for stock in all_stocks:
        hk_code = str(stock.get("hk_code") or "").zfill(5)
        if expected_member_codes and hk_code not in expected_member_codes:
            raise RuntimeError("catalog HK code is outside frozen HK Connect membership: " + hk_code)
        stocks_projection.append({"hk_code": hk_code, "name": stock.get("name") or ""})
        for relation in stock.get("relations") or []:
            rid = relation.get("relation_id")
            if not rid or rid not in relations_by_id or rid in api_relations:
                raise RuntimeError("live catalog has missing, unexpected, or duplicate relation ID: %r" % rid)
            prior = relations_by_id[rid]
            recovery = relation.get("recovery_v2r1") or {}
            source_record = relation.get("source_record") or {}
            comparisons = (
                ("hk_code", hk_code, prior.get("hk_code")),
                ("us_symbol", relation.get("us_symbol"), prior.get("us_symbol")),
                ("relation_type", source_record.get("type") or source_record.get("type_detail") or "", prior.get("relation_type") or ""),
                ("closure_status", recovery.get("closure_status"), prior.get("closure_status")),
                ("current_use_scope", recovery.get("primary_research_use"), prior.get("current_use_scope")),
                ("evidence_ids", recovery.get("evidence_ids") or [], prior.get("evidence_ids") or []),
            )
            for field, current, frozen in comparisons:
                if current != frozen:
                    raise RuntimeError("live catalog differs from frozen relation %s field %s" % (rid, field))
            if hk_code != prior.get("hk_code"):
                raise RuntimeError("live catalog HK code differs for relation %s" % rid)
            api_relations[rid] = {
                **prior,
                "hk_code": hk_code,
                "hk_name": stock.get("name") or prior.get("hk_name") or "",
                "us_symbol": relation.get("us_symbol") or "",
                "exchange": str(source_record.get("exchange") or "").strip(),
                "asset_class": str(source_record.get("asset_class") or "").strip(),
                "asset_name": str(source_record.get("asset_name") or prior.get("us_name") or "").strip(),
                "source_relation_type": str(source_record.get("type") or source_record.get("type_detail") or "").strip(),
            }
    if len(api_relations) != 1003 or set(api_relations) != set(relations_by_id):
        raise RuntimeError("live catalog relation set differs from frozen R0 relation set")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in api_relations.values():
        grouped[row["us_symbol"]].append(row)
    symbols = []
    for symbol, rows in sorted(grouped.items()):
        row_classes = {classify_exchange(row.get("exchange", "")) for row in rows}
        if len(row_classes) == 1:
            market_class = next(iter(row_classes))
        elif row_classes == {"US_LISTED_ACTIVE"}:
            market_class = "US_LISTED_ACTIVE"
        else:
            market_class = "CANNOT_CONFIRM_MARKET_CLASSIFICATION_CONFLICT"
        parseable = bool(TICKER_RE.fullmatch(symbol or ""))
        if not parseable and market_class == "US_LISTED_ACTIVE":
            market_class = "CANNOT_CONFIRM_SYMBOL_FORMAT"
        symbols.append({
            "us_symbol": symbol,
            "asset_name": sorted({row.get("asset_name", "") for row in rows if row.get("asset_name")})[0] if any(row.get("asset_name") for row in rows) else "",
            "market_class": market_class,
            "futu_code": "US." + symbol if market_class == "US_LISTED_ACTIVE" and parseable else "",
            "parseable_ticker": parseable,
            "relations": sorted(row["relation_id"] for row in rows),
            "exchange_evidence": sorted({row.get("exchange", "") for row in rows}),
            "asset_class_evidence": sorted({row.get("asset_class", "") for row in rows}),
            "relation_count": len(rows),
        })

    projection = {
        "schema_version": "futu-r1-catalog-projection-v1",
        "captured_at_utc": utc_now(),
        "source": {
            "endpoint": endpoint,
            "catalog_id": identity["catalog_id"],
            "catalog_integrity_sha256": identity["catalog_integrity_sha256"],
            "catalog_stock_count": len(stocks_projection),
            "catalog_relation_count": len(api_relations),
            "baseline_snapshot_sha256": baseline["snapshot_sha256"],
            "baseline_snapshot_file_sha256": sha256_file(BASELINE_PATH),
            "recovery_overlay_sha256": baseline["sources"]["mapping"]["recovery_overlay_sha256"],
            "recovery_overlay_integrity_sha256": baseline["sources"]["mapping"]["recovery_overlay_integrity_sha256"],
            "hk_connect_membership_sha256": baseline["sources"]["hk_membership"]["source_sha256"],
            "hk_connect_membership_date": baseline["sources"]["hk_membership"]["effective_date"],
        },
        "safety": {
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "stocks": sorted(stocks_projection, key=lambda row: row["hk_code"]),
        "relations": sorted(api_relations.values(), key=lambda row: row["relation_id"]),
        "symbols": symbols,
    }
    projection["projection_sha256"] = canonical_hash(projection, "projection_sha256")
    write_json(PROJECTION_PATH, projection)
    return projection


def classify_exchange(exchange: str) -> str:
    value = (exchange or "").strip()
    if not value:
        return "CANNOT_CONFIRM_EXCHANGE_ABSENT"
    if any(marker.casefold() in value.casefold() for marker in STALE_MARKERS):
        return "STALE_OR_FORMER_US_LISTING"
    if any(marker.casefold() in value.casefold() for marker in NON_SECURITY_MARKERS):
        return "NON_US_EQUITY_SECURITY_OR_MACRO_SERIES"
    if any(marker.casefold() in value.casefold() for marker in US_SECURITY_MARKERS):
        return "US_LISTED_ACTIVE"
    return "CANNOT_CONFIRM_EXCHANGE_CLASS"


def quota_result(ctx: Any) -> dict[str, Any]:
    started = utc_now()
    result = ctx.get_history_kl_quota(get_detail=True)
    if not isinstance(result, tuple) or len(result) != 2:
        return {"queried_at_utc": started, "ret": None, "error": "unexpected_quota_return_shape", "raw": clean(result)}
    ret, data = result
    out = {"queried_at_utc": started, "ret": int(ret), "raw": clean(data)}
    if int(ret) == 0 and isinstance(data, (tuple, list)) and len(data) == 3:
        out["used_quota"] = clean(data[0])
        out["remain_quota"] = clean(data[1])
        out["detail_list"] = clean(data[2])
    elif int(ret) != 0:
        out["error"] = str(data)
    return out


def kline_request(ctx: Any, code: str) -> dict[str, Any]:
    from futu import AuType, KLType, RET_OK

    queried_at = utc_now()
    try:
        ret, data, page_key = ctx.request_history_kline(
            code,
            start=TARGET_DATE,
            end=TARGET_DATE,
            ktype=KLType.K_DAY,
            autype=AuType.NONE,
            extended_time=False,
        )
        record = {
            "requested_at_utc": queried_at,
            "request": {
                "code": code,
                "start": TARGET_DATE,
                "end": TARGET_DATE,
                "ktype": "K_DAY",
                "autype": "None",
                "extended_time": False,
                "session": "SDK default (N/A)",
            },
            "ret": int(ret),
            "page_req_key": clean(page_key),
        }
        if int(ret) == RET_OK:
            try:
                rows = data.to_dict(orient="records")
            except Exception:
                rows = clean(data)
            record["response_rows"] = clean(rows)
        else:
            record["error"] = str(data)
        return record
    except Exception as exc:
        return {
            "requested_at_utc": queried_at,
            "request": {
                "code": code,
                "start": TARGET_DATE,
                "end": TARGET_DATE,
                "ktype": "K_DAY",
                "autype": "None",
                "extended_time": False,
                "session": "SDK default (N/A)",
            },
            "ret": None,
            "error": "%s: %s" % (type(exc).__name__, str(exc)),
        }


def run_canary() -> dict[str, Any]:
    if CANARY_PATH.exists():
        prior_canary = read_json(CANARY_PATH)
        if prior_canary.get("schema_version") == "futu-r1-canary-v1":
            # The daily-K quota is deliberately limited to the original three
            # requests. Re-running this command must replay the saved canary.
            return prior_canary
    baseline = verify_baseline()
    endpoint = baseline["sources"]["mapping"]["endpoint"]
    projection = fetch_catalog_pages(endpoint, baseline)
    symbol_lookup = {row["us_symbol"]: row for row in projection["symbols"]}
    canary_codes = []
    for symbol in CANARY_SYMBOLS:
        entry = symbol_lookup.get(symbol)
        if not entry or entry.get("market_class") != "US_LISTED_ACTIVE" or not entry.get("futu_code"):
            raise RuntimeError("canary symbol lacks active US exchange evidence: " + symbol)
        canary_codes.append(entry["futu_code"])

    from futu import OpenQuoteContext, RET_OK

    ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
    try:
        before = quota_result(ctx)
        records = [kline_request(ctx, code) for code in canary_codes]
        after = quota_result(ctx)
    finally:
        ctx.close()
    canary = {
        "schema_version": "futu-r1-canary-v1",
        "started_at_utc": records[0]["requested_at_utc"] if records else utc_now(),
        "completed_at_utc": utc_now(),
        "provider": "Futu OpenAPI Python SDK via local OpenD",
        "opend_host": FUTU_HOST,
        "opend_port": FUTU_PORT,
        "sdk_version": __import__("futu").__version__,
        "mapping_projection_sha256": projection["projection_sha256"],
        "target_us_session_date": TARGET_SESSION,
        "quota_before": before,
        "canary_requests": records,
        "quota_after": after,
        "checks": {},
        "status": "TESTED",
    }
    for record in records:
        rows = record.get("response_rows") or []
        exact_rows = [row for row in rows if str(row.get("time_key", ""))[:10] == TARGET_DATE]
        record["exact_target_date_row_count"] = len(exact_rows)
        if record.get("ret") != RET_OK or len(exact_rows) != 1:
            canary["status"] = "PARTIAL"
        elif not finite_positive(exact_rows[0].get("close")):
            canary["status"] = "PARTIAL"
    canary["checks"] = {
        "three_symbols_requested": len(records) == 3,
        "all_returns_ok": all(record.get("ret") == RET_OK for record in records),
        "all_exact_2026_10_15_rows": all(record.get("exact_target_date_row_count") == 1 for record in records),
        "all_close_positive": all(any(str(row.get("time_key", ""))[:10] == TARGET_DATE and finite_positive(row.get("close")) for row in (record.get("response_rows") or [])) for record in records),
        "quota_reported": before.get("ret") == RET_OK and after.get("ret") == RET_OK,
    }
    if not all(canary["checks"].values()):
        canary["status"] = "CANNOT_CONFIRM"
    write_json(CANARY_PATH, canary)
    return canary


def finite_positive(value: Any) -> bool:
    try:
        number = float(value)
        return math.isfinite(number) and number > 0
    except (TypeError, ValueError):
        return False

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canary", action="store_true", help="Capture or replay the three-symbol exact-day K-line canary")
    args = parser.parse_args()
    if not args.canary:
        parser.error("choose --canary; this R1 scope does not expose additional daily-K requests")
    try:
        replayed_saved_canary = (
            CANARY_PATH.exists()
            and read_json(CANARY_PATH).get("schema_version") == "futu-r1-canary-v1"
        )
        canary = run_canary()
        print(json.dumps({
            "status": canary.get("status"),
            "checks": canary.get("checks"),
            "quota_before": canary.get("quota_before"),
            "quota_after": canary.get("quota_after"),
            "file": str(CANARY_PATH),
            "replayed_saved_canary": replayed_saved_canary,
        }, ensure_ascii=False, sort_keys=True))
        return 0 if canary.get("status") == "TESTED" else 2
    except Exception as exc:
        print("ERROR: %s: %s" % (type(exc).__name__, str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
