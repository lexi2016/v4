"""ops.us_market_digest: phase_publication (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _materialize_us_market_phase_body(_v4_scope, /, *, data_root, trade_date, capture_phase, allow_late_post_close, rss_only_recovery, now, **kwargs):
    """One existing capture owner per exact artifact date, including retries.

    All fetch, merge and immutable evidence logic remains the reviewed
    producer below. The shared V4 lock only closes concurrent request reuse.
    """
    from infrastructure.interprocess_lock import owned_interprocess_lock

    if not _v4_global(_v4_scope, 'Path')(data_root).is_absolute():
        raise _v4_global(_v4_scope, 'ValueError')("US_OWNED_DATA_ROOT_MUST_BE_ABSOLUTE")
    date = _v4_global(_v4_scope, '_date')(trade_date)
    with owned_interprocess_lock(
        _v4_global(_v4_scope, 'Path')(data_root) / ".locks" / f"us-market-{date}.lock",
        timeout_seconds=300, timeout_message="US_CAPTURE_OWNER_BUSY",
    ):
        return _v4_global(_v4_scope, '_materialize_us_market_phase_locked')(
            data_root=data_root, trade_date=date, capture_phase=capture_phase,
            allow_late_post_close=allow_late_post_close,
            rss_only_recovery=rss_only_recovery, now=now, **kwargs,
        )


def _validate_rss_only_recovery_baseline(_v4_scope, /, payload, us_session_date):
    """Require an original mixed-time close artifact before RSS-only recovery."""
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("US_RSS_ONLY_RECOVERY_REQUIRES_EXISTING_ARTIFACT")
    snapshot = payload.get("market_snapshot")
    if not _v4_global(_v4_scope, 'isinstance')(snapshot, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("US_RSS_ONLY_RECOVERY_REQUIRES_EXISTING_MARKET_SNAPSHOT")
    if (
        payload.get("status") != "CANNOT_CONFIRM"
        or payload.get("market_snapshot_status") != "CANNOT_CONFIRM"
        or snapshot.get("status") != "CANNOT_CONFIRM"
        or snapshot.get("capture_phase") != "POST_CLOSE"
        or snapshot.get("capture_session_date") != us_session_date
        or _v4_global(_v4_scope, 'len')(snapshot.get("quotes") or []) != 33
        or _v4_global(_v4_scope, 'len')(snapshot.get("rows") or []) != 24
        or "QUOTE_SESSION_TIME_MIXED" not in (snapshot.get("cannot_confirm") or [])
        or _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(snapshot.get("provider_session_times") or [])) < 2
        or not _v4_global(_v4_scope, 're').fullmatch(r"[0-9a-f]{64}", _v4_global(_v4_scope, 'str')(snapshot.get("source_response_sha256") or ""))
    ):
        raise _v4_global(_v4_scope, 'ValueError')("US_RSS_ONLY_RECOVERY_EXISTING_SNAPSHOT_IDENTITY_INVALID")
    captures = payload.get("us_session_captures") or []
    if not _v4_global(_v4_scope, 'any')(
        _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
        and row.get("capture_phase") == "POST_CLOSE"
        and row.get("us_session_date") == us_session_date
        and row.get("capture_origin") == _v4_global(_v4_scope, 'ORIGINAL_TIME_CAPTURE')
        and row.get("original_time_capture") is True
        and not _v4_global(_v4_scope, '_is_late_capture_identity')(row)
        and row.get("captured_at") == snapshot.get("captured_at")
        for row in captures
    ):
        raise _v4_global(_v4_scope, 'ValueError')("US_RSS_ONLY_RECOVERY_ORIGINAL_CAPTURE_IDENTITY_MISSING")


def __materialize_us_market_phase_locked_body(_v4_scope, /, *, data_root, trade_date, capture_phase, allow_late_post_close, rss_only_recovery, now, **kwargs):
    """Materialize one phase and CAS-merge it with the exact-date artifact."""
    phase = _v4_global(_v4_scope, '_phase')(capture_phase)
    if _v4_global(_v4_scope, 'type')(allow_late_post_close) is not _v4_global(_v4_scope, 'bool'):
        raise _v4_global(_v4_scope, 'ValueError')("allow_late_post_close must be boolean")
    if _v4_global(_v4_scope, 'type')(rss_only_recovery) is not _v4_global(_v4_scope, 'bool'):
        raise _v4_global(_v4_scope, 'ValueError')("rss_only_recovery must be boolean")
    if allow_late_post_close and phase != "POST_CLOSE":
        raise _v4_global(_v4_scope, 'ValueError')("US_LATE_POST_CLOSE_ONLY")
    if rss_only_recovery and not allow_late_post_close:
        raise _v4_global(_v4_scope, 'ValueError')("US_RSS_ONLY_RECOVERY_REQUIRES_LATE_POST_CLOSE")
    if allow_late_post_close:
        # Validate the requested US session and the current New York recovery
        # window before reading the store or deriving the idempotency
        # identity.  This is intentionally the reuse admission check; an old
        # ``fetched_at`` belonging to an already-complete capture is allowed
        # to be reused while the same recovery window is still open.
        clock_now = _v4_global(_v4_scope, '_capture_now')(now)
        requested_session_date = _v4_global(_v4_scope, '_date')(
            _v4_global(_v4_scope, 'str')(kwargs.get("us_session_date") or trade_date)
        )
        _v4_global(_v4_scope, '_validate_late_post_close_window')(requested_session_date, now=clock_now)
        session_date = requested_session_date
        # ``trade_date`` remains the exact research artifact date.  The
        # provider session is a separate identity and must reach the builder
        # explicitly so a target-date artifact can hold the prior NY session.
        kwargs["us_session_date"] = session_date
        kwargs.setdefault("capture_id", _v4_global(_v4_scope, '_late_post_close_capture_id')(session_date, clock_now))
        build_now: datetime | str | None = clock_now
    else:
        session_date = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(kwargs.get("us_session_date") or trade_date))
        build_now = now
    store = _v4_global(_v4_scope, 'ResearchPeripheralStore')(data_root)
    existing = store.read_exact(trade_date, "external_finance")
    if rss_only_recovery:
        _validate_rss_only_recovery_baseline(_v4_scope, existing, session_date)
    requested_capture_id = _v4_global(_v4_scope, 'str')(kwargs.get("capture_id") or "").strip() or _v4_global(_v4_scope, '_deterministic_capture_id')(
        session_date, phase
    )
    if phase == "POST_CLOSE" and _v4_global(_v4_scope, 'isinstance')(existing, _v4_global(_v4_scope, 'Mapping')):
        # A valid completed capture is the idempotency boundary.  Read and
        # validate it before the producer is allowed to issue RSS or quote
        # requests; an older news-only artifact deliberately falls through.
        captures = existing.get("us_session_captures") or []
        snapshot = existing.get("market_snapshot")
        session_captures = [
            row
            for row in captures
            if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
            and row.get("capture_phase") == "POST_CLOSE"
            and row.get("us_session_date") == session_date
        ]
        # A late marker may exist on the snapshot, the capture row, or the
        # payload envelope.  Any such marker makes the identity late; this
        # prevents a malformed/older artifact from being reused by the
        # default natural path after one field was omitted.
        artifact_late = (
            _v4_global(_v4_scope, '_is_late_capture_identity')(existing)
            or _v4_global(_v4_scope, '_is_late_capture_identity')(snapshot)
            or _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, '_is_late_capture_identity')(row) for row in session_captures)
        )
        snapshot_matches_mode = (
            artifact_late
            if allow_late_post_close
            else not artifact_late
        )
        late_rss_capture_recorded = rss_only_recovery and _v4_global(_v4_scope, 'any')(
            _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
            and row.get("capture_phase") == "POST_CLOSE"
            and row.get("us_session_date") == session_date
            and row.get("capture_id") == requested_capture_id
            and row.get("quote_capture_status") == "NOT_ATTEMPTED"
            for row in session_captures
        )
        completed = (
            _v4_global(_v4_scope, 'isinstance')(snapshot, _v4_global(_v4_scope, 'Mapping'))
            and (snapshot.get("status") in {"READY", "PARTIAL"} or late_rss_capture_recorded)
            and snapshot.get("capture_phase") == "POST_CLOSE"
            and snapshot.get("capture_session_date") == session_date
            and snapshot_matches_mode
            and _v4_global(_v4_scope, 'any')(
                _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
                and row.get("capture_phase") == "POST_CLOSE"
                and row.get("us_session_date") == session_date
                and row.get("capture_id") == requested_capture_id
                and row.get("capture_origin") == (
                    _v4_global(_v4_scope, 'MANUAL_RECOVERY')
                    if rss_only_recovery
                    else _v4_global(_v4_scope, 'ORIGINAL_TIME_CAPTURE')
                )
                and row.get("original_time_capture") is (not rss_only_recovery)
                and (
                    _v4_global(_v4_scope, '_is_late_capture_identity')(row)
                    if allow_late_post_close
                    else not _v4_global(_v4_scope, '_is_late_capture_identity')(row)
                )
                for row in captures
            )
        )
        if completed:
            relative = store._relative(_v4_global(_v4_scope, '_date')(trade_date), "external_finance")
            receipt_relative = store._receipt_relative(_v4_global(_v4_scope, '_date')(trade_date), "external_finance")
            digest = _v4_global(_v4_scope, '_sha256')(existing)
            return {
                "payload": existing,
                "trade_date": _v4_global(_v4_scope, '_date')(trade_date),
                "source": "external_finance",
                "payload_path": relative,
                "receipt_path": receipt_relative,
                "payload_sha256": digest,
                "item_count": _v4_global(_v4_scope, 'int')(existing["item_count"]),
                "reused": True,
                "replaced": False,
                "market_snapshot_status": _v4_global(_v4_scope, 'str')(snapshot.get("status")),
                "capture_id": requested_capture_id,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
    if allow_late_post_close:
        # A new capture still needs an actual current timestamp.  Defer this
        # stricter check until after mode-aware reuse so a completed late
        # artifact can be returned without pretending its original timestamp
        # was the caller's current second.
        effective_fetched_at = kwargs.get("fetched_at")
        if effective_fetched_at is None:
            effective_fetched_at = clock_now
            # Keep the producer and materializer on the same second-resolved
            # capture instant when the caller leaves fetched_at unspecified.
            kwargs["fetched_at"] = effective_fetched_at
        _v4_global(_v4_scope, '_validate_late_post_close_context')(
            session_date,
            captured_at=effective_fetched_at,
            now=clock_now,
        )
    if phase == "PRE_OPEN" and _v4_global(_v4_scope, 'isinstance')(existing, _v4_global(_v4_scope, 'Mapping')):
        # PRE_OPEN has no quote snapshot, but a same-identity successful news
        # capture is still the idempotency boundary for scheduler retries.
        captures = existing.get("us_session_captures") or []
        snapshot = existing.get("market_snapshot")
        completed = (
            _v4_global(_v4_scope, 'isinstance')(snapshot, _v4_global(_v4_scope, 'Mapping'))
            and snapshot.get("capture_phase") == "PRE_OPEN"
            and snapshot.get("capture_session_date") == session_date
            and existing.get("status") in {"READY", "READY_EMPTY"}
            and _v4_global(_v4_scope, 'any')(
                _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
                and row.get("capture_phase") == "PRE_OPEN"
                and row.get("us_session_date") == session_date
                and row.get("capture_id") == requested_capture_id
                and row.get("original_time_capture") is True
                for row in captures
            )
        )
        if completed:
            relative = store._relative(_v4_global(_v4_scope, '_date')(trade_date), "external_finance")
            receipt_relative = store._receipt_relative(_v4_global(_v4_scope, '_date')(trade_date), "external_finance")
            digest = _v4_global(_v4_scope, '_sha256')(existing)
            return {
                "payload": existing,
                "trade_date": _v4_global(_v4_scope, '_date')(trade_date),
                "source": "external_finance",
                "payload_path": relative,
                "receipt_path": receipt_relative,
                "payload_sha256": digest,
                "item_count": _v4_global(_v4_scope, 'int')(existing["item_count"]),
                "reused": True,
                "replaced": False,
                "market_snapshot_status": _v4_global(_v4_scope, 'str')(snapshot.get("status") or "CANNOT_CONFIRM"),
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
    payload = _v4_global(_v4_scope, 'build_us_market_phase_payload')(
        trade_date,
        capture_phase=capture_phase,
        allow_late_post_close=allow_late_post_close,
        rss_only_recovery=rss_only_recovery,
        now=build_now,
        **kwargs,
    )
    if existing is None:
        result = store.publish(payload)
        return {
            "payload": payload,
            "market_snapshot_status": payload.get("market_snapshot_status"),
            "reused": False,
            "replaced": False,
            **result,
        }
    if phase == "POST_CLOSE" and payload.get("market_snapshot_status") != "READY" and not rss_only_recovery:
        incoming_captures = payload.get("us_session_captures") or []
        incoming_capture = _v4_global(_v4_scope, 'next')(
            (
                row
                for row in incoming_captures
                if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
                and row.get("capture_phase") == "POST_CLOSE"
            ),
            None,
        )
        incoming_capture_id = (
            _v4_global(_v4_scope, 'str')(incoming_capture.get("capture_id") or "")
            if _v4_global(_v4_scope, 'isinstance')(incoming_capture, _v4_global(_v4_scope, 'Mapping'))
            else ""
        )
        existing_capture_ids = {
            _v4_global(_v4_scope, 'str')(row.get("capture_id") or "")
            for row in (existing.get("us_session_captures") or [])
            if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
        }
        existing_snapshot = existing.get("market_snapshot")
        retained_snapshot_is_valid = (
            _v4_global(_v4_scope, 'isinstance')(existing_snapshot, _v4_global(_v4_scope, 'Mapping'))
            and existing_snapshot.get("capture_phase") == "POST_CLOSE"
            and existing_snapshot.get("capture_session_date") == session_date
            and existing_snapshot.get("status") in {"READY", "PARTIAL"}
        )
        if (
            retained_snapshot_is_valid
            and existing.get("status") in {"READY", "READY_EMPTY"}
            and incoming_capture_id
            and incoming_capture_id not in existing_capture_ids
        ):
            # A new failed close capture is an audited failure of this
            # materialization attempt.  Keep the previously verified
            # canonical artifact intact, but persist a receipt for the
            # incoming identity so the CLI and downstream audit cannot report
            # the attempt as successful.
            attempt = store.record_refresh_attempt(
                payload,
                retained_payload=existing,
                reason="US_POST_CLOSE_MARKET_SNAPSHOT_FAILED",
            )
            retained_date = _v4_global(_v4_scope, '_date')(trade_date)
            return {
                "payload": payload,
                "status": "CANNOT_CONFIRM",
                "trade_date": retained_date,
                "source": "external_finance",
                "payload_path": "",
                "receipt_path": attempt["refresh_attempt_path"],
                "payload_sha256": attempt["attempted_payload_sha256"],
                "item_count": _v4_global(_v4_scope, 'int')(payload["item_count"]),
                "reused": False,
                "replaced": False,
                "retained_previous": True,
                "retained_payload_path": store._relative(retained_date, "external_finance"),
                "retained_receipt_path": store._receipt_relative(retained_date, "external_finance"),
                "retained_payload_sha256": attempt["retained_payload_sha256"],
                "market_snapshot_status": "CANNOT_CONFIRM",
                "cannot_confirm": _v4_global(_v4_scope, 'list')(payload.get("cannot_confirm") or []),
                **attempt,
            }
    merged = _v4_global(_v4_scope, 'merge_us_phase_payloads')(
        existing,
        payload,
        preserve_existing_market_snapshot=rss_only_recovery,
    )
    result = store.replace(
        merged,
        expected_sha256=_v4_global(_v4_scope, '_sha256')(existing),
        reason=f"US_{_v4_global(_v4_scope, 'str')(capture_phase).upper()}_CAPTURE_MERGE",
    )
    return {
        "payload": merged,
        "market_snapshot_status": merged.get("market_snapshot_status"),
        "capture_id": requested_capture_id,
        "reused": False,
        **result,
    }


def _materialize_us_historical_backfill_body(_v4_scope, /, *, data_root, trade_date, development_dates, **kwargs):
    payload = _v4_global(_v4_scope, 'build_us_historical_backfill_payload')(
        trade_date,
        development_dates=development_dates,
        **kwargs,
    )
    result = _v4_global(_v4_scope, 'ResearchPeripheralStore')(data_root).publish_historical_backfill(payload)
    return {"payload": payload, **result}
