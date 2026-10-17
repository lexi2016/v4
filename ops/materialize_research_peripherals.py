"""Materialize V3.5-owned public research peripherals.

The producers in this module are deterministic adapters around two public
discovery surfaces: Google News RSS and the AIHot public timeline page.  They
only preserve source evidence and explicit discovery limitations; no model,
legacy artifact, V3 path, or trading decision is involved.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from infrastructure.data_store import _date, _sha256
from infrastructure.http_transport import (
    FetchResult,
    ProxyAwareHTTPTransport,
    TransportError,
)
from infrastructure.research_peripheral_store import ResearchPeripheralStore

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[1]))



GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
GOOGLE_TRANSLATE = "https://translate.googleapis.com/translate_a/single"
MYMEMORY_TRANSLATE = "https://api.mymemory.translated.net/get"
AIHOT_URL = "https://aihot.virxact.com/?mark_id=999_reallog_mark_ad%3A999%7CWeiboADNatural"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) v3.5-research-peripherals/1.0"

from ops._materialize_research_peripherals_parts import schema_values as _v4_definitions
DEFAULT_SUBSCRIPTIONS: tuple[dict[str, str], ...] = _v4_definitions._value_DEFAULT_SUBSCRIPTIONS(globals())

NEGATIVE_PATTERNS = _v4_definitions._value_NEGATIVE_PATTERNS(globals())
GENERIC_TITLES = frozenset({"stocks", "business politics economy and tech news analysis"})
ALLOWED_NICHE_SOURCES = ("data center dynamics", "space news", "spacenews", "the pharma letter")
SOURCE_TIER_PATTERNS: tuple[tuple[str, str], ...] = _v4_definitions._value_SOURCE_TIER_PATTERNS(globals())
AH_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = _v4_definitions._value_AH_KEYWORDS(globals())
THEME_LABELS = _v4_definitions._value_THEME_LABELS(globals())
SOURCE_CN_LABELS = _v4_definitions._value_SOURCE_CN_LABELS(globals())


FetchFn = Callable[..., bytes | str]
TranslateFn = Callable[..., str]
OriginalUrlResolver = Callable[..., str]
_DEFAULT_HTTP_TRANSPORT: ProxyAwareHTTPTransport | None = None


def _default_http_transport() -> ProxyAwareHTTPTransport:
    """Create the process transport after launchd environment injection."""
    global _DEFAULT_HTTP_TRANSPORT
    if _DEFAULT_HTTP_TRANSPORT is None:
        _DEFAULT_HTTP_TRANSPORT = ProxyAwareHTTPTransport()
    return _DEFAULT_HTTP_TRANSPORT
_CJK = re.compile(r"[\u3400-\u9fff]")
_CST = timezone(timedelta(hours=8))
_AI_MAX_ITEMS = 8
_AI_RISKS = ("AI 新闻默认作为技术/产业动态，需结合订单、业绩或A/H映射再升级。",)
_AI_THEME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = _v4_definitions._value__AI_THEME_RULES(globals())
_AI_IMPLICATIONS = _v4_definitions._value__AI_IMPLICATIONS(globals())
_AI_IMPACT_CHAINS = _v4_definitions._value__AI_IMPACT_CHAINS(globals())
_AI_CATALYST_KEYS = ("收购", "上调", "超预期", "首次覆盖", "订单", "扩产", "融资", "开源", "API", "发布", "关税", "Fed", "Iran")
_AI_NOISY_ENTITY_MARKERS = ("高盛", "天风", "华泰", "长江证券", "国盛", "国投证券", "中信", "中金", "申万", "交易台", "市场综述", "市场终评", "周报", "行业", "团队", "联系", "主要受", "主要在", "其中", "支撑了", "详细情况", "先进封装材料")
_REUSABLE_STATUSES = frozenset({"READY", "READY_EMPTY"})


def reuse_existing_payload(payload: Mapping[str, Any] | None) -> bool:
    """Return whether an exact-date artifact is safe to reuse.

    A ``CANNOT_CONFIRM`` artifact records a failed or incomplete attempt and
    must be retried on the next scheduled run.  Only the two terminal success
    states are reusable; this keeps the ``--reuse-existing`` optimization from
    turning a transient source outage into a stale daily result.
    """
    return isinstance(payload, Mapping) and str(payload.get("status") or "") in _REUSABLE_STATUSES


def _coerce_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(microsecond=0)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0)


def isoformat_utc(value: datetime | str | None) -> str:
    return _coerce_datetime(value).isoformat().replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _row_url(row: Mapping[str, Any]) -> str:
    return clean_text(row.get("original_url") or row.get("url") or row.get("source_url"))


def _is_article_url(value: Any) -> bool:
    """Accept a publisher article or Google News article redirect only."""
    from ops._materialize_research_peripherals_parts.feed_admission import __is_article_url_body as _v4_impl
    return _v4_impl(globals(), value)


def _row_admission_reasons(
    row: Mapping[str, Any],
    *,
    fetched_at: datetime | str | None = None,
    lookback_days: int = 2,
) -> list[str]:
    """Return deterministic source admission failures for one finance row."""
    from ops._materialize_research_peripherals_parts.feed_admission import __row_admission_reasons_body as _v4_impl
    return _v4_impl(globals(), row, fetched_at=fetched_at, lookback_days=lookback_days)


def _admit_external_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    fetched_at: datetime | str | None = None,
    lookback_days: int = 2,
) -> tuple[list[dict[str, Any]], list[str]]:
    from ops._materialize_research_peripherals_parts.feed_admission import __admit_external_rows_body as _v4_impl
    return _v4_impl(globals(), rows, fetched_at=fetched_at, lookback_days=lookback_days)


def _short_text(value: Any, limit: int = 180) -> str:
    text = clean_text(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _parse_item_datetime(value: Any) -> datetime | None:
    from ops._materialize_research_peripherals_parts.rss_parse import __parse_item_datetime_body as _v4_impl
    return _v4_impl(globals(), value)


def _format_cst_time(value: Any) -> str:
    parsed = _parse_item_datetime(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S +08:00") if parsed else clean_text(value)


def _keyword_hits(text: str, keyword: str) -> int:
    if keyword.isascii() and keyword.isalpha() and len(keyword) <= 3:
        return len(re.findall(rf"\b{re.escape(keyword.lower())}\b", text.lower()))
    return text.lower().count(keyword.lower())


def _has_keyword(text: str, keyword: str) -> bool:
    return _keyword_hits(text, keyword) > 0


def _clean_markup(value: Any) -> str:
    return clean_text(value)


def _normalize_entity_name(name: str) -> str:
    return re.sub(r"^(?:推荐|看好|关注|强call|强推|子公司)", "", name).strip()


def _is_noise_entity(name: str) -> bool:
    return len(name) < 2 or any(marker in name for marker in _AI_NOISY_ENTITY_MARKERS)


def _detect_named_entities(text: str) -> list[str]:
    from ops._materialize_research_peripherals_parts.cli import __detect_named_entities_body as _v4_impl
    return _v4_impl(globals(), text)


def _detect_stock_focus(text: str, symbols: Sequence[str], entities: Sequence[str]) -> list[str]:
    from ops._materialize_research_peripherals_parts.entity_topics import __detect_stock_focus_body as _v4_impl
    return _v4_impl(globals(), text, symbols, entities)


def _theme_score_map(text: str) -> Counter[str]:
    from ops._materialize_research_peripherals_parts.entity_topics import __theme_score_map_body as _v4_impl
    return _v4_impl(globals(), text)


def _top_theme_candidates(text: str, limit: int = 3) -> list[str]:
    return [theme for theme, _ in _theme_score_map(text).most_common(limit)]


def _infer_theme(text: str) -> str:
    scores = _theme_score_map(text)
    return scores.most_common(1)[0][0] if scores else "其他待复核"


def _infer_implication(text: str) -> str:
    theme = _infer_theme(text)
    return _AI_IMPLICATIONS.get(theme, "作为普通线索保留，需结合原文、公告、量价和第二来源复核。")


def _infer_impact_chain(text: str) -> str:
    theme = _infer_theme(text)
    return _AI_IMPACT_CHAINS.get(theme, "事件事实 -> 产业或市场预期变化 -> 等待第二来源和量价确认。")


def _infer_catalysts(text: str) -> list[str]:
    normalized = _clean_markup(text)
    catalysts = [key for key in _AI_CATALYST_KEYS if key.lower() in normalized.lower()]
    return catalysts[:5] or ["待复核后续公告、订单、业绩或价格信号。"]


def _infer_risks(text: str) -> list[str]:
    normalized = _clean_markup(text)
    risks: list[str] = []
    for pattern in (r"风险提示[:：]?([^。；\n]{2,80})", r"不及预期", r"监管", r"供应", r"价格"):
        match = re.search(pattern, normalized)
        if match:
            risks.append(_short_text(match.group(0), 80))
    return risks[:3] or ["缺少第二来源或量价确认，暂不作为确定性结论。"]


def _priority_score(item: Mapping[str, Any]) -> int:
    from ops._materialize_research_peripherals_parts.entity_topics import __priority_score_body as _v4_impl
    return _v4_impl(globals(), item)


def _absolute_http_url(value: Any, fallback: Any = "") -> str:
    candidate = clean_text(value)
    base = clean_text(fallback)
    joined = urllib.parse.urljoin(base, candidate) if candidate else base
    parsed = urllib.parse.urlparse(joined)
    return joined if parsed.scheme in {"http", "https"} and bool(parsed.netloc) else ""


def _score_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def google_rss_url(query: str, lookback_days: int = 2) -> str:
    if lookback_days < 0:
        raise ValueError("lookback_days must be non-negative")
    params = {
        "q": f"{query} when:{lookback_days}d",
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    return f"{GOOGLE_NEWS_RSS}?{urllib.parse.urlencode(params)}"


def fetch_url(
    url: str,
    timeout: int = 20,
    *,
    transport: ProxyAwareHTTPTransport | None = None,
) -> bytes:
    """Fetch one public URL through the bounded proxy-aware transport."""
    result = (transport or _default_http_transport()).fetch(url, timeout=timeout)
    return result.body


class _GoogleNewsParamsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.params: dict[str, str] = {}

    def handle_starttag(
        self, tag: str, attrs_list: list[tuple[str, str | None]]
    ) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        if (
            tag == "div"
            and attrs.get("data-n-a-sg")
            and attrs.get("data-n-a-ts")
        ):
            self.params = attrs


def decode_google_news_url(
    source_url: str,
    timeout: int = 15,
    *,
    opener=urllib.request.urlopen,
) -> str:
    """Resolve one Google News discovery URL to the publisher article URL.

    Google News serves signed redirect parameters in the article page.  The
    read-only ``Fbv4je`` endpoint converts those parameters to the publisher
    URL; the result is rejected unless it is a non-Google HTTP(S) URL.
    """
    from ops._materialize_research_peripherals_parts.google_redirects import _decode_google_news_url_body as _v4_impl
    return _v4_impl(globals(), source_url, timeout, opener=opener)


def _map_ah_relevance(
    title: str, description: str, subscription_id: str
) -> list[str]:
    from ops._materialize_research_peripherals_parts.cli import __map_ah_relevance_body as _v4_impl
    return _v4_impl(globals(), title, description, subscription_id)


def _v3_local_chinese_title(row: Mapping[str, Any], mappings: list[str]) -> str:
    from ops._materialize_research_peripherals_parts.translation_rows import __v3_local_chinese_title_body as _v4_impl
    return _v4_impl(globals(), row, mappings)


def _v3_local_summary(row: Mapping[str, Any], mappings: list[str]) -> str:
    source = clean_text(row.get("source_name") or row.get("source"))
    source_cn = SOURCE_CN_LABELS.get(source, source or "Google News RSS")
    theme_bucket = clean_text(row.get("theme_bucket"))
    theme = THEME_LABELS.get(theme_bucket, theme_bucket or "外部财经")
    mapping_text = "、".join(mappings) if mappings else "暂未映射到具体A/H标的，保留主题观察"
    published_at = clean_text(row.get("published_at")) or "发布时间未确认"
    return (
        f"来源：{source_cn}；发布时间：{published_at}；主题：{theme}；"
        f"A/H复核方向：{mapping_text}。英文原题保留在证据字段。"
    )


def _localize_external_row(source_row: Mapping[str, Any]) -> dict[str, Any]:
    from ops._materialize_research_peripherals_parts.translation_rows import __localize_external_row_body as _v4_impl
    return _v4_impl(globals(), source_row)


def _normalize_chinese_finance_translation(value: str) -> str:
    from ops._materialize_research_peripherals_parts.translation_validation import __normalize_chinese_finance_translation_body as _v4_impl
    return _v4_impl(globals(), value)


_WESTERN_AMOUNT_RE = re.compile(
    r"(?:(?P<prefix>US\$|HK\$|C\$|A\$|NZ\$|S\$|USD|HKD|EUR|GBP|CNY|RMB|JPY|JP¥|\$|€|£|¥)\s*"
    r"(?P<prefix_number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<prefix_unit>trillion|billion|million|thousand|tn|bn|mn|k|m|b)?"
    r"|(?P<suffix_number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<suffix_unit>trillion|billion|million|thousand|tn|bn|mn|k|m|b)\s*"
    r"(?P<suffix>USD|HKD|EUR|GBP|CNY|RMB|JPY|JP¥|US\$|HK\$|€|£|¥))",
    re.IGNORECASE,
)
_CHINESE_AMOUNT_RE = re.compile(
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>万亿|十亿|亿|千万|百万|十万|万|千)?\s*"
    r"(?P<currency>美元|美金|港元|港币|欧元|英镑|人民币|日元|日圆|元)"
)
_FINANCE_UNIT_MULTIPLIERS = _v4_definitions._value__FINANCE_UNIT_MULTIPLIERS(globals())
_FINANCE_CURRENCY_ALIASES = _v4_definitions._value__FINANCE_CURRENCY_ALIASES(globals())


def _finance_amounts(value: Any) -> list[tuple[str, float]]:
    from ops._materialize_research_peripherals_parts.translation_validation import __finance_amounts_body as _v4_impl
    return _v4_impl(globals(), value)


def _validate_finance_translation(source: Any, translated: Any) -> bool:
    """Check currency and order of magnitude before admitting translated text."""
    from ops._materialize_research_peripherals_parts.translation_validation import __validate_finance_translation_body as _v4_impl
    return _v4_impl(globals(), source, translated)


def _resolve_original_row(
    source_row: Mapping[str, Any],
    *,
    resolver: OriginalUrlResolver,
    timeout: int,
) -> dict[str, Any]:
    from ops._materialize_research_peripherals_parts.translation_rows import __resolve_original_row_body as _v4_impl
    return _v4_impl(globals(), source_row, resolver=resolver, timeout=timeout)


def _resolve_original_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    resolver: OriginalUrlResolver,
    timeout: int,
    max_workers: int = 4,
) -> list[dict[str, Any]]:
    from ops._materialize_research_peripherals_parts.translation_rows import __resolve_original_rows_body as _v4_impl
    return _v4_impl(globals(), rows, resolver=resolver, timeout=timeout, max_workers=max_workers)


def google_translate_zh(value: str, timeout: int = 20) -> str:
    """Translate public-source text to Simplified Chinese via a read-only endpoint."""
    from ops._materialize_research_peripherals_parts.translation_rows import _google_translate_zh_body as _v4_impl
    return _v4_impl(globals(), value, timeout)


def mymemory_translate_zh(
    value: str,
    timeout: int = 20,
    *,
    opener=urllib.request.urlopen,
) -> str:
    """Translate one public headline through MyMemory's read-only endpoint."""
    from ops._materialize_research_peripherals_parts.translation_rows import _mymemory_translate_zh_body as _v4_impl
    return _v4_impl(globals(), value, timeout, opener=opener)


def public_translate_zh(value: str, timeout: int = 20) -> str:
    """Translate a public headline with a bounded provider fallback chain."""
    errors: list[Exception] = []
    for translator in (mymemory_translate_zh, google_translate_zh):
        try:
            return translator(value, timeout)
        except (TimeoutError, TransportError, urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(error)
    raise ValueError("public translation providers unavailable") from errors[-1]


def _call_translator(translator: TranslateFn, value: str, timeout: int) -> str:
    try:
        return str(translator(value, timeout))
    except TypeError as first_error:
        try:
            return str(translator(value))
        except TypeError:
            raise first_error


def _original_url(row: Mapping[str, Any]) -> str:
    base = clean_text(row.get("source_url"))
    candidate = clean_text(row.get("original_url") or row.get("url") or base)
    return urllib.parse.urljoin(base, candidate) if candidate else ""


def _translate_row(
    source_row: Mapping[str, Any],
    *,
    translate_text: TranslateFn,
    timeout: int,
) -> dict[str, Any]:
    from ops._materialize_research_peripherals_parts.translation_rows import __translate_row_body as _v4_impl
    return _v4_impl(globals(), source_row, translate_text=translate_text, timeout=timeout)


def _translate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    translate_text: TranslateFn,
    timeout: int,
    max_workers: int = 6,
) -> list[dict[str, Any]]:
    from ops._materialize_research_peripherals_parts.translation_rows import __translate_rows_body as _v4_impl
    return _v4_impl(globals(), rows, translate_text=translate_text, timeout=timeout, max_workers=max_workers)


def _call_fetcher(fetcher: FetchFn, url: str, timeout: int) -> bytes | str | FetchResult:
    try:
        return fetcher(url, timeout)
    except TypeError as first_error:
        try:
            return fetcher(url)
        except TypeError:
            raise first_error


def _element_text(parent: ET.Element, local_name: str) -> str:
    for child in parent:
        if child.tag.rsplit("}", 1)[-1] == local_name:
            return html.unescape((child.text or "").strip())
    return ""


def _source_of(item: ET.Element) -> tuple[str, str]:
    for child in item:
        if child.tag.rsplit("}", 1)[-1] == "source":
            return clean_text(child.text), str(child.attrib.get("url") or "")
    return "", ""


def parse_rss_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0)


def strip_title_source(title: str, source_name: str) -> str:
    normalized = clean_text(title)
    if source_name and normalized.lower().endswith(f" - {source_name.lower()}"):
        normalized = normalized[: -(len(source_name) + 3)].strip()
    return normalized


def normalize_key(title: str) -> str:
    lowered = clean_text(title).lower()
    lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def source_tier(source_name: str, title: str) -> str:
    haystack = f"{source_name} {title}".lower()
    for needle, tier in SOURCE_TIER_PATTERNS:
        if needle in haystack:
            return tier
    return "T4: Aggregated"


def _tier_score(tier: str) -> int:
    if tier.startswith("T1"):
        return 35
    if tier.startswith("T2"):
        return 25
    if tier.startswith("T3"):
        return 14
    return 6


def _is_negative(title: str, description: str, source_name: str) -> bool:
    haystack = f"{title} {description} {source_name}".lower()
    if any(pattern in haystack for pattern in NEGATIVE_PATTERNS):
        return True
    key = normalize_key(title)
    return key in GENERIC_TITLES or len(key.split()) < 3


def _is_high_signal(row: Mapping[str, Any]) -> bool:
    tier = str(row.get("source_tier") or "")
    source = str(row.get("source_name") or "").lower()
    return tier.startswith(("T1", "T2", "T3")) or any(
        pattern in source for pattern in ALLOWED_NICHE_SOURCES
    )


def _event_class(title: str, description: str) -> str:
    haystack = f"{title} {description}".lower()
    if "ipo" in haystack or "listing" in haystack:
        return "IPO_LISTING"
    if any(word in haystack for word in ("earnings", "profit", "revenue")):
        return "EARNINGS"
    if any(word in haystack for word in ("policy", "tariff", "regulator")):
        return "POLICY_REGULATION"
    if any(word in haystack for word in ("acquisition", "deal", "merger")):
        return "M_A_DEAL"
    return "MARKET_SIGNAL"


def parse_rss_items(
    raw_xml: bytes | str,
    *,
    subscription_id: str,
    theme_bucket: str,
    fetched_at: datetime | str,
    source_url: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    from ops._materialize_research_peripherals_parts.rss_parse import _parse_rss_items_body as _v4_impl
    return _v4_impl(globals(), raw_xml, subscription_id=subscription_id, theme_bucket=theme_bucket, fetched_at=fetched_at, source_url=source_url, limit=limit)


def dedupe_and_rank(
    rows: Sequence[Mapping[str, Any]],
    max_items: int = 36,
    *,
    fetched_at: datetime | str | None = None,
    lookback_days: int = 2,
    rejected_reasons: list[str] | None = None,
) -> list[dict[str, Any]]:
    from ops._materialize_research_peripherals_parts.cli import _dedupe_and_rank_body as _v4_impl
    return _v4_impl(globals(), rows, max_items, fetched_at=fetched_at, lookback_days=lookback_days, rejected_reasons=rejected_reasons)


def overview_from_details(details: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    from ops._materialize_research_peripherals_parts.finance_payload import _overview_from_details_body as _v4_impl
    return _v4_impl(globals(), details)


def _base_payload(
    *,
    trade_date: str,
    source: str,
    status: str,
    source_url: str,
    fetched_at: str,
    raw_item_count: int,
    item_count: int,
    overview: list[dict[str, Any]],
    details: list[dict[str, Any]],
    items: list[dict[str, Any]],
    cannot_confirm: Sequence[str],
    feed_receipts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    from ops._materialize_research_peripherals_parts.finance_payload import __base_payload_body as _v4_impl
    return _v4_impl(globals(), trade_date=trade_date, source=source, status=status, source_url=source_url, fetched_at=fetched_at, raw_item_count=raw_item_count, item_count=item_count, overview=overview, details=details, items=items, cannot_confirm=cannot_confirm, feed_receipts=feed_receipts)


def _feed_receipt(
    feed_id: str,
    url: str,
    receipt: Mapping[str, Any] | None = None,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    """Normalize transport evidence into a stable per-feed contract."""
    from ops._materialize_research_peripherals_parts.feed_fetch import __feed_receipt_body as _v4_impl
    return _v4_impl(globals(), feed_id, url, receipt, error=error)


def _fetch_feed(
    fetcher: FetchFn,
    url: str,
    timeout: int,
    *,
    transport: ProxyAwareHTTPTransport | None = None,
) -> tuple[bytes | str, dict[str, Any]]:
    """Fetch one feed and retain transport metadata for its source receipt."""
    from ops._materialize_research_peripherals_parts.feed_fetch import __fetch_feed_body as _v4_impl
    return _v4_impl(globals(), fetcher, url, timeout, transport=transport)


def build_external_finance_payload(
    trade_date: str,
    *,
    fetched_at: datetime | str | None = None,
    fetch_rss: FetchFn | None = None,
    subscriptions: Sequence[Mapping[str, str]] = DEFAULT_SUBSCRIPTIONS,
    lookback_days: int = 2,
    limit_per_feed: int = 10,
    max_items: int = 36,
    timeout: int = 20,
    translate_text: TranslateFn | None = None,
    resolve_original_url: OriginalUrlResolver | None = None,
    transport: ProxyAwareHTTPTransport | None = None,
) -> dict[str, Any]:
    from ops._materialize_research_peripherals_parts.finance_payload import _build_external_finance_payload_body as _v4_impl
    return _v4_impl(globals(), trade_date, fetched_at=fetched_at, fetch_rss=fetch_rss, subscriptions=subscriptions, lookback_days=lookback_days, limit_per_feed=limit_per_feed, max_items=max_items, timeout=timeout, translate_text=translate_text, resolve_original_url=resolve_original_url, transport=transport)


class AIHotParser(HTMLParser):
    """Small deterministic parser for the public AIHot timeline markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, Any]] = []
        self.pending: dict[str, Any] | None = None
        self.current: dict[str, Any] | None = None
        self.capture_stack: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        from ops._materialize_research_peripherals_parts.ai_feeds import _AIHotParser_handle_starttag_body as _v4_impl
        return _v4_impl(globals(), self, tag, attrs_list)

    def handle_data(self, data: str) -> None:
        from ops._materialize_research_peripherals_parts.ai_feeds import _AIHotParser_handle_data_body as _v4_impl
        return _v4_impl(globals(), self, data)

    def handle_endtag(self, tag: str) -> None:
        from ops._materialize_research_peripherals_parts.ai_feeds import _AIHotParser_handle_endtag_body as _v4_impl
        return _v4_impl(globals(), self, tag)


def parse_aihot_items(
    page_html: str,
    *,
    fetched_at: datetime | str,
    source_url: str,
    limit: int = 30,
) -> list[dict[str, Any]]:
    from ops._materialize_research_peripherals_parts.ai_feeds import _parse_aihot_items_body as _v4_impl
    return _v4_impl(globals(), page_html, fetched_at=fetched_at, source_url=source_url, limit=limit)


def build_ai_items(
    raw_items: Sequence[Mapping[str, Any]],
    *,
    fetched_at: datetime | str | None = None,
    source_url: str = AIHOT_URL,
) -> list[dict[str, Any]]:
    """Build the V3-equivalent unified AI records and retain only score Top8.

    The function deliberately consumes already-materialized public rows.  It
    never imports or reads the legacy V3/assistant tree; all transformations
    are deterministic local equivalents of the former ``build_ai_items``
    helpers.
    """
    from ops._materialize_research_peripherals_parts.ai_feeds import _build_ai_items_body as _v4_impl
    return _v4_impl(globals(), raw_items, fetched_at=fetched_at, source_url=source_url)


def build_ai_news_payload(
    trade_date: str,
    *,
    page_html: str,
    fetched_at: datetime | str | None = None,
    source_url: str = AIHOT_URL,
    limit: int = 30,
    translate_text: TranslateFn | None = None,
    translation_timeout: int = 20,
    feed_receipts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    from ops._materialize_research_peripherals_parts.ai_feeds import _build_ai_news_payload_body as _v4_impl
    return _v4_impl(globals(), trade_date, page_html=page_html, fetched_at=fetched_at, source_url=source_url, limit=limit, translate_text=translate_text, translation_timeout=translation_timeout, feed_receipts=feed_receipts)


def translate_existing_payload(
    payload: Mapping[str, Any],
    *,
    translate_text: TranslateFn = google_translate_zh,
    timeout: int = 20,
    max_workers: int = 6,
) -> dict[str, Any]:
    """Enrich an existing exact-date payload without refetching source rows."""
    from ops._materialize_research_peripherals_parts.translation_rows import _translate_existing_payload_body as _v4_impl
    return _v4_impl(globals(), payload, translate_text=translate_text, timeout=timeout, max_workers=max_workers)


def materialize_existing_translations(
    *,
    data_root: Path,
    trade_date: str,
    source: str,
    translate_text: TranslateFn = google_translate_zh,
    timeout: int = 20,
) -> dict[str, Any]:
    from ops._materialize_research_peripherals_parts.translation_rows import _materialize_existing_translations_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, trade_date=trade_date, source=source, translate_text=translate_text, timeout=timeout)


def _publish_or_hourly_refresh(
    store: ResearchPeripheralStore,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish once, then CAS-refresh the same exact-date source hourly."""
    from ops._materialize_research_peripherals_parts.feed_fetch import __publish_or_hourly_refresh_body as _v4_impl
    return _v4_impl(globals(), store, payload)


def materialize_external_finance(
    *,
    data_root: Path,
    trade_date: str,
    fetch_rss: FetchFn | None = None,
    fetched_at: datetime | str | None = None,
    translate_text: TranslateFn = public_translate_zh,
    resolve_original_url: OriginalUrlResolver = decode_google_news_url,
    **kwargs: Any,
) -> dict[str, Any]:
    from ops._materialize_research_peripherals_parts.materialization import _materialize_external_finance_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, trade_date=trade_date, fetch_rss=fetch_rss, fetched_at=fetched_at, translate_text=translate_text, resolve_original_url=resolve_original_url, **kwargs)


def materialize_ai_news(
    *,
    data_root: Path,
    trade_date: str,
    fetch_html: FetchFn | None = None,
    fetched_at: datetime | str | None = None,
    source_url: str = AIHOT_URL,
    timeout: int = 30,
    limit: int = 30,
    translate_text: TranslateFn = google_translate_zh,
    transport: ProxyAwareHTTPTransport | None = None,
) -> dict[str, Any]:
    from ops._materialize_research_peripherals_parts.materialization import _materialize_ai_news_body as _v4_impl
    return _v4_impl(globals(), data_root=data_root, trade_date=trade_date, fetch_html=fetch_html, fetched_at=fetched_at, source_url=source_url, timeout=timeout, limit=limit, translate_text=translate_text, transport=transport)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    from ops._materialize_research_peripherals_parts.cli import _parse_args_body as _v4_impl
    return _v4_impl(globals(), argv)


def main(argv: Sequence[str] | None = None) -> int:
    from ops._materialize_research_peripherals_parts.cli import _main_body as _v4_impl
    return _v4_impl(globals(), argv)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = _v4_definitions._value___all__(globals())
