"""ops.us_market_digest: capture_merge (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __ordered_union_body(_v4_scope, /, *values):
    result: list[str] = []
    seen: set[str] = _v4_global(_v4_scope, 'set')()
    for value in values:
        if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')):
            items = [value]
        elif _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Sequence')) and not _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'bytes'), _v4_global(_v4_scope, 'bytearray'))):
            items = value
        else:
            items = []
        for item in items:
            normalized = _v4_global(_v4_scope, 'str')(item).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
    return result


def __merge_rows_body(_v4_scope, /, existing_rows, incoming_rows):
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for source_row in [*existing_rows, *incoming_rows]:
        row = _v4_global(_v4_scope, 'dict')(source_row)
        key = _v4_global(_v4_scope, '_row_key')(row)
        if not key[0]:
            continue
        previous = merged.get(key)
        if previous is None:
            merged[key] = row
            continue
        winner = row if _v4_global(_v4_scope, 'int')(row.get("score") or 0) > _v4_global(_v4_scope, 'int')(previous.get("score") or 0) else previous
        winner["market_scopes"] = _v4_global(_v4_scope, '_ordered_union')(
            previous.get("market_scopes"), row.get("market_scopes")
        )
        winner["subscription_ids"] = _v4_global(_v4_scope, '_ordered_union')(
            previous.get("subscription_ids") or previous.get("subscription_id"),
            row.get("subscription_ids") or row.get("subscription_id"),
        )
        winner["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
            _v4_global(_v4_scope, 'set')(previous.get("cannot_confirm") or [])
            | _v4_global(_v4_scope, 'set')(row.get("cannot_confirm") or [])
        )
        winner["capture_phases"] = _v4_global(_v4_scope, 'sorted')(
            _v4_global(_v4_scope, 'set')(previous.get("capture_phases") or [])
            | _v4_global(_v4_scope, 'set')(row.get("capture_phases") or [])
            | ({_v4_global(_v4_scope, 'clean_text')(previous.get("capture_phase"))} if _v4_global(_v4_scope, 'clean_text')(previous.get("capture_phase")) else _v4_global(_v4_scope, 'set')())
            | ({_v4_global(_v4_scope, 'clean_text')(row.get("capture_phase"))} if _v4_global(_v4_scope, 'clean_text')(row.get("capture_phase")) else _v4_global(_v4_scope, 'set')())
        )
        winner["capture_ids"] = _v4_global(_v4_scope, '_ordered_union')(
            previous.get("capture_ids"),
            row.get("capture_ids"),
            previous.get("capture_id"),
            row.get("capture_id"),
        )
        merged[key] = winner
    return _v4_global(_v4_scope, 'sorted')(
        merged.values(),
        key=lambda row: (
            _v4_global(_v4_scope, 'int')(row.get("score") or 0),
            _v4_global(_v4_scope, 'clean_text')(row.get("published_at") or row.get("fetched_at")),
            _v4_global(_v4_scope, 'clean_text')(row.get("capture_phase")),
            _v4_global(_v4_scope, 'clean_text')(row.get("id")),
        ),
        reverse=True,
    )


def __merge_captures_body(_v4_scope, /, existing, incoming):
    by_id: dict[str, dict[str, Any]] = {}
    for source_capture in [*existing, *incoming]:
        row = _v4_global(_v4_scope, 'dict')(source_capture)
        capture_id = _v4_global(_v4_scope, 'clean_text')(row.get("capture_id"))
        if not capture_id:
            continue
        prior = by_id.get(capture_id)
        if prior is not None and prior != row:
            # A retry with one capture_id is one identity; retain the latest
            # deterministic payload only when its fetch timestamp is newer.
            prior = prior if _v4_global(_v4_scope, 'clean_text')(prior.get("captured_at")) >= _v4_global(_v4_scope, 'clean_text')(row.get("captured_at")) else row
        by_id[capture_id] = prior or row
    return _v4_global(_v4_scope, 'sorted')(
        by_id.values(),
        key=lambda row: (
            _v4_global(_v4_scope, 'clean_text')(row.get("us_session_date")),
            _v4_global(_v4_scope, 'clean_text')(row.get("capture_phase")),
            _v4_global(_v4_scope, 'clean_text')(row.get("capture_id")),
        ),
    )


def __merge_receipts_body(_v4_scope, /, existing, incoming):
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for source_receipt in [*existing, *incoming]:
        row = _v4_global(_v4_scope, 'dict')(source_receipt)
        key = (
            _v4_global(_v4_scope, 'clean_text')(row.get("capture_id")),
            _v4_global(_v4_scope, 'clean_text')(row.get("feed_id")),
            _v4_global(_v4_scope, 'clean_text')(row.get("url")),
        )
        if key not in merged:
            merged[key] = row
    return _v4_global(_v4_scope, 'sorted')(merged.values(), key=lambda row: (_v4_global(_v4_scope, 'str')(row.get("capture_id") or ""), _v4_global(_v4_scope, 'str')(row.get("feed_id") or ""), _v4_global(_v4_scope, 'str')(row.get("url") or "")))
