#!/usr/bin/env python3
"""Full physical-page, local-only text derivation for valid over-limit PDFs."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import capture_body_corpus as base
import capture_missing_page1_v2 as v2_capture

OUT = base.OUT
CORPUS = OUT / "body_corpus_20260929_v3.json"
OUT_DIR = OUT / "pdf_text_derivatives_20260929_v3"
INDEX_JSON = OUT / "pdf_text_derivatives_20260929_v3_index.json"
INDEX_CSV = OUT / "pdf_text_derivatives_20260929_v3_index.csv"
EXISTING_006795 = OUT / "pdf_text_canary_20260929_AN202609291830006795_v2.json"
SEGMENT_LIMIT = 120_000
EXISTING_CANARY_CODE = "AN202609291830006795"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def stored_canary_entry(row: Mapping[str, Any], data: dict) -> dict:
    if data.get("art_code") != EXISTING_CANARY_CODE:
        raise ValueError("EXISTING_CANARY_ART_CODE_MISMATCH")
    if data.get("pdf_sha256") != row.get("pdf_sha256") or data.get("pdf_source_ref") != row.get("pdf_ref"):
        raise ValueError("EXISTING_CANARY_DERIVATION_PDF_BINDING_MISMATCH")
    pages = data.get("pages")
    segments = data.get("segments")
    if (not isinstance(pages, list) or not isinstance(segments, list)
            or data.get("pdf_page_count") != len(pages)
            or data.get("full_page_coverage") != list(range(1, len(pages) + 1))):
        raise ValueError("EXISTING_CANARY_PAGE_COVERAGE_INVALID")
    by_page = {}
    for segment in segments:
        if int(segment.get("text_characters", -1)) > SEGMENT_LIMIT:
            raise ValueError("EXISTING_CANARY_SEGMENT_TOO_LARGE")
        if sha(str(segment.get("text", "")).encode()) != segment.get("text_sha256"):
            raise ValueError("EXISTING_CANARY_SEGMENT_SHA_MISMATCH")
        by_page.setdefault(int(segment["page_index"]), []).append(segment)
    full_parts = []
    for page in pages:
        index = int(page["page_index"])
        items = sorted(by_page.get(index, []), key=lambda x: int(x.get("character_start", 0)))
        text = "".join(str(item.get("text", "")) for item in items)
        if (len(text) != page.get("text_characters")
                or sha(text.encode()) != page.get("text_sha256")
                or [int(s["segment_index"]) for s in items] != page.get("segment_indexes")):
            raise ValueError(f"EXISTING_CANARY_PAGE_RECONSTRUCTION_FAILED:{index}")
        expected_start = 0
        for segment in items:
            if int(segment.get("character_start", -1)) != expected_start:
                raise ValueError(f"EXISTING_CANARY_SEGMENT_GAP:{index}")
            expected_start = int(segment.get("character_end", -1))
        if expected_start != len(text):
            raise ValueError(f"EXISTING_CANARY_PAGE_END_MISMATCH:{index}")
        full_parts.append(text)
    full_text = "\n\n".join(full_parts)
    if (len(full_text) != data.get("full_text_characters")
            or sha(full_text.encode()) != data.get("full_text_sha256")):
        raise ValueError("EXISTING_CANARY_FULL_TEXT_HASH_MISMATCH")
    return {"art_code": row["art_code"], "title": row.get("title"),
        "derivative_status": "PASS_LOCAL_FULL_PHYSICAL_PAGE_COVERAGE",
        "derivative_path": str(EXISTING_006795), "derivative_sha256": sha(EXISTING_006795.read_bytes()),
        "pdf_sha256": row.get("pdf_sha256"), "pdf_bytes": row.get("pdf_bytes"),
        "pdf_source_ref": row.get("pdf_ref"), "pdf_page_count": data["pdf_page_count"],
        "full_text_characters": data["full_text_characters"],
        "full_text_sha256": data["full_text_sha256"], "segment_count": len(segments),
        "segment_character_limit": SEGMENT_LIMIT, "full_page_coverage": data["full_page_coverage"],
        "extraction": "reused and revalidated frozen local pypdfium2 v2 derivation; no network"}


def extract_pdf(raw: bytes) -> dict:
    code = r'''import json,sys
import pypdfium2 as pdfium
raw=sys.stdin.buffer.read()
doc=pdfium.PdfDocument(raw)
pages=[]
for idx in range(len(doc)):
    page=doc.get_page(idx)
    textpage=page.get_textpage()
    pages.append(textpage.get_text_range() or "")
    textpage.close()
    page.close()
doc.close()
sys.stdout.write(json.dumps({"pages":pages},ensure_ascii=False,separators=(",",":")))
'''
    if not v2_capture.WORKSPACE_PYTHON.is_file():
        raise RuntimeError("BUNDLED_PYPDFIUM2_RUNTIME_UNAVAILABLE")
    result = subprocess.run([str(v2_capture.WORKSPACE_PYTHON), "-c", code], input=raw,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300, check=False)
    if result.returncode != 0:
        raise RuntimeError("PYPDFIUM2_LOCAL_EXTRACTION_FAILED:" + result.stderr.decode("utf-8", "replace")[-500:])
    payload = json.loads(result.stdout.decode("utf-8"))
    pages = payload.get("pages")
    if not isinstance(pages, list) or any(not isinstance(text, str) for text in pages):
        raise RuntimeError("PYPDFIUM2_PAGE_TEXT_SHAPE_INVALID")
    return {"pages": pages}


def derive_one(api: Mapping[str, Any], store: Any, row: Mapping[str, Any]) -> dict:
    art = row["art_code"]
    ref = row.get("pdf_ref")
    if not isinstance(ref, Mapping) or ref.get("request", {}).get("url") != row.get("attachment_url"):
        raise ValueError(f"DERIVATION_PDF_REF_BINDING_MISMATCH:{art}")
    raw = api["read_eastmoney_response"](store, ref)
    if not raw.startswith(b"%PDF") or sha(raw) != row.get("pdf_sha256") or len(raw) != row.get("pdf_bytes"):
        raise ValueError(f"DERIVATION_PDF_READBACK_MISMATCH:{art}")
    parsed = extract_pdf(raw)
    raw_pages = parsed["pages"]
    if not raw_pages:
        raise ValueError(f"DERIVATION_PDF_HAS_NO_PAGES:{art}")
    page_rows = []
    segments = []
    full_parts = []
    for page_index, text in enumerate(raw_pages, 1):
        page_hash = sha(text.encode())
        segment_ids = []
        starts = range(0, len(text), SEGMENT_LIMIT) if text else [0]
        for start in starts:
            part = text[start:start + SEGMENT_LIMIT]
            segment = {"segment_index": len(segments) + 1, "page_index": page_index,
                "character_start": start, "character_end": start + len(part),
                "text_characters": len(part), "text_sha256": sha(part.encode()), "text": part}
            segments.append(segment)
            segment_ids.append(segment["segment_index"])
        page_rows.append({"page_index": page_index, "text_characters": len(text),
            "text_sha256": page_hash, "segment_indexes": segment_ids})
        full_parts.append(text)
    full_text = "\n\n".join(full_parts)
    covered = [p["page_index"] for p in page_rows]
    if covered != list(range(1, len(raw_pages) + 1)) or any(s["text_characters"] > SEGMENT_LIMIT for s in segments):
        raise ValueError(f"DERIVATION_PAGE_OR_SEGMENT_COVERAGE_INVALID:{art}")
    artifact = {"schema": "v4.manager_research.eastmoney_hk_overlimit_pdf_text_derivative.v3",
        "status": "PASS_LOCAL_FULL_PHYSICAL_PAGE_COVERAGE", "art_code": art,
        "title": row.get("title"), "target_notice_date": "2026-09-29",
        "source_body_status": row.get("body_status"), "source_body_content_page_count": row.get("content_page_count"),
        "source_api_body_page_refs": [p.get("source_ref") for p in row.get("pages", [])],
        "pdf_source_ref": ref, "pdf_sha256": sha(raw), "pdf_bytes": len(raw),
        "pdf_page_count": len(raw_pages), "extraction": "local pypdfium2 only; no content fetch, network, OCR or LLM",
        "segment_character_limit": SEGMENT_LIMIT,
        "full_text_characters": len(full_text), "full_text_sha256": sha(full_text.encode()),
        "full_page_coverage": covered, "pages": page_rows, "segments": segments}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{art}.json"
    atomic_json(path, artifact)
    return {"art_code": art, "title": row.get("title"),
        "derivative_status": artifact["status"], "derivative_path": str(path),
        "derivative_sha256": sha(path.read_bytes()), "pdf_sha256": artifact["pdf_sha256"],
        "pdf_bytes": artifact["pdf_bytes"], "pdf_source_ref": ref,
        "pdf_page_count": artifact["pdf_page_count"],
        "full_text_characters": artifact["full_text_characters"],
        "full_text_sha256": artifact["full_text_sha256"], "segment_count": len(segments),
        "segment_character_limit": SEGMENT_LIMIT, "full_page_coverage": covered,
        "extraction": artifact["extraction"]}


def build_index() -> dict:
    corpus_raw = CORPUS.read_bytes()
    corpus = json.loads(corpus_raw.decode("utf-8"))
    if len(corpus.get("rows", [])) != 234:
        raise ValueError("V3_CORPUS_ROW_COUNT_INVALID")
    eligible = [r for r in corpus["rows"] if r.get("body_status") == "OVER_CONTENT_PAGE_LIMIT"
        and r.get("pdf_status") == "VALID_PDF_BYTES"]
    if len(eligible) != 22:
        raise ValueError(f"VALID_OVERLIMIT_PDF_COUNT_INVALID:{len(eligible)}")
    api = base.imports()
    store, _provider = base.make_provider(api)
    rows = []
    for row in sorted(eligible, key=lambda r: r["art_code"]):
        if row["art_code"] == EXISTING_CANARY_CODE:
            if not EXISTING_006795.is_file():
                raise ValueError("EXISTING_CANARY_DERIVATIVE_NOT_FOUND")
            data = json.loads(EXISTING_006795.read_text(encoding="utf-8"))
            entry = stored_canary_entry(row, data)
        else:
            entry = derive_one(api, store, row)
        rows.append(entry)
        print(json.dumps({"progress": f"{len(rows)}/22", "art_code": entry["art_code"],
            "pdf_page_count": entry["pdf_page_count"], "full_text_characters": entry["full_text_characters"],
            "derivative_sha256": entry["derivative_sha256"]}, ensure_ascii=False), flush=True)
    if len({r["art_code"] for r in rows}) != 22 or sum(r["pdf_page_count"] for r in rows) <= 333:
        raise ValueError("DERIVATION_INDEX_COVERAGE_INVALID")
    payload = {"schema": "v4.manager_research.eastmoney_hk_overlimit_pdf_text_derivative_index.v3",
        "status": "PASS_22_LOCAL_FULL_PHYSICAL_PAGE_DERIVATIVES",
        "body_corpus_path": str(CORPUS), "body_corpus_sha256": sha(corpus_raw),
        "article_count": len(rows), "total_pdf_pages": sum(r["pdf_page_count"] for r in rows),
        "segment_character_limit": SEGMENT_LIMIT,
        "extraction": "local pypdfium2; no network, OCR or LLM",
        "pit_status": "CANNOT_CONFIRM", "first_publication_status": "CANNOT_CONFIRM",
        "rows": rows, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    atomic_json(INDEX_JSON, payload)
    fields = ["art_code", "title", "derivative_status", "derivative_path", "derivative_sha256",
        "pdf_sha256", "pdf_bytes", "pdf_page_count", "full_text_characters", "full_text_sha256",
        "segment_count", "segment_character_limit", "full_page_coverage", "extraction"]
    with INDEX_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            item = dict(row)
            item["full_page_coverage"] = json.dumps(row["full_page_coverage"])
            writer.writerow(item)
    receipt = {"status": payload["status"], "index_json_path": str(INDEX_JSON),
        "index_json_sha256": sha(INDEX_JSON.read_bytes()), "index_csv_path": str(INDEX_CSV),
        "index_csv_sha256": sha(INDEX_CSV.read_bytes()), "body_corpus_sha256": sha(corpus_raw),
        "article_count": len(rows), "total_pdf_pages": payload["total_pdf_pages"],
        "valid_overlimit_pdf_count": len(eligible), "derived_count": len(rows),
        "all_pdf_sources_readback_verified": True, "all_page_hashes_covered": True,
        "pit_status": "CANNOT_CONFIRM", "first_publication_status": "CANNOT_CONFIRM"}
    atomic_json(OUT / "pdf_text_derivatives_20260929_v3_receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    return receipt


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "derive-22":
        raise SystemExit("usage: derive_long_pdf_text_v3.py derive-22")
    build_index()
