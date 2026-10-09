"""Bounded read-only stage execution declarations, separate from selection proof.

A hash computed while reading a receipt is an observed file identity, not a
signature or independent run attestation. Matching selection identities binds
only that selection reference, never a natural/recovery execution as a whole.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta
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



def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def project_hk_current_day_research(lane: Mapping[str, Any]) -> dict[str, Any]:
    """Project only metadata bound into a verified selection, never infer PIT.

    Source limitations are independent of row availability. Malformed metadata
    remains explicitly research/unknown; it cannot promote the saved rows to
    formal HK Connect even if an older caller labelled their status READY.
    """
    raw = lane.get("hk_current_day_research")
    markers = [item.split("=", 1)[1] for item in lane.get("source_evidence") or ()
               if isinstance(item, str) and item.startswith("hk_current_day_research=")]
    if raw is None and not markers and lane.get("selection_mode") != "CURRENT_DAY_RESEARCH_ONLY":
        return {}
    reasons = ["CURRENT_CONNECT_ELIGIBILITY_CANNOT_CONFIRM", "CURRENT_DAY_RESEARCH_NOT_FORMAL_D1_PIT"]
    valid = False
    try:
        if not isinstance(raw, dict) or len(markers) != 1 or json.loads(markers[0]) != raw:
            raise ValueError("RESEARCH_METADATA_NOT_BOUND_TO_SOURCE_EVIDENCE")
        if (raw.get("input_mode") != "CURRENT_DAY_RESEARCH_ONLY"
                or raw.get("trade_date") != lane.get("trade_date")
                or raw.get("stage_id") != lane.get("stage_id")
                or lane.get("market") != "HK_CONNECT"
                or raw.get("current_connect_eligibility") != "CANNOT_CONFIRM"
                or raw.get("RESEARCH_ONLY") is not True
                or any(raw.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))):
            raise ValueError("RESEARCH_METADATA_IDENTITY_OR_SAFETY_CONFLICT")
        trade_date = datetime.strptime(str(raw.get("trade_date")), "%Y%m%d").date()
        universe_date = datetime.strptime(str(raw.get("universe_as_of")), "%Y%m%d").date()
        captured = datetime.fromisoformat(str(raw.get("captured_at")))
        cutoff_text = str(raw.get("cutoff_at"))
        cutoff = (datetime.fromisoformat(f"{trade_date.isoformat()}T{cutoff_text}+08:00")
                  if re.fullmatch(r"\d{2}:\d{2}:\d{2}", cutoff_text)
                  else datetime.fromisoformat(cutoff_text))
        if (raw["stage_id"] not in STAGE_BY_ID
                or cutoff.strftime("%H:%M:%S") != STAGE_BY_ID[raw["stage_id"]].cutoff):
            raise ValueError("RESEARCH_CUTOFF_DIFFERS_FROM_STAGE_CONTRACT")
        if (captured.utcoffset() != timedelta(hours=8) or cutoff.utcoffset() != timedelta(hours=8)
                or captured.date() != trade_date or cutoff.date() != trade_date
                or captured > cutoff or universe_date > trade_date
                or type(raw.get("stale_universe")) is not bool
                or raw["stale_universe"] != (universe_date < trade_date)):
            raise ValueError("RESEARCH_SOURCE_TIME_OR_UNIVERSE_CONFLICT")
        if not re.fullmatch(r"[0-9a-f]{64}", str(raw.get("input_binding_sha256"))):
            raise ValueError("RESEARCH_INPUT_SHA_INVALID")
        files = raw.get("source_files")
        if not isinstance(files, dict) or set(files) != {"snapshot", "receipt", "reference_codes", "final_receipt"}:
            raise ValueError("RESEARCH_SOURCE_FILES_INCOMPLETE")
        for entry in files.values():
            if (not isinstance(entry, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256")))
                    or not isinstance(entry.get("file"), str) or Path(entry["file"]).name != entry["file"]
                    or entry["file"] in {"", ".", ".."}):
                raise ValueError("RESEARCH_SOURCE_FILE_IDENTITY_INVALID")
        valid = True
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        reasons.append(str(error) if str(error).startswith("RESEARCH_") else "RESEARCH_METADATA_INVALID")
    return {
        "selection_mode": "CURRENT_DAY_RESEARCH_ONLY", "RESEARCH_ONLY": True,
        "hk_current_day_research": deepcopy(raw) if isinstance(raw, dict) else None,
        "research_source_status": "VERIFIED_SELECTION_METADATA" if valid else "CANNOT_CONFIRM",
        "research_source_restrictions": reasons,
    }


def _verified_result_summaries(
    stage_id: str, verified_markets: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """SelectionStore results remain visible even when execution evidence is absent."""
    summaries: dict[str, Any] = {}
    for market in STAGE_BY_ID[stage_id].markets:
        lane = verified_markets.get(market) or {}
        selected = _counter(lane.get("selected_rows"))
        identities = all(isinstance(lane.get(key), str) and lane[key] for key in _IDENTITY)
        available = identities and selected is not None and _verified_selection_status(lane.get("status"))
        requested, source = _counter(lane.get("requested_rows")), _counter(lane.get("source_rows"))
        summaries[market] = {
            "status": ("RESULT_AVAILABLE" if selected else "VERIFIED_EMPTY_RESULT") if available else "NO_VERIFIED_RESULT",
            "selection_status": lane.get("status"),
            "selected_rows": selected if available else None,
            "requested_rows": requested if available else None,
            "source_rows": source if available else None,
            "missing_quote_rows": requested - source if available and requested is not None and source is not None and source <= requested else None,
            "quote_coverage_ratio": round(source / requested, 6) if available and requested and source is not None and source <= requested else None,
            "evidence_scope": "VERIFIED_SELECTION_RESULT_NOT_EXECUTION_ATTESTATION",
            **{key: lane.get(key) if available else None for key in _IDENTITY if key != "selected_rows"},
            "trade_date": lane.get("trade_date") if available else None,
            "stage_id": lane.get("stage_id") if available else None,
            "market": market,
            "runtime_source_identity": deepcopy(lane.get("runtime_source_identity")) if available else None,
            "source_restrictions": [item for item in lane.get("cannot_confirm") or () if isinstance(item, str)],
            "quote_data_times": list(dict.fromkeys(
                row["source_last_bar_time"] for row in lane.get("rows") or ()
                if isinstance(row, dict) and isinstance(row.get("source_last_bar_time"), str)
                and row["source_last_bar_time"]
            )) if available else [],
            **project_hk_current_day_research(lane),
        }
    return summaries


def _a_input_reference(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the input reference from the original verified selection only."""
    def single(prefix: str) -> str | None:
        values = [item[len(prefix):] for item in envelope.get("source_evidence") or ()
                  if isinstance(item, str) and item.startswith(prefix)]
        return values[0] if len(values) == 1 else None
    return {"trade_date": envelope.get("trade_date"),
            "run_id": single("candidate_run_id="),
            "current_bytes_sha256": single("candidate_current_sha256="),
            "row_count": _counter(envelope.get("requested_rows"))}


def _a_input_binding(declared: Any, trio: Mapping[str, Any], history: str) -> dict[str, Any]:
    base = {"execution_verified": False, "natural_verified": False,
            "input_reread_performed": False, "candidate_pit_verified": False,
            "scope": "ORIGINAL_SELECTION_SOURCE_REFERENCE_AND_OWNER_RECORD_NOT_CURRENT_INPUT_REREAD_OR_PIT_ATTESTATION"}
    if declared is None:
        return {**base, "status": "A_INPUT_NOT_RECORDED"}
    if (not isinstance(declared, dict)
            or declared.get("schema_version") != "stage_center.runner.input_binding.v1"
            or declared.get("kind") != "A_SHARE_STAGE_ACQUISITION_UNIVERSE"
            or declared.get("binding_scope") != "INPUT_VALIDATED_FOR_THIS_INVOCATION"):
        return {**base, "status": "A_INPUT_BINDING_CONFLICT"}
    reference = trio.get("candidate_input_reference")
    if not isinstance(reference, dict):
        return {**base, "status": "A_INPUT_DECLARED_OWNER_OR_SELECTION_UNBOUND"}
    if (not isinstance(reference.get("run_id"), str) or not reference["run_id"]
            or not re.fullmatch(r"[0-9a-f]{64}", str(reference.get("current_bytes_sha256")))
            or not re.fullmatch(r"\d{8}", str(reference.get("trade_date")))
            or _counter(reference.get("row_count")) is None):
        return {**base, "status": "A_INPUT_SELECTION_REFERENCE_NOT_RECORDED"}
    if (_counter(declared.get("row_count")) is None
            or any(declared.get(key) != value for key, value in reference.items())):
        return {**base, "status": "A_INPUT_BINDING_CONFLICT"}
    bound = trio.get("status") == "BOUND_TO_VERIFIED_SELECTION_TRIO" and history == "OWNER_HISTORY_SHA_BOUND"
    return {**base, **reference, "status": "OWNER_DECLARED_INPUT_BOUND_TO_SELECTION" if bound
            else "A_INPUT_DECLARED_OWNER_OR_SELECTION_UNBOUND"}


def _research_input_binding(declared: Any, lane: Mapping[str, Any], trio: Mapping[str, Any], history: str) -> dict[str, Any]:
    projected = project_hk_current_day_research(lane)
    if not projected:
        return {"status": "NOT_CURRENT_DAY_RESEARCH"}
    base = {"execution_verified": False, "natural_verified": False}
    if not isinstance(declared, dict):
        return {**base, "status": "RESEARCH_INPUT_NOT_RECORDED"}
    metadata = projected.get("hk_current_day_research")
    if (projected["research_source_status"] != "VERIFIED_SELECTION_METADATA"
            or declared.get("role") != "CURRENT_DAY_RESEARCH_ONLY"
            or declared.get("research_metadata") != metadata
            or declared.get("input_binding_sha256") != metadata.get("input_binding_sha256")
            or declared.get("source_files") != metadata.get("source_files")):
        return {**base, "status": "RESEARCH_INPUT_BINDING_CONFLICT"}
    if trio.get("status") != "BOUND_TO_VERIFIED_SELECTION_TRIO" or history != "OWNER_HISTORY_SHA_BOUND":
        return {**base, "status": "RESEARCH_INPUT_DECLARED_OWNER_OR_SELECTION_UNBOUND"}
    return {**base, "status": "RESEARCH_INPUT_BOUND_TO_SELECTION_AND_OWNER_HISTORY",
            "input_binding_sha256": metadata["input_binding_sha256"],
            "source_files": deepcopy(metadata["source_files"]),
            "scope": "ORIGINAL_SELECTION_AND_OWNER_RECORD_NOT_INDEPENDENT_PIT_ATTESTATION"}


def _runtime_source_binding(declared: Any, history: str) -> dict[str, Any]:
    base = {"execution_verified": False, "natural_verified": False,
            "scope": "RECEIPT_SOURCE_DECLARATION_NOT_PROCESS_ATTESTATION"}
    if declared is None:
        return {**base, "status": "RUNTIME_SOURCE_IDENTITY_NOT_RECORDED"}
    try:
        if (not isinstance(declared, dict) or declared.get("schema_version") != "stage_center.runtime_source_identity.v1"
                or declared.get("status") != "RECORDED" or declared.get("owner") != "STAGE_RUNNER"
                or declared.get("scope") != "SOURCE_FILES_AT_RUNNER_ENTRY_NOT_PROCESS_ATTESTATION"
                or declared.get("missing_files") != []):
            raise ValueError("source identity schema")
        files = declared.get("files")
        if not isinstance(files, dict) or not files or len(files) > 256:
            raise ValueError("source identity files")
        for relative, entry in files.items():
            if (not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts
                    or not isinstance(entry, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256")))
                    or type(entry.get("bytes")) is not int or entry["bytes"] < 0):
                raise ValueError("source identity entry")
        body = {key: value for key, value in declared.items() if key not in {"sha256", "status"}}
        digest = hashlib.sha256(_canonical_bytes(body)).hexdigest()
        if digest != declared.get("sha256"):
            raise ValueError("source identity digest")
        return {**base, "status": "OWNER_HISTORY_SOURCE_IDENTITY_BOUND" if history == "OWNER_HISTORY_SHA_BOUND"
                else "RUNTIME_SOURCE_IDENTITY_HISTORY_UNBOUND", "sha256": digest, "files": deepcopy(files)}
    except (ValueError, TypeError, RecursionError):
        return {**base, "status": "RUNTIME_SOURCE_IDENTITY_CONFLICT"}


def _selection_source_binding(declared: Any, lane: Mapping[str, Any], trio: Mapping[str, Any], history: str, invocation: Any) -> dict[str, Any]:
    origin = lane.get("runtime_source_identity")
    base = {"execution_verified": False, "natural_verified": False}
    if origin is None:
        return {**base, "status": "SELECTION_SOURCE_IDENTITY_NOT_RECORDED"}
    if declared != origin or not isinstance(origin, dict):
        return {**base, "status": "SELECTION_SOURCE_IDENTITY_CONFLICT"}
    verified = _runtime_source_binding(origin, history)
    if verified["status"] == "RUNTIME_SOURCE_IDENTITY_CONFLICT":
        return {**base, "status": "SELECTION_SOURCE_IDENTITY_CONFLICT"}
    bound = (verified["status"] == "OWNER_HISTORY_SOURCE_IDENTITY_BOUND"
             and trio.get("status") == "BOUND_TO_VERIFIED_SELECTION_TRIO")
    invocation_sha = invocation.get("sha256") if isinstance(invocation, dict) else None
    return {**base, "status": "SELECTION_SOURCE_IDENTITY_BOUND_TO_TRIO_AND_OWNER_HISTORY" if bound
            else "SELECTION_SOURCE_IDENTITY_OWNER_OR_TRIO_UNBOUND", "sha256": origin.get("sha256"),
            "invocation_sha256": invocation_sha,
            "invocation_matches_selection": invocation_sha == origin.get("sha256") if invocation_sha else None,
            "scope": "SELECTED_RUN_SOURCE_RECORD_NOT_PROCESS_ATTESTATION"}


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
    if declared is None:
        return {"status": "SELECTION_TRIO_NOT_RECORDED"}
    if store is None:
        return {"status": "SELECTION_STORE_NOT_BOUND"}
    try:
        from pathlib import PurePosixPath
        if not isinstance(declared, dict) or declared.get("schema_version") != "stage_center.runner.selection_binding.v1":
            raise ValueError("invalid selection binding")
        if not _verified_selection_status(verified_lane.get("status")):
            raise ValueError("selection not verified")
        keys = (*_IDENTITY, "selected_rows")
        if any(_counter(value.get("selected_rows")) is None for value in (verified_lane, declared, original)):
            raise ValueError("invalid selected count")
        if any(declared.get(key) != verified_lane.get(key) or original.get(key) != verified_lane.get(key) for key in keys):
            raise ValueError("selection identities differ")
        verified = store._verify_run(trade_date, stage_id, market, declared["run_id"])
        if any(verified["envelope"].get(key) != declared.get(key) for key in keys):
            raise ValueError("original store returned another selection")
        envelope = verified["envelope"]
        if any(key in envelope and envelope.get(key) != expected for key, expected in (
                ("trade_date", trade_date), ("stage_id", stage_id), ("market", market))):
            raise ValueError("selection envelope slot differs")
        for key in ("hk_current_day_research", "runtime_source_identity"):
            if envelope.get(key) != verified_lane.get(key):
                raise ValueError("selection source metadata differs from original store")
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
            **({"candidate_input_reference": _a_input_reference(envelope)} if market == "A_SHARE" else {}),
            "execution_verified": False, "natural_verified": False,
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        return {"status": "SELECTION_TRIO_CONFLICT"}

def read_stage_execution(
    root: Path | None, trade_date: str, stage_id: str,
    verified_markets: Mapping[str, Mapping[str, Any]],
    *, selection_store: Any = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"\d{8}", trade_date) or stage_id not in STAGE_BY_ID:
        raise ValueError("invalid stage receipt key")
    result: dict[str, Any] = {
        "status": "EXECUTION_RECEIPT_ROOT_NOT_BOUND", "trade_date": trade_date,
        "stage_id": stage_id, "execution_verified": False, "natural_verified": False,
        "markets": {}, "historical_bad_row_status": "NOT_RECORDED_OR_NOT_BOUND",
        "cannot_confirm": [], "write_performed": False,
        "scope": "READ_ONLY_EXECUTION_DECLARATION_SEPARATE_FROM_VERIFIED_SELECTION",
        "selection_results": _verified_result_summaries(stage_id, verified_markets),
        "receipt_history_binding": "OWNER_HISTORY_NOT_RECORDED",
        "selection_artifact_bindings": {},
        "input_binding_status": {},
        "runtime_source_binding": {"status": "RUNTIME_SOURCE_IDENTITY_NOT_RECORDED"},
        "selection_source_bindings": {},
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
    result.update(status="DECLARED_ONLY", attempt_mode=receipt.get("execution_mode") or receipt.get("dispatch_mode"),
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
    history, clock_status = _owner_history_binding(root, receipt, trade_date, stage_id)
    result.update(receipt_history_binding=history, record_time_status=clock_status,
                  runner_invoked_at=receipt.get("runner_invoked_at"),
                  invocation_time_source=receipt.get("runner_clock_source"))
    result["runtime_source_binding"] = _runtime_source_binding(receipt.get("runtime_source_identity"), history)
    declared_inputs = receipt.get("input_bindings")
    declared_inputs = declared_inputs if isinstance(declared_inputs, dict) else {}
    selected_sources = receipt.get("selection_source_identities")
    selected_sources = selected_sources if isinstance(selected_sources, dict) else {}
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
        if available and _verified_selection_status(verified.get("status")):
            if all(original.get(k) == verified[k] for k in _IDENTITY):
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
        result["input_binding_status"][market] = (
            _a_input_binding(declared_inputs.get(market), result["selection_artifact_bindings"][market], history)
            if market == "A_SHARE" else _research_input_binding(
                declared_inputs.get(market), verified, result["selection_artifact_bindings"][market], history,
            )
        )
        result["selection_source_bindings"][market] = _selection_source_binding(
            selected_sources.get(market), verified, result["selection_artifact_bindings"][market],
            history, receipt.get("runtime_source_identity"),
        )
    if bound_count:
        result["status"] = "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED"
    a_input = result["input_binding_status"].get("A_SHARE")
    if a_input and a_input["status"] != "A_INPUT_NOT_RECORDED":
        result["candidate_binding"] = a_input["status"]
        if a_input["status"] == "OWNER_DECLARED_INPUT_BOUND_TO_SELECTION":
            result.update(candidate_run_id=a_input["run_id"], candidate_current_sha256=a_input["current_bytes_sha256"])
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
        result["runtime_source_binding"] = _runtime_source_binding(receipt.get("runtime_source_identity"), "OWNER_HISTORY_CONFLICT")
        for market, binding in result["input_binding_status"].items():
            if binding["status"] == "RESEARCH_INPUT_BOUND_TO_SELECTION_AND_OWNER_HISTORY":
                binding["status"] = "RESEARCH_INPUT_DECLARED_OWNER_OR_SELECTION_UNBOUND"
            elif binding["status"] == "OWNER_DECLARED_INPUT_BOUND_TO_SELECTION":
                binding["status"] = "A_INPUT_DECLARED_OWNER_OR_SELECTION_UNBOUND"
                result["candidate_binding"] = binding["status"]
        for binding in result["selection_source_bindings"].values():
            if binding["status"] == "SELECTION_SOURCE_IDENTITY_BOUND_TO_TRIO_AND_OWNER_HISTORY":
                binding["status"] = "SELECTION_SOURCE_IDENTITY_OWNER_OR_TRIO_UNBOUND"
    return result
