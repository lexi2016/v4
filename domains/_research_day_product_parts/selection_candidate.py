"""domains.research_day_product: selection_candidate (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __selection_entity_parts_body(_v4_scope, /, entry, card, *, supply_source):
    entity = _v4_global(_v4_scope, '_text')(entry.get("entity_id"))
    if not entity:
        if supply_source:
            entity = _v4_global(_v4_scope, '_text')(card.get("ticker"))
    if not entity:
        entities = card.get("entities")
        if not _v4_global(_v4_scope, 'isinstance')(entities, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(entities) != 1:
            raise _v4_global(_v4_scope, 'ValueError')("selection card must identify one entity")
        entity = _v4_global(_v4_scope, '_text')(entities[0])
    explicit_market = _v4_global(_v4_scope, '_text')(entry.get("market"))
    explicit_code = _v4_global(_v4_scope, '_text')(entry.get("normalized_code"))
    if explicit_market and explicit_code:
        return explicit_market, explicit_code, entity
    if "." not in entity:
        raise _v4_global(_v4_scope, 'ValueError')("selection entity must include market suffix")
    code, market = entity.rsplit(".", 1)
    if not code or not market:
        raise _v4_global(_v4_scope, 'ValueError')("selection entity identity is incomplete")
    return market, code, entity


def __selection_candidate_body(_v4_scope, /, entry, *, source_date, cutoff_at, route_status):
    card_value = entry.get("card", entry)
    if not _v4_global(_v4_scope, 'isinstance')(card_value, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("selection card is not an object")
    card = card_value
    event_id = _v4_global(_v4_scope, '_text')(entry.get("event_id") or card.get("event_id"))
    if not event_id:
        raise _v4_global(_v4_scope, 'ValueError')("selection card event_id is missing")
    source_ref_value = entry.get("source_ref")
    if source_ref_value is None:
        refs = entry.get("source_refs")
        if _v4_global(_v4_scope, 'isinstance')(refs, _v4_global(_v4_scope, 'list')) and refs:
            source_ref_value = refs[0]
    source_ref = _v4_global(_v4_scope, '_selection_source_ref')(card, source_ref_value, source_date=source_date)
    supply_source = source_ref.get("type") == _v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE')
    market, code, entity = _v4_global(_v4_scope, '_selection_entity_parts')(
        entry,
        card,
        supply_source=supply_source,
    )
    candidate = _v4_global(_v4_scope, 'selection_candidate_id')(market, code, entity)
    if supply_source:
        source = card.get("official_source") if _v4_global(_v4_scope, 'isinstance')(card.get("official_source"), _v4_global(_v4_scope, 'Mapping')) else {}
        status = _v4_global(_v4_scope, '_text')(source.get("identity_status"))
    else:
        source = card.get("source") if _v4_global(_v4_scope, 'isinstance')(card.get("source"), _v4_global(_v4_scope, 'Mapping')) else {}
        status = _v4_global(_v4_scope, '_text')(entry.get("source_status") or source.get("status"))
    if supply_source:
        if not status or status.upper() in {
            "UNKNOWN",
            "UNVERIFIED",
            "CANNOT_CONFIRM",
            "NOT_MATERIALIZED",
        }:
            status = "UNVERIFIED"
    elif not status:
        # Preserve legacy producer status strings byte-for-byte.  Only a
        # genuinely absent legacy status receives the historical fallback.
        status = "UNVERIFIED"
    gemini_status = _v4_global(_v4_scope, '_text')(entry.get("gemini_status")) or (
        "UNVERIFIED" if "GEMINI" in status.upper() else route_status["GEMINI"]
    )
    if gemini_status not in {"UNVERIFIED", "NOT_MATERIALIZED"}:
        gemini_status = "UNVERIFIED"
    if supply_source:
        candidate_routes = {
            "R1": route_status["R1"],
            "R6": route_status["R6"],
        }
    else:
        candidate_routes = {
            "R1": _v4_global(_v4_scope, '_text')(entry.get("r1_status"))
            or (
                "VERIFIED_SOURCE_IDENTITY"
                if "VERIFIED_SOURCE_IDENTITY" in status.upper()
                else route_status["R1"]
            ),
            "R6": _v4_global(_v4_scope, '_text')(entry.get("r6_status")) or route_status["R6"],
        }
    if candidate_routes["R6"] == "GEMINI_DISCOVERY_UNVERIFIED":
        raise _v4_global(_v4_scope, 'ValueError')("selection R6 is not a Gemini alias")
    eligibility = entry.get("eligibility")
    if eligibility is None:
        eligibility = card.get("eligibility_status") if supply_source else card.get("eligibility")
    if _v4_global(_v4_scope, 'isinstance')(eligibility, _v4_global(_v4_scope, 'Mapping')):
        raw_eligibility_status = _v4_global(_v4_scope, '_text')(eligibility.get("status"))
    elif _v4_global(_v4_scope, 'isinstance')(eligibility, _v4_global(_v4_scope, 'str')):
        raw_eligibility_status = eligibility.strip()
    else:
        raw_eligibility_status = ""
    eligibility_status = (
        raw_eligibility_status
        if raw_eligibility_status in {"ELIGIBILITY_CANNOT_CONFIRM", "ELIGIBLE"}
        else "ELIGIBILITY_CANNOT_CONFIRM"
    )
    if supply_source:
        published_at_value = card.get("published_at")
        if published_at_value is None:
            published_at_value = source.get("published_at")
        published_at = _v4_global(_v4_scope, '_selection_value_text')(published_at_value)
    else:
        published_at = _v4_global(_v4_scope, '_text')(
            entry.get("published_at")
            or source.get("published_at")
        )
    source_time = _v4_global(_v4_scope, '_text')(source_ref.get("source_time"))
    published_aware = _v4_global(_v4_scope, '_selection_aware_hkt')(published_at)
    try:
        cutoff_value = _v4_global(_v4_scope, 'datetime').fromisoformat(cutoff_at.replace("Z", "+00:00"))
        source_value = _v4_global(_v4_scope, 'datetime').fromisoformat(source_time.replace("Z", "+00:00"))
    except _v4_global(_v4_scope, 'ValueError'):
        cutoff_value = None
        source_value = None
    if cutoff_value is None or source_value is None or source_value.tzinfo is None or source_value.utcoffset() is None:
        pit_status = "CANNOT_CONFIRM"
    elif published_aware is None:
        pit_status = "CANNOT_CONFIRM"
    else:
        published_value = _v4_global(_v4_scope, 'datetime').fromisoformat(published_aware)
        pit_status = (
            "READY"
            if published_value.astimezone(_v4_global(_v4_scope, '_SHANGHAI')) <= cutoff_value.astimezone(_v4_global(_v4_scope, '_SHANGHAI'))
            and (
                supply_source
                or source_value.astimezone(_v4_global(_v4_scope, '_SHANGHAI')) <= cutoff_value.astimezone(_v4_global(_v4_scope, '_SHANGHAI'))
            )
            else "PIT_FAILED"
        )
    explicit_pit = _v4_global(_v4_scope, '_text')(entry.get("pit_status") or (None if supply_source else card.get("pit_status")))
    if explicit_pit in {"PIT_FAILED", "CANNOT_CONFIRM"}:
        pit_status = explicit_pit
    value_text = _v4_global(_v4_scope, '_selection_value_text') if supply_source else _v4_global(_v4_scope, '_text')
    return {
        "candidate_id": candidate,
        "event_stock_link_id": _v4_global(_v4_scope, 'event_stock_link_id')(event_id, candidate),
        "market": _v4_global(_v4_scope, 'unicodedata').normalize("NFKC", market.strip()).upper(),
        "normalized_code": _v4_global(_v4_scope, 'unicodedata').normalize("NFKC", code.strip()).upper(),
        "entity_id": entity,
        "event_id": event_id,
        "bucket": value_text(entry.get("bucket") if entry.get("bucket") is not None else card.get("bucket")),
        "catalyst": value_text(entry.get("catalyst") if entry.get("catalyst") is not None else card.get("catalyst")),
        "counterevidence": value_text(entry.get("counterevidence") if entry.get("counterevidence") is not None else card.get("counterevidence")),
        "invalidation": value_text(entry.get("invalidation") if entry.get("invalidation") is not None else card.get("invalidation")),
        "evidence_level": value_text(entry.get("evidence_level") if entry.get("evidence_level") is not None else card.get("evidence_level")),
        "financial_bridge": value_text(entry.get("financial_bridge") if entry.get("financial_bridge") is not None else card.get("financial_bridge")),
        "consensus": value_text(entry.get("consensus") if entry.get("consensus") is not None else card.get("consensus")),
        "overnight_pending": value_text(entry.get("overnight_pending") if entry.get("overnight_pending") is not None else card.get("overnight_pending")),
        "source_metadata": (
            {"supply_card": _v4_global(_v4_scope, 'deepcopy')(_v4_global(_v4_scope, 'dict')(card))}
            if supply_source
            else _v4_global(_v4_scope, 'dict')(source)
        ),
        "source_status": status,
        "published_at": published_at,
        "published_at_aware": published_aware,
        "source_time": source_time,
        "acceptance": (
            _v4_global(_v4_scope, 'RESEARCH_SUPPLY_ACCEPTANCE')
            if supply_source
            else "EARLY_DRAFT_FROZEN_ONLY"
        ),
        "eligibility": eligibility_status,
        "pit_status": pit_status,
        "research_status": "RESEARCH_ONLY",
        "recommendation_status": "RESEARCH_ONLY",
        "route_status": candidate_routes,
        "gemini_status": gemini_status,
        "source_refs": [source_ref],
    }


def __selection_snapshot_body(_v4_scope, /, phase, value, *, candidate_ids):
    supplied_candidate_ids = (
        _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) and "candidate_ids" in value
    )
    base: dict[str, Any] = {
        "phase": phase,
        "status": "NOT_MATERIALIZED",
        "run_id": None,
        "event_at": None,
        "artifact_sha256": None,
        "candidate_ids": [],
        "changes": [],
        "freeze_run_id": None,
        "freeze_snapshot_sha256": None,
        "snapshot_sha256": None,
    }
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        base.update(_v4_global(_v4_scope, 'dict')(value))
    base["phase"] = phase
    base["candidate_ids"] = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(base.get("candidate_ids") or []))
    base["changes"] = _v4_global(_v4_scope, 'list')(base.get("changes") or [])
    if base["status"] == "READY":
        if not supplied_candidate_ids:
            base["candidate_ids"] = _v4_global(_v4_scope, 'list')(candidate_ids)
        body = {key: item for key, item in base.items() if key != "snapshot_sha256"}
        calculated = _v4_global(_v4_scope, '_sha256')(body)
        if base.get("snapshot_sha256") is not None and base["snapshot_sha256"] != calculated:
            raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} snapshot SHA mismatch")
        base["snapshot_sha256"] = calculated
    else:
        base.update(
            {
                    "status": base["status"],
                    "run_id": None,
                    "event_at": None,
                    "artifact_sha256": None,
                    "candidate_ids": [],
                "changes": [],
                "freeze_run_id": None,
                "freeze_snapshot_sha256": None,
                "snapshot_sha256": None,
            }
        )
    return base
