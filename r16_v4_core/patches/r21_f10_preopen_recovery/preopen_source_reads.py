"""Exact 11/27 source archive, kept separate from the 07:00 replay."""
from datetime import datetime
from hashlib import sha256
from html import escape
import json
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from starlette.responses import HTMLResponse

from .formal_admission_reads import read_member

DAY = "2026-11-27"
COMPACT = "20261127"
ARCHIVE_PATH = "/research/preopen-source-archive"
MORNING = "parallel_closure_20261128/B/inputs/2026-11-27/morning_news.json"
MORNING_SHA = "6d94020ff00c35f95ffa05d4fca4f6979ee35c00aebfe099c1f35a139813b22c"
CATALOG = "preopen_recovery_20261128/D27_BACKFILL_CATALOG_READBACK.json"
CATALOG_SHA = "978e2d73e5d8df5b754fea6d03af10f9f01515b99ed0904cae846cce5d97cfab"
JYG_ROLE = "JIUYANGONGSHE_MORNING_NEWS"
CATALOG_SCOPE = "EASTMONEY_HK_DATE_CATALOG"
CATALOG_OWNER = "ManagerResearchJobService.refresh_announcements"
SHANGHAI = ZoneInfo("Asia/Shanghai")
PAGE_SIZE = 20


def _exact_source(root, member, digest, limit):
    try:
        raw = read_member(root, member, limit)
        if sha256(raw).hexdigest() == digest:
            return json.loads(raw)
    except (OSError, ValueError):
        pass
    return {}


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("SOURCE_CAPTURE_TIME_MISSING")
    captured = datetime.fromisoformat(value)
    if captured.tzinfo is None:
        raise ValueError("SOURCE_CAPTURE_TIMEZONE_MISSING")
    return captured.astimezone(SHANGHAI)


def _guard(value):
    return all(value.get(key) is False for key in
               ("production_allowed", "buy_gate_updated", "orders_sent"))


def _morning(root):
    source = _exact_source(root, MORNING, MORNING_SHA, 256 * 1024)
    data = source.get("morning_news", {})
    if (source.get("trade_date") != COMPACT
            or source.get("schema_version") != "v4_core.preopen_morning_projection.v1"
            or data.get("source_role") != JYG_ROLE or data.get("status") != "MORNING_NEWS_READY"):
        return None
    articles = data.get("articles", [])
    if len(articles) != data.get("articles_count") or not articles:
        return None
    items = []
    for article in articles:
        fetched_at = _timestamp(article.get("fetched_at"))
        url = urlsplit(article.get("url", ""))
        if (fetched_at.date().isoformat() != DAY or fetched_at.hour < 8
                or article.get("capture_time_source") != "SUCCESSFUL_ARTICLE_RESPONSE_BODY_READ"
                or article.get("body_status") != "ARTICLE_BODY_READ"
                or not article.get("title") or not article.get("body_text")
                or url.scheme != "https" or url.hostname != "www.jiuyangongshe.com"
                or url.username or url.password):
            return None
        items.append({**article, "fetched_at": fetched_at.isoformat()})
    return {**data, "articles": items, "source_sha256": MORNING_SHA,
            "source_scope": "D27_POST_CUTOFF_ARCHIVE", "eligible_at_0700": False}


def _catalog(root):
    value = _exact_source(root, CATALOG, CATALOG_SHA, 6 * 1024 * 1024)
    if (value.get("readback_status") != "VERIFIED" or value.get("status") != "COMPLETE"
            or value.get("owner") != CATALOG_OWNER or value.get("source_scope") != CATALOG_SCOPE
            or value.get("target_trade_date") != COMPACT or value.get("publication_date") != DAY
            or value.get("RESEARCH_ONLY") is not True or not _guard(value)):
        return None
    data = value.get("catalog", {})
    rows = data.get("source_rows", [])
    if (data.get("owner") != CATALOG_OWNER or data.get("source") != "EASTMONEY_HK"
            or data.get("source_scope") != CATALOG_SCOPE or data.get("publication_date") != DAY
            or data.get("target_trade_date") != COMPACT or data.get("status") != "COMPLETE"
            or data.get("terminal_empty_seen") is not True or data.get("gaps") != []
            or data.get("hkex_first_publication_verified") is not False or not _guard(data)
            or len(rows) != data.get("total_hits") or not rows
            or len({row.get("art_code") for row in rows}) != len(rows)
            or any(row.get("notice_date_iso") != DAY or not row.get("title") or not row.get("art_code")
                   for row in rows)):
        return None
    captures = [_timestamp(row.get("retrieved_at")) for row in rows]
    if any(row.date().isoformat() <= DAY for row in captures):
        return None
    return {"rows": rows, "run_id": data["run_id"], "captured_from": min(captures),
            "captured_through": max(captures)}


def _metadata_row(label, value):
    return f"<p>{escape(label)} {escape(str(value))}</p>"


class PreopenSourceReads:
    def __init__(self, root):
        try:
            self.morning = _morning(root)
        except (TypeError, ValueError, AttributeError):
            self.morning = None
        try:
            self.catalog = _catalog(root)
        except (KeyError, TypeError, ValueError, AttributeError):
            self.catalog = None

    def lane(self, payload, date):
        if date != COMPACT:
            return payload
        if not (self.morning or self.catalog):
            return payload
        extra = {
            "preopen_source_archive": {
                "research_date": COMPACT, "href": f"{ARCHIVE_PATH}?date={DAY}",
                "morning_count": len(self.morning["articles"]) if self.morning else 0,
                "announcement_count": len(self.catalog["rows"]) if self.catalog else 0,
                "is_0700_evidence": False,
            }
        }
        if self.morning:
            extra["morning_news"] = self.morning
        return {**payload, **extra}

    def resolve(self, query):
        if query.get("date") != [DAY] or set(query) - {"date", "page"}:
            return HTMLResponse("未绑定该日期的盘前来源归档。", status_code=404)
        values = query.get("page", ["1"])
        page = values[0] if len(values) == 1 else ""
        if not page.isascii() or not page.isdecimal() or len(page) > 5:
            return HTMLResponse("公告归档页码无效。", status_code=404)
        number = int(page)
        count = len(self.catalog["rows"]) if self.catalog else 0
        pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
        if not (1 <= number <= pages) or not (self.morning or self.catalog):
            return HTMLResponse("未找到已核验的盘前来源归档。", status_code=404)
        return HTMLResponse(self._html(number, pages), headers={"Cache-Control": "no-store"})

    def _html(self, page, pages):
        parts = [
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>11/27 盘前来源归档</title></head><body><main>'
            '<p><a href="/?view=research&amp;date=20261127">返回 11/27 研报决策台</a></p>'
            '<h1>11/27 早报与公告归档</h1>'
            '<p>以下来源均未获 07:00 盘前准入，仅供研究回看。</p>',
        ]
        if self.morning:
            parts.append('<h2>韭研公社早报 · 3 篇</h2>'
                         '<p>原采集窗口 08:30，08:40 为重试。平台发布时间字段未附时区。</p>')
            for item in self.morning["articles"]:
                parts.append("<details><summary>" + escape(item["title"]) + "</summary>")
                parts.append(_metadata_row("平台原始发布时间", item.get("source_published_at_raw") or "待核"))
                parts.append(_metadata_row("成功采集时间（上海）", _timestamp(item["fetched_at"]).isoformat()))
                parts.append(f'<p><a href="{escape(item["url"], quote=True)}" '
                             'rel="noreferrer">原文链接</a></p>')
                parts.append('<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'
                             + escape(item["body_text"]) + "</pre></details>")
        if self.catalog:
            rows = self.catalog["rows"]
            parts.append(f'<h2>港股东财公告目录 · {len(rows)} 条</h2>'
                         '<p>11/27 同日目录于 11/28 补采，标题索引可读。'
                         '未核验港交所首次发布时间，未采集附件正文。</p>')
            parts.append(_metadata_row("补采时间（上海）", self.catalog["captured_from"].isoformat()))
            parts.append(_metadata_row("来源运行", self.catalog["run_id"]))
            parts.append(f"<p>第 {page} / {pages} 页</p><ol start=\"{(page - 1) * PAGE_SIZE + 1}\">")
            start = (page - 1) * PAGE_SIZE
            for row in rows[start:start + PAGE_SIZE]:
                parts.append(f'<li>{escape(row["title"])} · {escape(row["art_code"])}</li>')
            parts.append("</ol>")
            for number, label in ((page - 1, "上一页"), (page + 1, "下一页")):
                if 1 <= number <= pages:
                    parts.append(f'<a href="{ARCHIVE_PATH}?date={DAY}&amp;page={number}">{label}</a> ')
        parts.append("</main></body></html>")
        return "".join(parts)
