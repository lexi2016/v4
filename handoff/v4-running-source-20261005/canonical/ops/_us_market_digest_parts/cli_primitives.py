"""ops.us_market_digest: cli_primitives (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _us_market_day_certification_body(_v4_scope, /, us_session_date):
    """Certify 2026 NYSE core-session identity without relaxing quote gates.

    The static calendar is an owned contract derived from the official NYSE
    holiday/trading-hours schedule.  Provider session-date and raw-response
    verification remain separate mandatory checks in the snapshot path.
    """
    from contracts.us_equity_calendar import session

    try:
        selected = session(us_session_date)
    except _v4_global(_v4_scope, 'ValueError') as exc:
        if _v4_global(_v4_scope, 'str')(exc) == "US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE":
            return {"status": "CANNOT_CONFIRM", "reason": _v4_global(_v4_scope, 'str')(exc)}
        raise
    if selected.close_at is None:
        return {
            "status": "CLOSED",
            "reason": selected.state,
            "source_url": selected.source_url,
        }
    return {
        "status": "VERIFIED",
        "reason": selected.state,
        "close_at": selected.close_at.isoformat(),
        "source_url": selected.source_url,
    }


def _parse_args_body(_v4_scope, /, argv):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(description=_v4_global(_v4_scope, '__doc__'))
    parser.add_argument("--data-root", type=_v4_global(_v4_scope, 'Path'), required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--capture-phase", choices=_v4_global(_v4_scope, 'US_CAPTURE_PHASES'))
    parser.add_argument(
        "--allow-late-post-close",
        action="store_true",
        help="explicitly recover the latest completed POST_CLOSE session inside its bounded New York recovery window",
    )
    parser.add_argument(
        "--rss-only-recovery",
        action="store_true",
        help="capture recent RSS through the existing owner while leaving the quote snapshot untouched",
    )
    parser.add_argument("--historical", action="store_true")
    parser.add_argument("--development-dates-file", type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--timeout", type=_v4_global(_v4_scope, 'int'), default=20)
    return parser.parse_args(_v4_global(_v4_scope, 'list')(argv) if argv is not None else None)


def _main_body(_v4_scope, /, argv):
    args = _v4_global(_v4_scope, 'parse_args')(argv)
    try:
        if args.historical:
            if args.capture_phase or args.development_dates_file is None or args.allow_late_post_close or args.rss_only_recovery:
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
            if args.allow_late_post_close:
                if args.capture_phase != "POST_CLOSE":
                    raise _v4_global(_v4_scope, 'ValueError')("US_LATE_POST_CLOSE_ONLY")
                recovery_now = _v4_global(_v4_scope, '_capture_now')()
                materialize_kwargs["allow_late_post_close"] = True
                # This CLI receives the NY session date (also used by the
                # registry), not an arbitrary historical destination date.
                materialize_kwargs["us_session_date"] = args.trade_date
                materialize_kwargs["now"] = recovery_now
                materialize_kwargs["capture_id"] = _v4_global(_v4_scope, '_late_post_close_capture_id')(
                    args.trade_date,
                    recovery_now,
                )
                materialize_kwargs["rss_only_recovery"] = args.rss_only_recovery
            elif args.rss_only_recovery:
                raise _v4_global(_v4_scope, 'ValueError')("US_RSS_ONLY_RECOVERY_REQUIRES_LATE_POST_CLOSE")
            result = _v4_global(_v4_scope, 'materialize_us_market_phase')(
                data_root=args.data_root,
                trade_date=args.trade_date,
                capture_phase=args.capture_phase,
                timeout=args.timeout,
                **materialize_kwargs,
            )
        capture_rows = result["payload"].get("us_session_captures") or []
        capture_identity = _v4_global(_v4_scope, 'next')(
            (
                row
                for row in _v4_global(_v4_scope, 'reversed')(capture_rows)
                if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
                and row.get("us_session_date") == _v4_global(_v4_scope, '_date')(args.trade_date)
                and row.get("capture_phase") == args.capture_phase
                and (not result.get("capture_id") or row.get("capture_id") == result.get("capture_id"))
            ),
            {},
        )
        rss_capture_status = _v4_global(_v4_scope, 'str')(capture_identity.get("rss_status") or "CANNOT_CONFIRM")
        market_snapshot_status = (
            result["payload"].get("market_snapshot_status")
            or result.get("market_snapshot_status")
            or "CANNOT_CONFIRM"
        )
        lane_has_success = (
            rss_capture_status in {"READY", "READY_EMPTY"}
            or market_snapshot_status == "READY"
        )
        operation_status = (
            "CAPTURED"
            if lane_has_success and result["payload"].get("status") in {"READY", "READY_EMPTY"}
            else "CAPTURED_WITH_UNVERIFIED_LANE"
            if lane_has_success
            else "NO_LANE_READY"
        )
        _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps({
            "status": result.get("status") or result["payload"]["status"],
            "trade_date": result["payload"]["trade_date"],
            "source": result["payload"]["source"],
            "payload_path": result["payload_path"],
            "receipt_path": result.get("receipt_path"),
            "payload_sha256": result["payload_sha256"],
            "reused": result.get("reused"),
            "replaced": result.get("replaced"),
            "capture_us_session_date": capture_identity.get("us_session_date"),
            "capture_phase": capture_identity.get("capture_phase"),
            "capture_id": capture_identity.get("capture_id"),
            "capture_run_id": capture_identity.get("run_id"),
            "capture_captured_at": capture_identity.get("captured_at"),
            "capture_capture_origin": capture_identity.get("capture_origin"),
            "capture_original_time": capture_identity.get("original_time_capture"),
            "capture_origin": result["payload"].get("capture_origin"),
            "rss_capture_status": rss_capture_status,
            "rss_capture_item_count": capture_identity.get("rss_item_count"),
            "rss_capture_raw_item_count": capture_identity.get("rss_raw_item_count"),
            "quote_capture_status": capture_identity.get("quote_capture_status"),
            "quote_capture_reason": capture_identity.get("quote_capture_reason"),
            "operation_status": operation_status,
            "rss_only_recovery": args.rss_only_recovery,
            "original_time_capture": result["payload"].get("original_time_capture"),
            "capture_mode": result["payload"].get("capture_mode"),
            "reason": result["payload"].get("reason"),
            "late": result["payload"].get("late", False),
            "natural_capture_window_start": result["payload"].get("natural_capture_window_start"),
            "natural_capture_window_end": result["payload"].get("natural_capture_window_end"),
            "allowed_recovery_window_start": result["payload"].get("allowed_recovery_window_start"),
            "allowed_recovery_window_end": result["payload"].get("allowed_recovery_window_end"),
            "market_snapshot_status": market_snapshot_status,
            "cannot_confirm": _v4_global(_v4_scope, 'list')(result["payload"].get("cannot_confirm") or []),
            "refresh_attempt_path": result.get("refresh_attempt_path"),
            "retained_previous": result.get("retained_previous", False),
            "retained_payload_path": result.get("retained_payload_path"),
            "retained_payload_sha256": result.get("retained_payload_sha256"),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ensure_ascii=False, sort_keys=True))
        return 0 if lane_has_success else 2
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps({
            "status": "CANNOT_CONFIRM",
            "reason": f"{_v4_global(_v4_scope, 'type')(error).__name__}:{error}",
            "market_snapshot_status": "CANNOT_CONFIRM",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ensure_ascii=False, sort_keys=True))
        return 2
