"""Frozen HK Connect opening second-filter v1.1 champion.

This is a modular port of the legacy graph nodes
``build_hkconnect_stage0925_preselect_pool`` and
``build_hkconnect_0920_auction_second_filter``.  The 0.2 model supplies only
D-1 Top100 membership; this module performs the cutoff-safe same-day rerank.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from infrastructure.data_store import _date


MODEL_ID = "hkconnect_opening_second_filter_v1_1"
MODEL_VERSION = "1.1"
CHAMPION_CONTRACT = "old_v3_rule_guardrail_with_hardcap_and_0920_reference_layer"
SCHEMA_VERSION = "v3_5.opening_second_filter.v1"
SIGNAL_CUTOFF = "09:19:59"
PUBLICATION_TIME = "09:20:00"
TOP_N = 20
STRICT_FAILURE_PCT = -2.2
LEVEL_BREAKOUT_CONFIRM_PCT = 0.5
LEVEL_NEAR_PRESSURE_PCT = 1.0
LEVEL_SUPPORT_EXTENDED_PCT = 8.0
LEVEL_GOOD_RISK_REWARD = 2.0
LEVEL_POOR_RISK_REWARD = 1.0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HK_ONLY_CANNOT_CONFIRM_MARKERS = (
    "HKCONNECT",
    "HK_CONNECT",
    "HKD",
    "港元",
    "港股",
    "BROKER_QUEUE",
    "BROKER QUEUE",
    "经纪队列",
    "經紀隊列",
    "SEAT_EVIDENCE",
    "DOMINANT_BROKER",
    "FUTU",
)


def _number(value: Any, default: float | None = None) -> float | None:
    if value in (None, "", "N/A", "nan") or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first(row: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def _hk_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("HK."):
        digits = text.split(".", 1)[1]
    elif text.endswith(".HK"):
        digits = text.split(".", 1)[0]
    else:
        digits = "".join(character for character in text if character.isdigit())
    return f"HK.{digits.zfill(5)}" if digits else ""


def _ts_code(code: str) -> str:
    return f"{code.split('.', 1)[1]}.HK_CONNECT"


def _validate_source_evidence(value: Mapping[str, Any]) -> dict[str, str]:
    expected = {
        "d1_pool_sha256",
        "auction_source_sha256",
        "source_output_sha256",
    }
    if set(value) != expected:
        raise ValueError("v1.1 source evidence must contain the three frozen SHA-256 fields")
    normalized = {key: str(value[key]).lower() for key in expected}
    if any(not _SHA256.fullmatch(digest) for digest in normalized.values()):
        raise ValueError("invalid v1.1 source evidence SHA-256")
    return normalized


def build_v11_opening_second_filter(
    preselect_rows: Sequence[Mapping[str, Any]],
    auction_rows: Sequence[Mapping[str, Any]],
    *,
    trade_date: str,
    signal_date: str,
    source_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Reproduce the frozen legacy champion rerank without old-path access."""
    trade_date = _date(trade_date)
    signal_date = _date(signal_date)
    evidence = _validate_source_evidence(source_evidence)
    preselect_by_code = {
        code: row
        for row in preselect_rows
        if (code := _hk_code(_first(row, "code", "symbol", "ts_code", "stock_code")))
    }
    output: list[dict[str, Any]] = []
    for auction_rank, auction in enumerate(auction_rows, start=1):
        code = _hk_code(_first(auction, "code", "futu_code", "symbol", "ts_code"))
        if not code or code not in preselect_by_code:
            continue
        preselect = preselect_by_code[code]
        score = _number(_first(auction, "stage1_ref_score", "auction_entry_score"), None)
        gap = _number(_first(auction, "auction_ref_gap_pct", "opening_gap_proxy_pct"), None)
        depth = _number(auction.get("visible_depth_hkd"), 0.0) or 0.0
        spread = _number(auction.get("spread_pct"), 0.0)
        if score is None:
            score = 0.0
            if gap is not None and 0 <= gap <= 5:
                score += 30
            if depth >= 1_000_000:
                score += min(depth / 10_000_000, 3) * 10
            if spread is not None and spread <= 1:
                score += 10
        if score >= 70 and (gap is None or gap <= 8):
            status = "AUCTION_SECOND_FILTER_PRIORITY"
        elif score >= 50:
            status = "AUCTION_SECOND_FILTER_WATCH"
        else:
            status = "AUCTION_SECOND_FILTER_LOW_PRIORITY"
        if gap is not None and gap > 8:
            status = "AUCTION_HIGH_OPEN_NO_CHASE"
        reference_price = _number(_first(auction, "last_price", "price"), None)
        strict_failure_price = (
            round(reference_price * (1 + STRICT_FAILURE_PCT / 100), 3)
            if reference_price
            else None
        )
        output.append(
            {
                "rank": 0,
                "code": code,
                "ts_code": _ts_code(code),
                "name": str(
                    _first(
                        preselect,
                        "name",
                        "stock_name",
                        default=_first(auction, "name", "stock_name", default=code),
                    )
                ),
                "target_date": trade_date,
                "signal_date": signal_date,
                "preselect_rank": _first(preselect, "stage_rank", "rank", "source_pool_rank"),
                "preselect_lane": _first(preselect, "source_lane", "lane"),
                "auction_rank": auction_rank,
                "auction_score": round(score, 4),
                "auction_label": str(
                    _first(
                        auction,
                        "stage1_ref_label",
                        "auction_entry_label",
                        default="AUCTION参考观察",
                    )
                ),
                "auction_ref_gap_pct": _first(
                    auction,
                    "auction_ref_gap_pct",
                    "opening_gap_proxy_pct",
                ),
                "first_to_last_ref_pct": auction.get("first_to_last_ref_pct", ""),
                "visible_depth_hkd": auction.get("visible_depth_hkd", ""),
                "bid_ask_imbalance": auction.get("bid_ask_imbalance", ""),
                "spread_pct": auction.get("spread_pct", ""),
                "last_price": _first(auction, "last_price", "price"),
                "prev_close_price": _first(auction, "prev_close_price", "last_close"),
                "bid_price": _first(auction, "bid_price", "bid1"),
                "ask_price": _first(auction, "ask_price", "ask1"),
                "bid_vol": _first(auction, "bid_vol", "bid_vol1"),
                "ask_vol": _first(auction, "ask_vol", "ask_vol1"),
                "turnover": auction.get("turnover", ""),
                "update_time": auction.get("update_time", ""),
                "collector_wall_time": auction.get("collector_wall_time", ""),
                "second_filter_status": status,
                "recommendation_status": "WATCH_ONLY",
                "reference_price_hkd": round(reference_price, 3) if reference_price else None,
                "strict_failure_price_hkd": strict_failure_price,
                "strict_failure_pct": STRICT_FAILURE_PCT if strict_failure_price is not None else None,
                "reference_only": True,
                "reference_scope": "PREOPEN_REFERENCE_ONLY_NOT_TRADABLE",
                "market_access": "NOT_TRADABLE_PREOPEN",
                "action_level": "NO_BUY",
                "cannot_confirm": [
                    "09:15-09:25港股通盘前参考不可交易，不是买入指令。",
                    "未确认完整经纪队列、十档、撤单轨迹或未匹配量。",
                ],
            }
        )
    output.sort(
        key=lambda row: (
            -(_number(row.get("auction_score"), 0.0) or 0.0),
            -(_number(row.get("turnover"), 0.0) or 0.0),
            str(row.get("code") or ""),
        )
    )
    rows = [{**row, "rank": rank} for rank, row in enumerate(output[:TOP_N], start=1)]
    status = (
        "AUCTION_SECOND_FILTER_READY"
        if len(rows) == TOP_N
        else "CANNOT_CONFIRM_V1_1_TOP20_SHORTFALL"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "model_id": MODEL_ID,
        "version": MODEL_VERSION,
        "champion_contract": CHAMPION_CONTRACT,
        "trade_date": trade_date,
        "signal_date": signal_date,
        "stage_id": "STAGE_0925",
        "signal_cutoff": SIGNAL_CUTOFF,
        "publication_time": PUBLICATION_TIME,
        "status": status,
        "row_count": len(rows),
        "required_row_count": TOP_N,
        "d1_membership_model": "0.2",
        "same_day_rerank_model": "1.1",
        "rows": rows,
        "source_evidence": evidence,
        "research_only": True,
        "reference_only": True,
        "reference_scope": "PREOPEN_REFERENCE_ONLY_NOT_TRADABLE",
        "market_access": "NOT_TRADABLE_PREOPEN",
        "action_level": "NO_BUY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
    }


def _rounded(value: Any, digits: int = 4) -> Any:
    number = _number(value, None)
    return round(number, digits) if number is not None else value


def _a_share_normalized_row(source: Mapping[str, Any]) -> dict[str, Any]:
    """Map the exact-date tdxpy fields onto the frozen V3 qmt contract."""
    row = dict(source)
    for target, source_key in (
        ("qmt_open", "open_price"),
        ("qmt_last", "last_price"),
        ("qmt_low", "low_price"),
        ("qmt_high", "high_price"),
        ("qmt_prev_close", "prev_close_price"),
        ("qmt_amount", "turnover"),
    ):
        if row.get(target) in (None, "") and row.get(source_key) not in (None, ""):
            row[target] = row[source_key]
    if row.get("qmt_stage_change_pct") in (None, ""):
        open_price = _number(row.get("qmt_open"), None)
        previous_close = _number(row.get("qmt_prev_close"), None)
        if open_price is not None and previous_close not in (None, 0):
            row["qmt_stage_change_pct"] = (
                open_price / previous_close - 1
            ) * 100
    return row


def _a_share_current_price(row: Mapping[str, Any]) -> tuple[float | None, str]:
    for basis in (
        "current_price",
        "current_last",
        "last_price",
        "qmt_last",
        "close",
        "current_open",
        "opening_price_hkd",
        "qmt_open",
        "first_open",
        "last_close",
    ):
        current = _number(row.get(basis), None)
        if current is not None:
            return current, basis
    return None, ""


def _a_share_preopen_snapshot_only(row: Mapping[str, Any]) -> bool:
    source_mode = str(row.get("source_mode") or "").upper()
    confidence = str(
        row.get("data_confidence")
        or row.get("price_structure_status")
        or row.get("evidence_level")
        or ""
    ).upper()
    return source_mode in {
        "PREOPEN_FUTU_SNAPSHOT",
        "HKCONNECT_0920_AUCTION_SECOND_FILTER",
    } or confidence in {
        "PREOPEN_SNAPSHOT_CONFIRMED",
        "AUCTION_SECOND_FILTER_READY",
        "L0_PYTDX_QUOTE_PROXY_ONLY",
    }


def _a_share_single_point_range(row: Mapping[str, Any]) -> bool:
    bar_count = _number(row.get("stage_replay_bar_count"), None)
    if bar_count is not None and bar_count <= 1:
        return True
    current, _ = _a_share_current_price(row)
    low = _number(_first(row, "stage_low_price", "low_price", "qmt_low"), None)
    high = _number(_first(row, "stage_high_price", "high_price", "qmt_high"), None)
    return (
        current is not None
        and low is not None
        and high is not None
        and abs(low - current) < 1e-9
        and abs(high - current) < 1e-9
    )


def _a_share_skip_snapshot_level(row: Mapping[str, Any], basis: str) -> bool:
    if basis in {
        "opening_price_hkd",
        "current_open_public_quote",
        "qmt_open_snapshot",
        "qmt_last_snapshot",
        "last_price_snapshot",
        "close_snapshot",
        "prev_close_snapshot",
        "last_close",
        "first_open",
        "qmt_open",
        "qmt_last",
        "qmt_prev_close",
    }:
        return True
    return (
        _a_share_preopen_snapshot_only(row)
        and _a_share_single_point_range(row)
        and basis
        in {
            "stage_low_price_rtdata_replay",
            "stage_high_price_rtdata_replay",
            "stage_low_snapshot",
            "stage_high_price",
            "stage_low_price",
            "low_price",
            "high_price",
            "low_price_rtdata_replay",
            "high_price_rtdata_replay",
            "qmt_low",
            "qmt_high",
        }
    )


def _a_share_support(row: Mapping[str, Any]) -> dict[str, Any]:
    support = None
    support_basis = ""
    for basis in (
        "qmt_low",
        "qmt_open",
        "qmt_last",
        "low_price",
        "first_open",
        "last_close",
        "qmt_prev_close",
    ):
        if _a_share_skip_snapshot_level(row, basis):
            continue
        support = _number(row.get(basis), None)
        if support is not None:
            support_basis = basis
            break
    cannot_confirm: list[str] = []
    if support is None:
        cannot_confirm.append("CANNOT_CONFIRM_A_SHARE_SUPPORT_INVALIDATION_LINE")
        return {
            "support_primary_price": None,
            "support_primary_basis": "",
            "invalidation_price": None,
            "invalidation_condition": "A_SHARE_SUPPORT_OR_INVALIDATION_LINE_NOT_CONFIRMED",
            "next_validation_time": "09:35",
            "fail_action_label": "WATCH_ONLY_WITH_INSUFFICIENT_RISK_LINE",
            "cannot_confirm": cannot_confirm,
        }
    if support_basis == "qmt_prev_close":
        cannot_confirm.append("CANNOT_CONFIRM_A_SHARE_INTRADAY_SUPPORT_FROM_PREV_CLOSE")
    return {
        "support_primary_price": support,
        "support_primary_basis": support_basis,
        "invalidation_price": _number(row.get("invalidation_price"), support),
        "invalidation_condition": row.get("invalidation_condition")
        or "A_SHARE_PRICE_BREAKS_OPENING_OR_INTRADAY_SUPPORT_DOWNGRADE_TO_WATCH",
        "next_validation_time": "09:35",
        "fail_action_label": "KEEP_OBSERVATION",
        "cannot_confirm": cannot_confirm,
    }


def _a_share_pressure(row: Mapping[str, Any]) -> dict[str, Any]:
    pressure = None
    pressure_basis = ""
    for basis in (
        "pressure_price",
        "resistance_price",
        "qmt_high",
        "high_price",
        "stage_high_price",
        "qmt_last",
        "qmt_open",
        "last_close",
        "first_open",
    ):
        if _a_share_skip_snapshot_level(row, basis):
            continue
        pressure = _number(row.get(basis), None)
        if pressure is not None:
            pressure_basis = basis
            break
    cannot_confirm: list[str] = []
    if pressure is None:
        cannot_confirm.append("CANNOT_CONFIRM_A_SHARE_PRESSURE_LINE")
    elif pressure_basis in {"qmt_last", "qmt_open", "last_close", "first_open"}:
        cannot_confirm.append("CANNOT_CONFIRM_A_SHARE_PRESSURE_FROM_SNAPSHOT_ONLY")
    return {
        "pressure_price": pressure,
        "pressure_basis": pressure_basis,
        "cannot_confirm": cannot_confirm,
    }


def _a_share_level_signal(
    row: Mapping[str, Any],
    support: Mapping[str, Any],
    pressure: Mapping[str, Any],
) -> dict[str, Any]:
    current, current_basis = _a_share_current_price(row)
    support_price = _number(support.get("support_primary_price"), None)
    pressure_price = _number(pressure.get("pressure_price"), None)
    support_basis = str(support.get("support_primary_basis") or "")
    pressure_basis = str(pressure.get("pressure_basis") or "")
    cannot_confirm: list[str] = []
    flags: list[str] = []
    reasons: list[str] = []
    score_delta = 0.0
    support_distance_pct: float | None = None
    pressure_distance_pct: float | None = None
    risk_reward_ratio: float | None = None
    breakout_status = "LEVEL_STRUCTURE_CANNOT_CONFIRM"
    if current is None or current <= 0:
        cannot_confirm.append("CANNOT_CONFIRM_A_SHARE_LEVEL_STRUCTURE_CURRENT_PRICE")
    if (
        support_price is None
        or support_price <= 0
        or pressure_price is None
        or pressure_price <= 0
    ):
        cannot_confirm.append("CANNOT_CONFIRM_A_SHARE_LEVEL_STRUCTURE_SUPPORT_PRESSURE")
    if cannot_confirm:
        return {
            "score_delta": 0.0,
            "flags": flags,
            "cannot_confirm": cannot_confirm,
            "current_price": current,
            "current_price_basis": current_basis,
            "support_distance_pct": "",
            "pressure_distance_pct": "",
            "risk_reward_ratio": "",
            "breakout_status": breakout_status,
            "level_structure_reason": "关键点位证据不足，暂不参与加分",
        }
    support_distance_pct = ((current - support_price) / support_price) * 100
    if current <= support_price * 0.997:
        score_delta -= 14
        flags.append("level_support_breakdown")
        breakout_status = "SUPPORT_BREAKDOWN"
        reasons.append(f"跌破支撑位{support_price:.2f}，点位结构转弱")
    elif support_distance_pct <= 0.8:
        score_delta += 2
        flags.append("level_support_retest")
        breakout_status = "SUPPORT_RETEST_HOLDING"
        reasons.append(f"贴近支撑位{support_price:.2f}，等待回踩确认")
    elif support_distance_pct <= 4:
        score_delta += 4
        flags.append("level_support_distance_healthy")
        reasons.append(f"距支撑位{support_distance_pct:.2f}%，下方风险距离可控")
    elif support_distance_pct >= LEVEL_SUPPORT_EXTENDED_PCT:
        score_delta -= 6
        flags.append("level_extended_from_support")
        reasons.append(f"距支撑位{support_distance_pct:.2f}%，追高风险上升")
    if current > pressure_price:
        breakout_pct = ((current - pressure_price) / pressure_price) * 100
        pressure_distance_pct = -breakout_pct
        if breakout_pct >= LEVEL_BREAKOUT_CONFIRM_PCT:
            score_delta += 8
            flags.append("level_pressure_breakout_confirmed")
            breakout_status = "PRESSURE_BREAKOUT_CONFIRMED"
            reasons.append(f"突破压力位{pressure_price:.2f}约{breakout_pct:.2f}%，结构加分")
        else:
            score_delta += 2
            flags.append("level_pressure_breakout_pending")
            breakout_status = "PRESSURE_BREAKOUT_PENDING"
            reasons.append(f"刚越过压力位{pressure_price:.2f}，仍需站稳确认")
    else:
        pressure_distance_pct = ((pressure_price - current) / current) * 100
        if pressure_distance_pct <= LEVEL_NEAR_PRESSURE_PCT:
            score_delta -= 6
            flags.append("level_near_pressure_unbroken")
            if breakout_status == "LEVEL_STRUCTURE_CANNOT_CONFIRM":
                breakout_status = "NEAR_PRESSURE_NOT_BROKEN"
            reasons.append(f"距压力位{pressure_distance_pct:.2f}%，未突破前不追高")
        elif pressure_distance_pct >= 3:
            score_delta += 2
            flags.append("level_pressure_room_available")
            if breakout_status == "LEVEL_STRUCTURE_CANNOT_CONFIRM":
                breakout_status = "ROOM_BEFORE_PRESSURE"
            reasons.append(f"距压力位{pressure_distance_pct:.2f}%，仍有上方观察空间")
    if support_price < current < pressure_price:
        downside = current - support_price
        upside = pressure_price - current
        if downside > 0:
            risk_reward_ratio = upside / downside
            if risk_reward_ratio >= LEVEL_GOOD_RISK_REWARD:
                score_delta += 5
                flags.append("level_risk_reward_good")
                reasons.append(
                    f"点位风险收益比{risk_reward_ratio:.2f}，上方空间占优"
                )
            elif risk_reward_ratio < LEVEL_POOR_RISK_REWARD:
                score_delta -= 7
                flags.append("level_risk_reward_poor")
                reasons.append(
                    f"点位风险收益比{risk_reward_ratio:.2f}，上方空间不足"
                )
    if pressure_basis in {
        "qmt_last",
        "qmt_open",
        "last_close",
        "first_open",
        "opening_price_hkd",
        "current_open_public_quote",
        "last_price_snapshot",
    } or support_basis in {
        "qmt_last",
        "qmt_open",
        "last_close",
        "first_open",
        "qmt_prev_close",
        "close_hkd_d1_anchor",
        "d1_close_hkd_anchor",
        "actual_float_d1_close_implied",
        "last_price_snapshot",
        "close_snapshot",
        "prev_close_snapshot",
    }:
        flags.append("level_snapshot_only")
        cannot_confirm.append("CANNOT_CONFIRM_A_SHARE_LEVEL_STRUCTURE_SNAPSHOT_ONLY")
        if score_delta > 0:
            score_delta = 0.0
        reasons.append("关键点位仅来自快照/锚点，实验层不做正向加分")
    if breakout_status == "LEVEL_STRUCTURE_CANNOT_CONFIRM":
        breakout_status = "LEVEL_STRUCTURE_BALANCED"
    return {
        "score_delta": round(max(-18.0, min(14.0, score_delta)), 2),
        "flags": flags,
        "cannot_confirm": list(dict.fromkeys(cannot_confirm)),
        "current_price": _rounded(current, 4),
        "current_price_basis": current_basis,
        "support_distance_pct": _rounded(support_distance_pct, 4),
        "pressure_distance_pct": _rounded(pressure_distance_pct, 4),
        "risk_reward_ratio": _rounded(risk_reward_ratio, 4)
        if risk_reward_ratio is not None
        else "",
        "breakout_status": breakout_status,
        "level_structure_reason": "；".join(reasons[:5])
        or "关键点位结构中性，未触发明显加减分",
    }


def _sanitize_a_share_cannot_confirm(items: Sequence[Any]) -> list[str]:
    cleaned: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        marker_text = text.upper()
        if any(
            marker in marker_text or marker in text
            for marker in _HK_ONLY_CANNOT_CONFIRM_MARKERS
        ):
            cleaned.append("CANNOT_CONFIRM_A_SHARE_LEVEL2_DEPTH_TICK_DATA")
        else:
            cleaned.append(text)
    return list(dict.fromkeys(cleaned))


def apply_a_share_v11_adapter(
    source_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Port the graph-authoritative ``_a_share_v1_1_core`` 09:25 adapter."""
    output: list[dict[str, Any]] = []
    for source in source_rows:
        row = _a_share_normalized_row(source)
        stage_score = _number(_first(row, "stage_score", "score", "pool_score"), 0.0) or 0.0
        pool_score = _number(row.get("pool_score"), None)
        change = _number(
            _first(
                row,
                "qmt_stage_change_pct",
                "qmt_gap_pct",
                "change_pct",
                "window_change_pct",
            ),
            None,
        )
        amount = _number(
            _first(row, "qmt_amount", "amount_in_window", "turnover"),
            None,
        )
        amount_yi = amount / 100_000_000 if amount is not None and amount > 10_000 else amount
        support = _a_share_support(row)
        pressure = _a_share_pressure(row)
        level_signal = _a_share_level_signal(row, support, pressure)

        score = 0.45 * max(0.0, min(100.0, stage_score))
        if pool_score is not None:
            score += 0.15 * max(0.0, min(100.0, pool_score))
        reasons: list[str] = []
        flags: list[str] = []
        cannot_confirm = [
            str(item)
            for item in row.get("cannot_confirm", [])
            if str(item).strip()
        ] if isinstance(row.get("cannot_confirm", []), list) else []
        if change is None:
            cannot_confirm.append("CANNOT_CONFIRM_A_SHARE_STAGE_CHANGE")
        elif change >= 15:
            score -= 18
            flags.append("chase_block_pct")
            reasons.append(
                f"A-share change {change:.2f}% triggers v1.1 no-chase guard"
            )
        elif change >= 10:
            score -= 8
            flags.append("high_spike_fade_risk")
            reasons.append(f"A-share change {change:.2f}% has spike-fade risk")
        elif change >= 5:
            score += 10
            reasons.append(f"A-share strong stage change {change:.2f}%")
        elif change >= 3:
            score += 7
            reasons.append(f"A-share stage change {change:.2f}%")
        elif change > 0:
            score += 3
            reasons.append(f"A-share positive stage change {change:.2f}%")
        else:
            score -= 8
            flags.append("weak_intraday_change")
            reasons.append(f"A-share weak or negative stage change {change:.2f}%")
        if amount_yi is None:
            cannot_confirm.append("CANNOT_CONFIRM_A_SHARE_INTRADAY_AMOUNT")
        elif amount_yi >= 1:
            score += 10
            reasons.append(f"A-share amount {amount_yi:.2f} yi CNY")
        elif amount_yi >= 0.2:
            score += 6
            reasons.append(f"A-share amount {amount_yi:.2f} yi CNY")
        else:
            score -= 6
            flags.append("amount_below_v1_floor")
            reasons.append(
                f"A-share amount {amount_yi:.2f} yi CNY below v1.1 floor"
            )
        raw_action = str(row.get("raw_action") or row.get("decision_level") or "")
        if raw_action in {"BUY_ON_PULLBACK", "WAIT_FOR_TRIGGER", "WATCH_TOP", "BUY_REVIEW"}:
            score += 6
            reasons.append(
                "A-share upstream stage candidate requires manual validation"
            )
        elif raw_action == "BUY_NOW":
            score -= 10
            flags.append("raw_buy_now_downgraded_no_chase")
            reasons.append(
                "A-share BUY_NOW is downgraded to research-only observation by v1.1"
            )
        elif raw_action in {"NO_BUY", "NO_TRADE", "BLOCKED"}:
            score -= 12
            flags.append("raw_action_blocked")
        if not _first(row, "qmt_open", "first_open"):
            cannot_confirm.append("CANNOT_CONFIRM_A_SHARE_OPEN_PRICE_CAPTURE")
        if not _first(row, "qmt_last", "last_close"):
            cannot_confirm.append("CANNOT_CONFIRM_A_SHARE_LAST_PRICE_CAPTURE")
        if not _first(row, "qmt_low", "low_price"):
            cannot_confirm.append("CANNOT_CONFIRM_A_SHARE_INTRADAY_LOW_PRICE")
        score += _number(level_signal.get("score_delta"), 0.0) or 0.0
        flags.extend(str(item) for item in level_signal["flags"])
        cannot_confirm.extend(
            str(item) for item in level_signal["cannot_confirm"]
        )
        if level_signal["level_structure_reason"]:
            reasons.append(str(level_signal["level_structure_reason"]))

        score = round(max(0.0, min(100.0, score)), 2)
        if "chase_block_pct" in flags or "raw_buy_now_downgraded_no_chase" in flags:
            label = "A_SHARE_NO_CHASE_SPIKE_FADE_RISK"
        elif score >= 45:
            label = "A_SHARE_OPENING_INITIAL_SCREEN_REQUIRES_CONFIRM"
        else:
            label = "A_SHARE_OPENING_INITIAL_SCREEN_WATCH"
        if "level_support_breakdown" in flags:
            label = "A_SHARE_DROP_OR_NO_CHASE"
        if support["fail_action_label"] == "WATCH_ONLY_WITH_INSUFFICIENT_RISK_LINE":
            label = "A_SHARE_WATCH_ONLY_WITH_INSUFFICIENT_RISK_LINE"
        combined_cannot_confirm = _sanitize_a_share_cannot_confirm(
            [
                *cannot_confirm,
                *support["cannot_confirm"],
                *pressure["cannot_confirm"],
            ]
        )
        output.append(
            {
                **row,
                "market": "A",
                "rank": row.get("rank") or row.get("stage_rank"),
                "model_id": MODEL_ID,
                "model_version": MODEL_VERSION,
                "opening_second_filter_label": label,
                "opening_second_filter_score": score,
                "opening_second_filter_reason": "; ".join(reasons[:6])
                or "A-share v1.1 adapter lacks enough price-volume evidence; keep watch-only",
                "opening_second_filter_strategy": "a_share_v1_1_price_volume_adapter",
                "opening_second_filter_flags": flags,
                "opening_second_filter_cannot_confirm": combined_cannot_confirm,
                "current_change_pct": _rounded(change, 4)
                if change is not None
                else "",
                "current_amount_yi": _rounded(amount_yi, 4)
                if amount_yi is not None
                else "",
                "price_structure_status": row.get("price_structure_status")
                or row.get("data_level")
                or row.get("evidence_level")
                or "A_SHARE_PRICE_STRUCTURE_DATA_PARTIAL",
                "current_price": level_signal["current_price"],
                "current_price_basis": level_signal["current_price_basis"],
                "support_distance_pct": level_signal["support_distance_pct"],
                "pressure_distance_pct": level_signal["pressure_distance_pct"],
                "risk_reward_ratio": level_signal["risk_reward_ratio"],
                "breakout_status": level_signal["breakout_status"],
                "level_structure_score_delta": level_signal["score_delta"],
                "level_structure_reason": level_signal["level_structure_reason"],
                "support_primary_price": support["support_primary_price"],
                "support_primary_basis": support["support_primary_basis"],
                "pressure_price": pressure["pressure_price"],
                "pressure_basis": pressure["pressure_basis"],
                "invalidation_price": support["invalidation_price"],
                "invalidation_condition": support["invalidation_condition"],
                "stage_display_decision": "09:25竞价初筛",
                "next_validation_time": support["next_validation_time"],
                "fail_action_label": support["fail_action_label"],
                "data_level": "A_SHARE_V1_1_OPENING_SECOND_FILTER",
                "research_only": True,
                "recommendation_status": "WATCH_ONLY",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
    return output
