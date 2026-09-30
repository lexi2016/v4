"""stage_center.selection: hk_four_lanes (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _merge_hk_four_lane_candidates_body(_v4_scope, /, rows):
    """Merge same-code V3 lane rows while preserving lane/source precedence.

    The Windows service builds one row from several lane inputs.  The first
    non-empty live quote is authoritative for names and quote fields; later
    static-lane rows only contribute their lane labels and missing metadata.
    """
    merged: dict[str, dict[str, Any]] = {}
    for raw in rows:
        code = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_a_row_value')(raw, "code", "ts_code") or "").strip()
        if not code:
            continue
        incoming = _v4_global(_v4_scope, 'dict')(raw)
        current = merged.get(code)
        if current is None:
            incoming["candidate_lanes"] = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, 'str')(item) for item in (incoming.get("candidate_lanes") or ())))
            merged[code] = incoming
            continue
        current["candidate_lanes"] = _v4_global(_v4_scope, 'list')(
            _v4_global(_v4_scope, 'dict').fromkeys(
                [
                    *(_v4_global(_v4_scope, 'str')(item) for item in (current.get("candidate_lanes") or ())),
                    *(_v4_global(_v4_scope, 'str')(item) for item in (incoming.get("candidate_lanes") or ())),
                ]
            )
        )
        for key, value in incoming.items():
            if key == "candidate_lanes":
                continue
            if value not in (None, "", (), [], {}):
                if current.get(key) in (None, "", (), [], {}):
                    current[key] = value
                elif key in {"candidate_bucket", "trade_status_contract"}:
                    current[key] = value
    return _v4_global(_v4_scope, 'list')(merged.values())


def _select_hk_four_lane_body(_v4_scope, /, rows, trade_date, stage_id, raw_artifact_sha256, *, source_status, requested_rows, missing_symbols, cannot_confirm, source_evidence, cap_limit_yi, shadow_capture, shadow_context, shadow_capture_error):
    _v4_global(_v4_scope, '_validate_date')(trade_date)
    _v4_global(_v4_scope, '_validate_market')(stage_id, "HK_CONNECT")
    selected: list[dict[str, Any]] = []
    for source in rows:
        code = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_a_row_value')(source, "code", "ts_code") or "").strip()
        if not code:
            raise _v4_global(_v4_scope, 'SelectionError')("HK selection row code is required")
        scored = _v4_global(_v4_scope, 'hk_four_lane_score')(source, stage_id, cap_limit_yi)
        raw_contract = _v4_global(_v4_scope, 'str')(source.get("trade_status_contract") or scored["trade_status"])
        raw_bucket = _v4_global(_v4_scope, 'str')(source.get("candidate_bucket") or "")
        raw_stage_score = _v4_global(_v4_scope, '_hk_float')(source, "stage_score")
        raw_pct = _v4_global(_v4_scope, '_hk_float')(source, "pct_chg")
        raw_volume = _v4_global(_v4_scope, '_hk_float')(source, "volume_ratio")
        scored_lanes = _v4_global(_v4_scope, 'list')(scored["lane_evidence"])
        if raw_bucket:
            candidate_bucket = raw_bucket
        else:
            cap_value = _v4_global(_v4_scope, '_hk_float')(source, "platform_circular_market_cap_hkd_yi", "circular_market_cap_hkd_yi")
            is_smallcap = cap_value is not None and cap_value <= cap_limit_yi
            if (is_smallcap or scored["continuation_pass"]) and "LIVE_HKCONNECT_GAINER" in scored_lanes:
                candidate_bucket = "SMALLCAP_DEMON_MAIN"
            elif "STRENGTH_THEME_WATCH" in scored_lanes:
                candidate_bucket = "STRENGTH_THEME_WATCH"
            else:
                candidate_bucket = "FOUR_LANE_OBSERVATION"
        lane_evidence = _v4_global(_v4_scope, 'list')(scored["lane_evidence"])
        lane_evidence.extend(
            item
            for item in (
                f"candidate_bucket={candidate_bucket}" if candidate_bucket else "",
                f"trade_status_contract={raw_contract}" if raw_contract else "",
            )
            if item and item not in lane_evidence
        )
        card = _v4_global(_v4_scope, '_stage_card_evidence')(
            source,
            code=code,
            open_price=source.get("open_price"),
            last_price=source.get("last_price"),
            high_price=source.get("high_price"),
            low_price=source.get("low_price"),
            source_last_bar_time=source.get("update_time"),
        )
        selected.append(
            {
                "code": code,
                "score": scored["score"],
                "status": scored["trade_status"],
                "formal_eligible": False,
                **card,
                "source_mode": "HK_CONNECT_FOUR_LANE",
                "candidate_lanes": scored_lanes,
                "lane_evidence": lane_evidence,
                "action_level": "NO_BUY",
                "trade_status": scored["trade_status"],
                "candidate_bucket": candidate_bucket,
                "trade_status_contract": raw_contract,
                "stage_score": scored["score"] if raw_stage_score is None else raw_stage_score,
                "pct_chg": _v4_global(_v4_scope, '_hk_float')(source, "pct_chg") if raw_pct is not None else None,
                "volume_ratio": _v4_global(_v4_scope, '_hk_float')(source, "volume_ratio") if raw_volume is not None else None,
                "d1_status": source.get("d1_status", ""),
                "d1_model_id": source.get("d1_model_id", ""),
                "d1_prob_active": source.get("d1_prob_active", ""),
                "d1_rank": source.get("d1_rank", ""),
                "d1_score": source.get("d1_score", ""),
                "d1_source_evidence": _v4_global(_v4_scope, 'list')(source.get("d1_source_evidence") or ()),
                "second_filter_rank": source.get("second_filter_rank", ""),
                "second_filter_score": source.get("second_filter_score", ""),
                "second_filter_status": source.get("second_filter_status", ""),
                "second_filter_action_level": source.get("second_filter_action_level", ""),
            }
        )
    if stage_id == "STAGE_0925":
        selected.sort(key=_v4_global(_v4_scope, 'hk_0925_pool_rank'))
    else:
        selected.sort(key=_v4_global(_v4_scope, 'hk_legacy_stage_sort_key'), reverse=True)
    # Keep a copy of the full, genuinely sorted selector result before the
    # public Top10 truncation.  The hook is opt-in and side-effect-only; with
    # its default ``None`` value this block performs no work and the existing
    # selector return remains byte-for-byte unchanged.
    sorted_for_shadow = selected
    top10 = _v4_global(_v4_scope, '_top10_contract')(source_evidence)
    legacy = _v4_global(_v4_scope, '_legacy_backfill')(source_evidence) and not top10
    selected = _v4_global(_v4_scope, '_cap_recommendations')(sorted_for_shadow, preserve_legacy=legacy)
    algorithm_sha = (
        _v4_global(_v4_scope, 'ALGORITHM_SHA256') if top10 else _v4_global(_v4_scope, 'LEGACY_ALGORITHM_SHA256')
    )
    if shadow_capture is not None:
        _v4_global(_v4_scope, '_invoke_hk_formula_margin_shadow')(
            shadow_capture,
            raw_rows=rows,
            sorted_rows=sorted_for_shadow,
            production_rows=selected,
            trade_date=trade_date,
            stage_id=stage_id,
            raw_artifact_sha256=raw_artifact_sha256,
            source_status=source_status,
            requested_rows=requested_rows,
            source_evidence=source_evidence,
            shadow_context=shadow_context,
            error_callback=shadow_capture_error,
        )
    return _v4_global(_v4_scope, '_selection_envelope')(
        trade_date=trade_date,
        stage_id=stage_id,
        market="HK_CONNECT",
        raw_artifact_sha256=raw_artifact_sha256,
        source_status=source_status,
        input_rows=_v4_global(_v4_scope, 'len')(rows),
        rows=selected,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot_confirm,
        source_evidence=(*source_evidence, f"algorithm_sha256={algorithm_sha}"),
        algorithm_sha256=algorithm_sha,
    )
