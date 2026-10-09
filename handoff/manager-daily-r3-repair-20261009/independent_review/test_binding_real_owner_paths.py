"""Independent probes retain the real dispatch and PREOPEN wrapper path."""
import hashlib
import json
import os
from pathlib import Path

import pytest

import test_manager_r3_binding_contract as original


APP_ROOT = Path(os.environ.get("V4_R3_REVIEW_APP_ROOT",
    str(Path(__file__).resolve().parents[1] / "candidate")))


def test_inventory_pins_actual_nested_consumer_bytes_in_synthetic_role(tmp_path, monkeypatch):
    # The scoped Chat candidate deliberately omits unrelated package files.
    # Use the complete inert role fixture for the scanner, then supply the
    # exact actual nested reader bytes; do not create a production shim.
    fixture = original._fixture(tmp_path, monkeypatch)
    path = original.OWNER_HK_SUPPLEMENT
    (fixture.owner_root / path).write_bytes((APP_ROOT / path).read_bytes())
    inventory = original.supervisor.binding_inventory(fixture.owner_root)
    assert inventory[path] == hashlib.sha256((APP_ROOT / path).read_bytes()).hexdigest()
    assert path in original.supervisor.PLAN_OWNER_REQUIRED_FILES


@pytest.mark.parametrize("daily", [False, True])
def test_matching_binding_sha_rejects_real_nested_reader_drift_before_owner(tmp_path, monkeypatch, daily):
    fixture = original._fixture(tmp_path, monkeypatch, daily=daily)
    assert original.OWNER_HK_SUPPLEMENT not in fixture.binding["files"]
    (fixture.owner_root / original.OWNER_HK_SUPPLEMENT).write_text("# synthetic parallel API source change\n")
    assert hashlib.sha256(fixture.path.read_bytes()).hexdigest() == fixture.sha
    with original._client(fixture.service) as client:
        original._memory_transport(monkeypatch, client)
        call = original.dispatch.request_bound_daily_cycle if daily else original.dispatch.request_bound_plan_cycle
        result = call(fixture.path, original.DATE)
    assert result["failure_stage"] == "ADMISSION"
    assert result["owner_execution_status"] == "OWNER_NOT_CALLED"
    assert result["parent_trigger_receipt"]["failure_code"] == "PLAN_OWNER_BINDING_CLOSED_INVENTORY_MISMATCH"
    assert fixture.events == []
    assert not list(fixture.service.store.root.rglob("*.json"))


@pytest.mark.parametrize("failure", ["timeout", "timeout_uppercase", "uppercase_detail"])
def test_real_preopen_owner_exception_keeps_timeout_unknown_and_details_bounded(tmp_path, monkeypatch, failure):
    fixture = original._fixture(tmp_path, monkeypatch)

    def failed_owner(date, **kwargs):
        fixture.events.append(("plan", date, kwargs))
        if failure.startswith("timeout"):
            raise TimeoutError("SYNTHETIC_PRIVATE_UPPERCASE_DETAIL" if failure == "timeout_uppercase"
                               else "synthetic completion is unknown")
        raise ValueError("SYNTHETIC_PRIVATE_UPPERCASE_DETAIL")

    fixture.service.refresh_workspace_plan = failed_owner
    with original._client(fixture.service) as client:
        original._memory_transport(monkeypatch, client)
        result = original.dispatch.request_bound_plan_cycle(fixture.path, original.DATE)
    assert len(fixture.events) == 1
    assert result["status"] == "FAILED"
    if failure.startswith("timeout"):
        assert result["dispatch_outcome"] == "CANNOT_CONFIRM", result
    assert "SYNTHETIC_PRIVATE_UPPERCASE_DETAIL" not in json.dumps(result), result
