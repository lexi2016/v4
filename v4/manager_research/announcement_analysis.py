"""Read-only projection of the reviewed, date-bound HK announcement analysis.

The source directory catalog remains owned by ``workspace_announcements``.
This module reads a separately imported derived product beside that catalog;
it never fetches announcements or changes the catalog's semantic_analysis
field.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from hashlib import sha256
from typing import Any, Mapping
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .workspace_projection import FLAGS, date_token, digest

SCHEMA = "v4.manager_research.eastmoney_hk_announcement_analysis.v1"
MULTI_SOURCE_SCHEMA = "v4.manager_research.eastmoney_hk_announcement_analysis.v2"
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
_HKEX_DIRECTORY_SCOPE = "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1"
_HKEX_COMPLETE_BODY = "COMPLETE_HKEX_OFFICIAL_PDF_BODY"
_MONTHLY_ELIGIBILITY_SCHEMA = "v4.manager_research.hk_connect_monthly_eligibility.v1"


def _validated_monthly_connect_eligibility(value: Any, *, target: str,
                                            publication: str) -> tuple[set[str], str]:
    if not isinstance(value, Mapping):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MONTHLY_CONNECT_WITNESS_MISSING")
    identity = value.get("identity_sha256")
    material = {key: item for key, item in value.items() if key != "identity_sha256"}
    codes = value.get("codes")
    source = value.get("source")
    ref_keys = {"artifact_ref", "manifest_ref", "receipt_ref", "current_ref", "capture_ref", "publication_ref"}
    hashes = value.get("authority_file_sha256s")
    if (value.get("schema_version") != _MONTHLY_ELIGIBILITY_SCHEMA
            or value.get("status") != "VERIFIED"
            or value.get("policy") != "CALENDAR_MONTH_LATEST_VERIFIED_V2"
            or value.get("target_trade_date") != target
            or value.get("month") != publication[:7].replace("-", "")
            or not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{64}", identity) is None
            or digest(material) != identity
            or any(value.get(key) is not expected for key, expected in FLAGS.items())
            or not isinstance(source, Mapping)
            or source.get("market") != "HK_CONNECT"
            or source.get("role") != "HK_CONNECT_FULL_MARKET_AUTHORITY"
            or source.get("source_date") != value.get("source_date")
            or not isinstance(value.get("source_date"), str)
            or not re.fullmatch(r"\d{8}", value["source_date"])
            or value["source_date"][:6] != value.get("month")
            or not isinstance(codes, list) or not codes or codes != sorted(set(codes))
            or not all(isinstance(code, str) and re.fullmatch(r"HK\.\d{5}", code) for code in codes)
            or value.get("code_count") != len(codes)
            or value.get("codes_sha256") != digest(codes)
            or not isinstance(hashes, Mapping) or set(hashes) != ref_keys
            or any(not isinstance(source.get(key), str) or not source[key]
                   or not isinstance(hashes.get(key), str)
                   or re.fullmatch(r"[0-9a-f]{64}", hashes[key]) is None for key in ref_keys)
            or any(not isinstance(source.get(key), str)
                   or re.fullmatch(r"[0-9a-f]{64}", source.get(key, "")) is None
                   for key in ("sha256", "capture_sha256", "source_sha256"))):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MONTHLY_CONNECT_WITNESS_INVALID")
    try:
        available = datetime.fromisoformat(str(source.get("available_at", "")).replace("Z", "+00:00"))
        cutoff = datetime.fromisoformat(str(value.get("capture_cutoff_at", "")).replace("Z", "+00:00"))
        source_day = datetime.strptime(value["source_date"], "%Y%m%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MONTHLY_CONNECT_TIME_INVALID") from exc
    if (available.tzinfo is None or cutoff.tzinfo is None or available > cutoff
            or value["source_date"] > cutoff.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y%m%d")
            or source_day.strftime("%Y%m") != publication[:7].replace("-", "")):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MONTHLY_CONNECT_TIME_INVALID")
    return set(codes), identity


def _record_identity(value: Mapping[str, Any]) -> tuple[str, str]:
    """Return an explicit source key without coercing one source ID into another."""
    art_code = value.get("art_code")
    variant_id = value.get("source_variant_id")
    if isinstance(art_code, str) and art_code and variant_id is None:
        return "art_code", art_code
    if isinstance(variant_id, str) and variant_id.startswith("HKEX:") and art_code is None:
        news_id = variant_id[5:]
        if re.fullmatch(r"\d{5,20}", news_id):
            return "source_variant_id", variant_id
    raise ValueError("ANNOUNCEMENT_ANALYSIS_RECORD_IDENTITY_INVALID")


def _publication_date(value: str) -> str:
    from .announcement_catalog import _date as catalog_date

    return catalog_date(value)


def _current_hk_datetime() -> datetime:
    return datetime.now(ZoneInfo("Asia/Hong_Kong"))


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
        "pdf.dfcfw.com", "www1.hkexnews.hk", "www.hkexnews.hk", "sc.hkexnews.hk",
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
    multi_source = product.get("schema_version") == MULTI_SOURCE_SCHEMA
    if (product.get("schema_version") not in {SCHEMA, MULTI_SOURCE_SCHEMA}
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
    counts = manifest.get("counts")
    semantic_rows = by_name["semantic_catalog"].get("row_count")
    body_rows = by_name["body_corpus"].get("row_count")
    expected_body_rows = (counts.get("eligible_eastmoney_announcements")
        if multi_source and isinstance(counts, Mapping) else
        counts.get("manager_announcements") if isinstance(counts, Mapping) else None)
    if (manifest.get("semantic_catalog_sha256") != by_name["semantic_catalog"]["sha256"]
            or manifest.get("body_corpus_sha256") != by_name["body_corpus"]["sha256"]
            or semantic_rows != (counts.get("combined_eligible_announcements")
                if multi_source and isinstance(counts, Mapping) else
                counts.get("manager_announcements") if isinstance(counts, Mapping) else None)
            or body_rows != expected_body_rows):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_SHA_OR_COUNT_MISMATCH")
    required_counts = {"directory_records", "directory_pages", "manager_announcements",
        "manager_source_identity_associations", "distinct_manager_source_codes", "complete_api_bodies",
        "long_pdf_focus_reads", "text_insufficient_unassessed"}
    if multi_source:
        required_counts |= {"eligible_eastmoney_announcements", "hkex_official_announcements",
            "combined_eligible_announcements", "complete_hkex_pdf_bodies"}
    association_count, source_codes = _source_identity_metrics(catalog)
    if (not isinstance(counts, Mapping) or set(counts) != required_counts
            or any(type(value) is not int or value < 0 for value in counts.values())
            or counts.get("directory_records") != catalog.get("captured_row_count")
            or counts.get("directory_pages") != catalog.get("captured_page_count")
            or (counts.get("manager_announcements") != catalog.get("manager_consumer_row_count")
                if not multi_source else (
                    counts.get("manager_announcements") != counts.get("combined_eligible_announcements")
                    or counts.get("combined_eligible_announcements") != (
                        counts.get("eligible_eastmoney_announcements") + counts.get("hkex_official_announcements"))
                    or counts.get("eligible_eastmoney_announcements") > catalog.get("manager_consumer_row_count")))
            or (multi_source and (manifest.get("additional_source_scopes") != [_HKEX_DIRECTORY_SCOPE]
                or counts.get("hkex_official_announcements") != manifest.get("hkex_source_variant_count")
                or counts.get("complete_hkex_pdf_bodies") > counts.get("hkex_official_announcements")
                or manifest.get("hkex_eligible_document_count") != counts.get("hkex_official_announcements")
                or manifest.get("hkex_directory_document_count") != sum(manifest.get(key, -1)
                    for key in ("hkex_eligible_document_count", "hkex_excluded_document_count",
                                "hkex_unresolved_document_count"))
                or not isinstance(manifest.get("hkex_directory_readback_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", manifest.get("hkex_directory_readback_sha256", "")) is None
                or not isinstance(manifest.get("monthly_connect_eligibility_identity_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", manifest.get("monthly_connect_eligibility_identity_sha256", "")) is None
                or not isinstance(manifest.get("monthly_connect_source_date"), str)
                or not re.fullmatch(r"\d{8}", manifest.get("monthly_connect_source_date", ""))
                or manifest.get("monthly_connect_source_date", "")[:6] != publication[:7].replace("-", "")
                or not isinstance(manifest.get("hkex_source_variant_sha256s"), Mapping)
                or set(manifest.get("hkex_source_variant_sha256s", {})) != set(
                    manifest.get("hkex_source_variant_sha256s", {}).keys())
                or len(manifest.get("hkex_source_variant_sha256s", {})) != counts.get("hkex_official_announcements")
                or any(not isinstance(key, str) or not re.fullmatch(r"HKEX:\d{5,20}", key)
                    or not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
                    for key, value in manifest.get("hkex_source_variant_sha256s", {}).items())))
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
    if product.get("schema_version") == MULTI_SOURCE_SCHEMA:
        return _validate_multi_source_product(product, target, publication, catalog)
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
        if (row.get("analysis_kind") != "TEXT_INSUFFICIENT_UNASSESSED"
                or row.get("selection_status") != "NOT_ASSESSED"):
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
                "pages": row.get("body_page_citations"),
                "content_page_count": row.get("body_page_count"),
                "body_text": None,
                "body_text_sha256": row.get("body_text_sha256"),
                "pdf_sha256": pdf.get("sha256"),
                "capture_receipt_sha256": failure.get("receipt_sha256") if isinstance(failure, Mapping) else None,
            }
        validated_terminal, failure_bindings = _validated_terminal_body_capture(
            terminal_body_capture, projected_body_rows, set(record_by_code))
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
                "error_code": body_capture_failure.get("error_code"),
                "receipt_sha256": body_capture_failure.get("receipt_sha256"),
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
    for field in ("connect_eligibility_status", "matched_connect_codes",
                  "connect_eligibility_identity_sha256"):
        if field in body:
            out[field] = deepcopy(body[field])
    if reader_content_gap:
        out["selection_status"] = "NOT_ASSESSED"
    return out


def _verify_hkex_variant_body(variant: Mapping[str, Any], publication: str) -> None:
    """Validate an official directory/body pair while keeping it separate from EM IDs."""
    kind, identity = _record_identity(variant)
    news_id = variant.get("news_id")
    if (kind != "source_variant_id" or identity != "HKEX:" + str(news_id)
            or not isinstance(news_id, str) or re.fullmatch(r"\d{5,20}", news_id) is None
            or variant.get("source") != "HKEX_OFFICIAL"
            or variant.get("source_scope") != _HKEX_DIRECTORY_SCOPE
            or variant.get("publication_date") != publication.replace("-", "")
            or not _safe_url(variant.get("source_url"))
            or "art_code" in variant
            or variant.get("cross_source_link_status") != "NOT_ASSESSED"):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_VARIANT_IDENTITY_INVALID")
    symbol = variant.get("symbol")
    if not isinstance(symbol, str) or re.fullmatch(r"HK\.\d{5}", symbol) is None:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_SOURCE_SYMBOL_INVALID")
    directory_ref = _source_ref(variant.get("directory_source_ref"))
    if directory_ref is None:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_DIRECTORY_SOURCE_MISSING")
    parsed_directory = urlparse(directory_ref["url"])
    if (parsed_directory.hostname != "www1.hkexnews.hk"
            or parsed_directory.path != "/search/titleSearchServlet.do"
            or variant.get("directory_raw_body_sha256") != directory_ref["body_sha256"]):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_DIRECTORY_SOURCE_MISMATCH")

    status = variant.get("body_status")
    pages = variant.get("pages")
    if not isinstance(pages, list):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_BODY_PAGES_INVALID")
    body_ref = _source_ref(variant.get("body_source_ref"))
    source_url = variant.get("source_url")
    if body_ref is not None:
        if body_ref["url"] != source_url:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_BODY_SOURCE_MISMATCH")
    elif status == _HKEX_COMPLETE_BODY:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_BODY_SOURCE_MISSING")

    if status == _HKEX_COMPLETE_BODY:
        if body_ref is None or not pages or not isinstance(variant.get("body_text"), str):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_BODY_INCOMPLETE")
        indexes: list[int] = []
        for page in pages:
            if not isinstance(page, Mapping):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_BODY_PAGE_INVALID")
            index = page.get("page_index")
            ref = _source_ref(page.get("source_ref"))
            text = page.get("text")
            text_sha = page.get("text_sha256")
            raw_sha = page.get("raw_body_sha256")
            if (type(index) is not int or index < 1 or ref != body_ref
                    or not isinstance(text, str) or not text.strip()
                    or not isinstance(text_sha, str)
                    or re.fullmatch(r"[0-9a-f]{64}", text_sha) is None
                    or sha256(text.encode("utf-8")).hexdigest() != text_sha
                    or raw_sha != body_ref["body_sha256"]):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_BODY_PAGE_SOURCE_INVALID")
            indexes.append(index)
        if indexes != list(range(1, len(indexes) + 1)):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_BODY_PAGE_SEQUENCE_INVALID")
        expected_text = "\n\n".join(str(page["text"]) for page in pages)
        body_text_sha = variant.get("body_text_sha256")
        if (variant.get("body_text") != expected_text
                or not isinstance(body_text_sha, str)
                or re.fullmatch(r"[0-9a-f]{64}", body_text_sha) is None
                or sha256(expected_text.encode("utf-8")).hexdigest() != body_text_sha):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_BODY_TEXT_SHA_MISMATCH")
    elif status in {"HKEX_BODY_CAPTURE_FAILED", "HKEX_OFFICIAL_PDF_TEXT_UNREADABLE",
                    "HKEX_OFFICIAL_PDF_BODY_UNREADABLE", "BODY_CAPTURE_FAILED",
                    "BODY_FETCH_FAILED", "BODY_NOT_CAPTURED"}:
        if pages or variant.get("body_text") is not None or variant.get("body_text_sha256") is not None:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_UNASSESSED_BODY_HAS_TEXT")
    else:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_BODY_STATUS_UNMAPPED")


def _analysis_hkex_record(record: Mapping[str, Any], variant: Mapping[str, Any]) -> dict[str, Any]:
    """Project an explicit semantic judgment for one official HKEX document."""
    _verify_hkex_variant_body(variant, _publication_date(variant.get("publication_date")))
    variant_id = variant["source_variant_id"]
    issuer_source = [variant["symbol"]]
    semantic_issuers = record.get("issuer_codes")
    if not isinstance(semantic_issuers, list):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_SEMANTIC_ISSUERS_MISSING")
    semantic_codes: list[str] = []
    for item in semantic_issuers:
        code = item.get("code") if isinstance(item, Mapping) else item
        if not isinstance(code, str) or not code:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_SEMANTIC_ISSUER_INVALID")
        semantic_codes.append(code)
    if semantic_codes != issuer_source:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_ISSUER_BINDING_MISMATCH")
    if (record.get("source_variant_id") != variant_id or "art_code" in record
            or record.get("source_scope") != _HKEX_DIRECTORY_SCOPE
            or record.get("title") not in {None, variant.get("title")}):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_SEMANTIC_BINDING_MISMATCH")
    status = variant.get("body_status")
    if status == _HKEX_COMPLETE_BODY:
        kind = _HKEX_COMPLETE_BODY
    else:
        kind = "TEXT_INSUFFICIENT_UNASSESSED"
    name = variant.get("name") if isinstance(variant.get("name"), str) else None
    issuer_codes = [{"code": variant["symbol"], "name": name}]
    pages = _citation_pages(variant.get("pages"))
    if kind == _HKEX_COMPLETE_BODY and not pages:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_BODY_SOURCE_MISSING")
    directory_ref = _source_ref(variant.get("directory_source_ref"))
    body_ref = _source_ref(variant.get("body_source_ref"))
    listing_source = {
        "source": "HKEX_OFFICIAL",
        "source_scope": _HKEX_DIRECTORY_SCOPE,
        "source_variant_id": variant_id,
        "news_id": variant.get("news_id"),
        "symbol": variant.get("symbol"),
        "publication_date": variant.get("publication_date"),
        "published_at": variant.get("published_at"),
        "available_at": variant.get("available_at"),
        "source_url": variant.get("source_url"),
        "directory_raw_body_sha256": variant.get("directory_raw_body_sha256"),
        "directory_source_ref": directory_ref,
        "body_source_ref": body_ref,
    }
    out = {
        "source_variant_id": variant_id,
        "source": "HKEX_OFFICIAL",
        "source_scope": _HKEX_DIRECTORY_SCOPE,
        "news_id": variant.get("news_id"),
        "title": variant.get("title"),
        "issuer_codes": issuer_codes,
        "classification": record.get("classification"),
        "classification_as_authored": record.get("classification_as_authored"),
        "security_scope": record.get("security_scope"),
        "factual_summary": record.get("factual_summary"),
        "why_useful": record.get("why_useful"),
        "research_priority": record.get("research_priority"),
        "event_status_assessment": record.get("event_status_assessment"),
        "date_semantics": deepcopy(record.get("date_semantics")) if isinstance(record.get("date_semantics"), Mapping) else {},
        "cutoff_boundary": deepcopy(record.get("cutoff_boundary")),
        "analysis_kind": kind,
        "body_status": status,
        "body_page_count": len(variant.get("pages", [])),
        "body_text_sha256": variant.get("body_text_sha256"),
        "body_page_citations": pages,
        "exact_quote": record.get("exact_quote") or (record.get("evidence") or {}).get("exact_excerpt"),
        "quote_location": deepcopy(record.get("quote_location")),
        "evidence": _clean_evidence(record.get("evidence")),
        "pdf_focus": {"source_url": variant.get("source_url"),
            "sha256": body_ref.get("body_sha256") if body_ref else None,
            "physical_pages_reviewed": deepcopy(record.get("pdf_physical_pages_reviewed", [])),
            "quote_page": record.get("quote_pdf_page"), "derivative": {}},
        "listing_source": listing_source,
        "semantic_record_sha256": digest(record),
        "body_record_sha256": digest(variant),
        "connect_eligibility_status": variant.get("connect_eligibility_status"),
        "matched_connect_codes": deepcopy(variant.get("matched_connect_codes")),
        "connect_eligibility_identity_sha256": variant.get("connect_eligibility_identity_sha256"),
        "first_hkex_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM",
        **FLAGS,
    }
    if kind == "TEXT_INSUFFICIENT_UNASSESSED":
        out["selection_status"] = "NOT_ASSESSED"
    return out


def _validated_terminal_body_capture(value: Mapping[str, Any] | None,
                                     body_by_code: Mapping[str, Mapping[str, Any]],
                                     expected_codes: set[str]) -> tuple[dict[str, Any] | None, dict[str, dict[str, str]]]:
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
    hkex_unresolved_count = value.get("hkex_unresolved_document_count", 0)
    hkex_unassessed = ((type(hkex_unresolved_count) is int and hkex_unresolved_count > 0)
        or value.get("hkex_body_coverage_status") in {"PARTIAL", "UNASSESSED_SOURCE_IDENTITY_GAPS"})
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
            or status != ("PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS" if not failures and not hkex_unassessed
                          else "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS")
            or any(not isinstance(value.get(key), str)
                   or re.fullmatch(r"[0-9a-f]{64}", value.get(key, "")) is None
                   for key in ("body_corpus_sha256", "body_corpus_manifest_sha256",
                               "body_batch_receipt_sha256", "capture_receipt_sha256"))
            or failures.keys() != failed_rows):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_TERMINAL_INVALID")
    for code, body in body_by_code.items():
        if code in failures:
            if (body.get("body_status") != "BODY_CAPTURE_FAILED"
                    or body.get("pages") != [] or body.get("content_page_count") is not None
                    or body.get("body_text") is not None or body.get("body_text_sha256") is not None
                    or body.get("pdf_sha256") is not None
                    or body.get("capture_receipt_sha256") != failures[code]["receipt_sha256"]):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_FAILURE_ROW_INVALID")
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


def _build_multi_source_product(semantic_catalog: Mapping[str, Any], body_corpus: Mapping[str, Any],
                  catalog_read: Mapping[str, Any], *, semantic_sha256: str,
                  body_sha256: str, verified_inputs: list[Mapping[str, Any]],
                  pdf_derivative_sha256s: Mapping[str, str], target: str,
                  publication: str, terminal_body_capture: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build a source-separated Eastmoney plus official HKEX projection."""
    catalog = _assert_catalog_readback(catalog_read, target, publication)
    if (semantic_catalog.get("schema") != "v4.announcement-semantic-catalog.v2"
            or not isinstance(semantic_catalog.get("status"), str)
            or not semantic_catalog["status"].startswith("PASS_")
            or _date_field(semantic_catalog.get("target_research_date"),
                           "ANNOUNCEMENT_ANALYSIS_CORPUS_TARGET_MISMATCH") != target
            or _publication_date(semantic_catalog.get("target_notice_date")) != publication
            or body_corpus.get("schema") != "v4.manager_research.eastmoney_hk_multi_source_announcement_body_corpus.v1"
            or _publication_date(body_corpus.get("target_notice_date")) != publication
            or body_corpus.get("target_trade_date") != target
            or body_corpus.get("publication_date") != publication):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_CORPUS_IDENTITY_INVALID")
    if not isinstance(terminal_body_capture, Mapping):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MULTI_SOURCE_CAPTURE_EVIDENCE_REQUIRED")

    listings = catalog.get("manager_consumer_rows")
    records = semantic_catalog.get("records")
    body_rows = body_corpus.get("rows")
    variants = body_corpus.get("source_variants")
    if not all(isinstance(value, list) for value in (listings, records, body_rows, variants)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_CORPUS_ROWS_MISSING")
    if (semantic_catalog.get("row_count") != len(records)
            or body_corpus.get("article_count") != len(body_rows)
            or body_corpus.get("eastmoney_article_count") != len(body_rows)
            or body_corpus.get("source_variant_count") != len(variants)
            or body_corpus.get("combined_document_count") != len(body_rows) + len(variants)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SAMPLE_COUNT_MISMATCH")

    eligibility_value = body_corpus.get("monthly_connect_eligibility")
    eligibility_codes, eligibility_identity = _validated_monthly_connect_eligibility(
        eligibility_value, target=target, publication=publication)
    if (terminal_body_capture.get("monthly_connect_eligibility") != eligibility_value
            or terminal_body_capture.get("monthly_connect_eligibility_identity_sha256") != eligibility_identity
            or terminal_body_capture.get("monthly_connect_source_date") != eligibility_value.get("source_date")):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MONTHLY_CONNECT_CAPTURE_BINDING_MISMATCH")

    listing_by_code: dict[str, Mapping[str, Any]] = {}
    eligible_codes: set[str] = set()
    for listing in listings:
        if not isinstance(listing, Mapping) or not isinstance(listing.get("art_code"), str):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_CATALOG_ROW_INVALID")
        code = listing["art_code"]
        if code in listing_by_code:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_CATALOG_DUPLICATE_ART_CODE")
        listing_by_code[code] = listing
        identities = listing.get("source_issuer_codes")
        if not isinstance(identities, list) or not identities:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITIES_MISSING")
        row_codes = [item.get("code") for item in identities if isinstance(item, Mapping)]
        if (len(row_codes) != len(identities)
                or any(not isinstance(value, str) or re.fullmatch(r"HK\.\d{5}", value) is None
                       for value in row_codes)):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITY_INVALID")
        if set(row_codes) & eligibility_codes:
            eligible_codes.add(code)

    body_by_code = {row.get("art_code"): row for row in body_rows if isinstance(row, Mapping)}
    if (len(body_by_code) != len(body_rows) or set(body_by_code) != eligible_codes
            or any("source_variant_id" in row for row in body_rows if isinstance(row, Mapping))):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_ELIGIBLE_EASTMONEY_SET_MISMATCH")
    if any(not isinstance(row.get("notice_date"), str)
           or row["notice_date"][:10] != publication for code, row in listing_by_code.items()
           if code in eligible_codes):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_LISTING_DATE_MISMATCH")

    variant_by_id: dict[str, Mapping[str, Any]] = {}
    for variant in variants:
        if not isinstance(variant, Mapping):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_VARIANT_INVALID")
        _verify_hkex_variant_body(variant, publication)
        variant_id = variant["source_variant_id"]
        if variant_id in variant_by_id:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_VARIANT_DUPLICATE")
        if (variant.get("connect_eligibility_status") != "ELIGIBLE"
                or variant.get("connect_eligibility_identity_sha256") != eligibility_identity
                or variant.get("symbol") not in eligibility_codes
                or variant.get("matched_connect_codes") != [variant.get("symbol")]):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_CONNECT_ELIGIBILITY_MISMATCH")
        variant_by_id[variant_id] = variant

    semantic_by_identity: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_RECORD_INVALID")
        identity = _record_identity(record)
        if identity in semantic_by_identity:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_RECORD_DUPLICATE")
        semantic_by_identity[identity] = record
    expected_identities = ({("art_code", code) for code in eligible_codes}
        | {("source_variant_id", variant_id) for variant_id in variant_by_id})
    if set(semantic_by_identity) != expected_identities:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_COMBINED_SOURCE_RECORD_SET_MISMATCH")

    terminal_variant_rows = terminal_body_capture.get("hkex_variant_records")
    if not isinstance(terminal_variant_rows, list):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_CAPTURE_VARIANTS_MISSING")
    terminal_variants = {row.get("source_variant_id"): row for row in terminal_variant_rows
        if isinstance(row, Mapping)}
    if (len(terminal_variants) != len(terminal_variant_rows)
            or set(terminal_variants) != set(variant_by_id)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_CAPTURE_VARIANT_SET_MISMATCH")
    hkex_readback_sha = terminal_body_capture.get("hkex_directory_readback_sha256")
    if (body_corpus.get("hkex_directory_readback_sha256") != hkex_readback_sha
            or body_corpus.get("hkex_directory_product_run_ids") != terminal_body_capture.get("hkex_directory_run_ids")
            or body_corpus.get("hkex_directory_document_count") != terminal_body_capture.get("hkex_directory_document_count")
            or body_corpus.get("hkex_eligible_document_count") != terminal_body_capture.get("hkex_eligible_document_count")
            or body_corpus.get("hkex_excluded_document_count") != terminal_body_capture.get("hkex_excluded_document_count")
            or body_corpus.get("hkex_unresolved_document_count") != terminal_body_capture.get("hkex_unresolved_document_count")
            or body_corpus.get("hkex_cross_source_link_status") != "NOT_ASSESSED"
            or terminal_body_capture.get("hkex_eligible_document_count") != len(variants)
            or terminal_body_capture.get("hkex_directory_document_count") != (
                terminal_body_capture.get("hkex_eligible_document_count", -1)
                + terminal_body_capture.get("hkex_excluded_document_count", -1)
                + terminal_body_capture.get("hkex_unresolved_document_count", -1))):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_DIRECTORY_COVERAGE_MISMATCH")
    if (body_corpus.get("input_identity_sha256") != terminal_body_capture.get("input_identity_sha256")
            or body_corpus.get("source_manifest_sha256") != terminal_body_capture.get("body_corpus_manifest_sha256")):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_CAPTURE_IDENTITY_MISMATCH")
    if terminal_body_capture.get("body_corpus_sha256") != body_sha256:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_CAPTURE_BODY_SHA_MISMATCH")

    body_capture, failures = _validated_terminal_body_capture(
        terminal_body_capture, body_by_code, eligible_codes)
    for code in sorted(eligible_codes):
        listing = listing_by_code[code]
        body = body_by_code[code]
        semantic = semantic_by_identity[("art_code", code)]
        if (semantic.get("title") not in {None, listing.get("title")}
                or body.get("title") not in {None, listing.get("title")}):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_LISTING_SOURCE_MISMATCH")
        source_identities = listing.get("source_issuer_codes")
        listing_codes = [item.get("code") for item in source_identities if isinstance(item, Mapping)]
        semantic_codes = [item.get("code") for item in semantic.get("issuer_codes", [])
                          if isinstance(item, Mapping)]
        if len(semantic_codes) != len(semantic.get("issuer_codes", [])) or semantic_codes != listing_codes:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_ISSUER_BINDING_MISMATCH")
        if code not in failures:
            _verify_body_source_rows(body, code, publication)
    for variant_id, variant in variant_by_id.items():
        evidence = terminal_variants[variant_id]
        if (evidence.get("body_record_sha256") != digest(variant)
                or evidence.get("body_file_sha256") != variant.get("body_artifact_sha256")
                or evidence.get("body_status") != variant.get("body_status")
                or evidence.get("directory_source_ref") != _source_ref(variant.get("directory_source_ref"))
                or evidence.get("body_source_ref") != _source_ref(variant.get("body_source_ref"))):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_BODY_ARTIFACT_BINDING_MISMATCH")

    canonical_objects = {"semantic_catalog": semantic_catalog, "body_corpus": body_corpus}
    descriptors = _verified_input_descriptors(verified_inputs, canonical_objects=canonical_objects)
    by_name = {item["name"]: item for item in descriptors}
    if (by_name["semantic_catalog"]["sha256"] != semantic_sha256
            or by_name["body_corpus"]["sha256"] != body_sha256
            or by_name["semantic_catalog"]["row_count"] != len(records)
            or by_name["body_corpus"]["row_count"] != len(body_rows)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_INPUT_SHA_OR_COUNT_MISMATCH")

    derivative_shas = dict(pdf_derivative_sha256s)
    if any(not isinstance(code, str) or not isinstance(value, str)
            or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for code, value in derivative_shas.items()):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_DERIVATIVE_MANIFEST_INVALID")
    out_records: list[dict[str, Any]] = []
    kinds: dict[str, int] = {}
    for code in sorted(eligible_codes):
        row = _analysis_record(semantic_by_identity[("art_code", code)], body_by_code[code],
            listing_by_code[code], body_capture_failure=failures.get(code))
        out_records.append(row)
        kinds[row["analysis_kind"]] = kinds.get(row["analysis_kind"], 0) + 1
    for variant_id in sorted(variant_by_id):
        row = _analysis_hkex_record(semantic_by_identity[("source_variant_id", variant_id)],
                                    variant_by_id[variant_id])
        out_records.append(row)
        kinds[row["analysis_kind"]] = kinds.get(row["analysis_kind"], 0) + 1
    derivative_keys = {row["art_code"] for row in out_records
        if row["analysis_kind"] == "LONG_PDF_KEY_SECTION_READ"}
    if set(derivative_shas) != derivative_keys:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_DERIVATIVE_BINDING_MISMATCH")

    source_identity_associations, distinct_source_codes = _source_identity_metrics(catalog)
    hkex_status_counts: dict[str, int] = {}
    for variant in variant_by_id.values():
        body_status = str(variant.get("body_status") or "UNKNOWN")
        hkex_status_counts[body_status] = hkex_status_counts.get(body_status, 0) + 1
    hkex_directory_count = terminal_body_capture.get("hkex_directory_document_count")
    hkex_excluded_count = terminal_body_capture.get("hkex_excluded_document_count")
    hkex_unresolved_count = terminal_body_capture.get("hkex_unresolved_document_count")
    if any(type(value) is not int or value < 0 for value in (
            hkex_directory_count, hkex_excluded_count, hkex_unresolved_count)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_DIRECTORY_COVERAGE_MISMATCH")
    counts = {
        "directory_records": catalog.get("captured_row_count"),
        "directory_pages": catalog.get("captured_page_count"),
        "manager_announcements": len(out_records),
        "manager_source_identity_associations": source_identity_associations,
        "distinct_manager_source_codes": len(distinct_source_codes),
        "complete_api_bodies": kinds.get("COMPLETE_API_BODY", 0),
        "long_pdf_focus_reads": kinds.get("LONG_PDF_KEY_SECTION_READ", 0),
        "text_insufficient_unassessed": kinds.get("TEXT_INSUFFICIENT_UNASSESSED", 0),
        "eligible_eastmoney_announcements": len(eligible_codes),
        "hkex_official_announcements": len(variant_by_id),
        "combined_eligible_announcements": len(out_records),
        "complete_hkex_pdf_bodies": kinds.get(_HKEX_COMPLETE_BODY, 0),
    }
    unresolved_gap = hkex_unresolved_count > 0
    if not variant_by_id and unresolved_gap:
        hkex_coverage_status = "UNASSESSED_SOURCE_IDENTITY_GAPS"
    elif not variant_by_id:
        hkex_coverage_status = "NO_ELIGIBLE_DOCUMENTS"
    elif all(row.get("body_status") == _HKEX_COMPLETE_BODY for row in variant_by_id.values()) and not unresolved_gap:
        hkex_coverage_status = "COMPLETE"
    else:
        hkex_coverage_status = "PARTIAL"
    source_manifest = {
        "target_trade_date": target, "publication_date": publication,
        "source_scope": "EASTMONEY_HK_DATE_CATALOG",
        "additional_source_scopes": [_HKEX_DIRECTORY_SCOPE],
        "catalog_run_id": catalog.get("run_id"),
        "catalog_product_sha256": catalog.get("sha256"),
        "catalog_row_count": catalog.get("captured_row_count"),
        "catalog_page_count": catalog.get("captured_page_count"),
        "manager_sample_count": catalog.get("manager_consumer_row_count"),
        "manager_issuer_count": None, "unknown_issuer_count": None,
        "issuer_count_status": "CANNOT_CONFIRM",
        "manager_source_identity_association_count": source_identity_associations,
        "distinct_manager_source_code_count": len(distinct_source_codes),
        "semantic_catalog_sha256": semantic_sha256, "body_corpus_sha256": body_sha256,
        "verified_inputs": descriptors,
        "pdf_derivative_sha256s": dict(sorted(derivative_shas.items())),
        "hkex_directory_readback_sha256": hkex_readback_sha,
        "hkex_directory_run_ids": terminal_body_capture.get("hkex_directory_run_ids"),
        "hkex_directory_document_count": hkex_directory_count,
        "hkex_eligible_document_count": len(variant_by_id),
        "hkex_excluded_document_count": hkex_excluded_count,
        "hkex_unresolved_document_count": hkex_unresolved_count,
        "hkex_source_variant_count": len(variant_by_id),
        "hkex_source_variant_sha256s": {
            variant_id: digest(variant) for variant_id, variant in sorted(variant_by_id.items())},
        "hkex_body_status_counts": dict(sorted(hkex_status_counts.items())),
        "hkex_body_coverage_status": hkex_coverage_status,
        "hkex_unresolved_source_identity_gap": unresolved_gap,
        "hkex_cross_source_link_status": "NOT_ASSESSED",
        "monthly_connect_eligibility_identity_sha256": eligibility_identity,
        "monthly_connect_source_date": eligibility_value.get("source_date"),
        "monthly_connect_code_count": eligibility_value.get("code_count"),
        "counts": counts,
        "first_publication_and_cutoff_status": "CANNOT_CONFIRM",
        "novelty_vs_prior_status": "CANNOT_CONFIRM",
        "point_in_time_status": "CANNOT_CONFIRM",
        "connect_eligibility_status": "VERIFIED_MONTHLY_SNAPSHOT",
    }
    if body_capture is not None:
        source_manifest["terminal_body_capture"] = body_capture
    product = {
        "schema_version": MULTI_SOURCE_SCHEMA, "status": "VERIFIED",
        "target_trade_date": target, "publication_date": publication,
        "producer": "OFFLINE_REVIEWED_SEMANTIC_CATALOG_IMPORT",
        "source_manifest": source_manifest,
        "source_manifest_sha256": digest(source_manifest),
        "summary": {**counts,
            "manager_source_identity_association_count": source_identity_associations,
            "distinct_manager_source_code_count": len(distinct_source_codes),
            "manager_issuer_count": None, "unknown_issuer_count": None,
            "issuer_count_status": "CANNOT_CONFIRM"},
        "interpretation_boundary": (
            "事后研究解读；Eastmoney 与 HKEX 官方文件保留各自源 ID 和来源边界。"
            "港股通名单为当月已验证快照；首次发布时间与历史 PIT 仍未确认，不构成交易信号或 BUY 输入。"
        ),
        "gaps": (["HKEX_SOURCE_IDENTITY_UNRESOLVED"] if unresolved_gap else []),
        "records": out_records, **FLAGS,
    }
    product["sha256"] = digest(product)
    return product


def _validate_multi_source_product(product: Mapping[str, Any], target: str,
                                   publication: str, catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the imported multi-source projection without joining source IDs."""
    manifest = product.get("source_manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MANIFEST_MISSING")
    counts = manifest.get("counts")
    records = product.get("records")
    listings = catalog.get("manager_consumer_rows")
    terminal = manifest.get("terminal_body_capture")
    if not isinstance(counts, Mapping) or not isinstance(records, list) or not isinstance(listings, list):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_RECORDS_MISSING")
    if not isinstance(terminal, Mapping):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MULTI_SOURCE_CAPTURE_EVIDENCE_REQUIRED")
    eligibility_value = terminal.get("monthly_connect_eligibility")
    eligibility_codes, eligibility_identity = _validated_monthly_connect_eligibility(
        eligibility_value, target=target, publication=publication)
    if (eligibility_identity != manifest.get("monthly_connect_eligibility_identity_sha256")
            or eligibility_value.get("source_date") != manifest.get("monthly_connect_source_date")
            or terminal.get("monthly_connect_eligibility_identity_sha256") != eligibility_identity):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MONTHLY_CONNECT_BINDING_MISMATCH")

    listing_by_code: dict[str, Mapping[str, Any]] = {}
    eligible_codes: set[str] = set()
    for listing in listings:
        if not isinstance(listing, Mapping) or not isinstance(listing.get("art_code"), str):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_CATALOG_ROW_INVALID")
        code = listing["art_code"]
        if code in listing_by_code:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_CATALOG_DUPLICATE_ART_CODE")
        listing_by_code[code] = listing
        identities = listing.get("source_issuer_codes")
        if not isinstance(identities, list) or not identities:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITIES_MISSING")
        issuer_codes = [item.get("code") for item in identities if isinstance(item, Mapping)]
        if (len(issuer_codes) != len(identities)
                or any(not isinstance(value, str) or re.fullmatch(r"HK\.\d{5}", value) is None
                       for value in issuer_codes)):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITY_INVALID")
        if set(issuer_codes) & eligibility_codes:
            eligible_codes.add(code)

    variant_rows = terminal.get("hkex_variant_records")
    if not isinstance(variant_rows, list):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_CAPTURE_VARIANTS_MISSING")
    variant_by_id = {row.get("source_variant_id"): row for row in variant_rows
                     if isinstance(row, Mapping)}
    if (len(variant_by_id) != len(variant_rows)
            or any(not isinstance(key, str) or not key.startswith("HKEX:") for key in variant_by_id)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_CAPTURE_VARIANTS_INVALID")
    if (manifest.get("hkex_eligible_document_count") != len(variant_by_id)
            or manifest.get("hkex_source_variant_count") != len(variant_by_id)
            or manifest.get("hkex_directory_document_count") != (
                manifest.get("hkex_eligible_document_count", -1)
                + manifest.get("hkex_excluded_document_count", -1)
                + manifest.get("hkex_unresolved_document_count", -1))
            or terminal.get("hkex_directory_readback_sha256") != manifest.get("hkex_directory_readback_sha256")
            or terminal.get("hkex_directory_document_count") != manifest.get("hkex_directory_document_count")
            or terminal.get("hkex_eligible_document_count") != manifest.get("hkex_eligible_document_count")
            or terminal.get("hkex_excluded_document_count") != manifest.get("hkex_excluded_document_count")
            or terminal.get("hkex_unresolved_document_count") != manifest.get("hkex_unresolved_document_count")
            or terminal.get("hkex_directory_run_ids") != manifest.get("hkex_directory_run_ids")
            or manifest.get("hkex_cross_source_link_status") != "NOT_ASSESSED"):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_DIRECTORY_COVERAGE_MISMATCH")
    source_variant_shas = manifest.get("hkex_source_variant_sha256s")
    if (not isinstance(source_variant_shas, Mapping)
            or set(source_variant_shas) != set(variant_by_id)
            or any(variant_by_id[key].get("body_record_sha256") != value
                   or not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
                   for key, value in source_variant_shas.items())):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_VARIANT_SHA_SET_MISMATCH")
    if (terminal.get("hkex_eligible_document_count") != len(variant_by_id)
            or terminal.get("hkex_directory_document_count") != (
                terminal.get("hkex_eligible_document_count", -1)
                + terminal.get("hkex_excluded_document_count", -1)
                + terminal.get("hkex_unresolved_document_count", -1))):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_DIRECTORY_COVERAGE_MISMATCH")

    by_identity: dict[tuple[str, str], Mapping[str, Any]] = {}
    kinds: dict[str, int] = {}
    for row in records:
        if not isinstance(row, Mapping):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_RECORD_INVALID")
        if any(row.get(key) is not value for key, value in FLAGS.items()):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_RECORD_SAFETY_FLAGS_INVALID")
        identity = _record_identity(row)
        if identity in by_identity:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_RECORD_IDENTITY_INVALID")
        by_identity[identity] = row
        kind = row.get("analysis_kind")
        if kind not in {"COMPLETE_API_BODY", "LONG_PDF_KEY_SECTION_READ",
                        "TEXT_INSUFFICIENT_UNASSESSED", _HKEX_COMPLETE_BODY}:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_KIND_INVALID")
        kinds[kind] = kinds.get(kind, 0) + 1
    expected_identities = ({("art_code", code) for code in eligible_codes}
        | {("source_variant_id", key) for key in variant_by_id})
    if set(by_identity) != expected_identities:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_COMBINED_SOURCE_RECORD_SET_MISMATCH")
    if (counts.get("eligible_eastmoney_announcements") != len(eligible_codes)
            or counts.get("hkex_official_announcements") != len(variant_by_id)
            or counts.get("combined_eligible_announcements") != len(expected_identities)
            or counts.get("manager_announcements") != len(expected_identities)
            or len(records) != len(expected_identities)):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_MANAGER_SAMPLE_MISMATCH")

    projected_em = {}
    for code in eligible_codes:
        row = by_identity[("art_code", code)]
        listing = listing_by_code[code]
        source = row.get("listing_source")
        if (not isinstance(source, Mapping)
                or row.get("title") != listing.get("title")
                or source.get("page_index") != listing.get("page_index")
                or source.get("item_index") != listing.get("item_index")
                or source.get("notice_date") != listing.get("notice_date")
                or source.get("display_time") != listing.get("display_time")
                or source.get("raw_body_sha256") != listing.get("raw_body_sha256")
                or source.get("source_ref") != _source_ref(listing.get("source_ref"))):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_LISTING_SOURCE_MISMATCH")
        source_codes = [item.get("code") for item in listing["source_issuer_codes"]]
        record_codes = [item.get("code") for item in row.get("issuer_codes", [])
                        if isinstance(item, Mapping)]
        if (len(record_codes) != len(row.get("issuer_codes", []))
                or record_codes != source_codes or not set(source_codes) & eligibility_codes):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_ISSUER_BINDING_MISMATCH")
        if row.get("body_status") == "BODY_CAPTURE_FAILED":
            if (row.get("analysis_kind") != "TEXT_INSUFFICIENT_UNASSESSED"
                    or row.get("selection_status") != "NOT_ASSESSED"):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_FAILURE_PROJECTION_INVALID")
        elif row.get("analysis_kind") == "COMPLETE_API_BODY" and not row.get("body_page_citations"):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_BODY_SOURCE_MISSING")
        elif row.get("analysis_kind") == "LONG_PDF_KEY_SECTION_READ" and not row.get("pdf_focus", {}).get("source_url"):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_PDF_SOURCE_MISSING")
        projected_em[code] = {
            "body_status": row.get("body_status"),
            "pages": row.get("body_page_citations"),
            "content_page_count": row.get("body_page_count"),
            "body_text": None,
            "body_text_sha256": row.get("body_text_sha256"),
            "pdf_sha256": (row.get("pdf_focus") or {}).get("sha256")
                if isinstance(row.get("pdf_focus"), Mapping) else None,
            "capture_receipt_sha256": (row.get("body_capture_failure") or {}).get("receipt_sha256")
                if isinstance(row.get("body_capture_failure"), Mapping) else None,
        }
    body_capture = terminal
    _validated_terminal_body_capture(body_capture, projected_em, eligible_codes)

    for variant_id, evidence in variant_by_id.items():
        row = by_identity[("source_variant_id", variant_id)]
        listing_source = row.get("listing_source")
        if (row.get("source") != "HKEX_OFFICIAL"
                or row.get("source_scope") != _HKEX_DIRECTORY_SCOPE
                or row.get("news_id") != variant_id[5:]
                or row.get("body_status") != evidence.get("body_status")
                or row.get("body_record_sha256") != evidence.get("body_record_sha256")
                or not isinstance(listing_source, Mapping)
                or listing_source.get("source_variant_id") != variant_id
                or listing_source.get("directory_source_ref") != evidence.get("directory_source_ref")
                or listing_source.get("body_source_ref") != evidence.get("body_source_ref")
                or row.get("title") != evidence.get("title")
                or row.get("issuer_codes") != [{"code": evidence.get("symbol"), "name": evidence.get("name")}]
                or row.get("selection_status") != (None if evidence.get("body_status") == _HKEX_COMPLETE_BODY else "NOT_ASSESSED")):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_RECORD_SOURCE_MISMATCH")
        if evidence.get("symbol") not in eligibility_codes:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_HKEX_CONNECT_ELIGIBILITY_MISMATCH")

    expected_kinds = {
        "COMPLETE_API_BODY": counts.get("complete_api_bodies", 0),
        "LONG_PDF_KEY_SECTION_READ": counts.get("long_pdf_focus_reads", 0),
        "TEXT_INSUFFICIENT_UNASSESSED": counts.get("text_insufficient_unassessed", 0),
        _HKEX_COMPLETE_BODY: counts.get("complete_hkex_pdf_bodies", 0),
    }
    if kinds != {key: value for key, value in expected_kinds.items() if value}:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_KIND_COUNTS_MISMATCH")
    if (counts.get("manager_source_identity_associations") != manifest.get("manager_source_identity_association_count")
            or counts.get("distinct_manager_source_codes") != manifest.get("distinct_manager_source_code_count")
            or manifest.get("manager_issuer_count") is not None
            or manifest.get("unknown_issuer_count") is not None
            or manifest.get("issuer_count_status") != "CANNOT_CONFIRM"):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITY_SUMMARY_MISMATCH")
    summary = product.get("summary")
    if not isinstance(summary, Mapping) or any(summary.get(key) != value for key, value in counts.items()):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SUMMARY_MISMATCH")
    if any(summary.get(key) != manifest.get(key) for key in (
            "manager_source_identity_association_count", "distinct_manager_source_code_count",
            "manager_issuer_count", "unknown_issuer_count", "issuer_count_status")):
        raise ValueError("ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITY_SUMMARY_MISMATCH")

    unassessed = {identity for identity, row in by_identity.items()
        if row.get("analysis_kind") == "TEXT_INSUFFICIENT_UNASSESSED"
        or has_reader_declared_content_gap(row)}
    if "stock_selection" in product:
        from .announcement_selection import read_projection
        read_projection(product)
        decisions = product["stock_selection"].get("article_decisions", [])
        decision_by_identity = {_record_identity(row): row for row in decisions if isinstance(row, Mapping)}
        if any(decision_by_identity.get(identity, {}).get("disposition") != "NOT_ASSESSED"
               for identity in unassessed):
            raise ValueError("ANNOUNCEMENT_ANALYSIS_UNASSESSED_CONTENT_SELECTION_MUST_BE_NOT_ASSESSED")
    elif unassessed:
        pass
    expected_gaps = ["HKEX_SOURCE_IDENTITY_UNRESOLVED"] if manifest.get("hkex_unresolved_document_count", 0) else []
    if product.get("gaps") != expected_gaps:
        raise ValueError("ANNOUNCEMENT_ANALYSIS_COVERAGE_GAPS_MISMATCH")
    return deepcopy(dict(product))


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
    if body_corpus.get("schema") == "v4.manager_research.eastmoney_hk_multi_source_announcement_body_corpus.v1":
        return _build_multi_source_product(semantic_catalog, body_corpus, catalog_read,
            semantic_sha256=semantic_sha256, body_sha256=body_sha256,
            verified_inputs=verified_inputs, pdf_derivative_sha256s=pdf_derivative_sha256s or {},
            target=target, publication=publication, terminal_body_capture=terminal_body_capture)
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
        terminal_body_capture, body_by_code, expected_codes)
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
    if product.get("schema_version") == "v4.manager_research.announcement_analysis_import_ref.v1":
        if set(product) != {"schema_version", "evidence_run_id", "handoff_manifest_sha256", "product_sha256"}:
            raise ValueError("ANNOUNCEMENT_ANALYSIS_IMPORT_ENVELOPE_INVALID")
        return import_registered_product(service, product["evidence_run_id"],
            product["handoff_manifest_sha256"], product["product_sha256"])
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


def import_registered_product(service: Any, evidence_run_id: str,
                              handoff_manifest_sha256: str,
                              product_sha256: str) -> dict[str, Any]:
    """Import a registered, independently reviewed product through the owner.

    The API must pass *references*, never client-supplied analysis/decisions.
    The existing unreviewed legacy importer remains available for compatible
    research archives but cannot create this receipt or satisfy consumption.
    The product and the owner-import receipt share the date-scoped writer lock.
    """
    from .workspace_announcements import (
        _now, validate_agent_judgment_receipt, validate_owner_analysis_import_receipt,
        validate_registered_handoff, read_analysis_consumption,
    )

    registered = validate_registered_handoff(service.store, evidence_run_id,
        handoff_manifest_sha256, product_sha256)
    product = registered['product']
    agent = validate_agent_judgment_receipt(product.get('agent_judgment_receipt'), product)
    if (agent['evidence_run_id'] != evidence_run_id
            or product.get('sha256') != product_sha256):
        raise ValueError('ANNOUNCEMENT_ANALYSIS_REGISTERED_PRODUCT_IDENTITY_MISMATCH')
    target = date_token(product.get('target_trade_date'))
    publication = _publication_date(product.get('publication_date'))
    catalog_read = service.get_announcement_date_catalog(target, publication)
    catalog = _assert_catalog_readback(catalog_read, target, publication)
    checked = validate_product(product, target_trade_date=target,
        publication_date=publication, catalog=catalog)
    if checked.get('sha256') != product_sha256:
        raise ValueError('ANNOUNCEMENT_ANALYSIS_REGISTERED_PRODUCT_SHA_MISMATCH')
    path = product_path(service.store, target, publication)
    receipt_path = path.with_name('owner_import_receipt.v1.json')
    with service.store._transaction(target, 'announcement-analysis-' + publication.replace('-', '')):
        previous = service.store._read(path)
        if previous is not None:
            previous = validate_product(previous, target_trade_date=target,
                publication_date=publication, catalog=catalog)
            if previous != checked:
                raise ValueError('ANNOUNCEMENT_ANALYSIS_PRODUCT_EXISTS')
        existing_receipt = service.store._read(receipt_path)
        if existing_receipt is not None:
            receipt = validate_owner_analysis_import_receipt(existing_receipt, checked)
            if (receipt.get('parent_task_id') != agent['parent_task_id']
                    or receipt.get('parent_run_id') != agent['parent_run_id']
                    or receipt.get('source_manifest_sha256') != checked.get('source_manifest_sha256')
                    or receipt.get('evidence_run_id') != evidence_run_id
                    or receipt.get('handoff_manifest_sha256') != handoff_manifest_sha256
                    or receipt.get('agent_judgment_receipt_sha256') != agent['sha256']):
                raise ValueError('ANNOUNCEMENT_ANALYSIS_OWNER_RECEIPT_CONFLICT')
        else:
            receipt = {
                'schema_version': 'v4.manager_research.announcement_analysis_owner_import.v1',
                'status': 'VERIFIED', 'target_trade_date': target,
                'publication_date': publication, 'product_sha256': product_sha256,
                'source_manifest_sha256': checked['source_manifest_sha256'],
                'evidence_run_id': evidence_run_id,
                'handoff_manifest_sha256': handoff_manifest_sha256,
                'agent_judgment_receipt_sha256': agent['sha256'],
                'parent_task_id': agent['parent_task_id'],
                'parent_run_id': agent['parent_run_id'],
                'available_at': _now(),
                'owner': 'ManagerResearchJobService.import_announcement_analysis',
                **FLAGS,
            }
            receipt['sha256'] = digest(receipt)
            validate_owner_analysis_import_receipt(receipt, checked)
        if previous is None:
            service.store._write_atomic(path, checked)
        if existing_receipt is None:
            service.store._write_atomic(receipt_path, receipt)
    readback = service.get_announcement_analysis(target, publication)
    if (readback.get('analysis', {}).get('status') != 'VERIFIED'
            or readback['analysis'].get('product_sha256') != product_sha256):
        raise ValueError('ANNOUNCEMENT_ANALYSIS_REGISTERED_READBACK_FAILED')
    consumption = read_analysis_consumption(service, target, publication,
        analysis_readback=readback)
    if (consumption.get('validation_status') != 'VERIFIED'
            or consumption.get('product_sha256') != product_sha256
            or consumption.get('owner_import_receipt_sha256') != receipt['sha256']):
        raise ValueError('ANNOUNCEMENT_ANALYSIS_REGISTERED_CONSUMPTION_READBACK_FAILED')
    readback.update(import_status='ALREADY_IMPORTED' if previous is not None else 'IMPORTED',
        owner_import_receipt=deepcopy(receipt), consumption_validation=consumption,
        evidence_run_id=evidence_run_id, handoff_manifest_sha256=handoff_manifest_sha256)
    return readback

def read(service: Any, target_trade_date: str,
         publication_date: str | None = None) -> dict[str, Any]:
    """Read the exact owner catalog and its optional derived analysis product."""
    target = date_token(target_trade_date)
    explicit = publication_date is not None
    if explicit:
        publication = _publication_date(publication_date)
        date_selection_basis = "EXPLICIT"
    else:
        current_day = _current_hk_datetime().date()
        if target == current_day.strftime("%Y%m%d"):
            publication = (current_day - timedelta(days=1)).isoformat()
            date_selection_basis = "CURRENT_TARGET_PREVIOUS_CALENDAR_DAY"
        else:
            publication = _publication_date(previous_hk_session(target))
            date_selection_basis = "PREVIOUS_HK_TRADING_SESSION"
    catalog_read = service.get_announcement_date_catalog(target, publication)
    source = _catalog_summary(catalog_read)
    result = {
        "schema_version": READ_SCHEMA,
        "target_trade_date": target,
        "publication_date": publication,
        "date_selection_basis": date_selection_basis,
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
