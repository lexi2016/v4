"""Read-only projection of the reviewed, date-bound HK announcement analysis.

The source directory catalog remains owned by ``workspace_announcements``.
This module reads a separately imported derived product beside that catalog;
it never fetches announcements or changes the catalog's semantic_analysis
field.
"""
from __future__ import annotations

from copy import deepcopy
import re
from hashlib import sha256
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
    url = request.get("url") if isinstance(request, Mapping) else None
    blob_sha256 = raw.get("blob_sha256")
    body_sha256 = raw.get("body_sha256")
    if (not _safe_url(url)
            or not isinstance(blob_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", blob_sha256) is None
            or not isinstance(body_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", body_sha256) is None):
        return None
    return {
        "url": url,
        "blob_sha256": blob_sha256,
        "body_sha256": body_sha256,
        "retrieved_at": raw.get("retrieved_at"),
    }


def _verified_input_descriptors(values: Any, *,
        canonical_objects: Mapping[str, Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
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
    if set(by_name) == set(EXPECTED_INPUTS) and all(
            by_name[name].get("sha256") == expected["sha256"]
            and by_name[name].get("row_count") == expected["row_count"]
            and "canonical_sha256" not in by_name[name]
            for name, expected in EXPECTED_INPUTS.items()):
        # Preserve the sealed 2026-09-29 import contract for existing readers.
        return [{"name": name, "sha256": expected["sha256"],
                 "row_count": expected["row_count"]}
                for name, expected in EXPECTED_INPUTS.items()]
    if (set(by_name).issubset(EXPECTED_INPUTS) and set(by_name) != set(EXPECTED_INPUTS)
            and not any("canonical_sha256" in value for value in by_name.values())):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_SET_MISMATCH")
    if not {"semantic_catalog", "body_corpus"}.issubset(by_name):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_SET_MISMATCH")
    out = []
    for name, value in sorted(by_name.items()):
        digest_value = value.get("sha256")
        row_count = value.get("row_count")
        canonical_sha = value.get("canonical_sha256")
        if (not isinstance(digest_value, str) or re.fullmatch(r"[0-9a-f]{64}", digest_value) is None
                or type(row_count) is not int or row_count < 0
                or any(key in value for key in ("path", "local_path", "uri"))
                or not isinstance(canonical_sha, str)
                or re.fullmatch(r"[0-9a-f]{64}", canonical_sha) is None):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_MANIFEST_INVALID")
        if canonical_objects is not None and name in canonical_objects:
            if digest(canonical_objects[name]) != canonical_sha:
                raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_CANONICAL_SHA_MISMATCH")
        out.append({"name": name, "sha256": digest_value,
                    "canonical_sha256": canonical_sha, "row_count": row_count})
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
    source_codes = catalog.get("manager_source_codes")
    matched_master_codes = catalog.get("manager_matched_master_codes")
    has_source_codes = isinstance(source_codes, list)
    distinct_source_code_count = (len(set(source_codes))
        if has_source_codes and all(isinstance(code, str) and code for code in source_codes) else None)
    source_identity_association_count = catalog.get("manager_source_identity_count")
    if type(source_identity_association_count) is not int or source_identity_association_count < 0:
        source_identity_association_count = None
    target = catalog_read.get("target_trade_date")
    publication = catalog_read.get("publication_date")
    legacy_date = target == SUPPORTED_TARGET_DATE and publication == SUPPORTED_PUBLICATION_DATE
    master_status = catalog.get("master_enrichment_status")
    master_count_is_complete = (legacy_date or master_status == "VERIFIED")
    manager_issuer_count = None
    if master_count_is_complete and isinstance(matched_master_codes, list):
        manager_issuer_count = len(set(code for code in matched_master_codes
            if isinstance(code, str) and code))
    issuer_count_status = "VERIFIED" if manager_issuer_count is not None else "CANNOT_CONFIRM"
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
        "manager_issuer_count": manager_issuer_count,
        "distinct_manager_source_code_count": distinct_source_code_count,
        "manager_source_identity_association_count": source_identity_association_count,
        "unknown_issuer_count": None if manager_issuer_count is None else 0,
        "issuer_count_status": issuer_count_status,
        "manager_source_identity_count": catalog.get("manager_source_identity_count"),
        "connect_eligibility_status": catalog.get("connect_eligibility_status", "NOT_ASSESSED"),
        "catalog_run_id": catalog.get("run_id"),
        "catalog_product_sha256": catalog.get("sha256"),
        "gaps": list(catalog_read.get("gaps", [])),
        "hkex_first_publication_verified": catalog.get("hkex_first_publication_verified") is True,
        "is_hkex_complete_directory": False,
    }


def _source_identity_metrics(catalog: Mapping[str, Any]) -> tuple[int, list[str]]:
    """Recompute source-code associations from the exact date-catalog rows."""
    rows = catalog.get("manager_consumer_rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITIES_MISSING")
    associations = 0
    source_codes: list[str] = []
    for row in rows:
        identities = row.get("source_issuer_codes") if isinstance(row, Mapping) else None
        if not isinstance(identities, list) or not identities:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITIES_MISSING")
        row_codes: list[str] = []
        for identity in identities:
            if (not isinstance(identity, Mapping)
                    or not isinstance(identity.get("code"), str) or not identity["code"]
                    or identity.get("market_code") != "116"
                    or identity.get("ann_type") != "H"):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITY_INVALID")
            row_codes.append(identity["code"])
        if len(row_codes) != len(set(row_codes)):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITY_DUPLICATE")
        associations += len(row_codes)
        source_codes.extend(row_codes)
    distinct_codes = sorted(set(source_codes))
    if (catalog.get("manager_source_identity_count") != associations
            or catalog.get("manager_source_codes") != distinct_codes):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITY_AGGREGATION_MISMATCH")
    return associations, distinct_codes


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
            or catalog.get("connect_eligibility_status", "NOT_ASSESSED") != "NOT_ASSESSED"
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
    if (manifest.get("target_trade_date") != target
            or manifest.get("publication_date") != publication
            or manifest.get("catalog_run_id") != catalog.get("run_id")
            or manifest.get("catalog_product_sha256") != catalog.get("sha256")
            or manifest.get("source_scope") != "EASTMONEY_HK_DATE_CATALOG"):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_BINDING_MISMATCH")
    derivative_shas = manifest.get("pdf_derivative_sha256s")
    if (not isinstance(derivative_shas, Mapping)
            or any(not isinstance(code, str) or not isinstance(sha, str)
                   or re.fullmatch(r"[0-9a-f]{64}", sha) is None
                   for code, sha in derivative_shas.items())):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_DERIVATIVE_MANIFEST_INVALID")
    descriptors = _verified_input_descriptors(manifest.get("verified_inputs"))
    if descriptors != manifest.get("verified_inputs"):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_MANIFEST_MISMATCH")
    legacy = (target == SUPPORTED_TARGET_DATE and publication == SUPPORTED_PUBLICATION_DATE
        and manifest.get("semantic_catalog_sha256") == EXPECTED_SEMANTIC_SHA256
        and manifest.get("body_corpus_sha256") == EXPECTED_BODY_SHA256
        and manifest.get("counts") == EXPECTED_COUNTS
        and len(derivative_shas) == EXPECTED_COUNTS["long_pdf_focus_reads"])
    if legacy:
        if descriptors != [
                {"name": name, "sha256": expected["sha256"], "row_count": expected["row_count"]}
                for name, expected in EXPECTED_INPUTS.items()]:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_MANIFEST_MISMATCH")
        return
    by_name = {item["name"]: item for item in descriptors}
    if (manifest.get("semantic_catalog_sha256") != by_name["semantic_catalog"]["sha256"]
            or manifest.get("body_corpus_sha256") != by_name["body_corpus"]["sha256"]
            or by_name["semantic_catalog"].get("row_count") != manifest.get("counts", {}).get("manager_announcements")
            or by_name["body_corpus"].get("row_count") != manifest.get("counts", {}).get("manager_announcements")):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_SHA_OR_COUNT_MISMATCH")
    counts = manifest.get("counts")
    required_counts = {"directory_records", "directory_pages", "manager_announcements",
        "manager_source_identity_associations", "distinct_manager_source_codes", "complete_api_bodies",
        "long_pdf_focus_reads", "text_insufficient_unassessed"}
    association_count, source_codes = _source_identity_metrics(catalog)
    if (not isinstance(counts, Mapping) or set(counts) != required_counts
            or any(type(value) is not int or value < 0 for value in counts.values())
            or counts.get("directory_records") != catalog.get("captured_row_count")
            or counts.get("directory_pages") != catalog.get("captured_page_count")
            or counts.get("manager_announcements") != catalog.get("manager_consumer_row_count")
            or counts.get("manager_source_identity_associations") != association_count
            or counts.get("distinct_manager_source_codes") != len(source_codes)
            or manifest.get("manager_source_identity_association_count") != association_count
            or manifest.get("distinct_manager_source_code_count") != len(source_codes)
            or manifest.get("manager_issuer_count") is not None
            or manifest.get("unknown_issuer_count") is not None
            or manifest.get("issuer_count_status") != "CANNOT_CONFIRM"):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_COUNTS_INVALID")


def validate_product(product: Mapping[str, Any], *, target_trade_date: str,
                     publication_date: str, catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Reject an imported result whose date, source, catalog, or rows drift."""
    target = date_token(target_trade_date)
    publication = _publication_date(publication_date)
    source_manifest = product.get("source_manifest") if isinstance(product, Mapping) else None
    legacy_source = (isinstance(source_manifest, Mapping)
        and source_manifest.get("semantic_catalog_sha256") == EXPECTED_SEMANTIC_SHA256
        and source_manifest.get("body_corpus_sha256") == EXPECTED_BODY_SHA256)
    if legacy_source and (target != SUPPORTED_TARGET_DATE or publication != SUPPORTED_PUBLICATION_DATE):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_DATE_NOT_SUPPORTED")
    if any(product.get(key) is not value for key, value in FLAGS.items()):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SAFETY_FLAGS_INVALID")
    _manifest_identity(product, target, publication, catalog)
    manifest = product["source_manifest"]
    legacy = (target == SUPPORTED_TARGET_DATE and publication == SUPPORTED_PUBLICATION_DATE
        and manifest.get("semantic_catalog_sha256") == EXPECTED_SEMANTIC_SHA256
        and manifest.get("body_corpus_sha256") == EXPECTED_BODY_SHA256
        and manifest.get("counts") == EXPECTED_COUNTS)
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
        source_identities = current_listing.get("source_issuer_codes")
        if source_identities is not None:
            source_codes = [item.get("code") for item in source_identities
                if isinstance(item, Mapping) and isinstance(item.get("code"), str)]
            record_codes = [item.get("code") for item in row.get("issuer_codes", [])
                if isinstance(item, Mapping) and isinstance(item.get("code"), str)]
            if (not source_codes or len(source_codes) != len(source_identities)
                    or record_codes != source_codes
                    or len(set(source_codes)) != len(source_codes)):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_ISSUER_BINDING_MISMATCH")
        kind = row.get("analysis_kind")
        if kind not in {"COMPLETE_API_BODY", "LONG_PDF_KEY_SECTION_READ", "TEXT_INSUFFICIENT_UNASSESSED"}:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_KIND_INVALID")
        kinds[kind] = kinds.get(kind, 0) + 1
        record_by_code[code] = row
    if (set(record_by_code) != set(manager_by_code)
            or len(records) != (EXPECTED_COUNTS["manager_announcements"] if legacy else len(manager_rows))):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MANAGER_SAMPLE_MISMATCH")
    terminal_body_capture = manifest.get("terminal_body_capture")
    failed_records = {code for code, row in record_by_code.items()
                      if row.get("body_status") == "BODY_CAPTURE_FAILED"}
    reader_gap_records = {code for code, row in record_by_code.items()
                          if has_reader_declared_content_gap(row)}
    for code in reader_gap_records:
        row = record_by_code[code]
        if row.get("analysis_kind") != "TEXT_INSUFFICIENT_UNASSESSED":
            raise ValueError("ANNOUNCEMENT_ANALYSIS_READER_CONTENT_GAP_PROJECTION_INVALID")
        # Products imported before the agent-judgment contract stored the
        # explicit NOT_ASSESSED decision only in the validated stock-selection
        # extension. Preserve those product bytes and SHA on read, while new
        # agent-judged products must carry the row-level marker.
        legacy_extension_only = (
            "selection_status" not in row
            and "agent_judgment_receipt" not in product
            and isinstance(product.get("stock_selection"), Mapping)
        )
        if row.get("selection_status") != "NOT_ASSESSED" and not legacy_extension_only:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_READER_CONTENT_GAP_PROJECTION_INVALID")
    if terminal_body_capture is None:
        if failed_records or any("body_capture_failure" in row for row in record_by_code.values()):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_FAILURE_UNBOUND")
    else:
        projected_body_rows = {}
        for code, row in record_by_code.items():
            failure = row.get("body_capture_failure")
            pdf = row.get("pdf_focus") if isinstance(row.get("pdf_focus"), Mapping) else {}
            projected_body_rows[code] = {
                "body_status": row.get("body_status"),
                "pages": (failure.get("retained_pages", []) if isinstance(failure, Mapping)
                          else row.get("body_page_citations")),
                "content_page_count": (failure.get("expected_page_count") if isinstance(failure, Mapping)
                                       else row.get("body_page_count")),
                "body_text": None,
                "body_text_sha256": row.get("body_text_sha256"),
                "pdf_sha256": pdf.get("sha256"),
                "capture_receipt_sha256": failure.get("receipt_sha256") if isinstance(failure, Mapping) else None,
            }
        validated_terminal, failure_bindings = _validated_terminal_body_capture(
            terminal_body_capture, projected_body_rows, set(record_by_code), publication=publication)
        if validated_terminal != terminal_body_capture or failure_bindings.keys() != failed_records:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_PRODUCT_BINDING_INVALID")
        for code, row in record_by_code.items():
            if code in failure_bindings:
                expected_failure = {"status": "BODY_CAPTURE_FAILED", **failure_bindings[code]}
                if (row.get("analysis_kind") != "TEXT_INSUFFICIENT_UNASSESSED"
                        or row.get("selection_status") != "NOT_ASSESSED"
                        or row.get("body_capture_failure") != expected_failure
                        or row.get("body_page_citations") != []
                        or row.get("body_page_count") is not None
                        or row.get("body_text_sha256") is not None
                        or row.get("exact_quote") is not None):
                    raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_FAILURE_PROJECTION_INVALID")
            elif "body_capture_failure" in row:
                raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_SUCCESS_PROJECTION_INVALID")
    expected_kinds = ({
        "COMPLETE_API_BODY": EXPECTED_COUNTS["complete_api_bodies"],
        "LONG_PDF_KEY_SECTION_READ": EXPECTED_COUNTS["long_pdf_focus_reads"],
        "TEXT_INSUFFICIENT_UNASSESSED": EXPECTED_COUNTS["text_insufficient_unassessed"],
    } if legacy else {
        "COMPLETE_API_BODY": manifest["counts"]["complete_api_bodies"],
        "LONG_PDF_KEY_SECTION_READ": manifest["counts"]["long_pdf_focus_reads"],
        "TEXT_INSUFFICIENT_UNASSESSED": manifest["counts"]["text_insufficient_unassessed"],
    })
    if kinds != {key: value for key, value in expected_kinds.items() if value}:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_KIND_COUNTS_MISMATCH")
    derivative_shas = product["source_manifest"].get("pdf_derivative_sha256s", {})
    long_rows = [row for row in records if row.get("analysis_kind") == "LONG_PDF_KEY_SECTION_READ"]
    if (set(derivative_shas) != {row.get("art_code") for row in long_rows}
            or any(row.get("pdf_focus", {}).get("derivative", {}).get("derivative_sha256")
                   != derivative_shas.get(row.get("art_code")) for row in long_rows)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_DERIVATIVE_BINDING_MISMATCH")
    summary = product.get("summary")
    summary_expected = EXPECTED_COUNTS if legacy else manifest["counts"]
    if not isinstance(summary, Mapping) or any(summary.get(key) != value for key, value in summary_expected.items()):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SUMMARY_MISMATCH")
    if not legacy and any(summary.get(key) != value for key, value in manifest["counts"].items()):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_COUNTS_INVALID")
    if not legacy and any(summary.get(key) != manifest.get(key) for key in (
            "manager_source_identity_association_count", "distinct_manager_source_code_count",
            "manager_issuer_count", "unknown_issuer_count", "issuer_count_status")):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITY_SUMMARY_MISMATCH")
    if "stock_selection" in product:
        from .announcement_selection import read_projection
        read_projection(product)
        extension = product.get("stock_selection")
        decisions = extension.get("article_decisions") if isinstance(extension, Mapping) else None
        unassessed_content_records = failed_records | reader_gap_records
        if unassessed_content_records:
            if not isinstance(decisions, list):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_UNASSESSED_CONTENT_SELECTION_MUST_BE_NOT_ASSESSED")
            by_code = {row.get("art_code"): row for row in decisions if isinstance(row, Mapping)}
            if any(by_code.get(code, {}).get("disposition") != "NOT_ASSESSED"
                   for code in unassessed_content_records):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_UNASSESSED_CONTENT_SELECTION_MUST_BE_NOT_ASSESSED")
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
        text_sha = page.get("text_sha256")
        if not isinstance(text_sha, str) or re.fullmatch(r"[0-9a-f]{64}", text_sha) is None:
            continue
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


def has_reader_declared_content_gap(record: Mapping[str, Any] | None) -> bool:
    """Return whether a reader explicitly found the captured body incomplete."""
    if not isinstance(record, Mapping):
        return False
    evidence = record.get("evidence")
    reader_fact = evidence.get("reader_fact_record") if isinstance(evidence, Mapping) else None
    if not isinstance(reader_fact, Mapping):
        return False
    validation = reader_fact.get("validation")
    return (
        reader_fact.get("body_read_complete") is False
        or reader_fact.get("source_content_gap") is True
        or (isinstance(validation, Mapping) and validation.get("source_content_gap") is True)
    )


def _analysis_record(record: Mapping[str, Any], body: Mapping[str, Any],
                     listing: Mapping[str, Any],
                     body_capture_failure: Mapping[str, Any] | None = None) -> dict[str, Any]:
    derivative = record.get("pdf_derivative")
    reader_content_gap = has_reader_declared_content_gap(record)
    if body.get("body_status") == "BODY_CAPTURE_FAILED":
        kind = "TEXT_INSUFFICIENT_UNASSESSED"
    elif body.get("body_status") == "COMPLETE_CONTENT_API_BODY":
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
    if reader_content_gap:
        kind = "TEXT_INSUFFICIENT_UNASSESSED"
    pdf_pages = record.get("pdf_physical_pages_reviewed")
    if not isinstance(pdf_pages, list):
        pdf_pages = []
    listing_ref = _source_ref(listing.get("source_ref"))
    if listing_ref is None:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_LISTING_SOURCE_INVALID")
    source_issuers = listing.get("source_issuer_codes")
    if isinstance(source_issuers, list):
        issuer_codes = []
        for source_issuer in source_issuers:
            if (not isinstance(source_issuer, Mapping)
                    or not isinstance(source_issuer.get("code"), str)
                    or source_issuer.get("market_code") != "116"
                    or source_issuer.get("ann_type") != "H"):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_ISSUER_INVALID")
            issuer_codes.append({"code": source_issuer["code"],
                "name": source_issuer.get("name") if isinstance(source_issuer.get("name"), str) else None,
                "source_stock_code": source_issuer.get("source_stock_code"),
                "market_code": "116", "ann_type": "H"})
        semantic_issuers = record.get("issuer_codes")
        if isinstance(semantic_issuers, list):
            semantic_codes = [item.get("code") for item in semantic_issuers if isinstance(item, Mapping)]
            if len(semantic_codes) != len(semantic_issuers) or semantic_codes != [item["code"] for item in issuer_codes]:
                raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_ISSUER_BINDING_MISMATCH")
    else:
        issuer_codes = deepcopy(record.get("issuer_codes", listing.get("matched_master_codes", [])))
    if body.get("body_status") == "BODY_CAPTURE_FAILED":
        if not isinstance(body_capture_failure, Mapping):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_FAILURE_UNBOUND")
        return {
            "art_code": record.get("art_code"),
            "title": listing.get("title"),
            "issuer_codes": issuer_codes,
            "classification": None,
            "classification_as_authored": None,
            "security_scope": None,
            "factual_summary": None,
            "why_useful": None,
            "research_priority": None,
            "event_status_assessment": None,
            "date_semantics": {"content_api_semantic_read_status": "BODY_CAPTURE_FAILED"},
            "cutoff_boundary": None,
            "analysis_kind": "TEXT_INSUFFICIENT_UNASSESSED",
            "body_status": "BODY_CAPTURE_FAILED",
            "body_page_count": None,
            "body_text_sha256": None,
            "body_page_citations": [],
            "exact_quote": None,
            "quote_location": None,
            "evidence": {},
            "pdf_focus": {"source_url": None, "sha256": None,
                "physical_pages_reviewed": [], "quote_page": None, "derivative": {}},
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
            "body_capture_failure": {
                "status": "BODY_CAPTURE_FAILED",
                **deepcopy(dict(body_capture_failure)),
            },
            "selection_status": "NOT_ASSESSED",
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
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
    date_semantics = deepcopy(record.get("date_semantics"))
    if not isinstance(date_semantics, Mapping):
        date_semantics = {}
    else:
        date_semantics = dict(date_semantics)
    if reader_content_gap:
        date_semantics["content_api_semantic_read_status"] = "INCOMPLETE_SOURCE_GAP"
    out = {
        "art_code": record.get("art_code"),
        "title": record.get("title") or listing.get("title"),
        "issuer_codes": issuer_codes,
        "classification": record.get("classification"),
        "classification_as_authored": record.get("classification_as_authored"),
        "security_scope": record.get("security_scope"),
        "factual_summary": record.get("factual_summary"),
        "why_useful": record.get("why_useful"),
        "research_priority": record.get("research_priority"),
        "event_status_assessment": record.get("event_status_assessment"),
        "date_semantics": date_semantics,
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
    if reader_content_gap:
        out["selection_status"] = "NOT_ASSESSED"
    return out


def _validated_terminal_body_capture(value: Mapping[str, Any] | None,
                                     body_by_code: Mapping[str, Mapping[str, Any]],
                                     expected_codes: set[str], *, publication: str | None = None) -> tuple[dict[str, Any] | None, dict[str, dict[str, str]]]:
    failed_rows = {code for code, row in body_by_code.items()
                   if row.get("body_status") == "BODY_CAPTURE_FAILED"}
    if value is None:
        if failed_rows:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_FAILURE_UNBOUND")
        return None, {}
    if not isinstance(value, Mapping):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_TERMINAL_INVALID")
    failures_raw = value.get("failed_articles")
    if not isinstance(failures_raw, list):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_TERMINAL_INVALID")
    failures: dict[str, dict[str, str]] = {}
    for item in failures_raw:
        if not isinstance(item, Mapping):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_TERMINAL_INVALID")
        code = item.get("art_code")
        error_code = item.get("error_code")
        receipt_sha = item.get("receipt_sha256")
        if (not isinstance(code, str) or code in failures or code not in expected_codes
                or not isinstance(error_code, str) or not error_code.strip()
                or not isinstance(receipt_sha, str)
                or re.fullmatch(r"[0-9a-f]{64}", receipt_sha) is None):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_TERMINAL_INVALID")
        failures[code] = {"error_code": error_code.strip(), "receipt_sha256": receipt_sha}
    counts = value.get("body_status_counts")
    status = value.get("status")
    if (value.get("schema_version") != "v4.manager_research.announcement_terminal_body_capture.v1"
            or status not in {"PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS",
                              "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS"}
            or value.get("article_count") != len(expected_codes)
            or not isinstance(value.get("input_identity_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value.get("input_identity_sha256", "")) is None
            or not isinstance(counts, Mapping)
            or any(type(count) is not int or count < 0 for count in counts.values())
            or sum(counts.values()) != len(expected_codes)
            or counts.get("COMPLETE_CONTENT_API_BODY", 0) != len(expected_codes) - len(failures)
            or counts.get("BODY_CAPTURE_FAILED", 0) != len(failures)
            or set(counts) - {"COMPLETE_CONTENT_API_BODY", "BODY_CAPTURE_FAILED"}
            or ({key: count for key, count in counts.items() if count}
                != {key: expected for key, expected in {
                    "COMPLETE_CONTENT_API_BODY": len(expected_codes) - len(failures),
                    "BODY_CAPTURE_FAILED": len(failures),
                }.items() if expected})
            or status != ("PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS" if not failures
                          else "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS")
            or any(not isinstance(value.get(key), str)
                   or re.fullmatch(r"[0-9a-f]{64}", value.get(key, "")) is None
                   for key in ("body_corpus_sha256", "body_corpus_manifest_sha256",
                               "body_batch_receipt_sha256", "capture_receipt_sha256"))
            or failures.keys() != failed_rows):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_TERMINAL_INVALID")
    terminal_failures = {item["art_code"]: item for item in failures_raw}
    for code, body in body_by_code.items():
        if code in failures:
            if (body.get("body_status") != "BODY_CAPTURE_FAILED"
                    or body.get("body_text") is not None or body.get("body_text_sha256") is not None
                    or body.get("pdf_sha256") is not None
                    or body.get("capture_receipt_sha256") != failures[code]["receipt_sha256"]):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_FAILURE_ROW_INVALID")
            pages=body.get("pages");total=body.get("content_page_count");entry=terminal_failures[code]
            if not isinstance(pages,list):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_FAILED_PAGES_INVALID")
            if not pages:
                if (total is not None or type(entry.get("captured_page_count",0)) is not int
                        or entry.get("captured_page_count",0)!=0
                        or entry.get("expected_page_count") is not None
                        or entry.get("retained_pages_sha256") is not None):
                    raise ValueError("ANNOUNCEMENT_ANALYSIS_FAILED_PAGES_BINDING_INVALID")
            else:
                if (publication is None or type(total) is not int or total<len(pages)
                        or type(entry.get("captured_page_count")) is not int
                        or entry["captured_page_count"]!=len(pages)
                        or type(entry.get("expected_page_count")) is not int
                        or entry["expected_page_count"]!=total
                        or entry.get("retained_pages_sha256")!=digest(pages)
                        or any(not isinstance(page,Mapping) or type(page.get("page_total")) is not int
                               or page["page_total"]!=total for page in pages)):
                    raise ValueError("ANNOUNCEMENT_ANALYSIS_FAILED_PAGES_BINDING_INVALID")
                _verify_body_source_rows(body,code,publication)
                failures[code].update(captured_page_count=len(pages),expected_page_count=total,
                    retained_pages_sha256=digest(pages),retained_pages=deepcopy(pages))
        elif body.get("body_status") != "COMPLETE_CONTENT_API_BODY":
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_TERMINAL_STATUS_INVALID")
    return deepcopy(dict(value)), failures


def _build_legacy_product(semantic_catalog: Mapping[str, Any], body_corpus: Mapping[str, Any],
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


def _date_field(value: Any, error: str) -> str:
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        value = value.replace("-", "")
    try:
        return date_token(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error) from exc


def _verify_body_source_rows(body: Mapping[str, Any], art_code: str,
                             publication: str) -> None:
    pages = body.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_PAGES_MISSING")
    indexes = []
    page_total = body.get("content_page_count")
    for page in pages:
        if not isinstance(page, Mapping):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_PAGE_INVALID")
        page_index = page.get("page_index")
        ref = _source_ref(page.get("source_ref"))
        text_sha = page.get("text_sha256")
        raw_sha = page.get("raw_body_sha256")
        if (type(page_index) is not int or page_index < 1 or ref is None
                or not isinstance(text_sha, str)
                or re.fullmatch(r"[0-9a-f]{64}", text_sha) is None
                or not isinstance(raw_sha, str)
                or re.fullmatch(r"[0-9a-f]{64}", raw_sha) is None):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_PAGE_SOURCE_INVALID")
        parsed = urlparse(ref["url"])
        from urllib.parse import parse_qs
        query = parse_qs(parsed.query, keep_blank_values=True)
        article_values = query.get("art_code")
        page_values = query.get("page_index")
        if (parsed.scheme != "https"
                or parsed.hostname != "np-cnotice-stock.eastmoney.com"
                or parsed.path != "/api/content/ann"
                or parsed.username is not None or parsed.password is not None or parsed.port is not None
                or article_values != [art_code]
                or page_values != [str(page_index)]
                or raw_sha != ref.get("body_sha256")
                or (page.get("blob_sha256") is not None
                    and page.get("blob_sha256") != ref.get("blob_sha256"))):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_PAGE_SOURCE_BINDING_MISMATCH")
        page_notice = page.get("notice_date")
        if (not isinstance(page_notice, str) or not re.match(r"^\d{4}-\d{2}-\d{2}(?:\s|T|$)", page_notice)
                or page_notice[:10] != publication):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_PAGE_DATE_MISMATCH")
        page_text = page.get("text")
        if not isinstance(page_text, str) or not page_text.strip():
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_PAGE_TEXT_MISSING")
        if sha256(page_text.encode("utf-8")).hexdigest() != text_sha:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_PAGE_TEXT_SHA_MISMATCH")
        indexes.append(page_index)
    if indexes != list(range(1, len(indexes) + 1)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_PAGE_SEQUENCE_INVALID")
    if body.get("body_status") == "COMPLETE_CONTENT_API_BODY" and page_total != len(indexes):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_PAGE_COVERAGE_MISMATCH")
    body_text = body.get("body_text")
    body_text_sha = body.get("body_text_sha256")
    if body.get("body_status") == "COMPLETE_CONTENT_API_BODY":
        expected_text = "\n\n".join(str(page["text"]) for page in pages)
        if (not isinstance(body_text, str) or body_text != expected_text
                or not isinstance(body_text_sha, str)
                or re.fullmatch(r"[0-9a-f]{64}", body_text_sha) is None
                or sha256(body_text.encode("utf-8")).hexdigest() != body_text_sha):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_TEXT_SHA_MISMATCH")
    elif body_text is not None:
        expected_text = "\n\n".join(str(page["text"]) for page in pages)
        if (not isinstance(body_text, str) or body_text != expected_text
                or (body_text_sha is not None and (not isinstance(body_text_sha, str)
                    or re.fullmatch(r"[0-9a-f]{64}", body_text_sha) is None
                    or sha256(body_text.encode("utf-8")).hexdigest() != body_text_sha))):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_TEXT_SHA_MISMATCH")


def build_product(semantic_catalog: Mapping[str, Any], body_corpus: Mapping[str, Any],
                  catalog_read: Mapping[str, Any], *, semantic_sha256: str,
                  body_sha256: str, verified_inputs: list[Mapping[str, Any]],
                  pdf_derivative_sha256s: Mapping[str, str] | None = None,
                  target_trade_date: str | None = None,
                  publication_date: str | None = None,
                  terminal_body_capture: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build an analysis projection bound to the supplied exact-date catalog.

    The sealed 2026-09-29 product remains readable through its original input
    checks. New dates require raw input hashes plus canonical JSON hashes and
    are validated against the source catalog's exact article and issuer IDs.
    """
    if (target_trade_date is None and publication_date is None
            and catalog_read.get("target_trade_date") == SUPPORTED_TARGET_DATE
            and catalog_read.get("publication_date") == SUPPORTED_PUBLICATION_DATE
            and semantic_catalog.get("target_research_date") == "2026-09-30"):
        return _build_legacy_product(semantic_catalog, body_corpus, catalog_read,
            semantic_sha256=semantic_sha256, body_sha256=body_sha256,
            verified_inputs=verified_inputs,
            pdf_derivative_sha256s=pdf_derivative_sha256s or {})

    target = _date_field(target_trade_date or catalog_read.get("target_trade_date"),
                         "ANNOUNCEMENT_ANALYSIS_TARGET_DATE_INVALID")
    publication = _publication_date(publication_date or catalog_read.get("publication_date"))
    catalog = _assert_catalog_readback(catalog_read, target, publication)
    if (semantic_catalog.get("schema") != "v4.announcement-semantic-catalog.v2"
            or not isinstance(semantic_catalog.get("status"), str)
            or not semantic_catalog["status"].startswith("PASS_")
            or _date_field(semantic_catalog.get("target_research_date"),
                           "ANNOUNCEMENT_ANALYSIS_CORPUS_TARGET_MISMATCH") != target
            or _publication_date(semantic_catalog.get("target_notice_date")) != publication
            or body_corpus.get("schema") != "v4.manager_research.eastmoney_hk_announcement_body_corpus.v3"
            or _publication_date(body_corpus.get("target_notice_date")) != publication):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_CORPUS_IDENTITY_INVALID")
    records = semantic_catalog.get("records")
    body_rows = body_corpus.get("rows")
    listing_rows = catalog.get("manager_consumer_rows")
    if not all(isinstance(value, list) for value in (records, body_rows, listing_rows)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_CORPUS_ROWS_MISSING")
    if (semantic_catalog.get("row_count") != len(records)
            or body_corpus.get("article_count") != len(body_rows)
            or not records or len(records) != len(body_rows)
            or len(records) != len(listing_rows)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SAMPLE_COUNT_MISMATCH")
    body_by_code = {row.get("art_code"): row for row in body_rows if isinstance(row, Mapping)}
    listing_by_code = {row.get("art_code"): row for row in listing_rows if isinstance(row, Mapping)}
    semantic_by_code = {row.get("art_code"): row for row in records if isinstance(row, Mapping)}
    expected_codes = set(listing_by_code)
    if (len(body_by_code) != len(body_rows) or len(semantic_by_code) != len(records)
            or len(listing_by_code) != len(listing_rows)
            or set(semantic_by_code) != expected_codes or set(body_by_code) != expected_codes
            or any(not isinstance(code, str) or not code for code in expected_codes)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_ARTICLE_SET_MISMATCH")
    body_capture, body_capture_failures = _validated_terminal_body_capture(
        terminal_body_capture, body_by_code, expected_codes, publication=publication)
    for code in sorted(expected_codes):
        listing = listing_by_code[code]
        semantic = semantic_by_code[code]
        body = body_by_code[code]
        if (not isinstance(listing.get("notice_date"), str)
                or listing["notice_date"][:10] != publication
                or semantic.get("title") not in {None, listing.get("title")}
                or body.get("title") not in {None, listing.get("title")}
                or not isinstance(listing.get("source_issuer_codes"), list)
                or not listing.get("source_issuer_codes")):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_LISTING_SOURCE_MISMATCH")
        semantic_codes = semantic.get("issuer_codes")
        listing_codes = [item.get("code") for item in listing["source_issuer_codes"]
            if isinstance(item, Mapping)]
        if (not isinstance(semantic_codes, list)
                or [item.get("code") for item in semantic_codes if isinstance(item, Mapping)] != listing_codes
                or len(listing_codes) != len(listing["source_issuer_codes"])):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_ISSUER_BINDING_MISMATCH")
        if code in body_capture_failures:
            continue
        _verify_body_source_rows(body, code, publication)

    canonical_objects = {"semantic_catalog": semantic_catalog, "body_corpus": body_corpus}
    descriptors = _verified_input_descriptors(verified_inputs, canonical_objects=canonical_objects)
    by_name = {item["name"]: item for item in descriptors}
    if (by_name["semantic_catalog"]["sha256"] != semantic_sha256
            or by_name["body_corpus"]["sha256"] != body_sha256
            or by_name["semantic_catalog"]["row_count"] != len(records)
            or by_name["body_corpus"]["row_count"] != len(body_rows)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_SHA_OR_COUNT_MISMATCH")
    derivative_shas = dict(pdf_derivative_sha256s or {})
    if any(not isinstance(code, str) or not isinstance(value, str)
            or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for code, value in derivative_shas.items()):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_DERIVATIVE_MANIFEST_INVALID")

    out_records = []
    kinds: dict[str, int] = {}
    for code in sorted(expected_codes):
        item = _analysis_record(semantic_by_code[code], body_by_code[code], listing_by_code[code],
            body_capture_failure=body_capture_failures.get(code))
        kinds[item["analysis_kind"]] = kinds.get(item["analysis_kind"], 0) + 1
        out_records.append(item)
    if set(derivative_shas) != {row["art_code"] for row in out_records
            if row["analysis_kind"] == "LONG_PDF_KEY_SECTION_READ"}:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_DERIVATIVE_BINDING_MISMATCH")
    source_identity_association_count, distinct_source_codes = _source_identity_metrics(catalog)
    counts = {
        "directory_records": catalog.get("captured_row_count"),
        "directory_pages": catalog.get("captured_page_count"),
        "manager_announcements": len(out_records),
        "manager_source_identity_associations": source_identity_association_count,
        "distinct_manager_source_codes": len(distinct_source_codes),
        "complete_api_bodies": kinds.get("COMPLETE_API_BODY", 0),
        "long_pdf_focus_reads": kinds.get("LONG_PDF_KEY_SECTION_READ", 0),
        "text_insufficient_unassessed": kinds.get("TEXT_INSUFFICIENT_UNASSESSED", 0),
    }
    manifest = {
        "target_trade_date": target, "publication_date": publication,
        "source_scope": "EASTMONEY_HK_DATE_CATALOG",
        "catalog_run_id": catalog.get("run_id"),
        "catalog_product_sha256": catalog.get("sha256"),
        "catalog_row_count": catalog.get("captured_row_count"),
        "catalog_page_count": catalog.get("captured_page_count"),
        "manager_sample_count": catalog.get("manager_consumer_row_count"),
        "manager_issuer_count": None,
        "unknown_issuer_count": None,
        "issuer_count_status": "CANNOT_CONFIRM",
        "manager_source_identity_association_count": source_identity_association_count,
        "distinct_manager_source_code_count": len(distinct_source_codes),
        "semantic_catalog_sha256": semantic_sha256, "body_corpus_sha256": body_sha256,
        "verified_inputs": descriptors,
        "pdf_derivative_sha256s": dict(sorted(derivative_shas.items())),
        "counts": counts,
        "first_publication_and_cutoff_status": "CANNOT_CONFIRM",
        "novelty_vs_prior_status": "CANNOT_CONFIRM",
        "point_in_time_status": "CANNOT_CONFIRM",
        "connect_eligibility_status": "NOT_ASSESSED",
    }
    if body_capture is not None:
        manifest["terminal_body_capture"] = body_capture
    product = {
        "schema_version": SCHEMA, "status": "VERIFIED", "target_trade_date": target,
        "publication_date": publication,
        "producer": "OFFLINE_REVIEWED_SEMANTIC_CATALOG_IMPORT",
        "source_manifest": manifest, "source_manifest_sha256": digest(manifest),
        "summary": {**counts,
            "manager_source_identity_association_count": source_identity_association_count,
            "distinct_manager_source_code_count": len(distinct_source_codes),
            "manager_issuer_count": None, "unknown_issuer_count": None,
            "issuer_count_status": "CANNOT_CONFIRM"},
        "interpretation_boundary": (
            "事后研究解读；不是目标日可得信息、历史PIT资格、HKEX权威全量目录、Connect资格、交易信号或BUY输入。"
        ),
        "records": out_records, **FLAGS,
    }
    product["sha256"] = digest(product)
    return product


def import_product(service: Any, product: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically import one validated analysis under the existing owner.

    Identical bytes are an idempotent no-op. A different existing product is
    preserved and requires a separate reviewed replacement workflow.
    """
    if not isinstance(product, Mapping):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_PRODUCT_IDENTITY_INVALID")
    target = date_token(product.get("target_trade_date"))
    publication = _publication_date(product.get("publication_date"))
    catalog_read = service.get_announcement_date_catalog(target, publication)
    catalog = _assert_catalog_readback(catalog_read, target, publication)
    checked = validate_product(product, target_trade_date=target,
        publication_date=publication, catalog=catalog)
    path = product_path(service.store, target, publication)
    with service.store._transaction(target, "announcement-analysis-" + publication.replace("-", "")):
        previous = service.store._read(path)
        if previous is not None:
            previous = validate_product(previous, target_trade_date=target,
                publication_date=publication, catalog=catalog)
            if previous.get("sha256") != checked.get("sha256"):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_PRODUCT_EXISTS")
            state = "ALREADY_IMPORTED"
        else:
            service.store._write_atomic(path, checked)
            state = "IMPORTED"
    result = read(service, target, publication)
    if result.get("analysis", {}).get("status") != "VERIFIED":
        raise ValueError("ANNOUNCEMENT_ANALYSIS_IMPORT_READBACK_FAILED")
    result["import_status"] = state
    return result


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
            "stock_selection": {
                "schema_version": "v4.manager_research.announcement_stock_selection_read.v1",
                "status": "NOT_ASSESSED",
                "decision_unit": "ISSUER_CODE",
                "stock_count": None,
                "selected_stock_count": None,
                "conditional_watch_count": None,
                "not_selected_stock_count": None,
                "not_assessed_stock_count": None,
                "stocks": [],
                "article_decisions": [],
                "gaps": ["ANNOUNCEMENT_SELECTION_NOT_ASSESSED"],
            },
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
            "stock_selection": {
                "schema_version": "v4.manager_research.announcement_stock_selection_read.v1",
                "status": "NOT_ASSESSED",
                "decision_unit": "ISSUER_CODE",
                "stock_count": None,
                "selected_stock_count": None,
                "conditional_watch_count": None,
                "not_selected_stock_count": None,
                "not_assessed_stock_count": None,
                "stocks": [],
                "article_decisions": [],
                "gaps": ["ANNOUNCEMENT_SELECTION_NOT_ASSESSED"],
            },
        }
        return result
    catalog = _assert_catalog_readback(catalog_read, target, publication)
    product = service.store._read(product_path(service.store, target, publication))
    if product is None:
        return result
    product = validate_product(product, target_trade_date=target,
                               publication_date=publication, catalog=catalog)
    from .announcement_selection import read_projection as read_stock_selection

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
        "stock_selection": read_stock_selection(product),
    }
    return result
