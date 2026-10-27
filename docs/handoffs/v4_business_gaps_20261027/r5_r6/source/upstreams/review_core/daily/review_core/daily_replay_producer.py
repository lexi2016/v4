"""Standalone deterministic independent close-review producer.

The computation mirrors the frozen replay contract using explicit row records
and the same aggregate/role/scenario rules.  It has no implicit panel pointer,
network route, media input, or model promotion side effect.  A caller may
inject the local semantic invoker explicitly; the deterministic market
dashboard remains valid and independent when that optional phase is absent.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .producer_inputs import normalize_date


SAFETY = {
    "SHADOW_ONLY": True,
    "NOT_BUY_ADVICE": True,
    "NO_BUY_GATE": True,
    "HOLDOUT_ACCESS_COUNT": 0,
    "FORMAL_GENERALIZATION_PENDING": True,
    "NO_MODEL_PROMOTED": True,
}
INDEPENDENT_REVIEW_STATUS = "INDEPENDENT_CLOSE_REVIEW_READY"
SCHEMA = "replay_model_v1"
LOCAL_SCHEMA = "review_core.local_replay.v1"
FULL_MARKET_SCOPE = "FULL_MARKET"
FORMAL_POOL_PROXY_SCOPE = "FORMAL_POOL_PROXY"
PARTIAL_COVERAGE_SCOPE = "PARTIAL_COVERAGE"
MARKET_UNIVERSE_SCOPES = frozenset({FULL_MARKET_SCOPE, FORMAL_POOL_PROXY_SCOPE, PARTIAL_COVERAGE_SCOPE})
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _number(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def _amount_yi(value: Any) -> float:
    return round(_number(value) / 100_000_000, 4)


def _validate_universe_scope(value: Any) -> str:
    scope = str(value or "").strip()
    if scope not in MARKET_UNIVERSE_SCOPES:
        raise ValueError(
            "universe_scope must be explicit and one of FULL_MARKET or FORMAL_POOL_PROXY"
        )
    return scope


def _rows_for_date(rows: Iterable[Mapping[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    result: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        row_date = normalize_date(row.get("trade_date"))
        if row_date != target:
            raise ValueError(f"row trade_date {row_date} does not match {target}")
        code = str(row.get("ts_code") or row.get("code") or "").strip()
        raw_sector = row.get("sector_name")
        if raw_sector is None or (isinstance(raw_sector, float) and raw_sector != raw_sector):
            raw_sector = row.get("sector") or row.get("industry") or ""
        sector = str(raw_sector or "").strip()
        if sector.lower() == "nan":
            sector = ""
        if not code:
            raise ValueError("market rows require ts_code")
        row["trade_date"] = target
        row["ts_code"] = code
        row["sector_name"] = sector
        row["name"] = str(row.get("name") or row.get("stock_name") or code)
        row["pct_chg"] = _number(row.get("pct_chg"), 0.0)
        amount = row.get("amount")
        if amount in (None, ""):
            amount = _number(row.get("amount_yi")) * 100_000_000
        row["amount"] = _number(amount)
        row["approx_limit_up"] = bool(row.get("approx_limit_up", row.get("is_limit_up_proxy", False)))
        row["approx_limit_down"] = bool(row.get("approx_limit_down", row.get("is_limit_down_proxy", False)))
        result.append(row)
    if not result:
        raise ValueError("market rows must not be empty")
    return result


def _aggregate_sector_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in rows:
        sector = str(row.get("sector_name") or "")
        code = str(row.get("ts_code") or row.get("code") or "")
        if sector and code:
            grouped[sector][code] = row
    result: list[dict[str, Any]] = []
    for sector, by_stock in grouped.items():
        items = list(by_stock.values())
        changes = sorted(_number(item.get("pct_chg")) for item in items)
        middle = len(changes) // 2
        median = changes[middle] if len(changes) % 2 else (changes[middle - 1] + changes[middle]) / 2
        up_ratio = sum(value > 0 for value in changes) / len(changes)
        down_ratio = sum(value < 0 for value in changes) / len(changes)
        result.append(
            {
                "board_name": sector,
                "stock_count": len(items),
                "median_pct_change": round(median, 4),
                "mean_pct_change": round(sum(changes) / len(changes), 4),
                "up_ratio": round(up_ratio, 4),
                "down_ratio": round(down_ratio, 4),
                "limit_up_count": int(sum(bool(item.get("approx_limit_up")) for item in items)),
                "limit_down_count": int(sum(bool(item.get("approx_limit_down")) for item in items)),
                "amount_yi": _amount_yi(sum(_number(item.get("amount")) for item in items)),
            }
        )
    return result


def _iso_trade_date(trade_date: str) -> str:
    return datetime.strptime(normalize_date(trade_date), "%Y%m%d").strftime("%Y-%m-%d")


def build_market_summary(
    rows: Sequence[Mapping[str, Any]],
    previous_amount_yi: float,
    trade_date: str,
    *,
    universe_scope: str | None = None,
) -> dict[str, Any]:
    target = normalize_date(trade_date)
    scope = _validate_universe_scope(universe_scope)
    changes = [_number(row.get("pct_chg")) for row in rows]
    up_count = sum(value > 0 for value in changes)
    down_count = sum(value < 0 for value in changes)
    flat_count = sum(value == 0 for value in changes)
    active_count = up_count + down_count + flat_count
    amount_yi = _amount_yi(sum(_number(row.get("amount")) for row in rows))
    width = up_count / active_count if active_count else 0.0
    if scope != FULL_MARKET_SCOPE:
        return {
            "universe_scope": scope,
            "market_completeness": "PARTIAL_COVERAGE" if scope == PARTIAL_COVERAGE_SCOPE else "PROXY_ONLY_CANNOT_CONFIRM",
            "regime": "CANNOT_CONFIRM_MARKET_REGIME_PARTIAL" if scope == PARTIAL_COVERAGE_SCOPE else "CANNOT_CONFIRM_MARKET_REGIME_PROXY_ONLY",
            "up_count": None,
            "down_count": None,
            "flat_count": None,
            "pool_up_count": up_count,
            "pool_down_count": down_count,
            "pool_flat_count": flat_count,
            "limit_up_count": None,
            "limit_down_count": None,
            "pool_limit_up_count": int(sum(bool(row.get("approx_limit_up")) for row in rows)),
            "pool_limit_down_count": int(sum(bool(row.get("approx_limit_down")) for row in rows)),
            "amount_yi": None,
            "amount_ratio_previous": None,
            "pool_amount_yi": amount_yi,
            "pool_amount_ratio_previous": round(amount_yi / previous_amount_yi, 6) if previous_amount_yi else None,
            "market_width": None,
            "confidence": 0.0,
            "external_environment": "CANNOT_CONFIRM_EXTERNAL_MARKET_DETAIL",
            "evidence_refs": [f"partial_selector:{target}" if scope == PARTIAL_COVERAGE_SCOPE else f"formal_pool_proxy:{target}"],
            "boundary": "当前输入覆盖不完整，不能确认全市场上涨/下跌、市场宽度或市场阶段。" if scope == PARTIAL_COVERAGE_SCOPE else "当前输入只覆盖正式池代理，不足以计算全市场上涨/下跌、市场宽度或市场阶段。",
        }
    regime = "retreat_or_negative_breadth" if width < 0.35 else ("repair_or_positive_breadth" if width > 0.55 else "divergence_or_weak_breadth")
    return {
        "universe_scope": scope,
        "market_completeness": "FULL_MARKET_VERIFIED",
        "regime": regime,
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "limit_up_count": int(sum(bool(row.get("approx_limit_up")) for row in rows)),
        "limit_down_count": int(sum(bool(row.get("approx_limit_down")) for row in rows)),
        "amount_yi": amount_yi,
        "amount_ratio_previous": round(amount_yi / previous_amount_yi, 6) if previous_amount_yi else None,
        "market_width": round(width, 6),
        "confidence": 0.76,
        "external_environment": "CANNOT_CONFIRM_EXTERNAL_MARKET_DETAIL",
        "evidence_refs": [f"selector_ready_panel:{target}_close", f"selector_frozen_industry_name:{target}"],
        "boundary": "收盘事实可重算；当前面板在收盘后物化，不能证明15:00前的历史PIT版本。",
    }


def build_board_rows(rows: Sequence[Mapping[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    sectors = _aggregate_sector_rows(rows)
    strongest = sorted(sectors, key=lambda row: (row["median_pct_change"], row["up_ratio"]), reverse=True)[:5]
    riskiest = sorted(sectors, key=lambda row: (row["median_pct_change"], -row["down_ratio"]))[:7]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*strongest, *riskiest]:
        name = row["board_name"]
        if name in seen:
            continue
        seen.add(name)
        if row["median_pct_change"] >= 1.0 and row["up_ratio"] >= 0.65:
            role = "strong_branch"
            note = "极弱市中的防御抗跌支线，不等同于进攻主线。"
        elif row["median_pct_change"] <= -5.0 and row["down_ratio"] >= 0.90:
            role = "risk_line"
            note = "下跌广度和跌停扩散均明显，属于主要亏钱效应来源。"
        else:
            role = "rotation"
            note = "相对抗跌或中性轮动，尚无持续进攻证据。"
        selected.append(
            {
                **row,
                "board_rank": len(selected) + 1,
                "board_role": role,
                "canonical_theme": name,
                "catalyst": "CANNOT_CONFIRM",
                "pricing_state": "CANNOT_CONFIRM_PRICE_CAUSAL_ORDER",
                "source_available_at": "D0收盘后物化；严格15:00 PIT版本不可确认",
                "eligible_for_strict_d0_1500": False,
                "confidence": 0.68,
                "evidence_refs": [f"sector_close:{name}:{target}"],
                "counterevidence": note,
                "trigger": "次日板块广度、容量承接和前排持续性同时改善才升级。",
                "invalidation": "仅单股脉冲、板块中位数转弱或风险锚继续扩散则降级。",
            }
        )
    return selected


def _role_row(stock: Mapping[str, Any], role: str, board: str, explanation: str, trade_date: str) -> dict[str, Any]:
    code = str(stock.get("ts_code") or stock.get("code") or "")
    return {
        "stock_code": code.split(".", 1)[0],
        "stock_name": str(stock.get("name") or code),
        "board_name": board,
        "canonical_theme": board,
        "primary_role": role,
        "secondary_roles": [],
        "board_height": 0,
        "one_word_board": False,
        "open_board_times": 0,
        "turnover_amount_yi": _amount_yi(stock.get("amount")),
        "pct_change": round(_number(stock.get("pct_chg")), 4),
        "confidence": 0.72,
        "role_explanation": explanation,
        "evidence_refs": [f"stock_close:{code}:{normalize_date(trade_date)}"],
        "trigger": "次日需同时验证个股承接和同板块广度，不能以单股冲高替代板块确认。",
        "invalidation": "个股放量失守且同板块无承接，或风险继续向同类股票扩散。",
        "counterevidence": "无逐笔封单、开板次数和盘中因果证据，角色仅基于收盘价量。",
    }


def build_role_rows(rows: Sequence[Mapping[str, Any]], resilient_boards: Sequence[str], risk_boards: Sequence[str], trade_date: str) -> list[dict[str, Any]]:
    materialized = _rows_for_date(rows, trade_date)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for board in list(resilient_boards)[:3]:
        peers = [row for row in materialized if str(row["sector_name"]) == str(board)]
        if not peers:
            continue
        positive = [row for row in peers if _number(row.get("pct_chg")) > 0]
        leader = sorted(peers, key=lambda row: (_number(row.get("pct_chg")), _number(row.get("amount"))), reverse=True)[0]
        capacity_pool = positive or peers
        alternatives = [row for row in capacity_pool if str(row.get("ts_code")) != str(leader.get("ts_code"))]
        capacity = sorted(alternatives or capacity_pool, key=lambda row: (_number(row.get("amount")), _number(row.get("pct_chg"))), reverse=True)[0]
        for stock, role, explanation in (
            (leader, "tomorrow_decider", "板块收盘涨幅前排；只作为次日防御强度定调锚。"),
            (capacity, "capacity_anchor", "板块正收益股票中成交额靠前，用于观察容量承接。"),
        ):
            code = str(stock.get("ts_code") or stock.get("code") or "")
            if code in seen:
                continue
            seen.add(code)
            result.append(_role_row(stock, role, str(board), explanation, trade_date))
    for board in list(risk_boards)[:4]:
        peers = [row for row in materialized if str(row["sector_name"]) == str(board)]
        if not peers:
            continue
        risk = sorted(peers, key=lambda row: (_number(row.get("pct_chg")), -_number(row.get("amount"))))[0]
        code = str(risk.get("ts_code") or risk.get("code") or "")
        if code in seen:
            continue
        seen.add(code)
        result.append(_role_row(risk, "risk_anchor", str(board), "板块跌幅前排，用于观察负反馈是否继续扩散。", trade_date))
    return result


def _approx_limit(code: str, name: str) -> float:
    code = str(code)
    if code.endswith(".BJ"):
        return 30.0
    raw = code.split(".", 1)[0]
    if raw.startswith(("300", "301", "688")):
        return 20.0
    if "ST" in str(name).upper():
        return 5.0
    return 10.0


def _scenario_tree(resilient: Sequence[str], risk: Sequence[str]) -> dict[str, Any]:
    resilient_label = "、".join(str(item) for item in list(resilient)[:2]) or "当日相对强势板块"
    risk_label = "、".join(str(item) for item in list(risk)[:3]) or "当日风险板块"
    return {
        "stronger": {
            "probability": 0.12,
            "open_trigger": [f"{risk_label}负反馈快速收敛"],
            "intraday_trigger": [f"{resilient_label}容量承接保持，同时风险锚止跌回收"],
            "close_validation": ["上涨家数明显回升且风险线不再扩散"],
            "invalidation": ["只有指数权重护盘、个股广度仍弱"],
            "counterevidence": ["极弱市后的单日反抽不自动等于新周期"],
        },
        "inline": {
            "probability": 0.28,
            "open_trigger": [f"指数企稳但个股仍分化，{resilient_label}保持相对强度"],
            "intraday_trigger": [f"{resilient_label}轮动，{risk_label}仅局部修复"],
            "close_validation": ["跌停减少但上涨家数未恢复到多数"],
            "invalidation": ["广度与风险线同步显著改善或同步恶化"],
            "counterevidence": ["局部涨停不能替代全市场赚钱效应"],
        },
        "weaker": {
            "probability": 0.60,
            "open_trigger": [f"{risk_label}风险锚继续低开并扩散"],
            "intraday_trigger": [f"{resilient_label}容量锚补跌，跌停家数继续增加"],
            "close_validation": ["下跌家数继续占绝对多数且成交放大"],
            "invalidation": ["风险锚止跌、跌停显著收敛且市场宽度同步修复"],
            "counterevidence": ["防御板块独强不代表全市场继续恶化"],
        },
    }


def _nonempty_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def build_independent_review(dashboard: Mapping[str, Any]) -> dict[str, Any]:
    """Port the deterministic semantic phase without importing its engine."""

    evidence = dashboard
    market = evidence.get("market_summary") or {}
    scope = _validate_universe_scope(market.get("universe_scope") or evidence.get("universe_scope"))
    width = float(market.get("market_width") or 0.0)
    regime = str(market.get("regime") or "CANNOT_CONFIRM_MARKET_REGIME")
    phase = {
        "retreat_or_negative_breadth": "退潮或负广度",
        "repair_or_positive_breadth": "修复或正广度",
        "divergence_or_weak_breadth": "分歧或弱广度",
    }.get(regime, regime)
    if scope != FULL_MARKET_SCOPE:
        phase = "CANNOT_CONFIRM_MARKET_REGIME_PARTIAL" if scope == PARTIAL_COVERAGE_SCOPE else "CANNOT_CONFIRM_MARKET_REGIME_PROXY_ONLY"
        conclusion = "当前覆盖不完整，不能确认全市场宽度或市场阶段。" if scope == PARTIAL_COVERAGE_SCOPE else "当前仅有正式池代理输入；不能据此确认全市场上涨/下跌、市场宽度或市场阶段。"
    else:
        conclusion = (
            f"市场阶段为{phase}；上涨{int(market.get('up_count') or 0)}家、下跌{int(market.get('down_count') or 0)}家，市场宽度{width:.2%}。"
            "局部强势必须同时接受全市场广度与风险线校验。"
        )
    board_conclusions = []
    for row in evidence["board_rows"]:
        name = str(row.get("board_name") or row.get("canonical_theme") or "")
        role = str(row.get("board_role") or "观察线")
        board_conclusions.append(
            {
                "board_name": name,
                "role": role,
                "conclusion": (
                    f"{name}中位涨跌幅{float(row.get('median_pct_change') or 0):.2f}%，上涨占比{float(row.get('up_ratio') or 0):.2%}，"
                    f"按{role}观察，不以单股脉冲替代板块确认。"
                ),
                "evidence_refs": _nonempty_strings(row.get("evidence_refs")),
                "counterevidence": [str(row.get("counterevidence") or "缺少盘中因果与持续性证据")],
            }
        )
    stock_conclusions = []
    for row in evidence["anchor_role_rows"]:
        stock_conclusions.append(
            {
                "stock_code": str(row.get("stock_code") or ""),
                "stock_name": str(row.get("stock_name") or ""),
                "role": str(row.get("primary_role") or "观察角色"),
                "conclusion": f"{row.get('stock_name')}仅作为{row.get('primary_role')}验证锚；角色用于观察板块承接，不构成买入建议。",
                "evidence_refs": _nonempty_strings(row.get("evidence_refs")),
                "invalidation": [str(row.get("invalidation") or "个股失守且同板块广度同步转弱")],
            }
        )
    scenario_conclusions = []
    for scenario in ("stronger", "inline", "weaker"):
        row = evidence["scenario_tree"].get(scenario) or {}
        scenario_conclusions.append(
            {
                "scenario": scenario,
                "probability": float(row.get("probability") or 0.0),
                "trigger": _nonempty_strings(row.get("open_trigger") or row.get("intraday_trigger")),
                "invalidation": _nonempty_strings(row.get("invalidation")),
            }
        )
    tomorrow_observation = []
    for row in evidence["anchor_role_rows"][:5]:
        tomorrow_observation.append(
            {
                "subject": f"{row.get('board_name') or '所属板块'} / {row.get('stock_name') or row.get('stock_code')}",
                "upgrade_trigger": str(row.get("trigger") or "个股承接与同板块广度同步改善才升级"),
                "downgrade_trigger": str(row.get("invalidation") or "个股转弱且同板块无承接则降级"),
            }
        )
    counterevidence = [str(row.get("counterevidence")) for row in evidence["board_rows"] if str(row.get("counterevidence") or "").strip()]
    return {
        "schema_version": "local_fupan_independent_review.v1",
        "actual_model": "local-deterministic-fupan-engine.v1",
        "review_date": str(evidence["review_date"]),
        "market_judgment": {
            "conclusion": conclusion,
            "market_phase": phase,
            "confidence": 0.0 if scope != FULL_MARKET_SCOPE else round(min(0.82, 0.55 + min(len(evidence["board_rows"]), 8) * 0.025), 3),
            "evidence_refs": _nonempty_strings(market.get("evidence_refs")),
            "counterevidence": counterevidence[:5] or ["缺少盘中因果、逐笔承接和催化先后证据"],
        },
        "board_conclusions": board_conclusions,
        "stock_role_conclusions": stock_conclusions,
        "scenario_conclusions": scenario_conclusions,
        "tomorrow_observation": tomorrow_observation,
        "red_team": {
            "strongest_counter_thesis": "最强板块可能只是弱市抱团或指数权重效应，并不自动代表全市场周期反转。",
            "missing_evidence": ["盘中逐笔承接", "催化发生与价格反应先后"],
            "cannot_confirm": [str(evidence.get("previous_plan_realization") or "昨日计划未绑定")],
        },
        "abstain": scope != FULL_MARKET_SCOPE or width < 0.35,
        "abstain_reason": (
            "覆盖不完整，不能确认全市场阶段。" if scope == PARTIAL_COVERAGE_SCOPE else "正式池代理不足以确认全市场阶段，保持 CANNOT_CONFIRM。"
            if scope != FULL_MARKET_SCOPE
            else ("市场宽度低于35%，保持观察。" if width < 0.35 else "")
        ),
        "boundary": {
            "research_only": True,
            "not_buy_advice": True,
            "target_video_used": False,
            "future_result_used": False,
            "dev_used": False,
            "holdout_used": False,
            "model_promoted": False,
        },
    }


def build_dashboard(
    rows: Sequence[Mapping[str, Any]],
    run_id: str,
    previous_amount_yi: float,
    trade_date: str,
    *,
    universe_scope: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    target = normalize_date(trade_date)
    scope = _validate_universe_scope(universe_scope)
    materialized = _rows_for_date(rows, target)
    market = build_market_summary(materialized, previous_amount_yi, target, universe_scope=scope)
    coverage = _aggregate_sector_rows(materialized)
    boards = build_board_rows(materialized, target)
    resilient = [row["board_name"] for row in boards if row["board_role"] == "strong_branch"]
    risk = [row["board_name"] for row in boards if row["board_role"] == "risk_line"]
    roles = build_role_rows(materialized, resilient, risk, target)
    conditional = [row for row in roles if row["primary_role"] in {"tomorrow_decider", "capacity_anchor"}][:4]
    risk_rows = [row for row in roles if row["primary_role"] == "risk_anchor"][:3]
    not_scored = {
        "board_macro_f1": "本次未评分",
        "stock_role_macro_f1": "本次未评分",
        "cannot_confirm_macro_f1": "本次未评分",
        "trigger_macro_f1": "本次未评分",
        "evidence_traceability_rate": 1.0,
    }
    dashboard = {
        "schema_version": SCHEMA,
        "status": INDEPENDENT_REVIEW_STATUS,
        "run_id": str(run_id),
        "review_date": target,
        "universe_scope": scope,
        "market_completeness": "FULL_MARKET_VERIFIED" if scope == FULL_MARKET_SCOPE else "PARTIAL_COVERAGE" if scope == PARTIAL_COVERAGE_SCOPE else "PROXY_ONLY_CANNOT_CONFIRM",
        "as_of": f"{_iso_trade_date(target)}T15:30:00+08:00",
        "objective": (
            f"{target} 覆盖不完整的收盘复盘；全市场宽度与阶段 CANNOT_CONFIRM。" if scope == PARTIAL_COVERAGE_SCOPE else f"{target} 正式池代理复盘；同日视频未作为输入；全市场宽度与阶段 CANNOT_CONFIRM。"
            if scope != FULL_MARKET_SCOPE
            else f"{target} D0独立完整复盘；同日视频未作为输入"
        ),
        "target_video_review_status": "CANNOT_CONFIRM_TARGET_VIDEO_NOT_CONSUMED",
        "target_video_evidence_count": 0,
        "video_augmented_review_complete": False,
        "target_video_used": False,
        "video_input_count": 0,
        "video_augmented": False,
        "market_summary": market,
        "previous_plan_realization": "CANNOT_CONFIRM_PREVIOUS_PLAN_REALIZATION_WITHOUT_BOUND_PRIOR_PLAN",
        "board_rows": boards,
        "anchor_role_rows": roles,
        "scenario_tree": _scenario_tree(resilient, risk),
        "shadow_watch_pool": {
            "shape": "3_CORE_4_CONDITIONAL_3_OBSERVATION_OR_RISK",
            "boundary": "SHADOW_ONLY",
            "not_buy_advice": True,
            "abstain": True,
            "abstain_reason": (
                "PARTIAL_COVERAGE_CANNOT_CONFIRM_MARKET" if scope == PARTIAL_COVERAGE_SCOPE else "FORMAL_POOL_PROXY_CANNOT_CONFIRM_MARKET"
                if scope != FULL_MARKET_SCOPE
                else "WEAK_MARKET_WIDTH_ALLOW_ABSTENTION"
            ),
            "core": [],
            "conditional": conditional,
            "observation_or_risk": risk_rows,
        },
        "r0_r3_metrics": {version: dict(not_scored) for version in ("R0", "R1", "R2", "R3")},
        "learning_events": [
            {
                "learning_event_id": f"DAILY-REPLAY-{target}-NO-TEACHER-SCORING",
                "error_slice": "单日展示不具备目标视频教师评分",
                "selected_single_variable_experiment": "未执行；保持last-good",
                "promotion_applied": False,
                "last_good": "REPLAY_RESEARCH_V1_20260720_002",
            }
        ],
        "evidence_index": {
            "market": f"evidence/market_facts_{target}.json",
            "boards": f"board_full_coverage_{target}.csv",
            "roles": f"anchor_roles_{target}.csv",
            "target_video": "未使用",
            "hashes": "artifact_hashes.v1.json",
        },
        "d3_sustainability_auxiliary": {
            "status": "未读取D+3结果",
            "role": "仅保留持续性接口，不参与本次判断",
            "d3_result_used_as_input": False,
        },
        "learning_status": "LEARNING_HYPOTHESIS_FAIL",
        "formal_generalization": "FORMAL_GENERALIZATION_PENDING",
        "model_promotion": "NO_MODEL_PROMOTED",
        "semantic_double_run_status": "本次为确定性单路，未执行模型语义双路",
        "semantic_double_run_consistency": None,
        "sol_decision_status": "未发起模型晋升；单日展示保持last-good",
        "visibility_stage": "POST_CLOSE_REVIEW_ONLY",
        "safety": dict(SAFETY),
        "safety_flags": dict(SAFETY_FLAGS),
    }
    dashboard["independent_review"] = build_independent_review(dashboard)
    return dashboard, coverage


def build_daily_replay_payload(
    trade_date: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    previous_amount_yi: float = 0.0,
    run_id: str | None = None,
    universe_scope: str | None = None,
) -> dict[str, Any]:
    dashboard, coverage = build_dashboard(
        rows,
        run_id or f"REPLAY_RESEARCH_V1_{normalize_date(trade_date)}_LOCAL",
        previous_amount_yi,
        trade_date,
        universe_scope=universe_scope,
    )
    result = dict(dashboard)
    result["schema"] = LOCAL_SCHEMA
    result["coverage_rows"] = coverage
    result["review_date"] = normalize_date(trade_date)
    return result


def attach_local_semantic_review(
    dashboard: Mapping[str, Any],
    *,
    output_dir: str | Path,
    mode: str = "deterministic",
    model: str = "gpt-5.6-sol",
    effort: str = "high",
    semantic_invoker: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Preserve the optional semantic phase behind an injected local seam.

    The producer never imports a model package.  A caller that has explicitly
    migrated the deterministic engine may inject a callable; otherwise the
    phase is reported as unavailable and the independent dashboard remains
    unchanged rather than being silently promoted.
    """

    if mode not in {"deterministic", "external-required", "disabled"}:
        raise ValueError(f"unsupported semantic model mode: {mode}")
    result = dict(dashboard)
    if mode == "disabled":
        result["local_model_status"] = "DISABLED_BY_EXPLICIT_ARGUMENT"
        result["semantic_model_call_count"] = 0
        return result
    if semantic_invoker is None:
        result["local_model_status"] = "CANNOT_CONFIRM_LOCAL_SEMANTIC_DEPENDENCY"
        result["semantic_model_call_count"] = 0
        result["semantic_model"] = model
        result["semantic_effort"] = effort
        result["semantic_boundary"] = "独立市场复盘未被语义阶段改写"
        return result
    enriched = dict(semantic_invoker(result))
    enriched.setdefault("semantic_model_call_count", 1)
    enriched.setdefault("local_model_status", "INJECTED_DETERMINISTIC_SEMANTIC_READY")
    enriched["target_video_used"] = False
    enriched["video_input_count"] = 0
    enriched["video_augmented"] = False
    enriched["safety_flags"] = dict(SAFETY_FLAGS)
    return enriched


def _safe_output_dir(output_dir: str | os.PathLike[str]) -> Path:
    root = Path(output_dir).expanduser().resolve()
    lowered = {part.lower() for part in root.parts}
    if ".runtime" in lowered or "30_runtime" in lowered or "v35" in lowered:
        raise ValueError("output_dir is reserved for an application/runtime tree")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> str:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=path.parent, prefix=f".{path.name}.") as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return _sha256_bytes(encoded)


def write_daily_replay_run(
    trade_date: str,
    rows: Sequence[Mapping[str, Any]],
    output_dir: str | os.PathLike[str],
    *,
    previous_amount_yi: float = 0.0,
    run_id: str | None = None,
    universe_scope: str | None = None,
) -> dict[str, Path]:
    dashboard = build_daily_replay_payload(
        trade_date,
        rows,
        previous_amount_yi=previous_amount_yi,
        run_id=run_id,
        universe_scope=universe_scope,
    )
    root = _safe_output_dir(output_dir)
    dashboard_path = root / "dashboard_cache" / "replay_model_v1.latest.json"
    eval_path = root / "r0_r3_eval.v1.json"
    acceptance_path = root / "acceptance.v1.json"
    manifest_path = root / "complete_replay_model_manifest.v1.json"
    hashes_path = root / "artifact_hashes.v1.json"
    dashboard_sha = _atomic_json(dashboard_path, dashboard)
    evaluation = {
        "schema_version": "r0_r3_eval.v1",
        "run_id": dashboard["run_id"],
        "status": INDEPENDENT_REVIEW_STATUS,
        "learning_hypothesis": {"status": "LEARNING_HYPOTHESIS_FAIL", "model_promotion": "NO_MODEL_PROMOTED", "reason": "单日效果展示未打开目标视频教师评分。"},
        "leakage_counts": {"target_video": 0, "future_result": 0, "identity_feature": 0, "dev_holdout": 0},
    }
    eval_sha = _atomic_json(eval_path, evaluation)
    acceptance = {
        "schema_version": "acceptance.v1",
        "run_id": dashboard["run_id"],
        "status": INDEPENDENT_REVIEW_STATUS,
        "learning_status": "LEARNING_HYPOTHESIS_FAIL",
        "formal_generalization_status": "FORMAL_GENERALIZATION_PENDING",
        "model_promotion": "NO_MODEL_PROMOTED",
        "research_only": True,
        "target_video_input_count": 0,
        "target_video_evidence_count": 0,
        "future_result_input_count": 0,
        "holdout_access_count": 0,
        "safety_flags": dict(SAFETY_FLAGS),
    }
    acceptance_sha = _atomic_json(acceptance_path, acceptance)
    manifest = {
        "schema_version": "complete_replay_model_manifest.v1",
        "run_id": dashboard["run_id"],
        "status": INDEPENDENT_REVIEW_STATUS,
        "learning_status": "LEARNING_HYPOTHESIS_FAIL",
        "formal_generalization": "FORMAL_GENERALIZATION_PENDING",
        "acceptance_sha256": acceptance_sha,
        "eval_sha256": eval_sha,
        "dashboard_sha256": dashboard_sha,
        "safety": dict(SAFETY),
        "safety_flags": dict(SAFETY_FLAGS),
    }
    manifest_sha = _atomic_json(manifest_path, manifest)
    artifacts = []
    for path, digest in ((dashboard_path, dashboard_sha), (manifest_path, manifest_sha), (acceptance_path, acceptance_sha), (eval_path, eval_sha)):
        artifacts.append({"path": path.relative_to(root).as_posix(), "sha256": digest, "bytes": path.stat().st_size})
    _atomic_json(hashes_path, {"schema_version": "artifact_hashes.v1", "hash_algorithm": "SHA256", "artifact_count": len(artifacts), "artifacts": artifacts})
    return {"dashboard": dashboard_path, "evaluation": eval_path, "acceptance": acceptance_path, "manifest": manifest_path, "artifact_hashes": hashes_path}


__all__ = [
    "INDEPENDENT_REVIEW_STATUS",
    "FULL_MARKET_SCOPE",
    "FORMAL_POOL_PROXY_SCOPE",
    "MARKET_UNIVERSE_SCOPES",
    "SAFETY",
    "SAFETY_FLAGS",
    "attach_local_semantic_review",
    "build_board_rows",
    "build_daily_replay_payload",
    "build_dashboard",
    "build_market_summary",
    "build_role_rows",
    "write_daily_replay_run",
]
