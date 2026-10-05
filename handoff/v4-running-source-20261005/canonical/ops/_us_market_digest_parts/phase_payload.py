"""ops.us_market_digest: phase_payload (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __annotate_payload_body(_v4_scope, /, payload, metadata):
    annotated = _v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'dict')(payload))
    origin = _v4_global(_v4_scope, 'str')(metadata["capture_origin"])
    original = _v4_global(_v4_scope, 'bool')(metadata["original_time_capture"])
    row_fields = {
        key: metadata[key]
        for key in (
            "us_session_date",
            "capture_phase",
            "session_timezone",
            "capture_window_start",
            "capture_window_end",
            "capture_id",
            "run_id",
            "capture_origin",
            "original_time_capture",
        )
    }
    for key in (
        "capture_mode",
        "reason",
        "capture_reason",
        "late",
        "natural_capture_window_start",
        "natural_capture_window_end",
        "allowed_recovery_window_start",
        "allowed_recovery_window_end",
    ):
        if key in metadata:
            row_fields[key] = metadata[key]
    for field in ("details", "overview"):
        rows = []
        for source_row in annotated.get(field) or []:
            row = _v4_global(_v4_scope, 'dict')(source_row)
            row.update(row_fields)
            row["first_seen_at"] = _v4_global(_v4_scope, 'str')(row.get("first_seen_at") or annotated["fetched_at"])
            row["capture_ids"] = _v4_global(_v4_scope, '_ordered_union')(
                row.get("capture_ids"), metadata["capture_id"]
            )
            phases = _v4_global(_v4_scope, 'set')(row.get("capture_phases") or [])
            phases.add(_v4_global(_v4_scope, 'str')(metadata["capture_phase"]))
            row["capture_phases"] = _v4_global(_v4_scope, 'sorted')(phases)
            rows.append(row)
        annotated[field] = rows
    receipts = []
    for source_receipt in annotated.get("feed_receipts") or []:
        receipt = _v4_global(_v4_scope, 'dict')(source_receipt)
        receipt.update(
            {
                "us_session_date": metadata["us_session_date"],
                "capture_phase": metadata["capture_phase"],
                "capture_id": metadata["capture_id"],
                "run_id": metadata["run_id"],
                "capture_origin": origin,
                "original_time_capture": original,
            }
        )
        for key in (
            "capture_mode",
            "reason",
            "capture_reason",
            "late",
            "natural_capture_window_start",
            "natural_capture_window_end",
            "allowed_recovery_window_start",
            "allowed_recovery_window_end",
        ):
            if key in metadata:
                receipt[key] = metadata[key]
        receipts.append(receipt)
    if "feed_receipts" in annotated:
        annotated["feed_receipts"] = _v4_global(_v4_scope, 'sorted')(
            receipts,
            key=lambda row: (
                _v4_global(_v4_scope, 'clean_text')(row.get("capture_id")),
                _v4_global(_v4_scope, 'clean_text')(row.get("feed_id")),
                _v4_global(_v4_scope, 'clean_text')(row.get("url")),
            ),
        )
    annotated["us_session_captures"] = [
        {
            **_v4_global(_v4_scope, 'dict')(metadata),
            "raw_item_count": _v4_global(_v4_scope, 'int')(annotated["raw_item_count"]),
            "item_count": _v4_global(_v4_scope, 'int')(annotated["item_count"]),
        }
    ]
    cannot_confirm = _v4_global(_v4_scope, 'set')(annotated.get("cannot_confirm") or [])
    if origin == _v4_global(_v4_scope, 'HISTORICAL_BACKFILL'):
        # A date-bounded Google RSS query is a reproducible discovery slice,
        # not a completeness guarantee for the historical session.
        cannot_confirm.add("HISTORICAL_BACKFILL_COVERAGE_UNCONFIRMED")
    else:
        market_day = _v4_global(_v4_scope, 'us_market_day_certification')(_v4_global(_v4_scope, 'str')(metadata["us_session_date"]))
        if market_day["status"] != "VERIFIED":
            cannot_confirm.add(market_day["reason"])
            annotated["status"] = "CANNOT_CONFIRM"
    annotated["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(cannot_confirm)
    annotated["capture_origin"] = origin
    annotated["original_time_capture"] = original
    for key in (
        "capture_mode",
        "reason",
        "capture_reason",
        "late",
        "natural_capture_window_start",
        "natural_capture_window_end",
        "allowed_recovery_window_start",
        "allowed_recovery_window_end",
    ):
        if key in metadata:
            annotated[key] = metadata[key]
    return annotated


def _build_us_market_phase_payload_body(_v4_scope, /, trade_date, *, capture_phase, us_session_date, fetched_at, capture_id, run_id, fetch_rss, fetch_quotes, fetch_quote, transport, translate_text, resolve_original_url, allow_late_post_close, rss_only_recovery, now, **kwargs):
    """Fetch and label one explicit US pre-open or post-close capture."""
    phase = _v4_global(_v4_scope, '_phase')(capture_phase)
    if phase == _v4_global(_v4_scope, 'HISTORICAL_BACKFILL_PHASE'):
        raise _v4_global(_v4_scope, 'ValueError')("use build_us_historical_backfill_payload for historical data")
    if resolve_original_url is not None:
        raise _v4_global(_v4_scope, 'ValueError')("US RSS lane does not fetch publisher bodies")
    if _v4_global(_v4_scope, 'type')(allow_late_post_close) is not _v4_global(_v4_scope, 'bool'):
        raise _v4_global(_v4_scope, 'ValueError')("allow_late_post_close must be boolean")
    if _v4_global(_v4_scope, 'type')(rss_only_recovery) is not _v4_global(_v4_scope, 'bool'):
        raise _v4_global(_v4_scope, 'ValueError')("rss_only_recovery must be boolean")
    if allow_late_post_close and phase != "POST_CLOSE":
        raise _v4_global(_v4_scope, 'ValueError')("US_LATE_POST_CLOSE_ONLY")
    if rss_only_recovery and not allow_late_post_close:
        raise _v4_global(_v4_scope, 'ValueError')("US_RSS_ONLY_RECOVERY_REQUIRES_LATE_POST_CLOSE")
    if allow_late_post_close:
        clock_now = _v4_global(_v4_scope, '_capture_now')(now)
        metadata_now: datetime | None = clock_now
        session_date = _v4_global(_v4_scope, '_date')(us_session_date or trade_date)
        effective_fetched_at: datetime | str = (
            clock_now if fetched_at is None else fetched_at
        )
        # Validate before any RSS or quote request.  The late flag is a
        # controlled recovery acknowledgement, not permission to backdate.
        _v4_global(_v4_scope, '_validate_late_post_close_context')(
            session_date,
            captured_at=effective_fetched_at,
            now=clock_now,
        )
    else:
        metadata_now = None
        session_date = _v4_global(_v4_scope, '_date')(us_session_date or trade_date)
        # Validate the natural window before touching either network seam.
        # When no timestamp is supplied, take one real instant and pass it
        # through so metadata and source rows share the same actual capture.
        effective_fetched_at = (
            _v4_global(_v4_scope, 'datetime').now(_v4_global(_v4_scope, 'US_TZ')).replace(microsecond=0)
            if fetched_at is None
            else fetched_at
        )
        _v4_global(_v4_scope, 'build_capture_metadata')(
            session_date,
            phase,
            captured_at=effective_fetched_at,
            capture_origin=_v4_global(_v4_scope, 'ORIGINAL_TIME_CAPTURE'),
            original_time_capture=True,
        )
    payload = _v4_global(_v4_scope, 'build_external_finance_payload')(
        trade_date,
        fetched_at=effective_fetched_at,
        fetch_rss=fetch_rss,
        subscriptions=_v4_global(_v4_scope, '_us_subscriptions')(),
        translate_text=translate_text,
        resolve_original_url=resolve_original_url,
        transport=transport,
        **kwargs,
    )
    # Existing unit-test fetch seams are intentionally reused for quote
    # requests when supplied.  The scheduled CLI leaves both seams unset and
    # therefore uses the same proxy-aware transport as the RSS producer.
    quote_fetcher = fetch_quotes or fetch_quote
    if quote_fetcher is None and fetch_rss is not None:
        quote_fetcher = fetch_rss
    recovery_origin = (
        _v4_global(_v4_scope, 'MANUAL_RECOVERY')
        if rss_only_recovery
        else _v4_global(_v4_scope, 'ORIGINAL_TIME_CAPTURE')
    )
    recovery_is_original = not rss_only_recovery
    metadata = _v4_global(_v4_scope, 'build_capture_metadata')(
        session_date,
        phase,
        captured_at=payload["fetched_at"],
        capture_id=capture_id,
        run_id=run_id,
        capture_origin=recovery_origin,
        original_time_capture=recovery_is_original,
        allow_late_post_close=allow_late_post_close,
        now=metadata_now,
    )
    if phase == "POST_CLOSE" and not rss_only_recovery:
        market_snapshot = _v4_global(_v4_scope, 'build_us_market_snapshot')(
            session_date,
            capture_phase=phase,
            captured_at=payload["fetched_at"],
            fetch_quotes=quote_fetcher,
            transport=transport,
            timeout=_v4_global(_v4_scope, 'int')(kwargs.get("timeout", 20)),
        )
    elif phase == "POST_CLOSE":
        market_snapshot = _v4_global(_v4_scope, '_empty_market_snapshot')(
            session_date,
            capture_phase=phase,
            captured_at=payload["fetched_at"],
            reasons=["US_MARKET_QUOTE_CAPTURE_NOT_REQUESTED_RSS_ONLY_RECOVERY"],
        )
    else:
        # The existing workload may still capture a pre-open news digest, but
        # the product contract is close-only.  Keep a complete 24-row status
        # surface without making an unnecessary quote request.
        market_snapshot = _v4_global(_v4_scope, '_empty_market_snapshot')(
            session_date,
            capture_phase=phase,
            captured_at=payload["fetched_at"],
            reasons=["MARKET_SNAPSHOT_NOT_DUE_PRE_OPEN"],
        )
    for key in (
        "capture_mode",
        "reason",
        "capture_reason",
        "late",
        "natural_capture_window_start",
        "natural_capture_window_end",
        "allowed_recovery_window_start",
        "allowed_recovery_window_end",
    ):
        if key in metadata:
            market_snapshot[key] = metadata[key]
    annotated = _v4_global(_v4_scope, '_annotate_payload')(
        payload,
        metadata,
    )
    capture_record = annotated["us_session_captures"][0]
    capture_record["rss_status"] = _v4_global(_v4_scope, 'str')(payload.get("status") or "CANNOT_CONFIRM")
    capture_record["rss_item_count"] = _v4_global(_v4_scope, 'int')(payload.get("item_count") or 0)
    capture_record["rss_raw_item_count"] = _v4_global(_v4_scope, 'int')(payload.get("raw_item_count") or 0)
    if rss_only_recovery:
        capture_record["quote_capture_status"] = "NOT_ATTEMPTED"
        capture_record["quote_capture_reason"] = "RSS_ONLY_RECOVERY"
    elif phase == "PRE_OPEN":
        capture_record["quote_capture_status"] = "NOT_DUE"
        capture_record["quote_capture_reason"] = "PRE_OPEN_HAS_NO_CLOSE_QUOTE_CAPTURE"
    else:
        capture_record["quote_capture_status"] = "ATTEMPTED"
    annotated["market_snapshot"] = market_snapshot
    annotated["market_snapshot_status"] = _v4_global(_v4_scope, 'str')(
        market_snapshot.get("status") or "CANNOT_CONFIRM"
    )
    annotated["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
        _v4_global(_v4_scope, 'set')(annotated.get("cannot_confirm") or [])
        | _v4_global(_v4_scope, 'set')(market_snapshot.get("cannot_confirm") or [])
    )
    if phase == "POST_CLOSE" and annotated["market_snapshot_status"] != "READY":
        annotated["status"] = "CANNOT_CONFIRM"
        annotated["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
            _v4_global(_v4_scope, 'set')(annotated["cannot_confirm"]) | {"MARKET_SNAPSHOT_CANNOT_CONFIRM"}
        )
    return annotated
