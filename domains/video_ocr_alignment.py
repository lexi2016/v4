"""V3-equivalent video frame/ASR/news alignment for close review."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from infrastructure.data_store import _date


THEME_KEYWORDS = [
    ("机器人", "机器人"), ("芯片", "芯片"), ("半导体", "半导体"),
    ("PCB", "PCB"), ("光刻", "光刻"), ("存储", "存储"),
    ("金融", "金融"), ("证券", "金融"), ("交通", "交通"),
    ("消费", "消费"), ("高位", "高位退潮"), ("低位", "低位切换"),
    ("退潮", "风险退潮"),
]

ROLE_KEYWORDS = [
    ("跌停", "risk_anchor"), ("亏钱", "risk_anchor"),
    ("风险", "risk_anchor"), ("高位", "risk_anchor"),
    ("容量", "capacity_anchor"), ("中军", "capacity_anchor"),
    ("活口", "survivor"), ("龙头", "leader"), ("前排", "leader"),
    ("后排", "rear_row"), ("低位", "low_level_rotation"),
]


def _code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value) if value is not None and str(value).strip() else fallback
    except (TypeError, ValueError):
        return fallback


def infer_theme(text: str) -> str:
    upper = text.upper()
    for keyword, theme in THEME_KEYWORDS:
        if keyword.upper() in upper:
            return theme
    return ""


def infer_role(text: str) -> str:
    for keyword, role in ROLE_KEYWORDS:
        if keyword in text:
            return role
    return "video_mentioned"


def _stock_from_frame_path(path_text: str) -> tuple[str, str]:
    name = ""
    code = ""
    for part in Path(path_text).stem.split("_"):
        normalized = _code(part)
        if normalized and len(part) >= 6:
            code = normalized
        elif code and not name and any("\u4e00" <= char <= "\u9fff" for char in part):
            name = part
    return name, code


def frame_cell(raw: Mapping[str, Any], trade_date: str, fallback_bv: str, index: int) -> dict[str, Any]:
    """Port of V3 row_from_spotcheck; no OCR facts are invented."""
    trade_date = _date(trade_date)
    asr_text = str(raw.get("asr_text") or raw.get("text") or "")
    stock_name = str(raw.get("stock_name") or raw.get("name") or "").strip()
    stock_code = _code(raw.get("stock_code") or raw.get("code") or raw.get("ts_code"))
    if not stock_name or not stock_code:
        frame_name, frame_code = _stock_from_frame_path(str(raw.get("frame_path") or ""))
        stock_name = stock_name or frame_name
        stock_code = stock_code or frame_code
    return {
        "trade_date": trade_date,
        "bv_id": str(raw.get("bv_id") or fallback_bv),
        "frame_time": str(raw.get("frame_time") or raw.get("timestamp") or raw.get("start") or ""),
        "frame_path": str(raw.get("frame_path") or ""),
        "sheet_name": "video_spotcheck_frame",
        "row_index": str(raw.get("segment_index") or raw.get("row_index") or index),
        "col_index": "",
        "col_date": trade_date,
        "ocr_raw_text": "",
        "normalized_text": stock_name,
        "section_label": infer_theme(asr_text) or "ASR股票名抽帧核验",
        "theme": infer_theme(asr_text),
        "stock_name": stock_name,
        "stock_code": stock_code,
        "role_label": infer_role(asr_text),
        "evidence_level": "ASR_STOCKDICT_FRAME_SPOTCHECK",
        "cannot_confirm": "OCR未运行；该行来自ASR股票词典命中和对应视频帧，不直接升级为买入事实。",
        "asr_segment": str(raw.get("segment_index") or ""),
        "asr_text": asr_text,
        "source_status": str(raw.get("status") or ""),
    }


def _index_by_code(rows: list[Mapping[str, Any]], keys: tuple[str, ...] = ("stock_code", "code", "ts_code")) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        for key in keys:
            code = _code(row.get(key))
            if code:
                output.setdefault(code, row)
                break
    return output


def _index_anchor(rows: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        stock, theme = _text(row.get("stock")), _text(row.get("theme"))
        if stock:
            output.setdefault(stock, row)
        if stock and theme:
            output.setdefault(f"{theme}:{stock}", row)
    return output


def _index_board(rows: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        for key in ("stock", "stock_name", "name"):
            name = _text(row.get(key))
            if name:
                output.setdefault(name, row)
        code = _code(row.get("stock_code") or row.get("code") or row.get("ts_code"))
        if code:
            output.setdefault(code, row)
    return output


def _asr_for_cell(cell: Mapping[str, Any], segments: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    segment_id = str(cell.get("asr_segment") or cell.get("segment_index") or "").strip()
    if segment_id:
        for row in segments:
            if str(row.get("segment_index") or "").strip() == segment_id:
                return row
    frame_time = _float(cell.get("frame_time"), -1)
    if frame_time >= 0:
        for row in segments:
            if _float(row.get("start"), -1) <= frame_time <= _float(row.get("end"), -1):
                return row
    return {}


def _price_status(row: Mapping[str, Any]) -> str:
    if not row:
        return "TDX_MISSING"
    pct, amplitude = _float(row.get("pct_chg")), _float(row.get("amplitude_pct"))
    if str(row.get("is_limit_down_proxy")).lower() == "true":
        return "LIMIT_DOWN_RISK"
    if str(row.get("is_limit_up_proxy")).lower() == "true":
        return "LIMIT_UP_STRONG"
    if pct <= -7:
        return "SHARP_DOWN"
    if pct >= 7:
        return "SHARP_UP"
    if amplitude >= 8:
        return "HIGH_AMPLITUDE"
    return "NORMAL_DAILY_BAR"


def build_alignment(
    trade_date: str,
    *,
    current_asr_pointer: Mapping[str, Any],
    spotcheck_rows: list[Mapping[str, Any]],
    asr_segments: list[Mapping[str, Any]] | None = None,
    news_rows: list[Mapping[str, Any]] | None = None,
    anchor_rows: list[Mapping[str, Any]] | None = None,
    board_rows: list[Mapping[str, Any]] | None = None,
    tdx_rows: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply the exact V3 frame-to-evidence alignment and preserve its boundaries."""
    trade_date = _date(trade_date)
    if current_asr_pointer.get("trade_date") != trade_date:
        raise ValueError("current ASR pointer date mismatch")
    if current_asr_pointer.get("status") != "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY":
        return {
            "schema_version": "v3_5.video_ocr_alignment.v1",
            "status": "NOT_MATERIALIZED",
            "trade_date": trade_date,
            "reason": "ASR_STOCKDICT_NOT_READY",
            "row_count": 0,
            "rows": [],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    if not spotcheck_rows:
        return {
            "schema_version": "v3_5.video_ocr_alignment.v1",
            "status": "CANNOT_CONFIRM",
            "trade_date": trade_date,
            "reason": "VIDEO_TABLE_CELLS_MISSING_INPUT",
            "row_count": 0,
            "rows": [],
            "cannot_confirm": ["未找到可结构化的视频抽帧股票行；需要先完成ASR股票词典抽帧核验或接入OCR。"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    fallback_bv = str((current_asr_pointer.get("transcript_evidence") or [{}])[0].get("bv_id") or "")
    cells = [frame_cell(row, trade_date, fallback_bv, index) for index, row in enumerate(spotcheck_rows, 1)]
    segments = asr_segments or []
    news = _index_by_code(news_rows or [])
    anchors = _index_anchor(anchor_rows or [])
    boards = _index_board(board_rows or [])
    tdx = _index_by_code(tdx_rows or [], ("code", "ts_code", "stock_code"))
    rows: list[dict[str, Any]] = []
    for index, cell in enumerate(cells, 1):
        code, stock_name = _code(cell.get("stock_code")), str(cell.get("stock_name") or "").strip()
        name_key, theme = _text(stock_name), str(cell.get("theme") or "").strip()
        anchor = anchors.get(f"{_text(theme)}:{name_key}") or anchors.get(name_key) or {}
        news_row = news.get(code) or news.get(name_key) or {}
        board = boards.get(code) or boards.get(name_key) or {}
        daily = tdx.get(code) or {}
        segment = _asr_for_cell(cell, segments)
        row_cannot = [str(cell.get("cannot_confirm") or "").strip()]
        if not news_row:
            row_cannot.append("未命中九阳公社新闻/研报交集，不能把视频提及解释为新闻催化。")
        if not daily:
            row_cannot.append("未命中TDX日线面板，无法评估当日价量状态。")
        if not anchor:
            row_cannot.append("未命中本地角色表，视频角色仅保留ASR启发式。")
        rows.append({
            "video_cell_id": f"{trade_date}:{cell.get('bv_id')}:{index:04d}",
            "trade_date": trade_date,
            "bv_id": cell.get("bv_id", ""),
            "frame_time": cell.get("frame_time", ""),
            "col_date": cell.get("col_date", ""),
            "theme": theme or str(anchor.get("theme") or ""),
            "stock_code": code,
            "stock_name": stock_name,
            "video_role": cell.get("role_label", ""),
            "asr_segment": cell.get("asr_segment") or segment.get("segment_index", ""),
            "asr_text": cell.get("asr_text") or segment.get("text", ""),
            "news_hit_status": news_row.get("hit_status") or ("NEWS_EVENT_HIT" if news_row else "NO_NEWS_MATCH"),
            "news_title": news_row.get("source_title") or news_row.get("news_source_title") or "",
            "news_url": news_row.get("source_url") or news_row.get("news_source_url") or "",
            "catalyst_excerpt": news_row.get("event_excerpt") or "",
            "local_role_status": "LOCAL_ROLE_MATCH" if anchor else "LOCAL_ROLE_MISSING",
            "local_role_type": anchor.get("role_type", ""),
            "local_theme": anchor.get("theme", ""),
            "board_status": "BOARD_MATCH" if board else "BOARD_MISSING",
            "price_volume_status": _price_status(daily),
            "pct_chg": daily.get("pct_chg", ""),
            "amplitude_pct": daily.get("amplitude_pct", ""),
            "amount_yi": daily.get("amount_yi", ""),
            "is_limit_up_proxy": daily.get("is_limit_up_proxy", ""),
            "is_limit_down_proxy": daily.get("is_limit_down_proxy", ""),
            "final_boundary": "SHADOW_RESEARCH_ONLY_NO_BUY_GATE",
            "frame_path": cell.get("frame_path", ""),
            "evidence_level": cell.get("evidence_level", ""),
            "cannot_confirm": "；".join(item for item in row_cannot if item),
        })
    return {
        "schema_version": "v3_5.video_ocr_alignment.v1",
        "status": "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY",
        "trade_date": trade_date,
        "row_count": len(rows),
        "rows": rows,
        "boundary": ["SHADOW_ONLY", "NOT_BUY_ADVICE", "NO_BUY_GATE"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
