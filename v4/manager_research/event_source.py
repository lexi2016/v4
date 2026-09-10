"""Bounded, research-only catalyst discovery for the manager product.

The financial provider owns official PDF facts.  This module owns a separate
event lane: it reads a small set of public directories, joins only to the
already materialized exact-date candidate rows, and keeps source coverage and
uncertainty visible.  It never creates a candidate universe and it never
turns a headline into an order, revenue, or BUY decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import re
import threading
import unicodedata
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urljoin, urlparse, urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .contracts import canonical_json, cutoff_at as contract_cutoff_at, strict_trade_date
from .pdf_parser import PdfParseError, extract_pdf_pages
from .ports import SourceResponse, SourceTransport


EVENT_SCHEMA_VERSION = "v4.manager_research.catalyst_result.v1"
MEDIA_SOURCE_ID = "iccsz.media.directory.v1"
HKEX_EVENT_SOURCE_ID = "v4.hkex.official_event_directory.v1"
ICCSZ_HOME_URL = "http://www.iccsz.com/"
ICCSZ_HOSTS = frozenset({"iccsz.com", "www.iccsz.com"})
MEDIA_MAX_DIRECTORY_DOCUMENTS = 24
MEDIA_MAX_ARTICLE_FETCHES = 16
HKEX_MAX_DOCUMENTS_PER_ISSUER = 3
# Event refresh may read the body of a small, already selected set of official
# announcements.  This is separate from the financial provider's PDF fact
# collection: page text is retained as event evidence and never passed through
# extract_pdf_facts or merged into ``facts``.
HKEX_EVENT_PDF_MAX_DOCUMENTS_PER_ISSUER = 2
HKEX_EVENT_PDF_MAX_BYTES = 8_000_000
HKEX_EVENT_PDF_MAX_PAGES = 40
# The focus lane is deliberately shorter than the bounded collection window.
# Older and unconfirmed material remains attached to each exact candidate, but
# only a recent, interpretable event may receive a manager-facing focus rank.
EVENT_FOCUS_WINDOW_DAYS = 14
_UTC8 = timezone(timedelta(hours=8))
_WS_RE = re.compile(r"\s+")
_DATE_IN_PATH_RE = re.compile(r"/(20\d{6})/")
_PUBLISHED_RE = re.compile(
    r"(?:发布时间|publish(?:ed)?\s*(?:at|time)?)\s*[:：]?\s*"
    r"(20\d{2}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)",
    re.IGNORECASE,
)
_REPORTED_DATE_RE = re.compile(r"(?<!\d)(\d{1,2}月\d{1,2}日)(?!\d)")
_EXCLUDED_HKEX_TOKENS = (
    "monthly return",
    "date of board meeting",
    "proxy",
    "list of directors",
    "interim results",
    "annual results",
    "final results",
    "interim report",
    "annual report",
    "results announcement",
)
_EVENT_TOKENS = (
    "合作", "携手", "协议", "签署", "战略", "订单", "采购", "交付", "量产",
    "发布", "推出", "收购", "出售", "投资", "获奖", "产品", "技术", "制造",
    "cooperation", "partnership", "agreement", "order", "contract", "launch",
    "acquisition", "production", "technology", "manufacturing",
)
_GENERIC_ANNOUNCEMENT_TOKENS = (
    "voluntary announcement", "announcement", "circular", "disclosure",
)
_EVENT_BODY_TOKENS = (
    *_EVENT_TOKENS,
    "approval", "approved", "regulatory", "licence", "license", "permit",
    "customer", "delivery", "deliveries", "commercialise", "commercialize",
    "mass production", "launch", "rollout", "合作", "订单", "交付", "审批",
    "监管", "许可", "客户", "量产", "产品", "签约", "协议",
)
_EVENT_BODY_STRONG_TOKENS = (
    "合作", "cooperation", "partnership", "agreement", "签约", "协议",
    "订单", "order", "contract", "采购", "customer", "客户", "delivery",
    "deliveries", "交付", "审批", "监管", "approval", "approved", "regulatory",
    "licen", "permit", "launch", "推出", "rollout", "commercialise",
    "commercialize", "mass production", "量产", "included in the list",
    "eligible securities", "trading liquidity", "stock connect",
)
_ROUTINE_EVENT_TITLE_TOKENS = (
    "poll results", "extraordinary general meeting", "annual general meeting",
    "notice of meeting", "results of egm", "results of sgm", "meeting minutes",
    # These documents are source evidence, but their retained body text is an
    # administrative notification or timetable.  A title keyword must never
    # be allowed to promote them as an operating catalyst.
    "notification letter", "electronic dissemination", "reply form",
    "interim dividend", "ex-dividend", "latest time to lodge transfer",
)
# These phrases occur in signatures, legal notices, and boilerplate around an
# announcement.  They are source evidence, but are not a business clause even
# when they happen to contain words such as ``order`` or ``agreement``.
_LEGAL_OR_SIGNATURE_TOKENS = (
    "by order of the board",
    "by order of board",
    "order of the board",
    "for and on behalf of the board",
    "registered office",
    "no responsibility",
    "listing rules",
    "this announcement is made pursuant",
    "pursuant to the listing",
    "hereinafter",
    "memorandum and articles",
    "incorporated in",
    "company secretary",
    "director",
    "legal notice",
    "disclaimer",
    "information only",
)
_TRUNCATED_CLAUSE_TOKENS = (
    "by order of",
    "pursuant to",
    "in accordance with",
    "as follows:",
    "as set out",
    "...",
    "…",
)


def _is_routine_hkex_event_title(title: str) -> bool:
    """Return whether an official title is routine corporate administration."""

    lower = _normal_text(title).lower()
    return bool(lower) and any(token in lower for token in _ROUTINE_EVENT_TITLE_TOKENS)


_CLAUSE_DANGLING_END_RE = re.compile(
    r"(?:\b(?:for|of|to|with|under|in|on|and|or|by|from)\s*|[,;:])$",
    re.IGNORECASE,
)
_ISSUER_SUBJECT_RE = re.compile(
    r"\b(?:the\s+(?:company|issuer|group|parties)|we|our\s+(?:company|group))\b|"
    r"(?:本公司|公司|发行人|集团|企业)",
    re.IGNORECASE,
)
_MARKET_ACCESS_SUBJECT_RE = re.compile(
    r"\b(?:h\s+shares|the\s+shares(?:\s+of\s+the\s+company)?|"
    r"shares\s+of\s+the\s+company|the\s+company['’]s\s+shares)\b",
    re.IGNORECASE,
)
_MARKET_ACCESS_ACTION_RE = re.compile(
    r"\b(?:have|has|are|were)\s+(?:been\s+)?included\b",
    re.IGNORECASE,
)
_MARKET_ACCESS_OBJECT_RE = re.compile(
    r"\beligible\s+securities\b.{0,160}\bstock\s+connect\b",
    re.IGNORECASE,
)
_COOPERATION_AGREEMENT_ACTION_RE = re.compile(
    r"\b(?:entered\s+into|signed|executed|reached|formed|established|"
    r"announced|renewed|extended)\b"
    r".{0,180}\b(?:cooperation|partnership|collaboration)\b"
    r"(?:\s+(?:agreement|arrangement|partnership))?\b",
    re.IGNORECASE,
)
_COOPERATION_OPERATION_ACTION_RE = re.compile(
    r"\b(?:will|shall|has|have|is|are)\s+"
    r"(?:deliver(?:ed)?|launch(?:ed)?|roll\s*out|rollout|"
    r"commerciali[sz](?:e|ed)|produce|mass[-\s]produce|develop|"
    r"manufacture|provide|supply|implement)\b"
    r".{0,180}\b(?:under|through|via|pursuant\s+to)\s+"
    r"(?:an?\s+)?(?:cooperation|partnership|collaboration)\b",
    re.IGNORECASE,
)
_COOPERATION_CJK_ACTION_RE = re.compile(
    r"(?:建立|签署|达成|推进|宣布|完成).{0,120}(?:合作|协作)",
    re.IGNORECASE,
)
_ORDER_OR_CUSTOMER_ACTION_RE = re.compile(
    r"\b(?:received|secured|won|obtained|fulfilled|delivered|signed|executed|"
    r"entered\s+into|agreed\s+to|announced|commenced|started)\b"
    r".{0,180}\b(?:orders?|purchase\s+orders?|contracts?|customers?|clients?)\b|"
    r"(?:收到|取得|赢得|获得|签署|执行|履行|宣布|启动).{0,120}(?:订单|合同|客户|采购)",
    re.IGNORECASE,
)
_REGULATORY_ACTION_RE = re.compile(
    r"\b(?:obtained|received|secured|was\s+granted|were\s+granted|"
    r"has\s+obtained|have\s+received|submitted|filed|applied\s+for|"
    r"approved)\b"
    r".{0,180}\b(?:regulatory\s+)?(?:approvals?|licenses?|licences?|"
    r"permits?|clearances?|authori[sz]ations?)\b|"
    r"\b(?:was|were|is|are)\s+approved\b.{0,100}\b(?:by|for)\b|"
    r"(?:获得|取得|获批|提交|申请|通过).{0,120}(?:审批|许可|牌照|批准|监管)",
    re.IGNORECASE,
)
_PRODUCT_OR_TECHNOLOGY_ACTION_RE = re.compile(
    r"\b(?:launched|released|introduced|developed|completed|delivered|"
    r"manufactured|produced|commerciali[sz]ed|started|commenced|rolled\s+out)\b"
    r".{0,180}\b(?:products?|technology|technologies|platforms?|solutions?|"
    r"devices?|systems?|services?|production|mass\s+production)\b|"
    r"(?:推出|发布|开发|完成|交付|制造|生产|量产|启动).{0,120}(?:产品|技术|平台|方案|系统|服务|生产)",
    re.IGNORECASE,
)


class EventSourceError(RuntimeError):
    """A bounded event source failed without invalidating financial facts."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(body: bytes) -> str:
    return sha256(body).hexdigest()


def _safe_media_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname in ICCSZ_HOSTS


def _normal_text(value: Any) -> str:
    return _WS_RE.sub(" ", unescape(str(value or "").replace("\xa0", " "))).strip()


def _normal_entity(value: Any) -> str:
    text = _normal_text(value).lower()
    text = re.sub(r"(?:股份有限公司|有限公司|有限责任公司)$", "", text)
    text = re.sub(r"[-_\s（）()]+(?:p|w|r|hk)?$", "", text, flags=re.IGNORECASE)
    return re.sub(r"[^\w\u3400-\u9fff]", "", text)


def _source_label(source_id: str) -> str:
    if source_id == MEDIA_SOURCE_ID:
        return "讯石行业媒体"
    if source_id == HKEX_EVENT_SOURCE_ID:
        return "港交所同发行人公告目录"
    return source_id


def _as_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _event_key(event: Mapping[str, Any]) -> str:
    """Return a stable raw-material key, preferring the provider event id.

    ``event_id`` is the source identity when it is present.  Older rows and
    directory-only records may not have one, so a source URL remains the
    fallback.  The explicit prefixes keep an id and a URL from accidentally
    colliding when a bounded source supplies both.
    """

    event_id = str(event.get("event_id") or "").strip()
    if event_id:
        return f"id:{event_id}"
    source_url = str(event.get("source_url") or event.get("url") or "").strip()
    return f"url:{source_url}" if source_url else ""


def _event_identity_matches(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Match the same source material across provider refresh projections."""

    left_id = str(left.get("event_id") or "").strip()
    right_id = str(right.get("event_id") or "").strip()
    if left_id and right_id and left_id == right_id:
        return True
    left_url = str(left.get("source_url") or left.get("url") or "").strip()
    right_url = str(right.get("source_url") or right.get("url") or "").strip()
    return bool(left_url and right_url and left_url == right_url)


def _record_identity(record: Mapping[str, Any]) -> str:
    """Build a conservative key for source receipts and excluded documents."""

    for field in ("event_id", "source_url", "url", "source_sha256", "source_id", "title"):
        value = str(record.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    return canonical_json(dict(record))


def _previous_first_seen(previous: Mapping[str, Any] | None, event: Mapping[str, Any]) -> str | None:
    if not isinstance(previous, Mapping):
        return None
    key = _event_key(event)
    for item in previous.get("events", []):
        if isinstance(item, Mapping) and _event_key(item) == key:
            value = item.get("first_seen_at")
            return value if isinstance(value, str) and value.strip() else None
    return None


def _candidate_matches(row: Mapping[str, Any], observations: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Join a directory headline to exact candidate names/codes.

    Matching is deliberately conservative.  If two exact candidate names
    match a headline, the event remains unjoined rather than leaking one
    issuer's catalyst to another row.
    """

    title = _normal_entity(row.get("title") or row.get("headline") or "")
    url = _normal_entity(row.get("url") or "")
    matches: list[Mapping[str, Any]] = []
    for observation in observations:
        code = str(observation.get("code") or "")
        code_number = code.split(".", 1)[-1]
        name = _normal_entity(observation.get("name") or observation.get("stock_name") or "")
        code_match = bool(code_number and code_number in url + title) or bool(
            code_number.lstrip("0") and code_number.lstrip("0") in title
        )
        name_match = bool(name and len(name) >= 2 and name in title)
        if code_match or name_match:
            matches.append(observation)
    return matches


class _DirectoryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self._anchor: dict[str, str] | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        href = values.get("href", "")
        if "/site/cn/news/" not in href.lower() or not re.search(r"\.html?$", href, re.IGNORECASE):
            return
        self._anchor = {"href": href, "title": values.get("title", "")}
        self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._anchor is None:
            return
        row = dict(self._anchor)
        row["text"] = _normal_text("".join(self._buffer))
        row["title"] = _normal_text(row.get("title") or row["text"])
        self.rows.append(row)
        self._anchor = None
        self._buffer = []


def parse_iccsz_directory(body: bytes, *, base_url: str = ICCSZ_HOME_URL) -> list[dict[str, Any]]:
    parser = _DirectoryParser()
    try:
        parser.feed(body.decode("utf-8-sig", errors="replace"))
    except Exception as exc:  # pragma: no cover - HTMLParser is permissive, retained as a boundary
        raise EventSourceError(f"ICCSZ directory parse failed: {type(exc).__name__}") from exc
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in parser.rows:
        url = urljoin(base_url, item["href"])
        if not _safe_media_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        path_date = _DATE_IN_PATH_RE.search(url)
        rows.append(
            {
                "url": url,
                "title": item["title"],
                "directory_date": path_date.group(1) if path_date else None,
            }
        )
    return rows


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.buffers: dict[str, list[str]] = {"title": [], "h1": [], "info": [], "intro": [], "body": []}
        self._active: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        cls = values.get("class", "").lower().split()
        target: str | None = None
        if tag.lower() == "title":
            target = "title"
        elif tag.lower() == "h1":
            target = "h1"
        elif "ableft" in cls:
            target = "info"
        elif "article_intro" in cls:
            target = "intro"
        elif "articlecontent" in cls:
            target = "body"
        if target is not None:
            self._active.append((tag.lower(), target))

    def handle_data(self, data: str) -> None:
        for _tag, target in self._active:
            self.buffers[target].append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._active) - 1, -1, -1):
            if self._active[index][0] == tag:
                self._active.pop(index)
                break


def _first_sentence(text: str, *, tokens: Sequence[str]) -> str | None:
    parts = [part.strip(" \t\r\n　") for part in re.split(r"(?<=[。！？!?])|\n+", text) if part.strip()]
    scored = [
        (sum(1 for token in tokens if token.lower() in part.lower()), -index, part)
        for index, part in enumerate(parts)
        if any(token.lower() in part.lower() for token in tokens)
    ]
    if scored:
        # Prefer the sentence with the richest operating-language evidence so
        # a generic cooperation summary does not mask a later ``推进/量产``
        # clause.  The original order breaks ties deterministically.
        return max(scored, key=lambda item: (item[0], item[1]))[2][:180]
    return parts[0][:180] if parts else None


def _counterparty(text: str) -> str | None:
    patterns = (
        r"(?:与|携手)([^，。；;]{2,100}?)(?:建立|达成|深化|签署|展开|共同|推进|合作)",
        r"(?:合作方|伙伴)[：:]?\s*([^，。；;]{2,60})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = _normal_text(match.group(1)).strip(" ：:，,、")
        value = re.sub(r"^(?:全球领先|领先|全球知名|知名)\s*", "", value)
        if value:
            return value[:100]
    # Preserve an English name only when it is explicitly parenthesized next
    # to a Chinese name; this avoids inventing a counterparty from prose.
    match = re.search(r"([\u3400-\u9fff]{2,20})[（(]([A-Za-z][A-Za-z .&'-]{2,50})", text)
    if match:
        return f"{match.group(1)}（{match.group(2).strip()}）"
    return None


def parse_iccsz_article(body: bytes, *, url: str, retrieved_at: str) -> dict[str, Any]:
    parser = _ArticleParser()
    try:
        parser.feed(body.decode("utf-8-sig", errors="replace"))
    except Exception as exc:
        raise EventSourceError(f"ICCSZ article parse failed: {type(exc).__name__}") from exc
    title = _normal_text("".join(parser.buffers["h1"]) or "".join(parser.buffers["title"]))
    info = _normal_text("".join(parser.buffers["info"]))
    intro = _normal_text("".join(parser.buffers["intro"]))
    body_text = _normal_text("".join(parser.buffers["body"]))
    text = " ".join(item for item in (intro, body_text) if item)
    if not title or not text:
        raise EventSourceError("ICCSZ article has no title or parsed正文")
    published_match = _PUBLISHED_RE.search(info or text)
    published_at: str | None = None
    if published_match:
        raw = published_match.group(1)
        formats = ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M")
        for fmt in formats:
            try:
                published_at = datetime.strptime(raw, fmt).replace(tzinfo=_UTC8).isoformat(timespec="seconds")
                break
            except ValueError:
                continue
    reported = _REPORTED_DATE_RE.search(text)
    event_kind = "COOPERATION" if any(token in text for token in ("合作", "携手", "协议", "partnership", "cooperation")) else "MEDIA_UPDATE"
    # Prefer the sentence that describes a possible operating change.  A
    # headline or opening cooperation sentence alone is not enough to
    # explain the business bridge; for the ICCSZ sample this keeps the
    # ``推进...量产`` wording attributed to the report without promoting it
    # to a completed production or revenue fact.
    business = _first_sentence(text, tokens=("制造", "量产", "产品", "客户", "市场", "工程", "technology", "production"))
    return {
        "title": title,
        "url": url,
        "publisher_timestamp": published_at,
        "publisher_timestamp_text": published_match.group(1) if published_match else None,
        "publisher_timezone": "Asia/Shanghai",
        "publisher_timezone_assumed": True,
        "reported_event_date_text": reported.group(1) if reported else None,
        "event_type": event_kind,
        # The partner is often present in the headline while the body uses
        # ``双方``.  Include the parsed title for entity attribution, while
        # retaining the conservative counterparty patterns.
        "counterparty": _counterparty(f"{title} {text}"),
        "business_excerpt": business,
        "source_excerpt": (intro or business or text)[:260],
        "parsed_body": True,
        "retrieved_at": retrieved_at,
    }


def _default_media_transport() -> SourceTransport:
    opener = build_opener(HTTPCookieProcessor())

    def request(
        url: str,
        *,
        timeout: float,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> SourceResponse:
        if not _safe_media_url(url):
            raise EventSourceError("refused non-ICCSZ source URL")
        request_headers = {
            "User-Agent": "Mozilla/5.0 (research-only; V4 manager catalyst lane)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        }
        if headers:
            request_headers.update(headers)
        request_obj = Request(url, data=body, headers=request_headers, method=method.upper())
        try:
            with opener.open(request_obj, timeout=timeout) as response:
                response_body = response.read()
                final_url = response.geturl()
                if not _safe_media_url(final_url):
                    raise EventSourceError("refused non-ICCSZ redirect target")
                return SourceResponse(
                    url=url,
                    final_url=final_url,
                    status_code=int(response.status),
                    body=response_body,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    retrieved_at=_now(),
                )
        except EventSourceError:
            raise
        except Exception as exc:
            raise EventSourceError(f"ICCSZ request failed: {type(exc).__name__}: {exc}") from exc

    return request


class BoundedMediaTransport:
    """Allowlisted media transport with an explicit request ceiling."""

    def __init__(
        self,
        transport: SourceTransport | None = None,
        *,
        timeout: float = 12.0,
        max_requests: int = MEDIA_MAX_ARTICLE_FETCHES + 1,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        self._transport = transport or _default_media_transport()
        self.timeout = float(timeout)
        self.max_requests = int(max_requests)
        self.request_count = 0
        self._lock = threading.Lock()

    def request(self, url: str) -> SourceResponse:
        if not _safe_media_url(url):
            raise EventSourceError("refused non-ICCSZ source URL")
        with self._lock:
            if self.request_count >= self.max_requests:
                raise EventSourceError("ICCSZ request bound exceeded")
            self.request_count += 1
        try:
            response = self._transport(url, timeout=self.timeout, method="GET")
        except TypeError:
            response = self._transport(url, timeout=self.timeout)
        final_url = response.final_url or response.url
        if not _safe_media_url(final_url):
            raise EventSourceError("refused non-ICCSZ redirect target")
        return response


def _event_from_article(
    observation: Mapping[str, Any],
    article: Mapping[str, Any],
    *,
    directory_sha256: str,
    directory_retrieved_at: str,
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source_url = str(article["url"])
    source_sha256 = str(article.get("source_sha256") or "")
    event_id = sha256(canonical_json({"url": source_url, "sha256": source_sha256})).hexdigest()[:24]
    first_seen = _previous_first_seen(previous, {"source_url": source_url}) or str(article["retrieved_at"])
    publisher = article.get("publisher_timestamp")
    event = {
        "event_id": event_id,
        "event_type": article.get("event_type") or "MEDIA_UPDATE",
        "source_kind": "MEDIA",
        "source_id": MEDIA_SOURCE_ID,
        "evidence_level": "MEDIA",
        "official_confirmation_status": "PENDING",
        "code": observation.get("code"),
        "name": observation.get("name"),
        "counterparty": article.get("counterparty"),
        "catalyst": article.get("title"),
        "why_might_affect_business": article.get("business_excerpt"),
        "source_excerpt": article.get("source_excerpt"),
        "realization_conditions": [
            "需由公司、合作方或监管披露确认合作范围、约束和可执行安排。",
            "需观察后续可核验订单、量产、客户交付或收入证据；媒体报道本身不等于订单或已确认收入。",
        ],
        "financial_counterevidence": [],
        "market_confirmation_gap": [
            "MEDIA_ONLY_OFFICIAL_CONFIRMATION_PENDING",
            "ORDER_OR_REVENUE_UNCONFIRMED",
        ],
        "reported_event_date_text": article.get("reported_event_date_text"),
        "publisher_timestamp": publisher,
        "publisher_timestamp_text": article.get("publisher_timestamp_text"),
        "publisher_timezone": article.get("publisher_timezone"),
        "publisher_timezone_assumed": article.get("publisher_timezone_assumed") is True,
        "first_seen_at": first_seen,
        "first_public_announcement_time": "CANNOT_CONFIRM",
        "source_url": source_url,
        "source_title": article.get("title"),
        "source_sha256": source_sha256,
        "directory_url": ICCSZ_HOME_URL,
        "directory_sha256": directory_sha256,
        "directory_retrieved_at": directory_retrieved_at,
        "retrieved_at": article.get("retrieved_at"),
        "body_parsed": True,
        "as_of_bucket": None,
    }
    return event


def _event_bucket(event: Mapping[str, Any], target: str, cutoff: str, now: datetime) -> str | None:
    published = _as_datetime(event.get("publisher_timestamp"))
    if published is None:
        return None
    target_date = datetime.strptime(target, "%Y%m%d").date()
    published_local = published.astimezone(_UTC8)
    if published_local.date() > target_date or published > now:
        return None
    cutoff_dt = datetime.fromisoformat(cutoff)
    return "historical" if published <= cutoff_dt else "current"


def _event_is_temporally_confirmed(event: Mapping[str, Any]) -> bool:
    """Whether an event has enough publication timing to enter a date bucket."""

    return event.get("as_of_bucket") in {"historical", "current"}


def _source_batch_failed(batch: Mapping[str, Any]) -> bool:
    """Return true only for a source whose bounded collection failed outright."""

    status = str(batch.get("status") or "").upper()
    if status == "CANNOT_CONFIRM":
        return True
    coverage = batch.get("coverage")
    if isinstance(coverage, Mapping) and str(coverage.get("status") or "").upper() == "CANNOT_CONFIRM":
        return True
    counts = batch.get("source_counts")
    if isinstance(counts, Mapping) and str(counts.get("status") or "").upper() == "CANNOT_CONFIRM":
        return True
    return False


def _empty_source_row(code: str, *, source_id: str, status: str, reason: str, coverage: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "events": [],
        "source_receipts": [],
        "coverage": dict(coverage),
        "source_id": source_id,
    }


def _source_row_with_events(
    code: str,
    *,
    source_id: str,
    events: list[dict[str, Any]],
    receipt: Mapping[str, Any] | None,
    coverage: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "status": "READY" if events else "DIRECTORY_ONLY",
        "reason": "EVENT_BODY_PARSED" if events else "DIRECTORY_ONLY_BODY_UNPARSED",
        "events": events,
        "source_receipts": [dict(receipt)] if isinstance(receipt, Mapping) else [],
        "coverage": dict(coverage),
        "source_id": source_id,
    }


def discover_iccsz_events(
    *,
    target_trade_date: str,
    cutoff_at: str,
    observations: Sequence[Mapping[str, Any]],
    transport: BoundedMediaTransport | None = None,
    previous_rows: Mapping[str, Mapping[str, Any]] | None = None,
    current_event_as_of: str | None = None,
) -> dict[str, Any]:
    """Discover ICCSZ articles once, then join only exact candidate rows."""

    target = strict_trade_date(target_trade_date)
    if cutoff_at != contract_cutoff_at(target):
        raise EventSourceError("event source cutoff_at does not match target trade date")
    media_transport = transport or BoundedMediaTransport()
    now = _as_datetime(current_event_as_of) or datetime.now(timezone.utc)
    rows: dict[str, dict[str, Any]] = {}
    for observation in observations:
        code = str(observation.get("code") or "")
        rows[code] = _empty_source_row(
            code,
            source_id=MEDIA_SOURCE_ID,
            status="NO_MATCH",
            reason="NO_MATCH_IS_NOT_COMPLETE",
            coverage={"source_id": MEDIA_SOURCE_ID, "status": "NOT_RUN"},
        )
    try:
        directory = media_transport.request(ICCSZ_HOME_URL)
        if directory.status_code < 200 or directory.status_code >= 300:
            raise EventSourceError(f"ICCSZ directory HTTP {directory.status_code}")
        directory_sha = _digest(directory.body)
        directory_rows = parse_iccsz_directory(directory.body, base_url=directory.final_url or ICCSZ_HOME_URL)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        for code in rows:
            rows[code] = _empty_source_row(
                code,
                source_id=MEDIA_SOURCE_ID,
                status="CANNOT_CONFIRM",
                reason="MEDIA_DIRECTORY_FAILED",
                coverage={"source_id": MEDIA_SOURCE_ID, "status": "CANNOT_CONFIRM", "error": message, "directory_requests": 1},
            )
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "source_id": MEDIA_SOURCE_ID,
            "rows": rows,
            "source_counts": {"source_id": MEDIA_SOURCE_ID, "requested_candidates": len(observations), "status": "CANNOT_CONFIRM", "directory_requests": media_transport.request_count, "error": message},
            "coverage": {"status": "CANNOT_CONFIRM", "completeness": "BOUNDED_SOURCE_FAILED", "no_match_is_not_complete": True},
            "current_event_as_of": now.isoformat(timespec="seconds"),
        }

    bounded_rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in directory_rows:
        item_date = item.get("directory_date")
        if isinstance(item_date, str) and item_date > target:
            continue
        url = str(item.get("url") or "")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        bounded_rows.append(item)
        if len(bounded_rows) >= MEDIA_MAX_DIRECTORY_DOCUMENTS:
            break

    matching: dict[str, list[dict[str, Any]]] = {str(obs.get("code")): [] for obs in observations}
    article_cache: dict[str, tuple[dict[str, Any] | None, str | None]] = {}
    matched_titles = 0
    parsed_count = 0
    directory_only_count = 0
    failed_count = 0
    for directory_row in bounded_rows:
        matches = _candidate_matches(directory_row, observations)
        if len(matches) != 1:
            continue
        matched_titles += 1
        observation = matches[0]
        code = str(observation.get("code"))
        url = str(directory_row["url"])
        if url not in article_cache:
            try:
                article_response = media_transport.request(url)
                if article_response.status_code < 200 or article_response.status_code >= 300:
                    raise EventSourceError(f"article HTTP {article_response.status_code}")
                article = parse_iccsz_article(article_response.body, url=url, retrieved_at=article_response.retrieved_at)
                article["source_sha256"] = _digest(article_response.body)
                article_cache[url] = (article, None)
                parsed_count += 1
            except Exception as exc:
                article_cache[url] = (None, f"{type(exc).__name__}: {exc}")
                failed_count += 1
        article, error = article_cache[url]
        if article is None:
            directory_only_count += 1
            receipt = {
                "source_kind": "MEDIA",
                "source_id": MEDIA_SOURCE_ID,
                "url": url,
                "title": directory_row.get("title"),
                "directory_url": ICCSZ_HOME_URL,
                "directory_sha256": directory_sha,
                "directory_retrieved_at": directory.retrieved_at,
                "body_parsed": False,
                "status": "DIRECTORY_ONLY",
                "error": error,
            }
            event = {
                "event_id": sha256(canonical_json({"url": url, "title": directory_row.get("title")})).hexdigest()[:24],
                "event_type": "MEDIA_UPDATE",
                "source_kind": "MEDIA",
                "source_id": MEDIA_SOURCE_ID,
                "evidence_level": "MEDIA_DIRECTORY_ONLY",
                "official_confirmation_status": "PENDING",
                "code": code,
                "name": observation.get("name"),
                "counterparty": None,
                "catalyst": directory_row.get("title"),
                "why_might_affect_business": "目录标题显示近期行业信息；正文尚未解析，业务影响待核验。",
                "source_excerpt": None,
                "realization_conditions": ["补齐正文并由公司、合作方或监管披露确认后再核验。"],
                "financial_counterevidence": [],
                "market_confirmation_gap": ["DIRECTORY_ONLY_BODY_NOT_PARSED", "OFFICIAL_CONFIRMATION_PENDING"],
                "reported_event_date_text": None,
                "publisher_timestamp": None,
                "publisher_timestamp_text": None,
                "publisher_timezone": None,
                "publisher_timezone_assumed": False,
                "first_seen_at": _previous_first_seen((previous_rows or {}).get(code), {"source_url": url}) or directory.retrieved_at,
                "first_public_announcement_time": "CANNOT_CONFIRM",
                "source_url": url,
                "source_title": directory_row.get("title"),
                "source_sha256": None,
                "directory_url": ICCSZ_HOME_URL,
                "directory_sha256": directory_sha,
                "directory_retrieved_at": directory.retrieved_at,
                "retrieved_at": directory.retrieved_at,
                "body_parsed": False,
                "as_of_bucket": None,
            }
            matching[code].append({"event": event, "receipt": receipt})
            continue
        event = _event_from_article(
            observation,
            article,
            directory_sha256=directory_sha,
            directory_retrieved_at=directory.retrieved_at,
            previous=(previous_rows or {}).get(code),
        )
        bucket = _event_bucket(event, target, cutoff_at, now)
        if bucket is None:
            # The body and entity join are still useful evidence, but a
            # missing publisher time cannot be assigned to either the
            # historical 09:40 cutoff or the current supplement.  Keep that
            # evidence visible as an explicit candidate-level gap instead of
            # turning it into a false NO_MATCH.
            if article.get("publisher_timestamp") is None:
                event["publisher_timestamp"] = "CANNOT_CONFIRM"
                event["evidence_level"] = "MEDIA_DIRECTORY_ONLY"
                event["market_confirmation_gap"] = list(dict.fromkeys([
                    *[str(item) for item in event.get("market_confirmation_gap", []) if item],
                    "PUBLISHER_TIMESTAMP_UNAVAILABLE",
                ]))
                event["event_status"] = "CANNOT_CONFIRM"
                event["as_of_bucket"] = None
                receipt = {
                    "source_kind": "MEDIA",
                    "source_id": MEDIA_SOURCE_ID,
                    "url": url,
                    "locator": url,
                    "title": article.get("title"),
                    "source_sha256": article.get("source_sha256"),
                    "body_sha256": article.get("source_sha256"),
                    "directory_url": ICCSZ_HOME_URL,
                    "directory_sha256": directory_sha,
                    "directory_retrieved_at": directory.retrieved_at,
                    "publisher_timestamp": "CANNOT_CONFIRM",
                    "publisher_timestamp_text": article.get("publisher_timestamp_text"),
                    "timestamp_status": "CANNOT_CONFIRM",
                    "body_parsed": True,
                    "status": "CANNOT_CONFIRM",
                    "reason": "PUBLISHER_TIMESTAMP_UNAVAILABLE",
                }
                matching[code].append({"event": event, "receipt": receipt})
            continue
        event["as_of_bucket"] = bucket
        receipt = {
            "source_kind": "MEDIA",
            "source_id": MEDIA_SOURCE_ID,
            "url": url,
            "locator": url,
            "title": article.get("title"),
            "source_sha256": article.get("source_sha256"),
            "body_sha256": article.get("source_sha256"),
            "directory_url": ICCSZ_HOME_URL,
            "directory_sha256": directory_sha,
            "directory_retrieved_at": directory.retrieved_at,
            "publisher_timestamp": article.get("publisher_timestamp"),
            "body_parsed": True,
            "status": "READY",
        }
        matching[code].append({"event": event, "receipt": receipt})

    source_coverage = {
        "source_id": MEDIA_SOURCE_ID,
        "source_label": _source_label(MEDIA_SOURCE_ID),
        "status": "READY" if parsed_count else "PARTIAL_WITH_ROWS",
        "requested_candidates": len(observations),
        "directory_requests": 1,
        "directory_documents_seen": len(bounded_rows),
        "directory_documents_bound": matched_titles,
        "article_requests": max(0, media_transport.request_count - 1),
        "article_parsed": parsed_count,
        "directory_only": directory_only_count,
        "timestamp_unconfirmed": sum(
            1
            for entries in matching.values()
            for entry in entries
            if isinstance(entry.get("event"), Mapping)
            and not _event_is_temporally_confirmed(entry["event"])
            and entry["event"].get("body_parsed") is True
        ),
        "failed": failed_count,
        "completeness": "BOUNDED_HOME_DIRECTORY_ONLY",
        "no_match_is_not_complete": True,
        "directory_sha256": directory_sha,
        "directory_retrieved_at": directory.retrieved_at,
    }
    for code in rows:
        entries = matching.get(code, [])
        events = [entry["event"] for entry in entries]
        receipts = [entry["receipt"] for entry in entries]
        # Deduplicate by source URL while retaining the newest parser result.
        unique: dict[str, dict[str, Any]] = {}
        for event in events:
            unique[_event_key(event)] = event
        events = list(unique.values())
        if events:
            timestamp_unconfirmed = any(
                event.get("event_status") == "CANNOT_CONFIRM"
                or (event.get("body_parsed") is True and not _event_is_temporally_confirmed(event))
                for event in events
            )
            has_temporally_confirmed_event = any(_event_is_temporally_confirmed(event) for event in events)
            if timestamp_unconfirmed and not has_temporally_confirmed_event:
                row_status = "CANNOT_CONFIRM"
                row_reason = "PUBLISHER_TIMESTAMP_UNAVAILABLE"
            else:
                row_status = "READY" if any(event.get("body_parsed") and _event_is_temporally_confirmed(event) for event in events) else "DIRECTORY_ONLY"
                row_reason = "EVENT_BODY_PARSED" if row_status == "READY" else "DIRECTORY_ONLY_BODY_NOT_PARSED"
            rows[code] = {
                "status": row_status,
                "reason": row_reason,
                "events": events[:3],
                "source_receipts": receipts[:3],
                "coverage": dict(source_coverage),
                "source_id": MEDIA_SOURCE_ID,
            }
        else:
            rows[code] = _empty_source_row(
                code,
                source_id=MEDIA_SOURCE_ID,
                status="NO_MATCH",
                reason="NO_MATCH_IS_NOT_COMPLETE",
                coverage={**source_coverage, "candidate_status": "NO_MATCH"},
            )
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "source_id": MEDIA_SOURCE_ID,
        "rows": rows,
        "source_counts": source_coverage,
        "coverage": {
            "status": source_coverage["status"],
            "completeness": source_coverage["completeness"],
            "no_match_is_not_complete": True,
            "current_event_as_of": now.isoformat(timespec="seconds"),
        },
        "current_event_as_of": now.isoformat(timespec="seconds"),
    }


def _is_hkex_event_row(row: Mapping[str, Any]) -> bool:
    text = f"{row.get('headline', '')} {row.get('document_title', '')}".lower()
    if any(token in text for token in _EXCLUDED_HKEX_TOKENS):
        return False
    # A neutral ``Voluntary Announcement`` title is only a bounded candidate;
    # it is not evidence of a catalyst.  The selected PDF body below must
    # contain a substantive event sentence before the row is emitted as an
    # event.  This keeps announcements whose title omits the real subject in
    # scope without promoting the title itself.
    return any(token in text for token in (*_EVENT_TOKENS, *_GENERIC_ANNOUNCEMENT_TOKENS))


def _is_abbreviation_period(text: str, index: int) -> bool:
    """Return whether a period belongs to a compact English abbreviation."""

    prefix = text[: index + 1]
    # U.S., U.K., e.g. and similar dotted abbreviations should not become
    # artificial sentence boundaries.  The final period is the only one that
    # can otherwise look like a boundary because internal periods are followed
    # immediately by another letter.
    return bool(re.search(r"(?:[A-Za-z]\.){2,}$", prefix))


def _is_unicode_closing_delimiter(value: str) -> bool:
    """Return whether one character closes a quote or bracket.

    Unicode has dedicated close-punctuation categories for the CJK brackets
    and typographic final quotes that commonly follow an English full stop.
    ASCII quotes are category ``Po`` rather than ``Pe``/``Pf``, so they remain
    an explicit part of the small compatibility set.
    """

    return bool(value) and (
        value in "\"')]}"
        or unicodedata.category(value) in {"Pe", "Pf"}
    )


def _is_sentence_boundary_follower(value: str) -> bool:
    """Return whether a character may close a sentence after a full stop."""

    return bool(value) and (
        _is_unicode_closing_delimiter(value)
        or value in ":;!?"
    )


def _is_sentence_period(text: str, index: int) -> bool:
    """Return whether a full stop is a sentence boundary.

    Decimal numbers, version strings and dotted dates are ordinary object
    text. A sentence period is retained only after those internal forms and
    compact abbreviations have been excluded.
    """

    previous = text[index - 1] if index else ""
    following = text[index + 1] if index + 1 < len(text) else ""
    if previous.isdigit() and following.isdigit():
        return False
    if _is_abbreviation_period(text, index):
        return False
    if following and not following.isspace() and not _is_sentence_boundary_follower(following):
        return False
    return True


def _split_event_sentences(text: str) -> list[str]:
    """Split event text without treating numeric or abbreviation dots as boundaries."""

    normalized = _normal_text(text)
    if not normalized:
        return []
    sentences: list[str] = []
    start = 0
    index = 0
    while index < len(normalized):
        mark = normalized[index]
        if mark in "。！？!?" or (mark == "." and _is_sentence_period(normalized, index)):
            end = index + 1
            while end < len(normalized) and (
                normalized[end] in "。！？!?"
                or _is_unicode_closing_delimiter(normalized[end])
            ):
                end += 1
            sentence = normalized[start:end].strip()
            if sentence:
                sentences.append(sentence)
            start = end
            index = end
            continue
        index += 1
    tail = normalized[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _event_body_excerpt(text: str, *, title: str = "") -> tuple[str | None, int]:
    """Return one short event sentence after the shared action gate.

    Discovery remains score-based, but a candidate must first pass the same
    kind-specific classifier used by the final parse. An unconfirmed candidate
    is still retained when no valid sentence exists, so source material is not
    silently discarded.
    """

    candidates: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(_split_event_sentences(text)):
        if not sentence or len(sentence) < 8:
            continue
        lower = sentence.lower()
        hits = sum(1 for token in _EVENT_BODY_STRONG_TOKENS if token.lower() in lower)
        if not hits:
            continue
        # Boilerplate about listing, the exchange, or disclaimer status can
        # mention a generic announcement token without describing business.
        if any(token in lower for token in ("stock exchange", "listing rules", "no responsibility", "registered office")) and hits < 2:
            continue
        candidates.append((hits, -index, sentence))
    if not candidates:
        return None, 0

    valid_candidates: list[tuple[int, int, str]] = []
    for score, negative_index, sentence in candidates:
        event_kind, _reason = _classify_hkex_business_clause(sentence, score, title=title)
        if event_kind is not None:
            valid_candidates.append((score, negative_index, sentence))
    selected = max(valid_candidates or candidates)
    return selected[2][:480], selected[0]


def _has_complete_market_access_clause(lower: str) -> bool:
    """Require a subject, inclusion predicate, and complete Stock Connect object."""

    subject = _MARKET_ACCESS_SUBJECT_RE.search(lower)
    action = _MARKET_ACCESS_ACTION_RE.search(lower)
    object_match = _MARKET_ACCESS_OBJECT_RE.search(lower)
    if not subject or not action or not object_match:
        return False
    return subject.start() < action.start() < object_match.start()


def _has_complete_cooperation_clause(lower: str) -> bool:
    """Require an explicit subject and a concrete cooperation action/object."""

    subject = _ISSUER_SUBJECT_RE.search(lower)
    if not subject:
        return False
    for action_re in (
        _COOPERATION_AGREEMENT_ACTION_RE,
        _COOPERATION_OPERATION_ACTION_RE,
        _COOPERATION_CJK_ACTION_RE,
    ):
        action = action_re.search(lower)
        if action and subject.start() < action.start():
            return True
    return False


def _has_complete_issuer_action_clause(lower: str, action_re: re.Pattern[str]) -> bool:
    """Require the issuer subject to precede one event-specific action/object."""

    subject = _ISSUER_SUBJECT_RE.search(lower)
    action = action_re.search(lower)
    return bool(subject and action and subject.start() < action.start())


def _single_clause_text(lower: str) -> str | None:
    """Return one clause without a terminal mark, rejecting sentence stitching."""

    sentences = _split_event_sentences(lower)
    if len(sentences) != 1:
        return None
    sentence = sentences[0].rstrip()
    while sentence and _is_unicode_closing_delimiter(sentence[-1]):
        sentence = sentence[:-1].rstrip()
    return re.sub(r"[.!?。！？]+$", "", sentence).rstrip()


def _classify_hkex_business_clause(
    excerpt: str,
    score: int,
    *,
    title: str = "",
) -> tuple[str | None, str | None]:
    """Classify a complete business clause, or retain it as unconfirmed.

    HKEX PDFs commonly put a signing line or legal notice next to the actual
    announcement.  Token scoring alone treated ``By order of the Board`` as an
    order event.  Classification therefore has an explicit negative boundary
    before it considers the positive event vocabulary.
    """

    lower = _normal_text(excerpt).lower()
    if not lower or score <= 0:
        return None, "HKEX_EVENT_BODY_NO_SUBSTANTIVE_EVENT_LANGUAGE"
    if _is_routine_hkex_event_title(title):
        return None, "HKEX_EVENT_ROUTINE_DOCUMENT_EXCLUDED"
    # Cached official rows may retain a body excerpt containing a static
    # background sentence followed by the actual action.  Apply the same
    # sentence-local subject/action gate used by fresh extraction so a subject
    # in the first sentence cannot be borrowed by a later partner/regulator
    # sentence.  Fresh extraction normally reaches this function one sentence
    # at a time; this branch is the shared cache bridge.
    sentences = _split_event_sentences(lower)
    if len(sentences) > 1:
        valid: list[tuple[int, int, str]] = []
        for index, sentence in enumerate(sentences):
            sentence_score = sum(
                1 for token in _EVENT_BODY_STRONG_TOKENS if token.lower() in sentence
            )
            if sentence_score <= 0:
                continue
            event_kind, _reason = _classify_hkex_business_clause(
                sentence,
                sentence_score,
                title=title,
            )
            if event_kind is not None:
                valid.append((sentence_score, -index, event_kind))
        if valid:
            return max(valid)[2], None
        return None, "HKEX_EVENT_BUSINESS_ACTION_UNCONFIRMED"
    lower = _single_clause_text(lower)
    if lower is None:
        return None, "HKEX_EVENT_BUSINESS_ACTION_UNCONFIRMED"
    if len(lower) < 24:
        return None, "HKEX_EVENT_BUSINESS_CLAUSE_TOO_SHORT"
    if any(token in lower for token in _LEGAL_OR_SIGNATURE_TOKENS):
        return None, "HKEX_EVENT_LEGAL_OR_SIGNATURE_TEXT"
    if any(lower.endswith(token) or token in lower for token in _TRUNCATED_CLAUSE_TOKENS):
        # Keep a genuinely complete sentence such as ``in accordance with the
        # agreement, the parties will deliver...`` eligible; a fragment that
        # ends at the legal lead-in is only a source locator.
        if not re.search(r"(?:will|shall|has|have|entered|signed|launch|deliver|provide|推进|签署|建立|达成|交付|合作)", lower):
            return None, "HKEX_EVENT_TRUNCATED_BUSINESS_TEXT"
    # The strong-token score is discovery-only.  Every returned kind must pass
    # its own subject/action/object matcher in this same sentence; an
    # auxiliary such as ``has`` or ``is`` can never promote a static clause.
    candidates: tuple[tuple[str, tuple[str, ...], Callable[[str], bool]], ...] = (
        (
            "COOPERATION",
            ("合作", "cooperation", "partnership", "collaboration", "签约", "协议"),
            _has_complete_cooperation_clause,
        ),
        (
            "MARKET_ACCESS",
            ("included in the list", "eligible securities", "stock connect", "trading liquidity"),
            lambda value: not _CLAUSE_DANGLING_END_RE.search(value)
            and _has_complete_market_access_clause(value),
        ),
        (
            "ORDER_OR_CUSTOMER",
            ("订单", "order", "contract", "采购", "customer", "客户"),
            lambda value: _has_complete_issuer_action_clause(value, _ORDER_OR_CUSTOMER_ACTION_RE),
        ),
        (
            "REGULATORY",
            ("审批", "监管", "approval", "approved", "regulatory", "licen", "permit"),
            lambda value: _has_complete_issuer_action_clause(value, _REGULATORY_ACTION_RE),
        ),
        (
            "PRODUCT_OR_TECHNOLOGY",
            ("产品", "product", "technology", "技术", "量产", "production"),
            lambda value: _has_complete_issuer_action_clause(value, _PRODUCT_OR_TECHNOLOGY_ACTION_RE),
        ),
    )
    saw_kind_language = False
    for kind, tokens, matcher in candidates:
        if not any(token in lower for token in tokens):
            continue
        saw_kind_language = True
        if matcher(lower):
            return kind, None
    # There is deliberately no OFFICIAL_UPDATE fallback: a source with no
    # reliable kind-specific matcher remains source evidence but unconfirmed.
    if saw_kind_language:
        return None, "HKEX_EVENT_BUSINESS_ACTION_UNCONFIRMED"
    return None, "HKEX_EVENT_BUSINESS_ACTION_UNCONFIRMED"


def event_is_focus_eligible(
    event: Mapping[str, Any],
    *,
    target_trade_date: str,
    window_days: int = EVENT_FOCUS_WINDOW_DAYS,
) -> bool:
    """Return whether one event may enter the small manager focus set."""

    if event.get("body_parsed") is not True or event.get("event_relevant") is False:
        return False
    if event.get("event_status") == "CANNOT_CONFIRM" or event.get("summary_status") == "UNCONFIRMED":
        return False
    if not _event_is_temporally_confirmed(event):
        return False
    if not event.get("source_excerpt") or not event.get("event_type"):
        return False
    published = _as_datetime(event.get("publisher_timestamp"))
    if published is None:
        return False
    try:
        target_day = datetime.strptime(strict_trade_date(target_trade_date), "%Y%m%d").date()
    except (TypeError, ValueError):
        return False
    local_day = published.astimezone(_UTC8).date()
    return target_day - timedelta(days=max(0, int(window_days))) <= local_day <= target_day


def parse_hkex_event_document(
    body: bytes,
    *,
    title: str,
    max_bytes: int = HKEX_EVENT_PDF_MAX_BYTES,
    max_pages: int = HKEX_EVENT_PDF_MAX_PAGES,
) -> dict[str, Any]:
    """Parse bounded official announcement text for event evidence only.

    This deliberately returns page text metadata and a short excerpt rather
    than financial facts.  Oversized, non-PDF, scanned, and non-substantive
    documents remain explicit boundaries for the catalyst source.
    """

    if len(body) > max_bytes:
        return {
            "body_parsed": False,
            "parse_status": "PDF_BYTE_BUDGET_EXCEEDED",
            "parse_reason": "HKEX_EVENT_PDF_BYTE_BUDGET_EXCEEDED",
            "event_relevant": False,
            "pages": [],
        }
    if not body.startswith(b"%PDF"):
        return {
            "body_parsed": False,
            "parse_status": "NOT_A_PDF",
            "parse_reason": "HKEX_EVENT_DOCUMENT_NOT_PDF",
            "event_relevant": False,
            "pages": [],
        }
    try:
        pages = extract_pdf_pages(body)
    except PdfParseError as exc:
        return {
            "body_parsed": False,
            "parse_status": "PDF_PARSE_FAILED",
            "parse_reason": f"HKEX_EVENT_PDF_PARSE_FAILED:{type(exc).__name__}",
            "error": str(exc),
            "pages": [],
        }
    if not pages:
        return {
            "body_parsed": False,
            "parse_status": "PDF_NO_TEXT",
            "parse_reason": "HKEX_EVENT_PDF_SCANNED_OR_NO_TEXT",
            "event_relevant": False,
            "pages": [],
        }
    if len(pages) > max_pages:
        return {
            "body_parsed": False,
            "parse_status": "PDF_PAGE_BUDGET_EXCEEDED",
            "parse_reason": "HKEX_EVENT_PDF_PAGE_BUDGET_EXCEEDED",
            "event_relevant": False,
            "page_count": len(pages),
            "pages": [],
        }
    title_lower = str(title or "").lower()
    if any(token in title_lower for token in _ROUTINE_EVENT_TITLE_TOKENS):
        return {
            "body_parsed": True,
            "parse_status": "BODY_PARSED_NON_SUBSTANTIVE",
            "parse_reason": "HKEX_EVENT_ROUTINE_DOCUMENT_EXCLUDED",
            "event_relevant": False,
            "exclusion_reason": "正文已解析；标题和正文属于股东会/投票结果等例行公司治理文件，不计重大催化。",
            "page_count": len(pages),
            "pages": [int(page.get("page") or 0) for page in pages],
        }
    best: tuple[int, int, str] | None = None
    for page in pages:
        excerpt, score = _event_body_excerpt(str(page.get("text") or ""), title=title)
        if excerpt is None:
            continue
        candidate = (score, -int(page.get("page") or 0), excerpt)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return {
            "body_parsed": True,
            "parse_status": "BODY_PARSED_NON_SUBSTANTIVE",
            "parse_reason": "HKEX_EVENT_BODY_NO_SUBSTANTIVE_EVENT_LANGUAGE",
            "event_relevant": False,
            "exclusion_reason": "正文已解析，但未发现合作、订单、产品、交付或监管事项句子；不计重大催化。",
            "page_count": len(pages),
            "pages": [int(page.get("page") or 0) for page in pages],
        }
    score, negative_page, excerpt = best
    page_number = -negative_page
    event_kind, unconfirmed_reason = _classify_hkex_business_clause(excerpt, score)
    if event_kind is None:
        return {
            "body_parsed": True,
            "parse_status": "BODY_PARSED_SUMMARY_UNCONFIRMED",
            "parse_reason": unconfirmed_reason or "HKEX_EVENT_BODY_SUMMARY_UNCONFIRMED",
            "event_relevant": False,
            "event_status": "CANNOT_CONFIRM",
            "summary_status": "UNCONFIRMED",
            "summary_reason": "正文和定位已保留，但未找到完整、可解释的业务动作条款；不计业务事件或焦点排名。",
            "source_excerpt": excerpt,
            "evidence_page": page_number,
            "page_count": len(pages),
            "pages": [int(page.get("page") or 0) for page in pages],
            "score": score,
            "title": title,
        }
    return {
        "body_parsed": True,
        "parse_status": "BODY_PARSED_EVENT",
        "parse_reason": "HKEX_EVENT_BODY_SUBSTANTIVE_EVENT_TEXT",
        "event_relevant": True,
        "event_status": "READY",
        "summary_status": "INTERPRETABLE",
        "event_kind": event_kind,
        "source_excerpt": excerpt,
        "evidence_page": page_number,
        "page_count": len(pages),
        "pages": [int(page.get("page") or 0) for page in pages],
        "score": score,
        "title": title,
    }


def collect_hkex_event_directory(
    provider: Any,
    *,
    target_trade_date: str,
    cutoff_at: str,
    observations: Sequence[Mapping[str, Any]],
    previous_rows: Mapping[str, Mapping[str, Any]] | None = None,
    current_event_as_of: str | None = None,
) -> dict[str, Any]:
    """Read bounded same-issuer HKEX title rows without touching financial PDFs."""

    from .hkex_provider import ACTIVE_STOCK_LIST_URL, TITLE_SEARCH_URL, _is_substantive_report, parse_title_rows

    target = strict_trade_date(target_trade_date)
    now = _as_datetime(current_event_as_of) or datetime.now(timezone.utc)
    rows: dict[str, dict[str, Any]] = {}
    counts: dict[str, Any] = {
        "source_id": HKEX_EVENT_SOURCE_ID,
        "source_label": _source_label(HKEX_EVENT_SOURCE_ID),
        "requested_candidates": len(observations),
        "directory_requests": 0,
        "matched_issuers": 0,
        "event_rows": 0,
        "directory_only": 0,
        "pdf_requests": 0,
        "body_parsed": 0,
        "substantive_body": 0,
        "summary_unconfirmed": 0,
        "excluded_non_substantive": 0,
        "no_match": 0,
        "failed": 0,
        "completeness": "BOUNDED_SAME_ISSUER_DIRECTORY_ONLY",
        "no_match_is_not_complete": True,
    }
    try:
        mapping, mapping_sha, mapping_retrieved_at = provider._load_active_stocks()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        for observation in observations:
            code = str(observation.get("code") or "")
            rows[code] = _empty_source_row(code, source_id=HKEX_EVENT_SOURCE_ID, status="CANNOT_CONFIRM", reason="HKEX_EVENT_MAPPING_FAILED", coverage={**counts, "error": error})
        counts.update(status="CANNOT_CONFIRM", error=error)
        return {"schema_version": EVENT_SCHEMA_VERSION, "source_id": HKEX_EVENT_SOURCE_ID, "rows": rows, "source_counts": counts, "coverage": {"status": "CANNOT_CONFIRM", "completeness": counts["completeness"], "no_match_is_not_complete": True}, "current_event_as_of": now.isoformat(timespec="seconds")}

    for observation in observations:
        code = str(observation.get("code") or "")
        code_number = code.split(".", 1)[-1]
        issuer = mapping.get(code_number)
        if issuer is None:
            rows[code] = _empty_source_row(code, source_id=HKEX_EVENT_SOURCE_ID, status="CANNOT_CONFIRM", reason="ISSUER_NOT_IN_OFFICIAL_ACTIVE_LIST", coverage=dict(counts))
            continue
        counts["matched_issuers"] += 1
        target_day = datetime.strptime(target, "%Y%m%d").date()
        from_day = target_day - timedelta(days=90)
        query = urlencode({
            "lang": "EN", "category": "0", "market": "SEHK", "searchType": "0", "documentType": "-1",
            "t1code": "-2", "t2Gcode": "-2", "t2code": "-2", "stockId": issuer["stock_id"],
            "from": from_day.strftime("%Y%m%d"), "to": target, "title": "",
        })
        directory_url = f"{TITLE_SEARCH_URL}?{query}"
        try:
            provider._request(directory_url)
            response = provider._request(TITLE_SEARCH_URL, method="POST", body=query.encode("ascii"), headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": directory_url})
            counts["directory_requests"] += 2
            if response.status_code < 200 or response.status_code >= 300:
                raise EventSourceError(f"HKEX event directory HTTP {response.status_code}")
            directory_rows = parse_title_rows(response.body)
        except Exception as exc:
            counts["failed"] += 1
            rows[code] = _empty_source_row(code, source_id=HKEX_EVENT_SOURCE_ID, status="CANNOT_CONFIRM", reason="HKEX_EVENT_DIRECTORY_FAILED", coverage={**counts, "error": f"{type(exc).__name__}: {exc}"})
            continue
        cutoff_dt = datetime.fromisoformat(cutoff_at)
        candidates = [
            item for item in directory_rows
            if item.get("stock_code") == code_number
            and not _is_substantive_report(item)
            and _is_hkex_event_row({"headline": item.get("headline"), "document_title": item.get("document_title")})
            and _as_datetime(item.get("published_at")) is not None
            and _as_datetime(item.get("published_at")) <= now
            and str(item.get("published_at"))[:10].replace("-", "") <= target
        ]
        candidates = sorted(candidates, key=lambda item: (str(item.get("published_at", "")), str(item.get("url", ""))), reverse=True)[:HKEX_MAX_DOCUMENTS_PER_ISSUER]
        events: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []
        excluded_documents: list[dict[str, Any]] = []
        for item in candidates[:HKEX_EVENT_PDF_MAX_DOCUMENTS_PER_ISSUER]:
            published = str(item.get("published_at"))
            published_dt = _as_datetime(published)
            if published_dt is None:
                continue
            source_url = str(item.get("url"))
            source_title = item.get("document_title") or item.get("headline")
            directory_sha = _digest(response.body)
            body_response: SourceResponse | None = None
            parse_result: dict[str, Any]
            try:
                body_response = provider._request(source_url)
                counts["pdf_requests"] += 1
                if body_response.status_code < 200 or body_response.status_code >= 300:
                    raise EventSourceError(f"HKEX event document HTTP {body_response.status_code}")
                parse_result = parse_hkex_event_document(
                    body_response.body,
                    title=str(source_title or ""),
                )
            except Exception as exc:
                counts["failed"] += 1
                parse_result = {
                    "body_parsed": False,
                    "parse_status": "DOCUMENT_REQUEST_FAILED",
                    "parse_reason": f"HKEX_EVENT_DOCUMENT_REQUEST_FAILED:{type(exc).__name__}",
                    "error": f"{type(exc).__name__}: {exc}",
                    "event_relevant": False,
                    "pages": [],
                }
            body_sha = _digest(body_response.body) if body_response is not None else None
            body_retrieved_at = body_response.retrieved_at if body_response is not None else response.retrieved_at
            receipt = {
                "source_kind": "OFFICIAL",
                "source_id": HKEX_EVENT_SOURCE_ID,
                "url": source_url,
                "title": source_title,
                "directory_url": directory_url,
                "directory_sha256": directory_sha,
                "directory_retrieved_at": response.retrieved_at,
                "publisher_timestamp": published,
                "document_sha256": body_sha,
                "document_retrieved_at": body_retrieved_at,
                "body_parsed": bool(parse_result.get("body_parsed")),
                "parse_status": parse_result.get("parse_status"),
                "parse_reason": parse_result.get("parse_reason"),
                "evidence_page": parse_result.get("evidence_page"),
                "page_count": parse_result.get("page_count"),
            }
            if parse_result.get("event_relevant") is True:
                counts["body_parsed"] += 1
                counts["substantive_body"] += 1
                event = {
                    "event_id": sha256(canonical_json({"url": source_url, "sha256": body_sha, "title": source_title})).hexdigest()[:24],
                    "event_type": parse_result.get("event_kind") or "OFFICIAL_ANNOUNCEMENT",
                    "source_kind": "OFFICIAL",
                    "source_id": HKEX_EVENT_SOURCE_ID,
                    "evidence_level": "OFFICIAL_BODY_PARSED",
                    "official_confirmation_status": "OFFICIAL_BODY_PARSED",
                    "code": code,
                    "name": observation.get("name"),
                    "counterparty": None,
                    "catalyst": item.get("headline") or source_title,
                    "why_might_affect_business": parse_result.get("source_excerpt"),
                    "source_excerpt": parse_result.get("source_excerpt"),
                    "realization_conditions": ["核对官方正文中的条款、约束和履约/交付条件，再观察订单、量产或收入兑现。"],
                    "financial_counterevidence": [],
                    "market_confirmation_gap": ["MARKET_PRICE_VOLUME_UNCONFIRMED", "ORDER_OR_REVENUE_UNCONFIRMED"],
                    "reported_event_date_text": None,
                    "publisher_timestamp": published,
                    "publisher_timestamp_text": item.get("release_time"),
                    "publisher_timezone": "Asia/Shanghai",
                    "publisher_timezone_assumed": False,
                    "first_seen_at": _previous_first_seen((previous_rows or {}).get(code), {"source_url": source_url}) or response.retrieved_at,
                    "first_public_announcement_time": published,
                    "source_url": source_url,
                    "source_title": source_title,
                    "source_sha256": body_sha,
                    "directory_url": directory_url,
                    "directory_sha256": directory_sha,
                    "directory_retrieved_at": response.retrieved_at,
                    "retrieved_at": body_retrieved_at,
                    "body_parsed": True,
                    "body_parse_status": parse_result.get("parse_status"),
                    "body_parse_reason": parse_result.get("parse_reason"),
                    "evidence_page": parse_result.get("evidence_page"),
                    "page_count": parse_result.get("page_count"),
                    "as_of_bucket": "historical" if published_dt <= cutoff_dt else "current",
                }
                events.append(event)
                receipt["status"] = "READY"
                receipt["event_relevant"] = True
            elif parse_result.get("summary_status") == "UNCONFIRMED":
                # Keep the parsed source, hash and page visible as an audit
                # item, while making it impossible for downstream advice or
                # focus ranking to treat a legal/signature fragment as a
                # business event.
                counts["body_parsed"] += 1
                counts["summary_unconfirmed"] += 1
                receipt.update(
                    status="CANNOT_CONFIRM",
                    event_relevant=False,
                    summary_status="UNCONFIRMED",
                    summary_reason=parse_result.get("summary_reason"),
                )
                event = {
                    "event_id": sha256(canonical_json({"url": source_url, "sha256": body_sha, "title": source_title})).hexdigest()[:24],
                    "event_type": "OFFICIAL_UNCONFIRMED",
                    "source_kind": "OFFICIAL",
                    "source_id": HKEX_EVENT_SOURCE_ID,
                    "evidence_level": "OFFICIAL_BODY_PARSED_UNCONFIRMED",
                    "official_confirmation_status": "CANNOT_CONFIRM",
                    "event_status": "CANNOT_CONFIRM",
                    "summary_status": "UNCONFIRMED",
                    "code": code,
                    "name": observation.get("name"),
                    "counterparty": None,
                    "catalyst": item.get("headline") or source_title,
                    "why_might_affect_business": "正文和定位已保留；业务影响摘要待核实，不计作已解释事件。",
                    "source_excerpt": parse_result.get("source_excerpt"),
                    "summary_reason": parse_result.get("summary_reason"),
                    "realization_conditions": ["补齐完整业务动作条款后再判断业务影响。"],
                    "financial_counterevidence": [],
                    "market_confirmation_gap": ["BUSINESS_SUMMARY_UNCONFIRMED", "MARKET_PRICE_VOLUME_UNCONFIRMED", "ORDER_OR_REVENUE_UNCONFIRMED"],
                    "reported_event_date_text": None,
                    "publisher_timestamp": published,
                    "publisher_timestamp_text": item.get("release_time"),
                    "publisher_timezone": "Asia/Shanghai",
                    "publisher_timezone_assumed": False,
                    "first_seen_at": _previous_first_seen((previous_rows or {}).get(code), {"source_url": source_url}) or response.retrieved_at,
                    "first_public_announcement_time": published,
                    "source_url": source_url,
                    "source_title": source_title,
                    "source_sha256": body_sha,
                    "directory_url": directory_url,
                    "directory_sha256": directory_sha,
                    "directory_retrieved_at": response.retrieved_at,
                    "retrieved_at": body_retrieved_at,
                    "body_parsed": True,
                    "body_parse_status": parse_result.get("parse_status"),
                    "body_parse_reason": parse_result.get("parse_reason"),
                    "evidence_page": parse_result.get("evidence_page"),
                    "page_count": parse_result.get("page_count"),
                    "as_of_bucket": "historical" if published_dt <= cutoff_dt else "current",
                }
                events.append(event)
            elif parse_result.get("body_parsed") is True:
                counts["body_parsed"] += 1
                counts["excluded_non_substantive"] += 1
                receipt.update(
                    status="EXCLUDED_NON_SUBSTANTIVE",
                    event_relevant=False,
                    exclusion_reason=parse_result.get("exclusion_reason") or "正文已解析但未形成重大催化句子；不计重大催化。",
                )
                excluded_documents.append({
                    "source_url": source_url,
                    "source_title": source_title,
                    "publisher_timestamp": published,
                    "body_parsed": True,
                    "parse_status": parse_result.get("parse_status"),
                    "exclusion_reason": receipt["exclusion_reason"],
                    "document_sha256": body_sha,
                    "evidence_page": parse_result.get("evidence_page"),
                })
            else:
                counts["directory_only"] += 1
                receipt.update(status="DIRECTORY_ONLY", event_relevant=False)
                event = {
                    "event_id": sha256(canonical_json({"url": source_url, "title": source_title})).hexdigest()[:24],
                    "event_type": "OFFICIAL_ANNOUNCEMENT",
                    "source_kind": "OFFICIAL",
                    "source_id": HKEX_EVENT_SOURCE_ID,
                    "evidence_level": "OFFICIAL_DIRECTORY_ONLY",
                    "official_confirmation_status": "BODY_NOT_PARSED",
                    "code": code,
                    "name": observation.get("name"),
                    "counterparty": None,
                    "catalyst": item.get("headline") or source_title,
                    "why_might_affect_business": "港交所同发行人目录显示非财报公告；正文未能在有界 PDF 读取中核验，业务影响待确认。",
                    "source_excerpt": None,
                    "realization_conditions": ["补齐官方公告正文并确认条款、约束和实际业务影响。"],
                    "financial_counterevidence": [],
                    "market_confirmation_gap": ["DIRECTORY_ONLY_BODY_NOT_PARSED", "MARKET_PRICE_VOLUME_UNCONFIRMED", "ORDER_OR_REVENUE_UNCONFIRMED"],
                    "reported_event_date_text": None,
                    "publisher_timestamp": published,
                    "publisher_timestamp_text": item.get("release_time"),
                    "publisher_timezone": "Asia/Shanghai",
                    "publisher_timezone_assumed": False,
                    "first_seen_at": _previous_first_seen((previous_rows or {}).get(code), {"source_url": source_url}) or response.retrieved_at,
                    "first_public_announcement_time": "CANNOT_CONFIRM",
                    "source_url": source_url,
                    "source_title": source_title,
                    "source_sha256": None,
                    "directory_url": directory_url,
                    "directory_sha256": directory_sha,
                    "directory_retrieved_at": response.retrieved_at,
                    "retrieved_at": response.retrieved_at,
                    "body_parsed": False,
                    "body_parse_status": parse_result.get("parse_status"),
                    "body_parse_reason": parse_result.get("parse_reason"),
                    "as_of_bucket": "historical" if published_dt <= cutoff_dt else "current",
                }
                events.append(event)
            receipts.append(receipt)
        if events:
            counts["event_rows"] += len(events)
            row_status = "READY" if any(event.get("event_relevant") is True and event.get("event_status") != "CANNOT_CONFIRM" for event in events) else (
                "CANNOT_CONFIRM" if any(event.get("event_status") == "CANNOT_CONFIRM" for event in events) else "DIRECTORY_ONLY"
            )
            rows[code] = {"status": row_status, "reason": "EVENT_BODY_PARSED" if row_status == "READY" else ("BUSINESS_SUMMARY_UNCONFIRMED" if row_status == "CANNOT_CONFIRM" else "DIRECTORY_ONLY_BODY_NOT_PARSED"), "events": events, "excluded_documents": excluded_documents, "source_receipts": receipts, "coverage": dict(counts), "source_id": HKEX_EVENT_SOURCE_ID}
        elif excluded_documents:
            counts["no_match"] += 1
            rows[code] = {"status": "NO_MATCH", "reason": "NON_SUBSTANTIVE_ANNOUNCEMENTS_EXCLUDED", "events": [], "excluded_documents": excluded_documents, "source_receipts": receipts, "coverage": dict(counts), "source_id": HKEX_EVENT_SOURCE_ID}
        else:
            counts["no_match"] += 1
            rows[code] = _empty_source_row(code, source_id=HKEX_EVENT_SOURCE_ID, status="NO_MATCH", reason="NO_MATCH_IS_NOT_COMPLETE", coverage=dict(counts))
    counts["status"] = "READY" if counts["substantive_body"] else "PARTIAL_WITH_ROWS"
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "source_id": HKEX_EVENT_SOURCE_ID,
        "rows": rows,
        "source_counts": counts,
        "coverage": {"status": counts["status"], "completeness": counts["completeness"], "no_match_is_not_complete": True, "current_event_as_of": now.isoformat(timespec="seconds")},
        "current_event_as_of": now.isoformat(timespec="seconds"),
    }


def build_catalyst_advice(
    events: Sequence[Mapping[str, Any]],
    *,
    financial_advice: Mapping[str, Any] | None = None,
    target_trade_date: str | None = None,
    focus_window_days: int = EVENT_FOCUS_WINDOW_DAYS,
) -> dict[str, Any]:
    """Create a concise backend-owned event interpretation, separate from finance."""

    if not events:
        return {
            "status": "CANNOT_CONFIRM",
            "label": "CANNOT_CONFIRM（催化）",
            "priority_rank": None,
            "priority_reason": "已检查本批有界事件源，但没有可绑定事件；NO_MATCH 不代表全市场无催化。",
            "summary": "当前催化覆盖只到已接入的有界媒体与同发行人公告目录。",
        }
    temporally_confirmed = [event for event in events if _event_is_temporally_confirmed(event)]
    interpretable = [
        event for event in events
        if event.get("body_parsed") is True
        and event.get("event_relevant") is not False
        and event.get("event_status") != "CANNOT_CONFIRM"
        and event.get("summary_status") != "UNCONFIRMED"
        and event.get("source_excerpt")
    ]
    focus_events = [
        event for event in interpretable
        if target_trade_date is None
        or event_is_focus_eligible(event, target_trade_date=target_trade_date, window_days=focus_window_days)
    ]
    if not temporally_confirmed:
        return {
            "status": "CANNOT_CONFIRM",
            "label": "CANNOT_CONFIRM（催化时间）",
            "priority_rank": None,
            "priority_reason": "已解析到匹配事件正文，但发布时点未确认；不能放入历史09:40或当前补充时间桶。",
            "summary": "事件正文、来源回执和实体归属已保留，发布时点与历史/当前可用性仍待确认。",
        }
    if not focus_events:
        reason = (
            "来源材料已保留，但没有同时满足完整业务动作、明确发布时间和"
            f"目标日前{focus_window_days}个自然日窗口的可解释事件；不进入重点焦点或排名。"
        )
        if any(event.get("summary_status") == "UNCONFIRMED" for event in events):
            reason += " 正文摘要待核实，不能把签名、法律或残缺片段当作业务影响。"
        elif any(event.get("body_parsed") is not True for event in events):
            reason += " DIRECTORY_ONLY 仅作为审计线索。"
        return {
            "status": "CANNOT_CONFIRM",
            "label": "CANNOT_CONFIRM（催化焦点）",
            "priority_rank": None,
            "focus_eligible": False,
            "focus_window_days": focus_window_days,
            "priority_reason": reason,
            "summary": "完整候选和来源回执保留在审计区；未知材料不自动等于正向催化。",
        }
    current_count = sum(1 for event in focus_events if event.get("as_of_bucket") == "current")
    media_count = sum(1 for event in focus_events if event.get("source_kind") == "MEDIA")
    official_count = sum(1 for event in focus_events if event.get("source_kind") == "OFFICIAL")
    reason = (
        f"后端在当前有界窗口发现 {len(focus_events)} 条可解释事件（当前补充 {current_count} 条；媒体 {media_count}、"
        f"港交所目录 {official_count}），保留为催化观察；官方确认、订单/收入与市场兑现仍未确认。"
    )
    if financial_advice and str(financial_advice.get("action")) in {"AVOID", "WATCH"}:
        reason += " 财务意见单独显示，不会把事件从页面隐藏。"
    return {
        "status": "OBSERVE",
        "label": "催化观察",
        "priority_rank": None,
        "focus_eligible": True,
        "focus_window_days": focus_window_days,
        "priority_reason": reason,
        "summary": "事件与财务意见分开；合作或报道不自动等于订单、收入或 BUY。",
    }


def merge_event_batches(
    *,
    target_trade_date: str,
    cutoff_at: str,
    observations: Sequence[Mapping[str, Any]],
    batches: Sequence[Mapping[str, Any]],
    previous_rows: Mapping[str, Mapping[str, Any]] | None = None,
    current_event_as_of: str | None = None,
) -> dict[str, Any]:
    """Merge source-specific event results without merging financial facts."""

    now = _as_datetime(current_event_as_of) or datetime.now(timezone.utc)
    merged_rows: dict[str, dict[str, Any]] = {}
    source_counts: list[Mapping[str, Any]] = []
    for batch in batches:
        if isinstance(batch.get("source_counts"), Mapping):
            source_counts.append(batch["source_counts"])
    for observation in observations:
        code = str(observation.get("code") or "")
        # Previous event objects are raw source material, not a disposable
        # classification projection.  Seed the union from the previous exact
        # product so a refresh that returns only the current bounded window
        # cannot erase older source identities or excerpts.  Current rows are
        # appended only when they are genuinely new; the previous object wins
        # on an identity collision and therefore remains byte-for-byte source
        # faithful for immutable raw fields.
        event_list: list[dict[str, Any]] = []
        previous = (previous_rows or {}).get(code)
        if isinstance(previous, Mapping):
            previous_events = previous.get("events")
            if isinstance(previous_events, list):
                for event in previous_events:
                    if isinstance(event, Mapping):
                        event_list.append(dict(event))
        receipts: list[dict[str, Any]] = []
        excluded_documents: list[dict[str, Any]] = []
        source_coverage: list[dict[str, Any]] = []
        errors: list[str] = []
        for batch in batches:
            batch_rows = batch.get("rows") if isinstance(batch, Mapping) else None
            item = batch_rows.get(code) if isinstance(batch_rows, Mapping) else None
            if not isinstance(item, Mapping):
                continue
            item_events = item.get("events") if isinstance(item.get("events"), list) else []
            for event in item_events:
                if isinstance(event, Mapping):
                    if not _event_key(event):
                        continue
                    if not any(_event_identity_matches(existing, event) for existing in event_list):
                        event_list.append(dict(event))
            for receipt in item.get("source_receipts", []) if isinstance(item.get("source_receipts"), list) else []:
                if isinstance(receipt, Mapping):
                    receipts.append(dict(receipt))
            for document in item.get("excluded_documents", []) if isinstance(item.get("excluded_documents"), list) else []:
                if isinstance(document, Mapping):
                    excluded_documents.append(dict(document))
            coverage = item.get("coverage")
            if isinstance(coverage, Mapping):
                source_coverage.append(dict(coverage))
            if item.get("status") == "CANNOT_CONFIRM" and item.get("reason"):
                errors.append(str(item["reason"]))
        # Preserve source receipts and excluded-document evidence from the
        # previous exact product as well.  The current batch is kept first so
        # its current receipt metadata remains visible; only exact duplicate
        # identities are collapsed.
        if isinstance(previous, Mapping):
            previous_receipts = previous.get("source_receipts")
            if isinstance(previous_receipts, list):
                receipts.extend(dict(item) for item in previous_receipts if isinstance(item, Mapping))
            previous_excluded = previous.get("excluded_documents")
            if isinstance(previous_excluded, list):
                excluded_documents.extend(dict(item) for item in previous_excluded if isinstance(item, Mapping))
        receipt_map: dict[str, dict[str, Any]] = {}
        for receipt in receipts:
            receipt_map.setdefault(_record_identity(receipt), receipt)
        receipts = list(receipt_map.values())
        excluded_map: dict[str, dict[str, Any]] = {}
        for document in excluded_documents:
            excluded_map.setdefault(_record_identity(document), document)
        excluded_documents = list(excluded_map.values())
        event_list.sort(key=lambda event: (str(event.get("publisher_timestamp") or ""), str(event.get("source_url") or "")), reverse=True)
        historical = [event for event in event_list if event.get("as_of_bucket") == "historical"]
        current = [event for event in event_list if event.get("as_of_bucket") == "current"]
        financial_advice = None
        catalyst_advice = build_catalyst_advice(
            event_list,
            financial_advice=financial_advice,
            target_trade_date=target_trade_date,
        )
        focus_events = [
            event for event in event_list
            if event_is_focus_eligible(event, target_trade_date=target_trade_date)
        ]
        if event_list:
            if any(
                event.get("body_parsed") is True
                and event.get("event_relevant") is not False
                and event.get("event_status") != "CANNOT_CONFIRM"
                and event.get("summary_status") != "UNCONFIRMED"
                and _event_is_temporally_confirmed(event)
                for event in event_list
            ):
                status = "READY"
            elif any(event.get("event_status") == "CANNOT_CONFIRM" for event in event_list):
                status = "CANNOT_CONFIRM"
            else:
                status = "DIRECTORY_ONLY"
        elif errors:
            status = "CANNOT_CONFIRM"
        else:
            status = "NO_MATCH"
        merged_rows[code] = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "status": status,
            "reason": "NO_MATCH_IS_NOT_COMPLETE" if status == "NO_MATCH" else ("EVENTS_MERGED" if event_list else ";".join(errors)),
            "events": event_list[:6],
            "historical_events": historical[:6],
            "current_events": current[:6],
            "excluded_documents": excluded_documents[:6],
            "catalyst_advice": catalyst_advice,
            "source_coverage": source_coverage,
            "source_receipts": receipts,
            "coverage": {
                "requested_candidates": len(observations),
                "source_count": len(source_coverage),
                "event_count": len(event_list),
                "historical_event_count": len(historical),
                "current_event_count": len(current),
                "interpretable_event_count": sum(
                    1 for event in event_list
                    if event.get("body_parsed") is True
                    and event.get("event_relevant") is not False
                    and event.get("event_status") != "CANNOT_CONFIRM"
                    and event.get("summary_status") != "UNCONFIRMED"
                ),
                "focus_event_count": len(focus_events),
                "focus_window_days": EVENT_FOCUS_WINDOW_DAYS,
                "excluded_non_substantive_count": len(excluded_documents),
                "no_match_is_not_complete": True,
                "completeness": "BOUNDED_SOURCES_ONLY",
                "current_event_as_of": now.isoformat(timespec="seconds"),
            },
            "current_event_as_of": now.isoformat(timespec="seconds"),
            "financial_counterevidence": [],
            "market_confirmation_gap": sorted({
                gap
                for event in event_list
                for gap in (event.get("market_confirmation_gap") if isinstance(event.get("market_confirmation_gap"), list) else [])
            }),
        }
    all_events = [event for row in merged_rows.values() for event in row.get("events", [])]
    source_statuses = [
        str(batch.get("status") or batch.get("coverage", {}).get("status") or "").upper()
        for batch in batches
        if isinstance(batch, Mapping)
    ]
    all_sources_failed = bool(source_statuses) and all(
        _source_batch_failed(batch)
        for batch in batches
        if isinstance(batch, Mapping)
    )
    interpretable_events = [
        event for event in all_events
        if event.get("event_relevant") is not False
        and event.get("event_status") != "CANNOT_CONFIRM"
        and event.get("summary_status") != "UNCONFIRMED"
    ]
    aggregate_status = "CANNOT_CONFIRM" if all_sources_failed and not interpretable_events else ("READY" if interpretable_events else "PARTIAL_WITH_ROWS")
    aggregate_reason = (
        "ALL_EVENT_SOURCES_FAILED"
        if aggregate_status == "CANNOT_CONFIRM" and all_sources_failed and not all_events
        else None
    )
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "status": aggregate_status,
        "reason": aggregate_reason,
        "rows": merged_rows,
        "source_counts": source_counts,
        "coverage": {
            "requested_candidates": len(observations),
            "event_count": len(all_events),
            "historical_event_count": sum(len(row.get("historical_events", [])) for row in merged_rows.values()),
            "current_event_count": sum(len(row.get("current_events", [])) for row in merged_rows.values()),
            "focus_event_count": sum(
                1 for event in all_events
                if event_is_focus_eligible(event, target_trade_date=target_trade_date)
            ),
            "focus_window_days": EVENT_FOCUS_WINDOW_DAYS,
            "excluded_non_substantive_count": sum(len(row.get("excluded_documents", [])) for row in merged_rows.values()),
            "source_counts": source_counts,
            "status": aggregate_status,
            "reason": aggregate_reason,
            "all_sources_failed": all_sources_failed,
            "completeness": "BOUNDED_SOURCES_ONLY",
            "no_match_is_not_complete": True,
            "current_event_as_of": now.isoformat(timespec="seconds"),
            "historical_cutoff_at": cutoff_at,
        },
        "current_event_as_of": now.isoformat(timespec="seconds"),
        "historical_cutoff_at": cutoff_at,
    }


__all__ = [
    "BoundedMediaTransport",
    "EVENT_SCHEMA_VERSION",
    "EventSourceError",
    "HKEX_EVENT_SOURCE_ID",
    "ICCSZ_HOME_URL",
    "MEDIA_SOURCE_ID",
    "build_catalyst_advice",
    "collect_hkex_event_directory",
    "discover_iccsz_events",
    "event_is_focus_eligible",
    "merge_event_batches",
    "parse_hkex_event_document",
    "parse_iccsz_article",
    "parse_iccsz_directory",
]
