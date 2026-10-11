#!/usr/bin/env python3
"""Append the zero-fit start for one independent read-only resume probe."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
GUARD = ROOT / "workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity"
REG = ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/receipts/r7_recovery_05/registration"
CONTRACT = REG / "R7_RESUME_READONLY_PREFLIGHT_02_CONTRACT.json"
BINDING = REG / "R7_RESUME_READONLY_PREFLIGHT_02_BINDING.json"
START_RECEIPT = REG / "R7_RESUME_READONLY_PREFLIGHT_02_START_RECEIPT.json"
REGISTRY = ROOT / "contracts/EXPERIMENT_REGISTRY.jsonl"
ROUTE = "F5_PLUS64_BREADTH1_R7_ONE_PROCESS_LOCAL_VALIDATION_20261011"
EXECUTION = ROUTE + "_R7_RESUME_PREFLIGHT_READONLY_02"
ARM = "LOCAL_R7_RESUME_PREFLIGHT_READONLY_ONLY"
PROFILE = {
    "track_id": "HK_SPIKE_F5_FIXED_TOP20_RESEARCH",
    "route_id": ROUTE,
    "registration_mode": "LIVE_EXECUTION",
    "start_stage": "R7_RESUME_READONLY_PREFLIGHT_STARTED",
    "terminal_stage": "R7_RESUME_READONLY_PREFLIGHT_TERMINAL",
    "occurred_at_reason": "R7_READONLY_PREFLIGHT_UTC",
    "baseline_id": "F5_PLUS64_BASE34_PLUS_PATH_FROZEN_R1_20260926",
    "one_variable": "registered_readonly_r7_resume_control_preflight",
    "signal_scope": "R7_RESUME_CONTROL_GRAPH_ONLY",
    "target_scope": "NO_TARGET_INPUTS_OR_MODEL_OR_TRUTH",
    "device": "CPU_RESEARCH_ONLY",
    "evidence_level": "ENGINEERING_CANARY_ONLY",
}


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> None:
    if os.environ.get("PYTHON") != sys.executable:
        raise SystemExit("PYTHON_ENV_MUST_MATCH_EXPLICIT_LOCKED_EXECUTABLE")
    if START_RECEIPT.exists() or START_RECEIPT.is_symlink():
        raise SystemExit("PREFLIGHT_START_RECEIPT_EXISTS_NO_REUSE")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    contract_sha, binding_sha = sha(CONTRACT), sha(BINDING)
    if (contract.get("route_id") != ROUTE or contract.get("execution_id") != EXECUTION
            or binding.get("contract_sha256") != contract_sha
            or binding.get("execution_id") != EXECUTION):
        raise SystemExit("PREFLIGHT_REGISTRATION_IDENTITY_MISMATCH")
    sys.path.insert(0, str(GUARD))
    from execution_guard_core import ExecutionGuard
    from registry_adapter import OfficialRegistryAdapter

    artifact_paths = [
        REG / "run_r7_resume_readonly_preflight_probe_02.py",
        REG / "register_r7_resume_readonly_preflight_02.py",
        ROOT / "workspace/f5_breadth1_r3_frozen_input_20261011/src/run_f5_breadth1.py",
        *sorted((ROOT / "workspace/f5_breadth1_r3_frozen_input_20261011/src").glob("*.py")),
        ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/receipts/r7_recovery_05/control_resume/R7_RECOVERY_05_RESUME_AUTHORIZATION_V2.json",
        ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/receipts/r7_recovery_05/control_resume/R7_RECOVERY_05_RESUME_CONTRACT_V2.json",
        ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/receipts/r7_recovery_05/control_resume/R7_RECOVERY_05_RESUME_READ_PLAN_V2.json",
        ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/contracts/BREADTH1_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_DRAFT.json",
        ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/bindings/REAL_INPUT_BINDING_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_DRAFT.json",
        ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/bindings/PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_READ_RELEASE.json",
        ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/bindings/REAL_INPUT_READ_PLAN_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY.json",
        ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/bindings/PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_GRANT.json",
        ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/receipts/r7_one_shot_pipeline_recovery_01/PIPELINE_TERMINAL_RECEIPT.json",
        ROOT / "workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity/registry_adapter.py",
        ROOT / "workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity/execution_guard_core.py",
        ROOT / "contracts/build_experiment_registry_backfill_20260821.py",
        ROOT / "contracts/validate_experiment_registry_append_compatibility_v1.py",
    ]
    adapter = OfficialRegistryAdapter(
        registry_path=REGISTRY, contract_path=CONTRACT, input_binding_path=BINDING,
        artifact_paths=artifact_paths, event_profile=PROFILE,
    )
    guard = ExecutionGuard(adapter, experiment_id=ROUTE, max_real_fit_debits=0)
    claim = guard.claim_no_fit(
        execution_id=EXECUTION, arm=ARM,
        contract_sha256=contract_sha, input_binding_sha256=binding_sha,
    )
    matching = [event for event in adapter.list_events(ROUTE)
                if event.get("execution_id") == EXECUTION]
    starts = [event for event in matching if event.get("event_type") == "RUN_STARTED"]
    if len(starts) != 1 or any(event.get("event_type") == "TERMINAL" for event in matching):
        raise SystemExit("PREFLIGHT_START_LIFECYCLE_NOT_UNIQUE")
    event = dict(starts[0])
    receipt = {
        "schema": "BREADTH1_R7_RESUME_READONLY_PREFLIGHT_START_RECEIPT_V1",
        "status": "RUN_STARTED_REVIEWER_READONLY_BODY_PENDING",
        "route_id": ROUTE,
        "execution_id": EXECUTION,
        "arm": ARM,
        "contract_path": str(CONTRACT.resolve()),
        "contract_sha256": contract_sha,
        "binding_path": str(BINDING.resolve()),
        "binding_sha256": binding_sha,
        "event_sha256": event.get("event_sha256"),
        "registry_event_id": event.get("registry_event_id"),
        "registry_sha256_after_start": sha(REGISTRY),
        "fit_budget_debit": claim.real_fit_budget_debit,
        "target_input_reads": 0,
        "fit_predict_model_truth_calls": 0,
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    with START_RECEIPT.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
