"""stage_center.selection: hk_auction_filter (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _select_hk_0925_second_filter_body(_v4_scope, /, rows, trade_date, raw_artifact_sha256, *, source_status, requested_rows, missing_symbols, cannot_confirm, source_evidence):
    """Preserve the authoritative 09:20 second-filter rank/order verbatim."""
    _v4_global(_v4_scope, '_validate_date')(trade_date)
    normalized: list[dict[str, Any]] = []
    signal_dates: list[str] = []
    for index, source in _v4_global(_v4_scope, 'enumerate')(rows, start=1):
        # ``signal_date`` is the prior trading session for the 09:20 auction;
        # only target_date binds this stage's trade-date identity.
        for date_key in ("target_date",):
            value = _v4_global(_v4_scope, 'str')(source.get(date_key) or "").replace("-", "")
            if value and value != trade_date:
                raise _v4_global(_v4_scope, 'SelectionError')(f"HK 0925 {date_key} drift")
        signal_date = _v4_global(_v4_scope, 'str')(source.get("signal_date") or "").replace("-", "")
        if signal_date:
            _v4_global(_v4_scope, '_validate_date')(signal_date)
            if signal_date == trade_date:
                raise _v4_global(_v4_scope, 'SelectionError')("HK 0925 signal_date must be prior to trade_date")
            if signal_date not in signal_dates:
                signal_dates.append(signal_date)
        code = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_a_row_value')(source, "code", "ts_code") or "").strip()
        if not code:
            raise _v4_global(_v4_scope, 'SelectionError')("HK 0925 row code is required")
        raw_rank = _v4_global(_v4_scope, '_optional_number')(source.get("rank"))
        rank = _v4_global(_v4_scope, 'int')(raw_rank) if raw_rank is not None else index
        card = _v4_global(_v4_scope, '_stage_card_evidence')(
            source,
            code=code,
            open_price=source.get("open_price"),
            last_price=source.get("last_price"),
            high_price=source.get("high_price"),
            low_price=source.get("low_price"),
            source_last_bar_time=source.get("update_time"),
        )
        normalized.append(
            {
                "code": code,
                "score": _v4_global(_v4_scope, 'round')(_v4_global(_v4_scope, '_number')(source.get("auction_score")), 6),
                "rank": rank,
                "status": _v4_global(_v4_scope, 'str')(source.get("second_filter_status") or "WATCH_ONLY"),
                "formal_eligible": False,
                "support": _v4_global(_v4_scope, '_hk_float')(source, "reference_price_hkd", "last_price"),
                "pressure": _v4_global(_v4_scope, '_hk_float')(source, "ask_price"),
                "invalidation": _v4_global(_v4_scope, '_hk_float')(source, "strict_failure_price_hkd", "bid_price"),
                "source_mode": "HK_CONNECT_AUCTION_SECOND_FILTER_STAGE_0925",
                "lane_evidence": [
                    _v4_global(_v4_scope, 'str')(source.get("preselect_lane") or ""),
                    _v4_global(_v4_scope, 'str')(source.get("second_filter_status") or ""),
                ],
                "action_level": "NO_BUY",
                "trade_status": "WATCH_ONLY",
                **card,
            }
        )
    # Do not sort: source rank/order is itself the oracle and may be non-lexical.
    top10 = _v4_global(_v4_scope, '_top10_contract')(source_evidence)
    legacy = _v4_global(_v4_scope, '_legacy_backfill')(source_evidence) and not top10
    normalized = _v4_global(_v4_scope, '_cap_recommendations')(normalized, preserve_legacy=legacy)
    algorithm_sha = (
        _v4_global(_v4_scope, 'ALGORITHM_SHA256') if top10 else _v4_global(_v4_scope, 'LEGACY_ALGORITHM_SHA256')
    )
    status = "READY" if normalized and source_status not in {"CANNOT_CONFIRM", "READ_FAILED"} else ("READY_EMPTY" if not normalized else "PARTIAL_WITH_ROWS")
    result = _v4_global(_v4_scope, '_selection_envelope')(
        trade_date=trade_date,
        stage_id="STAGE_0925",
        market="HK_CONNECT",
        raw_artifact_sha256=raw_artifact_sha256,
        source_status=status,
        input_rows=_v4_global(_v4_scope, 'len')(rows),
        rows=normalized,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot_confirm,
        source_evidence=(
            *source_evidence,
            "route=hk_connect_0915_0920_auction_second_filter",
            *(f"signal_date={value}" for value in signal_dates),
            f"algorithm_sha256={algorithm_sha}",
        ),
        algorithm_sha256=algorithm_sha,
    )
    # The source status is an envelope-level fact; keep malformed/failed source
    # evidence fail-closed instead of silently replacing it with READY.
    if source_status in {"CANNOT_CONFIRM", "READ_FAILED"} and normalized:
        result["source_status"] = "CANNOT_CONFIRM"
        result["selection_status"] = "PARTIAL_WITH_ROWS"
    return result
