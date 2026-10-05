#!/usr/bin/env python3
"""Merge frozen v1, v2, the original three canaries, and the 23 PDF receipts."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import capture_body_corpus as base
import capture_overlimit_pdfs_v3 as pdf_capture

OUT = base.OUT
V1 = OUT / "body_corpus_20260929.json"
V2 = OUT / "body_corpus_20260929_v2.json"
CANARY = OUT / "missing_page1_canary_20260929.json"
PDF_RUN = OUT / "overlimit_pdf_capture_20260929_v3" / "capture_manifest.json"
PDF_RECEIPTS = OUT / "overlimit_pdf_capture_20260929_v3" / "receipts"
OUTPUT_JSON = OUT / "body_corpus_20260929_v3.json"
OUTPUT_CSV = OUT / "body_corpus_20260929_v3.csv"
OUTPUT_RECEIPT = OUT / "body_corpus_20260929_v3_receipt.json"
FROZEN_V1_SHA = "0978ae6fc652b2ee9ffda64575b642816046088c278416168bad39bd330a7ec4"
FROZEN_V2_SHA = "b94a3b56497da4f74faaedbdc1f2d1dfed310eedf63c30639f399fb5fae32e4f"
FROZEN_CANARY_SHA = "1f1f731384fbe4d5c3078a40f63b0c2293b83127bf432b5dc2b2a4f7fda4f3b5"
FROZEN_PDF_TARGET_SHA = pdf_capture.FROZEN_TARGET_SHA
MAX_PAGE_LIMIT = 20


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canon_sha(value: Any) -> str:
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def refs_and_rows(api: Mapping[str, Any], store: Any) -> tuple[dict, dict]:
    raws = {path: path.read_bytes() for path in (V1, V2, CANARY)}
    expected = {V1: FROZEN_V1_SHA, V2: FROZEN_V2_SHA, CANARY: FROZEN_CANARY_SHA}
    for path, raw in raws.items():
        if sha(raw) != expected[path]:
            raise ValueError(f"FROZEN_SOURCE_SHA_MISMATCH:{path.name}")
    v1 = json.loads(raws[V1].decode("utf-8"))
    v2 = json.loads(raws[V2].decode("utf-8"))
    canary = json.loads(raws[CANARY].decode("utf-8"))
    rows = {r["art_code"]: dict(r) for r in v1["rows"]}
    if len(rows) != 234:
        raise ValueError("V1_ROW_COUNT_NOT_234")
    v2_by_code = {r["art_code"]: r for r in v2["rows"]}
    if len(v2_by_code) != 234:
        raise ValueError("V2_ROW_COUNT_NOT_234")
    for code, row in rows.items():
        if row.get("body_status") != "MISSING_PAGE1":
            continue
        refreshed = v2_by_code.get(code)
        if refreshed and refreshed.get("body_status") != "MISSING_PAGE1":
            rows[code] = dict(refreshed)
    for item in canary.get("results", []):
        code = item.get("art_code")
        if code not in rows or rows[code].get("body_status") != "MISSING_PAGE1":
            raise ValueError(f"CANARY_DOES_NOT_REPLACE_V1_MISSING_ROW:{code}")
        receipts = sorted(item.get("content_receipts", []), key=lambda r: int(r.get("page_index", 0)))
        page_rows = []
        body_parts = []
        for receipt in receipts:
            if receipt.get("status") != "CAPTURED" or not isinstance(receipt.get("source_ref"), Mapping):
                raise ValueError(f"CANARY_CONTENT_RECEIPT_INCOMPLETE:{code}")
            raw = api["read_eastmoney_response"](store, receipt["source_ref"])
            if sha(raw) != receipt.get("raw_body_sha256") or len(raw) != receipt.get("response_bytes"):
                raise ValueError(f"CANARY_CONTENT_REF_READBACK_MISMATCH:{code}:{receipt.get('page_index')}")
            meta = receipt["content_metadata"]
            if meta.get("art_code") != code or base.notice_day(meta.get("notice_date")) != "2026-09-29":
                raise ValueError(f"CANARY_CONTENT_IDENTITY_MISMATCH:{code}")
            if sha(str(meta.get("notice_content", "")).encode()) != meta.get("text_sha256"):
                raise ValueError(f"CANARY_CONTENT_TEXT_SHA_MISMATCH:{code}")
            body_parts.append(str(meta.get("notice_content", "")))
            page_rows.append({"page_index": int(receipt["page_index"]),
                "page_total": meta.get("page_total"), "notice_date": meta.get("notice_date"),
                "notice_title": meta.get("notice_title"), "attach_url_web": meta.get("attachment_url"),
                "raw_body_sha256": receipt.get("raw_body_sha256"), "text_sha256": meta.get("text_sha256"),
                "text_characters": meta.get("text_characters"), "retrieved_at": receipt.get("retrieved_at"),
                "source_ref": receipt["source_ref"], "text": meta.get("notice_content", "")})
        total = item.get("content_page_total")
        page_indexes = [r["page_index"] for r in page_rows]
        if page_indexes != list(range(1, len(page_indexes) + 1)) or not page_rows:
            raise ValueError(f"CANARY_PAGE_INDEX_SEQUENCE_INVALID:{code}")
        text = "\n\n".join(body_parts)
        body_status = ("OVER_CONTENT_PAGE_LIMIT" if type(total) is not int or total > MAX_PAGE_LIMIT
                       else "COMPLETE_CONTENT_API_BODY")
        pdf_receipt = item.get("pdf_receipt") or {}
        pdf_ref = pdf_receipt.get("source_ref")
        if pdf_receipt.get("pdf_signature_valid") and isinstance(pdf_ref, Mapping):
            pdf_raw = api["read_eastmoney_response"](store, pdf_ref)
            if (not pdf_raw.startswith(b"%PDF") or sha(pdf_raw) != pdf_receipt.get("pdf_sha256")
                    or len(pdf_raw) != pdf_receipt.get("response_bytes")):
                raise ValueError(f"CANARY_PDF_READBACK_MISMATCH:{code}")
            pdf_status = "VALID_PDF_BYTES"
        else:
            pdf_raw = b""
            pdf_status = "CAPTURE_FAILED"
        first = page_rows[0]
        rows[code] = {"art_code": code, "title": item.get("title"),
            "body_status": body_status, "body_text": text if body_status == "COMPLETE_CONTENT_API_BODY" else None,
            "partial_body_text": text if body_status != "COMPLETE_CONTENT_API_BODY" else None,
            "body_text_characters": len(text),
            "body_text_sha256": sha(text.encode()) if body_status == "COMPLETE_CONTENT_API_BODY" else None,
            "partial_body_text_sha256": sha(text.encode()) if body_status != "COMPLETE_CONTENT_API_BODY" else None,
            "content_page_count": total, "present_page_indexes": page_indexes,
            "pages": page_rows, "content_notice_date": first.get("notice_date"),
            "content_display_time": item.get("content_receipts", [{}])[0].get("content_metadata", {}).get("display_time"),
            "attachment_url": first.get("attach_url_web"),
            "pdf_status": pdf_status, "pdf_ref": pdf_ref,
            "pdf_bytes": len(pdf_raw) if pdf_raw else None,
            "pdf_sha256": sha(pdf_raw) if pdf_raw else None,
            "pdf_capture_receipt_path": str(OUT / "canary_receipts" / "receipts" / f"{code}.pdf.ppdf.json"),
            "matched_master_codes": rows[code].get("matched_master_codes", []),
            "hk_source_stock_codes_116": rows[code].get("hk_source_stock_codes_116", []),
            "listing_evidence": item.get("listing_evidence"),
            "provenance_overlay": {"source": "missing_page1_canary_20260929.json",
                "source_sha256": FROZEN_CANARY_SHA, "content_api_capture": "original_frozen_canary"}}
    return rows, {"v1": v1, "v2": v2, "canary": canary}


def pdf_receipts(api: Mapping[str, Any], store: Any) -> dict[str, dict]:
    manifest = json.loads(PDF_RUN.read_text(encoding="utf-8"))
    if (manifest.get("target_manifest_sha256") != FROZEN_PDF_TARGET_SHA
            or manifest.get("target_count") != 23 or manifest.get("processed_count") != 23
            or manifest.get("source_body_page_fetches") != 0 or manifest.get("failed_url_retries") != 0):
        raise ValueError("V3_PDF_CAPTURE_MANIFEST_NOT_TERMINAL")
    targets = json.loads(pdf_capture.TARGETS.read_text(encoding="utf-8"))["targets"]
    by_code = {}
    for target in targets:
        marker_path, receipt_path, _key = pdf_capture.path_pair(target["attachment_url"])
        if not marker_path.is_file() or not receipt_path.is_file():
            raise ValueError(f"PDF_TARGET_NO_TERMINAL_RECEIPT:{target['art_code']}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("art_code") != target["art_code"] or receipt.get("request_url") != target["attachment_url"]:
            raise ValueError(f"PDF_TARGET_RECEIPT_BINDING_MISMATCH:{target['art_code']}")
        ref = receipt.get("source_ref")
        if receipt.get("status") == "CAPTURED_VALID_PDF":
            if not isinstance(ref, Mapping) or ref.get("request", {}).get("url") != target["attachment_url"]:
                raise ValueError(f"PDF_RECEIPT_SOURCE_REF_MISMATCH:{target['art_code']}")
            raw = api["read_eastmoney_response"](store, ref)
            if (not raw.startswith(b"%PDF") or sha(raw) != receipt.get("pdf_sha256")
                    or len(raw) != receipt.get("response_bytes")):
                raise ValueError(f"PDF_RECEIPT_READBACK_MISMATCH:{target['art_code']}")
        elif receipt.get("status") not in {"CAPTURE_FAILED", "HTTP_FAILED", "INVALID_PDF_BYTES", "ATTEMPT_INDETERMINATE_NO_RETRY"}:
            raise ValueError(f"PDF_RECEIPT_NONTERMINAL:{target['art_code']}:{receipt.get('status')}")
        by_code[target["art_code"]] = receipt
    if len(by_code) != 23:
        raise ValueError("PDF_RECEIPT_UNIQUE_TARGET_COUNT_INVALID")
    return by_code


def validate_page_refs(api: Mapping[str, Any], store: Any, rows: dict[str, dict]) -> None:
    for code, row in rows.items():
        pages = row.get("pages") or []
        body_status = row.get("body_status")
        if body_status == "COMPLETE_CONTENT_API_BODY":
            if row.get("present_page_indexes") != list(range(1, int(row.get("content_page_count", 0)) + 1)):
                raise ValueError(f"COMPLETE_BODY_PAGE_COVERAGE_INVALID:{code}")
        page_texts = []
        for page in pages:
            ref = page.get("source_ref")
            if not isinstance(ref, Mapping):
                raise ValueError(f"PAGE_SOURCE_REF_MISSING:{code}:{page.get('page_index')}")
            request_url = ref.get("request", {}).get("url")
            raw = api["read_eastmoney_response"](store, ref)
            expected_raw_sha = page.get("raw_body_sha256") or ref.get("body_sha256")
            if sha(raw) != expected_raw_sha or sha(raw) != ref.get("body_sha256"):
                raise ValueError(f"PAGE_SOURCE_RAW_SHA_MISMATCH:{code}:{page.get('page_index')}")
            detail = base.parse_content(raw)
            if (detail.get("art_code") != code or detail.get("page_size") != row.get("content_page_count")
                    or int(detail.get("page_index") or page.get("page_index")) != int(page.get("page_index"))
                    or base.notice_day(detail.get("notice_date")) != "2026-09-29"):
                raise ValueError(f"PAGE_SOURCE_IDENTITY_MISMATCH:{code}:{page.get('page_index')}")
            text = detail.get("notice_content")
            if not isinstance(text, str) or sha(text.encode()) != page.get("text_sha256"):
                raise ValueError(f"PAGE_SOURCE_TEXT_SHA_MISMATCH:{code}:{page.get('page_index')}")
            if page.get("text") != text:
                raise ValueError(f"PAGE_TEXT_READBACK_MISMATCH:{code}:{page.get('page_index')}")
            if not isinstance(request_url, str) or f"art_code={code}" not in request_url:
                raise ValueError(f"PAGE_SOURCE_URL_BINDING_MISMATCH:{code}:{page.get('page_index')}")
            page_texts.append(text)
        joined = "\n\n".join(page_texts)
        if row.get("body_status") == "COMPLETE_CONTENT_API_BODY":
            if joined != row.get("body_text") or sha(joined.encode()) != row.get("body_text_sha256"):
                raise ValueError(f"ROW_BODY_TEXT_JOIN_MISMATCH:{code}")
        elif pages:
            if joined != row.get("partial_body_text") and row.get("partial_body_text") is not None:
                raise ValueError(f"ROW_PARTIAL_BODY_TEXT_JOIN_MISMATCH:{code}")
            if row.get("body_text") is not None or row.get("body_text_sha256") is not None:
                raise ValueError(f"OVERLIMIT_ROW_MISLABELLED_AS_FULL_BODY:{code}")
        pdf_ref = row.get("pdf_ref")
        if row.get("pdf_status") == "VALID_PDF_BYTES":
            if not isinstance(pdf_ref, Mapping):
                raise ValueError(f"VALID_PDF_REF_MISSING:{code}")
            raw_pdf = api["read_eastmoney_response"](store, pdf_ref)
            if (not raw_pdf.startswith(b"%PDF") or sha(raw_pdf) != row.get("pdf_sha256")
                    or len(raw_pdf) != row.get("pdf_bytes") or row.get("attachment_url") != pdf_ref.get("request", {}).get("url")):
                raise ValueError(f"PDF_SOURCE_REF_MISMATCH:{code}")


def build() -> dict:
    api = base.imports()
    store, _provider = base.make_provider(api)
    rows, source_docs = refs_and_rows(api, store)
    new_receipts = pdf_receipts(api, store)
    for code, receipt in new_receipts.items():
        row = rows[code]
        row["pdf_capture_receipt_path"] = str(PDF_RECEIPTS / f"{pdf_capture.sha(str(row['attachment_url']).encode())}.json")
        row["pdf_capture_status"] = receipt.get("status")
        row["pdf_ref"] = receipt.get("source_ref")
        row["pdf_bytes"] = receipt.get("response_bytes")
        row["pdf_sha256"] = receipt.get("pdf_sha256")
        row["pdf_status"] = "VALID_PDF_BYTES" if receipt.get("status") == "CAPTURED_VALID_PDF" else receipt.get("status")
        row.setdefault("provenance_overlay", {})
        row["provenance_overlay"].update({"pdf_capture_manifest_sha256": sha(PDF_RUN.read_bytes()),
            "pdf_target_manifest_sha256": FROZEN_PDF_TARGET_SHA,
            "capture_attempt_path": receipt.get("attempt_path"),
            "pdf_receipt_path": row["pdf_capture_receipt_path"]})
    validate_page_refs(api, store, rows)
    ordered = sorted(rows.values(), key=lambda r: r["art_code"])
    body_counts = Counter(r.get("body_status") for r in ordered)
    pdf_counts = Counter(r.get("pdf_status") for r in ordered)
    if body_counts != Counter({"COMPLETE_CONTENT_API_BODY": 207, "OVER_CONTENT_PAGE_LIMIT": 27}):
        raise ValueError(f"BODY_V3_COUNTS_WRONG:{dict(body_counts)}")
    if pdf_counts != Counter({"VALID_PDF_BYTES": 226, "CAPTURE_FAILED": 5, "PDF_REF_MISSING": 3}):
        raise ValueError(f"PDF_V3_COUNTS_WRONG:{dict(pdf_counts)}")
    payload = {"schema": "v4.manager_research.eastmoney_hk_announcement_body_corpus.v3",
        "target_notice_date": "2026-09-29", "article_count": 234,
        "body_status_counts": dict(body_counts), "pdf_status_counts": dict(pdf_counts),
        "body_limit_pages": MAX_PAGE_LIMIT,
        "body_limit_characters": api["MAX_EASTMONEY_BODY_CHARACTERS"],
        "interpretation": "207 body-complete; 27 over the content API page limit, of which 22 have valid PDFs available for retrospective local derivation and 5 retain terminal PDF capture failures; 3 complete-body rows have no PDF ref. No source row is silently counted as zero or omitted.",
        "pit_status": "CANNOT_CONFIRM", "first_publication_status": "CANNOT_CONFIRM",
        "body_sources": {"v1_sha256": FROZEN_V1_SHA, "v2_sha256": FROZEN_V2_SHA,
            "original_canary_sha256": FROZEN_CANARY_SHA,
            "pdf_target_manifest_sha256": FROZEN_PDF_TARGET_SHA,
            "pdf_capture_manifest_sha256": sha(PDF_RUN.read_bytes())},
        "source_refs_verified_via": "existing MaterialStore read_eastmoney_response; no catalog/content-directory re-fetch",
        "rows": ordered}
    atomic_json(OUTPUT_JSON, payload)
    fieldnames = ["art_code", "title", "body_status", "content_page_count", "present_page_indexes",
        "body_text_characters", "body_text_sha256", "body_ref_count", "pdf_status", "pdf_bytes",
        "pdf_sha256", "pdf_capture_status", "pdf_capture_receipt_path", "attachment_url",
        "listing_evidence", "matched_master_codes", "hk_source_stock_codes_116"]
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in ordered:
            csvrow = dict(row)
            csvrow["body_ref_count"] = len(row.get("pages", []))
            csvrow["present_page_indexes"] = json.dumps(row.get("present_page_indexes", []), ensure_ascii=False)
            csvrow["listing_evidence"] = json.dumps(row.get("listing_evidence"), ensure_ascii=False)
            csvrow["matched_master_codes"] = json.dumps(row.get("matched_master_codes", []), ensure_ascii=False)
            csvrow["hk_source_stock_codes_116"] = json.dumps(row.get("hk_source_stock_codes_116", []), ensure_ascii=False)
            writer.writerow(csvrow)
    receipt = {"schema": "v4.manager_research.eastmoney_hk_announcement_body_corpus_v3_receipt.v1",
        "status": "PASS_234_BODY_REF_READBACK", "body_corpus_path": str(OUTPUT_JSON),
        "body_corpus_sha256": sha(OUTPUT_JSON.read_bytes()), "csv_path": str(OUTPUT_CSV),
        "csv_sha256": sha(OUTPUT_CSV.read_bytes()), "article_count": len(ordered),
        "body_status_counts": dict(body_counts), "pdf_status_counts": dict(pdf_counts),
        "unique_art_codes": len({r["art_code"] for r in ordered}),
        "all_page_refs_readback_verified": True, "all_valid_pdf_refs_readback_verified": True,
        "pit_status": "CANNOT_CONFIRM", "first_publication_status": "CANNOT_CONFIRM",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    atomic_json(OUTPUT_RECEIPT, receipt)
    print(json.dumps(receipt, ensure_ascii=False))
    return receipt


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "build-v3":
        raise SystemExit("usage: build_body_corpus_v3.py build-v3")
    build()
