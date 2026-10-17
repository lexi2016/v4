## Source excerpt: `ops/_us_market_digest_parts/phase_publication.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu-industry-us-20261016-r1/app/ops/_us_market_digest_parts/phase_publication.py`

Original full-file SHA-256: `6a0abaef5e2f50297d3021d06e781c1832a690d09269317f84fa407505027379`

Release/worktree group: `us_digest`

Existing exact-date publisher and separate explicit US-session identity handling.

### Full-source lines 6-24

```python

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

```

### Full-source lines 62-94

```python

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

```
