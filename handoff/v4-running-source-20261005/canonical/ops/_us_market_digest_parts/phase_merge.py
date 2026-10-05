"""ops.us_market_digest: phase_merge (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _merge_us_phase_payloads_body(_v4_scope, /, existing, incoming, *, preserve_existing_market_snapshot=False):
    """Merge a new phase into one exact-date external-finance artifact."""
    existing_date, existing_source = _v4_global(_v4_scope, 'validate_research_peripheral')(existing)
    incoming_date, incoming_source = _v4_global(_v4_scope, 'validate_research_peripheral')(incoming)
    if (existing_date, existing_source) != (incoming_date, incoming_source):
        raise _v4_global(_v4_scope, 'ValueError')("US phase payload identity mismatch")
    if existing_source != "external_finance":
        raise _v4_global(_v4_scope, 'ValueError')("US phase merge requires external_finance")
    merged = _v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'dict')(existing))
    details = _v4_global(_v4_scope, '_merge_rows')(existing.get("details") or [], incoming.get("details") or [])
    merged["details"] = details
    merged["overview"] = _v4_global(_v4_scope, 'overview_from_details')(details)
    merged["items"] = []
    merged["item_count"] = _v4_global(_v4_scope, 'len')(details)
    merged["fetched_at"] = _v4_global(_v4_scope, 'max')(
        _v4_global(_v4_scope, 'clean_text')(existing.get("fetched_at")), _v4_global(_v4_scope, 'clean_text')(incoming.get("fetched_at"))
    )
    merged["source_url"] = _v4_global(_v4_scope, 'clean_text')(incoming.get("source_url") or existing.get("source_url"))
    merged["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
        _v4_global(_v4_scope, 'set')(existing.get("cannot_confirm") or []) | _v4_global(_v4_scope, 'set')(incoming.get("cannot_confirm") or [])
    )
    captures = _v4_global(_v4_scope, '_merge_captures')(
        existing.get("us_session_captures") or [],
        incoming.get("us_session_captures") or [],
    )
    merged["us_session_captures"] = captures
    existing_captures = existing.get("us_session_captures") or []
    incoming_captures = incoming.get("us_session_captures") or []
    capture_counts = [
        row.get("raw_item_count")
        for row in captures
        if _v4_global(_v4_scope, 'type')(row.get("raw_item_count")) is _v4_global(_v4_scope, 'int') and row.get("raw_item_count") >= 0
    ]
    if not existing_captures:
        # The first US capture may follow a regular external-finance refresh
        # that predates capture identity.  Preserve that source count while
        # adding the new capture count; otherwise details can outnumber raw
        # rows and the exact-date store correctly rejects the merge.
        merged["raw_item_count"] = _v4_global(_v4_scope, 'int')(existing.get("raw_item_count") or 0) + _v4_global(_v4_scope, 'int')(
            incoming.get("raw_item_count") or 0
        )
    elif _v4_global(_v4_scope, 'len')(capture_counts) == _v4_global(_v4_scope, 'len')(captures):
        # Capture IDs are the idempotency boundary.  A retry of one phase
        # must not inflate the aggregate raw count.
        merged["raw_item_count"] = _v4_global(_v4_scope, 'sum')(capture_counts)
    elif not incoming_captures:
        merged["raw_item_count"] = _v4_global(_v4_scope, 'int')(existing.get("raw_item_count") or 0) + _v4_global(_v4_scope, 'int')(
            incoming.get("raw_item_count") or 0
        )
    else:
        merged["raw_item_count"] = _v4_global(_v4_scope, 'int')(existing.get("raw_item_count") or 0) + _v4_global(_v4_scope, 'int')(incoming.get("raw_item_count") or 0)
    origins = {_v4_global(_v4_scope, 'str')(row.get("capture_origin")) for row in captures}
    merged["capture_origin"] = _v4_global(_v4_scope, 'next')(_v4_global(_v4_scope, 'iter')(origins)) if _v4_global(_v4_scope, 'len')(origins) == 1 else _v4_global(_v4_scope, 'MIXED_CAPTURE')
    merged["original_time_capture"] = _v4_global(_v4_scope, 'bool')(captures) and _v4_global(_v4_scope, 'all')(
        row.get("original_time_capture") is True for row in captures
    )
    late_captures = [row for row in captures if row.get("late") is True]
    if late_captures:
        latest_late = _v4_global(_v4_scope, 'max')(
            late_captures,
            key=lambda row: _v4_global(_v4_scope, 'clean_text')(row.get("captured_at")),
        )
        merged.update(
            {
                "capture_mode": _v4_global(_v4_scope, 'str')(latest_late.get("capture_mode") or _v4_global(_v4_scope, 'LATE_POST_CLOSE_CAPTURE_MODE')),
                "reason": _v4_global(_v4_scope, 'str')(latest_late.get("reason") or _v4_global(_v4_scope, 'LATE_POST_CLOSE_CAPTURE_REASON')),
                "capture_reason": _v4_global(_v4_scope, 'str')(latest_late.get("capture_reason") or latest_late.get("reason") or _v4_global(_v4_scope, 'LATE_POST_CLOSE_CAPTURE_REASON')),
                "late": latest_late.get("late") is True,
                **{
                    field: latest_late[field]
                    for field in (
                        "natural_capture_window_start",
                        "natural_capture_window_end",
                        "allowed_recovery_window_start",
                        "allowed_recovery_window_end",
                    )
                    if field in latest_late
                },
            }
        )
    merged["feed_receipts"] = _v4_global(_v4_scope, '_merge_receipts')(
        existing.get("feed_receipts") or [], incoming.get("feed_receipts") or []
    )
    prior_snapshot = existing.get("market_snapshot")
    if preserve_existing_market_snapshot and not _v4_global(_v4_scope, 'isinstance')(prior_snapshot, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("US_RSS_ONLY_RECOVERY_REQUIRES_EXISTING_MARKET_SNAPSHOT")
    merged_snapshot = (
        _v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'dict')(prior_snapshot))
        if preserve_existing_market_snapshot
        else _v4_global(_v4_scope, '_merge_market_snapshots')(
            prior_snapshot, incoming.get("market_snapshot")
        )
    )
    if merged_snapshot is not None:
        merged["market_snapshot"] = merged_snapshot
        merged["market_snapshot_status"] = _v4_global(_v4_scope, 'str')(
            merged_snapshot.get("status") or "CANNOT_CONFIRM"
        )
        merged["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
            _v4_global(_v4_scope, 'set')(merged.get("cannot_confirm") or [])
            | _v4_global(_v4_scope, 'set')(merged_snapshot.get("cannot_confirm") or [])
        )
    if details:
        merged["status"] = (
            "CANNOT_CONFIRM"
            if "ZH_TRANSLATION_INCOMPLETE" in merged["cannot_confirm"]
            else "READY"
        )
    else:
        merged["status"] = "CANNOT_CONFIRM" if merged["cannot_confirm"] else "READY_EMPTY"
    # A close quote failure is a failure of this product's capture even when
    # the companion news rows were fetched successfully.  A PRE_OPEN-only
    # artifact keeps its news status while exposing the not-due snapshot.
    post_close_capture = _v4_global(_v4_scope, 'any')(
        row.get("capture_phase") == "POST_CLOSE"
        for row in captures
        if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
    )
    if post_close_capture and merged.get("market_snapshot_status") != "READY":
        merged["status"] = "CANNOT_CONFIRM"
        merged["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
            _v4_global(_v4_scope, 'set')(merged.get("cannot_confirm") or [])
            | {"MARKET_SNAPSHOT_CANNOT_CONFIRM"}
        )
    _v4_global(_v4_scope, 'validate_research_peripheral')(merged)
    return merged
