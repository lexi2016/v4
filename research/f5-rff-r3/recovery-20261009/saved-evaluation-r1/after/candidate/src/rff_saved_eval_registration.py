"""RFF saved-evaluation profile over the existing official registry owner.

The original adapter owns locking, canonical materialization, compatibility
validation and durable append. This module adds a frozen RFF scope; it never
writes registry bytes itself, consumes a fit debit, or retries an append.

The guard's required zero-activity fields describe the evaluation-only contract.
Actual worker observations are recorded separately and may be unknown. A guard
accounting summary therefore describes structural budget accounting; callers
must also inspect ``actual_fit_count_status`` and ``observed_worker_accounting``
before asserting any observed execution count.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROUTE_ID = "F5_FULL64_RFF_LOGISTIC_R1_20260927"
CANDIDATE_EXECUTION_ID = "F5_FULL64_RFF_LOGISTIC_R1_20260927_RESUME_20260928_01"
NO_FIT_KIND = "NO_FIT_ENGINEERING_CANARY"
COUNTERS = ("fit_calls", "real_fit_returned_count", "predict_calls",
            "control_fit_calls", "control_predict_calls", "calibrator_fit_calls", "model_load_calls")
ZERO_AUTHORIZATIONS = ("fit_calls_authorized", "predict_calls_authorized",
                       "control_fit_calls_authorized", "control_predict_calls_authorized",
                       "calibrator_fit_calls_authorized", "model_load_calls_authorized")
SOURCE_CATEGORIES = ("code_files", "executable_helpers", "official_helpers",
                     "metadata_files", "authorization_records")
SAFETY = {"research_only": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def event_profile(binding: Mapping[str, Any]) -> dict[str, str]:
    if binding.get("route_id") != ROUTE_ID:
        raise RuntimeError("RFF_SAVED_EVAL_ROUTE_ID_MISMATCH")
    if binding.get("candidate_execution_id") != CANDIDATE_EXECUTION_ID:
        raise RuntimeError("RFF_SAVED_EVAL_CANDIDATE_IDENTITY_MISMATCH")
    return {
        "track_id": "HK_BURST_F5_FULL_HISTORY_RESEARCH",
        "route_id": ROUTE_ID,
        "registration_mode": "LIVE_EXECUTION",
        "start_stage": "RFF_SAVED_EVALUATION_RUN_STARTED",
        "terminal_stage": "RFF_SAVED_EVALUATION_TERMINAL",
        "occurred_at_reason": "LIVE_EXECUTION_UTC",
        "baseline_id": "F5_FULL64_ORIGINAL_PLUS_PATH_BINARY_2024",
        "one_variable": "rff_saved_prediction_full2024_evaluation_only",
        "signal_scope": f"SAVED_PREDICTION_SEAL:{CANDIDATE_EXECUTION_ID}",
        "target_scope": "EXPOSED_2024_FROZEN_LABELS_246_SESSIONS",
        "device": "CPU_RESEARCH_ONLY",
        "evidence_level": "DIRECTION_ONLY",
    }


def _route_events(events: list[dict[str, Any]], route_id: str) -> list[dict[str, Any]]:
    return [row for row in events
            if row.get("route_id") == route_id or row.get("experiment_id") == route_id]


def _source_drift(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Compare current bytes with the frozen manifest without loading modules."""
    changed = []
    for category in SOURCE_CATEGORIES:
        for name, item in binding.get(category, {}).items():
            path = Path(item["path"])
            observed_sha = None
            error = None
            try:
                observed_sha = sha256_file(path) if path.is_file() else None
                state = "MISSING" if observed_sha is None else "SHA_MISMATCH"
            except OSError as exc:
                state = "READ_ERROR"
                error = {"type": type(exc).__name__, "message": str(exc)}
            if observed_sha != item["sha256"]:
                detail = {"category": category, "name": name, "path": str(path),
                          "bound_sha256": item["sha256"], "observed_sha256": observed_sha,
                          "state": state}
                if error is not None:
                    detail["error"] = error
                changed.append(detail)
    return {"status": "DRIFT_DETECTED" if changed else "UNCHANGED", "files": changed}


def _check_no_observed_activity(value: Mapping[str, Any]) -> None:
    for key in COUNTERS:
        item = value.get(key)
        if item is not None and (type(item) is not int or item != 0):
            raise RuntimeError(f"RFF_SAVED_EVAL_OBSERVED_ACTIVITY_VIOLATES_ZERO_CONTRACT:{key}")
    for key in ("fit_call_entered", "candidate_model_loaded"):
        item = value.get(key)
        if item is not None and item is not False:
            raise RuntimeError(f"RFF_SAVED_EVAL_OBSERVED_ACTIVITY_VIOLATES_ZERO_CONTRACT:{key}")


def _observed_accounting(event: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    _check_no_observed_activity(event)
    supplied = event.get("observed_worker_accounting")
    observed = dict(supplied) if isinstance(supplied, Mapping) else {
        key: event.get(key) for key in (*COUNTERS, "fit_call_entered", "candidate_model_loaded")
    }
    _check_no_observed_activity(observed)
    zero = (all(type(observed.get(key)) is int and observed[key] == 0 for key in COUNTERS)
            and observed.get("fit_call_entered") is False
            and observed.get("candidate_model_loaded") is False)
    known = zero and observed.get("status", "KNOWN") in {"KNOWN", "KNOWN_NOT_LAUNCHED"}
    for key in (*COUNTERS, "fit_call_entered", "candidate_model_loaded"):
        observed.setdefault(key, None)
    observed["status"] = observed.get("status", "KNOWN") if known else "UNKNOWN"
    return observed, known


def build_official_adapter_class(
    adapter_module: Any, *, binding: Mapping[str, Any], run_spec_path: Path,
    input_binding_path: Path, run_spec_sha256: str, input_binding_sha256: str,
):
    """Create the RFF route profile without modifying the official owner.

    Source drift prevents success, but an already claimed run may close as
    CANNOT_CONFIRM with complete bound/observed drift evidence. RUN_SPEC and
    INPUT_BINDING identities never relax. Append errors always propagate; the
    owner may inspect the durable chain, and must never blindly retry.
    """
    frozen = json.loads(canonical_bytes(dict(binding)))
    profile = event_profile(frozen)
    route_id = frozen["route_id"]
    execution_id = frozen["execution_id"]
    if not isinstance(execution_id, str) or not execution_id or execution_id == CANDIDATE_EXECUTION_ID:
        raise RuntimeError("RFF_SAVED_EVAL_NEW_EXECUTION_ID_REQUIRED")
    registry_path = Path(frozen["official_registry_path"]).resolve()
    start_receipt_path = Path(frozen["start_receipt_path"]).resolve()
    run_spec_path = Path(run_spec_path).resolve()
    input_binding_path = Path(input_binding_path).resolve()
    expected_registry_sha = frozen["official_registry_sha256_before_start"]
    expected_previous_sha = frozen["expected_previous_event_sha256"]
    expected_route = frozen["expected_route_event_sha256_before_start"]

    class RffSavedEvaluationOfficialAdapter(adapter_module.OfficialRegistryAdapter):
        def __init__(self, **kwargs):
            if kwargs.get("event_profile") is None:
                kwargs["event_profile"] = profile
            elif dict(kwargs["event_profile"]) != profile:
                raise RuntimeError("RFF_SAVED_EVAL_EVENT_PROFILE_MISMATCH")
            super().__init__(**kwargs)
            if (self.registry_path != registry_path or self.contract_path != run_spec_path
                    or self.input_binding_path != input_binding_path):
                raise RuntimeError("RFF_SAVED_EVAL_ADAPTER_PATH_IDENTITY_MISMATCH")
            for key, actual in (("builder", self.builder_path), ("validator", self.validator_path)):
                if actual != Path(frozen["official_helpers"][key]["path"]).resolve():
                    raise RuntimeError(f"RFF_SAVED_EVAL_ADAPTER_HELPER_PATH_MISMATCH:{key}")
            self.authorization_records: dict[str, Any] = {}
            self._authorization_records_snapshot: dict[str, Any] | None = None

        def _verify_core_snapshots(self) -> None:
            if not run_spec_path.is_file() or sha256_file(run_spec_path) != run_spec_sha256:
                raise RuntimeError("RFF_SAVED_EVAL_RUN_SPEC_CHANGED")
            if not input_binding_path.is_file() or sha256_file(input_binding_path) != input_binding_sha256:
                raise RuntimeError("RFF_SAVED_EVAL_INPUT_BINDING_CHANGED")
            if json.loads(input_binding_path.read_bytes()) != frozen:
                raise RuntimeError("RFF_SAVED_EVAL_BOUND_BINDING_OBJECT_MISMATCH")
            if sha256_bytes(canonical_bytes(frozen["code_files"])) != frozen["code_sha256"]:
                raise RuntimeError("RFF_SAVED_EVAL_CODE_MANIFEST_SHA_MISMATCH")
            spec = json.loads(run_spec_path.read_bytes())
            if (any(type(spec.get(key)) is not int or spec[key] != 0 for key in ZERO_AUTHORIZATIONS)
                    or spec.get("candidate_model_load_authorized") is not False):
                raise RuntimeError("RFF_SAVED_EVAL_SPEC_NOT_ZERO_ACTIVITY")

        def _authorization_snapshot(self) -> dict[str, Any]:
            records = (self._authorization_records_snapshot
                       if self._authorization_records_snapshot is not None else self.authorization_records)
            if not isinstance(records, Mapping):
                raise RuntimeError("RFF_SAVED_EVAL_AUTHORIZATION_RECORDS_NOT_OBJECT")
            return json.loads(canonical_bytes(dict(records)))

        def source_drift(self) -> dict[str, Any]:
            return _source_drift(dict(frozen, authorization_records=self._authorization_snapshot()))

        def _verify_contract_snapshots(self) -> dict[str, Any]:
            """Keep core bytes exact and return explicit dependency/authority drift."""
            self._verify_core_snapshots()
            return self.source_drift()

        def claim_run_started(self, event: Mapping[str, Any], *, max_real_fit_debits: int) -> None:
            with self._locked():
                raw, events = self._read_validated()
                if any(row.get("execution_id") == execution_id for row in events):
                    raise RuntimeError("RFF_SAVED_EVAL_EXECUTION_ID_ALREADY_REGISTERED")
                if sha256_bytes(raw) != expected_registry_sha or sha256_file(registry_path) != expected_registry_sha:
                    raise RuntimeError("RFF_SAVED_EVAL_REGISTRY_PREFIX_CHANGED")
                # The parent sets release/review records before claiming. Freeze
                # their declarations in the same lock as the durable start.
                if self._authorization_records_snapshot is None:
                    self._authorization_records_snapshot = self._authorization_snapshot()
                drift = self._verify_contract_snapshots()
                if drift["files"]:
                    raise RuntimeError("RFF_SAVED_EVAL_BOUND_SOURCE_DRIFT:" + canonical_bytes(drift).decode())
                if [row.get("event_sha256") for row in _route_events(events, route_id)] != expected_route:
                    raise RuntimeError("RFF_SAVED_EVAL_ROUTE_PREFIX_MISMATCH")
                if not events or events[-1].get("event_sha256") != expected_previous_sha:
                    raise RuntimeError("RFF_SAVED_EVAL_PREVIOUS_EVENT_SHA_MISMATCH")
                if (type(max_real_fit_debits) is not int or max_real_fit_debits != 1
                        or event.get("event_type") != "RUN_STARTED"
                        or event.get("experiment_id") != route_id
                        or event.get("execution_id") != execution_id
                        or not event.get("arm")
                        or event.get("execution_kind") != NO_FIT_KIND
                        or event.get("contract_sha256") != run_spec_sha256
                        or event.get("input_binding_sha256") != input_binding_sha256
                        or any(type(event.get(key)) is not int or event[key] != 0
                               for key in ("planned_real_fit_count", "real_fit_budget_debit"))):
                    raise RuntimeError("RFF_SAVED_EVAL_START_IDENTITY_OR_ZERO_DEBIT_MISMATCH")
                self._append_unlocked(raw, events, self._event_spec(event, event_type="RUN_STARTED"))
                after_raw, after = self._read_validated()
                if (not after_raw.startswith(raw) or len(after) != len(events) + 1
                        or after[-1].get("registry_event_id") != f"{execution_id}_RUN_STARTED"):
                    raise RuntimeError("RFF_SAVED_EVAL_START_DURABLE_READBACK_MISMATCH")

        def terminalize(self, claim: Any, event: Mapping[str, Any]) -> None:
            with self._locked():
                raw, events = self._read_validated()
                drift = self._verify_contract_snapshots()
                starts = [row for row in events if row.get("execution_id") == execution_id
                          and row.get("event_type") == "RUN_STARTED"]
                terminals = [row for row in events if row.get("execution_id") == execution_id
                             and row.get("event_type") == "TERMINAL"]
                if len(starts) != 1 or terminals:
                    raise RuntimeError("RFF_SAVED_EVAL_TERMINAL_LIFECYCLE_INVALID")
                start = starts[0]
                if start.get("authorization_records", {}) != self._authorization_snapshot():
                    raise RuntimeError("RFF_SAVED_EVAL_START_AUTHORIZATION_IDENTITY_MISMATCH")
                for key in ("experiment_id", "execution_id", "arm", "contract_sha256", "input_binding_sha256"):
                    if start.get(key) != getattr(claim, key) or event.get(key) != getattr(claim, key):
                        raise RuntimeError(f"RFF_SAVED_EVAL_TERMINAL_IDENTITY_MISMATCH:{key}")
                if (event.get("event_type") != "TERMINAL" or event.get("execution_kind") != NO_FIT_KIND
                        or getattr(claim, "execution_kind", None) != NO_FIT_KIND
                        or type(getattr(claim, "real_fit_budget_debit", None)) is not int
                        or getattr(claim, "real_fit_budget_debit", None) != 0
                        or any(type(event.get(key)) is not int or event[key] != 0
                               or type((start.get("deterministic_metrics") or {}).get(key)) is not int
                               or start["deterministic_metrics"][key] != 0
                               for key in ("planned_real_fit_count", "real_fit_budget_debit"))):
                    raise RuntimeError("RFF_SAVED_EVAL_TERMINAL_NOT_ZERO_DEBIT")
                status = event.get("terminal_status")
                if status not in {"COMPLETED", "CANNOT_CONFIRM"}:
                    raise RuntimeError("RFF_SAVED_EVAL_TERMINAL_STATUS_INVALID")
                if [row.get("event_sha256") for row in _route_events(events, route_id)] != expected_route + [start["event_sha256"]]:
                    raise RuntimeError("RFF_SAVED_EVAL_ROUTE_CHANGED_AFTER_START")
                start_index = events.index(start)
                prefix = b"".join(raw.splitlines(keepends=True)[:start_index])
                if (len(events) != start_index + 1 or sha256_bytes(prefix) != expected_registry_sha
                        or start.get("previous_event_sha256") != expected_previous_sha):
                    raise RuntimeError("RFF_SAVED_EVAL_REGISTRY_CHANGED_AFTER_START")
                missing_receipt = not start_receipt_path.is_file()
                if missing_receipt:
                    if status != "CANNOT_CONFIRM":
                        raise RuntimeError("RFF_SAVED_EVAL_START_RECEIPT_MISSING")
                else:
                    receipt = json.loads(start_receipt_path.read_bytes())
                    expected_receipt = {
                        "status": "RUN_STARTED_DURABLE", "execution_id": execution_id,
                        "candidate_execution_id": CANDIDATE_EXECUTION_ID, "route_id": route_id,
                        "run_spec_sha256": run_spec_sha256, "input_binding_sha256": input_binding_sha256,
                        "source_code_sha256": frozen["code_sha256"], "start_event_sha256": start["event_sha256"],
                        "official_registry_sha256_after_start": sha256_bytes(raw),
                    }
                    if not isinstance(receipt, dict) or any(receipt.get(key) != value for key, value in expected_receipt.items()):
                        raise RuntimeError("RFF_SAVED_EVAL_START_RECEIPT_IDENTITY_MISMATCH")
                if drift["files"] and status != "CANNOT_CONFIRM":
                    raise RuntimeError("RFF_SAVED_EVAL_SOURCE_DRIFT_REQUIRES_CANNOT_CONFIRM:" + canonical_bytes(drift).decode())
                observed, known = _observed_accounting(event)
                if status == "COMPLETED" and (not known or observed["status"] != "KNOWN"):
                    raise RuntimeError("RFF_SAVED_EVAL_COMPLETED_REQUIRES_OBSERVED_ZERO_ACTIVITY")
                projected = dict(event, observed_worker_accounting=observed, source_drift=drift)
                spec = self._event_spec(projected, event_type="TERMINAL")
                if missing_receipt:
                    spec["stop_reason"] = "START_RECEIPT_MISSING_AFTER_DURABLE_START"
                self._append_unlocked(raw, events, spec)
                after_raw, after = self._read_validated()
                if (not after_raw.startswith(raw) or len(after) != len(events) + 1
                        or after[-1].get("registry_event_id") != f"{execution_id}_TERMINAL"
                        or after[-1].get("decision") != status):
                    raise RuntimeError("RFF_SAVED_EVAL_TERMINAL_DURABLE_READBACK_MISMATCH")

        def _event_spec(self, event: Mapping[str, Any], *, event_type: str) -> dict[str, Any]:
            _check_no_observed_activity(event)
            for key, expected in SAFETY.items():
                if key in event and event[key] is not expected:
                    raise RuntimeError(f"RFF_SAVED_EVAL_SAFETY_FLAG_MISMATCH:{key}")
            if event.get("promotion_now", False) is not False:
                raise RuntimeError("RFF_SAVED_EVAL_SAFETY_FLAG_MISMATCH:promotion_now")
            spec = super()._event_spec(event, event_type=event_type)
            spec.update(code_sha256=frozen["code_sha256"], candidate_execution_id=CANDIDATE_EXECUTION_ID,
                        evidence_ceiling="DIRECTION_ONLY", promotion_now=False,
                        route_truth_status="EXPOSED_2024_AFTER_CANDIDATE_PREDICTION_SEAL",
                        authorization_records=self._authorization_snapshot())
            metrics = dict(spec.get("deterministic_metrics") or {})
            reasons = dict((spec.get("input_identity") or {}).get("null_reasons") or {})
            metrics.update(execution_kind=NO_FIT_KIND, planned_real_fit_count=0,
                           real_fit_budget_debit=0, fit_call_entered=False, real_fit_returned_count=0,
                           fit_accounting_basis="STATIC_EVALUATION_ONLY_CONTRACT",
                           guard_accounting_scope="STRUCTURAL_ZERO_DEBIT_NOT_WORKER_OBSERVATION")
            if event_type == "RUN_STARTED":
                spec["truth_access"] = "NOT_READ_IN_THIS_EVALUATION"
                spec["sealed_status"] = "EXPOSED_2024_CURRENT_EVALUATION_NOT_STARTED"
                metrics.update(truth_positive_denominator=None, selection_slots=None,
                               truth_accounting={"decode_attempts": 0, "decode_completed": 0})
                reasons["deterministic_metrics.truth_positive_denominator"] = "TRUTH_NOT_READ_AT_RUN_START"
                reasons["deterministic_metrics.selection_slots"] = "NOT_MEASURED_AT_RUN_START"
            else:
                observed, known = _observed_accounting(event)
                drift = dict(event["source_drift"])
                evaluation = dict(event.get("evaluation_metrics") or {})
                completed = event["terminal_status"] == "COMPLETED"
                if completed and evaluation.get("metrics_computed") is not True:
                    raise RuntimeError("RFF_SAVED_EVAL_COMPLETED_REQUIRES_VALIDATED_METRICS")
                if not completed and evaluation.get("metrics_computed") is True:
                    evaluation = {"metrics_computed": False, "reported_metrics_not_accepted": True,
                                  "reported_metrics_sha256": evaluation.get("metrics_sha256")}
                spec.update(truth_access=str(event["truth_access"]), sealed_status=str(event["sealed_status"]),
                            evaluation_metrics=evaluation)
                metrics.update(
                    truth_positive_denominator=event.get("truth_positive_denominator") if completed else None,
                    selection_slots=event.get("selection_slots") if completed else None,
                    evaluation_metrics=evaluation, source_drift=drift,
                    observed_worker_accounting=observed,
                    actual_fit_count_status="OBSERVED_ZERO_ACTIVITY" if known else "CANNOT_CONFIRM_WORKER_OBSERVATION_MISSING",
                    truth_accounting=dict(event.get("truth_accounting") or {}),
                )
                if not known:
                    reasons["deterministic_metrics.observed_worker_accounting"] = "WORKER_OBSERVATION_MISSING_OR_INVALID"
                for key in ("truth_positive_denominator", "selection_slots"):
                    if metrics[key] is None:
                        reasons[f"deterministic_metrics.{key}"] = "METRICS_NOT_VALIDATED"
                if drift["files"]:
                    spec["stop_reason"] = "BOUND_SOURCE_DRIFT_AFTER_DURABLE_START"
                    unavailable = {str(Path(item["path"]).resolve()) for item in drift["files"]
                                   if item["state"] in {"MISSING", "READ_ERROR"}}
                    artifacts = [path for path in spec["artifact_paths"]
                                 if str(Path(path).resolve()) not in unavailable]
                    spec["artifact_paths"] = artifacts
                    spec["artifact_path"] = artifacts
                elif event.get("stop_reason"):
                    spec["stop_reason"] = str(event["stop_reason"])
            spec["deterministic_metrics"] = metrics
            identity = dict(spec.get("input_identity") or {})
            identity.update(candidate_execution_id=CANDIDATE_EXECUTION_ID, null_reasons=reasons)
            spec["input_identity"] = identity
            return spec

    return RffSavedEvaluationOfficialAdapter
