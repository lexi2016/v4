#!/usr/bin/env python3
"""Official, one-debit candidate launcher for the frozen F5 XENDCG route."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


CANDIDATE_ROOT = Path(__file__).resolve().parents[1]
BATCH_ROOT = CANDIDATE_ROOT.parent
RECOVERY_ROOT = BATCH_ROOT / "recovery_01"
READBACK_ROOT = RECOVERY_ROOT / "readback_01"
PROJECT_ROOT = BATCH_ROOT.parents[3]
SRC = CANDIDATE_ROOT / "src"
RUN_SPEC_PATH = CANDIDATE_ROOT / "contracts/CANDIDATE_RUN_SPEC_R5.json"
INPUT_BINDING_PATH = CANDIDATE_ROOT / "contracts/CANDIDATE_INPUT_BINDING_R5.json"
PARENT_RELEASE_PATH = CANDIDATE_ROOT / "contracts/CANDIDATE_PARENT_RELEASE_R5.json"
REVIEW_TRANSCRIPT_PATH = PROJECT_ROOT / "handoffs/F5_FULL64_XENDCG_R1_20260924/CANDIDATE_ENTRY_REVIEW_TRANSCRIPT.json"
READBACK_TRANSCRIPT_PATH = READBACK_ROOT / "evidence/READBACK_REVIEW_TRANSCRIPT.json"
READBACK_TERMINAL_EVENT_SHA256 = "cce7cb0f855a2699e82209a39b256147f33c60fa9023eff1611af29a07b8d792"
EXECUTION_ID = "F5_FULL64_XENDCG_R1_20260924_CANDIDATE_01"
SYNTHETIC_EXECUTION_ID = "F5_FULL64_XENDCG_R1_20260924_CANDIDATE_01_SYNTHETIC_CANARY"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(BATCH_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(BATCH_ROOT / "src"))
if str(RECOVERY_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(RECOVERY_ROOT / "src"))

import candidate_worker  # noqa: E402
from recovery_spawn_support import import_resource_tree  # noqa: E402


class CandidateEntryError(RuntimeError):
    pass


def _worker_fit_returned_count(worker_status: Mapping[str, Any]) -> int:
    fit_calls = worker_status.get("fit_calls")
    fit_call_entered = worker_status.get("fit_call_entered")
    returned = worker_status.get("real_fit_returned_count")
    if type(fit_calls) is not int or fit_calls not in (0, 1):
        raise CandidateEntryError("CANDIDATE_WORKER_FIT_CALL_COUNT_INVALID")
    if type(fit_call_entered) is not bool or fit_calls != int(fit_call_entered):
        raise CandidateEntryError("CANDIDATE_WORKER_FIT_ENTRY_ACCOUNTING_MISMATCH")
    if type(returned) is not int or returned not in (0, 1) or returned > fit_calls:
        raise CandidateEntryError("CANDIDATE_WORKER_FIT_RETURN_ACCOUNTING_INVALID")
    return returned


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CandidateEntryError(f"CANDIDATE_JSON_NOT_OBJECT:{Path(path).name}")
    return value


def _worker_progress_from_doc(value: Mapping[str, Any]) -> dict[str, Any]:
    returned = _worker_fit_returned_count(value)
    predict_calls = value.get("predict_calls")
    if type(predict_calls) is not int or predict_calls < 0:
        raise CandidateEntryError("CANDIDATE_WORKER_PREDICT_CALL_COUNT_INVALID")
    return {
        "fit_call_entered": value["fit_call_entered"],
        "real_fit_returned_count": returned,
        "predict_calls": predict_calls,
    }


def _read_worker_progress(output_root: Path, *, worker_launched: bool) -> dict[str, Any]:
    if not worker_launched:
        return {
            "worker_status": {},
            "fit_call_entered": False,
            "real_fit_returned_count": 0,
            "predict_calls": 0,
            "fit_accounting_status": "KNOWN",
            "fit_accounting_source": "PARENT_BEFORE_WORKER_LAUNCH",
            "fit_accounting_reason": "WORKER_NOT_LAUNCHED",
        }

    worker_status_path = output_root / "CANDIDATE_WORKER_STATUS.json"
    worker_status: dict[str, Any] = {}
    status_error = "WORKER_STATUS_MISSING"
    if worker_status_path.is_file():
        try:
            worker_status = _json(worker_status_path)
            progress = _worker_progress_from_doc(worker_status)
            return {
                "worker_status": worker_status,
                **progress,
                "fit_accounting_status": "KNOWN",
                "fit_accounting_source": "DURABLE_WORKER_STATUS",
                "fit_accounting_reason": "WORKER_STATUS_SNAPSHOT_VALID",
            }
        except (CandidateEntryError, OSError, json.JSONDecodeError, TypeError, ValueError):
            status_error = "WORKER_STATUS_UNREADABLE_OR_COUNTERS_INVALID"

    result_path = output_root / "CANDIDATE_RESULT_RECEIPT.json"
    if result_path.is_file():
        try:
            result_doc = _json(result_path)
            progress = _worker_progress_from_doc(result_doc)
            return {
                "worker_status": worker_status,
                **progress,
                "fit_accounting_status": "KNOWN",
                "fit_accounting_source": "DURABLE_CANDIDATE_RESULT_RECEIPT",
                "fit_accounting_reason": f"{status_error};RESULT_RECEIPT_COUNTERS_VALID",
            }
        except (CandidateEntryError, OSError, json.JSONDecodeError, TypeError, ValueError):
            status_error = f"{status_error};RESULT_RECEIPT_UNREADABLE_OR_COUNTERS_INVALID"

    return {
        "worker_status": worker_status,
        "fit_call_entered": None,
        "real_fit_returned_count": None,
        "predict_calls": None,
        "fit_accounting_status": "UNKNOWN",
        "fit_accounting_source": None,
        "fit_accounting_reason": f"{status_error}_AFTER_WORKER_LAUNCH",
    }


def _exclusive_json(path: Path, value: Mapping[str, Any]) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return _sha256_bytes(raw)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CandidateEntryError(f"CANDIDATE_MODULE_SPEC_FAILED:{name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_contracts(
    run_spec_path: Path = RUN_SPEC_PATH,
    input_binding_path: Path = INPUT_BINDING_PATH,
    *,
    expected_execution_id: str = EXECUTION_ID,
) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    spec_bytes = Path(run_spec_path).read_bytes()
    binding_bytes = Path(input_binding_path).read_bytes()
    spec = json.loads(spec_bytes)
    binding = json.loads(binding_bytes)
    if not isinstance(spec, dict) or not isinstance(binding, dict):
        raise CandidateEntryError("CANDIDATE_CONTRACT_NOT_OBJECT")
    if spec.get("schema") != "F5_FULL64_XENDCG_CANDIDATE_RUN_SPEC_R5_V1" or binding.get("schema") != "F5_FULL64_XENDCG_CANDIDATE_INPUT_BINDING_R5_V1":
        raise CandidateEntryError("CANDIDATE_CONTRACT_SCHEMA_MISMATCH")
    if _sha256_bytes(spec_bytes) != binding.get("run_spec_sha256"):
        raise CandidateEntryError("CANDIDATE_RUN_SPEC_SHA_MISMATCH")
    if binding.get("run_spec_path") != str(Path(run_spec_path).resolve()):
        raise CandidateEntryError("CANDIDATE_RUN_SPEC_PATH_MISMATCH")
    if binding.get("input_binding_path") != str(Path(input_binding_path).resolve()):
        raise CandidateEntryError("CANDIDATE_INPUT_BINDING_PATH_MISMATCH")
    if spec.get("execution_id") != expected_execution_id or binding.get("execution_id") != expected_execution_id:
        raise CandidateEntryError("CANDIDATE_EXECUTION_ID_MISMATCH")
    if spec.get("route_id") != binding.get("route_id"):
        raise CandidateEntryError("CANDIDATE_ROUTE_ID_MISMATCH")
    if spec.get("input_binding_path") != str(Path(input_binding_path).resolve()):
        raise CandidateEntryError("CANDIDATE_RUN_SPEC_BINDING_PATH_MISMATCH")
    if spec.get("candidate_parent_release_path") != binding.get("parent_release_path"):
        raise CandidateEntryError("CANDIDATE_PARENT_RELEASE_PATH_MISMATCH")
    return spec, binding, spec_bytes, binding_bytes


def _verify_source_snapshot(binding: Mapping[str, Any]) -> None:
    code_files = binding["code_files"]
    canonical = json.dumps(dict(code_files), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if _sha256_bytes(canonical) != binding.get("code_sha256"):
        raise CandidateEntryError("CANDIDATE_CODE_MANIFEST_SHA_MISMATCH")
    for name, item in code_files.items():
        path = Path(item["path"])
        if not path.is_file() or _sha256_file(path) != item["sha256"]:
            raise CandidateEntryError(f"CANDIDATE_SOURCE_SHA_MISMATCH:{name}")
    for name, item in binding["official_helpers"].items():
        path = Path(item["path"])
        if not path.is_file() or _sha256_file(path) != item["sha256"]:
            raise CandidateEntryError(f"CANDIDATE_OFFICIAL_HELPER_SHA_MISMATCH:{name}")
    for name, item in binding["executable_helpers"].items():
        path = Path(item["path"])
        if not path.is_file() or _sha256_file(path) != item["sha256"]:
            raise CandidateEntryError(f"CANDIDATE_EXECUTABLE_HELPER_SHA_MISMATCH:{name}")


def _verify_prefit_and_readback(binding: Mapping[str, Any]) -> None:
    result = binding["prefit_artifacts"]["result"]
    run = binding["prefit_artifacts"]["run"]
    trace = binding["prefit_artifacts"]["resource_trace"]
    for name, item in binding["prefit_artifacts"].items():
        path = Path(item["path"])
        if not path.is_file() or _sha256_file(path) != item["sha256"]:
            raise CandidateEntryError(f"CANDIDATE_PREFIT_ARTIFACT_SNAPSHOT_MISMATCH:{name}")
    result_doc = _json(Path(result["path"]))
    if (
        result_doc.get("execution_id") != binding.get("prefit_execution_id")
        or result_doc.get("status") != "PREFIT_COMPLETED_AWAITING_INDEPENDENT_DELTA_REVIEW_AND_CANDIDATE_RELEASE"
        or result_doc.get("fit_calls") != 0
        or result_doc.get("predict_calls") != 0
        or result_doc.get("evaluation_label_values_decoded") is not False
    ):
        raise CandidateEntryError("CANDIDATE_PREFIT_RESULT_SCOPE_MISMATCH")
    for name, item in binding["prefit_artifacts"].items():
        if name in {"result", "run", "resource_trace"}:
            continue
        expected = result_doc.get("artifacts", {}).get(str(Path(item["path"]).resolve()))
        if expected != item["sha256"]:
            raise CandidateEntryError(f"CANDIDATE_PREFIT_DERIVATIVE_NOT_LINKED:{name}")

    readback_binding = binding["readback_input_binding"]
    readback_transcript = binding["readback_review_transcript"]
    for name, item in (("binding", readback_binding), ("transcript", readback_transcript)):
        path = Path(item["path"])
        if not path.is_file() or _sha256_file(path) != item["sha256"]:
            raise CandidateEntryError(f"CANDIDATE_READBACK_SNAPSHOT_MISMATCH:{name}")
    transcript = _json(Path(readback_transcript["path"]))
    if transcript.get("reviewer_agent") != "/root/xendcg_review" or transcript.get("reviewer_verdict") != "PASS":
        raise CandidateEntryError("CANDIDATE_READBACK_VERDICT_NOT_PASS")
    if binding.get("readback_terminal_event_sha256") != READBACK_TERMINAL_EVENT_SHA256:
        raise CandidateEntryError("CANDIDATE_READBACK_TERMINAL_SHA_MISMATCH")


def _verify_parent_release(
    spec: Mapping[str, Any],
    binding: Mapping[str, Any],
    release: Mapping[str, Any],
    *,
    input_binding_path: Path,
    release_path: Path,
    reviewer_transcript_path: Path,
) -> tuple[str, str]:
    release_sha = _sha256_file(release_path)
    transcript_sha = _sha256_file(reviewer_transcript_path)
    transcript = _json(reviewer_transcript_path)
    reviewer_id = str(transcript.get("reviewer_agent", ""))
    if not reviewer_id or reviewer_id != "/root/xendcg_review" or transcript.get("reviewer_verdict") != "PASS":
        raise CandidateEntryError("CANDIDATE_ENTRY_REVIEW_NOT_PASS")
    if release.get("reviewer_agent") != reviewer_id or release.get("reviewer_verdict") != "PASS":
        raise CandidateEntryError("PARENT_RELEASE_REVIEW_IDENTITY_MISMATCH")
    expected = {
        "active": True,
        "execution_id": binding["execution_id"],
        "route_id": binding["route_id"],
        "candidate_run_spec_sha256": binding["run_spec_sha256"],
        "candidate_input_binding_sha256": _sha256_file(input_binding_path),
        "candidate_source_sha256": binding["code_sha256"],
        "official_registry_path": binding["official_registry_path"],
        "official_registry_sha256_before_start": binding["official_registry_sha256_before_start"],
        "expected_route_event_sha256_before_start": binding["expected_route_event_sha256_before_start"],
        "reviewer_transcript_path": str(reviewer_transcript_path.resolve()),
        "reviewer_transcript_sha256": transcript_sha,
        "readback_terminal_event_sha256": binding["readback_terminal_event_sha256"],
        "prefit_result_receipt_sha256": binding["prefit_result_receipt_sha256"],
        "prefit_run_receipt_sha256": binding["prefit_run_receipt_sha256"],
        "candidate_fit_calls_authorized": 1,
        "control_fit_calls_authorized": 0,
        "control_predict_calls_authorized": 0,
        "calibrator_fit_calls_authorized": 0,
        "full_2024_prediction_and_evaluation_authorized": True,
        "automatic_retry_after_real_start": False,
        "num_boost_round": 200,
        "learner_params": spec["learner_params"],
        "resource_caps": binding["resources"],
    }
    if release.get("schema") != "F5_FULL64_XENDCG_CANDIDATE_PARENT_RELEASE_R5_V1":
        raise CandidateEntryError("CANDIDATE_PARENT_RELEASE_SCHEMA_MISMATCH")
    if not release.get("parent_authorization_id") or release.get("parent_authorization_id") == "PARENT_RELEASE_REQUIRED_BEFORE_ANY_REAL_INPUT_READ":
        raise CandidateEntryError("CANDIDATE_PARENT_AUTHORIZATION_MISSING")
    if release.get("run_spec_sha256") != binding["run_spec_sha256"] or release.get("input_binding_sha256") != expected["candidate_input_binding_sha256"]:
        raise CandidateEntryError("CANDIDATE_PARENT_RELEASE_CONTRACT_IDENTITY_MISMATCH")
    if release.get("release_path") != str(release_path.resolve()):
        raise CandidateEntryError("CANDIDATE_PARENT_RELEASE_PATH_IDENTITY_MISMATCH")
    if release.get("release_sha256") not in (None, release_sha):
        raise CandidateEntryError("CANDIDATE_PARENT_RELEASE_SELF_SHA_MISMATCH")
    if any(release.get(key) != value for key, value in expected.items()):
        mismatched = [key for key, value in expected.items() if release.get(key) != value]
        raise CandidateEntryError(f"CANDIDATE_PARENT_RELEASE_FIELD_MISMATCH:{','.join(mismatched)}")
    return release_sha, transcript_sha


def _load_official_modules(binding: Mapping[str, Any]):
    for name, item in binding["official_helpers"].items():
        path = Path(item["path"])
        if not path.is_file() or _sha256_file(path) != item["sha256"]:
            raise CandidateEntryError(f"CANDIDATE_OFFICIAL_HELPER_SHA_MISMATCH:{name}")
    helper = binding["official_helpers"]
    guard_path = Path(helper["execution_guard"]["path"])
    if str(guard_path.parent) not in sys.path:
        sys.path.insert(0, str(guard_path.parent))
    adapter_module = _load_module(Path(helper["registry_adapter"]["path"]), "f5_xendcg_candidate_registry_adapter")
    guard_module = _load_module(guard_path, "f5_xendcg_candidate_execution_guard")
    return adapter_module, guard_module


def _make_candidate_adapter(
    adapter_module: Any,
    guard_module: Any,
    spec: Mapping[str, Any],
    binding: Mapping[str, Any],
    *,
    run_spec_path: Path,
    input_binding_path: Path,
    release_path: Path,
    reviewer_transcript_path: Path,
    registry_path: Path,
    expected_registry_sha: str,
    release_sha: str,
    review_sha: str,
    start_registry_snapshot: dict[str, str | None],
    synthetic_mode: bool = False,
):
    route_id = str(binding["route_id"])
    execution_id = str(binding["execution_id"])
    run_sha = str(binding["run_spec_sha256"])
    input_sha = _sha256_file(input_binding_path)
    code_sha = str(binding["code_sha256"])
    helper_specs = binding["official_helpers"]
    artifact_paths = [run_spec_path, input_binding_path, release_path, reviewer_transcript_path]
    artifact_paths.extend(Path(item["path"]) for item in binding["code_files"].values())
    artifact_paths.extend(Path(item["path"]) for item in binding["executable_helpers"].values())
    artifact_paths.extend(Path(item["path"]) for item in helper_specs.values())
    artifact_paths.extend(Path(item["path"]) for item in binding["prefit_artifacts"].values())
    artifact_paths.extend(
        Path(binding[key]["path"])
        for key in ("readback_input_binding", "readback_review_transcript")
    )
    event_profile = {
        "track_id": "HK_BURST_F5_FULL_HISTORY_RESEARCH",
        "route_id": route_id,
        "registration_mode": "LIVE_EXECUTION",
        "start_stage": "CANDIDATE_XENDCG_RUN_STARTED",
        "terminal_stage": "CANDIDATE_XENDCG_TERMINAL",
        "occurred_at_reason": "LIVE_EXECUTION_UTC",
        "baseline_id": "F5_FULL64_ORIGINAL_PLUS_PATH_BINARY_2024",
        "one_variable": "replace_binary_BCE_with_native_rank_xendcg",
        "signal_scope": "ORIGINAL_2018_TO_2023_TRAINING_FOLD",
        "target_scope": "EXPOSED_2024_FULL_GRID_AFTER_PREDICTION_SEAL",
        "device": "CPU_RESEARCH_ONLY",
        "evidence_level": "DIRECTION_ONLY",
    }

    class CandidateOfficialAdapter(adapter_module.OfficialRegistryAdapter):
        def claim_run_started(self, event: Mapping[str, Any], *, max_real_fit_debits: int) -> None:
            with self._locked():
                raw, events = self._read_validated()
                if _sha256_bytes(raw) != expected_registry_sha:
                    raise CandidateEntryError("CANDIDATE_OFFICIAL_REGISTRY_CHANGED_BEFORE_START")
                if _sha256_file(release_path) != release_sha or _sha256_file(reviewer_transcript_path) != review_sha:
                    raise CandidateEntryError("CANDIDATE_RELEASE_OR_REVIEWER_SNAPSHOT_CHANGED_UNDER_LOCK")
                if _sha256_file(run_spec_path) != run_sha or _sha256_file(input_binding_path) != input_sha:
                    raise CandidateEntryError("CANDIDATE_CONTRACT_SNAPSHOT_CHANGED_UNDER_LOCK")
                _verify_source_snapshot(binding)
                current_route = [row for row in events if row.get("route_id") == route_id or row.get("experiment_id") == route_id]
                if [row.get("event_sha256") for row in current_route] != binding["expected_route_event_sha256_before_start"]:
                    raise CandidateEntryError("CANDIDATE_ROUTE_PREFIX_EVENT_CHAIN_MISMATCH")
                if any(str(row.get("execution_id")) == execution_id for row in events):
                    raise CandidateEntryError("CANDIDATE_EXECUTION_ID_ALREADY_REGISTERED")
                total_real_debits = sum(
                    int((row.get("deterministic_metrics") or {}).get("real_fit_budget_debit") or 0)
                    for row in current_route
                )
                if total_real_debits != 0:
                    raise CandidateEntryError("CANDIDATE_ROUTE_HAS_PRIOR_REAL_FIT_DEBIT")
                if max_real_fit_debits != 1 or event.get("planned_real_fit_count") != 1 or event.get("real_fit_budget_debit") != 1:
                    raise CandidateEntryError("CANDIDATE_START_MUST_DEBIT_EXACTLY_ONE_FIT")
                if event.get("experiment_id") != route_id or event.get("execution_id") != execution_id:
                    raise CandidateEntryError("CANDIDATE_START_IDENTITY_MISMATCH")
                if event.get("contract_sha256") != run_sha or event.get("input_binding_sha256") != input_sha:
                    raise CandidateEntryError("CANDIDATE_START_CONTRACT_SHA_MISMATCH")
                if event.get("execution_kind") not in (None, "REAL_FIT"):
                    raise CandidateEntryError("CANDIDATE_START_EXECUTION_KIND_MISMATCH")
                self._append_unlocked(raw, events, self._event_spec(event, event_type="RUN_STARTED"))
                start_registry_snapshot["sha256"] = _sha256_file(registry_path)

        def terminalize(self, claim: Any, event: Mapping[str, Any]) -> None:
            with self._locked():
                raw, events = self._read_validated()
                expected_after_start = start_registry_snapshot.get("sha256")
                if not expected_after_start or _sha256_bytes(raw) != expected_after_start:
                    raise CandidateEntryError("CANDIDATE_REGISTRY_CHANGED_BEFORE_TERMINAL")
                starts = [row for row in events if row.get("execution_id") == execution_id and row.get("event_type") == "RUN_STARTED"]
                terminals = [row for row in events if row.get("execution_id") == execution_id and row.get("event_type") == "TERMINAL"]
                if len(starts) != 1 or terminals:
                    raise CandidateEntryError("CANDIDATE_TERMINAL_LIFECYCLE_INVALID")
                start = starts[0]
                unknown_accounting = event.get("fit_accounting_status") == "UNKNOWN"
                if unknown_accounting:
                    if (
                        event.get("terminal_status") == "COMPLETED"
                        or event.get("fit_call_entered") is not None
                        or event.get("real_fit_returned_count") is not None
                        or event.get("predict_calls") is not None
                        or not event.get("fit_accounting_reason")
                    ):
                        raise CandidateEntryError("CANDIDATE_UNKNOWN_FIT_ACCOUNTING_TERMINAL_INVALID")
                else:
                    entered = event.get("fit_call_entered")
                    returned = event.get("real_fit_returned_count")
                    predict_count = event.get("predict_calls")
                    if (
                        type(entered) is not bool
                        or type(returned) is not int
                        or returned not in (0, 1)
                        or returned > int(entered)
                        or type(predict_count) is not int
                        or predict_count < 0
                    ):
                        raise CandidateEntryError("CANDIDATE_KNOWN_FIT_ACCOUNTING_TERMINAL_INVALID")
                for field, expected in (
                    ("experiment_id", claim.experiment_id),
                    ("execution_id", claim.execution_id),
                    ("arm", claim.arm),
                    ("contract_sha256", claim.contract_sha256),
                    ("input_binding_sha256", claim.input_binding_sha256),
                ):
                    if start.get(field) != expected or event.get(field) != expected:
                        raise CandidateEntryError(f"CANDIDATE_TERMINAL_IDENTITY_MISMATCH:{field}")
                self._append_unlocked(raw, events, self._event_spec(event, event_type="TERMINAL"))

        def _event_spec(self, event: Mapping[str, Any], *, event_type: str) -> dict[str, Any]:
            result = super()._event_spec(event, event_type=event_type)
            result["runtime"] = {"python": str(Path(sys.executable).resolve()), "python_version": sys.version.split()[0]}
            result["code_sha256"] = code_sha
            result["parent_authorization_id"] = binding["parent_authorization_id"]
            result["candidate_parent_release_sha256"] = release_sha
            result["candidate_review_transcript_sha256"] = review_sha
            result["prefit_readback_terminal_event_sha256"] = binding["readback_terminal_event_sha256"]
            result["truth_access"] = "NOT_READ"
            result["sealed_status"] = "EXPOSED_2024_LABELS_NOT_DECODED"
            metrics = dict(result.get("deterministic_metrics") or {})
            metrics.update({
                "planned_real_fit_count": int(event.get("planned_real_fit_count", 1)),
                "real_fit_budget_debit": int(event.get("real_fit_budget_debit", 1)),
                "fit_call_entered": event.get("fit_call_entered"),
                "real_fit_returned_count": event.get("real_fit_returned_count"),
                "predict_calls": event.get("predict_calls"),
                "control_fit_calls": 0,
                "control_predict_calls": 0,
                "calibrator_fit_calls": 0,
            })
            if event.get("fit_accounting_status") == "UNKNOWN":
                metrics["fit_accounting_status"] = "UNKNOWN"
                metrics["fit_accounting_reason"] = str(event.get("fit_accounting_reason"))
            elif event_type == "TERMINAL":
                metrics["fit_accounting_status"] = "KNOWN"
                metrics["fit_accounting_source"] = str(event.get("fit_accounting_source"))
            result["deterministic_metrics"] = metrics
            if event_type == "TERMINAL":
                status = str(event.get("terminal_status", "CANNOT_CONFIRM"))
                result["decision"] = status
                result["stop_reason"] = str(event.get("error_type") or "CANDIDATE_TERMINAL_RECORDED")
                result["truth_access"] = (
                    "EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL"
                    if Path(binding["prediction_seal_path"]).is_file() and Path(binding["eval_truth_read_path"]).is_file()
                    else "TRAIN_LABELS_READ_EVAL_LABELS_NOT_DECODED"
                    if Path(binding["output_root"], "CANDIDATE_INPUT_HASH_RECEIPT.json").is_file()
                    else "NO_INPUT_DECODE_MARKER"
                )
                if Path(binding["result_path"]).is_file():
                    result["artifact_paths"] = list(result["artifact_paths"]) + [str(Path(binding["result_path"]).resolve())]
                    result["artifact_path"] = list(result["artifact_path"]) + [str(Path(binding["result_path"]).resolve())]
                run_receipt = Path(binding["run_receipt_path"])
                if run_receipt.is_file():
                    result["artifact_paths"] = list(result["artifact_paths"]) + [str(run_receipt.resolve())]
                    result["artifact_path"] = list(result["artifact_path"]) + [str(run_receipt.resolve())]
            return result

    CandidateOfficialAdapter.base_artifact_paths = tuple(artifact_paths)
    return CandidateOfficialAdapter


def _run_candidate(
    *,
    run_spec_path: Path,
    input_binding_path: Path,
    release_path: Path,
    reviewer_transcript_path: Path,
    expected_execution_id: str,
    synthetic_canary: bool = False,
    synthetic_marker_path: Path | None = None,
    worker_target: Callable[[Mapping[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    spec, binding, spec_bytes, binding_bytes = _load_contracts(
        run_spec_path,
        input_binding_path,
        expected_execution_id=expected_execution_id,
    )
    if not release_path.is_file():
        raise FileNotFoundError("CANDIDATE_PARENT_RELEASE_MISSING_NO_INPUT_READ")
    if not reviewer_transcript_path.is_file():
        raise FileNotFoundError("CANDIDATE_REVIEWER_TRANSCRIPT_MISSING_NO_INPUT_READ")
    _verify_source_snapshot(binding)
    _verify_prefit_and_readback(binding)
    if _sha256_bytes(spec_bytes) != binding["run_spec_sha256"]:
        raise CandidateEntryError("CANDIDATE_RUN_SPEC_SNAPSHOT_MISMATCH")
    release = _json(release_path)
    if synthetic_canary:
        synthetic_expected = {
            "schema": "F5_FULL64_XENDCG_CANDIDATE_PARENT_RELEASE_R5_V1",
            "synthetic_only": True,
            "parent_authorization_id": "SYNTHETIC_CANDIDATE_ENTRY_CANARY_ONLY",
            "release_path": str(release_path.resolve()),
            "run_spec_sha256": _sha256_bytes(spec_bytes),
            "input_binding_sha256": _sha256_bytes(binding_bytes),
            "execution_id": binding["execution_id"],
            "route_id": binding["route_id"],
            "official_registry_path": str(Path(binding["official_registry_path"]).resolve()),
            "official_registry_sha256_before_start": binding["official_registry_sha256_before_start"],
        }
        if any(release.get(key) != value for key, value in synthetic_expected.items()):
            raise CandidateEntryError("CANDIDATE_SYNTHETIC_RELEASE_INVALID")
        release_sha = _sha256_file(release_path)
        review_sha = _sha256_file(reviewer_transcript_path)
    else:
        release_sha, review_sha = _verify_parent_release(
            spec,
            binding,
            release,
            input_binding_path=input_binding_path,
            release_path=release_path,
            reviewer_transcript_path=reviewer_transcript_path,
        )
    registry_path = Path(binding["official_registry_path"])
    registry_before = _sha256_file(registry_path)
    if registry_before != binding["official_registry_sha256_before_start"]:
        raise CandidateEntryError("CANDIDATE_REGISTRY_SHA_MISMATCH_BEFORE_START")
    runtime_binding = dict(binding)
    runtime_binding["parent_authorization_id"] = release.get("parent_authorization_id")
    output_root = Path(binding["output_root"])
    for path in (output_root, Path(binding["run_receipt_path"]), Path(binding["start_receipt_path"])):
        if path.exists():
            raise FileExistsError(f"CANDIDATE_OUTPUT_ALREADY_EXISTS_NO_REENTRY:{path.name}")

    adapter_module, guard_module = _load_official_modules(binding)
    start_registry_snapshot: dict[str, str | None] = {"sha256": None}
    AdapterClass = _make_candidate_adapter(
        adapter_module,
        guard_module,
        spec,
        runtime_binding,
        run_spec_path=run_spec_path,
        input_binding_path=input_binding_path,
        release_path=release_path,
        reviewer_transcript_path=reviewer_transcript_path,
        registry_path=registry_path,
        expected_registry_sha=registry_before,
        release_sha=release_sha,
        review_sha=review_sha,
        start_registry_snapshot=start_registry_snapshot,
        synthetic_mode=synthetic_canary,
    )
    helper_specs = binding["official_helpers"]
    adapter = AdapterClass(
        registry_path=registry_path,
        contract_path=run_spec_path,
        input_binding_path=input_binding_path,
        artifact_paths=list(AdapterClass.base_artifact_paths),
        builder_path=Path(helper_specs["builder"]["path"]),
        validator_path=Path(helper_specs["validator"]["path"]),
        event_profile={
            "track_id": "HK_BURST_F5_FULL_HISTORY_RESEARCH",
            "route_id": binding["route_id"],
            "registration_mode": "LIVE_EXECUTION",
            "start_stage": "CANDIDATE_XENDCG_RUN_STARTED",
            "terminal_stage": "CANDIDATE_XENDCG_TERMINAL",
            "occurred_at_reason": "LIVE_EXECUTION_UTC",
            "baseline_id": "F5_FULL64_ORIGINAL_PLUS_PATH_BINARY_2024",
            "one_variable": "replace_binary_BCE_with_native_rank_xendcg",
            "signal_scope": "ORIGINAL_2018_TO_2023_TRAINING_FOLD",
            "target_scope": "EXPOSED_2024_FULL_GRID_AFTER_PREDICTION_SEAL",
            "device": "CPU_RESEARCH_ONLY",
            "evidence_level": "DIRECTION_ONLY",
        },
    )
    guard = guard_module.ExecutionGuard(adapter, experiment_id=binding["route_id"], max_real_fit_debits=1)
    if guard.accounting().run_started_count != len(binding["expected_route_event_sha256_before_start"]) // 2:
        # Every earlier complete execution contributes one RUN_STARTED; candidate
        # must be the next unregistered one. This checks cardinality only.
        raise CandidateEntryError("CANDIDATE_ROUTE_LIFECYCLE_COUNT_MISMATCH")

    # Resolve and validate the accepted native environment before the durable
    # start. This touches no fold/evaluation inputs and leaves any native startup
    # failure without a route debit.
    native_runtime_path = Path(binding["native_runtime_path"])
    native_runtime = _load_module(native_runtime_path, "f5_full64_xendcg_candidate_native_runtime_parent")
    native_contract = _json(Path(binding["native_reference_contract_path"]))
    native_spec = native_runtime.native_spec_from_contract(native_contract)
    if Path(sys.executable).resolve() != Path(native_spec["python_executable_path"]).resolve():
        raise CandidateEntryError("CANDIDATE_LOCKED_PYTHON_MISMATCH")
    native_runtime.validate_native_files(native_spec)
    resource_tree = import_resource_tree(
        Path(binding["resource_tree_path"]),
        str(binding["resource_tree_sha256"]),
    )
    resources = binding["resources"]
    resource_trace_path = Path(binding["resource_trace_path"])
    start_receipt_path = Path(binding["start_receipt_path"])
    execution_id = expected_execution_id
    arm = "CANDIDATE_NATIVE_RANK_XENDCG_FULL_2024_RAW_SCORE"
    claim = guard.claim(
        execution_id=execution_id,
        arm=arm,
        contract_sha256=_sha256_bytes(spec_bytes),
        input_binding_sha256=_sha256_bytes(binding_bytes),
    )
    status = "CANNOT_CONFIRM"
    error_type: str | None = None
    monitor: dict[str, Any] | None = None
    worker_status: dict[str, Any] = {}
    fit_call_entered: bool | None = False
    fit_returned_count: int | None = 0
    predict_calls: int | None = 0
    fit_accounting_status = "KNOWN"
    fit_accounting_source = "PARENT_BEFORE_WORKER_LAUNCH"
    fit_accounting_reason = "WORKER_NOT_LAUNCHED"
    worker_launched = False
    try:
        registry_after_start = _sha256_file(registry_path)
        if registry_after_start != start_registry_snapshot.get("sha256"):
            raise CandidateEntryError("CANDIDATE_REGISTRY_CHANGED_IMMEDIATELY_AFTER_START")
        raw_registry = registry_path.read_bytes()
        events = [json.loads(line) for line in raw_registry.decode("utf-8").splitlines() if line.strip()]
        start_event = next((row for row in reversed(events) if row.get("execution_id") == execution_id and row.get("event_type") == "RUN_STARTED"), None)
        if start_event is None:
            raise CandidateEntryError("CANDIDATE_RUN_STARTED_NOT_DURABLE_AFTER_APPEND")
        start_receipt = {
            "schema": "F5_FULL64_XENDCG_CANDIDATE_START_RECEIPT_V1",
            "status": "RUN_STARTED_DURABLE",
            "route_id": binding["route_id"],
            "execution_id": execution_id,
            "parent_authorization_id": release.get("parent_authorization_id"),
            "run_spec_sha256": _sha256_bytes(spec_bytes),
            "input_binding_sha256": _sha256_bytes(binding_bytes),
            "source_code_sha256": binding["code_sha256"],
            "parent_release_sha256": release_sha,
            "reviewer_transcript_sha256": review_sha,
            "official_registry_sha256_before_start": registry_before,
            "official_registry_sha256_after_start": registry_after_start,
            "start_event_sha256": start_event["event_sha256"],
            "previous_event_sha256": start_event["previous_event_sha256"],
            "candidate_fit_calls_authorized": 1,
            "fit_budget_debit": 1,
            "control_fit_calls_authorized": 0,
            "control_predict_calls_authorized": 0,
            "calibrator_fit_calls_authorized": 0,
            "automatic_retry": False,
            "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        }
        output_root.mkdir(parents=True, exist_ok=False)
        start_receipt_sha = _exclusive_json(start_receipt_path, start_receipt)
        resource_trace_path.parent.mkdir(parents=True, exist_ok=True)
        if resource_trace_path.exists():
            raise FileExistsError("CANDIDATE_RESOURCE_TRACE_ALREADY_EXISTS_NO_REENTRY")
        payload = {
            "execution_id": execution_id,
            "source_code_sha256": binding["code_sha256"],
            "code_files": binding["code_files"],
            "executable_helpers": binding["executable_helpers"],
            "input_files": binding["input_files"],
            "training_contract": binding["training_contract"],
            "evaluation_contract": binding["evaluation_contract"],
            "prediction_contract": binding["prediction_contract"],
            "learner_params": spec["learner_params"],
            "num_boost_round": spec["num_boost_round"],
            "dataset_params": binding["dataset_params"],
            "feature_names": binding["feature_names"],
            "feature_count": binding["feature_count"],
            "baseline_artifacts": binding["baseline_artifacts"],
            "prefit_artifacts": binding["prefit_artifacts"],
            "output_root": str(output_root.resolve()),
            "start_receipt_path": str(start_receipt_path.resolve()),
            "start_receipt_sha256": start_receipt_sha,
            "run_spec_sha256": _sha256_bytes(spec_bytes),
            "input_binding_sha256": _sha256_bytes(binding_bytes),
            "native_spec": native_spec,
            "native_runtime_path": str(native_runtime_path.resolve()),
            "grouping_path": str(Path(binding["code_files"]["grouping"]["path"]).resolve()),
            "route_source_root": str(BATCH_ROOT / "src"),
            "recovery_source_root": str(RECOVERY_ROOT / "src"),
            "run_spec": spec,
            "parent_authorization_id": release.get("parent_authorization_id"),
            "synthetic_fit_boundary_canary": bool(synthetic_canary),
            "synthetic_marker_path": str(synthetic_marker_path.resolve()) if synthetic_marker_path else None,
        }
        # The worker hashes/reads bound inputs only after this durable RUN_STARTED.
        worker_launched = True
        monitor = resource_tree.run_spawn_monitored(
            worker_target or candidate_worker.run_candidate_worker,
            payload,
            native_spec=native_spec,
            native_runtime_helper_path=native_runtime_path,
            wall_seconds_max=float(resources["wall_seconds_max"]),
            rss_bytes_max=int(resources["aggregate_process_tree_rss_bytes_max"]),
            threads=int(resources["cpu_threads"]),
            resource_trace_path=resource_trace_path,
            sample_seconds=float(resources["sampling_interval_seconds"]),
        )
        progress = _read_worker_progress(output_root, worker_launched=True)
        worker_status = progress["worker_status"]
        fit_call_entered = progress["fit_call_entered"]
        fit_returned_count = progress["real_fit_returned_count"]
        predict_calls = progress["predict_calls"]
        fit_accounting_status = progress["fit_accounting_status"]
        fit_accounting_source = progress["fit_accounting_source"]
        fit_accounting_reason = progress["fit_accounting_reason"]
        if fit_accounting_status == "UNKNOWN":
            error_type = f"CANDIDATE_WORKER_ACCOUNTING_UNKNOWN:{fit_accounting_reason}"
        result_path = output_root / "CANDIDATE_RESULT_RECEIPT.json"
        if (
            monitor.get("terminal_reason") is None
            and monitor.get("worker_exitcode") == 0
            and worker_status.get("status") == "CANDIDATE_FIT_PREDICT_AND_FULL2024_EVALUATION_COMPLETED"
            and result_path.is_file()
        ):
            result_doc = _json(result_path)
            result_progress = _worker_progress_from_doc(result_doc)
            if (
                result_progress["real_fit_returned_count"] == 1
                and result_progress["real_fit_returned_count"] == fit_returned_count
                and result_progress["predict_calls"] == predict_calls
                and fit_accounting_status == "KNOWN"
                and result_doc.get("fit_calls") == 1
                and result_progress["predict_calls"] > 0
                and result_doc.get("control_fit_calls") == 0
                and result_doc.get("control_predict_calls") == 0
            ):
                status = "COMPLETED"
            else:
                error_type = "CANDIDATE_RESULT_BUDGET_OR_CALL_COUNT_MISMATCH"
        else:
            if synthetic_canary and worker_status.get("status") == "SYNTHETIC_CANARY_STOPPED_BEFORE_NATIVE_FIT":
                error_type = "SYNTHETIC_CANARY_STOPPED_BEFORE_NATIVE_FIT"
            else:
                error_type = str(monitor.get("terminal_reason") or worker_status.get("error_type") or f"CANDIDATE_WORKER_EXIT_{monitor.get('worker_exitcode')}")
    except Exception as exc:
        error_type = type(exc).__name__
        status = "CANNOT_CONFIRM"
        progress = _read_worker_progress(output_root, worker_launched=worker_launched)
        worker_status = progress["worker_status"]
        fit_call_entered = progress["fit_call_entered"]
        fit_returned_count = progress["real_fit_returned_count"]
        predict_calls = progress["predict_calls"]
        fit_accounting_status = progress["fit_accounting_status"]
        fit_accounting_source = progress["fit_accounting_source"]
        fit_accounting_reason = progress["fit_accounting_reason"]
    finally:
        run_receipt = {
            "schema": "F5_FULL64_XENDCG_CANDIDATE_RUN_RECEIPT_V1",
            "execution_id": execution_id,
            "route_id": binding["route_id"],
            "parent_authorization_id": release.get("parent_authorization_id"),
            "parent_release_sha256": release_sha,
            "reviewer_transcript_sha256": review_sha,
            "run_spec_sha256": _sha256_bytes(spec_bytes),
            "input_binding_sha256": _sha256_bytes(binding_bytes),
            "worker_status_sha256": _sha256_file(output_root / "CANDIDATE_WORKER_STATUS.json") if (output_root / "CANDIDATE_WORKER_STATUS.json").is_file() else None,
            "candidate_result_sha256": _sha256_file(output_root / "CANDIDATE_RESULT_RECEIPT.json") if (output_root / "CANDIDATE_RESULT_RECEIPT.json").is_file() else None,
            "resource_trace_path": str(resource_trace_path.resolve()),
            "resource_trace_sha256": _sha256_file(resource_trace_path) if resource_trace_path.is_file() else None,
            "resource_monitor": {key: monitor.get(key) for key in (
                "elapsed_seconds", "peak_aggregate_tree_rss_bytes", "worker_exitcode", "terminal_reason",
                "wall_seconds_max", "aggregate_rss_bytes_max", "threads", "sample_interval_seconds",
                "hard_peak_memory_guarantee", "post_trace_fsync_terminal_check", "final_post_fsync_check",
            )} if monitor else None,
            "terminal_status": status,
            "fit_call_entered": fit_call_entered,
            "real_fit_returned_count": fit_returned_count,
            "predict_calls": predict_calls,
            "fit_accounting_status": fit_accounting_status,
            "fit_accounting_source": fit_accounting_source,
            "fit_accounting_reason": fit_accounting_reason,
            "control_fit_calls": 0,
            "control_predict_calls": 0,
            "calibrator_fit_calls": 0,
            "bound_input_bytes_read_after_run_started": (output_root / "CANDIDATE_INPUT_HASH_RECEIPT.json").is_file(),
            "evaluation_label_values_decoded": (output_root / "EVALUATION_TRUTH_READ_START.json").is_file(),
            "truth_access": "EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL" if (output_root / "EVALUATION_TRUTH_READ_START.json").is_file() else "TRAIN_LABELS_READ_EVAL_LABELS_NOT_DECODED" if (output_root / "CANDIDATE_INPUT_HASH_RECEIPT.json").is_file() else "NO_INPUT_DECODE_MARKER",
            "error_type": error_type,
            "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        }
        run_receipt_path = Path(binding["run_receipt_path"])
        try:
            if not run_receipt_path.exists():
                _exclusive_json(run_receipt_path, run_receipt)
        except BaseException as receipt_exc:
            status = "CANNOT_CONFIRM"
            error_type = error_type or type(receipt_exc).__name__
        terminal_event = {
            "event_type": "TERMINAL",
            "experiment_id": claim.experiment_id,
            "execution_id": claim.execution_id,
            "arm": claim.arm,
            "contract_sha256": claim.contract_sha256,
            "input_binding_sha256": claim.input_binding_sha256,
            "planned_real_fit_count": 1,
            "real_fit_budget_debit": 1,
            "fit_call_entered": fit_call_entered,
            "real_fit_returned_count": fit_returned_count,
            "predict_calls": predict_calls,
            "fit_accounting_status": fit_accounting_status,
            "fit_accounting_source": fit_accounting_source,
            "fit_accounting_reason": fit_accounting_reason,
            "terminal_status": status,
            "error_type": error_type,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        artifact_paths = list(adapter.artifact_paths)
        artifact_paths.extend(path for path in (
            start_receipt_path,
            Path(binding["run_receipt_path"]),
            Path(binding["resource_trace_path"]),
            output_root / "CANDIDATE_MODEL.txt",
            output_root / "CANDIDATE_FIT_RECEIPT.json",
            output_root / "CANDIDATE_SCORES.csv.gz",
            output_root / "CANDIDATE_RAW_SCORES.npy",
            output_root / "CANDIDATE_TOP3.csv.gz",
            output_root / "PREDICTION_SEALED_BEFORE_EVAL_TRUTH_READ.json",
            output_root / "METRICS.json",
            output_root / "CANDIDATE_RESULT_RECEIPT.json",
        ) if path.is_file())
        adapter.artifact_paths = tuple(dict.fromkeys(artifact_paths))
        try:
            # The generic ExecutionGuard append path coerces counters to bool/int.
            # Append through this official locked adapter wrapper so explicit
            # UNKNOWN/null counters survive while its lifecycle/identity checks run.
            adapter.terminalize(claim, terminal_event)
        except BaseException:
            # Keep the one durable debit and do not retry this execution.
            raise

    registry_after_terminal = _sha256_file(registry_path)
    raw_registry = registry_path.read_bytes()
    events = [json.loads(line) for line in raw_registry.decode("utf-8").splitlines() if line.strip()]
    terminal = next((row for row in reversed(events) if row.get("execution_id") == execution_id and row.get("event_type") == "TERMINAL"), None)
    if terminal is None:
        raise CandidateEntryError("CANDIDATE_TERMINAL_NOT_DURABLE_AFTER_APPEND")
    terminal_receipt_path = output_root / "CANDIDATE_TERMINAL_RECEIPT.json"
    terminal_receipt_sha = _exclusive_json(terminal_receipt_path, {
        "schema": "F5_FULL64_XENDCG_CANDIDATE_TERMINAL_RECEIPT_V1",
        "execution_id": execution_id,
        "terminal_status": terminal["decision"],
        "terminal_event_sha256": terminal["event_sha256"],
        "previous_event_sha256": terminal["previous_event_sha256"],
        "official_registry_sha256_after_terminal": registry_after_terminal,
        "fit_call_entered": fit_call_entered,
        "real_fit_returned_count": fit_returned_count,
        "predict_calls": predict_calls,
        "fit_accounting_status": fit_accounting_status,
        "fit_accounting_source": fit_accounting_source,
        "fit_accounting_reason": fit_accounting_reason,
        "start_receipt_sha256": _sha256_file(start_receipt_path),
        "run_receipt_sha256": _sha256_file(Path(binding["run_receipt_path"])) if Path(binding["run_receipt_path"]).is_file() else None,
    })
    return {
        "execution_id": execution_id,
        "terminal_status": terminal["decision"],
        "start_event_sha256": start_event["event_sha256"],
        "terminal_event_sha256": terminal["event_sha256"],
        "official_registry_sha256_after_terminal": registry_after_terminal,
        "candidate_result_sha256": _sha256_file(output_root / "CANDIDATE_RESULT_RECEIPT.json") if (output_root / "CANDIDATE_RESULT_RECEIPT.json").is_file() else None,
        "candidate_terminal_receipt_sha256": terminal_receipt_sha,
        "real_fit_budget_debit": 1,
        "fit_call_entered": fit_call_entered,
        "real_fit_returned_count": fit_returned_count,
        "predict_calls": predict_calls,
        "fit_accounting_status": fit_accounting_status,
        "fit_accounting_source": fit_accounting_source,
        "fit_accounting_reason": fit_accounting_reason,
        "automatic_retry": False,
    }


def run_candidate() -> dict[str, Any]:
    spec, binding, _spec_raw, _binding_raw = _load_contracts()
    release_path = Path(binding["parent_release_path"])
    review_path = Path(binding["candidate_review_transcript_path"])
    return _run_candidate(
        run_spec_path=RUN_SPEC_PATH,
        input_binding_path=INPUT_BINDING_PATH,
        release_path=release_path,
        reviewer_transcript_path=review_path,
        expected_execution_id=EXECUTION_ID,
    )


def _synthetic_parent_release(binding_path: Path, spec_path: Path, binding: Mapping[str, Any], spec: Mapping[str, Any], registry_path: Path, release_path: Path, review_path: Path) -> dict[str, Any]:
    return {
        "schema": "F5_FULL64_XENDCG_CANDIDATE_PARENT_RELEASE_R5_V1",
        "synthetic_only": True,
        "active": True,
        "parent_authorization_id": "SYNTHETIC_CANDIDATE_ENTRY_CANARY_ONLY",
        "release_path": str(release_path.resolve()),
        "run_spec_sha256": _sha256_file(spec_path),
        "input_binding_sha256": _sha256_file(binding_path),
        "reviewer_agent": "SYNTHETIC_CANARY_ONLY",
        "reviewer_verdict": "SYNTHETIC_ONLY",
        "reviewer_transcript_path": str(review_path.resolve()),
        "reviewer_transcript_sha256": _sha256_file(review_path),
        "official_registry_path": str(registry_path.resolve()),
        "official_registry_sha256_before_start": _sha256_file(registry_path),
        "expected_route_event_sha256_before_start": binding["expected_route_event_sha256_before_start"],
        "execution_id": binding["execution_id"],
        "route_id": binding["route_id"],
        "candidate_run_spec_sha256": _sha256_file(spec_path),
        "candidate_input_binding_sha256": _sha256_file(binding_path),
        "candidate_source_sha256": binding["code_sha256"],
        "readback_terminal_event_sha256": binding["readback_terminal_event_sha256"],
        "prefit_result_receipt_sha256": binding["prefit_result_receipt_sha256"],
        "prefit_run_receipt_sha256": binding["prefit_run_receipt_sha256"],
        "candidate_fit_calls_authorized": 1,
        "control_fit_calls_authorized": 0,
        "control_predict_calls_authorized": 0,
        "calibrator_fit_calls_authorized": 0,
        "full_2024_prediction_and_evaluation_authorized": True,
        "automatic_retry_after_real_start": False,
        "num_boost_round": 200,
        "learner_params": spec["learner_params"],
        "resource_caps": binding["resources"],
    }


def run_synthetic_spawn_canary(*, missing_worker_status: bool = False) -> dict[str, Any]:
    """Exercise the actual file-backed official start/worker/terminal chain on a registry clone."""
    import copy
    import tempfile

    base_spec, base_binding, _, _ = _load_contracts()
    official_registry = Path(base_binding["official_registry_path"])
    official_sha = _sha256_file(official_registry)
    with tempfile.TemporaryDirectory(prefix="f5-xendcg-candidate-canary-") as temp_text:
        temp = Path(temp_text)
        temp_registry = temp / "EXPERIMENT_REGISTRY.jsonl"
        temp_registry.write_bytes(official_registry.read_bytes())
        spec = copy.deepcopy(base_spec)
        binding = copy.deepcopy(base_binding)
        binding["execution_id"] = SYNTHETIC_EXECUTION_ID
        binding["official_registry_path"] = str(temp_registry.resolve())
        binding["official_registry_sha256_before_start"] = _sha256_file(temp_registry)
        binding["output_root"] = str((temp / "candidate_output").resolve())
        binding["run_receipt_path"] = str((temp / "candidate_output/CANDIDATE_RUN_RECEIPT.json").resolve())
        binding["resource_trace_path"] = str((temp / "candidate_output/CANDIDATE_RESOURCE_TRACE.json").resolve())
        binding["start_receipt_path"] = str((temp / "candidate_output/CANDIDATE_START_RECEIPT.json").resolve())
        binding["prediction_seal_path"] = str((temp / "candidate_output/PREDICTION_SEALED_BEFORE_EVAL_TRUTH_READ.json").resolve())
        binding["eval_truth_read_path"] = str((temp / "candidate_output/EVALUATION_TRUTH_READ_START.json").resolve())
        binding["result_path"] = str((temp / "candidate_output/CANDIDATE_RESULT_RECEIPT.json").resolve())
        binding["parent_authorization_id"] = "SYNTHETIC_CANDIDATE_ENTRY_CANARY_ONLY"
        binding["parent_release_path"] = str((temp / "CANDIDATE_PARENT_RELEASE.json").resolve())
        binding["candidate_review_transcript_path"] = str((temp / "CANDIDATE_ENTRY_REVIEW_TRANSCRIPT.json").resolve())
        spec["execution_id"] = SYNTHETIC_EXECUTION_ID
        spec["input_binding_path"] = str((temp / "CANDIDATE_INPUT_BINDING.json").resolve())
        spec["candidate_parent_release_path"] = binding["parent_release_path"]
        spec["candidate_entry_review_transcript_path"] = binding["candidate_review_transcript_path"]
        spec["official_registry_sha256_before_start"] = binding["official_registry_sha256_before_start"]
        spec["registry_path"] = binding["official_registry_path"]
        spec_raw = json.dumps(spec, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        spec_path = temp / "CANDIDATE_RUN_SPEC.json"
        spec_path.write_bytes(spec_raw)
        binding["run_spec_path"] = str(spec_path.resolve())
        binding["run_spec_sha256"] = _sha256_file(spec_path)
        binding["input_binding_path"] = str((temp / "CANDIDATE_INPUT_BINDING.json").resolve())
        binding_path = Path(binding["input_binding_path"])
        binding_path.write_text(json.dumps(binding, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        review_path = temp / "CANDIDATE_ENTRY_REVIEW_TRANSCRIPT.json"
        review_path.write_text(json.dumps({
            "schema": "SYNTHETIC_CANDIDATE_ENTRY_REVIEW_TRANSCRIPT",
            "reviewer_agent": "SYNTHETIC_CANARY_ONLY",
            "reviewer_verdict": "SYNTHETIC_ONLY",
            "synthetic_only": True,
        }, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        release_path = temp / "CANDIDATE_PARENT_RELEASE.json"
        release = _synthetic_parent_release(binding_path, spec_path, binding, spec, temp_registry, release_path, review_path)
        release_path.write_text(json.dumps(release, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        marker_path = temp / "SYNTHETIC_FIT_BOUNDARY.json"
        # Release/source validation is identical; only the worker is marked as a
        # synthetic boundary probe and it exits before opening any real input.
        run_spec_path = spec_path
        result = _run_candidate(
            run_spec_path=run_spec_path,
            input_binding_path=binding_path,
            release_path=release_path,
            reviewer_transcript_path=review_path,
            expected_execution_id=SYNTHETIC_EXECUTION_ID,
            synthetic_canary=True,
            synthetic_marker_path=marker_path,
            worker_target=(candidate_worker.synthetic_exit_without_worker_status if missing_worker_status else None),
        )
        run_receipt = _json(temp / "candidate_output/CANDIDATE_RUN_RECEIPT.json")
        resource_trace = _json(temp / "candidate_output/CANDIDATE_RESOURCE_TRACE.json")
        worker_status_path = temp / "candidate_output/CANDIDATE_WORKER_STATUS.json"
        rows = [json.loads(line) for line in temp_registry.read_text(encoding="utf-8").splitlines() if line.strip()]
        lifecycle = [row for row in rows if row.get("execution_id") == SYNTHETIC_EXECUTION_ID]
        if [row.get("event_type") for row in lifecycle] != ["RUN_STARTED", "TERMINAL"]:
            raise CandidateEntryError("SYNTHETIC_CANDIDATE_LIFECYCLE_MISMATCH")
        if (lifecycle[0].get("deterministic_metrics") or {}).get("real_fit_budget_debit") != 1:
            raise CandidateEntryError("SYNTHETIC_CANDIDATE_DEBIT_MISMATCH")
        if lifecycle[1].get("decision") != "CANNOT_CONFIRM":
            raise CandidateEntryError("SYNTHETIC_CANDIDATE_TERMINAL_DECISION_MISMATCH")
        if missing_worker_status:
            terminal_metrics = lifecycle[1].get("deterministic_metrics") or {}
            if worker_status_path.exists() or marker_path.exists():
                raise CandidateEntryError("SYNTHETIC_MISSING_STATUS_WORKER_WROTE_OUTPUT")
            if (
                run_receipt.get("fit_accounting_status") != "UNKNOWN"
                or run_receipt.get("fit_accounting_reason") != "WORKER_STATUS_MISSING_AFTER_WORKER_LAUNCH"
                or run_receipt.get("fit_call_entered") is not None
                or run_receipt.get("real_fit_returned_count") is not None
                or run_receipt.get("predict_calls") is not None
            ):
                raise CandidateEntryError("SYNTHETIC_MISSING_STATUS_RUN_RECEIPT_NOT_UNKNOWN")
            if (
                terminal_metrics.get("fit_accounting_status") != "UNKNOWN"
                or terminal_metrics.get("fit_accounting_reason") != "WORKER_STATUS_MISSING_AFTER_WORKER_LAUNCH"
                or terminal_metrics.get("fit_call_entered") is not None
                or terminal_metrics.get("real_fit_returned_count") is not None
                or terminal_metrics.get("predict_calls") is not None
            ):
                raise CandidateEntryError("SYNTHETIC_MISSING_STATUS_TERMINAL_NOT_UNKNOWN")
            if resource_trace.get("worker_exitcode") != 23:
                raise CandidateEntryError("SYNTHETIC_MISSING_STATUS_EXIT_CODE_MISMATCH")
        else:
            marker = _json(marker_path)
            worker_status = _json(worker_status_path)
            if worker_status.get("status") != "SYNTHETIC_CANARY_STOPPED_BEFORE_NATIVE_FIT":
                raise CandidateEntryError("SYNTHETIC_CANDIDATE_WORKER_NOT_REACHED")
            if any(worker_status.get(key) != 0 for key in ("fit_calls", "real_fit_returned_count", "predict_calls", "control_fit_calls", "control_predict_calls", "calibrator_fit_calls")):
                raise CandidateEntryError("SYNTHETIC_CANDIDATE_WORKER_BUDGET_MISMATCH")
            if run_receipt.get("fit_call_entered") is not False or run_receipt.get("real_fit_returned_count") != 0 or run_receipt.get("predict_calls") != 0:
                raise CandidateEntryError("SYNTHETIC_CANDIDATE_RUN_RECEIPT_BUDGET_MISMATCH")
            if resource_trace.get("worker_exitcode") != 0 or resource_trace.get("terminal_reason") is not None:
                raise CandidateEntryError("SYNTHETIC_CANDIDATE_RESOURCE_TRACE_FAILED")
            if marker.get("real_input_rows_read") != 0 or marker.get("real_lightgbm_train_calls") != 0 or marker.get("predict_calls") != 0:
                raise CandidateEntryError("SYNTHETIC_CANDIDATE_TOUCHED_REAL_DATA_OR_FIT")
        if _sha256_file(official_registry) != official_sha:
            raise CandidateEntryError("SYNTHETIC_CANDIDATE_CHANGED_OFFICIAL_REGISTRY")
        return {
            "schema": "F5_FULL64_XENDCG_CANDIDATE_FILE_LAUNCHER_SYNTHETIC_CANARY_V1",
            "synthetic_only": True,
            "spawn_method": "spawn",
            "official_start_and_terminal_chain": ["RUN_STARTED", "TERMINAL"],
            "temporary_registry_debit": 1,
            "worker_exitcode": resource_trace.get("worker_exitcode"),
            "worker_stopped_before_native_fit": not missing_worker_status,
            "real_lightgbm_train_calls": 0,
            "predict_calls": 0,
            "real_input_rows_read": 0,
            "official_registry_unchanged": True,
            "terminal_status": result["terminal_status"],
            "start_event_sha256": result["start_event_sha256"],
            "terminal_event_sha256": result["terminal_event_sha256"],
            "worker_status_file_present": worker_status_path.is_file(),
            "fit_accounting_status": result["fit_accounting_status"],
            "fit_accounting_source": result["fit_accounting_source"],
            "fit_accounting_reason": result["fit_accounting_reason"],
            "fit_call_entered": result["fit_call_entered"],
            "real_fit_returned_count": result["real_fit_returned_count"],
            "predict_calls": result["predict_calls"],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    synthetic_group = parser.add_mutually_exclusive_group()
    synthetic_group.add_argument("--synthetic-spawn-canary", action="store_true")
    synthetic_group.add_argument("--synthetic-missing-status-canary", action="store_true")
    args = parser.parse_args(argv)
    if args.synthetic_spawn_canary:
        result = run_synthetic_spawn_canary()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.synthetic_missing_status_canary:
        result = run_synthetic_spawn_canary(missing_worker_status=True)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    result = run_candidate()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("terminal_status") == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
