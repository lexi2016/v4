"""domains.research_day_product: primitives (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __selection_value_text_body(_v4_scope, /, value):
    """Project optional supply values without losing deterministic encoding."""

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


def __published_timestamp_body(_v4_scope, /, value):
    """Parse the article publication timestamp without assuming a timezone."""

    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or not value:
        raise _v4_global(_v4_scope, 'ValueError')("missing published_at")
    try:
        parsed = _v4_global(_v4_scope, 'datetime').fromisoformat(value.replace("Z", "+00:00"))
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("invalid published_at") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _v4_global(_v4_scope, 'ValueError')("published_at must include timezone")
    return parsed.astimezone(_v4_global(_v4_scope, '_SHANGHAI'))


def __variant_body(_v4_scope, /, row):
    ignored = {
        "slot",
        "article_id",
        "dedupe_key",
        "source_dedup_keys",
        "duplicate_evidence_count",
        "published_at",
        "collected_at",
        "first_seen_at",
        "event_time",
        "source_published_at",
        "last_checked_at",
        "source_row_ref",
        "source_artifact_path",
        "source_artifact_sha256",
        "source_receipt_path",
        "source_receipt_sha256",
        "source_input_sha256",
        "identity_status",
    }
    return {_v4_global(_v4_scope, 'str')(key): value for key, value in row.items() if key not in ignored}


def _selection_candidate_id_body(_v4_scope, /, market, normalized_code, entity_id):
    """Build the only selection identity; event linkage stays separate."""

    values = [
        _v4_global(_v4_scope, 'unicodedata').normalize("NFKC", _v4_global(_v4_scope, 'str')(value or "").strip())
        for value in (market, normalized_code, entity_id)
    ]
    if _v4_global(_v4_scope, 'any')(not value for value in values):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate identity is incomplete")
    if _v4_global(_v4_scope, 'any')("|" in value for value in values[:2]):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate identity contains a separator")
    return f"{values[0].upper()}.{values[1].upper()}|{values[2]}"


def __selection_aware_hkt_body(_v4_scope, /, value):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith(" HKT"):
        try:
            parsed = _v4_global(_v4_scope, 'datetime').strptime(raw[:-4], "%Y-%m-%d %H:%M")
        except _v4_global(_v4_scope, 'ValueError'):
            return None
        return parsed.replace(tzinfo=_v4_global(_v4_scope, '_SHANGHAI')).isoformat()
    try:
        parsed = _v4_global(_v4_scope, 'datetime').fromisoformat(raw.replace("Z", "+00:00"))
    except _v4_global(_v4_scope, 'ValueError'):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(_v4_global(_v4_scope, '_SHANGHAI')).isoformat()
