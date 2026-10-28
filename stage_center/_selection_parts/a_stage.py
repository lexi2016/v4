"""stage_center.selection: a_stage (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _a_stage_label_body(_v4_scope, /, window_change_pct, close_position, complete):
    """Port V3 ``_label`` while retaining research-only wording."""
    window_change = _v4_global(_v4_scope, '_number')(window_change_pct)
    close = _v4_global(_v4_scope, '_number')(close_position)
    if not complete:
        return "阶段数据不完整观察", "窗口内分钟线覆盖不足，只能作为部分观察。"
    if window_change >= 2 and close >= 0.65:
        return "阶段强承接观察", "窗口内上涨并靠近高位收，作为阶段观察。"
    if window_change > 0 and close >= 0.45:
        return "阶段承接一般观察", "窗口内小幅上涨或承接一般，等待下一阶段确认。"
    if window_change <= -3:
        return "阶段明显转弱观察", "窗口内明显回落，不能升级为买入依据。"
    return "仅观察", "窗口结构不清晰，只保留观察。"


def _select_a_stage_body(_v4_scope, /, rows, trade_date, stage_id, raw_artifact_sha256, *, source_status, requested_rows, missing_symbols, cannot_confirm, source_evidence, formal_incomplete, source_mode):
    """Materialize A-share stage rows with V3's formal-pool semantics."""
    _v4_global(_v4_scope, '_validate_date')(trade_date)
    _v4_global(_v4_scope, '_validate_market')(stage_id, "A_SHARE")
    normalized_input = [_v4_global(_v4_scope, '_a_normalized_row')(row, source_mode=source_mode) for row in rows]
    for source in rows:
        row_date = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_a_row_value')(source, "trade_date", "verify_date", "date8", "target_date") or "").replace("-", "")
        if row_date and row_date != trade_date:
            raise _v4_global(_v4_scope, 'SelectionError')("A selection trade_date drift")
        row_stage = _v4_global(_v4_scope, 'str')(source.get("stage_id") or "").strip()
        if row_stage and row_stage != stage_id:
            raise _v4_global(_v4_scope, 'SelectionError')("A selection stage_id drift")
    eligible = [row for source, row in _v4_global(_v4_scope, 'zip')(rows, normalized_input) if _v4_global(_v4_scope, '_truthy')(source.get("formal_eligible"))]
    if eligible:
        selected = [row for source, row in _v4_global(_v4_scope, 'zip')(rows, normalized_input) if _v4_global(_v4_scope, '_truthy')(source.get("formal_eligible"))]
    elif formal_incomplete:
        return _v4_global(_v4_scope, '_selection_envelope')(
            trade_date=trade_date,
            stage_id=stage_id,
            market="A_SHARE",
            raw_artifact_sha256=raw_artifact_sha256,
            source_status="CANNOT_CONFIRM",
            input_rows=_v4_global(_v4_scope, 'len')(rows),
            rows=(),
            requested_rows=requested_rows,
            missing_symbols=missing_symbols,
            cannot_confirm=(*cannot_confirm, "FORMAL_INCOMPLETE_WITHOUT_ELIGIBLE_ROWS"),
            source_evidence=source_evidence,
        )
    else:
        selected = normalized_input
    # Python's stable sort is intentional: V3 ranks equal scores according to
    # authoritative source order, never lexical code order.
    top10 = _v4_global(_v4_scope, '_top10_contract')(source_evidence)
    # The explicit production contract has priority over historical replay
    # compatibility evidence.  A production artifact must never widen back
    # to the old unbounded historical slice merely because its source also
    # carries a replay marker.
    legacy = _v4_global(_v4_scope, '_legacy_backfill')(source_evidence) and not top10
    selected = _v4_global(_v4_scope, '_cap_recommendations')(
        _v4_global(_v4_scope, 'sorted')(selected, key=lambda item: item["score"], reverse=True), preserve_legacy=legacy
    )
    algorithm_sha = (
        _v4_global(_v4_scope, 'ALGORITHM_SHA256') if top10 else _v4_global(_v4_scope, 'LEGACY_ALGORITHM_SHA256')
    )
    evidence = (*source_evidence, f"algorithm_sha256={algorithm_sha}", f"source_mode={source_mode}")
    return _v4_global(_v4_scope, '_selection_envelope')(
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
        source_evidence=evidence,
        algorithm_sha256=algorithm_sha,
    )
