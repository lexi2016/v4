"""Read-only projection of the reviewed, date-bound HK announcement analysis.

The source directory catalog remains owned by ``workspace_announcements``.
This module reads a separately imported derived product beside that catalog;
it never fetches announcements or changes the catalog's semantic_analysis
field.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping
from urllib.parse import urlparse

from .workspace_projection import FLAGS, date_token, digest

SCHEMA = "v4.manager_research.eastmoney_hk_announcement_analysis.v1"
READ_SCHEMA = "v4.manager_research.eastmoney_hk_announcement_analysis_read.v1"
PRODUCT_FILENAME = "analysis.v1.json"
SUPPORTED_TARGET_DATE = "20260930"
SUPPORTED_PUBLICATION_DATE = "2026-09-29"
EXPECTED_SEMANTIC_SHA256 = "432a37e3617a33da32e9205ac05e3e39eab2eb75aafd20f6fb4647914d3340d7"
EXPECTED_BODY_SHA256 = "fec1257e1a0f8ddc30825591dd15e092b94664e7c6d4448d4c33a82ea2abeea4"
EXPECTED_INPUTS = {
    "semantic_catalog": {"sha256": EXPECTED_SEMANTIC_SHA256, "row_count": 234},
    "body_corpus": {"sha256": EXPECTED_BODY_SHA256, "row_count": 234},
    "short_additions": {"sha256": "7ceb46c795daafd99cd66b845367c6857dd450f4386c8e1aa9c625959496d467", "row_count": 40},
    "long_additions": {"sha256": "61271fa312c8943bb6160cf02dbe5d65896823a0176070ed1dae5a4a14bd137f", "row_count": 22},
    "pdf_derivative_index": {"sha256": "ea4cfdb2ef578c6c3fb39fc3b18ec32a18ef3101fb71852ac212295f3b21a3f9", "row_count": 22},
}
EXPECTED_COUNTS = {
    "directory_records": 744,
    "directory_pages": 39,
    "manager_announcements": 234,
    "manager_issuers": 140,
    "complete_api_bodies": 207,
    "long_pdf_focus_reads": 22,
    "text_insufficient_unassessed": 5,
}


def _publication_date(value: str) -> str:
    from .announcement_catalog import _date as catalog_date

    return catalog_date(value)


def previous_hk_session(target_trade_date: str) -> str:
    """Use the existing HK securities calendar to resolve the default day."""
    from contracts.trading_calendar import load_market_calendar, previous_session

    target = date_token(target_trade_date)
    return previous_session(load_market_calendar(), target, market="hk_securities")


def product_path(store: Any, target_trade_date: str, publication_date: str) -> Any:
    target = date_token(target_trade_date)
    publication = _publication_date(publication_date).replace("-", "")
    return (store.root / "workspace_announcements" / target / "eastmoney_date_catalog"
            / publication / PRODUCT_FILENAME)


def _safe_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return (parsed.scheme == "https" and parsed.hostname in {
        "np-cnotice-stock.eastmoney.com", "np-anotice-stock.eastmoney.com",
        "pdf.dfcfw.com",
    } and parsed.username is None and parsed.password is None)


def _source_ref(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    request = raw.get("request")
    url = request.get("url") if isinstance(request, Mapping) else raw.get("final_url")
    if not _safe_url(url):
        return None
    return {
        "url": url,
        "blob_sha256": raw.get("blob_sha256"),
        "body_sha256": raw.get("body_sha256"),
        "retrieved_at": raw.get("retrieved_at"),
    }


def _verified_input_descriptors(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_MANIFEST_INVALID")
    by_name: dict[str, Mapping[str, Any]] = {}
    for value in values:
        if not isinstance(value, Mapping):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_MANIFEST_INVALID")
        name = value.get("name")
        if not isinstance(name, str) or name in by_name or "path" in value:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_MANIFEST_INVALID")
        by_name[name] = value
    if set(by_name) != set(EXPECTED_INPUTS):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_SET_MISMATCH")
    out = []
    for name, expected in EXPECTED_INPUTS.items():
        value = by_name[name]
        if (value.get("sha256") != expected["sha256"]
                or value.get("row_count") != expected["row_count"]):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_SHA_MISMATCH")
        out.append({"name": name, "sha256": expected["sha256"],
                    "row_count": expected["row_count"]})
    return out


def _catalog_summary(catalog_read: Mapping[str, Any]) -> dict[str, Any]:
    catalog = catalog_read.get("catalog")
    if not isinstance(catalog, Mapping):
        return {
            "status": catalog_read.get("status", "NOT_RUN"),
            "readback_status": catalog_read.get("readback_status", "NOT_RUN"),
            "source_scope": catalog_read.get("source_scope"),
            "directory_record_count": None,
            "directory_page_count": None,
            "manager_announcement_count": None,
            "manager_issuer_count": None,
            "catalog_run_id": None,
            "catalog_product_sha256": None,
            "gaps": list(catalog_read.get("gaps", [])),
            "hkex_first_publication_verified": False,
            "is_hkex_complete_directory": False,
        }
    codes = catalog.get("manager_matched_master_codes")
    return {
        "status": catalog_read.get("status"),
        "readback_status": catalog_read.get("readback_status"),
        "source": catalog.get("source"),
        "source_scope": catalog.get("source_scope"),
        "coverage_scope": catalog.get("coverage_scope"),
        "publication_date": catalog.get("publication_date"),
        "directory_record_count": catalog.get("captured_row_count"),
        "directory_page_count": catalog.get("captured_page_count"),
        "directory_data_page_count": catalog.get("expected_data_page_count"),
        "terminal_empty_page_seen": catalog.get("terminal_empty_seen"),
        "manager_announcement_count": catalog.get("manager_consumer_row_count"),
        "manager_issuer_count": len(codes) if isinstance(codes, list) else None,
        "catalog_run_id": catalog.get("run_id"),
        "catalog_product_sha256": catalog.get("sha256"),
        "gaps": list(catalog_read.get("gaps", [])),
        "hkex_first_publication_verified": catalog.get("hkex_first_publication_verified") is True,
        "is_hkex_complete_directory": False,
    }


def _assert_catalog_readback(catalog_read: Mapping[str, Any], target: str,
                             publication: str) -> Mapping[str, Any]:
    catalog = catalog_read.get("catalog")
    if (catalog_read.get("schema_version") != "v4.manager_research.eastmoney_hk_date_catalog_read.v1"
            or catalog_read.get("target_trade_date") != target
            or catalog_read.get("publication_date") != publication
            or catalog_read.get("source_scope") != "EASTMONEY_HK_DATE_CATALOG"
            or catalog_read.get("status") != "COMPLETE"
            or catalog_read.get("readback_status") != "VERIFIED"
            or not isinstance(catalog, Mapping)
            or catalog.get("target_trade_date") != target
            or catalog.get("publication_date") != publication
            or catalog.get("source_scope") != "EASTMONEY_HK_DATE_CATALOG"
            or catalog.get("status") != "COMPLETE"
            or catalog.get("hkex_first_publication_verified") is not False):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_CATALOG_IDENTITY_INVALID")
    return catalog


def _manifest_identity(product: Mapping[str, Any], target: str,
                       publication: str, catalog: Mapping[str, Any]) -> None:
    if (product.get("schema_version") != SCHEMA
            or product.get("status") != "VERIFIED"
            or product.get("target_trade_date") != target
            or product.get("publication_date") != publication):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_PRODUCT_IDENTITY_INVALID")
    without_sha = {key: value for key, value in product.items() if key != "sha256"}
    if product.get("sha256") != digest(without_sha):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_PRODUCT_SHA_MISMATCH")
    manifest = product.get("source_manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MANIFEST_MISSING")
    if product.get("source_manifest_sha256") != digest(manifest):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MANIFEST_SHA_MISMATCH")
    if (manifest.get("semantic_catalog_sha256") != EXPECTED_SEMANTIC_SHA256
            or manifest.get("body_corpus_sha256") != EXPECTED_BODY_SHA256):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_SHA_MISMATCH")
    if _verified_input_descriptors(manifest.get("verified_inputs")) != manifest.get("verified_inputs"):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_MANIFEST_MISMATCH")
    if (manifest.get("target_trade_date") != target
            or manifest.get("publication_date") != publication
            or manifest.get("catalog_run_id") != catalog.get("run_id")
            or manifest.get("catalog_product_sha256") != catalog.get("sha256")
            or manifest.get("source_scope") != "EASTMONEY_HK_DATE_CATALOG"):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_BINDING_MISMATCH")
    if manifest.get("counts") != EXPECTED_COUNTS:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_COUNTS_INVALID")
    derivative_shas = manifest.get("pdf_derivative_sha256s")
    if (not isinstance(derivative_shas, Mapping) or len(derivative_shas) != 22
            or any(not isinstance(code, str) or not isinstance(sha, str)
                   or re.fullmatch(r"[0-9a-f]{64}", sha) is None
                   for code, sha in derivative_shas.items())):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_DERIVATIVE_MANIFEST_INVALID")


def validate_product(product: Mapping[str, Any], *, target_trade_date: str,
                     publication_date: str, catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Reject an imported result whose date, source, catalog, or rows drift."""
    target = date_token(target_trade_date)
    publication = _publication_date(publication_date)
    if target != SUPPORTED_TARGET_DATE or publication != SUPPORTED_PUBLICATION_DATE:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_DATE_NOT_SUPPORTED")
    if any(product.get(key) is not value for key, value in FLAGS.items()):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SAFETY_FLAGS_INVALID")
    _manifest_identity(product, target, publication, catalog)
    records = product.get("records")
    manager_rows = catalog.get("manager_consumer_rows")
    if not isinstance(records, list) or not isinstance(manager_rows, list):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_RECORDS_MISSING")
    manager_by_code: dict[str, Mapping[str, Any]] = {}
    for row in manager_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("art_code"), str):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_CATALOG_ROW_INVALID")
        code = row["art_code"]
        if code in manager_by_code:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_CATALOG_DUPLICATE_ART_CODE")
        manager_by_code[code] = row
    record_by_code: dict[str, Mapping[str, Any]] = {}
    kinds: dict[str, int] = {}
    for row in records:
        if not isinstance(row, Mapping):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_RECORD_INVALID")
        if any(row.get(key) is not value for key, value in FLAGS.items()):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_RECORD_SAFETY_FLAGS_INVALID")
        code = row.get("art_code")
        if not isinstance(code, str) or code in record_by_code:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_RECORD_IDENTITY_INVALID")
        if code not in manager_by_code or row.get("title") != manager_by_code[code].get("title"):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_RECORD_CATALOG_MISMATCH")
        listing = row.get("listing_source")
        current_listing = manager_by_code[code]
        if (not isinstance(listing, Mapping)
                or listing.get("page_index") != current_listing.get("page_index")
                or listing.get("item_index") != current_listing.get("item_index")
                or listing.get("raw_body_sha256") != current_listing.get("raw_body_sha256")
                or listing.get("source_ref") != _source_ref(current_listing.get("source_ref"))):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_LISTING_SOURCE_MISMATCH")
        kind = row.get("analysis_kind")
        if kind not in {"COMPLETE_API_BODY", "LONG_PDF_KEY_SECTION_READ", "TEXT_INSUFFICIENT_UNASSESSED"}:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_KIND_INVALID")
        kinds[kind] = kinds.get(kind, 0) + 1
        record_by_code[code] = row
    if set(record_by_code) != set(manager_by_code) or len(records) != EXPECTED_COUNTS["manager_announcements"]:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MANAGER_SAMPLE_MISMATCH")
    expected_kinds = {
        "COMPLETE_API_BODY": EXPECTED_COUNTS["complete_api_bodies"],
        "LONG_PDF_KEY_SECTION_READ": EXPECTED_COUNTS["long_pdf_focus_reads"],
        "TEXT_INSUFFICIENT_UNASSESSED": EXPECTED_COUNTS["text_insufficient_unassessed"],
    }
    if kinds != expected_kinds:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_KIND_COUNTS_MISMATCH")
    derivative_shas = product["source_manifest"].get("pdf_derivative_sha256s", {})
    long_rows = [row for row in records if row.get("analysis_kind") == "LONG_PDF_KEY_SECTION_READ"]
    if (set(derivative_shas) != {row.get("art_code") for row in long_rows}
            or any(row.get("pdf_focus", {}).get("derivative", {}).get("derivative_sha256")
                   != derivative_shas.get(row.get("art_code")) for row in long_rows)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_DERIVATIVE_BINDING_MISMATCH")
    summary = product.get("summary")
    if not isinstance(summary, Mapping) or any(summary.get(key) != value for key, value in EXPECTED_COUNTS.items()):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SUMMARY_MISMATCH")
    return deepcopy(dict(product))


def _citation_pages(raw_pages: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_pages, list):
        return []
    out = []
    for page in raw_pages:
        if not isinstance(page, Mapping):
            continue
        ref = _source_ref(page.get("source_ref"))
        if ref is None:
            continue
        page_index = page.get("page_index")
        if type(page_index) is not int or page_index < 1:
            continue
        text_sha = page.get("text_sha256") or page.get("sha256") or page.get("raw_body_sha256")
        out.append({"page_index": page_index, "text_sha256": text_sha,
                    "source_ref": ref})
    return out


def _clean_evidence(raw: Any) -> dict[str, Any]:
    """Keep reviewed citations while removing local debug filesystem paths."""
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key in {"path", "derivative_path", "pdf_capture_receipt_path"}:
            continue
        if key in {"source_ref", "pdf_source_ref"} or key.endswith("_source_ref"):
            source_ref = _source_ref(value)
            if source_ref is not None:
                out["source_ref" if key == "source_ref" else key] = source_ref
        elif key in {"source_api_page_refs", "api_page_refs", "pages"}:
            out[key] = _citation_pages(value)
        elif isinstance(value, Mapping):
            out[key] = _clean_evidence(value)
        elif isinstance(value, list):
            out[key] = [(_clean_evidence(item) if isinstance(item, Mapping) else deepcopy(item))
                        for item in value]
        else:
            out[key] = deepcopy(value)
    return out


def _analysis_record(record: Mapping[str, Any], body: Mapping[str, Any],
                     listing: Mapping[str, Any]) -> dict[str, Any]:
    derivative = record.get("pdf_derivative")
    if body.get("body_status") == "COMPLETE_CONTENT_API_BODY":
        kind = "COMPLETE_API_BODY"
    elif (body.get("body_status") == "OVER_CONTENT_PAGE_LIMIT"
            and body.get("pdf_status") == "VALID_PDF_BYTES"
            and isinstance(derivative, Mapping)
            and derivative.get("derivative_status") == "PASS_LOCAL_FULL_PHYSICAL_PAGE_COVERAGE"
            and isinstance(record.get("pdf_physical_pages_reviewed"), list)
            and record.get("pdf_physical_pages_reviewed")):
        kind = "LONG_PDF_KEY_SECTION_READ"
    elif body.get("body_status") == "OVER_CONTENT_PAGE_LIMIT":
        kind = "TEXT_INSUFFICIENT_UNASSESSED"
    else:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_STATUS_UNMAPPED")
    pdf_pages = record.get("pdf_physical_pages_reviewed")
    if not isinstance(pdf_pages, list):
        pdf_pages = []
    listing_ref = _source_ref(listing.get("source_ref"))
    if listing_ref is None:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_LISTING_SOURCE_INVALID")
    pdf_url = body.get("attachment_url")
    if not _safe_url(pdf_url):
        pdf_url = None
    body_citations = _citation_pages(body.get("pages"))
    if kind == "COMPLETE_API_BODY" and not body_citations:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_SOURCE_MISSING")
    if kind == "LONG_PDF_KEY_SECTION_READ" and pdf_url is None:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_PDF_SOURCE_MISSING")
    derivative_summary = {}
    if isinstance(derivative, Mapping):
        for key in ("derivative_sha256", "full_text_sha256", "page_count"):
            if derivative.get(key) is not None:
                derivative_summary[key] = deepcopy(derivative[key])
    return {
        "art_code": record.get("art_code"),
        "title": record.get("title") or listing.get("title"),
        "issuer_codes": deepcopy(record.get("issuer_codes", listing.get("matched_master_codes", []))),
        "classification": record.get("classification"),
        "classification_as_authored": record.get("classification_as_authored"),
        "security_scope": record.get("security_scope"),
        "factual_summary": record.get("factual_summary"),
        "why_useful": record.get("why_useful"),
        "research_priority": record.get("research_priority"),
        "event_status_assessment": record.get("event_status_assessment"),
        "date_semantics": deepcopy(record.get("date_semantics")),
        "cutoff_boundary": deepcopy(record.get("cutoff_boundary")),
        "analysis_kind": kind,
        "body_status": body.get("body_status"),
        "body_page_count": body.get("content_page_count"),
        "body_text_sha256": body.get("body_text_sha256") or record.get("source_body_sha256"),
        "body_page_citations": body_citations,
        "exact_quote": record.get("exact_quote") or (record.get("evidence") or {}).get("exact_excerpt"),
        "quote_location": deepcopy(record.get("quote_location")),
        "evidence": _clean_evidence(record.get("evidence")),
        "pdf_focus": {
            "source_url": pdf_url,
            "sha256": body.get("pdf_sha256") or record.get("source_pdf_sha256"),
            "physical_pages_reviewed": deepcopy(pdf_pages),
            "quote_page": record.get("quote_pdf_page"),
            "derivative": derivative_summary,
        },
        "listing_source": {
            "page_index": listing.get("page_index"),
            "item_index": listing.get("item_index"),
            "notice_date": listing.get("notice_date"),
            "display_time": listing.get("display_time"),
            "raw_body_sha256": listing.get("raw_body_sha256"),
            "source_ref": listing_ref,
        },
        "semantic_record_sha256": digest(record),
        "body_record_sha256": digest(body),
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def build_product(semantic_catalog: Mapping[str, Any], body_corpus: Mapping[str, Any],
                  catalog_read: Mapping[str, Any], *, semantic_sha256: str,
                  body_sha256: str, verified_inputs: list[Mapping[str, Any]],
                  pdf_derivative_sha256s: Mapping[str, str]) -> dict[str, Any]:
    """Build the immutable page projection from exact, already reviewed inputs."""
    target = SUPPORTED_TARGET_DATE
    publication = SUPPORTED_PUBLICATION_DATE
    catalog = _assert_catalog_readback(catalog_read, target, publication)
    if semantic_sha256 != EXPECTED_SEMANTIC_SHA256 or body_sha256 != EXPECTED_BODY_SHA256:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_SHA_MISMATCH")
    verified_inputs = _verified_input_descriptors(list(verified_inputs))
    if (semantic_catalog.get("schema") != "v4.announcement-semantic-catalog.v2"
            or semantic_catalog.get("status") != "PASS_234_UNIQUE_ANNOUNCEMENTS_WITH_SOURCE_BOUND_READS_AND_EXPLICIT_GAPS"
            or semantic_catalog.get("target_notice_date") != publication
            or semantic_catalog.get("target_research_date") != "2026-09-30"
            or semantic_catalog.get("row_count") != EXPECTED_COUNTS["manager_announcements"]
            or body_corpus.get("schema") != "v4.manager_research.eastmoney_hk_announcement_body_corpus.v3"
            or body_corpus.get("target_notice_date") != publication
            or body_corpus.get("article_count") != EXPECTED_COUNTS["manager_announcements"]):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_CORPUS_IDENTITY_INVALID")
    records = semantic_catalog.get("records")
    body_rows = body_corpus.get("rows")
    listing_rows = catalog.get("manager_consumer_rows")
    if not all(isinstance(value, list) for value in (records, body_rows, listing_rows)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_CORPUS_ROWS_MISSING")
    body_by_code = {row.get("art_code"): row for row in body_rows if isinstance(row, Mapping)}
    listing_by_code = {row.get("art_code"): row for row in listing_rows if isinstance(row, Mapping)}
    semantic_by_code = {row.get("art_code"): row for row in records if isinstance(row, Mapping)}
    expected_codes = set(listing_by_code)
    if (len(records) != 234 or len(body_rows) != 234 or len(listing_rows) != 234
            or len(semantic_by_code) != 234 or len(body_by_code) != 234 or len(listing_by_code) != 234
            or set(semantic_by_code) != expected_codes or set(body_by_code) != expected_codes):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SAMPLE_MISMATCH")
    if any(not isinstance(row.get("notice_date"), str)
           or row["notice_date"][:10] != publication for row in listing_rows):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_LISTING_DATE_MISMATCH")
    if (catalog.get("source_scope") != "EASTMONEY_HK_DATE_CATALOG"
            or catalog.get("captured_row_count") != 744
            or catalog.get("captured_page_count") != 39
            or catalog.get("manager_consumer_row_count") != 234
            or len(catalog.get("manager_matched_master_codes", [])) != 140
            or catalog.get("terminal_empty_seen") is not True):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_CATALOG_COUNTS_MISMATCH")
    counts = deepcopy(EXPECTED_COUNTS)
    kinds: dict[str, int] = {}
    out_records = []
    for code in sorted(expected_codes):
        row = _analysis_record(semantic_by_code[code], body_by_code[code], listing_by_code[code])
        kinds[row["analysis_kind"]] = kinds.get(row["analysis_kind"], 0) + 1
        out_records.append(row)
    if kinds != {
        "COMPLETE_API_BODY": 207,
        "LONG_PDF_KEY_SECTION_READ": 22,
        "TEXT_INSUFFICIENT_UNASSESSED": 5,
    }:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_KIND_COUNTS_MISMATCH")
    manifest = {
        "target_trade_date": target,
        "publication_date": publication,
        "source_scope": "EASTMONEY_HK_DATE_CATALOG",
        "catalog_run_id": catalog.get("run_id"),
        "catalog_product_sha256": catalog.get("sha256"),
        "catalog_row_count": catalog.get("captured_row_count"),
        "catalog_page_count": catalog.get("captured_page_count"),
        "manager_sample_count": catalog.get("manager_consumer_row_count"),
        "manager_issuer_count": len(catalog.get("manager_matched_master_codes", [])),
        "semantic_catalog_sha256": semantic_sha256,
        "body_corpus_sha256": body_sha256,
        "verified_inputs": [deepcopy(dict(row)) for row in verified_inputs],
        "pdf_derivative_sha256s": dict(sorted(pdf_derivative_sha256s.items())),
        "counts": counts,
        "first_publication_and_cutoff_status": "CANNOT_CONFIRM",
        "novelty_vs_prior_status": "CANNOT_CONFIRM",
        "point_in_time_status": "CANNOT_CONFIRM",
    }
    product = {
        "schema_version": SCHEMA,
        "status": "VERIFIED",
        "target_trade_date": target,
        "publication_date": publication,
        "producer": "OFFLINE_REVIEWED_SEMANTIC_CATALOG_IMPORT",
        "source_manifest": manifest,
        "source_manifest_sha256": digest(manifest),
        "summary": counts,
        "interpretation_boundary": (
            "事后研究解读；不是目标日可得信息、历史PIT资格、HKEX权威全量目录、交易信号或BUY输入。"
        ),
        "records": out_records,
        **FLAGS,
    }
    product["sha256"] = digest(product)
    return product


def read(service: Any, target_trade_date: str,
         publication_date: str | None = None) -> dict[str, Any]:
    """Read the exact owner catalog and its optional derived analysis product."""
    target = date_token(target_trade_date)
    explicit = publication_date is not None
    publication = (_publication_date(publication_date) if explicit
                   else _publication_date(previous_hk_session(target)))
    catalog_read = service.get_announcement_date_catalog(target, publication)
    source = _catalog_summary(catalog_read)
    result = {
        "schema_version": READ_SCHEMA,
        "target_trade_date": target,
        "publication_date": publication,
        "date_selection_basis": "EXPLICIT" if explicit else "PREVIOUS_HK_TRADING_SESSION",
        "source_catalog": source,
        "analysis": {
            "status": "NOT_IMPORTED",
            "source_manifest": None,
            "source_manifest_sha256": None,
            "summary": None,
            "records": [],
            "gaps": ["ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED"],
            "point_in_time_status": "CANNOT_CONFIRM",
        },
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if catalog_read.get("readback_status") != "VERIFIED":
        missing_catalog = (catalog_read.get("status") == "NOT_RUN"
                           and catalog_read.get("readback_status") == "NOT_RUN")
        result["analysis"] = {
            "status": "NOT_IMPORTED" if missing_catalog else "SOURCE_CATALOG_UNVERIFIED",
            "source_manifest": None,
            "source_manifest_sha256": None,
            "summary": None,
            "records": [],
            "gaps": ["ANNOUNCEMENT_DATE_CATALOG_NOT_RUN" if missing_catalog
                     else "ANNOUNCEMENT_ANALYSIS_SOURCE_CATALOG_UNVERIFIED"],
            "point_in_time_status": "CANNOT_CONFIRM",
        }
        return result
    catalog = _assert_catalog_readback(catalog_read, target, publication)
    product = service.store._read(product_path(service.store, target, publication))
    if product is None:
        return result
    product = validate_product(product, target_trade_date=target,
                               publication_date=publication, catalog=catalog)
    result["analysis"] = {
        "status": "VERIFIED",
        "producer": product.get("producer"),
        "source_manifest": product.get("source_manifest"),
        "source_manifest_sha256": product.get("source_manifest_sha256"),
        "product_sha256": product.get("sha256"),
        "summary": product.get("summary"),
        "interpretation_boundary": product.get("interpretation_boundary"),
        "first_publication_and_cutoff_status": product["source_manifest"].get("first_publication_and_cutoff_status"),
        "novelty_vs_prior_status": product["source_manifest"].get("novelty_vs_prior_status"),
        "point_in_time_status": product["source_manifest"].get("point_in_time_status"),
        "gaps": [],
        "records": product.get("records", []),
    }
    return result
