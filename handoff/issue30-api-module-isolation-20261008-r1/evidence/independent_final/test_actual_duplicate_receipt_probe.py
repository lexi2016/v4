"""The public recovery entry must reject ambiguous JSON before service actions."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
from test_recovery_continuation import _make_prepared, _resume, _set_state, setup_actual


def test_recovery_rejects_duplicate_status_in_operation_receipt(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    expected = _set_state(harness, fixture, "candidate", "unloaded")
    original = receipt_path.read_text()
    assert original.startswith("{")
    # The existing canonical object digest remains valid under last-key-wins
    # parsing. A strict reader must reject the duplicate even though the final
    # decoded status is the original PREPARED value.
    receipt_path.write_text('{"status":"FOREIGN_UNREVIEWED_STATUS",' + original[1:])
    current = harness.m.ACTIVE_API_PLIST.read_bytes()
    with pytest.raises(ValueError, match="DUPLICATE|JSON_INVALID"):
        _resume(harness, fixture, receipt_path, expected)
    assert harness.m.ACTIVE_API_PLIST.read_bytes() == current
    assert fixture["runtime"]["actions"] == []
