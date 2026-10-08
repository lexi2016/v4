"""Independent failed-switch recovery probes; no real service/network calls."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
import test_actual_api_cutover as actual_helpers


@pytest.fixture
def setup_actual():
    fixture = actual_helpers.ActualCutoverTests("test_failed_bootstrap_recovers_using_same_lock_and_exact_base")
    fixture.setUp()
    try:
        yield fixture, fixture.integrated_fixture()
    finally:
        fixture.doCleanups()


def test_operator_can_resume_after_transient_automatic_restore_failure(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m, plan = harness.m, fixture["plan"]
    replace = m._atomic_replace_bytes

    def fail_candidate_bootstrap(action):
        if action == "bootstrap":
            fixture["runtime"]["identity"] = None
            raise ValueError("SYNTHETIC_CANDIDATE_BOOTSTRAP_FAILURE")

    def fail_restore_once(path, raw, metadata_source, expected_current_sha, **kwargs):
        if raw == fixture["original"]:
            raise OSError("SYNTHETIC_TRANSIENT_RESTORE_RENAME_FAILURE")
        return replace(path, raw, metadata_source, expected_current_sha, **kwargs)

    fixture["runtime"]["hook"] = fail_candidate_bootstrap
    with monkeypatch.context() as scoped:
        scoped.setattr(m, "_atomic_replace_bytes", fail_restore_once)
        with pytest.raises(ValueError, match="ROLLBACK_INCOMPLETE"):
            m._run_switch(plan, confirmation=m.CONFIRM_SWITCH,
                expected_current_sha=actual_helpers.digest(fixture["original"]),
                expected_staged_sha=plan["target"]["staged_api_plist_sha256"])

    fixture["runtime"]["hook"] = None
    receipts = list((m.EVIDENCE_ROOT / "api_only_switch_runs").glob("*/operation_receipt.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["status"] == "ROLLBACK_INCOMPLETE"
    assert m.ACTIVE_API_PLIST.read_bytes() == m.STAGED_API_PLIST_PATH.read_bytes()
    assert fixture["runtime"]["identity"] is None
    assert Path(receipt["backup_path"]).read_bytes() == fixture["original"]

    result = m._run_rollback(plan, receipt_path=receipts[0],
        confirmation=m.CONFIRM_ROLLBACK,
        expected_current_sha=plan["target"]["staged_api_plist_sha256"])
    assert result["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert m.ACTIVE_API_PLIST.read_bytes() == fixture["original"]
