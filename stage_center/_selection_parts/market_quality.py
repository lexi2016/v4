"""stage_center.selection: market_quality (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _live_stage_quality_score_body(_v4_scope, /, qmt, candidate, stage_id):
    """Port Windows V3 ``live_stage_quality_score`` without backend imports."""
    open_price = _v4_global(_v4_scope, '_live_safe_float')(qmt.get("open")) or _v4_global(_v4_scope, '_live_safe_float')(qmt.get("lastPrice"))
    last_price = _v4_global(_v4_scope, '_live_safe_float')(qmt.get("lastPrice"))
    prev_close = _v4_global(_v4_scope, '_live_safe_float')(qmt.get("lastClose"))
    high_price = _v4_global(_v4_scope, '_live_safe_float')(qmt.get("high")) or last_price
    low_price = _v4_global(_v4_scope, '_live_safe_float')(qmt.get("low")) or last_price
    amount = _v4_global(_v4_scope, '_live_safe_float')(qmt.get("amount")) or 0.0
    bid_vol1 = _v4_global(_v4_scope, '_live_first_float')(qmt.get("bidVol"))
    ask_vol1 = _v4_global(_v4_scope, '_live_first_float')(qmt.get("askVol"))
    pool_score = _v4_global(_v4_scope, '_live_safe_float')(candidate.get("score")) or 0.0
    gap_change = _v4_global(_v4_scope, '_live_pct_change')(open_price, prev_close) or 0.0
    window_change = _v4_global(_v4_scope, '_live_pct_change')(last_price, open_price) or 0.0
    amount_bonus = _v4_global(_v4_scope, 'min')(amount / 100_000_000.0, 6.0) * 2.5
    bid_pressure = _v4_global(_v4_scope, '_live_bid_pressure')(bid_vol1, ask_vol1)
    pool_ratio = _v4_global(_v4_scope, '_live_bounded')(pool_score / 125.0, 0.0, 1.0)
    if stage_id == "STAGE_0925":
        score = (
            50.0
            + _v4_global(_v4_scope, '_live_bounded')(gap_change, -10.0, 10.0) * 10.0
            + amount_bonus
            + bid_pressure
            + pool_ratio * 3.0
        )
        return _v4_global(_v4_scope, 'round')(score, 6)
    score = (
        50.0
        + window_change * 9.0
        + _v4_global(_v4_scope, '_live_close_position')(last_price, high_price, low_price) * 25.0
        + amount_bonus
        + bid_pressure
        + pool_ratio * 8.0
    )
    return _v4_global(_v4_scope, 'round')(score, 6)


def _stage_row_sort_key_body(_v4_scope, /, row):
    """Port Windows V3 ``stage_row_sort_key`` exactly."""
    gap_value = _v4_global(_v4_scope, '_live_safe_float')(row.get("qmt_gap_pct"))
    gap_tiebreak = -999999.0 if gap_value is None else gap_value
    amount_tiebreak = _v4_global(_v4_scope, '_live_safe_float')(row.get("qmt_amount")) or 0.0
    if row.get("stage_id") == "STAGE_0925":
        second_key = gap_tiebreak
        third_key = -_v4_global(_v4_scope, 'int')(amount_tiebreak)
    else:
        second_key = amount_tiebreak
        third_key = _v4_global(_v4_scope, '_live_rank_int')(row.get("stage1_formal_rank") or row.get("pool_rank"))
    acquisition_rank = row.get("acquisition_rank", row.get("source_order"))
    if acquisition_rank not in (None, ""):
        try:
            tie_break = f"{_v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'float')(_v4_global(_v4_scope, 'str')(acquisition_rank))):09d}"
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
            tie_break = _v4_global(_v4_scope, 'str')(acquisition_rank)
    else:
        # Historical callers that do not carry an explicit acquisition rank
        # retain the old lexical fallback. Production rows always carry the
        # validated raw ``batch_index`` so ties cannot be filled by code order.
        tie_break = _v4_global(_v4_scope, 'str')(row.get("stock_code") or "")
    score_value = _v4_global(_v4_scope, '_live_safe_float')(row.get("stage_score"))
    return (
        -(-999999.0 if score_value is None else score_value),
        -second_key,
        third_key,
        tie_break,
    )


def _hk_legacy_stage_sort_key_body(_v4_scope, /, row):
    """Port the Windows V3 HK non-09:25 ordering tuple verbatim.

    ``hk_demon_service`` sorts the already-scored rows in descending tuple
    order.  The contract gate is deliberately evaluated before any later
    WATCH_ONLY presentation normalization.
    """
    bucket = _v4_global(_v4_scope, 'str')(row.get("candidate_bucket") or "")
    bucket_weight = {
        "SMALLCAP_DEMON_MAIN": 2,
        "FOUR_LANE_OBSERVATION": 1,
    }.get(bucket, 0)
    contract = _v4_global(_v4_scope, 'str')(row.get("trade_status_contract") or row.get("trade_status") or "")
    no_trade_gate = 0 if contract == "NO_TRADE" else 1
    stage_score_value = _v4_global(_v4_scope, '_hk_float')(row, "stage_score", "score")
    pct_chg_value = _v4_global(_v4_scope, '_hk_float')(row, "pct_chg")
    volume_ratio_value = _v4_global(_v4_scope, '_hk_float')(row, "volume_ratio")
    stage_score = 0.0 if stage_score_value is None else stage_score_value
    # Old V3 uses ``item.get("pct_chg") or -999`` and
    # ``item.get("volume_ratio") or 0`` verbatim: an explicit numeric zero is
    # therefore treated like a missing/empty value, while negative and positive
    # observations retain their values.
    pct_chg = pct_chg_value or -999.0
    volume_ratio = volume_ratio_value or 0.0
    return bucket_weight, no_trade_gate, stage_score, pct_chg, volume_ratio
