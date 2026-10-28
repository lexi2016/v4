"""stage_center.live_collectors: hk_replay (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __collect_hk_0925_replay_body(_v4_scope, /, plan, *, codes, replay_provider):
    cutoff_at = _v4_global(_v4_scope, '_stage_0925_hk_reference_cutoff_iso')(plan.trade_date)
    evidence = (
        "route=hk_connect_0915_0920_auction_second_filter",
        "exact_date=true",
        "replay_method=v3_hkconnect_0915_0920_reference_snapshot",
        f"replay_trade_date={plan.trade_date}",
        f"replay_cutoff={cutoff_at}",
    )
    requested = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, '_canonical_hk_code')(code) for code in codes if _v4_global(_v4_scope, '_canonical_hk_code')(code)))
    if replay_provider is None:
        return _v4_global(_v4_scope, 'SourceResult')(
            "hk_auction_second_filter",
            "CANNOT_CONFIRM",
            requested_rows=_v4_global(_v4_scope, 'len')(requested),
            cannot_confirm=("HK_0925_REPLAY_PROVIDER_UNAVAILABLE",),
            source_evidence=evidence,
        )
    try:
        payload = replay_provider.snapshot(
            requested,
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            cutoff_at=cutoff_at,
        )
        payload, captured_at, raw_rows = _v4_global(_v4_scope, '_validate_replay_payload')(
            payload,
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            cutoff_at=cutoff_at,
        )
        by_code: dict[str, dict[str, Any]] = {}
        for raw in raw_rows:
            if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
                continue
            code = _v4_global(_v4_scope, '_canonical_hk_code')(raw.get("symbol") or raw.get("code") or raw.get("ts_code"))
            if not code or code not in requested:
                continue
            update_time = _v4_global(_v4_scope, '_exact_market_timestamp')(
                raw.get("update_time") or raw.get("time") or raw.get("stage_replay_latest_time"),
                plan.trade_date,
            )
            if update_time is None or update_time > _v4_global(_v4_scope, 'datetime').fromisoformat(cutoff_at):
                raise _v4_global(_v4_scope, 'ValueError')(f"replay row timestamp outside exact cutoff: {code}")
            by_code[code] = {
                "batch_index": _v4_global(_v4_scope, 'len')(by_code) + 1,
                "code": code,
                "name": raw.get("name") or raw.get("stock_name") or code,
                "stock_name": raw.get("stock_name") or raw.get("name") or code,
                "update_time": update_time.strftime("%Y-%m-%d %H:%M:%S"),
                "time": update_time.strftime("%Y-%m-%d %H:%M:%S"),
                "last_price": _v4_global(_v4_scope, '_safe_number')(raw.get("last_price")),
                "open_price": _v4_global(_v4_scope, '_safe_number')(raw.get("open_price") or raw.get("reference_price_hkd") or raw.get("last_price")),
                "high_price": _v4_global(_v4_scope, '_safe_number')(raw.get("high_price") or raw.get("last_price")),
                "low_price": _v4_global(_v4_scope, '_safe_number')(raw.get("low_price") or raw.get("last_price")),
                "prev_close_price": _v4_global(_v4_scope, '_safe_number')(raw.get("prev_close_price") or raw.get("prev_close")),
                "turnover": _v4_global(_v4_scope, '_safe_number')(raw.get("turnover") or raw.get("turnover_hkd")) or 0.0,
                "amount": _v4_global(_v4_scope, '_safe_number')(raw.get("turnover") or raw.get("turnover_hkd")) or 0.0,
                "volume": _v4_global(_v4_scope, '_safe_number')(raw.get("volume")) or 0.0,
                "window_start": f"{plan.trade_date[:4]}-{plan.trade_date[4:6]}-{plan.trade_date[6:]} 09:15:00",
                "window_end": update_time.strftime("%Y-%m-%d %H:%M:%S"),
                "bar_count": raw.get("bar_count", 1),
                "temporal_cutoff_safe": True,
                "target_date": plan.trade_date,
                "signal_date": raw.get("signal_date") or "",
                "rank": raw.get("rank") or "",
                "auction_score": raw.get("auction_score") or raw.get("stage1_ref_score") or 0.0,
                "second_filter_status": raw.get("second_filter_status") or "WATCH_ONLY",
                "preselect_lane": raw.get("preselect_lane") or "",
                "reference_price_hkd": raw.get("reference_price_hkd") or raw.get("last_price") or "",
                "strict_failure_price_hkd": raw.get("strict_failure_price_hkd") or raw.get("bid_price") or "",
            }
        rows = _v4_global(_v4_scope, 'tuple')(by_code[code] for code in requested if code in by_code)
        missing = _v4_global(_v4_scope, 'tuple')(code for code in requested if code not in by_code)
        cannot = [_v4_global(_v4_scope, 'str')(item) for item in (payload.get("cannot_confirm") or ()) if _v4_global(_v4_scope, 'str')(item)]
        if missing:
            cannot.append("HK_0925_REPLAY_ROWS_MISSING: " + ", ".join(missing))
        status = "READY" if _v4_global(_v4_scope, 'len')(rows) == _v4_global(_v4_scope, 'len')(requested) else ("PARTIAL_WITH_ROWS" if rows else "CANNOT_CONFIRM")
        return _v4_global(_v4_scope, 'SourceResult')(
            "hk_auction_second_filter",
            status,
            rows=rows,
            requested_rows=_v4_global(_v4_scope, 'len')(requested),
            missing_symbols=missing,
            cannot_confirm=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(cannot)),
            source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*evidence, f"replay_source={payload.get('source') or 'V3_HKCONNECT_0915_0920_REFERENCE_SNAPSHOT'}", f"replay_captured_at={captured_at}"))),
        )
    except _v4_global(_v4_scope, 'Exception') as error:
        return _v4_global(_v4_scope, 'SourceResult')(
            "hk_auction_second_filter",
            "CANNOT_CONFIRM",
            requested_rows=_v4_global(_v4_scope, 'len')(requested),
            cannot_confirm=(f"HK_0925_REPLAY_ERROR:{_v4_global(_v4_scope, 'type')(error).__name__}:{error}",),
            source_evidence=evidence,
        )


def __collect_hk_stage8_replay_body(_v4_scope, /, plan, *, codes, replay_provider):
    cutoff_at = _v4_global(_v4_scope, '_stage_cutoff_iso')(plan.trade_date, plan.stage_id)
    evidence = (
        "route=v3_hkconnect_stage8_rtd_data_replay",
        "exact_date=true",
        "replay_method=v3_hkconnect_stage8_rtd_data",
        f"replay_trade_date={plan.trade_date}",
        f"replay_cutoff={cutoff_at}",
    )
    requested = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, '_canonical_hk_code')(code) for code in codes if _v4_global(_v4_scope, '_canonical_hk_code')(code)))
    if replay_provider is None:
        return _v4_global(_v4_scope, 'SourceResult')(
            "v3_hkconnect_stage8_replay",
            "CANNOT_CONFIRM",
            requested_rows=_v4_global(_v4_scope, 'len')(requested),
            cannot_confirm=("HK_STAGE8_EXACT_RTDATA_REPLAY_UNAVAILABLE",),
            source_evidence=evidence,
        )
    try:
        payload = replay_provider.snapshot(
            requested,
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            cutoff_at=cutoff_at,
        )
        payload, captured_at, raw_rows = _v4_global(_v4_scope, '_validate_replay_payload')(
            payload,
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            cutoff_at=cutoff_at,
        )
        cutoff = _v4_global(_v4_scope, 'datetime').fromisoformat(cutoff_at)
        by_code: dict[str, dict[str, Any]] = {}
        for raw in raw_rows:
            if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
                continue
            code = _v4_global(_v4_scope, '_canonical_hk_code')(raw.get("symbol") or raw.get("code") or raw.get("ts_code"))
            if not code or code not in requested:
                continue
            update_time = _v4_global(_v4_scope, '_exact_market_timestamp')(
                raw.get("stage_replay_latest_time") or raw.get("update_time") or raw.get("time"),
                plan.trade_date,
            )
            if update_time is None or update_time > cutoff:
                raise _v4_global(_v4_scope, 'ValueError')(f"replay row timestamp outside exact cutoff: {code}")
            source_universe = _v4_global(_v4_scope, 'str')(raw.get("source_universe") or "")
            candidate_lanes = [
                token
                for token in (item.strip() for item in source_universe.split("|"))
                if token in {
                    "LIVE_HKCONNECT_GAINER",
                    "NEW_HKCONNECT_BATCH",
                    "OLD_DEMON_MEMORY",
                    "LOW_FLOAT_FILTER",
                    "PREOPEN_AUCTION_CONTINUATION",
                }
            ]
            last_price = _v4_global(_v4_scope, '_safe_number')(raw.get("last_price"))
            prev_close = _v4_global(_v4_scope, '_safe_number')(raw.get("prev_close_price") or raw.get("prev_close"))
            pct = _v4_global(_v4_scope, '_safe_number')(raw.get("pct_chg"))
            if pct is None and prev_close not in (None, 0) and last_price is not None:
                pct = (last_price - prev_close) / prev_close * 100.0
            turnover = _v4_global(_v4_scope, '_safe_number')(raw.get("turnover_hkd") or raw.get("turnover"))
            by_code[code] = {
                "code": code,
                "name": raw.get("name") or raw.get("stock_name") or code,
                "stock_name": raw.get("stock_name") or raw.get("name") or code,
                "candidate_lanes": candidate_lanes,
                "source_universe": source_universe,
                "prev_close_price": prev_close,
                "last_price": last_price,
                "pct_chg": pct,
                "turnover": turnover,
                "turnover_hkd": turnover,
                "volume_ratio": _v4_global(_v4_scope, '_safe_number')(raw.get("volume_ratio")),
                "turnover_rate": _v4_global(_v4_scope, '_safe_number')(raw.get("turnover_rate")),
                "platform_circular_market_cap_hkd_yi": _v4_global(_v4_scope, '_safe_number')(raw.get("platform_circular_market_cap_hkd_yi")),
                "offer_float_market_cap_hkd_yi": _v4_global(_v4_scope, '_safe_number')(raw.get("offer_float_market_cap_hkd_yi")),
                "stage_window_change_pct": _v4_global(_v4_scope, '_safe_number')(raw.get("stage_window_change_pct")),
                "update_time": update_time.strftime("%Y-%m-%d %H:%M:%S"),
                "stage_replay_latest_time": update_time.strftime("%Y-%m-%d %H:%M:%S"),
                "temporal_cutoff_safe": True,
                "trade_date": plan.trade_date,
                "stage_id": plan.stage_id,
            }
        rows = _v4_global(_v4_scope, 'tuple')(by_code[code] for code in requested if code in by_code)
        missing = _v4_global(_v4_scope, 'tuple')(code for code in requested if code not in by_code)
        cannot = [_v4_global(_v4_scope, 'str')(item) for item in (payload.get("cannot_confirm") or ()) if _v4_global(_v4_scope, 'str')(item)]
        if missing:
            cannot.append("HK_STAGE8_REPLAY_ROWS_MISSING: " + ", ".join(missing))
        status = "READY" if _v4_global(_v4_scope, 'len')(rows) == _v4_global(_v4_scope, 'len')(requested) else ("PARTIAL_WITH_ROWS" if rows else "CANNOT_CONFIRM")
        return _v4_global(_v4_scope, 'SourceResult')(
            "v3_hkconnect_stage8_replay",
            status,
            rows=rows,
            requested_rows=_v4_global(_v4_scope, 'len')(requested),
            missing_symbols=missing,
            cannot_confirm=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys(cannot)),
            source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*evidence, f"replay_source={payload.get('source') or 'V3_HKCONNECT_STAGE8_RTDATA_REPLAY'}", f"replay_captured_at={captured_at}"))),
        )
    except _v4_global(_v4_scope, 'Exception') as error:
        return _v4_global(_v4_scope, 'SourceResult')(
            "v3_hkconnect_stage8_replay",
            "CANNOT_CONFIRM",
            requested_rows=_v4_global(_v4_scope, 'len')(requested),
            cannot_confirm=(f"HK_STAGE8_REPLAY_ERROR:{_v4_global(_v4_scope, 'type')(error).__name__}:{error}",),
            source_evidence=evidence,
        )
