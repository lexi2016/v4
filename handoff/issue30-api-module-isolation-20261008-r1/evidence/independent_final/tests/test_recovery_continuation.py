"""Recovery continuation contracts using synthetic files and simulated launchd.

The original 21-cutover fixture supplies the real pinned integration core and
real package/plist/receipt checks. Service, HTTP and historical product reads
remain the fixture's explicit simulations; these are not Mac release tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import test_actual_api_cutover as actual_helpers


@pytest.fixture
def setup_actual():
    harness = actual_helpers.ActualCutoverTests("test_failed_bootstrap_recovers_using_same_lock_and_exact_base")
    harness.setUp()
    try:
        yield harness, harness.integrated_fixture()
    finally:
        harness.doCleanups()


class SyntheticInterruption(BaseException):
    """Model a process interruption after durable PREPARED, before bootout."""


def _make_prepared(harness, fixture, monkeypatch):
    m, plan = harness.m, fixture["plan"]
    preflight = m._preflight
    calls = 0

    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SyntheticInterruption("SYNTHETIC_PROCESS_INTERRUPTION")
        return preflight(*args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(m, "_preflight", interrupted)
        with pytest.raises(SyntheticInterruption):
            m._run_switch(plan, confirmation=m.CONFIRM_SWITCH,
                          expected_current_sha=actual_helpers.digest(fixture["original"]),
                          expected_staged_sha=plan["target"]["staged_api_plist_sha256"])
    paths = list((m.EVIDENCE_ROOT / "api_only_switch_runs").glob("*/operation_receipt.json"))
    assert len(paths) == 1
    assert json.loads(paths[0].read_text())["status"] == "PREPARED"
    assert fixture["runtime"]["actions"] == []
    return paths[0]


def _make_incomplete(harness, fixture, monkeypatch):
    m, plan = harness.m, fixture["plan"]
    replace = m._atomic_replace_bytes

    def failed_bootstrap(action):
        if action == "bootstrap":
            fixture["runtime"]["identity"] = None
            raise ValueError("SYNTHETIC_BOOTSTRAP_FAILURE")

    def failed_restore(path, raw, metadata_source, expected_current_sha, **kwargs):
        if raw == fixture["original"]:
            raise OSError("SYNTHETIC_TRANSIENT_RESTORE_RENAME_FAILURE")
        return replace(path, raw, metadata_source, expected_current_sha, **kwargs)

    fixture["runtime"]["hook"] = failed_bootstrap
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(m, "_atomic_replace_bytes", failed_restore)
            with pytest.raises(ValueError, match="ROLLBACK_INCOMPLETE"):
                m._run_switch(plan, confirmation=m.CONFIRM_SWITCH,
                              expected_current_sha=actual_helpers.digest(fixture["original"]),
                              expected_staged_sha=plan["target"]["staged_api_plist_sha256"])
    finally:
        fixture["runtime"]["hook"] = None
    paths = list((m.EVIDENCE_ROOT / "api_only_switch_runs").glob("*/operation_receipt.json"))
    assert len(paths) == 1
    return paths[0]


def _set_state(harness, fixture, pointer, runtime):
    m = harness.m
    if pointer == "original":
        m.ACTIVE_API_PLIST.write_bytes(fixture["original"])
    elif pointer == "candidate":
        m.ACTIVE_API_PLIST.write_bytes(m.STAGED_API_PLIST_PATH.read_bytes())
    elif pointer == "absent":
        m.ACTIVE_API_PLIST.unlink(missing_ok=True)
    else:
        raise AssertionError(pointer)
    if runtime == "unloaded":
        fixture["runtime"]["identity"] = None
    else:
        raw = fixture["original"] if runtime == "original" else m.STAGED_API_PLIST_PATH.read_bytes()
        fixture["runtime"]["identity"] = {"state": "running", "pid": "3011", **m._identity_from_plist(raw)}
    fixture["runtime"]["actions"].clear()
    return "ABSENT" if pointer == "absent" else actual_helpers.digest(m.ACTIVE_API_PLIST.read_bytes())


def _resume(harness, fixture, receipt_path, expected_sha):
    return harness.m._run_rollback(fixture["plan"], receipt_path=receipt_path,
                                  confirmation=harness.m.CONFIRM_ROLLBACK,
                                  expected_current_sha=expected_sha)


def _assert_contract(m, receipt_path, fixture):
    receipt = json.loads(receipt_path.read_text())
    reference = receipt["prepared_receipt"]
    prepared_path = Path(reference["path"])
    assert prepared_path.name == "prepared_receipt.json"
    assert actual_helpers.digest(prepared_path.read_bytes()) == reference["sha256"]
    prepared = json.loads(prepared_path.read_text())
    assert prepared["status"] == "PREPARED"
    assert receipt["before"] == prepared["before"]
    assert all(receipt["after"][key] == value for key, value in prepared["after"].items())
    for field in ("api_release_integration", "candidate_release", "backup_path", "backup_sha256",
                  "backup_metadata", "origin_operation_dir", "plan_sha256"):
        assert receipt[field] == prepared[field]
    assert prepared["api_release_integration"]["base"] == fixture["base_record"]
    assert Path(prepared["backup_path"]).parent == prepared_path.parent
    assert prepared["backup_sha256"] == actual_helpers.digest(fixture["original"])
    assert prepared["plan_sha256"] == m._canonical_sha(fixture["plan"])
    return receipt, prepared_path


def test_candidate_hardpins_final_core_bytes():
    m = actual_helpers.load(actual_helpers.SOURCE)
    assert m.INTEGRATION_GUARD_SHA256 == actual_helpers.digest(actual_helpers.CORE.read_bytes())


def test_incomplete_receipt_retains_original_prepared_contract(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    receipt_path = _make_incomplete(harness, fixture, monkeypatch)
    receipt, _ = _assert_contract(harness.m, receipt_path, fixture)
    assert receipt["status"] == "ROLLBACK_INCOMPLETE"
    assert "TRANSIENT_RESTORE_RENAME" in receipt["reason"]


@pytest.mark.parametrize("pointer", ["original", "candidate", "absent"])
@pytest.mark.parametrize("runtime", ["original", "candidate", "unloaded"])
def test_prepared_recovery_known_pointer_and_runtime_matrix(setup_actual, monkeypatch, pointer, runtime):
    harness, fixture = setup_actual
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    _, prepared_path = _assert_contract(harness.m, receipt_path, fixture)
    prepared_raw = prepared_path.read_bytes()
    token = _set_state(harness, fixture, pointer, runtime)
    result = _resume(harness, fixture, receipt_path, token)
    assert result["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert harness.m.ACTIVE_API_PLIST.read_bytes() == fixture["original"]
    assert fixture["runtime"]["identity"]["V35_RELEASE_ID"] == fixture["base"].name
    assert prepared_path.read_bytes() == prepared_raw
    _assert_contract(harness.m, Path(result["receipt_path"]), fixture)
    if runtime == "original":
        assert fixture["runtime"]["actions"] == []
    elif runtime == "unloaded":
        assert fixture["runtime"]["actions"] == ["bootstrap"]
    else:
        assert fixture["runtime"]["actions"] == ["bootout", "bootstrap"]


def test_existing_cli_rollback_resumes_failure_under_shared_lease(setup_actual, monkeypatch, capsys):
    harness, fixture = setup_actual
    m, plan = harness.m, fixture["plan"]
    receipt_path = _make_incomplete(harness, fixture, monkeypatch)
    original_action = m._launchctl_action

    def assert_shared_lock(action):
        with pytest.raises((ValueError, TimeoutError, BlockingIOError), match="LOCK.*BUSY"):
            with fixture["core"].shared_api_release_lock(m.ACTIVE_API_PLIST, timeout_seconds=0):
                pytest.fail("continuation released its shared lock")
        return original_action(action)

    monkeypatch.setattr(m, "_launchctl_action", assert_shared_lock)
    monkeypatch.setattr(m, "_load_plan", lambda: plan)
    assert m.main(["rollback", "--receipt", str(receipt_path), "--confirm", m.CONFIRM_ROLLBACK,
                   "--expected-current-plist-sha256", plan["target"]["staged_api_plist_sha256"]]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert m.ACTIVE_API_PLIST.read_bytes() == fixture["original"]


@pytest.mark.parametrize("pointer,wrong_token", [
    ("candidate", "ABSENT"), ("original", "f" * 64), ("absent", "f" * 64),
    ("absent", ""), ("absent", "absent"),
])
def test_recovery_requires_explicit_exact_current_cas(setup_actual, monkeypatch, pointer, wrong_token):
    harness, fixture = setup_actual
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    _set_state(harness, fixture, pointer, "unloaded")
    with pytest.raises(ValueError, match="CURRENT_PLIST_PREIMAGE_MISMATCH|EXPECTED_CURRENT_SHA_INVALID"):
        _resume(harness, fixture, receipt_path, wrong_token)
    assert fixture["runtime"]["actions"] == []
    assert harness.m.ACTIVE_API_PLIST.exists() is (pointer != "absent")


def test_recovery_refuses_unknown_pointer_even_with_matching_operator_sha(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    unknown = b"unknown publisher pointer\n"
    harness.m.ACTIVE_API_PLIST.write_bytes(unknown)
    with pytest.raises(ValueError, match="ACTIVE_PLIST_UNEXPECTED_SHA"):
        _resume(harness, fixture, receipt_path, actual_helpers.digest(unknown))
    assert harness.m.ACTIVE_API_PLIST.read_bytes() == unknown
    assert fixture["runtime"]["actions"] == []


@pytest.mark.parametrize("runtime_state", ["UNKNOWN", "LOADED_UNVERIFIED", "FOREIGN", "MISSING_PID"])
def test_recovery_refuses_unknown_runtime_before_mutation(setup_actual, monkeypatch, runtime_state):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    token = _set_state(harness, fixture, "candidate", "candidate")
    identity = dict(fixture["runtime"]["identity"])
    if runtime_state == "FOREIGN":
        identity["V35_RELEASE_ID"] = "unrecognized-job"
        observed = {"state": "LOADED", "identity": identity}
    elif runtime_state == "MISSING_PID":
        identity.pop("pid")
        observed = {"state": "LOADED", "identity": identity}
    else:
        observed = {"state": runtime_state, "identity": None}
    monkeypatch.setattr(m, "_observe_loaded", lambda: observed)
    with pytest.raises(ValueError, match="REFUSES_UNKNOWN_LOADED_IDENTITY|RUNTIME_STATE_UNVERIFIED"):
        _resume(harness, fixture, receipt_path, token)
    assert m.ACTIVE_API_PLIST.read_bytes() == m.STAGED_API_PLIST_PATH.read_bytes()
    assert fixture["runtime"]["actions"] == []


@pytest.mark.parametrize("field", ["before", "after", "api_release_integration", "backup_path", "backup_metadata"])
def test_rehashed_mutable_receipt_cannot_change_prepared_contract(setup_actual, monkeypatch, field):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    receipt = json.loads(receipt_path.read_text())
    if isinstance(receipt[field], dict):
        receipt[field]["unapproved_change"] = True
    else:
        receipt[field] += ".unapproved"
    m._write_receipt(receipt_path, receipt)
    with pytest.raises(ValueError, match="PREPARED_CONTRACT_MISMATCH"):
        _resume(harness, fixture, receipt_path, actual_helpers.digest(fixture["original"]))
    assert fixture["runtime"]["actions"] == []


def test_prepared_bytes_cannot_change_even_after_rehashing_itself(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    receipt, prepared_path = _assert_contract(m, receipt_path, fixture)
    prepared = json.loads(prepared_path.read_text())
    prepared["backup_metadata"]["mode"] = 0o600
    prepared_path.chmod(0o600)
    prepared_path.write_bytes(m._receipt_bytes(prepared))
    assert actual_helpers.digest(prepared_path.read_bytes()) != receipt["prepared_receipt"]["sha256"]
    with pytest.raises(ValueError, match="PREPARED_RECEIPT_SHA_MISMATCH"):
        _resume(harness, fixture, receipt_path, actual_helpers.digest(fixture["original"]))
    assert fixture["runtime"]["actions"] == []


def test_prepared_reference_cannot_redirect_outside_origin_contract(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    receipt, prepared_path = _assert_contract(m, receipt_path, fixture)
    redirected = m._new_operation_dir("-foreign") / "prepared_receipt.json"
    redirected.write_bytes(prepared_path.read_bytes())
    receipt["prepared_receipt"]["path"] = str(redirected)
    m._write_receipt(receipt_path, receipt)
    with pytest.raises(ValueError, match="PREPARED_RECEIPT_ORIGIN_MISMATCH"):
        _resume(harness, fixture, receipt_path, actual_helpers.digest(fixture["original"]))
    assert fixture["runtime"]["actions"] == []


@pytest.mark.parametrize("change", ["bytes", "metadata"])
def test_recovery_refuses_changed_original_backup(setup_actual, monkeypatch, change):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    receipt, _ = _assert_contract(m, receipt_path, fixture)
    backup = Path(receipt["backup_path"])
    if change == "bytes":
        backup.write_bytes(b"corrupted backup")
    else:
        backup.chmod(0o600 if (backup.stat().st_mode & 0o777) != 0o600 else 0o640)
    with pytest.raises(ValueError, match="BACKUP_SHA_MISMATCH|BACKUP_METADATA_MISMATCH"):
        _resume(harness, fixture, receipt_path, actual_helpers.digest(fixture["original"]))
    assert fixture["runtime"]["actions"] == []


def test_source_receipt_change_during_continuation_cannot_lower_cas(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    token = _set_state(harness, fixture, "candidate", "candidate")
    guards = m._verify_readonly_guards
    changed = False

    def change_receipt_after_checks(plan):
        nonlocal changed
        result = guards(plan)
        if not changed:
            changed = True
            receipt = json.loads(receipt_path.read_text())
            receipt["status"] = "ROLLBACK_INCOMPLETE"
            m._write_receipt(receipt_path, receipt)
        return result

    monkeypatch.setattr(m, "_verify_readonly_guards", change_receipt_after_checks)
    with pytest.raises(ValueError, match="SOURCE_RECEIPT_CHANGED"):
        _resume(harness, fixture, receipt_path, token)
    assert fixture["runtime"]["actions"] == []
    assert m.ACTIVE_API_PLIST.read_bytes() == m.STAGED_API_PLIST_PATH.read_bytes()


def test_repeat_failure_can_resume_from_latest_receipt_same_original_contract(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    first_path = _make_incomplete(harness, fixture, monkeypatch)
    first, prepared_path = _assert_contract(m, first_path, fixture)
    immutable_raw = prepared_path.read_bytes()

    def fail_old_bootstrap(action):
        if action == "bootstrap":
            fixture["runtime"]["identity"] = None
            raise ValueError("SYNTHETIC_SECOND_TRANSIENT_FAILURE")

    fixture["runtime"]["hook"] = fail_old_bootstrap
    second = _resume(harness, fixture, first_path, fixture["plan"]["target"]["staged_api_plist_sha256"])
    assert second["status"] == "ROLLBACK_INCOMPLETE"
    second_path = Path(second["receipt_path"])
    assert second_path.parent != first_path.parent
    second_receipt, _ = _assert_contract(m, second_path, fixture)
    assert second_receipt["prepared_receipt"] == first["prepared_receipt"]
    assert second_receipt["backup_path"] == first["backup_path"]
    assert m.ACTIVE_API_PLIST.read_bytes() == fixture["original"]
    fixture["runtime"]["hook"] = None
    third = _resume(harness, fixture, second_path, actual_helpers.digest(fixture["original"]))
    assert third["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert prepared_path.read_bytes() == immutable_raw
    _assert_contract(m, Path(third["receipt_path"]), fixture)


def test_recovery_does_not_require_healthy_candidate_to_restore_known_base(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_incomplete(harness, fixture, monkeypatch)
    (fixture["release"] / "app/domains/preselection_pools.py").write_bytes(b"broken candidate bytes\n")
    result = _resume(harness, fixture, receipt_path, fixture["plan"]["target"]["staged_api_plist_sha256"])
    assert result["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert m.ACTIVE_API_PLIST.read_bytes() == fixture["original"]


def test_recovery_cannot_select_a_different_base_with_rehashed_records(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    receipt, prepared_path = _assert_contract(m, receipt_path, fixture)
    prepared = json.loads(prepared_path.read_text())
    prepared["api_release_integration"]["base"]["api_plist_sha256"] = "f" * 64
    prepared_path.chmod(0o600)
    prepared_path.write_bytes(m._receipt_bytes(prepared))
    receipt["api_release_integration"] = prepared["api_release_integration"]
    receipt["prepared_receipt"]["sha256"] = actual_helpers.digest(prepared_path.read_bytes())
    m._write_receipt(receipt_path, receipt)
    with pytest.raises(ValueError, match="BASE_POINTER_BINDING_MISMATCH"):
        _resume(harness, fixture, receipt_path, actual_helpers.digest(fixture["original"]))
    assert fixture["runtime"]["actions"] == []


def test_bare_status_receipt_without_prepared_binding_is_not_recoverable(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    receipt = json.loads(receipt_path.read_text())
    receipt.pop("prepared_receipt", None)
    m._write_receipt(receipt_path, receipt)
    with pytest.raises(ValueError, match="PREPARED_RECEIPT_REQUIRED"):
        _resume(harness, fixture, receipt_path, actual_helpers.digest(fixture["original"]))
    assert fixture["runtime"]["actions"] == []


def test_runtime_change_during_last_backup_check_refuses_bootout(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    token = _set_state(harness, fixture, "candidate", "candidate")
    verify_backup = m._verify_recovery_backup
    calls = 0

    def change_runtime_at_bootout_boundary(*args, **kwargs):
        nonlocal calls
        result = verify_backup(*args, **kwargs)
        calls += 1
        # public validation, restore validation, then the pre-bootout guard.
        if calls == 3:
            fixture["runtime"]["identity"] = dict(fixture["plan"]["before"]["loaded_identity"])
        return result

    monkeypatch.setattr(m, "_verify_recovery_backup", change_runtime_at_bootout_boundary)
    result = _resume(harness, fixture, receipt_path, token)
    assert result["status"] == "ROLLBACK_INCOMPLETE"
    assert "RUNTIME_CHANGED_BEFORE_BOOTOUT" in result["reason"]
    assert fixture["runtime"]["actions"] == []
    assert m.ACTIVE_API_PLIST.read_bytes() == m.STAGED_API_PLIST_PATH.read_bytes()


def test_recovery_success_requires_original_runtime_at_final_readback(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    token = _set_state(harness, fixture, "candidate", "unloaded")

    def drift_during_readback(**kwargs):
        fixture["runtime"]["identity"] = {"state": "running", "pid": "9111",
            **m._identity_from_plist(m.STAGED_API_PLIST_PATH.read_bytes())}
        return {"status": "SYNTHETIC_PRODUCT_READBACK"}

    monkeypatch.setattr(m, "_verify_historical_product_readback", drift_during_readback)
    result = _resume(harness, fixture, receipt_path, token)
    assert result["status"] == "ROLLBACK_INCOMPLETE"
    assert "FINAL_RUNTIME_NOT_ORIGINAL" in result["reason"]
    assert m.ACTIVE_API_PLIST.read_bytes() == fixture["original"]


def test_cli_reports_incomplete_continuation_with_nonzero_exit(setup_actual, monkeypatch, capsys):
    harness, fixture = setup_actual
    m, plan = harness.m, fixture["plan"]
    receipt_path = _make_incomplete(harness, fixture, monkeypatch)

    def fail_old_bootstrap(action):
        if action == "bootstrap":
            fixture["runtime"]["identity"] = None
            raise ValueError("SYNTHETIC_OLD_BOOTSTRAP_FAILURE")

    fixture["runtime"]["hook"] = fail_old_bootstrap
    monkeypatch.setattr(m, "_load_plan", lambda: plan)
    assert m.main(["rollback", "--receipt", str(receipt_path), "--confirm", m.CONFIRM_ROLLBACK,
                   "--expected-current-plist-sha256", plan["target"]["staged_api_plist_sha256"]]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ROLLBACK_INCOMPLETE"
    latest = json.loads(Path(result["receipt_path"]).read_text())
    assert latest["resumed_from_receipt"]["path"] == str(receipt_path)
    assert latest["recovery_expected_current_plist_sha256"] == plan["target"]["staged_api_plist_sha256"]


def test_launchctl_adapter_uses_frozen_service_target_for_missing_pointer(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    # Call only the argument adapter from an unmodified module; no subprocess
    # executes. System-manual support is documented separately from this test.
    m = actual_helpers.load(actual_helpers.SOURCE)
    m.ACTIVE_API_PLIST = harness.root / "missing/com.lexi.v35.api-only.plist"
    calls = []

    def capture_run(argv, **kwargs):
        calls.append(argv)
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(m.subprocess, "run", capture_run)
    m._launchctl_action("bootout")
    m._launchctl_action("bootstrap")
    assert calls == [[str(m.LAUNCHCTL), "bootout", f"gui/{m.os.getuid()}/{m.LABEL}"],
                     [str(m.LAUNCHCTL), "bootstrap", f"gui/{m.os.getuid()}", str(m.ACTIVE_API_PLIST)]]
    assert not m.ACTIVE_API_PLIST.exists()


def test_aborted_before_bootout_retains_contract_and_can_resume(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m, plan = harness.m, fixture["plan"]
    preflight = m._preflight
    calls = 0

    def abort(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("SYNTHETIC_PREFLIGHT_INTERRUPTION")
        return preflight(*args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(m, "_preflight", abort)
        with pytest.raises(ValueError, match="SYNTHETIC_PREFLIGHT_INTERRUPTION"):
            m._run_switch(plan, confirmation=m.CONFIRM_SWITCH,
                          expected_current_sha=actual_helpers.digest(fixture["original"]),
                          expected_staged_sha=plan["target"]["staged_api_plist_sha256"])
    paths = list((m.EVIDENCE_ROOT / "api_only_switch_runs").glob("*/operation_receipt.json"))
    assert len(paths) == 1
    receipt, _ = _assert_contract(m, paths[0], fixture)
    assert receipt["status"] == "ABORTED_BEFORE_BOOTOUT"
    result = _resume(harness, fixture, paths[0], actual_helpers.digest(fixture["original"]))
    assert result["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert fixture["runtime"]["actions"] == []

