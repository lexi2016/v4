"""A-only validations/decisions for the frozen MWB_V1_20261013 contract.

No read/write, clock, network, producer, legacy-manager or model invocation.
B owns the public types, persistence, execution identity and scheduling.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from zoneinfo import ZoneInfo

VERSION = "v4.manager_workbench.v1"
RULE = "POSITIVE_OPERATING_RESEARCH_V1"
US_FACTOR_RULES_VERSION = "POSITIVE_OPERATING_RESEARCH_V1_US_DAILY_RETURN_FACTOR_V1"
HK = ZoneInfo("Asia/Hong_Kong")
LANES = ("ANNOUNCEMENT", "US_MAPPING", "OVERSOLD", "STAGE_REFERENCE", "CLOSE_REFERENCE")
RESEARCH_LANES = LANES[:3]
STATES = frozenset(("NOT_RUN", "RUNNING", "READY", "READY_EMPTY", "PARTIAL", "INPUT_MISSING", "FAILED", "NOT_APPLICABLE"))
DECISIONS = frozenset(("SELECTED", "CONDITIONAL_WATCH", "UNASSESSED", "NOT_SELECTED", "OBSERVATION_ONLY"))
PHASES = frozenset(("PREOPEN", "INTRADAY", "NEXT_DAY", "RETROSPECTIVE", "MANUAL"))
SHA = re.compile(r"^[0-9a-f]{64}$")
SYMBOL = re.compile(r"^HK\.[0-9]{5}$")
DATE = re.compile(r"^[0-9]{8}$")


def digest(value):
    return sha256((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode()).hexdigest()


def plain(value):
    """Accept the B-owned Pydantic contract types without creating duplicates."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def bytes_digest(value):
    return sha256(value.encode("utf-8")).hexdigest()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("MWB_TIME_MISSING")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("MWB_TIME_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("MWB_TIME_ZONE_REQUIRED")
    return result


def current(context, value):
    try:
        return timestamp(value) <= timestamp(context["cutoff"])
    except (ValueError, KeyError, TypeError):
        return False


def validate_context(context):
    if not isinstance(context, dict) or context.get("market") != "HK_CONNECT":
        raise ValueError("MWB_MARKET")
    if context.get("phase") not in PHASES or context.get("trigger") not in ("SCHEDULED", "MANUAL"):
        raise ValueError("MWB_PHASE_TRIGGER")
    date = context.get("target_date")
    if not isinstance(date, str) or not DATE.fullmatch(date):
        raise ValueError("MWB_DATE")
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("MWB_DATE_INVALID") from exc
    timestamp(context.get("cutoff"))
    if not isinstance(context.get("source_sessions"), dict) or not isinstance(context.get("scope_refs"), dict):
        raise ValueError("MWB_SOURCE_CONTEXT_REQUIRED")
    if context.get("rules_version") not in (RULE, "POSITIVE_OPERATING_RESEARCH_V1_OVERSOLD_PRICE40_V2", US_FACTOR_RULES_VERSION):
        raise ValueError("MWB_RULE_VERSION")
    return context


def valid_sha(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def hk_symbol(value):
    return isinstance(value, str) and SYMBOL.fullmatch(value) is not None


def decimal(value):
    if isinstance(value, bool) or value is None or isinstance(value, float):
        raise ValueError("MWB_DECIMAL_UNTRUSTED")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("MWB_DECIMAL_INVALID") from None
    if not result.is_finite():
        raise ValueError("MWB_DECIMAL_NONFINITE")
    return result


def membership(record, context):
    """True, False, or None; a monthly identity must be effective on target day."""
    member = record.get("membership")
    if not isinstance(member, dict) or member.get("verification") != "VERIFIED":
        return None
    if not (valid_sha(member.get("sha256")) and member.get("owner") and
            isinstance(member.get("effective_from"), str) and isinstance(member.get("effective_through"), str)):
        return None
    date = context["target_date"]
    if not (DATE.fullmatch(member["effective_from"]) and DATE.fullmatch(member["effective_through"]) and
            member["effective_from"] <= date <= member["effective_through"] and
            current(context, member.get("available_at"))):
        return None
    if type(member.get("eligible")) is not bool:
        return None
    return member["eligible"]


def result(lane, batch, context, rows, *, state=None, gaps=None):
    """Preserve authoritative scope counts; never turn missing scope into zero."""
    gaps = list(batch.get("gaps") or []) + list(gaps or [])
    original = batch.get("coverage") or {}
    scope = original.get("scope_count")
    observed = original.get("observed_count")
    if type(scope) is not int or scope < 0:
        scope = None
    if type(observed) is not int or observed < 0:
        observed = None
    if scope is None or observed is None:
        gaps.append("AUTHORITY_COVERAGE_UNKNOWN")
    if observed is not None and observed != len(batch.get("records", [])):
        gaps.append("OBSERVED_COUNT_MISMATCH")
    if scope is not None and observed is not None and observed > scope:
        gaps.append("SCOPE_COUNT_MISMATCH")
    source_indices = {x.get("source_index") for x in rows if type(x.get("source_index")) is int}
    if source_indices:
        unknown_sources={x["source_index"] for x in rows if x.get("decision") in (None, "UNASSESSED")}
        assessed_sources={x["source_index"] for x in rows if x.get("decision") not in (None, "UNASSESSED")}
        assessed = len(assessed_sources - unknown_sources)
        unknown = len(unknown_sources)
    else:
        assessed = sum(x.get("decision") not in (None, "UNASSESSED") for x in rows)
        unknown = sum(x.get("decision") == "UNASSESSED" for x in rows)
    if (unknown and "RECORDS_UNASSESSED" not in gaps):
        gaps.append("RECORDS_UNASSESSED")
    if observed is None or scope is None or len(rows) < len(batch.get("records", [])):
        assessed_count = None
        unknown_count = None
        gaps.append("ROW_DISPOSITION_INCOMPLETE")
    else:
        assessed_count, unknown_count = assessed, unknown
    if state is None:
        state = "PARTIAL" if gaps else ("READY" if rows else "READY_EMPTY")
    if state not in STATES:
        raise ValueError("MWB_LANE_STATE")
    if state in ("READY", "READY_EMPTY") and gaps:
        state = "PARTIAL"
    return dict(lane=lane, state=state, rows=rows, coverage=dict(scope_count=scope,
        observed_count=observed, assessed_count=assessed_count, unassessed_count=unknown_count,
        gaps=gaps), input_sha256=batch.get("input_sha256"), rules_version=context["rules_version"],
        run_id=batch.get("run_id") or context.get("scope_refs",{}).get("run_id") or "A_RUN_ID_NOT_BOUND", evidence_refs=batch.get("evidence_refs", []), gaps=gaps)


def row(record, decision, reason, *, conditions=None, metrics=None, evidence=None, **extra):
    symbol = record.get("symbol")
    return dict(market="HK_CONNECT", symbol=symbol if hk_symbol(symbol) else None,
        name=record.get("name"), decision=decision, reason=reason,
        conditions=conditions or [], invalidation_conditions=record.get("invalidation_conditions") or [],
        risks=record.get("risks") or [], metrics=metrics or {},
        evidence_ids=evidence if evidence is not None else list(record.get("evidence_ids") or []),
        membership=record.get("membership"), available_at=record.get("available_at"), **extra)

