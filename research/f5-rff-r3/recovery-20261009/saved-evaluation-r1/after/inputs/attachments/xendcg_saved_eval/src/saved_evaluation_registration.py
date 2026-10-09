"""R2 profile over the existing official no-fit registry owner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


NO_FIT_KIND = "NO_FIT_ENGINEERING_CANARY"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def event_profile(binding: Mapping[str, Any]) -> dict[str, str]:
    return {
        "track_id": "HK_BURST_F5_FULL_HISTORY_RESEARCH",
        "route_id": str(binding["route_id"]),
        "registration_mode": "LIVE_EXECUTION",
        "start_stage": "SAVED_EVALUATION_R2_RUN_STARTED",
        "terminal_stage": "SAVED_EVALUATION_R2_TERMINAL",
        "occurred_at_reason": "LIVE_EXECUTION_UTC",
        "baseline_id": "F5_FULL64_ORIGINAL_PLUS_PATH_BINARY_2024",
        "one_variable": "saved_prediction_full2024_evaluation_only",
        "signal_scope": "CANDIDATE_01_SAVED_PREDICTION_SEAL",
        "target_scope": "EXPOSED_2024_FROZEN_LABELS_246_SESSIONS",
        "device": "CPU_RESEARCH_ONLY",
        "evidence_level": "ENGINEERING_CANARY_ONLY",
    }


def _route_events(events: list[dict[str, Any]], route_id: str) -> list[dict[str, Any]]:
    return [row for row in events if row.get("route_id") == route_id or row.get("experiment_id") == route_id]


def build_official_adapter_class(
    adapter_module: Any, *, binding: Mapping[str, Any], run_spec_path: Path,
    input_binding_path: Path, run_spec_sha256: str, input_binding_sha256: str,
):
    """Subclass only the existing official adapter's current R2 event profile.

    The base adapter still owns the registry lock, canonical builder, validator,
    fsync, and readback. This subclass adds immutable-prefix checks specific to
    the current execution and projects the observed evaluation exposure/metrics.
    """
    route_id = str(binding["route_id"])
    execution_id = str(binding["execution_id"])
    expected_registry_sha = str(binding["official_registry_sha256_before_start"])
    expected_route = list(binding["expected_route_event_sha256_before_start"])
    registry_path = Path(binding["official_registry_path"]).resolve()
    start_receipt_path = Path(binding["start_receipt_path"]).resolve()

    class SavedEvaluationR2OfficialAdapter(adapter_module.OfficialRegistryAdapter):
        def _verify_contract_snapshots(self) -> None:
            if sha256_file(run_spec_path) != run_spec_sha256:
                raise RuntimeError("SAVED_EVAL_R2_RUN_SPEC_CHANGED")
            if sha256_file(input_binding_path) != input_binding_sha256:
                raise RuntimeError("SAVED_EVAL_R2_INPUT_BINDING_CHANGED")
            _verify_files(binding, ("code_files", "executable_helpers", "official_helpers"))

        def claim_run_started(self, event: Mapping[str, Any], *, max_real_fit_debits: int) -> None:
            with self._locked():
                raw, events = self._read_validated()
                if sha256_bytes(raw) != expected_registry_sha or sha256_file(registry_path) != expected_registry_sha:
                    raise RuntimeError("SAVED_EVAL_R2_REGISTRY_PREFIX_CHANGED")
                self._verify_contract_snapshots()
                current_route = _route_events(events, route_id)
                if [row.get("event_sha256") for row in current_route] != expected_route:
                    raise RuntimeError("SAVED_EVAL_R2_ROUTE_PREFIX_MISMATCH")
                if any(str(row.get("execution_id")) == execution_id for row in events):
                    raise RuntimeError("SAVED_EVAL_R2_EXECUTION_ID_ALREADY_REGISTERED")
                # The existing ExecutionGuard.claim_no_fit API supplies these
                # accounting values as top-level fields.  The official adapter's
                # _event_spec projects them into registry deterministic_metrics.
                # Validate the owner API shape here instead of requiring a
                # second, incompatible nested representation.
                planned_real_fit_count = event.get("planned_real_fit_count")
                real_fit_budget_debit = event.get("real_fit_budget_debit")
                if (
                    max_real_fit_debits != 1
                    or event.get("experiment_id") != route_id
                    or event.get("execution_id") != execution_id
                    or event.get("execution_kind") != NO_FIT_KIND
                    or type(planned_real_fit_count) is not int
                    or planned_real_fit_count != 0
                    or type(real_fit_budget_debit) is not int
                    or real_fit_budget_debit != 0
                    or event.get("contract_sha256") != run_spec_sha256
                    or event.get("input_binding_sha256") != input_binding_sha256
                ):
                    raise RuntimeError("SAVED_EVAL_R2_START_IDENTITY_OR_ZERO_DEBIT_MISMATCH")
                self._append_unlocked(raw, events, self._event_spec(event, event_type="RUN_STARTED"))

        def terminalize(self, claim: Any, event: Mapping[str, Any]) -> None:
            with self._locked():
                raw, events = self._read_validated()
                self._verify_contract_snapshots()
                starts = [row for row in events if row.get("execution_id") == execution_id and row.get("event_type") == "RUN_STARTED"]
                terminals = [row for row in events if row.get("execution_id") == execution_id and row.get("event_type") == "TERMINAL"]
                if len(starts) != 1 or terminals:
                    raise RuntimeError("SAVED_EVAL_R2_TERMINAL_LIFECYCLE_INVALID")
                start = starts[0]
                for field in ("experiment_id", "execution_id", "arm", "contract_sha256", "input_binding_sha256"):
                    if start.get(field) != getattr(claim, field) or event.get(field) != getattr(claim, field):
                        raise RuntimeError(f"SAVED_EVAL_R2_TERMINAL_IDENTITY_MISMATCH:{field}")
                metrics = start.get("deterministic_metrics") or {}
                if (metrics.get("planned_real_fit_count") != 0
                        or metrics.get("real_fit_budget_debit") != 0
                        or event.get("execution_kind") != NO_FIT_KIND
                        or event.get("planned_real_fit_count") != 0
                        or event.get("real_fit_budget_debit") != 0):
                    raise RuntimeError("SAVED_EVAL_R2_TERMINAL_NOT_ZERO_DEBIT")
                if event.get("terminal_status") not in {"COMPLETED", "CANNOT_CONFIRM"}:
                    raise RuntimeError("SAVED_EVAL_R2_TERMINAL_STATUS_INVALID")

                route_sha = [row.get("event_sha256") for row in _route_events(events, route_id)]
                if route_sha != expected_route + [start.get("event_sha256")]:
                    raise RuntimeError("SAVED_EVAL_R2_ROUTE_CHANGED_AFTER_START")
                receipt = None
                if start_receipt_path.is_file():
                    receipt = json.loads(start_receipt_path.read_text(encoding="utf-8"))
                    if receipt.get("start_event_sha256") != start.get("event_sha256"):
                        raise RuntimeError("SAVED_EVAL_R2_START_RECEIPT_EVENT_MISMATCH")
                    if receipt.get("official_registry_sha256_after_start") != sha256_bytes(raw):
                        raise RuntimeError("SAVED_EVAL_R2_REGISTRY_CHANGED_AFTER_START")
                    for key, expected in (
                        ("execution_id", execution_id),
                        ("route_id", route_id),
                        ("run_spec_sha256", run_spec_sha256),
                        ("input_binding_sha256", input_binding_sha256),
                    ):
                        if receipt.get(key) != expected:
                            raise RuntimeError(f"SAVED_EVAL_R2_START_RECEIPT_IDENTITY_MISMATCH:{key}")
                elif event.get("terminal_status") != "CANNOT_CONFIRM":
                    raise RuntimeError("SAVED_EVAL_R2_START_RECEIPT_MISSING")

                spec = self._event_spec(event, event_type="TERMINAL")
                if receipt is None:
                    spec["stop_reason"] = "START_RECEIPT_MISSING_AFTER_DURABLE_START"
                self._append_unlocked(raw, events, spec)

        def _event_spec(self, event: Mapping[str, Any], *, event_type: str) -> dict[str, Any]:
            spec = super()._event_spec(event, event_type=event_type)
            spec["code_sha256"] = str(binding["code_sha256"])
            metrics = dict(spec.get("deterministic_metrics") or {})
            reasons = dict((spec.get("input_identity") or {}).get("null_reasons") or {})
            if event_type == "RUN_STARTED":
                spec["truth_access"] = "NOT_READ"
                spec["sealed_status"] = "NOT_ENTERED"
                metrics["truth_positive_denominator"] = None
                metrics["selection_slots"] = None
                reasons["deterministic_metrics.truth_positive_denominator"] = "TRUTH_NOT_READ_AT_RUN_START"
                reasons["deterministic_metrics.selection_slots"] = "NOT_MEASURED_AT_RUN_START"
            else:
                spec["truth_access"] = str(event["truth_access"])
                spec["sealed_status"] = str(event["sealed_status"])
                spec["evaluation_metrics"] = dict(event["evaluation_metrics"])
                metrics["truth_positive_denominator"] = event.get("truth_positive_denominator")
                metrics["selection_slots"] = event.get("selection_slots")
                metrics["evaluation_metrics"] = dict(event["evaluation_metrics"])
                metrics["fit_call_entered"] = event.get("fit_call_entered")
                metrics["real_fit_returned_count"] = event.get("real_fit_returned_count")
                for field in ("fit_call_entered", "real_fit_returned_count"):
                    if metrics[field] is None:
                        reasons[f"deterministic_metrics.{field}"] = "WORKER_STATUS_MISSING_OR_INVALID"
                observed = event.get("observed_worker_accounting")
                if isinstance(observed, Mapping):
                    metrics["observed_worker_accounting"] = dict(observed)
                    if observed.get("status") != "KNOWN":
                        reasons["deterministic_metrics.observed_worker_accounting"] = "WORKER_STATUS_MISSING_OR_INVALID"
                if metrics["truth_positive_denominator"] is None:
                    reasons["deterministic_metrics.truth_positive_denominator"] = str(event.get("truth_denominator_null_reason", "METRICS_NOT_VALIDATED"))
                if metrics["selection_slots"] is None:
                    reasons["deterministic_metrics.selection_slots"] = str(event.get("selection_slots_null_reason", "METRICS_NOT_VALIDATED"))
            spec["deterministic_metrics"] = metrics
            identity = dict(spec.get("input_identity") or {})
            identity["null_reasons"] = reasons
            spec["input_identity"] = identity
            return spec

    return SavedEvaluationR2OfficialAdapter


def _verify_files(binding: Mapping[str, Any], categories: tuple[str, ...]) -> None:
    for category in categories:
        for name, item in binding.get(category, {}).items():
            path = Path(item["path"])
            if not path.is_file() or sha256_file(path) != item["sha256"]:
                raise RuntimeError(f"SAVED_EVAL_R2_BOUND_FILE_SHA_MISMATCH:{category}:{name}")
