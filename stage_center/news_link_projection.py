"""Supplement stage cards with verified news links; never rewrite selections."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from infrastructure.shared_morning_news_reader import SharedMorningNewsReader


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def project_news_links(rows: list[dict], market: dict, *, trade_date: str,
                       morning_root: Path | str | None) -> list[dict]:
    """Caller supplies the already verified SelectionStore market and names."""
    evidence = market.get("source_evidence") or []
    cutoffs = {v.split("=", 1)[1] for v in evidence if isinstance(v, str) and v.startswith("v4_stage_cutoff=")}
    slots = {v.split("=", 1)[1] for v in evidence if isinstance(v, str) and v.startswith("v4_hourly_slot=")}
    reasons = set(market.get("cannot_confirm") or [])
    candidates = []
    for row in rows:
        match = re.fullmatch(r"(?:SH|SZ|BJ|A)\.(\d{6})", str(row.get("code") or ""))
        name = str(row.get("name") or "").strip()
        if match and len(name) >= 2:
            candidates.append({"stock_code": match[1], "stock_name": name})
    link_error = ""
    linked: dict[str, Any] = {}
    if market.get("selection_manifest_receipt_verified") is not True:
        link_error = "股票来源校验未通过，无法关联新闻"
    elif not morning_root:
        link_error = "新闻数据入口未配置"
    elif len(cutoffs) != 1:
        link_error = "阶段截止时间缺失或冲突，无法关联新闻"
    else:
        try:
            cutoff = next(iter(cutoffs))
            if len(cutoff) == 5:
                cutoff += ":00"
            linked = SharedMorningNewsReader(morning_root).link_candidates(
                trade_date, candidates, cutoff=cutoff)
        except (OSError, ValueError, TypeError, KeyError) as error:
            link_error = ("当天新闻归档缺失" if str(error) == "MORNING_NEWS_EXACT_DATE_MISSING"
                          else "新闻来源或关联解析器校验失败")
    by_code: dict[str, list[dict]] = {}
    for mention in linked.get("mentions", []):
        by_code.setdefault(str(mention.get("stock_code")), []).append(mention)
    result = []
    valid_ids = {(r["stock_code"], r["stock_name"]) for r in candidates}
    for source in rows:
        row = dict(source)
        code = str(row.get("code") or "").split(".")[-1]
        matches = by_code.get(code, [])
        if not _number(row.get("news_quality_score")):
            if link_error:
                row["news_missing_reason"] = link_error
            elif (code, str(row.get("name") or "").strip()) not in valid_ids:
                row["news_missing_reason"] = "股票代码或名称缺失，无法关联新闻"
            elif matches:
                row["news_link"] = {
                    "score": max(m["news_quality_score"] for m in matches),
                    "article_count": len(matches),
                    "articles": [{k: m.get(k) for k in ("source_title", "source_url", "published_at", "logic_excerpt")}
                                 for m in matches],
                    "mode": linked["mode"], "pit_capture_verified": False,
                    "articles_sha256": linked["articles_sha256"],
                    "candidate_identity_sha256": linked["candidate_identity_sha256"],
                    "selection_artifact_sha256": market.get("selection_artifact_sha256"),
                    "trade_date": trade_date, "cutoff": linked["cutoff"],
                }
                row["news_missing_reason"] = "原阶段未生成新闻分；补关联分未计入原阶段分"
            elif linked.get("excluded_reasons"):
                row["news_missing_reason"] = "已核验正文未匹配；另有新闻发布时间缺失或晚于阶段截止"
            else:
                row["news_missing_reason"] = "截至该阶段的新闻正文未匹配到该股票"
        if not _number(row.get("research_quality_score")):
            code_missing = f"RESEARCH_CONTEXT_CODE_MISSING:A.{code}"
            slot = next(iter(slots)) if len(slots) == 1 else ""
            label = f"{slot[:2]}:{slot[2:]} 研报归档" if slot else "该时段研报归档"
            row["research_missing_reason"] = (
                f"{label}无该股记录" if code_missing in reasons
                else f"{label}未提供可核验的个股质量分"
            )
        result.append(row)
    return result
