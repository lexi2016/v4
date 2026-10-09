"""Available unchanged API projection functions, not a live HTTP service."""
from __future__ import annotations
from typing import Any, Mapping
STAGE_DEFINITIONS = {}  # Test omits display labels; identity and counts use original code.

def _stage_projection_status(
    markets: Mapping[str, Mapping[str, Any]],
    fallback: Any,
) -> str:
    """Reduce market statuses without hiding a lane-level evidence gap."""
    statuses = {str(item.get("status") or "CANNOT_CONFIRM") for item in markets.values()}
    has_rows = any(int(item.get("selected_rows") or item.get("candidate_count") or 0) > 0 for item in markets.values())
    if not statuses:
        return str(fallback or "CANNOT_CONFIRM")
    if statuses == {"READY"}:
        return "READY"
    if statuses == {"READY_EMPTY"}:
        return "READY_EMPTY"
    if "CANNOT_CONFIRM" in statuses:
        return "PARTIAL_WITH_ROWS" if has_rows else "CANNOT_CONFIRM"
    if "PARTIAL_WITH_ROWS" in statuses or str(fallback) == "PARTIAL_WITH_ROWS":
        return "PARTIAL_WITH_ROWS"
    return str(fallback or "PARTIAL_WITH_ROWS")



def _hk_display_mode(
    market_payload: Mapping[str, Any],
    rows: list[dict],
    execution_market: Mapping[str, Any] | None,
) -> tuple[str, list[str]]:
    """Only call HK rows formal after selection and execution binding agree."""
    status = str(market_payload.get("status") or "CANNOT_CONFIRM")
    selection_status = str(market_payload.get("selection_status") or status)
    reasons = [str(item) for item in market_payload.get("cannot_confirm") or []]
    identity_present = all(
        isinstance(market_payload.get(field), str) and market_payload.get(field)
        for field in ("artifact_id", "run_id", "raw_artifact_sha256")
    )
    requested_rows = market_payload.get("requested_rows")
    source_rows = market_payload.get("source_rows")
    selected_rows = market_payload.get("selected_rows")
    source_evidence = market_payload.get("source_evidence")
    complete_empty_evidence = (
        isinstance(requested_rows, int)
        and not isinstance(requested_rows, bool)
        and requested_rows >= 0
        and isinstance(source_rows, int)
        and not isinstance(source_rows, bool)
        and source_rows == requested_rows
        and isinstance(selected_rows, int)
        and not isinstance(selected_rows, bool)
        and selected_rows == 0
        and market_payload.get("source_status") in {"READY", "READY_EMPTY"}
        and isinstance(source_evidence, (list, tuple))
        and any(isinstance(item, str) and item.strip() for item in source_evidence)
        and not market_payload.get("missing_symbols")
        and not market_payload.get("cannot_confirm")
    )
    verified_empty = (
        status == "READY_EMPTY"
        and selection_status == "READY_EMPTY"
        and market_payload.get("source_status") in {"READY", "READY_EMPTY"}
        and identity_present
        and not rows
        and complete_empty_evidence
        and not reasons
    )
    if verified_empty:
        return "READY_EMPTY", []

    if status == "READY_EMPTY":
        if not complete_empty_evidence:
            reasons.append("HK_READY_EMPTY_INPUT_OR_SOURCE_EVIDENCE_INCOMPLETE")
        if market_payload.get("source_status") not in {"READY", "READY_EMPTY"}:
            reasons.append("HK_READY_EMPTY_SOURCE_STATUS_NOT_READY")
        if selection_status != "READY_EMPTY":
            reasons.append("HK_READY_EMPTY_SELECTION_STATUS_MISMATCH")
        if not identity_present:
            reasons.append("SELECTION_ARTIFACT_MISSING_OR_INVALID")
        return "CANNOT_CONFIRM", list(dict.fromkeys(reasons))

    if status == "CANNOT_CONFIRM" or not identity_present:
        if not reasons:
            reasons.append("SELECTION_ARTIFACT_MISSING_OR_INVALID")
        return ("OBSERVATION_UNVERIFIED" if rows else "CANNOT_CONFIRM"), reasons

    execution = execution_market if isinstance(execution_market, Mapping) else {}
    binding = execution.get("selection_binding")
    unsafe_rows = any(
        isinstance(row, Mapping) and row.get("formal_eligible") is False
        for row in rows
    )
    selection_ready = (
        status == "READY"
        and selection_status == "READY"
        and not reasons
    )
    execution_bound = binding == "BOUND_TO_VERIFIED_SELECTION"
    if selection_ready and execution_bound and rows and not unsafe_rows:
        return "FORMAL", []

    if selection_ready and not rows:
        reasons.append("HK_READY_SELECTION_HAS_NO_ROWS")

    if unsafe_rows:
        reasons.append("HK_FORMAL_ELIGIBILITY_FALSE")
    if not execution_bound:
        execution_reasons = execution.get("reasons")
        reasons.extend(str(item) for item in execution_reasons or [])
        reasons.append(f"HK_EXECUTION_SELECTION_BINDING_{binding or 'CANNOT_CONFIRM'}")
    if not selection_ready:
        reasons.append(f"HK_SELECTION_STATUS_{status}")
    return ("OBSERVATION_UNVERIFIED" if rows else "CANNOT_CONFIRM"), list(dict.fromkeys(reasons))



def project_shared_selection(
    payload: dict,
    limit: int = 50,
    *,
    ordinary_hk_display: bool = False,
) -> dict:
    canonical_markets = payload.get("markets", {})
    frontend_markets: dict[str, dict] = {}
    unified_rows: list[dict] = []
    aliases = {"A_SHARE": "A", "HK_CONNECT": "HK"}
    execution_markets = (
        (payload.get("execution_evidence") or {}).get("markets") or {}
    )
    backfill_provenance_fields = frozenset(
        {
            "selection_mode",
            "backfill_run_id",
            "backfill_run_ids",
            "selection_manifest_sha256",
            "selection_receipt_sha256",
            "selection_artifact_sha256",
            "selection_manifest_receipt_verified",
            "runner_receipt_verified",
            "runner_receipt_status",
            "runner_receipt_sha256",
            "recovery_provenance",
        }
    )
    for canonical_market, market_payload in canonical_markets.items():
        alias = aliases.get(canonical_market, canonical_market)
        rows = list(market_payload.get("rows") or [])[:limit]
        frontend_markets[alias] = {
            key: market_payload.get(key)
            for key in (
                "market",
                "RESEARCH_ONLY",
                "status",
                "selection_status",
                "artifact_id",
                "run_id",
                "algorithm_id",
                "algorithm_sha256",
                "raw_artifact_sha256",
                "source_status",
                "requested_rows",
                "source_rows",
                "selected_rows",
                "coverage_ratio",
                "source_evidence",
                "missing_symbols",
                "cannot_confirm",
                "name_authority_status",
                "name_authority_source",
                "name_authority_receipt_sha256",
                "name_authority_selector_sha256",
                "name_authority_source_sha256",
                "name_authority_selector_sha_source",
                "name_authority_pool_ids",
                "name_authority_applied_count",
                "name_authority_missing_count",
                "name_authority_error",
                "selection_mode",
                "backfill_run_id",
                "backfill_run_ids",
                "selection_manifest_sha256",
                "selection_receipt_sha256",
                "selection_artifact_sha256",
                "selection_manifest_receipt_verified",
                "runner_receipt_verified",
                "runner_receipt_status",
                "runner_receipt_sha256",
                "recovery_provenance",
                "superseded_source",
                "quarantined_source",
            )
            if key not in backfill_provenance_fields or key in market_payload
        }
        frontend_markets[alias]["candidate_count"] = len(rows)
        frontend_markets[alias]["rows"] = rows
        if canonical_market == "HK_CONNECT" and ordinary_hk_display:
            display_mode, display_reasons = _hk_display_mode(
                market_payload, rows, execution_markets.get(canonical_market)
            )
            frontend_markets[alias]["display_mode"] = display_mode
            frontend_markets[alias]["display_reasons"] = display_reasons
            frontend_markets[alias]["observation_count"] = len(rows)
            if display_mode in {"CANNOT_CONFIRM", "OBSERVATION_UNVERIFIED"}:
                frontend_markets[alias]["candidate_count"] = None
                frontend_markets[alias]["status"] = (
                    "PARTIAL_WITH_ROWS" if display_mode == "OBSERVATION_UNVERIFIED" else "CANNOT_CONFIRM"
                )
                frontend_markets[alias]["selected_rows"] = None
        for row in rows:
            unified_rows.append(
                {
                    **dict(row),
                    "market": alias,
                    "symbol": row.get("code"),
                    "selection_rank": row.get("rank"),
                }
            )
    a_rows = frontend_markets.get("A", {}).get("rows", [])
    hk_rows = frontend_markets.get("HK", {}).get("rows", [])
    selected_a = len(a_rows)
    hk_display_mode = frontend_markets.get("HK", {}).get("display_mode")
    selected_hk = (
        None if hk_display_mode in {"CANNOT_CONFIRM", "OBSERVATION_UNVERIFIED"}
        else len(hk_rows)
    )
    selected_total = None if selected_hk is None else selected_a + selected_hk
    stage_id = payload.get("stage_id")
    stage_definition = STAGE_DEFINITIONS.get(stage_id, {})
    stage_status = _stage_projection_status(frontend_markets, payload.get("status", "CANNOT_CONFIRM"))
    cannot_confirm: list[str] = [str(item) for item in payload.get("cannot_confirm") or []]
    for market, market_payload in frontend_markets.items():
        market_status = str(market_payload.get("status") or "CANNOT_CONFIRM")
        reasons = list(market_payload.get("cannot_confirm") or ())
        if market == "HK":
            reasons.extend(market_payload.get("display_reasons") or ())
            reasons = list(dict.fromkeys(reasons))
        if not reasons and market_status == "CANNOT_CONFIRM":
            reasons = [f"{market}_SELECTION_CANNOT_CONFIRM"]
        # A lane can have rows and still carry a hard evidence boundary.
        # Keep every lane reason visible at the stage boundary; the
        # status reducer above deliberately remains PARTIAL_WITH_ROWS.
        for reason in reasons:
            value = f"{market}:{reason}"
            if value not in cannot_confirm:
                cannot_confirm.append(value)
    return {
        **payload,
        "status": stage_status,
        "selection_markets": canonical_markets,
        "markets": frontend_markets,
        "market_summaries": frontend_markets,
        "unified_rows": unified_rows,
        "cannot_confirm": cannot_confirm,
        "stage": {
            "stage_id": stage_id,
            "label": stage_definition.get("label", stage_id),
            "window": stage_definition.get("window", ""),
            "status": stage_status,
            "display_status": stage_status,
            "cannot_confirm": cannot_confirm,
        },
        "selected_a_rows": selected_a,
        "selected_hk_rows": selected_hk,
        "selected_total_rows": selected_total,
        "selection_mode": "SHARED_STAGE_CENTER_READ_ONLY",
        "recommendation_status": "WATCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }

