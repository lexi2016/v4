"""Bounded read-only stage execution declarations, separate from selection proof.

A hash computed while reading a receipt is an observed file identity, not a
signature or independent run attestation. Matching selection identities binds
only that selection reference, never a natural/recovery execution as a whole.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from infrastructure.owned_io import SafeRoot
from .contracts import STAGE_BY_ID

_MAX_BYTES = 1_048_576
_IDENTITY = ("run_id", "artifact_id", "algorithm_sha256", "raw_artifact_sha256")
_COUNTERS = ("requested_rows", "source_rows", "observed_rows", "accepted_rows", "selected_rows")


def _counter(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _exact_bytes(root: Path, trade_date: str, stage_id: str) -> bytes:
    """Reuse existing all-ancestry O_NOFOLLOW, bounded nonblocking file reads."""
    return SafeRoot(root).read_bytes(f"{trade_date}/{stage_id}/receipt.json", max_bytes=_MAX_BYTES)


def _auction_diagnostics(reasons: list[str]) -> dict[str, Any] | None:
    # Parse only the already emitted SDK diagnostics object, not a new protocol.
    for reason in reasons:
        marker = reason.find("{")
        if marker < 0:
            continue
        try:
            parsed, _ = json.JSONDecoder().raw_decode(reason[marker:])
        except (ValueError, TypeError):
            continue
        if not isinstance(parsed, dict) or parsed.get("schema_version") != "PYTDX_0925_DIAGNOSTICS_V1":
            continue
        result = {key: _counter(parsed.get(key)) for key in (
            "pages_read", "raw_tick_count", "exact_time_count", "accepted_tick_count", "read_error_count")}
        stops = parsed.get("stop_reasons")
        result["stop_reasons"] = {str(k)[:100]: _counter(v) for k, v in stops.items()} if isinstance(stops, dict) else {}
        result["evidence_level"] = "RECEIPT_DECLARED_DIAGNOSTICS"
        return result
    return None


def read_stage_execution(
    root: Path | None, trade_date: str, stage_id: str,
    verified_markets: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if not re.fullmatch(r"\d{8}", trade_date) or stage_id not in STAGE_BY_ID:
        raise ValueError("invalid stage receipt key")
    result: dict[str, Any] = {
        "status": "EXECUTION_RECEIPT_ROOT_NOT_BOUND", "trade_date": trade_date,
        "stage_id": stage_id, "execution_verified": False, "natural_verified": False,
        "markets": {}, "historical_bad_row_status": "NOT_RECORDED_OR_NOT_BOUND",
        "cannot_confirm": [], "write_performed": False,
        "scope": "READ_ONLY_EXECUTION_DECLARATION_SEPARATE_FROM_VERIFIED_SELECTION",
    }
    if root is None:
        result["cannot_confirm"] = ["EXECUTION_RECEIPT_ROOT_NOT_BOUND"]
        return result
    result["receipt_path"] = str(root / trade_date / stage_id / "receipt.json")
    try:
        raw = _exact_bytes(root, trade_date, stage_id)
        receipt = json.loads(raw)
        if not isinstance(receipt, dict):
            raise ValueError("RECEIPT_NOT_OBJECT")
    except FileNotFoundError:
        result.update(status="EXECUTION_RECEIPT_MISSING", cannot_confirm=["EXACT_DATE_STAGE_RECEIPT_MISSING"])
        return result
    except (OSError, ValueError, UnicodeError, RecursionError):
        result.update(status="EXECUTION_RECEIPT_READ_REFUSED", cannot_confirm=["RECEIPT_PATH_TYPE_SIZE_OR_JSON_INVALID"])
        return result
    result["observed_sha256"] = hashlib.sha256(raw).hexdigest()
    if (receipt.get("schema_version") != "stage_center.runner.receipt.v1"
            or receipt.get("runner") != "stage_center"
            or receipt.get("trade_date") != trade_date or receipt.get("stage_id") != stage_id):
        result.update(status="RECEIPT_IDENTITY_CONFLICT", cannot_confirm=["SCHEMA_DATE_STAGE_OWNER_MISMATCH"])
        return result
    if any(receipt.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent")):
        result.update(status="RECEIPT_SAFETY_CONFLICT", cannot_confirm=["RECEIPT_SAFETY_NOT_EXPLICIT_FALSE"])
        return result
    markets = receipt.get("markets")
    if not isinstance(markets, dict):
        result.update(status="RECEIPT_IDENTITY_CONFLICT", cannot_confirm=["RECEIPT_MARKETS_NOT_OBJECT"])
        return result
    result.update(status="DECLARED_ONLY", attempt_mode=receipt.get("dispatch_mode"),
                  due_status=receipt.get("due_status"), declared_status=receipt.get("status"),
                  recorded_at=receipt.get("recorded_at"), node_id=receipt.get("node_id"),
                  node_attempt_count=_counter(receipt.get("node_attempt_count")),
                  node_outcome=receipt.get("node_outcome"), retry_after=receipt.get("retry_after"),
                  first_failed_layer=receipt.get("first_failed_layer"), error=receipt.get("error"),
                  candidate_run_id=receipt.get("candidate_run_id"),
                  candidate_current_sha256=receipt.get("candidate_current_sha256"),
                  candidate_binding="REFERENCE_ONLY_CURRENT_TRIO_NOT_BOUND", 
                  cannot_confirm=["NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING", "NO_IMMUTABLE_NATURAL_RECOVERY_HISTORY"])
    if not result["recorded_at"]:
        result["cannot_confirm"].append("RECEIPT_RECORD_TIME_NOT_RECORDED")
    bound_count = 0
    for market, original in markets.items():
        if market not in STAGE_BY_ID[stage_id].markets or not isinstance(original, dict):
            result["cannot_confirm"].append("UNSCHEDULED_OR_INVALID_MARKET_RECEIPT")
            continue
        reasons = [str(x)[:20_000] for x in original.get("cannot_confirm", [])] if isinstance(original.get("cannot_confirm"), (list, tuple)) else []
        projected = {key: _counter(original.get(key)) for key in _COUNTERS}
        projected.update(status=original.get("status"), reasons=reasons,
                         selection_binding="NO_VERIFIED_SELECTION_BINDING",
                         failure_layer=receipt.get("first_failed_layer"),
                         declared_identity={key: original.get(key) for key in _IDENTITY},
                         write_performed=original.get("write_performed") if type(original.get("write_performed")) is bool else None)
        diagnostics = _auction_diagnostics(reasons)
        if diagnostics is not None:
            projected["diagnostics"] = diagnostics
            projected["failure_layer"] = "EXACT_AUCTION_COLLECTION"
        if any("ACTIVE_SNAPSHOT_UNAVAILABLE" in reason for reason in reasons):
            projected["failure_layer"] = "ACTIVE_SNAPSHOT_READ_OR_VALIDATION"
        verified = verified_markets.get(market) or {}
        # Invalid sentinel envelopes never authenticate a receipt reference.
        available = all(isinstance(verified.get(k), str) and verified[k] for k in _IDENTITY)
        if available and verified.get("status") != "CANNOT_CONFIRM":
            if all(original.get(k) == verified[k] for k in _IDENTITY):
                if projected["selected_rows"] == verified.get("selected_rows"):
                    projected["selection_binding"] = "BOUND_TO_VERIFIED_SELECTION"
                    bound_count += 1
                else:
                    projected["selection_binding"] = "SELECTION_COUNT_CONFLICT"
            elif any(original.get(k) for k in _IDENTITY):
                projected["selection_binding"] = "SELECTION_IDENTITY_CONFLICT"
        result["markets"][market] = projected
    if bound_count:
        result["status"] = "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED"
    return result
