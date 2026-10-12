#!/usr/bin/env python3
"""Bounded full-body capture for an exact owner-readback announcement catalog.

This is a parameterized migration of the accepted body-batch logic. It uses the
existing Eastmoney provider and shared MaterialStore, creates source-bound body
artifacts, and makes no semantic or point-in-time judgment.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import threading
import time
from typing import Any, Mapping
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

APP_ROOT = Path(__file__).resolve().parents[1]
WORKERS = 3
MAX_SECONDS = 3600.0
MAX_NETWORK_REQUESTS = 2000
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
REQUEST_INTERVAL_SECONDS = 0.35
ARTICLE_SHARD_SIZE = 20
MAX_EXTENDED_CONTENT_PAGES = 150
MAX_EXTENDED_BODY_CHARACTERS = 1_000_000
APPROVED_CANARY_TARGET_DATE = "20261008"
APPROVED_CANARY_PUBLICATION_DATE = "2026-10-07"
APPROVED_CANARY_ARTICLE = "AN202610071830178357"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def atomic_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json_bytes(value)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)
    return digest(raw)


def read_json(path: str | Path) -> Any:
    """Accept CLI string paths and internal Path values at one boundary."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def imports() -> dict[str, Any]:
    import sys
    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))
    from v4.manager_research.announcement_catalog import date_scoped_url, _source_stock_identity
    from v4.manager_research.announcement_source import (
        MAX_EASTMONEY_BODY_CHARACTERS,
        MAX_EASTMONEY_CONTENT_PAGES,
        MAX_EASTMONEY_RESPONSE_BYTES,
        capture,
        capture_eastmoney,
        eastmoney_content_url,
        read_response,
        read_eastmoney_response,
        safe_reason,
    )
    from v4.manager_research.hkex_provider import (
        HkexOfficialProvider, _safe_eastmoney_hk_url, _safe_official_url,
    )
    from v4.manager_research.materials import MaterialStore
    from v4.manager_research.pdf_parser import extract_pdf_pages
    from v4.manager_research.workspace_projection import canonical_symbol
    return locals()


def _body_security_match(api: Mapping[str, Any], source_issuers: list[Mapping[str, Any]],
                         detail: Mapping[str, Any]) -> list[str]:
    securities = detail.get("security")
    if not isinstance(securities, list):
        return []
    observed: set[str] = set()
    for item in securities:
        if not isinstance(item, Mapping) or str(item.get("market_uni", "")) != "116":
            continue
        raw_stock = str(item.get("stock", "")).strip().upper()
        if raw_stock:
            observed.add(api["canonical_symbol"](raw_stock) or raw_stock)
    matched: list[str] = []
    for issuer in source_issuers:
        code = issuer.get("code")
        raw_key = str(issuer.get("source_stock_code") or "").strip().upper()
        identity = api["_source_stock_identity"](raw_key)
        if identity is None or identity != (code, raw_key):
            raise ValueError("BODY_SOURCE_ISSUER_IDENTITY_INVALID")
        canonical = api["canonical_symbol"](raw_key) or raw_key
        if isinstance(code, str) and (code in observed or canonical in observed or raw_key in observed):
            matched.append(code)
    return sorted(set(matched))


class SharedCaptureGate:
    """A serialized fetch gate with aggregate time/request/byte limits.

    Three workers validate and write independently, but physical requests pass
    through one lock so cumulative response bytes cannot race past the budget.
    """
    def __init__(self, *, seconds: float, max_requests: int, max_bytes: int, interval: float):
        self.seconds = seconds
        self.max_requests = max_requests
        self.max_response_bytes = max_bytes
        self.interval = interval
        self.started = time.monotonic()
        self.requests = 0
        self.response_bytes = 0
        self._last: float | None = None
        self._lock = threading.RLock()
        self._owner: int | None = None
        self._reserved_bytes = 0

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started)

    def check(self) -> None:
        if self.elapsed_seconds >= self.seconds:
            raise RuntimeError("BODY_BATCH_TIME_BUDGET_EXHAUSTED")

    def before_request(self) -> None:
        self._lock.acquire()
        owner = threading.get_ident()
        try:
            self.check()
            if self.requests >= self.max_requests:
                raise RuntimeError("BODY_BATCH_REQUEST_BUDGET_EXHAUSTED")
            if self.response_bytes + self._reserved_bytes + self.max_response_bytes > self.max_response_bytes_total:
                raise RuntimeError("BODY_BATCH_RESPONSE_BYTE_BUDGET_EXHAUSTED")
            if self._last is not None:
                wait = max(0.0, self.interval - (time.monotonic() - self._last))
                if wait:
                    time.sleep(wait)
            self.check()
            self.requests += 1
            self._last = time.monotonic()
            self._owner = owner
            self._reserved_bytes = self.max_response_bytes
        except Exception:
            self._lock.release()
            raise

    @property
    def max_response_bytes_total(self) -> int:
        # Assigned from the constructor's total budget, separate from per-response cap.
        return getattr(self, "_max_response_bytes_total", self.max_response_bytes)

    def set_response_limits(self, *, per_response: int, total: int) -> None:
        self.max_response_bytes = per_response
        self._max_response_bytes_total = total

    def record_response_bytes(self, size: int) -> None:
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("BODY_BATCH_RESPONSE_SIZE_INVALID")
        owner = threading.get_ident()
        with self._lock:
            self.check()
            if self._owner == owner:
                self._reserved_bytes = 0
            if self.response_bytes + size > self.max_response_bytes_total:
                raise RuntimeError("BODY_BATCH_RESPONSE_BYTE_BUDGET_EXHAUSTED")
            self.response_bytes += size

    def end_request(self) -> None:
        if self._owner == threading.get_ident():
            self._owner = None
            self._reserved_bytes = 0
            self._lock.release()


def _catalog_product(catalog_read: Mapping[str, Any]) -> Mapping[str, Any]:
    value = catalog_read.get("catalog") if isinstance(catalog_read.get("catalog"), Mapping) else catalog_read
    if not isinstance(value, Mapping):
        raise ValueError("SAVED_CATALOG_PRODUCT_MISSING")
    return value


def _validate_catalog(api: Mapping[str, Any], catalog_read: Mapping[str, Any], store: Any,
                      target_trade_date: str, publication_date: str) -> list[dict[str, Any]]:
    catalog = _catalog_product(catalog_read)
    if (catalog_read.get("readback_status") != "VERIFIED"
            or catalog_read.get("target_trade_date") != target_trade_date
            or catalog_read.get("publication_date") != publication_date
            or not re.fullmatch(r"[0-9a-f]{32}", str(catalog.get("run_id", "")))
            or catalog.get("target_trade_date") != target_trade_date
            or catalog.get("publication_date") != publication_date
            or catalog.get("source_scope") != "EASTMONEY_HK_DATE_CATALOG"
            or catalog.get("status") != "COMPLETE"
            or catalog.get("connect_eligibility_status") != "NOT_ASSESSED"
            or catalog.get("RESEARCH_ONLY") is not True
            or catalog.get("production_allowed") is not False
            or catalog.get("orders_sent") is not False
            or catalog.get("buy_gate_updated") is not False):
        raise ValueError("SAVED_CATALOG_BINDING_OR_SAFETY_MISMATCH")
    if not re.fullmatch(r"[0-9a-f]{64}", str(catalog.get("sha256", ""))):
        raise ValueError("SAVED_CATALOG_PRODUCT_SHA_MISSING")
    rows = catalog.get("manager_consumer_rows")
    pages = catalog.get("page_receipts")
    if (not isinstance(rows, list) or not rows
            or len(rows) != catalog.get("manager_consumer_row_count")
            or not isinstance(pages, list) or not pages
            or len(pages) != catalog.get("captured_page_count")):
        raise ValueError("SAVED_CATALOG_ROW_OR_PAGE_COUNT_MISMATCH")
    page_map: dict[int, Mapping[str, Any]] = {}
    expected_pages = catalog.get("expected_data_page_count")
    terminal_page = catalog.get("expected_terminal_page_index")
    if (type(expected_pages) is not int or expected_pages < 1
            or type(terminal_page) is not int or terminal_page != expected_pages + 1
            or catalog.get("terminal_empty_seen") is not True
            or catalog.get("captured_row_count") != catalog.get("total_hits")):
        raise ValueError("SAVED_CATALOG_COMPLETENESS_MISMATCH")
    for receipt in pages:
        page_index = receipt.get("page_index")
        if type(page_index) is not int or receipt.get("capture_status") != "PASS":
            raise ValueError("SAVED_CATALOG_PAGE_RECEIPT_INVALID")
        ref = receipt.get("source_ref")
        if not isinstance(ref, Mapping):
            raise ValueError("SAVED_CATALOG_PAGE_SOURCE_REF_MISSING")
        expected_url = api["date_scoped_url"](publication_date, page_index)
        if (receipt.get("requested_url") != expected_url
                or (ref.get("request") or {}).get("url") != expected_url
                or ref.get("http_status") != 200):
            raise ValueError("SAVED_CATALOG_PAGE_DATE_OR_URL_MISMATCH")
        raw = api["read_eastmoney_response"](store, ref)
        if digest(raw) != receipt.get("raw_body_sha256"):
            raise ValueError("SAVED_CATALOG_LISTING_BODY_SHA_MISMATCH")
        payload = json.loads(raw.decode("utf-8"))
        data = payload.get("data") if isinstance(payload, Mapping) else None
        source_list = data.get("list") if isinstance(data, Mapping) else None
        if not isinstance(source_list, list) or len(source_list) != receipt.get("row_count"):
            raise ValueError("SAVED_CATALOG_LISTING_ROWS_INVALID")
        page_map[page_index] = {"raw_rows": source_list, "receipt": receipt}
    if sorted(page_map) != list(range(1, terminal_page + 1)):
        raise ValueError("SAVED_CATALOG_PAGE_SET_OR_TOTAL_MISMATCH")
    seen: set[str] = set()
    for row in rows:
        art_code = row.get("art_code")
        page_index = row.get("page_index")
        if (not isinstance(art_code, str) or re.fullmatch(r"AN[A-Z0-9]{8,32}", art_code) is None
                or art_code in seen or row.get("notice_date") is None
                or str(row.get("notice_date"))[:10] != publication_date):
            raise ValueError("SAVED_CATALOG_ARTICLE_ID_OR_DATE_INVALID")
        seen.add(art_code)
        page = page_map.get(page_index)
        if not page:
            raise ValueError("SAVED_CATALOG_ARTICLE_PAGE_MISSING")
        candidates = [source_row for source_row in page["raw_rows"]
                      if isinstance(source_row, Mapping) and source_row.get("art_code") == art_code]
        if len(candidates) != 1 or candidates[0] != row.get("raw_row"):
            raise ValueError("SAVED_CATALOG_ARTICLE_NOT_BOUND_TO_LISTING_PAGE")
        raw_codes = row.get("source_issuer_codes")
        if not isinstance(raw_codes, list) or not raw_codes:
            raise ValueError("SAVED_CATALOG_SOURCE_IDENTITY_MISSING")
        for identity in raw_codes:
            raw_code = identity.get("source_stock_code") if isinstance(identity, Mapping) else None
            parsed_identity = api["_source_stock_identity"](raw_code)
            if (not isinstance(identity, Mapping) or identity.get("market_code") != "116"
                    or identity.get("ann_type") != "H"
                    or not isinstance(raw_code, str)
                    or parsed_identity is None
                    or parsed_identity != (identity.get("code"), raw_code)):
                raise ValueError("SAVED_CATALOG_SOURCE_IDENTITY_INVALID")
    if len(seen) != len(rows):
        raise ValueError("SAVED_CATALOG_ARTICLE_SET_INCOMPLETE")
    return rows


def _source_ref_hashes(ref: Mapping[str, Any]) -> bool:
    return all(isinstance(ref.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", ref[key])
               for key in ("blob_sha256", "body_sha256"))


def _capture_url(api: Mapping[str, Any], store: Any, provider: Any, gate: SharedCaptureGate,
                 url: str, *, art_code: str, page_index: int | str, kind: str,
                 out_root: Path) -> tuple[dict[str, Any], bytes | None]:
    url_key = digest(url.encode("utf-8"))
    attempt_path = out_root / "attempts" / f"{url_key}.json"
    receipt_path = out_root / "receipts" / f"{url_key}.json"
    if receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt.get("request_url") != url:
            raise ValueError("BODY_BATCH_URL_RECEIPT_BINDING_MISMATCH")
        ref = receipt.get("source_ref")
        if receipt.get("status") != "CAPTURED" or not isinstance(ref, Mapping) or not _source_ref_hashes(ref):
            return receipt, None
        raw = api["read_eastmoney_response"](store, ref)
        if digest(raw) != receipt.get("raw_body_sha256"):
            raise ValueError("BODY_BATCH_CACHED_RECEIPT_RAW_SHA_MISMATCH")
        return receipt, raw
    if attempt_path.exists():
        receipt = {"schema": "v4.manager_research.body_capture_receipt.v1", "request_url": url,
                   "art_code": art_code, "page_index": page_index, "kind": kind,
                   "status": "ATTEMPT_INDETERMINATE_NO_RETRY",
                   "error_code": "PRIOR_ATTEMPT_MARKER_WITHOUT_TERMINAL_RECEIPT", "terminal_at": utc_now()}
        atomic_json(receipt_path, receipt)
        return receipt, None
    atomic_json(attempt_path, {"schema": "v4.manager_research.body_capture_attempt.v1", "request_url": url,
        "art_code": art_code, "page_index": page_index, "kind": kind, "started_at": utc_now(),
        "one_attempt_only": True, "provider_timeout_seconds": getattr(provider, "_timeout", None)})
    receipt: dict[str, Any] = {"schema": "v4.manager_research.body_capture_receipt.v1", "request_url": url,
        "art_code": art_code, "page_index": page_index, "kind": kind, "attempt_path": str(attempt_path)}
    try:
        ref = api["capture_eastmoney"](provider, url, budget=gate, force=False)
        raw = api["read_eastmoney_response"](store, ref)
        gate.record_response_bytes(len(raw))
        if ref.get("http_status") != 200 or not _source_ref_hashes(ref):
            raise ValueError("BODY_BATCH_SOURCE_HTTP_OR_HASH_INVALID")
        receipt.update(status="CAPTURED", source_ref=ref, raw_body_sha256=digest(raw),
            response_bytes=len(raw), retrieved_at=ref.get("retrieved_at"), from_cache=ref.get("from_cache"),
            terminal_at=utc_now())
        return receipt, raw
    except Exception as exc:
        receipt.update(status="CAPTURE_FAILED", error_code=api["safe_reason"](exc, "BODY_CAPTURE_FAILED"),
                       terminal_at=utc_now())
        return receipt, None
    finally:
        gate.end_request()
        # Written by caller after identity metadata has been attached.
        if not receipt_path.exists():
            atomic_json(receipt_path, receipt)


def _notice_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^\s*(\d{4}-\d{2}-\d{2})", value)
    return match.group(1) if match else None


def _content_detail(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, Mapping) or value.get("success") != 1 or not isinstance(value.get("data"), Mapping):
        raise ValueError("BODY_CONTENT_RESPONSE_INVALID")
    return dict(value["data"])


def _valid_pdf_url(api: Mapping[str, Any], url: Any, art_code: str) -> bool:
    if not isinstance(url, str) or not api["_safe_eastmoney_hk_url"](url):
        return False
    parsed = urlsplit(url)
    expected = f"AN{art_code[2:]}_1.pdf"
    return expected in parsed.path


def _capture_pdf_fallback(api: Mapping[str, Any], store: Any, provider: Any, gate: SharedCaptureGate,
                          *, detail: Mapping[str, Any], row: Mapping[str, Any], out_root: Path) -> dict[str, Any]:
    art_code = str(row["art_code"])
    url = detail.get("attach_url_web")
    if not _valid_pdf_url(api, url, art_code):
        raise ValueError("BODY_PDF_ATTACHMENT_URL_MISMATCH")
    receipt, raw = _capture_url(api, store, provider, gate, url, art_code=art_code,
        page_index="pdf", kind="pdf", out_root=out_root)
    if receipt.get("status") != "CAPTURED" or raw is None or not raw.startswith(b"%PDF"):
        raise ValueError("BODY_PDF_BYTES_UNAVAILABLE_OR_INVALID")
    if len(raw) > 8_000_000:
        raise ValueError("BODY_PDF_BYTE_LIMIT_EXCEEDED")
    pages = api["extract_pdf_pages"](raw, max_bytes=8_000_000, max_pages=40,
        max_text_characters=240_000, timeout_seconds=10)
    receipt["pdf_metadata"] = {"page_count": len(pages), "extracted_text_characters": sum(len(str(p.get("text", ""))) for p in pages),
        "extraction_status": "UNVERIFIED_ENCODING"}
    atomic_json(out_root / "receipts" / f"{digest(url.encode('utf-8'))}.json", receipt)
    return {"status": "PDF_CAPTURED_TEXT_UNVERIFIED_ENCODING", "request_url": url,
        "source_ref": receipt["source_ref"], "raw_body_sha256": digest(raw),
        "pages": pages, "text_characters": sum(len(str(p.get("text", ""))) for p in pages)}


def _capture_article(api: Mapping[str, Any], store: Any, provider: Any, gate: SharedCaptureGate,
                     row: Mapping[str, Any], out_root: Path,
                     target_trade_date: str, publication_date: str) -> dict[str, Any]:
    art_code = row["art_code"]
    attempt_path = out_root / "article_attempts" / f"{art_code}.json"
    receipt_path = out_root / "article_receipts" / f"{art_code}.json"
    body_path = out_root / "bodies" / f"{art_code}.json"
    if receipt_path.exists():
        previous = read_json(receipt_path)
        if (previous.get("art_code") != art_code
                or previous.get("target_trade_date") != target_trade_date
                or previous.get("publication_date") != publication_date
                or previous.get("listing_raw_body_sha256") != row.get("raw_body_sha256")):
            raise ValueError("BODY_BATCH_PRIOR_ARTICLE_RECEIPT_IDENTITY_MISMATCH")
        return previous
    if attempt_path.exists():
        result = {"art_code": art_code, "status": "ATTEMPT_INDETERMINATE_NO_RETRY",
                  "error_code": "ARTICLE_ATTEMPT_MARKER_WITHOUT_TERMINAL_RECEIPT", "terminal_at": utc_now()}
        atomic_json(receipt_path, result)
        return result
    atomic_json(attempt_path, {"art_code": art_code, "started_at": utc_now(), "one_attempt_only": True})
    result: dict[str, Any] = {"schema": "v4.manager_research.announcement_body_article_receipt.v1",
        "art_code": art_code, "target_trade_date": target_trade_date, "publication_date": publication_date,
        "listing_source_ref": row.get("source_ref"), "listing_raw_body_sha256": row.get("raw_body_sha256"),
        "source_issuer_codes": row.get("source_issuer_codes"), "status": "BODY_CAPTURE_FAILED",
        "semantic_status": "NOT_REVIEWED", "started_at": utc_now()}
    pages: list[dict[str, Any]] = []
    try:
        issuers = row.get("source_issuer_codes")
        if not isinstance(issuers, list) or not issuers:
            raise ValueError("BODY_SOURCE_ISSUER_IDENTITY_MISSING")
        expected_title = str(row.get("title") or "").strip()
        if not expected_title:
            raise ValueError("BODY_LISTING_TITLE_MISSING")
        expected_total: int | None = None
        text_characters = 0
        first_detail: Mapping[str, Any] | None = None
        for page_index in range(1, MAX_EXTENDED_CONTENT_PAGES + 1):
            if gate.elapsed_seconds >= gate.seconds:
                raise RuntimeError("BODY_BATCH_TIME_BUDGET_EXHAUSTED")
            url = api["eastmoney_content_url"](art_code, page_index=page_index)
            page_receipt, raw = _capture_url(api, store, provider, gate, url, art_code=art_code,
                page_index=page_index, kind="body", out_root=out_root)
            if page_receipt.get("status") != "CAPTURED" or raw is None:
                raise ValueError(str(page_receipt.get("error_code") or "BODY_CONTENT_CAPTURE_FAILED"))
            detail = _content_detail(raw)
            if (detail.get("art_code") != art_code or detail.get("notice_title") != expected_title
                    or _notice_date(detail.get("notice_date")) != publication_date):
                raise ValueError("BODY_CONTENT_ARTICLE_TITLE_OR_DATE_MISMATCH")
            total = detail.get("page_size")
            if type(total) is not int or total < 1:
                raise ValueError("BODY_CONTENT_PAGE_TOTAL_INVALID")
            if expected_total is None:
                expected_total = total
                first_detail = detail
                if expected_total > MAX_EXTENDED_CONTENT_PAGES:
                    raise ValueError("BODY_CONTENT_PAGE_LIMIT_EXCEEDED")
            elif total != expected_total:
                raise ValueError("BODY_CONTENT_PAGE_TOTAL_DRIFT")
            matched = api["_body_security_match"](api, issuers, detail)
            if not matched:
                raise ValueError("BODY_CONTENT_116_H_STOCK_IDENTITY_MISMATCH")
            text = detail.get("notice_content")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("BODY_CONTENT_TEXT_MISSING")
            text_hash = digest(text.encode("utf-8"))
            text_characters += len(text)
            page_receipt["content_metadata"] = {"art_code": art_code,
                "notice_title": detail.get("notice_title"), "notice_date": detail.get("notice_date"),
                "page_index": page_index, "page_total": total, "text_characters": len(text),
                "text_sha256": text_hash, "matched_source_issuer_codes": matched}
            atomic_json(out_root / "receipts" / f"{digest(url.encode('utf-8'))}.json", page_receipt)
            pages.append({"page_index": page_index, "page_total": total, "source_ref": page_receipt["source_ref"],
                "raw_body_sha256": page_receipt["raw_body_sha256"], "retrieved_at": page_receipt["retrieved_at"],
                "notice_date": detail.get("notice_date"), "notice_title": detail.get("notice_title"),
                "text": text, "text_sha256": text_hash, "source_stock_codes_matched": matched})
            if text_characters > MAX_EXTENDED_BODY_CHARACTERS:
                raise ValueError("BODY_CONTENT_TEXT_LIMIT_EXCEEDED")
            if page_index == total:
                joined = "\n\n".join(page["text"] for page in pages)
                result.update(status="COMPLETE_CONTENT_API_BODY", body_status="COMPLETE_CONTENT_API_BODY",
                    content_page_count=total, content_api_pages_captured=len(pages), text_characters=text_characters,
                    body_text=joined, body_text_sha256=digest(joined.encode("utf-8")),
                    pagination_mode=("EXTENDED_API_PAGINATION" if total > api["MAX_EASTMONEY_CONTENT_PAGES"] else "STANDARD_API_PAGINATION"))
                break
        if result["status"] == "BODY_CAPTURE_FAILED" and first_detail is not None:
            if expected_total is not None and len(pages) != expected_total:
                raise ValueError("BODY_CONTENT_PAGE_COVERAGE_INCOMPLETE")
    except Exception as exc:
        result.update(status="BODY_CAPTURE_FAILED", body_status="BODY_CAPTURE_FAILED",
                      error_code=api["safe_reason"](exc, "BODY_CAPTURE_FAILED"), content_api_pages_captured=len(pages))
    body_value = {"schema": "v4.manager_research.source_bound_announcement_body.v1",
        "art_code": art_code, "title": row.get("title"), "target_trade_date": target_trade_date,
        "publication_date": publication_date, "listing_source_ref": row.get("source_ref"),
        "listing_raw_body_sha256": row.get("raw_body_sha256"), "source_issuer_codes": row.get("source_issuer_codes"),
        "content_api_pages": pages, "body_status": result.get("body_status", "BODY_CAPTURE_FAILED"),
        "body_text": result.get("body_text"), "body_text_sha256": result.get("body_text_sha256"),
        "pdf": result.get("pdf"), "semantic_status": "NOT_REVIEWED",
        "first_hkex_publication_time": "CANNOT_CONFIRM", "original_point_in_time_availability": "CANNOT_CONFIRM"}
    body_sha = atomic_json(body_path, body_value)
    result.update(body_path=str(body_path.relative_to(out_root)), body_file_sha256=body_sha,
        page_count=len(pages), terminal_at=utc_now())
    atomic_json(receipt_path, result)
    return result


def _index_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"art_code": row["art_code"], "title": row.get("title"),
        "target_trade_date": row.get("target_trade_date"), "publication_date": row.get("publication_date"),
        "source_issuer_codes": row.get("source_issuer_codes"),
        "listing_source_ref": row.get("listing_source_ref"),
        "listing_raw_body_sha256": row.get("listing_raw_body_sha256"),
        "status": row.get("status"), "body_status": row.get("body_status"),
        "semantic_status": row.get("semantic_status", "NOT_REVIEWED"),
        "body_path": row.get("body_path"), "body_file_sha256": row.get("body_file_sha256"),
        "content_api_pages_captured": row.get("content_api_pages_captured", row.get("page_count", 0)),
        "error_code": row.get("error_code"), "first_hkex_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM"} for row in rows]


def _body_corpus_row(item: Mapping[str, Any], body_file: Mapping[str, Any]) -> dict[str, Any]:
    status = body_file.get("body_status", "BODY_CAPTURE_FAILED")
    pages = body_file.get("content_api_pages")
    if not isinstance(pages, list):
        pages = []
    return {"art_code": body_file.get("art_code"), "title": body_file.get("title"),
        "connect_eligibility_status": item.get("connect_eligibility_status"),
        "matched_connect_codes": item.get("matched_connect_codes"),
        "connect_eligibility_identity_sha256": item.get("connect_eligibility_identity_sha256"),
        "source_issuer_codes": item.get("source_issuer_codes"),
        "listing_source_ref": item.get("listing_source_ref"),
        "listing_raw_body_sha256": item.get("listing_raw_body_sha256"),
        "attachment_url": None, "body_status": status, "transport_body_status": status,
        "transport_first_hkex_publication_time": "CANNOT_CONFIRM",
        "transport_pit_status": "CANNOT_CONFIRM", "transport_semantic_status": "NOT_REVIEWED",
        "body_text": body_file.get("body_text"), "body_text_sha256": body_file.get("body_text_sha256"),
        "content_page_count": body_file.get("content_api_pages", [{}])[0].get("page_total") if pages else None,
        "pages": pages, "pdf_sha256": None, "capture_receipt_sha256": item.get("body_file_sha256")}


def _verified_hkex_directory_readback(value: Mapping[str, Any], target: str,
                                      publication: str) -> tuple[set[str], list[Mapping[str, Any]]]:
    if (value.get("target_trade_date") != target
            or value.get("daily_publication_date") != target
            or publication.replace("-", "") != target
            or value.get("publication_timezone") != "Asia/Hong_Kong"):
        raise ValueError("HKEX_DAILY_DIRECTORY_DATE_BINDING_INVALID")
    coverage = value.get("coverage")
    products = coverage.get("market_directory_products") if isinstance(coverage, Mapping) else None
    if not isinstance(products, list) or not products:
        raise ValueError("HKEX_DAILY_DIRECTORY_PRODUCT_MISSING")
    run_ids: set[str] = set()
    ordered_run_ids: list[str] = []
    expected_counts: dict[str, int] = {}
    for product in products:
        if not isinstance(product, Mapping):
            continue
        if (product.get("source_scope") != "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1"
                or product.get("from_date") != target or product.get("to_date") != target):
            continue
        run_id = product.get("product_run_id")
        count = product.get("record_count")
        if (product.get("window_mode") != "HK_CALENDAR_DAY_V1"
                or product.get("status") != "COMPLETE"
                or product.get("directory_exhaustion") != "VERIFIED"
                or type(count) is not int or count < 0
                or count != product.get("loaded_record")
                or count != product.get("captured_row_count")
                or count != product.get("unique_news_id_count")
                or not isinstance(run_id, str)
                or re.fullmatch(r"[0-9a-f]{32}", run_id) is None
                or re.fullmatch(r"[0-9a-f]{64}", str(product.get("product_sha256", ""))) is None
                or run_id in expected_counts):
            raise ValueError("HKEX_DAILY_DIRECTORY_PRODUCT_INCOMPLETE_OR_DUPLICATE")
        run_ids.add(run_id)
        ordered_run_ids.append(run_id)
        expected_counts[run_id] = count
    if not run_ids:
        raise ValueError("HKEX_DAILY_DIRECTORY_NOT_COMPLETE_FOR_TARGET_DAY")
    document_sets = coverage.get("market_directory_document_sets") if isinstance(coverage, Mapping) else None
    selected_run_id = ordered_run_ids[-1]
    if document_sets is not None:
        if not isinstance(document_sets, list) or len(document_sets) != len(ordered_run_ids):
            raise ValueError("HKEX_DAILY_DIRECTORY_PER_RUN_DOCUMENT_SETS_INVALID")
        set_run_ids = []
        documents_by_run: dict[str, list[Mapping[str, Any]]] = {}
        capture_cutoffs = []
        product_by_run = {product.get("product_run_id"): product for product in products
            if isinstance(product, Mapping) and product.get("product_run_id") in run_ids}
        for document_set in document_sets:
            if not isinstance(document_set, Mapping):
                raise ValueError("HKEX_DAILY_DIRECTORY_PER_RUN_DOCUMENT_SETS_INVALID")
            run_id = document_set.get("product_run_id")
            capture_cutoff = document_set.get("product_capture_cutoff")
            docs = document_set.get("official_documents")
            try:
                parsed_cutoff = datetime.fromisoformat(capture_cutoff.replace("Z", "+00:00")) \
                    if isinstance(capture_cutoff, str) else None
            except ValueError:
                parsed_cutoff = None
            product_cutoff = product_by_run.get(run_id, {}).get("query_cutoff")
            try:
                parsed_product_cutoff = datetime.fromisoformat(product_cutoff.replace("Z", "+00:00")) \
                    if isinstance(product_cutoff, str) else None
            except ValueError:
                parsed_product_cutoff = None
            if (run_id not in run_ids or run_id in documents_by_run
                    or parsed_cutoff is None or parsed_cutoff.utcoffset() is None
                    or parsed_product_cutoff is None or parsed_product_cutoff != parsed_cutoff
                    or not isinstance(docs, list)):
                raise ValueError("HKEX_DAILY_DIRECTORY_PER_RUN_DOCUMENT_SETS_INVALID")
            set_run_ids.append(run_id)
            capture_cutoffs.append(parsed_cutoff)
            documents_by_run[run_id] = docs
        if set_run_ids != ordered_run_ids:
            raise ValueError("HKEX_DAILY_DIRECTORY_PER_RUN_DOCUMENT_SETS_INVALID")
        if any(later < earlier for earlier, later in zip(capture_cutoffs, capture_cutoffs[1:])):
            raise ValueError("HKEX_DAILY_DIRECTORY_PER_RUN_DOCUMENT_SETS_INVALID")
        newest = max(capture_cutoffs)
        newest_run_ids = [run_id for run_id, cutoff in zip(set_run_ids, capture_cutoffs) if cutoff == newest]
        if len(newest_run_ids) != 1:
            raise ValueError("HKEX_DAILY_DIRECTORY_LATEST_RUN_AMBIGUOUS")
        selected_run_id = newest_run_ids[0]
    else:
        if len(run_ids) != 1:
            raise ValueError("HKEX_DAILY_DIRECTORY_PER_RUN_DOCUMENT_SETS_REQUIRED")
        documents = value.get("official_documents")
        if not isinstance(documents, list):
            raise ValueError("HKEX_DAILY_DIRECTORY_DOCUMENTS_MISSING")
        documents_by_run = {next(iter(run_ids)): documents}
    selected_by_run: dict[str, list[Mapping[str, Any]]] = {run_id: [] for run_id in run_ids}
    observed_counts = {run_id: 0 for run_id in run_ids}
    observed_news_ids = {run_id: set() for run_id in run_ids}
    for run_id, documents in documents_by_run.items():
        for doc in documents:
            if not isinstance(doc, Mapping):
                raise ValueError("HKEX_DAILY_DIRECTORY_DOCUMENT_IDENTITY_INVALID")
            news_id = doc.get("news_id")
            if (doc.get("capture_run_id") != run_id
                    or doc.get("source") != "HKEX_OFFICIAL"
                    or doc.get("source_scope") != "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1"
                    or not isinstance(news_id, str) or re.fullmatch(r"\d{5,20}", news_id) is None
                    or doc.get("capture_trade_date") != target
                    or doc.get("target_trade_date") != target
                    or doc.get("publication_date") != target
                    or not _safe_hkex_row_url(doc.get("source_url"))
                    or not isinstance(doc.get("directory_ref"), Mapping)
                    or doc.get("directory_ref", {}).get("request", {}).get("url", "").split("?", 1)[0]
                        != "https://www1.hkexnews.hk/search/titleSearchServlet.do"):
                raise ValueError("HKEX_DAILY_DIRECTORY_DOCUMENT_IDENTITY_INVALID")
            if news_id in observed_news_ids[run_id]:
                raise ValueError("HKEX_DAILY_DIRECTORY_DUPLICATE_NEWS_ID")
            observed_news_ids[run_id].add(news_id)
            observed_counts[run_id] += 1
            selected_by_run[run_id].append(doc)
    if any(observed_counts[run_id] != expected_counts[run_id] for run_id in run_ids):
        raise ValueError("HKEX_DAILY_DIRECTORY_DOCUMENT_SET_COUNT_MISMATCH")
    # The projection retains an immutable complete document set per source run.
    # Validate every historical set above, then body-capture only the newest
    # exact-day run so repeated observations cannot collide on source_variant_id.
    return run_ids, selected_by_run[selected_run_id]


def _verified_monthly_connect_eligibility(value: Mapping[str, Any], publication: str) -> tuple[set[str], str]:
    """Validate the exact month snapshot witness supplied by the daily runner."""
    if not isinstance(value, Mapping):
        raise ValueError("HK_CONNECT_MONTHLY_ELIGIBILITY_MISSING")
    identity = value.get("identity_sha256")
    material = {key: item for key, item in value.items() if key != "identity_sha256"}
    if (value.get("schema_version") != "v4.manager_research.hk_connect_monthly_eligibility.v1"
            or value.get("status") != "VERIFIED"
            or value.get("policy") != "CALENDAR_MONTH_LATEST_VERIFIED_V2"
            or value.get("month") != publication[:7].replace("-", "")
            or value.get("target_trade_date") != publication.replace("-", "")
            or not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{64}", identity) is None
            or sha256(json.dumps(material, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest() != identity
            or any(value.get(key) is not expected for key, expected in (
                ("RESEARCH_ONLY", True), ("production_allowed", False),
                ("buy_gate_updated", False), ("orders_sent", False)))):
        raise ValueError("HK_CONNECT_MONTHLY_ELIGIBILITY_IDENTITY_INVALID")
    source = value.get("source")
    codes = value.get("codes")
    if (not isinstance(source, Mapping)
            or source.get("market") != "HK_CONNECT"
            or source.get("role") != "HK_CONNECT_FULL_MARKET_AUTHORITY"
            or source.get("source_date") != value.get("source_date")
            or not isinstance(value.get("source_date"), str)
            or not re.fullmatch(r"\d{8}", value["source_date"])
            or value["source_date"][:6] != value.get("month")
            or not isinstance(value.get("capture_cutoff_at"), str)
            or not isinstance(codes, list) or not codes or codes != sorted(set(codes))
            or not all(isinstance(code, str) and re.fullmatch(r"HK\.\d{5}", code) for code in codes)
            or value.get("code_count") != len(codes)
            or value.get("codes_sha256") != sha256(json.dumps(
                codes, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                allow_nan=False).encode("utf-8")).hexdigest()
            ):
        raise ValueError("HK_CONNECT_MONTHLY_ELIGIBILITY_SOURCE_INVALID")
    available_at = source.get("available_at")
    try:
        available = datetime.fromisoformat(str(available_at).replace("Z", "+00:00"))
        cutoff = datetime.fromisoformat(value["capture_cutoff_at"].replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("HK_CONNECT_MONTHLY_ELIGIBILITY_TIME_INVALID") from exc
    if (available.tzinfo is None or cutoff.tzinfo is None or available > cutoff
            or value["source_date"][:6] != publication[:7].replace("-", "")):
        raise ValueError("HK_CONNECT_MONTHLY_ELIGIBILITY_TIME_OR_MONTH_INVALID")
    if value["source_date"] > cutoff.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y%m%d"):
        raise ValueError("HK_CONNECT_MONTHLY_SOURCE_DATE_AFTER_CAPTURE_CUTOFF")
    source_hashes = value.get("authority_file_sha256s")
    required_refs = ("artifact_ref", "manifest_ref", "receipt_ref", "current_ref",
                     "capture_ref", "publication_ref")
    if (not isinstance(source_hashes, Mapping)
            or set(source_hashes) != set(required_refs)
            or any(not isinstance(source.get(ref), str) or not source.get(ref)
                   or not isinstance(source_hashes.get(ref), str)
                   or re.fullmatch(r"[0-9a-f]{64}", source_hashes[ref]) is None
                   for ref in required_refs)
            or not all(re.fullmatch(r"[0-9a-f]{64}", str(source.get(key, "")))
                       for key in ("sha256", "capture_sha256", "source_sha256"))):
        raise ValueError("HK_CONNECT_MONTHLY_ELIGIBILITY_AUTHORITY_BINDING_INVALID")
    return set(codes), identity


def _apply_monthly_connect_eligibility(directory_rows: list[Mapping[str, Any]],
                                       hkex_documents: list[Mapping[str, Any]],
                                       codes: set[str], identity: str
                                       ) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                                                  list[Mapping[str, Any]], list[dict[str, Any]]]:
    """Filter both complete directories by exact issuer codes, before body I/O."""
    eligible_eastmoney: list[dict[str, Any]] = []
    eastmoney_coverage: list[dict[str, Any]] = []
    for row in directory_rows:
        source_identities = row.get("source_issuer_codes")
        source_codes = [item["code"] for item in source_identities
            if isinstance(item, Mapping) and isinstance(item.get("code"), str)
            and re.fullmatch(r"HK\.\d{5}", item["code"])] if isinstance(source_identities, list) else []
        matched = sorted(set(source_codes) & codes)
        unresolved_identity_count = (len(source_identities) - len(source_codes)
            if isinstance(source_identities, list) else 1)
        status = ("ELIGIBLE" if matched else "UNRESOLVED"
            if not source_codes or unresolved_identity_count else "NOT_ELIGIBLE")
        eastmoney_coverage.append({
            "art_code": row.get("art_code"), "status": status,
            "source_issuer_codes": source_identities,
            "matched_connect_codes": matched,
            "unresolved_source_identity_count": unresolved_identity_count,
            "listing_source_ref": row.get("source_ref"),
            "listing_raw_body_sha256": row.get("raw_body_sha256"),
        })
        if matched:
            eligible_eastmoney.append(dict(row, connect_eligibility_status=status,
                matched_connect_codes=matched,
                connect_eligibility_identity_sha256=identity))

    eligible_hkex: list[Mapping[str, Any]] = []
    hkex_coverage: list[dict[str, Any]] = []
    for doc in hkex_documents:
        symbol = doc.get("symbol")
        valid_symbol = isinstance(symbol, str) and re.fullmatch(r"HK\.\d{5}", symbol)
        status = "ELIGIBLE" if valid_symbol and symbol in codes else (
            "UNRESOLVED" if not valid_symbol else "NOT_ELIGIBLE")
        hkex_coverage.append({
            "news_id": doc.get("news_id"), "symbol": symbol, "status": status,
            "source_scope": doc.get("source_scope"), "source_url": doc.get("source_url"),
            "directory_source_ref": doc.get("directory_ref"),
            "connect_eligibility_identity_sha256": identity,
        })
        if status == "ELIGIBLE":
            eligible_hkex.append(doc)
    return eligible_eastmoney, eastmoney_coverage, eligible_hkex, hkex_coverage


def _safe_hkex_row_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        from urllib.parse import urlparse
        parsed = urlparse(value)
    except ValueError:
        return False
    from v4.manager_research.hkex_provider import _safe_official_url
    return (_safe_official_url(value) and parsed.hostname in {
        "www1.hkexnews.hk", "www.hkexnews.hk", "sc.hkexnews.hk"})


def _capture_hkex_variant(api: Mapping[str, Any], store: Any, provider: Any,
                          gate: SharedCaptureGate, doc: Mapping[str, Any],
                          output: Path, target: str, publication: str) -> dict[str, Any]:
    news_id = str(doc["news_id"])
    variant_id = "HKEX:" + news_id
    row = {key: doc.get(key) for key in (
        "source", "source_scope", "news_id", "event_id", "symbol", "name", "title",
        "publication_date", "published_at", "available_at", "source_url", "directory_ref",
        "first_directory_ref", "capture_run_id", "capture_revision", "query_cutoff",
        "source_refs", "body_status", "body_reason", "document_sha256")}
    body_ref = next((ref for ref in doc.get("source_refs", []) if isinstance(ref, Mapping)
        and (ref.get("request") or {}).get("url") == doc.get("source_url")), None)
    status = str(doc.get("body_status") or "BODY_NOT_CAPTURED")
    if body_ref is None and str(doc.get("source_url", "")).lower().endswith(".pdf"):
        receipt_path = output / "official_variants" / f"{news_id}.attempt.json"
        if receipt_path.exists():
            raise RuntimeError("HKEX_BODY_ATTEMPT_EXISTS_NO_RETRY")
        atomic_json(receipt_path, {"schema": "v4.manager_research.hkex_body_variant_attempt.v1",
            "source_variant_id": variant_id, "source_url": doc.get("source_url"),
            "started_at": utc_now(), "one_attempt_only": True})
        try:
            body_ref = api["capture"](provider, {"url": doc["source_url"], "method": "GET"}, budget=gate)
            raw = api["read_response"](store, body_ref)
            gate.record_response_bytes(len(raw))
            status = "BODY_CAPTURED_UNASSESSED" if body_ref.get("http_status", 0) >= 200 and raw.startswith(b"%PDF") else "BODY_FETCH_FAILED"
        except Exception as exc:
            status = "BODY_FETCH_FAILED"
            row["body_reason"] = api["safe_reason"](exc, "HKEX_BODY_CAPTURE_FAILED")
            raw = None
        finally:
            gate.end_request()
    else:
        raw = api["read_response"](store, body_ref) if body_ref is not None else None
    directory_ref = doc.get("directory_ref")
    directory_raw = api["read_response"](store, directory_ref)
    if (not isinstance(directory_raw, bytes)
            or directory_ref.get("body_sha256") != sha256(directory_raw).hexdigest()):
        raise ValueError("HKEX_DAILY_DIRECTORY_SOURCE_REFERENCE_INVALID")
    pages: list[dict[str, Any]] = []
    body_text = None
    body_text_sha = None
    if body_ref is not None and raw is not None and body_ref.get("http_status", 0) >= 200 and raw.startswith(b"%PDF"):
        parsed_pages = api["extract_pdf_pages"](raw, max_bytes=8_000_000, max_pages=40,
            max_text_characters=240_000, timeout_seconds=10)
        for index, page in enumerate(parsed_pages, 1):
            text = page.get("text") if isinstance(page, Mapping) else None
            if isinstance(text, str) and text.strip():
                pages.append({"page_index": index, "page_total": len(parsed_pages),
                    "source_ref": body_ref, "raw_body_sha256": body_ref.get("body_sha256"),
                    "retrieved_at": body_ref.get("retrieved_at"), "text": text,
                    "text_sha256": digest(text.encode("utf-8"))})
        if pages:
            body_text = "\n\n".join(page["text"] for page in pages)
            body_text_sha = digest(body_text.encode("utf-8"))
            status = "COMPLETE_HKEX_OFFICIAL_PDF_BODY"
        else:
            status = "HKEX_OFFICIAL_PDF_TEXT_UNREADABLE"
    elif status == "BODY_CAPTURED_UNASSESSED":
        status = "HKEX_OFFICIAL_PDF_BODY_UNREADABLE"
    body_file = {"schema": "v4.manager_research.source_bound_hkex_official_body.v1",
        "source_variant_id": variant_id, "target_trade_date": target,
        **row, "publication_date": publication, "body_source_ref": body_ref,
        "directory_source_ref": directory_ref, "directory_raw_body_sha256": digest(directory_raw),
        "body_status": status, "body_text": body_text, "body_text_sha256": body_text_sha,
        "pages": pages, "semantic_status": "NOT_REVIEWED",
        "first_hkex_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM"}
    artifact = output / "official_variants" / f"{news_id}.json"
    artifact_sha = atomic_json(artifact, body_file)
    return {"source_variant_id": variant_id, "source": "HKEX_OFFICIAL",
        "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1", "news_id": news_id,
        "event_id": doc.get("event_id"), "symbol": doc.get("symbol"), "issuer_codes": [doc.get("symbol")],
        "title": doc.get("title"), "publication_date": publication,
        "published_at": doc.get("published_at"), "available_at": doc.get("available_at"),
        "source_url": doc.get("source_url"), "directory_source_ref": directory_ref,
        "body_source_ref": body_ref, "directory_raw_body_sha256": digest(directory_raw),
        "body_status": status, "body_text": body_text, "body_text_sha256": body_text_sha,
        "pages": pages, "cross_source_link_status": "NOT_ASSESSED",
        "body_artifact": str(artifact.relative_to(output)), "body_artifact_sha256": artifact_sha,
        "semantic_status": "NOT_REVIEWED", "first_hkex_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM"}


def _run_article_canary(api: Mapping[str, Any], store: Any, provider: Any,
                        row: Mapping[str, Any], output: Path,
                        target_trade_date: str, publication_date: str,
                        catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Capture one approved catalog article without producing full-batch inputs."""
    if output.exists() or output.is_symlink():
        raise RuntimeError("BODY_BATCH_CANARY_OUTPUT_EXISTS_NO_RETRY")
    output.mkdir(parents=True, exist_ok=False)
    art_code = str(row["art_code"])
    started_at = utc_now()
    attempt_sha = atomic_json(output / "canary_attempt.json", {
        "schema": "v4.manager_research.announcement_body_canary_attempt.v1",
        "started_at": started_at,
        "target_trade_date": target_trade_date,
        "publication_date": publication_date,
        "catalog_run_id": catalog.get("run_id"),
        "catalog_sha256": catalog.get("sha256"),
        "art_code": art_code,
        "one_article_only": True,
        "one_attempt_only": True,
    })
    gate = SharedCaptureGate(seconds=MAX_SECONDS, max_requests=MAX_NETWORK_REQUESTS,
        max_bytes=MAX_RESPONSE_BYTES, interval=REQUEST_INTERVAL_SECONDS)
    gate.set_response_limits(per_response=api["MAX_EASTMONEY_RESPONSE_BYTES"], total=MAX_RESPONSE_BYTES)
    try:
        item = _capture_article(api, store, provider, gate, row, output,
            target_trade_date, publication_date)
        error_code = None
    except Exception as exc:
        item = {"art_code": art_code, "status": "BODY_CAPTURE_FAILED",
                "body_status": "BODY_CAPTURE_FAILED",
                "error_code": api["safe_reason"](exc, "BODY_CAPTURE_FAILED"),
                "terminal_at": utc_now()}
        error_code = item["error_code"]
    item_receipt_path = output / "article_receipts" / f"{art_code}.json"
    item_receipt_sha = digest(item_receipt_path.read_bytes()) if item_receipt_path.is_file() else None
    body_rel = item.get("body_path")
    body_path = output / body_rel if isinstance(body_rel, str) else None
    body_sha = digest(body_path.read_bytes()) if body_path is not None and body_path.is_file() else None
    receipt = {
        "schema": "v4.manager_research.announcement_body_canary_receipt.v1",
        "status": "CANARY_PARTIAL",
        "formal_import_eligible": False,
        "completeness": "ONE_ARTICLE_ONLY",
        "target_trade_date": target_trade_date,
        "publication_date": publication_date,
        "catalog_run_id": catalog.get("run_id"),
        "catalog_sha256": catalog.get("sha256"),
        "art_code": art_code,
        "one_article_only": True,
        "one_attempt_only": True,
        "attempt_path": "canary_attempt.json",
        "attempt_sha256": attempt_sha,
        "article_status": item.get("status"),
        "body_status": item.get("body_status", item.get("status")),
        "article_receipt_path": (str(item_receipt_path.relative_to(output))
                                  if item_receipt_sha else None),
        "article_receipt_sha256": item_receipt_sha,
        "body_path": body_rel if body_sha else None,
        "body_file_sha256": body_sha,
        "error_code": error_code or item.get("error_code"),
        "semantic_status": "NOT_REVIEWED",
        "first_hkex_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM",
        "live_import": "NOT_RUN",
        "generated_at": utc_now(),
    }
    atomic_json(output / "canary_receipt.json", receipt)
    return receipt


def run_capture(catalog_read: Mapping[str, Any], material_root: str | Path,
                output_root: str | Path, target_trade_date: str, publication_date: str,
                *, canary_article: str | None = None,
                hkex_directory_readback: Mapping[str, Any] | None = None,
                monthly_connect_eligibility: Mapping[str, Any] | None = None,
                api_overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Capture every catalog article; writes only below ``output_root``."""
    target_trade_date = re.sub(r"-", "", str(target_trade_date))
    if not re.fullmatch(r"\d{8}", target_trade_date):
        raise ValueError("BODY_BATCH_TARGET_DATE_INVALID")
    if (not isinstance(publication_date, str)
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", publication_date)):
        raise ValueError("BODY_BATCH_PUBLICATION_DATE_INVALID")
    api = imports()
    api["_body_security_match"] = _body_security_match
    if api_overrides:
        api.update(api_overrides)
    store = api["MaterialStore"](material_root)
    directory_rows = _validate_catalog(api, catalog_read, store, target_trade_date, publication_date)
    catalog = _catalog_product(catalog_read)
    eligibility_codes: set[str] | None = None
    eligibility_identity = None
    if monthly_connect_eligibility is not None:
        eligibility_codes, eligibility_identity = _verified_monthly_connect_eligibility(
            monthly_connect_eligibility, publication_date)
    hkex_run_ids: set[str] = set()
    hkex_documents: list[Mapping[str, Any]] = []
    if hkex_directory_readback is not None:
        hkex_run_ids, hkex_documents = _verified_hkex_directory_readback(
            hkex_directory_readback, target_trade_date, publication_date)
        if eligibility_codes is None or eligibility_identity is None:
            raise ValueError("HK_CONNECT_MONTHLY_ELIGIBILITY_REQUIRED_FOR_DAILY_SOURCES")
    elif eligibility_codes is not None:
        raise ValueError("HKEX_DAILY_DIRECTORY_REQUIRED_FOR_MONTHLY_ELIGIBILITY")

    rows: list[dict[str, Any]]
    eastmoney_row_eligibility: list[dict[str, Any]]
    eligible_hkex_documents: list[Mapping[str, Any]]
    hkex_directory_eligibility: list[dict[str, Any]]
    if eligibility_codes is None:
        rows, eastmoney_row_eligibility = directory_rows, []
        eligible_hkex_documents, hkex_directory_eligibility = hkex_documents, []
    else:
        (rows, eastmoney_row_eligibility, eligible_hkex_documents,
         hkex_directory_eligibility) = _apply_monthly_connect_eligibility(
             directory_rows, hkex_documents, eligibility_codes, eligibility_identity)
    output = Path(output_root)
    if canary_article is not None:
        if (target_trade_date != APPROVED_CANARY_TARGET_DATE
                or publication_date != APPROVED_CANARY_PUBLICATION_DATE
                or canary_article != APPROVED_CANARY_ARTICLE):
            raise ValueError("BODY_BATCH_CANARY_ARTICLE_OR_DATE_NOT_AUTHORIZED")
        selected = [row for row in rows if row.get("art_code") == canary_article]
        if len(selected) != 1:
            raise ValueError("BODY_BATCH_CANARY_ARTICLE_NOT_IN_VERIFIED_CATALOG")
        provider = api["HkexOfficialProvider"](material_store=store, timeout=20.0)
        return _run_article_canary(api, store, provider, selected[0], output,
            target_trade_date, publication_date, catalog)
    marker = output / "batch_attempt.json"
    receipt_path = output / "batch_receipt.json"
    output.mkdir(parents=True, exist_ok=True)
    if marker.exists() or receipt_path.exists():
        raise RuntimeError("BODY_BATCH_ATTEMPT_EXISTS_NO_RETRY")
    associations = sum(len(row["source_issuer_codes"]) for row in rows)
    distinct_codes = sorted({identity["code"] for row in rows for identity in row["source_issuer_codes"]})
    catalog_identity = {"target_trade_date": target_trade_date, "publication_date": publication_date,
        "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
        "article_ids": [row["art_code"] for row in rows],
        "listing_body_sha256s": [row["raw_body_sha256"] for row in rows]}
    if eligibility_identity is not None:
        catalog_identity.update(monthly_connect_eligibility_identity_sha256=eligibility_identity,
            hkex_directory_readback_sha256=digest(json_bytes(hkex_directory_readback)),
            hkex_eligible_news_ids=[doc.get("news_id") for doc in eligible_hkex_documents])
    input_identity_sha = digest(json_bytes(catalog_identity))
    started_at = utc_now()
    (output / "bodies").mkdir(parents=True, exist_ok=True)
    atomic_json(marker, {"schema": "v4.manager_research.body_batch_attempt.v1", "started_at": started_at,
        **catalog_identity, "input_identity_sha256": input_identity_sha, "article_count": len(rows),
        "workers": WORKERS, "max_seconds": MAX_SECONDS, "max_network_requests": MAX_NETWORK_REQUESTS,
        "max_response_bytes": MAX_RESPONSE_BYTES, "max_extended_content_pages": MAX_EXTENDED_CONTENT_PAGES,
        "max_body_characters": MAX_EXTENDED_BODY_CHARACTERS, "one_attempt_only": True})
    provider = api["HkexOfficialProvider"](material_store=store, timeout=20.0)
    gate = SharedCaptureGate(seconds=MAX_SECONDS, max_requests=MAX_NETWORK_REQUESTS,
        max_bytes=MAX_RESPONSE_BYTES, interval=REQUEST_INTERVAL_SECONDS)
    gate.set_response_limits(per_response=api["MAX_EASTMONEY_RESPONSE_BYTES"], total=MAX_RESPONSE_BYTES)
    by_art: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="hk-ann-body") as pool:
        futures = {pool.submit(_capture_article, api, store, provider, gate, row, output,
                    target_trade_date, publication_date): row for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                item = future.result()
            except Exception as exc:
                item = {"art_code": row.get("art_code"), "target_trade_date": target_trade_date,
                    "publication_date": publication_date, "status": "BODY_CAPTURE_FAILED",
                    "body_status": "BODY_CAPTURE_FAILED", "semantic_status": "NOT_REVIEWED",
                    "error_code": api["safe_reason"](exc, "BODY_CAPTURE_FAILED"), "terminal_at": utc_now()}
            by_art[str(row.get("art_code"))] = item
            done_counts: dict[str, int] = {}
            for done in by_art.values():
                status = str(done.get("body_status", done.get("status", "UNKNOWN")))
                done_counts[status] = done_counts.get(status, 0) + 1
            atomic_json(output / "progress.json", {"schema": "v4.manager_research.body_batch_progress.v1",
                "completed_article_rows": len(by_art), "total_article_rows": len(rows),
                "body_status_counts": done_counts, "physical_requests": gate.requests,
                "response_bytes": gate.response_bytes, "elapsed_seconds": round(gate.elapsed_seconds, 3),
                "updated_at": utc_now()})
    hkex_variants: list[dict[str, Any]] = []
    hkex_status_counts: dict[str, int] = {}
    if hkex_directory_readback is not None:
        for doc in eligible_hkex_documents:
            try:
                variant = _capture_hkex_variant(api, store, provider, gate, doc, output,
                    target_trade_date, publication_date)
            except Exception as exc:
                news_id = str(doc.get("news_id") or "")
                directory_ref = doc.get("directory_ref")
                try:
                    directory_raw = api["read_response"](store, directory_ref)
                    directory_sha = digest(directory_raw)
                except Exception:
                    directory_sha = None
                variant = {"source_variant_id": "HKEX:" + news_id,
                    "source": "HKEX_OFFICIAL",
                    "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
                    "news_id": news_id, "symbol": doc.get("symbol"), "title": doc.get("title"),
                    "publication_date": doc.get("publication_date"),
                    "published_at": doc.get("published_at"),
                    "source_url": doc.get("source_url"),
                    "directory_source_ref": directory_ref,
                    "directory_raw_body_sha256": directory_sha,
                    "body_source_ref": None, "body_status": "HKEX_BODY_CAPTURE_FAILED",
                    "body_text": None, "body_text_sha256": None, "pages": [],
                    "cross_source_link_status": "NOT_ASSESSED",
                    "error_code": api["safe_reason"](exc, "HKEX_BODY_CAPTURE_FAILED"),
                    "semantic_status": "NOT_REVIEWED",
                    "first_hkex_publication_time": "CANNOT_CONFIRM",
                    "original_point_in_time_availability": "CANNOT_CONFIRM"}
                artifact = output / "official_variants" / f"{news_id}.json"
                artifact_sha = atomic_json(artifact, {
                    "schema": "v4.manager_research.source_bound_hkex_official_body.v1",
                    "source_variant_id": variant["source_variant_id"],
                    "target_trade_date": target_trade_date,
                    "publication_date": publication_date,
                    "source": "HKEX_OFFICIAL",
                    "source_scope": "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1",
                    "news_id": news_id, "symbol": doc.get("symbol"), "name": doc.get("name"),
                    "title": doc.get("title"), "publication_date": doc.get("publication_date"),
                    "source_url": doc.get("source_url"),
                    "directory_source_ref": directory_ref, "body_source_ref": None,
                    "directory_raw_body_sha256": directory_sha, "body_status": "HKEX_BODY_CAPTURE_FAILED",
                    "body_text": None, "body_text_sha256": None, "pages": [],
                    "semantic_status": "NOT_REVIEWED",
                    "first_hkex_publication_time": "CANNOT_CONFIRM",
                    "original_point_in_time_availability": "CANNOT_CONFIRM"})
                variant["body_artifact"] = str(artifact.relative_to(output))
                variant["body_artifact_sha256"] = artifact_sha
            if eligibility_identity is not None:
                matched_code = doc.get("symbol")
                variant["connect_eligibility_status"] = "ELIGIBLE"
                variant["matched_connect_codes"] = [matched_code] if isinstance(matched_code, str) else []
                variant["connect_eligibility_identity_sha256"] = eligibility_identity
            hkex_variants.append(variant)
            status = str(variant.get("body_status") or "UNKNOWN")
            hkex_status_counts[status] = hkex_status_counts.get(status, 0) + 1
    results: list[dict[str, Any]] = []
    corpus_rows: list[dict[str, Any]] = []
    for row in rows:
        item = by_art.get(str(row["art_code"])) or {"art_code": row["art_code"],
            "status": "NOT_ATTEMPTED", "body_status": "NOT_ATTEMPTED", "semantic_status": "NOT_REVIEWED"}
        item.setdefault("target_trade_date", target_trade_date)
        item.setdefault("publication_date", publication_date)
        item.setdefault("title", row.get("title"))
        item.setdefault("source_issuer_codes", row.get("source_issuer_codes"))
        item.setdefault("listing_source_ref", row.get("source_ref"))
        item.setdefault("listing_raw_body_sha256", row.get("raw_body_sha256"))
        if eligibility_identity is not None:
            item.setdefault("connect_eligibility_status", "ELIGIBLE")
            item.setdefault("matched_connect_codes", row.get("matched_connect_codes", []))
            item.setdefault("connect_eligibility_identity_sha256", eligibility_identity)
        results.append(item)
        body_rel = item.get("body_path")
        body_file = read_json(output / body_rel) if isinstance(body_rel, str) and (output / body_rel).is_file() else {
            "art_code": row["art_code"], "title": row.get("title"), "body_status": "BODY_CAPTURE_FAILED",
            "content_api_pages": [], "body_text": None, "body_text_sha256": None}
        corpus_rows.append(_body_corpus_row(item, body_file))
    for start in range(0, len(results), ARTICLE_SHARD_SIZE):
        shard_index = start // ARTICLE_SHARD_SIZE + 1
        shard_items = _index_rows(results[start:start + ARTICLE_SHARD_SIZE])
        atomic_json(output / "article_index_shards" / f"articles-{shard_index:03d}.json", {
            "schema": "v4.manager_research.announcement_semantic_review_article_index.v1",
            "shard_index": shard_index, "shard_size": len(shard_items),
            "total_shards": math.ceil(len(results) / ARTICLE_SHARD_SIZE),
            "target_trade_date": target_trade_date, "publication_date": publication_date,
            "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
            "semantic_status": "NOT_REVIEWED", "articles": shard_items})
    status_counts: dict[str, int] = {}
    for item in results:
        status = str(item.get("body_status", item.get("status", "UNKNOWN")))
        status_counts[status] = status_counts.get(status, 0) + 1
    body_manifest = {"schema": "v4.manager_research.source_bound_announcement_body_corpus.v1",
        "target_trade_date": target_trade_date, "publication_date": publication_date,
        "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
        "input_identity_sha256": input_identity_sha, "source_identity_counts": {
            "article_count": len(rows), "source_code_association_count": associations,
            "distinct_source_code_count": len(distinct_codes), "issuer_count": None,
            "unknown_issuer_count": None, "issuer_count_status": "CANNOT_CONFIRM"},
        "body_status_counts": status_counts, "semantic_status": "NOT_REVIEWED",
        "article_receipts": _index_rows(results),
        "article_index_shard_count": math.ceil(len(results) / ARTICLE_SHARD_SIZE),
        "limits": {"workers": WORKERS, "physical_requests": gate.requests,
            "max_physical_requests": MAX_NETWORK_REQUESTS, "response_bytes": gate.response_bytes,
            "max_response_bytes": MAX_RESPONSE_BYTES, "max_extended_content_pages": MAX_EXTENDED_CONTENT_PAGES,
            "max_body_characters": MAX_EXTENDED_BODY_CHARACTERS,
            "elapsed_seconds": round(gate.elapsed_seconds, 3),
            "request_interval_seconds": REQUEST_INTERVAL_SECONDS}, "generated_at": utc_now()}
    if eligibility_identity is not None:
        body_manifest["monthly_connect_eligibility"] = {
            "identity_sha256": eligibility_identity,
            "source_date": monthly_connect_eligibility["source_date"],
            "capture_cutoff_at": monthly_connect_eligibility["capture_cutoff_at"],
            "code_count": monthly_connect_eligibility["code_count"],
            "codes_sha256": monthly_connect_eligibility["codes_sha256"],
            "eastmoney_directory_row_count": len(directory_rows),
            "eligible_eastmoney_row_count": len(rows),
            "excluded_eastmoney_row_count": sum(item["status"] == "NOT_ELIGIBLE" for item in eastmoney_row_eligibility),
            "unresolved_eastmoney_row_count": sum(item["status"] == "UNRESOLVED" for item in eastmoney_row_eligibility),
            "eastmoney_row_eligibility": eastmoney_row_eligibility,
            "hkex_directory_document_count": len(hkex_documents),
            "eligible_hkex_document_count": len(eligible_hkex_documents),
            "excluded_hkex_document_count": sum(item["status"] == "NOT_ELIGIBLE" for item in hkex_directory_eligibility),
            "unresolved_hkex_document_count": sum(item["status"] == "UNRESOLVED" for item in hkex_directory_eligibility),
        }
    if hkex_directory_readback is not None:
        body_manifest["hkex_official_supplement"] = {
            "schema": "v4.manager_research.hkex_official_body_supplement.v1",
            "directory_readback_sha256": digest(json_bytes(hkex_directory_readback)),
            "directory_product_run_ids": sorted(hkex_run_ids),
            "directory_document_count": len(hkex_documents),
            "eligible_document_count": len(eligible_hkex_documents),
            "excluded_document_count": sum(item["status"] == "NOT_ELIGIBLE" for item in hkex_directory_eligibility),
            "unresolved_document_count": sum(item["status"] == "UNRESOLVED" for item in hkex_directory_eligibility),
            "directory_row_eligibility": hkex_directory_eligibility,
            "body_status_counts": dict(sorted(hkex_status_counts.items())),
            "source_variant_ids": [row["source_variant_id"] for row in hkex_variants],
            "cross_source_link_status": "NOT_ASSESSED",
            "body_variants": [
                {key: row.get(key) for key in ("source_variant_id", "news_id", "body_status",
                    "body_source_ref", "directory_source_ref", "body_artifact", "body_artifact_sha256",
                    "error_code")}
                for row in hkex_variants],
        }
    manifest_sha = atomic_json(output / "body_corpus_manifest.json", body_manifest)
    complete = status_counts.get("COMPLETE_CONTENT_API_BODY", 0)
    body_corpus = {"schema": ("v4.manager_research.eastmoney_hk_multi_source_announcement_body_corpus.v1"
            if hkex_directory_readback is not None
            else "v4.manager_research.eastmoney_hk_announcement_body_corpus.v3"),
        "target_notice_date": publication_date, "article_count": len(corpus_rows),
        "transport_complete_body_count": complete, "rows": corpus_rows,
        "source_manifest_artifact": "body_corpus_manifest.json",
        "source_manifest_sha256": manifest_sha, "semantic_status": "NOT_REVIEWED",
        "input_identity_sha256": input_identity_sha}
    if hkex_directory_readback is not None:
        unresolved_hkex_count = sum(item["status"] == "UNRESOLVED" for item in hkex_directory_eligibility)
        excluded_hkex_count = sum(item["status"] == "NOT_ELIGIBLE" for item in hkex_directory_eligibility)
        body_corpus.update(target_trade_date=target_trade_date, publication_date=publication_date,
            eastmoney_article_count=len(corpus_rows), source_variant_count=len(hkex_variants),
            combined_document_count=len(corpus_rows) + len(hkex_variants),
            source_variants=hkex_variants,
            hkex_directory_readback_sha256=digest(json_bytes(hkex_directory_readback)),
            hkex_directory_product_run_ids=sorted(hkex_run_ids),
            hkex_directory_document_count=len(hkex_documents),
            hkex_eligible_document_count=len(eligible_hkex_documents),
            hkex_excluded_document_count=excluded_hkex_count,
            hkex_unresolved_document_count=unresolved_hkex_count,
            hkex_cross_source_link_status="NOT_ASSESSED")
    if eligibility_identity is not None:
        body_corpus["monthly_connect_eligibility"] = dict(monthly_connect_eligibility)
    corpus_sha = atomic_json(output / "body_corpus.json", body_corpus)
    batch_status = ("PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS" if complete == len(rows)
        else "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS")
    if hkex_directory_readback is not None and any(
            row.get("body_status") != "COMPLETE_HKEX_OFFICIAL_PDF_BODY" for row in hkex_variants):
        batch_status = "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS"
    batch = {"schema": "v4.manager_research.announcement_body_batch_receipt.v1", "status": batch_status,
        "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
        "target_trade_date": target_trade_date, "publication_date": publication_date,
        "input_identity_sha256": input_identity_sha, "article_rows": len(rows),
        "terminal_article_receipts": len(results), "body_status_counts": status_counts,
        "body_corpus": "body_corpus.json", "body_corpus_sha256": corpus_sha,
        "body_corpus_manifest": "body_corpus_manifest.json", "body_corpus_manifest_sha256": manifest_sha,
        "semantic_status": "NOT_REVIEWED", "limits": body_manifest["limits"],
        "started_at": started_at, "terminal_at": utc_now(),
        "live_import": "NOT_RUN", "live_api_ui": "NOT_VERIFIED", "natural_run": "NOT_VERIFIED"}
    if eligibility_identity is not None:
        batch["monthly_connect_eligibility"] = {
            "identity_sha256": eligibility_identity,
            "source_date": monthly_connect_eligibility["source_date"],
            "code_count": monthly_connect_eligibility["code_count"],
            "codes_sha256": monthly_connect_eligibility["codes_sha256"],
        }
        batch["eastmoney_directory_coverage"] = {
            "raw_row_count": len(directory_rows), "eligible_row_count": len(rows),
            "excluded_row_count": sum(item["status"] == "NOT_ELIGIBLE" for item in eastmoney_row_eligibility),
            "unresolved_row_count": sum(item["status"] == "UNRESOLVED" for item in eastmoney_row_eligibility),
        }
    if hkex_directory_readback is not None:
        all_hkex_bodies_captured = all(
            row.get("body_status") == "COMPLETE_HKEX_OFFICIAL_PDF_BODY" for row in hkex_variants)
        unresolved_hkex_documents = sum(
            item["status"] == "UNRESOLVED" for item in hkex_directory_eligibility)
        if not eligible_hkex_documents and unresolved_hkex_documents:
            hkex_body_coverage_status = "UNASSESSED_SOURCE_IDENTITY_GAPS"
        elif not eligible_hkex_documents:
            hkex_body_coverage_status = "NO_ELIGIBLE_DOCUMENTS"
        elif all_hkex_bodies_captured:
            hkex_body_coverage_status = "COMPLETE"
        else:
            hkex_body_coverage_status = "PARTIAL"
        batch["hkex_official_supplement"] = {
            "directory_product_run_ids": sorted(hkex_run_ids),
            "directory_document_count": len(hkex_documents),
            "eligible_document_count": len(eligible_hkex_documents),
            "excluded_document_count": sum(item["status"] == "NOT_ELIGIBLE" for item in hkex_directory_eligibility),
            "unresolved_document_count": sum(item["status"] == "UNRESOLVED" for item in hkex_directory_eligibility),
            "body_variant_count": len(hkex_variants),
            "body_status_counts": dict(sorted(hkex_status_counts.items())),
            "body_coverage_status": hkex_body_coverage_status,
            "unresolved_source_identity_gap": unresolved_hkex_documents > 0,
            "cross_source_link_status": "NOT_ASSESSED",
            "directory_readback_sha256": digest(json_bytes(hkex_directory_readback),),
        }
        if unresolved_hkex_documents:
            batch_status = "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS"
    atomic_json(receipt_path, batch)
    return batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-read", required=True,
        help="exact verified owner GET /announcements date-catalog response JSON")
    parser.add_argument("--material-root", required=True,
        help="the existing shared manager MaterialStore root")
    parser.add_argument("--output-root", required=True,
        help="run-local output directory; never the owner or shared source store")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--publication-date", required=True)
    parser.add_argument("--canary-article", default=None,
        help=("capture only the explicitly authorized 20261008/2026-10-07 article "
              "AN202610071830178357; emits CANARY_PARTIAL, never full-batch import inputs"))
    args = parser.parse_args()
    result = run_capture(read_json(args.catalog_read), args.material_root, args.output_root,
        args.target_date, args.publication_date, canary_article=args.canary_article)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
