"""Original cycle/owner adapters preserve input admission and trigger identity.

Only synthetic clocks, diagnostic responses and temporary stores are used.
The product-creation behavior is exercised by test_manager_r3_dates_inputs.
"""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from ops import run_manager_announcement_cycle as cycle
from v4.manager_research import workspace, workspace_plan_autorun as autorun
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS, HK


def missing_input(date="20261009"):
    return {
        "target_trade_date": date,
        "status": "CANNOT_CONFIRM",
        "reason": "WORKSPACE_PLAN_INPUTS_NOT_READY",
        "failure_reasons": ["ANNOUNCEMENT:NOT_RUN", "OVERSOLD:CANNOT_CONFIRM"],
        "input_identity": "a" * 64,
        "plan_product": {
            "status": "CANNOT_CONFIRM", "consumed": False,
            "run_id": None, "sha256": None,
        },
        **FLAGS,
    }


@pytest.mark.parametrize("kind", ["SCHEDULED_MORNING", "SCHEDULED_PREOPEN", "MANUAL_REFRESH"])
def test_owner_admission_is_distinct_from_a_product_readback(kind):
    value = missing_input()
    result = autorun.owner_plan_readback(value, "20261009", expected_kind=kind)
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["reason"] == "WORKSPACE_PLAN_INPUTS_NOT_READY"
    assert result["failure_reasons"] == value["failure_reasons"]
    assert result["run_id"] is None
    assert result["product_sha256"] is None
    assert result["execution_kind_source"] == "OWNER_INPUT_DIAGNOSTIC"


@pytest.mark.parametrize("field,value", [
    ("run_id", "1" * 32), ("sha256", "b" * 64), ("consumed", True),
])
def test_input_admission_cannot_hide_a_materialized_product(field, value):
    response = missing_input()
    response["plan_product"][field] = value
    with pytest.raises(ValueError):
        autorun.owner_plan_readback(response, "20261009", expected_kind="MANUAL_REFRESH")


def test_input_admission_date_and_reasons_are_required():
    with pytest.raises(ValueError):
        autorun.owner_plan_readback(missing_input("20261008"), "20261009", expected_kind="MANUAL_REFRESH")
    value = missing_input()
    value["failure_reasons"] = []
    with pytest.raises(ValueError):
        autorun.owner_plan_readback(value, "20261009", expected_kind="MANUAL_REFRESH")


def test_input_admission_cannot_hide_an_owner_attempt():
    value = missing_input()
    value["workspace_plan_attempt"] = {"run_id": "1" * 32, "state": "FAILED"}
    with pytest.raises(ValueError, match="PLAN_OWNER_INPUT_DIAGNOSTIC_INVALID"):
        autorun.owner_plan_readback(value, "20261009", expected_kind="MANUAL_REFRESH")


@pytest.mark.parametrize("branch,hour,minute", [("MORNING", 7, 0), ("PREOPEN", 9, 27)])
def test_original_scheduled_wrappers_keep_input_missing_and_supply_context(branch, hour, minute):
    calls = []
    def refresh(date, **kwargs):
        calls.append((date, deepcopy(kwargs)))
        return missing_input(date)
    service = SimpleNamespace(refresh_workspace_plan=refresh)
    now = datetime(2026, 10, 9, hour, minute, tzinfo=HK)
    if branch == "MORNING":
        result = autorun.run_scheduled_morning_plan(service, "20261009", now=now,
            config={"enabled": True, "interval_seconds": 300, "status": "PROPOSAL_ONLY"})
    else:
        result = autorun.run_scheduled_preopen_plan_safe(service, "20261009", now=now)
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["reason"] == "WORKSPACE_PLAN_INPUTS_NOT_READY"
    assert result["run_id"] is None
    context = calls[0][1]["execution_context"]
    assert context["trigger_kind"] == "SCHEDULED"
    assert context["scheduled_for"] == now.isoformat()
    assert context["natural_run_verified"] is False


def test_original_evening_owner_keeps_input_missing_without_saved_product(tmp_path, monkeypatch):
    calls = []
    store = ManagerResearchStore(tmp_path / "state")
    def refresh(date, **kwargs):
        calls.append((date, deepcopy(kwargs)))
        return missing_input(date)
    service = SimpleNamespace(store=store, refresh_workspace_plan=refresh)
    monkeypatch.setattr(workspace, "get_workspace", lambda *_a, **_k: {"input_identity": "a" * 64})
    now = datetime(2026, 10, 8, 17, 0, tzinfo=HK)
    result = cycle.run_next_hk_session_plan_material_refresh(service, "20261008", now=now,
        config={"enabled": True})
    assert result["target_trade_date"] == "20261009"
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["reason"] == "WORKSPACE_PLAN_INPUTS_NOT_READY"
    assert workspace._read_plan(store, "20261009") is None
    assert calls[0][1]["execution_context"] == {
        "trigger_kind": "SCHEDULED", "timing": "ON_TIME",
        "scheduled_for": now.isoformat(), "natural_run_verified": False,
    }


def test_saved_owner_projection_preserves_the_same_execution_context(tmp_path):
    service = SimpleNamespace(store=ManagerResearchStore(tmp_path / "state"))
    context = {"trigger_kind": "SCHEDULED", "timing": "LATE_CATCHUP",
        "scheduled_for": "2026-10-09T10:00:00+08:00", "natural_run_verified": False}
    saved = {"run_id": "1" * 32, "sha256": "b" * 64,
        "workspace": {"target_trade_date": "20261009"},
        "execution_kind": "MANUAL_REFRESH", "execution_context": context,
        "owner": autorun.PLAN_OWNER}
    readback = cycle._saved_owner_readback(service, "20261009", saved)
    assert readback["plan_product"]["execution_context"] == context
    readback["plan_product"]["execution_context"]["timing"] = "ON_TIME"
    assert saved["execution_context"]["timing"] == "LATE_CATCHUP"


def test_scheduled_envelope_never_turns_input_not_ready_into_owner_failed():
    service = SimpleNamespace(refresh_workspace_plan=lambda date, **_kwargs: missing_input(date))
    result = cycle.run_scheduled_plan_target(service, "20261009", "20261009",
        now=datetime(2026, 10, 9, 9, 27, tzinfo=HK), plan_config={"enabled": True})
    assert result["status"] == "PARTIAL"
    assert result["dispatch_outcome"] == "INPUT_NOT_READY"
    assert result["plan_result"]["status"] == "CANNOT_CONFIRM"
    assert result["failure_reasons"] == missing_input()["failure_reasons"]
    assert cycle.valid_owner_plan_result(result["plan_result"], "PREOPEN") is False


def test_plan_only_child_outside_slot_does_not_send_owner_request(tmp_path, monkeypatch, capsys):
    from infrastructure.scheduling import manager_announcement_supervisor as supervisor
    from v4.manager_research import plan_owner_dispatch as dispatch
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            now = datetime(2026, 10, 9, 11, 1, tzinfo=HK)
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    binding = {
        "enabled": True, "plan_material_refresh_only": True,
        "announcement_collection_enabled": False, "plan_material_refresh": {"enabled": True},
        "morning_plan": {"enabled": True}, "daily_automation": {"enabled": True},
    }
    # Admission/canary/root validation is independently tested without stubs in
    # test_manager_r3_binding_identity. This test isolates the existing child slot.
    monkeypatch.setattr(supervisor, "load_binding", lambda *_args: binding)
    monkeypatch.setattr(cycle, "datetime", Clock)
    monkeypatch.setattr(cycle.sys, "version_info", (3, 14, 0))
    monkeypatch.chdir(cycle.APP_ROOT)
    for key in ("PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT"):
        monkeypatch.delenv(key, raising=False)
    def forbidden(*_args, **_kwargs):
        pytest.fail("a non-due child sent an owner request")
    monkeypatch.setattr(dispatch, "request_bound_plan_cycle", forbidden)
    monkeypatch.setattr(dispatch, "request_bound_daily_cycle", forbidden)
    assert cycle.main(["--binding", str(tmp_path / "not-read.json")]) == 0
    import json
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "NOT_DUE"
    assert result["dispatch_outcome"] == "NOT_TRIGGERED"
    assert result["network_requests"] == result["state_writes"] == 0
