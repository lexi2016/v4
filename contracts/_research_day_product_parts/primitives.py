"""contracts.research_day_product: primitives (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __pair_identity_body(_v4_scope, /, row):
    """Match the producer's exact URL+stock identity without guessing missing data."""

    url = _v4_global(_v4_scope, 'unicodedata').normalize(
        "NFKC", _v4_global(_v4_scope, 'str')(row.get("url") or row.get("source_url") or "").strip()
    )
    stock_code = _v4_global(_v4_scope, 'unicodedata').normalize(
        "NFKC", _v4_global(_v4_scope, 'str')(row.get("stock_code") or row.get("code") or "").strip()
    ).upper()
    if not url or not stock_code:
        return None
    return f"{url}|{stock_code}"


def __selection_timestamp_body(_v4_scope, /, value, field, *, nullable):
    if nullable and value is None:
        return None
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or not value:
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid selection {field}")
    try:
        parsed = _v4_global(_v4_scope, 'datetime').fromisoformat(value.replace("Z", "+00:00"))
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid selection {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _v4_global(_v4_scope, 'ValueError')(f"selection {field} must include timezone")
    return value


def __selection_parsed_timestamp_body(_v4_scope, /, value, field):
    """Parse a required timestamp after enforcing an explicit timezone."""

    text = _v4_global(_v4_scope, '_selection_timestamp')(value, field)
    assert text is not None
    try:
        parsed = _v4_global(_v4_scope, 'datetime').fromisoformat(text.replace("Z", "+00:00"))
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid selection {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _v4_global(_v4_scope, 'ValueError')(f"selection {field} must include timezone")
    return parsed


def __validate_selection_source_ref_body(_v4_scope, /, value, *, source_date):
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) and value.get("type") == _v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE'):
        required = {
            "type",
            "path",
            "raw_sha256",
            "frozen_payload_sha256",
            "json_pointer",
            "source_date",
            "source_time",
            "supply_receipt_path",
            "supply_receipt_sha256",
        }
        if _v4_global(_v4_scope, 'set')(value) != required:
            raise _v4_global(_v4_scope, 'ValueError')("invalid research supply source reference")
        if not _v4_global(_v4_scope, 'isinstance')(value.get("path"), _v4_global(_v4_scope, 'str')) or not value["path"]:
            raise _v4_global(_v4_scope, 'ValueError')("research supply source path is missing")
        if not _v4_global(_v4_scope, 'isinstance')(value.get("supply_receipt_path"), _v4_global(_v4_scope, 'str')) or not value["supply_receipt_path"]:
            raise _v4_global(_v4_scope, 'ValueError')("research supply receipt path is missing")
        _v4_global(_v4_scope, '_selection_sha')(value.get("raw_sha256"), "supply source raw SHA")
        _v4_global(_v4_scope, '_selection_sha')(value.get("frozen_payload_sha256"), "supply source frozen SHA")
        _v4_global(_v4_scope, '_selection_sha')(value.get("supply_receipt_sha256"), "supply receipt SHA")
        pointer = value.get("json_pointer")
        if not _v4_global(_v4_scope, 'isinstance')(pointer, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, 're').fullmatch(
            r"/frozen_payload/event_cards/(?:0|[1-9][0-9]*)", pointer
        ):
            raise _v4_global(_v4_scope, 'ValueError')("research supply source JSON pointer is missing")
        if value.get("source_date") != source_date:
            raise _v4_global(_v4_scope, 'ValueError')("research supply source date mismatch")
        _v4_global(_v4_scope, '_selection_timestamp')(value.get("source_time"), "research supply source_time")
        return
    required = {
        "type",
        "path",
        "raw_sha256",
        "frozen_payload_sha256",
        "json_pointer",
        "source_date",
        "source_time",
    }
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or not required.issubset(value):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection source reference")
    if value.get("type") != "EARLY_DRAFT_FROZEN_ENVELOPE":
        raise _v4_global(_v4_scope, 'ValueError')("selection source reference type is not frozen envelope")
    if not _v4_global(_v4_scope, 'isinstance')(value.get("path"), _v4_global(_v4_scope, 'str')) or not value["path"]:
        raise _v4_global(_v4_scope, 'ValueError')("selection source reference path is missing")
    _v4_global(_v4_scope, '_selection_sha')(value.get("raw_sha256"), "source raw SHA")
    _v4_global(_v4_scope, '_selection_sha')(value.get("frozen_payload_sha256"), "source frozen SHA")
    pointer = value.get("json_pointer")
    if not _v4_global(_v4_scope, 'isinstance')(pointer, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, 're').fullmatch(
        r"/frozen_payload/event_cards/(?:0|[1-9][0-9]*)", pointer
    ):
        raise _v4_global(_v4_scope, 'ValueError')("selection source JSON pointer is missing")
    if value.get("source_date") != source_date:
        raise _v4_global(_v4_scope, 'ValueError')("selection source date mismatch")
    _v4_global(_v4_scope, '_selection_timestamp')(value.get("source_time"), "source_time")
