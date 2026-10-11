#!/usr/bin/env python3
"""Persist the reviewer's exact read-only probe result and append its terminal."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
REG = ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/receipts/r7_recovery_05/registration"
CONTRACT = REG / "R7_RESUME_READONLY_PREFLIGHT_02_CONTRACT.json"
BINDING = REG / "R7_RESUME_READONLY_PREFLIGHT_02_BINDING.json"
START_RECEIPT = REG / "R7_RESUME_READONLY_PREFLIGHT_02_START_RECEIPT.json"
STDOUT = REG / "R7_RESUME_READONLY_PREFLIGHT_02_REVIEWER_STDOUT.log"
STDERR = REG / "R7_RESUME_READONLY_PREFLIGHT_02_REVIEWER_STDERR.log"
OUTPUT = REG / "R7_RESUME_READONLY_PREFLIGHT_02_REVIEWER_OUTPUT.json"
COMMAND_RECEIPT = REG / "R7_RESUME_READONLY_PREFLIGHT_02_COMMAND_RECEIPT.json"
TERMINAL_RECEIPT = REG / "R7_RESUME_READONLY_PREFLIGHT_02_TERMINAL_RECEIPT.json"
ROUTE = "F5_PLUS64_BREADTH1_R7_ONE_PROCESS_LOCAL_VALIDATION_20261011"
EXECUTION = ROUTE + "_R7_RESUME_PREFLIGHT_READONLY_02"
ARM = "LOCAL_R7_RESUME_PREFLIGHT_READONLY_ONLY"
LOCKED = "/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1/.venv_locked/bin/python3.13"
PROFILE = {
    "track_id": "HK_SPIKE_F5_FIXED_TOP20_RESEARCH", "route_id": ROUTE,
    "registration_mode": "LIVE_EXECUTION", "start_stage": "R7_RESUME_READONLY_PREFLIGHT_STARTED",
    "terminal_stage": "R7_RESUME_READONLY_PREFLIGHT_TERMINAL",
    "occurred_at_reason": "R7_READONLY_PREFLIGHT_UTC",
    "baseline_id": "F5_PLUS64_BASE34_PLUS_PATH_FROZEN_R1_20260926",
    "one_variable": "registered_readonly_r7_resume_control_preflight",
    "signal_scope": "R7_RESUME_CONTROL_GRAPH_ONLY",
    "target_scope": "NO_TARGET_INPUTS_OR_MODEL_OR_TRUTH",
    "device": "CPU_RESEARCH_ONLY", "evidence_level": "ENGINEERING_CANARY_ONLY",
}
RAW_STDOUT = '{"buy_gate_updated": false, "error": "name \'PANEL_HEADER_RECOVERY_OUTPUT_PATH\' is not defined", "error_type": "NameError", "fit_calls": 0, "model_load_calls": 0, "orders_sent": false, "predict_calls": 0, "production_allowed": false, "registry_writes_by_probe": 0, "research_only": true, "schema": "BREADTH1_R7_RESUME_READONLY_PREFLIGHT_PROBE_V1", "status": "FAIL_READONLY_RESUME_PREFLIGHT", "target_data_file_reads": 0, "truth_reads": 0}\n'
COMMAND = f"PYTHON={LOCKED} {LOCKED} -I -B {ROOT}/research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/receipts/r7_recovery_05/registration/run_r7_resume_readonly_preflight_probe_02.py"


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def static_artifacts() -> list[Path]:
    batch = ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011"
    src = ROOT / "workspace/f5_breadth1_r3_frozen_input_20261011/src"
    return [
        REG / "run_r7_resume_readonly_preflight_probe_02.py",
        REG / "register_r7_resume_readonly_preflight_02.py",
        REG / "record_r7_resume_readonly_preflight_reviewer_result_02.py",
        ROOT / "workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity/registry_adapter.py",
        ROOT / "workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity/execution_guard_core.py",
        ROOT / "contracts/build_experiment_registry_backfill_20260821.py",
        ROOT / "contracts/validate_experiment_registry_append_compatibility_v1.py",
        batch / "receipts/r7_recovery_05/control_resume/R7_RECOVERY_05_RESUME_AUTHORIZATION_V2.json",
        batch / "receipts/r7_recovery_05/control_resume/R7_RECOVERY_05_RESUME_CONTRACT_V2.json",
        batch / "receipts/r7_recovery_05/control_resume/R7_RECOVERY_05_RESUME_READ_PLAN_V2.json",
        batch / "contracts/BREADTH1_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_DRAFT.json",
        batch / "bindings/REAL_INPUT_BINDING_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_DRAFT.json",
        batch / "bindings/PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_READ_RELEASE.json",
        batch / "bindings/REAL_INPUT_READ_PLAN_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY.json",
        batch / "bindings/PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_GRANT.json",
        batch / "receipts/r7_one_shot_pipeline/PIPELINE_TERMINAL_RECEIPT.json",
        batch / "receipts/r7_one_shot_pipeline_recovery_01/PIPELINE_TERMINAL_RECEIPT.json",
        *sorted(src.glob("*.py")),
    ]


def main() -> None:
    if os.environ.get("PYTHON") != sys.executable:
        raise SystemExit("PYTHON_ENV_MUST_MATCH_EXPLICIT_LOCKED_EXECUTABLE")
    outputs = (STDOUT, STDERR, OUTPUT, COMMAND_RECEIPT, TERMINAL_RECEIPT)
    if any(path.exists() or path.is_symlink() for path in outputs):
        raise SystemExit("REVIEWER_RESULT_OUTPUT_ALREADY_EXISTS_NO_OVERWRITE")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    start_receipt = json.loads(START_RECEIPT.read_text(encoding="utf-8"))
    if (contract.get("execution_id") != EXECUTION or binding.get("execution_id") != EXECUTION
            or binding.get("contract_sha256") != sha(CONTRACT)
            or start_receipt.get("contract_sha256") != sha(CONTRACT)
            or start_receipt.get("binding_sha256") != sha(BINDING)
            or start_receipt.get("event_sha256") != "28261af8dbb380e31777b198a790986ed5666757fc236abcfd676b7c547bb3d3"):
        raise SystemExit("REGISTERED_READONLY_PROBE_IDENTITY_MISMATCH")
    reviewer_result = json.loads(RAW_STDOUT)
    if (reviewer_result.get("status") != "FAIL_READONLY_RESUME_PREFLIGHT"
            or reviewer_result.get("error") != "name 'PANEL_HEADER_RECOVERY_OUTPUT_PATH' is not defined"
            or reviewer_result.get("target_data_file_reads") != 0
            or reviewer_result.get("fit_calls") != 0 or reviewer_result.get("predict_calls") != 0
            or reviewer_result.get("model_load_calls") != 0 or reviewer_result.get("truth_reads") != 0
            or reviewer_result.get("registry_writes_by_probe") != 0):
        raise SystemExit("REVIEWER_OUTPUT_UNEXPECTED_OR_ACTION_COUNTS_NONZERO")
    STDOUT.write_bytes(RAW_STDOUT.encode("utf-8"))
    STDERR.write_bytes(b"")
    OUTPUT.write_text(json.dumps({
        "schema": "BREADTH1_R7_RESUME_READONLY_PREFLIGHT_REVIEWER_OUTPUT_V1",
        "reviewer_reported_start_utc": "2026-10-11T13:42:20Z",
        "reviewer_reported_return_utc": "2026-10-11T13:42:24Z",
        "reviewer_reported_elapsed_seconds": 0.297459,
        "exit_code": 1,
        "stdout_path": str(STDOUT.resolve()),
        "stdout_sha256": sha(STDOUT),
        "stderr_path": str(STDERR.resolve()),
        "stderr_sha256": sha(STDERR),
        "result": reviewer_result,
        "interpretation": "The independent no-target probe stopped at an unresolved resume constant before target access; it confirms zero target/model/truth actions and zero R7 action debit. This is a failed engineering validation, not a PASS.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command_receipt = {
        "schema": "BREADTH1_R7_RESUME_READONLY_PREFLIGHT_COMMAND_RECEIPT_V1",
        "command": COMMAND,
        "execution_id": EXECUTION,
        "reviewer_execution_start_utc": "2026-10-11T13:42:20Z",
        "reviewer_execution_return_utc": "2026-10-11T13:42:24Z",
        "elapsed_seconds": 0.297459,
        "exit_code": 1,
        "probe_sha256": sha(REG / "run_r7_resume_readonly_preflight_probe_02.py"),
        "contract_sha256": sha(CONTRACT),
        "binding_sha256": sha(BINDING),
        "run_started_event_sha256": start_receipt["event_sha256"],
        "reviewer_output_path": str(OUTPUT.resolve()),
        "reviewer_output_sha256": sha(OUTPUT),
        "stdout_path": str(STDOUT.resolve()), "stdout_sha256": sha(STDOUT),
        "stderr_path": str(STDERR.resolve()), "stderr_sha256": sha(STDERR),
        "target_input_reads": 0,
        "fit_calls": 0, "predict_calls": 0, "model_load_calls": 0, "truth_reads": 0,
        "registry_writes_by_probe": 0,
        "safety": {"research_only": True, "production_allowed": False,
                    "buy_gate_updated": False, "orders_sent": False},
    }
    COMMAND_RECEIPT.write_text(json.dumps(command_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sys.path.insert(0, str(ROOT / "workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity"))
    from execution_guard_core import ExecutionClaim, ExecutionGuard, NO_FIT_ENGINEERING_KIND
    from registry_adapter import OfficialRegistryAdapter

    adapter = OfficialRegistryAdapter(
        registry_path=ROOT / "contracts/EXPERIMENT_REGISTRY.jsonl",
        contract_path=CONTRACT,
        input_binding_path=BINDING,
        artifact_paths=[*static_artifacts(), STDOUT, STDERR, OUTPUT, COMMAND_RECEIPT],
        event_profile=PROFILE,
    )
    events = list(adapter.list_events(ROUTE))
    matches = [event for event in events if event.get("execution_id") == EXECUTION]
    starts = [event for event in matches if event.get("event_type") == "RUN_STARTED"]
    terminals = [event for event in matches if event.get("event_type") == "TERMINAL"]
    if len(starts) != 1 or len(terminals) != 0:
        raise SystemExit("REGISTERED_PREFLIGHT_LIFECYCLE_NOT_TERMINALIZABLE")
    start = starts[0]
    claim = ExecutionClaim(
        experiment_id=ROUTE, execution_id=EXECUTION, arm=ARM,
        contract_sha256=sha(CONTRACT), input_binding_sha256=sha(BINDING),
        execution_kind=NO_FIT_ENGINEERING_KIND, real_fit_budget_debit=0,
    )
    guard = ExecutionGuard(adapter, experiment_id=ROUTE, max_real_fit_debits=0)
    guard.append_no_fit_terminal(claim, succeeded=False, error_type="NameError")
    after = list(adapter.list_events(ROUTE))
    terminal_events = [event for event in after
                       if event.get("execution_id") == EXECUTION and event.get("event_type") == "TERMINAL"]
    if len(terminal_events) != 1 or terminal_events[0].get("previous_event_sha256") != start.get("event_sha256"):
        raise SystemExit("REGISTERED_PREFLIGHT_TERMINAL_IDENTITY_MISMATCH")
    terminal_event = terminal_events[0]
    terminal_receipt = {
        "schema": "BREADTH1_R7_RESUME_READONLY_PREFLIGHT_TERMINAL_RECEIPT_V1",
        "status": terminal_event.get("terminal_status"),
        "decision": "CANNOT_CONFIRM_ENGINEERING_CANARY",
        "route_id": ROUTE, "execution_id": EXECUTION,
        "run_started_event_sha256": start.get("event_sha256"),
        "terminal_event_sha256": terminal_event.get("event_sha256"),
        "terminal_error_type": terminal_event.get("error_type"),
        "reviewer_output_path": str(OUTPUT.resolve()), "reviewer_output_sha256": sha(OUTPUT),
        "command_receipt_path": str(COMMAND_RECEIPT.resolve()), "command_receipt_sha256": sha(COMMAND_RECEIPT),
        "stdout_path": str(STDOUT.resolve()), "stdout_sha256": sha(STDOUT),
        "stderr_path": str(STDERR.resolve()), "stderr_sha256": sha(STDERR),
        "r7_logical_admission_debit_preserved": 1,
        "additional_r7_debit": 0,
        "target_input_reads": 0,
        "fit_calls": 0, "predict_calls": 0, "model_load_calls": 0, "truth_reads": 0,
        "research_only": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
    }
    TERMINAL_RECEIPT.write_text(json.dumps(terminal_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": terminal_receipt["status"], "terminal_event_sha256": terminal_event.get("event_sha256"),
                      "terminal_receipt_sha256": sha(TERMINAL_RECEIPT), "r7_debit": 1,
                      "additional_r7_debit": 0, "target_reads": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
