"""Empty, date-free V1.1 structural form. These terms are labels, not presets."""

FORM = {
    "schema_version": "ACT082_STEP1_V1_1",
    "scope_status": [None, "IN_SCOPE", "OUT_OF_SCOPE", "UNKNOWN"],
    "background_tags": [
        "BG_PARALLEL_HEAVY_CANNON", "BG_POST_DISASTER_REBUILD", "BG_POISED_TO_LAUNCH",
        "BG_STANDARD_N_STRUCTURE", "BG_FIRST_RED_BRICK", "BG_SINGLE_NEEDLE_REFILL",
        "BG_MULTI_TF_WEEKLY_CONTEXT", "UNKNOWN",
    ],
    "event_stage": [
        "STAGE_0_BASE_OR_ANOMALY_MOTHER", "STAGE_1_B1_PULLBACK_CONSENSUS", "STAGE_2_B2_CONFIRMATION",
        "STAGE_3_B3_TREND_CONTINUATION", "STAGE_4_REBUILD_RECOVERY", "UNKNOWN",
    ],
    "confirmation_timing": {
        "event_id": None, "linked_prior_invalidated_event_id": None, "mother_anchor_date_relative_bar": None,
        "stage_confirm_bar": None, "prior_damage_preserved": ["Y", "N", "UNKNOWN"],
    },
    "risk_clues": [
        "CLUE_THREE_QUARTER_BEAR_VOL", "CLUE_UPPER_SHADOW_DIVERGENCE", "CLUE_FAR_FROM_WY", "UNKNOWN",
    ],
    "signal_invalidated": [
        "INV_ANCHOR_LOW_BROKEN", "INV_DOWNTREND_CONTINUATION", "INV_S1_HIGH_VOLUME_STALL", "UNKNOWN",
    ],
    "exit_reference": {
        "exit_price_reference": None, "exit_time_discipline": None,
        "references": {
            "B1": "买入K线低点或前N型低点",
            "B2": "前N型低点，B2阳线底适用情境按1006原课字符9739至9899",
            "B3": "B3阳线低点或B2中长阳中间价位，按1006原课字符8513至8554",
            "S1": "高量滞涨防守纪律",
        },
    },
    "evidence_sufficiency": [
        "SUFFICIENT_D_ONLY", "PARTIAL_MISSING_LEFT_MOTHER", "PARTIAL_MISSING_WEEKLY_OR_MARKET",
        "INSUFFICIENT_EVIDENCE",
    ],
    "empty_answer": {
        "blind_id": None, "scope_status": None, "background_tags": None, "event_stage": None,
        "event_id": None, "linked_prior_invalidated_event_id": None, "mother_anchor_date_relative_bar": None,
        "stage_confirm_bar": None, "prior_damage_preserved": None, "risk_clues": None, "signal_invalidated": None,
        "exit_price_reference": None, "exit_time_discipline": None, "evidence_sufficiency": None,
    },
    "contract": [
        "范围前置。OUT_OF_SCOPE 样本五维字段填 N/A；缺证据的具体字段填 UNKNOWN。",
        "仅用截至 D 的观察；重建建新事件，旧破锚永久保留；风险线索不等于失效或退出。",
        "不猜测未给出的周线、大盘或母体信息。砖型图课堂同版未认证。",
    ],
}

