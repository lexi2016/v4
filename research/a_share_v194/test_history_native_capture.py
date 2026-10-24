"""Only the new exact-path byte acquisition, no market record decoding."""
from pathlib import Path

import history_native_capture as capture


def test_capture_stable_bytes_preserves_original_and_rejects_in_read_stat_drift(tmp_path, monkeypatch):
    native = tmp_path / "sz000001.day"
    original = b"x" * 64
    native.write_bytes(original)
    entry = dict(code="000001.SZ", native_path=str(native))
    result = capture.capture_native_entry(entry, tmp_path / "stable", 1024)
    assert result["state"] == "NATIVE_CAPTURED_STABLE_BYTES"
    assert Path(result["effective_native"]["path"]).read_bytes() == original
    assert native.read_bytes() == original
    real_stat = capture.file_stat
    calls = []

    def changing_stat(path):
        value = real_stat(path)
        calls.append(path)
        return value if len(calls) == 1 else {**value, "mtime_ns": value["mtime_ns"] + 1}

    monkeypatch.setattr(capture, "file_stat", changing_stat)
    result = capture.capture_native_entry(entry, tmp_path / "changed", 1024)
    assert result["state"] == "NATIVE_CHANGED_DURING_CAPTURE"
    assert result["effective_native"] is None
    assert Path(result["captured_original_bytes"]["path"]).is_file()


def test_capture_first_canary_reuses_original_binding_without_opening_original(tmp_path, monkeypatch):
    native = tmp_path / "sz000001.day"
    native.write_bytes(b"x" * 32)
    preserved = tmp_path / "preserved.day"
    preserved.write_bytes(b"x" * 32)
    binding = dict(name="native", kind="day_bytes", path=str(preserved), sha256=capture.sha(preserved), bytes=32)
    entry = dict(code="000001.SZ", native_path=str(native), reused_original_native_stat=capture.file_stat(native),
                 reuse_canary_stock=dict(code="000001.SZ", sources=[binding]))
    real_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path != native, "original canary native bytes were reopened"
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    result = capture.capture_native_entry(entry, tmp_path / "output", 1024)
    assert result["effective_native"] == binding
    assert result["new_original_files_read"] == 0
    assert result["capture_vintage"].startswith("UNCHANGED_R1_SAMPLE_CAPTURE")


def test_capture_missing_and_invalid_layout_are_explicit_not_dropped(tmp_path):
    missing = capture.capture_native_entry(dict(code="920000.BJ", native_path=str(tmp_path / "missing.day")),
                                           tmp_path / "output", 1024)
    assert missing["code"] == "920000.BJ" and missing["state"] == "NATIVE_MISSING_AT_CAPTURE"
    assert missing["effective_native"] is None
    invalid_path = tmp_path / "invalid.day"
    invalid_path.write_bytes(b"trailing")
    invalid = capture.capture_native_entry(dict(code="920001.BJ", native_path=str(invalid_path)),
                                           tmp_path / "output", 1024)
    assert invalid["code"] == "920001.BJ" and invalid["state"] == "NATIVE_INVALID_RECORD_LAYOUT"
    assert Path(invalid["captured_original_bytes"]["path"]).read_bytes() == b"trailing"
    assert invalid["effective_native"] is None
