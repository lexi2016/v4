"""Deterministic V3 video-to-local-review gap audit."""
from __future__ import annotations

import re
from typing import Any, Mapping

from infrastructure.data_store import _date


CHECKS = [
    ("昨日预案兑现", ("昨天", "预期", "计划", "兑现", "不及预期", "失效"), "prior_plan_rows", "PLAN_TABLE_MISSING", "prior_plan_rows / markdown"),
    ("指数量能与风险状态", ("指数", "放量", "缩量", "大阴", "修复", "量能"), "market_rows", "WEAK_GATE", "summary_cards / market_rows"),
    ("早盘到午后接棒", ("早盘", "上午", "午后", "下午", "接棒", "卡位"), "intraday_handoff_rows", "NEXT_DAY_TRIGGER_GAP", "intraday_handoff_rows"),
    ("主线/风险主线分层", ("主线", "支线", "轮动", "退潮", "风险", "分歧"), "board_rows", "BOARD_COVERAGE_GAP", "BOARD_FULL_COVERAGE_TABLE"),
    ("龙头/容量锚/风险锚", ("龙头", "核心", "容量", "锚", "前排", "后排"), "anchor_role_v3_rows", "ANCHOR_ROLE_GAP", "anchor_role_v3_table"),
    ("研报/资讯催化", ("研报", "公告", "消息", "催化", "逻辑"), "catalyst_rows", "RESEARCH_CATALYST_GAP", "catalyst_matrix"),
    ("明日触发/失效", ("明天", "次日", "不追", "低吸", "跟随", "失效", "验证"), "trigger_rows", "NEXT_DAY_TRIGGER_GAP", "scenario_tree / trigger_rows"),
]


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def gap_row(
    row_id: str,
    bv_id: str,
    title: str,
    item: str,
    video_framework: str,
    local_answer: str,
    gap_type: str,
    evidence: str,
    impact: str,
    decision: str,
    backwritten_to: str,
    cannot_confirm: str = "",
) -> dict[str, Any]:
    """Exact field contract from V3 bilibili_fupan_update_watch.gap_row."""
    return {
        "row_id": row_id,
        "bv_id": bv_id,
        "timestamp": "ASR_RAW_NO_TIMESTAMP",
        "title_or_segment": title,
        "item": item,
        "video_question_or_framework": video_framework,
        "video_framework": video_framework,
        "current_review_skill_rule": item,
        "current_local_review_behavior": local_answer,
        "local_review_answer": local_answer,
        "gap_type": gap_type,
        "evidence_route": evidence,
        "evidence_path": evidence,
        "impact": impact,
        "decision": decision,
        "status": decision,
        "backwritten_to": backwritten_to,
        "cannot_confirm": cannot_confirm,
    }


def _local_review_view(review: Mapping[str, Any]) -> dict[str, list[Any]]:
    model = review.get("model_review") if isinstance(review.get("model_review"), Mapping) else {}
    market = model.get("market_summary") if isinstance(model.get("market_summary"), Mapping) else {}
    previous = str(model.get("previous_plan_realization") or "")
    return {
        "prior_plan_rows": [] if not previous or previous.startswith("CANNOT_CONFIRM") else [previous],
        "market_rows": [market] if market else [],
        "intraday_handoff_rows": review.get("intraday_handoff_rows") if isinstance(review.get("intraday_handoff_rows"), list) else [],
        "board_rows": model.get("board_rows") if isinstance(model.get("board_rows"), list) else [],
        "anchor_role_v3_rows": model.get("anchor_role_rows") if isinstance(model.get("anchor_role_rows"), list) else [],
        "catalyst_rows": review.get("catalyst_rows") if isinstance(review.get("catalyst_rows"), list) else [],
        "trigger_rows": review.get("trigger_rows") if isinstance(review.get("trigger_rows"), list) else [],
    }


def build_gap_audit(
    trade_date: str,
    *,
    bv_id: str,
    title: str,
    transcript_text: str,
    transcript_path: str,
    review: Mapping[str, Any],
    stock_mentions: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Port V3's fixed gap matrix without fuzzy recovery or model mutation."""
    trade_date = _date(trade_date)
    if review.get("trade_date") != trade_date:
        raise ValueError("review date mismatch")
    local = _local_review_view(review)
    rows: list[dict[str, Any]] = []
    if not transcript_text:
        rows.append(gap_row(
            "G001", bv_id, title, "同日视频ASR",
            "必须先有同日视频逐字稿，才能比较UP复盘框架和本地复盘质量。",
            "当前没有可用ASR逐字稿。", "ASR_UNCERTAIN", transcript_path,
            "无法做视频质量对比；页面必须显示视频未闭环。", "BLOCKED",
            "video_risk_redteam / acceptance", "FunASR transcript not found",
        ))

    next_id = len(rows) + 1
    compact = _compact(transcript_text)
    for item, words, key, gap_type, backwritten_to in CHECKS:
        video_mentions = any(word in compact for word in words)
        local_count = len(local[key])
        if not video_mentions and local_count <= 0:
            decision = "NO_ACTION"
            local_answer = "视频和本地复盘都未形成可验证材料。"
            impact = "暂不构成差距。"
        elif local_count > 0:
            decision = "LOCAL_REVIEW_HAS_OUTPUT"
            local_answer = f"本地已有 {key}={local_count} 行，可承接视频问题。"
            impact = "保留并自动纳入观察证据；股票名和视频时间段仍保持ASR_REVIEW_REQUIRED证据等级。"
        else:
            decision = "LOCAL_REVIEW_WEAK_OR_MISSING"
            local_answer = f"本地 {key} 为空或未写回。"
            impact = "用户看页面时无法理解视频指出的关键复盘维度。"
        rows.append(gap_row(
            f"G{next_id:03d}", bv_id, title, item,
            f"视频出现/可能出现 `{','.join(words[:4])}` 这一类复盘问题。",
            local_answer,
            "NO_ACTION" if decision == "LOCAL_REVIEW_HAS_OUTPUT" else gap_type,
            transcript_path,
            impact,
            decision,
            backwritten_to,
            "" if transcript_text else "ASR transcript missing",
        ))
        next_id += 1

    for stock_index, mention in enumerate(stock_mentions or [], 1):
        rows.append({
            "row_id": f"S{stock_index:03d}",
            "bv_id": str(mention.get("bv_id") or bv_id),
            "timestamp": "ASR_RAW_NO_TIMESTAMP",
            "title_or_segment": title,
            "item": "视频口播股票名",
            "stock_code": str(mention.get("stock_code") or "").split(".", 1)[0],
            "ts_code": str(mention.get("stock_code") or ""),
            "stock_name": str(mention.get("stock_name") or ""),
            "name": str(mention.get("stock_name") or ""),
            "video_question_or_framework": "B站复盘视频 ASR 精确命中 A 股股票名，作为复盘观察池补充，不作为买入门槛。",
            "video_framework": "B站复盘视频 ASR 精确命中 A 股股票名，作为复盘观察池补充，不作为买入门槛。",
            "current_review_skill_rule": "视频股票名交叉",
            "current_local_review_behavior": f"ASR stock recovery: {mention.get('stock_name', '')}({str(mention.get('stock_code') or '').split('.', 1)[0]})",
            "local_review_answer": "EXACT_LOCAL_STOCK_NAME",
            "gap_type": "ASR_UNCERTAIN",
            "role": "video_mentioned_stock",
            "theme": "video_stock_mention",
            "evidence_route": transcript_path,
            "evidence_path": transcript_path,
            "evidence_snippet": "EXACT_LOCAL_STOCK_NAME",
            "impact": "补入 D-1 复盘观察池；ASR、盘前盘口和板块承接仍保持证据等级边界。",
            "decision": "ASR_REVIEW_REQUIRED",
            "status": "ASR_REVIEW_REQUIRED",
            "backwritten_to": "video_stock_mentions_recovered / fupan_pool",
            "cannot_confirm": "ASR stock-name hit/recovery is auto-included as observation evidence; not BUY gate.",
        })

    closed = sum(row.get("decision") == "LOCAL_REVIEW_HAS_OUTPUT" for row in rows)
    status = "VIDEO_GAP_AUDIT_READY" if transcript_text and review else "VIDEO_GAP_AUDIT_PARTIAL"
    return {
        "schema_version": "v3_5.video_gap_audit.v1",
        "status": status,
        "trade_date": trade_date,
        "quality_score": round(closed / max(1, len(rows)), 4),
        "gap_rows": rows,
        "gap_row_count": len(rows),
        "closed_rows": closed,
        "transcript_path": transcript_path,
        "stock_name_hit_count": len(stock_mentions or []),
        "boundary": ["SHADOW_ONLY", "NOT_BUY_ADVICE", "NO_BUY_GATE"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
