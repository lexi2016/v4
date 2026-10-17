## Source excerpt: `ops/_us_market_digest_parts/phase_payload.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu-industry-us-20261016-r1/app/ops/_us_market_digest_parts/phase_payload.py`

Original full-file SHA-256: `fdfeeaf376efb3f2def86abd633d94790e0e9163586d23068eb9bab2c343bd56`

Release/worktree group: `us_digest`

Payload builder keeps trade date and requested US session separate.

### Full-source lines 120-178

```python

def _build_us_market_phase_payload_body(_v4_scope, /, trade_date, *, capture_phase, us_session_date, fetched_at, capture_id, run_id, fetch_rss, fetch_quotes, fetch_quote, fetch_futu_boards, transport, translate_text, resolve_original_url, allow_late_post_close, rss_only_recovery, now, **kwargs):
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

```
