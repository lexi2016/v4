"""Date-scoped, research-only US-to-HK relation projection for the Manager owner.

The reviewed 2026-09-30 report is an immutable retrospective research artifact.
Daily runs read only the injected exact-session US owner and a small reviewed
relation registry; they never fetch prices, assert PIT eligibility, or change
the existing Stage/selection/BUY paths.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import uuid4

from .contracts import sha256_json, strict_trade_date
from .workspace_projection import FLAGS, HK, digest, timestamp
from .workspace_plan import plan_context

SCHEMA = "v4.manager_research.us_mapping_research.v1"
DAILY_SCHEMA = "v4.manager_research.us_mapping_daily_run.v1"
REVIEWED_PATH = Path(__file__).with_name("us_mapping_reviewed_20260930.json")
RELATION_REGISTRY_PATH = Path(__file__).with_name("us_mapping_relation_registry.json")
CURRENT_RELATION_EVIDENCE_PATH = Path(__file__).with_name("us_mapping_relation_evidence_20261011.json")
CURRENT_RELATION_REVIEW_PATH = Path(__file__).with_name("us_mapping_relation_evidence_review_20261011.json")
CURRENT_RELATION_REVIEW_RECEIPT_SHA256 = "5e24b82049ca848f7536b084166537415722375414cfc762da8b179919947350"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_TARGET_SEED = "20260930"
_DAILY_RELATION_TYPES = {"DIRECT_NAMED_COMPONENT_SUPPLY", "PRODUCT_PEER", "OPTICAL_TRANSPORT_PEER"}
_RELATION_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _now_text(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_tree(value: Mapping[str, Any]) -> None:
    for key, expected in FLAGS.items():
        if value.get(key) is not expected:
            raise ValueError("US_MAPPING_SAFETY_INVALID")


def _read_reviewed() -> dict[str, Any]:
    raw = REVIEWED_PATH.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("US_MAPPING_REVIEWED_ARTIFACT_INVALID")
    unsigned = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if (value.get("schema_version") != "v4.manager_research.us_mapping_reviewed.v1"
            or value.get("target_trade_date") != _TARGET_SEED
            or value.get("artifact_sha256") != sha256_json(unsigned)
            or not isinstance(value.get("cards"), list)):
        raise ValueError("US_MAPPING_REVIEWED_ARTIFACT_INTEGRITY_FAILED")
    _safe_tree(value)
    return value


def _read_saved(store: Any, date: str) -> dict[str, Any] | None:
    path = store.root / "us_mapping_research" / date / "latest.json"
    pointer = store._read(path)
    if pointer is None:
        return None
    if (pointer.get("schema_version") != "v4.manager_research.us_mapping_daily_pointer.v1"
            or pointer.get("target_trade_date") != date
            or not isinstance(pointer.get("run_id"), str)
            or not _SHA.fullmatch(str(pointer.get("artifact_sha256") or ""))):
        raise ValueError("US_MAPPING_DAILY_POINTER_INVALID")
    artifact = store._read(path.parent / "runs" / f"{pointer['run_id']}.json")
    if artifact is None:
        raise ValueError("US_MAPPING_DAILY_ARTIFACT_MISSING")
    unsigned = {key: item for key, item in artifact.items() if key != "artifact_sha256"}
    if (artifact.get("schema_version") != DAILY_SCHEMA
            or artifact.get("target_trade_date") != date
            or artifact.get("run_id") != pointer["run_id"]
            or artifact.get("artifact_sha256") != pointer["artifact_sha256"]
            or sha256_json(unsigned) != pointer["artifact_sha256"]):
        raise ValueError("US_MAPPING_DAILY_ARTIFACT_INTEGRITY_FAILED")
    _safe_tree(artifact)
    return artifact


def read_workspace_mapping(service: Any, target_trade_date: str) -> dict[str, Any]:
    date = strict_trade_date(target_trade_date)
    try:
        daily = _read_saved(service.store, date)
    except (OSError, ValueError, KeyError, TypeError):
        daily = None
        read_status = "FAILED"
    else:
        read_status = "NOT_RUN"
    if daily is None:
        daily = {
            "schema_version": DAILY_SCHEMA,
            "status": read_status,
            "target_trade_date": date,
            "run_id": None,
            "generated_at": None,
            "us_session_date": None,
            "research_cutoff": None,
            "coverage": {
                "reviewed_us_symbol_count": 4,
                "matched_us_symbol_count": None,
                "matched_hk_relation_count": None,
                "configured_us_universe_count": None,
                "available_us_universe_count": None,
                "full_market_coverage": False,
            },
            "matches": [],
            "gaps": ["DAILY_MAPPING_NOT_MATERIALIZED" if read_status == "NOT_RUN" else "DAILY_MAPPING_READBACK_INVALID"],
            "source_identity": None,
            "input_identity": None,
            **FLAGS,
        }
    if date == _TARGET_SEED:
        try:
            reviewed = _read_reviewed()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            reviewed = {
                "schema_version": "v4.manager_research.us_mapping_reviewed.v1",
                "target_trade_date": date,
                "status": "CANNOT_CONFIRM",
                "reviewed_at": None,
                "cards": [],
                "gaps": ["REVIEWED_US_HK_RELATION_ARTIFACT_INVALID"],
                **FLAGS,
            }
    else:
        reviewed = None
    return {
        "schema_version": SCHEMA,
        "target_trade_date": date,
        "daily_run": daily,
        "reviewed_research": reviewed,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _relation_index() -> dict[str, list[dict[str, Any]]]:
    reviewed = _read_reviewed()
    out: dict[str, list[dict[str, Any]]] = {}
    for card in reviewed["cards"]:
        if not isinstance(card, Mapping):
            continue
        for symbol in card.get("daily_match_symbols", []):
            if isinstance(symbol, str) and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
                out.setdefault(symbol, []).append(dict(card))
    return out


def _relation_availability_details(reviewed: Mapping[str, Any]) -> tuple[
        datetime | None, str | None, dict[str, Any] | None]:
    """Return the release-pinned system availability and its source identities.

    The report's ``reviewed_at`` is a retrospective calendar date. It cannot
    establish when the rows became available inside this application. Both
    daily and current-workspace joins therefore require the separately pinned
    deployment registry.
    """
    try:
        raw = RELATION_REGISTRY_PATH.read_bytes()
        registry = json.loads(raw)
        if not isinstance(registry, Mapping):
            return None, "US_HK_RELATION_AVAILABILITY_UNVERIFIED", None
        unsigned = {key: item for key, item in registry.items() if key != "artifact_sha256"}
        seed_sha = hashlib.sha256(REVIEWED_PATH.read_bytes()).hexdigest()
        availability = timestamp(registry.get("available_at"))
        if (not isinstance(registry, Mapping)
                or registry.get("schema_version") != "v4.manager_research.us_mapping_relation_registry.v1"
                or registry.get("artifact_sha256") != sha256_json(unsigned)
                or registry.get("source_seed_sha256") != seed_sha
                or registry.get("source_report_sha256") != (reviewed.get("report") or {}).get("sha256")
                or not availability
                or registry.get("availability_basis") != "V4_RELEASE_PUBLICATION"
                or not isinstance(registry.get("release_id"), str)
                or not registry.get("release_id")
                or not _SHA.fullmatch(str(registry.get("release_manifest_sha256") or ""))
                or not _SHA.fullmatch(str(registry.get("deployment_receipt_sha256") or ""))):
            return None, "US_HK_RELATION_AVAILABILITY_UNVERIFIED", None
        return availability, None, {
            "registry_file_sha256": hashlib.sha256(raw).hexdigest(),
            "registry_artifact_sha256": registry["artifact_sha256"],
            "registry_schema_version": registry["schema_version"],
            "availability_basis": registry["availability_basis"],
            "availability_scope": registry["availability_scope"],
            "release_id": registry["release_id"],
            "release_manifest_sha256": registry["release_manifest_sha256"],
            "deployment_receipt_sha256": registry["deployment_receipt_sha256"],
            "available_at": availability.isoformat(),
            "seed_file_sha256": seed_sha,
            "source_report_sha256": registry["source_report_sha256"],
        }
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None, "US_HK_RELATION_AVAILABILITY_UNVERIFIED", None


def _relation_available_at(reviewed: Mapping[str, Any]) -> tuple[datetime | None, str | None]:
    availability, gap, _details = _relation_availability_details(reviewed)
    return availability, gap


def _reviewed_seed_relations(target_date: str, cutoff: datetime) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Project only the immutable reviewed seed rows whose release was available by cutoff."""
    try:
        reviewed = _read_reviewed()
        available_at, gap, availability = _relation_availability_details(reviewed)
        if gap or available_at is None or availability is None:
            return [], {}, [gap or "US_HK_RELATION_AVAILABILITY_UNVERIFIED"]
        if available_at > cutoff:
            return [], availability, ["US_HK_RELATION_NOT_AVAILABLE_AT_RESEARCH_CUTOFF"]
        seed_file_sha = str(availability["seed_file_sha256"])
        seed_artifact_sha = str(reviewed["artifact_sha256"])
        timing = ("RETROSPECTIVE_AFTER_TARGET_DATE"
                  if available_at.date().strftime("%Y%m%d") > target_date else "AVAILABLE_BY_TARGET_DATE")
        relations: list[dict[str, Any]] = []
        for raw_card in reviewed.get("cards", []):
            if not isinstance(raw_card, Mapping):
                continue
            card = dict(raw_card)
            if card.get("relationship_type") not in _DAILY_RELATION_TYPES:
                continue
            symbols = card.get("daily_match_symbols")
            if not isinstance(symbols, list):
                continue
            for raw_symbol in symbols:
                if not isinstance(raw_symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", raw_symbol):
                    continue
                sources = card.get("official_sources")
                if not isinstance(sources, list):
                    sources = []
                provenance = {
                    "relation_source": "RELEASE_PINNED_REVIEWED_SEED",
                    "reviewed_relation_artifact_sha256": seed_artifact_sha,
                    "reviewed_seed_file_sha256": seed_file_sha,
                    **availability,
                }
                relations.append({
                    "us_symbol": raw_symbol,
                    "hk_symbol": card.get("hk_symbol"),
                    "hk_code": card.get("hk_code"),
                    "hk_name": card.get("hk_name"),
                    "relationship_type": card.get("relationship_type"),
                    "direction": card.get("direction") or "NOT_STATED_IN_REVIEWED_CARD",
                    "reason": card.get("reason"),
                    "maturity": card.get("maturity"),
                    "limitations": deepcopy(card.get("limitations") or []),
                    "published_at": card.get("published_at"),
                    "sources": deepcopy(sources),
                    "official_sources": deepcopy(sources),
                    "relation_source": "RELEASE_PINNED_REVIEWED_SEED",
                    "evidence_review_status": "RELEASE_PINNED_REVIEWED_RESEARCH",
                    "evidence_timing": timing,
                    "available_at": available_at.isoformat(),
                    "target_date_eligibility": "CANNOT_CONFIRM",
                    "provenance": provenance,
                    **FLAGS,
                })
        return relations, availability, []
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return [], {}, ["US_HK_RELATION_AVAILABILITY_UNVERIFIED"]


def _current_relation_review(evidence_raw: bytes, evidence: Mapping[str, Any],
                             cards: list[Mapping[str, Any]],
                             assessments: list[Mapping[str, Any]]) -> tuple[dict[str, Any], str]:
    """Validate the independent semantic review against exact artifact and relation identities."""
    raw = CURRENT_RELATION_REVIEW_PATH.read_bytes()
    receipt_sha = hashlib.sha256(raw).hexdigest()
    if receipt_sha != CURRENT_RELATION_REVIEW_RECEIPT_SHA256:
        raise ValueError("US_RELATION_REVIEW_RECEIPT_SHA256_MISMATCH")
    receipt = json.loads(raw)
    if not isinstance(receipt, Mapping):
        raise ValueError("US_RELATION_REVIEW_RECEIPT_INVALID")
    artifact_version = evidence.get("schema_version")
    expected_review_version = {
        "v4.manager_research.us_mapping_relation_evidence.v1":
            "v4.manager_research.us_mapping_relation_evidence_review.v1",
        "v4.manager_research.us_mapping_relation_evidence.v2":
            "v4.manager_research.us_mapping_relation_evidence_review.v2",
    }.get(artifact_version)
    if (expected_review_version is None
            or receipt.get("schema_version") != expected_review_version
            or receipt.get("status") != "PASS"
            or receipt.get("reviewer_identity") != "/root/us_mapping_completion_review"
            or not isinstance(receipt.get("reviewed_scope"), str) or not receipt.get("reviewed_scope")
            or receipt.get("evidence_path") != "v4/manager_research/us_mapping_relation_evidence_20261011.json"
            or receipt.get("evidence_file_sha256") != hashlib.sha256(evidence_raw).hexdigest()
            or receipt.get("declared_artifact_sha256") != evidence.get("artifact_sha256")
            or receipt.get("recomputed_artifact_sha256") != evidence.get("artifact_sha256")
            or receipt.get("http_body_rehash_status") != "CANNOT_CONFIRM"
            or not isinstance(receipt.get("limitations"), list)
            or not isinstance(receipt.get("CANNOT_CONFIRM"), list)):
        raise ValueError("US_RELATION_REVIEW_RECEIPT_BINDING_INVALID")
    for key, expected in FLAGS.items():
        if receipt.get("safety", {}).get(key) is not expected:
            raise ValueError("US_RELATION_REVIEW_RECEIPT_SAFETY_INVALID")
    reviewed_at = timestamp(receipt.get("reviewed_at"))
    if reviewed_at is None:
        raise ValueError("US_RELATION_REVIEW_RECEIPT_TIME_INVALID")
    captured_times = [
        timestamp(item.get("available_at"))
        for item in [*cards, *assessments]
        if isinstance(item, Mapping)
    ]
    if any(value is None for value in captured_times) or any(value > reviewed_at for value in captured_times):
        raise ValueError("US_RELATION_REVIEW_RECEIPT_TIME_BEFORE_EVIDENCE")
    expected_pairs = {
        (card.get("us_symbol"), card.get("hk_symbol"), card.get("relationship_type"), card.get("direction"))
        for card in cards
    }
    raw_pairs = receipt.get("reviewed_pairs")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise ValueError("US_RELATION_REVIEW_RECEIPT_PAIRS_INVALID")
    reviewed_pairs = set()
    for pair in raw_pairs:
        if not isinstance(pair, Mapping):
            raise ValueError("US_RELATION_REVIEW_RECEIPT_PAIRS_INVALID")
        reviewed_pairs.add((pair.get("us_symbol"), pair.get("hk_symbol"),
                            pair.get("relationship_type"), pair.get("direction")))
    if len(reviewed_pairs) != len(raw_pairs) or reviewed_pairs != expected_pairs:
        raise ValueError("US_RELATION_REVIEW_RECEIPT_PAIRS_MISMATCH")
    expected_assessments = {
        (assessment.get("us_symbol"), assessment.get("candidate_hk_code"),
         assessment.get("status"), assessment.get("conclusion"), sha256_json(assessment))
        for assessment in assessments
    }
    raw_assessments = receipt.get("reviewed_symbol_assessments", [])
    if assessments and not isinstance(raw_assessments, list):
        raise ValueError("US_RELATION_REVIEW_RECEIPT_ASSESSMENTS_INVALID")
    reviewed_assessments = set()
    for assessment in raw_assessments if isinstance(raw_assessments, list) else []:
        if not isinstance(assessment, Mapping):
            raise ValueError("US_RELATION_REVIEW_RECEIPT_ASSESSMENTS_INVALID")
        reviewed_assessments.add((assessment.get("us_symbol"), assessment.get("candidate_hk_code"),
                                  assessment.get("status"), assessment.get("conclusion"),
                                  assessment.get("assessment_sha256")))
    if (len(reviewed_assessments) != len(raw_assessments if isinstance(raw_assessments, list) else [])
            or reviewed_assessments != expected_assessments):
        raise ValueError("US_RELATION_REVIEW_RECEIPT_ASSESSMENTS_MISMATCH")
    # Bind issuer identities separately when a relation card does not itself
    # carry an identity-role source or an explicit exchange:ticker statement.
    # Older v1 receipts use one AMD object; v2 may use a list or a symbol-keyed
    # mapping. The independent review receipt, rather than a relation excerpt,
    # supplies the identity claim and its retrieval/capture provenance.
    raw_identity_evidence = receipt.get("us_symbol_identity_evidence")
    if isinstance(raw_identity_evidence, list):
        identity_entries = raw_identity_evidence
    elif isinstance(raw_identity_evidence, Mapping):
        if "us_symbol" in raw_identity_evidence:
            identity_entries = [raw_identity_evidence]
        else:
            identity_entries = [
                {"us_symbol": symbol, **deepcopy(dict(value))}
                for symbol, value in raw_identity_evidence.items()
                if isinstance(value, Mapping)
            ]
    else:
        identity_entries = []
    identity_by_symbol: dict[str, dict[str, Any]] = {}
    for identity in identity_entries:
        if not isinstance(identity, Mapping):
            raise ValueError("US_RELATION_REVIEW_RECEIPT_IDENTITIES_INVALID")
        symbol = identity.get("us_symbol")
        body_sha = identity.get("source_body_sha256")
        body_sha_status = identity.get("source_body_sha256_status")
        retrieved_at = timestamp(identity.get("retrieved_at"))
        if (not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol)
                or identity.get("identity_status") != "VERIFIED"
                or not isinstance(identity.get("issuer"), str) or not identity.get("issuer")
                or not isinstance(identity.get("exchange"), str) or not identity.get("exchange")
                or not str(identity.get("url") or "").startswith("https://")
                or not isinstance(identity.get("source_locator"), str) or not identity.get("source_locator")
                or retrieved_at is None or retrieved_at > reviewed_at
                or (identity.get("source_capture_status") is not None
                    and (not isinstance(identity.get("source_capture_status"), str)
                         or not identity.get("source_capture_status")))
                or (body_sha is None and body_sha_status != "CANNOT_CONFIRM")
                or (body_sha is not None and (not isinstance(body_sha, str)
                    or not _SHA.fullmatch(body_sha)
                    or body_sha_status != "VERIFIED_SHA256_HTTP_RESPONSE_BODY_BYTES"))
                or symbol in identity_by_symbol):
            raise ValueError("US_RELATION_REVIEW_RECEIPT_IDENTITY_INVALID")
        identity_by_symbol[symbol] = deepcopy(dict(identity))

    identity_needed: set[str] = set()
    for card in cards:
        symbol = str(card.get("us_symbol") or "")
        has_identity_role = any(
            isinstance(source, Mapping) and source.get("role") == "US_SYMBOL_IDENTITY"
            for source in card.get("sources", [])
        )
        explicit_exchange_ticker = any(
            isinstance(source, Mapping)
            and re.search(rf"\b(?:NASDAQ|NYSE)\s*:\s*{re.escape(symbol)}\b",
                          str(source.get("excerpt") or ""), re.IGNORECASE)
            for source in card.get("sources", [])
        )
        if not has_identity_role and not explicit_exchange_ticker:
            identity_needed.add(symbol)
    if not identity_needed.issubset(identity_by_symbol):
        raise ValueError("US_RELATION_REVIEW_RECEIPT_IDENTITIES_MISSING")
    return {
        "receipt_sha256": receipt_sha,
        "reviewer_identity": receipt["reviewer_identity"],
        "reviewed_at": reviewed_at.isoformat(),
        "status": receipt["status"],
        "http_body_rehash_status": receipt["http_body_rehash_status"],
        "limitations": deepcopy(receipt["limitations"]),
        "cannot_confirm": deepcopy(receipt["CANNOT_CONFIRM"]),
        "us_symbol_identity_evidence": identity_by_symbol,
        "reviewed_symbol_assessments": deepcopy(raw_assessments),
    }, "INDEPENDENT_SEMANTIC_REVIEW_PASS_BODY_REHASH_CANNOT_CONFIRM"


def attach_current_relation_evidence(us_market: Mapping[str, Any]) -> dict[str, Any]:
    """Attach source-hashed relations only to the exact current workspace bridge.

    This is a read-only, retrospective research overlay. It never changes the
    saved target-date product, BUY state, or target-date eligibility.
    """
    result = deepcopy(dict(us_market))
    rows = result.get("symbol_assessments")
    if not isinstance(rows, list):
        result["relation_evidence"] = {
            "status": "CANNOT_CONFIRM", "artifact_sha256": None, "gaps": ["US_SYMBOL_ASSESSMENTS_NOT_AVAILABLE"],
            "target_date_eligibility": "CANNOT_CONFIRM", **FLAGS,
        }
        return result
    cutoff = timestamp(result.get("research_cutoff"))
    target_date = strict_trade_date(str(result.get("target_trade_date") or ""))
    source_identity = result.get("source_identity")
    bridge_source_payload_sha = (
        source_identity.get("payload_sha256") if isinstance(source_identity, Mapping) else None
    )
    session = result.get("expected_us_session")
    if (cutoff is None or not isinstance(session, str)
            or not _SHA.fullmatch(str(bridge_source_payload_sha or ""))):
        reason = "US_RELATION_EVIDENCE_BRIDGE_IDENTITY_UNVERIFIED"
        result["relation_evidence"] = {
            "status": "CANNOT_CONFIRM", "artifact_sha256": None, "gaps": [reason],
            "target_date_eligibility": "CANNOT_CONFIRM", "current_bridge_session": session,
            "current_bridge_source_payload_sha256": None, **FLAGS,
        }
        for row in rows:
            if isinstance(row, dict):
                row["relation_assessment_status"] = "NOT_EVALUATED"
                row["relation_count"] = None
                row["relations"] = []
                row["relation_gaps"] = [reason]
        return result

    evidence: Mapping[str, Any] | None = None
    evidence_raw = b""
    parsed_cards: list[dict[str, Any]] = []
    parsed_symbol_assessments: list[dict[str, Any]] = []
    withheld_candidates: list[Any] = []
    current_artifact_error: str | None = None
    try:
        raw = CURRENT_RELATION_EVIDENCE_PATH.read_bytes()
        evidence_raw = raw
        evidence = json.loads(raw)
        if not isinstance(evidence, Mapping):
            raise ValueError("US_RELATION_EVIDENCE_ARTIFACT_INVALID")
        unsigned = {key: value for key, value in evidence.items() if key != "artifact_sha256"}
        cards = evidence.get("relations")
        raw_symbol_assessments = evidence.get("symbol_assessments", [])
        withheld_candidates = evidence.get("withheld_candidates", [])
        if (evidence.get("schema_version") not in {
                "v4.manager_research.us_mapping_relation_evidence.v1",
                "v4.manager_research.us_mapping_relation_evidence.v2",
            }
                or evidence.get("artifact_sha256") != sha256_json(unsigned)
                or not isinstance(cards, list)
                or not isinstance(raw_symbol_assessments, list)
                or not isinstance(withheld_candidates, list)
                or evidence.get("source_hash_algorithm") != "SHA256_HTTP_RESPONSE_BODY_BYTES"):
            raise ValueError("US_RELATION_EVIDENCE_ARTIFACT_INTEGRITY_FAILED")
        _safe_tree(evidence)
        for candidate in withheld_candidates:
            if (not isinstance(candidate, Mapping)
                    or not isinstance(candidate.get("company"), str) or not candidate.get("company")
                    or not isinstance(candidate.get("us_symbol"), str)
                    or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", candidate["us_symbol"])
                    or not isinstance(candidate.get("candidate_hk_code"), str)
                    or not re.fullmatch(r"\d{5}", candidate["candidate_hk_code"])
                    or candidate.get("status") != "CANNOT_CONFIRM"
                    or not isinstance(candidate.get("reason"), str) or not candidate.get("reason")):
                raise ValueError("US_RELATION_EVIDENCE_WITHHELD_CANDIDATE_INVALID")
        cutoff = timestamp(result.get("research_cutoff"))
        target_date = strict_trade_date(str(result.get("target_trade_date") or ""))
        source_identity = result.get("source_identity")
        bridge_source_payload_sha = (
            source_identity.get("payload_sha256") if isinstance(source_identity, Mapping) else None
        )
        session = result.get("expected_us_session")
        if (cutoff is None or not isinstance(session, str)
                or not _SHA.fullmatch(str(bridge_source_payload_sha or ""))):
            raise ValueError("US_RELATION_EVIDENCE_BRIDGE_IDENTITY_UNVERIFIED")
        parsed_cards = []
        for raw_card in cards:
            if not isinstance(raw_card, Mapping):
                raise ValueError("US_RELATION_EVIDENCE_CARD_INVALID")
            card = deepcopy(dict(raw_card))
            symbol = card.get("us_symbol")
            sources = card.get("sources")
            available_at = timestamp(card.get("available_at"))
            if (not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol)
                    or not isinstance(card.get("relationship_type"), str)
                    or not _RELATION_TOKEN.fullmatch(card["relationship_type"])
                    or not isinstance(card.get("direction"), str)
                    or not _RELATION_TOKEN.fullmatch(card["direction"])
                    or not isinstance(card.get("hk_code"), str) or not re.fullmatch(r"\d{5}", card["hk_code"])
                    or card.get("hk_symbol") != "HK." + card["hk_code"]
                    or not isinstance(card.get("hk_name"), str) or not card.get("hk_name")
                    or not isinstance(card.get("reason"), str) or not card.get("reason")
                    or not isinstance(card.get("maturity"), str) or not card.get("maturity")
                    or not isinstance(card.get("limitations"), list) or not card["limitations"]
                    or available_at is None or not isinstance(sources, list) or len(sources) < 2):
                raise ValueError("US_RELATION_EVIDENCE_CARD_FIELDS_INVALID")
            source_roles = set()
            source_retrieval_times: list[datetime] = []
            for source in sources:
                if not isinstance(source, Mapping):
                    raise ValueError("US_RELATION_EVIDENCE_SOURCE_INVALID")
                role = source.get("role")
                url = source.get("url")
                source_body_sha = source.get("source_body_sha256")
                retrieved_at = timestamp(source.get("retrieved_at"))
                retrieval_started_at = timestamp(source.get("retrieval_started_at"))
                if (role not in {"RELATION", "HK_LISTING_IDENTITY", "US_SYMBOL_IDENTITY"}
                        or not isinstance(url, str) or not url.startswith("https://")
                        or not isinstance(source.get("title"), str) or not source.get("title")
                        or not isinstance(source.get("excerpt"), str) or not source.get("excerpt")
                        or not _SHA.fullmatch(str(source_body_sha or "")) or retrieved_at is None
                        or retrieval_started_at is None or retrieval_started_at > retrieved_at
                        or source.get("http_status") != 200
                        or (source.get("published_at") is not None
                            and not isinstance(source.get("published_at"), str))
                        or not isinstance(source.get("source_locator"), str)):
                    raise ValueError("US_RELATION_EVIDENCE_SOURCE_FIELDS_INVALID")
                source_roles.add(role)
                source_retrieval_times.append(retrieved_at)
            if not {"RELATION", "HK_LISTING_IDENTITY"}.issubset(source_roles):
                raise ValueError("US_RELATION_EVIDENCE_IDENTITY_BASIS_INCOMPLETE")
            if max(source_retrieval_times) != available_at:
                raise ValueError("US_RELATION_EVIDENCE_AVAILABILITY_NOT_BOUND_TO_SOURCE_RECEIPTS")
            parsed_cards.append(card)
        parsed_symbol_assessments = []
        seen_assessed_symbols: set[str] = set()
        for raw_assessment in raw_symbol_assessments:
            if not isinstance(raw_assessment, Mapping):
                raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_INVALID")
            assessment = deepcopy(dict(raw_assessment))
            symbol = assessment.get("us_symbol")
            code = assessment.get("candidate_hk_code")
            sources = assessment.get("sources")
            available_at = timestamp(assessment.get("available_at"))
            if (not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol)
                    or symbol in seen_assessed_symbols
                    or not isinstance(code, str) or not re.fullmatch(r"\d{5}", code)
                    or assessment.get("candidate_hk_symbol") != "HK." + code
                    or assessment.get("status") != "ASSESSED_WITH_GAPS"
                    or assessment.get("conclusion") != "CANNOT_CONFIRM"
                    or not isinstance(assessment.get("assessment_scope"), str)
                    or not assessment.get("assessment_scope")
                    or not isinstance(assessment.get("reason"), str) or not assessment.get("reason")
                    or not isinstance(assessment.get("limitations"), list) or not assessment["limitations"]
                    or available_at is None or not isinstance(sources, list) or not sources):
                raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_FIELDS_INVALID")
            source_retrieval_times: list[datetime] = []
            for source in sources:
                if not isinstance(source, Mapping):
                    raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_INVALID")
                role = source.get("role")
                url = source.get("url")
                body_sha = source.get("source_body_sha256")
                hash_status = source.get("source_body_sha256_status")
                capture_status = source.get("source_capture_status")
                retrieved_at = timestamp(source.get("retrieved_at"))
                retrieval_started_at = timestamp(source.get("retrieval_started_at"))
                if (role not in {"RELATION", "HISTORICAL_RELATION_CONTEXT", "SOURCE_RETRIEVAL_ATTEMPT"}
                        or not isinstance(url, str) or not url.startswith("https://")
                        or not isinstance(source.get("title"), str) or not source.get("title")
                        or not isinstance(source.get("excerpt"), str) or not source.get("excerpt")
                        or not isinstance(source.get("source_locator"), str) or not source.get("source_locator")
                        or retrieved_at is None
                        or (retrieval_started_at is not None and retrieval_started_at > retrieved_at)):
                    raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_FIELDS_INVALID")
                if body_sha is None:
                    if hash_status != "CANNOT_CONFIRM" or capture_status not in {
                            "WEB_EXTRACTED_CONTENT_BODY_NOT_CAPTURED",
                            "HTTP_429_NO_RESPONSE_BODY",
                            "WEB_EXTRACTED_WITHDRAWN_SOURCE_BODY_NOT_CAPTURED",
                        }:
                        raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_HASH_STATUS_INVALID")
                    if capture_status == "HTTP_429_NO_RESPONSE_BODY" and source.get("http_status") != 429:
                        raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_HTTP_STATUS_INVALID")
                    if capture_status != "HTTP_429_NO_RESPONSE_BODY" and source.get("http_status") is not None:
                        raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_HTTP_STATUS_INVALID")
                elif (not _SHA.fullmatch(str(body_sha))
                        or hash_status != "VERIFIED_SHA256_HTTP_RESPONSE_BODY_BYTES"
                        or capture_status != "HTTP_RESPONSE_BODY_CAPTURED"
                        or source.get("http_status") != 200):
                    raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_HASH_STATUS_INVALID")
                if retrieval_started_at is not None and source.get("http_status") not in {200, 429}:
                    raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_HTTP_STATUS_INVALID")
                source_retrieval_times.append(retrieved_at)
            if max(source_retrieval_times) != available_at:
                raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_AVAILABILITY_NOT_BOUND_TO_SOURCES")
            seen_assessed_symbols.add(symbol)
            parsed_symbol_assessments.append(assessment)
        if not parsed_cards and not parsed_symbol_assessments:
            raise ValueError("US_RELATION_EVIDENCE_HAS_NO_RELATIONS_OR_ASSESSMENTS")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        reason = str(exc) if str(exc).startswith("US_RELATION_EVIDENCE_") else "US_RELATION_EVIDENCE_ARTIFACT_INVALID"
        current_artifact_error = reason
        evidence = None
        parsed_cards = []
        parsed_symbol_assessments = []
        withheld_candidates = []

    review_info: dict[str, Any] | None = None
    current_review_status: str | None = None
    review_error: str | None = None
    if evidence is not None:
        try:
            review_info, current_review_status = _current_relation_review(
                evidence_raw, evidence, parsed_cards, parsed_symbol_assessments,
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            review_error = str(exc) if str(exc).startswith("US_RELATION_REVIEW_") else "US_RELATION_REVIEW_RECEIPT_INVALID"

    configured_symbols = {
        str(row.get("symbol") or "").upper() for row in rows if isinstance(row, Mapping)
    }
    seed_relations, seed_availability, seed_gaps = _reviewed_seed_relations(target_date, cutoff)
    seed_relations = [
        relation for relation in seed_relations if relation.get("us_symbol") in configured_symbols
    ]
    eligible_current: list[dict[str, Any]] = []
    post_cutoff_count = 0
    post_cutoff_review_count = 0
    review_pending_count = 0
    eligible_current_symbol_assessments: list[dict[str, Any]] = []
    post_cutoff_assessment_count = 0
    post_cutoff_assessment_review_count = 0
    assessment_review_pending_count = 0
    current_reviewed_at = timestamp(review_info.get("reviewed_at")) if review_info else None
    for card in parsed_cards:
        if str(card.get("us_symbol") or "").upper() not in configured_symbols:
            continue
        available_at = timestamp(card.get("available_at"))
        if available_at is None:
            current_artifact_error = "US_RELATION_EVIDENCE_CARD_FIELDS_INVALID"
            continue
        if available_at > cutoff:
            post_cutoff_count += 1
            continue
        if review_info is None or current_reviewed_at is None:
            review_pending_count += 1
            continue
        if current_reviewed_at > cutoff:
            post_cutoff_review_count += 1
            continue
        effective_available_at = max(available_at, current_reviewed_at)
        relation = deepcopy(card)
        relation["relation_source"] = "CURRENT_REVIEWED_RELATION_EVIDENCE"
        relation["source_captured_available_at"] = available_at.isoformat()
        relation["available_at"] = effective_available_at.isoformat()
        relation["reviewed_at"] = current_reviewed_at.isoformat()
        relation["evidence_timing"] = (
            "RETROSPECTIVE_AFTER_TARGET_DATE"
            if effective_available_at.date().strftime("%Y%m%d") > target_date
            else "AVAILABLE_BY_TARGET_DATE"
        )
        relation["evidence_review_status"] = current_review_status
        relation["reviewer_identity"] = review_info["reviewer_identity"]
        relation["review_receipt_sha256"] = review_info["receipt_sha256"]
        relation["http_body_rehash_status"] = review_info["http_body_rehash_status"]
        relation["review_limitations"] = deepcopy(review_info["limitations"])
        relation["target_date_eligibility"] = "CANNOT_CONFIRM"
        relation["provenance"] = {
            "relation_source": relation["relation_source"],
            "evidence_path": "v4/manager_research/us_mapping_relation_evidence_20261011.json",
            "evidence_file_sha256": hashlib.sha256(evidence_raw).hexdigest(),
            "evidence_artifact_sha256": evidence.get("artifact_sha256"),
            "review_receipt_sha256": review_info["receipt_sha256"],
            "reviewer_identity": review_info["reviewer_identity"],
            "reviewed_at": current_reviewed_at.isoformat(),
            "source_captured_available_at": available_at.isoformat(),
            "available_at": effective_available_at.isoformat(),
            "http_body_rehash_status": review_info["http_body_rehash_status"],
        }
        identity = review_info.get("us_symbol_identity_evidence", {}).get(card.get("us_symbol"))
        if identity:
            identity = deepcopy(identity)
            relation["reviewer_identity_evidence"] = identity
            identity_source = {
                "role": "US_SYMBOL_IDENTITY",
                "title": identity.get("title") or f"{identity['issuer']} official issuer identity source",
                "url": identity["url"],
                "published_at": identity.get("published_at"),
                "retrieved_at": identity["retrieved_at"],
                "source_locator": identity["source_locator"],
                "source_body_sha256": identity.get("source_body_sha256"),
                "source_body_sha256_status": identity["source_body_sha256_status"],
                "evidence_source": "INDEPENDENT_REVIEW_RECEIPT",
            }
            if identity.get("source_capture_status"):
                identity_source["source_capture_status"] = identity["source_capture_status"]
            relation["sources"] = [*deepcopy(card.get("sources", [])), identity_source]
        relation.update(FLAGS)
        eligible_current.append(relation)

    for assessment in parsed_symbol_assessments:
        if str(assessment.get("us_symbol") or "").upper() not in configured_symbols:
            continue
        captured_at = timestamp(assessment.get("available_at"))
        if captured_at is None:
            current_artifact_error = "US_RELATION_SYMBOL_ASSESSMENT_FIELDS_INVALID"
            continue
        if captured_at > cutoff:
            post_cutoff_assessment_count += 1
            continue
        if review_info is None or current_reviewed_at is None:
            assessment_review_pending_count += 1
            continue
        if current_reviewed_at > cutoff:
            post_cutoff_assessment_review_count += 1
            continue
        effective_available_at = max(captured_at, current_reviewed_at)
        reviewed_assessment = deepcopy(assessment)
        reviewed_assessment["relation_source"] = "CURRENT_REVIEWED_SYMBOL_ASSESSMENT"
        reviewed_assessment["source_captured_available_at"] = captured_at.isoformat()
        reviewed_assessment["available_at"] = effective_available_at.isoformat()
        reviewed_assessment["reviewed_at"] = current_reviewed_at.isoformat()
        reviewed_assessment["evidence_timing"] = (
            "RETROSPECTIVE_AFTER_TARGET_DATE"
            if effective_available_at.date().strftime("%Y%m%d") > target_date
            else "AVAILABLE_BY_TARGET_DATE"
        )
        reviewed_assessment["evidence_review_status"] = current_review_status
        reviewed_assessment["reviewer_identity"] = review_info["reviewer_identity"]
        reviewed_assessment["review_receipt_sha256"] = review_info["receipt_sha256"]
        reviewed_assessment["assessment_sha256"] = sha256_json(assessment)
        reviewed_assessment["target_date_eligibility"] = "CANNOT_CONFIRM"
        reviewed_assessment["provenance"] = {
            "relation_source": reviewed_assessment["relation_source"],
            "evidence_path": "v4/manager_research/us_mapping_relation_evidence_20261011.json",
            "evidence_file_sha256": hashlib.sha256(evidence_raw).hexdigest(),
            "evidence_artifact_sha256": evidence.get("artifact_sha256"),
            "assessment_sha256": reviewed_assessment["assessment_sha256"],
            "review_receipt_sha256": review_info["receipt_sha256"],
            "reviewer_identity": review_info["reviewer_identity"],
            "reviewed_at": current_reviewed_at.isoformat(),
            "source_captured_available_at": captured_at.isoformat(),
            "available_at": effective_available_at.isoformat(),
        }
        reviewed_assessment.update(FLAGS)
        eligible_current_symbol_assessments.append(reviewed_assessment)

    # The old four relations were available under the separate release registry.
    # Dedupe identical typed/directed relations while keeping both provenance records.
    eligible_cards: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for relation in [*seed_relations, *eligible_current]:
        key = (
            str(relation.get("us_symbol") or ""), str(relation.get("hk_symbol") or ""),
            str(relation.get("relationship_type") or ""), str(relation.get("direction") or ""),
        )
        existing = by_key.get(key)
        new_provenance = deepcopy(relation.get("provenance") or {})
        if existing is None:
            relation["evidence_provenance"] = [new_provenance]
            by_key[key] = relation
            eligible_cards.append(relation)
            continue
        provenance_rows = existing.get("evidence_provenance")
        if isinstance(provenance_rows, list) and new_provenance not in provenance_rows:
            provenance_rows.append(new_provenance)
        source_rows = existing.get("sources") if isinstance(existing.get("sources"), list) else []
        seen_source_ids = {
            (item.get("url"), item.get("title")) for item in source_rows if isinstance(item, Mapping)
        }
        for source in relation.get("sources", []) if isinstance(relation.get("sources"), list) else []:
            if isinstance(source, Mapping) and (source.get("url"), source.get("title")) not in seen_source_ids:
                source_rows.append(deepcopy(dict(source)))
                seen_source_ids.add((source.get("url"), source.get("title")))
        existing["sources"] = source_rows
        existing["evidence_review_status"] = "MULTIPLE_REVIEWED_EVIDENCE_SOURCES"

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for card in eligible_cards:
        by_symbol.setdefault(str(card["us_symbol"]), []).append(card)
    assessed_gap_by_symbol = {
        str(assessment["us_symbol"]): assessment
        for assessment in eligible_current_symbol_assessments
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        linked = by_symbol.get(symbol, [])
        row["relations"] = deepcopy(linked)
        row["relation_count"] = len(linked) if linked else None
        if linked:
            sources = {relation.get("relation_source") for relation in linked}
            if sources == {"RELEASE_PINNED_REVIEWED_SEED"}:
                row["relation_assessment_status"] = "RELEASE_PINNED_REVIEWED_RELATIONS_AVAILABLE"
            elif sources == {"CURRENT_REVIEWED_RELATION_EVIDENCE"}:
                row["relation_assessment_status"] = "INDEPENDENTLY_REVIEWED_RELATIONS_AVAILABLE"
            else:
                row["relation_assessment_status"] = "MULTI_SOURCE_REVIEWED_RELATIONS_AVAILABLE"
            row["relation_gaps"] = []
        elif row.get("instrument_classification") == "ETF_PROXY":
            row["relation_assessment_status"] = "ETF_THEME_PROXY_ONLY"
            row["relation_gaps"] = ["ETF_PROXY_IS_NOT_AN_ISSUER_RELATION"]
        elif symbol in assessed_gap_by_symbol:
            row["relation_assessment_status"] = "ASSESSED_WITH_GAPS"
            row["relation_assessment_evidence"] = deepcopy(assessed_gap_by_symbol[symbol])
            row["relation_gaps"] = [str(assessed_gap_by_symbol[symbol]["reason"])]
        elif any(str(assessment.get("us_symbol") or "") == symbol for assessment in parsed_symbol_assessments):
            row["relation_assessment_status"] = "ASSESSED_WITH_GAPS_NOT_AVAILABLE_BY_CUTOFF"
            row["relation_gaps"] = ["SYMBOL_ASSESSMENT_OR_REVIEW_NOT_AVAILABLE_BY_CUTOFF"]
        else:
            row["relation_assessment_status"] = "NOT_EVALUATED"
            row["relation_gaps"] = ["RELATION_SEARCH_NOT_COMPLETE_FOR_SYMBOL"]
            pending_symbols = {str(card.get("us_symbol")) for card in parsed_cards}
            if symbol in pending_symbols and (post_cutoff_count or post_cutoff_review_count or review_pending_count):
                row["relation_gaps"] = ["CURRENT_RELATION_EVIDENCE_NOT_AVAILABLE_BY_CUTOFF"]
    artifact_sha = str(evidence.get("artifact_sha256")) if evidence is not None else None
    overlay_identity = digest([
        target_date, session, bridge_source_payload_sha,
        result.get("research_cutoff"), artifact_sha, eligible_cards,
        eligible_current_symbol_assessments,
    ])
    gaps = ["RELATION_EVIDENCE_COVERAGE_NOT_COMPLETE"]
    if post_cutoff_count:
        gaps.append("RELATION_EVIDENCE_AFTER_CURRENT_CUTOFF")
    if post_cutoff_review_count:
        gaps.append("RELATION_REVIEW_AFTER_CURRENT_CUTOFF")
    if review_pending_count:
        gaps.append("RELATION_EVIDENCE_REVIEW_PENDING")
    if post_cutoff_assessment_count:
        gaps.append("SYMBOL_ASSESSMENT_AFTER_CURRENT_CUTOFF")
    if post_cutoff_assessment_review_count:
        gaps.append("SYMBOL_ASSESSMENT_REVIEW_AFTER_CURRENT_CUTOFF")
    if assessment_review_pending_count:
        gaps.append("SYMBOL_ASSESSMENT_REVIEW_PENDING")
    if review_error:
        gaps.append("US_RELATION_REVIEW_RECEIPT_INVALID")
    if current_artifact_error:
        gaps.append(current_artifact_error)
    gaps.extend(seed_gaps)
    relation_source_artifacts = []
    if seed_availability and seed_relations:
        relation_source_artifacts.append({
            "relation_source": "RELEASE_PINNED_REVIEWED_SEED",
            "reviewed_relation_artifact_sha256": seed_relations[0]["provenance"]["reviewed_relation_artifact_sha256"],
            "reviewed_seed_file_sha256": seed_availability["seed_file_sha256"],
            "availability_registry_file_sha256": seed_availability["registry_file_sha256"],
            "availability_registry_artifact_sha256": seed_availability["registry_artifact_sha256"],
            "release_id": seed_availability["release_id"],
            "available_at": seed_availability["available_at"],
            "eligible_relation_count": len(seed_relations),
        })
    if evidence is not None:
        relation_source_artifacts.append({
            "relation_source": "CURRENT_REVIEWED_RELATION_EVIDENCE",
            "evidence_path": "v4/manager_research/us_mapping_relation_evidence_20261011.json",
            "evidence_file_sha256": hashlib.sha256(evidence_raw).hexdigest(),
            "evidence_artifact_sha256": artifact_sha,
            "review_receipt_sha256": review_info.get("receipt_sha256") if review_info else None,
            "reviewer_identity": review_info.get("reviewer_identity") if review_info else None,
            "reviewed_at": review_info.get("reviewed_at") if review_info else None,
            "http_body_rehash_status": review_info.get("http_body_rehash_status") if review_info else "CANNOT_CONFIRM",
            "eligible_relation_count": len(eligible_current),
            "source_card_count": len(parsed_cards),
            "symbol_assessment_count": len(parsed_symbol_assessments),
            "eligible_symbol_assessment_count": len(eligible_current_symbol_assessments),
        })
    explicitly_assessed_equities = {
        str(row.get("symbol") or "").upper()
        for row in rows if isinstance(row, Mapping)
        and row.get("instrument_classification") == "EQUITY_PROXY"
        and (by_symbol.get(str(row.get("symbol") or "").upper())
             or str(row.get("relation_assessment_status") or "").startswith("ASSESSED_WITH_GAPS"))
    }
    configured_equities = {
        str(row.get("symbol") or "").upper()
        for row in rows if isinstance(row, Mapping)
        and row.get("instrument_classification") == "EQUITY_PROXY"
    }
    result["relation_evidence"] = {
        "status": "PARTIAL_SOURCE_EVIDENCE_COVERAGE" if eligible_cards else "NOT_EVALUATED",
        "artifact_sha256": artifact_sha,
        "source_card_count": len(parsed_cards),
        "eligible_relation_count": len(eligible_cards),
        "post_cutoff_relation_count": post_cutoff_count,
        "post_cutoff_review_count": post_cutoff_review_count,
        "review_pending_relation_count": review_pending_count,
        "symbol_assessment_count": len(parsed_symbol_assessments),
        "eligible_symbol_assessment_count": len(eligible_current_symbol_assessments),
        "post_cutoff_symbol_assessment_count": post_cutoff_assessment_count,
        "post_cutoff_symbol_assessment_review_count": post_cutoff_assessment_review_count,
        "review_pending_symbol_assessment_count": assessment_review_pending_count,
        "reviewed_seed_relation_count": len(seed_relations),
        "current_reviewed_relation_count": len(eligible_current),
        "withheld_candidate_count": len(withheld_candidates),
        "withheld_candidates": deepcopy(withheld_candidates),
        "mapped_us_symbol_count": len(by_symbol),
        "configured_us_symbol_count": len(rows),
        "configured_equity_symbol_count": len(configured_equities),
        "explicitly_assessed_equity_symbol_count": len(explicitly_assessed_equities),
        "unassessed_equity_symbols": sorted(configured_equities - explicitly_assessed_equities),
        "equity_assessment_coverage_complete": configured_equities == explicitly_assessed_equities,
        "coverage_complete": False,
        "relation_source_artifacts": relation_source_artifacts,
        "review_receipt": deepcopy(review_info) if review_info else None,
        "source_body_rehash_status": review_info.get("http_body_rehash_status") if review_info else "CANNOT_CONFIRM",
        "assessment_identity": overlay_identity,
        "current_bridge_session": session,
        "current_bridge_source_payload_sha256": bridge_source_payload_sha,
        "target_date_eligibility": "CANNOT_CONFIRM",
        "retrospective_relations_present": any(
            card.get("evidence_timing") == "RETROSPECTIVE_AFTER_TARGET_DATE" for card in eligible_cards),
        "gaps": sorted(set(gaps)),
        **FLAGS,
    }
    return result


def build_daily_run(service: Any, target_trade_date: str, *, now: datetime) -> dict[str, Any]:
    date = strict_trade_date(target_trade_date)
    if now.tzinfo is None:
        raise ValueError("US_MAPPING_CLOCK_MUST_BE_AWARE")
    context = plan_context(date, now=now)
    from .us_market_bridge import project_us_market

    bridge = project_us_market(getattr(service, "_workspace_us_market_reader", None), date, context)
    reviewed = _read_reviewed()
    source_status = bridge.get("status")
    gaps = list(bridge.get("gaps") or [])
    matches: list[dict[str, Any]] = []
    complete_snapshot = source_status == "READY"
    row_mapping_eligible = complete_snapshot or (
        source_status == "PARTIAL" and bridge.get("mapping_eligible") is True
    )
    relation_available_at, relation_registry_gap = _relation_available_at(reviewed)
    cutoff = timestamp(bridge.get("research_cutoff"))
    relation_available = bool(
        relation_available_at is not None and cutoff is not None and relation_available_at <= cutoff
    )
    if relation_registry_gap:
        gaps.append(relation_registry_gap)
    elif not relation_available:
        gaps.append("US_HK_RELATION_NOT_AVAILABLE_AT_RESEARCH_CUTOFF")
    if row_mapping_eligible and relation_available:
        relations = _relation_index()
        for row in bridge.get("raw_individual_up") or []:
            if not isinstance(row, Mapping):
                continue
            symbol = str(row.get("symbol") or "").upper()
            for card in relations.get(symbol, []):
                matches.append({
                    "us_symbol": symbol,
                    "change_pct": row.get("change_pct"),
                    "session_date": row.get("session_date"),
                    "hk_symbol": card.get("hk_symbol"),
                    "hk_name": card.get("hk_name"),
                    "research_priority": card.get("research_priority"),
                    "relationship_type": card.get("relationship_type"),
                    "reason": card.get("reason"),
                    "maturity": card.get("maturity"),
                    "limitations": card.get("limitations"),
                    "official_sources": deepcopy(card.get("official_sources", [])),
                    "reviewed_relation_artifact_sha256": reviewed.get("artifact_sha256"),
                    "target_date_eligibility": "CANNOT_CONFIRM",
                    "source_row": deepcopy(dict(row)),
                })
    if source_status == "SOURCE_FAILED":
        status = "FAILED"
    elif source_status in {"INPUT_MISSING", "CANNOT_CONFIRM"}:
        status = "INPUT_MISSING" if source_status == "INPUT_MISSING" else "CANNOT_CONFIRM"
    elif source_status == "PARTIAL":
        status = "PARTIAL"
        gaps.append("US_MARKET_SOURCE_PARTIAL")
    elif complete_snapshot:
        status = "COMPLETED" if matches else "VALID_EMPTY" if relation_available else "PARTIAL"
    else:
        status = "CANNOT_CONFIRM"
        gaps.append("US_MARKET_SOURCE_STATUS_UNRECOGNIZED")

    coverage = bridge.get("coverage") if isinstance(bridge.get("coverage"), Mapping) else {}
    source_identity = bridge.get("source_identity") if isinstance(bridge.get("source_identity"), Mapping) else None
    relation_sha = reviewed.get("artifact_sha256") if relation_available else None
    identity = digest([date, bridge.get("expected_us_session"), bridge.get("research_cutoff"), source_identity,
                       matches, relation_sha])
    run_id = uuid4().hex
    value = {
        "schema_version": DAILY_SCHEMA,
        "status": status,
        "target_trade_date": date,
        "run_id": run_id,
        "generated_at": _now_text(now),
        "us_session_date": bridge.get("expected_us_session"),
        "research_cutoff": bridge.get("research_cutoff"),
        "coverage_scope": "FOUR_REVIEWED_US_TICKER_RELATIONS_WITHIN_FIXED_33_CONFIGURED_SYMBOL_SAMPLE_NOT_FULL_MARKET",
        "coverage": {
            "reviewed_us_symbol_count": 4,
            "matched_us_symbol_count": len({row["us_symbol"] for row in matches}) if row_mapping_eligible and relation_available else None,
            "matched_hk_relation_count": len(matches) if row_mapping_eligible and relation_available else None,
            "configured_us_universe_count": coverage.get("requested_symbol_count") if row_mapping_eligible else None,
            "available_us_universe_count": coverage.get("available_symbol_count") if row_mapping_eligible else None,
            "full_market_coverage": False,
        },
        "matches": matches,
        "source_status": source_status,
        "source_identity": deepcopy(dict(source_identity)) if source_identity else None,
        "source_gaps": gaps,
        "input_identity": identity,
        "relation_artifact_sha256": relation_sha,
        "target_date_eligibility": "CANNOT_CONFIRM",
        "producer_owner": "ManagerResearchJobService / ResearchPeripheralStore read adapter",
        "readback_required": True,
        "gaps": sorted(set(gaps)),
        **FLAGS,
    }
    return value


def persist_daily_run(service: Any, target_trade_date: str, *, now: datetime) -> dict[str, Any]:
    value = build_daily_run(service, target_trade_date, now=now)
    unsigned = dict(value)
    value["artifact_sha256"] = sha256_json(unsigned)
    _safe_tree(value)
    store = service.store
    directory = store.root / "us_mapping_research" / value["target_trade_date"]
    run_path = directory / "runs" / f"{value['run_id']}.json"
    pointer_path = directory / "latest.json"
    with store._transaction(value["target_trade_date"], value["input_identity"]):
        store._write_atomic(run_path, value)
        pointer = {
            "schema_version": "v4.manager_research.us_mapping_daily_pointer.v1",
            "target_trade_date": value["target_trade_date"],
            "run_id": value["run_id"],
            "artifact_sha256": value["artifact_sha256"],
            **FLAGS,
        }
        store._write_atomic(pointer_path, pointer)
    saved = _read_saved(store, value["target_trade_date"])
    if saved is None or saved.get("artifact_sha256") != value["artifact_sha256"]:
        raise ValueError("US_MAPPING_DAILY_READBACK_FAILED")
    return saved


__all__ = ["DAILY_SCHEMA", "SCHEMA", "build_daily_run", "persist_daily_run", "read_workspace_mapping"]
