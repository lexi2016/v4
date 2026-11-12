"""Standalone deterministic page materializer for explicit close-review inputs.

The producer accepts parsed raw public records, local daily records, selector
rows, and an already locked video audit record.  It ports the page builder's
row shaping rules without importing a legacy module or writing to a shared
dashboard.  Video is copied only into the later gap/audit section.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .producer_inputs import by_code, load_raw_page_inputs, normalize_date


SCHEMA = "review_core.local_fupan_page.v1"
PAGE_STATUS = "FUPAN_PAGE_COMPLETED_DATA_PARTIAL"
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value).replace("%", "").strip()
        return float(text) if text else default
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    return isinstance(value, bool) and value or str(value or "").strip().lower() in {"1", "true", "yes", "是"}


def _code_key(value: Any) -> str:
    return str(value or "").strip().split(".", 1)[0]


def _stock_text(row: Mapping[str, Any]) -> str:
    return f"{row.get('name') or row.get('stock_name') or row.get('code') or row.get('ts_code')}({row.get('code') or row.get('ts_code')}) {row.get('pct_chg', '')}%，{row.get('amount_yi', '')}亿"


def _compact(value: Any, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


def _require_rows(value: Any, name: str, trade_date: str, *, allow_empty: bool = True) -> list[dict[str, Any]]:
    if value is None:
        if allow_empty:
            return []
        raise ValueError(f"{name} is required")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be a list")
    target = normalize_date(trade_date)
    rows: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError(f"{name} rows must be objects")
        row = dict(raw)
        raw_date = row.get("trade_date") or row.get("target_trade_date")
        if raw_date:
            row_date = normalize_date(raw_date)
            if row_date != target:
                raise ValueError(f"{name} row trade_date {row_date} does not match {target}")
        else:
            row["target_trade_date"] = target
        row["trade_date"] = target
        rows.append(row)
    if not rows and not allow_empty:
        raise ValueError(f"{name} is empty")
    return rows


def enrich_board_rows(
    board_rows: Sequence[Mapping[str, Any]],
    stock_rows: Sequence[Mapping[str, Any]],
    daily_by_code: Mapping[str, Mapping[str, Any]],
    trade_date: str,
) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in stock_rows:
        grouped[int(row.get("board_rank") or 0)].append(row)
    enriched: list[dict[str, Any]] = []
    for board in board_rows:
        rank = int(board.get("board_rank") or 0)
        members = grouped.get(rank, [])
        matched = [daily_by_code.get(_code_key(row.get("code") or row.get("ts_code"))) for row in members]
        matched_clean = [dict(row) for row in matched if row]
        amount_sum = round(sum(_as_float(row.get("amount_yi")) for row in matched_clean), 2)
        pct_values = [_as_float(row.get("pct_chg")) for row in matched_clean if row.get("pct_chg") not in (None, "") and not row.get("split_detected")]
        split_count = sum(1 for row in matched_clean if row.get("split_detected"))
        pct_avg = round(statistics.mean(pct_values), 2) if pct_values else ""
        strong_amount = sorted(matched_clean, key=lambda row: _as_float(row.get("amount_yi")), reverse=True)[:4]
        local_capacity = "、".join(_stock_text(row) for row in strong_amount)
        split_note = f"（{split_count}只除权已排除）" if split_count else ""
        if rank == 1:
            role = "MAINLINE 主线候选"
        elif rank <= 3:
            role = "STRONG_BRANCH 强分支"
        elif int(board.get("zt_count") or 0) >= 5:
            role = "ROTATION_BRANCH 轮动分支"
        else:
            role = "WATCH_ONLY 观察分支"
        enriched.append(
            {
                "trade_date": target,
                "section": board.get("board_name"),
                "evidence_level": "DXX_THEME_CONFIRMED + TDX_DAILY_CROSSCHECK",
                "today_role": role,
                "local_evidence": (
                    f"短线侠涨停 {board.get('zt_count')} 家；催化：{board.get('board_catalyst')}；"
                    f"TDX 日线匹配 {len(matched_clean)}/{len(members)} 只，匹配成交额合计 {amount_sum} 亿，平均涨幅 {pct_avg}%{split_note}。"
                ),
                "anchors": (
                    f"高度：{board.get('leader_candidates') or '无'}；"
                    f"容量：{board.get('capacity_anchor_candidates') or local_capacity or '无'}；"
                    f"分歧：{board.get('risk_anchor_candidates') or '未见明显分歧锚'}"
                ),
                "next_trigger": "次日看容量锚是否继续承接、前排是否不瀑布、后排是否不大面积掉队；若只剩小票冲高，降级为轮动。",
                "cannot_confirm": board.get("cannot_confirm"),
            }
        )
    return enriched


def build_anchor_rows(board_rows: Sequence[Mapping[str, Any]], daily_rows: Sequence[Mapping[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    rows: list[dict[str, Any]] = []
    for board in list(board_rows)[:8]:
        rows.append(
            {
                "trade_date": target,
                "role": f"{board.get('section') or board.get('board_name')} 高度/前排锚",
                "stocks": str(board.get("leader_candidates") or board.get("top_stocks") or ""),
                "evidence": f"短线侠板块排名 {board.get('board_rank')}，涨停 {board.get('zt_count')} 家，催化：{board.get('board_catalyst')}",
                "boundary": "高度/前排锚只用于复盘结构，不等于买入依据。",
            }
        )
        if board.get("capacity_anchor_candidates"):
            rows.append(
                {
                    "trade_date": target,
                    "role": f"{board.get('section') or board.get('board_name')} 容量锚",
                    "stocks": str(board.get("capacity_anchor_candidates")),
                    "evidence": "短线侠板块内成交额/封板结构靠前；已用 TDX 日线做匹配。",
                    "boundary": "容量锚需要次日继续承接确认，不能用当日涨停池直接外推。",
                }
            )
    ordered = sorted((_row for _row in daily_rows), key=lambda row: _as_float(row.get("amount_yi")), reverse=True)
    rows.append(
        {
            "trade_date": target,
            "role": "全市场容量锚",
            "stocks": "；".join(_stock_text(row) for row in ordered[:8]),
            "evidence": "本地 TDX 5.29 日线全市场重建后按成交额排序。",
            "boundary": "容量强不等于主线，必须和题材/板块/分时承接一起验证。",
        }
    )
    negative_amount = [row for row in ordered if row.get("pct_chg") not in (None, "") and _as_float(row.get("pct_chg")) < 0][:6]
    rows.append(
        {
            "trade_date": target,
            "role": "全市场风险锚",
            "stocks": "；".join(_stock_text(row) for row in negative_amount),
            "evidence": "本地 TDX 5.29 日线中高成交负收益样本。",
            "boundary": "风险锚用于判断分歧和亏钱效应，不作为反向推荐。",
        }
    )
    return rows


def build_catalyst_rows(board_rows: Sequence[Mapping[str, Any]], jyg_all_count: int | None, trade_date: str) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    rows: list[dict[str, Any]] = []
    for board in list(board_rows)[:12]:
        catalyst = str(board.get("board_catalyst") or "")
        quality = "PUBLIC_DXX_CATALYST_WITH_RUMOR_BOUNDARY" if any(marker in catalyst for marker in ("传闻", "网传", "未证实")) else "PUBLIC_DXX_CATALYST"
        rows.append(
            {
                "trade_date": target,
                "direction": board.get("board_name"),
                "catalyst": catalyst,
                "source": "短线侠涨停复盘",
                "quality": quality,
                "action": "可解释题材，不证明强度；强度以涨停池 + TDX 日线 + 分时承接验证。",
                "boundary": "若催化含传闻/小作文，复盘只能写线索，不能写实锤。",
            }
        )
    rows.append(
        {
            "trade_date": target,
            "direction": "韭研公社",
            "catalyst": f"{datetime_display(target)} 公开异动页 allCount={jyg_all_count}",
            "source": "韭研公社公开页",
            "quality": "METADATA_ONLY_NO_USABLE_ROWS" if not jyg_all_count else "PUBLIC_JYG_ROWS_FETCHED",
            "action": "本轮无可用正文时不写入事实；只作为已查询证据。",
            "boundary": "不能把未返回的异动正文补造成催化。",
        }
    )
    return rows


def datetime_display(trade_date: str) -> str:
    target = normalize_date(trade_date)
    return f"{target[:4]}-{target[4:6]}-{target[6:]}"


def build_anchor_role_v3_rows(board_stock_rows: Sequence[Mapping[str, Any]], daily_by_code: Mapping[str, Mapping[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in board_stock_rows:
        grouped[str(row.get("board_name") or "")].append(row)
    rows: list[dict[str, Any]] = []
    for theme, members in grouped.items():
        ordered = sorted(members, key=lambda row: (int(row.get("stock_order_in_board") or 999), -_as_float(row.get("turnover_amount_yi"))))
        for index, row in enumerate(ordered[:8], start=1):
            code = str(row.get("code") or "")
            daily = daily_by_code.get(code, {})
            pct = daily.get("pct_chg", "")
            amount = daily.get("amount_yi", "")
            role_type = "rear_row"
            if index == 1 or _as_float(row.get("lianban_num_int")) >= 2:
                role_type = "leader"
            elif _as_float(row.get("turnover_amount_yi")) >= 10 or _as_float(amount) >= 10:
                role_type = "capacity_anchor"
            if str(row.get("limit_type")) in {"分歧板", "回封板"} or str(row.get("open_board_times")) not in {"", "0"}:
                role_type = "risk_anchor" if role_type == "rear_row" else role_type
            rows.append(
                {
                    "trade_date": target,
                    "theme": theme,
                    "stock": str(row.get("name") or code),
                    "role_type": role_type,
                    "why_this_role": f"短线侠板块第{row.get('board_rank')}行内第{index}；涨停形态={row.get('limit_type')}; TDX日线涨幅={pct}%，成交额={amount}亿。",
                    "confirmed_by": "短线侠涨停池 + 本地TDX日线 + 开盘阶段1分钟K代理",
                    "not_confirmed_by": "未确认逐笔主动买卖、十档队列、撤单、未匹配量、视频同日逐字稿。",
                    "tomorrow_if_strong": "次日看前排/容量锚是否继续承接，不能只看后排冲高。",
                    "tomorrow_if_weak": "若容量锚或前排负反馈，降级为轮动/风险观察。",
                    "cannot_confirm": "角色用于复盘学习和次日验证树，不是买入建议。",
                }
            )
    return rows


def build_formal_pool_validation(formal_rows: Sequence[Mapping[str, Any]], daily_rows: Sequence[Mapping[str, Any]], trade_date: str) -> dict[str, Any]:
    target = normalize_date(trade_date)
    daily_by_code = {_code_key(row.get("code") or row.get("ts_code")): row for row in daily_rows}
    matched: list[dict[str, Any]] = []
    for row in formal_rows:
        daily = daily_by_code.get(_code_key(row.get("stock_code") or row.get("ts_code")))
        if not daily:
            continue
        pct = _as_float(daily.get("pct_chg"))
        matched.append(
            {
                "stock_code": _code_key(row.get("stock_code") or row.get("ts_code")),
                "stock_name": row.get("stock_name") or daily.get("name") or "",
                "rank": row.get("rank") or "",
                "pct_chg": pct,
                "amount_yi": _as_float(daily.get("amount_yi")),
                "is_limit_up_proxy": _truthy(daily.get("is_limit_up_proxy")),
                "is_limit_down_proxy": _truthy(daily.get("is_limit_down_proxy")),
                "source_path": daily.get("source_path") or "",
            }
        )
    pct_values = [row["pct_chg"] for row in matched]
    avg_pct = round(statistics.mean(pct_values), 4) if pct_values else None
    median_pct = round(statistics.median(pct_values), 4) if pct_values else None
    up_count = sum(value > 0 for value in pct_values)
    down_count = sum(value < 0 for value in pct_values)
    weak = bool(pct_values) and (down_count > up_count or (median_pct is not None and median_pct < 0))
    return {
        "trade_date": target,
        "status": "FORMAL_POOL_WEAK_REALIZATION" if weak else "FORMAL_POOL_REALIZATION_REVIEWED",
        "display_status": "正式池兑现偏弱" if weak else "正式池兑现已复核",
        "pool_rows": len(formal_rows),
        "matched_daily": len(matched),
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": len(pct_values) - up_count - down_count,
        "limit_up_proxy": sum(1 for row in matched if row["is_limit_up_proxy"]),
        "limit_down_proxy": sum(1 for row in matched if row["is_limit_down_proxy"]),
        "avg_pct": avg_pct,
        "median_pct": median_pct,
        "formal_recommendation_allowed": False,
        "interpretation": (
            f"正式池 {len(formal_rows)} 只，匹配 TDX {len(matched)} 只，上涨 {up_count}、下跌 {down_count}，均值 {avg_pct}%、中位数 {median_pct}%；不能包装成计划有效兑现。"
            if weak
            else "正式池已按当日日线复核；仍不能替代次日开盘盘口确认。"
        ),
        "top_up": sorted(matched, key=lambda item: item["pct_chg"], reverse=True)[:8],
        "top_down": sorted(matched, key=lambda item: item["pct_chg"])[:12],
        "evidence_paths": [str(row.get("source_path") or "") for row in matched if row.get("source_path")],
    }


def build_prior_plan_rows(board_rows: Sequence[Mapping[str, Any]], stage_counts: Mapping[str, Mapping[str, int]], trade_date: str) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    rows: list[dict[str, Any]] = []
    stage4 = stage_counts.get("stage4", {})
    for board in list(board_rows)[:8]:
        section = str(board.get("section") or "")
        rows.append(
            {
                "trade_date": target,
                "planned_anchor": section,
                "prior_expectation": "承接 D-1 复盘观察池/Stage7 明日观察池，先看开盘四阶段。",
                "mapped_theme": section,
                "open_realization": f"Stage4 强承接 {stage4.get('阶段强承接观察', 0)}，一般 {stage4.get('阶段承接一般观察', 0)}。",
                "intraday_validation": "Stage6/Stage7 已接入，均为 1分钟K代理；不能确认L2盘口。",
                "close_result": str(board.get("today_role") or ""),
                "tomorrow_scenario": str(board.get("next_trigger") or ""),
                "cannot_confirm": "该行是复盘验证树，不是买卖计划。",
            }
        )
    return rows


def build_handoff_rows(board_rows: Sequence[Mapping[str, Any]], stage7_counts: Mapping[str, int], trade_date: str) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    return [
        {
            "trade_date": target,
            "theme": str(board.get("section") or ""),
            "morning_anchor": str(board.get("anchors") or "").split("；", 1)[0],
            "morning_status": "开盘四阶段已接入，证据等级 DATA_PARTIAL_PYTDX_1MIN_BAR。",
            "afternoon_handoff": f"Stage7 标签分布：{dict(stage7_counts)}",
            "failed_anchor": "未接入结构化L2，失败锚只能按日线/1分钟K代理识别。",
            "stage_l0_evidence": str(board.get("local_evidence") or ""),
            "close_role": str(board.get("today_role") or ""),
            "cannot_confirm": "不能用尾盘强弱倒推开盘买点。",
        }
        for board in list(board_rows)[:10]
    ]


def build_scenario_rows(board_rows: Sequence[Mapping[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    result: list[dict[str, Any]] = []
    for board in list(board_rows)[:10]:
        section = str(board.get("section") or "")
        result.extend(
            [
                {
                    "trade_date": target,
                    "theme": section,
                    "scenario": "强于预期",
                    "need_to_see": "容量锚和前排不瀑布，次日 09:25-09:45 承接继续强。",
                    "action": "保留观察池，等待真实盘口确认。",
                    "reject_if": "只有后排冲高或容量锚转弱。",
                    "evidence_route": "正式 selector + D-1复盘池 + 09:25/09:45阶段证据。",
                    "cannot_confirm": "不是买入清单。",
                },
                {
                    "trade_date": target,
                    "theme": section,
                    "scenario": "弱于预期",
                    "need_to_see": "竞价低于预期、开盘承接失败或尾盘锚同步转弱。",
                    "action": "降级为风险/轮动观察。",
                    "reject_if": "用收盘涨幅替代开盘承接。",
                    "evidence_route": "次日阶段证据 + 分时承接。",
                    "cannot_confirm": "当前不预测确定涨跌。",
                },
            ]
        )
    return result


def build_trigger_rows(trade_date: str) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    return [
        {
            "trade_date": target,
            "condition": "强于预期",
            "need": "次日主线前排与容量锚继续承接，09:25-09:45 不弱化。",
            "action": "只保留观察池，等待盘口确认。",
            "reject_if": "只剩后排冲高、容量锚转弱或开盘承接失败。",
        },
        {
            "trade_date": target,
            "condition": "弱于预期",
            "need": "竞价低于预期、开盘失守、尾盘锚同步转弱。",
            "action": "降级为风险观察，不追后排。",
            "reject_if": "用收盘涨幅倒推开盘买点。",
        },
    ]


def build_rule_rows(rule_rows: Sequence[Mapping[str, Any]] | None, trade_date: str) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(list(rule_rows or [])[:30], start=1):
        status = str(item.get("status") or item.get("adoption_status") or "")
        rows.append(
            {
                "trade_date": target,
                "rule": str(item.get("rule_id") or item.get("name") or item.get("title") or f"rule_{index}"),
                "source_bv": str(item.get("source_video_bv") or item.get("bv") or ""),
                "rule_type": str(item.get("rule_type") or item.get("type") or ""),
                "old_status": status,
                "source_quality": "RULE_LIBRARY_READ",
                "suggested_status": status if status else "candidate",
                "output_change": "注入复盘提问/验收边界；不直接写成当日买卖事实。",
                "reason": "规则只作为复盘问题和验收边界，不作为当日结论。",
            }
        )
    if not rows:
        rows.append(
            {
                "trade_date": target,
                "rule": "rule_library_inventory",
                "source_bv": "",
                "rule_type": "inventory",
                "old_status": "missing_or_empty",
                "source_quality": "RULE_LIBRARY_MISSING_OR_EMPTY",
                "suggested_status": "blocked",
                "output_change": "只显示规则库缺口。",
                "reason": "未找到可解析规则行。",
            }
        )
    return rows


def _video_layer(video: Mapping[str, Any] | None, trade_date: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    target = normalize_date(trade_date)
    if not video:
        return (
            {
                "status": "DAILY_VIDEO_NOT_LOCKED",
                "trade_date": target,
                "date_scope": "CANNOT_CONFIRM",
                "bv_id": "",
                "title": "",
                "asr_status": "ASR_REVIEW_REQUIRED",
                "targeted_spotcheck_count": 0,
                "cannot_confirm": ["exact-date video audit input missing"],
            },
            [],
            [],
        )
    item = dict(video)
    raw_date = item.get("trade_date") or item.get("target_trade_date")
    if not raw_date or normalize_date(raw_date) != target:
        raise ValueError("video trade_date does not match target")
    item["trade_date"] = target
    gaps = [dict(row) for row in item.get("gap_rows", []) if isinstance(row, Mapping)]
    for row in gaps:
        if row.get("trade_date") and normalize_date(row["trade_date"]) != target:
            raise ValueError("video gap row trade_date does not match target")
        row["trade_date"] = target
    learning = [dict(row) for row in item.get("learning_rows", []) if isinstance(row, Mapping)]
    for row in learning:
        if row.get("trade_date") and normalize_date(row["trade_date"]) != target:
            raise ValueError("video learning row trade_date does not match target")
        row["trade_date"] = target
    item.setdefault("status", "VIDEO_GAP_AUDIT_READY" if gaps else "ASR_REVIEW_REQUIRED")
    item.setdefault("date_scope", "SAME_DAY_FUPAN")
    item.setdefault("asr_status", "ASR_REVIEW_REQUIRED")
    item.setdefault("targeted_spotcheck_count", 0)
    return item, gaps, learning


def build_fupan_page_payload(
    trade_date: str,
    raw_inputs: Mapping[str, Any],
    *,
    video: Mapping[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    target = normalize_date(trade_date)
    if not isinstance(raw_inputs, Mapping):
        raise ValueError("raw_inputs must be a mapping")
    if normalize_date(raw_inputs.get("trade_date") or target) != target:
        raise ValueError("raw input trade_date does not match target")
    board_raw = _require_rows(raw_inputs.get("dxx_board_raw"), "dxx_board_raw", target, allow_empty=False)
    stock_rows = _require_rows(raw_inputs.get("dxx_stock_rows"), "dxx_stock_rows", target, allow_empty=False)
    daily_rows = _require_rows(raw_inputs.get("daily_rows"), "daily_rows", target, allow_empty=False)
    daily_by_code = by_code(daily_rows)
    board_rows = enrich_board_rows(board_raw, stock_rows, daily_by_code, target)
    anchor_rows = build_anchor_rows(board_raw, daily_rows, target)
    jyg_count = raw_inputs.get("jyg_all_count")
    catalyst_rows = build_catalyst_rows(board_raw, int(jyg_count) if jyg_count not in (None, "") else None, target)
    anchor_role_rows = build_anchor_role_v3_rows(stock_rows, daily_by_code, target)
    stage_counts = raw_inputs.get("stage_counts") if isinstance(raw_inputs.get("stage_counts"), Mapping) else {"stage4": {}, "stage5": {}, "stage6": {}, "stage7": {}}
    formal_rows = _require_rows(raw_inputs.get("formal_rows"), "formal_rows", target)
    review_rows = _require_rows(raw_inputs.get("review_rows"), "review_rows", target)
    tplus1_rows = _require_rows(raw_inputs.get("tplus1_rows"), "tplus1_rows", target)
    formal_validation = build_formal_pool_validation(formal_rows, daily_rows, target)
    prior_plan_rows = build_prior_plan_rows(board_rows, stage_counts, target)
    handoff_rows = build_handoff_rows(board_rows, stage_counts.get("stage7", {}), target)
    scenario_rows = build_scenario_rows(board_rows, target)
    rules = build_rule_rows(raw_inputs.get("rule_rows"), target)
    video_layer, gap_rows, learning_rows = _video_layer(video, target)
    daily_stats = dict(raw_inputs.get("daily_stats") or {})
    qingxu_rows = _require_rows(raw_inputs.get("qingxu_rows"), "qingxu_rows", target)
    lianban_rows = _require_rows(raw_inputs.get("dxx_lianban_rows"), "dxx_lianban_rows", target)
    market_rows = [
        {"trade_date": target, "source": "短线侠", "metric": ("成交额_亿元" if row.get("metric") == "HSLN" else row.get("metric_name") or row.get("metric")), "value": row.get("value"), "evidence": row.get("evidence_state")}
        for row in qingxu_rows
    ] + [
        {"trade_date": target, "source": "TDX日线", "metric": "全市场行数", "value": daily_stats.get("rows", len(daily_rows)), "evidence": daily_stats.get("evidence_state", "LOCAL_TDX_DAILY_PANEL_REBUILT")},
        {"trade_date": target, "source": "TDX日线", "metric": "成交额合计_亿元", "value": daily_stats.get("amount_sum_yi"), "evidence": daily_stats.get("evidence_state", "LOCAL_TDX_DAILY_PANEL_REBUILT")},
        {"trade_date": target, "source": "TDX日线", "metric": "上涨/下跌", "value": f"{daily_stats.get('up_count', '')}/{daily_stats.get('down_count', '')}", "evidence": daily_stats.get("evidence_state", "LOCAL_TDX_DAILY_PANEL_REBUILT")},
        {"trade_date": target, "source": "TDX日线", "metric": "涨停/跌停代理", "value": f"{daily_stats.get('limit_up_proxy_count', '')}/{daily_stats.get('limit_down_proxy_count', '')}", "evidence": daily_stats.get("evidence_state", "LOCAL_TDX_DAILY_PANEL_REBUILT")},
        {"trade_date": target, "source": "TDX日线", "metric": "涨幅均值/中位数", "value": f"{daily_stats.get('pct_mean', '')}/{daily_stats.get('pct_median', '')}", "evidence": daily_stats.get("evidence_state", "LOCAL_TDX_DAILY_PANEL_REBUILT")},
    ]
    summary_cards = [
        {"title": "状态边界", "value": "DATA_PARTIAL", "body": "复盘只确认日线/板块/锚点骨架；L2逐笔、同日视频和实时阶段需另行验收。", "trade_date": target},
        {"title": "正式池兑现", "value": formal_validation["display_status"], "body": formal_validation["interpretation"], "trade_date": target},
        {"title": "视频差距红队", "value": video_layer.get("status"), "body": "视频仅作为复盘后的差距审计增强，不写入独立复盘事实。", "trade_date": target},
        {"title": "事件正文", "value": "未形成可用正文事件行", "body": "缺少正文时不补造事件。", "trade_date": target},
        {"title": "首屏看什么", "value": str(board_rows[0].get("section") if board_rows else "CANNOT_CONFIRM"), "body": "题材骨架只作复盘材料，不等于买入结论。", "trade_date": target},
        {"title": "市场宽度", "value": f"涨停 {daily_stats.get('limit_up_proxy_count', '-')}, 跌停 {daily_stats.get('limit_down_proxy_count', '-')}", "body": f"TDX日线 {daily_stats.get('rows', len(daily_rows))} 行。", "trade_date": target},
        {"title": "开盘阶段", "value": "实时4/7 + 回放3/7", "body": "阶段行必须显式传入，不能包装成实时可交易证据。", "trade_date": target},
        {"title": "题材证据", "value": f"{len(board_raw)}个板块", "body": f"板块 {len(board_raw)} 行、涨停股 {len(stock_rows)} 行、连板结果 {len(lianban_rows)} 行。", "trade_date": target},
        {"title": "容量锚", "value": "TDX日线补齐", "body": "按成交额保留容量观察锚。", "trade_date": target},
        {"title": "规则/视频资产", "value": "已盘点", "body": "规则和视频仅用于复盘问题与验收边界。", "trade_date": target},
    ]
    independent = {"target_video_used": False, "video_input_count": 0, "video_augmented": False}
    cannot_confirm = _require_rows(raw_inputs.get("cannot_confirm_items"), "cannot_confirm_items", target)
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA,
        "run_id": run_id or f"LOCAL_FUPAN_PAGE_{target}",
        "ok": True,
        "trade_date": target,
        "generated_at": str(raw_inputs.get("generated_at") or "explicit-input-run"),
        "status": PAGE_STATUS,
        "display_status": f"{datetime_display(target)}复盘已接入（数据部分）",
        "data_completeness": {"status": "EVIDENCE_BOUNDED", "available": [f"TDX日线 {len(daily_rows)} 行", f"板块结构 {len(board_rows)} 行", f"锚点角色 {len(anchor_role_rows)} 行"], "missing": ["L2逐笔/十档/撤单轨迹", "T+1验证"], "meaning": "数据不完整只表示精度证据边界，不表示日线、板块或锚点为空。"},
        "summary": {
            "one_line": f"{datetime_display(target)} 页面已补齐复盘骨架，但保持 DATA_PARTIAL：短线侠板块 {len(board_raw)} 行、涨停股 {len(stock_rows)} 行；不能替代次日开盘盘口确认。",
            "formal_pool_rows": len(formal_rows),
            "review_pool_rows": len(review_rows),
            "dxx_board_rows": len(board_raw),
            "dxx_stock_rows": len(stock_rows),
            "dxx_lianban_rows": len(lianban_rows),
            "jyg_all_count": jyg_count,
            "tdx_daily_rows": len(daily_rows),
            "tplus1_rows": len(tplus1_rows),
        },
        "summary_cards": summary_cards,
        "formal_pool_validation": formal_validation,
        "video_risk_redteam": {"status": video_layer.get("status"), "display_status": "目标交易日视频差距审计已物化", "bv_id": video_layer.get("bv_id"), "title": video_layer.get("title"), "upload_date": video_layer.get("upload_date"), "date_scope": video_layer.get("date_scope"), "gap_rows": gap_rows, "safety_flags": dict(SAFETY_FLAGS), "independent_review_impact": "NONE"},
        "video_gap_rows": gap_rows,
        "video_learning_rows": learning_rows,
        "prior_plan_rows": prior_plan_rows,
        "intraday_handoff_rows": handoff_rows,
        "anchor_role_v3_rows": anchor_role_rows,
        "scenario_tree_rows": scenario_rows,
        "rule_adoption_rows": rules,
        "board_rows": board_rows,
        "market_rows": market_rows,
        "news_article_rows": _require_rows(raw_inputs.get("news_article_rows"), "news_article_rows", target),
        "news_event_rows": _require_rows(raw_inputs.get("news_event_rows"), "news_event_rows", target),
        "news_research_hit_rows": _require_rows(raw_inputs.get("news_research_hit_rows"), "news_research_hit_rows", target),
        "news_event_source_paths": dict(raw_inputs.get("news_event_source_paths") or {}),
        "morning_news_acceptance": dict(raw_inputs.get("morning_news_acceptance") or {}),
        "anchor_rows": anchor_rows,
        "catalyst_rows": catalyst_rows,
        "trigger_rows": build_trigger_rows(target),
        "source_status_rows": _require_rows(raw_inputs.get("source_status_rows"), "source_status_rows", target),
        "cannot_confirm_items": cannot_confirm,
        "independent_review": independent,
        "safety_flags": dict(SAFETY_FLAGS),
        "artifact_paths": {},
    }


def build_fupan_page_from_raw_paths(trade_date: str, *, plate_json: str | Path, lianban_json: str | Path, qingxu_json: str | Path, tdx_root: str | Path, name_map: Mapping[str, str], jyg_html: str | Path | None = None, video: Mapping[str, Any] | None = None, formal_rows: Sequence[Mapping[str, Any]] | None = None, review_rows: Sequence[Mapping[str, Any]] | None = None, tplus1_rows: Sequence[Mapping[str, Any]] | None = None, stage_counts: Mapping[str, Mapping[str, int]] | None = None, rule_rows: Sequence[Mapping[str, Any]] | None = None, run_id: str | None = None) -> dict[str, Any]:
    raw = load_raw_page_inputs(trade_date, plate_json=plate_json, lianban_json=lianban_json, qingxu_json=qingxu_json, tdx_root=tdx_root, name_map=name_map, jyg_html=jyg_html)
    raw.update({"formal_rows": list(formal_rows or []), "review_rows": list(review_rows or []), "tplus1_rows": list(tplus1_rows or []), "stage_counts": dict(stage_counts or {}), "rule_rows": list(rule_rows or [])})
    return build_fupan_page_payload(trade_date, raw, video=video, run_id=run_id)


def _safe_output_dir(output_dir: str | os.PathLike[str]) -> Path:
    root = Path(output_dir).expanduser().resolve()
    lowered = {part.lower() for part in root.parts}
    if ".runtime" in lowered or "30_runtime" in lowered or "v35" in lowered:
        raise ValueError("output_dir is reserved for an application/runtime tree")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _atomic_json(path: Path, value: Mapping[str, Any]) -> str:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=path.parent, prefix=f".{path.name}.") as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return hashlib.sha256(encoded).hexdigest()


def write_fupan_page_run(trade_date: str, raw_inputs: Mapping[str, Any], output_dir: str | os.PathLike[str], *, video: Mapping[str, Any] | None = None, run_id: str | None = None) -> dict[str, Path]:
    payload = build_fupan_page_payload(trade_date, raw_inputs, video=video, run_id=run_id)
    root = _safe_output_dir(output_dir)
    payload_path = root / f"fupan_payload_{payload['trade_date']}.json"
    manifest_path = root / "manifest.json"
    receipt_path = root / "receipt.json"
    payload_sha = _atomic_json(payload_path, payload)
    manifest = {"schema": f"{SCHEMA}.manifest", "trade_date": payload["trade_date"], "run_id": payload["run_id"], "payload_sha256": payload_sha, "input_mode": "explicit_raw_records", "safety_flags": dict(SAFETY_FLAGS)}
    manifest_sha = _atomic_json(manifest_path, manifest)
    receipt = {"schema": f"{SCHEMA}.receipt", "trade_date": payload["trade_date"], "run_id": payload["run_id"], "status": "WRITTEN", "payload_sha256": payload_sha, "manifest_sha256": manifest_sha, "safety_flags": dict(SAFETY_FLAGS)}
    _atomic_json(receipt_path, receipt)
    return {"payload": payload_path, "manifest": manifest_path, "receipt": receipt_path}


__all__ = [
    "PAGE_STATUS",
    "SCHEMA",
    "build_anchor_role_v3_rows",
    "build_fupan_page_from_raw_paths",
    "build_fupan_page_payload",
    "build_formal_pool_validation",
    "build_handoff_rows",
    "build_prior_plan_rows",
    "build_scenario_rows",
    "enrich_board_rows",
    "write_fupan_page_run",
]
