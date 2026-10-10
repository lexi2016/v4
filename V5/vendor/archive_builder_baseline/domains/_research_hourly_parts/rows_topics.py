"""domains.research_hourly: rows_topics (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _stock_aliases_body(_v4_scope, /, stock_master):
    aliases: dict[str, tuple[str, str]] = {}
    for code, info in stock_master.items():
        if _v4_global(_v4_scope, 'isinstance')(info, _v4_global(_v4_scope, 'dict')):
            name = _v4_global(_v4_scope, 'str')(info.get("name") or info.get("stock_name") or "").strip()
            alias_values = [name, code, *(info.get("aliases") or [])]
        else:
            name = _v4_global(_v4_scope, 'str')(info).strip()
            alias_values = [name, code]
        if not name:
            name = code
        for alias in alias_values:
            alias = _v4_global(_v4_scope, 'str')(alias or "").strip()
            if alias:
                aliases[alias] = (code, name)
    return aliases


def _unassigned_entity_notes_body(_v4_scope, /, items, stock_master):
    """Report candidate tags that lack text or an explicit mapping receipt."""
    aliases = _v4_global(_v4_scope, 'stock_aliases')(stock_master)
    notes: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = _v4_global(_v4_scope, 'set')()
    for item in items:
        haystack = " ".join([item.title, item.summary])
        direct_codes = {code for alias, (code, _name) in aliases.items() if alias and alias in haystack}
        receipt_codes = {
            entity[0]
            for receipt in item.source_entity_receipts
            if (entity := _v4_global(_v4_scope, '_receipt_entity')(receipt, aliases)) is not None
        }
        for candidate in item.mentioned_stock_candidates:
            entity = aliases.get(candidate)
            if entity is None or entity[0] in direct_codes or entity[0] in receipt_codes:
                continue
            key = (item.item_id, entity[0])
            if key in seen:
                continue
            seen.add(key)
            notes.append(
                {
                    "item_id": item.item_id,
                    "reason": "STOCK_CANDIDATE_ENTITY_NOT_VERIFIED",
                    "stock_code": entity[0],
                    "stock_name": entity[1],
                    "source_path": item.source_path,
                    "url": item.url,
                }
            )
    return notes


def _aggregate_stock_research_daily_body(_v4_scope, /, evidence_rows):
    grouped: dict[tuple[str, str], list[StockResearchEvidence]] = {}
    for row in evidence_rows:
        grouped.setdefault((row.trade_date, row.stock_code), []).append(row)
    daily: list[StockResearchDaily] = []
    for (_trade_date, _code), rows in grouped.items():
        rows.sort(key=lambda row: row.event_time)
        strong = _v4_global(_v4_scope, 'sum')(row.evidence_level == "L3_STRONG" for row in rows)
        medium = _v4_global(_v4_scope, 'sum')(row.evidence_level == "L2_MEDIUM" for row in rows)
        weak = _v4_global(_v4_scope, 'sum')(row.evidence_level == "L1_WEAK" for row in rows)
        score = _v4_global(_v4_scope, 'score_evidence')(rows)
        if strong:
            status = "HOT"
        elif _v4_global(_v4_scope, 'len')(rows) >= 2:
            status = "REPEATED"
        elif rows[0].cannot_confirm:
            status = "CANNOT_CONFIRM"
        else:
            status = "NEW"
        daily.append(
            _v4_global(_v4_scope, 'StockResearchDaily')(
                stock_code=rows[0].stock_code,
                stock_name=rows[0].stock_name,
                trade_date=rows[0].trade_date,
                first_seen_time=rows[0].event_time,
                last_seen_time=rows[-1].event_time,
                evidence_count=_v4_global(_v4_scope, 'len')(rows),
                source_count=_v4_global(_v4_scope, 'len')({row.source_type for row in rows}),
                strong_evidence_count=strong,
                medium_evidence_count=medium,
                weak_evidence_count=weak,
                themes=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'sorted')({row.theme for row in rows if row.theme})),
                top_catalysts=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'sorted')({row.catalyst for row in rows if row.catalyst})),
                source_types=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'sorted')({row.source_type for row in rows})),
                latest_evidence_sentence=rows[-1].evidence_sentence,
                research_score=score,
                research_status=status,
                pool_overlap={},
                next_action="补盘口/分时/成交/复盘证据，等待正式池或人工审查确认。",
            )
        )
    return _v4_global(_v4_scope, 'sorted')(daily, key=lambda row: (-row.research_score, row.first_seen_time, row.stock_code))
