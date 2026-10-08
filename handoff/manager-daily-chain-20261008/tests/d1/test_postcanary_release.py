from __future__ import annotations

import hashlib
import importlib.util
import json
import plistlib
from pathlib import Path

import pytest


TASK = Path(__file__).resolve().parents[1]
SCRIPT = TASK / "prepare_postcanary_release.py"


def _module():
    spec = importlib.util.spec_from_file_location("d1_postcanary_release", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _successful_canary(module, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    target = "20260925"
    run_id = "a" * 32
    product_sha = "b" * 64
    source_inventory = {"ops/run_manager_announcement_cycle.py": "c" * 64}
    source_inventory_sha = module._canonical_sha(source_inventory)
    owner = "ManagerResearchJobService.refresh_workspace_plan"
    run_root = state / "workspace_plan_runs" / target
    plan_root = state / "workspace_plans" / target
    run_root.mkdir(parents=True)
    plan_root.mkdir(parents=True)
    run_latest = {"run_id": run_id, "state": "PARTIAL"}
    plan_latest = {"run_id": run_id, "sha256": product_sha,
                   "execution_kind": "MANUAL_REFRESH", "owner": owner}
    for root, latest in ((run_root, run_latest), (plan_root, plan_latest)):
        raw = json.dumps(latest, sort_keys=True).encode()
        (root / "latest.json").write_bytes(raw)
        (root / f"{run_id}.json").write_bytes(raw)
    disabled = {"files": source_inventory}
    canary = {
        "status": "PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING",
        "scope": "HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK",
        "app_root": str(module.API_ROOT),
        "candidate_binding_app_root": str(module.API_ROOT),
        "owner_execution_app_root": str(module.API_ROOT),
        "manager_state_root": str(state),
        "candidate_release_id": "manager-daily-chain-20261008-r2-api",
        "candidate_release_manifest_path": str(module.API_RELEASE_ROOT / "release-manifest.json"),
        "candidate_release_manifest_sha256": module.EXPECTED_API_MANIFEST_SHA256,
        "candidate_application_inventory_sha256": module.EXPECTED_API_INVENTORY_SHA256,
        "candidate_manager_source_inventory_sha256": source_inventory_sha,
        "plan_material_refresh_only": True,
        "announcement_collection_enabled": False,
        "announcement_network_requests": 0,
        "hook_executed": False,
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "formal_recommendation_count": 0,
        "execution_kind": "MANUAL_REFRESH",
        "owner": owner,
        "owner_attempt_state": "PARTIAL",
        "target_trade_date": target,
        "run_id": run_id,
        "product_sha256": product_sha,
        "input_identity": "d" * 64,
        "owner_evidence": {},
        **module.SAFETY,
        "state_preimage": {
            "target_preexisted": False,
            "protected_dates_sha256": module._protected_hashes(state),
        },
    }
    canary_path = tmp_path / "plan-canary.json"
    canary_path.write_text(json.dumps(canary, sort_keys=True), encoding="utf-8")
    canary_sha = _sha(canary_path.read_bytes())
    operation = {
        "status": canary["status"],
        "activation_status": "NOT_ACTIVATED",
        "launchctl_called": False,
        "canary_path": str(canary_path),
        "canary_sha256": canary_sha,
        "api_app_root": str(module.API_ROOT),
        "manager_state_root": str(state),
        "candidate_release_manifest_sha256": module.EXPECTED_API_MANIFEST_SHA256,
        "application_inventory_sha256": module.EXPECTED_API_INVENTORY_SHA256,
        "manager_source_inventory_sha256": source_inventory_sha,
        "target_trade_date": target,
        "run_id": run_id,
        "product_sha256": product_sha,
        "input_identity": canary["input_identity"],
        "owner_attempt_state": "PARTIAL",
    }
    operation_path = tmp_path / "operation-receipt.json"
    operation_path.write_text(json.dumps(operation, sort_keys=True), encoding="utf-8")
    module.FORMAL_MANAGER_STATE = state
    module.CANARY_PATH = canary_path
    module.CANARY_OPERATION_RECEIPT = operation_path
    return disabled, canary, operation, canary_sha


def test_missing_canary_dry_run_is_blocked_without_writes(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "CANARY_PATH", tmp_path / "missing-canary.json")
    monkeypatch.setattr(module, "CANARY_OPERATION_RECEIPT", tmp_path / "missing-operation.json")
    monkeypatch.setattr(module, "FORMAL_MANAGER_STATE", tmp_path / "formal-state")
    monkeypatch.setattr(module, "_check_release_and_disabled_inputs",
                        lambda: ({}, {"python": str(module.EXACT_PYTHON)}, {"api": {}, "scheduler": {}}))
    monkeypatch.setattr(module, "_check_live_preimages", lambda _stage: {})
    monkeypatch.setattr(module, "_build_plists", lambda *_a, **_kw: (
        {"ProgramArguments": ["/usr/bin/env", "V4_MANAGER_PLAN_OWNER_BINDING_PATH=/tmp/pending"]},
        {"EnvironmentVariables": {"V4_MANAGER_PLAN_OWNER_BINDING_PATH": "/tmp/pending"}},
    ))
    result = module.dry_run()
    assert result["status"] == "BLOCKED_FRESH_CANARY_REQUIRED"
    assert result["launchctl_called"] is False
    assert result["live_files_written"] is False
    assert list(tmp_path.iterdir()) == []


def test_real_staged_r2_dry_run_uses_api_binding_python_and_legacy_renderer(tmp_path, monkeypatch):
    module = _module()
    missing_canary = tmp_path / "no-canary.json"
    missing_operation = tmp_path / "no-operation.json"
    monkeypatch.setattr(module, "CANARY_PATH", missing_canary)
    monkeypatch.setattr(module, "CANARY_OPERATION_RECEIPT", missing_operation)

    # This exercises the actual immutable R2 roots, staged disabled binding,
    # both staged plists, saved/live plist preimages, and the SHA-pinned legacy
    # API-only renderer. Only the absent canary path is controlled by the test.
    result = module.dry_run()
    assert result["status"] == "BLOCKED_FRESH_CANARY_REQUIRED"
    assert result["launchctl_called"] is False
    assert result["live_files_written"] is False
    inputs = result["validated_inputs"]
    assert inputs["api_release_manifest_sha256"] == module.EXPECTED_API_MANIFEST_SHA256
    assert inputs["disabled_binding_sha256"] == module.EXPECTED_DISABLED_BINDING_SHA256
    assert inputs["staged_api_plist_sha256"] == module.EXPECTED_DISABLED_API_PLIST_SHA256
    assert inputs["staged_scheduler_plist_sha256"] == module.EXPECTED_DISABLED_SCHEDULER_PLIST_SHA256
    assert inputs["api_execution_python"] == inputs["stager_python"]
    assert inputs["same_root_api_renderer"]["sha256"] == module.EXPECTED_SAFE_CUTOVER_BACKEND_SHA256
    assert inputs["same_root_api_renderer"]["api_binding_path_preview"].endswith(
        "postcanary/PENDING/manager-plan-binding-c1.enabled.json")
    assert inputs["live_plist_preimages"]["api"]["sha256"] == module.EXPECTED_ACTIVE_API_PLIST_SHA256
    assert inputs["live_plist_preimages"]["scheduler"]["sha256"] == module.EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256
    assert not missing_canary.exists() and not missing_operation.exists()


def test_canary_pair_binds_exact_r2_release_state_and_expected_sha(tmp_path, monkeypatch):
    module = _module()
    disabled, _canary, _operation, canary_sha = _successful_canary(module, tmp_path)
    operation, _raw, actual_sha = module._load_fresh_canary(canary_sha, disabled)
    assert operation["status"] == "PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING"
    assert actual_sha == canary_sha
    with pytest.raises(ValueError, match="POSTCANARY_EXPECTED_CANARY_SHA_MISMATCH"):
        module._load_fresh_canary("f" * 64, disabled)


@pytest.mark.parametrize("mutation,expected", [
    ("wrong_release", "POSTCANARY_CANARY_RELEASE_OR_POLICY_MISMATCH"),
    ("wrong_state", "POSTCANARY_CANARY_RELEASE_OR_POLICY_MISMATCH"),
    ("protected_drift", "POSTCANARY_PROTECTED_STATE_PREIMAGE_MISMATCH"),
    ("owner_store_drift", "POSTCANARY_OWNER_STORE_WRITE_SET_CHANGED"),
])
def test_canary_and_formal_state_must_still_match(tmp_path, mutation, expected):
    module = _module()
    disabled, canary, operation, canary_sha = _successful_canary(module, tmp_path)
    if mutation == "wrong_release":
        canary["candidate_release_manifest_sha256"] = "f" * 64
    elif mutation == "wrong_state":
        canary["manager_state_root"] = str(tmp_path / "other-state")
    elif mutation == "protected_drift":
        protected = module.FORMAL_MANAGER_STATE / "workspace_plans/20261007"
        protected.mkdir(parents=True)
        (protected / "latest.json").write_text("drift", encoding="utf-8")
    elif mutation == "owner_store_drift":
        extra = module.FORMAL_MANAGER_STATE / "workspace_plans/20260925/extra.json"
        extra.write_text("{}", encoding="utf-8")
    if mutation in {"wrong_release", "wrong_state"}:
        module.CANARY_PATH.write_text(json.dumps(canary, sort_keys=True), encoding="utf-8")
        operation["canary_sha256"] = _sha(module.CANARY_PATH.read_bytes())
        module.CANARY_OPERATION_RECEIPT.write_text(json.dumps(operation, sort_keys=True), encoding="utf-8")
        canary_sha = operation["canary_sha256"]
    with pytest.raises(ValueError, match=expected):
        module._load_fresh_canary(canary_sha, disabled)


def test_enabled_binding_is_plan_only_and_carries_canary_sha(tmp_path):
    module = _module()
    disabled = {
        "enabled": False, "plan_material_refresh_only": False,
        "announcement_collection_enabled": False,
        "RESEARCH_ONLY": True,
        "research_only": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
    }
    path = tmp_path / "plan-canary.json"
    binding = module._build_enabled_binding(disabled, canary_path=path, canary_sha256="a" * 64)
    assert binding["enabled"] is True
    assert binding["plan_material_refresh_only"] is True
    assert binding["announcement_collection_enabled"] is False
    assert binding["plan_activation_receipt"] == {"path": str(path), "sha256": "a" * 64}
    assert binding["plan_material_refresh"]["status"] == "PROPOSAL_ONLY"
    assert binding["production_allowed"] is False
    assert binding["buy_gate_updated"] is False
    assert binding["orders_sent"] is False


def test_live_plist_preimages_are_compared_before_any_candidate_stage(tmp_path, monkeypatch):
    module = _module()
    state = tmp_path / "manager-state"
    state.mkdir()
    api_root = tmp_path / "active-api"
    scheduler_root = tmp_path / "active-scheduler"
    api_manifest = tmp_path / "api-manifest.json"
    scheduler_manifest = tmp_path / "scheduler-manifest.json"
    api_manifest.write_text("api", encoding="utf-8")
    scheduler_manifest.write_text("sched", encoding="utf-8")
    api_sha, scheduler_sha = _sha(api_manifest.read_bytes()), _sha(scheduler_manifest.read_bytes())
    api_payload = {"ProgramArguments": ["/usr/bin/env", f"V35_APP_ROOT={api_root}",
        f"V4_MANAGER_RESEARCH_STATE_ROOT={state}", f"V35_RELEASE_MANIFEST_PATH={api_manifest}",
        f"V35_RELEASE_MANIFEST_SHA256={api_sha}", "/usr/bin/python"]}
    scheduler_payload = {"ProgramArguments": ["/bin/bash", "scheduler.sh"],
        "EnvironmentVariables": {"V35_APP_ROOT": str(scheduler_root),
            "V4_MANAGER_RESEARCH_STATE_ROOT": str(state),
            "V35_RELEASE_MANIFEST_PATH": str(scheduler_manifest),
            "V35_RELEASE_MANIFEST_SHA256": scheduler_sha}}
    api_raw = plistlib.dumps(api_payload)
    scheduler_raw = plistlib.dumps(scheduler_payload)
    live_api, live_scheduler = tmp_path / "active-api.plist", tmp_path / "active-scheduler.plist"
    saved_api, saved_scheduler = tmp_path / "saved-api.plist", tmp_path / "saved-scheduler.plist"
    live_api.write_bytes(api_raw); saved_api.write_bytes(api_raw)
    live_scheduler.write_bytes(scheduler_raw); saved_scheduler.write_bytes(scheduler_raw)
    monkeypatch.setattr(module, "FORMAL_MANAGER_STATE", state)
    monkeypatch.setattr(module, "API_PLIST", live_api)
    monkeypatch.setattr(module, "SCHEDULER_PLIST", live_scheduler)
    monkeypatch.setattr(module, "PREIMAGE_ROOT", tmp_path)
    monkeypatch.setattr(module, "ACTIVE_API_ROOT", api_root)
    monkeypatch.setattr(module, "ACTIVE_SCHEDULER_ROOT", scheduler_root)
    monkeypatch.setattr(module, "EXPECTED_ACTIVE_API_PLIST_SHA256", _sha(api_raw))
    monkeypatch.setattr(module, "EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256", _sha(scheduler_raw))
    stage = {"source_api_plist": {"path": str(live_api), "sha256": _sha(api_raw)},
        "source_scheduler_plist": {"path": str(live_scheduler), "sha256": _sha(scheduler_raw)}}
    monkeypatch.setattr(module, "PREIMAGE_ROOT", tmp_path)
    (tmp_path / "active-api-only.plist").write_bytes(api_raw)
    (tmp_path / "active-scheduler.plist").write_bytes(scheduler_raw)
    result = module._check_live_preimages(stage)
    assert result["api"]["preimage_sha256"] == _sha(api_raw)
    live_api.write_bytes(api_raw + b"stale")
    with pytest.raises(ValueError, match="POSTCANARY_LIVE_PLIST_PREIMAGE_MISMATCH:api"):
        module._check_live_preimages(stage)


def test_plist_pins_name_same_enabled_binding_and_scheduler_canary_sha(tmp_path, monkeypatch):
    module = _module()
    api_root = tmp_path / "api"
    scheduler_root = tmp_path / "scheduler"
    (api_root / "ops").mkdir(parents=True)
    (api_root / "ops/run_manager_announcement_cycle.py").write_text("cycle\n", encoding="utf-8")
    python = tmp_path / "python"
    python.write_text("python", encoding="utf-8")
    api_binding, scheduler_binding = tmp_path / "disabled.json", tmp_path / "disabled.json"
    monkeypatch.setattr(module, "API_ROOT", api_root)
    monkeypatch.setattr(module, "SCHEDULER_ROOT", scheduler_root)
    monkeypatch.setattr(module, "FORMAL_MANAGER_STATE", tmp_path / "state")
    monkeypatch.setattr(module, "DISABLED_BINDING", api_binding)
    monkeypatch.setattr(module, "EXACT_PYTHON", python)
    monkeypatch.setattr(module, "EXPECTED_API_MANIFEST_SHA256", "1" * 64)
    monkeypatch.setattr(module, "EXPECTED_SCHEDULER_MANIFEST_SHA256", "2" * 64)
    monkeypatch.setattr(module, "_legacy_api_rewrite", lambda value: value)
    owner_path = tmp_path / "enabled.json"
    api = {"ProgramArguments": ["/usr/bin/env", f"V35_APP_ROOT={api_root}",
        f"V4_MANAGER_RESEARCH_STATE_ROOT={module.FORMAL_MANAGER_STATE}",
        f"V35_RELEASE_MANIFEST_SHA256={module.EXPECTED_API_MANIFEST_SHA256}",
        f"V4_MANAGER_PLAN_OWNER_BINDING_PATH={api_binding}", "/usr/bin/python"]}
    scheduler = {"EnvironmentVariables": {
        "V35_APP_ROOT": str(scheduler_root),
        "V4_MANAGER_RESEARCH_STATE_ROOT": str(module.FORMAL_MANAGER_STATE),
        "V35_RELEASE_MANIFEST_SHA256": module.EXPECTED_SCHEDULER_MANIFEST_SHA256,
        "V35_RELEASE_ID": "manager-daily-chain-20261008-r2-scheduler",
        "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(scheduler_binding),
        "V4_MANAGER_ANNOUNCEMENT_PYTHON": str(python),
        "V4_MANAGER_ANNOUNCEMENT_PYTHON_SHA256": _sha(python.read_bytes()),
        "production_allowed": "false", "buy_gate_updated": "false", "orders_sent": "false"}}
    api_out, scheduler_out = module._build_plists({"api": api, "scheduler": scheduler},
        binding_path=owner_path, canary_sha256="e" * 64)
    assert module._assignments(api_out)["V4_MANAGER_PLAN_OWNER_BINDING_PATH"] == str(owner_path)
    assert scheduler_out["EnvironmentVariables"]["V4_MANAGER_PLAN_OWNER_BINDING_PATH"] == str(owner_path)
    assert scheduler_out["EnvironmentVariables"]["V4_MANAGER_ANNOUNCEMENT_BINDING"] == str(owner_path)
    assert scheduler_out["EnvironmentVariables"]["V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256"] == "e" * 64
