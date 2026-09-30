"""Bounded public-news reader for the V4 manager research product.

This module adapts the public Eastmoney search route used by the existing
Vibe reader.  It is intentionally a reader, not a catalyst selector: rows are
joined to the already fixed candidate observations, retained with their
original title/excerpt/source/link, and never converted into a score,
recommendation, or event-value claim.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
import hashlib
from html import unescape
import json
import re
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


READER_SCHEMA = "v4.manager_research.material_reader.v1"
READER_SOURCE_ID = "eastmoney.public.news.reader.v1"
READER_SOURCE_METHOD = "eastmoney.search-api-web.cmsArticleWebOld"
READER_PROVIDER = "Eastmoney public news"
MAX_ROWS_PER_CANDIDATE = 20
MAX_WORKERS = 3
REQUEST_TIMEOUT_SECONDS = 12.0
MAX_EXCLUDED_ROWS = 30
EASTMONEY_SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"
_HTML_TAG_RE = re.compile(r"<[^>]*>")


class ReaderSourceError(RuntimeError):
    """A bounded public-news source failed for one candidate."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    return unescape(_HTML_TAG_RE.sub("", str(value))).strip()


def _valid_http_url(value: Any) -> str | None:
    """Return a source URL only when it is an absolute HTTP(S) URL.

    Public-source payloads are data, not trusted markup.  Keep the original
    spelling for a valid link, but drop non-web schemes and malformed values
    before they enter the reader projection or its attribution list.
    """

    raw = _text(value)
    if not raw or any(character.isspace() for character in raw):
        return None
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        # ``urlsplit`` defers validating the port until this property is
        # accessed.  Force that validation here so the backend projection
        # emits the same accepted URL set as the frontend ``URL`` check.
        parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not hostname:
        return None
    return raw


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso_date(value: Any) -> str | None:
    raw = _text(value)
    if re.fullmatch(r"\d{8}", raw):
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return None


def _published_date(value: Any) -> str | None:
    raw = _text(value).replace("/", "-")
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
    return _iso_date(match.group(1)) if match else None


def _target_iso(value: Any) -> str | None:
    return _iso_date(value)


def _canonical(code: str, market: str) -> str:
    compact = re.sub(r"[^0-9]", "", _text(code))
    return f"HK.{compact.zfill(5)}" if market.upper() == "HK" else compact.zfill(6)


def _source_value(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _company_match(text: str, code: str, name: str, market: str) -> str | None:
    haystack = _text(text).casefold()
    if not haystack:
        return None
    compact = re.sub(r"[^0-9]", "", _text(code))
    if not compact:
        return None
    patterns = [re.escape(compact)]
    if market.upper() == "HK":
        patterns.extend((re.escape(f"HK.{compact}"), re.escape(f"{compact}.HK")))
    if any(re.search(rf"(?<!\d){pattern}(?!\d)", haystack, flags=re.IGNORECASE) for pattern in patterns):
        return "code"
    clean_name = _text(name).casefold()
    if clean_name and len(clean_name) >= 2 and clean_name in haystack:
        return "name"
    # Public HK headlines sometimes omit the -W suffix.  This remains an
    # explicit name match and does not create a market-wide join.
    if market.upper() == "HK" and clean_name.endswith("-w") and clean_name[:-2] in haystack:
        return "name_variant"
    return None


def _scope_for(title: str, body: str, *, matched: str | None, market: str) -> tuple[str, str]:
    """Describe visible scope without deciding whether a row is valuable."""

    if not matched:
        return "industry_background", "未出现固定候选的代码或名称；保留为背景材料，不绑定公司事实"
    text = f"{title} {body}"
    if re.search(r"龙虎榜.*(?:前\s*\d+|前十|席位|详情)|(?:前\s*\d+|前十).*(?:龙虎榜|席位)", text, flags=re.I):
        return "ranking_context", "榜单/排名材料；只展示原文范围，不把榜单数字归属于本公司"
    if market.upper() == "HK" and re.search(r"(?:港股通|南向资金)", text, flags=re.I):
        if re.search(r"(?:名单|连续(?:净买入|买入)|排名|排行|成交活跃股|活跃股)", text, flags=re.I):
            return "ranking_context", "港股通/南向排名或名单材料；不推断本公司资金流"
        if re.search(r"(?:净买入|净卖出|亿港元|成交金额|成交净买入|加仓|流出|多只|其他)", text, flags=re.I):
            return "aggregate_context", "市场聚合材料；数字没有切分到本公司"
    if re.search(r"\d+\s*只?(?:个股|股票|股)|融资客|大宗交易|净买入超|净卖出超|成交额超|全市场", text, flags=re.I):
        return "aggregate_context", "市场聚合材料；数字没有切分到本公司"
    return "company_material", "标题或正文出现固定候选代码/名称；仅展示原文，不替代官方事实"


def _jsonp_rows(body: bytes) -> list[dict[str, Any]]:
    text = body.decode("utf-8-sig", errors="replace").strip()
    start = text.find("(")
    end = text.rfind(")")
    if start < 0 or end <= start:
        raise ReaderSourceError("PUBLIC_NEWS_RESPONSE_NOT_JSONP")
    try:
        payload = json.loads(text[start + 1:end])
    except json.JSONDecodeError as exc:
        raise ReaderSourceError("PUBLIC_NEWS_RESPONSE_INVALID_JSON") from exc
    result = payload.get("result") if isinstance(payload, Mapping) else None
    rows = result.get("cmsArticleWebOld") if isinstance(result, Mapping) else None
    if not isinstance(rows, list):
        raise ReaderSourceError("PUBLIC_NEWS_RESPONSE_ROWS_MISSING")
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _normalise_target_code(code: str, market: str) -> str:
    raw = _text(code).upper()
    if market.upper() == "HK":
        return re.sub(r"[^0-9]", "", raw).zfill(5)
    return re.sub(r"[^0-9]", "", raw).zfill(6)


def build_search_url(code: str, *, market: str = "HK", limit: int = MAX_ROWS_PER_CANDIDATE) -> str:
    """Build the same public search route as the Vibe adapter."""

    safe_limit = max(1, min(int(limit), MAX_ROWS_PER_CANDIDATE))
    inner = {
        "uid": "",
        "keyword": _normalise_target_code(code, market),
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": safe_limit,
                "preTag": "<em>",
                "postTag": "</em>",
            }
        },
    }
    params = {
        "cb": "jQuery35101792940631092459_1764599530165",
        "param": json.dumps(inner, ensure_ascii=False, separators=(",", ":")),
        "_": "1764599530176",
    }
    return f"{EASTMONEY_SEARCH_URL}?{urlencode(params)}"


def _http_fetch_raw(url: str, timeout: float, referer: str) -> tuple[int, bytes]:
    request = Request(
        url,
        headers={
            "Accept": "*/*",
            "Referer": referer,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
        status = int(getattr(response, "status", 200))
    return status, body


def _news_referer(code: str, market: str) -> str:
    return f"https://so.eastmoney.com/news/s?keyword={_normalise_target_code(code, market)}"


def _default_fetch(code: str, *, market: str, limit: int, timeout: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = build_search_url(code, market=market, limit=limit)
    try:
        status, body = _http_fetch_raw(url, timeout, _news_referer(code, market))
    except Exception as exc:  # noqa: BLE001 — per-stock source failure is data
        raise ReaderSourceError(f"PUBLIC_NEWS_FETCH_FAILED:{type(exc).__name__}") from exc
    if status < 200 or status >= 300:
        raise ReaderSourceError(f"PUBLIC_NEWS_HTTP_{status}")
    return _jsonp_rows(body), {
        "url": url,
        "source_body_sha256": hashlib.sha256(body).hexdigest(),
        "http_status": status,
    }


def material_reader_fetcher(
    store: Any,
    *,
    ttl_seconds: float | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    raw_fetch: Callable[..., tuple[int, bytes]] | None = None,
) -> Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]]:
    """Reader fetcher over the shared MaterialStore (one search per code/limit).

    Each bounded search response is stored once and reused by any caller that
    asks for the same (market, code, limit) until its TTL expires; the reader
    receipt still reports the raw body digest and the original status.
    """

    fetch_raw = raw_fetch or _http_fetch_raw

    def fetch(*, code: str, market: str = "HK", limit: int = MAX_ROWS_PER_CANDIDATE) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        capped = max(1, min(int(limit), MAX_ROWS_PER_CANDIDATE))
        url = build_search_url(code, market=market, limit=capped)
        referer = _news_referer(code, market)

        def transport(_url: str) -> dict[str, Any]:
            try:
                status, body = fetch_raw(url, timeout, referer)
            except Exception as exc:  # noqa: BLE001 — per-stock source failure is data
                raise ReaderSourceError(f"PUBLIC_NEWS_FETCH_FAILED:{type(exc).__name__}") from exc
            if status < 200 or status >= 300 or not body:
                raise ReaderSourceError(f"PUBLIC_NEWS_HTTP_{status}")
            return {
                "body": body,
                "content_type": "application/javascript",
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }

        material = store.fetch(
            f"eastmoney:{market}:{code}:{capped}",
            url=url,
            ttl_seconds=ttl_seconds,
            transport=transport,
        )
        return _jsonp_rows(material.body), {
            "url": material.url,
            "source_body_sha256": material.sha256,
            "http_status": 200,
        }

    return fetch


def _empty_bundle(code: str, name: str, market: str, target_date: Any, queried_at: str, status: str, gaps: list[str]) -> dict[str, Any]:
    return {
        "schema": READER_SCHEMA,
        "source_id": READER_SOURCE_ID,
        "available": False,
        "status": status,
        "market": market,
        "code": code,
        "canonical_symbol": _canonical(code, market),
        "name": name or code,
        "target_date": _target_iso(target_date),
        "queried_at": queried_at,
        "collected_at": queried_at,
        "provider": READER_PROVIDER,
        "source_method": READER_SOURCE_METHOD,
        "source_hash": None,
        "raw_record_count": 0,
        "material_count": 0,
        "company_record_count": 0,
        "background_record_count": 0,
        "truncated": False,
        "materials": [],
        "company_news": [],
        "background": [],
        "excluded": [],
        "source_gaps": list(gaps),
    }


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # A repeated article can arrive under the same Eastmoney URL, or through
    # two publisher rows with different URLs but identical title/body/date.
    # Keep one readable card while retaining every source attribution.
    by_key: dict[str, dict[str, Any]] = {}
    by_url: dict[str, dict[str, Any]] = {}
    by_content: dict[str, dict[str, Any]] = {}
    for item in items:
        url = _text(item.get("url"))
        content_key = _stable_hash({
            "title": item.get("title"),
            "content_excerpt": item.get("content_excerpt"),
            "published_at": item.get("published_at"),
        })
        key = url or content_key
        prior = by_url.get(url) if url else None
        if prior is None:
            prior = by_content.get(content_key)
        if prior is None:
            item["source_attributions"] = [
                {
                    "source_name": item.get("source_name"),
                    "url": item.get("url"),
                    "source_method": item.get("source_method"),
                }
            ]
            item["source_count"] = 1
            by_key[key] = item
            if url:
                by_url[url] = item
            by_content[content_key] = item
            continue
        attributions = prior.setdefault("source_attributions", [])
        attribution = {
            "source_name": item.get("source_name"),
            "url": item.get("url"),
            "source_method": item.get("source_method"),
        }
        if attribution not in attributions:
            attributions.append(attribution)
        prior["source_count"] = len(attributions)
        if url:
            by_url[url] = prior
        by_content[content_key] = prior
    return list(by_key.values())


def project_public_news(
    rows: Sequence[Mapping[str, Any]] | None,
    *,
    code: str,
    name: str = "",
    market: str = "HK",
    target_date: str | None = None,
    queried_at: str | None = None,
    source_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project raw public rows into an exact-company, date-bounded reader feed."""

    queried = queried_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    target_iso = _target_iso(target_date) if target_date is not None else None
    if target_date is not None and target_iso is None:
        return _empty_bundle(code, name, market, target_date, queried, "INVALID_DATE", ["INVALID_DATE: 新闻目标日期必须是 YYYY-MM-DD 或 YYYYMMDD"])
    raw_rows = list(rows) if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)) else []
    materials: list[dict[str, Any]] = []
    background: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            if len(excluded) < MAX_EXCLUDED_ROWS:
                excluded.append({"index": index, "reason": "INVALID_RECORD"})
            continue
        title = _text(_source_value(raw, "新闻标题", "标题", "title"))
        body = _text(_source_value(raw, "新闻内容", "内容", "content", "summary"))
        published_at = _text(_source_value(raw, "发布时间", "published_at", "publish_time", "date"))
        published = _published_date(published_at)
        if not title or not published:
            if len(excluded) < MAX_EXCLUDED_ROWS:
                excluded.append({"index": index, "title": title[:160] or None, "reason": "MISSING_TITLE_OR_PUBLISHED_AT"})
            continue
        if target_iso is not None and published > target_iso:
            if len(excluded) < MAX_EXCLUDED_ROWS:
                excluded.append({"index": index, "title": title[:160], "published_at": published_at, "reason": "PUBLISHED_AFTER_TARGET_DATE"})
            continue
        url = _valid_http_url(_source_value(raw, "新闻链接", "url"))
        source_name = _text(_source_value(raw, "文章来源", "source", "source_name", "mediaName")) or None
        matched = _company_match(f"{title} {body}", code, name, market)
        binding, scope_label = _scope_for(title, body, matched=matched, market=market)
        item = {
            "id": _stable_hash({"code": code, "market": market, "title": title, "published_at": published_at, "url": url})[:24],
            "material_type": "PUBLIC_NEWS",
            "market": market,
            "code": code,
            "canonical_symbol": _canonical(code, market),
            "name": name or code,
            "title": title[:240],
            "content_excerpt": body[:2000] if body else None,
            "content_is_excerpt": True,
            "content_chars": len(body),
            "published_at": published_at,
            "published_date": published,
            "source_name": source_name,
            "source_url": url,
            "url": url,
            "association": "company" if matched else "industry_background",
            "association_evidence": matched,
            "reading_scope": binding,
            "reading_scope_label": scope_label,
            "source_method": READER_SOURCE_METHOD,
            "source_id": READER_SOURCE_ID,
            "queried_at": queried,
            "collected_at": queried,
            "raw_source_record": {"title": title, "published_at": published_at, "source_name": source_name, "url": url},
        }
        if matched:
            materials.append(item)
        else:
            background.append(item)
    materials = _dedupe(materials)
    background = _dedupe(background)
    materials.sort(key=lambda item: (str(item.get("published_at") or ""), str(item.get("id") or "")), reverse=True)
    background.sort(key=lambda item: (str(item.get("published_at") or ""), str(item.get("id") or "")), reverse=True)
    truncated = len(materials) > MAX_ROWS_PER_CANDIDATE
    materials = materials[:MAX_ROWS_PER_CANDIDATE]
    source_hash_payload = {
        "code": code,
        "market": market,
        "target_date": target_iso,
        "materials": materials,
        "background": background[:MAX_ROWS_PER_CANDIDATE],
        "source_meta": dict(source_meta or {}),
    }
    gaps: list[str] = []
    if not raw_rows:
        gaps.append("PUBLIC_NEWS_EMPTY: 公开个股新闻源未返回记录")
    if raw_rows and not materials:
        gaps.append("COMPANY_MATCH_EMPTY: 返回记录没有标题/正文代码或名称匹配")
    if background:
        gaps.append(f"INDUSTRY_BACKGROUND_RETAINED: {len(background)} 条背景材料单列展示")
    visible_materials = materials + background
    return {
        "schema": READER_SCHEMA,
        "source_id": READER_SOURCE_ID,
        "available": bool(materials or background),
        # Background rows are useful reading context, but they do not prove an
        # exact company join.  Keep that distinction visible in the status.
        "status": "READY" if materials else ("PARTIAL" if background else ("PARTIAL" if raw_rows else "CANNOT_CONFIRM")),
        "market": market,
        "code": code,
        "canonical_symbol": _canonical(code, market),
        "name": name or code,
        "target_date": target_iso,
        "queried_at": queried,
        "collected_at": queried,
        "provider": READER_PROVIDER,
        "source_method": READER_SOURCE_METHOD,
        "source_url": _valid_http_url((source_meta or {}).get("url")),
        "source_body_sha256": (source_meta or {}).get("source_body_sha256"),
        "source_hash": _stable_hash(source_hash_payload),
        "raw_record_count": len(raw_rows),
        "material_count": len(visible_materials),
        "company_record_count": len(materials),
        "background_record_count": len(background),
        "truncated": truncated,
        "materials": materials,
        "company_news": materials,
        "background": background[:MAX_ROWS_PER_CANDIDATE],
        "excluded": excluded,
        "source_gaps": gaps,
    }


def read_public_news(
    code: str,
    *,
    name: str = "",
    market: str = "HK",
    target_date: str | None = None,
    limit: int = MAX_ROWS_PER_CANDIDATE,
    queried_at: str | None = None,
    fetcher: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Fetch one bounded candidate feed; source errors stay on that row."""

    queried = queried_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    if target_date is not None and _target_iso(target_date) is None:
        return _empty_bundle(code, name, market, target_date, queried, "INVALID_DATE", ["INVALID_DATE: 新闻目标日期必须是 YYYY-MM-DD 或 YYYYMMDD"])
    try:
        result = fetcher(code=code, market=market, limit=max(1, min(int(limit), MAX_ROWS_PER_CANDIDATE))) if fetcher else _default_fetch(code, market=market, limit=limit, timeout=REQUEST_TIMEOUT_SECONDS)
        source_meta: Mapping[str, Any] = {}
        if isinstance(result, tuple) and len(result) == 2:
            rows, raw_meta = result
            source_meta = raw_meta if isinstance(raw_meta, Mapping) else {}
        else:
            rows = result
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise ReaderSourceError("PUBLIC_NEWS_FETCHER_RETURNED_INVALID_ROWS")
        return project_public_news(rows, code=code, name=name, market=market, target_date=target_date, queried_at=queried, source_meta=source_meta)
    except Exception as exc:  # noqa: BLE001 — per-stock failures are explicit reader state
        bundle = _empty_bundle(code, name, market, target_date, queried, "ERROR", [f"PUBLIC_NEWS_ERROR: {type(exc).__name__}"])
        bundle["error_type"] = type(exc).__name__
        return bundle


def read_public_news_batch(
    observations: Sequence[Mapping[str, Any]],
    *,
    target_date: str,
    limit: int = MAX_ROWS_PER_CANDIDATE,
    queried_at: str | None = None,
    fetcher: Callable[..., Any] | None = None,
    max_workers: int = MAX_WORKERS,
) -> dict[str, Any]:
    """Read the fixed candidate rows with small bounded concurrency."""

    queried = queried_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: dict[str, dict[str, Any]] = {}
    observation_list = [item for item in observations if isinstance(item, Mapping) and item.get("code")]

    def collect(observation: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        code = str(observation.get("code") or "")
        return code, read_public_news(
            code,
            name=str(observation.get("name") or ""),
            market="HK" if str(observation.get("market") or "HK_CONNECT").upper() in {"HK", "HK_CONNECT"} else "A",
            target_date=target_date,
            limit=limit,
            queried_at=queried,
            fetcher=fetcher,
        )

    with ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), max(1, len(observation_list))))) as executor:
        futures = [executor.submit(collect, item) for item in observation_list]
        for future in as_completed(futures):
            try:
                code, bundle = future.result()
            except Exception as exc:  # pragma: no cover - collect already fail-closes
                continue
            rows[code] = bundle
    for observation in observation_list:
        code = str(observation.get("code") or "")
        if code not in rows:
            rows[code] = _empty_bundle(code, str(observation.get("name") or ""), "HK", target_date, queried, "ERROR", ["PUBLIC_NEWS_WORKER_MISSING"])
    bundles = list(rows.values())
    ready = sum(1 for item in bundles if item.get("status") == "READY")
    partial = sum(1 for item in bundles if item.get("status") == "PARTIAL")
    errors = sum(1 for item in bundles if item.get("status") == "ERROR")
    usable = ready + partial
    if bundles and ready == len(bundles):
        status = "READY"
    elif usable:
        # A readable row together with any partial/error row is an explicit
        # mixed result.  READY is reserved for every requested candidate.
        status = "PARTIAL_WITH_ROWS"
    else:
        status = "CANNOT_CONFIRM"
    return {
        "schema": READER_SCHEMA,
        "source_id": READER_SOURCE_ID,
        "status": status,
        "target_date": _target_iso(target_date),
        "queried_at": queried,
        "requested_candidates": len(observation_list),
        "rows": rows,
        "source_counts": {
            "source_id": READER_SOURCE_ID,
            "source_method": READER_SOURCE_METHOD,
            "requested_candidates": len(observation_list),
            "ready_candidates": ready,
            "partial_candidates": partial,
            "error_candidates": errors,
            "raw_record_count": sum(int(item.get("raw_record_count") or 0) for item in bundles),
            "material_count": sum(int(item.get("material_count") or 0) for item in bundles),
            "truncated_candidates": sum(1 for item in bundles if item.get("truncated") is True),
            "status": status,
            "completeness": "BOUNDED_FIXED_CANDIDATE_PUBLIC_NEWS",
        },
        "coverage": {
            "requested_candidates": len(observation_list),
            "ready_candidates": ready,
            "partial_candidates": partial,
            "error_candidates": errors,
            "material_count": sum(int(item.get("material_count") or 0) for item in bundles),
            "status": status,
            "completeness": "BOUNDED_FIXED_CANDIDATE_PUBLIC_NEWS",
            "full_day_coverage": "NOT_VERIFIED",
            "no_material_is_not_no_candidate": True,
        },
    }


__all__ = [
    "EASTMONEY_SEARCH_URL",
    "MAX_ROWS_PER_CANDIDATE",
    "READER_SCHEMA",
    "READER_SOURCE_ID",
    "READER_SOURCE_METHOD",
    "ReaderSourceError",
    "build_search_url",
    "project_public_news",
    "read_public_news",
    "read_public_news_batch",
]
