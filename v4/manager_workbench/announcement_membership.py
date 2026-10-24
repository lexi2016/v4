"""User-fixed HK Connect membership gate for announcement candidates.

This module verifies and reuses one existing authority. It does not infer an
effective interval, acquire data, or produce a second membership dataset.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from infrastructure.owned_io import SafeRoot

SCHEMA = "v4.manager_workbench.announcement_connect_membership.v1"
_POLICY_SCHEMA = "v4.manager_workbench.announcement_fixed_connect_membership_policy.v1"
_FIXED_POLICY = "FIXED_UNTIL_EXPLICIT_USER_UPDATE"
_SOURCE_REF_ORDER = ("artifact", "capture", "current", "manifest", "publication", "receipt")
_SOURCE_WORKLOAD = "v35_dispatcher.research_panel_daily_hk"
_SOURCE_OWNER = "FUTU_HKCONNECT_PLATE_MEMBERSHIP"
_HK_CODE = re.compile(r"^HK\.([0-9]{5})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_error(exc: Exception) -> str:
    value = str(exc)
    return value if re.fullmatch(r"[A-Z0-9_:-]{1,96}", value) else "FIXED_CONNECT_MEMBERSHIP_UNVERIFIED"


def _valid_date_token(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        return False
    try:
        date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")
    except ValueError:
        return False
    return True


def _available_by_cutoff(available_at: Any, cutoff: Any) -> bool:
    try:
        available = datetime.fromisoformat(available_at)
        bound = datetime.fromisoformat(cutoff)
    except (TypeError, ValueError):
        return False
    return bool(available.tzinfo is not None and available.utcoffset() is not None
                and bound.tzinfo is not None and bound.utcoffset() is not None
                and available <= bound)


def _config_value(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _fixed_policy() -> dict[str, Any]:
    path = Path(__file__).with_name("announcement_membership_policy.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_POLICY_INVALID")
    return value


def _read_fixed_json(root: SafeRoot, reference: Any) -> tuple[dict[str, Any], str]:
    if (not isinstance(reference, dict)
            or not isinstance(reference.get("relative"), str)
            or not _SHA256.fullmatch(str(reference.get("sha256", "")))):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_REFERENCE_INVALID")
    raw = root.read_bytes(reference["relative"])
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != reference["sha256"]:
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_SHA_MISMATCH")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_OWNER_OBJECT_INVALID")
    return value, actual_sha


def _resolve_fixed_authority(config: Any, target_date: str, cutoff: str) -> dict[str, Any]:
    if not _valid_date_token(target_date):
        raise ValueError("MEMBERSHIP_TARGET_DATE_INVALID")
    policy = _fixed_policy()
    authority = policy.get("authority")
    if (policy.get("schema") != _POLICY_SCHEMA
            or policy.get("decision") != _FIXED_POLICY
            or policy.get("replacement") != "EXPLICIT_USER_REQUEST_ONLY"
            or not isinstance(authority, dict)
            or authority.get("owner") != _SOURCE_OWNER
            or authority.get("producer_workload_id") != _SOURCE_WORKLOAD
            or authority.get("market") != "HK_CONNECT"
            or authority.get("scope_type") != "HK_CONNECT_FULL_MARKET"
            or not _valid_date_token(authority.get("source_date"))
            or not isinstance(authority.get("available_at"), str)
            or not isinstance(authority.get("member_count"), int)
            or authority.get("member_count", 0) <= 0
            or not _SHA256.fullmatch(str(authority.get("members_sha256", "")))
            or not _SHA256.fullmatch(str(authority.get("identity_sha256", "")))):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_POLICY_INVALID")
    references = authority.get("references")
    if not isinstance(references, dict) or set(references) != set(_SOURCE_REF_ORDER):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_POLICY_REFERENCES_INVALID")

    root_path = _config_value(config, "shared_root")
    if not isinstance(root_path, (str, Path)) or not str(root_path):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_SOURCE_ROOT_MISSING")
    source_root = SafeRoot(root_path)
    owner_files: dict[str, dict[str, Any]] = {}
    checked_files: list[dict[str, Any]] = []
    identity_refs: list[list[str]] = []
    for name in _SOURCE_REF_ORDER:
        reference = references[name]
        owner_files[name], actual_sha = _read_fixed_json(source_root, reference)
        checked_files.append({"source_local_path": str(source_root.root),
                              "relative": reference["relative"], "sha256": actual_sha})
        identity_refs.append([reference["relative"], actual_sha])

    artifact = owner_files["artifact"]
    capture = owner_files["capture"]
    current = owner_files["current"]
    manifest = owner_files["manifest"]
    publication = owner_files["publication"]
    receipt = owner_files["receipt"]
    ref = {name: references[name]["relative"] for name in _SOURCE_REF_ORDER}
    sha = {name: references[name]["sha256"] for name in _SOURCE_REF_ORDER}
    capture_identity = _sha({key: value for key, value in capture.items() if key != "capture_sha256"})
    producer_ids = (manifest.get("producer_owner", {}).get("workload_id"),
                    capture.get("producer_owner", {}).get("workload_id"),
                    current.get("producer_owner", {}).get("workload_id"),
                    publication.get("producer_owner", {}).get("workload_id"))
    codes = artifact.get("codes")
    if any(value != authority["producer_workload_id"] for value in producer_ids):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_PRODUCER_MISMATCH")
    if (artifact.get("schema_version") != "v3_shared_data.stage_universe.capture.v2"
            or artifact.get("market") != authority["market"]
            or artifact.get("effective_date") != authority["source_date"]
            or artifact.get("source_date") != authority["source_date"]
            or artifact.get("code_count") != authority["member_count"]
            or artifact.get("production_allowed") is not False
            or artifact.get("orders_sent", False) is not False
            or not isinstance(codes, list) or len(codes) != authority["member_count"]
            or not codes or any(not isinstance(code, str) or not _HK_CODE.fullmatch(code) for code in codes)
            or len(set(codes)) != len(codes)
            or capture.get("codes") != codes
            or current.get("plate_codes", {}).get("HK.GangGuTong") != codes
            or _sha(sorted(codes)) != authority["members_sha256"]):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_CODES_INVALID")
    if (current.get("schema_version") != "v3_shared_data.hk_connect.authority.current.v2"
            or current.get("status") != "READY"
            or current.get("authority_role") != "HK_CONNECT_FULL_MARKET_AUTHORITY"
            or current.get("source_role") != authority["owner"]
            or current.get("market") != authority["market"]
            or current.get("scope") != "FULL_MARKET"
            or current.get("source_date") != authority["source_date"]
            or current.get("effective_date") != authority["source_date"]
            or current.get("artifact_relative") != ref["artifact"]
            or current.get("artifact_sha256") != sha["artifact"]
            or current.get("capture_relative") != ref["capture"]
            or current.get("capture_sha256") != capture_identity
            or current.get("manifest_relative") != ref["manifest"]
            or current.get("manifest_sha256") != sha["manifest"]
            or current.get("publication_relative") != ref["publication"]
            or current.get("receipt_relative") != ref["receipt"]
            or current.get("receipt_sha256") != sha["receipt"]
            or current.get("code_count") != authority["member_count"]
            or current.get("codes_sha256") != authority["members_sha256"]
            or current.get("production_allowed") is not False
            or current.get("orders_sent", False) is not False
            or current.get("buy_gate_updated", False) is not False):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_CURRENT_BINDING_INVALID")
    if (manifest.get("schema_version") != "v3_shared_data.hk_connect.authority.manifest.v2"
            or manifest.get("authority_role") != "HK_CONNECT_FULL_MARKET_AUTHORITY"
            or manifest.get("status") != "READY"
            or manifest.get("artifact_relative") != ref["artifact"]
            or manifest.get("artifact_sha256") != sha["artifact"]
            or manifest.get("capture_relative") != ref["capture"]
            or manifest.get("capture_sha256") != capture_identity
            or manifest.get("publication_relative") != ref["publication"]
            or manifest.get("effective_date") != authority["source_date"]
            or manifest.get("source_date") != authority["source_date"]
            or manifest.get("production_allowed") is not False
            or manifest.get("orders_sent", False) is not False):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_MANIFEST_INVALID")
    if (capture.get("schema_version") != "v4.manager_hk_connect_capture.v2"
            or capture.get("capture_sha256") != capture_identity
            or capture_identity != manifest.get("capture_sha256")
            or capture_identity != receipt.get("capture_sha256")
            or _sha(capture.get("membership_source_payload")) != capture.get("membership_source_sha256")
            or capture.get("production_allowed") is not False
            or capture.get("orders_sent", False) is not False):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_CAPTURE_INVALID")
    if (publication.get("schema_version") != "v3_shared_data.hk_connect.authority.publication.v2"
            or publication.get("status") != "READY"
            or publication.get("market") != authority["market"]
            or publication.get("scope") != "FULL_MARKET"
            or publication.get("source_date") != authority["source_date"]
            or publication.get("available_at") != authority["available_at"]
            or publication.get("artifact_relative") != ref["artifact"]
            or publication.get("artifact_sha256") != sha["artifact"]
            or publication.get("capture_sha256") != capture_identity
            or publication.get("current_relative") != ref["current"]
            or publication.get("current_sha256") != sha["current"]
            or publication.get("manifest_relative") != ref["manifest"]
            or publication.get("receipt_relative") != ref["receipt"]
            or publication.get("production_allowed") is not False
            or publication.get("orders_sent", False) is not False
            or publication.get("buy_gate_updated", False) is not False):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_PUBLICATION_INVALID")
    if (receipt.get("schema_version") != "v3_shared_data.hk_connect.authority.receipt.v2"
            or receipt.get("status") != "READY"
            or receipt.get("artifact_sha256") != sha["artifact"]
            or receipt.get("capture_sha256") != capture_identity
            or receipt.get("manifest_sha256") != sha["manifest"]
            or receipt.get("production_allowed") is not False
            or receipt.get("orders_sent", False) is not False):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_RECEIPT_INVALID")
    if _sha(identity_refs) != authority["identity_sha256"]:
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_IDENTITY_MISMATCH")
    if (authority["source_date"] > target_date):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_SOURCE_AFTER_TARGET_DATE")
    if not _available_by_cutoff(authority["available_at"], cutoff):
        raise ValueError("FIXED_CONNECT_MEMBERSHIP_AFTER_CUTOFF_OR_UNKNOWN")

    return {
        "source_root": str(source_root.root),
        "owner": authority["owner"],
        "producer_owner": authority["producer_workload_id"],
        "source_date": authority["source_date"],
        "available_at": authority["available_at"],
        "authority_sha256": sha["artifact"],
        "authority_version": authority["identity_sha256"],
        "member_count": len(codes),
        "members_sha256": _sha(sorted(codes)),
        "codes": sorted(codes),
        "checked_files": checked_files,
        "references": deepcopy(references),
    }


def resolve_membership_gate(config: Any, target_date: str, cutoff: str) -> dict[str, Any]:
    """Resolve one user-fixed authority without imposing monthly target validity."""
    base = {"schema": SCHEMA, "target_date": target_date, "cutoff": cutoff,
            "market": "HK_CONNECT", "basis": "USER_FIXED_UNIVERSE",
            "membership_policy": _FIXED_POLICY}
    try:
        fixed = _resolve_fixed_authority(config, target_date, cutoff)
        pin = {"source_local_path": fixed["source_root"], "owner": fixed["owner"],
               "producer_owner": fixed["producer_owner"],
               "artifact_relative": fixed["references"]["artifact"]["relative"],
               "artifact_sha256": fixed["authority_sha256"],
               "checked_files": deepcopy(fixed["checked_files"])}
        return {
            **base,
            "status": "VERIFIED",
            "owner": fixed["owner"],
            "producer_owner": fixed["producer_owner"],
            "authority_sha256": fixed["authority_sha256"],
            "authority_version": fixed["authority_version"],
            "source_date": fixed["source_date"],
            "effective_from": None,
            "effective_to": None,
            "available_at": fixed["available_at"],
            "member_count": fixed["member_count"],
            "members_sha256": fixed["members_sha256"],
            "codes": fixed["codes"],
            "authority_pin": deepcopy(pin),
        }
    except Exception as exc:
        return {**base, "status": "CANNOT_CONFIRM", "failure_code": _safe_error(exc),
                "owner": None, "producer_owner": None, "authority_sha256": None,
                "authority_version": None, "source_date": None,
                "effective_from": None, "effective_to": None, "available_at": None,
                "member_count": None, "members_sha256": None, "codes": [], "authority_pin": None}


def revalidate_membership_gate(config: Any, gate: Any, target_date: str, cutoff: str) -> dict[str, Any]:
    """Re-resolve the same authority at the same date/cutoff before admission."""
    failure = {"schema": SCHEMA, "target_date": target_date, "cutoff": cutoff,
               "market": "HK_CONNECT", "basis": "USER_FIXED_UNIVERSE",
               "membership_policy": _FIXED_POLICY, "effective_from": None, "effective_to": None}
    if (not isinstance(gate, dict) or gate.get("schema") != SCHEMA
            or gate.get("status") != "VERIFIED" or gate.get("target_date") != target_date
            or gate.get("cutoff") != cutoff or gate.get("market") != "HK_CONNECT"):
        return {**failure, "status": "CANNOT_CONFIRM", "failure_code": "MEMBERSHIP_GATE_INPUT_INVALID",
                "codes": []}
    fresh = resolve_membership_gate(config, target_date, cutoff)
    fields = ("basis", "membership_policy", "owner", "producer_owner", "authority_sha256",
              "authority_version", "source_date", "effective_from", "effective_to", "available_at",
              "member_count", "members_sha256")
    if fresh.get("status") != "VERIFIED" or any(fresh.get(key) != gate.get(key) for key in fields):
        return {**failure, "status": "CANNOT_CONFIRM", "failure_code": "MEMBERSHIP_GATE_BINDING_CHANGED",
                "codes": []}
    return fresh


def issuer_codes(metadata: Any) -> list[str]:
    if not isinstance(metadata, dict):
        return []
    values = metadata.get("source_issuer_codes")
    if isinstance(values, list):
        if len(values) != 1:
            return []
        value = values[0]
    else:
        value = metadata.get("symbol")
    raw = value.get("code") if isinstance(value, dict) else value
    match = _HK_CODE.fullmatch(raw) if isinstance(raw, str) else None
    return [match.group(0)] if match else []


def classify_codes(codes: list[str], gate: Any) -> tuple[str, str]:
    if not isinstance(gate, dict) or gate.get("status") != "VERIFIED":
        return "UNKNOWN", "MEMBERSHIP_AUTHORITY_UNVERIFIED"
    if len(codes) != 1:
        return "UNKNOWN", "ISSUER_CODE_MISSING_OR_AMBIGUOUS"
    members = gate.get("codes")
    if not isinstance(members, list) or not gate.get("authority_sha256"):
        return "UNKNOWN", "MEMBERSHIP_AUTHORITY_UNVERIFIED"
    fixed = gate.get("basis") == "USER_FIXED_UNIVERSE"
    if codes[0] in members:
        return "IN", "HK_CONNECT_MEMBER_IN_FIXED_UNIVERSE" if fixed else "HK_CONNECT_MEMBER_AT_TARGET_DATE"
    return "OUT", "OUTSIDE_FIXED_HK_CONNECT_UNIVERSE" if fixed else "NOT_IN_HK_CONNECT_UNIVERSE_AT_TARGET_DATE"


def classify_payload(payload: Any, gate: Any) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    metadata = payload.get("article_metadata")
    codes = issuer_codes(metadata)
    status, reason = classify_codes(codes, gate)
    return {"article_id": payload.get("article_id"),
            "symbol": metadata.get("symbol") if isinstance(metadata, dict) else None,
            "title": metadata.get("title") if isinstance(metadata, dict) else None,
            "issuer_codes": codes, "membership_status": status, "membership_reason": reason}


def classify_capture_row(row: Any, gate: Any) -> dict[str, Any]:
    row = row if isinstance(row, dict) else {}
    metadata = {"source_issuer_codes": row.get("source_issuer_codes")}
    codes = issuer_codes(metadata)
    status, reason = classify_codes(codes, gate)
    return {"article_id": "EASTMONEY:" + str(row.get("art_code") or ""),
            "symbol": codes[0] if len(codes) == 1 else "CANNOT_CONFIRM",
            "title": row.get("title"), "issuer_codes": codes,
            "membership_status": status, "membership_reason": reason}


def capture_recovery_manifest(rows: Any, gate: Any) -> dict[str, Any]:
    """Return a body-free, deterministic lock for one captured membership batch.

    The row manifest binds the exact listing identities and membership decisions;
    body hashes are recorded separately so a previously incomplete IN row may be
    completed from a validated cache receipt without changing the frozen listing
    set.
    """
    if not isinstance(rows, list) or not isinstance(gate, dict) or gate.get("status") != "VERIFIED":
        raise ValueError("RECOVERY_MANIFEST_INPUT_UNVERIFIED")
    records: list[dict[str, Any]] = []
    article_ids: list[str] = []
    eligible: list[str] = []
    body_sha256: dict[str, str] = {}
    eligible_missing_body: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("RECOVERY_MANIFEST_ROW_INVALID")
        art_code = row.get("art_code")
        article_id = "EASTMONEY:" + str(art_code or "")
        raw_row = row.get("raw_row")
        listing_ref = row.get("listing_source_ref")
        if (not re.fullmatch(r"EASTMONEY:AN[A-Z0-9]{8,32}", article_id)
                or not isinstance(raw_row, dict) or not isinstance(listing_ref, dict)
                or not re.fullmatch(r"[0-9a-f]{64}", str(listing_ref.get("sha256", "")))
                or row.get("window_consumption_status") not in {
                    "ELIGIBLE_SOURCE_TIME", "EXCLUDED_OUTSIDE_WINDOW"
                }):
            raise ValueError("RECOVERY_MANIFEST_ROW_IDENTITY_INVALID")
        article_ids.append(article_id)
        membership = classify_capture_row(row, gate)
        in_window = row.get("window_consumption_status") == "ELIGIBLE_SOURCE_TIME"
        if in_window and membership["membership_status"] == "IN":
            eligible.append(article_id)
        body_complete = row.get("body_complete") is True
        body_sha = row.get("body_text_sha256")
        if body_complete:
            if (not isinstance(row.get("body_text"), str) or not row.get("body_text")
                    or not isinstance(body_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", body_sha)
                    or hashlib.sha256(row["body_text"].encode("utf-8")).hexdigest() != body_sha):
                raise ValueError("RECOVERY_MANIFEST_BODY_SHA_INVALID")
            body_sha256[article_id] = body_sha
        elif in_window and membership["membership_status"] == "IN":
            eligible_missing_body.append(article_id)
        records.append({
            "article_id": article_id,
            "publication_date": row.get("publication_date"),
            "title": row.get("title"),
            "display_time": row.get("display_time"),
            "window_status": row["window_consumption_status"],
            "raw_row_sha256": _sha(raw_row),
            "listing_source_sha256": listing_ref["sha256"],
            "issuer_codes": membership["issuer_codes"],
            "membership_status": membership["membership_status"],
        })
    if len(set(article_ids)) != len(article_ids):
        raise ValueError("RECOVERY_MANIFEST_DUPLICATE_ARTICLE")
    records.sort(key=lambda item: item["article_id"])
    article_ids.sort()
    eligible.sort()
    eligible_missing_body.sort()
    return {
        "row_count": len(records),
        "article_ids": article_ids,
        "article_ids_sha256": _sha(article_ids),
        "row_manifest_sha256": _sha(records),
        "eligible_article_ids": eligible,
        "eligible_article_ids_sha256": _sha(eligible),
        "eligible_count": len(eligible),
        "body_sha256": body_sha256,
        "eligible_missing_body_article_ids": eligible_missing_body,
    }


def filter_payloads(payloads: list[dict[str, Any]], gate: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    allowed, excluded = [], []
    for payload in payloads:
        item = classify_payload(payload, gate)
        if item["membership_status"] == "IN":
            allowed.append(payload)
        else:
            excluded.append(item)
    return allowed, excluded


def classify_symbol(symbol: Any, gate: Any) -> tuple[str, str]:
    match = _HK_CODE.fullmatch(symbol) if isinstance(symbol, str) else None
    codes = [match.group(0)] if match else []
    return classify_codes(codes, gate)


def project_stocks(stocks: Any, gate: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    eligible, excluded, unknown = [], [], []
    for stock in stocks if isinstance(stocks, list) else []:
        if not isinstance(stock, dict):
            continue
        status, reason = classify_symbol(stock.get("symbol"), gate)
        projection = deepcopy(stock)
        projection["membership_status"] = status
        projection["membership_reason"] = reason
        for article in projection.get("articles", []):
            if isinstance(article, dict):
                article["membership_status"] = status
                article["membership_reason"] = reason
        if status == "IN":
            eligible.append(projection)
        elif status == "OUT":
            excluded.append(projection)
        else:
            unknown.append(projection)
    return eligible, excluded, unknown


def project_status_rows(rows: Any, gate: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    eligible, excluded, unknown = [], [], []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        status, reason = classify_symbol(row.get("symbol"), gate)
        projection = {**row, "membership_status": status, "membership_reason": reason}
        if status == "IN":
            eligible.append(projection)
        elif status == "OUT":
            excluded.append(projection)
        else:
            unknown.append(projection)
    return eligible, excluded, unknown


def public_gate(gate: Any) -> dict[str, Any]:
    if not isinstance(gate, dict):
        gate = {"status": "CANNOT_CONFIRM", "failure_code": "MEMBERSHIP_AUTHORITY_UNVERIFIED"}
    keys = ("status", "target_date", "cutoff", "market", "basis", "membership_policy",
            "owner", "producer_owner", "authority_sha256", "authority_version", "source_date",
            "effective_from", "effective_to", "available_at", "member_count", "members_sha256",
            "failure_code")
    return {key: gate.get(key) for key in keys}
