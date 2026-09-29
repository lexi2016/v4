"""ops.us_market_digest: snapshot_merge (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __merge_market_snapshots_body(_v4_scope, /, existing, incoming):
    """Keep the newest scheduled quote snapshot in one exact-date artifact."""
    if existing is None and incoming is None:
        return None
    if existing is None:
        return _v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'dict')(incoming)) if incoming is not None else None
    if incoming is None:
        return _v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'dict')(existing))
    existing_time = _v4_global(_v4_scope, '_snapshot_timestamp')(existing)
    incoming_time = _v4_global(_v4_scope, '_snapshot_timestamp')(incoming)
    existing_valid = existing.get("status") in {"READY", "PARTIAL"}
    incoming_valid = incoming.get("status") in {"READY", "PARTIAL"}
    if existing_valid != incoming_valid:
        winner = existing if existing_valid else incoming
    elif existing_time is None and incoming_time is None:
        winner = incoming
    elif existing_time is None:
        winner = incoming
    elif incoming_time is None:
        winner = existing
    else:
        winner = incoming if incoming_time >= existing_time else existing
    merged = _v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'dict')(winner))
    # The two scheduled phases may have different provider identities.  Keep
    # every observed session value visible instead of inventing a unified date.
    for field in ("provider_session_dates", "provider_session_times"):
        merged[field] = _v4_global(_v4_scope, 'sorted')(
            {
                _v4_global(_v4_scope, 'str')(value)
                for source in (existing, incoming)
                for value in (source.get(field) or [])
                if _v4_global(_v4_scope, 'str')(value).strip()
            }
        )
    mixed_reasons: set[str] = _v4_global(_v4_scope, 'set')()
    if _v4_global(_v4_scope, 'len')(merged.get("provider_session_dates") or []) > 1:
        mixed_reasons.add("QUOTE_SESSION_DATE_MIXED")
    if _v4_global(_v4_scope, 'len')(merged.get("provider_session_times") or []) > 1:
        mixed_reasons.add("QUOTE_SESSION_TIME_MIXED")
    if mixed_reasons:
        merged["status"] = "PARTIAL"
        merged["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
            _v4_global(_v4_scope, 'set')(merged["cannot_confirm"]) | mixed_reasons
        )
    return merged
