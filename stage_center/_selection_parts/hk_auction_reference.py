"""stage_center.selection: hk_auction_reference (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _select_hk_0925_d1_reference_body(_v4_scope, /, rows, trade_date, raw_artifact_sha256, *, source_status, requested_rows, missing_symbols, cannot_confirm, source_evidence):
    """Expose the old-V3 D-1 Top10 while the exact 09:20 filter is missing.

    This is deliberately a reference lane, not a second-filter result.  It
    carries the frozen D-1 rank/name/score only, leaves quote fields empty,
    and keeps the envelope ``CANNOT_CONFIRM`` so consumers cannot treat the
    rows as a confirmed opening recommendation.
    """
    _v4_global(_v4_scope, '_validate_date')(trade_date)
    _v4_global(_v4_scope, '_validate_market')("STAGE_0925", "HK_CONNECT")
    indexed: list[tuple[int, int, Mapping[str, Any]]] = []
    for index, source in _v4_global(_v4_scope, 'enumerate')(rows, start=1):
        row_date = _v4_global(_v4_scope, 'str')(
            _v4_global(_v4_scope, '_a_row_value')(source, "target_date", "trade_date", "date8") or ""
        ).replace("-", "")
        if row_date and row_date != trade_date:
            raise _v4_global(_v4_scope, 'SelectionError')("HK 0925 D1 reference target_date drift")
        code = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_a_row_value')(source, "code", "ts_code", "stock_code") or "").strip()
        if not code:
            raise _v4_global(_v4_scope, 'SelectionError')("HK 0925 D1 reference row code is required")
        raw_rank = _v4_global(_v4_scope, '_optional_number')(
            _v4_global(_v4_scope, '_a_row_value')(source, "pool_rank", "d1_rank", "rank")
        )
        indexed.append((_v4_global(_v4_scope, 'int')(raw_rank) if raw_rank is not None else index, index, source))

    indexed.sort(key=lambda item: (item[0], item[1]))
    normalized: list[dict[str, Any]] = []
    for output_rank, (rank, _index, source) in _v4_global(_v4_scope, 'enumerate')(
        indexed[:_v4_global(_v4_scope, 'STAGE_RECOMMENDATION_LIMIT')], start=1
    ):
        code = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_a_row_value')(source, "code", "ts_code", "stock_code") or "").strip()
        name = _v4_global(_v4_scope, '_a_row_value')(source, "name", "stock_name", "security_name", "display_name")
        score = _v4_global(_v4_scope, '_optional_number')(
            _v4_global(_v4_scope, '_a_row_value')(source, "pool_score", "score_prob_active", "d1_score", "score")
        )
        lane_evidence = _v4_global(_v4_scope, 'list')(
            _v4_global(_v4_scope, 'dict').fromkeys(
                (
                    "D1_PRESELECT_REFERENCE",
                    "WAITING_0920_SECOND_FILTER",
                    "exact_date=true",
                    "post_open_snapshot_used=false",
                    "future_snapshot_used=false",
                    *(_v4_global(_v4_scope, 'str')(item) for item in (source.get("source_evidence") or ()) if _v4_global(_v4_scope, 'str')(item)),
                )
            )
        )
        normalized.append(
            {
                "code": code,
                "name": name,
                "stock_name": name,
                "score": 0.0 if score is None else _v4_global(_v4_scope, 'round')(score, 6),
                "rank": output_rank,
                "status": "WAITING_0920_SECOND_FILTER",
                "formal_eligible": False,
                "support": None,
                "pressure": None,
                "invalidation": None,
                "source_mode": "HK_CONNECT_D1_PRESELECT_REFERENCE",
                "lane_evidence": lane_evidence,
                "candidate_lanes": ["D1_PRESELECT_REFERENCE"],
                "action_level": "NO_BUY",
                "trade_status": "WATCH_ONLY",
                "d1_status": source.get("d1_status", "STRICT_0_2_READY"),
                "d1_model_id": source.get(
                    "d1_model_id",
                    source.get("model_id", source.get("model", "prob_active")),
                ),
                "d1_prob_active": source.get(
                    "d1_prob_active", source.get("prob_active", source.get("score_prob_active", ""))
                ),
                "d1_rank": source.get("d1_rank", source.get("pool_rank", rank)),
                "d1_score": source.get("d1_score", source.get("pool_score", score)),
                "d1_source_evidence": _v4_global(_v4_scope, 'list')(source.get("d1_source_evidence") or ()),
                "second_filter_status": "WAITING_0920_SECOND_FILTER",
                "second_filter_rank": None,
                "second_filter_score": None,
                "current_change_pct": None,
                "open_price": None,
                "last_price": None,
                "high_price": None,
                "low_price": None,
                "source_last_bar_time": None,
                "next_validation_time": "09:20:05",
                "support_primary_price": None,
                "pressure_price": None,
                "invalidation_price": None,
            }
        )
    evidence = _v4_global(_v4_scope, 'tuple')(
        _v4_global(_v4_scope, 'dict').fromkeys(
            (
                *source_evidence,
                "route=old_v3_opening_second_screen_d1_fallback",
                "D1_PRESELECT_REFERENCE",
                "WAITING_0920_SECOND_FILTER",
                "exact_date=true",
                "post_open_snapshot_used=false",
                "future_snapshot_used=false",
                "selection_contract=V3_TOP10_RECOMMENDATION",
            )
        )
    )
    cannot = _v4_global(_v4_scope, 'tuple')(
        _v4_global(_v4_scope, 'dict').fromkeys(
            (
                *cannot_confirm,
                "WAITING_0920_SECOND_FILTER",
                "HK_0920_EXACT_SECOND_FILTER_UNAVAILABLE",
            )
        )
    )
    algorithm_sha = _v4_global(_v4_scope, 'ALGORITHM_SHA256')
    result = _v4_global(_v4_scope, '_selection_envelope')(
        trade_date=trade_date,
        stage_id="STAGE_0925",
        market="HK_CONNECT",
        raw_artifact_sha256=raw_artifact_sha256,
        source_status="CANNOT_CONFIRM" if source_status in {"CANNOT_CONFIRM", "READ_FAILED"} else source_status,
        input_rows=_v4_global(_v4_scope, 'len')(rows),
        rows=normalized,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot,
        source_evidence=(*evidence, f"algorithm_sha256={algorithm_sha}"),
        algorithm_sha256=algorithm_sha,
    )
    # ``_selection_envelope`` normally marks rows under a failed source as
    # PARTIAL_WITH_ROWS.  This lane is intentionally stronger: rows are only
    # a D-1 reference and the stage remains unconfirmed at every level.
    if normalized:
        result["selection_status"] = "CANNOT_CONFIRM"
    return result
