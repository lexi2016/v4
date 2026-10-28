"""stage_center.selection: a_auction (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _select_a_0925_auction_body(_v4_scope, /, rows, trade_date, raw_artifact_sha256, *, next_validation_time, source_status, requested_rows, missing_symbols, cannot_confirm, source_evidence):
    """Port V3 ``_rows_from_auction`` for exact-date 09:25 evidence.

    The auction price is compared with the exact previous close and passed
    through the Windows V3 live-stage formula.  Auction amount is only the
    bounded liquidity bonus; it is never exposed as the recommendation score.
    Rows are ranked descending by the bounded score with Python-stable ties,
    and the route records the exact-date/time contract in evidence rather than
    falling through to minute-bar scoring.
    """
    _v4_global(_v4_scope, '_validate_date')(trade_date)
    _v4_global(_v4_scope, '_validate_market')("STAGE_0925", "A_SHARE")
    normalized: list[dict[str, Any]] = []
    invalid_evidence: list[str] = []
    for index, source in _v4_global(_v4_scope, 'enumerate')(rows):
        row_date = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_a_row_value')(source, "trade_date", "verify_date", "date8", "target_date") or "").replace("-", "")
        if row_date and row_date != trade_date:
            raise _v4_global(_v4_scope, 'SelectionError')("A 09:25 auction trade_date drift")
        time_value = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_a_row_value')(source, "time", "captured_at", "update_time") or "")
        time_match = _v4_global(_v4_scope, 're').search(r"(?:^|\D)(\d{1,2}):(\d{2})(?:\D|$)", time_value)
        if time_match:
            hhmm_value: int | None = _v4_global(_v4_scope, 'int')(time_match.group(1)) * 100 + _v4_global(_v4_scope, 'int')(time_match.group(2))
        elif _v4_global(_v4_scope, 're').fullmatch(r"\d{4}", time_value.strip()):
            hhmm_value = _v4_global(_v4_scope, 'int')(time_value.strip())
        else:
            hhmm_value = None
        if hhmm_value is None:
            invalid_evidence.append(f"row {index + 1} lacks a verifiable auction time")
            continue
        if not (920 <= hhmm_value <= 930):
            invalid_evidence.append(f"row {index + 1} outside 09:20-09:30 auction window")
            continue
        if not _v4_global(_v4_scope, '_truthy')(source.get("is_open_call_auction_match"), True):
            invalid_evidence.append(f"row {index + 1} is not an opening auction match")
            continue
        code = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_a_row_value')(source, "code", "ts_code", "stock_code") or "").strip()
        if not code:
            raise _v4_global(_v4_scope, 'SelectionError')("A 09:25 auction row code is required")
        amount = _v4_global(_v4_scope, '_number')(_v4_global(_v4_scope, '_a_row_value')(source, "amount_yuan", "auction_amount_est_yuan", "amount"))
        price = _v4_global(_v4_scope, '_optional_number')(_v4_global(_v4_scope, '_a_row_value')(source, "price", "open_price", "last_price"))
        prev_close = _v4_global(_v4_scope, '_optional_number')(
            _v4_global(_v4_scope, '_a_row_value')(source, "prev_close_price", "prev_close", "last_close")
        )
        current_change = _v4_global(_v4_scope, '_live_pct_change')(price, prev_close)
        qmt = {
            "open": price,
            "lastPrice": price,
            "lastClose": prev_close,
            "high": _v4_global(_v4_scope, '_optional_number')(_v4_global(_v4_scope, '_a_row_value')(source, "high_price", "high")) or price,
            "low": _v4_global(_v4_scope, '_optional_number')(_v4_global(_v4_scope, '_a_row_value')(source, "low_price", "low")) or price,
            "amount": amount,
            "bidVol": _v4_global(_v4_scope, '_a_row_value')(source, "bid_vol", "bid_vol1"),
            "askVol": _v4_global(_v4_scope, '_a_row_value')(source, "ask_vol", "ask_vol1"),
        }
        bounded_score = _v4_global(_v4_scope, '_clamp')(
            _v4_global(_v4_scope, 'live_stage_quality_score')(
                qmt,
                {"score": _v4_global(_v4_scope, '_a_row_value')(source, "pool_score", "candidate_score")},
                "STAGE_0925",
            )
        )
        card_source = _v4_global(_v4_scope, 'dict')(source)
        card_source["current_change_pct"] = current_change
        card = _v4_global(_v4_scope, '_stage_card_evidence')(
            card_source,
            code=code,
            open_price=_v4_global(_v4_scope, '_a_row_value')(source, "open_price", "open"),
            last_price=_v4_global(_v4_scope, '_a_row_value')(source, "last_price", "close", "price"),
            high_price=_v4_global(_v4_scope, '_a_row_value')(source, "high_price", "high"),
            low_price=_v4_global(_v4_scope, '_a_row_value')(source, "low_price", "low"),
            source_last_bar_time=_v4_global(_v4_scope, '_a_row_value')(source, "update_time", "time"),
            next_validation_time=next_validation_time or _v4_global(_v4_scope, '_a_row_value')(source, "next_validation_time"),
        )
        normalized.append(
            {
                "code": code,
                "score": _v4_global(_v4_scope, 'round')(bounded_score, 6),
                "status": "集合竞价成交代理观察",
                "formal_eligible": False,
                "prev_close_price": prev_close,
                "current_change_pct": None if current_change is None else _v4_global(_v4_scope, 'round')(current_change, 4),
                "qmt_gap_pct": 0.0 if current_change is None else _v4_global(_v4_scope, 'round')(current_change, 6),
                "qmt_amount": amount,
                "stage_score": _v4_global(_v4_scope, 'round')(bounded_score, 6),
                "support": price,
                "pressure": price,
                "invalidation": price,
                "source_mode": "A_SHARE_AUCTION_TRANSACTION_STAGE_0925",
                "lane_evidence": [
                    "A_SHARE_EXACT_DATE_AUCTION_TRANSACTION",
                    "window=09:20-09:30",
                    "exact_date=true",
                    "formula=windows_v3_live_stage_quality_score",
                    "score_bounded_0_100=true",
                    "current_change_pct_basis=AUCTION_PRICE_VS_PREV_CLOSE",
                ],
                "action_level": "NO_BUY",
                "trade_status": "WATCH_ONLY",
                "bar_order": index,
                **card,
            }
        )
    normalized = _v4_global(_v4_scope, '_cap_recommendations')(_v4_global(_v4_scope, 'sorted')(normalized, key=lambda item: item["score"], reverse=True))
    cannot = (*cannot_confirm, *invalid_evidence)
    top10 = _v4_global(_v4_scope, '_top10_contract')(source_evidence)
    legacy = _v4_global(_v4_scope, '_legacy_backfill')(source_evidence) and not top10
    algorithm_sha = _v4_global(_v4_scope, 'A_SHARE_LIVE_ALGORITHM_SHA256') if top10 else _v4_global(_v4_scope, 'LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256')
    evidence = (
        *source_evidence,
        "route=a_share_exact_date_auction_transaction",
        "exact_date=true",
        "window=09:20-09:30",
        "formula=windows_v3_live_stage_quality_score",
        "score_bounded_0_100=true",
        "current_change_pct_basis=AUCTION_PRICE_VS_PREV_CLOSE",
        f"algorithm_sha256={algorithm_sha}",
    )
    return _v4_global(_v4_scope, '_selection_envelope')(
        trade_date=trade_date,
        stage_id="STAGE_0925",
        market="A_SHARE",
        raw_artifact_sha256=raw_artifact_sha256,
        source_status=source_status if not invalid_evidence else "CANNOT_CONFIRM",
        input_rows=_v4_global(_v4_scope, 'len')(rows),
        rows=normalized,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot,
        source_evidence=evidence,
        algorithm_sha256=algorithm_sha,
    )
