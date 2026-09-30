"""domains.research_hourly: source_evidence (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __receipt_entity_body(_v4_scope, /, receipt, aliases):
    status = _v4_global(_v4_scope, '_receipt_status')(receipt)
    if status not in _v4_global(_v4_scope, 'VERIFIED_ENTITY_RECEIPT_STATUSES'):
        return None
    if not _v4_global(_v4_scope, '_receipt_locator')(receipt):
        return None
    code = _v4_global(_v4_scope, 'str')(
        receipt.get("stock_code")
        or receipt.get("code")
        or receipt.get("normalized_code")
        or receipt.get("entity_id")
        or ""
    ).strip()
    name = _v4_global(_v4_scope, 'str')(receipt.get("stock_name") or receipt.get("name") or receipt.get("entity_name") or "").strip()
    resolved: tuple[str, str] | None = None
    if code and code in aliases:
        resolved = aliases[code]
    if name and name in aliases:
        if resolved is not None and resolved[0] != aliases[name][0]:
            return None
        resolved = aliases[name]
    return resolved


def _normalized_source_evidence_level_body(_v4_scope, /, item):
    raw_level = _v4_global(_v4_scope, 'str')(item.source_evidence_level or "").strip().upper()
    if raw_level not in {"L1_WEAK", "L2_MEDIUM", "L3_STRONG"}:
        return None
    if raw_level == "L3_STRONG" and item.cannot_confirm:
        raw_level = "L2_MEDIUM"
    confidence = _v4_global(_v4_scope, 'str')(item.source_confidence or "").strip().upper()
    if confidence not in {"LOW", "MEDIUM", "HIGH"}:
        confidence = {"L1_WEAK": "LOW", "L2_MEDIUM": "MEDIUM", "L3_STRONG": "HIGH"}[raw_level]
    if raw_level != "L3_STRONG" and confidence == "HIGH":
        confidence = "MEDIUM" if raw_level == "L2_MEDIUM" else "LOW"
    return raw_level, confidence


def _extract_stock_evidence_body(_v4_scope, /, items, stock_master):
    aliases = _v4_global(_v4_scope, 'stock_aliases')(stock_master)
    aliases_by_code: dict[str, tuple[str, ...]] = {}
    for alias, (code, _name) in aliases.items():
        aliases_by_code.setdefault(code, _v4_global(_v4_scope, 'tuple')())
        aliases_by_code[code] = (*aliases_by_code[code], alias)
    evidence: dict[str, StockResearchEvidence] = {}
    for item in items:
        haystack = " ".join([item.title, item.summary])
        matched: list[tuple[str, str, bool, dict[str, Any] | None]] = []
        for alias, (code, name) in aliases.items():
            if alias and alias in haystack:
                matched.append((code, name, True, None))
        for receipt in item.source_entity_receipts:
            entity = _v4_global(_v4_scope, '_receipt_entity')(receipt, aliases)
            if entity:
                matched.append((entity[0], entity[1], False, receipt))
        unique_matches: dict[str, tuple[str, str, bool, dict[str, Any] | None]] = {}
        for code, name, direct, receipt in matched:
            existing = unique_matches.get(code)
            if existing is None or (direct and not existing[2]):
                unique_matches[code] = (code, name, direct, receipt)
        matched = _v4_global(_v4_scope, 'list')(unique_matches.values())
        if not matched:
            continue
        for code, name, direct, receipt in matched:
            theme_only = not direct and receipt is None
            level, confidence = _v4_global(_v4_scope, 'evidence_level')(item, direct=direct, theme_only=theme_only)
            cannot = _v4_global(_v4_scope, 'list')(item.cannot_confirm)
            if theme_only:
                cannot.append("THEME_ONLY_OR_TAG_MAPPING_NEEDS_REVIEW")
            sentence = (
                _v4_global(_v4_scope, '_receipt_evidence_sentence')(receipt)
                if receipt is not None
                else _v4_global(_v4_scope, 'evidence_sentence')(item, name, aliases_by_code.get(code, ()))
            )
            receipt_locator = _v4_global(_v4_scope, '_receipt_locator')(receipt) if receipt is not None else ""
            if receipt is not None and not sentence:
                sentence = f"source-to-entity receipt {receipt_locator} verifies {name}"
            dedup_key = _v4_global(_v4_scope, 'stable_hash')("|".join([code, item.trade_date, item.source_type, item.title, sentence]))
            row = _v4_global(_v4_scope, 'StockResearchEvidence')(
                evidence_id=_v4_global(_v4_scope, 'stable_hash')("evidence|" + dedup_key),
                stock_code=code,
                stock_name=name,
                trade_date=item.trade_date,
                event_time=item.display_event_time or item.event_time,
                source_published_at=item.source_published_at,
                first_seen_at=item.first_seen_at,
                last_checked_at=item.last_checked_at,
                display_event_time=item.display_event_time or item.event_time,
                is_new_since_last_slot=item.is_new_since_last_slot,
                is_recheck_duplicate=item.is_recheck_duplicate,
                time_bucket=_v4_global(_v4_scope, 'time_bucket')(item.display_event_time or item.event_time),
                source_type=item.source_type,
                source_name=item.source_name,
                source_title=item.title,
                source_path=item.source_path,
                url=item.url,
                theme=item.themes[0] if item.themes else "",
                catalyst=item.themes[0] if item.themes else "",
                evidence_sentence=sentence,
                evidence_level=level,
                confidence=confidence,
                extractor="dictionary",
                is_direct_stock_mention=direct,
                is_theme_only_mapping=theme_only,
                dedup_key=dedup_key,
                quality_flags=(f"SOURCE_ENTITY_RECEIPT:{receipt_locator}",) if receipt_locator else (),
                cannot_confirm=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(cannot)),
            )
            evidence.setdefault(dedup_key, row)
    return _v4_global(_v4_scope, 'sorted')(evidence.values(), key=lambda row: (row.stock_code, row.event_time, row.source_type))


def _validate_hourly_stage_source_body(_v4_scope, /, source, *, trade_date, slot, cutoff, allow_late_observations, manifest_pit_cutoff):
    """Validate source identity and times that the archive projection discards.

    A late-observation exception is only used by the original CLI recovery path.
    The stage reader never uses it: every observed timestamp must precede the
    actual stage cutoff.  No date, timestamp, score or delta flag is repaired.
    """
    manifest = source.get("source_manifest")
    if (source.get("trade_date") != trade_date or not _v4_global(_v4_scope, 'isinstance')(manifest, _v4_global(_v4_scope, 'Mapping'))
            or manifest.get("hourly_slot") != slot):
        raise _v4_global(_v4_scope, 'ValueError')("HOURLY_SOURCE_DATE_SLOT_MISMATCH")
    if source.get("slot", slot) != slot or manifest.get("trade_date", trade_date) != trade_date:
        raise _v4_global(_v4_scope, 'ValueError')("HOURLY_SOURCE_DATE_SLOT_MISMATCH")
    declared_pit_cutoff = manifest.get("pit_cutoff")
    # New producer snapshots carry an explicit PIT declaration.  Bind it to
    # the slot-derived cutoff before projecting any rows.  A few older unit
    # fixtures predate this field and remain compatible when they have none;
    # once the producer identity (or a declaration itself) is present, a
    # missing declaration is an invalid source rather than an inferred time.
    requires_pit_cutoff = _v4_global(_v4_scope, 'bool')(
        source.get("slot") == slot
        or manifest.get("producer") == "ops.collect_hourly_research_input"
        or manifest.get("capture_origin") == "ORIGINAL_SLOT"
        or declared_pit_cutoff not in (None, "")
    )
    if declared_pit_cutoff in (None, ""):
        if requires_pit_cutoff:
            raise _v4_global(_v4_scope, 'ValueError')("HOURLY_SOURCE_MANIFEST_PIT_CUTOFF_MISSING")
    else:
        declared_cutoff = _v4_global(_v4_scope, 'hourly_source_time')(declared_pit_cutoff)
        expected_cutoff = (manifest_pit_cutoff or cutoff).replace(microsecond=0)
        if declared_cutoff != expected_cutoff:
            raise _v4_global(_v4_scope, 'ValueError')("HOURLY_SOURCE_MANIFEST_PIT_CUTOFF_MISMATCH")
    for name in ("generated_at", "published_at"):
        if manifest.get(name) not in (None, ""):
            value = _v4_global(_v4_scope, 'hourly_source_time')(manifest[name])
            if value.strftime("%Y%m%d") != trade_date or value > cutoff:
                raise _v4_global(_v4_scope, 'ValueError')("HOURLY_SOURCE_MANIFEST_PIT_MISMATCH")
    for name in ("raw_items", "research_items", "stock_research_timeline", "stock_research_daily"):
        rows = source.get(name, [])
        if not _v4_global(_v4_scope, 'isinstance')(rows, _v4_global(_v4_scope, 'list')):
            raise _v4_global(_v4_scope, 'ValueError')("HOURLY_SOURCE_ROWS_INVALID:" + name)
        for row in rows:
            if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'ValueError')("HOURLY_SOURCE_ROW_INVALID:" + name)
            values = [row]
            if name == "raw_items" and "raw_payload" in row:
                if not _v4_global(_v4_scope, 'isinstance')(row["raw_payload"], _v4_global(_v4_scope, 'Mapping')):
                    raise _v4_global(_v4_scope, 'ValueError')("HOURLY_SOURCE_RAW_PAYLOAD_INVALID")
                values.append(row["raw_payload"])
            for value in values:
                if value.get("trade_date", trade_date) != trade_date or value.get("slot", slot) != slot:
                    raise _v4_global(_v4_scope, 'ValueError')("HOURLY_SOURCE_ROW_DATE_SLOT_MISMATCH")
                for field in _v4_global(_v4_scope, '_HOURLY_SOURCE_TIMES'):
                    if value.get(field) in (None, ""):
                        continue
                    if _v4_global(_v4_scope, 'hourly_source_time')(value[field]) > cutoff and not (
                        allow_late_observations and field in _v4_global(_v4_scope, '_HOURLY_OBSERVATION_TIMES')
                    ):
                        raise _v4_global(_v4_scope, 'ValueError')("HOURLY_SOURCE_ROW_PIT_MISMATCH:" + name + "." + field)
