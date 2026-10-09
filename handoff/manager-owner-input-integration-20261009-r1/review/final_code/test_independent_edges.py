"""Reviewer-local synthetic edge tests; no source/runtime/real owner mutation."""
from datetime import datetime, timedelta
import importlib
import os
from pathlib import Path
import sys

import pytest

APP = Path(os.environ["PLAN_AUDIT_APP_ROOT"])
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "tests"))
from test_manager_app_plan_identity_20261009 import (
    app_owner, material_owner, DATE, PUBLICATION, FLAGS, _snapshot, _get,
)


def clocks(kind):
    from v4.manager_research.workspace_plan_autorun import morning_window, preopen_window
    if kind == "SCHEDULED_MORNING":
        return datetime.fromisoformat("2026-10-09T08:00:00+08:00"), morning_window(DATE)[1]
    return datetime.fromisoformat("2026-10-09T09:28:00+08:00"), preopen_window(DATE)[1]


@pytest.mark.parametrize("kind", ["SCHEDULED_MORNING", "SCHEDULED_PREOPEN"])
def test_same_immutable_inputs_reuse_scheduled_run_with_advancing_native_witness(material_owner, monkeypatch, kind):
    service, client, roots, witness, _owner, _built = material_owner
    workspace = importlib.import_module(service.__class__.__module__.rsplit(".", 1)[0] + ".workspace")
    clock, deadline = clocks(kind)
    witness[0] = clock
    monkeypatch.setattr(workspace, "_now", lambda: witness[0].isoformat())
    first = service.refresh_workspace_plan(DATE, execution_kind=kind, now=clock, deadline=deadline)
    assert len(first["material_discovery_evidence"]["cards"]) == 1
    before = {key: _snapshot(roots[key]) for key in ("shared", "research", "manager")}
    witness[0] += timedelta(seconds=30)
    repeated = service.refresh_workspace_plan(DATE, execution_kind=kind, now=witness[0], deadline=deadline)
    assert repeated["plan_product"]["status"] == "ALREADY_MATERIALIZED"
    assert repeated["input_identity"] == first["input_identity"]
    assert repeated["plan_product"]["run_id"] == first["plan_product"]["run_id"]
    assert repeated["plan_product"]["sha256"] == first["plan_product"]["sha256"]
    assert repeated["selection_diagnostics"]["membership"]["source"]["read_at"] != first["selection_diagnostics"]["membership"]["source"]["read_at"]
    assert _get(client)["plan_product"]["status"] == "CURRENT"
    assert {key: _snapshot(roots[key]) for key in before} == before
    assert all(repeated[key] is value for key, value in FLAGS.items())


@pytest.mark.parametrize("kind", ["SCHEDULED_MORNING", "SCHEDULED_PREOPEN"])
@pytest.mark.parametrize("changed", ["selection_date", "announcement_date"])
def test_corrected_scheduled_binding_preserves_original_immutable_run(app_owner, monkeypatch, kind, changed):
    service, client, workspace, roots = app_owner
    clock, deadline = clocks(kind)
    monkeypatch.setattr(workspace, "_now", lambda: clock.isoformat())
    old_bindings = {"selection_date": DATE, "announcement_date": PUBLICATION}
    old_bindings[changed] = "20261007"
    first = service.refresh_workspace_plan(DATE, execution_kind=kind, now=clock, deadline=deadline,
                                           workspace_date_bindings=old_bindings)
    old_run = first["plan_product"]["run_id"]
    before = _snapshot(roots["manager"])
    old_immutable = {key: value for key, value in before.items() if key.endswith("/" + old_run + ".json")}
    assert len(old_immutable) == 2
    corrected = service.refresh_workspace_plan(DATE, execution_kind=kind, now=clock, deadline=deadline)
    assert corrected["plan_product"]["run_id"] != old_run
    assert corrected["date_bindings"] == {"plan_date": DATE, "selection_date": DATE, "announcement_date": PUBLICATION}
    after = _snapshot(roots["manager"])
    assert {key: after[key] for key in old_immutable} == old_immutable
    assert _get(client)["plan_product"]["status"] == "CURRENT"
    assert all(corrected[key] is value for key, value in FLAGS.items())


def test_legacy_v1_witness_clock_retains_native_meaning_and_cannot_be_target_v2(app_owner, monkeypatch):
    _service, _client, _workspace, roots = app_owner
    from test_manager_r2_rework import universe, DATE as V1_DATE, AS_OF
    from domains.manager_research_evidence import read_universe_evidence
    from v4.manager_research.connect_selection import read_scope, filter_cards
    from v4.manager_research.workspace_plan import plan_context
    root = roots["shared"]
    early = universe(root)
    later = read_universe_evidence(root, V1_DATE, as_of=AS_OF, clock=lambda: AS_OF.replace(second=10))
    assert early.source["sha256"] == later.source["sha256"]
    assert early.source["available_at"] != later.source["available_at"]
    assert "read_at" not in early.source and "read_at" not in later.source
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_ROOT", str(root))
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_ROOT", str(APP))
    import hashlib
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_SHA256", hashlib.sha256((APP / "stage_center/hk_universe_preflight.py").read_bytes()).hexdigest())
    scope = read_scope(plan_context(V1_DATE, now=AS_OF))
    assert scope["status"] == "CANNOT_CONFIRM"
    rows, rejected = filter_cards([{"symbol": "HK.00001"}], scope, target_date=V1_DATE)
    assert rows == [] and len(rejected) == 1
