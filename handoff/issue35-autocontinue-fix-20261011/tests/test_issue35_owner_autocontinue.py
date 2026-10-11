"""Issue #35 offline regression contracts. Run against ONE patched source root.

No network, market data, scheduler service or trades.  Never advances a
historical clock: fake inputs are synthetic identity tokens, not stock data.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from v4.manager_research import workspace as owner
from v4.manager_research import plan_owner_dispatch as dispatch
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS


DATE = "20261012"
OWNER = "ManagerResearchJobService.refresh_workspace_plan"


@pytest.fixture
def owner_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ManagerResearchStore(tmp_path / "manager")
    token = {"input": "a" * 64}
    phase = {"cutoff": "2026-10-11T13:00:00+00:00"}

    def fresh(_service, date, **_kwargs):
        assert date == DATE
        return {
            "target_trade_date": DATE,
            "input_identity": token["input"],
            "semantic_version": "issue35-offline-test",
            "date_bindings": {"selection_date": DATE, "announcement_date": "20261009"},
            "plan_context": {"research_cutoff": phase["cutoff"]},
            "gaps": [],
            "stocks": [{"symbol": "HK.00001", "reason": "SYNTHETIC_TEST_ONLY"}],
            "summary": {"input_test": True},
            "existing_material_coverage": {"input_test": True},
            **FLAGS,
        }

    monkeypatch.setattr(owner, "get_workspace", fresh)
    monkeypatch.setattr(owner, "checkpoint", lambda: None)
    monkeypatch.setattr(owner, "_attach_daily_channels", lambda value: value)
    # Runtime R1 also projects day channels inside _readback_plan.
    from v4.manager_research import workspace_daily_channels
    monkeypatch.setattr(workspace_daily_channels, "build_daily_channels", lambda value: [])
    # These synthetic fingerprints exercise only the saved/current identity
    # comparison.  Real market sources are never bypassed in production.
    monkeypatch.setattr(
        owner, "input_identity_diagnostics",
        lambda saved, current, **kw: {
            "status": "MATCH"
            if isinstance(saved, dict) and saved.get("input_identity") == current.get("input_identity")
            else "CHANGED",
            "changed_components": [],
        },
    )
    return SimpleNamespace(store=store), token


def _actual_plan_readback(service):
    return owner.get_workspace(service, DATE, include_saved=True)


def test_new_owner_run_has_terminal_attempt_before_plan_readback(owner_service):
    service, _token = owner_service
    result = owner.refresh_workspace_plan(service, DATE)
    plan = result["plan_product"]
    assert plan["status"] == "CURRENT", plan
    assert plan["consumed"] is True
    assert result["workspace_plan_attempt"]["run_id"] == plan["run_id"]
    assert result["workspace_plan_attempt"]["state"] == "SUCCEEDED"
    assert result["workspace_plan_product_attempt"]["sha256"] == result["workspace_plan_attempt"]["sha256"]
    verified = owner.verified_plan_attempt(service.store, owner._read_plan(service.store, DATE))
    assert verified["run_id"] == plan["run_id"]


def test_same_material_no_second_run_and_changed_material_new_run(owner_service):
    service, token = owner_service
    first = owner.refresh_workspace_plan(service, DATE)
    again = owner.refresh_workspace_plan(service, DATE)
    assert again["plan_product"]["status"] == "ALREADY_MATERIALIZED"
    assert again["plan_product"]["run_id"] == first["plan_product"]["run_id"]
    assert again["plan_product"]["sha256"] == first["plan_product"]["sha256"]

    token["input"] = "b" * 64
    changed = owner.refresh_workspace_plan(service, DATE)
    assert changed["plan_product"]["status"] == "CURRENT"
    assert changed["plan_product"]["run_id"] != first["plan_product"]["run_id"]
    assert changed["plan_product"]["sha256"] != first["plan_product"]["sha256"]
    archived = service.store._read(
        service.store.root / "workspace_plans" / DATE / (first["plan_product"]["run_id"] + ".json")
    )
    assert archived["sha256"] == first["plan_product"]["sha256"]


def test_failed_owner_attempt_preserves_last_success_pointer(owner_service, monkeypatch):
    service, token = owner_service
    first = owner.refresh_workspace_plan(service, DATE)
    token["input"] = "b" * 64
    base_readback = owner._readback_plan

    def reject_new_post_terminal_readback(store, date, current, **kwargs):
        latest = store._read(store.root / "workspace_plans" / date / "latest.json")
        if isinstance(latest, dict) and latest["run_id"] != first["plan_product"]["run_id"]:
            raise ValueError("WORKSPACE_PLAN_SAVE_READBACK_FAILED")
        return base_readback(store, date, current, **kwargs)

    monkeypatch.setattr(owner, "_readback_plan", reject_new_post_terminal_readback)
    with pytest.raises(ValueError, match="WORKSPACE_PLAN_SAVE_READBACK_FAILED"):
        owner.refresh_workspace_plan(service, DATE)
    saved = owner._read_plan(service.store, DATE)
    assert saved["run_id"] == first["plan_product"]["run_id"]
    terminal = service.store._read(service.store.root / "workspace_plan_runs" / DATE / "latest.json")
    assert terminal["state"] == "FAILED"
    assert terminal["run_id"] != first["plan_product"]["run_id"]


def test_dispatch_evening_does_not_replay_stale_completed_receipt(monkeypatch):
    prior_plan = {"run_id": "a" * 32, "product_sha256": "b" * 64, "input_identity": "c" * 64}
    prior = {"response": {"plan_result": prior_plan}, "state": "COMPLETED"}
    saved = {"run_id": "a" * 32, "sha256": "b" * 64, "input_identity": "c" * 64}
    marker = {"status": "CURRENT", "consumed": True, "run_id": saved["run_id"], "sha256": saved["sha256"]}
    monkeypatch.setattr(
        "ops.run_manager_announcement_cycle.valid_owner_plan_result",
        lambda plan, branch: branch == "EVENING_NEXT_SESSION",
    )
    monkeypatch.setattr(owner, "_read_plan", lambda *_args: saved)
    monkeypatch.setattr(owner, "verified_plan_attempt", lambda *_args: {"run_id": saved["run_id"]})
    monkeypatch.setattr(owner, "get_workspace", lambda *_args, **_kwargs: {"plan_product": dict(marker)})

    ident = {"branch": "EVENING_NEXT_SESSION", "target_trade_date": DATE}
    now = datetime.now(timezone.utc)
    service = SimpleNamespace(store=SimpleNamespace())
    assert dispatch._completed_dispatch_still_current(service, ident, prior, now=now) is True
    marker["status"] = "STALE_INPUTS_CHANGED"
    marker["consumed"] = False
    assert dispatch._completed_dispatch_still_current(service, ident, prior, now=now) is False
    assert dispatch._completed_dispatch_still_current(
        service, {"branch": "SAME_DAY_CATCHUP", "target_trade_date": DATE}, prior, now=now
    ) is True


def test_missing_formal_stage_consumer_stays_unbound(tmp_path):
    from v4.manager_research.service import ManagerResearchJobService

    formal_reader = object()
    service = ManagerResearchJobService(
        ManagerResearchStore(tmp_path / "stage-manager"),
        None, None,
        workspace_stage_selection_reader=formal_reader,
    )
    try:
        assert service._workspace_stage_selection_reader is formal_reader
    finally:
        service.close()
