"""Deterministic A-share close-review model ported from the V3 replay lane."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


SAFETY = {
    "SHADOW_ONLY": True,
    "NOT_BUY_ADVICE": True,
    "NO_BUY_GATE": True,
    "HOLDOUT_ACCESS_COUNT": 0,
    "FORMAL_GENERALIZATION_PENDING": True,
    "NO_MODEL_PROMOTED": True,
}
MODEL_STATUS = "INDEPENDENT_CLOSE_REVIEW_READY"


def _amount_yi(value: float) -> float:
    return round(float(value or 0.0) / 100_000_000, 4)


def _limit_pct(code: str, name: str) -> float:
    raw = str(code).split(".", 1)[0]
    if str(code).endswith(".BJ"):
        return 30.0
    if raw.startswith(("300", "301", "688")):
        return 20.0
    if "ST" in str(name).upper():
        return 5.0
    return 10.0


def prepare_close_rows(rows: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    """Normalize the exact V3 selector close fields without reading future rows."""
    datetime.strptime(trade_date, "%Y%m%d")
    required = {
        "trade_date", "ts_code", "name", "pct_chg", "amount", "bar_close_pos",
        "tdx_industry_code", "tdx_industry_name",
    }
    missing = sorted(required.difference(rows.columns))
    if missing:
        raise ValueError("A-share close panel missing fields: " + ", ".join(missing))
    current = rows.loc[rows["trade_date"].astype(str) == trade_date].copy()
    current = current.loc[
        current["ts_code"].astype(str).str.endswith((".SZ", ".SH", ".BJ"))
    ].copy()
    current["pct_chg"] = pd.to_numeric(current["pct_chg"], errors="coerce")
    current["amount"] = pd.to_numeric(current["amount"], errors="coerce")
    current = current.dropna(subset=["ts_code", "pct_chg", "amount"])
    current["sector_name"] = current["tdx_industry_name"].replace("", pd.NA)
    current["limit_pct"] = [
        _limit_pct(code, name)
        for code, name in zip(current["ts_code"], current["name"], strict=False)
    ]
    current["approx_limit_up"] = current["pct_chg"] >= current["limit_pct"] * 0.99
    current["approx_limit_down"] = current["pct_chg"] <= -current["limit_pct"] * 0.99
    if current.empty:
        raise ValueError(f"no A-share close rows for trade date {trade_date}")
    return current


def _sector_rows(rows: pd.DataFrame) -> list[dict[str, Any]]:
    usable = rows.dropna(subset=["sector_name"]).copy()
    grouped = (
        usable.groupby("sector_name", dropna=True)
        .agg(
            stock_count=("ts_code", "nunique"),
            median_pct_change=("pct_chg", "median"),
            mean_pct_change=("pct_chg", "mean"),
            up_ratio=("pct_chg", lambda values: float((values > 0).mean())),
            down_ratio=("pct_chg", lambda values: float((values < 0).mean())),
            limit_up_count=("approx_limit_up", "sum"),
            limit_down_count=("approx_limit_down", "sum"),
            total_amount=("amount", "sum"),
        )
        .reset_index()
    )
    return [
        {
            "board_name": str(row["sector_name"]),
            "stock_count": int(row["stock_count"]),
            "median_pct_change": round(float(row["median_pct_change"]), 4),
            "mean_pct_change": round(float(row["mean_pct_change"]), 4),
            "up_ratio": round(float(row["up_ratio"]), 4),
            "down_ratio": round(float(row["down_ratio"]), 4),
            "limit_up_count": int(row["limit_up_count"]),
            "limit_down_count": int(row["limit_down_count"]),
            "amount_yi": _amount_yi(row["total_amount"]),
        }
        for row in grouped.to_dict("records")
    ]


def build_market_summary(rows: pd.DataFrame, trade_date: str) -> dict[str, Any]:
    up_count = int((rows["pct_chg"] > 0).sum())
    down_count = int((rows["pct_chg"] < 0).sum())
    flat_count = int((rows["pct_chg"] == 0).sum())
    active_count = up_count + down_count + flat_count
    width = up_count / active_count if active_count else 0.0
    regime = (
        "retreat_or_negative_breadth" if width < 0.35
        else "repair_or_positive_breadth" if width > 0.55
        else "divergence_or_weak_breadth"
    )
    return {
        "regime": regime,
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "limit_up_count": int(rows["approx_limit_up"].sum()),
        "limit_down_count": int(rows["approx_limit_down"].sum()),
        "amount_yi": _amount_yi(rows["amount"].sum()),
        "market_width": round(width, 6),
        "external_environment": "CANNOT_CONFIRM_EXTERNAL_MARKET_DETAIL",
        "evidence_refs": [f"selector_ready_panel:{trade_date}_close"],
        "boundary": "收盘事实可重算；收盘后面板不能证明严格15:00历史PIT版本。",
    }


def build_board_rows(rows: pd.DataFrame, trade_date: str) -> list[dict[str, Any]]:
    sectors = _sector_rows(rows)
    strongest = sorted(
        sectors, key=lambda row: (row["median_pct_change"], row["up_ratio"]), reverse=True
    )[:5]
    riskiest = sorted(
        sectors, key=lambda row: (row["median_pct_change"], -row["down_ratio"])
    )[:7]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*strongest, *riskiest]:
        name = row["board_name"]
        if name in seen:
            continue
        seen.add(name)
        if row["median_pct_change"] >= 1.0 and row["up_ratio"] >= 0.65:
            role = "strong_branch"
            counterevidence = "极弱市中的防御抗跌支线，不等同于进攻主线。"
        elif row["median_pct_change"] <= -5.0 and row["down_ratio"] >= 0.90:
            role = "risk_line"
            counterevidence = "下跌广度和跌停扩散均明显，属于主要亏钱效应来源。"
        else:
            role = "rotation"
            counterevidence = "相对抗跌或中性轮动，尚无持续进攻证据。"
        selected.append({
            **row,
            "trade_date": trade_date,
            "board_rank": len(selected) + 1,
            "board_role": role,
            "canonical_theme": name,
            "catalyst": "CANNOT_CONFIRM",
            "pricing_state": "CANNOT_CONFIRM_PRICE_CAUSAL_ORDER",
            "source_available_at": "D0_CLOSE",
            "eligible_for_strict_d0_1500": False,
            "evidence_refs": [f"sector_close:{name}:{trade_date}"],
            "counterevidence": counterevidence,
            "trigger": "次日板块广度、容量承接和前排持续性同时改善才升级。",
            "invalidation": "仅单股脉冲、板块中位数转弱或风险锚继续扩散则降级。",
        })
    return selected


def _role_row(
    stock: pd.Series, role: str, board: str, explanation: str, trade_date: str,
) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "stock_code": str(stock["ts_code"]).split(".", 1)[0],
        "stock_name": str(stock["name"]),
        "board_name": board,
        "canonical_theme": board,
        "primary_role": role,
        "turnover_amount_yi": _amount_yi(stock["amount"]),
        "pct_change": round(float(stock["pct_chg"]), 4),
        "role_explanation": explanation,
        "evidence_refs": [f"stock_close:{stock['ts_code']}:{trade_date}"],
        "trigger": "次日需同时验证个股承接和同板块广度。",
        "invalidation": "个股放量失守且同板块无承接，或风险继续扩散。",
        "counterevidence": "无逐笔封单、开板次数和盘中因果证据，角色仅基于收盘价量。",
        "recommendation_status": "WATCH_ONLY",
    }


def build_role_rows(
    rows: pd.DataFrame,
    resilient_boards: list[str],
    risk_boards: list[str],
    trade_date: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for board in resilient_boards[:3]:
        peers = rows.loc[rows["sector_name"] == board].copy()
        if peers.empty:
            continue
        positive = peers.loc[peers["pct_chg"] > 0]
        leader = peers.sort_values(["pct_chg", "amount"], ascending=False).iloc[0]
        capacity_pool = positive if not positive.empty else peers
        alternatives = capacity_pool.loc[capacity_pool["ts_code"] != leader["ts_code"]]
        capacity = (alternatives if not alternatives.empty else capacity_pool).sort_values(
            ["amount", "pct_chg"], ascending=False
        ).iloc[0]
        for stock, role, explanation in (
            (leader, "tomorrow_decider", "板块收盘涨幅前排；只作为次日强度定调锚。"),
            (capacity, "capacity_anchor", "板块正收益股票中成交额靠前，用于观察容量承接。"),
        ):
            code = str(stock["ts_code"])
            if code not in seen:
                seen.add(code)
                result.append(_role_row(stock, role, board, explanation, trade_date))
    for board in risk_boards[:4]:
        peers = rows.loc[rows["sector_name"] == board].copy()
        if peers.empty:
            continue
        risk = peers.sort_values(["pct_chg", "amount"], ascending=[True, False]).iloc[0]
        code = str(risk["ts_code"])
        if code not in seen:
            seen.add(code)
            result.append(_role_row(
                risk, "risk_anchor", board, "板块跌幅前排，用于观察负反馈是否继续扩散。", trade_date
            ))
    return result


def build_close_model(rows: pd.DataFrame, trade_date: str, run_id: str) -> dict[str, Any]:
    current = prepare_close_rows(rows, trade_date)
    market = build_market_summary(current, trade_date)
    boards = build_board_rows(current, trade_date)
    resilient = [row["board_name"] for row in boards if row["board_role"] == "strong_branch"]
    risk = [row["board_name"] for row in boards if row["board_role"] == "risk_line"]
    roles = build_role_rows(current, resilient, risk, trade_date)
    conditional = [
        row for row in roles if row["primary_role"] in {"tomorrow_decider", "capacity_anchor"}
    ][:4]
    risk_rows = [row for row in roles if row["primary_role"] == "risk_anchor"][:3]
    return {
        "schema_version": "replay_model_v1",
        "status": MODEL_STATUS,
        "run_id": run_id,
        "review_date": trade_date,
        "as_of": datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%dT15:30:00+08:00"),
        "objective": f"{trade_date} D0独立完整复盘；同日视频未作为输入",
        "producer_type": "DETERMINISTIC_PYTHON",
        "target_video_review_status": "CANNOT_CONFIRM_TARGET_VIDEO_NOT_CONSUMED",
        "target_video_evidence_count": 0,
        "video_augmented_review_complete": False,
        "market_summary": market,
        "previous_plan_realization": "CANNOT_CONFIRM_PREVIOUS_PLAN_REALIZATION_WITHOUT_BOUND_PRIOR_PLAN",
        "board_rows": boards,
        "anchor_role_rows": roles,
        "scenario_tree": {
            "stronger": {
                "probability": 0.12,
                "open_trigger": ["风险线负反馈快速收敛"],
                "invalidation": ["只有指数权重护盘、个股广度仍弱"],
            },
            "inline": {
                "probability": 0.28,
                "open_trigger": ["指数企稳但个股仍分化"],
                "invalidation": ["广度与风险线同步显著改善或同步恶化"],
            },
            "weaker": {
                "probability": 0.60,
                "open_trigger": ["风险锚继续低开并扩散"],
                "invalidation": ["风险锚止跌、跌停显著收敛且市场宽度同步修复"],
            },
        },
        "shadow_watch_pool": {
            "shape": "3_CORE_4_CONDITIONAL_3_OBSERVATION_OR_RISK",
            "boundary": "SHADOW_ONLY",
            "not_buy_advice": True,
            "abstain": True,
            "abstain_reason": "WEAK_MARKET_WIDTH_ALLOW_ABSTENTION",
            "core": [],
            "conditional": conditional,
            "observation_or_risk": risk_rows,
        },
        "learning_status": "LEARNING_HYPOTHESIS_FAIL",
        "formal_generalization": "FORMAL_GENERALIZATION_PENDING",
        "model_promotion": "NO_MODEL_PROMOTED",
        "semantic_model_status": "DISABLED_BY_V3_5_NO_LLM_PRODUCTION_RULE",
        "semantic_model_call_count": 0,
        "visibility_stage": "POST_CLOSE_REVIEW_ONLY",
        "safety": dict(SAFETY),
    }
