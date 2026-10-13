"""Afternoon Futu bars must reach the existing lane/observation flow."""
from dataclasses import replace
from types import SimpleNamespace
import inspect

import pytest

from stage_center.acquisition import SourceResult
from stage_center._live_collectors_parts.hk_minute import _collect_hk_minute_body
import stage_center.live_collectors as live


def collect(stage, reason=None, *, late=False, empty=False):
    row = {"code": "HK.01196", "futu_captured_at": "2026-10-13T13:15:03+08:00"}
    source = SourceResult("futu", "READY", rows=() if empty else (row,), requested_rows=1)
    calls = []
    def refresh(value, **kwargs):
        calls.append(kwargs["stage_id"])
        if reason:
            return replace(value, cannot_confirm=(reason,))
        return replace(value, rows=(dict(row, candidate_lanes=["LIVE_HKCONNECT_GAINER"]),))
    scope = dict(vars(live))
    scope.update(_shared_scripts_root=lambda x:x,
                 _load_shared_module=lambda *a:SimpleNamespace(collect_futu_minute=lambda *a,**k:object()),
                 _scoped_process_runner=lambda *a:None,
                 _to_source=lambda *a,**k:source, refresh_hk_active_lanes=refresh)
    plan = SimpleNamespace(stage_id=stage, trade_date="20261013", universe_bindings={},
                           same_day_late_observation_recovery=late)
    extra = {"snapshot_root": None} if "snapshot_root" in inspect.signature(_collect_hk_minute_body).parameters else {}
    result = _collect_hk_minute_body(scope, plan, codes=["HK.01196"], python_path="python",
                                    shared_root="root", process_runner=None, replay_provider=None, **extra)
    return result, calls


@pytest.mark.parametrize("stage", ["STAGE_1300_1315", "STAGE_1445_1500"])
def test_afternoon_reaches_verified_snapshot_lane(stage):
    result, calls = collect(stage)
    assert calls == [stage]
    assert result.rows[0]["candidate_lanes"] == ["LIVE_HKCONNECT_GAINER"]
    assert any(x.startswith("futu_captured_at=") for x in result.source_evidence)


@pytest.mark.parametrize("reason", ["HK_ACTIVE_SNAPSHOT_UNAVAILABLE", "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"])
def test_missing_timed_snapshot_preserves_observation_bars(reason):
    result, _ = collect("STAGE_1300_1315", reason)
    assert result.status == "PARTIAL_WITH_ROWS" and len(result.rows) == 1
    assert reason in result.cannot_confirm
    assert "active_snapshot_degraded_to_futu_observation=true" in result.source_evidence
    assert not result.rows[0].get("candidate_lanes")


@pytest.mark.parametrize("reason", ["HK_ACTIVE_GAINER_NO_MATCH", "HK_ACTIVE_SNAPSHOT_CORRUPT"])
def test_no_match_or_invalid_snapshot_is_not_relabelled_as_missing(reason):
    result, _ = collect("STAGE_1445_1500", reason)
    assert "active_snapshot_degraded_to_futu_observation=true" not in result.source_evidence


def test_late_recovery_does_not_probe_current_book():
    result, calls = collect("STAGE_1445_1500", late=True)
    assert calls == [] and result.status == "PARTIAL_WITH_ROWS"
    assert "FUTU_AFTERFACT_CAPTURE_NOT_PIT_SAFE" in result.cannot_confirm


def test_empty_futu_result_does_not_create_observation_rows():
    result, calls = collect("STAGE_1300_1315", empty=True)
    assert not result.rows and not calls
