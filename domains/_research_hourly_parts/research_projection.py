"""domains.research_hourly: research_projection (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _build_raw_items_body(_v4_scope, /, trade_date, rows):
    raw_items: list[RawResearchItem] = []
    for index, row in _v4_global(_v4_scope, 'enumerate')(rows):
        source_type = _v4_global(_v4_scope, 'normalize_source_type')(row.get("source_type"))
        title = _v4_global(_v4_scope, 'compact_text')(row.get("title"), 300)
        raw_text = _v4_global(_v4_scope, 'compact_text')(row.get("raw_text") or row.get("body") or row.get("summary"), 5000)
        published_at = _v4_global(_v4_scope, 'compact_text')(row.get("display_event_time") or row.get("published_at") or row.get("event_time"), 40)
        source_path = _v4_global(_v4_scope, 'compact_text')(row.get("source_path"), 300)
        url = _v4_global(_v4_scope, 'compact_text')(row.get("url"), 500)
        flags: list[str] = []
        if not title:
            flags.append("MISSING_TITLE")
        if not raw_text:
            flags.append("MISSING_TEXT")
        if not published_at:
            flags.append("MISSING_PUBLISHED_AT")
        raw_id = _v4_global(_v4_scope, 'compact_text')(row.get("raw_id")) or _v4_global(_v4_scope, 'stable_hash')(
            "|".join([trade_date, source_type, title, raw_text[:300], _v4_global(_v4_scope, 'str')(index)])
        )
        raw_items.append(
            _v4_global(_v4_scope, 'RawResearchItem')(
                raw_id=raw_id,
                trade_date=trade_date,
                source_type=source_type,
                source_name=_v4_global(_v4_scope, 'compact_text')(row.get("source_name"), 120),
                source_path=source_path,
                url=url,
                title=title,
                raw_text=raw_text,
                published_at=published_at,
                crawl_time=_v4_global(_v4_scope, 'compact_text')(row.get("crawl_time"), 40),
                raw_payload=_v4_global(_v4_scope, 'dict')(row),
                quality_flags=_v4_global(_v4_scope, 'tuple')(flags),
            )
        )
    return raw_items


def _normalize_research_items_body(_v4_scope, /, raw_items):
    dedup: dict[str, ResearchItem] = {}
    for raw in raw_items:
        text = raw.raw_text or raw.title
        summary = _v4_global(_v4_scope, 'compact_text')(text, 280)
        themes = _v4_global(_v4_scope, 'split_tokens')(raw.raw_payload.get("themes") or raw.raw_payload.get("theme") or raw.raw_payload.get("sector"))
        candidates = _v4_global(_v4_scope, 'split_tokens')(
            raw.raw_payload.get("mentioned_stock_candidates")
            or raw.raw_payload.get("stock_tags")
            or raw.raw_payload.get("stocks")
            or raw.raw_payload.get("stock")
        )
        cannot = _v4_global(_v4_scope, 'list')(raw.quality_flags)
        source_cannot = raw.raw_payload.get("source_cannot_confirm") or raw.raw_payload.get("cannot_confirm")
        if source_cannot:
            cannot.extend(_v4_global(_v4_scope, 'split_tokens')(source_cannot))
        if not (raw.source_path or raw.url):
            cannot.append("MISSING_SOURCE_TRACE")
        quality = "OK" if not cannot else "CANNOT_CONFIRM"
        dedup_key = _v4_global(_v4_scope, 'stable_hash')("|".join([raw.source_type, raw.title, raw.published_at or raw.trade_date, summary[:100]]))
        item = _v4_global(_v4_scope, 'ResearchItem')(
            item_id=_v4_global(_v4_scope, 'stable_hash')("item|" + dedup_key),
            raw_id=raw.raw_id,
            trade_date=raw.trade_date,
            event_time=_v4_global(_v4_scope, 'event_time_of')(raw),
            source_published_at=_v4_global(_v4_scope, 'compact_text')(raw.raw_payload.get("source_published_at"), 40),
            first_seen_at=_v4_global(_v4_scope, 'compact_text')(raw.raw_payload.get("first_seen_at"), 40),
            last_checked_at=_v4_global(_v4_scope, 'compact_text')(raw.raw_payload.get("last_checked_at") or raw.crawl_time, 40),
            display_event_time=_v4_global(_v4_scope, 'compact_text')(raw.raw_payload.get("display_event_time") or _v4_global(_v4_scope, 'event_time_of')(raw), 40),
            is_new_since_last_slot=_v4_global(_v4_scope, 'truthy')(raw.raw_payload.get("is_new_since_last_slot")),
            is_recheck_duplicate=_v4_global(_v4_scope, 'truthy')(raw.raw_payload.get("is_recheck_duplicate")),
            source_type=raw.source_type,
            source_name=raw.source_name,
            source_path=raw.source_path,
            url=raw.url,
            title=raw.title or "未命名研报/资讯",
            summary=summary,
            themes=themes,
            mentioned_stock_candidates=candidates,
            dedup_key=dedup_key,
            item_quality=quality,
            source_evidence_level=_v4_global(_v4_scope, 'compact_text')(raw.raw_payload.get("source_evidence_level"), 40),
            source_confidence=_v4_global(_v4_scope, 'compact_text')(raw.raw_payload.get("source_confidence"), 40),
            cannot_confirm=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(cannot)),
            source_entity_receipts=_v4_global(_v4_scope, 'normalize_entity_receipts')(raw.raw_payload),
        )
        dedup.setdefault(dedup_key, item)
    return _v4_global(_v4_scope, 'list')(dedup.values())


def _build_research_pool_bridge_body(_v4_scope, /, trade_date, daily_rows, evidence_rows, pool_rows):
    pools_by_code: dict[str, dict[str, Any]] = {}
    for row in pool_rows or []:
        code = _v4_global(_v4_scope, 'str')(row.get("stock_code") or row.get("symbol") or row.get("code") or "").strip()
        if code:
            pools_by_code[code] = row
    evidence_by_code: dict[str, list[StockResearchEvidence]] = {}
    for row in evidence_rows:
        evidence_by_code.setdefault(row.stock_code, []).append(row)
    bridges: list[ResearchPoolBridge] = []
    for daily in daily_rows:
        pool = pools_by_code.get(daily.stock_code, {})
        matched_pool = _v4_global(_v4_scope, 'str')(pool.get("matched_pool") or pool.get("pool") or "NONE") if pool else "NONE"
        matched_stage = _v4_global(_v4_scope, 'str')(pool.get("matched_stage") or pool.get("stage") or "") if pool else ""
        formal_overlap = matched_pool.upper() == "FORMAL" or _v4_global(_v4_scope, 'bool')(pool.get("formal_overlap"))
        stage_overlap = _v4_global(_v4_scope, 'bool')(matched_stage)
        evidence_ids = _v4_global(_v4_scope, 'tuple')(row.evidence_id for row in evidence_by_code.get(daily.stock_code, []))
        max_level = "L3_STRONG" if daily.strong_evidence_count else "L2_MEDIUM" if daily.medium_evidence_count else "L1_WEAK"
        bridges.append(
            _v4_global(_v4_scope, 'ResearchPoolBridge')(
                bridge_id=_v4_global(_v4_scope, 'stable_hash')("bridge|" + "|".join([trade_date, daily.stock_code, matched_pool, matched_stage])),
                trade_date=trade_date,
                stock_code=daily.stock_code,
                stock_name=daily.stock_name,
                research_score=daily.research_score,
                evidence_level=max_level,
                matched_pool=matched_pool,
                matched_stage=matched_stage,
                formal_overlap=formal_overlap,
                stage_overlap=stage_overlap,
                reason="研报/资讯证据与池或阶段形成只读桥接" if pool else "研报/资讯证据已形成，但未命中池或阶段",
                next_action=daily.next_action,
                source_evidence_ids=evidence_ids,
            )
        )
    return bridges


def _write_snapshot_outputs_body(_v4_scope, /, snapshot, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "research_lane_snapshot.json").write_text(
        _v4_global(_v4_scope, 'json').dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    _v4_global(_v4_scope, 'write_jsonl')(output_dir / "raw_items.jsonl", snapshot.get("raw_items") or [])
    _v4_global(_v4_scope, 'write_jsonl')(output_dir / "research_items.jsonl", snapshot.get("research_items") or [])
    _v4_global(_v4_scope, 'write_csv')(output_dir / "stock_research_evidence.csv", snapshot.get("stock_research_timeline") or [])
    _v4_global(_v4_scope, 'write_csv')(output_dir / "stock_research_daily.csv", snapshot.get("stock_research_daily") or [])
    _v4_global(_v4_scope, 'write_csv')(output_dir / "research_pool_bridge.csv", snapshot.get("research_pool_bridge") or [])
    (output_dir / "manifest.json").write_text(_v4_global(_v4_scope, 'json').dumps(snapshot.get("source_manifest") or {}, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    summary = snapshot.get("research_quality_summary") or {}
    cannot_confirm = snapshot.get("cannot_confirm") or []
    report = [
        "# v3.5 研报模块质量报告",
        "",
        f"trade_date: {snapshot['trade_date']}",
        f"schema_version: {snapshot['schema_version']}",
        f"write_policy: {snapshot['write_policy']}",
        f"default_status: {snapshot['default_status']}",
        "",
        "## Counts",
        *[f"- {key}: {value}" for key, value in summary.items()],
        "",
        "## Cannot Confirm",
        *[f"- {item}" for item in cannot_confirm],
    ]
    (output_dir / "quality_report.md").write_text("\n".join(report), encoding="utf-8-sig")


def _project_hourly_stage_fields_body(_v4_scope, /, source):
    """Project only explicitly present facts through frozen producer lineage.

    Caller must first verify the raw SHA against the exact archive receipt and
    validate dates/PIT. No title-only join, text/entity re-extraction, quality
    scale conversion, default delta flag or stock_pool.research_score alias.
    Ambiguous/missing lineage affects that evidence/code, never another code.
    """
    normalized: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    raw_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for item in source.get("research_items", []):
        normalized.setdefault(_v4_global(_v4_scope, '_stage_item_identity')(item), []).append(item)
    for raw in source.get("raw_items", []):
        raw_by_id.setdefault(_v4_global(_v4_scope, 'str')(raw.get("raw_id") or ""), []).append(raw)
    items: dict[tuple[str, str], dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []
    gaps: list[str] = []
    for row in source.get("stock_research_timeline", []):
        code = _v4_global(_v4_scope, 'canonical_stage_a_code')(row.get("stock_code"))
        if not code:
            continue
        matched = normalized.get(_v4_global(_v4_scope, '_stage_item_identity')(row, evidence=True), [])
        if _v4_global(_v4_scope, 'len')(matched) != 1 or not _v4_global(_v4_scope, 'str')(matched[0].get("item_id") or ""):
            gaps.append("RESEARCH_ITEM_LINEAGE_MISSING_OR_AMBIGUOUS:" + code)
            continue
        item = matched[0]
        raw_id = _v4_global(_v4_scope, 'str')(item.get("raw_id") or "").strip()
        if not raw_id:
            gaps.append("RESEARCH_RAW_LINEAGE_MISSING:" + code)
            continue
        raw_candidates = raw_by_id.get(raw_id, [])
        raw_payload: Mapping[str, Any] = {}
        if _v4_global(_v4_scope, 'len')(raw_candidates) == 0:
            gaps.append("RESEARCH_RAW_LINEAGE_MISSING:" + code)
        elif _v4_global(_v4_scope, 'len')(raw_candidates) > 1:
            gaps.append("RESEARCH_RAW_LINEAGE_AMBIGUOUS:" + code)
        else:
            raw_payload = raw_candidates[0].get("raw_payload", {})
        output: dict[str, Any] = {
            "stock_code": code, "item_id": item["item_id"], "raw_id": raw_id,
            "source_title": row.get("source_title", ""), "source_path": row.get("source_path", ""),
            "url": row.get("url", ""), "cannot_confirm": _v4_global(_v4_scope, 'list')(item.get("cannot_confirm") or []),
        }
        if _v4_global(_v4_scope, 'isinstance')(item.get("item_quality"), _v4_global(_v4_scope, 'str')):
            output["item_quality"] = item["item_quality"]
        for flag in ("is_new_since_last_slot", "is_recheck_duplicate"):
            values = [r[flag] for r in (item, raw_payload, row) if flag in r]
            if values and _v4_global(_v4_scope, 'all')(_v4_global(_v4_scope, 'type')(v) is _v4_global(_v4_scope, 'bool') for v in values) and _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(values)) == 1:
                output[flag] = values[0]
            else:
                gaps.append("RESEARCH_DELTA_FLAG_UNPROVEN:" + code)
        numeric = [r["quality_score"] for r in (item, raw_payload) if "quality_score" in r]
        if numeric:
            if _v4_global(_v4_scope, 'all')(_v4_global(_v4_scope, 'type')(v) in (_v4_global(_v4_scope, 'int'), _v4_global(_v4_scope, 'float')) and _v4_global(_v4_scope, 'math').isfinite(_v4_global(_v4_scope, 'float')(v)) for v in numeric) and _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(numeric)) == 1:
                output["quality_score"] = numeric[0]
            else:
                gaps.append("RESEARCH_ITEM_QUALITY_SCORE_INVALID:" + code)
        key = (code, _v4_global(_v4_scope, 'str')(item["item_id"]))
        if key in items and items[key] != output:
            # Never select one side of a conflicting item/code association.
            raise _v4_global(_v4_scope, 'ValueError')("HOURLY_SOURCE_ITEM_CODE_CONFLICT:" + code)
        items.setdefault(key, output)
        evidence.append({"stock_code": code, "evidence_id": row.get("evidence_id"),
                         "cannot_confirm": _v4_global(_v4_scope, 'list')(row.get("cannot_confirm") or [])})
    return _v4_global(_v4_scope, 'list')(items.values()), evidence, _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(gaps))
