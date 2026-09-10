"""Compact public-HTML collector for the three 韭研公社 morning articles."""
from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from scripts.live_acquisition.universe import resolve_stage_universe

from .consumer import read_verified_latest
from .hashing import sha256_json
from .morning_news import SCHEMA_VERSION, _clean_code, materialize_stock_mentions
from .v192_selector import PREMARKET_SCORE_FORMULA, V192_ROLE
from .paths import validate_date
from .store import StoreError

_BASE = "https://www.jiuyangongshe.com/"
_ARTICLE_BASE = f"{_BASE}a/"
_KEYWORDS = ("开盘必读", "盘前纪要", "盘前解读", "盘前重要纪要")
_SLOTS = ("开盘必读", "盘前纪要", "盘前解读")
_SEARCH_TEMPLATES = {
    "开盘必读": "{label}开盘必读资讯",
    "盘前纪要": "{label}盘前纪要",
    # The visible official title contains a separating space; matching is
    # compacted below so the title and query remain equivalent.
    "盘前解读": "{label} 盘前解读",
}
_FETCH_ATTEMPTS = 2
_SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


class MorningNewsNotReady(ValueError):
    """Fewer than three exact-date readable articles are currently public."""


def load_shared_candidate_registry(root: Path | str, trade_date: str) -> list[dict[str, Any]]:
    """Read explicit V3 intersection fields from the shared candidate contracts.

    The stage-universe and frozen V1.9.2 pool are independent shared artifacts;
    no legacy V3 path is consulted.  ``formal_pool_hit`` denotes membership in
    that shared pool contract and never enables formal recommendation or orders.
    """

    trade_date = validate_date(trade_date)
    root = Path(root)
    try:
        universe = resolve_stage_universe(root, trade_date, "A_SHARE")
        verified = read_verified_latest(root, trade_date, V192_ROLE)
    except (OSError, ValueError, StoreError):
        # Missing or tampered universe/pool evidence is a typed data gap, not
        # permission to inspect an arbitrary run directory.
        return []
    if verified.verification.get("status") != "READY":
        return []
    provenance = verified.manifest.get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("premarket_score_formula") != PREMARKET_SCORE_FORMULA:
        return []
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if verified.receipt.get(key) is not False:
            return []
        if key in verified.manifest and verified.manifest.get(key) is not False:
            return []
    universe_codes = {_clean_code(code) for code in universe.codes if _clean_code(code)}
    artifact_path = verified.artifact_path
    try:
        with artifact_path.open("r", encoding="utf-8-sig", newline="") as handle:
            pool_rows = list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        return []
    if len(pool_rows) != int(verified.verification.get("row_count") or -1):
        return []
    if any(
        str(row.get("premarket_score_formula") or "") != PREMARKET_SCORE_FORMULA
        or str(row.get("premarket_pool_score") or "").strip() == ""
        for row in pool_rows
    ):
        return []
    registry: list[dict[str, Any]] = []
    for row in pool_rows:
        code = _clean_code(row.get("stock_code") or row.get("ts_code"))
        name = str(row.get("stock_name") or "").strip()
        if not code or len(name) < 2:
            continue
        registry.append(
            {
                "stock_code": code,
                "stock_name": name,
                "preselect_hit": "Y" if code in universe_codes else "N",
                # This is an explicit field in the shared candidate contract,
                # materialized from the verified role, never inferred by V35
                # from pool_id/selector_version display metadata.
                "formal_pool_hit": "Y",
                "research_hit_status": "RESEARCH_HIT_NOT_CONFIRMED",
                # V3's morning-news research lane starts public HTML items at
                # confidence 24.  Visible-pool evidence is independent and
                # remains an explicit verified zero in this shared contract.
                "research_source_confidence": 24.0,
                "research_visible_hit": "N",
                "source_type": "正文股票名匹配",
                "field_provenance": f"SHARED_VERIFIED_{V192_ROLE}",
                "evidence_path": str(artifact_path),
            }
        )
    return registry


def _default_fetcher(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 V3SharedMorningNews/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        content_type = response.headers.get("content-type", "")
    match = re.search(r"charset=([\w-]+)", content_type, re.I)
    return raw.decode(match.group(1) if match else "utf-8", errors="replace")


def _fetch_with_retry(fetcher: Callable[[str], str], url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(_FETCH_ATTEMPTS):
        try:
            return fetcher(url)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt + 1 >= _FETCH_ATTEMPTS:
                break
    raise MorningNewsNotReady(f"public morning news fetch retries exhausted for {url}") from last_error


def _decode_js(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return html.unescape(value)


def _strip_tags(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<br\s*/?>|</(?:p|div|li|section|article)>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _title(raw: str) -> str:
    match = re.search(r"<title>(.*?)</title>", raw, flags=re.I | re.S)
    if not match:
        return ""
    return re.sub(r"[-_—]+韭研公社$", "", html.unescape(match.group(1)).strip())


def _published(raw: str) -> str:
    match = re.search(r"20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", raw)
    return match.group(0) if match else ""


def _body(raw: str) -> str:
    match = re.search(r'content:"((?:\\.|[^"\\])*)"', raw)
    if not match:
        return ""
    return _strip_tags(_decode_js(match.group(1)))


def _slot(title: str, trade_date: str) -> str:
    date = datetime.strptime(trade_date, "%Y%m%d")
    compact = re.sub(r"\s+", "", title)
    if f"{date.month}月{date.day}日" not in compact:
        return ""
    if "开盘必读" in compact:
        return "开盘必读"
    if "盘前纪要" in compact and "盘前重要纪要" not in compact:
        return "盘前纪要"
    if "盘前解读" in compact or "盘前重要纪要" in compact:
        return "盘前解读"
    return ""


def _homepage_records(raw: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r'article_id:"(?P<id>[a-z0-9]+)".*?title:"(?P<title>(?:\\.|[^"\\])*)".*?create_time:"(?P<time>20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"',
        flags=re.S,
    )
    records = []
    for match in pattern.finditer(raw):
        records.append(
            {
                "id": match.group("id"),
                "title": _decode_js(match.group("title")),
                "published_at": match.group("time"),
            }
        )
    return records


def _search_title(slot: str, trade_date: str) -> str:
    date = datetime.strptime(trade_date, "%Y%m%d")
    label = f"{date.month}月{date.day}日"
    return _SEARCH_TEMPLATES[slot].format(label=label)


def _search_url(slot: str, trade_date: str) -> str:
    query = _search_title(slot, trade_date)
    return f"{_BASE}search/new?{urllib.parse.urlencode({'k': query})}"


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", html.unescape(value))


def _search_records(raw: str, trade_date: str, slot: str) -> list[dict[str, str]]:
    """Extract same-day article links from the server-rendered official search page."""

    iso_date = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
    title_query = _compact(_search_title(slot, trade_date))
    records: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    link_pattern = re.compile(r'<a\b[^>]*href=["\']/a/(?P<id>[a-z0-9]+)["\']', flags=re.I)
    for match in link_pattern.finditer(raw):
        context = raw[max(0, match.start() - 1800) : match.end() + 3000]
        visible = _strip_tags(context)
        if iso_date not in visible or title_query not in _compact(visible):
            continue
        article_id = match.group("id")
        if article_id in seen_ids:
            continue
        time_match = re.search(r"20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", visible)
        records.append(
            {
                "id": article_id,
                "title": _search_title(slot, trade_date),
                "published_at": time_match.group(0) if time_match else "",
            }
        )
        seen_ids.add(article_id)

    # Keep the hydration parser as a compatibility path for pages that expose
    # the result in data objects instead of a visible link card.
    for row in _homepage_records(raw):
        if row["id"] in seen_ids:
            continue
        if row["published_at"].startswith(iso_date) and title_query in _compact(row["title"]):
            records.append(row)
            seen_ids.add(row["id"])
    return records


def _article_from_candidate(
    row: Mapping[str, str],
    trade_date: str,
    fetcher: Callable[[str], str],
    source_hashes: dict[str, str],
    attempted_urls: set[str],
) -> dict[str, Any] | None:
    url = f"{_ARTICLE_BASE}{row['id']}"
    if url in attempted_urls:
        return None
    attempted_urls.add(url)
    raw = _fetch_with_retry(fetcher, url)
    source_hashes[url] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    title = _title(raw) or str(row.get("title") or "")
    published_at = _published(raw) or str(row.get("published_at") or "")
    category = _slot(title, trade_date)
    body = _body(raw)
    if not category or not published_at.startswith(datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")):
        return None
    return {
        "title": title,
        "url": url,
        "published_at": published_at,
        "category": category,
        "body_status": "ARTICLE_BODY_READ" if len(body) >= 300 else "ARTICLE_BODY_PARTIAL",
        "body_excerpt_preview": body[:220],
        "body_text": body,
        "source": "韭研公社",
    }


def _readable_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {row["url"]: row for row in articles}
    ordered = sorted(unique.values(), key=lambda row: (row["published_at"], row["url"]))
    return [row for row in ordered if row["body_status"] == "ARTICLE_BODY_READ"]


def collect_public_morning_news(
    trade_date: str,
    *,
    fetcher: Callable[[str], str] = _default_fetcher,
    candidate_registry: Mapping[str, Mapping[str, Any]] | Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    trade_date = validate_date(trade_date)
    iso_date = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
    homepage = _fetch_with_retry(fetcher, _BASE)
    homepage_candidates = [
        row
        for row in _homepage_records(homepage)
        if row["published_at"].startswith(iso_date)
        and any(keyword in row["title"] for keyword in _KEYWORDS)
    ]
    articles: list[dict[str, Any]] = []
    source_hashes = {"homepage": hashlib.sha256(homepage.encode("utf-8")).hexdigest()}
    attempted_urls: set[str] = set()
    for row in homepage_candidates:
        article = _article_from_candidate(row, trade_date, fetcher, source_hashes, attempted_urls)
        if article is not None:
            articles.append(article)

    readable = _readable_articles(articles)
    slot_counts = {slot: sum(row["category"] == slot for row in readable) for slot in _SLOTS}
    missing_slots = [slot for slot, count in slot_counts.items() if not count]
    search_fallback_urls: list[str] = []
    for slot in missing_slots:
        search_url = _search_url(slot, trade_date)
        search_fallback_urls.append(search_url)
        search_raw = _fetch_with_retry(fetcher, search_url)
        source_hashes[search_url] = hashlib.sha256(search_raw.encode("utf-8")).hexdigest()
        for row in _search_records(search_raw, trade_date, slot):
            article = _article_from_candidate(row, trade_date, fetcher, source_hashes, attempted_urls)
            if article is not None:
                articles.append(article)
        readable = _readable_articles(articles)
        slot_counts = {candidate_slot: sum(row["category"] == candidate_slot for row in readable) for candidate_slot in _SLOTS}
        missing_slots = [candidate_slot for candidate_slot, count in slot_counts.items() if not count]

    readable = _readable_articles(articles)
    slot_counts = {slot: sum(row["category"] == slot for row in readable) for slot in _SLOTS}
    missing_slots = [slot for slot, count in slot_counts.items() if not count]
    if len(readable) < 3:
        raise MorningNewsNotReady(
            f"exact-date readable morning articles {len(readable)}/3 for {trade_date}"
        )
    if missing_slots:
        raise MorningNewsNotReady(
            f"missing required morning news slots {','.join(missing_slots)} for {trade_date}"
        )
    status = "MORNING_NEWS_READY"
    stock_mentions = materialize_stock_mentions(readable, candidate_registry)
    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": trade_date,
        "status": status,
        "display_status": f"韭研公社当天正文已读 {len(readable)} 篇",
        "source_role": "JIUYANGONGSHE_MORNING_NEWS",
        "source_mode": "PUBLIC_HTML_SINGLE_OWNER",
        "source_input_sha256": sha256_json(source_hashes),
        "source_hashes": source_hashes,
        "discovery": {
            "homepage_candidate_count": len(homepage_candidates),
            "search_fallback_urls": search_fallback_urls,
        },
        "required_news_contract": {
            "ok": not missing_slots,
            "required_article_count": 3,
            "article_count": len(readable),
            "slot_counts": slot_counts,
            "missing_required_slots": missing_slots,
        },
        "article_count": len(readable),
        "mention_count": len(stock_mentions),
        "articles": readable,
        "stock_mentions": stock_mentions,
        "cannot_confirm": (
            [f"MISSING_REQUIRED_SLOT:{slot}" for slot in missing_slots]
            + ([] if candidate_registry is not None else ["STOCK_MENTIONS_CANDIDATE_REGISTRY_MISSING"])
        ),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        **_SAFETY,
    }


__all__ = [
    "MorningNewsNotReady",
    "collect_public_morning_news",
    "load_shared_candidate_registry",
]
