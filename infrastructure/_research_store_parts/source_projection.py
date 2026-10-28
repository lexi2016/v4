"""infrastructure.research_store: source_projection (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchSelectionStore__verify_candidate_source_projection_body(_v4_scope, /, cls, candidate, ref, verified, *, source_date, target_trade_date, cutoff_at):
    card = verified.get("card")
    if not _v4_global(_v4_scope, 'isinstance')(card, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source card is missing")
    document = verified.get("document")
    if not _v4_global(_v4_scope, 'isinstance')(document, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source envelope is missing")
    if ref.get("source_date") != source_date:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source date binding mismatch")
    if ref.get("type") == _v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE'):
        _b04_verify_supply_candidate_projection(_v4_scope, cls, candidate, ref, verified, card, document, target_trade_date, cutoff_at)
        return
    _b04_verify_event_candidate_projection(_v4_scope, cls, candidate, ref, card, document, target_trade_date)

def _b04_verify_supply_candidate_projection(_v4_scope, cls, candidate, ref, verified, card, document, target_trade_date, cutoff_at):
    if document.get("target_trade_date") != target_trade_date:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate target date mismatch")

    frozen_payload = document.get("frozen_payload")

    if not _v4_global(_v4_scope, 'isinstance')(frozen_payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("research supply frozen payload is missing")

    ticker = cls._selection_identity_text(card.get("ticker"))

    if not _v4_global(_v4_scope, 're').fullmatch(r"\d{5}\.HK", ticker):
        raise _v4_global(_v4_scope, 'ValueError')("research supply card ticker is invalid")

    event_id = cls._selection_identity_text(card.get("event_id"))

    if event_id != candidate.get("event_id"):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source identity mismatch")

    candidate_entity = cls._selection_identity_text(candidate.get("entity_id"))

    if candidate_entity != ticker:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source entity mismatch")

    code, market = ticker.rsplit(".", 1)

    expected_candidate_id = f"{market}.{code}|{ticker}"

    if candidate.get("candidate_id") != expected_candidate_id:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate identity mismatch")

    if candidate.get("market") != market or candidate.get("normalized_code") != code:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate normalized identity mismatch")

    if candidate.get("event_stock_link_id") != f"{event_id}|{expected_candidate_id}":
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate event link mismatch")

    def supply_text(value: Any) -> str:
        if value is None:
            return ""
        if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')):
            return value.strip()
        if _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'Mapping'), _v4_global(_v4_scope, 'list'))):
            return _v4_global(_v4_scope, 'json').dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        return _v4_global(_v4_scope, 'str')(value).strip()

    for field in (
        "bucket",
        "catalyst",
        "counterevidence",
        "invalidation",
        "evidence_level",
        "financial_bridge",
        "consensus",
        "overnight_pending",
    ):
        if candidate.get(field) != supply_text(card.get(field)):
            raise _v4_global(_v4_scope, 'ValueError')(f"selection candidate source {field} mismatch")

    if candidate.get("source_metadata") != {"supply_card": _v4_global(_v4_scope, 'dict')(card)}:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source metadata mismatch")

    route_status = frozen_payload.get("route_status")

    if not _v4_global(_v4_scope, 'isinstance')(route_status, _v4_global(_v4_scope, 'Mapping')) or candidate.get("route_status") != {
        "R1": route_status.get("R1"),
        "R6": route_status.get("R6"),
    }:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate route status mismatch")

    official = card.get("official_source")

    if not _v4_global(_v4_scope, 'isinstance')(official, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("research supply official source is missing")

    expected_status = cls._selection_identity_text(official.get("identity_status"))

    if not expected_status or expected_status.upper() in {
        "UNKNOWN",
        "UNVERIFIED",
        "CANNOT_CONFIRM",
        "NOT_MATERIALIZED",
    }:
        expected_status = "UNVERIFIED"

    if candidate.get("source_status") != expected_status:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source status mismatch")

    eligibility = card.get("eligibility_status")

    if _v4_global(_v4_scope, 'isinstance')(eligibility, _v4_global(_v4_scope, 'Mapping')):
        expected_eligibility = cls._selection_identity_text(eligibility.get("status"))
    elif _v4_global(_v4_scope, 'isinstance')(eligibility, _v4_global(_v4_scope, 'str')) and eligibility.strip():
        expected_eligibility = eligibility.strip()
    else:
        expected_eligibility = ""

    if expected_eligibility not in {"ELIGIBILITY_CANNOT_CONFIRM", "ELIGIBLE"}:
        expected_eligibility = "ELIGIBILITY_CANNOT_CONFIRM"

    if candidate.get("eligibility") != expected_eligibility:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source eligibility mismatch")

    published_value = card.get("published_at")

    if published_value is None:
        published_value = official.get("published_at")

    expected_published_at = supply_text(published_value)

    if candidate.get("published_at") != expected_published_at:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate published_at mismatch")

    expected_aware = _v4_global(_v4_scope, '_selection_aware_hkt')(expected_published_at)

    if candidate.get("published_at_aware") != expected_aware:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate published_at projection mismatch")

    if candidate.get("source_time") != ref.get("source_time"):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source_time mismatch")

    if cutoff_at is None:
        cutoff_at = _v4_global(_v4_scope, 'str')(document.get("cutoff_at") or "")

    try:
        cutoff = _v4_global(_v4_scope, 'datetime').fromisoformat(_v4_global(_v4_scope, 'str')(cutoff_at).replace("Z", "+00:00"))
        published = (
            _v4_global(_v4_scope, 'datetime').fromisoformat(expected_aware.replace("Z", "+00:00"))
            if expected_aware
            else None
        )
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate cutoff or published timestamp is invalid") from error

    expected_pit = (
        "CANNOT_CONFIRM"
        if cutoff.tzinfo is None or cutoff.utcoffset() is None or published is None
        else "READY"
        if published.astimezone(_v4_global(_v4_scope, '_SHANGHAI')) <= cutoff.astimezone(_v4_global(_v4_scope, '_SHANGHAI'))
        else "PIT_FAILED"
    )

    if candidate.get("pit_status") != expected_pit:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate PIT status mismatch")

    if candidate.get("acceptance") != "RESEARCH_SUPPLY_ONLY":
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate supply acceptance mismatch")

    return


def _b04_verify_event_candidate_projection(_v4_scope, cls, candidate, ref, card, document, target_trade_date):
    raw_target_date = document.get("target_trade_date")

    frozen_payload = document.get("frozen_payload")

    if raw_target_date is None and _v4_global(_v4_scope, 'isinstance')(frozen_payload, _v4_global(_v4_scope, 'Mapping')):
        raw_target_date = frozen_payload.get("target_trade_date")

    if _v4_global(_v4_scope, 'str')(raw_target_date) != target_trade_date:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate target date mismatch")

    event_id = cls._selection_identity_text(card.get("event_id"))

    if event_id != candidate.get("event_id"):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source identity mismatch")

    entities = card.get("entities")

    if not _v4_global(_v4_scope, 'isinstance')(entities, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(entities) != 1:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source entities are ambiguous")

    source_entity = cls._selection_identity_text(entities[0])

    candidate_entity = cls._selection_identity_text(candidate.get("entity_id"))

    if source_entity != candidate_entity:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source entity mismatch")

    if "." not in candidate_entity:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate entity identity is invalid")

    source_code, source_market = candidate_entity.rsplit(".", 1)

    if (
        source_code.strip().upper() != cls._selection_identity_text(candidate.get("normalized_code")).upper()
        or source_market.strip().upper() != cls._selection_identity_text(candidate.get("market")).upper()
    ):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate normalized identity mismatch")

    expected_candidate_id = (
        f"{cls._selection_identity_text(candidate.get('market')).upper()}."
        f"{cls._selection_identity_text(candidate.get('normalized_code')).upper()}|"
        f"{candidate_entity}"
    )

    if candidate.get("candidate_id") != expected_candidate_id:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate identity mismatch")

    if candidate.get("event_stock_link_id") != f"{event_id}|{expected_candidate_id}":
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate event link mismatch")

    source = card.get("source") if _v4_global(_v4_scope, 'isinstance')(card.get("source"), _v4_global(_v4_scope, 'Mapping')) else {}

    for field in (
        "bucket",
        "catalyst",
        "counterevidence",
        "invalidation",
        "evidence_level",
        "financial_bridge",
        "consensus",
        "overnight_pending",
    ):
        expected = cls._selection_identity_text(card.get(field))
        if candidate.get(field) != expected:
            raise _v4_global(_v4_scope, 'ValueError')(f"selection candidate source {field} mismatch")

    expected_metadata = _v4_global(_v4_scope, 'dict')(source)

    if candidate.get("source_metadata") != expected_metadata:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source metadata mismatch")

    expected_status = cls._selection_identity_text(source.get("status")) or "UNVERIFIED"

    if candidate.get("source_status") != expected_status:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source status mismatch")

    raw_eligibility = card.get("eligibility")

    if _v4_global(_v4_scope, 'isinstance')(raw_eligibility, _v4_global(_v4_scope, 'Mapping')):
        expected_eligibility = (
            cls._selection_identity_text(raw_eligibility.get("status"))
            or "ELIGIBILITY_CANNOT_CONFIRM"
        )
    elif _v4_global(_v4_scope, 'isinstance')(raw_eligibility, _v4_global(_v4_scope, 'str')) and raw_eligibility.strip():
        expected_eligibility = raw_eligibility.strip()
    else:
        expected_eligibility = "ELIGIBILITY_CANNOT_CONFIRM"

    if candidate.get("eligibility") != expected_eligibility:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source eligibility mismatch")

    expected_published_at = cls._selection_identity_text(source.get("published_at"))

    if candidate.get("published_at") != expected_published_at:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate published_at mismatch")

    if candidate.get("published_at_aware") != _v4_global(_v4_scope, '_selection_aware_hkt')(expected_published_at):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate published_at projection mismatch")

    if candidate.get("source_time") != ref.get("source_time"):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source_time mismatch")

    try:
        source_time = _v4_global(_v4_scope, 'datetime').fromisoformat(
            _v4_global(_v4_scope, 'str')(ref.get("source_time") or "").replace("Z", "+00:00")
        )
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source_time is invalid") from error

    if source_time.tzinfo is None or source_time.utcoffset() is None:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source_time must include timezone")

    for field in ("official_url", "published_at", "source_status"):
        if field in ref:
            expected = {
                "official_url": source.get("official_url", ""),
                "published_at": source.get("published_at", ""),
                "source_status": source.get("status", ""),
            }[field]
            if ref.get(field) != expected:
                raise _v4_global(_v4_scope, 'ValueError')(f"selection source {field} mismatch")
