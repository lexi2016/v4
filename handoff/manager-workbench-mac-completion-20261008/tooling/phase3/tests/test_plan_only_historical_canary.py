from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008/phase3")
TOOL_PATH = TASK_ROOT / "tools/run_plan_only_historical_canary.py"
SPEC = importlib.util.spec_from_file_location("plan_only_historical_canary", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
canary = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = canary
SPEC.loader.exec_module(canary)


def test_dry_run_reports_exact_candidate_binding_and_absent_target_preimage() -> None:
    result = canary.dry_run()

    assert result["status"] == "DRY_RUN_NO_HTTP_NO_WRITE"
    assert result["release_id"] == "manager-workbench-r1-mac-20261008-api-r2"
    assert result["application_inventory_entries"] == 1016
    assert result["disabled_plan_owner_binding"]["file_count"] == 357
    assert result["release_manifest_sha256"] == "2cc1447a740195c4f50299330d845635ddf762c45eb59586436a527e4f8b75a8"
    assert result["application_inventory_sha256"] == "c371c633437e366d28549a94be35741e8d137d2a0836155695c9d125bb427f05"
    assert result["disabled_plan_owner_binding"]["path"] == str(canary.BINDING_PATH)
    assert result["staged_api_plist"]["path"] == str(canary.PLIST_PATH)
    assert result["disabled_plan_owner_binding"]["enabled"] is False
    assert result["disabled_plan_owner_binding"]["announcement_collection_enabled"] is False
    assert result["disabled_plan_owner_binding"]["plan_material_refresh_only"] is False
    assert result["interpreter"]["configured_path"].endswith("/bin/python")
    assert result["interpreter"]["process_executable"] == result["interpreter"]["configured_path"]
    assert result["target_preimage"]["target_date_paths_absent"] is True
    assert result["target_preimage"]["target_state_before"]["directories"] == {
        "workspace_plan_runs/20260925": None,
        "workspace_plans/20260925": None,
    }
    assert result["target_preimage"]["target_state_before"]["lock"] is None
    assert result["target_preimage"]["overwrite_policy"] == "REFUSE_IF_ANY_TARGET_DATE_DIRECTORY_OR_LOCK_EXISTS"
    assert result["target_preimage"]["post_post_failure_policy"] == (
        "PRESERVE_OWNER_STATE_STOP_AND_REVIEW_NO_AUTOMATED_RETRY_OR_ROLLBACK"
    )
    assert result["target_preimage"]["absent_paths"] == [
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/workspace_plan_runs/20260925",
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/workspace_plans/20260925",
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/.locks/20260925-workspace-plan-refresh.mutex",
    ]
    assert result["http_calls"] == []
    assert result["launchctl_called"] is False
    assert result["other_formal_state_written"] is False
    assert result["safety"] == canary.SAFETY


def test_dry_run_stops_before_preimage_read_when_python_identity_fails() -> None:
    with patch.object(canary, "_load_release_and_runtime", return_value=({}, {})), \
            patch.object(canary, "_validate_execution_python", side_effect=ValueError("PYTHON_PIN_MISMATCH")), \
            patch.object(canary, "_check_target_preimage") as check_preimage:
        with pytest.raises(ValueError, match="PYTHON_PIN_MISMATCH"):
            canary.dry_run()

    check_preimage.assert_not_called()


def test_default_cli_uses_dry_run_and_never_selects_execute(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(canary, "dry_run", return_value={"status": "DRY_RUN_NO_HTTP_NO_WRITE"}), \
            patch.object(canary, "execute", side_effect=AssertionError("execute must require --execute")) as execute:
        assert canary.main([]) == 0

    execute.assert_not_called()
    assert json.loads(capsys.readouterr().out)["status"] == "DRY_RUN_NO_HTTP_NO_WRITE"


def test_broken_target_directory_symlink_cannot_pass_absent_preimage(tmp_path: Path) -> None:
    state_root = tmp_path / "formal-state"
    run_parent = state_root / "workspace_plan_runs"
    plan_parent = state_root / "workspace_plans"
    lock_parent = state_root / ".locks"
    for parent in (run_parent, plan_parent, lock_parent):
        parent.mkdir(parents=True)
    (run_parent / canary.TARGET).symlink_to(tmp_path / "missing-target")

    with patch.object(canary, "FORMAL_MANAGER_STATE", state_root):
        with pytest.raises(ValueError, match="D1_TARGET_STATE_DIRECTORY_SYMLINK"):
            canary._check_target_preimage()


def test_post_post_failure_receipt_preserves_partial_owner_state_and_blocks_retry(tmp_path: Path) -> None:
    state_root = tmp_path / "formal-state"
    run_parent = state_root / "workspace_plan_runs"
    plan_parent = state_root / "workspace_plans"
    lock_parent = state_root / ".locks"
    for parent in (run_parent, plan_parent, lock_parent):
        parent.mkdir(parents=True)
    identity = {
        "manifest_sha256": "a" * 64,
        "inventory_sha256": "b" * 64,
        "source_inventory_sha256": "c" * 64,
        "binding": {},
    }
    output_root = tmp_path / "execution-01"

    async def owner_writes_then_fails(_identity, _environment, _protected, execution_state=None):
        assert execution_state is not None
        run_root = run_parent / canary.TARGET
        plan_root = plan_parent / canary.TARGET
        run_root.mkdir()
        plan_root.mkdir()
        for path in (run_root / "latest.json", run_root / "run-id.json",
                     plan_root / "latest.json", plan_root / "run-id.json"):
            path.write_text('{"simulated_owner_state":true}\n', encoding="utf-8")
        execution_state.update(stage="GET_RESPONSE_RECEIVED", post_started=True,
                               post_response_received=True, get_started=True,
                               get_response_received=True)
        raise ValueError("D1_CANARY_OWNER_READBACK_MISMATCH")

    with patch.object(canary, "FORMAL_MANAGER_STATE", state_root), \
            patch.object(canary, "OUTPUT_ROOT", output_root), \
            patch.object(canary, "_load_release_and_runtime", return_value=(identity, {})), \
            patch.object(canary, "_validate_execution_python"), \
            patch.object(canary, "_execute_owner_canary", side_effect=owner_writes_then_fails):
        with pytest.raises(ValueError, match="OWNER_READBACK_MISMATCH"):
            canary.execute()

        failure_path = output_root / "failure-receipt.json"
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        assert failure["execution_state"]["post_started"] is True
        assert failure["execution_state"]["stage"] == "GET_RESPONSE_RECEIVED"
        assert failure["target_state_changed"] is True
        assert failure["protected_dates_unchanged"] is True
        assert failure["post_post_failure_recovery"]["automatic_rollback"] == "NOT_PERFORMED"
        assert failure["post_post_failure_recovery"]["automatic_retry"] == "PROHIBITED"
        assert failure["owner_target_state_after_failure"]["directories"]["workspace_plans/20260925"] == {
            "latest.json": canary._sha(b'{"simulated_owner_state":true}\n'),
            "run-id.json": canary._sha(b'{"simulated_owner_state":true}\n'),
        }

        retry_output_root = tmp_path / "execution-02"
        with patch.object(canary, "OUTPUT_ROOT", retry_output_root):
            with pytest.raises(FileExistsError, match="D1_TARGET_STATE_PREEXISTS"):
                canary.execute()
        assert not retry_output_root.exists()
