#!/usr/bin/env python3
"""Single-attempt capture of the frozen 23 over-limit PDF attachments.

Only the exact URLs frozen in over_content_pdf_targets_20260929_v3.json are
eligible. Page-1 API bodies are read from their existing MaterialStore refs for
identity validation; this script never requests content pages or directories.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import capture_body_corpus as base

OUT = base.OUT
SOURCE_V1 = OUT / "body_corpus_20260929.json"
TARGETS = OUT / "over_content_pdf_targets_20260929_v3.json"
V2 = OUT / "body_corpus_20260929_v2.json"
RUN_DIR = OUT / "overlimit_pdf_capture_20260929_v3"
ATTEMPTS = RUN_DIR / "attempts"
RECEIPTS = RUN_DIR / "receipts"
RUNS = RUN_DIR / "runs"
MANIFEST = RUN_DIR / "capture_manifest.json"
FROZEN_SOURCE_SHA = "0978ae6fc652b2ee9ffda64575b642816046088c278416168bad39bd330a7ec4"
FROZEN_TARGET_SHA = "684537f85bd2a3ce23e97409e51bb34aaeb71bb3b9c72d744727b78031f915a7"
MAX_SECONDS = 45.0
MAX_REQUESTS = 57
MAX_BYTES = 64 * 1024 * 1024
PROVIDER_TIMEOUT = 20.0


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha(raw)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def durable_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)
    try:
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def load_frozen_targets() -> tuple[dict, dict[str, dict]]:
    source_raw = SOURCE_V1.read_bytes()
    if sha(source_raw) != FROZEN_SOURCE_SHA:
        raise ValueError("FROZEN_V1_CORPUS_SHA_MISMATCH")
    source = json.loads(source_raw.decode("utf-8"))
    manifest_raw = TARGETS.read_bytes()
    manifest = json.loads(manifest_raw.decode("utf-8"))
    rows = manifest.get("targets")
    if (manifest.get("source_corpus_sha256") != FROZEN_SOURCE_SHA
            or manifest.get("target_manifest_sha256") != FROZEN_TARGET_SHA
            or manifest.get("targets_sha256") != FROZEN_TARGET_SHA
            or not isinstance(rows, list) or len(rows) != 23
            or len({r.get("art_code") for r in rows}) != 23
            or canonical_sha(rows) != FROZEN_TARGET_SHA):
        raise ValueError("FROZEN_23_TARGET_MANIFEST_INVALID")
    source_by_code = {r.get("art_code"): r for r in source.get("rows", [])}
    over_limit_missing = {r.get("art_code") for r in source.get("rows", [])
        if r.get("body_status") == "OVER_CONTENT_PAGE_LIMIT" and r.get("pdf_status") == "PDF_REF_MISSING"}
    if {r.get("art_code") for r in rows} != over_limit_missing:
        raise ValueError("TARGET_SET_NOT_EXACTLY_V1_OVERLIMIT_MISSING_PDFS")
    v2 = json.loads(V2.read_text(encoding="utf-8"))
    protected_failures = {r.get("art_code") for r in v2.get("rows", []) if r.get("pdf_status") == "CAPTURE_FAILED"}
    if protected_failures & {r.get("art_code") for r in rows}:
        raise ValueError("PROTECTED_TERMINAL_FAILURE_IN_TARGET_SET")
    for target in rows:
        art = target.get("art_code")
        source_row = source_by_code.get(art)
        source_pages = source_row.get("pages") if isinstance(source_row, Mapping) else None
        source_page1 = source_pages[0] if isinstance(source_pages, list) and source_pages else None
        ref = target.get("page1_content_ref")
        if (not isinstance(source_row, Mapping) or not isinstance(ref, Mapping)
                or not isinstance(source_page1, Mapping)
                or source_row.get("body_status") != "OVER_CONTENT_PAGE_LIMIT"
                or source_row.get("pdf_status") != "PDF_REF_MISSING"
                or ref != source_page1.get("source_ref")
                or target.get("attachment_url") != source_row.get("attachment_url")
                or target.get("attachment_url") != source_page1.get("attach_url_web")
                or target.get("page1_content_url") != ref.get("request", {}).get("url")
                or target.get("page1_content_raw_body_sha256") != source_page1.get("raw_body_sha256")
                or target.get("content_page_total") != source_page1.get("page_total")):
            raise ValueError(f"FROZEN_PAGE1_BINDING_INVALID:{art}")
    return manifest, source_by_code


def verify_page1_inputs(api: Mapping[str, Any], store: Any, targets: list[dict]) -> None:
    """Read only existing page-1 refs and prove the attachment URL/code join."""
    for target in targets:
        art = target["art_code"]
        ref = target["page1_content_ref"]
        if ref.get("request", {}).get("url") != target.get("page1_content_url"):
            raise ValueError(f"PAGE1_REF_URL_MISMATCH:{art}")
        raw = api["read_eastmoney_response"](store, ref)
        if sha(raw) != target.get("page1_content_raw_body_sha256") or sha(raw) != ref.get("body_sha256"):
            raise ValueError(f"PAGE1_REF_BODY_SHA_MISMATCH:{art}")
        detail = base.parse_content(raw)
        if (detail.get("art_code") != art or base.notice_day(detail.get("notice_date")) != "2026-09-29"
                or detail.get("page_size") != target.get("content_page_total")
                or detail.get("attach_url_web") != target.get("attachment_url")):
            raise ValueError(f"PAGE1_CONTENT_IDENTITY_OR_ATTACHMENT_MISMATCH:{art}")


def path_pair(url: str) -> tuple[Path, Path, str]:
    key = sha(url.encode("utf-8"))
    return ATTEMPTS / f"{key}.attempt.json", RECEIPTS / f"{key}.json", key


def read_prior(api: Mapping[str, Any], store: Any, url: str, receipt_path: Path, marker_path: Path) -> dict | None:
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("request_url") != url:
            raise ValueError("PDF_RECEIPT_URL_COLLISION")
        ref = receipt.get("source_ref")
        if isinstance(ref, Mapping):
            raw = api["read_eastmoney_response"](store, ref)
            if sha(raw) != receipt.get("raw_body_sha256") or len(raw) != receipt.get("response_bytes"):
                raise ValueError("PDF_RECEIPT_READBACK_MISMATCH")
        return receipt
    if marker_path.exists():
        receipt = {"schema": "v4.manager_research.overlimit_pdf_capture_receipt.v3",
            "request_url": url, "request_url_sha256": sha(url.encode()),
            "status": "ATTEMPT_INDETERMINATE_NO_RETRY",
            "attempt_path": str(marker_path), "retrieved_at": None}
        durable_json(receipt_path, receipt)
        return receipt
    return None


def capture_one(api: Mapping[str, Any], store: Any, provider: Any, target: Mapping[str, Any], run_id: str) -> dict:
    art = str(target["art_code"])
    url = str(target["attachment_url"])
    if not api["_safe_eastmoney_url"](url) or f"H2_{art}_1.pdf" not in url:
        raise ValueError(f"FROZEN_PDF_URL_INVALID:{art}")
    marker_path, receipt_path, url_sha = path_pair(url)
    prior = read_prior(api, store, url, receipt_path, marker_path)
    if prior is not None:
        if prior.get("art_code") not in (None, art):
            raise ValueError("PDF_RECEIPT_ART_CODE_MISMATCH")
        return prior
    marker = {"schema": "v4.manager_research.overlimit_pdf_capture_attempt.v3",
        "art_code": art, "request_url": url, "request_url_sha256": url_sha,
        "batch_run_id": run_id, "started_at": now_utc(), "force": False,
        "one_attempt_only": True, "provider_timeout_seconds": PROVIDER_TIMEOUT,
        "per_document_seconds": MAX_SECONDS, "per_document_requests": MAX_REQUESTS,
        "per_document_response_bytes": MAX_BYTES,
        "max_single_response_bytes": api["MAX_EASTMONEY_RESPONSE_BYTES"]}
    durable_json(marker_path, marker)
    receipt = {"schema": "v4.manager_research.overlimit_pdf_capture_receipt.v3",
        "art_code": art, "kind": "pdf", "request_url": url, "request_url_sha256": url_sha,
        "attempt_path": str(marker_path), "batch_run_id": run_id,
        "started_at": marker["started_at"]}
    budget = api["CaptureBudget"](seconds=MAX_SECONDS, max_requests=MAX_REQUESTS,
        interval=0.5, max_response_bytes=MAX_BYTES)
    try:
        ref = api["capture_eastmoney"](provider, url, budget=budget, force=False)
        raw = api["read_eastmoney_response"](store, ref)
        budget.record_response_bytes(len(raw))
        valid_pdf = raw.startswith(b"%PDF")
        receipt.update(source_ref=ref, http_status=ref.get("http_status"),
            final_url=ref.get("final_url"), from_cache=ref.get("from_cache"),
            retrieved_at=ref.get("retrieved_at"), response_bytes=len(raw),
            raw_body_sha256=sha(raw), pdf_signature_valid=valid_pdf,
            pdf_sha256=sha(raw) if valid_pdf else None,
            status=("CAPTURED_VALID_PDF" if ref.get("http_status") == 200 and valid_pdf
                    else "INVALID_PDF_BYTES" if ref.get("http_status") == 200
                    else "HTTP_FAILED"),
            document_budget={"elapsed_seconds": round(budget.elapsed_seconds, 3),
                "requests_used": budget.requests, "response_bytes": budget.response_bytes,
                "max_requests": MAX_REQUESTS, "max_response_bytes": MAX_BYTES})
    except Exception as exc:
        receipt.update(status="CAPTURE_FAILED", error=api["safe_reason"](exc, "PDF_CAPTURE_FAILED"),
            failed_at=now_utc(), document_budget={"elapsed_seconds": round(budget.elapsed_seconds, 3),
                "requests_used": budget.requests, "response_bytes": budget.response_bytes,
                "max_requests": MAX_REQUESTS, "max_response_bytes": MAX_BYTES})
    durable_json(receipt_path, receipt)
    return receipt


def run_capture() -> dict:
    target_manifest, _ = load_frozen_targets()
    api = base.imports()
    store, provider = base.make_provider(api)
    if provider._timeout != PROVIDER_TIMEOUT:
        raise ValueError("PROVIDER_TIMEOUT_CHANGED")
    original_request = provider._request_eastmoney_hk
    def request_with_timeout_cap(url: str, *, timeout: float):
        return original_request(url, timeout=min(float(timeout), PROVIDER_TIMEOUT))
    provider._request_eastmoney_hk = request_with_timeout_cap
    targets = target_manifest["targets"]
    verify_page1_inputs(api, store, targets)
    cache_urls = set(base.load_material_url_index(store))
    already_cached = sorted(t["attachment_url"] for t in targets if t["attachment_url"] in cache_urls)
    if already_cached:
        raise ValueError("TARGET_PDF_ALREADY_HAS_SUCCESSFUL_MATERIALSTORE_FILE")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    documents = []
    previous_end = None
    # The selected minimum-page document is the route canary and is attempted first.
    ordered = sorted(targets, key=lambda t: (t["art_code"] != target_manifest["canary_art_code"], t["art_code"]))
    for index, target in enumerate(ordered, 1):
        if previous_end is not None:
            delay = 0.5 - (time.monotonic() - previous_end)
            if delay > 0:
                time.sleep(delay)
        receipt = capture_one(api, store, provider, target, run_id)
        previous_end = time.monotonic()
        documents.append(receipt)
        statuses = [r.get("status") for r in documents]
        progress = {"schema": "v4.manager_research.overlimit_pdf_capture_run.v3",
            "batch_run_id": run_id, "target_manifest_sha256": FROZEN_TARGET_SHA,
            "target_count": 23, "processed_count": index,
            "status_counts": {s: statuses.count(s) for s in sorted(set(statuses))},
            "art_code": receipt.get("art_code"), "latest_status": receipt.get("status"),
            "updated_at": now_utc()}
        durable_json(RUNS / f"{run_id}.progress.json", progress)
        print(json.dumps({"progress": f"{index}/23", "art_code": receipt.get("art_code"),
            "status": receipt.get("status"), "from_cache": receipt.get("from_cache"),
            "response_bytes": receipt.get("response_bytes")}, ensure_ascii=False), flush=True)
    receipt_map = {r.get("art_code"): r for r in documents}
    if len(receipt_map) != 23 or set(receipt_map) != {t["art_code"] for t in targets}:
        raise ValueError("CAPTURE_RECEIPT_COVERAGE_INVALID")
    statuses = [r.get("status") for r in documents]
    summary = {"schema": "v4.manager_research.overlimit_pdf_capture_run.v3",
        "batch_run_id": run_id, "target_manifest_path": str(TARGETS),
        "target_manifest_sha256": FROZEN_TARGET_SHA, "source_corpus_sha256": FROZEN_SOURCE_SHA,
        "target_count": 23, "processed_count": 23,
        "status_counts": {s: statuses.count(s) for s in sorted(set(statuses))},
        "source_body_page_fetches": 0, "failed_url_retries": 0,
        "capture_receipt_paths": sorted(str(path) for path in RECEIPTS.glob("*.json")),
        "finished_at": now_utc(), "status": "PASS_23_TERMINAL_RECEIPTS"}
    durable_json(RUNS / f"{run_id}.json", summary)
    durable_json(MANIFEST, {**summary, "run_receipt_path": str(RUNS / f"{run_id}.json")})
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "capture-23":
        raise SystemExit("usage: capture_overlimit_pdfs_v3.py capture-23")
    run_capture()
