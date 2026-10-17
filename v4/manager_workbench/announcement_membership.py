"""Target-date HK Connect membership gate for announcement candidates.

This module only resolves and projects the existing monthly authority. It does
not acquire, cache, or produce a second membership dataset.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from .contracts import Phase, RunContext


SCHEMA = "v4.manager_workbench.announcement_connect_membership.v1"
_HK_CODE = re.compile(r"^HK\.([0-9]{5})$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_error(exc: Exception) -> str:
    value = str(exc)
    return value if re.fullmatch(r"[A-Z0-9_:-]{1,96}", value) else "MONTHLY_CONNECT_MEMBERSHIP_UNVERIFIED"


def _context(target_date: str, cutoff: str) -> RunContext:
    return RunContext(target_date=target_date, phase=Phase.MANUAL, cutoff=cutoff, trigger="MANUAL",
                      rules_version="V4_ANNOUNCEMENT_CONNECT_MEMBERSHIP_V1")


def resolve_membership_gate(config: Any, target_date: str, cutoff: str) -> dict[str, Any]:
    """Resolve through the existing owner binding and NativeAdapters verifier."""
    base = {"schema": SCHEMA, "target_date": target_date, "cutoff": cutoff, "market": "HK_CONNECT"}
    try:
        from .inputs import NativeAdapters
        from .inputs.source_bindings import membership as resolve_owner_membership

        context = _context(target_date, cutoff)
        pin = resolve_owner_membership(config, context)
        context.scope_refs["owner_bindings"] = {"membership": deepcopy(pin)}
        codes, evidence, gaps = NativeAdapters(config).membership(context)
        if gaps or evidence is None or not codes:
            raise ValueError("MONTHLY_CONNECT_MEMBERSHIP_UNVERIFIED")
        projection = pin.get("projection")
        if not isinstance(projection, dict):
            raise ValueError("MONTHLY_CONNECT_MEMBERSHIP_PROJECTION_INVALID")
        normalized = sorted(codes)
        if (evidence.sha256 != pin.get("artifact_sha256")
                or projection.get("market") != "HK_CONNECT"
                or projection.get("owner") != evidence.owner
                or projection.get("available_at") != evidence.available_at
                or evidence.verification.value != "VERIFIED"):
            raise ValueError("MONTHLY_CONNECT_MEMBERSHIP_BINDING_MISMATCH")
        return {
            **base,
            "status": "VERIFIED",
            "owner": evidence.owner,
            "authority_sha256": evidence.sha256,
            "authority_version": projection.get("version"),
            "effective_from": projection.get("effective_from"),
            "effective_to": projection.get("effective_to"),
            "available_at": evidence.available_at,
            "member_count": len(normalized),
            "members_sha256": _sha(normalized),
            "codes": normalized,
            "authority_pin": deepcopy(pin),
        }
    except Exception as exc:
        return {**base, "status": "CANNOT_CONFIRM", "failure_code": _safe_error(exc),
                "owner": None, "authority_sha256": None, "authority_version": None,
                "effective_from": None, "effective_to": None, "available_at": None,
                "member_count": None, "members_sha256": None, "codes": [], "authority_pin": None}


def revalidate_membership_gate(config: Any, gate: Any, target_date: str, cutoff: str) -> dict[str, Any]:
    """Re-resolve the same authority at the same date/cutoff before admission."""
    if (not isinstance(gate, dict) or gate.get("schema") != SCHEMA
            or gate.get("status") != "VERIFIED" or gate.get("target_date") != target_date
            or gate.get("cutoff") != cutoff or gate.get("market") != "HK_CONNECT"):
        return {"schema": SCHEMA, "status": "CANNOT_CONFIRM", "target_date": target_date,
                "cutoff": cutoff, "market": "HK_CONNECT", "failure_code": "MEMBERSHIP_GATE_INPUT_INVALID",
                "codes": []}
    fresh = resolve_membership_gate(config, target_date, cutoff)
    fields = ("owner", "authority_sha256", "authority_version", "effective_from", "effective_to",
              "available_at", "member_count", "members_sha256")
    if fresh.get("status") != "VERIFIED" or any(fresh.get(key) != gate.get(key) for key in fields):
        return {"schema": SCHEMA, "status": "CANNOT_CONFIRM", "target_date": target_date,
                "cutoff": cutoff, "market": "HK_CONNECT", "failure_code": "MEMBERSHIP_GATE_BINDING_CHANGED",
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
    if codes[0] in members:
        return "IN", "HK_CONNECT_MEMBER_AT_TARGET_DATE"
    return "OUT", "NOT_IN_HK_CONNECT_UNIVERSE_AT_TARGET_DATE"


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
    keys = ("status", "target_date", "cutoff", "market", "owner", "authority_sha256",
            "authority_version", "effective_from", "effective_to", "available_at", "member_count",
            "failure_code")
    return {key: gate.get(key) for key in keys}
