"""Public HKEX company-announcement provider used by manager research jobs.

The provider follows the public HKEX title-search flow: the official active
stock list supplies the issuer identity and stock id, then the official title
directory is queried for that issuer and exact historical date window.  It
never scans the market and it never accepts a caller supplied remote URL.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from hashlib import sha256
import json
import math
import re
import threading
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener
from .errors import public_error

from .contracts import ContractError, cutoff_at as make_cutoff_at, strict_trade_date
from .pdf_parser import PdfParseError, extract_pdf_facts
from .ports import SourceResponse, SourceTransport


HKEX_HOSTS = frozenset({"www1.hkexnews.hk", "www.hkexnews.hk", "sc.hkexnews.hk"})
EASTMONEY_HK_HOSTS = frozenset({
    "np-anotice-stock.eastmoney.com",
    "np-cnotice-stock.eastmoney.com",
    "pdf.dfcfw.com",
})
ACTIVE_STOCK_LIST_URL = "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json"
TITLE_SEARCH_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml"
SOURCE_PROVIDER_ID = "v4.hkex.official_titlesearch.v1"
_UTC8 = timezone(timedelta(hours=8))
_DATE_TIME_RE = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})\s*$")
_WS_RE = re.compile(r"\s+")
_SUBSTANTIVE_REPORT_TOKENS = (
    "interim results",
    "annual results",
    "final results",
    "interim report",
    "annual report",
    "results announcement",
)
# Bump when extract_pdf_facts' observable output changes so cached parses of
# immutable archived PDFs are recomputed instead of going stale.
PDF_FACTS_CACHE_VERSION = 1


class ProviderError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(body: bytes) -> str:
    return sha256(body).hexdigest()


def _safe_official_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (parsed.scheme == "https" and parsed.hostname in HKEX_HOSTS
                and parsed.port in (None, 443) and parsed.username is None
                and parsed.password is None and not parsed.fragment)
    except (TypeError, ValueError):
        return False


def _safe_eastmoney_hk_url(url: str) -> bool:
    """Allow only the tested Eastmoney HK notice endpoints and attached PDFs."""
    try:
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname not in EASTMONEY_HK_HOSTS
                or parsed.port not in (None, 443) or parsed.username is not None
                or parsed.password is not None or parsed.fragment):
            return False
        if parsed.hostname == "np-anotice-stock.eastmoney.com":
            return parsed.path == "/api/security/ann"
        if parsed.hostname == "np-cnotice-stock.eastmoney.com":
            return parsed.path == "/api/content/ann"
        return bool(re.fullmatch(r"/pdf/H2_AN[A-Z0-9]{8,32}_1\.pdf", parsed.path))
    except (TypeError, ValueError):
        return False


class _HKEXRedirectHandler(HTTPRedirectHandler):
    max_repeats = 1
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _safe_official_url(newurl):
            raise ProviderError("HKEX_REDIRECT_TARGET_REFUSED")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _EastmoneyRedirectHandler(HTTPRedirectHandler):
    max_repeats = 1
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _safe_eastmoney_hk_url(newurl):
            raise ProviderError("EASTMONEY_HK_REDIRECT_TARGET_REFUSED")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _normal_text(value: str) -> str:
    return _WS_RE.sub(" ", value.replace("\xa0", " ")).strip()


def _default_transport(*, max_response_bytes: int = 32 * 1024 * 1024) -> SourceTransport:
    if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or max_response_bytes < 1:
        raise ProviderError("INVALID_RESPONSE_SIZE_BUDGET")
    opener = build_opener(HTTPCookieProcessor(), _HKEXRedirectHandler())

    def request(url: str, *, timeout: float, method: str = "GET", body: bytes | None = None,
                headers: Mapping[str, str] | None = None) -> SourceResponse:
        if not _safe_official_url(url):
            raise ProviderError("refused non-HKEX source URL")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ProviderError("INVALID_TRANSPORT_TIMEOUT")
        request_headers = {
            "User-Agent": "Mozilla/5.0 (research-only; V4 manager research)",
            "Accept": "text/html,application/json,application/pdf;q=0.9,*/*;q=0.8",
        }
        if headers:
            request_headers.update(headers)
        request_obj = Request(url, data=body, headers=request_headers, method=method.upper())
        deadline = time.monotonic() + timeout
        try:
            with opener.open(request_obj, timeout=timeout) as response:
                final_url = response.geturl()
                if not _safe_official_url(final_url):
                    raise ProviderError("refused non-HKEX redirect target")
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                length = response_headers.get("content-length")
                if length is not None and (not str(length).isdigit() or int(length) > max_response_bytes):
                    raise ProviderError("HKEX_RESPONSE_SIZE_BUDGET_EXCEEDED")
                chunks: list[bytes] = []
                total = 0
                read = getattr(response, "read1", response.read)
                while True:
                    if time.monotonic() >= deadline:
                        raise ProviderError("HKEX_RESPONSE_TIME_BUDGET_EXCEEDED")
                    chunk = read(min(64 * 1024, max_response_bytes - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_response_bytes:
                        raise ProviderError("HKEX_RESPONSE_SIZE_BUDGET_EXCEEDED")
                    chunks.append(chunk)
                return SourceResponse(url=url, final_url=final_url, status_code=int(response.status),
                    body=b"".join(chunks), headers=response_headers, retrieved_at=_now())
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(public_error(exc)) from exc
    return request


def _default_eastmoney_hk_transport(*, max_response_bytes: int = 8 * 1024 * 1024) -> SourceTransport:
    """Read the tested Eastmoney HK list/detail and full attached PDF only."""
    if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or max_response_bytes < 1:
        raise ProviderError("INVALID_RESPONSE_SIZE_BUDGET")
    opener = build_opener(_EastmoneyRedirectHandler())

    def request(url: str, *, timeout: float, method: str = "GET", body: bytes | None = None,
                headers: Mapping[str, str] | None = None) -> SourceResponse:
        if not _safe_eastmoney_hk_url(url) or method.upper() != "GET" or body is not None:
            raise ProviderError("EASTMONEY_HK_REQUEST_REFUSED")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ProviderError("INVALID_TRANSPORT_TIMEOUT")
        request_headers = {
            "User-Agent": "Mozilla/5.0 (research-only; V4 manager research)",
            "Accept": "application/json,application/pdf;q=0.9,*/*;q=0.8",
        }
        if headers:
            request_headers.update(headers)
        request_obj = Request(url, headers=request_headers, method="GET")
        deadline = time.monotonic() + timeout
        try:
            with opener.open(request_obj, timeout=timeout) as response:
                final_url = response.geturl()
                if not _safe_eastmoney_hk_url(final_url):
                    raise ProviderError("EASTMONEY_HK_REDIRECT_TARGET_REFUSED")
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                length = response_headers.get("content-length")
                if length is not None and (not str(length).isdigit() or int(length) > max_response_bytes):
                    raise ProviderError("EASTMONEY_HK_RESPONSE_SIZE_BUDGET_EXCEEDED")
                chunks: list[bytes] = []
                total = 0
                read = getattr(response, "read1", response.read)
                while True:
                    if time.monotonic() >= deadline:
                        raise ProviderError("EASTMONEY_HK_RESPONSE_TIME_BUDGET_EXCEEDED")
                    chunk = read(min(64 * 1024, max_response_bytes - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_response_bytes:
                        raise ProviderError("EASTMONEY_HK_RESPONSE_SIZE_BUDGET_EXCEEDED")
                    chunks.append(chunk)
                return SourceResponse(url=url, final_url=final_url, status_code=int(response.status),
                    body=b"".join(chunks), headers=response_headers, retrieved_at=_now())
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(public_error(exc)) from exc
    return request


class _AnnouncementParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self._row: dict[str, str] | None = None
        self._td_class = ""
        self._headline = False
        self._doc_link = False
        self._anchor_href = ""
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key: value or "" for key, value in attrs}
        if tag == "tr":
            self._row = {}
            self._td_class = ""
            return
        if self._row is None:
            return
        if tag == "td":
            self._td_class = attrs_map.get("class", "")
            self._buffer = []
        elif tag == "div" and "headline" in attrs_map.get("class", "").split():
            self._headline = True
            self._buffer = []
        elif tag == "div" and "doc-link" in attrs_map.get("class", "").split():
            self._doc_link = True
        elif tag == "a" and self._doc_link:
            self._anchor_href = attrs_map.get("href", "")
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._row is not None and (self._td_class or self._headline or self._doc_link):
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._row is None:
            return
        text = _normal_text("".join(self._buffer))
        if tag == "a" and self._doc_link:
            if self._anchor_href:
                self._row["document_href"] = self._anchor_href
                self._row["document_title"] = text
            self._anchor_href = ""
            self._buffer = []
        elif tag == "div" and self._headline:
            self._row["headline"] = text
            self._headline = False
            self._buffer = []
        elif tag == "td":
            classes = self._td_class.split()
            if "release-time" in classes:
                self._row["release_time"] = text
            elif "stock-short-code" in classes:
                self._row["stock_code"] = text
            elif "stock-short-name" in classes:
                self._row["stock_name"] = text
            self._td_class = ""
            self._buffer = []
        elif tag == "tr":
            row = self._row
            if row.get("release_time") and row.get("document_href"):
                self.rows.append(row)
            self._row = None
            self._doc_link = False
            self._buffer = []


def parse_title_rows(body: bytes, *, base_url: str = TITLE_SEARCH_URL) -> list[dict[str, Any]]:
    try:
        parser = _AnnouncementParser()
        parser.feed(body.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise ProviderError(f"HKEX title directory HTML parse failed: {type(exc).__name__}") from exc
    rows: list[dict[str, Any]] = []
    for row in parser.rows:
        release_time = _normal_text(row.get("release_time", ""))
        release_time = re.sub(r"^Release Time:\s*", "", release_time, flags=re.IGNORECASE)
        match = _DATE_TIME_RE.match(release_time)
        if not match:
            continue
        day, month, year, hour, minute = (int(item) for item in match.groups())
        try:
            published = datetime(year, month, day, hour, minute, tzinfo=_UTC8)
        except ValueError:
            continue
        href = urljoin(base_url, row["document_href"])
        if not _safe_official_url(href):
            continue
        rows.append(
            {
                "published_at": published.isoformat(timespec="minutes"),
                "release_time": release_time,
                "stock_code": re.sub(r"^Stock Code:\s*", "", _normal_text(row.get("stock_code", "")), flags=re.IGNORECASE),
                "stock_name": re.sub(r"^Stock Short Name:\s*", "", _normal_text(row.get("stock_name", "")), flags=re.IGNORECASE),
                "headline": _normal_text(row.get("headline", "")),
                "document_title": _normal_text(row.get("document_title", "")),
                "url": href,
            }
        )
    return rows


def _candidate_score(row: Mapping[str, Any]) -> tuple[int, str]:
    text = f"{row.get('headline', '')} {row.get('document_title', '')}".lower()
    # Result documents are ranked by document type before publication time.
    # A recent interim report must outrank an older annual report: the latter
    # is readable too, but it is the wrong reporting period for a current
    # historical date. Other substantive notices remain bounded fallbacks.
    title_priority = (
        ("interim results", 400),
        ("annual results", 350),
        ("results announcement", 300),
        ("profit warning", 250),
        ("profit alert", 250),
        ("business update", 200),
        ("acquisition", 190),
        ("disposal", 190),
        ("major transaction", 190),
    )
    excluded = ("monthly return", "date of board meeting", "proxy", "list of directors")
    # A neutral announcement is not a substantive candidate.  We still keep
    # it as the deterministic fallback when no better title exists, where the
    # PDF parser can explicitly return CANNOT_CONFIRM instead of inventing a
    # company fact from the title.
    score = -1
    for token, priority in title_priority:
        if token in text:
            score = max(score, priority)
    if any(token in text for token in excluded):
        score -= 50
    return score, str(row.get("published_at", ""))


def _is_substantive_report(row: Mapping[str, Any]) -> bool:
    text = f"{row.get('headline', '')} {row.get('document_title', '')}".lower()
    return any(token in text for token in _SUBSTANTIVE_REPORT_TOKENS)


class HkexOfficialProvider:
    provider_id = SOURCE_PROVIDER_ID
    # The V4 event-refresh owner may attach the bounded public reader feed
    # after the official event batch.  This opt-in marker keeps fixture
    # providers and offline tests from making an unsolicited network request.
    reader_source_enabled = True

    def __init__(
        self, transport: SourceTransport | None = None, *, timeout: float = 20.0,
        active_stock_ttl_seconds: float = 300.0,
        event_media_transport: Any | None = None,
        eastmoney_transport: SourceTransport | None = None,
        material_store: Any | None = None,
    ):
        self._transport = transport or _default_transport()
        self._timeout = timeout
        if not 0 < active_stock_ttl_seconds <= 3600:
            raise ValueError("active_stock_ttl_seconds must be in (0, 3600]")
        self._active_stock_ttl_seconds = float(active_stock_ttl_seconds)
        self._active_stock_expires_at = 0.0
        self._active_stock_lock = threading.RLock()
        self._active_stock_cache: tuple[dict[str, dict[str, Any]], str, str] | None = None
        # The event lane has its own allowlisted transport and request bound.
        # It is deliberately kept separate from the HKEX PDF transport so an
        # event refresh cannot alter financial-source caching or receipts.
        self._event_media_transport = event_media_transport
        # Eastmoney is a separately labelled HK notice mirror. It is opt-in
        # through the original manager announcement owner and never feeds the
        # HKEX-only official-document lane.
        self._eastmoney_transport = eastmoney_transport or _default_eastmoney_hk_transport()
        # An optional shared material store turns every URL this provider
        # touches into a fetch-once artifact: archived PDFs are immutable,
        # current listings/search pages expire on a short TTL, and the PDF
        # parse is cached by (blob, parser version, title) as well.
        self._material_store = material_store
        self._material_transport: Any | None = None
        if material_store is not None:
            from .material_transport import DEFAULT_DYNAMIC_TTL_SECONDS, MaterialTransport

            self._material_transport = MaterialTransport(
                material_store,
                self._transport,
                namespace="hkex-official",
                ttl_for=lambda url: (
                    None
                    if urlparse(url).path.lower().endswith(".pdf")
                    else DEFAULT_DYNAMIC_TTL_SECONDS
                ),
            )
            self._transport = self._material_transport

    def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        cache_response: bool = True,
    ) -> SourceResponse:
        if not _safe_official_url(url):
            raise ProviderError("refused non-HKEX source URL")
        transport = self._transport
        if not cache_response:
            # Only the original title-search session handshake bypasses GET cache.
            # It still uses the same original cookie transport and URL checks.
            if method != "GET" or not url.startswith(TITLE_SEARCH_URL + "?") or self._material_transport is None:
                raise ProviderError("refused uncached request outside official form handshake")
            transport = self._material_transport._transport
        try:
            response = transport(
                url,
                timeout=self._timeout,
                method=method,
                body=body,
                headers=headers,
            )
            if response.final_url and not _safe_official_url(response.final_url):
                raise ProviderError("refused non-HKEX redirect target")
            return response
        except TypeError:
            # Small test transports often expose only ``(url, timeout=...)``.
            # They are read-only and can still serve GET fixtures.
            if method != "GET" or body is not None:
                raise
            response = transport(url, timeout=self._timeout)
            if response.final_url and not _safe_official_url(response.final_url):
                raise ProviderError("refused non-HKEX redirect target")
            return response

    def _request_eastmoney_hk(self, url: str, *, timeout: float | None = None) -> SourceResponse:
        if not _safe_eastmoney_hk_url(url):
            raise ProviderError("EASTMONEY_HK_REQUEST_REFUSED")
        request_timeout=self._timeout if timeout is None else timeout
        if not math.isfinite(request_timeout) or request_timeout<=0:
            raise ProviderError("EASTMONEY_HK_REQUEST_TIME_BUDGET_EXHAUSTED")
        try:
            response = self._eastmoney_transport(url, timeout=request_timeout, method="GET")
            if not isinstance(response, SourceResponse):
                raise ProviderError("EASTMONEY_HK_TRANSPORT_RESPONSE_INVALID")
            if response.url != url or response.final_url and not _safe_eastmoney_hk_url(response.final_url):
                raise ProviderError("EASTMONEY_HK_REDIRECT_TARGET_REFUSED")
            if not isinstance(response.body, bytes) or len(response.body) > 8 * 1024 * 1024:
                raise ProviderError("EASTMONEY_HK_RESPONSE_SIZE_BUDGET_EXCEEDED")
            return response
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(public_error(exc)) from exc

    def _load_active_stocks(self) -> tuple[dict[str, dict[str, Any]], str, str]:
        with self._active_stock_lock:
            if self._active_stock_cache is not None and time.monotonic() < self._active_stock_expires_at:
                return self._active_stock_cache
            # Expired mapping must not survive a failed refresh. This is a
            # current issuer lookup cache, never proof of historical eligibility.
            self._active_stock_cache = None
            self._active_stock_expires_at = 0.0
            response = self._request(ACTIVE_STOCK_LIST_URL)
            if response.status_code < 200 or response.status_code >= 300:
                raise ProviderError(f"HKEX active stock list HTTP {response.status_code}")
            try:
                payload = json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderError("HKEX active stock list is not JSON") from exc
            if not isinstance(payload, list):
                raise ProviderError("HKEX active stock list is not an array")
            by_code: dict[str, dict[str, Any]] = {}
            for item in payload:
                if not isinstance(item, Mapping):
                    continue
                code = item.get("c")
                stock_id = item.get("i")
                issuer = item.get("n")
                if not isinstance(code, str) or not re.fullmatch(r"\d{5}", code):
                    continue
                if not isinstance(stock_id, (int, str)) or not str(stock_id).isdigit():
                    continue
                if not isinstance(issuer, str) or not issuer.strip():
                    continue
                by_code[code] = {
                    "stock_id": str(stock_id),
                    "issuer": _normal_text(issuer),
                    "mapping_code": code,
                }
            if not by_code:
                raise ProviderError("HKEX active stock list contained no issuer rows")
            self._active_stock_cache = (by_code, _digest(response.body), response.retrieved_at)
            self._active_stock_expires_at = time.monotonic() + self._active_stock_ttl_seconds
            return self._active_stock_cache

    def collect(
        self,
        *,
        target_trade_date: str,
        cutoff_at: str,
        observation: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        target = strict_trade_date(target_trade_date)
        if cutoff_at != make_cutoff_at(target):
            raise ContractError("provider cutoff_at does not match target trade date")
        code = observation.get("code")
        if not isinstance(code, str) or not re.fullmatch(r"HK\.\d{5}", code):
            raise ContractError("provider observation code must be HK.#####")
        code_number = code.split(".", 1)[1]
        try:
            mapping, mapping_sha, mapping_retrieved_at = self._load_active_stocks()
        except ProviderError as exc:
            return self._failure(code, target, "ISSUER_MAPPING_UNAVAILABLE", str(exc))
        issuer_info = mapping.get(code_number)
        if issuer_info is None:
            return self._failure(code, target, "ISSUER_NOT_IN_OFFICIAL_ACTIVE_LIST", "code not present in HKEX active stock list")

        target_day = datetime.strptime(target, "%Y%m%d").date()
        from_day = target_day - timedelta(days=370)
        query = urlencode(
            {
                "lang": "EN",
                "category": "0",
                "market": "SEHK",
                "searchType": "0",
                "documentType": "-1",
                "t1code": "-2",
                "t2Gcode": "-2",
                "t2code": "-2",
                "stockId": issuer_info["stock_id"],
                "from": from_day.strftime("%Y%m%d"),
                "to": target,
                "title": "",
            }
        )
        directory_url = f"{TITLE_SEARCH_URL}?{query}"
        try:
            # The form is POSTed by the public HKEX page.  The default
            # transport retains its session cookie between mapping and search.
            self._request(directory_url)
            form_body = query.encode("ascii")
            response = self._request(
                TITLE_SEARCH_URL,
                method="POST",
                body=form_body,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": directory_url},
            )
        except Exception as exc:
            return self._failure(code, target, "DIRECTORY_REQUEST_FAILED", str(exc), issuer_info, mapping_sha, mapping_retrieved_at, directory_url)
        if response.status_code < 200 or response.status_code >= 300:
            return self._failure(code, target, "DIRECTORY_HTTP_ERROR", f"HTTP {response.status_code}", issuer_info, mapping_sha, mapping_retrieved_at, directory_url, response=response)
        try:
            rows = parse_title_rows(response.body)
        except ProviderError as exc:
            return self._failure(code, target, "DIRECTORY_PARSE_FAILED", str(exc), issuer_info, mapping_sha, mapping_retrieved_at, directory_url, response=response)
        cutoff_dt = datetime.fromisoformat(cutoff_at)
        eligible = [
            row
            for row in rows
            if row.get("stock_code") == code_number
            and datetime.fromisoformat(str(row["published_at"])) <= cutoff_dt
            and str(row["published_at"])[:10].replace("-", "") <= target
        ]
        if not eligible:
            return self._failure(code, target, "NO_QUALIFYING_ANNOUNCEMENT", "no official announcement at or before the 09:40 cutoff", issuer_info, mapping_sha, mapping_retrieved_at, directory_url, response=response, row_count=len(rows))
        # Bind a financial research request to the newest effective report.
        # If that report is scanned or otherwise unparseable, fail closed with
        # its own source receipt.  Silently selecting an older annual report
        # would change the reporting period while still looking READY.
        report_candidates = [row for row in eligible if _is_substantive_report(row)]
        if report_candidates:
            latest_report = max(
                report_candidates,
                key=lambda item: (str(item.get("published_at", "")), str(item.get("url", ""))),
            )
            candidates = [latest_report]
        else:
            # For issuers without a substantive report in the window, retain a
            # small same-issuer event fallback (dividend/EGM/business update).
            candidates = sorted(
                eligible,
                key=lambda item: (_candidate_score(item)[0], str(item.get("published_at", ""))),
                reverse=True,
            )[:6]
        selected: Mapping[str, Any] | None = None
        document_response: SourceResponse | None = None
        facts: list[dict[str, Any]] = []
        parsed_pages: list[dict[str, Any]] = []
        last_failure: str | None = None
        # A directory often places a scanned or metadata-only notice ahead of
        # a readable interim/dividend filing.  Try a small bounded set of the
        # same issuer's already-filtered official rows, then keep the exact
        # readable row that supplied the facts.  This does not scan symbols or
        # accept a caller URL.
        for candidate in candidates[:6]:
            document_url = str(candidate["url"])
            try:
                candidate_response = self._request(document_url)
            except Exception as exc:
                last_failure = f"{type(exc).__name__}: {exc}"
                continue
            if candidate_response.status_code < 200 or candidate_response.status_code >= 300:
                last_failure = f"HTTP {candidate_response.status_code}"
                continue
            if document_response is None:
                selected = candidate
                document_response = candidate_response
            try:
                title = str(candidate.get("document_title", ""))
                material = None
                if self._material_transport is not None:
                    # The response above was just served by the same store, so
                    # this is a cache read that adds no network request; the
                    # parsed facts are then reused by later refreshes of the
                    # same immutable document.
                    material = self._material_transport.material(document_url, timeout=self._timeout)
                if material is not None:
                    candidate_facts, candidate_pages = self._material_transport.parsed(
                        material,
                        parser_id="hkex-pdf-facts",
                        parser_version=PDF_FACTS_CACHE_VERSION,
                        params={"title": title},
                        parse_fn=lambda body: extract_pdf_facts(body, title=title),
                    )
                else:
                    candidate_facts, candidate_pages = extract_pdf_facts(
                        candidate_response.body,
                        title=title,
                    )
            except PdfParseError as exc:
                last_failure = str(exc)
                continue
            if candidate_facts:
                selected = candidate
                document_response = candidate_response
                facts = candidate_facts
                parsed_pages = candidate_pages
                break
            # Preserve a retrieved official response for a useful
            # CANNOT_CONFIRM receipt when no candidate has readable facts.
            if not parsed_pages:
                parsed_pages = candidate_pages
        if selected is None or document_response is None:
            selected = candidates[0]
            return self._failure(
                code,
                target,
                "DOCUMENT_REQUEST_FAILED",
                last_failure or "no official document response",
                issuer_info,
                mapping_sha,
                mapping_retrieved_at,
                directory_url,
                response=response,
                selected=selected,
            )
        document_url = str(selected["url"])
        locators = [f"PDF page {page['page']}" for page in parsed_pages]
        source = {
            "source_kind": "HKEX_OFFICIAL_ISSUER_ANNOUNCEMENT",
            "provider_id": self.provider_id,
            "issuer_code": code,
            "issuer": issuer_info["issuer"],
            "published_at": selected["published_at"],
            "retrieved_at": document_response.retrieved_at,
            "url": document_url,
            "sha256": _digest(document_response.body),
            "bytes": len(document_response.body),
            "directory_url": directory_url,
            "directory_sha256": _digest(response.body),
            "issuer_mapping_url": ACTIVE_STOCK_LIST_URL,
            "issuer_mapping_sha256": mapping_sha,
            "issuer_mapping_retrieved_at": mapping_retrieved_at,
            "matching_basis": f"HKEX active stock list c={code_number}, i={issuer_info['stock_id']}; title directory stock code={selected.get('stock_code')}",
            "publication_time_evidence": "HKEX official title directory release-time row",
            "document_title": selected.get("document_title", ""),
            "headline": selected.get("headline", ""),
            "text_locators": locators[:12],
            "pdf_parser": "pypdf",
            "pdf_parser_version": "6.10.0",
            "pdf_page_count": len(parsed_pages),
            "parse_status": "STRUCTURED_FACTS" if facts else "NO_STRUCTURED_FACTS",
            "report_selection": "LATEST_EFFECTIVE_REPORT" if report_candidates else "BOUNDED_EVENT_FALLBACK",
        }
        if not facts:
            return {
                "status": "CANNOT_CONFIRM",
                "reason": "PDF_NO_STRUCTURED_FACTS",
                "failure_detail": "official document was retrieved and parsed, but no generic structured facts were established; title alone is not complete research",
                "issuer": issuer_info["issuer"],
                "source": source,
                "facts": [],
            }
        return {
            "status": "READY",
            "reason": "OFFICIAL_PDF_FACTS_EXTRACTED",
            "issuer": issuer_info["issuer"],
            "source": source,
            "facts": facts,
        }

    def collect_announcement_batch(self, *, context, issuers, pending_documents=(),
                                   max_issuers=3, max_documents=4, budget=None,
                                   reusable_documents=None):
        """Original official transport/store, bounded native-master scope; no Stage."""
        from .announcement_source import collect_batch
        return collect_batch(self, context=context, issuers=issuers,
                             pending_documents=pending_documents, max_issuers=max_issuers,
                             max_documents=max_documents, budget=budget,
                             reusable_documents=reusable_documents)

    def collect_eastmoney_hk_batch(self, *, context, issuers, max_issuers=3,
                                  max_documents=4, budget=None):
        """Capture a bounded Eastmoney HK notice batch through this same owner/provider."""
        from .announcement_source import collect_eastmoney_hk_batch
        return collect_eastmoney_hk_batch(self, context=context, issuers=issuers,
            max_issuers=max_issuers, max_documents=max_documents, budget=budget)

    def collect_events(
        self,
        *,
        target_trade_date: str,
        cutoff_at: str,
        observations: Sequence[Mapping[str, Any]],
        previous_rows: Mapping[str, Mapping[str, Any]] | None = None,
        current_event_as_of: str | None = None,
    ) -> Mapping[str, Any]:
        """Collect independent catalyst evidence without reading financial PDFs.

        The media directory is fetched once and joined to the exact stage
        rows.  HKEX event checks use the existing same-issuer title directory
        and exclude report/monthly-return rows.  Neither branch calls
        ``extract_pdf_facts`` or mutates the financial source result.
        """

        from .event_source import (
            BoundedMediaTransport,
            collect_hkex_event_directory,
            discover_iccsz_events,
            merge_event_batches,
        )

        media_transport = self._event_media_transport
        if media_transport is None:
            if self._material_store is not None:
                from .event_source import _default_media_transport
                from .material_transport import DEFAULT_DYNAMIC_TTL_SECONDS, MaterialTransport

                media_transport = BoundedMediaTransport(
                    transport=MaterialTransport(
                        self._material_store,
                        _default_media_transport(),
                        namespace="manager-media",
                        ttl_seconds=DEFAULT_DYNAMIC_TTL_SECONDS,
                    )
                )
            else:
                media_transport = BoundedMediaTransport()
        media_batch = discover_iccsz_events(
            target_trade_date=target_trade_date,
            cutoff_at=cutoff_at,
            observations=observations,
            transport=media_transport,
            previous_rows=previous_rows,
            current_event_as_of=current_event_as_of,
        )
        hkex_batch = collect_hkex_event_directory(
            self,
            target_trade_date=target_trade_date,
            cutoff_at=cutoff_at,
            observations=observations,
            previous_rows=previous_rows,
            current_event_as_of=current_event_as_of,
        )
        return merge_event_batches(
            target_trade_date=target_trade_date,
            cutoff_at=cutoff_at,
            observations=observations,
            batches=(media_batch, hkex_batch),
            previous_rows=previous_rows,
            current_event_as_of=current_event_as_of,
        )

    @staticmethod
    def _failure(
        code: str,
        target: str,
        reason: str,
        detail: str,
        issuer_info: Mapping[str, Any] | None = None,
        mapping_sha: str | None = None,
        mapping_retrieved_at: str | None = None,
        directory_url: str | None = None,
        *,
        response: SourceResponse | None = None,
        selected: Mapping[str, Any] | None = None,
        document_response: SourceResponse | None = None,
        row_count: int | None = None,
    ) -> dict[str, Any]:
        source: dict[str, Any] | None = None
        if issuer_info is not None:
            source = {
                "source_kind": "HKEX_OFFICIAL_ISSUER_ANNOUNCEMENT",
                "provider_id": SOURCE_PROVIDER_ID,
                "issuer_code": code,
                "issuer": issuer_info.get("issuer"),
                "issuer_mapping_url": ACTIVE_STOCK_LIST_URL,
                "issuer_mapping_sha256": mapping_sha,
                "issuer_mapping_retrieved_at": mapping_retrieved_at,
                "directory_url": directory_url,
                # These fields describe the evidence boundary even when the
                # directory has no qualifying row.  The UI may show this
                # partial receipt alongside CANNOT_CONFIRM, while READY
                # rows still require a document URL and digest below.
                "matching_basis": f"HKEX active stock list code={code}",
                "publication_time_evidence": "HKEX official title directory was queried; no qualifying document was confirmed",
            }
        if response is not None and source is not None:
            source["directory_retrieved_at"] = response.retrieved_at
            source["directory_sha256"] = _digest(response.body)
            source["directory_http_status"] = response.status_code
        if selected is not None and source is not None:
            source.update(
                {
                    "published_at": selected.get("published_at"),
                    "url": selected.get("url"),
                    "document_title": selected.get("document_title", ""),
                    "headline": selected.get("headline", ""),
                }
            )
        if document_response is not None and source is not None:
            source.update(
                {
                    "retrieved_at": document_response.retrieved_at,
                    "sha256": _digest(document_response.body),
                    "bytes": len(document_response.body),
                    "document_http_status": document_response.status_code,
                }
            )
        return {
            "status": "CANNOT_CONFIRM",
            "reason": reason,
            "failure_detail": detail,
            "issuer": issuer_info.get("issuer") if issuer_info else None,
            "source": source,
            "facts": [],
            "row_count": row_count,
        }
