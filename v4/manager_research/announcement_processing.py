"""Deterministic projections for already captured and reviewed announcements.

This module consumes owner-bound products only. It does not collect sources,
call a model, or alter the canonical source identities or decisions.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, time, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .workspace_projection import digest

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HKEX_ID = re.compile(r"^HKEX:\d{5,20}$")
_CODE = re.compile(r"^HK\.\d{5}$")
_RULE_REVIEW_SCHEMA = "v4.manager_research.announcement_rule_review.v1"
_RULE_RECEIPT_SCHEMA = "v4.manager_research.announcement_rule_review_receipt.v1"
_RULE_VERSION = "POSITIVE_OPERATING_RESEARCH_V1"
_HK = ZoneInfo("Asia/Hong_Kong")
_RULE_DISPOSITIONS = {
    "SELECTED_EVENT", "SELECTED_PERFORMANCE", "CONDITIONAL_WATCH",
    "NOT_SELECTED", "NOT_ASSESSED",
}
_RULE_DIRECTIONS = {"POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN"}
_RULE_EVIDENCE = {"VERIFIED_EXISTING_FACTS", "INSUFFICIENT_EXISTING_FACTS"}
_WINDOW_INPUT_SCHEMA = "v4.manager_research.announcement_preopen_window_inputs.v1"
_WINDOW_SCHEMA = "v4.manager_research.announcement_preopen_window.v1"


def _identity(value: Mapping[str, Any]) -> tuple[str, str] | None:
    article = value.get("art_code")
    variant = value.get("source_variant_id")
    if isinstance(article, str) and article and variant is None:
        return "art_code", article
    if isinstance(variant, str) and _HKEX_ID.fullmatch(variant) and article is None:
        return "source_variant_id", variant
    return None


def _source_refs(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    listing = record.get("listing_source")
    if not isinstance(listing, Mapping):
        return []
    refs: list[dict[str, Any]] = []
    candidates = [listing.get("source_ref"), listing.get("directory_source_ref"),
                  listing.get("body_source_ref")]
    pages = record.get("body_page_citations")
    if isinstance(pages, list):
        candidates.extend(page.get("source_ref") for page in pages if isinstance(page, Mapping))
    seen: set[tuple[Any, ...]] = set()
    for ref in candidates:
        if not isinstance(ref, Mapping):
            continue
        url, blob_sha, body_sha = ref.get("url"), ref.get("blob_sha256"), ref.get("body_sha256")
        if not isinstance(url, str) or not isinstance(body_sha, str) or not _SHA256.fullmatch(body_sha):
            continue
        if blob_sha is not None and (not isinstance(blob_sha, str) or not _SHA256.fullmatch(blob_sha)):
            continue
        key = (url, blob_sha, body_sha)
        if key in seen:
            continue
        seen.add(key)
        refs.append({"url": url, "blob_sha256": blob_sha, "body_sha256": body_sha})
    return refs


def _decision_index(decisions: Any) -> dict[tuple[str, str], Mapping[str, Any]]:
    if decisions is None:
        return {}
    if not isinstance(decisions, list):
        raise ValueError("ANNOUNCEMENT_PROCESSING_DECISIONS_INVALID")
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, Mapping):
            raise ValueError("ANNOUNCEMENT_PROCESSING_DECISIONS_INVALID")
        identity = _identity(decision)
        if identity is None or identity in result:
            raise ValueError("ANNOUNCEMENT_PROCESSING_DECISION_IDENTITY_INVALID")
        result[identity] = decision
    return result


def _body_index(body_corpus: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    rows = body_corpus.get("rows")
    variants = body_corpus.get("source_variants", [])
    if not isinstance(rows, list) or not isinstance(variants, list):
        raise ValueError("ANNOUNCEMENT_PROCESSING_BODY_ROWS_INVALID")
    for collection in (rows, variants):
        for item in collection:
            if not isinstance(item, Mapping):
                raise ValueError("ANNOUNCEMENT_PROCESSING_BODY_ROW_INVALID")
            identity = _identity(item)
            if identity is None or identity in result:
                raise ValueError("ANNOUNCEMENT_PROCESSING_BODY_IDENTITY_INVALID")
            result[identity] = item
    return result


def _explicit_event_link(record: Mapping[str, Any], body: Mapping[str, Any] | None) -> str | None:
    listing = record.get("listing_source")
    values = [record.get("event_id"), body.get("event_id") if isinstance(body, Mapping) else None,
              listing.get("event_id") if isinstance(listing, Mapping) else None]
    nonempty = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    if nonempty and len(set(nonempty)) == 1:
        return nonempty[0]
    return None


def build_incremental_processing(
    product: Mapping[str, Any], body_corpus: Mapping[str, Any], decisions: Any, *,
    target_trade_date: str, publication_date: str, semantic_sha256: str,
    body_sha256: str, decision_sha256: str | None, reviewer_sha256: str,
) -> dict[str, Any]:
    """Project source-bound structured events, exact reuse, and pending work.

    Caller must invoke this only after validating the reviewer receipt and the
    source/body products. Candidate content matches remain unmerged unless an
    explicit common event id also binds date, issuer, and exact content hash.
    """
    for name, value in (("semantic", semantic_sha256), ("body", body_sha256),
                        ("reviewer", reviewer_sha256)):
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ValueError(f"ANNOUNCEMENT_PROCESSING_{name.upper()}_SHA_INVALID")
    if decision_sha256 is not None and (not isinstance(decision_sha256, str)
            or not _SHA256.fullmatch(decision_sha256)):
        raise ValueError("ANNOUNCEMENT_PROCESSING_DECISION_SHA_INVALID")
    if (product.get("target_trade_date") != target_trade_date
            or product.get("publication_date") != publication_date):
        raise ValueError("ANNOUNCEMENT_PROCESSING_DATE_BINDING_MISMATCH")

    raw_records = product.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("ANNOUNCEMENT_PROCESSING_RECORDS_INVALID")
    records: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in raw_records:
        if not isinstance(record, Mapping):
            raise ValueError("ANNOUNCEMENT_PROCESSING_RECORD_INVALID")
        identity = _identity(record)
        if identity is None or identity in records:
            raise ValueError("ANNOUNCEMENT_PROCESSING_RECORD_IDENTITY_INVALID")
        records[identity] = record

    decisions_by_identity = _decision_index(decisions)
    body_by_identity = _body_index(body_corpus)
    decision_status = "EXPLICIT_DISPOSITIONS" if decisions is not None else "NOT_ASSESSED"
    if decisions is not None and set(decisions_by_identity) - set(records):
        raise ValueError("ANNOUNCEMENT_PROCESSING_DECISION_SOURCE_MISMATCH")

    events: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    source_members: list[dict[str, Any]] = []
    source_refs_preserved = 0
    for identity in sorted(records):
        record = records[identity]
        body = body_by_identity.get(identity)
        listing = record.get("listing_source")
        issuers = record.get("issuer_codes")
        issuer_codes = sorted({item.get("code") for item in issuers
            if isinstance(item, Mapping) and isinstance(item.get("code"), str)
            and _CODE.fullmatch(item.get("code", ""))}) if isinstance(issuers, list) else []
        refs = _source_refs(record)
        source_refs_preserved += len(refs)
        decision = decisions_by_identity.get(identity)
        decision_disposition = decision.get("disposition") if isinstance(decision, Mapping) else None
        body_bound = (isinstance(body, Mapping)
            and record.get("body_record_sha256") == digest(body)
            and record.get("body_text_sha256") == body.get("body_text_sha256"))
        gap = (record.get("analysis_kind") == "TEXT_INSUFFICIENT_UNASSESSED"
               or record.get("selection_status") == "NOT_ASSESSED"
               or not body_bound)
        assessment = "NOT_ASSESSED" if gap else "REVIEWED"
        event = {
            "source_identity": {"kind": identity[0], "id": identity[1]},
            "source": record.get("source", "EASTMONEY_HK" if identity[0] == "art_code" else "HKEX_OFFICIAL"),
            "publication_date": (listing.get("publication_date") if isinstance(listing, Mapping)
                                 and isinstance(listing.get("publication_date"), str) else publication_date),
            "issuer_codes": issuer_codes,
            "classification": record.get("classification"),
            "factual_summary": record.get("factual_summary"),
            "why_useful": record.get("why_useful"),
            "event_status_assessment": record.get("event_status_assessment"),
            "analysis_kind": record.get("analysis_kind"),
            "assessment_status": assessment,
            "body_status": record.get("body_status"),
            "semantic_record_sha256": record.get("semantic_record_sha256"),
            "body_record_sha256": record.get("body_record_sha256"),
            "source_refs": refs,
            "decision": ({key: deepcopy(decision.get(key)) for key in (
                "disposition", "selection_basis", "reason", "risk_notes") if key in decision}
                if isinstance(decision, Mapping) else None),
        }
        events.append(event)
        reason_codes: list[str] = []
        if gap:
            reason_codes.append("SOURCE_CONTENT_NOT_ASSESSED")
        if decision_disposition in {None, "NOT_ASSESSED"}:
            reason_codes.append("EXPLICIT_DISPOSITION_PENDING")
        if identity not in body_by_identity:
            reason_codes.append("BODY_SOURCE_ROW_MISSING")
        elif not body_bound:
            reason_codes.append("BODY_SOURCE_ROW_BINDING_MISMATCH")
        if reason_codes:
            pending.append({"source_identity": event["source_identity"],
                "reason_codes": reason_codes, "body_status": record.get("body_status")})

        body_hash = body.get("body_text_sha256") if body_bound else None
        if (not isinstance(body_hash, str) or not _SHA256.fullmatch(body_hash)
                or not issuer_codes):
            continue
        event_date = event["publication_date"]
        if not isinstance(event_date, str):
            event_date = publication_date
        source_members.append({
            "identity": event["source_identity"],
            "source_family": event["source"],
            "publication_date": event_date,
            "issuer_codes": issuer_codes,
            "body_text_sha256": body_hash,
            "event_id": _explicit_event_link(record, body),
            "source_refs": refs,
        })

    body_identities = set(body_by_identity)
    semantic_identities = set(records)
    for missing in sorted(body_identities - semantic_identities):
        pending.append({"source_identity": {"kind": missing[0], "id": missing[1]},
            "reason_codes": ["REVIEWED_SEMANTIC_RECORD_PENDING"],
            "body_status": body_by_identity[missing].get("body_status")})

    exact_content: dict[tuple[str, tuple[str, ...], str], list[dict[str, Any]]] = defaultdict(list)
    explicit_events: dict[tuple[str, tuple[str, ...], str, str], list[dict[str, Any]]] = defaultdict(list)
    for member in source_members:
        key = (member["publication_date"], tuple(member["issuer_codes"]), member["body_text_sha256"])
        exact_content[key].append(member)
        if member["event_id"] is not None:
            explicit_events[key + (member["event_id"],)].append(member)

    source_groups = []
    grouped_identities: set[tuple[str, str]] = set()
    for key, members in sorted(explicit_events.items()):
        if len(members) < 2 or len({item["source_family"] for item in members}) < 2:
            continue
        group_id = digest({"publication_date": key[0], "issuer_codes": list(key[1]),
            "body_text_sha256": key[2], "event_id": key[3]})
        source_groups.append({"group_id": group_id, "group_status": "EXACT_SOURCE_LINK_VERIFIED",
            "publication_date": key[0], "issuer_codes": list(key[1]),
            "body_text_sha256": key[2], "event_id": key[3],
            "members": [deepcopy(item["identity"]) for item in sorted(
                members, key=lambda item: (item["identity"]["kind"], item["identity"]["id"]))],
            "source_refs": [ref for item in members for ref in item["source_refs"]]})
        grouped_identities.update((item["identity"]["kind"], item["identity"]["id"]) for item in members)

    unmerged_candidates = []
    for key, members in sorted(exact_content.items()):
        if len(members) < 2:
            continue
        identities = {(item["identity"]["kind"], item["identity"]["id"]) for item in members}
        if identities <= grouped_identities:
            continue
        unmerged_candidates.append({
            "candidate_status": "UNMERGED_SHARED_CONTENT_IDENTITY_UNVERIFIED",
            "publication_date": key[0], "issuer_codes": list(key[1]),
            "body_text_sha256": key[2],
            "members": [deepcopy(item["identity"]) for item in sorted(
                members, key=lambda item: (item["identity"]["kind"], item["identity"]["id"]))],
            "source_refs": [ref for item in members for ref in item["source_refs"]],
        })

    fingerprint = digest({"target_trade_date": target_trade_date,
        "publication_date": publication_date, "semantic_sha256": semantic_sha256,
        "body_sha256": body_sha256, "decision_sha256": decision_sha256,
        "reviewer_sha256": reviewer_sha256,
        "projection_schema": "v4.manager_research.announcement_incremental_processing.v1"})
    return {
        "schema_version": "v4.manager_research.announcement_incremental_processing.v1",
        "target_trade_date": target_trade_date, "publication_date": publication_date,
        "input_fingerprint_sha256": fingerprint,
        "reuse": {"semantic_status": "REUSED_EXACT_REVIEWED_INPUT",
            "semantic_input_sha256": semantic_sha256,
            "body_input_sha256": body_sha256,
            "reviewer_output_sha256": reviewer_sha256,
            "decision_status": decision_status,
            "decision_input_sha256": decision_sha256,
            "reused_semantic_record_count": len(records),
            "reused_decision_count": len(decisions_by_identity)},
        "counts": {"structured_events": len(events),
            "pending_analysis_or_disposition": len(pending),
            "exact_source_link_groups": len(source_groups),
            "unmerged_exact_content_candidates": len(unmerged_candidates),
            "source_references_preserved": source_refs_preserved},
        "structured_events": events,
        "pending_queue": pending,
        "source_groups": source_groups,
        "unmerged_exact_content_candidates": unmerged_candidates,
        "projection_network_request_count": 0,
        "llm_inference_count": 0,
    }


def _window_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"ANNOUNCEMENT_WINDOW_{field.upper()}_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"ANNOUNCEMENT_WINDOW_{field.upper()}_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"ANNOUNCEMENT_WINDOW_{field.upper()}_MUST_BE_AWARE")
    return parsed.astimezone(_HK)


def _window_date(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("ANNOUNCEMENT_WINDOW_PUBLICATION_DATE_INVALID")
    token = value.replace("-", "")
    if not re.fullmatch(r"\d{8}", token):
        raise ValueError("ANNOUNCEMENT_WINDOW_PUBLICATION_DATE_INVALID")
    try:
        return datetime.strptime(token, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("ANNOUNCEMENT_WINDOW_PUBLICATION_DATE_INVALID") from exc


def _load_source_file(ref: Any, *, base_dir: Path, role: str) -> tuple[Any, dict[str, str]]:
    if not isinstance(ref, Mapping):
        raise ValueError(f"ANNOUNCEMENT_WINDOW_{role.upper()}_FILE_REF_INVALID")
    path_value, expected_sha = ref.get("path"), ref.get("sha256")
    if (not isinstance(path_value, str) or not path_value.strip()
            or not isinstance(expected_sha, str) or not _SHA256.fullmatch(expected_sha)):
        raise ValueError(f"ANNOUNCEMENT_WINDOW_{role.upper()}_FILE_REF_INVALID")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"ANNOUNCEMENT_WINDOW_{role.upper()}_FILE_MISSING")
    raw = path.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError(f"ANNOUNCEMENT_WINDOW_{role.upper()}_FILE_SHA_MISMATCH")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"ANNOUNCEMENT_WINDOW_{role.upper()}_FILE_JSON_INVALID") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"ANNOUNCEMENT_WINDOW_{role.upper()}_FILE_OBJECT_REQUIRED")
    return value, {"path": str(path.resolve()), "sha256": actual_sha}


def _record_index(records: Any, role: str) -> dict[tuple[str, str], Mapping[str, Any]]:
    if not isinstance(records, list):
        raise ValueError(f"ANNOUNCEMENT_WINDOW_{role.upper()}_RECORDS_INVALID")
    indexed: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError(f"ANNOUNCEMENT_WINDOW_{role.upper()}_RECORD_INVALID")
        identity = _identity(record)
        if identity is None or identity in indexed:
            raise ValueError(f"ANNOUNCEMENT_WINDOW_{role.upper()}_IDENTITY_INVALID")
        indexed[identity] = record
    return indexed


def _rule_review_record_index(records: Any) -> dict[tuple[str, str], Mapping[str, Any]]:
    indexed = _record_index(records, "rule_review")
    for row in indexed.values():
        if (row.get("disposition") not in _RULE_DISPOSITIONS
                or row.get("selection_basis") not in {
                    "OPERATING_EVENT", "PERFORMANCE_RESEARCH", "CONDITIONAL_WATCH",
                    "NOT_SELECTED", "NOT_ASSESSED"}
                or row.get("direction") not in _RULE_DIRECTIONS
                or row.get("evidence_sufficiency") not in _RULE_EVIDENCE
                or not isinstance(row.get("source_record_sha256"), str)
                or not _SHA256.fullmatch(row.get("source_record_sha256", ""))
                or not isinstance(row.get("reason"), str) or not row.get("reason", "").strip()
                or not isinstance(row.get("risk_notes"), list)):
            raise ValueError("ANNOUNCEMENT_WINDOW_RULE_REVIEW_RECORD_INVALID")
        body_sha = row.get("body_text_sha256")
        if body_sha is not None and (not isinstance(body_sha, str) or not _SHA256.fullmatch(body_sha)):
            raise ValueError("ANNOUNCEMENT_WINDOW_RULE_REVIEW_BODY_SHA_INVALID")
    return indexed


def _validate_rule_receipt(review: Mapping[str, Any], receipt: Mapping[str, Any], *,
                           target: str, publication: str, semantic_sha: str) -> dict[str, str]:
    _rule_review_record_index(review.get("records"))
    reader = review.get("reader_identity")
    reviewer = receipt.get("reviewer_identity")
    reviewed_at = receipt.get("reviewed_at")
    if (review.get("schema_version") != _RULE_REVIEW_SCHEMA
            or review.get("rule_version") != _RULE_VERSION
            or review.get("target_trade_date") != target
            or _window_date(review.get("publication_date")) != publication
            or review.get("semantic_catalog_sha256") != semantic_sha
            or not isinstance(reader, str) or not reader.strip()
            or receipt.get("schema_version") != _RULE_RECEIPT_SCHEMA
            or receipt.get("review_conclusion") != "PASS"
            or receipt.get("target_trade_date") != target
            or _window_date(receipt.get("publication_date")) != publication
            or receipt.get("rule_version") != _RULE_VERSION
            or receipt.get("semantic_catalog_sha256") != semantic_sha
            or receipt.get("records_sha256") != digest(review.get("records"))
            or not isinstance(reviewer, str) or not reviewer.strip() or reviewer == reader
            or not isinstance(reviewed_at, str)):
        raise ValueError("ANNOUNCEMENT_WINDOW_RULE_REVIEW_RECEIPT_INVALID")
    parsed_reviewed_at = _window_datetime(reviewed_at, "reviewed_at")
    return {"reader_identity": reader, "reviewer_identity": reviewer,
        "reviewed_at": parsed_reviewed_at.isoformat()}


def _source_publication_time(record: Mapping[str, Any], source_family: str,
                             publication: str, as_of: datetime) -> tuple[datetime | None, str]:
    listing = record.get("listing_source")
    listing = listing if isinstance(listing, Mapping) else {}
    if source_family == "HKEX_OFFICIAL":
        directory_ref = listing.get("directory_source_ref")
        if (listing.get("source") != "HKEX_OFFICIAL"
                or listing.get("source_scope") != "HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1"
                or not isinstance(listing.get("source_variant_id"), str)
                or not _HKEX_ID.fullmatch(listing.get("source_variant_id", ""))
                or record.get("source_variant_id") != listing.get("source_variant_id")
                or _window_date(listing.get("publication_date")) != publication
                or not isinstance(directory_ref, Mapping)
                or not isinstance(directory_ref.get("url"), str)
                or not directory_ref.get("url")
                or not isinstance(directory_ref.get("body_sha256"), str)
                or not _SHA256.fullmatch(directory_ref.get("body_sha256", ""))):
            return None, "HKEX_PUBLICATION_SOURCE_REF_UNVERIFIED"
        raw = listing.get("published_at")
        if isinstance(raw, str) and raw.strip():
            if len(raw.strip()) <= 10 or not any(separator in raw for separator in ("T", " ")):
                return None, "HKEX_PUBLICATION_TIME_NOT_EXACT"
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if value.tzinfo is None or value.utcoffset() is None:
                    value = value.replace(tzinfo=_HK)
                value = value.astimezone(_HK)
                if value.date().isoformat() != publication:
                    return None, "HKEX_PUBLISHED_AT_DATE_MISMATCH"
                return value, "EXACT_HKEX_PUBLISHED_AT"
            except ValueError:
                return None, "PUBLICATION_TIME_INVALID"
        return None, "PUBLICATION_TIME_UNKNOWN"
    # Eastmoney notice_date locates prior complete calendar days. Same-day
    # records require a separate official time and source reference.
    exact = listing.get("official_publication_time")
    exact_ref = listing.get("official_publication_source_ref")
    if (isinstance(exact, str) and exact.strip() and isinstance(exact_ref, Mapping)
            and isinstance(exact_ref.get("url"), str) and exact_ref.get("url")
            and isinstance(exact_ref.get("body_sha256"), str)
            and _SHA256.fullmatch(exact_ref.get("body_sha256", ""))):
        try:
            value = datetime.fromisoformat(exact.replace("Z", "+00:00"))
            if value.tzinfo is None or value.utcoffset() is None:
                return None, "OFFICIAL_PUBLICATION_TIME_NOT_AWARE"
            value = value.astimezone(_HK)
            if value.date().isoformat() != publication:
                return None, "OFFICIAL_PUBLICATION_TIME_DATE_MISMATCH"
            return value, "EXACT_OFFICIAL_PUBLICATION_TIME"
        except ValueError:
            return None, "PUBLICATION_TIME_INVALID"
    notice_day = listing.get("notice_date")
    if isinstance(notice_day, str) and len(notice_day) >= 10:
        try:
            date_only = datetime.strptime(notice_day[:10], "%Y-%m-%d").date()
        except ValueError:
            date_only = None
        if date_only is not None and date_only.isoformat() == publication:
            if date_only < as_of.date():
                return datetime.combine(date_only, time.min, _HK), "DATE_ONLY_PRIOR_DAY"
            return None, "SAME_DAY_PUBLICATION_TIME_UNVERIFIED"
    return None, "PUBLICATION_TIME_UNKNOWN"


def _availability_times(source: Mapping[str, Any], base_dir: Path) -> tuple[
        dict[str, Any], list[dict[str, str]], dict[str, Any], list[str]]:
    availability = source.get("availability")
    if not isinstance(availability, Mapping):
        return {}, [], {}, ["AVAILABILITY_TIMESTAMPS_MISSING"]
    out = {}
    refs = []
    evidence: dict[str, Any] = {}
    errors: list[str] = []
    for field in ("source_available_at", "qualification_available_at", "owner_available_at"):
        raw = availability.get(field)
        try:
            out[field] = None if raw is None else _window_datetime(raw, field).isoformat()
        except ValueError:
            out[field] = None
            errors.append(f"{field.upper()}_INVALID")
    file_refs = availability.get("files", {})
    if not isinstance(file_refs, Mapping):
        return out, [], {}, [*errors, "AVAILABILITY_FILES_INVALID"]
    for role, ref in sorted(file_refs.items()):
        if role not in {"monthly_eligibility", "capture_receipt", "owner_import_receipt"}:
            raise ValueError("ANNOUNCEMENT_WINDOW_AVAILABILITY_ROLE_INVALID")
        try:
            value, normalized = _load_source_file(ref, base_dir=base_dir, role=f"availability_{role}")
            refs.append({"role": role, **normalized})
            evidence[role] = value
        except ValueError as exc:
            errors.append(str(exc))
    return out, refs, evidence, errors


def _availability_evidence_errors(availability: Mapping[str, Any],
        availability_refs: list[dict[str, str]], evidence: Mapping[str, Any],
        load_errors: list[str], product: Mapping[str, Any], body_ref: Mapping[str, Any],
        publication: str, target: str) -> list[str]:
    """Tie each cutoff timestamp to the native saved receipt that establishes it."""
    errors = list(load_errors)
    required = {"monthly_eligibility", "capture_receipt", "owner_import_receipt"}
    ref_by_role = {row["role"]: row for row in availability_refs}
    if set(evidence) != required or set(ref_by_role) != required:
        errors.append("AVAILABILITY_EVIDENCE_FILES_INCOMPLETE")
        return sorted(set(errors))
    try:
        monthly = evidence["monthly_eligibility"]
        from ops.manager_announcement_body_batch import _verified_monthly_connect_eligibility
        _codes, monthly_identity = _verified_monthly_connect_eligibility(monthly, publication)
        qualification_at = _window_datetime(monthly.get("capture_cutoff_at"), "capture_cutoff_at")
        if (monthly.get("target_trade_date") != publication.replace("-", "")
                or availability.get("qualification_available_at") != qualification_at.isoformat()):
            errors.append("QUALIFICATION_AVAILABILITY_RECEIPT_MISMATCH")

        capture = evidence["capture_receipt"]
        body_sha = body_ref.get("sha256")
        monthly_ref_sha = ref_by_role["monthly_eligibility"]["sha256"]
        capture_target = capture.get("target_trade_date")
        if (capture.get("schema_version") != "v4.manager_research.announcement_daily_capture.v1"
                or capture_target not in {target, publication.replace("-", "")}
                or capture.get("publication_date") != publication
                or capture.get("monthly_connect_eligibility_identity_sha256") != monthly_identity
                or capture.get("monthly_connect_eligibility_file_sha256") != monthly_ref_sha
                or capture.get("body_corpus_file_sha256") != body_sha
                or not isinstance(capture.get("evidence_run_id"), str)
                or not re.fullmatch(r"[0-9a-f]{32}", capture.get("evidence_run_id", ""))):
            errors.append("SOURCE_CAPTURE_RECEIPT_BINDING_INVALID")
        capture_path = Path(ref_by_role["capture_receipt"]["path"])
        batch_path = capture_path.with_name("body_batch_receipt.json")
        batch_sha = capture.get("body_batch_receipt_sha256")
        if (not isinstance(batch_sha, str) or not _SHA256.fullmatch(batch_sha)
                or batch_path.is_symlink() or not batch_path.is_file()):
            errors.append("SOURCE_CAPTURE_BATCH_RECEIPT_MISSING")
        else:
            batch_raw = batch_path.read_bytes()
            if hashlib.sha256(batch_raw).hexdigest() != batch_sha:
                errors.append("SOURCE_CAPTURE_BATCH_RECEIPT_SHA_MISMATCH")
            else:
                try:
                    batch = json.loads(batch_raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    batch = None
                if (not isinstance(batch, Mapping)
                        or batch.get("schema") != "v4.manager_research.announcement_body_batch_receipt.v1"
                        or batch.get("target_trade_date") != capture_target
                        or batch.get("publication_date") != publication
                        or batch.get("status") != capture.get("status")
                        or batch.get("body_corpus_sha256") != body_sha
                        or not isinstance(batch.get("catalog_run_id"), str)
                        or not batch.get("catalog_run_id")
                        or batch.get("catalog_run_id") != capture.get("catalog_run_id")
                        or not isinstance(batch.get("catalog_sha256"), str)
                        or not _SHA256.fullmatch(batch.get("catalog_sha256", ""))
                        or batch.get("catalog_sha256") != capture.get("catalog_product_sha256")):
                    errors.append("SOURCE_CAPTURE_BATCH_RECEIPT_BINDING_INVALID")
                else:
                    terminal_at = _window_datetime(batch.get("terminal_at"), "terminal_at")
                    started_at = _window_datetime(batch.get("started_at"), "started_at")
                    if (started_at > terminal_at
                            or availability.get("source_available_at") != terminal_at.isoformat()):
                        errors.append("SOURCE_AVAILABILITY_CAPTURE_TIME_MISMATCH")

        owner_receipt = evidence["owner_import_receipt"]
        from .workspace_announcements import validate_owner_analysis_import_receipt
        checked_owner = validate_owner_analysis_import_receipt(owner_receipt, product)
        owner_at = _window_datetime(checked_owner.get("available_at"), "owner_import_available_at")
        if (product.get("target_trade_date") != target
                or product.get("publication_date") != publication
                or availability.get("owner_available_at") != owner_at.isoformat()):
            errors.append("OWNER_AVAILABILITY_RECEIPT_MISMATCH")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        reason = str(exc)
        errors.append(reason if re.fullmatch(r"[A-Z0-9_:. -]{1,180}", reason)
            else "AVAILABILITY_EVIDENCE_INVALID")
    return sorted(set(errors))


def _candidate_source_day(source: Mapping[str, Any], *, base_dir: Path, target: str,
                          start: datetime, as_of: datetime) -> dict[str, Any]:
    publication = _window_date(source.get("publication_date"))
    publication_day = publication.replace("-", "")
    if datetime.strptime(publication_day, "%Y%m%d").date() < start.date() or publication_day > target:
        raise ValueError("ANNOUNCEMENT_WINDOW_SOURCE_OUTSIDE_BOUNDS")
    product, product_ref = _load_source_file(source.get("analysis_product"),
        base_dir=base_dir, role="analysis_product")
    semantic, semantic_ref = _load_source_file(source.get("semantic_catalog"),
        base_dir=base_dir, role="semantic_catalog")
    body, body_ref = _load_source_file(source.get("body_corpus"),
        base_dir=base_dir, role="body_corpus")
    review, review_ref = _load_source_file(source.get("rule_review"),
        base_dir=base_dir, role="rule_review")
    review_receipt, receipt_ref = _load_source_file(source.get("rule_review_receipt"),
        base_dir=base_dir, role="rule_review_receipt")
    refs = {"analysis_product": product_ref, "semantic_catalog": semantic_ref,
        "body_corpus": body_ref, "rule_review": review_ref,
        "rule_review_receipt": receipt_ref}
    availability, availability_refs, availability_evidence, availability_load_errors = _availability_times(
        source, base_dir)
    refs.update({row["role"]: {"path": row["path"], "sha256": row["sha256"]}
        for row in availability_refs})

    product_manifest = product.get("source_manifest")
    if (product.get("target_trade_date") not in {target, publication.replace("-", "")}
            or product.get("publication_date") != publication
            or product.get("sha256") != digest({key: value for key, value in product.items() if key != "sha256"})
            or not isinstance(product_manifest, Mapping)
            or product.get("source_manifest_sha256") != digest(product_manifest)):
        raise ValueError("ANNOUNCEMENT_WINDOW_ANALYSIS_PRODUCT_BINDING_INVALID")
    if product_manifest.get("semantic_catalog_sha256") != semantic_ref["sha256"]:
        raise ValueError("ANNOUNCEMENT_WINDOW_SEMANTIC_PRODUCT_SHA_MISMATCH")
    verified_inputs = product_manifest.get("verified_inputs")
    verified_by_name = {row.get("name"): row.get("sha256") for row in verified_inputs
        if isinstance(row, Mapping)} if isinstance(verified_inputs, list) else {}
    if verified_by_name.get("semantic_catalog") != semantic_ref["sha256"]:
        raise ValueError("ANNOUNCEMENT_WINDOW_SEMANTIC_INPUT_NOT_BOUND")
    if verified_by_name.get("body_corpus") not in {body_ref["sha256"], body.get("sha256"), digest(body)}:
        raise ValueError("ANNOUNCEMENT_WINDOW_BODY_INPUT_NOT_BOUND")
    product_records = _record_index(product.get("records"), "analysis_product")
    semantic_records = _record_index(semantic.get("records"), "semantic_catalog")
    body_records = _record_index([*body.get("rows", []), *body.get("source_variants", [])], "body_corpus")
    if set(product_records) != set(semantic_records):
        raise ValueError("ANNOUNCEMENT_WINDOW_PRODUCT_SEMANTIC_IDENTITY_MISMATCH")
    if (review.get("schema_version") != _RULE_REVIEW_SCHEMA
            or review.get("rule_version") != _RULE_VERSION
            or review.get("status") not in {"DRAFT_UNREVIEWED", "PASS", "VERIFIED"}):
        raise ValueError("ANNOUNCEMENT_WINDOW_RULE_REVIEW_INVALID")
    receipt_meta = _validate_rule_receipt(review, review_receipt, target=target,
        publication=publication, semantic_sha=semantic_ref["sha256"])
    review_records = _rule_review_record_index(review.get("records"))
    if set(review_records) != set(semantic_records):
        raise ValueError("ANNOUNCEMENT_WINDOW_RULE_REVIEW_IDENTITY_MISMATCH")
    availability_evidence_errors = _availability_evidence_errors(availability,
        availability_refs, availability_evidence, availability_load_errors, product,
        body_ref, publication, target)
    product_readiness = source.get("product_readiness")
    if product_readiness not in {"REGISTERED_OWNER_PRODUCT", "DERIVED_DRAFT_UNREGISTERED"}:
        raise ValueError("ANNOUNCEMENT_WINDOW_PRODUCT_READINESS_INVALID")

    day_events = []
    day_pending = []
    day_actual = []
    for identity in sorted(semantic_records):
        semantic_record = semantic_records.get(identity)
        analysis_record = product_records.get(identity)
        reviewed = review_records.get(identity)
        body_record = body_records.get(identity)
        source_id = {"kind": identity[0], "id": identity[1]}
        row_reasons = []
        if semantic_record is None or analysis_record is None or reviewed is None:
            row_reasons.append("SOURCE_OR_REVIEW_RECORD_MISSING")
        if body_record is None:
            row_reasons.append("BODY_SOURCE_ROW_MISSING")
        if semantic_record is not None and reviewed is not None:
            if reviewed.get("source_record_sha256") != digest(semantic_record):
                row_reasons.append("REVIEW_SEMANTIC_RECORD_SHA_MISMATCH")
        if isinstance(semantic_record, Mapping) and isinstance(analysis_record, Mapping):
            if analysis_record.get("semantic_record_sha256") != digest(semantic_record):
                row_reasons.append("SOURCE_PRODUCT_SEMANTIC_SHA_MISMATCH")
        expected_body_sha = body_record.get("body_text_sha256") if isinstance(body_record, Mapping) else None
        if isinstance(body_record, Mapping) and isinstance(analysis_record, Mapping):
            if analysis_record.get("body_record_sha256") != digest(body_record):
                row_reasons.append("SOURCE_PRODUCT_BODY_RECORD_SHA_MISMATCH")
            if analysis_record.get("body_text_sha256") != expected_body_sha:
                row_reasons.append("SOURCE_PRODUCT_BODY_TEXT_SHA_MISMATCH")
        reviewed_body_sha = reviewed.get("body_text_sha256") if isinstance(reviewed, Mapping) else None
        if reviewed_body_sha != expected_body_sha:
            row_reasons.append("REVIEW_BODY_SHA_MISMATCH")
        if isinstance(analysis_record, Mapping) and analysis_record.get("analysis_kind") == "TEXT_INSUFFICIENT_UNASSESSED":
            row_reasons.append("SOURCE_CONTENT_NOT_ASSESSED")
        publication_time = None
        publication_basis = "PUBLICATION_TIME_UNKNOWN"
        if isinstance(analysis_record, Mapping):
            source_family = analysis_record.get("source") or (
                "EASTMONEY_HK" if identity[0] == "art_code" else "HKEX_OFFICIAL")
            publication_time, publication_basis = _source_publication_time(
                analysis_record, source_family, publication, as_of)
        day_start = datetime.strptime(publication_day, "%Y%m%d").replace(tzinfo=_HK)
        in_window = (start <= publication_time <= as_of) if publication_time is not None else (
            publication_basis == "DATE_ONLY_PRIOR_DAY"
            and start.date() <= day_start.date() < as_of.date())
        if not in_window:
            row_reasons.append(publication_basis if publication_time is None
                else "SOURCE_PUBLICATION_OUTSIDE_WINDOW")
        event = {
            "publication_date": publication, "source_identity": source_id,
            "source": (analysis_record.get("source") if isinstance(analysis_record, Mapping)
                else source.get("source_family")),
            "title": analysis_record.get("title") if isinstance(analysis_record, Mapping) else None,
            "issuer_codes": deepcopy(analysis_record.get("issuer_codes", []))
                if isinstance(analysis_record, Mapping) else [],
            "classification": analysis_record.get("classification") if isinstance(analysis_record, Mapping) else None,
            "factual_summary": analysis_record.get("factual_summary") if isinstance(analysis_record, Mapping) else None,
            "why_useful": analysis_record.get("why_useful") if isinstance(analysis_record, Mapping) else None,
            "event_status_assessment": analysis_record.get("event_status_assessment")
                if isinstance(analysis_record, Mapping) else None,
            "analysis_kind": analysis_record.get("analysis_kind") if isinstance(analysis_record, Mapping) else None,
            "body_status": analysis_record.get("body_status") if isinstance(analysis_record, Mapping) else None,
            "semantic_record_sha256": analysis_record.get("semantic_record_sha256")
                if isinstance(analysis_record, Mapping) else None,
            "source_record_sha256": reviewed.get("source_record_sha256") if isinstance(reviewed, Mapping) else None,
            "body_text_sha256": reviewed_body_sha if isinstance(reviewed_body_sha, str) else None,
            "publication_time": publication_time.isoformat() if publication_time else None,
            "publication_time_basis": publication_basis,
            "disposition": reviewed.get("disposition") if isinstance(reviewed, Mapping) else "NOT_ASSESSED",
            "selection_basis": reviewed.get("selection_basis") if isinstance(reviewed, Mapping) else None,
            "direction": reviewed.get("direction") if isinstance(reviewed, Mapping) else "UNKNOWN",
            "evidence_sufficiency": reviewed.get("evidence_sufficiency") if isinstance(reviewed, Mapping)
                else "INSUFFICIENT_EXISTING_FACTS",
            "reason": reviewed.get("reason") if isinstance(reviewed, Mapping) else None,
            "risk_notes": deepcopy(reviewed.get("risk_notes", [])) if isinstance(reviewed, Mapping) else [],
            "supporting_exact_quote": reviewed.get("supporting_exact_quote") if isinstance(reviewed, Mapping) else None,
            "source_refs": _source_refs(analysis_record) if isinstance(analysis_record, Mapping) else [],
            "rule_review_sha256": review_ref["sha256"],
            "rule_review_receipt_sha256": receipt_ref["sha256"],
            "reviewer_identity": receipt_meta["reviewer_identity"],
            "rule_reviewed_at": receipt_meta["reviewed_at"],
            "source_record_validation": "CANNOT_CONFIRM" if any(code in {
                "SOURCE_OR_REVIEW_RECORD_MISSING", "BODY_SOURCE_ROW_MISSING",
                "REVIEW_SEMANTIC_RECORD_SHA_MISMATCH", "REVIEW_BODY_SHA_MISMATCH",
                "SOURCE_PRODUCT_SEMANTIC_SHA_MISMATCH", "SOURCE_PRODUCT_BODY_RECORD_SHA_MISMATCH",
                "SOURCE_PRODUCT_BODY_TEXT_SHA_MISMATCH", "SOURCE_CONTENT_NOT_ASSESSED",
            } for code in row_reasons) else "PASS",
            "retrospective_status": "SOURCE_PUBLISHED_IN_WINDOW" if in_window and not row_reasons else "PENDING",
            "pending_reason_codes": sorted(set(row_reasons)),
            "product_readiness": product_readiness,
        }
        day_events.append(event)
        if event["retrospective_status"] != "SOURCE_PUBLISHED_IN_WINDOW":
            day_pending.append({"publication_date": publication,
                "source_identity": source_id, "reason_codes": sorted(set(row_reasons))})
        else:
            availability_reasons = []
            for field in ("source_available_at", "qualification_available_at", "owner_available_at"):
                value = availability.get(field)
                if value is None:
                    availability_reasons.append(f"{field.upper()}_CANNOT_CONFIRM")
                elif _window_datetime(value, field) > as_of:
                    availability_reasons.append(f"{field.upper()}_AFTER_AS_OF")
            availability_reasons.extend(availability_evidence_errors)
            if product_readiness != "REGISTERED_OWNER_PRODUCT":
                availability_reasons.append("OWNER_PRODUCT_NOT_REGISTERED_BY_AS_OF")
            if _window_datetime(receipt_meta["reviewed_at"], "reviewed_at") > as_of:
                availability_reasons.append("RULE_REVIEW_AFTER_AS_OF")
            positive = (event["disposition"] in {"SELECTED_EVENT", "SELECTED_PERFORMANCE"}
                and event["direction"] == "POSITIVE"
                and event["evidence_sufficiency"] == "VERIFIED_EXISTING_FACTS")
            if positive:
                day_actual.append({"publication_date": publication,
                    "source_identity": source_id,
                    "source_record_sha256": event["source_record_sha256"],
                    "status": "CANNOT_CONFIRM" if availability_reasons else "AVAILABLE_AT_AS_OF",
                    "reason_codes": sorted(set(availability_reasons))})
    return {
        "publication_date": publication, "source_family": source.get("source_family"),
        "product_readiness": product_readiness,
        "analysis_product_sha256": product_ref["sha256"],
        "semantic_catalog_sha256": semantic_ref["sha256"],
        "body_corpus_sha256": body_ref["sha256"],
        "rule_review_sha256": review_ref["sha256"],
        "rule_review_receipt_sha256": receipt_ref["sha256"],
        "rule_review_records_sha256": digest(review.get("records")),
        "rule_review_receipt_status": "PASS", "record_count": len(day_events),
        "pending_count": len(day_pending),
        "status": "PARTIAL" if day_pending else "PASS",
        "source_files": refs, "availability": availability,
        "availability_file_refs": availability_refs,
        "events": day_events, "pending": day_pending, "actual_evaluations": day_actual,
    }


def process_saved_window(input_manifest: Mapping[str, Any], *, base_dir: Path | None = None,
                         elapsed_seconds: float | None = None) -> dict[str, Any]:
    """Build a source-bound retrospective and as-of projection from frozen JSON only."""
    if not isinstance(input_manifest, Mapping) or input_manifest.get("schema_version") != _WINDOW_INPUT_SCHEMA:
        raise ValueError("ANNOUNCEMENT_WINDOW_INPUT_SCHEMA_INVALID")
    target = input_manifest.get("target_trade_date")
    if not isinstance(target, str) or not re.fullmatch(r"\d{8}", target):
        raise ValueError("ANNOUNCEMENT_WINDOW_TARGET_DATE_INVALID")
    start = _window_datetime(input_manifest.get("window_start"), "window_start")
    as_of = _window_datetime(input_manifest.get("as_of"), "as_of")
    if start > as_of or as_of.strftime("%Y%m%d") != target:
        raise ValueError("ANNOUNCEMENT_WINDOW_BOUNDS_INVALID")
    base_dir = base_dir or Path.cwd()
    sources = input_manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("ANNOUNCEMENT_WINDOW_SOURCES_REQUIRED")
    missing_dates = input_manifest.get("missing_dates", [])
    if not isinstance(missing_dates, list):
        raise ValueError("ANNOUNCEMENT_WINDOW_MISSING_DATES_INVALID")
    missing_dates = sorted({_window_date(value).replace("-", "") for value in missing_dates})
    source_days = []
    for source in sources:
        if not isinstance(source, Mapping):
            raise ValueError("ANNOUNCEMENT_WINDOW_SOURCE_INVALID")
        source_days.append(_candidate_source_day(source, base_dir=base_dir,
            target=target, start=start, as_of=as_of))
    source_dates = {row["publication_date"].replace("-", "") for row in source_days}
    if len(source_dates) != len(source_days):
        raise ValueError("ANNOUNCEMENT_WINDOW_SOURCE_DATE_DUPLICATE")
    expected_dates = []
    cursor = start.date()
    while cursor <= as_of.date():
        expected_dates.append(cursor.strftime("%Y%m%d"))
        cursor = cursor.fromordinal(cursor.toordinal() + 1)
    missing_dates = sorted(set(missing_dates) | (set(expected_dates) - source_dates))
    if set(missing_dates) & source_dates:
        raise ValueError("ANNOUNCEMENT_WINDOW_MISSING_DATE_HAS_SOURCE")
    source_days.sort(key=lambda row: row["publication_date"])
    events = [event for day in source_days for event in day["events"]
        if event["retrospective_status"] == "SOURCE_PUBLISHED_IN_WINDOW"]
    pending = [item for day in source_days for item in day["pending"]]
    actual_evaluations = [item for day in source_days for item in day["actual_evaluations"]]
    positive = [event for event in events if event["disposition"] in {
        "SELECTED_EVENT", "SELECTED_PERFORMANCE"} and event["direction"] == "POSITIVE"
        and event["evidence_sufficiency"] == "VERIFIED_EXISTING_FACTS"]
    actual_positive = [row for row in actual_evaluations if row["status"] == "AVAILABLE_AT_AS_OF"]
    actual_status = ("CANNOT_CONFIRM" if not actual_evaluations
        or len(actual_positive) != len(actual_evaluations) else "VERIFIED")
    coverage_status = "PARTIAL" if missing_dates else "COMPLETE"
    input_files = [{"publication_date": day["publication_date"], "role": role, **ref}
        for day in source_days for role, ref in day["source_files"].items()]
    input_files.sort(key=lambda row: (row["publication_date"], row["role"]))
    fingerprint = digest({"target_trade_date": target, "window_start": start.isoformat(),
        "as_of": as_of.isoformat(), "missing_dates": missing_dates,
        "sources": [{"publication_date": day["publication_date"],
            "source_files": {role: ref["sha256"] for role, ref in sorted(day["source_files"].items())},
            "rule_review_records_sha256": day["rule_review_records_sha256"],
            "product_readiness": day["product_readiness"], "source_family": day["source_family"],
            "availability": day["availability"]} for day in source_days],
        "schema_version": _WINDOW_SCHEMA})
    public_days = [{key: value for key, value in day.items()
        if key not in {"events", "pending", "actual_evaluations"}} for day in source_days]
    return {
        "schema_version": _WINDOW_SCHEMA,
        "status": "PARTIAL" if coverage_status == "PARTIAL" else "VERIFIED",
        "target_trade_date": target, "window_start": start.isoformat(), "as_of": as_of.isoformat(),
        "coverage": {"status": coverage_status, "expected_dates": expected_dates,
            "covered_dates": sorted(source_dates), "missing_dates": missing_dates,
            "missing_date_count": len(missing_dates)},
        "source_days": public_days,
        "retrospective_research": {"status": "PARTIAL" if pending or missing_dates else "VERIFIED",
            "candidate_count": len(events), "positive_candidate_count": len(positive),
            "candidates": events, "pending_count": len(pending), "pending_queue": pending},
        "actual_preopen": {"status": actual_status,
            "positive_candidate_count": len(actual_positive) if actual_status == "VERIFIED" else None,
            "positive_candidates": actual_positive, "candidate_evaluations": actual_evaluations,
            "gaps": ["ACTUAL_PREOPEN_QUALIFICATION_OR_AVAILABILITY_CANNOT_CONFIRM"]
                if actual_status == "CANNOT_CONFIRM" else []},
        "input_files": input_files, "input_fingerprint_sha256": fingerprint,
        "registered_fingerprint_sha256": None,
        "processing": {"physical_http_request_count": 0, "llm_inference_count": 0,
            "elapsed_seconds": elapsed_seconds,
            "duration_scope": "SAVED_JSON_READ_AND_DETERMINISTIC_PROJECTION"},
        "RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
    }


def validate_preopen_window(artifact: Any, *, base_dir: Path | None = None,
                            target_trade_date: str | None = None,
                            semantic_sha256: str | None = None,
                            body_sha256: str | None = None,
                            decisions: Any = None) -> dict[str, Any]:
    if not isinstance(artifact, Mapping) or artifact.get("schema_version") != _WINDOW_SCHEMA:
        raise ValueError("ANNOUNCEMENT_WINDOW_ARTIFACT_SCHEMA_INVALID")
    target = artifact.get("target_trade_date")
    start = _window_datetime(artifact.get("window_start"), "window_start")
    as_of = _window_datetime(artifact.get("as_of"), "as_of")
    coverage = artifact.get("coverage")
    days = artifact.get("source_days")
    files = artifact.get("input_files")
    if (not isinstance(target, str) or not re.fullmatch(r"\d{8}", target)
            or start > as_of or as_of.strftime("%Y%m%d") != target
            or (target_trade_date is not None and target != target_trade_date)
            or not isinstance(coverage, Mapping) or coverage.get("status") not in {"COMPLETE", "PARTIAL"}
            or not isinstance(days, list) or not days or not isinstance(files, list)
            or not isinstance(artifact.get("input_fingerprint_sha256"), str)
            or not _SHA256.fullmatch(artifact.get("input_fingerprint_sha256", ""))):
        raise ValueError("ANNOUNCEMENT_WINDOW_ARTIFACT_INVALID")
    base_dir = base_dir or Path.cwd()
    indexed_days = {row.get("publication_date"): row for row in days if isinstance(row, Mapping)}
    if len(indexed_days) != len(days):
        raise ValueError("ANNOUNCEMENT_WINDOW_SOURCE_DAY_BINDING_INVALID")
    expected_covered = {day.replace("-", "") for day in indexed_days}
    if expected_covered != set(coverage.get("covered_dates", [])):
        raise ValueError("ANNOUNCEMENT_WINDOW_SOURCE_DAY_BINDING_INVALID")
    refs_seen = set()
    flat_refs = []
    for publication, row in indexed_days.items():
        if (row.get("rule_review_receipt_status") != "PASS"
                or not isinstance(row.get("rule_review_records_sha256"), str)
                or not _SHA256.fullmatch(row.get("rule_review_records_sha256", ""))
                or not isinstance(row.get("source_files"), Mapping)):
            raise ValueError("ANNOUNCEMENT_WINDOW_REVIEW_NOT_PASSED")
        for role, ref in row["source_files"].items():
            if not isinstance(ref, Mapping):
                raise ValueError("ANNOUNCEMENT_WINDOW_SOURCE_FILE_REF_INVALID")
            key = (publication, role, ref.get("path"), ref.get("sha256"))
            if key in refs_seen:
                raise ValueError("ANNOUNCEMENT_WINDOW_ARTIFACT_FILE_REF_DUPLICATE")
            refs_seen.add(key)
            _load_source_file(ref, base_dir=base_dir, role="registered_source")
            flat_refs.append({"publication_date": publication, "role": role,
                "path": ref.get("path"), "sha256": ref.get("sha256")})
        if semantic_sha256 and publication == as_of.date().isoformat():
            if row["source_files"].get("semantic_catalog", {}).get("sha256") != semantic_sha256:
                raise ValueError("ANNOUNCEMENT_WINDOW_CURRENT_SEMANTIC_SHA_MISMATCH")
        if body_sha256 and publication == as_of.date().isoformat():
            if row["source_files"].get("body_corpus", {}).get("sha256") != body_sha256:
                raise ValueError("ANNOUNCEMENT_WINDOW_CURRENT_BODY_SHA_MISMATCH")
    if len(files) != len(flat_refs) or sorted(
            (row.get("publication_date"), row.get("role"), row.get("path"), row.get("sha256"))
            for row in files if isinstance(row, Mapping)) != sorted(
            (row["publication_date"], row["role"], row["path"], row["sha256"]) for row in flat_refs):
        raise ValueError("ANNOUNCEMENT_WINDOW_FLAT_FILE_MAP_MISMATCH")
    missing_dates = coverage.get("missing_dates")
    if not isinstance(missing_dates, list) or missing_dates != sorted(set(missing_dates)):
        raise ValueError("ANNOUNCEMENT_WINDOW_COVERAGE_DATES_INVALID")
    expected_dates = []
    cursor = start.date()
    while cursor <= as_of.date():
        expected_dates.append(cursor.strftime("%Y%m%d"))
        cursor = cursor.fromordinal(cursor.toordinal() + 1)
    if (coverage.get("expected_dates") != expected_dates
            or set(coverage.get("covered_dates", [])) | set(missing_dates) != set(expected_dates)
            or set(coverage.get("covered_dates", [])) & set(missing_dates)
            or coverage.get("missing_date_count") != len(missing_dates)
            or coverage.get("status") != ("PARTIAL" if missing_dates else "COMPLETE")):
        raise ValueError("ANNOUNCEMENT_WINDOW_COVERAGE_INVALID")

    binding = artifact.get("registered_binding")
    if binding is not None:
        current = indexed_days.get(as_of.date().isoformat())
        if (not isinstance(binding, Mapping) or current is None
                or binding.get("target_trade_date") != target
                or binding.get("source_semantic_catalog_sha256")
                    != current["source_files"].get("semantic_catalog", {}).get("sha256")
                or binding.get("source_body_corpus_file_sha256")
                    != current["source_files"].get("body_corpus", {}).get("sha256")
                or binding.get("draft_analysis_product_sha256") != current.get("analysis_product_sha256")):
            raise ValueError("ANNOUNCEMENT_WINDOW_REGISTERED_BINDING_INVALID")
        expected_registered_fingerprint = digest({
            "input_fingerprint_sha256": artifact.get("input_fingerprint_sha256"),
            "registered_binding": binding})
        if artifact.get("registered_fingerprint_sha256") != expected_registered_fingerprint:
            raise ValueError("ANNOUNCEMENT_WINDOW_REGISTERED_FINGERPRINT_INVALID")
        draft, _ = _load_source_file(current["source_files"].get("analysis_product"),
            base_dir=base_dir, role="registered_current_draft")
        if binding.get("draft_source_manifest_sha256") != draft.get("source_manifest_sha256"):
            raise ValueError("ANNOUNCEMENT_WINDOW_REGISTERED_DRAFT_MANIFEST_MISMATCH")
    elif artifact.get("registered_fingerprint_sha256") is not None:
        raise ValueError("ANNOUNCEMENT_WINDOW_REGISTERED_FINGERPRINT_WITHOUT_BINDING")

    # Rebuild the derived portion from the frozen files, so a changed candidate
    # list cannot be registered merely by editing the JSON envelope.
    source_inputs = []
    for publication, row in sorted(indexed_days.items()):
        source_inputs.append({
            "publication_date": publication,
            "source_family": row.get("source_family"),
            "product_readiness": row.get("product_readiness"),
            "analysis_product": row["source_files"].get("analysis_product"),
            "semantic_catalog": row["source_files"].get("semantic_catalog"),
            "body_corpus": row["source_files"].get("body_corpus"),
            "rule_review": row["source_files"].get("rule_review"),
            "rule_review_receipt": row["source_files"].get("rule_review_receipt"),
            "availability": {**dict(row.get("availability", {})),
                "files": {ref.get("role"): {"path": ref.get("path"), "sha256": ref.get("sha256")}
                    for ref in row.get("availability_file_refs", []) if isinstance(ref, Mapping)}},
        })
    recomputed = process_saved_window({
        "schema_version": _WINDOW_INPUT_SCHEMA, "target_trade_date": target,
        "window_start": artifact.get("window_start"), "as_of": artifact.get("as_of"),
        "missing_dates": missing_dates, "sources": source_inputs,
    }, base_dir=base_dir)
    for field in ("input_fingerprint_sha256", "coverage", "source_days",
                  "retrospective_research", "actual_preopen", "input_files"):
        if artifact.get(field) != recomputed.get(field):
            raise ValueError("ANNOUNCEMENT_WINDOW_DERIVED_CONTENT_MISMATCH")

    if decisions is not None:
        decision_index = _decision_index(decisions)
        current = indexed_days.get(as_of.date().isoformat())
        if current is None:
            raise ValueError("ANNOUNCEMENT_WINDOW_CURRENT_SOURCE_MISSING")
        review, _ = _load_source_file(current["source_files"].get("rule_review"),
            base_dir=base_dir, role="current_rule_review")
        rule_rows = _rule_review_record_index(review.get("records"))
        if set(decision_index) != set(rule_rows):
            raise ValueError("ANNOUNCEMENT_WINDOW_NATIVE_DECISION_IDENTITY_MISMATCH")
        for identity, row in rule_rows.items():
            decision = decision_index[identity]
            for field in ("disposition", "selection_basis", "reason", "risk_notes"):
                if decision.get(field) != row.get(field):
                    raise ValueError("ANNOUNCEMENT_WINDOW_NATIVE_DECISION_REVIEW_MISMATCH")
    result = deepcopy(dict(artifact))
    if semantic_sha256 is not None or body_sha256 is not None:
        result["registered_binding"] = {"target_trade_date": target,
            "semantic_catalog_sha256": semantic_sha256,
            "body_corpus_file_sha256": body_sha256}
    return result


def read_preopen_window(product: Any, *, window_start: str, as_of: str,
                        handoff_verified: bool) -> dict[str, Any]:
    requested_start = _window_datetime(window_start, "window_start")
    requested_as_of = _window_datetime(as_of, "as_of")
    manifest = product.get("source_manifest") if isinstance(product, Mapping) else None
    artifact = manifest.get("preopen_window") if isinstance(manifest, Mapping) else None
    if not handoff_verified or not isinstance(artifact, Mapping):
        return {"status": "CANNOT_CONFIRM", "reason": "REGISTERED_WINDOW_NOT_VERIFIED",
            "window_start": requested_start.isoformat(), "as_of": requested_as_of.isoformat()}
    try:
        checked = validate_preopen_window(artifact, target_trade_date=product.get("target_trade_date"))
    except (ValueError, OSError, KeyError, TypeError):
        return {"status": "CANNOT_CONFIRM", "reason": "REGISTERED_WINDOW_BINDING_INVALID",
            "window_start": requested_start.isoformat(), "as_of": requested_as_of.isoformat()}
    if checked.get("window_start") != requested_start.isoformat() or checked.get("as_of") != requested_as_of.isoformat():
        return {"status": "CANNOT_CONFIRM", "reason": "REQUESTED_WINDOW_DOES_NOT_MATCH_REGISTERED_WINDOW",
            "window_start": requested_start.isoformat(), "as_of": requested_as_of.isoformat(),
            "registered_fingerprint_sha256": checked.get("registered_fingerprint_sha256")}
    return {"status": "VERIFIED", "window_start": checked["window_start"],
        "as_of": checked["as_of"], "registered_fingerprint_sha256": checked.get("registered_fingerprint_sha256"),
        "coverage": deepcopy(checked["coverage"]),
        "retrospective_research": deepcopy(checked["retrospective_research"]),
        "actual_preopen": deepcopy(checked["actual_preopen"]),
        "input_fingerprint_sha256": checked["input_fingerprint_sha256"]}
