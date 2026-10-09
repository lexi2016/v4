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
import sys
import time
from uuid import uuid4
from typing import Any, Mapping
from urllib.parse import urlsplit

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
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


def _mkdir_output(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def atomic_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json_bytes(value)
    tmp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        tmp.write_bytes(raw)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
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
        capture_eastmoney,
        eastmoney_content_url,
        read_eastmoney_response,
        safe_reason,
    )
    from v4.manager_research.hkex_provider import HkexOfficialProvider, _safe_eastmoney_hk_url
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
    """Independent in-flight cap and start pacing with per-request byte leases.

    The condition protects only admission/accounting. HTTP, store writes and
    readback run outside it. Each thread owns at most one opaque request id;
    repeated settlement/release cannot spend or release another request's lease.
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
        self._condition = threading.Condition(threading.Lock())
        self._slots = threading.BoundedSemaphore(WORKERS)
        self._local = threading.local()
        self._leases: dict[str, dict[str, Any]] = {}
        self._admission_stop: str | None = None
        self._unknown_requests = 0
        self._http_policy: dict[str, Any] | None = None

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started)

    def check(self) -> None:
        if self.elapsed_seconds >= self.seconds:
            raise RuntimeError("BODY_BATCH_TIME_BUDGET_EXHAUSTED")

    def before_request(self) -> None:
        if getattr(self._local, "request_id", None) is not None:
            raise RuntimeError("BODY_BATCH_REQUEST_ALREADY_ACTIVE")
        self.check()
        if not self._slots.acquire(timeout=max(0.0, self.seconds - self.elapsed_seconds)):
            raise RuntimeError("BODY_BATCH_TIME_BUDGET_EXHAUSTED")
        admitted = False
        try:
            with self._condition:
                while True:
                    self.check()
                    if self._admission_stop:
                        raise RuntimeError(self._admission_stop)
                    if self.requests >= self.max_requests:
                        raise RuntimeError("BODY_BATCH_REQUEST_BUDGET_EXHAUSTED")
                    reserved = sum(int(lease["reserved"] or 0) for lease in self._leases.values())
                    if self.response_bytes + reserved + self.max_response_bytes > self.max_response_bytes_total:
                        raise RuntimeError("BODY_BATCH_RESPONSE_BYTE_BUDGET_EXHAUSTED")
                    wait = (0.0 if self._last is None else
                            max(0.0, self.interval - (time.monotonic() - self._last)))
                    if not wait:
                        request_id = uuid4().hex
                        self._leases[request_id] = {"reserved": self.max_response_bytes, "settled": None, "observed": 0, "unknown": False}
                        self._local.request_id = request_id
                        self.requests += 1
                        self._last = time.monotonic()
                        admitted = True
                        return
                    # Condition.wait releases the short accounting lock. Both
                    # pacing and semaphore waits remain bounded by the deadline.
                    self._condition.wait(timeout=min(wait, max(0.0, self.seconds - self.elapsed_seconds)))
        finally:
            if not admitted:
                self._slots.release()

    @property
    def max_response_bytes_total(self) -> int:
        return getattr(self, "_max_response_bytes_total", self.max_response_bytes)

    def set_response_limits(self, *, per_response: int, total: int) -> None:
        with self._condition:
            if self.requests or self._leases:
                raise RuntimeError("BODY_BATCH_RESPONSE_LIMITS_ALREADY_ACTIVE")
            if type(per_response) is not int or type(total) is not int or not 0 < per_response <= total:
                raise ValueError("BODY_BATCH_RESPONSE_LIMITS_INVALID")
            self.max_response_bytes = per_response
            self._max_response_bytes_total = total

    def _account_observed(self, lease: dict[str, Any], size: int) -> None:
        # Called with the condition held. Totals are cumulative per request;
        # the transport, provider and source may report the same total again.
        if type(size) is not int or size < lease["observed"]:
            raise ValueError("BODY_BATCH_RESPONSE_SIZE_INVALID")
        delta = size - lease["observed"]
        lease["observed"] = size
        lease["reserved"] = max(0, lease["reserved"] - delta)
        self.response_bytes += delta
        reserved = sum(item["reserved"] for item in self._leases.values())
        if self.response_bytes + reserved > self.max_response_bytes_total:
            # An opaque injected transport can return more than its reservation.
            # Retain the exact evidence, then stop; never pretend the bytes fit.
            self._admission_stop = "BODY_BATCH_RESPONSE_BYTE_BUDGET_EXHAUSTED"
        self._condition.notify_all()

    def reserve_transport_read(self, requested: int) -> int:
        """Bound the next read, including the over-limit probe, before it runs."""
        if type(requested) is not int or requested < 1:
            raise ValueError("BODY_BATCH_READ_SIZE_INVALID")
        with self._condition:
            self.check()
            if self._admission_stop:
                raise RuntimeError(self._admission_stop)
            lease = self._leases.get(getattr(self._local, "request_id", None))
            if lease is None or lease["settled"] is not None:
                raise RuntimeError("BODY_BATCH_READ_WITHOUT_ACTIVE_REQUEST")
            reserved = sum(item["reserved"] for item in self._leases.values())
            available = max(0, self.max_response_bytes_total - self.response_bytes - reserved)
            allowed = min(requested, lease["reserved"] + available)
            if allowed <= 0:
                raise RuntimeError("BODY_BATCH_RESPONSE_BYTE_BUDGET_EXHAUSTED")
            lease["reserved"] = max(lease["reserved"], allowed)
            return allowed

    def record_transport_progress(self, size: int) -> None:
        """Record proven bytes even if the next read or validation will fail."""
        with self._condition:
            lease = self._leases.get(getattr(self._local, "request_id", None))
            if lease is None:
                raise RuntimeError("BODY_BATCH_PROGRESS_WITHOUT_ACTIVE_REQUEST")
            self._account_observed(lease, size)

    def mark_transport_unknown(self) -> None:
        with self._condition:
            lease = self._leases.get(getattr(self._local, "request_id", None))
            if lease is not None and not lease["unknown"]:
                lease["unknown"] = True
                self._unknown_requests += 1
            if self._http_policy is None:
                self._admission_stop = "BODY_BATCH_TRANSPORT_CONSUMPTION_UNKNOWN"
            self._condition.notify_all()

    def record_http_policy(self, policy: Mapping[str, Any]) -> None:
        # Already sanitized by the provider; retain only the published contract.
        allowed = ("status_code", "reason", "action", "retry_after_raw",
                   "retry_after_seconds", "cooldown_until_utc", "automatic_retry")
        clean = {key: policy.get(key) for key in allowed}
        with self._condition:
            previous = self._http_policy
            if (previous is None or (previous["action"] != "STOP" and clean["action"] == "STOP")
                    or (previous["action"] == clean["action"] == "STOP_AND_COOLDOWN"
                        and str(clean["cooldown_until_utc"]) > str(previous["cooldown_until_utc"]))):
                self._http_policy = clean
            self._admission_stop = "BODY_BATCH_" + str(self._http_policy["reason"]) + "_STOP"
            self._condition.notify_all()

    def accounting_snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {"scope": "THIS_GATE", "observed_response_bytes": self.response_bytes,
                    "unknown_consumption_requests": self._unknown_requests,
                    "admission_stop_reason": self._admission_stop,
                    "physical_network_bytes_verified": False,
                    "http_policy": dict(self._http_policy) if self._http_policy is not None else None}

    def record_response_bytes(self, size: int) -> None:
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("BODY_BATCH_RESPONSE_SIZE_INVALID")
        with self._condition:
            lease = self._leases.get(getattr(self._local, "request_id", None))
            if lease is None:
                self.check()  # Cache hits have no transport admission.
                return
            if lease["settled"] is not None and lease["settled"] != size:
                raise RuntimeError("BODY_BATCH_RESPONSE_SETTLEMENT_MISMATCH")
            self._account_observed(lease, size)
            lease["settled"] = size
            lease["reserved"] = 0
            if size > self.max_response_bytes or self.response_bytes > self.max_response_bytes_total:
                raise RuntimeError("BODY_BATCH_RESPONSE_BYTE_BUDGET_EXHAUSTED")
            self.check()

    def record_transport_response(self, size: int) -> None:
        self.record_response_bytes(size)

    def end_request(self) -> None:
        with self._condition:
            request_id = getattr(self._local, "request_id", None)
            if request_id is None:
                return
            self._local.request_id = None
            lease = self._leases.pop(request_id, None)
            if lease is not None:
                self._slots.release()
                self._condition.notify_all()


class _WorkerProviders:
    """Reuse one provider/opener per worker; share only the material store."""
    def __init__(self, api: Mapping[str, Any], store: Any, gate: SharedCaptureGate | None = None):
        self.api = api
        self.store = store
        self.gate = gate
        self.local = threading.local()

    def get(self) -> Any:
        if not hasattr(self.local, "provider"):
            self.local.provider = self.api["HkexOfficialProvider"](material_store=self.store, timeout=20.0)
            if self.gate is not None:
                self.local.provider._capture_policy = self.gate
        return self.local.provider


def _capture_worker(api: Mapping[str, Any], store: Any, providers: _WorkerProviders,
                    gate: SharedCaptureGate, row: Mapping[str, Any], output: Path,
                    target: str, publication: str) -> dict[str, Any]:
    return _capture_article(api, store, providers.get(), gate, row, output, target, publication)


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
    from infrastructure.owned_io import SafeRoot
    # Serialize the same URL's attempt/receipt transition, not unrelated HTTP.
    with SafeRoot(out_root).kernel_lock(".locks/url-" + digest(url.encode("utf-8")) + ".mutex",
                                       timeout=max(0.0, gate.seconds - gate.elapsed_seconds)):
        return _capture_url_owned(api, store, provider, gate, url, art_code=art_code,
                                  page_index=page_index, kind=kind, out_root=out_root)


def _capture_url_owned(api: Mapping[str, Any], store: Any, provider: Any, gate: SharedCaptureGate,
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
        receipt["byte_accounting"] = gate.accounting_snapshot()
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
        "attachment_url": None, "body_status": status, "transport_body_status": status,
        "transport_first_hkex_publication_time": "CANNOT_CONFIRM",
        "transport_pit_status": "CANNOT_CONFIRM", "transport_semantic_status": "NOT_REVIEWED",
        "body_text": body_file.get("body_text"), "body_text_sha256": body_file.get("body_text_sha256"),
        "content_page_count": body_file.get("content_api_pages", [{}])[0].get("page_total") if pages else None,
        "pages": pages, "pdf_sha256": None, "capture_receipt_sha256": item.get("body_file_sha256")}


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
                api_overrides: Mapping[str, Any] | None = None,
                capture_gate: SharedCaptureGate | None = None) -> dict[str, Any]:
    from infrastructure.owned_io import SafeRoot
    # One batch owner, including canary; marker checks and all aggregate writes
    # stay within this lease. Existing incomplete markers still forbid retries.
    # Lock a sibling path so the canary's output-must-not-exist guard remains
    # meaningful. Never unlink this persistent flock inode after release.
    output = SafeRoot(output_root).root
    lock_name = ".locks/body-batch-" + digest(output.name.encode("utf-8")) + ".mutex"
    with SafeRoot(output.parent).kernel_lock(lock_name, timeout=0):
        return _run_capture_owned(catalog_read, material_root, output_root,
            target_trade_date, publication_date, canary_article=canary_article,
            api_overrides=api_overrides, capture_gate=capture_gate)


def _run_capture_owned(catalog_read: Mapping[str, Any], material_root: str | Path,
                output_root: str | Path, target_trade_date: str, publication_date: str,
                *, canary_article: str | None = None,
                api_overrides: Mapping[str, Any] | None = None,
                capture_gate: SharedCaptureGate | None = None) -> dict[str, Any]:
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
    rows = _validate_catalog(api, catalog_read, store, target_trade_date, publication_date)
    catalog = _catalog_product(catalog_read)
    output = Path(output_root)
    if canary_article is not None:
        if capture_gate is not None:
            raise ValueError("BODY_BATCH_SHARED_GATE_CANARY_NOT_SUPPORTED")
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
    _mkdir_output(output)
    if marker.exists() or receipt_path.exists():
        raise RuntimeError("BODY_BATCH_ATTEMPT_EXISTS_NO_RETRY")
    associations = sum(len(row["source_issuer_codes"]) for row in rows)
    distinct_codes = sorted({identity["code"] for row in rows for identity in row["source_issuer_codes"]})
    catalog_identity = {"target_trade_date": target_trade_date, "publication_date": publication_date,
        "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
        "article_ids": [row["art_code"] for row in rows],
        "listing_body_sha256s": [row["raw_body_sha256"] for row in rows]}
    input_identity_sha = digest(json_bytes(catalog_identity))
    started_at = utc_now()
    atomic_json(marker, {"schema": "v4.manager_research.body_batch_attempt.v1", "started_at": started_at,
        **catalog_identity, "input_identity_sha256": input_identity_sha, "article_count": len(rows),
        "workers": WORKERS, "max_seconds": MAX_SECONDS, "max_network_requests": MAX_NETWORK_REQUESTS,
        "max_response_bytes": MAX_RESPONSE_BYTES, "max_extended_content_pages": MAX_EXTENDED_CONTENT_PAGES,
        "max_body_characters": MAX_EXTENDED_BODY_CHARACTERS, "one_attempt_only": True})
    gate = capture_gate
    if gate is None:
        gate = SharedCaptureGate(seconds=MAX_SECONDS, max_requests=MAX_NETWORK_REQUESTS,
            max_bytes=MAX_RESPONSE_BYTES, interval=REQUEST_INTERVAL_SECONDS)
        gate.set_response_limits(per_response=api["MAX_EASTMONEY_RESPONSE_BYTES"], total=MAX_RESPONSE_BYTES)
    elif (gate.seconds != MAX_SECONDS or gate.max_requests != MAX_NETWORK_REQUESTS
            or gate.max_response_bytes_total != MAX_RESPONSE_BYTES
            or gate.max_response_bytes != api["MAX_EASTMONEY_RESPONSE_BYTES"]
            or gate.interval != REQUEST_INTERVAL_SECONDS):
        raise ValueError("BODY_BATCH_OWNER_GATE_LIMITS_MISMATCH")
    providers = _WorkerProviders(api, store, gate)
    by_art: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="hk-ann-body") as pool:
        futures = {pool.submit(_capture_worker, api, store, providers, gate, row, output,
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
                "response_bytes": gate.response_bytes, "byte_accounting": gate.accounting_snapshot(),
                "elapsed_seconds": round(gate.elapsed_seconds, 3),
                "updated_at": utc_now()})
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
            "byte_accounting": gate.accounting_snapshot(),
            "max_response_bytes": MAX_RESPONSE_BYTES, "max_extended_content_pages": MAX_EXTENDED_CONTENT_PAGES,
            "max_body_characters": MAX_EXTENDED_BODY_CHARACTERS,
            "elapsed_seconds": round(gate.elapsed_seconds, 3),
            "request_interval_seconds": REQUEST_INTERVAL_SECONDS}, "generated_at": utc_now()}
    manifest_sha = atomic_json(output / "body_corpus_manifest.json", body_manifest)
    complete = status_counts.get("COMPLETE_CONTENT_API_BODY", 0)
    body_corpus = {"schema": "v4.manager_research.eastmoney_hk_announcement_body_corpus.v3",
        "target_notice_date": publication_date, "article_count": len(corpus_rows),
        "transport_complete_body_count": complete, "rows": corpus_rows,
        "source_manifest_artifact": "body_corpus_manifest.json",
        "source_manifest_sha256": manifest_sha, "semantic_status": "NOT_REVIEWED",
        "input_identity_sha256": input_identity_sha}
    corpus_sha = atomic_json(output / "body_corpus.json", body_corpus)
    batch_status = ("PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS" if complete == len(rows)
        else "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS")
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
