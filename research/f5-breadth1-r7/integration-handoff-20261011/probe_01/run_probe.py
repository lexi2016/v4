#!/usr/bin/env python3
"""Read-only R7 resume control probe; emits one JSON result to stdout."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
GUARD = ROOT / "workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity"
SRC = ROOT / "workspace/f5_breadth1_r3_frozen_input_20261011/src"
REG = ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/receipts/r7_recovery_05/registration"
CONTRACT = REG / "R7_RESUME_READONLY_PREFLIGHT_CONTRACT.json"
BINDING = REG / "R7_RESUME_READONLY_PREFLIGHT_BINDING.json"
AUTH = ROOT / "research/hk_burst_f5/batches/breadth1_r3_frozen_input_20261011/receipts/r7_recovery_05/control_resume/R7_RECOVERY_05_RESUME_AUTHORIZATION_V2.json"
ROUTE = "F5_PLUS64_BREADTH1_R7_ONE_PROCESS_LOCAL_VALIDATION_20261011"
EXECUTION = ROUTE + "_R7_RESUME_PREFLIGHT_READONLY_01"
ARM = "LOCAL_R7_RESUME_PREFLIGHT_READONLY_ONLY"
SAFETY = {
    "research_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    if (binding.get("contract_sha256") != sha(CONTRACT)
            or binding.get("probe_path") != str(Path(__file__).resolve())
            or binding.get("probe_sha256") != sha(Path(__file__))):
        raise RuntimeError("PREFLIGHT_SELF_IDENTITY_MISMATCH")
    source_map = {str(path.relative_to(ROOT)): sha(path) for path in sorted(SRC.glob("*.py"))}
    if source_map != binding.get("source_sha256"):
        raise RuntimeError("PREFLIGHT_R7_SOURCE_MAP_MISMATCH")
    for key, item in binding.get("r7_control_sha256", {}).items():
        control = Path(item.get("path", ""))
        if not control.is_file() or control.is_symlink() or sha(control) != item.get("sha256"):
            raise RuntimeError(f"PREFLIGHT_CONTROL_SHA_MISMATCH:{key}")
    for key, item in binding.get("official_dependency_sha256", {}).items():
        dependency = Path(item.get("path", ""))
        if not dependency.is_file() or dependency.is_symlink() or sha(dependency) != item.get("sha256"):
            raise RuntimeError(f"PREFLIGHT_OFFICIAL_DEPENDENCY_SHA_MISMATCH:{key}")
    if str(GUARD) not in sys.path:
        sys.path.insert(0, str(GUARD))
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    runner = load_module(SRC / "run_f5_breadth1.py", "r7_readonly_resume_runner")
    budget = sys.modules.get("f5_breadth1_budget")
    if budget is None:
        import f5_breadth1_budget as budget

    paths = runner._r7_chain_paths()
    original_failure_dir = budget.PANEL_HEADER_RECOVERY_OUTPUT_PATH
    prior_terminal = budget.PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_PATH
    if paths["resume_run"].exists() or paths["resume_run"].is_symlink():
        raise RuntimeError("RESUME_OUTPUT_PRESENT_BEFORE_PROBE")
    if not original_failure_dir.is_dir() or original_failure_dir.is_symlink():
        raise RuntimeError("PRESERVED_FAILURE_DIRECTORY_MISSING_OR_SYMLINK")
    prior_terminal_sha = sha(prior_terminal)
    if prior_terminal_sha != budget.PANEL_HEADER_RECOVERY_PRIOR_FAILURE_TERMINAL_SHA256:
        raise RuntimeError("PRESERVED_FAILURE_TERMINAL_SHA_MISMATCH")

    preflight = runner._preflight_registered_r7_resume(AUTH, sha(AUTH))
    official = preflight["official"]
    events = list(official.list_events(runner.EXPERIMENT_ID))
    r7_events = [
        event for event in events
        if event.get("execution_id") == budget.PANEL_HEADER_RECOVERY_EXECUTION_ID
        and event.get("budget_action_key") == budget.PANEL_HEADER_RECOVERY_ACTION_KEY
    ]
    starts = [event for event in r7_events if event.get("event_type") == "RUN_STARTED"]
    terminals = [event for event in r7_events if event.get("event_type") == "TERMINAL"]
    fit_keys = {
        f"{runner.ROUTE_ID}:{runner.CANDIDATE_ID}:{action}"
        for action in ("fit", "predict", "truth_decode")
    }
    if len(r7_events) != 2 or len(starts) != 1 or len(terminals) != 1:
        raise RuntimeError("ORIGINAL_R7_ADMISSION_LIFECYCLE_NOT_EXACT")
    if any(event.get("budget_action_key") in fit_keys for event in events):
        raise RuntimeError("R7_FIT_PREDICT_OR_TRUTH_ACTION_ALREADY_STARTED")
    if preflight.get("resume_release") is None:
        raise RuntimeError("R7_RESUME_RELEASE_NOT_VERIFIED")
    if sha(prior_terminal) != prior_terminal_sha:
        raise RuntimeError("PRESERVED_FAILURE_TERMINAL_CHANGED_DURING_PROBE")

    original_paths = runner._r7_chain_paths
    duplicate_refusal = None

    def duplicate_path_view():
        duplicate = dict(original_paths())
        duplicate["resume_run"] = original_failure_dir
        return duplicate

    runner._r7_chain_paths = duplicate_path_view
    try:
        runner._preflight_registered_r7_resume(AUTH, sha(AUTH))
    except runner.SyntheticChainError as exc:
        duplicate_refusal = str(exc)
    finally:
        runner._r7_chain_paths = original_paths
    if duplicate_refusal != "R7_RESUME_FIXED_PATH_OR_NO_OVERWRITE_GATE_FAILED":
        raise RuntimeError("DUPLICATE_RESUME_PATH_REFUSAL_NOT_EXACT")
    if paths["resume_run"].exists() or paths["resume_run"].is_symlink():
        raise RuntimeError("PROBE_CREATED_RESUME_OUTPUT")
    if sha(prior_terminal) != prior_terminal_sha:
        raise RuntimeError("PRESERVED_FAILURE_TERMINAL_CHANGED_AFTER_PROBE")

    result = {
        "schema": "BREADTH1_R7_RESUME_READONLY_PREFLIGHT_PROBE_V1",
        "status": "PASS_READONLY_RESUME_PREFLIGHT_AND_DUPLICATE_REFUSAL",
        "route_id": ROUTE,
        "execution_id": EXECUTION,
        "resume_control_graph": "PASS",
        "verified_resume_release_sha256": preflight["resume_release"].expected_sha256,
        "verified_resume_authorization_sha256": preflight["authorization_sha256"],
        "original_r7_start_event_sha256": starts[0].get("event_sha256"),
        "original_r7_failure_terminal_event_sha256": terminals[0].get("event_sha256"),
        "original_r7_logical_admission_debit": starts[0].get("budget_action_debit"),
        "duplicate_path_refusal": duplicate_refusal,
        "preserved_prior_failure_terminal_path": str(prior_terminal.resolve()),
        "preserved_prior_failure_terminal_sha256": prior_terminal_sha,
        "resume_output_absent_after_probe": True,
        "target_data_file_reads": 0,
        "fit_calls": 0,
        "predict_calls": 0,
        "model_load_calls": 0,
        "truth_reads": 0,
        "registry_writes_by_probe": 0,
        **SAFETY,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except BaseException as exc:
        result = {
            "schema": "BREADTH1_R7_RESUME_READONLY_PREFLIGHT_PROBE_V1",
            "status": "FAIL_READONLY_RESUME_PREFLIGHT",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "target_data_file_reads": 0,
            "fit_calls": 0,
            "predict_calls": 0,
            "model_load_calls": 0,
            "truth_reads": 0,
            "registry_writes_by_probe": 0,
            **SAFETY,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        code = 1
    raise SystemExit(code)
