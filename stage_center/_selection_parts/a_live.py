"""stage_center.selection: a_live (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _select_a_live_stage_body(_v4_scope, /, rows, trade_date, stage_id, raw_artifact_sha256, *, source_status, requested_rows, missing_symbols, cannot_confirm, source_evidence):
    """Materialize A rows using the Windows V3 live-stage formula.

    Each source row carries a ``qmt`` snapshot and a ``candidate`` formal-pool
    record (or their flattened equivalents).  This deliberately bypasses the
    older minute-bar ``select_a_stage`` formula: historical 09:40-09:45 rows
    must be recomputed from the exact pytdx adapter and formal candidate pool.
    """
    _v4_global(_v4_scope, '_validate_date')(trade_date)
    _v4_global(_v4_scope, '_validate_market')(stage_id, "A_SHARE")
    selected: list[dict[str, Any]] = []
    for source in rows:
        code = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_a_row_value')(source, "code", "stock_code", "ts_code") or "").strip()
        if not code:
            raise _v4_global(_v4_scope, 'SelectionError')("A live stage row code is required")
        row_date = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_a_row_value')(source, "trade_date", "verify_date", "date8", "target_date") or "").replace("-", "")
        if row_date and row_date != trade_date:
            raise _v4_global(_v4_scope, 'SelectionError')("A live stage trade_date drift")
        row_stage = _v4_global(_v4_scope, 'str')(source.get("stage_id") or "").strip()
        if row_stage and row_stage != stage_id:
            raise _v4_global(_v4_scope, 'SelectionError')("A live stage stage_id drift")
        qmt_value = source.get("qmt")
        qmt = _v4_global(_v4_scope, 'dict')(qmt_value) if _v4_global(_v4_scope, 'isinstance')(qmt_value, _v4_global(_v4_scope, 'Mapping')) else {
            "open": source.get("qmt_open", source.get("open")),
            "lastPrice": source.get("qmt_last", source.get("lastPrice", source.get("price"))),
            "lastClose": source.get("qmt_prev_close", source.get("lastClose")),
            "high": source.get("qmt_high", source.get("high")),
            "low": source.get("qmt_low", source.get("low")),
            "amount": source.get("qmt_amount", source.get("amount")),
            "bidVol": source.get("qmt_bid_vol1", source.get("bidVol")),
            "askVol": source.get("qmt_ask_vol1", source.get("askVol")),
        }
        candidate_value = source.get("candidate")
        candidate = _v4_global(_v4_scope, 'dict')(candidate_value) if _v4_global(_v4_scope, 'isinstance')(candidate_value, _v4_global(_v4_scope, 'Mapping')) else {
            "score": source.get("pool_score", source.get("candidate_score", source.get("score", 0.0))),
        }
        live_score = _v4_global(_v4_scope, 'live_stage_quality_score')(qmt, candidate, stage_id)
        news_score = _v4_global(_v4_scope, '_live_safe_float')(source.get("news_quality_score")) or 0.0
        research_score = _v4_global(_v4_scope, '_live_safe_float')(source.get("research_quality_score")) or 0.0
        research_bonus = _v4_global(_v4_scope, 'min')((news_score + research_score) / 40.0, 5.0)
        stage_score = _v4_global(_v4_scope, 'round')(live_score + research_bonus, 6)
        card = _v4_global(_v4_scope, '_stage_card_evidence')(
            source,
            code=code,
            open_price=qmt.get("open"),
            last_price=qmt.get("lastPrice"),
            high_price=qmt.get("high"),
            low_price=qmt.get("low"),
        )
        formal_eligible = _v4_global(_v4_scope, '_truthy')(source.get("formal_eligible"), False)
        lane_evidence = _v4_global(_v4_scope, 'list')(source.get("lane_evidence") or ())
        if formal_eligible:
            if not lane_evidence:
                lane_evidence = ["A_SHARE_FORMAL_POOL"]
        else:
            # A stale upstream lane marker is not authority.  Non-formal
            # acquisition rows must not retain the formal-pool identity.
            lane_evidence = [item for item in lane_evidence if item != "A_SHARE_FORMAL_POOL"]
            if "STAGE_ACQUISITION_UNIVERSE" not in lane_evidence:
                lane_evidence.append("STAGE_ACQUISITION_UNIVERSE")
        stage_row = {
            "code": code,
            "score": stage_score,
            "status": "WATCH_ONLY",
            "formal_eligible": formal_eligible,
            **card,
            "source_mode": "A_SHARE_WINDOWS_V3_LIVE_STAGE",
            "lane_evidence": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys((*lane_evidence, "WINDOWS_V3_LIVE_FORMULA"))),
            "action_level": "WATCH_ONLY",
            "trade_status": "WATCH_ONLY",
            "stage_id": stage_id,
            "trade_date": trade_date,
            "stage_score": stage_score,
            "stage1_formal_rank": _v4_global(_v4_scope, 'str')(source.get("stage1_formal_rank") or source.get("formal_rank") or ""),
            "pool_score": _v4_global(_v4_scope, 'str')(candidate.get("score") or ""),
            "qmt_amount": _v4_global(_v4_scope, '_live_safe_float')(qmt.get("amount")) or 0.0,
            "qmt_gap_pct": _v4_global(_v4_scope, '_live_pct_change')(
                _v4_global(_v4_scope, '_live_safe_float')(qmt.get("open")) or _v4_global(_v4_scope, '_live_safe_float')(qmt.get("lastPrice")),
                _v4_global(_v4_scope, '_live_safe_float')(qmt.get("lastClose")),
            ) or 0.0,
            "stock_code": code,
            "acquisition_rank": source.get("acquisition_rank", source.get("source_order", "")),
            "news_quality_score": news_score,
            "research_quality_score": research_score,
            "research_bonus": research_bonus,
            "latest_research_slot": source.get("latest_research_slot", ""),
            "research_delta_hits": source.get("research_delta_hits", 0),
            "news_research_reason": source.get("news_research_reason", ""),
            "source_health": source.get("source_health", ""),
        }
        selected.append(stage_row)
    top10 = _v4_global(_v4_scope, '_top10_contract')(source_evidence)
    legacy = _v4_global(_v4_scope, '_legacy_backfill')(source_evidence) and not top10
    selected = _v4_global(_v4_scope, '_cap_recommendations')(_v4_global(_v4_scope, 'sorted')(selected, key=_v4_global(_v4_scope, 'stage_row_sort_key')), preserve_legacy=legacy)
    algorithm_sha = (
        _v4_global(_v4_scope, 'A_SHARE_LIVE_ALGORITHM_SHA256') if top10 else _v4_global(_v4_scope, 'LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256')
    )
    envelope = _v4_global(_v4_scope, '_selection_envelope')(
        trade_date=trade_date,
        stage_id=stage_id,
        market="A_SHARE",
        raw_artifact_sha256=raw_artifact_sha256,
        source_status=source_status,
        input_rows=_v4_global(_v4_scope, 'len')(rows),
        rows=selected,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot_confirm,
        source_evidence=(
            *source_evidence,
            f"algorithm_sha256={algorithm_sha}",
            "formula=windows_v3_live_stage_quality_score",
            "sort=windows_v3_stage_row_sort_key",
        ),
        algorithm_sha256=algorithm_sha,
    )
    return envelope
