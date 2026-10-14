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
_VERIFIED_SELECTION_STATUSES = frozenset({"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS", "NOOP_ALREADY_VERIFIED"})


def _counter(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _verified_selection_status(value: Any) -> bool:
    return isinstance(value, str) and value in _VERIFIED_SELECTION_STATUSES


def _selection_result_available(lane: Mapping[str, Any]) -> bool:
    return _verified_selection_status(lane.get("status")) or (
        lane.get("status") == "CANNOT_CONFIRM"
        and lane.get("_selection_store_verified") is True
        and (_counter(lane.get("selected_rows")) or 0) > 0
    )


def _store_verified_markets(store: Any, trade_date: str, stage_id: str,
                            markets: Mapping[str, Mapping[str, Any]],
                            selection_stores: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """An external status/boolean cannot authenticate a different run or slot."""
    result = {}
    for market in STAGE_BY_ID[stage_id].markets:
        lane = dict(markets.get(market) or {})
        lane["_selection_store_verified"] = False
        selected_store = (selection_stores or {}).get(market, store)
        lane["_selection_execution_namespace_matches"] = selected_store is store
        if selected_store is None:
            result[market] = lane
            continue
        try:
            if store is not None:
                lane["_selection_execution_namespace_matches"] = Path(selected_store.root) == Path(store.root)
            verified = selected_store._verify_run(trade_date, stage_id, market, lane["run_id"])
            envelope = verified["envelope"]
            for key, expected in (("trade_date", trade_date), ("stage_id", stage_id), ("market", market)):
                if (verified.get(key) != expected or envelope.get(key) != expected
                        or lane.get(key, expected) != expected):
                    raise ValueError("selection result scope differs")
            for key in (*_IDENTITY, "selected_rows", "requested_rows", "source_rows"):
                if lane.get(key) != envelope.get(key):
                    raise ValueError("selection result identity or counts differ")
            if (lane.get("status") != envelope.get("selection_status")
                    or list(lane.get("source_evidence") or []) != list(envelope.get("source_evidence") or [])):
                raise ValueError("selection result status or source evidence differs")
            rows = envelope.get("rows")
            selected = _counter(envelope.get("selected_rows"))
            if not isinstance(rows, list) or selected is None or selected != len(rows):
                raise ValueError("selection result row count differs")
            # Name overlays and the display-only order field may differ; the
            # immutable code/rank sequence cannot belong to another result.
            if "rows" in lane and [(r.get("code"), r.get("rank")) for r in lane["rows"]] != [
                    (r.get("code"), r.get("rank")) for r in rows]:
                raise ValueError("selection result rows differ")
            lane["_selection_store_verified"] = True
            result[market] = lane
        except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
            result[market] = {}
    return result


def research_source_projection(source_evidence: Any, trade_date: str, market: str) -> dict[str, Any]:
    """Project the one immutable source declaration, without certifying D1."""
    declarations = [item[len("research_source="):] for item in (source_evidence or [])
                    if isinstance(item, str) and item.startswith("research_source=")]
    if not declarations:
        return {"research_source": None, "research_source_status": "NOT_RECORDED"}
    try:
        from datetime import datetime
        if len(declarations) != 1:
            raise ValueError("ambiguous research source")
        value = json.loads(declarations[0])
        if (not isinstance(value, dict) or _canonical_bytes(value).decode() != declarations[0]
                or value.get("schema_version") != "HK_CURRENT_DAY_RESEARCH_V1"
                or value.get("mode") != "CURRENT_DAY_RESEARCH_ONLY"
                or market != "HK_CONNECT" or value.get("market") != market
                or value.get("trade_date") != trade_date
                or value.get("hk_connect_membership_status") != "CANNOT_CONFIRM"
                or value.get("formal_d1_eligible") is not False):
            raise ValueError("research source scope or limits differ")
        as_of = value.get("universe_as_of")
        if (not isinstance(as_of, str) or not re.fullmatch(r"\d{8}", as_of)
                or as_of > trade_date or value.get("stale_universe") is not (as_of < trade_date)):
            raise ValueError("research universe date differs")
        captured = datetime.fromisoformat(value["captured_at"])
        if captured.utcoffset() is None or captured.strftime("%Y%m%d") != trade_date:
            raise ValueError("research capture clock differs")
        for key in ("source_sha256", "security_master_sha256", "reference_codes_sha256", "receipt_sha256", "final_receipt_sha256"):
            if key == "source_sha256" or key in value:
                if not isinstance(value.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", value[key]):
                    raise ValueError("research source digest invalid")
        return {"research_source": value, "research_source_status": "RECORDED_IN_VERIFIED_SELECTION"}
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return {"research_source": None, "research_source_status": "CANNOT_CONFIRM"}


def _exact_bytes(root: Path, trade_date: str, stage_id: str) -> bytes:
    """Reuse existing all-ancestry O_NOFOLLOW, bounded nonblocking file reads."""
    return SafeRoot(root).read_bytes(f"{trade_date}/{stage_id}/receipt.json")


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



def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _verified_result_summaries(
    trade_date: str, stage_id: str, verified_markets: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """SelectionStore results remain visible even when execution evidence is absent."""
    summaries: dict[str, Any] = {}
    for market in STAGE_BY_ID[stage_id].markets:
        lane = verified_markets.get(market) or {}
        selected = _counter(lane.get("selected_rows"))
        identities = all(isinstance(lane.get(key), str) and lane[key] for key in _IDENTITY)
        available = identities and selected is not None and _selection_result_available(lane)
        requested, source = _counter(lane.get("requested_rows")), _counter(lane.get("source_rows"))
        summaries[market] = {
            "status": ("RESULT_AVAILABLE" if selected else "VERIFIED_EMPTY_RESULT") if available else "NO_VERIFIED_RESULT",
            "selection_status": lane.get("status"),
            "selection_mode": lane.get("selection_mode") if available else None,
            "selected_rows": selected if available else None,
            "requested_rows": requested if available else None,
            "source_rows": source if available else None,
            "missing_quote_rows": requested - source if available and requested is not None and source is not None and source <= requested else None,
            "quote_coverage_ratio": round(source / requested, 6) if available and requested and source is not None and source <= requested else None,
            "evidence_scope": "VERIFIED_SELECTION_RESULT_NOT_EXECUTION_ATTESTATION",
            "trade_date": trade_date, "stage_id": stage_id, "market": market,
            "source_evidence": list(lane.get("source_evidence") or []) if available else [],
            **research_source_projection(lane.get("source_evidence") if available else [], trade_date, market),
            **{key: lane.get(key) if available else None for key in _IDENTITY if key != "selected_rows"},
        }
    return summaries


def _owner_history_binding(root: Path, receipt: Mapping[str, Any], trade_date: str, stage_id: str) -> tuple[str, str]:
    """Verify only the original owner's immutable copy, never natural execution."""
    history = receipt.get("receipt_history")
    if history is None:
        return "OWNER_HISTORY_NOT_RECORDED", "RECEIPT_RECORD_TIME_NOT_BOUND" if receipt.get("recorded_at") else "RECEIPT_RECORD_TIME_NOT_RECORDED"
    try:
        if not isinstance(history, dict) or history.get("schema_version") != "stage_center.runner.history_ref.v1":
            raise ValueError("invalid history schema")
        sha = history.get("sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("invalid history digest")
        relative = f"{trade_date}/{stage_id}/attempt_evidence/recorded-{sha}/RECEIPT.json"
        if history.get("relative_path") != relative:
            raise ValueError("history must belong to this exact slot")
        raw = SafeRoot(root).read_bytes(relative, max_bytes=_MAX_BYTES)
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("history bytes differ")
        archived = json.loads(raw)
        expected = {key: value for key, value in receipt.items() if key != "receipt_history"}
        if not isinstance(archived, dict) or _canonical_bytes(archived) != _canonical_bytes(expected):
            raise ValueError("history and current receipt differ")
        from datetime import datetime, timedelta
        recorded = receipt.get("recorded_at")
        if not isinstance(recorded, str):
            raise ValueError("missing write clock")
        when = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
        if when.utcoffset() != timedelta(0) or receipt.get("record_time_source") != "OWNER_WRITE_CLOCK_UTC":
            raise ValueError("write clock is not an explicit UTC owner record")
        return "OWNER_HISTORY_SHA_BOUND", "OWNER_WRITE_CLOCK_RECORDED"
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return "OWNER_HISTORY_CONFLICT", "RECEIPT_RECORD_TIME_NOT_VERIFIED"


def _selection_trio_binding(
    store: Any, declared: Any, original: Mapping[str, Any],
    verified_lane: Mapping[str, Any], trade_date: str, stage_id: str, market: str,
    history_bound: bool,
) -> dict[str, Any]:
    """Read only the configured SelectionStore, with distinct canonical and byte SHAs."""
    if verified_lane.get("_selection_execution_namespace_matches") is False:
        return {"status": "EXECUTION_RECEIPT_NAMESPACE_NOT_BOUND"}
    if declared is None:
        return {"status": "SELECTION_TRIO_NOT_RECORDED"}
    if store is None:
        return {"status": "SELECTION_STORE_NOT_BOUND"}
    try:
        from pathlib import PurePosixPath
        if not isinstance(declared, dict) or declared.get("schema_version") != "stage_center.runner.selection_binding.v1":
            raise ValueError("invalid selection binding")
        if not _selection_result_available(verified_lane):
            raise ValueError("selection not verified")
        keys = (*_IDENTITY, "selected_rows")
        if any(_counter(value.get("selected_rows")) is None for value in (verified_lane, declared, original)):
            raise ValueError("invalid selected count")
        if any(declared.get(key) != verified_lane.get(key) or original.get(key) != verified_lane.get(key) for key in keys):
            raise ValueError("selection identities differ")
        for value in (declared, original):
            if any(key in value and value[key] != expected for key, expected in (
                    ("trade_date", trade_date), ("stage_id", stage_id), ("market", market))):
                raise ValueError("receipt selection scope differs")
        verified = store._verify_run(trade_date, stage_id, market, declared["run_id"])
        if any(verified["envelope"].get(key) != declared.get(key) for key in keys):
            raise ValueError("original store returned another selection")
        artifact_relative = verified["artifact_relative"]
        parent = PurePosixPath(artifact_relative).parent
        paths = {
            "artifact_relative": artifact_relative,
            "manifest_relative": str(parent / "manifest.json"),
            "receipt_relative": str(parent / "receipt.json"),
        }
        if any(declared.get(key) != value for key, value in paths.items()):
            raise ValueError("selection paths differ from original store")
        io = SafeRoot(store.root)
        # Keep the existing store's bounded file reads; never follow declared absolute paths.
        raw = {key: io.read_bytes(value) for key, value in paths.items()}
        hashes = {
            "artifact_bytes_sha256": hashlib.sha256(raw["artifact_relative"]).hexdigest(),
            "manifest_bytes_sha256": hashlib.sha256(raw["manifest_relative"]).hexdigest(),
            "receipt_bytes_sha256": hashlib.sha256(raw["receipt_relative"]).hexdigest(),
            "manifest_canonical_sha256": hashlib.sha256(_canonical_bytes(json.loads(raw["manifest_relative"]))).hexdigest(),
            "receipt_canonical_sha256": hashlib.sha256(_canonical_bytes(json.loads(raw["receipt_relative"]))).hexdigest(),
        }
        if any(declared.get(key) != value for key, value in hashes.items()):
            raise ValueError("selection bytes or canonical digest changed")
        if (verified["artifact_sha256"] != hashes["artifact_bytes_sha256"]
                or verified["manifest_sha256"] != hashes["manifest_canonical_sha256"]
                or verified["receipt_sha256"] != hashes["receipt_canonical_sha256"]):
            raise ValueError("selection changed after original store verification")
        return {
            "status": "BOUND_TO_VERIFIED_SELECTION_TRIO" if history_bound else "SELECTION_TRIO_MATCHES_CURRENT_RECEIPT_HISTORY_UNBOUND",
            "run_id": declared["run_id"], **hashes,
            "execution_verified": False, "natural_verified": False,
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        return {"status": "SELECTION_TRIO_CONFLICT"}

def read_stage_execution(
    root: Path | None, trade_date: str, stage_id: str,
    verified_markets: Mapping[str, Mapping[str, Any]],
    *, selection_store: Any = None, selection_stores: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"\d{8}", trade_date) or stage_id not in STAGE_BY_ID:
        raise ValueError("invalid stage receipt key")
    verified_markets = _store_verified_markets(selection_store, trade_date, stage_id, verified_markets, selection_stores)
    result: dict[str, Any] = {
        "status": "EXECUTION_RECEIPT_ROOT_NOT_BOUND", "trade_date": trade_date,
        "stage_id": stage_id, "execution_verified": False, "natural_verified": False,
        "markets": {}, "historical_bad_row_status": "NOT_RECORDED_OR_NOT_BOUND",
        "cannot_confirm": [], "write_performed": False,
        "scope": "READ_ONLY_EXECUTION_DECLARATION_SEPARATE_FROM_VERIFIED_SELECTION",
        "selection_results": _verified_result_summaries(trade_date, stage_id, verified_markets),
        "receipt_history_binding": "OWNER_HISTORY_NOT_RECORDED",
        "selection_artifact_bindings": {},
        "RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
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
    result.update(declared_attempt_mode=receipt.get("dispatch_mode"),
                  execution_origin=receipt.get("execution_origin"),
                  same_day_late_observation_recovery=receipt.get("same_day_late_observation_recovery"),
                  runtime_source_identity=receipt.get("runtime_source_identity") if isinstance(receipt.get("runtime_source_identity"), dict) else None,
                  runtime_source_identity_scope="OWNER_RECEIPT_DECLARED_FILE_OBSERVATIONS",
                  attempt_mode_status="OWNER_DECLARATION_ONLY")
    replay = (receipt.get("execution_origin") in {"MANUAL_REPLAY", "CURRENT_DAY_RESEARCH_REPLAY", "HISTORICAL_BACKFILL", "LATE_CATCHUP_REPLAY"}
              or receipt.get("due_status") in {"HISTORICAL_BACKFILL", "LATE_CATCHUP_REPLAY"}
              or receipt.get("mode") == "BACKFILL"
              or receipt.get("same_day_late_observation_recovery") is True)
    if replay and result["attempt_mode"] == "NATURAL":
        result.update(attempt_mode="RECOVERY", attempt_mode_status="NATURAL_DECLARATION_CONFLICT")
        result["cannot_confirm"].append("NATURAL_DECLARATION_CONFLICTS_WITH_REPLAY_ORIGIN")
    if any(lane.get("selection_mode") == "BACKFILL" and lane.get("status") == "RESULT_AVAILABLE"
           for lane in result["selection_results"].values()):
        result.update(attempt_mode="BACKFILL", attempt_mode_status="BACKFILL_RESULT_EXECUTION_UNBOUND")
        result["cannot_confirm"].append("CURRENT_RECEIPT_IS_NOT_BACKFILL_EXECUTION_RECEIPT")
    if not result["recorded_at"]:
        result["cannot_confirm"].append("RECEIPT_RECORD_TIME_NOT_RECORDED")
    history, clock_status = _owner_history_binding(root, receipt, trade_date, stage_id)
    result.update(receipt_history_binding=history, record_time_status=clock_status,
                  runner_invoked_at=receipt.get("runner_invoked_at"),
                  invocation_time_source=receipt.get("runner_clock_source"))
    if history == "OWNER_HISTORY_SHA_BOUND":
        result["cannot_confirm"].remove("NO_IMMUTABLE_NATURAL_RECOVERY_HISTORY")
    elif history == "OWNER_HISTORY_CONFLICT":
        result["cannot_confirm"].append("OWNER_RECEIPT_HISTORY_OR_WRITE_CLOCK_CONFLICT")
    declared_artifacts = receipt.get("selection_artifacts")
    declared_artifacts = declared_artifacts if isinstance(declared_artifacts, dict) else {}
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
        if market == "HK_CONNECT" and any("HK D1 status must be STRICT_0_2_READY" in reason for reason in reasons):
            projected["failure_layer"] = "PRESELECTION_INPUT"
        verified = verified_markets.get(market) or {}
        # Invalid sentinel envelopes never authenticate a receipt reference.
        available = all(isinstance(verified.get(k), str) and verified[k] for k in _IDENTITY)
        if available and _selection_result_available(verified):
            scope_conflict = any(key in original and original[key] != expected for key, expected in (
                ("trade_date", trade_date), ("stage_id", stage_id), ("market", market)))
            if verified.get("_selection_execution_namespace_matches") is False:
                projected["selection_binding"] = "EXECUTION_RECEIPT_NAMESPACE_NOT_BOUND"
            elif scope_conflict:
                projected["selection_binding"] = "SELECTION_IDENTITY_CONFLICT"
            elif all(original.get(k) == verified[k] for k in _IDENTITY):
                if projected["selected_rows"] == verified.get("selected_rows"):
                    projected["selection_binding"] = "BOUND_TO_VERIFIED_SELECTION"
                    bound_count += 1
                else:
                    projected["selection_binding"] = "SELECTION_COUNT_CONFLICT"
            elif any(original.get(k) for k in _IDENTITY):
                projected["selection_binding"] = "SELECTION_IDENTITY_CONFLICT"
        result["markets"][market] = projected
        result["selection_artifact_bindings"][market] = _selection_trio_binding(
            selection_store, declared_artifacts.get(market), original, verified,
            trade_date, stage_id, market, history == "OWNER_HISTORY_SHA_BOUND",
        )
    if bound_count:
        result["status"] = "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED"
    try:
        unchanged = _exact_bytes(root, trade_date, stage_id) == raw
    except (OSError, ValueError):
        unchanged = False
    if not unchanged:
        result["receipt_history_binding"] = "OWNER_HISTORY_CONFLICT"
        result["cannot_confirm"].append("RECEIPT_CHANGED_DURING_READ")
        for binding in result["selection_artifact_bindings"].values():
            if binding["status"] == "BOUND_TO_VERIFIED_SELECTION_TRIO":
                binding["status"] = "SELECTION_TRIO_MATCHES_OBSERVED_RECEIPT_CURRENT_CHANGED"
    return result
