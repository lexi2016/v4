"""Pure exact-date classification for the legacy Bibabu Bilibili lane."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Mapping

from infrastructure.data_store import _date


RELEVANT_TITLE_HINTS = (
    "复盘", "A股", "指数", "主线", "题材", "涨停", "趋势", "明天", "高位", "低位",
    "机构", "兑现", "行情", "分歧", "强势", "锚定", "业绩",
)
NEGATIVE_TITLE_HINTS = ("回测系统", "止盈止损", "课程", "教程", "python", "代码")


def _date_labels(trade_date: str) -> set[str]:
    current = datetime.strptime(trade_date, "%Y%m%d")
    return {
        f"{current.month}.{current.day}",
        f"{current.month}月{current.day}",
        f"{current.month}月{current.day}日",
        f"{current.month}-{current.day}",
    }


def _previous_weekday(trade_date: str) -> str:
    current = datetime.strptime(trade_date, "%Y%m%d").date() - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current.strftime("%Y%m%d")


def classify_video_date(title: str, upload_date: str, trade_date: str) -> str:
    trade_date = _date(trade_date)
    title = re.sub(r"\s+", "", str(title or ""))
    upload_date = re.sub(r"\D", "", str(upload_date or ""))[:8]
    if any(marker.casefold() in title.casefold() for marker in NEGATIVE_TITLE_HINTS):
        return "NOT_FUPAN"
    relevant = any(marker in title for marker in RELEVANT_TITLE_HINTS)
    if not relevant:
        return "NOT_FUPAN"
    if upload_date == trade_date or any(marker in title for marker in _date_labels(trade_date)):
        return "SAME_DAY_FUPAN"
    prior = _previous_weekday(trade_date)
    if upload_date == prior or any(marker in title for marker in _date_labels(prior)):
        return "PRIOR_SESSION_FUPAN"
    return "LATEST_FUPAN_UPDATE"


def build_video_acceptance(
    trade_date: str,
    candidates: list[Mapping[str, Any]],
    *,
    lookup_status: str = "READY",
    lookup_reason: str = "",
) -> dict[str, Any]:
    trade_date = _date(trade_date)
    rows: list[dict[str, Any]] = []
    for rank, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, Mapping):
            raise ValueError("Bilibili candidate must be an object")
        bv_id = str(candidate.get("bv_id") or "")
        if not re.fullmatch(r"BV[0-9A-Za-z]+", bv_id):
            raise ValueError("invalid Bilibili BV identity")
        title = str(candidate.get("title") or "")
        upload_date = re.sub(r"\D", "", str(candidate.get("upload_date") or ""))[:8]
        rows.append({
            "candidate_rank": rank,
            "bv_id": bv_id,
            "title": title,
            "upload_date": upload_date,
            "duration": candidate.get("duration"),
            "uploader": str(candidate.get("uploader") or ""),
            "source_url": f"https://www.bilibili.com/video/{bv_id}/",
            "date_scope": classify_video_date(title, upload_date, trade_date),
            "metadata_status": "READY",
        })
    same_day = [row for row in rows if row["date_scope"] == "SAME_DAY_FUPAN"]
    if lookup_status != "READY":
        status = "TOOL_BLOCKED" if lookup_status == "TOOL_BLOCKED" else "BLOCKED_NEED_USER_COOKIE_OR_BV"
        today_status = "DAILY_VIDEO_NOT_LOCKED"
    elif same_day:
        status = "VIDEO_METADATA_READY"
        today_status = "TODAY_BV_LOCKED"
    else:
        status = "NO_NEW_VIDEO"
        today_status = "DAILY_VIDEO_NOT_LOCKED"
    return {
        "schema_version": "v3_5.bilibili_fupan_acceptance.v1",
        "status": status,
        "trade_date": trade_date,
        "today_bv_status": today_status,
        "asr_status": "NOT_USED",
        "cookie_mode": "NO_COOKIES",
        "source_index": rows,
        "locked_videos": same_day,
        "checks": {
            "source_index_rows": len(rows),
            "same_day_video_count": len(same_day),
            "target_up_route_checked": lookup_status == "READY",
            "no_video_claim_promoted_to_market_fact": True,
        },
        "cannot_confirm": [] if same_day else [lookup_reason or "SAME_DAY_VIDEO_NOT_LOCKED"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
