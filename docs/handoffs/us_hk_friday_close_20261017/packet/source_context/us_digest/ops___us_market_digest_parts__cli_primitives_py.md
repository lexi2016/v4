## Source excerpt: `ops/_us_market_digest_parts/cli_primitives.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu-industry-us-20261016-r1/app/ops/_us_market_digest_parts/cli_primitives.py`

Original full-file SHA-256: `252bcc75e3f1ff26ffe58c16c49935d36f5f9ed4811d8bd820f7a454a9d21968`

Release/worktree group: `us_digest`

CLI date/session selection passed into the existing US phase materializer.

### Full-source lines 65-112

```python

def _main_body(_v4_scope, /, argv):
    args = _v4_global(_v4_scope, 'parse_args')(argv)
    recovery_now = None
    session_date = None
    try:
        session_date = _v4_global(_v4_scope, '_date')(
            _v4_global(_v4_scope, 'str')(args.us_session_date or args.trade_date)
        )
        if args.manual_late_recovery and (
            not args.allow_late_post_close or args.capture_phase != "POST_CLOSE"
        ):
            raise _v4_global(_v4_scope, 'ValueError')("US_MANUAL_LATE_RECOVERY_REQUIRES_POST_CLOSE_LATE_CAPTURE")
        if args.historical:
            if args.capture_phase or args.us_session_date or args.development_dates_file is None or args.allow_late_post_close or args.manual_late_recovery or args.rss_only_recovery:
                raise _v4_global(_v4_scope, 'ValueError')("historical mode requires only --development-dates-file")
            allowlist_payload = _v4_global(_v4_scope, 'json').loads(args.development_dates_file.read_text(encoding="utf-8"))
            if _v4_global(_v4_scope, 'isinstance')(allowlist_payload, _v4_global(_v4_scope, 'Mapping')):
                allowlist_payload = allowlist_payload.get("dates")
            if not _v4_global(_v4_scope, 'isinstance')(allowlist_payload, _v4_global(_v4_scope, 'list')):
                raise _v4_global(_v4_scope, 'ValueError')("development date allowlist must be a JSON list")
            result = _v4_global(_v4_scope, 'materialize_us_historical_backfill')(
                data_root=args.data_root,
                trade_date=args.trade_date,
                development_dates=allowlist_payload,
                timeout=args.timeout,
            )
        else:
            if not args.capture_phase or args.development_dates_file is not None:
                raise _v4_global(_v4_scope, 'ValueError')("live mode requires --capture-phase and no development allowlist")
            materialize_kwargs: dict[str, Any] = {}
            materialize_kwargs["us_session_date"] = session_date
            if args.allow_late_post_close:
                if args.capture_phase != "POST_CLOSE":
                    raise _v4_global(_v4_scope, 'ValueError')("US_LATE_POST_CLOSE_ONLY")
                recovery_now = _v4_global(_v4_scope, '_capture_now')()
                materialize_kwargs["allow_late_post_close"] = True
                materialize_kwargs["now"] = recovery_now
                materialize_kwargs["capture_id"] = _v4_global(_v4_scope, '_late_post_close_capture_id')(
                    session_date,
                    recovery_now,
                )
                materialize_kwargs["rss_only_recovery"] = args.rss_only_recovery
            elif args.rss_only_recovery:
                raise _v4_global(_v4_scope, 'ValueError')("US_RSS_ONLY_RECOVERY_REQUIRES_LATE_POST_CLOSE")
            result = _v4_global(_v4_scope, 'materialize_us_market_phase')(
                data_root=args.data_root,
                trade_date=args.trade_date,
                capture_phase=args.capture_phase,

```
