"""R7: the exact original preimage includes its recorded file metadata."""
import json

from test_recovery_continuation import _make_prepared, _resume, _set_state, setup_actual


def test_original_runtime_recovery_repairs_original_pointer_metadata_without_service_action(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    expected_metadata = json.loads(receipt_path.read_text())["backup_metadata"]
    token = _set_state(harness, fixture, "original", "original")
    m.ACTIVE_API_PLIST.chmod(0o777)
    result = _resume(harness, fixture, receipt_path, token)
    assert result["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert m._file_metadata(m.ACTIVE_API_PLIST) == expected_metadata
    assert m.ACTIVE_API_PLIST.read_bytes() == fixture["original"]
    assert fixture["runtime"]["actions"] == []


def test_recovery_cannot_report_success_if_metadata_drifts_after_bootstrap(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    token = _set_state(harness, fixture, "candidate", "unloaded")

    def drift_after_bootstrap(action):
        if action == "bootstrap":
            m.ACTIVE_API_PLIST.chmod(0o777)

    fixture["runtime"]["hook"] = drift_after_bootstrap
    result = _resume(harness, fixture, receipt_path, token)
    assert result["status"] == "ROLLBACK_INCOMPLETE"
    assert "PREIMAGE_METADATA_MISMATCH" in result["reason"]
