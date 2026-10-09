"""Multiline schema and keyword values; called at original assignment time."""
from ._namespace import read_global as _v4_global


def _value_SELECTION_ARTIFACT_FIELDS_V1(_v4_scope, /):
    return (
        (
    "code",
    "score",
    "rank",
    "status",
    "formal_eligible",
    "support",
    "pressure",
    "invalidation",
    "source_mode",
    "lane_evidence",
    "action_level",
    "trade_status",
)
    )


def _value_SELECTION_ARTIFACT_FIELDS_V2(_v4_scope, /):
    return (
        (
    *_v4_global(_v4_scope, 'SELECTION_ARTIFACT_FIELDS_V1'),
    "name",
    "stock_name",
    "current_change_pct",
    "open_price",
    "last_price",
    "high_price",
    "low_price",
    "source_last_bar_time",
    "next_validation_time",
    # V3 and V3.5 use different public spellings.  Persist both in the
    # producer so neither consumer has to infer missing evidence.
    "support_primary_price",
    "pressure_price",
    "invalidation_price",
)
    )


def _value_LEGACY_ALGORITHM_MANIFEST(_v4_scope, /):
    return (
        {
    "algorithm_id": _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'),
    "version": "stage_center.selection.v2",
    "a_share": {
        "score": "round(clamp(50 + 8*window_change_pct + 25*close_position + 3*min(amount/1e8,4) - (0 if complete else 18)),0,100),2)",
        "sort": "score_desc_python_stable_input_order",
        "formal_filter": "eligible_rows_if_any_else_empty_when_FORMAL_INCOMPLETE_else_all",
    },
    "hk_connect": {
        "four_lane_score_base": 42,
        "caps": {"small_cap_yi": 100.0, "continuation_soft_yi": 150.0},
        "action_boundary": "all_actions_NO_BUY_trade_status_research_only",
        "0925": "preserve_second_filter_rank_and_order",
    },
}
    )


def _value_LEGACY_A_SHARE_LIVE_ALGORITHM_MANIFEST(_v4_scope, /):
    return (
        {
    "algorithm_id": _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'),
    "version": "stage_center.selection.a_share_live.v1",
    "score": "round(50 + 9*window_change_pct + 25*close_position + min(amount/1e8,6)*2.5 + bid_pressure + clamp(pool_score/125,0,1)*8,6)",
    "bid_pressure": "clamp((bid_vol1/(bid_vol1+ask_vol1)-0.5)*12,-6,6), else 0 when either side missing or sum<=0",
    "stage_0925": "round(50 + clamp(gap_change_pct,-10,10)*10 + amount_bonus + bid_pressure + clamp(pool_score/125,0,1)*3,6)",
    "sort": "(-stage_score,-qmt_amount,formal_rank,stock_code); STAGE_0925 uses (-stage_score,-qmt_gap_pct,-int(qmt_amount),stock_code)",
    "research_bonus": "min((news_quality_score+research_quality_score)/40,5)",
}
    )


def _value_ALGORITHM_SHA_ALLOWLIST(_v4_scope, /):
    return (
        _v4_global(_v4_scope, 'frozenset')(
    {
        _v4_global(_v4_scope, 'LEGACY_ALGORITHM_SHA256'),
        _v4_global(_v4_scope, 'ALGORITHM_SHA256'),
        _v4_global(_v4_scope, 'LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256'),
        _v4_global(_v4_scope, 'A_SHARE_LIVE_ALGORITHM_SHA256'),
        _v4_global(_v4_scope, 'PRE_V11_TOP10_ALGORITHM_SHA256'),
        _v4_global(_v4_scope, 'V11_PIT_TOP10_ALGORITHM_SHA256'),
    }
)
    )


def _value___all__(_v4_scope, /):
    return (
        [
    "ALGORITHM_MANIFEST",
    "ALGORITHM_SHA256",
    "TOP10_ALGORITHM_MANIFEST",
    "LEGACY_ALGORITHM_SHA256",
    "A_SHARE_LIVE_ALGORITHM_MANIFEST",
    "A_SHARE_LIVE_ALGORITHM_SHA256",
    "A_SHARE_LIVE_TOP10_ALGORITHM_MANIFEST",
    "LEGACY_A_SHARE_LIVE_ALGORITHM_SHA256",
    "SELECTION_ARTIFACT_FIELDS_V1",
    "SELECTION_ARTIFACT_FIELDS_V2",
    "SELECTION_ARTIFACT_FIELDS",
    "SelectionError",
    "SelectionStore",
    "a_stage_label",
    "a_stage_score",
    "hk_four_lane_score",
    "merge_hk_four_lane_candidates",
    "live_stage_quality_score",
    "publish_selection",
    "read_verified_selection",
    "select_a_0925_auction",
    "select_a_live_stage",
    "select_a_stage",
    "select_hk_0925_second_filter",
    "select_hk_0925_d1_reference",
    "select_hk_four_lane",
    "stage_row_sort_key",
]
    )
