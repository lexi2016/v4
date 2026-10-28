"""Fuyao A-share limit-up reason source.

This adapter is deliberately small and read-only.  It turns the bounded
``limit-up-pool`` response into the ``{six_digit_code: reason}`` shape used by
the existing theme reader while keeping enough request/response provenance
for that reader's date-bound cache.

The endpoint does not echo a row-level trading date.  ``date_ms`` is therefore
the only date binding accepted here; the response ``timestamp`` is retained as
ready-time metadata and is never used as the source trade date.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

BASE_URL = "https://fuyao.aicubes.cn"
ENDPOINT = "/api/a-share/special-data/limit-up-pool"
CONTRACT_URL = "https://fuyao.aicubes.cn/docs/api-reference/limit-up-data/"
SCHEMA = "vibe.fuyao.limit_up_reasons.v1"
DEFAULT_PAGE_SIZE = 200
DEFAULT_MAX_PAGES = 100
DEFAULT_TIMEOUT = 15.0
MAX_PAGE_SIZE = 200

_SHANGHAI = timezone(timedelta(hours=8))
_DATE_RE = re.compile(r"^\d{8}$")
_DATE_DASHED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TICKER_RE = re.compile(r"^\d{6}$")
_THSCODE_RE = re.compile(r"^\d{6}\.(?:SZ|SH|BJ)$", re.IGNORECASE)
_DATE_KEYS = {
    "date",
    "tradedate",
    "requestdate",
    "targetdate",
    "datems",
    "requestdatems",
    "targetdatems",
}


class FuyaoError(RuntimeError):
    """Base error for source configuration, transport, and schema failures."""


class FuyaoConfigError(FuyaoError):
    """The source cannot be called with the supplied request configuration."""


class FuyaoTransportError(FuyaoError):
    """The source request did not produce a usable HTTP response."""


class FuyaoSchemaError(FuyaoError):
    """The response is incomplete, inconsistent, or not safely mappable."""


@dataclass(frozen=True)
class FuyaoResult:
    """Complete one-date reason fetch and its source provenance."""

    reasons: dict[str, str]
    metadata: dict[str, Any]


def _target_date(value: str) -> str:
    text = str(value or "").strip()
    if _DATE_RE.fullmatch(text):
        date = text
    elif _DATE_DASHED_RE.fullmatch(text):
        date = text.replace("-", "")
    else:
        raise FuyaoConfigError("target date must be YYYYMMDD")
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError as exc:
        raise FuyaoConfigError("target date is invalid") from exc
    return date


def requested_date_ms(date: str) -> int:
    """Return Shanghai midnight for an exact requested trading date."""

    normalized = _target_date(date)
    instant = datetime.strptime(normalized, "%Y%m%d").replace(tzinfo=_SHANGHAI)
    return int(instant.timestamp() * 1000)


def _as_positive_int(value: Any, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool):
        raise FuyaoSchemaError(f"{field} must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.strip().isdigit():
        result = int(value.strip())
    else:
        raise FuyaoSchemaError(f"{field} must be an integer")
    if result < 0 or (result == 0 and not allow_zero):
        raise FuyaoSchemaError(f"{field} must be positive")
    return result


def _date_from_explicit_value(value: Any) -> str | None:
    """Parse a returned date field without treating ready timestamps as dates."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        text = str(value)
        if len(text) == 8:
            return _target_date(text)
        if len(text) in (10, 13):
            return datetime.fromtimestamp(value / (1000 if len(text) == 13 else 1), _SHANGHAI).strftime("%Y%m%d")
        raise FuyaoSchemaError("returned date field is invalid")
    if isinstance(value, float) and value.is_integer():
        return _date_from_explicit_value(int(value))
    if not isinstance(value, str):
        raise FuyaoSchemaError("returned date field is invalid")
    text = value.strip()
    if _DATE_RE.fullmatch(text) or _DATE_DASHED_RE.fullmatch(text):
        return _target_date(text)
    if text.isdigit() and len(text) in (10, 13):
        return _date_from_explicit_value(int(text))
    if "T" in text or " " in text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_SHANGHAI)
            return parsed.astimezone(_SHANGHAI).strftime("%Y%m%d")
        except ValueError as exc:
            raise FuyaoSchemaError("returned date field is invalid") from exc
    raise FuyaoSchemaError("returned date field is invalid")


def _iter_explicit_dates(value: Any):
    """Yield known date fields, excluding the endpoint's ready timestamp."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z]", "", str(key).lower())
            if normalized_key in _DATE_KEYS and item is not None:
                yield str(key), item
            if isinstance(item, (Mapping, list)):
                yield from _iter_explicit_dates(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_explicit_dates(item)


def _response_bytes(response: Any, payload: Mapping[str, Any]) -> bytes:
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _page_payload(
    payload: Any,
    *,
    requested_page: int,
    page_size: int,
    target_date: str,
) -> tuple[list[Mapping[str, Any]], dict[str, int], bool]:
    if not isinstance(payload, Mapping):
        raise FuyaoSchemaError("response body is not an object")
    if payload.get("code") != 0:
        raise FuyaoSchemaError("API returned a non-zero code")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise FuyaoSchemaError("response data is missing")
    pagination = data.get("pagination")
    items = data.get("item")
    if not isinstance(pagination, Mapping) or not isinstance(items, list):
        raise FuyaoSchemaError("pagination or item is missing")
    total = _as_positive_int(pagination.get("total"), "pagination.total", allow_zero=True)
    pages = _as_positive_int(pagination.get("pages"), "pagination.pages", allow_zero=True)
    returned_size = _as_positive_int(pagination.get("size"), "pagination.size")
    returned_page = _as_positive_int(pagination.get("page"), "pagination.page")
    if returned_size != page_size:
        raise FuyaoSchemaError("pagination.size does not match requested size")
    if returned_page != requested_page:
        raise FuyaoSchemaError("pagination.page does not match requested page")
    expected_pages = math.ceil(total / page_size) if total else 0
    if pages != expected_pages and not (total == 0 and pages == 1):
        raise FuyaoSchemaError("pagination.pages does not match total and size")
    if total == 0:
        if items:
            raise FuyaoSchemaError("empty total returned non-empty items")
    else:
        expected_items = min(page_size, total - ((requested_page - 1) * page_size))
        if expected_items < 0 or len(items) != expected_items:
            raise FuyaoSchemaError("page is truncated or has unexpected row count")
    explicit_date_seen = False
    for key, value in _iter_explicit_dates(payload):
        returned_date = _date_from_explicit_value(value)
        if returned_date != target_date:
            raise FuyaoSchemaError(f"returned {key} does not match requested date")
        explicit_date_seen = True
    normalized_items: list[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise FuyaoSchemaError("item row is not an object")
        normalized_items.append(item)
    return normalized_items, {"total": total, "pages": pages, "size": returned_size, "page": returned_page}, explicit_date_seen


def _reason_row(item: Mapping[str, Any]) -> tuple[str, str]:
    ticker = item.get("ticker")
    thscode = item.get("thscode")
    name = item.get("name")
    reason = item.get("limit_up_reason")
    limit_up_time = item.get("limit_up_time")
    if not isinstance(ticker, str) or not _TICKER_RE.fullmatch(ticker.strip()):
        raise FuyaoSchemaError("ticker is missing or invalid")
    if not isinstance(thscode, str) or not _THSCODE_RE.fullmatch(thscode.strip()):
        raise FuyaoSchemaError("thscode is missing or invalid")
    ticker = ticker.strip()
    thscode = thscode.strip().upper()
    if thscode[:6] != ticker:
        raise FuyaoSchemaError("ticker and thscode do not match")
    if not isinstance(name, str) or not name.strip():
        raise FuyaoSchemaError("name is missing")
    if not isinstance(limit_up_time, str) or not limit_up_time.strip():
        raise FuyaoSchemaError("limit_up_time is missing")
    if not isinstance(reason, str) or not reason.strip() or reason.strip().lower() == "nan":
        raise FuyaoSchemaError("limit_up_reason is missing or empty")
    return ticker, " ".join(reason.strip().split())


def fetch_limit_up_reasons(
    date: str,
    *,
    api_key: str | None = None,
    http_get: Callable[..., Any] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
    timeout: float = DEFAULT_TIMEOUT,
) -> FuyaoResult:
    """Fetch every bounded page for one exact date.

    ``http_get`` is injectable for deterministic fixture tests.  A failed page
    or any duplicate/schema/date mismatch raises before a partial map can be
    returned as complete.
    """

    target_date = _target_date(date)
    key = str(api_key or "").strip()
    if not key:
        raise FuyaoConfigError("FUYAO_API_KEY is not configured")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise FuyaoConfigError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
        raise FuyaoConfigError("max_pages must be positive")
    if timeout <= 0:
        raise FuyaoConfigError("timeout must be positive")
    if not callable(http_get):
        raise FuyaoConfigError("explicit V4 HTTP owner required")
    getter = http_get
    date_ms = requested_date_ms(target_date)
    headers = {"X-api-key": key, "User-Agent": "vibe-astock-fuyao/1"}
    all_reasons: dict[str, str] = {}
    page_hashes: list[str] = []
    response_bytes: list[bytes] = []
    declared: dict[str, int] | None = None
    explicit_date_seen = False
    response_timestamp: Any = None

    for page in range(1, max_pages + 1):
        params = {
            "date_ms": date_ms,
            "page": page,
            "size": page_size,
            "sort_field": "limit_up_time",
            "sort_dir": "desc",
        }
        try:
            response = getter(
                f"{BASE_URL}{ENDPOINT}",
                params=params,
                headers=headers,
                timeout=timeout,
            )
        except requests.Timeout as exc:
            raise FuyaoTransportError("request timed out") from exc
        except requests.RequestException as exc:
            raise FuyaoTransportError(f"request failed: {type(exc).__name__}") from exc
        except Exception as exc:  # injected transports should have the same safe error boundary
            raise FuyaoTransportError(f"request failed: {type(exc).__name__}") from exc
        status = getattr(response, "status_code", None)
        if status != 200:
            raise FuyaoTransportError(f"HTTP status {status}")
        try:
            payload = response.json()
        except Exception as exc:
            raise FuyaoSchemaError("response JSON is invalid") from exc
        items, page_info, explicit = _page_payload(
            payload,
            requested_page=page,
            page_size=page_size,
            target_date=target_date,
        )
        explicit_date_seen = explicit_date_seen or explicit
        if declared is None:
            declared = page_info
        elif any(declared[key] != page_info[key] for key in ("total", "pages", "size")):
            raise FuyaoSchemaError("pagination changed between pages")
        if isinstance(payload.get("data"), Mapping):
            response_timestamp = payload["data"].get("timestamp")
        raw_bytes = _response_bytes(response, payload)
        response_bytes.append(raw_bytes)
        page_hashes.append(hashlib.sha256(raw_bytes).hexdigest())
        for item in items:
            ticker, reason = _reason_row(item)
            if ticker in all_reasons:
                raise FuyaoSchemaError("duplicate ticker across response pages")
            all_reasons[ticker] = reason
        if page_info["pages"] == 0 or page >= page_info["pages"]:
            break
    else:
        raise FuyaoSchemaError("pagination exceeded bounded page limit")

    if declared is None:
        raise FuyaoSchemaError("no response page was fetched")
    if len(all_reasons) != declared["total"]:
        raise FuyaoSchemaError("deduplicated row count does not match pagination.total")
    response_digest = hashlib.sha256(b"".join(response_bytes)).hexdigest()
    metadata: dict[str, Any] = {
        "schema": SCHEMA,
        "provider": "FUYAO",
        "endpoint": f"{BASE_URL}{ENDPOINT}",
        "contract_locator": CONTRACT_URL,
        "request_target_date": target_date,
        "request_date_ms": date_ms,
        "request_params": {
            "date_ms": date_ms,
            "size": page_size,
            "sort_field": "limit_up_time",
            "sort_dir": "desc",
        },
        "date_evidence_basis": "REQUEST_CONTRACT",
        "response_trade_date_echo": False,
        "response_explicit_date_validated": explicit_date_seen,
        "response_timestamp": response_timestamp,
        "source_response_sha256": response_digest,
        "page_response_sha256": page_hashes,
        "pagination": {
            "total": declared["total"],
            "pages": declared["pages"],
            "size": declared["size"],
            "pages_fetched": len(page_hashes),
        },
        "source_row_count": len(all_reasons),
        "deduplicated_ticker_count": len(all_reasons),
        "complete": True,
    }
    return FuyaoResult(reasons=all_reasons, metadata=metadata)


__all__ = [
    "BASE_URL",
    "CONTRACT_URL",
    "DEFAULT_MAX_PAGES",
    "DEFAULT_PAGE_SIZE",
    "ENDPOINT",
    "FuyaoConfigError",
    "FuyaoError",
    "FuyaoResult",
    "FuyaoSchemaError",
    "FuyaoTransportError",
    "SCHEMA",
    "fetch_limit_up_reasons",
    "requested_date_ms",
]
