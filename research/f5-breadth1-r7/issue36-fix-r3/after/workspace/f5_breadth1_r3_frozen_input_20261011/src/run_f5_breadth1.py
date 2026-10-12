#!/usr/bin/env python3
"""Frozen-input BREADTH1 admission and one-shot real-run orchestration."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import importlib
import importlib.metadata
import json
from pathlib import Path
import sys
import subprocess
from typing import Any, Mapping
from uuid import uuid4

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd

SRC_DIR = Path(__file__).resolve().parent
CODE_ROOT = SRC_DIR.parent
PROJECT_ROOT = CODE_ROOT.parent.parent
BATCH_ROOT = PROJECT_ROOT / "research" / "hk_burst_f5" / "batches" / "breadth1_r3_frozen_input_20261011"
CONTRACT_PATH = BATCH_ROOT / "contracts" / "BREADTH1_DRAFT.json"
SYNTHETIC_BINDING_PATH = BATCH_ROOT / "bindings" / "SYNTHETIC_INPUT_BINDING.json"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from f5_breadth1_core import (
    CODE_BINDINGS, EXPERIMENT_ID, ROUTE_ID, TRACK_ID, load_frozen_metrics, persist_csv_snapshot,
    persist_mask_snapshot, persist_npy_snapshot, score_to_top3, sha256_file,
    require_strict_positive_int, validate_exact_top3, validate_top3_scores,
    verify_candidate_code_bindings, write_json_exclusive,
)
from f5_breadth1_budget import (
    ActionBudgetClaim, BREADTH1OfficialActionAdapter, CANDIDATE_ID, PANEL_HEADER_RECOVERY_EXECUTION_ID,
    PANEL_HEADER_FAILED_RECEIPT_PATH, PANEL_HEADER_FAILED_REGISTRY_RECEIPT_PATH,
    PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_PATH, PANEL_HEADER_R5_FAILED_RECEIPT_PATH,
    PANEL_HEADER_R6_FAILED_RECEIPT_PATH,
    PANEL_HEADER_RECOVERY_GRANT_PATH, PANEL_HEADER_RECOVERY_READ_PLAN_PATH,
    PANEL_HEADER_RECOVERY_READ_RELEASE_PATH, PANEL_HEADER_DIAGNOSTIC_RECEIPT_PATH,
    TRAIN_LABEL_DIAGNOSTIC_RECEIPT_PATH, VerifiedActionRelease, VerifiedActionContext,
    PANEL_HEADER_RECOVERY_ACTION_KEY, PANEL_HEADER_RECOVERY_GRANT_ID,
    PANEL_HEADER_RECOVERY_READ_RELEASE_PATH, PANEL_HEADER_RECOVERY_OUTPUT_PATH, PANEL_HEADER_RECOVERY_RESUME_AUTH_PATH,
    PANEL_HEADER_RECOVERY_RESUME_CONTRACT_PATH, PANEL_HEADER_RECOVERY_RESUME_PENDING_BINDING_PATH,
    PANEL_HEADER_RECOVERY_RESUME_READ_RELEASE_PATH, PANEL_HEADER_RECOVERY_RESUME_FINAL_BINDING_PATH,
    PANEL_HEADER_RECOVERY_RESUME_RUN_PATH, PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_PATH,
    PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_SHA256,
)
from f5_breadth1_evaluate import evaluate_real_truth_once, evaluate_synthetic_artifacts
from f5_breadth1_inputs import (
    PreparedRealInputs, aggregate_breadth1, append_breadth1_column, audit_real_input_admission,
    load_verified_input_admission_read_release, prepare_real_inputs,
    load_verified_r7_resume_read_release,
    required_sessions_from_keys_and_calendar,
)
from f5_breadth1_worker import assemble_full_g_scores, fit_and_predict_real_once


EVENT_PROFILE = {
    "track_id": TRACK_ID,
    "route_id": ROUTE_ID,
    "registration_mode": "LIVE_EXECUTION",
    "start_stage": "BREADTH1_SYNTHETIC_RUN_STARTED",
    "terminal_stage": "BREADTH1_SYNTHETIC_TERMINAL",
    "occurred_at_reason": "LIVE_ENGINEERING_CANARY_UTC",
    "baseline_id": "F5_PLUS64_BASE34_PLUS_PATH_FROZEN_R1_20260926",
    "one_variable": "full_parent_pool_positive_finite_return_share_BREADTH1",
    "signal_scope": "SYNTHETIC_FIXTURE_ONLY",
    "target_scope": "SYNTHETIC_FIXTURE_ONLY",
    "device": "CPU_RESEARCH_ONLY",
    "evidence_level": "ENGINEERING_CANARY_ONLY",
}

LOCKED_SYNTHETIC_RUNTIME = {
    "python_version": "3.13.12",
    "python_executable_invocation_path": "/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1/.venv_locked/bin/python3.13",
    "python_executable_resolved_path": "/Users/lexi/Documents/Codex/2026-08-13/v35-019ff682/runtime/python/cpython-3.13.12-macos-aarch64-none/bin/python3.13",
    "python_executable_sha256": "95fb891ec36d4022bdf62172f9d3c757fb3c7b1669a274cacc87fe261a535b7e",
    "site_packages_path": "/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1/.venv_locked/lib/python3.13/site-packages",
    "environment_lock_receipt_path": "/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/outputs/HK_SPIKE_F5_INTAKE_20260914/ENVIRONMENT_LOCK_RECEIPT.json",
    "environment_lock_receipt_sha256": "e00665080e28f74f328463a0f6aabdeda4ed8bd3bf236edbca6ca128208193c6",
    "requirements_lock_path": "/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1/requirements.lock.txt",
    "requirements_lock_sha256": "73348b7f14b4689459de16d626fed1eb8d2d9392fcbebfb38fa2856078c52f78",
    "package_source": "REUSED_EXISTING_ACCEPTED_LOCKED_RUNTIME_NO_INSTALL",
    "packages": {
        "numpy": "2.3.5",
        "pandas": "2.2.3",
        "scikit-learn": "1.8.0",
        "scipy": "1.17.0",
        "lightgbm": "4.6.0",
        "joblib": "1.5.3",
        "threadpoolctl": "3.6.0",
        "pytest": "9.0.2",
        "psutil": "7.2.2",
    },
    "lightgbm_imported": False,
    "fit_calls": 0,
}

class SyntheticChainError(RuntimeError):
    pass


def _chain_error_details(exc: BaseException) -> dict[str, Any]:
    """Keep a bounded original cause chain when adapters wrap a failure."""
    chain = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append({"error_type": type(current).__name__, "error": str(current),
                      "error_notes": list(getattr(current, "__notes__", ()))})
        current = (current.__cause__ if current.__cause__ is not None else
                   None if current.__suppress_context__ else current.__context__)
    return {"error_type": type(exc).__name__, "error": str(exc),
            "error_notes": list(getattr(exc, "__notes__", ())),
            "exception_chain": chain, "exception_chain_truncated": current is not None}


def _r7_chain_paths() -> dict[str, Path]:
    """Fixed current R7 identities; no caller-selected recovery or output ID."""
    return {
        "contract": BATCH_ROOT / "contracts" / "BREADTH1_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_DRAFT.json",
        "pending_binding": BATCH_ROOT / "bindings" / "REAL_INPUT_BINDING_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY_DRAFT.json",
        "final_binding": BATCH_ROOT / "bindings" / "REAL_INPUT_BINDING_ADMITTED_PARENT_PANEL_DATE_RECOVERY_R7_ENGINEERING_RETRY.json",
        "scope_lock": BATCH_ROOT / "SCOPE_LOCK_R7_PARENT_PANEL_DATE_RECOVERY.md",
        "run": BATCH_ROOT / "receipts" / "r7_one_shot_pipeline_recovery_01",
        "resume_contract": PANEL_HEADER_RECOVERY_RESUME_CONTRACT_PATH,
        "resume_pending_binding": PANEL_HEADER_RECOVERY_RESUME_PENDING_BINDING_PATH,
        "resume_read_release": PANEL_HEADER_RECOVERY_RESUME_READ_RELEASE_PATH,
        "resume_final_binding": PANEL_HEADER_RECOVERY_RESUME_FINAL_BINDING_PATH,
        "resume_run": PANEL_HEADER_RECOVERY_RESUME_RUN_PATH,
        "resume_authorization": PANEL_HEADER_RECOVERY_RESUME_AUTH_PATH,
    }


def _read_chain_control(path: Path, expected_sha256: str | None = None) -> tuple[dict[str, Any], str]:
    """Read only one bounded in-batch control JSON, never a target input."""
    from f5_breadth1_budget import _parse_json_object

    path = Path(path)
    root = BATCH_ROOT.resolve()
    try:
        relative = path.absolute().relative_to(root)
    except ValueError as exc:
        raise SyntheticChainError("CHAIN_CONTROL_OUTSIDE_BATCH") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SyntheticChainError("CHAIN_CONTROL_SYMLINK_NOT_ALLOWED")
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise SyntheticChainError("CHAIN_CONTROL_MISSING_OR_OVERSIZED")
    with path.open("rb") as handle:
        payload = handle.read(16 * 1024 * 1024 + 1)
    if len(payload) > 16 * 1024 * 1024:
        raise SyntheticChainError("CHAIN_CONTROL_GREW_PAST_BOUND")
    digest = sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise SyntheticChainError("CHAIN_CONTROL_SHA_MISMATCH")
    return dict(_parse_json_object(payload, "CHAIN_CONTROL")), digest


def _preflight_registered_real_chain() -> dict[str, Any]:
    """Validate code/runtime/control identities and unused keys, without claim."""
    paths = _r7_chain_paths()
    contract, contract_sha = _read_chain_control(paths["contract"])
    _, pending_sha = _read_chain_control(paths["pending_binding"])
    # The name is historical; this verifier binds the same recorded locked
    # interpreter/packages and only reads code/environment control receipts.
    runtime = contract.get("synthetic_test_runtime")
    _verify_synthetic_runtime(runtime, runtime)
    if contract.get("safety") != {
        "research_only": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
    }:
        raise SyntheticChainError("CHAIN_RESEARCH_ONLY_FLAGS_MISMATCH")
    run_path = paths["run"]
    official = _make_official_adapter(
        run_path, run_path / "PIPELINE_TERMINAL_RECEIPT.json",
        contract_path=paths["contract"], input_binding_path=paths["pending_binding"],
        scope_lock_path=paths["scope_lock"],
        event_profile={**EVENT_PROFILE,
                       "signal_scope": "FROZEN_INPUT_AS_OBSERVED_RESEARCH",
                       "target_scope": "ORIGINAL_F5_NEW_DAILY_TOP3"},
    )
    budget = BREADTH1OfficialActionAdapter(
        official, contract_sha256=contract_sha, input_binding_sha256=pending_sha,
        synthetic=False, admission_only=True,
    )
    budget._read_pending_admission_snapshot()
    grant_payload, grant = budget._read_fixed_panel_header_recovery_grant()
    keys = {PANEL_HEADER_RECOVERY_ACTION_KEY,
            *(f"{ROUTE_ID}:{CANDIDATE_ID}:{name}" for name in ("fit", "predict", "truth_decode"))}
    with official._locked():
        _, events = official._read_validated()
        if any(event.get("budget_action_key") in keys
               or event.get("execution_id") == PANEL_HEADER_RECOVERY_EXECUTION_ID
               for event in events):
            raise SyntheticChainError("R7_OR_MODEL_ACTION_ALREADY_CONSUMED_NO_RETRY")
    return {
        "official": official, "contract_sha256": contract_sha,
        "pending_binding_sha256": pending_sha, "grant": dict(grant),
        "grant_sha256": sha256(grant_payload).hexdigest(),
    }


def _preflight_registered_r7_resume(
    authorization_path: Path,
    authorization_sha256: str,
) -> dict[str, Any]:
    """Verify the one separately authorized R7 continuation before target I/O."""
    paths = _r7_chain_paths()
    if (
        Path(authorization_path).resolve() != paths["resume_authorization"].resolve()
        or not isinstance(authorization_sha256, str) or len(authorization_sha256) != 64
        or paths["resume_run"].exists() or paths["resume_run"].is_symlink()
        or paths["resume_final_binding"].exists() or paths["resume_final_binding"].is_symlink()
    ):
        raise SyntheticChainError("R7_RESUME_FIXED_PATH_OR_NO_OVERWRITE_GATE_FAILED")
    authorization, authorization_sha = _read_chain_control(paths["resume_authorization"], authorization_sha256)
    if authorization.get("schema") != "BREADTH1_R7_PRETARGET_RESUME_AUTHORIZATION_V3" or authorization.get("status") != "AUTHORIZED_PRETARGET_ENGINEERING_RESUMPTION":
        raise SyntheticChainError("R7_RESUME_AUTHORIZATION_STATUS_MISMATCH")
    # Previous physical attempt must remain in place and be exactly failed.
    previous = authorization.get("previous_engineering_attempt")
    previous_path = BATCH_ROOT / "receipts" / "r7_recovery_05" / "resume_invocation_02" / "PIPELINE_TERMINAL_RECEIPT.json"
    if (not isinstance(previous, Mapping)
            or previous.get("pipeline_terminal_path") != str(previous_path.resolve())
            or previous.get("pipeline_terminal_sha256") != "254e63c23c0b9b11b2685725796b4ebcfcafc234fd1eb5b2d086f04e655e76bd"):
        raise SyntheticChainError("R7_PREVIOUS_ENGINEERING_ATTEMPT_IDENTITY_MISSING")
    previous_terminal, _ = _read_chain_control(previous_path, previous["pipeline_terminal_sha256"])
    if (previous_terminal.get("stage") != "input_admission"
            or previous_terminal.get("status") != "NO_FIT"
            or previous_terminal.get("error") != "FIRST_PASS_FIXED_INPUT_ADMISSION_ACTION_NOT_PRESENT_IN_OFFICIAL_REGISTRY"
            or previous_terminal.get("action_debits") != {"admission": 1, "fit": 0, "predict": 0, "truth_decode": 0}
            or previous_terminal.get("input_read_observation") is not None
            or any(previous_terminal.get(k) != 0 for k in ("real_fit_calls", "real_predict_calls", "real_model_load_calls", "real_truth_decode_calls"))):
        raise SyntheticChainError("R7_PREVIOUS_ENGINEERING_ATTEMPT_NOT_PRETARGET")
    old_identity = authorization.get("original_r7_identity")
    failure = authorization.get("preserved_original_failure")
    controls = authorization.get("resume_control_identity")
    original_controls = authorization.get("original_control_identity")
    if not all(isinstance(item, Mapping) for item in (old_identity, failure, controls, original_controls)):
        raise SyntheticChainError("R7_RESUME_AUTHORIZATION_IDENTITY_INCOMPLETE")
    original_contract, original_contract_sha = _read_chain_control(paths["contract"], old_identity.get("contract_sha256"))
    original_binding, original_binding_sha = _read_chain_control(paths["pending_binding"], old_identity.get("input_binding_sha256"))
    original_release, original_release_sha = _read_chain_control(PANEL_HEADER_RECOVERY_READ_RELEASE_PATH, old_identity.get("read_release_sha256"))
    original_plan, original_plan_sha = _read_chain_control(
        PANEL_HEADER_RECOVERY_READ_PLAN_PATH, original_controls.get("read_plan_sha256")
    )
    original_grant, original_grant_sha = _read_chain_control(
        PANEL_HEADER_RECOVERY_GRANT_PATH, original_controls.get("grant_sha256")
    )
    if (
        original_controls.get("contract_sha256") != original_contract_sha
        or original_controls.get("pending_binding_sha256") != original_binding_sha
        or original_controls.get("read_release_sha256") != original_release_sha
        or original_controls.get("grant_sha256") != original_grant_sha
        or original_binding.get("contract_sha256") != original_contract_sha
        or original_grant.get("grant_id") != PANEL_HEADER_RECOVERY_GRANT_ID
        or original_grant.get("execution_id") != PANEL_HEADER_RECOVERY_EXECUTION_ID
        or original_grant.get("budget_action_key") != PANEL_HEADER_RECOVERY_ACTION_KEY
        or original_grant.get("action_cap") != 1
        or original_grant.get("failure_or_interruption_refund") is not False
        or original_plan.get("contract_sha256") != original_contract_sha
        or original_plan.get("pre_admission_binding_sha256") != original_binding_sha
        or original_plan.get("read_release_sha256") != original_release_sha
        or original_plan.get("recovery_grant_id") != PANEL_HEADER_RECOVERY_GRANT_ID
        or original_plan.get("recovery_execution_id") != PANEL_HEADER_RECOVERY_EXECUTION_ID
    ):
        raise SyntheticChainError("R7_RESUME_ORIGINAL_CONTROL_IDENTITY_MISMATCH")
    contract, contract_sha = _read_chain_control(paths["resume_contract"], controls.get("contract_sha256"))
    pending_binding, pending_sha = _read_chain_control(paths["resume_pending_binding"], controls.get("pending_binding_sha256"))
    _, read_release_sha = _read_chain_control(paths["resume_read_release"], controls.get("read_release_sha256"))
    resume_plan_path = BATCH_ROOT / "receipts" / "r7_recovery_06" / "control_resume" / "R7_RECOVERY_06_RESUME_READ_PLAN_V3.json"
    resume_plan, resume_plan_sha = _read_chain_control(resume_plan_path, controls.get("read_plan_sha256"))
    if (
        resume_plan.get("contract_sha256") != contract_sha
        or resume_plan.get("pre_admission_binding_sha256") != pending_sha
        or resume_plan.get("pre_admission_binding_path") != str(paths["resume_pending_binding"].resolve())
        or resume_plan.get("read_release_sha256") != read_release_sha
        or resume_plan.get("read_release_path") != str(paths["resume_read_release"].resolve())
        or resume_plan.get("recovery_execution_id") != PANEL_HEADER_RECOVERY_EXECUTION_ID
        or resume_plan.get("recovery_action_key") != PANEL_HEADER_RECOVERY_ACTION_KEY
        or resume_plan.get("recovery_output_path") != str(paths["resume_run"].relative_to(PROJECT_ROOT))
        or controls.get("read_plan_sha256") != resume_plan_sha
    ):
        raise SyntheticChainError("R7_RESUME_V3_PLAN_DOES_NOT_BIND_ACTIVE_INPUT")
    if (
        contract.get("status") != "DRAFT_NO_REAL_RUN"
        or contract.get("is_execution_contract") is not False
        or pending_binding.get("status") != "ADMISSION_PENDING"
        or pending_binding.get("synthetic_only") is not False
        or pending_binding.get("contract_sha256") != contract_sha
        or pending_binding.get("route_id") != ROUTE_ID
        or pending_binding.get("candidate_id") != CANDIDATE_ID
        or controls.get("contract_sha256") != contract_sha
        or controls.get("pending_binding_sha256") != pending_sha
        or controls.get("read_release_sha256") != read_release_sha
        or controls.get("grant_sha256") != original_grant_sha
    ):
        raise SyntheticChainError("R7_RESUME_CONTROL_GRAPH_MISMATCH")
    if contract.get("safety") != {
        "research_only": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
    }:
        raise SyntheticChainError("R7_RESUME_RESEARCH_ONLY_FLAGS_MISMATCH")
    event_profile = {
        **EVENT_PROFILE,
        "signal_scope": "FROZEN_INPUT_AS_OBSERVED_RESEARCH",
        "target_scope": "ORIGINAL_F5_NEW_DAILY_TOP3",
    }
    official = _make_official_adapter(
        paths["resume_run"], paths["resume_run"] / "PIPELINE_TERMINAL_RECEIPT.json",
        contract_path=paths["resume_contract"], input_binding_path=paths["resume_pending_binding"],
        scope_lock_path=paths["scope_lock"], event_profile=event_profile,
    )
    action_budget = BREADTH1OfficialActionAdapter(
        official, contract_sha256=contract_sha, input_binding_sha256=pending_sha,
        synthetic=False, admission_only=True,
    )
    action_budget._read_pending_admission_snapshot()
    events = official.list_events(EXPERIMENT_ID)
    action_events = [event for event in events if event.get("budget_action_key") == PANEL_HEADER_RECOVERY_ACTION_KEY]
    starts = [event for event in action_events if event.get("event_type") == "RUN_STARTED"]
    terminals = [event for event in action_events if event.get("event_type") == "TERMINAL"]
    start, terminal = (starts[0], terminals[0]) if len(starts) == len(terminals) == 1 else ({}, {})
    fit_keys = {f"{ROUTE_ID}:{CANDIDATE_ID}:{name}" for name in ("fit", "predict", "truth_decode")}
    if (
        failure.get("terminal_event_id") != f"{PANEL_HEADER_RECOVERY_EXECUTION_ID}_TERMINAL"
        or terminal.get("registry_event_id") != failure.get("terminal_event_id")
        or len(starts) != 1 or len(terminals) != 1 or len(action_events) != 2
        or start.get("execution_id") != PANEL_HEADER_RECOVERY_EXECUTION_ID
        or start.get("event_sha256") != failure.get("start_event_sha256")
        or terminal.get("event_sha256") != failure.get("terminal_event_sha256")
        or start.get("contract_sha256") != original_contract_sha
        or start.get("input_binding_sha256") != original_binding_sha
        or start.get("deterministic_metrics", {}).get("budget_release_sha256") != original_release_sha
        or start.get("budget_action_debit") != 1
        or terminal.get("decision") != "CANNOT_CONFIRM_ACTION_FAILED"
        or terminal.get("budget_action_debit") != 0
        or any(event.get("budget_action_key") in fit_keys for event in events)
        or terminal.get("started_event_sha256") != start.get("event_sha256")
        or not isinstance(start.get("artifact_sha256"), list)
        or any(value not in start.get("artifact_sha256", []) for value in (
            original_contract_sha, original_binding_sha, original_grant_sha, original_plan_sha,
        ))
        or failure.get("pipeline_terminal_path") != str(PANEL_HEADER_RECOVERY_OUTPUT_PATH / "PIPELINE_TERMINAL_RECEIPT.json")
        or not PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_PATH.is_file()
        or PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_PATH.is_symlink()
        or sha256_file(PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_PATH) != PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_SHA256
    ):
        raise SyntheticChainError("R7_RESUME_PRIOR_ACTION_LIFECYCLE_NOT_EXACT_OR_ALREADY_ADVANCED")
    prior, _ = _read_chain_control(
        PANEL_HEADER_RECOVERY_OUTPUT_PATH / "PIPELINE_TERMINAL_RECEIPT.json",
        failure.get("pipeline_terminal_sha256"),
    )
    if (
        prior.get("status") != "NO_FIT" or prior.get("stage") != "input_admission"
        or prior.get("error_type") != "AdmissionBlocked"
        or prior.get("error") != "INPUT_ADMISSION_RELEASE_BINDING_FILE_IDENTITY_MISMATCH"
        or prior.get("input_read_observation") is not None
        or prior.get("action_debits") != {"admission": 1, "fit": 0, "predict": 0, "truth_decode": 0}
        or prior.get("real_fit_calls") != 0 or prior.get("real_predict_calls") != 0
        or prior.get("real_model_load_calls") != 0 or prior.get("real_truth_decode_calls") != 0
    ):
        raise SyntheticChainError("R7_RESUME_PRIOR_FAILURE_NOT_PROVEN_PRETARGET")
    resume_auth_value = {
        **authorization,
        "authorization_ref": {"path": str(paths["resume_authorization"].resolve()), "sha256": authorization_sha},
    }
    verified_release = load_verified_r7_resume_read_release(
        paths["resume_read_release"], read_release_sha,
        contract_sha256=contract_sha, input_binding_sha256=pending_sha,
        input_binding_path=paths["resume_pending_binding"],
        resume_authorization=resume_auth_value,
    )
    claim_metrics = start.get("deterministic_metrics")
    claim = ActionBudgetClaim(
        route_id=ROUTE_ID, candidate_id=CANDIDATE_ID, action="input_admission_recovery",
        action_key=PANEL_HEADER_RECOVERY_ACTION_KEY, execution_id=PANEL_HEADER_RECOVERY_EXECUTION_ID,
        contract_sha256=original_contract_sha, input_binding_sha256=original_binding_sha,
        release_sha256=str(claim_metrics.get("budget_release_sha256")), sealed_status="NOT_CHECKED",
        registry_event_id=str(start.get("registry_event_id")), registry_event_sha256=str(start.get("event_sha256")),
    )
    return {
        "official": official, "contract_sha256": contract_sha,
        "pending_binding_sha256": pending_sha, "grant": original_grant,
        "grant_sha256": original_grant_sha, "resume": resume_auth_value,
        "resume_claim": claim, "resume_release": verified_release,
        "resume_start_event": start, "resume_failure_terminal_event": terminal,
        "original_contract_sha256": original_contract_sha,
        "original_binding_sha256": original_binding_sha,
        "original_release_sha256": original_release_sha,
        "authorization_sha256": authorization_sha,
    }


def _rebind_cached_prepared_inputs(
    prepared: PreparedRealInputs, context: VerifiedActionContext,
) -> PreparedRealInputs:
    """Promote only receipt identity after proving the exact admission link."""
    if not isinstance(prepared, PreparedRealInputs) or not isinstance(context, VerifiedActionContext):
        raise SyntheticChainError("CHAIN_REQUIRES_VERIFIED_CONTEXT_AND_CACHED_INPUTS")
    binding = context.input_binding_value
    receipt = prepared.receipt
    pre_sha = binding.get("pre_admission_binding_sha256")
    verified = binding.get("verified_arrays")
    admission = context.input_admission_receipt_value
    if (
        binding.get("status") != "PASS"
        or receipt.get("status") != "PREPARED_AWAITING_WORKER"
        or not isinstance(pre_sha, str) or len(pre_sha) != 64
        or pre_sha == context.input_binding_sha256
        or receipt.get("input_binding_sha256") != pre_sha
        or admission.get("input_binding_sha256") != pre_sha
        or admission.get("pre_admission_binding_sha256") != pre_sha
        or receipt.get("input_admission_receipt_sha256") != context.input_admission_receipt_sha256
        or binding.get("input_admission_receipt_sha256") != context.input_admission_receipt_sha256
        or not isinstance(verified, Mapping) or verified.get("status") != "PASS"
        or receipt.get("verified_arrays") != {key: value for key, value in verified.items() if key != "status"}
    ):
        raise SyntheticChainError("CACHED_INPUT_ADMISSION_TO_FINAL_BINDING_MISMATCH")
    return replace(prepared, receipt={
        **dict(receipt), "pre_admission_binding_sha256": pre_sha,
        "input_binding_sha256": context.input_binding_sha256,
        "same_process_cache_reused": True, "additional_target_reads": 0,
    })


def _make_chain_action_budget(audit: Mapping[str, Any], preflight: Mapping[str, Any]):
    paths = _r7_chain_paths()
    resume_mode = isinstance(preflight.get("resume"), Mapping)
    expected_final_binding = paths["resume_final_binding"] if resume_mode else paths["final_binding"]
    run_dir = paths["resume_run"] if resume_mode else paths["run"]
    final = audit.get("final_action_binding")
    if not isinstance(final, Mapping) or final.get("path") != str(expected_final_binding.resolve()):
        raise SyntheticChainError("CHAIN_FINAL_BINDING_PATH_MISMATCH")
    official = _make_official_adapter(
        run_dir, run_dir / "PIPELINE_TERMINAL_RECEIPT.json",
        contract_path=paths["resume_contract"] if resume_mode else paths["contract"],
        input_binding_path=expected_final_binding,
        scope_lock_path=paths["scope_lock"],
        event_profile={**EVENT_PROFILE,
                       "start_stage": "BREADTH1_REAL_ACTION_STARTED",
                       "terminal_stage": "BREADTH1_REAL_ACTION_TERMINAL",
                       "signal_scope": "FROZEN_INPUT_AS_OBSERVED_RESEARCH",
                       "target_scope": "ORIGINAL_F5_NEW_DAILY_TOP3",
                       "evidence_level": "RESEARCH_ONLY_PENDING_EVALUATION"},
    )
    return BREADTH1OfficialActionAdapter(
        official, contract_sha256=preflight["contract_sha256"],
        input_binding_sha256=final["sha256"], synthetic=False,
    )


def _write_chain_action_release(
    action_budget: BREADTH1OfficialActionAdapter,
    audit: Mapping[str, Any], preflight: Mapping[str, Any],
    *, sealed: Mapping[str, Any] | None = None,
) -> VerifiedActionRelease:
    """Materialize the existing grant's conditional continuation, no new grant.

    No PASS is manufactured: the official adapter verifies the immutable audit
    receipt and completed admission lifecycle before this file is written.
    The truth release is created only from the actual sealed saved artifacts.
    """
    contract, binding, admission = action_budget._read_contract_binding_snapshot()
    grant, grant_sha = _read_chain_control(PANEL_HEADER_RECOVERY_GRANT_PATH, preflight["grant_sha256"])
    resume = preflight.get("resume") if isinstance(preflight.get("resume"), Mapping) else None
    original_r7_identity = resume.get("original_r7_identity") if resume is not None else None
    expected_grant_contract_sha = (
        original_r7_identity.get("contract_sha256") if isinstance(original_r7_identity, Mapping)
        else action_budget.contract_sha256
    )
    expected_grant_binding_sha = (
        original_r7_identity.get("input_binding_sha256") if isinstance(original_r7_identity, Mapping)
        else binding.get("pre_admission_binding_sha256")
    )
    if (grant != preflight["grant"] or grant.get("grant_id") != PANEL_HEADER_RECOVERY_GRANT_ID
            or grant.get("execution_id") != PANEL_HEADER_RECOVERY_EXECUTION_ID
            or grant.get("contract_sha256") != expected_grant_contract_sha
            or grant.get("input_binding_sha256") != expected_grant_binding_sha
            or type(grant.get("action_cap")) is not int or grant.get("action_cap") != 1
            or grant.get("failure_or_interruption_refund") is not False
            or "if PASS, continue the existing single-fit, single-full-predict, immutable-seal, and single sealed-evaluation authorization"
            not in str(grant.get("authorized_scope", ""))
            or admission is None or audit.get("receipt_sha256") != admission[1]):
        raise SyntheticChainError("CHAIN_CONTINUATION_NOT_BOUND_TO_VERIFIED_R7_GRANT")
    registry_receipt, registry_sha = _read_chain_control(
        Path(str(audit["registry_receipt_path"])), str(audit["registry_receipt_sha256"]))
    if (registry_receipt.get("execution_id") != PANEL_HEADER_RECOVERY_EXECUTION_ID
            or registry_receipt.get("input_admission_status") != "PASS"
            or registry_receipt.get("input_admission_receipt_sha256") != admission[1]
            or registry_receipt.get("final_action_binding") != audit.get("final_action_binding")):
        raise SyntheticChainError("CHAIN_ADMISSION_REGISTRY_RECEIPT_MISMATCH")
    value = {
        "schema": "F5_BREADTH1_ACTION_BUDGET_RELEASE_V1", "status": "APPROVED",
        "route_id": ROUTE_ID, "candidate_id": CANDIDATE_ID, "synthetic_only": False,
        "contract_sha256": action_budget.contract_sha256,
        "input_binding_sha256": action_budget.input_binding_sha256,
        "input_admission_receipt_sha256": admission[1], "real_release_issued": True,
        "authorization_basis": {
            "kind": "EXISTING_R7_CONDITIONAL_CONTINUATION_NOT_NEW_AUTHORIZATION",
            "grant_path": str(PANEL_HEADER_RECOVERY_GRANT_PATH.resolve()), "grant_sha256": grant_sha,
            "grant_id": grant["grant_id"], "admission_execution_id": grant["execution_id"],
            "user_authorization_source_item_id": grant["user_authorization_source_item_id"],
            "user_authorization_timestamp_utc": grant["user_authorization_timestamp_utc"],
            "user_authorization_text": grant["user_authorization_text"],
        },
        "research_only": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
    }
    if resume is not None:
        value["r7_resume_addendum"] = {
            "path": str(PANEL_HEADER_RECOVERY_RESUME_AUTH_PATH.resolve()),
            "sha256": resume.get("authorization_sha256"),
            "original_r7_action_key": PANEL_HEADER_RECOVERY_ACTION_KEY,
            "original_r7_execution_id": PANEL_HEADER_RECOVERY_EXECUTION_ID,
            "logical_r7_debit_total": 1,
            "additional_r7_debit": 0,
            "physical_invocation_index": 3,
            "resume_contract_sha256": action_budget.contract_sha256,
            "resume_input_binding_sha256": action_budget.input_binding_sha256,
        }
    run_dir = _r7_chain_paths()["resume_run"] if resume is not None else _r7_chain_paths()["run"]
    if sealed is None:
        value.update(action_scope="FIT_PREDICT", sealed_status="PREDICTIONS_NOT_YET_SEALED",
                     actions={name: {"max_calls": 1, "official_registry_receipt_sha256": registry_sha}
                              for name in ("fit", "predict")})
        release_path = run_dir / "FIT_PREDICT_RELEASE.json"
    else:
        handoff_path = Path(str(sealed["terminal_path"]))
        handoff, handoff_sha = _read_chain_control(handoff_path, str(sealed["terminal_sha256"]))
        if handoff.get("status") != "AWAITING_TRUTH_RELEASE":
            raise SyntheticChainError("CHAIN_TRUTH_RELEASE_REQUIRES_SEALED_HANDOFF")
        seal_path = Path(str(handoff["prediction_seal_path"]))
        seal, seal_sha = _read_chain_control(seal_path, handoff["prediction_seal_sha256"])
        prior = _verified_real_action_terminals(action_budget, ("fit", "predict"))
        if (seal.get("prior_action_terminals") != prior
                or handoff.get("prior_action_terminals") != prior
                or seal.get("contract_sha256") != action_budget.contract_sha256
                or seal.get("input_binding_sha256") != action_budget.input_binding_sha256):
            raise SyntheticChainError("CHAIN_SEAL_PRIOR_ACTION_IDENTITY_MISMATCH")
        durable = {"schema": "F5_BREADTH1_PIPELINE_ACTION_RECEIPT_V1",
                   "route_id": ROUTE_ID, "candidate_id": CANDIDATE_ID,
                   "contract_sha256": action_budget.contract_sha256,
                   "input_binding_sha256": action_budget.input_binding_sha256,
                   "prior_action_terminals": prior, "admission_registry_receipt_sha256": registry_sha}
        prior_sha = write_json_exclusive(durable, run_dir / "FIT_PREDICT_REGISTRY_RECEIPT.json")
        value.update(
            action_scope="SEALED_TRUTH_EVALUATION",
            sealed_status="PREDICTIONS_SEALED_AWAITING_TRUTH_RELEASE",
            actions={"truth_decode": {"max_calls": 1, "official_registry_receipt_sha256": prior_sha}},
            prediction_seal={"path": str(seal_path.resolve()), "sha256": seal_sha},
            awaiting_truth_terminal={"path": str(handoff_path.resolve()), "sha256": handoff_sha},
            candidate_artifacts=seal["candidate_artifacts"], prior_action_terminals=prior,
        )
        release_path = run_dir / "SEALED_TRUTH_RELEASE.json"
    digest = write_json_exclusive(value, release_path)
    release = VerifiedActionRelease(release_path, digest)
    action_budget.verify_real_action_context(release)
    return release


def _chain_action_observation(official: Any) -> dict[str, Any]:
    """Observed durable debits; an unmatched start never means zero calls."""
    from f5_breadth1_budget import _is_sha

    names = ("admission", "fit", "predict", "truth_decode")
    if official is None:
        return {"integrity": "CANNOT_CONFIRM", "debits": {name: None for name in names},
                "calls": {name: None for name in names}}
    try:
        events = official.list_events(EXPERIMENT_ID)
        debits, calls = {}, {}
        for name in names:
            key = (PANEL_HEADER_RECOVERY_ACTION_KEY if name == "admission"
                   else f"{ROUTE_ID}:{CANDIDATE_ID}:{name}")
            execution_id = (PANEL_HEADER_RECOVERY_EXECUTION_ID if name == "admission"
                            else f"{ROUTE_ID}_{CANDIDATE_ID}_{name.upper()}_ONE_SHOT")
            relevant = [e for e in events if e.get("budget_action_key") == key]
            starts = [e for e in relevant if e.get("event_type") == "RUN_STARTED"]
            terminals = [e for e in relevant if e.get("event_type") == "TERMINAL"]
            debits[name] = len(starts)
            if not starts and not terminals:
                calls[name] = 0
            elif (len(starts) == len(terminals) == 1
                  and starts[0].get("execution_id") == terminals[0].get("execution_id") == execution_id
                  and _is_sha(starts[0].get("event_sha256"))
                  and _is_sha(terminals[0].get("event_sha256"))
                  and terminals[0].get("started_event_sha256") == starts[0].get("event_sha256")):
                terminal = terminals[0]
                entered = (terminal.get("fit_call_entered") if name == "fit"
                           else terminal.get("deterministic_metrics", {}).get("action_callback_entered"))
                calls[name] = int(entered) if type(entered) is bool else None
            else:
                calls[name] = None
        return {"integrity": "COMPLETE" if all(v is not None for v in calls.values()) else "CANNOT_CONFIRM",
                "debits": debits, "calls": calls}
    except Exception as exc:
        return {"integrity": "CANNOT_CONFIRM", "error_type": type(exc).__name__,
                "debits": {name: None for name in names}, "calls": {name: None for name in names}}


def run_registered_real_chain(
    *, resume_authorization_path: Path | None = None,
    resume_authorization_sha256: str | None = None,
) -> dict[str, Any]:
    """The sole R7 real entry: check -> admission cache -> fit/predict -> seal -> eval.

    Run only on the authorized locked local interpreter. The optional resume
    path preserves the consumed R7 claim and requires a separate immutable
    engineering authorization. Arrays and the live model stay in this process.
    """
    paths = _r7_chain_paths()
    resume_mode = resume_authorization_path is not None or resume_authorization_sha256 is not None
    accepted_evaluation_statuses = {"DIRECTION_ONLY", "NO_BREAKTHROUGH"}
    if resume_mode:
        accepted_evaluation_statuses.add("EFFECT_CANNOT_CONFIRM")
    if resume_mode and (resume_authorization_path is None or resume_authorization_sha256 is None):
        raise SyntheticChainError("R7_RESUME_REQUIRES_FIXED_AUTHORIZATION_PATH_AND_SHA")
    run_dir = paths["resume_run"] if resume_mode else paths["run"]
    if run_dir.exists() or run_dir.is_symlink():
        raise SyntheticChainError("R7_PIPELINE_OUTPUT_ALREADY_EXISTS_NO_OVERWRITE")
    current = run_dir
    while current != BATCH_ROOT.parent:
        if current.is_symlink():
            raise SyntheticChainError("R7_PIPELINE_OUTPUT_SYMLINK_NOT_ALLOWED")
        current = current.parent
    terminal_path = run_dir / "PIPELINE_TERMINAL_RECEIPT.json"
    checkpoints: list[dict[str, Any]] = []
    stage = "control_and_runtime_preflight"
    official = None
    audit = None
    admission_invoked = False
    pipeline_invoked = False
    evaluation = None
    error = None
    try:
        preflight = (
            _preflight_registered_r7_resume(resume_authorization_path, resume_authorization_sha256)
            if resume_mode else _preflight_registered_real_chain()
        )
        official = preflight["official"]
        # Preflight verifies that the fixed resume output is still absent. Only
        # after that check may this physical invocation create it.
        run_dir.mkdir(parents=True, exist_ok=False)
        stage = "input_admission"
        admission_invoked = True
        if resume_mode:
            resume_auth = preflight["resume"]
            checkpoint_value = {
                "schema": "BREADTH1_R7_RESUME_CHECKPOINT_V1",
                "status": "PRETARGET_RESUME_AUTHENTICATED",
                "authorization_sha256": preflight["authorization_sha256"],
                "r7_start_event_sha256": preflight["resume_start_event"]["event_sha256"],
                "r7_failed_terminal_event_sha256": preflight["resume_failure_terminal_event"]["event_sha256"],
                "original_pipeline_terminal_sha256": sha256_file(
                    PANEL_HEADER_RECOVERY_OUTPUT_PATH / "PIPELINE_TERMINAL_RECEIPT.json"
                ),
                "resume_contract_sha256": preflight["contract_sha256"],
                "resume_input_binding_sha256": preflight["pending_binding_sha256"],
                "resume_read_release_sha256": preflight["resume_release"].expected_sha256,
                "physical_invocation_index": 3,
                "logical_r7_action_debit_total": 1,
                "additional_r7_action_debit": 0,
                "target_input_reads": 0,
                "fit_calls": 0,
                "predict_calls": 0,
                "model_load_calls": 0,
                "truth_decode_calls": 0,
                "research_only": True,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            checkpoint_path = run_dir / "RESUME_CHECKPOINT_PRETARGET.json"
            checkpoint_sha = write_json_exclusive(checkpoint_value, checkpoint_path)
            checkpoints.append({
                "stage": "PRETARGET_RESUME_AUTHENTICATED",
                "path": str(checkpoint_path.resolve()),
                "sha256": checkpoint_sha,
            })
            preflight.update({
                "status": "AUTHORIZED_PRETARGET_R7_RESUMPTION",
                "authorization_path": str(paths["resume_authorization"].resolve()),
                "checkpoint_path": str(checkpoint_path.resolve()),
                "checkpoint_sha256": checkpoint_sha,
                "resume_control_identity": resume_auth["resume_control_identity"],
                "original_r7_identity": resume_auth["original_r7_identity"],
                "preserved_original_failure": resume_auth["preserved_original_failure"],
            })
        audit = run_registered_input_admission_audit(resume_context=preflight if resume_mode else None)
        if resume_mode:
            checkpoints.append(_write_r7_resume_stage_checkpoint(
                run_dir,
                stage="INPUT_ADMISSION",
                status=str(audit.get("status", "CANNOT_CONFIRM")),
                previous=checkpoints[-1],
                evidence_paths=[
                    audit.get("receipt_path"), audit.get("registry_receipt_path"),
                    (audit.get("final_action_binding") or {}).get("path"),
                ],
                facts={
                    "target_input_file_count": audit.get("actual_read", {}).get("file_count"),
                    "target_input_total_bytes": audit.get("actual_read", {}).get("total_bytes"),
                    "read_ledger_status": audit.get("actual_read", {}).get("status"),
                    "real_fit_calls": 0, "real_predict_calls": 0,
                    "real_model_load_calls": 0, "real_truth_decode_calls": 0,
                },
            ))
        if audit.get("status") != "PASS":
            raise SyntheticChainError("R7_INPUT_ADMISSION_NOT_PASS_NO_FIT")
        stage = "verified_cache_transition"
        budget = _make_chain_action_budget(audit, preflight)
        official = budget.official
        fit_release = _write_chain_action_release(budget, audit, preflight)
        context = budget.verify_real_action_context(fit_release)
        prepared = _rebind_cached_prepared_inputs(audit.pop("_prepared_inputs", None), context)
        stage = "fit_predict_seal"
        pipeline_invoked = True
        candidate_dir = run_dir / "candidate"
        sealed = run_real_candidate_pipeline(
            action_budget=budget, fit_predict_release=fit_release, prepared_inputs=prepared,
            execution_dir=candidate_dir, model_path=candidate_dir / "model.txt",
            scoreable_prediction_path=candidate_dir / "scoreable_predictions.npy",
            candidate_scores_path=candidate_dir / "candidate_scores.csv.gz",
            candidate_top3_path=candidate_dir / "candidate_top3.csv.gz",
        )
        if resume_mode:
            checkpoints.append(_write_r7_resume_stage_checkpoint(
                run_dir,
                stage="PREDICTIONS_SEALED",
                status=str(sealed.get("status", "CANNOT_CONFIRM")),
                previous=checkpoints[-1],
                evidence_paths=[sealed.get("terminal_path"), sealed.get("prediction_seal_path")],
                facts={
                    "real_fit_calls": sealed.get("real_fit_calls"),
                    "real_predict_calls": sealed.get("real_predict_calls"),
                    "real_model_load_calls": sealed.get("real_model_load_calls", 0),
                    "real_truth_decode_calls": 0,
                    "prior_action_terminals": sealed.get("prior_action_terminals"),
                },
            ))
        stage = "seal_bound_truth_release"
        truth_release = _write_chain_action_release(budget, audit, preflight, sealed=sealed)
        stage = "sealed_evaluation"
        evaluation = resume_sealed_evaluation(
            action_budget=budget, truth_release=truth_release, execution_dir=candidate_dir)
        if resume_mode:
            checkpoints.append(_write_r7_resume_stage_checkpoint(
                run_dir,
                stage="SEALED_EVALUATION",
                status=str(evaluation.get("status", "CANNOT_CONFIRM")),
                previous=checkpoints[-1],
                evidence_paths=[evaluation.get("terminal_path"), evaluation.get("evaluation_report_path")],
                facts={
                    "real_fit_calls": 1, "real_predict_calls": 1,
                    "real_model_load_calls": 0,
                    "real_truth_decode_calls": evaluation.get("real_truth_decode_calls"),
                    "current_gates_only": evaluation.get("current_gates_only"),
                },
            ))
        evaluation_terminal = Path(str(evaluation.get("terminal_path", "")))
        if (
            evaluation.get("status") not in accepted_evaluation_statuses
            or not evaluation_terminal.is_absolute()
            or not evaluation_terminal.is_file()
            or evaluation_terminal.is_symlink()
            or sha256_file(evaluation_terminal) != evaluation.get("terminal_sha256")
            or evaluation.get("real_truth_decode_calls") != 1
        ):
            raise SyntheticChainError("R7_EVALUATION_TERMINAL_NOT_DURABLE_OR_ACTION_COUNT_MISMATCH")
        stage = "completed"
    except BaseException as exc:
        preserved_audit = getattr(exc, "r7_admission_audit_snapshot", None)
        if isinstance(preserved_audit, Mapping):
            audit = dict(preserved_audit)
        error = _chain_error_details(exc)

    if resume_mode and not run_dir.exists():
        run_dir.mkdir(parents=True, exist_ok=False)

    observation = _chain_action_observation(official)
    calls = dict(observation["calls"])
    # Before invoking the worker there cannot have been a new model/truth
    # callback in this invocation, even when the registry is unavailable.
    if not pipeline_invoked:
        calls.update(fit=0, predict=0, truth_decode=0)
    if not admission_invoked:
        calls["admission"] = 0
    complete = bool(
        error is None and isinstance(evaluation, Mapping)
        and evaluation.get("status") in accepted_evaluation_statuses
        and isinstance(evaluation.get("terminal_path"), str)
        and isinstance(evaluation.get("terminal_sha256"), str)
        and evaluation.get("real_truth_decode_calls") == 1
        and observation["integrity"] == "COMPLETE"
        and all(observation["debits"].get(name) == 1 for name in ("admission", "fit", "predict", "truth_decode"))
        and all(calls.get(name) == 1 for name in ("fit", "predict", "truth_decode"))
    )
    if error is None and not complete:
        error = {"error_type": "SyntheticChainError",
                 "error": "CHAIN_ACTION_ACCOUNTING_NOT_CONFIRMED_COMPLETE"}
    status = (evaluation["status"] if complete else
              "NO_FIT" if calls.get("fit") == 0 and not pipeline_invoked else "EFFECT_CANNOT_CONFIRM")
    if resume_mode:
        evidence_candidates = [
            audit.get("receipt_path") if isinstance(audit, Mapping) else None,
            audit.get("registry_receipt_path") if isinstance(audit, Mapping) else None,
            (audit.get("final_action_binding") or {}).get("path") if isinstance(audit, Mapping) else None,
            run_dir / "candidate" / "TERMINAL_RECEIPT.json",
            run_dir / "candidate" / "PREDICTION_SEAL.json",
            run_dir / "candidate" / "TRUTH_EVALUATION_TERMINAL_RECEIPT.json",
        ]
        checkpoints.append(_write_r7_resume_stage_checkpoint(
            run_dir,
            stage="ATTEMPT_TERMINAL",
            status=status,
            previous=checkpoints[-1] if checkpoints else None,
            evidence_paths=evidence_candidates,
            facts={
                "pipeline_stage": stage,
                "action_debits": observation["debits"],
                "action_calls": calls,
                "action_integrity": observation["integrity"],
                "error": error,
                "physical_invocation_index": 3,
                "logical_r7_action_debit_total": 1,
                "additional_r7_action_debit": 0,
            },
        ))
    terminal = {
        "schema": "F5_BREADTH1_R7_ONE_PROCESS_TERMINAL_V1", "status": status, "decision": status,
        "stage": stage, "execution_id": PANEL_HEADER_RECOVERY_EXECUTION_ID,
        "route_id": ROUTE_ID, "candidate_id": CANDIDATE_ID,
        "admission_status": audit.get("status") if isinstance(audit, Mapping) else "CANNOT_CONFIRM" if admission_invoked else "NOT_ENTERED",
        "input_read_observation": audit.get("actual_read") if isinstance(audit, Mapping) else None,
        "input_admission_receipt_path": audit.get("receipt_path") if isinstance(audit, Mapping) else None,
        "input_admission_receipt_sha256": audit.get("receipt_sha256") if isinstance(audit, Mapping) else None,
        "admission_registry_receipt_path": audit.get("registry_receipt_path") if isinstance(audit, Mapping) else None,
        "admission_registry_receipt_sha256": audit.get("registry_receipt_sha256") if isinstance(audit, Mapping) else None,
        "evaluation_terminal_path": evaluation.get("terminal_path") if isinstance(evaluation, Mapping) else None,
        "evaluation_terminal_sha256": evaluation.get("terminal_sha256") if isinstance(evaluation, Mapping) else None,
        "action_observation": observation, "action_debits": observation["debits"],
        "real_fit_calls": calls["fit"], "real_predict_calls": calls["predict"],
        "real_truth_decode_calls": calls["truth_decode"], "real_model_load_calls": 0,
        "effect_status": (
            "CANNOT_CONFIRM" if status == "EFFECT_CANNOT_CONFIRM" else
            "TESTED" if complete else
            "NOT_TESTED" if status == "NO_FIT" else "CANNOT_CONFIRM"
        ),
        "retry_allowed": False, "refund_allowed": False, "same_process": True,
        "physical_invocation_index": 3 if resume_mode else 1,
        "prior_failure_terminal_sha256": (
            sha256_file(paths["run"] / "PIPELINE_TERMINAL_RECEIPT.json") if resume_mode else None
        ),
        "resume_checkpoint_chain": checkpoints,
        "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        **(error or {}),
    }
    digest = write_json_exclusive(terminal, terminal_path)
    return {key: terminal[key] for key in (
        "status", "decision", "stage", "real_fit_calls", "real_predict_calls",
        "real_truth_decode_calls", "real_model_load_calls", "effect_status")
    } | {
        "terminal_path": str(terminal_path.resolve()),
        "terminal_sha256": digest,
        "resume_checkpoint_chain": checkpoints,
    }


def _write_r7_resume_stage_checkpoint(
    run_dir: Path,
    *,
    stage: str,
    status: str,
    previous: Mapping[str, Any] | None,
    evidence_paths: list[Any],
    facts: Mapping[str, Any],
) -> dict[str, Any]:
    """Write one immutable SHA-linked stage receipt under the fixed resume dir."""
    from datetime import datetime, timezone

    safe_stage = "".join(ch for ch in stage.upper() if ch.isalnum() or ch == "_")
    if not safe_stage or Path(run_dir).resolve() != PANEL_HEADER_RECOVERY_RESUME_RUN_PATH.resolve():
        raise SyntheticChainError("R7_RESUME_CHECKPOINT_FIXED_STAGE_PATH_INVALID")
    path = Path(run_dir) / f"RESUME_CHECKPOINT_{safe_stage}.json"
    evidence: list[dict[str, Any]] = []
    for value in evidence_paths:
        if not isinstance(value, (str, Path)):
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = candidate.resolve()
        try:
            candidate.resolve().relative_to(BATCH_ROOT.resolve())
        except ValueError as exc:
            raise SyntheticChainError("R7_RESUME_CHECKPOINT_EVIDENCE_OUTSIDE_BATCH") from exc
        if candidate.is_symlink() or not candidate.is_file():
            continue
        evidence.append({
            "path": str(candidate.resolve()),
            "sha256": sha256_file(candidate),
            "bytes": candidate.stat().st_size,
        })
    value = {
        "schema": "BREADTH1_R7_RESUME_STAGE_CHECKPOINT_V1",
        "stage": stage,
        "status": status,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "authorization_path": str(PANEL_HEADER_RECOVERY_RESUME_AUTH_PATH.resolve()),
        "authorization_sha256": sha256_file(PANEL_HEADER_RECOVERY_RESUME_AUTH_PATH),
        "physical_invocation_index": 3,
        "logical_r7_action_debit_total": 1,
        "additional_r7_action_debit": 0,
        "previous_checkpoint": dict(previous) if isinstance(previous, Mapping) else None,
        "evidence": evidence,
        "facts": dict(facts),
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    digest = write_json_exclusive(value, path)
    return {"stage": stage, "path": str(path.resolve()), "sha256": digest}


def run_real_candidate_pipeline(
    *,
    action_budget: BREADTH1OfficialActionAdapter,
    fit_predict_release: VerifiedActionRelease,
    prepared_inputs: PreparedRealInputs,
    execution_dir: Path,
    model_path: Path,
    scoreable_prediction_path: Path,
    candidate_scores_path: Path,
    candidate_top3_path: Path,
) -> dict[str, Any]:
    """Consume the cached input snapshot, fit/predict, then seal outputs.

    The function has no injectable model, callback, metrics implementation, or
    binding. The enclosing one-process chain creates the separate exact-seal
    truth release after this function writes its immutable handoff and seal,
    then calls ``resume_sealed_evaluation`` without exiting or reloading.
    """

    if action_budget is None or action_budget.synthetic:
        raise SyntheticChainError("REAL_PIPELINE_REQUIRES_OFFICIAL_REAL_ACTION_ADAPTER")
    execution_dir = Path(execution_dir).resolve()
    try:
        execution_dir.relative_to(BATCH_ROOT.resolve())
    except ValueError as exc:
        raise SyntheticChainError("REAL_EXECUTION_OUTPUT_MUST_STAY_INSIDE_NEW_BATCH") from exc
    if execution_dir.exists():
        raise SyntheticChainError("REAL_EXECUTION_OUTPUT_ALREADY_EXISTS_NO_OVERWRITE")
    execution_dir.mkdir(parents=True, exist_ok=False)
    terminal_path = execution_dir / "TERMINAL_RECEIPT.json"
    stage = "verified_input_context"
    context = None
    prepare_receipt_sha = None
    fit_predict_result = None
    try:
        for path_value in (model_path, scoreable_prediction_path, candidate_scores_path, candidate_top3_path):
            path = Path(path_value).resolve()
            try:
                path.relative_to(execution_dir)
            except ValueError as exc:
                raise SyntheticChainError("REAL_CANDIDATE_OUTPUTS_MUST_STAY_INSIDE_EXECUTION_DIR") from exc
            if path.exists():
                raise SyntheticChainError("REAL_CANDIDATE_OUTPUT_ALREADY_EXISTS_NO_OVERWRITE")
        context = action_budget.verify_real_action_context(fit_predict_release)
        stage = "prepare"
        if not isinstance(prepared_inputs, PreparedRealInputs):
            raise SyntheticChainError("REAL_PIPELINE_REQUIRES_SAME_TRANSACTION_ADMISSION_SNAPSHOT")
        prepared = prepared_inputs
        if (
            prepared.receipt.get("input_binding_sha256") != context.input_binding_sha256
            or prepared.receipt.get("input_admission_receipt_sha256") != context.input_admission_receipt_sha256
            or prepared.receipt.get("status") != "PREPARED_AWAITING_WORKER"
        ):
            raise SyntheticChainError("REAL_PIPELINE_ADMISSION_SNAPSHOT_BINDING_MISMATCH")
        prep_path = execution_dir / "PREPARE_RECEIPT.json"
        prep_value = {**dict(prepared.receipt), "execution_dir": str(execution_dir)}
        prepare_receipt_sha = write_json_exclusive(prep_value, prep_path)

        stage = "fit_predict"
        model, fit_predict_result = fit_and_predict_real_once(
            train_x=prepared.train_x,
            train_y=prepared.train_y,
            score_x=prepared.score_x,
            eval_row_keys=prepared.eval_row_keys,
            score_row_keys=prepared.score_row_keys,
            scoreable_mask=prepared.scoreable_mask,
            calendar=prepared.calendar,
            release=fit_predict_release,
            action_budget=action_budget,
            model_path=model_path,
            scoreable_prediction_path=scoreable_prediction_path,
            candidate_scores_path=candidate_scores_path,
            candidate_top3_path=candidate_top3_path,
        )
        action_terminals = _verified_real_action_terminals(action_budget, ("fit", "predict"))
        predicted_artifacts = fit_predict_result.get("artifact_receipts")
        if not isinstance(predicted_artifacts, Mapping) or set(predicted_artifacts) != {
            "scoreable_prediction", "candidate_scores", "candidate_top3",
        }:
            raise SyntheticChainError("REAL_PREDICTION_ARTIFACT_SET_INCOMPLETE")
        for name, artifact in predicted_artifacts.items():
            artifact_path = Path(str(artifact.get("path", ""))).resolve()
            try:
                artifact_path.relative_to(execution_dir)
            except ValueError as exc:
                raise SyntheticChainError(f"REAL_PREDICTION_ARTIFACT_OUTSIDE_EXECUTION_DIR:{name}") from exc
            if not artifact_path.is_file() or sha256_file(artifact_path) != artifact.get("sha256"):
                raise SyntheticChainError(f"REAL_PREDICTION_ARTIFACT_SHA_MISMATCH:{name}")
        fit_resource_trace_path = Path(model_path).with_name("FIT_RESOURCE_TRACE.json").resolve()
        fit_resource_observation = fit_predict_result.get("fit_resource_trace")
        if not fit_resource_trace_path.is_file() or not isinstance(fit_resource_observation, Mapping):
            raise SyntheticChainError("REAL_FIT_RESOURCE_TRACE_MISSING")
        resource_trace_identity = {
            "path": str(fit_resource_trace_path),
            "sha256": sha256_file(fit_resource_trace_path),
            "worker_count": fit_resource_observation.get("worker_count"),
            "actual_thread_count": fit_resource_observation.get("actual_thread_count"),
            "peak_worker_tree_rss_bytes": fit_resource_observation.get("peak_worker_tree_rss_bytes"),
            "rss_observation_complete": fit_resource_observation.get("rss_observation_complete"),
            "wall_observation_seconds": max(
                (float(sample.get("elapsed_seconds", 0.0)) for sample in fit_resource_observation.get("samples", [])),
                default=0.0,
            ),
        }
        seal = {
            "schema": "F5_BREADTH1_REAL_PREDICTION_SEAL_V1",
            "status": "PREDICTIONS_SEALED_AWAITING_TRUTH_RELEASE",
            "execution_dir": str(execution_dir),
            "contract_sha256": context.contract_sha256,
            "input_binding_sha256": context.input_binding_sha256,
            "fit_predict_release_sha256": context.release_sha256,
            "input_admission_receipt_sha256": context.input_admission_receipt_sha256,
            "prepare_receipt_sha256": prepare_receipt_sha,
            "model_sha256": sha256_file(Path(fit_predict_result["model_path"])),
            "candidate_artifacts": fit_predict_result["artifact_receipts"],
            "prior_action_terminals": action_terminals,
            "training_rows": int(len(prepared.train_x)),
            "evaluation_G_rows": int(len(prepared.eval_row_keys)),
            "evaluation_S_rows": int(len(prepared.score_x)),
            "fit_resource_observation": resource_trace_identity,
            "fit_thread_count": fit_predict_result.get("fit_thread_count"),
            "predict_thread_count": fit_predict_result.get("thread_count"),
            "real_input_accessed": True,
            "real_fit_calls": 1,
            "real_predict_calls": 1,
            "real_truth_decode_calls": 0,
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        seal_path = execution_dir / "PREDICTION_SEAL.json"
        seal_sha = write_json_exclusive(seal, seal_path)
        terminal = {
            "schema": "F5_BREADTH1_REAL_TERMINAL_RECEIPT_V1",
            "status": "AWAITING_TRUTH_RELEASE",
            "decision": "AWAITING_TRUTH_RELEASE",
            "stage": "prediction_sealed",
            "prepare_receipt_sha256": prepare_receipt_sha,
            "prediction_seal_path": str(seal_path.resolve()),
            "prediction_seal_sha256": seal_sha,
            "prior_action_terminals": action_terminals,
            "effect_status": "NOT_TESTED",
            "real_input_accessed": True,
            "real_fit_calls": 1,
            "real_predict_calls": 1,
            "real_truth_decode_calls": 0,
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        terminal_sha = write_json_exclusive(terminal, terminal_path)
        return {"terminal_path": str(terminal_path), "terminal_sha256": terminal_sha, **terminal}
    except BaseException as exc:
        registry_events = None
        try:
            registry_events = [
                event for event in action_budget.official.list_events(EXPERIMENT_ID)
                if event.get("route_id") == ROUTE_ID
                and event.get("candidate_id") == CANDIDATE_ID
            ]
        except Exception:
            registry_events = None
        actions = ("fit", "predict")
        action_debits = (
            {
                action: sum(
                    int(event.get("budget_action") == action and event.get("event_type") == "RUN_STARTED")
                    for event in registry_events
                )
                for action in actions
            }
            if registry_events is not None else None
        )
        action_terminals = (
            {
                action: [
                    event for event in registry_events
                    if event.get("budget_action") == action and event.get("event_type") == "TERMINAL"
                ]
                for action in actions
            }
            if registry_events is not None else {}
        )
        fit_terminal = action_terminals.get("fit", [])
        predict_terminal = action_terminals.get("predict", [])
        fit_call_entered = int(len(fit_terminal) == 1 and fit_terminal[0].get("fit_call_entered") is True)
        predict_callback_entered = int(
            len(predict_terminal) == 1
            and predict_terminal[0].get("deterministic_metrics", {}).get("action_callback_entered") is True
        )
        missing_terminal = bool(
            action_debits is None
            or any(action_debits[action] and len(action_terminals[action]) != 1 for action in actions)
        )
        possible_fit = bool(action_debits is None or action_debits["fit"])
        effect_unresolved = bool(fit_call_entered or (possible_fit and missing_terminal))
        terminal = {
            "schema": "F5_BREADTH1_REAL_TERMINAL_RECEIPT_V1",
            "status": "EFFECT_CANNOT_CONFIRM" if effect_unresolved else "NO_FIT",
            "decision": "EFFECT_CANNOT_CONFIRM" if effect_unresolved else "NO_FIT_EFFECT_NOT_TESTED",
            "stage": stage,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "prepare_receipt_sha256": prepare_receipt_sha,
            "prediction_sealed": fit_predict_result is not None,
            "real_input_accessed": bool(context is not None),
            "action_debits": action_debits,
            "real_fit_calls": fit_call_entered,
            "real_predict_calls": predict_callback_entered,
            "real_truth_decode_calls": 0,
            "effect_status": "CANNOT_CONFIRM" if effect_unresolved else "NOT_TESTED",
            "terminal_integrity": "CANNOT_CONFIRM" if missing_terminal else "ACTION_TERMINALS_COMPLETE",
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if not terminal_path.exists():
            try:
                write_json_exclusive(terminal, terminal_path)
            except FileExistsError:
                pass
        raise


def _verified_real_action_terminals(
    action_budget: BREADTH1OfficialActionAdapter,
    actions: tuple[str, ...],
) -> dict[str, str]:
    events = action_budget.official.list_events(EXPERIMENT_ID)
    result: dict[str, str] = {}
    for action in actions:
        key = f"{ROUTE_ID}:{CANDIDATE_ID}:{action}"
        starts = [event for event in events if event.get("budget_action_key") == key and event.get("event_type") == "RUN_STARTED"]
        terminals = [event for event in events if event.get("budget_action_key") == key and event.get("event_type") == "TERMINAL"]
        if len(starts) != 1 or len(terminals) != 1:
            raise SyntheticChainError(f"REAL_ACTION_TERMINAL_NOT_UNIQUE:{action}")
        terminal = terminals[0]
        if (
            terminal.get("execution_id") != starts[0].get("execution_id")
            or (
                terminal.get("started_event_sha256") is not None
                and terminal.get("started_event_sha256") != starts[0].get("event_sha256")
            )
            or terminal.get("decision") != "ACTION_COMPLETED_RESEARCH_ONLY"
            or terminal.get("truth_access") != "NOT_READ"
        ):
            raise SyntheticChainError(f"REAL_ACTION_TERMINAL_NOT_SUCCESSFUL:{action}")
        digest = terminal.get("event_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise SyntheticChainError(f"REAL_ACTION_TERMINAL_SHA_MISSING:{action}")
        result[action] = digest
    return result


def resume_sealed_evaluation(
    *,
    action_budget: BREADTH1OfficialActionAdapter,
    truth_release: VerifiedActionRelease,
    execution_dir: Path,
) -> dict[str, Any]:
    """Evaluate the uniquely released immutable seal in the current chain.

    This stage does not prepare, fit, predict, or load the model. The truth
    approval must identify the exact sealed terminal, seal, candidate artifacts,
    and prior fit/predict registry terminal hashes.
    """

    if action_budget is None or action_budget.synthetic:
        raise SyntheticChainError("SEALED_EVALUATION_REQUIRES_OFFICIAL_REAL_ACTION_ADAPTER")
    execution_dir = Path(execution_dir).resolve()
    try:
        execution_dir.relative_to(BATCH_ROOT.resolve())
    except ValueError as exc:
        raise SyntheticChainError("REAL_EXECUTION_OUTPUT_MUST_STAY_INSIDE_NEW_BATCH") from exc
    handoff_path = execution_dir / "TERMINAL_RECEIPT.json"
    seal_path = execution_dir / "PREDICTION_SEAL.json"
    evaluation_terminal_path = execution_dir / "TRUTH_EVALUATION_TERMINAL_RECEIPT.json"
    if evaluation_terminal_path.exists():
        raise SyntheticChainError("TRUTH_EVALUATION_TERMINAL_ALREADY_EXISTS_NO_OVERWRITE")
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff_sha = sha256_file(handoff_path)
    seal_sha = sha256_file(seal_path)
    if (
        handoff.get("status") != "AWAITING_TRUTH_RELEASE"
        or handoff.get("decision") != "AWAITING_TRUTH_RELEASE"
        or handoff.get("prediction_seal_path") != str(seal_path.resolve())
        or handoff.get("prediction_seal_sha256") != seal_sha
    ):
        raise SyntheticChainError("TRUTH_RESUME_REQUIRES_EXACT_AWAITING_TRUTH_HANDOFF")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if (
        seal.get("schema") != "F5_BREADTH1_REAL_PREDICTION_SEAL_V1"
        or seal.get("status") != "PREDICTIONS_SEALED_AWAITING_TRUTH_RELEASE"
        or seal.get("execution_dir") != str(execution_dir)
    ):
        raise SyntheticChainError("TRUTH_RESUME_SEAL_CONTENT_MISMATCH")
    candidate_artifacts = seal.get("candidate_artifacts")
    if not isinstance(candidate_artifacts, Mapping) or set(candidate_artifacts) != {
        "scoreable_prediction", "candidate_scores", "candidate_top3",
    }:
        raise SyntheticChainError("TRUTH_RESUME_SEALED_ARTIFACT_SET_MISMATCH")
    for name, record in candidate_artifacts.items():
        if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
            raise SyntheticChainError(f"TRUTH_RESUME_SEALED_ARTIFACT_INVALID:{name}")
        path = Path(record["path"]).resolve()
        try:
            path.relative_to(execution_dir)
        except ValueError as exc:
            raise SyntheticChainError(f"TRUTH_RESUME_ARTIFACT_OUTSIDE_EXECUTION_DIR:{name}") from exc
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            raise SyntheticChainError(f"TRUTH_RESUME_SEALED_ARTIFACT_SHA_MISMATCH:{name}")

    stage2_receipt_path = execution_dir / "TRUTH_EVALUATION_PREFLIGHT_REJECTED.json"
    stage = "verify_truth_release"
    try:
        action_context = action_budget.verify_real_action_context(truth_release)
        release_value = action_context.release_value
        if (
            release_value.get("action_scope") != "SEALED_TRUTH_EVALUATION"
            or release_value.get("prediction_seal") != {"path": str(seal_path.resolve()), "sha256": seal_sha}
            or release_value.get("awaiting_truth_terminal") != {"path": str(handoff_path.resolve()), "sha256": handoff_sha}
            or release_value.get("candidate_artifacts") != dict(candidate_artifacts)
            or release_value.get("prior_action_terminals") != seal.get("prior_action_terminals")
        ):
            raise SyntheticChainError("TRUTH_RELEASE_DOES_NOT_MATCH_IMMUTABLE_SEAL")
        bound_evaluation = action_context.input_binding_value.get("evaluation_artifacts")
        if not isinstance(bound_evaluation, Mapping):
            raise SyntheticChainError("REAL_EVALUATION_ARTIFACT_BINDING_MISSING")

        def bound(name: str) -> tuple[Path, str]:
            item = bound_evaluation.get(name)
            if not isinstance(item, Mapping) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
                raise SyntheticChainError(f"REAL_EVALUATION_ARTIFACT_BINDING_INVALID:{name}")
            return Path(item["path"]), item["sha256"]

        plus_scores, plus_scores_sha = bound("PLUS_PATH_scores")
        plus_top3, plus_top3_sha = bound("PLUS_PATH_top3")
        base_scores, base_scores_sha = bound("BASE34_scores")
        base_top3, base_top3_sha = bound("BASE34_top3")
        calendar_path, calendar_sha = bound("calendar")
        stage = "truth_decode"
        report_path = execution_dir / "TRUTH_EVALUATION_REPORT.json"
        evaluation = evaluate_real_truth_once(
            release=truth_release,
            budget_adapter=action_budget,
            candidate_scores_path=Path(candidate_artifacts["candidate_scores"]["path"]),
            candidate_scores_sha256=candidate_artifacts["candidate_scores"]["sha256"],
            candidate_top3_path=Path(candidate_artifacts["candidate_top3"]["path"]),
            candidate_top3_sha256=candidate_artifacts["candidate_top3"]["sha256"],
            plus_path_scores_path=plus_scores,
            plus_path_scores_sha256=plus_scores_sha,
            plus_path_top3_path=plus_top3,
            plus_path_top3_sha256=plus_top3_sha,
            base34_scores_path=base_scores,
            base34_scores_sha256=base_scores_sha,
            base34_top3_path=base_top3,
            base34_top3_sha256=base_top3_sha,
            calendar_path=calendar_path,
            calendar_sha256=calendar_sha,
            report_path=report_path,
        )
        gates = evaluation.get("current_gates_only")
        complete = bool(
            report_path.is_file()
            and isinstance(gates, Mapping)
            and type(gates.get("passed")) is bool
            and type(evaluation.get("truth_decode_calls")) is int
            and evaluation.get("truth_decode_calls") == 1
        )
        status = (
            "EFFECT_CANNOT_CONFIRM" if not complete else
            "DIRECTION_ONLY" if gates["passed"] is True else
            "NO_BREAKTHROUGH"
        )
        terminal = {
            "schema": "F5_BREADTH1_REAL_TRUTH_EVALUATION_TERMINAL_V1",
            "status": status,
            "decision": status,
            "stage": "completed" if complete else "integrity_incomplete",
            "awaiting_truth_terminal_sha256": handoff_sha,
            "prediction_seal_sha256": seal_sha,
            "action_budget_release_sha256": action_context.release_sha256,
            "evaluation_report_path": str(report_path.resolve()),
            "evaluation_report_sha256": sha256_file(report_path) if report_path.is_file() else None,
            "current_gates_only": gates,
            "effect_status": "TESTED" if complete else "CANNOT_CONFIRM",
            "real_input_accessed": True,
            "real_fit_calls": 0,
            "real_predict_calls": 0,
            "real_model_load_calls": 0,
            "real_truth_decode_calls": (1 if complete else
                                        _chain_action_observation(action_budget.official)["calls"]["truth_decode"]),
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        terminal_sha = write_json_exclusive(terminal, evaluation_terminal_path)
        return {"terminal_path": str(evaluation_terminal_path), "terminal_sha256": terminal_sha, **terminal}
    except BaseException as exc:
        observation = _chain_action_observation(action_budget.official)
        truth_debit = observation["debits"]["truth_decode"]
        truth_callback_entered = observation["calls"]["truth_decode"]
        if observation.get("error_type"):
            exc.add_note(f"TRUTH_ACTION_OBSERVATION_CANNOT_CONFIRM:{observation['error_type']}")
        if truth_debit != 0 or truth_callback_entered != 0:
            terminal = {
                "schema": "F5_BREADTH1_REAL_TRUTH_EVALUATION_TERMINAL_V1",
                "status": "EFFECT_CANNOT_CONFIRM",
                "decision": ("TRUTH_DECODE_ATTEMPT_CONSUMED_NO_REFUND"
                             if type(truth_debit) is int and truth_debit > 0 else
                             "TRUTH_ACTION_STATE_CANNOT_CONFIRM"),
                "stage": stage,
                **_chain_error_details(exc),
                "awaiting_truth_terminal_sha256": handoff_sha,
                "prediction_seal_sha256": seal_sha,
                "action_debits": {"truth_decode": truth_debit},
                "action_observation": observation,
                "real_input_accessed": (None if truth_callback_entered is None else bool(truth_callback_entered)),
                "real_fit_calls": 0,
                "real_predict_calls": 0,
                "real_model_load_calls": 0,
                "real_truth_decode_calls": truth_callback_entered,
                "effect_status": "CANNOT_CONFIRM",
                "research_only": True,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            target_path = evaluation_terminal_path
        else:
            terminal = {
                "schema": "F5_BREADTH1_REAL_TRUTH_EVALUATION_PREFLIGHT_RECEIPT_V1",
                "status": "TRUTH_RELEASE_REJECTED_NO_ACTION_DEBIT",
                "decision": "NO_TRUTH_READ_NO_REFIT_OR_REPREDICT",
                "stage": stage,
                **_chain_error_details(exc),
                "awaiting_truth_terminal_sha256": handoff_sha,
                "prediction_seal_sha256": seal_sha,
                "action_debits": {"truth_decode": 0},
                "real_input_accessed": False,
                "real_fit_calls": 0,
                "real_predict_calls": 0,
                "real_model_load_calls": 0,
                "real_truth_decode_calls": 0,
                "research_only": True,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            target_path = stage2_receipt_path.with_name(f"TRUTH_EVALUATION_PREFLIGHT_REJECTED_{truth_release.expected_sha256}.json")
        try:
            if not target_path.exists():
                write_json_exclusive(terminal, target_path)
        except BaseException as receipt_exc:
            exc.add_note(f"TRUTH_STAGE_RECEIPT_WRITE_UNCONFIRMED:{type(receipt_exc).__name__}:{receipt_exc}")
        raise


def run_test_only_fake_worker_seal_eval_chain(output_dir: Path, fake_fit_predict_callback: Any) -> dict[str, Any]:
    """Exercise prepare -> fake worker -> sealed files -> seven-file evaluation.

    This entry point is intentionally test-only: it accepts a fake worker
    callback, receives only generated fixtures, and is never used by the CLI
    or real execution orchestration. The frozen metrics loader is still fixed.
    """

    output_dir = Path(output_dir).resolve()
    try:
        output_dir.relative_to((BATCH_ROOT / "synthetic_output").resolve())
    except ValueError as exc:
        raise SyntheticChainError("FAKE_WORKER_OUTPUT_MUST_STAY_INSIDE_SYNTHETIC_OUTPUT") from exc
    if not callable(fake_fit_predict_callback):
        raise SyntheticChainError("FAKE_WORKER_CALLBACK_REQUIRED_FOR_TEST_ONLY_CHAIN")
    output_dir.mkdir(parents=True, exist_ok=False)
    tests_dir = CODE_ROOT / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    from f5_breadth1_synthetic_fixtures import (
        SYNTHETIC_CODES, SYNTHETIC_SESSIONS, synthetic_evaluation,
        synthetic_keys_calendar, synthetic_matrix, synthetic_parent,
    )
    from f5_breadth1_core import load_csv_snapshot, persist_npy_snapshot, persist_mask_snapshot

    terminal_path = output_dir / "SYNTHETIC_TERMINAL_RECEIPT.json"
    prepared = False
    predicted = False
    try:
        metrics = load_frozen_metrics()
        parent_rows, producer = synthetic_parent()
        train_keys, calendar = synthetic_keys_calendar()
        required = required_sessions_from_keys_and_calendar(train_keys, calendar)
        breadth = aggregate_breadth1(
            parent_rows,
            expected_codes=SYNTHETIC_CODES,
            expected_sessions=SYNTHETIC_SESSIONS,
            required_sessions=required,
            producer_binding=producer,
        )
        x64, row_keys, _original_mask = synthetic_matrix()
        # For this end-to-end fake worker case all fixture rows are explicitly
        # scoreable so the fixed saved controls share the same G identity.
        scoreable_mask = np.ones(len(row_keys), dtype=np.bool_)
        x65, mapped_keys, mapped_mask = append_breadth1_column(
            x64, row_keys, breadth, original_mask=scoreable_mask,
        )
        train_y = np.asarray([0, 1] * (len(x65) // 2), dtype=np.int8)
        if len(train_y) != len(x65):
            train_y = np.resize(train_y, len(x65)).astype(np.int8)
        score_row_keys = mapped_keys.loc[mapped_mask].reset_index(drop=True)
        score_x = x65[mapped_mask].copy()
        prepared = True
        fake_model_receipt, probabilities = fake_fit_predict_callback(
            train_x=x65.copy(),
            train_y=train_y.copy(),
            score_x=score_x.copy(),
            score_row_keys=score_row_keys.copy(),
        )
        probabilities = np.asarray(probabilities)
        if probabilities.dtype != np.float64 or probabilities.shape != (len(score_x),):
            raise SyntheticChainError("FAKE_WORKER_PROBABILITY_SHAPE_OR_DTYPE_INVALID")
        scores = assemble_full_g_scores(
            eval_row_keys=mapped_keys,
            score_row_keys=score_row_keys,
            scoreable_mask=mapped_mask,
            scoreable_probabilities=probabilities,
        )
        candidate_top3 = score_to_top3(scores, metrics)
        calendar = calendar.loc[:, ["session_id", "market_date"]].copy()
        calendar["year"] = 2024
        validate_exact_top3(candidate_top3, calendar)
        validate_top3_scores(candidate_top3, scores)

        _fixture_candidate_scores, _fixture_candidate_top3, plus_top3, base_top3, truth = synthetic_evaluation(metrics)
        # Saved control score snapshots contain the fixed identity/truth rows;
        # the control Top3 artifacts below are consumed as-is and never reranked.
        plus_scores = truth.copy()
        base_scores = truth.copy()
        plus_scores["scoreable"] = 1
        base_scores["scoreable"] = 1
        plus_scores["probability"] = np.linspace(0.80, 0.40, len(plus_scores), dtype=np.float64)
        base_scores["probability"] = np.linspace(0.75, 0.35, len(base_scores), dtype=np.float64)
        for selected in (plus_top3, base_top3):
            validate_exact_top3(selected, calendar)

        artifact_frames = {
            "candidate_scores": (scores, "CANDIDATE_SCORES_SYNTHETIC.csv.gz"),
            "candidate_top3": (candidate_top3, "CANDIDATE_TOP3_SYNTHETIC.csv.gz"),
            "plus_path_scores": (plus_scores, "PLUS_PATH_SCORES_SYNTHETIC.csv.gz"),
            "plus_path_top3": (plus_top3, "PLUS_PATH_TOP3_SYNTHETIC.csv.gz"),
            "base34_scores": (base_scores, "BASE34_SCORES_SYNTHETIC.csv.gz"),
            "base34_top3": (base_top3, "BASE34_TOP3_SYNTHETIC.csv.gz"),
            "calendar": (calendar, "EVALUATION_CALENDAR_SYNTHETIC.csv.gz"),
        }
        artifact_receipts: dict[str, dict[str, Any]] = {}
        saved: dict[str, pd.DataFrame] = {}
        for name, (frame, filename) in artifact_frames.items():
            saved_frame, digest, size = persist_csv_snapshot(frame, output_dir / filename)
            saved[name] = saved_frame
            artifact_receipts[name] = {"path": filename, "sha256": digest, "bytes": size}
        _, digest, size = persist_npy_snapshot(x65, output_dir / "X65_SYNTHETIC.npy")
        artifact_receipts["x65"] = {"path": "X65_SYNTHETIC.npy", "sha256": digest, "bytes": size}
        _, digest, size = persist_mask_snapshot(mapped_mask, output_dir / "SCOREABLE_MASK_SYNTHETIC.npy")
        artifact_receipts["scoreable_mask"] = {"path": "SCOREABLE_MASK_SYNTHETIC.npy", "sha256": digest, "bytes": size}
        _, digest, size = persist_csv_snapshot(mapped_keys, output_dir / "ROW_KEYS_SYNTHETIC.csv.gz")
        artifact_receipts["row_keys"] = {"path": "ROW_KEYS_SYNTHETIC.csv.gz", "sha256": digest, "bytes": size}

        sealed = {
            "schema": "F5_BREADTH1_SYNTHETIC_PREDICTION_SEAL_V1",
            "status": "SYNTHETIC_SEALED_AWAITING_FAKE_TRUTH_RELEASE",
            "model_receipt": fake_model_receipt,
            "evaluation_input_count": 7,
            "artifacts": artifact_receipts,
            "candidate_artifacts": {
                name: artifact_receipts[name]
                for name in ("candidate_scores", "candidate_top3")
            },
            "real_fit_calls": 0,
            "real_predict_calls": 0,
            "real_truth_decode_calls": 0,
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        seal_sha = write_json_exclusive(sealed, output_dir / "SYNTHETIC_PREDICTION_SEAL.json")
        predicted = True
        terminal = {
            "schema": "F5_BREADTH1_SYNTHETIC_TERMINAL_V1",
            "status": "AWAITING_SYNTHETIC_TRUTH_RELEASE",
            "decision": "AWAITING_SYNTHETIC_TRUTH_RELEASE",
            "effect_status": "NOT_TESTED",
            "prepare_complete": True,
            "worker_complete": True,
            "prediction_sealed": True,
            "seven_file_evaluation_complete": False,
            "prediction_seal_path": str((output_dir / "SYNTHETIC_PREDICTION_SEAL.json").resolve()),
            "seal_sha256": seal_sha,
            "real_input_accessed": False,
            "real_fit_calls": 0,
            "real_predict_calls": 0,
            "real_truth_decode_calls": 0,
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        terminal_sha = write_json_exclusive(terminal, terminal_path)
        return {
            "status": terminal["status"],
            "terminal_path": str(terminal_path),
            "terminal_sha256": terminal_sha,
            "artifact_receipts": artifact_receipts,
            "sealed_artifact_count": int(len(artifact_frames)),
        }
    except BaseException as exc:
        if not terminal_path.exists():
            terminal = {
                "schema": "F5_BREADTH1_SYNTHETIC_TERMINAL_V1",
                "status": "EFFECT_CANNOT_CONFIRM",
                "decision": "SYNTHETIC_WORKER_OR_CONTINUATION_REJECTED",
                "effect_status": "NOT_TESTED",
                "prepare_complete": prepared,
                "worker_complete": False,
                "prediction_sealed": predicted,
                "seven_file_evaluation_complete": False,
                "error_type": type(exc).__name__,
                "real_input_accessed": False,
                "real_fit_calls": 0,
                "real_predict_calls": 0,
                "real_truth_decode_calls": 0,
                "research_only": True,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            write_json_exclusive(terminal, terminal_path)
        raise


def build_test_only_truth_release(output_dir: Path) -> dict[str, Any]:
    """Build an explicit fake approval pinned to the generated synthetic seal."""

    output_dir = Path(output_dir).resolve()
    terminal_path = output_dir / "SYNTHETIC_TERMINAL_RECEIPT.json"
    seal_path = output_dir / "SYNTHETIC_PREDICTION_SEAL.json"
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal_sha = sha256_file(seal_path)
    if (
        terminal.get("status") != "AWAITING_SYNTHETIC_TRUTH_RELEASE"
        or terminal.get("seal_sha256") != seal_sha
        or terminal.get("prediction_seal_path") != str(seal_path.resolve())
    ):
        raise SyntheticChainError("SYNTHETIC_RELEASE_REQUIRES_EXACT_SEALED_HANDOFF")
    return {
        "schema": "F5_BREADTH1_SYNTHETIC_TRUTH_RELEASE_V1",
        "status": "APPROVED_SYNTHETIC_ONLY",
        "seal_path": str(seal_path.resolve()),
        "seal_sha256": seal_sha,
        "candidate_artifacts": dict(seal["candidate_artifacts"]),
    }


def resume_test_only_sealed_evaluation(output_dir: Path, fake_release: Mapping[str, Any]) -> dict[str, Any]:
    """Read and evaluate saved synthetic files only after their fake approval."""

    output_dir = Path(output_dir).resolve()
    try:
        output_dir.relative_to((BATCH_ROOT / "synthetic_output").resolve())
    except ValueError as exc:
        raise SyntheticChainError("SYNTHETIC_EVALUATION_OUTPUT_MUST_STAY_INSIDE_SYNTHETIC_OUTPUT") from exc
    terminal_path = output_dir / "SYNTHETIC_TERMINAL_RECEIPT.json"
    seal_path = output_dir / "SYNTHETIC_PREDICTION_SEAL.json"
    evaluation_path = output_dir / "SYNTHETIC_EVALUATION.json"
    evaluation_terminal_path = output_dir / "SYNTHETIC_EVALUATION_TERMINAL_RECEIPT.json"
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal_sha = sha256_file(seal_path)
    if (
        terminal.get("status") != "AWAITING_SYNTHETIC_TRUTH_RELEASE"
        or terminal.get("seal_sha256") != seal_sha
        or fake_release.get("schema") != "F5_BREADTH1_SYNTHETIC_TRUTH_RELEASE_V1"
        or fake_release.get("status") != "APPROVED_SYNTHETIC_ONLY"
        or fake_release.get("seal_path") != str(seal_path.resolve())
        or fake_release.get("seal_sha256") != seal_sha
        or fake_release.get("candidate_artifacts") != seal.get("candidate_artifacts")
    ):
        raise SyntheticChainError("SYNTHETIC_TRUTH_RELEASE_DOES_NOT_MATCH_IMMUTABLE_SEAL")
    if evaluation_path.exists() or evaluation_terminal_path.exists():
        raise SyntheticChainError("SYNTHETIC_EVALUATION_ALREADY_EXISTS_NO_OVERWRITE")

    from f5_breadth1_core import load_csv_snapshot

    artifacts = seal.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != {
        "candidate_scores", "candidate_top3", "plus_path_scores", "plus_path_top3",
        "base34_scores", "base34_top3", "calendar", "x65", "scoreable_mask", "row_keys",
    }:
        raise SyntheticChainError("SYNTHETIC_SEALED_ARTIFACT_SET_MISMATCH")
    reread: dict[str, pd.DataFrame] = {}
    for name in (
        "candidate_scores", "candidate_top3", "plus_path_scores", "plus_path_top3",
        "base34_scores", "base34_top3", "calendar",
    ):
        record = artifacts[name]
        path = output_dir / record["path"]
        reread[name], actual_sha, actual_bytes = load_csv_snapshot(path, record["sha256"])
        if actual_sha != record["sha256"] or actual_bytes != record["bytes"]:
            raise SyntheticChainError(f"SYNTHETIC_EVALUATION_SNAPSHOT_MISMATCH:{name}")
    metrics = load_frozen_metrics()
    truth_projection = reread["plus_path_scores"].loc[
        :, ["session_id", "code", "y", "episode_state", "first_exact"]
    ].copy()
    evaluation = evaluate_synthetic_artifacts(
        candidate_scores=reread["candidate_scores"],
        candidate_top3=reread["candidate_top3"],
        plus_path_top3=reread["plus_path_top3"],
        base34_top3=reread["base34_top3"],
        synthetic_truth=truth_projection,
        calendar=reread["calendar"],
        metrics=metrics,
    )
    evaluation_sha = write_json_exclusive(evaluation, evaluation_path)
    evaluation_terminal = {
        "schema": "F5_BREADTH1_SYNTHETIC_EVALUATION_TERMINAL_V1",
        "status": "ENGINEERING_CANARY_ONLY",
        "decision": "SYNTHETIC_CHAIN_COMPLETED_AFTER_EXPLICIT_RELEASE",
        "effect_status": "NOT_TESTED",
        "seal_sha256": seal_sha,
        "evaluation_sha256": evaluation_sha,
        "evaluation_status": evaluation["status"],
        "synthetic_gate_result": evaluation["current_gates_only"],
        "seven_file_evaluation_complete": True,
        "real_input_accessed": False,
        "real_fit_calls": 0,
        "real_predict_calls": 0,
        "real_truth_decode_calls": 0,
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    terminal_sha = write_json_exclusive(evaluation_terminal, evaluation_terminal_path)
    return {
        "status": evaluation_terminal["status"],
        "terminal_path": str(evaluation_terminal_path),
        "terminal_sha256": terminal_sha,
        "evaluation": evaluation,
    }


def run_synthetic_io_chain(output_dir: Path, metrics: Any | None = None) -> dict[str, Any]:
    """Persist and consume one deterministic synthetic parent-to-diagnostics chain."""

    tests_dir = CODE_ROOT / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    from f5_breadth1_synthetic_fixtures import (
        SYNTHETIC_CODES, SYNTHETIC_SESSIONS, synthetic_evaluation,
        synthetic_keys_calendar, synthetic_matrix, synthetic_parent,
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    metrics = metrics or load_frozen_metrics()

    parent_rows, producer = synthetic_parent()
    train_keys, eval_calendar = synthetic_keys_calendar()
    required_sessions = required_sessions_from_keys_and_calendar(train_keys, eval_calendar)
    breadth = aggregate_breadth1(
        parent_rows,
        expected_codes=SYNTHETIC_CODES,
        expected_sessions=SYNTHETIC_SESSIONS,
        required_sessions=required_sessions,
        producer_binding=producer,
    )
    x64, row_keys, original_mask = synthetic_matrix()
    x65, mapped_keys, mapped_mask = append_breadth1_column(
        x64, row_keys, breadth, original_mask=original_mask
    )

    artifact_receipts: dict[str, dict[str, Any]] = {}
    parsed_breadth, digest, size = persist_csv_snapshot(breadth, output_dir / "BREADTH1_BY_SESSION.csv.gz")
    artifact_receipts["breadth1_by_session"] = {"path": "BREADTH1_BY_SESSION.csv.gz", "sha256": digest, "bytes": size}
    breadth_saved = parsed_breadth["breadth1"].to_numpy(dtype=np.float32)
    if not np.array_equal(breadth_saved.view(np.uint32), breadth["breadth1"].to_numpy(dtype=np.float32).view(np.uint32)):
        raise SyntheticChainError("BREADTH1_FLOAT32_ROUND_TRIP_MISMATCH")

    x65_saved, digest, size = persist_npy_snapshot(x65, output_dir / "X65_SYNTHETIC.npy")
    artifact_receipts["x65"] = {"path": "X65_SYNTHETIC.npy", "sha256": digest, "bytes": size}
    keys_saved, digest, size = persist_csv_snapshot(mapped_keys, output_dir / "ROW_KEYS_SYNTHETIC.csv.gz")
    artifact_receipts["row_keys"] = {"path": "ROW_KEYS_SYNTHETIC.csv.gz", "sha256": digest, "bytes": size}
    if not keys_saved[["code", "session_id"]].reset_index(drop=True).equals(mapped_keys[["code", "session_id"]].reset_index(drop=True)):
        raise SyntheticChainError("ROW_KEY_ROUND_TRIP_MISMATCH")
    mask_saved, digest, size = persist_mask_snapshot(mapped_mask, output_dir / "SCOREABLE_MASK_SYNTHETIC.npy")
    artifact_receipts["scoreable_mask"] = {"path": "SCOREABLE_MASK_SYNTHETIC.npy", "sha256": digest, "bytes": size}
    if not np.array_equal(mask_saved, original_mask):
        raise SyntheticChainError("ORIGINAL_MASK_CHANGED")

    candidate_scores, _, plus_top3, base_top3, truth = synthetic_evaluation(metrics)
    candidate_top3 = score_to_top3(candidate_scores, metrics)
    calendar = eval_calendar.loc[:, ["session_id", "market_date"]].copy()
    calendar["year"] = 2024
    validate_exact_top3(candidate_top3, calendar)
    validate_exact_top3(plus_top3, calendar)
    validate_exact_top3(base_top3, calendar)
    validate_top3_scores(candidate_top3, candidate_scores)

    persisted: dict[str, pd.DataFrame] = {}
    for name, frame, filename in (
        ("candidate_scores", candidate_scores, "CANDIDATE_SCORES_SYNTHETIC.csv.gz"),
        ("candidate_top3", candidate_top3, "CANDIDATE_TOP3_SYNTHETIC.csv.gz"),
        ("plus_path_top3", plus_top3, "PLUS_PATH_TOP3_SYNTHETIC.csv.gz"),
        ("base34_top3", base_top3, "BASE34_TOP3_SYNTHETIC.csv.gz"),
        ("synthetic_truth", truth, "SYNTHETIC_TRUTH.csv.gz"),
    ):
        saved, digest, size = persist_csv_snapshot(frame, output_dir / filename)
        persisted[name] = saved
        artifact_receipts[name] = {"path": filename, "sha256": digest, "bytes": size}

    evaluation = evaluate_synthetic_artifacts(
        candidate_scores=persisted["candidate_scores"],
        candidate_top3=persisted["candidate_top3"],
        plus_path_top3=persisted["plus_path_top3"],
        base34_top3=persisted["base34_top3"],
        synthetic_truth=persisted["synthetic_truth"],
        calendar=calendar,
        metrics=metrics,
    )
    metrics_sha = write_json_exclusive(evaluation, output_dir / "SYNTHETIC_METRICS.json")
    artifact_receipts["synthetic_metrics"] = {
        "path": "SYNTHETIC_METRICS.json",
        "sha256": metrics_sha,
        "bytes": (output_dir / "SYNTHETIC_METRICS.json").stat().st_size,
    }
    code_sha = {
        str(Path(relative)): sha256_file(PROJECT_ROOT / relative)
        for relative in CODE_BINDINGS
    }
    receipt = {
        "schema": "F5_BREADTH1_SYNTHETIC_IO_RECEIPT_V1",
        "status": "ENGINEERING_CANARY_ONLY",
        "synthetic_only": True,
        "real_input_accessed": False,
        "real_fit_calls": 0,
        "real_predict_calls": 0,
        "real_truth_decode_calls": 0,
        "synthetic_truth_access": "SYNTHETIC_FIXTURE_ONLY",
        "required_sessions": list(required_sessions),
        "parent_grid_rows": int(len(parent_rows)),
        "feature_rows": int(len(x64)),
        "feature_columns_before_after": [int(x64.shape[1]), int(x65.shape[1])],
        "original_prefix_nan_count": int(np.isnan(x64).sum()),
        "breadth1_summary": parsed_breadth.to_dict(orient="records"),
        "original_prefix_row_key_mask_parity": True,
        "candidate_top3_exact_three_per_day": True,
        "controls_loaded_from_saved_top3_without_reselection": True,
        "metrics_sha256": "c8ffabf345069d64a82ac686e6747afda8c22433f1309eecdc999a7ad1eac763",
        "artifact_receipts": artifact_receipts,
        "code_sha256": code_sha,
        "evaluation_gate_result_is_synthetic_only": evaluation["current_gates_only"],
    }
    receipt_sha = write_json_exclusive(receipt, output_dir / "SYNTHETIC_IO_RECEIPT.json")
    return {
        "output_dir": str(output_dir),
        "receipt_path": str(output_dir / "SYNTHETIC_IO_RECEIPT.json"),
        "receipt_sha256": receipt_sha,
        "artifact_receipts": artifact_receipts,
        "evaluation": evaluation,
    }


def _verify_frozen_identity(contract: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, str]:
    if (
        contract.get("status") != "DRAFT_NO_REAL_RUN"
        or contract.get("route_id") != ROUTE_ID
        or contract.get("candidate_id") != ROUTE_ID
    ):
        raise SyntheticChainError("CONTRACT_NOT_FROZEN_DRAFT_FOR_BREADTH1")
    if (
        binding.get("schema") != "F5_BREADTH1_SYNTHETIC_INPUT_BINDING_V1"
        or binding.get("synthetic_only") is not True
        or binding.get("route_id") != ROUTE_ID
        or binding.get("candidate_id") != ROUTE_ID
        or binding.get("contract_sha256") != sha256(CONTRACT_PATH.read_bytes()).hexdigest()
    ):
        raise SyntheticChainError("SYNTHETIC_INPUT_BINDING_INVALID")
    _verify_synthetic_runtime(contract.get("synthetic_test_runtime"), binding.get("synthetic_test_runtime"))
    expected = contract.get("code_sha256")
    binding_expected = binding.get("code_sha256")
    if not isinstance(expected, Mapping) or dict(expected) != dict(binding_expected or {}):
        raise SyntheticChainError("CONTRACT_AND_SYNTHETIC_CODE_BINDING_DIFFER")
    try:
        return verify_candidate_code_bindings(expected)
    except ValueError as exc:
        raise SyntheticChainError(f"FROZEN_CODE_BINDING_INVALID:{exc}") from exc


def _verify_synthetic_runtime(contract_runtime: Any, binding_runtime: Any) -> dict[str, Any]:
    if contract_runtime != LOCKED_SYNTHETIC_RUNTIME or binding_runtime != LOCKED_SYNTHETIC_RUNTIME:
        raise SyntheticChainError("SYNTHETIC_TEST_RUNTIME_BINDING_MISMATCH")
    executable = Path(sys.executable)
    if (
        sys.version_info[:3] != (3, 13, 12)
        or str(executable) != LOCKED_SYNTHETIC_RUNTIME["python_executable_invocation_path"]
        or str(executable.resolve()) != LOCKED_SYNTHETIC_RUNTIME["python_executable_resolved_path"]
        or sha256_file(executable.resolve()) != LOCKED_SYNTHETIC_RUNTIME["python_executable_sha256"]
    ):
        raise SyntheticChainError("SYNTHETIC_TEST_PYTHON_IDENTITY_MISMATCH")
    try:
        actual_packages = {
            name: importlib.metadata.version(name)
            for name in LOCKED_SYNTHETIC_RUNTIME["packages"]
        }
    except importlib.metadata.PackageNotFoundError as exc:
        raise SyntheticChainError(f"SYNTHETIC_TEST_RUNTIME_PACKAGE_MISSING:{exc.name}") from exc
    if actual_packages != LOCKED_SYNTHETIC_RUNTIME["packages"]:
        raise SyntheticChainError("SYNTHETIC_TEST_PACKAGE_VERSION_MISMATCH")
    if not Path(LOCKED_SYNTHETIC_RUNTIME["site_packages_path"]).is_dir():
        raise SyntheticChainError("SYNTHETIC_TEST_SITE_PACKAGES_MISSING")
    for path_key, sha_key in (
        ("environment_lock_receipt_path", "environment_lock_receipt_sha256"),
        ("requirements_lock_path", "requirements_lock_sha256"),
    ):
        path = Path(LOCKED_SYNTHETIC_RUNTIME[path_key])
        if not path.is_file() or sha256_file(path) != LOCKED_SYNTHETIC_RUNTIME[sha_key]:
            raise SyntheticChainError(f"SYNTHETIC_TEST_RUNTIME_LOCK_IDENTITY_MISMATCH:{path_key}")
    return {
        **LOCKED_SYNTHETIC_RUNTIME,
        "python_version_observed": sys.version,
        "python_executable_invocation_path_observed": str(executable),
        "python_executable_resolved_path_observed": str(executable.resolve()),
        "package_versions_observed": actual_packages,
    }


def _run_registered_unit_suite() -> dict[str, Any]:
    import unittest

    tests_dir = CODE_ROOT / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for name in ("test_f5_breadth1_inputs", "test_f5_breadth1_evaluate", "test_f5_breadth1_pipeline"):
        suite.addTests(loader.loadTestsFromModule(importlib.import_module(name)))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}
    if not result.wasSuccessful():
        raise SyntheticChainError(f"REGISTERED_SYNTHETIC_UNIT_SUITE_FAILED:{summary}")
    return summary


def _make_official_adapter(
    output_dir: Path,
    registry_receipt_path: Path,
    *,
    registry_path: Path | None = None,
    contract_path: Path | None = None,
    input_binding_path: Path | None = None,
    scope_lock_path: Path | None = None,
    event_profile: Mapping[str, str] | None = None,
):
    registry_path = registry_path or PROJECT_ROOT / "contracts" / "EXPERIMENT_REGISTRY.jsonl"
    contract_path = contract_path or CONTRACT_PATH
    input_binding_path = input_binding_path or SYNTHETIC_BINDING_PATH
    guard_dir = PROJECT_ROOT / "workspace" / "hkconnect_price_semantics_v2_20260919" / "zero_label_parity"
    if str(guard_dir) not in sys.path:
        sys.path.insert(0, str(guard_dir))
    from registry_adapter import OfficialRegistryAdapter

    code_paths = [PROJECT_ROOT / path for path in CODE_BINDINGS]
    return OfficialRegistryAdapter(
        registry_path=registry_path,
        contract_path=contract_path,
        input_binding_path=input_binding_path,
        artifact_paths=[*code_paths, scope_lock_path or BATCH_ROOT / "SCOPE_LOCK.md"],
        event_profile=event_profile or EVENT_PROFILE,
    )


def _duplicate_claim_probe(execution_id: str) -> bool:
    """Fresh-process guard probe; it only attempts an already-persisted ID."""

    guard_dir = PROJECT_ROOT / "workspace" / "hkconnect_price_semantics_v2_20260919" / "zero_label_parity"
    if str(guard_dir) not in sys.path:
        sys.path.insert(0, str(guard_dir))
    from execution_guard_core import DuplicateExecutionId, ExecutionGuard

    registry_receipt_path = BATCH_ROOT / "receipts" / "registry_append" / f"{execution_id}.json"
    output_dir = BATCH_ROOT / "synthetic_output" / execution_id
    adapter = _make_official_adapter(output_dir, registry_receipt_path)
    starts = [
        event for event in adapter.list_events(EXPERIMENT_ID)
        if event.get("execution_id") == execution_id and event.get("event_type") == "RUN_STARTED"
    ]
    if len(starts) != 1:
        return False
    contract_sha = sha256(CONTRACT_PATH.read_bytes()).hexdigest()
    input_binding_sha = sha256(SYNTHETIC_BINDING_PATH.read_bytes()).hexdigest()
    guard = ExecutionGuard(adapter, experiment_id=EXPERIMENT_ID, max_real_fit_debits=1)
    try:
        guard.claim_no_fit(
            execution_id=execution_id,
            arm="BREADTH1_SYNTHETIC_IO_CHAIN",
            contract_sha256=contract_sha,
            input_binding_sha256=input_binding_sha,
        )
    except DuplicateExecutionId:
        return True
    return False


def run_registered_input_admission_audit(
    *, resume_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Register the fixed, user-authorized recovery audit before any released input opens."""

    paths = _r7_chain_paths()
    resume = dict(resume_context) if isinstance(resume_context, Mapping) else None
    real_contract_path = paths["resume_contract"] if resume is not None else paths["contract"]
    real_binding_path = paths["resume_pending_binding"] if resume is not None else paths["pending_binding"]
    if real_contract_path.is_symlink() or real_binding_path.is_symlink():
        raise SyntheticChainError("RECOVERY_CONTRACT_OR_BINDING_SYMLINK_NOT_ALLOWED")
    contract_bytes = real_contract_path.read_bytes()
    binding_bytes = real_binding_path.read_bytes()
    contract = json.loads(contract_bytes.decode("utf-8"))
    binding = json.loads(binding_bytes.decode("utf-8"))
    if contract.get("status") != "DRAFT_NO_REAL_RUN" or contract.get("is_execution_contract") is not False:
        raise SyntheticChainError("INPUT_ADMISSION_AUDIT_REQUIRES_DRAFT_NO_EXECUTION_CONTRACT")
    if binding.get("status") != "ADMISSION_PENDING" or binding.get("synthetic_only") is not False:
        raise SyntheticChainError("INPUT_ADMISSION_AUDIT_REQUIRES_PENDING_REAL_BINDING_DRAFT")
    contract_sha = sha256(contract_bytes).hexdigest()
    binding_sha = sha256(binding_bytes).hexdigest()
    read_release_path = paths["resume_read_release"] if resume is not None else PANEL_HEADER_RECOVERY_READ_RELEASE_PATH
    if read_release_path.is_symlink():
        raise SyntheticChainError("INPUT_ADMISSION_READ_RELEASE_SYMLINK_NOT_ALLOWED")
    try:
        read_release_path.resolve().relative_to((BATCH_ROOT / "bindings").resolve())
    except ValueError as exc:
        raise SyntheticChainError("INPUT_ADMISSION_READ_RELEASE_MUST_STAY_IN_BATCH_BINDINGS") from exc
    final_binding_path = paths["resume_final_binding"] if resume is not None else paths["final_binding"]
    if final_binding_path.exists():
        raise SyntheticChainError("FINAL_REAL_INPUT_BINDING_ALREADY_EXISTS_NO_OVERWRITE")

    event_profile = {
        **EVENT_PROFILE,
        "start_stage": "BREADTH1_PARENT_PANEL_DATE_RECOVERY_R7_ADMISSION_STARTED",
        "terminal_stage": "BREADTH1_PARENT_PANEL_DATE_RECOVERY_R7_ADMISSION_TERMINAL",
        "signal_scope": "READ_RELEASED_PARENT_INPUTS_ONLY",
        "target_scope": "NO_MODEL_OR_TRUTH_ACTION",
        "one_variable": "verified_current_binding_identity_and_R6_control_validation_failure_linkage",
        "evidence_level": "CANNOT_CONFIRM_UNTIL_AUDIT_RECEIPT",
    }
    admission_execution_id = PANEL_HEADER_RECOVERY_EXECUTION_ID
    registry_receipt_path = (
        paths["resume_run"] / "R7_RESUME_ADMISSION_REGISTRY_RECEIPT.json"
        if resume is not None else
        BATCH_ROOT / "receipts" / "registry_append" / f"{admission_execution_id}.json"
    )
    if registry_receipt_path.exists():
        raise SyntheticChainError("RECOVERY_ADMISSION_REGISTRY_RECEIPT_ALREADY_EXISTS_NO_OVERWRITE")
    adapter = (
        resume["official"] if resume is not None else
        _make_official_adapter(
            BATCH_ROOT / "receipts" / "input_admission",
            registry_receipt_path,
            contract_path=real_contract_path,
            input_binding_path=real_binding_path,
            scope_lock_path=paths["scope_lock"],
            event_profile=event_profile,
        )
    )
    if resume is not None:
        adapter.artifact_paths = (
            *adapter.artifact_paths, paths["resume_authorization"], read_release_path,
            paths["resume_run"] / "RESUME_CHECKPOINT_PRETARGET.json",
            PANEL_HEADER_RECOVERY_OUTPUT_PATH / "PIPELINE_TERMINAL_RECEIPT.json",
        )
    adapter.artifact_paths = (
        *adapter.artifact_paths,
        PANEL_HEADER_RECOVERY_GRANT_PATH,
        PANEL_HEADER_RECOVERY_READ_PLAN_PATH,
        real_binding_path,
        PANEL_HEADER_FAILED_RECEIPT_PATH,
        PANEL_HEADER_FAILED_REGISTRY_RECEIPT_PATH,
        PANEL_HEADER_R4_RUNTIME_FAILURE_RECEIPT_PATH,
        PANEL_HEADER_R5_FAILED_RECEIPT_PATH,
        PANEL_HEADER_R6_FAILED_RECEIPT_PATH,
        PANEL_HEADER_DIAGNOSTIC_RECEIPT_PATH,
        TRAIN_LABEL_DIAGNOSTIC_RECEIPT_PATH,
    )
    action_budget = BREADTH1OfficialActionAdapter(
        adapter,
        contract_sha256=contract_sha,
        input_binding_sha256=binding_sha,
        synthetic=False,
        admission_only=True,
    )
    # This lock-held fixed action key is durably consumed before the release
    # or any target input bytes are opened. Failure and interruption do not
    # refund the one logical admission check.
    claim = resume["resume_claim"] if resume is not None else action_budget.claim_parent_panel_date_recovery()
    adapter.artifact_paths = (*adapter.artifact_paths, read_release_path)
    verified_release = None
    audit = None
    final_binding = None
    callback_entered = False
    terminal_attempted = False
    try:
        callback_entered = True
        if resume is not None:
            verified_release = resume["resume_release"]
        else:
            verified_release = load_verified_input_admission_read_release(
                read_release_path,
                claim.release_sha256,
                contract_sha256=contract_sha,
                input_binding_sha256=binding_sha,
                input_binding_path=real_binding_path,
            )
        audit = audit_real_input_admission(
            verified_release, registry_claim=claim, registry_adapter=adapter,
            resume_context=resume,
        )
        if audit.get("status") == "PASS":
            final_binding = _materialize_admitted_real_binding(
                audit,
                final_binding_path=final_binding_path,
            )
        producer_artifact_paths = tuple(
            Path(audit["actual_read"]["files"][name]["path"])
            for name in (
                "producer_source", "producer_output_run_receipt",
                "producer_environment_receipt", "full_grid_flag_join_receipt",
            )
            if name in audit.get("actual_read", {}).get("files", {})
        )
        adapter.artifact_paths = (
            *adapter.artifact_paths,
            Path(audit["receipt_path"]),
            *((Path(final_binding["path"]),) if final_binding is not None else ()),
            *producer_artifact_paths,
        )
        audit_succeeded = audit.get("status") in {"PASS", "INPUT_REJECTED"}
        if resume is None:
            terminal_attempted = True
            action_budget.terminalize(
                claim,
                succeeded=audit_succeeded,
                callback_entered=True,
                error_type=None if audit_succeeded else str(audit.get("status", "CANNOT_CONFIRM_INPUT_ADMISSION")),
            )

        lifecycle = [
            event for event in adapter.list_events(EXPERIMENT_ID)
            if event.get("execution_id") == claim.execution_id
        ]
        if len(lifecycle) != 2 or {event.get("event_type") for event in lifecycle} != {"RUN_STARTED", "TERMINAL"}:
            raise SyntheticChainError("INPUT_ADMISSION_REGISTRY_LIFECYCLE_RECEIPT_MISMATCH")
        pre_admission_binding_snapshot = audit.pop("_pre_admission_binding_snapshot", None)
        registry_path = PROJECT_ROOT / "contracts" / "EXPERIMENT_REGISTRY.jsonl"
        registry_receipt = {
            "schema": "F5_BREADTH1_INPUT_ADMISSION_REGISTRY_RECEIPT_V1",
            "route_id": ROUTE_ID,
            "execution_id": claim.execution_id,
            "route_lifecycle_count": len(lifecycle),
            "events": [
                {
                    "registry_event_id": event.get("registry_event_id"),
                    "event_type": event.get("event_type"),
                    "event_sha256": event.get("event_sha256"),
                    "decision": event.get("decision"),
                }
                for event in lifecycle
            ],
            "registry_path": str(registry_path),
            "registry_bytes_after_append": registry_path.stat().st_size if resume is None else None,
            "registry_sha256_after_append": sha256_file(registry_path) if resume is None else None,
            "registry_bytes_at_resume_audit": registry_path.stat().st_size if resume is not None else None,
            "registry_sha256_at_resume_audit": sha256_file(registry_path) if resume is not None else None,
            "input_admission_receipt_path": audit["receipt_path"],
            "input_admission_receipt_sha256": audit["receipt_sha256"],
            "input_admission_status": audit["status"],
            "pre_admission_binding_path": audit.get("pre_admission_binding_path"),
            "pre_admission_binding_sha256": audit.get("pre_admission_binding_sha256"),
            "final_action_binding": final_binding,
            "pre_admission_snapshot_reused_in_memory": isinstance(pre_admission_binding_snapshot, Mapping),
            "r7_resume": ({
                "authorization_path": str(paths["resume_authorization"].resolve()),
                "authorization_sha256": resume.get("authorization_sha256"),
                "original_start_event_sha256": resume["resume_start_event"]["event_sha256"],
                "original_failed_terminal_event_sha256": resume["resume_failure_terminal_event"]["event_sha256"],
                "logical_r7_action_debit_total": 1,
                "additional_r7_action_debit": 0,
                "physical_invocation_index": 3,
            } if resume is not None else None),
            "observed_input_artifacts_hashed_by_registry_terminal": [
                {
                    "name": name,
                    "path": audit.get("actual_read", {}).get("files", {}).get(name, {}).get("path"),
                    "sha256": audit.get("actual_read", {}).get("files", {}).get(name, {}).get("sha256"),
                    "bytes": audit.get("actual_read", {}).get("files", {}).get(name, {}).get("bytes"),
                    "separate_from_target_input_read_budget": True,
                }
                for name in ()
                if name in audit.get("actual_read", {}).get("files", {})
            ],
            "target_input_file_count": audit["actual_read"]["file_count"],
            "target_input_total_bytes": audit["actual_read"]["total_bytes"],
            "official_registry_hash_and_append_io": (
                "NO_R7_EVENT_APPEND; R7 START_AND_FAILED_TERMINAL_PRESERVED; RESUME AUDIT IS REGISTERED ON SEPARATE ENGINEERING ROUTE"
                if resume is not None else
                "SEPARATELY_IDENTIFIED_BY_REGISTRY_RECEIPT_AND_AFTER_APPEND_IDENTITY"
            ),
            "real_fit_calls": 0,
            "real_predict_calls": 0,
            "real_truth_decode_calls": 0,
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        registry_receipt_sha = write_json_exclusive(registry_receipt, registry_receipt_path)
        return {
            **audit,
            "final_action_binding": final_binding,
            "registry_receipt_path": str(registry_receipt_path),
            "registry_receipt_sha256": registry_receipt_sha,
        }
    except BaseException as exc:
        # Preserve already-observed accounting without reopening targets or
        # serializing the cached arrays. A later registry/receipt I/O failure
        # must not erase the immutable admission receipt's known facts.
        if isinstance(audit, Mapping):
            snapshot = {key: value for key, value in audit.items() if not key.startswith("_")}
            snapshot["final_action_binding"] = final_binding
            exc.r7_admission_audit_snapshot = snapshot
            audit_path = audit.get("receipt_path")
            if isinstance(audit_path, str) and Path(audit_path) not in adapter.artifact_paths:
                adapter.artifact_paths = (*adapter.artifact_paths, Path(audit_path))
        if verified_release is not None and verified_release.path not in adapter.artifact_paths:
            adapter.artifact_paths = (*adapter.artifact_paths, verified_release.path)
        # terminalize may append durably and then fail its readback. Never
        # invoke it twice for the same claim, and keep the original exception.
        if resume is None and not terminal_attempted:
            terminal_attempted = True
            try:
                action_budget.terminalize(
                    claim, succeeded=False, callback_entered=callback_entered,
                    error_type=type(exc).__name__,
                )
            except BaseException as terminal_exc:
                exc.add_note(f"ADMISSION_TERMINAL_WRITE_UNCONFIRMED:{type(terminal_exc).__name__}:{terminal_exc}")
        raise


def _materialize_admitted_real_binding(
    audit: Mapping[str, Any],
    *,
    final_binding_path: Path,
) -> dict[str, Any]:
    """Create the action binding from the exact already-read pre-admission snapshot.

    Keeping the final action binding in a separate file avoids a self-referential
    hash: the admission receipt binds the pre-admission file, while this file
    binds the receipt and that pre-admission identity.
    """

    snapshot = audit.get("_pre_admission_binding_snapshot")
    actual_read = audit.get("actual_read")
    read_files = actual_read.get("files") if isinstance(actual_read, Mapping) else None
    input_binding_record = read_files.get("input_binding") if isinstance(read_files, Mapping) else None
    pre_sha = audit.get("pre_admission_binding_sha256")
    pre_path = audit.get("pre_admission_binding_path")
    read_authorization = audit.get("read_authorization")
    read_budget = audit.get("read_budget")
    if (
        audit.get("status") != "PASS"
        or not isinstance(snapshot, Mapping)
        or not isinstance(input_binding_record, Mapping)
        or not isinstance(pre_sha, str)
        or input_binding_record.get("sha256") != pre_sha
        or not isinstance(pre_path, str)
        or input_binding_record.get("path") != pre_path
        or not isinstance(audit.get("receipt_sha256"), str)
        or not isinstance(audit.get("read_release_sha256"), str)
        or not isinstance(audit.get("verified_arrays"), Mapping)
    ):
        raise SyntheticChainError("ADMITTED_BINDING_REQUIRES_PASS_AND_EXACT_PRE_ADMISSION_SNAPSHOT")
    final_binding = dict(snapshot)
    frozen_artifacts = final_binding.get("frozen_artifacts")
    if not isinstance(frozen_artifacts, Mapping):
        raise SyntheticChainError("ADMITTED_BINDING_FROZEN_PREPARE_ARTIFACTS_MISSING")
    prepare_names = ("train_x64", "train_y", "train_keys", "eval_x64", "evaluation_calendar", "pretruth_scores")
    prepare_artifacts: dict[str, dict[str, Any]] = {}
    for name in prepare_names:
        descriptor = frozen_artifacts.get(name)
        if not isinstance(descriptor, Mapping):
            raise SyntheticChainError(f"ADMITTED_BINDING_FROZEN_ARTIFACT_MISSING:{name}")
        prepare_artifacts[name] = {
            "path": descriptor.get("path"),
            "sha256": descriptor.get("sha256"),
            "max_bytes": descriptor.get("max_bytes"),
        }
    final_binding.update({
        "schema": "F5_BREADTH1_REAL_INPUT_BINDING_V1",
        "status": "PASS",
        "input_admission_status": "PASS",
        "real_input_accessed": True,
        "pre_admission_binding_path": pre_path,
        "pre_admission_binding_sha256": pre_sha,
        "input_admission_receipt_path": audit.get("receipt_path"),
        "input_admission_receipt_sha256": audit.get("receipt_sha256"),
        "input_admission_receipt_max_bytes": 16 * 1024 * 1024,
        "input_admission_read_release_sha256": audit.get("read_release_sha256"),
        "current_authorized_real_actions": {
            "read": 0, "fit": 0, "predict": 0, "model_load": 0, "truth_decode": 0,
        },
        "verified_arrays": {"status": "PASS", **dict(audit["verified_arrays"])},
        "prepare_artifacts": prepare_artifacts,
    })
    if isinstance(audit.get("r7_resume"), Mapping):
        final_binding["r7_resume"] = dict(audit["r7_resume"])
    first_pass = final_binding.get("first_pass_read_release")
    if isinstance(first_pass, Mapping):
        final_binding["first_pass_read_release"] = {
            **dict(first_pass),
            "status": "PASS",
            "read_release_sha256": audit.get("read_release_sha256"),
            "read_release_path": read_authorization.get("path") if isinstance(read_authorization, Mapping) else None,
            "max_files": read_budget.get("max_files") if isinstance(read_budget, Mapping) else None,
            "max_file_bytes": read_budget.get("max_file_bytes") if isinstance(read_budget, Mapping) else None,
            "max_total_bytes": read_budget.get("max_total_bytes") if isinstance(read_budget, Mapping) else None,
            "reason": None,
        }
    digest = write_json_exclusive(final_binding, Path(final_binding_path))
    return {"path": str(Path(final_binding_path).resolve()), "sha256": digest}


def run_registered_synthetic_chain() -> dict[str, Any]:
    contract_bytes = CONTRACT_PATH.read_bytes()
    binding_bytes = SYNTHETIC_BINDING_PATH.read_bytes()
    contract = json.loads(contract_bytes.decode("utf-8"))
    binding = json.loads(binding_bytes.decode("utf-8"))
    contract_sha = sha256(contract_bytes).hexdigest()
    input_binding_sha = sha256(binding_bytes).hexdigest()
    guard_dir = PROJECT_ROOT / "workspace" / "hkconnect_price_semantics_v2_20260919" / "zero_label_parity"
    if str(guard_dir) not in sys.path:
        sys.path.insert(0, str(guard_dir))
    from execution_guard_core import ExecutionGuard

    run_id = f"{ROUTE_ID}_SYNTHETIC_{uuid4().hex}"
    output_dir = BATCH_ROOT / "synthetic_output" / run_id
    terminal_receipt_path = output_dir / "TERMINAL_RECEIPT.json"
    registry_receipt_path = BATCH_ROOT / "receipts" / "registry_append" / f"{run_id}.json"
    registry_path = PROJECT_ROOT / "contracts" / "EXPERIMENT_REGISTRY.jsonl"
    adapter = _make_official_adapter(output_dir, registry_receipt_path)
    fit_cap = require_strict_positive_int(
        contract["budget_proposal"]["fit"]["max_calls"], "fit budget cap", maximum=1
    )
    guard = ExecutionGuard(adapter, experiment_id=EXPERIMENT_ID, max_real_fit_debits=fit_cap)
    claim = guard.claim_no_fit(
        execution_id=run_id,
        arm="BREADTH1_SYNTHETIC_IO_CHAIN",
        contract_sha256=contract_sha,
        input_binding_sha256=input_binding_sha,
    )
    try:
        duplicate = subprocess.run(
            [sys.executable, str(__file__), "--duplicate-claim-probe", run_id],
            check=False,
            capture_output=True,
            text=True,
        )
        if duplicate.returncode != 0 or json.loads(duplicate.stdout).get("duplicate_blocked") is not True:
            raise SyntheticChainError("PERSISTED_SECOND_PROCESS_DUPLICATE_ID_NOT_BLOCKED")
        code_sha = _verify_frozen_identity(contract, binding)
        metrics = load_frozen_metrics()
        chain = run_synthetic_io_chain(output_dir, metrics)
        tests = _run_registered_unit_suite()
        terminal = {
            "registry_route_id": ROUTE_ID,
            "execution_id": run_id,
            "contract_sha256": contract_sha,
            "synthetic_input_binding_sha256": input_binding_sha,
            "synthetic_io_receipt_path": chain["receipt_path"],
            "synthetic_io_receipt_sha256": chain["receipt_sha256"],
            "unit_test_summary": tests,
            "code_sha256": code_sha,
            "runtime": _verify_synthetic_runtime(
                contract.get("synthetic_test_runtime"),
                binding.get("synthetic_test_runtime"),
            ),
            "device": "CPU_RESEARCH_ONLY",
            "real_fit_budget_debit": 0,
            "real_fit_returned_count": 0,
            "real_predict_calls": 0,
            "real_truth_decode_calls": 0,
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        terminal_receipt_sha = write_json_exclusive(terminal, terminal_receipt_path)
        adapter.artifact_paths = (
            *adapter.artifact_paths,
            output_dir / "SYNTHETIC_IO_RECEIPT.json",
            terminal_receipt_path,
        )
    except BaseException as exc:
        guard.append_no_fit_terminal(claim, succeeded=False, error_type=type(exc).__name__)
        raise
    guard.append_no_fit_terminal(claim, succeeded=True)
    route_events = adapter.list_events(EXPERIMENT_ID)
    lifecycle = [event for event in route_events if event.get("execution_id") == run_id]
    if len(lifecycle) != 2 or {event.get("event_type") for event in lifecycle} != {"RUN_STARTED", "TERMINAL"}:
        raise SyntheticChainError("OFFICIAL_REGISTRY_LIFECYCLE_RECEIPT_MISMATCH")
    registry_receipt = {
        "schema": "F5_BREADTH1_REGISTRY_APPEND_RECEIPT_V1",
        "route_id": ROUTE_ID,
        "execution_id": run_id,
        "route_lifecycle_count": len(lifecycle),
        "events": [
            {
                "registry_event_id": event.get("registry_event_id"),
                "event_type": event.get("event_type"),
                "event_sha256": event.get("event_sha256"),
                "decision": event.get("decision"),
                "deterministic_metrics": event.get("deterministic_metrics"),
            }
            for event in lifecycle
        ],
        "registry_path": str(registry_path),
        "registry_bytes_after_append": registry_path.stat().st_size,
        "registry_sha256_after_append": sha256_file(registry_path),
        "terminal_receipt_sha256": terminal_receipt_sha,
        "overall_registry_inventory": "NOT_COMPUTED_BY_NARROW_ROUTE_ADAPTER",
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    registry_receipt_sha = write_json_exclusive(registry_receipt, registry_receipt_path)
    return {
        **chain,
        "unit_tests": tests,
        "execution_id": run_id,
        "terminal_receipt_sha256": terminal_receipt_sha,
        "registry_receipt_path": str(registry_receipt_path),
        "registry_receipt_sha256": registry_receipt_sha,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registered-synthetic-chain", action="store_true")
    parser.add_argument("--duplicate-claim-probe")
    parser.add_argument("--registered-real-chain", action="store_true")
    args = parser.parse_args(argv)
    if args.duplicate_claim_probe is not None or args.registered_synthetic_chain:
        parser.error("R3_STAGE1_SYNTHETIC_EXECUTION_DISABLED")
    if not args.registered_real_chain:
        parser.error("USE_REGISTERED_REAL_CHAIN_ONLY_NO_ADMISSION_ONLY_MODE")
    try:
        result = run_registered_real_chain()
    except Exception as exc:
        print(json.dumps({"status": "PREFLIGHT_REJECTED", "error_type": type(exc).__name__,
                          "error": str(exc), "retry_allowed": False}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"DIRECTION_ONLY", "NO_BREAKTHROUGH"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

