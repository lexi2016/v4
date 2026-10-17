"""Targeted regression tests for the Issue #44 product-size contract.

Run from the actual V4 runtime/source root:
  python -m pytest -q <this-file>

The >64 MiB fixture is synthetic and non-sensitive. No capture or model is run.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from v4.manager_workbench.inputs import capture_store


def _store(tmp_path):
    store = capture_store.CaptureStore(tmp_path / "capture")
    store.grant(expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
    return store


def test_product_over_64_mib_first_save_and_same_sha_reuse(tmp_path):
    store = _store(tmp_path)
    # Encoded JSON exceeds SafeRoot's 64 MiB default but remains within the
    # existing downstream 256 MiB consumer bound.
    value = {"synthetic": "x" * (65 * 1024 * 1024)}
    first = store.save_product(value)
    second = store.save_product(value)

    raw = store.io.read_bytes(first["artifact_ref"], max_bytes=capture_store.PRODUCT_MAX_BYTES)
    assert len(raw) > 64 * 1024 * 1024
    assert hashlib.sha256(raw).hexdigest() == first["sha256"] == second["sha256"]
    assert first == second
    assert first["owner"] == capture_store.OWNER
    assert first["artifact_ref"] == f"products/{first['sha256']}.json"


def test_product_over_local_contract_is_rejected_without_truncation(tmp_path, monkeypatch):
    store = _store(tmp_path)
    # Lower only the module-local contract for a small deterministic boundary
    # test; the shared SafeRoot default is not changed.
    monkeypatch.setattr(capture_store, "PRODUCT_MAX_BYTES", 128)
    value = {"synthetic": "x" * 256}
    with pytest.raises(ValueError, match="OWNED_FILE_TOO_LARGE"):
        store.save_product(value)


def test_shared_safe_root_default_remains_64_mib():
    import inspect
    from infrastructure.owned_io import SafeRoot

    parameter = inspect.signature(SafeRoot.read_bytes).parameters["max_bytes"]
    assert parameter.default == 64 * 1024 * 1024
