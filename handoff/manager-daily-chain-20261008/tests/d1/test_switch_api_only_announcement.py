from __future__ import annotations

import importlib.util
import ast
import json
import plistlib
import subprocess
from pathlib import Path

import pytest


HELPER_PATH = Path(__file__).parents[1] / "helpers/switch_api_only_announcement.py"
SPEC = importlib.util.spec_from_file_location("switch_api_only_announcement", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
switch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(switch)


def _raw_sha(value: bytes) -> str:
    return switch._sha(value)


def _seed_operation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path, bytes, bytes, dict[str, bool]]:
    task = tmp_path / "task"
    task.mkdir()
    active = tmp_path / "LaunchAgents" / "api.plist"
    staged = task / "staged_api.plist"
    scheduler = tmp_path / "LaunchAgents" / "scheduler.plist"
    stage_center = tmp_path / "LaunchAgents" / "stage-center-scheduler.plist"
    active.parent.mkdir()
    state = tmp_path / "manager_state"
    state.mkdir()
    api = tmp_path / "release" / "app"
    api.mkdir(parents=True)
    old_raw = plistlib.dumps({
        "Label": switch.LABEL, "KeepAlive": True, "RunAtLoad": False,
        "WorkingDirectory": "/old/release/app",
        "ProgramArguments": ["/usr/bin/env", "V35_APP_ROOT=/old/release/app",
            "V35_RELEASE_ID=old-api", "V35_RELEASE_MANIFEST_SHA256=" + "d" * 64,
            "V35_RELEASE_MANIFEST_PATH=/old/release/release-manifest.json",
            "PYTHONPATH=/old/release/app/upstreams:/old/release/app",
            "V4_MANAGER_RESEARCH_STATE_ROOT=/old/state",
            *[f"{key}={value}" for key, value in switch.SAFETY_EXPECTED.items()],
            str(switch.PINNED_PYTHON), "-B", "-m", "apps.api.v35_api.run"],
    })
    new_raw = plistlib.dumps({
        "Label": switch.LABEL, "KeepAlive": True, "RunAtLoad": False,
        "WorkingDirectory": str(api),
        "ProgramArguments": ["/usr/bin/env", f"V35_APP_ROOT={api}",
            "V35_RELEASE_ID=candidate-api-r2", "V35_RELEASE_MANIFEST_SHA256=" + "a" * 64,
            f"V35_RELEASE_MANIFEST_PATH={api.parent / 'release-manifest.json'}",
            f"PYTHONPATH={api / 'upstreams'}:{api}", f"V4_MANAGER_RESEARCH_STATE_ROOT={state}",
            "V4_MANAGER_PLAN_OWNER_BINDING_PATH=/task/disabled-binding.json",
            *[f"{key}={value}" for key, value in switch.SAFETY_EXPECTED.items()],
            str(switch.PINNED_PYTHON), "-B", "-m", "apps.api.v35_api.run"],
    })
    active.write_bytes(old_raw)
    staged.write_bytes(new_raw)
    scheduler.write_bytes(b"scheduler-plist-remains-identical")
    stage_center.write_bytes(b"stage-center-plist-remains-identical")
    monkeypatch.setattr(switch, "TASK_ROOT", task)
    monkeypatch.setattr(switch, "ACTIVE_API_PLIST", active)
    monkeypatch.setattr(switch, "ACTIVE_SCHEDULER_PLIST", scheduler)
    monkeypatch.setattr(switch, "STAGE_CENTER_SCHEDULER_PLIST", stage_center)
    monkeypatch.setattr(switch, "STAGED_API_PLIST", staged)
    monkeypatch.setattr(switch, "FORMAL_MANAGER_STATE", state)
    monkeypatch.setattr(switch, "API_ROOT", api)
    monkeypatch.setattr(switch, "EXPECTED_ACTIVE_API_PLIST_SHA256", _raw_sha(old_raw))
    monkeypatch.setattr(switch, "EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256", _raw_sha(scheduler.read_bytes()))
    monkeypatch.setattr(switch, "EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256", _raw_sha(stage_center.read_bytes()))
    monkeypatch.setattr(switch, "EXPECTED_STAGED_API_PLIST_SHA256", _raw_sha(new_raw))
    monkeypatch.setattr(switch, "EXPECTED_API_RELEASE_ID", "candidate-api-r2")
    monkeypatch.setattr(switch, "EXPECTED_API_MANIFEST_SHA256", "a" * 64)
    monkeypatch.setattr(switch, "EXPECTED_API_INVENTORY_SHA256", "b" * 64)
    monkeypatch.setattr(switch, "EXPECTED_DISABLED_BINDING_SHA256", "c" * 64)
    monkeypatch.setattr(switch, "_preflight", lambda: {"status": "READY"})
    launch_state = {"loaded": True}
    monkeypatch.setattr(switch, "_test_loaded_state", launch_state, raising=False)

    def loaded_output() -> str:
        if not launch_state["loaded"]:
            raise ValueError("API_ONLY_LAUNCH_AGENT_NOT_LOADED:test fixture")
        identity = switch._identity_from_plist(active.read_bytes())
        return "state = running\n" + "\n".join(f"{key}={value}" for key, value in identity.items())

    def fake_launchctl(*args: str) -> None:
        if args == ("bootout",):
            launch_state["loaded"] = False
        elif args == ("bootstrap",):
            launch_state["loaded"] = True

    monkeypatch.setattr(switch, "_launchctl_print", loaded_output)
    monkeypatch.setattr(switch, "_launchctl", fake_launchctl)
    monkeypatch.setattr(switch, "_wait_for_loaded", lambda *args, **kwargs: {"route": "AVAILABLE"})
    return active, staged, scheduler, old_raw, new_raw, launch_state


def test_real_staged_plist_delta_only_changes_api_release_and_disabled_binding() -> None:
    active_raw = switch.ACTIVE_API_PLIST.read_bytes()
    staged_raw = switch.STAGED_API_PLIST.read_bytes()
    result = switch._verify_plist_pair(active_raw, staged_raw)
    assert result["new_release_id"] == switch.EXPECTED_API_RELEASE_ID
    assert result["plan_binding_enabled"] is False
    assert result["plan_canary_required_for_announcement_import"] is False


def test_registered_announcement_handoff_is_pinned_and_failed_articles_stay_unassessed() -> None:
    result = switch._load_registered_announcement_handoff()
    assert result["status"] == "REGISTERED_HANDOFF_VERIFIED_READ_ONLY"
    assert result["evidence_run_id"] == switch.EXPECTED_ANNOUNCEMENT_EVIDENCE_RUN_ID
    assert result["target_trade_date"] == "20261008"
    assert result["publication_date"] == "2026-10-07"
    assert result["article_rows"] == 613
    assert result["body_complete_rows"] == 608
    assert result["body_failed_rows"] == 5
    assert result["failed_dispositions"] == "NOT_ASSESSED"
    assert result["owner_import"] == "NOT_RUN_BY_PREFLIGHT"
    assert result["external_review_authentication"] == "DECLARED_OUTPUT_BOUND_NOT_PLATFORM_AUTHENTICATED"


def test_stage_center_scheduler_pinned_sha_matches_real_preimage() -> None:
    path = switch.STAGE_CENTER_SCHEDULER_PLIST
    assert path.is_file()
    assert not path.is_symlink()
    assert len(switch.EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256) == 64
    assert switch._sha_file(path) == switch.EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256


def test_reviewed_import_route_has_no_plan_binding_or_canary_gate() -> None:
    router_path = switch.API_ROOT / "apps/api/v35_api/manager_research_router.py"
    router = ast.parse(router_path.read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(router)
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "import_announcement_analysis")
    names = {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)}
    assert "validate_registered_handoff" in names
    assert "import_announcement_analysis" in attributes
    assert "validate_binding" not in names | attributes
    assert "plan_activation_receipt" not in names | attributes


def test_plist_pair_rejects_safety_or_launch_policy_changes() -> None:
    original = plistlib.loads(switch.ACTIVE_API_PLIST.read_bytes())
    staged = plistlib.loads(switch.STAGED_API_PLIST.read_bytes())
    args = staged["ProgramArguments"]
    staged["ProgramArguments"] = ["orders_sent=true" if item == "orders_sent=false" else item for item in args]
    with pytest.raises(ValueError, match="API_ONLY_SAFETY_FLAG_MISMATCH"):
        switch._verify_plist_pair(plistlib.dumps(original), plistlib.dumps(staged))

    staged = plistlib.loads(switch.STAGED_API_PLIST.read_bytes())
    staged["KeepAlive"] = False
    with pytest.raises(ValueError, match="API_ONLY_LAUNCH_AGENT_POLICY_CHANGED"):
        switch._verify_plist_pair(plistlib.dumps(original), plistlib.dumps(staged))


def test_wrong_confirmation_fails_before_preflight_or_any_write(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def reject_if_called():
        nonlocal called
        called = True
        raise AssertionError("preflight must not run")

    monkeypatch.setattr(switch, "_preflight", reject_if_called)
    with pytest.raises(ValueError, match="EXPLICIT_API_ONLY_SWITCH_CONFIRMATION_REQUIRED"):
        switch._run_switch(confirmation="", expected_current_sha="x", expected_staged_sha="y")
    assert called is False


def test_staged_sha_drift_aborts_before_launchctl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active, staged, scheduler, old_raw, _, _ = _seed_operation(tmp_path, monkeypatch)
    staged.write_bytes(b"staged-bytes-changed-after-preflight")
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(switch, "_launchctl", lambda *args: commands.append(args))
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_PREIMAGE_CHANGED_AFTER_PREFLIGHT"):
        switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
            expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
            expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert active.read_bytes() == old_raw
    assert scheduler.read_bytes() == b"scheduler-plist-remains-identical"
    assert commands == []


def test_scheduler_drift_after_bootout_restores_api_without_overwriting_scheduler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active, staged, scheduler, old_raw, new_raw, launch_state = _seed_operation(tmp_path, monkeypatch)
    commands: list[tuple[str, ...]] = []
    original_launchctl = switch._launchctl

    def change_scheduler_after_bootout(*args: str) -> None:
        commands.append(args)
        original_launchctl(*args)
        if args == ("bootout",):
            scheduler.write_bytes(b"external-scheduler-change")

    monkeypatch.setattr(switch, "_launchctl", change_scheduler_after_bootout)
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_ABORTED_AFTER_BOOTOUT_PREIMAGE_DRIFT"):
        switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
            expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
            expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert active.read_bytes() == old_raw
    assert active.read_bytes() != new_raw
    assert scheduler.read_bytes() == b"external-scheduler-change"
    assert commands == [("bootout",), ("bootstrap",)]
    receipts = list((tmp_path / "task/writer/api_only_switch_runs").glob("*/operation_receipt.json"))
    receipt = json.loads(receipts[0].read_text())
    assert receipt["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert launch_state["loaded"] is True


def test_stage_center_drift_before_bootout_aborts_without_launchctl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active, _, scheduler, old_raw, _, launch_state = _seed_operation(tmp_path, monkeypatch)
    stage_center = switch.STAGE_CENTER_SCHEDULER_PLIST
    stage_center.write_bytes(b"external-stage-center-change")
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(switch, "_launchctl", lambda *args: commands.append(args))
    with pytest.raises(ValueError, match="STAGE_CENTER_SCHEDULER_PLIST_CHANGED_BEFORE_API_ONLY_SWITCH"):
        switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
            expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
            expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert commands == []
    assert launch_state["loaded"] is True
    assert active.read_bytes() == old_raw
    assert scheduler.read_bytes() == b"scheduler-plist-remains-identical"
    assert stage_center.read_bytes() == b"external-stage-center-change"


def test_stage_center_drift_after_bootout_restores_api_and_preserves_external_bytes(tmp_path: Path,
                                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    active, _, scheduler, old_raw, _, launch_state = _seed_operation(tmp_path, monkeypatch)
    stage_center = switch.STAGE_CENTER_SCHEDULER_PLIST
    commands: list[tuple[str, ...]] = []
    original_launchctl = switch._launchctl

    def change_stage_center_after_bootout(*args: str) -> None:
        commands.append(args)
        original_launchctl(*args)
        if args == ("bootout",):
            stage_center.write_bytes(b"external-stage-center-change")

    monkeypatch.setattr(switch, "_launchctl", change_stage_center_after_bootout)
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK"):
        switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
            expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
            expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert active.read_bytes() == old_raw
    assert scheduler.read_bytes() == b"scheduler-plist-remains-identical"
    assert stage_center.read_bytes() == b"external-stage-center-change"
    assert commands == [("bootout",), ("bootstrap",)]
    assert launch_state["loaded"] is True
    receipt_path = next((tmp_path / "task/writer/api_only_switch_runs").glob("*/operation_receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert receipt["stage_center_scheduler_guard"] == "DRIFTED_EXTERNAL_STATE"


def test_bootout_error_while_old_api_remains_loaded_is_observed_and_not_retried(tmp_path: Path,
                                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    active, _, scheduler, old_raw, _, launch_state = _seed_operation(tmp_path, monkeypatch)
    commands: list[tuple[str, ...]] = []

    def failed_bootout(*args: str) -> None:
        commands.append(args)
        raise RuntimeError("launchctl returned nonzero while old job remains loaded")

    monkeypatch.setattr(switch, "_launchctl", failed_bootout)
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK"):
        switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
            expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
            expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert commands == [("bootout",)]
    assert launch_state["loaded"] is True
    assert active.read_bytes() == old_raw
    assert scheduler.read_bytes() == b"scheduler-plist-remains-identical"
    receipt_path = next((tmp_path / "task/writer/api_only_switch_runs").glob("*/operation_receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["recovery_action"] == "OLD_API_REMAINS_LOADED"


def test_bootout_error_after_unload_bootstraps_exact_old_api_once(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    active, _, scheduler, old_raw, _, launch_state = _seed_operation(tmp_path, monkeypatch)
    commands: list[tuple[str, ...]] = []
    original_launchctl = switch._launchctl

    def unload_then_error(*args: str) -> None:
        commands.append(args)
        original_launchctl(*args)
        if args == ("bootout",):
            raise RuntimeError("launchctl returned error after unloading")

    monkeypatch.setattr(switch, "_launchctl", unload_then_error)
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK"):
        switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
            expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
            expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert commands == [("bootout",), ("bootstrap",)]
    assert launch_state["loaded"] is True
    assert active.read_bytes() == old_raw
    assert scheduler.read_bytes() == b"scheduler-plist-remains-identical"


def test_successful_bootout_command_must_be_observed_unloaded_before_replacement(tmp_path: Path,
                                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    active, staged, scheduler, old_raw, new_raw, launch_state = _seed_operation(tmp_path, monkeypatch)
    commands: list[tuple[str, ...]] = []

    def report_success_without_unloading(*args: str) -> None:
        commands.append(args)

    monkeypatch.setattr(switch, "_launchctl", report_success_without_unloading)
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK"):
        switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
            expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
            expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert commands == [("bootout",)]
    assert launch_state["loaded"] is True
    assert active.read_bytes() == old_raw
    assert active.read_bytes() != new_raw
    assert staged.read_bytes() == new_raw
    assert scheduler.read_bytes() == b"scheduler-plist-remains-identical"
    receipt_path = next((tmp_path / "task/writer/api_only_switch_runs").glob("*/operation_receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["recovery_action"] == "OLD_API_REMAINS_LOADED"


@pytest.mark.parametrize("failure_site", ["active_snapshot", "scheduler_sha", "stage_center_sha", "xattr_snapshot"])
def test_post_bootout_snapshot_io_failures_recover_old_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                           failure_site: str) -> None:
    active, _, scheduler, old_raw, _, launch_state = _seed_operation(tmp_path, monkeypatch)
    commands: list[tuple[str, ...]] = []
    original_launchctl = switch._launchctl

    def track_launchctl(*args: str) -> None:
        commands.append(args)
        original_launchctl(*args)

    monkeypatch.setattr(switch, "_launchctl", track_launchctl)

    if failure_site == "active_snapshot":
        original_read = Path.read_bytes
        read_count = {"n": 0}

        def fail_one_post_bootout_read(path: Path) -> bytes:
            if path == active:
                read_count["n"] += 1
            if path == active and read_count["n"] == 3:
                raise OSError("injected post-bootout active plist read failure")
            return original_read(path)

        monkeypatch.setattr(Path, "read_bytes", fail_one_post_bootout_read)
    elif failure_site in {"scheduler_sha", "stage_center_sha"}:
        original_sha_file = switch._sha_file
        scheduler_sha_count = {"n": 0}
        guarded_path = scheduler if failure_site == "scheduler_sha" else switch.STAGE_CENTER_SCHEDULER_PLIST

        def fail_one_post_bootout_guarded_plist_sha(path: Path) -> str:
            if path == guarded_path:
                scheduler_sha_count["n"] += 1
                failure_count = 2 if failure_site == "scheduler_sha" else 3
                if scheduler_sha_count["n"] == failure_count:
                    raise OSError("injected post-bootout guarded plist read failure")
            return original_sha_file(path)

        monkeypatch.setattr(switch, "_sha_file", fail_one_post_bootout_guarded_plist_sha)
    else:
        original_snapshot = switch._xattr_snapshot
        active_xattr_count = {"n": 0}

        def fail_one_post_bootout_xattr_snapshot(path: Path) -> dict[str, str]:
            if path == active:
                active_xattr_count["n"] += 1
                if active_xattr_count["n"] == 3:
                    raise OSError("injected post-bootout xattr snapshot failure")
            return original_snapshot(path)

        monkeypatch.setattr(switch, "_xattr_snapshot", fail_one_post_bootout_xattr_snapshot)

    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK"):
        switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
            expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
            expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert commands == [("bootout",), ("bootstrap",)]
    assert launch_state["loaded"] is True
    assert active.read_bytes() == old_raw
    assert scheduler.read_bytes() == b"scheduler-plist-remains-identical"
    assert switch.STAGE_CENTER_SCHEDULER_PLIST.read_bytes() == b"stage-center-plist-remains-identical"
    receipt_path = next((tmp_path / "task/writer/api_only_switch_runs").glob("*/operation_receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert receipt["stage_center_scheduler_guard"] == "UNCHANGED"


def test_operator_rollback_refuses_stage_center_preimage_drift_before_bootout(tmp_path: Path,
                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    active, staged, scheduler, old_raw, _, _ = _seed_operation(tmp_path, monkeypatch)
    result = switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
        expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
        expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    stage_center = switch.STAGE_CENTER_SCHEDULER_PLIST
    stage_center.write_bytes(b"external-stage-center-change")
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(switch, "_launchctl", lambda *args: commands.append(args))
    with pytest.raises(ValueError, match="API_ONLY_ROLLBACK_STAGE_CENTER_SCHEDULER_PREIMAGE_MISMATCH"):
        switch._run_rollback(receipt_path=Path(result["receipt_path"]),
            confirmation=switch.CONFIRM_ROLLBACK,
            expected_current_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert commands == []
    assert active.read_bytes() != old_raw
    assert active.read_bytes() == staged.read_bytes()
    assert scheduler.read_bytes() == b"scheduler-plist-remains-identical"
    assert stage_center.read_bytes() == b"external-stage-center-change"


def test_switch_writes_candidate_and_keeps_scheduler_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active, staged, scheduler, old_raw, new_raw, _ = _seed_operation(tmp_path, monkeypatch)
    result = switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
        expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
        expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert active.read_bytes() == new_raw
    assert scheduler.read_bytes() == b"scheduler-plist-remains-identical"
    assert Path(result["backup_path"]).read_bytes() == old_raw
    receipt_path = Path(result["receipt_path"])
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "API_ONLY_SWITCHED_ROUTE_VERIFIED"
    assert receipt["post_bootout_observation"]["state"] == "NOT_LOADED"
    assert receipt["receipt_sha256"] == switch._sha(json.dumps(
        {k: v for k, v in receipt.items() if k != "receipt_sha256"},
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def test_switch_runtime_failure_restores_exact_preimage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active, staged, scheduler, old_raw, new_raw, _ = _seed_operation(tmp_path, monkeypatch)
    attempts = 0

    def fail_candidate_then_verify_old(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("API_OPENAPI_NOT_READY")
        return {"runtime": "old"}

    monkeypatch.setattr(switch, "_wait_for_loaded", fail_candidate_then_verify_old)
    monkeypatch.setattr(switch, "_job_is_loaded", lambda: True)
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK"):
        switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
            expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
            expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert active.read_bytes() == old_raw
    assert scheduler.read_bytes() == b"scheduler-plist-remains-identical"
    receipts = list((tmp_path / "task/writer/api_only_switch_runs").glob("*/operation_receipt.json"))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text())["status"] == "ROLLED_BACK_TO_PREIMAGE"


def test_operator_rollback_restores_recorded_preimage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active, staged, scheduler, old_raw, _, _ = _seed_operation(tmp_path, monkeypatch)
    result = switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
        expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
        expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    outcome = switch._run_rollback(receipt_path=Path(result["receipt_path"]),
        confirmation=switch.CONFIRM_ROLLBACK,
        expected_current_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert outcome["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert active.read_bytes() == old_raw
    assert scheduler.read_bytes() == b"scheduler-plist-remains-identical"


def test_atomic_replace_preserves_xattrs_and_mode(tmp_path: Path) -> None:
    xattr = Path("/usr/bin/xattr")
    if not xattr.is_file():
        pytest.skip("xattr utility is unavailable")
    source = tmp_path / "source.plist"
    destination = tmp_path / "destination.plist"
    source.write_bytes(b"source-bytes")
    destination.write_bytes(b"old-destination")
    source.chmod(0o640)
    created = subprocess.run([str(xattr), "-wx", "com.example.test", "0102", str(source)],
                             capture_output=True, text=True)
    if created.returncode != 0:
        pytest.skip("test filesystem does not support xattrs")
    switch._atomic_replace_bytes(destination, b"new-destination", source)
    assert destination.read_bytes() == b"new-destination"
    assert destination.stat().st_mode & 0o777 == 0o644
    assert switch._xattr_snapshot(destination) == switch._xattr_snapshot(source)


def test_rollback_rejects_tampered_receipt_before_launchctl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active, staged, scheduler, old_raw, _, _ = _seed_operation(tmp_path, monkeypatch)
    result = switch._run_switch(confirmation=switch.CONFIRM_SWITCH,
        expected_current_sha=switch.EXPECTED_ACTIVE_API_PLIST_SHA256,
        expected_staged_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    receipt_path = Path(result["receipt_path"])
    receipt = json.loads(receipt_path.read_text())
    receipt["candidate_release_id"] = "other"
    receipt_path.write_text(json.dumps(receipt))
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(switch, "_launchctl", lambda *args: commands.append(args))
    with pytest.raises(ValueError, match="API_ONLY_ROLLBACK_RECEIPT_SHA_MISMATCH"):
        switch._run_rollback(receipt_path=receipt_path, confirmation=switch.CONFIRM_ROLLBACK,
            expected_current_sha=switch.EXPECTED_STAGED_API_PLIST_SHA256)
    assert commands == []
    assert active.read_bytes() != old_raw
    assert scheduler.read_bytes() == b"scheduler-plist-remains-identical"
