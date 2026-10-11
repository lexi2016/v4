"""Thin adapter from :mod:`execution_guard_core` to the official registry.

The adapter owns no second ledger.  It reuses the project's official builder
and append-compatibility validator while holding the existing registry lock for
the complete check, materialize, candidate validation, append, flush, and
fsync sequence.  It is intentionally separate from the parity runner so the
guard tests can use an in-memory stub and never start a model call.
"""
from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping, Sequence

from execution_guard_core import (
    DuplicateExecutionId,
    ExecutionClaim,
    NO_FIT_ENGINEERING_KIND,
    REAL_FIT_EXECUTION_KIND,
    RealFitBudgetExceeded,
    RegistryIntegrityError,
    TerminalizationRejected,
)


ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
REGISTRY_PATH = ROOT / "contracts" / "EXPERIMENT_REGISTRY.jsonl"
BUILDER_PATH = ROOT / "contracts" / "build_experiment_registry_backfill_20260821.py"
VALIDATOR_PATH = ROOT / "contracts" / "validate_experiment_registry_append_compatibility_v1.py"

DEFAULT_EVENT_PROFILE = {
    "track_id": "HKCONNECT_OPENING_STAGE11_CLOSED_LOOP_RESEARCH",
    "route_id": "HKCONNECT_PRICE_SEMANTICS_V2_CONTROLLED_TRAINING",
    "registration_mode": "LIVE_EXECUTION",
    "start_stage": "CONTROLLED_TRAINING_RUN_STARTED",
    "terminal_stage": "CONTROLLED_TRAINING_TERMINAL",
    "occurred_at_reason": "LIVE_EXECUTION_UTC",
    "baseline_id": "HKCONNECT_PRICE_SEMANTICS_V2_ZERO_LABEL_PARITY_20260919",
    "one_variable": "controlled_real_fit_budget_guard",
    "signal_scope": "CONTROLLED_TRAINING_ONLY",
    "target_scope": "CONTROLLED_TRAINING_ONLY",
    "device": "CPU_RESEARCH_ONLY",
    "evidence_level": "ENGINEERING_CANARY_ONLY",
}
_REQUIRED_PROFILE_FIELDS = frozenset(DEFAULT_EVENT_PROFILE)


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OfficialRegistryAdapter:
    """Atomic lifecycle adapter for one experiment's real-fit guard.

    ``claim_run_started`` and ``terminalize`` both re-read the official
    registry while holding the same OS lock.  A caller cannot perform a stale
    list-then-append sequence through this class.
    """

    def __init__(
        self,
        *,
        registry_path: Path = REGISTRY_PATH,
        contract_path: Path | None = None,
        input_binding_path: Path | None = None,
        artifact_paths: Sequence[Path] = (),
        builder_path: Path = BUILDER_PATH,
        validator_path: Path = VALIDATOR_PATH,
        event_profile: Mapping[str, str] | None = None,
    ) -> None:
        self.registry_path = Path(registry_path).resolve()
        self.lock_path = self.registry_path.with_name(f".{self.registry_path.name}.lock")
        self.contract_path = Path(contract_path).resolve() if contract_path else None
        self.input_binding_path = Path(input_binding_path).resolve() if input_binding_path else None
        self.artifact_paths = tuple(Path(path).resolve() for path in artifact_paths)
        self.builder_path = Path(builder_path).resolve()
        self.validator_path = Path(validator_path).resolve()
        self.event_profile = self._validated_profile(event_profile)
        self.builder = _load_module(self.builder_path, "hkconnect_zero_label_official_builder")
        self.validator = _load_module(self.validator_path, "hkconnect_zero_label_official_validator")

    def list_events(self, experiment_id: str) -> Sequence[Mapping[str, Any]]:
        with self._locked():
            _, events = self._read_validated()
            normalized: list[dict[str, Any]] = []
            for event in events:
                if event.get("experiment_id") != experiment_id:
                    continue
                if event.get("event_type") not in {"RUN_STARTED", "TERMINAL"}:
                    continue
                item = dict(event)
                metrics = event.get("deterministic_metrics")
                if isinstance(metrics, Mapping):
                    for field in (
                        "execution_kind",
                        "planned_real_fit_count",
                        "real_fit_budget_debit",
                        "real_fit_returned_count",
                        "fit_call_entered",
                    ):
                        if field in metrics:
                            item[field] = metrics[field]
                identity = event.get("input_identity")
                if "input_binding_sha256" not in item and isinstance(identity, Mapping):
                    binding = identity.get("input_binding_sha256")
                    if binding:
                        item["input_binding_sha256"] = binding
                if event.get("event_type") == "TERMINAL":
                    item["terminal_status"] = event.get("decision")
                normalized.append(item)
            return normalized

    def claim_run_started(self, event: Mapping[str, Any], *, max_real_fit_debits: int) -> None:
        """Atomically check identity/budget, append, flush, and fsync a start."""

        with self._locked():
            raw, events = self._read_validated()
            execution_id = self._required(event, "execution_id")
            experiment_id = self._required(event, "experiment_id")
            if any(str(existing.get("execution_id")) == execution_id for existing in events):
                raise DuplicateExecutionId(f"execution_id already exists: {execution_id}")
            debits = sum(
                int(self._metric(existing, "real_fit_budget_debit") or 0)
                for existing in events
                if existing.get("experiment_id") == experiment_id
                and existing.get("event_type") == "RUN_STARTED"
            )
            requested_debit = self._metric(event, "real_fit_budget_debit")
            execution_kind = str(self._metric(event, "execution_kind") or REAL_FIT_EXECUTION_KIND)
            planned = self._metric(event, "planned_real_fit_count")
            if isinstance(requested_debit, bool) or requested_debit not in (0, 1):
                raise RegistryIntegrityError("RUN_STARTED real_fit_budget_debit must be 0 or 1")
            if execution_kind == REAL_FIT_EXECUTION_KIND:
                if requested_debit != 1 or planned not in (None, 1):
                    raise RegistryIntegrityError("real-fit RUN_STARTED accounting is invalid")
            elif execution_kind == NO_FIT_ENGINEERING_KIND:
                if requested_debit != 0 or planned not in (None, 0):
                    raise RegistryIntegrityError("no-fit RUN_STARTED accounting is invalid")
            else:
                raise RegistryIntegrityError(f"unsupported execution_kind: {execution_kind}")
            # A zero-debit engineering claim remains valid after the real-fit
            # budget is exhausted.  Only a positive debit consumes the cap;
            # synthetic/no-fit lifecycle evidence must still be terminalized.
            if requested_debit and debits + requested_debit > max_real_fit_debits:
                raise RealFitBudgetExceeded(f"real-fit debit budget exhausted: {debits}/{max_real_fit_debits}")
            self._append_unlocked(raw, events, self._event_spec(event, event_type="RUN_STARTED"))

    def terminalize(self, claim: ExecutionClaim, event: Mapping[str, Any]) -> None:
        """Atomically validate one start/identity and append one terminal."""

        with self._locked():
            raw, events = self._read_validated()
            starts = [
                existing
                for existing in events
                if existing.get("event_type") == "RUN_STARTED"
                and existing.get("experiment_id") == claim.experiment_id
                and existing.get("execution_id") == claim.execution_id
            ]
            if len(starts) != 1:
                raise RegistryIntegrityError(
                    f"terminalization requires exactly one durable start: {claim.execution_id}"
                )
            start = starts[0]
            for field in ("experiment_id", "execution_id", "arm", "contract_sha256", "input_binding_sha256"):
                if self._identity_value(start, field) != getattr(claim, field):
                    raise TerminalizationRejected(f"start identity mismatch: {field}")
                if self._identity_value(event, field) != getattr(claim, field):
                    raise TerminalizationRejected(f"terminal identity mismatch: {field}")
            if any(
                existing.get("event_type") == "TERMINAL"
                and existing.get("experiment_id") == claim.experiment_id
                and existing.get("execution_id") == claim.execution_id
                for existing in events
            ):
                raise RegistryIntegrityError(f"duplicate terminal: {claim.execution_id}")
            terminal_status = str(event.get("terminal_status", ""))
            entered = event.get("fit_call_entered")
            returned = event.get("real_fit_returned_count")
            start_kind = str(self._metric(start, "execution_kind") or REAL_FIT_EXECUTION_KIND)
            terminal_kind = str(self._metric(event, "execution_kind") or start_kind)
            if terminal_kind != start_kind or terminal_kind != claim.execution_kind:
                raise TerminalizationRejected("terminal execution_kind mismatch")
            if not terminal_status or not isinstance(entered, bool):
                raise TerminalizationRejected("terminal fit accounting is incomplete")
            if isinstance(returned, bool) or returned not in (0, 1):
                raise TerminalizationRejected("terminal returned-fit count is invalid")
            if start_kind == REAL_FIT_EXECUTION_KIND:
                if terminal_status == "COMPLETED" and (not entered or returned != 1):
                    raise TerminalizationRejected("completed terminal fit accounting is invalid")
                if terminal_status.startswith("FAILED") and (not entered or returned != 0):
                    raise TerminalizationRejected("failed terminal fit accounting is invalid")
            elif entered or returned != 0:
                raise TerminalizationRejected("no-fit terminal cannot report fit activity")
            self._append_unlocked(raw, events, self._event_spec(event, event_type="TERMINAL"))

    def append_parity_event(self, spec: Mapping[str, Any], *, execution_id: str) -> None:
        """Append one parity lifecycle event under the official registry lock.

        This narrow method is for the zero-label data check's own
        ``RUN_STARTED``/``TERMINAL`` lifecycle.  It does not expose a generic
        guard append path: starts require a globally unused execution ID, while
        terminals require exactly one earlier start and no earlier terminal.
        """

        event_type = str(spec.get("event_type", ""))
        if event_type not in {"RUN_STARTED", "TERMINAL"}:
            raise RegistryIntegrityError(f"unsupported parity lifecycle event: {event_type}")
        if str(spec.get("execution_id", "")) != execution_id or not execution_id:
            raise RegistryIntegrityError("parity execution_id mismatch")
        for field in ("experiment_id", "arm", "contract_sha256", "input_binding_sha256"):
            self._required(spec, field)
        with self._locked():
            raw, events = self._read_validated()
            same = [existing for existing in events if existing.get("execution_id") == execution_id]
            if event_type == "RUN_STARTED" and same:
                raise DuplicateExecutionId(f"execution_id already exists: {execution_id}")
            if event_type == "TERMINAL":
                starts = [existing for existing in same if existing.get("event_type") == "RUN_STARTED"]
                terminals = [existing for existing in same if existing.get("event_type") == "TERMINAL"]
                if len(starts) != 1 or terminals:
                    raise RegistryIntegrityError(f"parity terminal lifecycle invalid: {execution_id}")
                for field in (
                    "experiment_id", "execution_id", "arm", "contract_sha256", "input_binding_sha256"
                ):
                    if spec.get(field) != starts[0].get(field):
                        raise TerminalizationRejected(f"parity terminal identity mismatch: {field}")
            self._append_unlocked(raw, events, spec)

    def append_parity_correction(
        self,
        *,
        execution_id: str,
        target_registry_event_id: str,
        target_event_sha256: str,
        receipt_path: Path,
        report_path: Path,
    ) -> None:
        """Append the one bounded parity correction without rewriting history.

        This is deliberately narrower than a generic registry append.  It can
        only correct the already-terminalized parity execution and always
        targets the exact earlier terminal event by both registry id and hash.
        """

        if not execution_id or not target_registry_event_id or len(target_event_sha256) != 64:
            raise RegistryIntegrityError("parity correction identity is incomplete")
        with self._locked():
            raw, events = self._read_validated()
            matches = [
                event
                for event in events
                if event.get("registry_event_id") == target_registry_event_id
                and event.get("event_sha256") == target_event_sha256
                and event.get("execution_id") == execution_id
                and event.get("event_type") == "TERMINAL"
            ]
            if len(matches) != 1:
                raise RegistryIntegrityError("parity correction target is not one earlier terminal")
            target = matches[0]
            correction_id = f"{execution_id}_CORRECTION_MASK_UNVERIFIED"
            if any(event.get("registry_event_id") == correction_id for event in events):
                raise RegistryIntegrityError(f"parity correction already exists: {correction_id}")
            correction = dict(target)
            correction["registry_event_id"] = correction_id
            correction["registration_mode"] = "APPENDED_CORRECTION"
            correction["event_type"] = "CORRECTION"
            correction["stage"] = "ZERO_LABEL_PARITY_CORRECTION"
            correction["occurred_at"] = _utc_now()
            correction["occurred_at_reason"] = "ADMINISTRATIVE_CORRECTION_TIME_NOT_USED_AS_EXPERIMENT_TIME"
            correction["artifact_paths"] = [str(receipt_path), str(report_path)]
            correction["artifact_path"] = [str(receipt_path), str(report_path)]
            correction["decision"] = "CANNOT_CONFIRM_MASK_PARITY"
            correction["stop_reason"] = "MASK_PARITY_UNVERIFIED_PRODUCER_SCOPE_ONLY"
            metrics = dict(correction.get("deterministic_metrics") or {})
            metrics.update(
                {
                    "corrects_registry_event_id": target_registry_event_id,
                    "corrects_event_sha256": target_event_sha256,
                    "corrected_fields": ["decision", "stop_reason", "evidence_level"],
                    "corrected_status": "PARTIAL_PRODUCER_PARITY_PASS_MASK_UNVERIFIED",
                }
            )
            correction["deterministic_metrics"] = metrics
            self._append_unlocked(raw, events, correction)

    def _locked(self):
        return _RegistryLock(self.lock_path)

    def _read_validated(self) -> tuple[bytes, list[dict[str, Any]]]:
        if not self.registry_path.is_file():
            raise FileNotFoundError(str(self.registry_path))
        raw = self.registry_path.read_bytes()
        self.validator.validate_registry_bytes(raw, source="zero-label-adapter-before-append")
        try:
            events = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RegistryIntegrityError("official registry is not canonical JSONL") from exc
        return raw, events

    def _append_unlocked(self, raw: bytes, events: list[dict[str, Any]], spec: Mapping[str, Any]) -> None:
        if not events:
            raise RegistryIntegrityError("official registry unexpectedly empty")
        materialized = self.builder.materialize([dict(spec)], starting_previous_sha=events[-1]["event_sha256"])
        payload = self.builder._registry_payload(materialized)
        self.validator.validate_registry_bytes(raw + payload, source="zero-label-adapter-candidate-append")
        with self.registry_path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

    def _event_spec(self, event: Mapping[str, Any], *, event_type: str) -> dict[str, Any]:
        if self.contract_path is None or not self.contract_path.is_file():
            raise FileNotFoundError("adapter contract_path is required")
        execution_id = self._required(event, "execution_id")
        experiment_id = self._required(event, "experiment_id")
        arm = self._required(event, "arm")
        contract_sha = self._required(event, "contract_sha256")
        input_binding_sha = self._required(event, "input_binding_sha256")
        terminal = event_type == "TERMINAL"
        artifact_paths = [self.contract_path, *self.artifact_paths]
        if self.input_binding_path is not None:
            input_paths: list[Path] = [self.input_binding_path]
        else:
            input_paths = []
        return {
            "schema_version": "1.0",
            "registry_event_id": f"{execution_id}_{event_type}",
            "execution_id": execution_id,
            "experiment_id": experiment_id,
            "arm": arm,
            "track_id": self.event_profile["track_id"],
            "registration_mode": self.event_profile["registration_mode"],
            "route_id": self.event_profile["route_id"],
            "stage": self.event_profile["start_stage"] if not terminal else self.event_profile["terminal_stage"],
            "event_type": event_type,
            "occurred_at": event.get("finished_at") or event.get("started_at") or _utc_now(),
            "occurred_at_reason": self.event_profile["occurred_at_reason"],
            "contract_path": str(self.contract_path),
            "artifact_paths": [str(path) for path in artifact_paths],
            "input_paths": [str(path) for path in input_paths] if input_paths else None,
            "input_sha256": input_binding_sha,
            "input_binding_sha256": input_binding_sha,
            "code_sha256": _sha256(Path(__file__).resolve()),
            "config_sha256": contract_sha,
            "baseline_id": self.event_profile["baseline_id"],
            "one_variable": self.event_profile["one_variable"],
            "signal_date_range": {"count": 0, "scope": self.event_profile["signal_scope"]},
            "target_date_range": {"count": 0, "scope": self.event_profile["target_scope"]},
            "truth_access": "NOT_READ",
            "sealed_status": "NOT_ENTERED",
            "runtime": {"python": str(Path(os.environ.get("PYTHON", "python3")).resolve())},
            "device": self.event_profile["device"],
            "artifact_path": [str(path) for path in artifact_paths],
            "checkpoint_ref": None,
            "deterministic_metrics": {
                "truth_positive_denominator": None,
                "selection_slots": None,
                "execution_kind": str(event.get("execution_kind") or REAL_FIT_EXECUTION_KIND),
                "planned_real_fit_count": int(event.get("planned_real_fit_count", 0 if event.get("execution_kind") == NO_FIT_ENGINEERING_KIND else 1)),
                "real_fit_budget_debit": int(event.get("real_fit_budget_debit", 0) or 0),
                "real_fit_returned_count": int(event.get("real_fit_returned_count", 0) or 0),
                "fit_call_entered": bool(event.get("fit_call_entered", False)),
            },
            "decision": "RUNNING" if not terminal else str(event.get("terminal_status", "CANNOT_CONFIRM")),
            "stop_reason": "NONE" if not terminal else str(event.get("error_type") or "CONTROLLED_TERMINAL"),
            "evidence_level": self.event_profile["evidence_level"],
            "input_identity": {
                "experiment_id": experiment_id,
                "arm": arm,
                "contract_sha256": contract_sha,
                "input_binding_sha256": input_binding_sha,
                "null_reasons": {},
            },
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @staticmethod
    def _validated_profile(profile: Mapping[str, str] | None) -> dict[str, str]:
        value = dict(DEFAULT_EVENT_PROFILE)
        if profile is not None:
            unknown = set(profile) - _REQUIRED_PROFILE_FIELDS
            if unknown:
                raise RegistryIntegrityError(f"unsupported event_profile fields: {sorted(unknown)}")
            value.update({str(key): str(item) for key, item in profile.items()})
        missing = [key for key in _REQUIRED_PROFILE_FIELDS if not value.get(key)]
        if missing:
            raise RegistryIntegrityError(f"event_profile fields missing: {sorted(missing)}")
        if value["registration_mode"] != "LIVE_EXECUTION":
            raise RegistryIntegrityError("event_profile registration_mode must remain LIVE_EXECUTION")
        return value

    @staticmethod
    def _required(event: Mapping[str, Any], key: str) -> str:
        value = str(event.get(key, ""))
        if not value:
            raise RegistryIntegrityError(f"missing required guard field: {key}")
        return value

    @staticmethod
    def _metric(event: Mapping[str, Any], key: str) -> Any:
        value = event.get(key)
        if value is not None:
            return value
        metrics = event.get("deterministic_metrics")
        if isinstance(metrics, Mapping):
            return metrics.get(key)
        return None

    @staticmethod
    def _identity_value(event: Mapping[str, Any], key: str) -> Any:
        value = event.get(key)
        if value is not None:
            return value
        identity = event.get("input_identity")
        if key == "input_binding_sha256" and isinstance(identity, Mapping):
            return identity.get(key)
        return None


class _RegistryLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        assert self.handle is not None
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        return False
