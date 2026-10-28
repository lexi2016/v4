"""Read-only exact-date adapter for manager workbench research discoveries.

B1 only defines the consumer contract.  It never runs a scanner, producer,
materializer, scheduler, quote fetch, or historical backfill.  B2 may later
publish validated artifacts below the existing manager research state root.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query


SCHEMA_VERSION = "v4.manager_workbench.research.v1"
MARKET = "HK_CONNECT"
SLOT = "1530"
RULE_VERSION = "manager-workbench-b1-contract-v1"
STATUSES = {
    "PENDING_SLOT",
    "NOT_RUN",
    "READY",
    "READY_EMPTY",
    "PARTIAL",
    "INPUT_MISSING",
    "STALE",
    "FAILED",
    "NOT_APPLICABLE",
}
SOURCE_LANES = {"STAGE", "CLOSE_DISCOVERY", "CONTINUOUS_TRACKING"}
FOUR_FLAGS = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
_DATE_RE = re.compile(r"^\d{8}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL_RE = re.compile(r"^HK\.\d{5}$")
_OFFSET_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_FORBIDDEN_KEYS = {"token", "password", "secret", "traceback", "stack", "stacktrace"}
_VISIBLE_STATUSES = frozenset({"READY", "PARTIAL", "STALE"})
_NON_DATA_STATUSES = frozenset({"PENDING_SLOT", "NOT_RUN", "INPUT_MISSING", "FAILED", "NOT_APPLICABLE"})
_CLOSE_RECAPTURE_SCHEMA = "v4.manager_close_recapture.v1"
_CLOSE_RECAPTURE_FLAGS = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
_MANUAL_HK_SECURITIES_EXECUTION = "MANUAL_HK_SECURITIES_SESSION_OBSERVATION"
_MANUAL_HK_SECURITIES_OBSERVATION = "HK_SECURITIES_SESSION_MINUTE_OBSERVATION"
_MANUAL_HK_SECURITIES_METADATA = {
    "execution_kind": _MANUAL_HK_SECURITIES_EXECUTION,
    "observation_type": _MANUAL_HK_SECURITIES_OBSERVATION,
    "observation_market": "HK_SECURITIES",
    "observation_market_state": "FULL_TRADING_DAY",
    "connect_market_state": "NON_TRADING_DAY",
    "official_close_status": "CANNOT_CONFIRM",
    "natural_run": False,
    "pool_eligibility_for_observation_market": "CANNOT_CONFIRM",
    **_CLOSE_RECAPTURE_FLAGS,
}
# B1 does not define B2 rules.  A producer may only mark a row qualified when
# every predicate it declares as required is present, versioned, and true.
QUALIFIED_PREDICATE_POLICY = "ALL_DECLARED_PREDICATES"
_SENSITIVE_TEXT_RE = re.compile(
    r"(?:Traceback \(most recent call last\)|Bearer\s+[A-Za-z0-9._~+/-]{8,}|"
    r"(?:api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*\S+|"
    r"sk-[A-Za-z0-9_-]{8,}|/Users/[^\s]+|/home/[^\s]+)",
    re.IGNORECASE,
)
_HK_TZ = ZoneInfo("Asia/Hong_Kong")


class WorkbenchResearchContractError(ValueError):
    pass


def _has_manual_hk_securities_markers(value: Mapping[str, Any]) -> bool:
    return (value.get("execution_kind") == _MANUAL_HK_SECURITIES_EXECUTION
            or value.get("observation_type") == _MANUAL_HK_SECURITIES_OBSERVATION
            or value.get("observation_market") == "HK_SECURITIES")


def _matches_manual_hk_securities_metadata(
    value: Mapping[str, Any], trade_date: str, target_trade_date: str | None = None,
) -> bool:
    for key, expected in _MANUAL_HK_SECURITIES_METADATA.items():
        actual = value.get(key)
        if isinstance(expected, bool):
            if actual is not expected:
                return False
        elif actual != expected:
            return False
    return (value.get("source_trade_date") == trade_date
            and (target_trade_date is None or value.get("target_trade_date") == target_trade_date))


def _strict_date(value: str | None) -> str:
    if value is None or _DATE_RE.fullmatch(value) is None:
        raise HTTPException(status_code=422, detail="date must use YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="date must be a real calendar date") from exc


def _now_hk() -> datetime:
    return datetime.now(_HK_TZ)


def _safe_text(value: str, field: str) -> str:
    stripped = value.strip()
    if _SENSITIVE_TEXT_RE.search(stripped):
        raise WorkbenchResearchContractError(f"{field} contains forbidden diagnostic or credential material")
    return stripped


def _safe_ref(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise WorkbenchResearchContractError(f"{field} must be a string or null")
    stripped = _safe_text(value, field)
    if not stripped:
        return None
    if stripped.startswith(('/', './', '../')) or re.match(r"^[A-Za-z]:[\\/]", stripped):
        raise WorkbenchResearchContractError(f"{field} must not expose a local path")
    return stripped


def _timestamp(value: Any, field: str, *, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise WorkbenchResearchContractError(f"{field} is required")
        return None
    if not isinstance(value, str) or _OFFSET_TIME_RE.fullmatch(value.strip()) is None:
        raise WorkbenchResearchContractError(f"{field} must be offset-aware ISO-8601")
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkbenchResearchContractError(f"{field} is invalid") from exc
    return value.strip()


def _utc_instant(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkbenchResearchContractError(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise WorkbenchResearchContractError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _not_after(value: str | None, as_of: str | None, field: str) -> None:
    if value is None or as_of is None:
        return
    if _utc_instant(value, field) > _utc_instant(as_of, "as_of"):
        raise WorkbenchResearchContractError(f"{field} must be <= as_of")


def _finite_number(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise WorkbenchResearchContractError(f"{field} must be a finite number")


def _turnover_amount(value: Any, field: str, *, as_of: str | None) -> dict[str, Any] | None:
    """Validate the small PIT contract for a supplied turnover observation.

    B1 does not define a turnover threshold.  It only accepts a value when its
    unit and observation timestamp are explicit, and bounds that timestamp by
    the exact response envelope.  Missing definitions fail closed.
    """

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise WorkbenchResearchContractError(f"{field} must be an object or null")
    if "as_of" not in value:
        raise WorkbenchResearchContractError(f"{field}.as_of is required")
    nested_as_of = _timestamp(value.get("as_of"), f"{field}.as_of", required=True)
    _not_after(nested_as_of, as_of, f"{field}.as_of")
    currency = _safe_ref(value.get("currency"), f"{field}.currency")
    if not currency:
        raise WorkbenchResearchContractError(f"{field}.currency is required")
    unit = _safe_ref(value.get("unit"), f"{field}.unit")
    if not unit:
        raise WorkbenchResearchContractError(f"{field}.unit is required")
    if "value" not in value:
        raise WorkbenchResearchContractError(f"{field}.value is required")
    amount = value.get("value")
    if amount is not None:
        _finite_number(amount, f"{field}.value")
    return dict(value)


def _volume_comparison(value: Any, field: str, *, as_of: str | None) -> dict[str, Any] | None:
    """Validate explicit volume-baseline metadata without defining B2 rules."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise WorkbenchResearchContractError(f"{field} must be an object or null")
    if "baseline_as_of" not in value:
        raise WorkbenchResearchContractError(f"{field}.baseline_as_of is required")
    state = _safe_ref(value.get("state"), f"{field}.state")
    if not state:
        raise WorkbenchResearchContractError(f"{field}.state is required")
    baseline_as_of = _timestamp(value.get("baseline_as_of"), f"{field}.baseline_as_of")
    _not_after(baseline_as_of, as_of, f"{field}.baseline_as_of")
    if "ratio" not in value:
        raise WorkbenchResearchContractError(f"{field}.ratio is required")
    ratio = value.get("ratio")
    if ratio is not None:
        _finite_number(ratio, f"{field}.ratio")
    # An absent baseline is an explicit unknown state.  A defined comparison
    # without a PIT baseline cannot be projected as exact-date evidence.
    if baseline_as_of is None and (state != "unknown" or ratio is not None):
        raise WorkbenchResearchContractError(
            f"{field}.baseline_as_of is required for a defined comparison"
        )
    return dict(value)


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WorkbenchResearchContractError(f"{field} must be a string array")
    rows: list[str] = []
    for index, item in enumerate(value):
        safe = _safe_text(item, f"{field}[{index}]")
        if safe:
            rows.append(safe)
    return rows


def _nonnegative_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorkbenchResearchContractError(f"{field} must be a non-negative integer or null")
    return value


def _safe_tree(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise WorkbenchResearchContractError(f"{path} keys must be strings")
            normalized = key.lower().replace("_", "").replace("-", "")
            if normalized in _FORBIDDEN_KEYS or any(term in normalized for term in ("accesstoken", "authtoken", "apikey")):
                raise WorkbenchResearchContractError(f"{path}.{key} is forbidden")
            _safe_tree(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _safe_tree(item, f"{path}[{index}]")
        return
    if isinstance(value, str):
        _safe_text(value, path)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise WorkbenchResearchContractError(f"{path} is not JSON-safe")


def _source(value: Any, field: str, *, as_of: str | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkbenchResearchContractError(f"{field} must be an object")
    market = value.get("market")
    if market != MARKET:
        raise WorkbenchResearchContractError(f"{field}.market must be {MARKET}")
    sha = value.get("sha256")
    if sha is not None and (not isinstance(sha, str) or _SHA_RE.fullmatch(sha.lower()) is None):
        raise WorkbenchResearchContractError(f"{field}.sha256 is invalid")
    lane = _safe_ref(value.get("lane"), f"{field}.lane")
    if lane is not None and lane not in SOURCE_LANES:
        raise WorkbenchResearchContractError(f"{field}.lane is invalid")
    source_date = _safe_ref(value.get("source_date"), f"{field}.source_date")
    if source_date is not None:
        if _DATE_RE.fullmatch(source_date) is None:
            raise WorkbenchResearchContractError(f"{field}.source_date must use YYYYMMDD")
        try:
            datetime.strptime(source_date, "%Y%m%d")
        except ValueError as exc:
            raise WorkbenchResearchContractError(f"{field}.source_date is invalid") from exc
    observed_at = _timestamp(value.get("observed_at"), f"{field}.observed_at")
    available_at = _timestamp(value.get("available_at"), f"{field}.available_at")
    _not_after(observed_at, as_of, f"{field}.observed_at")
    _not_after(available_at, as_of, f"{field}.available_at")
    return {
        "owner": _safe_ref(value.get("owner"), f"{field}.owner"),
        "role": _safe_ref(value.get("role"), f"{field}.role"),
        "artifact_ref": _safe_ref(value.get("artifact_ref"), f"{field}.artifact_ref"),
        "manifest_ref": _safe_ref(value.get("manifest_ref"), f"{field}.manifest_ref"),
        "receipt_ref": _safe_ref(value.get("receipt_ref"), f"{field}.receipt_ref"),
        "run_id": _safe_ref(value.get("run_id"), f"{field}.run_id"),
        "sha256": sha.lower() if isinstance(sha, str) else None,
        "source_date": source_date,
        "market": MARKET,
        "lane": lane,
        "reason": _safe_ref(value.get("reason"), f"{field}.reason"),
        "observed_at": observed_at,
        "available_at": available_at,
    }


def _predicate(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkbenchResearchContractError(f"{field} must be an object")
    state = value.get("value")
    if not (state is True or state is False or state == "unknown"):
        raise WorkbenchResearchContractError(f"{field}.value must be true, false, or unknown")
    return {
        "predicate_id": _safe_ref(value.get("predicate_id"), f"{field}.predicate_id"),
        "value": state,
        "reason": _safe_ref(value.get("reason"), f"{field}.reason"),
        "input_refs": _strings(value.get("input_refs", []), f"{field}.input_refs"),
        "rule_version": _safe_ref(value.get("rule_version"), f"{field}.rule_version"),
    }


def _candidate(
    value: Any,
    index: int,
    trade_date: str,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    field = f"candidates[{index}]"
    if not isinstance(value, Mapping):
        raise WorkbenchResearchContractError(f"{field} must be an object")
    symbol = value.get("symbol")
    if not isinstance(symbol, str) or _SYMBOL_RE.fullmatch(symbol) is None:
        raise WorkbenchResearchContractError(f"{field}.symbol must be normalized HK.#####")
    candidate_id = value.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise WorkbenchResearchContractError(f"{field}.candidate_id is required")
    source_lanes = _strings(value.get("source_lanes"), f"{field}.source_lanes")
    if not source_lanes:
        raise WorkbenchResearchContractError(f"{field}.source_lanes must not be empty")
    if len(set(source_lanes)) != len(source_lanes) or any(lane not in SOURCE_LANES for lane in source_lanes):
        raise WorkbenchResearchContractError(f"{field}.source_lanes contains an invalid or duplicate lane")
    turnover = _turnover_amount(value.get("turnover_amount"), f"{field}.turnover_amount", as_of=as_of)
    volume_comparison = _volume_comparison(
        value.get("volume_comparison"), f"{field}.volume_comparison", as_of=as_of
    )
    predicates_raw = value.get("predicates", [])
    if not isinstance(predicates_raw, list):
        raise WorkbenchResearchContractError(f"{field}.predicates must be an array")
    predicates = [_predicate(item, f"{field}.predicates[{i}]") for i, item in enumerate(predicates_raw)]
    sources_raw = value.get("sources", [])
    if not isinstance(sources_raw, list):
        raise WorkbenchResearchContractError(f"{field}.sources must be an array")
    sources = [_source(item, f"{field}.sources[{i}]", as_of=as_of) for i, item in enumerate(sources_raw)]
    source_lane_values = {source["lane"] for source in sources if source["lane"] is not None}
    if not source_lane_values.issubset(set(source_lanes)):
        raise WorkbenchResearchContractError(f"{field}.sources contains a lane absent from source_lanes")
    qualified = value.get("qualified")
    if not (qualified is True or qualified is False or qualified is None):
        raise WorkbenchResearchContractError(f"{field}.qualified must be true, false, or null")
    timestamps = {
        timestamp_field: _timestamp(value.get(timestamp_field), f"{field}.{timestamp_field}", required=True)
        for timestamp_field in ("first_seen_at", "last_seen_at", "observed_at", "available_at")
    }
    for timestamp_field, timestamp_value in timestamps.items():
        _not_after(timestamp_value, as_of, f"{field}.{timestamp_field}")
    if QUALIFIED_PREDICATE_POLICY == "ALL_DECLARED_PREDICATES" and qualified is True:
        if not predicates:
            raise WorkbenchResearchContractError(
                f"{field}.qualified=true requires an explicit required predicate set"
            )
        if any(
            predicate["value"] is not True
            or not isinstance(predicate["predicate_id"], str)
            or not predicate["predicate_id"].strip()
            or not isinstance(predicate["rule_version"], str)
            or not predicate["rule_version"].strip()
            for predicate in predicates
        ):
            raise WorkbenchResearchContractError(
                f"{field}.qualified=true requires every declared required predicate=true"
            )
    return {
        "candidate_id": candidate_id.strip(),
        "symbol": symbol,
        "name": _safe_ref(value.get("name"), f"{field}.name") or symbol,
        "source_lanes": source_lanes,
        "first_seen_at": timestamps["first_seen_at"],
        "last_seen_at": timestamps["last_seen_at"],
        "observed_at": timestamps["observed_at"],
        "available_at": timestamps["available_at"],
        "turnover_amount": turnover,
        "volume_comparison": volume_comparison,
        "position": dict(value.get("position")) if isinstance(value.get("position"), Mapping) else None,
        "catalyst": dict(value.get("catalyst")) if isinstance(value.get("catalyst"), Mapping) else None,
        "research_priority": dict(value.get("research_priority")) if isinstance(value.get("research_priority"), Mapping) else None,
        "data_status": _safe_ref(value.get("data_status"), f"{field}.data_status") or "CANNOT_CONFIRM",
        "attention_reason": _safe_ref(value.get("attention_reason"), f"{field}.attention_reason"),
        "predicates": predicates,
        "sources": sources,
        "risks": list(value.get("risks")) if isinstance(value.get("risks"), list) else [],
        "observation_plan": dict(value.get("observation_plan")) if isinstance(value.get("observation_plan"), Mapping) else None,
        "qualified": qualified,
        "trade_date": trade_date,
    }


def _summary_item(value: Any, field: str, *, as_of: str | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkbenchResearchContractError(f"{field} must be an object")
    occurred_at = _timestamp(value.get("occurred_at"), f"{field}.occurred_at", required=True)
    _not_after(occurred_at, as_of, f"{field}.occurred_at")
    return {
        "item_id": _safe_ref(value.get("item_id"), f"{field}.item_id"),
        "candidate_id": _safe_ref(value.get("candidate_id"), f"{field}.candidate_id"),
        "name": _safe_ref(value.get("name"), f"{field}.name") or "CANNOT_CONFIRM",
        "occurred_at": occurred_at,
        "reason": _safe_ref(value.get("reason"), f"{field}.reason") or "CANNOT_CONFIRM",
        "evidence_status": _safe_ref(value.get("evidence_status"), f"{field}.evidence_status") or "CANNOT_CONFIRM",
        "kind": _safe_ref(value.get("kind"), f"{field}.kind"),
    }


def _require_lineage(source: dict[str, Any], field: str, *, require_lane: bool) -> None:
    if require_lane and not isinstance(source.get("lane"), str):
        raise WorkbenchResearchContractError(f"{field}.lane is required for visible candidates")
    for key in ("owner", "role", "run_id", "source_date", "sha256"):
        value = source.get(key)
        if not isinstance(value, str) or not value.strip():
            raise WorkbenchResearchContractError(f"{field}.{key} is required for visible data")
    if _SHA_RE.fullmatch(str(source["sha256"]).lower()) is None:
        raise WorkbenchResearchContractError(f"{field}.sha256 is invalid for visible data")
    if _DATE_RE.fullmatch(str(source["source_date"])) is None:
        raise WorkbenchResearchContractError(f"{field}.source_date is required for visible data")
    if not any(
        isinstance(source.get(key), str) and str(source[key]).strip()
        for key in ("artifact_ref", "manifest_ref", "receipt_ref")
    ):
        raise WorkbenchResearchContractError(
            f"{field} requires an artifact, manifest, or receipt reference for visible data"
        )


def _require_visible_lineage(
    *,
    run_id: str | None,
    universe: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
) -> None:
    if not isinstance(run_id, str) or not run_id.strip():
        raise WorkbenchResearchContractError("run_id is required for visible data")
    if universe is None:
        raise WorkbenchResearchContractError("universe lineage is required for visible data")
    _require_lineage(universe, "universe", require_lane=False)
    for candidate_index, candidate in enumerate(candidates):
        sources = candidate["sources"]
        for source_index, source in enumerate(sources):
            _require_lineage(
                source,
                f"candidates[{candidate_index}].sources[{source_index}]",
                require_lane=True,
            )
        for lane in candidate["source_lanes"]:
            if not any(source.get("lane") == lane for source in sources):
                raise WorkbenchResearchContractError(
                    f"candidates[{candidate_index}] is missing lineage for source lane {lane}"
                )


def _validate_r2_evidence_contract(candidates: list[dict[str, Any]], as_of: str | None,
                                   generated_at: str | None, expected_date: str, *,
                                   state_root: Path | None = None,
                                   verify_published_sources: bool = False) -> None:
    from domains.manager_close_discovery import REQUIRED_PREDICATES, RULE_VERSION as R2_RULE
    if as_of is None or generated_at is None:
        raise WorkbenchResearchContractError("R2 requires observed and generated time")
    observed=_utc_instant(as_of,"as_of").astimezone(_HK_TZ)
    if (observed.strftime("%Y%m%d")!=expected_date or not (15,30)<=(observed.hour,observed.minute)<(15,32)
        or _utc_instant(generated_at,"generated_at")<_utc_instant(as_of,"as_of")):
        raise WorkbenchResearchContractError("R2 exact observation window is invalid")
    for candidate in candidates:
        predicates=candidate["predicates"]
        if (tuple(p["predicate_id"] for p in predicates)!=REQUIRED_PREDICATES
            or any(p["rule_version"]!=R2_RULE for p in predicates)):
            raise WorkbenchResearchContractError("R2 requires the complete version-bound four-leg conjunction")
        # Closed admission, not generic self-reported rule/source strings.
        # Enabling these two legs requires an actual authority adapter AND a
        # separately approved rule; neither is present in the supplied baseline.
        if any(p["value"]!="unknown" for p in predicates[1:3]):
            raise WorkbenchResearchContractError("R2 volume/position authority is not implemented")
        # Additive diagnostic contract only. Existing R2 artifacts without the
        # field remain valid; no authority or positive predicate is introduced.
        from domains.manager_condition_evidence import validate_condition_projection
        for field,kind in (("volume_comparison","volume"),("position","price")):
            diagnostic=candidate.get(field) or {}
            if "evidence_audit" in diagnostic:
                try:
                    validate_condition_projection(diagnostic["evidence_audit"],kind=kind,
                        symbol=candidate["symbol"],as_of=observed,sources=candidate["sources"],
                        state_root=state_root,
                        verify_published_sources=verify_published_sources)
                except (ValueError,TypeError,KeyError,OverflowError) as exc:
                    raise WorkbenchResearchContractError("R2 condition diagnostic is invalid") from exc
        expected=False if any(p["value"] is False for p in predicates) else None
        if candidate["qualified"] is not expected:
            raise WorkbenchResearchContractError("R2 qualified value contradicts verified conditions")
        if predicates[0]["value"] != "unknown":
            amount=candidate["turnover_amount"] or {}
            if (amount.get("currency")!="HKD" or amount.get("unit")!="HKD"
                or amount.get("contract_state")!="VERIFIED_HKD" or amount.get("status")!="OBSERVED"
                or not isinstance(amount.get("value"),(int,float))
                or predicates[0]["value"] is not (amount["value"]>100_000_000)):
                raise WorkbenchResearchContractError("R2 turnover predicate is not backed by the explicit HKD value")
        if predicates[3]["value"] is True:
            catalyst=candidate["catalyst"] or {}
            if catalyst.get("status")!="CONFIRMED_PIT" or not catalyst.get("evidence"):
                raise WorkbenchResearchContractError("R2 direct catalyst evidence is missing")
            for evidence in catalyst["evidence"]:
                for field in ("published_at","first_seen_at","available_at"):
                    stamp=_timestamp(evidence.get(field),"catalyst."+field,required=True)
                    _not_after(stamp,as_of,"catalyst."+field)
                if _utc_instant(evidence["first_seen_at"],"first_seen_at").astimezone(_HK_TZ).strftime("%Y%m%d")!=expected_date:
                    raise WorkbenchResearchContractError("R2 catalyst is not new for this session")
                if not _SHA_RE.fullmatch(str(evidence.get("publication_sha256",""))):
                    raise WorkbenchResearchContractError("R2 catalyst publication hash is missing")
        for source in candidate["sources"]:
            if any(not source.get(key) for key in ("source_date","run_id","sha256","reason","observed_at","available_at")):
                raise WorkbenchResearchContractError("R2 source lineage is incomplete")


def validate_workbench_payload(value: Any, *, expected_date: str, state_root: Path | str | None = None,
                               verify_published_sources: bool = False,
                               rebound_authority_root: Path | str | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkbenchResearchContractError("payload must be an object")
    _safe_tree(value)
    if value.get("schema_version") != SCHEMA_VERSION:
        raise WorkbenchResearchContractError("schema_version is invalid")
    if value.get("market") != MARKET:
        raise WorkbenchResearchContractError("market is invalid")
    if value.get("trade_date") != expected_date:
        raise WorkbenchResearchContractError("trade_date does not match exact request")
    if value.get("slot") != SLOT:
        raise WorkbenchResearchContractError("slot is invalid")
    status = value.get("status")
    if status not in STATUSES:
        raise WorkbenchResearchContractError("status is invalid")
    for key, expected in FOUR_FLAGS.items():
        if value.get(key) is not expected:
            raise WorkbenchResearchContractError(f"{key} has an invalid safety value")
    cannot_confirm = _strings(value.get("cannot_confirm", []), "cannot_confirm")
    rule_version = _safe_ref(value.get("rule_version"), "rule_version")
    if not rule_version:
        raise WorkbenchResearchContractError("rule_version is required")
    cache_key = value.get("cache_key")
    expected_key = f"{expected_date}|{MARKET}|{SLOT}|{rule_version}"
    if cache_key != expected_key:
        raise WorkbenchResearchContractError("cache_key is invalid")
    as_of = _timestamp(value.get("as_of"), "as_of", required=status in {"READY", "READY_EMPTY", "PARTIAL", "STALE"})
    generated_at = _timestamp(value.get("generated_at"), "generated_at", required=status in {"READY", "READY_EMPTY", "PARTIAL", "STALE"})
    run_id = _safe_ref(value.get("run_id"), "run_id")
    coverage_raw = value.get("coverage", {})
    if not isinstance(coverage_raw, Mapping):
        raise WorkbenchResearchContractError("coverage must be an object")
    coverage = {
        "eligible_count": _nonnegative_int(coverage_raw.get("eligible_count"), "coverage.eligible_count"),
        "covered_count": _nonnegative_int(coverage_raw.get("covered_count"), "coverage.covered_count"),
        "missing_count": _nonnegative_int(coverage_raw.get("missing_count"), "coverage.missing_count"),
        "missing_reasons": _strings(coverage_raw.get("missing_reasons", []), "coverage.missing_reasons"),
    }
    if coverage["eligible_count"] is not None and coverage["covered_count"] is not None:
        if coverage["covered_count"] > coverage["eligible_count"]:
            raise WorkbenchResearchContractError("coverage.covered_count exceeds eligible_count")
    candidates_raw = value.get("candidates", [])
    if not isinstance(candidates_raw, list):
        raise WorkbenchResearchContractError("candidates must be an array")
    candidates = [_candidate(item, index, expected_date, as_of=as_of) for index, item in enumerate(candidates_raw)]
    identities = [(item["symbol"], item["candidate_id"]) for item in candidates]
    if len({symbol for symbol, _ in identities}) != len(identities):
        raise WorkbenchResearchContractError("candidate symbols must be unique after source merge")
    if len({candidate_id for _, candidate_id in identities}) != len(identities):
        raise WorkbenchResearchContractError("candidate_id must be unique after source merge")
    if status == "READY_EMPTY" and candidates:
        raise WorkbenchResearchContractError("READY_EMPTY cannot contain candidates")
    if status == "READY" and not candidates:
        raise WorkbenchResearchContractError("READY must contain candidates")
    summary_raw = value.get("priority_summary", {})
    if not isinstance(summary_raw, Mapping):
        raise WorkbenchResearchContractError("priority_summary must be an object")
    priority_summary: dict[str, list[dict[str, Any]]] = {}
    for key in ("focus", "theme_changes", "risk_upgrades"):
        raw = summary_raw.get(key, [])
        if not isinstance(raw, list):
            raise WorkbenchResearchContractError(f"priority_summary.{key} must be an array")
        priority_summary[key] = [
            _summary_item(item, f"priority_summary.{key}[{i}]", as_of=as_of)
            for i, item in enumerate(raw)
        ]
    universe_raw = value.get("universe")
    universe = _source(universe_raw, "universe", as_of=as_of) if universe_raw is not None else None
    if status in _NON_DATA_STATUSES and (candidates or any(priority_summary.values())):
        raise WorkbenchResearchContractError(f"{status} must not carry candidates or priority summary")
    if rule_version == "manager-close-rework-r2-v1" and status in {"READY", "READY_EMPTY", "PARTIAL", "STALE"}:
        _validate_r2_evidence_contract(
            candidates, as_of, generated_at, expected_date,
            state_root=Path(state_root).expanduser() if state_root is not None else None,
            verify_published_sources=verify_published_sources,
        )
        if (coverage["eligible_count"] is None or coverage["covered_count"] is None or coverage["missing_count"] is None
            or coverage["covered_count"]+coverage["missing_count"]!=coverage["eligible_count"]):
            raise WorkbenchResearchContractError("R2 coverage counts do not reconcile")
    if status in _VISIBLE_STATUSES:
        _require_visible_lineage(run_id=run_id, universe=universe, candidates=candidates)
    diagnostic = {}
    if rule_version == '20260921_REBOUND_V3_1530_OBSERVATION_V1':
        from domains.manager_close_rebound import validate_projection
        try:
            diagnostic['rebound_screen'] = validate_projection(value,
                state_root=Path(state_root) if state_root is not None else None,
                verify_sources=verify_published_sources,
                root=Path(rebound_authority_root) if rebound_authority_root is not None else None)
        except (ValueError, TypeError, KeyError, OSError, ImportError, RuntimeError) as exc:
            raise WorkbenchResearchContractError('V3 rebound input, phase or derivation is invalid') from exc
    if 'failure_diagnostic' in value:
        from infrastructure.manager_close_attempt import validate_failure_diagnostic
        try:
            checked = validate_failure_diagnostic(value['failure_diagnostic'])
        except ValueError as exc:
            raise WorkbenchResearchContractError('failure diagnostic is invalid') from exc
        if status not in _NON_DATA_STATUSES or checked['code'] not in cannot_confirm:
            raise WorkbenchResearchContractError('failure diagnostic contradicts status')
        diagnostic['failure_diagnostic'] = checked
    return {
        "schema_version": SCHEMA_VERSION,
        "market": MARKET,
        "trade_date": expected_date,
        "slot": SLOT,
        "as_of": as_of,
        "generated_at": generated_at,
        "run_id": run_id,
        "status": status,
        "rule_version": rule_version,
        "cache_key": expected_key,
        "universe": universe,
        "coverage": coverage,
        "cannot_confirm": cannot_confirm,
        "priority_summary": priority_summary,
        "candidates": candidates,
        **diagnostic,
        **FOUR_FLAGS,
    }


def _empty_envelope(trade_date: str, status: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "market": MARKET,
        "trade_date": trade_date,
        "slot": SLOT,
        "as_of": None,
        "generated_at": None,
        "run_id": None,
        "status": status,
        "rule_version": RULE_VERSION,
        "cache_key": f"{trade_date}|{MARKET}|{SLOT}|{RULE_VERSION}",
        "universe": None,
        "coverage": {
            "eligible_count": None,
            "covered_count": None,
            "missing_count": None,
            "missing_reasons": [reason],
        },
        "cannot_confirm": [reason],
        "priority_summary": {"focus": [], "theme_changes": [], "risk_upgrades": []},
        "candidates": [],
        **FOUR_FLAGS,
    }


class ManagerWorkbenchResearchReader:
    """Reads one exact B1/B2 artifact below the existing manager state root."""

    def __init__(self, state_root: Path | str, *, rebound_authority_root: Path | str | None = None):
        self.state_root = Path(state_root).expanduser()
        self.rebound_authority_root = rebound_authority_root
        self.artifact_root = self.state_root / "workbench_research"

    def _path(self, trade_date: str) -> Path:
        return self.artifact_root / trade_date / f"{SLOT}.json"

    def _close_recapture_empty(self, trade_date: str, status: str, reason: str) -> dict[str, Any]:
        return {"schema_version": _CLOSE_RECAPTURE_SCHEMA, "status": status,
                "source_trade_date": trade_date, "target_trade_date": None, "plan_trade_date": None,
                "capture_mode": "LATE_OBSERVATION",
                "observation_type": "PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION",
                "candidate_overlay": {"count": 0, "rows": []},
                "cannot_confirm": [reason], **_CLOSE_RECAPTURE_FLAGS}

    def _requested_day_observation_empty(self, trade_date: str, status: str, reason: str) -> dict[str, Any]:
        return {"schema_version": _CLOSE_RECAPTURE_SCHEMA, "status": status,
                "source_trade_date": None, "requested_trade_date": trade_date,
                "target_trade_date": None, "plan_trade_date": None,
                "market": MARKET, "capture_mode": "LATE_OBSERVATION",
                "execution_kind": _MANUAL_HK_SECURITIES_EXECUTION,
                "observation_type": _MANUAL_HK_SECURITIES_OBSERVATION,
                "observation_market": "HK_SECURITIES", "observation_market_state": "UNKNOWN",
                "connect_market_state": "UNKNOWN", "official_close_status": "CANNOT_CONFIRM",
                "pool_eligibility_for_observation_market": "CANNOT_CONFIRM",
                "candidate_overlay": {"count": 0, "rows": []},
                "planner_availability": "DISPLAY_ONLY_NOT_PLANNER_INPUT",
                "planner_eligible_context": False,
                "formal_recommendation_effect": "NONE", "buy_gate_effect": "NONE",
                "cannot_confirm": [reason], **_CLOSE_RECAPTURE_FLAGS}

    def read_close_recapture(self, trade_date: str) -> dict[str, Any]:
        """Read the planner's exact-date PyTDX minute artifact; never reads or writes 1530."""
        return self._read_close_recapture(trade_date, manual_hk_observation=False)

    def read_requested_day_hk_observation(self, trade_date: str) -> dict[str, Any]:
        """Read a verified manual HK-securities observation for request-day display only."""
        return self._read_close_recapture(trade_date, manual_hk_observation=True)

    def _read_close_recapture(self, trade_date: str, *, manual_hk_observation: bool) -> dict[str, Any]:
        """Read one explicit late observation contract without changing planner defaults."""
        empty = (self._requested_day_observation_empty if manual_hk_observation
                 else self._close_recapture_empty)
        if _DATE_RE.fullmatch(str(trade_date)) is None:
            return empty(str(trade_date), "FAILED", "CLOSE_RECAPTURE_DATE_INVALID")
        directory = self.artifact_root / trade_date
        path = directory / "close_recapture.json"
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            if manual_hk_observation:
                return empty(trade_date, "NOT_RUN", "REQUESTED_DAY_HK_OBSERVATION_NOT_MATERIALIZED")
            status_path = directory / "close_recapture.status.json"
            try:
                status_raw = status_path.read_bytes()
            except FileNotFoundError:
                return empty(trade_date, "NOT_RUN", "CLOSE_RECAPTURE_NOT_MATERIALIZED")
            except OSError:
                return empty(trade_date, "FAILED", "CLOSE_RECAPTURE_STATUS_READ_FAILED")
            try:
                status_value = json.loads(status_raw.decode("utf-8"))
                if (not isinstance(status_value, dict) or status_value.get("schema_version") != _CLOSE_RECAPTURE_SCHEMA
                        or status_value.get("source_trade_date") != trade_date
                        or status_value.get("status") != "FAILED"
                        or any(status_value.get(key) is not value for key, value in _CLOSE_RECAPTURE_FLAGS.items())):
                    raise ValueError("status contract")
                return status_value
            except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
                return empty(trade_date, "FAILED", "CLOSE_RECAPTURE_STATUS_INVALID")
        except OSError:
            return empty(trade_date, "FAILED", "CLOSE_RECAPTURE_ARTIFACT_READ_FAILED")
        try:
            from infrastructure.manager_input_attestation import digest, load, resolve
            value = json.loads(raw.decode("utf-8"))
            if (not isinstance(value, dict) or value.get("schema_version") != _CLOSE_RECAPTURE_SCHEMA
                    or value.get("status") not in {"READY", "PARTIAL"}
                    or value.get("source_trade_date") != trade_date
                    or value.get("target_trade_date") != value.get("plan_trade_date")
                    or _DATE_RE.fullmatch(str(value.get("plan_trade_date") or "")) is None
                    or value.get("plan_trade_date") <= trade_date
                    or value.get("market") != MARKET
                    or value.get("capture_mode") != "LATE_OBSERVATION"
                    or value.get("observation_type") != (_MANUAL_HK_SECURITIES_OBSERVATION if manual_hk_observation
                                                          else "PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION")
                    or value.get("received_not_historical_1530") is not True
                    or any(value.get(key) is not expected for key, expected in _CLOSE_RECAPTURE_FLAGS.items())):
                raise WorkbenchResearchContractError("close recapture envelope invalid")
            if manual_hk_observation:
                if (value.get("status") != "READY"
                        or not _matches_manual_hk_securities_metadata(value, trade_date, value.get("plan_trade_date"))):
                    raise WorkbenchResearchContractError("requested-day HK securities observation labels invalid")
            elif _has_manual_hk_securities_markers(value):
                raise WorkbenchResearchContractError("manual HK securities observation requires display-only reader")
            request = value.get("request")
            pool = value.get("pool")
            source = value.get("source")
            window = value.get("bar_window")
            coverage = value.get("coverage")
            snapshot = value.get("snapshot")
            overlay_ref = value.get("candidate_overlay")
            if (not isinstance(request, Mapping) or not isinstance(pool, Mapping) or not isinstance(source, Mapping)
                    or not isinstance(window, Mapping) or not isinstance(coverage, Mapping)
                    or not isinstance(snapshot, Mapping) or not isinstance(overlay_ref, Mapping)):
                raise WorkbenchResearchContractError("close recapture evidence fields invalid")
            for field in ("started_at", "captured_at", "available_at"):
                _timestamp(request.get(field), "request." + field, required=True)
            if (_utc_instant(request["started_at"], "request.started_at")
                    > _utc_instant(request["captured_at"], "request.captured_at")
                    or _utc_instant(request["captured_at"], "request.captured_at")
                    > _utc_instant(request["available_at"], "request.available_at")):
                raise WorkbenchResearchContractError("close recapture timestamp order invalid")
            if (source.get("provider") != "pytdx_exhq" or source.get("source_id") != "pytdx"
                    or window.get("stage_id") != "STAGE_1545_1555"
                    or window.get("start_at") != "15:46:00" or window.get("end_before") != "15:55:05"):
                raise WorkbenchResearchContractError("close recapture source window invalid")
            for field in ("observed_at_min", "observed_at_max"):
                _timestamp(window.get(field), "bar_window." + field, required=True)
            if (_utc_instant(window["observed_at_min"], "bar_window.observed_at_min")
                    > _utc_instant(window["observed_at_max"], "bar_window.observed_at_max")
                    or _utc_instant(window["observed_at_max"], "bar_window.observed_at_max")
                    > _utc_instant(request["captured_at"], "request.captured_at")):
                raise WorkbenchResearchContractError("close recapture observed time invalid")
            if (pool.get("owner") != "v3_shared_data" or pool.get("role") != "HK_CONNECT_D1_TOP100_0_2"
                    or pool.get("trade_date") != trade_date or pool.get("row_count") != 100
                    or not _SHA_RE.fullmatch(str(pool.get("artifact_sha256") or ""))
                    or not _SHA_RE.fullmatch(str(pool.get("manifest_sha256") or ""))
                    or not _SHA_RE.fullmatch(str(pool.get("receipt_sha256") or ""))
                    or not isinstance(pool.get("run_id"), str) or not pool["run_id"]):
                raise WorkbenchResearchContractError("close recapture pool binding invalid")
            if (coverage.get("eligible_count") != 100 or type(coverage.get("requested_count")) is not int
                    or type(coverage.get("completed_count")) is not int
                    or type(coverage.get("observed_count")) is not int
                    or type(coverage.get("no_data_count")) is not int
                    or not isinstance(coverage.get("ratio"), (int, float))
                    or not math.isfinite(float(coverage["ratio"]))):
                raise WorkbenchResearchContractError("close recapture coverage invalid")
            if manual_hk_observation and (
                    coverage.get("requested_count") != 100 or coverage.get("completed_count") != 100
                    or coverage.get("observed_count") != 100 or coverage.get("no_data_count") != 0
                    or coverage.get("no_data_symbols") != [] or float(coverage.get("ratio")) != 1.0):
                raise WorkbenchResearchContractError("requested-day HK observation coverage is incomplete")
            expected_snapshot = f"workbench_research/{trade_date}/inputs/close_recapture_pytdx.json"
            expected_overlay = f"workbench_research/{trade_date}/close_recapture.candidates.json"
            if (snapshot.get("artifact_ref") != expected_snapshot or overlay_ref.get("artifact_ref") != expected_overlay
                    or not _SHA_RE.fullmatch(str(snapshot.get("sha256") or ""))
                    or not _SHA_RE.fullmatch(str(overlay_ref.get("sha256") or ""))
                    or type(snapshot.get("row_count")) is not int or type(overlay_ref.get("count")) is not int):
                raise WorkbenchResearchContractError("close recapture artifact refs invalid")
            snapshot_path = resolve(self.state_root, expected_snapshot)
            overlay_path = resolve(self.state_root, expected_overlay)
            snapshot_raw = snapshot_path.read_bytes()
            overlay_raw = overlay_path.read_bytes()
            if (digest(snapshot_raw) != snapshot["sha256"] or digest(overlay_raw) != overlay_ref["sha256"]
                    or json.loads(snapshot_raw.decode("utf-8")).get("pool") != dict(pool)):
                raise WorkbenchResearchContractError("close recapture source bytes mismatch")
            snapshot_value = load(snapshot_path)
            overlay = load(overlay_path)
            rows = overlay.get("rows")
            if (snapshot_value.get("schema_version") != "v4.manager_close_recapture_pytdx_snapshot.v1"
                    or snapshot_value.get("source_trade_date") != trade_date
                    or snapshot_value.get("stage_id") != window["stage_id"]
                    or snapshot_value.get("source", {}).get("provider") != "pytdx_exhq"
                    or snapshot_value.get("coverage") != dict(coverage)
                    or type(snapshot.get("row_count")) is not int
                    or snapshot.get("row_count") != len(snapshot_value.get("source_rows", []))
                    or overlay.get("schema_version") != "v4.manager_close_recapture_candidate_overlay.v1"
                    or overlay.get("source_trade_date") != trade_date
                    or overlay.get("target_trade_date") != value.get("plan_trade_date")
                    or overlay.get("source_pool") != dict(pool)
                    or not isinstance(rows, list) or len(rows) != overlay_ref["count"]
                    or len(rows) != coverage["observed_count"] or not rows):
                raise WorkbenchResearchContractError("close recapture snapshot/overlay contract invalid")
            if manual_hk_observation and (
                    not _matches_manual_hk_securities_metadata(snapshot_value, trade_date)
                    or not _matches_manual_hk_securities_metadata(overlay, trade_date, value.get("plan_trade_date"))
                    or len(snapshot_value.get("source_rows", [])) != 100 or len(rows) != 100):
                raise WorkbenchResearchContractError("requested-day HK observation source lineage invalid")
            allowed_codes = set()
            for row in snapshot_value.get("source_rows", []):
                if isinstance(row, Mapping) and _SYMBOL_RE.fullmatch(str(row.get("code") or "")):
                    allowed_codes.add(row["code"])
            seen = set()
            for row in rows:
                if (not isinstance(row, Mapping) or _SYMBOL_RE.fullmatch(str(row.get("symbol") or "")) is None
                        or row["symbol"] in seen or row["symbol"] not in allowed_codes
                        or row.get("source_trade_date") != trade_date
                        or row.get("candidate_status") != "OBSERVATION_ONLY"
                        or row.get("turnover_currency") != "UNKNOWN" or row.get("turnover_unit") != "UNKNOWN"):
                    raise WorkbenchResearchContractError("close recapture candidate row invalid")
                seen.add(row["symbol"])
                observed = _timestamp(row.get("observed_at"), "candidate.observed_at", required=True)
                available = _timestamp(row.get("available_at"), "candidate.available_at", required=True)
                if (_utc_instant(observed, "candidate.observed_at")
                        > _utc_instant(available, "candidate.available_at")
                        or _utc_instant(available, "candidate.available_at")
                        > _utc_instant(request["available_at"], "request.available_at")):
                    raise WorkbenchResearchContractError("close recapture candidate times invalid")
                if manual_hk_observation:
                    observed_local = _utc_instant(observed, "candidate.observed_at").astimezone(_HK_TZ)
                    clock_time = observed_local.timetz().replace(tzinfo=None)
                    if (observed_local.strftime("%Y%m%d") != trade_date
                            or not time.fromisoformat(window["start_at"]) <= clock_time < time.fromisoformat(window["end_before"])):
                        raise WorkbenchResearchContractError("requested-day HK observation source date/window invalid")
            receipt_path = directory / "close_recapture.receipt.json"
            receipt = load(receipt_path)
            if (receipt.get("schema_version") != "v4.manager_close_recapture_receipt.v1"
                    or receipt.get("status") != value.get("status")
                    or receipt.get("source_trade_date") != trade_date
                    or receipt.get("target_trade_date") != value.get("plan_trade_date")
                    or receipt.get("artifact_ref") != f"workbench_research/{trade_date}/close_recapture.json"
                    or receipt.get("artifact_sha256") != digest(raw)
                    or receipt.get("snapshot_sha256") != snapshot["sha256"]
                    or receipt.get("candidate_overlay_sha256") != overlay_ref["sha256"]
                    or any(receipt.get(key) is not expected for key, expected in _CLOSE_RECAPTURE_FLAGS.items())):
                raise WorkbenchResearchContractError("close recapture receipt invalid")
            if manual_hk_observation and (
                    not _matches_manual_hk_securities_metadata(receipt, trade_date, value.get("plan_trade_date"))
                    or receipt.get("candidate_count") != 100
                    or receipt.get("pool_manifest_sha256") != pool.get("manifest_sha256")
                    or receipt.get("captured_at") != request.get("captured_at")
                    or receipt.get("available_at") != request.get("available_at")):
                raise WorkbenchResearchContractError("requested-day HK observation receipt binding invalid")
            return {**value, "requested_trade_date": trade_date,
                    "candidate_overlay": {**dict(overlay_ref), "rows": rows},
                    "receipt": {key: receipt.get(key) for key in ("artifact_sha256", "captured_at", "available_at", "candidate_count",
                        "execution_kind", "observation_type", "observation_market", "official_close_status")},
                    "snapshot_verified": True, "candidate_overlay_verified": True}
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, KeyError):
            return empty(trade_date, "FAILED", "CLOSE_RECAPTURE_ARTIFACT_INVALID")

    def read(self, trade_date: str) -> dict[str, Any]:
        now = _now_hk()
        today = now.strftime("%Y%m%d")
        if trade_date > today or (trade_date == today and (now.hour, now.minute) < (15, 30)):
            return _empty_envelope(trade_date, "PENDING_SLOT", "WORKBENCH_RESEARCH_SLOT_NOT_REACHED")
        path = self._path(trade_date)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return self._read_attempt(trade_date,now)
        except OSError:
            return _empty_envelope(trade_date, "FAILED", "WORKBENCH_RESEARCH_ARTIFACT_READ_FAILED")
        try:
            value = json.loads(raw.decode("utf-8"))
            validated=validate_workbench_payload(
                value, expected_date=trade_date, state_root=self.state_root,
                verify_published_sources=True, rebound_authority_root=self.rebound_authority_root,
            )
            for field in ("as_of","generated_at"):
                if validated.get(field) and _utc_instant(validated[field],field)>now.astimezone(timezone.utc):
                    raise WorkbenchResearchContractError("artifact is not available at the current time")
            attempt_path=self.artifact_root/trade_date/"1530.status.json"
            if attempt_path.exists():
                try:
                    attempt=validate_workbench_payload(json.loads(attempt_path.read_bytes()),expected_date=trade_date)
                    if attempt["status"] not in _NON_DATA_STATUSES or not attempt.get("generated_at"):
                        raise WorkbenchResearchContractError("attempt must be a dated non-data state")
                    if (_utc_instant(attempt["generated_at"],"attempt.generated_at")
                        > _utc_instant(validated["generated_at"],"generated_at")):
                        return self._read_attempt(trade_date,now)
                    # An older EXECUTION_STARTED receipt was superseded by this
                    # successful artifact. Do not age it into a false failure.
                except (OSError,UnicodeError,ValueError,TypeError):
                    return _empty_envelope(trade_date,"FAILED","WORKBENCH_RESEARCH_ATTEMPT_INVALID")
            return validated
        except (UnicodeError, json.JSONDecodeError, WorkbenchResearchContractError) as exc:
            cause = str(exc.__cause__) if exc.__cause__ is not None else ''
            allowed = {'REBOUND_HISTORY_AUTHORITY_ROOT_NOT_BOUND', 'REBOUND_HISTORY_AUTHORITY_ROOT_INVALID',
                       'REBOUND_HISTORY_AUTHORITY_ROOT_CONFLICT', 'REBOUND_HISTORY_AUTHORITY_LAYOUT_MISSING',
                       'REBOUND_HISTORY_AUTHORITY_BINDING_MISMATCH'}
            return _empty_envelope(trade_date, 'FAILED',
                cause if cause in allowed else 'WORKBENCH_RESEARCH_ARTIFACT_INVALID')

    def _read_attempt(self, trade_date: str, now: datetime) -> dict[str, Any]:
        # Reading never schedules work. Absence of a receipt means only that
        # execution is not evidenced, not that a scan successfully found zero.
        path=self.artifact_root/trade_date/"1530.status.json"
        try:
            value=validate_workbench_payload(json.loads(path.read_bytes()),expected_date=trade_date)
            if value["status"] not in _NON_DATA_STATUSES:
                raise WorkbenchResearchContractError("attempt must not project data")
            generated=value.get("generated_at")
            if not generated or _utc_instant(generated,"generated_at")>now.astimezone(timezone.utc):
                raise WorkbenchResearchContractError("attempt time is invalid")
            if value["status"]=="PENDING_SLOT" and "EXECUTION_STARTED" in value["cannot_confirm"]:
                if (now.astimezone(timezone.utc)-_utc_instant(generated,"generated_at")).total_seconds()>180:
                    return _empty_envelope(trade_date,"FAILED","EXECUTION_DID_NOT_FINISH")
            return value
        except FileNotFoundError:
            return _empty_envelope(trade_date,"NOT_RUN","WORKBENCH_RESEARCH_NO_EXECUTION_RECEIPT")
        except (OSError,UnicodeError,ValueError,TypeError):
            return _empty_envelope(trade_date,"FAILED","WORKBENCH_RESEARCH_ATTEMPT_INVALID")


def create_manager_workbench_router(state_root: Path | str, *,
                                    rebound_authority_root: Path | str | None = None) -> APIRouter:
    reader = ManagerWorkbenchResearchReader(state_root, rebound_authority_root=rebound_authority_root)
    router = APIRouter(prefix="/api/v4/manager/workbench-research", tags=["manager-workbench-research"])

    @router.get("")
    def read_workbench_research(
        date: str = Query(..., description="Exact trade date in YYYYMMDD format."),
        market: str = Query(MARKET),
        slot: str = Query(SLOT),
    ) -> dict[str, Any]:
        selected = _strict_date(date)
        if market != MARKET:
            raise HTTPException(status_code=422, detail=f"market must be {MARKET}")
        if slot == "CLOSE_RECAPTURE":
            return reader.read_close_recapture(selected)
        if slot != SLOT:
            raise HTTPException(status_code=422, detail=f"slot must be {SLOT}")
        return reader.read(selected)

    return router


__all__ = [
    "ManagerWorkbenchResearchReader",
    "WorkbenchResearchContractError",
    "create_manager_workbench_router",
    "validate_workbench_payload",
]
