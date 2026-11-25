"""Project the native hourly input and HK close snapshot without upstream writers."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
import math
from typing import Any
from zoneinfo import ZoneInfo

from v4_core.runner.evidence import DatedInputs, EvidenceError, SAFETY_FLAGS, aware_time, iso_date, mapping, require, symbol


def _text(value: Any) -> str:
    return str(value or "").strip()


def _hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        result = float(value)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _row_time(value: Any, fallback: Any) -> str:
    try:
        stamp = datetime.fromisoformat(_text(value) or _text(fallback))
    except ValueError as exc:
        raise EvidenceError("HOURLY_SOURCE_ROW_TIME_INVALID") from exc
    if stamp.utcoffset() is None:
        stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return stamp.isoformat(timespec="seconds")


def _rows(payload: dict, key: str, date: str) -> list[dict]:
    values = payload.get(key)
    require(isinstance(values, list) and values, f"NATIVE_{key.upper()}_UNAVAILABLE")
    require(all(isinstance(row, dict) and iso_date(row.get("trade_date")) == date for row in values),
            f"NATIVE_{key.upper()}_DATE_MISMATCH")
    return values


def _dedupe_articles(raw: list[dict]) -> list[tuple[tuple[str, ...], dict]]:
    grouped: dict[tuple[str, ...], dict] = {}
    for row in raw:
        key = tuple(_text(value).lower() for value in (
            row.get("stock_code") or row.get("code"), row.get("source_title") or row.get("title"),
            row.get("url") or row.get("source_url"), row.get("source_path"),
            row.get("source_name") or row.get("source_type"), row.get("claim_type") or row.get("evidence_level"),
        ))
        require(bool(key[0] and key[1] and (key[2] or key[3])), "HOURLY_SOURCE_ARTICLE_IDENTITY_INCOMPLETE")
        current = grouped.setdefault(key, {**row, "_count": 0, "_keys": set()})
        current["_count"] += 1
        if row.get("dedup_key"):
            current["_keys"].add(_text(row["dedup_key"]))
        if len(_text(row.get("evidence_sentence"))) > len(_text(current.get("evidence_sentence"))):
            current["evidence_sentence"] = row.get("evidence_sentence")
        if _text(row.get("event_time")) > _text(current.get("event_time")):
            current["event_time"] = row.get("event_time")
    return sorted(grouped.items(), key=lambda pair: (_text(pair[1].get("event_time")),
                                                    _text(pair[1].get("stock_code"))), reverse=True)


def build_hourly_archive(
    inputs: DatedInputs, entry: dict, asof: datetime,
) -> tuple[dict[str, Any], dict[str, list]]:
    source_file = inputs.file(entry.get("source"))
    payload = mapping(source_file.json(), "HOURLY_NATIVE_SOURCE_INVALID")
    day = inputs.trade_date
    compact = day.replace("-", "")
    manifest = mapping(payload.get("source_manifest"), "HOURLY_NATIVE_SOURCE_MANIFEST_UNAVAILABLE")
    require(iso_date(payload.get("trade_date")) == iso_date(manifest.get("trade_date")) == day
            and payload.get("slot") == manifest.get("hourly_slot") == "1900"
            and payload.get("default_status") == "RESEARCH_ONLY" and payload.get("write_policy") == "read_only"
            and payload.get("buy_gate_effect") == payload.get("live_order_effect") == "none",
            "HOURLY_NATIVE_IDENTITY_OR_SAFETY_MISMATCH")
    generated = aware_time(manifest.get("published_at") or manifest.get("generated_at"))
    require(generated <= asof and generated.date().isoformat() == day
            and generated <= aware_time(entry.get("observed_at")), "HOURLY_NATIVE_SOURCE_TIME_MISMATCH")
    timeline = _rows(payload, "stock_research_timeline", day)
    daily = _rows(payload, "stock_research_daily", day)
    bridge_rows = _rows(payload, "research_pool_bridge", day)
    bridges = {row["stock_code"]: row for row in bridge_rows if row.get("stock_code")}
    require(len(bridges) == len(bridge_rows), "HOURLY_NATIVE_BRIDGE_IDENTITY_INVALID")
    source_counts: Counter[str] = Counter()
    articles: list[dict] = []
    by_code: dict[str, list[dict]] = defaultdict(list)
    for key, row in _dedupe_articles(timeline):
        canonical_key = "\x1f".join(key)
        source_name = _text(row.get("source_name") or row.get("source_type"))
        source_counts[source_name or "UNKNOWN"] += 1
        event_time = row.get("event_time")
        article = {
            "article_id": _hash(f"{compact}\x1e{canonical_key}"),
            "dedupe_key": _hash(canonical_key), "archive_date": compact,
            "stock_code": _text(row.get("stock_code") or row.get("code")),
            "stock_name": _text(row.get("stock_name") or row.get("name")),
            "source_type": _text(row.get("source_type")), "source_name": source_name,
            "source_title": _text(row.get("source_title") or row.get("title")),
            "source_path_sha256": _hash(_text(row.get("source_path"))),
            "url": _text(row.get("url") or row.get("source_url")),
            **{field: _text(row.get(field)) for field in
               ("theme", "catalyst", "evidence_sentence", "evidence_level", "confidence")},
            "published_at": _row_time(row.get("source_published_at"), event_time),
            "collected_at": _row_time(row.get("last_checked_at"), event_time),
            "first_seen_at": _row_time(row.get("first_seen_at"), event_time),
            "duplicate_evidence_count": row["_count"], "source_dedup_keys": sorted(row["_keys"]),
            "recommendation_status": "RESEARCH_ONLY",
        }
        articles.append(article)
        by_code[article["stock_code"]].append(article)
    pool: list[dict] = []
    codes: set[str] = set()
    for row in daily:
        code = _text(row.get("stock_code"))
        require(code and code not in codes and code in bridges, "HOURLY_NATIVE_DAILY_OR_BRIDGE_IDENTITY_INVALID")
        codes.add(code)
        matches = by_code.get(code, [])
        first = min((item["first_seen_at"] for item in matches), default=generated.isoformat())
        last = max((item["collected_at"] for item in matches), default=generated.isoformat())
        bridge = bridges[code]
        pool.append({
            "stock_code": code, "stock_name": _text(row.get("stock_name")), "archive_date": compact,
            "research_score": _number(row.get("research_score")), "research_status": _text(row.get("research_status")),
            **{field: int(_number(row.get(field))) for field in
               ("evidence_count", "source_count", "strong_evidence_count", "medium_evidence_count", "weak_evidence_count")},
            **{field: sorted({_text(item) for item in row.get(field, []) if _text(item)}) for field in
               ("source_types", "themes", "top_catalysts")},
            "first_seen_at": _row_time(row.get("first_seen_time"), first),
            "collected_at": _row_time(row.get("last_seen_time"), last),
            "formal_overlap": bool(bridge.get("formal_overlap", False)),
            "stage_overlap": bool(bridge.get("stage_overlap", False)),
            "recommendation_status": "RESEARCH_ONLY",
        })
    require(codes == bridges.keys(), "HOURLY_NATIVE_DAILY_BRIDGE_SET_MISMATCH")
    pool.sort(key=lambda row: (-row["research_score"], row["stock_code"]))
    raw_gaps = payload.get("cannot_confirm")
    require(isinstance(raw_gaps, list), "HOURLY_NATIVE_GAP_LEDGER_UNAVAILABLE")
    source_status = entry.get("status")
    require(source_status in {"READY", "PARTIAL_WITH_ROWS"}, "HOURLY_NATIVE_UPSTREAM_STATUS_UNRECOGNIZED")
    ready = source_status == "READY" and not raw_gaps and manifest.get("natural_execution_verified") is True
    return {
        "status": "READY" if ready else "PARTIAL", "source_status": source_status,
        "source_mode": "NATIVE_INPUT_MATERIALIZATION", "source_input_sha256": source_file.sha256,
        "source_identity": {"source": source_file.identity()}, "source_generated_at": generated.isoformat(),
        "source_gap_count": len(raw_gaps), "natural_execution_verified": manifest.get("natural_execution_verified") is True,
        "article_count": len(articles), "stock_pool_count": len(pool), "source_counts": dict(sorted(source_counts.items())),
        **SAFETY_FLAGS,
    }, {"articles": articles, "stock_pool": pool}


def _hk_code(raw: Any) -> str:
    value = _text(raw)
    canonical = symbol(f"{value}.HK" if value.isdigit() else value, "HK")
    return f"HK.{canonical.split('.')[0]}"


def build_hk_close(
    inputs: DatedInputs, entry: dict,
) -> tuple[dict[str, Any], dict[str, list]]:
    close_file = inputs.file(entry.get("close_snapshot"))
    close_receipt_file = inputs.file(entry.get("close_snapshot_receipt"))
    model_file = inputs.file(entry.get("model_pool"))
    close = mapping(close_file.json(), "HK_CLOSE_NATIVE_SNAPSHOT_INVALID")
    receipt = mapping(close_receipt_file.json(), "HK_CLOSE_NATIVE_SNAPSHOT_RECEIPT_INVALID")
    model = mapping(model_file.json(), "HK_CLOSE_NATIVE_MODEL_POOL_INVALID")
    day = inputs.trade_date
    compact = day.replace("-", "")
    require(iso_date(close.get("trade_date")) == iso_date(receipt.get("trade_date")) == day
            and close.get("status") == "READY" and receipt.get("source_sha256") == close_file.sha256,
            "HK_CLOSE_NATIVE_SNAPSHOT_BINDING_MISMATCH")
    require(iso_date(model.get("trade_date")) == iso_date(model.get("target_date")) == day
            and iso_date(model.get("signal_date")) < day and model.get("market") == "HK"
            and model.get("status") == "STRICT_0_2_READY" and model.get("pool_id") == "hkconnect_d1_top100",
            "HK_CLOSE_NATIVE_MODEL_BINDING_MISMATCH")
    require(all(item.get(flag) is False for item in (close, model) for flag in SAFETY_FLAGS if flag != "research_only"),
            "HK_CLOSE_NATIVE_UNSAFE")
    close_rows = _rows(close, "rows", day)
    require(close.get("same_date_row_count") == len(close_rows) and len(close_rows) >= 20,
            "HK_CLOSE_NATIVE_SNAPSHOT_INCOMPLETE")
    ranked: list[dict] = []
    seen = set()
    for row in close_rows:
        code = _hk_code(row.get("code") or row.get("code_norm") or row.get("symbol"))
        last = _number(row.get("close"))
        previous = _number(row.get("pre_close") or row.get("prev_close"))
        amount = _number(row.get("amount"))
        require(code not in seen and last > 0 and previous > 0 and amount >= 0, "HK_CLOSE_NATIVE_ROW_INVALID")
        seen.add(code)
        change = (last / previous - 1.0) * 100.0
        ranked.append({"code": code, "name": _text(row.get("name") or row.get("stock_name")),
                       "pct_chg": change, "pct_chg_close": change, "close": last, "pre_close": previous,
                       "amount": amount, "trade_date": compact})
    ranked.sort(key=lambda row: (-row["pct_chg_close"], -row["amount"], row["code"]))
    truth = [{**row, "rank": rank} for rank, row in enumerate(ranked[:20], 1)]
    truth_codes = {row["code"] for row in truth}
    source_rows = _rows(model, "rows", day)
    require(len(source_rows) == model.get("source_row_count") == 100, "HK_CLOSE_NATIVE_MODEL_POOL_INCOMPLETE")
    ordered = sorted(source_rows, key=lambda row: (_number(row.get("pool_rank") or row.get("rank")) or 1e12,
                                                  _hk_code(row.get("symbol") or row.get("code"))))
    selected_codes: set[str] = set()
    models = []
    for rank, row in enumerate(ordered, 1):
        code = _hk_code(row.get("symbol") or row.get("code"))
        require(code not in selected_codes and str(row.get("market")).upper() in {"HK", "HKCONNECT"}
                and iso_date(row.get("target_date") or row.get("trade_date")) == day, "HK_CLOSE_NATIVE_MODEL_ROW_INVALID")
        selected_codes.add(code)
        models.append({"rank": rank, "code": code, "name": _text(row.get("stock_name") or row.get("name")),
                       "strategy": "prob_active", "pool_version": "0.2", "trade_date": compact,
                       "hit_top20": code in truth_codes})
    hits = [row["code"] for row in models if row["hit_top20"]]
    return {
        "status": "PARTIAL", "source_status": "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE",
        "source_mode": "NATIVE_INPUT_MATERIALIZATION", "model_pit_status": "CANNOT_CONFIRM",
        "stage_evidence_status": "CANNOT_CONFIRM",
        "source_identity": {"close_snapshot": close_file.identity(), "close_snapshot_receipt": close_receipt_file.identity(),
                            "model_pool": model_file.identity()},
        "model_upstream_sha256": model.get("source_sha256"), "model_source_run_id": model.get("source_run_id"),
        "close_snapshot_rows": len(ranked), "close_top20": len(truth), "model_rows": len(models),
        "model_hit_count": len(hits), "model_hit_codes": hits, **SAFETY_FLAGS,
    }, {"close_top20": truth, "model_rows": models}
