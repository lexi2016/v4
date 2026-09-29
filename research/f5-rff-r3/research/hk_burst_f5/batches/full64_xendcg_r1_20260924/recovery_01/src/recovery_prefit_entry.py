#!/usr/bin/env python3
"""Parent-release-gated recovery entry for the one failed no-fit prefit stage.

This entry imports and calls the original prefit runner without modifying its
file.  It accepts exactly the immutable attempt1 failure pair as predecessor,
requires a new recovery execution identity and fresh release/review binding,
and supplies the spawn-importable resource/worker modules from recovery_01.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping


RECOVERY_ROOT = Path(__file__).resolve().parents[1]
BATCH_ROOT = RECOVERY_ROOT.parent
PROJECT_ROOT = BATCH_ROOT.parents[3]
RECOVERY_SRC = RECOVERY_ROOT / "src"
ROUTE_SRC = BATCH_ROOT / "src"
CONTRACTS = RECOVERY_ROOT / "contracts"
RUN_SPEC_PATH = CONTRACTS / "RECOVERY_RUN_SPEC_R3.json"
INPUT_BINDING_PATH = CONTRACTS / "RECOVERY_INPUT_BINDING_R3.json"
PREFIT_RELEASE_PATH = CONTRACTS / "PREFIT_RECOVERY01_R3_PARENT_ROW_READ_RELEASE.json"
PREFIT_REVIEW_RECEIPT_PATH = Path(
    "/Users/lexi/Desktop/学习/因子工厂/handoffs/F5_FULL64_XENDCG_R1_20260924/PREFIT_RECOVERY01_R3_ENTRY_REVIEW_TRANSCRIPT.json"
)

ATTEMPT1_EXECUTION_ID = "F5_FULL64_XENDCG_R1_20260924_PREFIT"
ATTEMPT1_START_EVENT_SHA256 = "59eb082e2ce8da3650c6d387f42882c02f6b5048eb5938bf78a477154ef133b7"
ATTEMPT1_TERMINAL_EVENT_SHA256 = "c2008287146f022533fa394b41ba2412ef4c35dc8448fc8579a3a0b22654e232"
ATTEMPT1_RUN_RECEIPT_SHA256 = "b5b61e4a7a8a0b2c63423b91887b018f21c3899213c113751628f46b30d70d4c"
ATTEMPT1_RESOURCE_TRACE_SHA256 = "058ff63df147ec118650aacc0baac775535afad34ed855a83406b9f3238aac98"
ATTEMPT1_REGISTRY_SHA256 = "24eedd8f54932a0444e46849170f3d9add587fe35c0d0dfa0205716c80e910b2"

if str(RECOVERY_SRC) not in sys.path:
    sys.path.insert(0, str(RECOVERY_SRC))
if str(ROUTE_SRC) not in sys.path:
    sys.path.insert(0, str(ROUTE_SRC))

import prefit_runner as runner  # noqa: E402
from recovery_spawn_support import import_resource_tree  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise runner.PrefitError(f"MODULE_LOAD_SPEC_FAILED:{name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _assert_attempt1_only_predecessor(events: list[dict[str, Any]]) -> None:
    route = runner.ROUTE_ID
    scoped = [
        row for row in events
        if row.get("experiment_id") == route or row.get("route_id") == route
    ]
    if len(scoped) != 2:
        raise runner.PrefitError("RECOVERY_PREDECESSOR_ROUTE_EVENT_COUNT_MISMATCH")
    by_type = {str(row.get("event_type")): row for row in scoped}
    if set(by_type) != {"RUN_STARTED", "TERMINAL"}:
        raise runner.PrefitError("RECOVERY_PREDECESSOR_EVENT_TYPES_MISMATCH")
    start = by_type["RUN_STARTED"]
    terminal = by_type["TERMINAL"]
    if (
        start.get("route_id") != route
        or terminal.get("route_id") != route
        or start.get("execution_id") != ATTEMPT1_EXECUTION_ID
        or start.get("event_sha256") != ATTEMPT1_START_EVENT_SHA256
        or start.get("previous_event_sha256") != "b7d3a4ed7daf40853e0b194deec24fd238cc6f85b4d6054ba341f33c9b51f7cd"
        or terminal.get("execution_id") != ATTEMPT1_EXECUTION_ID
        or terminal.get("event_sha256") != ATTEMPT1_TERMINAL_EVENT_SHA256
        or terminal.get("previous_event_sha256") != ATTEMPT1_START_EVENT_SHA256
        or start.get("contract_sha256") != "7e675da01709b40e0bb9713ad50dd7dec021d4b1a4c503f8bf88dedbbebcbbb5"
        or start.get("input_binding_sha256") != "b9273862afed8683925a8ddaf83202e92b55f377f7b57b479730d019f87e5bac"
        or terminal.get("decision") != "CANNOT_CONFIRM"
        or terminal.get("stop_reason") != "PREFIT_WORKER_FAILED"
        or terminal.get("truth_access") != "NO_TRAIN_LABEL_DECODE_MARKER"
    ):
        raise runner.PrefitError("RECOVERY_PREDECESSOR_FAILURE_IDENTITY_MISMATCH")

    start_metrics = start.get("deterministic_metrics", {})
    terminal_metrics = terminal.get("deterministic_metrics", {})
    for metrics in (start_metrics, terminal_metrics):
        if (
            metrics.get("execution_kind") != "NO_FIT_ENGINEERING_CANARY"
            or metrics.get("planned_real_fit_count") != 0
            or metrics.get("real_fit_budget_debit") != 0
        ):
            raise runner.PrefitError("RECOVERY_PREDECESSOR_NONZERO_DEBIT")
    if (
        start_metrics.get("fit_call_entered") is not False
        or terminal_metrics.get("fit_call_entered") is not False
        or terminal_metrics.get("real_fit_returned_count") != 0
    ):
        raise runner.PrefitError("RECOVERY_PREDECESSOR_FIT_ACTIVITY_REPORTED")

    attempt1_dir = BATCH_ROOT / "prefit"
    immutable_artifacts = {
        attempt1_dir / "PREFIT_RUN_RECEIPT.json": ATTEMPT1_RUN_RECEIPT_SHA256,
        attempt1_dir / "PREFIT_RESOURCE_TRACE.json": ATTEMPT1_RESOURCE_TRACE_SHA256,
    }
    for path, expected in immutable_artifacts.items():
        if not path.is_file() or _sha256(path) != expected:
            raise runner.PrefitError(f"RECOVERY_ATTEMPT1_ARTIFACT_DRIFT:{path.name}")
    forbidden_markers = (
        "PREFIT_WORKER_STATUS.json",
        "PREFIT_WORKER_START_RECEIPT.json",
        "PREFIT_INPUT_HASH_RECEIPT.json",
        "TRAIN_LABEL_READ_START_RECEIPT.json",
        "PREFIT_RESULT_RECEIPT.json",
    )
    if any((attempt1_dir / name).exists() for name in forbidden_markers):
        raise runner.PrefitError("RECOVERY_ATTEMPT1_WORKER_OR_INPUT_MARKER_UNEXPECTEDLY_EXISTS")


def _recovery_official_guard(
    binding: Mapping[str, Any],
    *,
    run_spec_sha: str,
    input_binding_sha: str,
    expected_registry_sha256: str,
    expected_release_sha256: str,
    expected_reviewer_receipt_sha256: str,
    expected_source_code_sha256: str,
):
    guard_path = Path(binding["official_helpers"]["execution_guard"]["path"])
    adapter_path = Path(binding["official_helpers"]["registry_adapter"]["path"])
    executable_helpers = runner._executable_helper_bindings(binding)
    runner._verify_file_bindings(executable_helpers, error_prefix="EXECUTABLE_HELPER_SHA_MISMATCH")
    if str(guard_path.parent) not in sys.path:
        sys.path.insert(0, str(guard_path.parent))
    guard_module = _load_module(guard_path, "f5_full64_xendcg_recovery01_execution_guard")
    adapter_module = _load_module(adapter_path, "f5_full64_xendcg_recovery01_registry_adapter")
    recovery_execution_id = str(runner.EXECUTION_ID)

    class RecoveryRegistryAdapter(adapter_module.OfficialRegistryAdapter):
        def claim_run_started(self, event: Mapping[str, Any], *, max_real_fit_debits: int) -> None:
            with self._locked():
                raw, events = self._read_validated()
                if expected_registry_sha256 != ATTEMPT1_REGISTRY_SHA256:
                    raise runner.PrefitError("PARENT_RECOVERY_RELEASE_REGISTRY_SHA_NOT_ATTEMPT1_PREFIX")
                if runner.sha256_bytes(raw) != expected_registry_sha256:
                    raise runner.PrefitError("OFFICIAL_REGISTRY_CHANGED_AFTER_PARENT_RECOVERY_RELEASE")
                _assert_attempt1_only_predecessor(events)
                runner._verify_start_snapshots(
                    release_path=PREFIT_RELEASE_PATH,
                    expected_release_sha256=expected_release_sha256,
                    reviewer_receipt_path=PREFIT_REVIEW_RECEIPT_PATH,
                    expected_reviewer_receipt_sha256=expected_reviewer_receipt_sha256,
                    run_spec_path=RUN_SPEC_PATH,
                    expected_run_spec_sha256=run_spec_sha,
                    input_binding_path=INPUT_BINDING_PATH,
                    expected_input_binding_sha256=input_binding_sha,
                    code_files=binding["code_files"],
                    expected_code_sha256=expected_source_code_sha256,
                    executable_helpers=executable_helpers,
                )
                if max_real_fit_debits != 1 or event.get("execution_kind") != "NO_FIT_ENGINEERING_CANARY":
                    raise runner.PrefitError("RECOVERY_PREFIT_REQUIRES_ZERO_DEBIT_NO_FIT_GUARD")
                if any(str(row.get("execution_id")) == recovery_execution_id for row in events):
                    raise runner.PrefitError("RECOVERY_EXECUTION_ID_ALREADY_REGISTERED")
                if (
                    event.get("experiment_id") != runner.ROUTE_ID
                    or event.get("execution_id") != recovery_execution_id
                    or event.get("contract_sha256") != run_spec_sha
                    or event.get("input_binding_sha256") != input_binding_sha
                    or event.get("real_fit_budget_debit") != 0
                    or event.get("planned_real_fit_count") != 0
                ):
                    raise runner.PrefitError("RECOVERY_RUN_STARTED_IDENTITY_OR_DEBIT_MISMATCH")
                self._append_unlocked(raw, events, self._event_spec(event, event_type="RUN_STARTED"))

        def _event_spec(self, event: Mapping[str, Any], *, event_type: str) -> dict[str, Any]:
            spec = super()._event_spec(event, event_type=event_type)
            spec["runtime"] = {"python": str(Path(sys.executable).resolve()), "python_version": sys.version.split()[0]}
            spec["code_sha256"] = expected_source_code_sha256
            if event_type == "TERMINAL":
                if runner.RESULT_PATH.is_file():
                    spec["truth_access"] = "TRAIN_LABELS_READ_EVAL_LABELS_NOT_DECODED"
                elif runner.TRAIN_LABEL_READ_START_PATH.is_file():
                    spec["truth_access"] = "TRAIN_LABEL_READ_STARTED_EVAL_LABELS_NOT_DECODED"
                elif runner.INPUT_HASH_PATH.is_file():
                    spec["truth_access"] = "FROZEN_INPUT_BYTES_HASHED_TRAIN_LABELS_NOT_DECODED"
                else:
                    spec["truth_access"] = "NO_TRAIN_LABEL_DECODE_MARKER"
                spec["sealed_status"] = "EXPOSED_2024_LABELS_NOT_DECODED"
            return spec

    code_paths = [Path(item["path"]) for item in binding["code_files"].values()]
    artifact_paths = [
        RUN_SPEC_PATH,
        INPUT_BINDING_PATH,
        runner.PLAN_PACKAGE_BINDING_PATH,
        PREFIT_RELEASE_PATH,
        PREFIT_REVIEW_RECEIPT_PATH,
        *code_paths,
        runner.RESOURCE_TREE_PATH,
        runner.NATIVE_RUNTIME_PATH,
        runner.NATIVE_REFERENCE_CONTRACT_PATH,
        *[Path(item["path"]) for item in binding["official_helpers"].values()],
        BATCH_ROOT / "prefit/PREFIT_RUN_RECEIPT.json",
        BATCH_ROOT / "prefit/PREFIT_RESOURCE_TRACE.json",
    ]
    profile = {
        "track_id": "HK_BURST_F5_FULL_HISTORY_RESEARCH",
        "route_id": runner.ROUTE_ID,
        "registration_mode": "LIVE_EXECUTION",
        "start_stage": "INCREMENTAL_PREFIT_RECOVERY01_RUN_STARTED",
        "terminal_stage": "INCREMENTAL_PREFIT_RECOVERY01_TERMINAL",
        "occurred_at_reason": "LIVE_EXECUTION_UTC",
        "baseline_id": "F5_FULL64_ORIGINAL_PLUS_PATH_BINARY_2024",
        "one_variable": "binary_BCE_to_native_rank_xendcg",
        "signal_scope": "ORIGINAL_2018_TO_2023_TRAINING_FOLD",
        "target_scope": "EXPOSED_2024_DEVELOPMENT_EVALUATION_NOT_DECODED_DURING_PREFIT",
        "device": "CPU_RESEARCH_ONLY",
        "evidence_level": "ENGINEERING_CANARY_ONLY",
    }
    adapter = RecoveryRegistryAdapter(
        registry_path=runner.OFFICIAL_REGISTRY_PATH,
        contract_path=RUN_SPEC_PATH,
        input_binding_path=INPUT_BINDING_PATH,
        artifact_paths=artifact_paths,
        builder_path=Path(binding["official_helpers"]["builder"]["path"]),
        validator_path=Path(binding["official_helpers"]["validator"]["path"]),
        event_profile=profile,
    )

    class RecoveryExecutionGuard(guard_module.ExecutionGuard):
        def accounting(self):
            scoped = self.backend.list_events(self.experiment_id)
            current = [row for row in scoped if row.get("execution_id") == recovery_execution_id]
            return guard_module.summarize(current, self.experiment_id)

    return RecoveryExecutionGuard(adapter, experiment_id=runner.ROUTE_ID, max_real_fit_debits=1), adapter


def _recovery_resource_tree_module(binding: Mapping[str, Any]):
    resource_tree = import_resource_tree(runner.RESOURCE_TREE_PATH, str(binding["resource_tree_sha256"]))
    original_monitor = resource_tree.run_spawn_monitored
    output_paths = {key: str(value) for key, value in binding["prefit_output_paths"].items()}
    execution_id = str(runner.EXECUTION_ID)
    route_id = str(runner.ROUTE_ID)

    def recovery_monitor(target, payload, **kwargs):
        if target is not runner._prefit_worker:
            raise runner.PrefitError("RECOVERY_RESOURCE_TARGET_IDENTITY_MISMATCH")
        worker_payload = {
            "recovery_execution_id": execution_id,
            "recovery_route_id": route_id,
            "recovery_output_paths": output_paths,
            "prefit_payload": dict(payload),
            "synthetic_zero_fit_guard": bool(payload.get("recovery_synthetic_zero_fit_guard", False)),
        }
        from recovery_prefit_worker import run_prefit_worker

        return original_monitor(run_prefit_worker, worker_payload, **kwargs)

    resource_tree.run_spawn_monitored = recovery_monitor
    return resource_tree


def configure_recovery_runner() -> dict[str, Any]:
    run_spec, _run_sha = runner.read_json_snapshot(RUN_SPEC_PATH)
    binding, _binding_sha = runner.read_json_snapshot(INPUT_BINDING_PATH)
    execution_id = str(run_spec.get("execution_id", ""))
    if not execution_id.endswith("_PREFIT_RECOVERY01") or execution_id == ATTEMPT1_EXECUTION_ID:
        raise runner.PrefitError("RECOVERY_EXECUTION_ID_INVALID")
    expected_predecessor = {
        "predecessor_execution_id": ATTEMPT1_EXECUTION_ID,
        "predecessor_run_started_event_sha256": ATTEMPT1_START_EVENT_SHA256,
        "predecessor_terminal_event_sha256": ATTEMPT1_TERMINAL_EVENT_SHA256,
        "predecessor_registry_sha256": ATTEMPT1_REGISTRY_SHA256,
        "predecessor_real_fit_debit": 0,
        "recovery_stage": "INCREMENTAL_PREFIT_ONLY",
        "recovery_fit_calls_authorized": 0,
        "recovery_predict_calls_authorized": 0,
        "automatic_retry": False,
    }
    if run_spec.get("recovery") != expected_predecessor or binding.get("recovery_predecessor") != expected_predecessor:
        raise runner.PrefitError("RECOVERY_PREDECESSOR_CONTRACT_MISMATCH")
    if binding.get("recovery_resource_tree_module") != "resource_tree":
        raise runner.PrefitError("RECOVERY_RESOURCE_TREE_IMPORT_CONTRACT_MISMATCH")
    if run_spec.get("route_id") != "F5_FULL64_XENDCG_R1_20260924" or binding.get("route_id") != run_spec.get("route_id"):
        raise runner.PrefitError("RECOVERY_ROUTE_ID_MISMATCH")
    if run_spec.get("input_binding_path") != str(INPUT_BINDING_PATH.resolve()):
        raise runner.PrefitError("RECOVERY_RUN_SPEC_BINDING_PATH_MISMATCH")
    if run_spec.get("prefit_parent_release_path") != str(PREFIT_RELEASE_PATH.resolve()):
        raise runner.PrefitError("RECOVERY_RUN_SPEC_RELEASE_PATH_MISMATCH")
    if binding.get("run_spec_path") != str(RUN_SPEC_PATH.resolve()):
        raise runner.PrefitError("RECOVERY_BINDING_RUN_SPEC_PATH_MISMATCH")

    output_paths = binding.get("prefit_output_paths")
    if not isinstance(output_paths, dict):
        raise runner.PrefitError("RECOVERY_OUTPUT_PATHS_MISSING")
    runner.RUN_SPEC_PATH = RUN_SPEC_PATH
    runner.INPUT_BINDING_PATH = INPUT_BINDING_PATH
    runner.PREFIT_RELEASE_PATH = PREFIT_RELEASE_PATH
    runner.PREFIT_REVIEW_RECEIPT_PATH = PREFIT_REVIEW_RECEIPT_PATH
    runner.ROUTE_ID = str(run_spec["route_id"])
    runner.EXECUTION_ID = execution_id
    runner.PREFIT_DIR = Path(output_paths["root"])
    runner.RESULT_PATH = Path(output_paths["result"])
    runner.RUN_RECEIPT_PATH = Path(output_paths["run_receipt"])
    runner.RESOURCE_TRACE_PATH = Path(output_paths["resource_trace"])
    runner.WORKER_STATUS_PATH = Path(output_paths["worker_status"])
    runner.WORKER_START_PATH = Path(output_paths["worker_start"])
    runner.INPUT_HASH_PATH = Path(output_paths["input_hash_receipt"])
    runner.TRAIN_LABEL_READ_START_PATH = Path(output_paths["train_label_read_start"])
    runner.OFFICIAL_REGISTRY_PATH = Path(binding["official_registry_path"])
    runner._resource_tree_module = _recovery_resource_tree_module
    runner._official_guard = _recovery_official_guard

    return {"route_id": runner.ROUTE_ID, "execution_id": runner.EXECUTION_ID, "run_spec": run_spec, "binding": binding}


def main() -> int:
    configure_recovery_runner()
    result = runner.run_prefit()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
