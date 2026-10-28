"""stage_center.selection: hk_formula_score (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _hk_four_lane_score_body(_v4_scope, /, row, stage_id, cap_limit_yi):
    """Port V3 ``_four_lane_score`` and return its evidence without mutation."""
    stage = stage_id or _v4_global(_v4_scope, 'str')(row.get("stage_id") or "STAGE_0930_0935")
    lanes = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, 'str')(item) for item in (row.get("candidate_lanes") or ([row.get("lane")] if row.get("lane") else []))))
    # Never trust an adapter's precomputed continuation flag; the V3 lane,
    # stage, cap, strength, and turnover evidence is recomputed here.
    continuation_pass = _v4_global(_v4_scope, '_hk_continuation_passes')(row, stage, cap_limit_yi)
    pct = _v4_global(_v4_scope, '_hk_float')(row, "pct_chg")
    window_change = _v4_global(_v4_scope, '_hk_float')(row, "stage_window_change_pct", "window_change_pct")
    volume_ratio = _v4_global(_v4_scope, '_hk_float')(row, "volume_ratio")
    turnover_yi = _v4_global(_v4_scope, '_hk_money_yi')(row)
    turnover_rate = _v4_global(_v4_scope, '_hk_float')(row, "turnover_rate", "futu_turnover_rate")
    platform_cap_yi = _v4_global(_v4_scope, '_hk_float')(row, "platform_circular_market_cap_hkd_yi", "circular_market_cap_hkd_yi")
    offer_float_yi = _v4_global(_v4_scope, '_hk_float')(row, "offer_float_market_cap_hkd_yi")
    score = 42
    reasons: list[str] = []
    risks: list[str] = []
    if "LIVE_HKCONNECT_GAINER" in lanes:
        score += 16
        reasons.append("港股通实时强势")
    if "PREOPEN_AUCTION_CONTINUATION" in lanes:
        score += 4
        reasons.append("09:20二筛命中")
    if continuation_pass:
        score += 8
        reasons.append("09:20二筛后续阶段承接确认")
    if platform_cap_yi is not None:
        if platform_cap_yi <= cap_limit_yi:
            score += 14
            reasons.append(f"平台流通市值{platform_cap_yi:.2f}亿港元<=100亿")
        elif continuation_pass:
            score += 4
            reasons.append(f"平台流通市值{platform_cap_yi:.2f}亿港元>100亿但<=150亿，且二筛延续确认")
        else:
            score -= 12
            risks.append(f"平台流通市值{platform_cap_yi:.2f}亿港元>100亿，降为强势主题观察")
            if "STRENGTH_THEME_WATCH" not in lanes:
                lanes.append("STRENGTH_THEME_WATCH")
    if offer_float_yi is not None:
        if "LOW_FLOAT_FILTER" not in lanes:
            lanes.append("LOW_FLOAT_FILTER")
        if offer_float_yi <= 20:
            score += 8
            reasons.append(f"非AH实际流通估算{offer_float_yi:.2f}亿港元")
        elif offer_float_yi <= 50:
            score += 4
            reasons.append(f"非AH中低实际流通估算{offer_float_yi:.2f}亿港元")
    elif "LOW_FLOAT_FILTER" in lanes:
        score += 4
        reasons.append("非AH低流通名单命中")
    if pct is not None:
        if pct >= 15:
            score += 22
            reasons.append(f"涨幅{pct:.2f}%")
            risks.append("盘中涨幅较大，不能追高，必须等回踩承接")
        elif pct >= 10:
            score += 18
            reasons.append(f"涨幅{pct:.2f}%")
        elif pct >= 5:
            score += 12
            reasons.append(f"涨幅{pct:.2f}%")
        elif pct > 0:
            score += 5
            reasons.append(f"红盘{pct:.2f}%")
        elif pct <= -5:
            score -= 10
            risks.append(f"当日下跌{pct:.2f}%")
    if volume_ratio is not None:
        if volume_ratio >= 3:
            score += 12
            reasons.append(f"量比{volume_ratio:.2f}")
        elif volume_ratio >= 1.5:
            score += 8
            reasons.append(f"量比{volume_ratio:.2f}")
        elif volume_ratio >= 1:
            score += 4
            reasons.append(f"量比{volume_ratio:.2f}")
        else:
            score -= 6
            risks.append("量比不足")
    if turnover_yi is not None:
        if turnover_yi >= 1:
            score += 7
            reasons.append(f"成交额{turnover_yi:.2f}亿港元")
        elif turnover_yi >= 0.2:
            score += 3
            reasons.append(f"成交额{turnover_yi:.2f}亿港元")
    if turnover_rate is not None:
        if turnover_rate >= 20:
            score += 10
            reasons.append(f"换手{turnover_rate:.2f}%")
        elif turnover_rate >= 8:
            score += 7
            reasons.append(f"换手{turnover_rate:.2f}%")
        elif turnover_rate >= 3:
            score += 4
            reasons.append(f"换手{turnover_rate:.2f}%")
    if "OLD_DEMON_MEMORY" in lanes:
        score += 5
        reasons.append("老妖记忆命中")
    if "NEW_HKCONNECT_BATCH" in lanes:
        score += 3
        reasons.append("新调入名单命中")
    if _v4_global(_v4_scope, 'len')(lanes) >= 3:
        score += 4
        reasons.append("多路共振")
    if "STRENGTH_THEME_WATCH" in lanes and not continuation_pass:
        score = _v4_global(_v4_scope, 'min')(score, 74)
    if stage in {"STAGE_1300_1315", "STAGE_1445_1500", "STAGE_1545_1555"} and pct is not None and pct >= 5:
        score += 4
        reasons.append("午后/尾盘仍保持强度")
    if pct is not None and pct < 3:
        score = _v4_global(_v4_scope, 'min')(score, 78)
        risks.append("涨幅不足3%，只能观察承接，不能排在妖股主榜前列")
    elif pct is not None and pct < 5:
        score = _v4_global(_v4_scope, 'min')(score, 88)
        risks.append("涨幅不足5%，需二次放量才可升级")
    if continuation_pass and window_change is not None:
        if window_change >= 3:
            score += 6
            reasons.append(f"阶段涨幅{window_change:.2f}%且守住09:20参考价")
        elif window_change < 0:
            score -= 8
            risks.append("09:20二筛后阶段转弱")
    if "OPENING_INITIAL_SCREEN" in lanes:
        status = "OPENING_INITIAL_SCREEN_RESEARCH_ONLY" if score >= 45 else "WATCH_ONLY"
    elif "PREOPEN_AUCTION_CONTINUATION" in lanes and score >= 72:
        status = "WAIT_FOR_TRIGGER"
    elif "STRENGTH_THEME_WATCH" in lanes:
        status = "WATCH_ONLY"
    elif score >= 84:
        status = "WAIT_FOR_TRIGGER"
    elif score >= 62:
        status = "WATCH_ONLY"
    else:
        status = "NO_TRADE"
    return {
        "score": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, '_clamp')(score)),
        "lane_evidence": lanes,
        "reasons": reasons,
        "risks": risks,
        "trade_status": status,
        "explanation": "；".join(reasons[:6]) if reasons else "四路融合证据不足",
        "continuation_pass": continuation_pass,
    }
