"""Known original plist bytes are not a complete original metadata preimage."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
from test_recovery_continuation import _make_prepared, _resume, setup_actual


def test_recovery_restores_original_metadata_when_pointer_bytes_are_already_original(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    prepared = json.loads(receipt_path.read_text())
    expected_metadata = prepared["backup_metadata"]
    assert m.ACTIVE_API_PLIST.read_bytes() == fixture["original"]
    original_mode = m.ACTIVE_API_PLIST.stat().st_mode & 0o7777
    m.ACTIVE_API_PLIST.chmod(0o777 if original_mode != 0o777 else 0o640)
    fixture["runtime"]["identity"] = None
    result = _resume(harness, fixture, receipt_path, prepared["backup_sha256"])
    assert result["status"] == "ROLLED_BACK_TO_PREIMAGE"
    assert m._file_metadata(m.ACTIVE_API_PLIST) == expected_metadata
