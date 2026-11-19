"""Afternoon Futu bars must reach the existing lane/observation flow."""
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
import inspect

import pytest

from stage_center.acquisition import SourceResult
from stage_center._live_collectors_parts.hk_minute import _collect_hk_minute_body
from stage_center._live_collectors_parts.hk_minute import _hk_futu_scan_evidence
import stage_center._live_collectors_parts.hk_minute as hk_minute
import stage_center.live_collectors as live


def collect(stage, reason=None, *, late=False, empty=False, captured_at="2026-10-13T13:15:03+08:00"):
    row = {"code": "HK.01196", "score": 0.75, "temporal_cutoff_safe": True}
    if captured_at is not None:
        row["futu_captured_at"] = captured_at
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


@pytest.mark.parametrize(
    "captured_at,clock_available,date_matches,before_cutoff,gap",
    [
        ("2026-10-13T13:14:59+08:00", "true", "true", "true", "HK_FUTU_FULL_CHAIN_PIT_UNVERIFIED"),
        ("2026-10-13T13:15:00+08:00", "true", "true", "false", "HK_FUTU_CAPTURE_NOT_BEFORE_STAGE_CUTOFF"),
        ("2026-10-13T13:15:03+08:00", "true", "true", "false", "HK_FUTU_CAPTURE_NOT_BEFORE_STAGE_CUTOFF"),
        (None, "false", "CANNOT_CONFIRM", "CANNOT_CONFIRM", "HK_FUTU_CAPTURE_CLOCK_UNAVAILABLE"),
    ],
)
def test_capture_clock_metadata_stays_separate_from_bar_window(
    captured_at, clock_available, date_matches, before_cutoff, gap
):
    result, calls = collect("STAGE_1300_1315", captured_at=captured_at)

    assert calls == ["STAGE_1300_1315"]
    assert result.status == "PARTIAL_WITH_ROWS"
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["score"] == 0.75
    assert row["temporal_cutoff_safe"] is True
    assert row["candidate_lanes"] == ["LIVE_HKCONNECT_GAINER"]
    assert gap not in result.cannot_confirm
    assert f"futu_pit_cannot_confirm={gap}" in result.source_evidence
    assert "futu_full_chain_pit_status=CANNOT_CONFIRM" in result.source_evidence
    assert "futu_capture_clock_alone_is_not_pit_proof=true" in result.source_evidence
    assert f"futu_capture_clock_available={clock_available}" in result.source_evidence
    assert f"futu_capture_clock_date_matches_stage={date_matches}" in result.source_evidence
    assert f"futu_capture_before_stage_cutoff={before_cutoff}" in result.source_evidence


def test_capture_pit_metadata_preserves_real_data_errors():
    result, _ = collect("STAGE_1300_1315", "HK_ACTIVE_SNAPSHOT_CORRUPT")
    assert "HK_ACTIVE_SNAPSHOT_CORRUPT" in result.cannot_confirm
    assert "HK_FUTU_CAPTURE_NOT_BEFORE_STAGE_CUTOFF" not in result.cannot_confirm
    assert "futu_pit_cannot_confirm=HK_FUTU_CAPTURE_NOT_BEFORE_STAGE_CUTOFF" in result.source_evidence


@pytest.mark.parametrize(
    "stage,started,finished,start_before,finish_before",
    [
        ("STAGE_1300_1315", "13:14:50", "13:14:59", "true", "true"),
        ("STAGE_1300_1315", "13:14:59", "13:15:01", "true", "false"),
        ("STAGE_1445_1500", "15:00:01", "15:00:04", "false", "false"),
    ],
)
def test_afternoon_invocation_clock_reaches_source_evidence(
    monkeypatch, stage, started, finished, start_before, finish_before
):
    clocks = iter(datetime.fromisoformat(f"2026-10-13T{value}+08:00") for value in (started, finished))
    monkeypatch.setattr(hk_minute, "_hk_futu_scan_clock", lambda: next(clocks))
    result, _ = collect(stage)
    evidence = result.source_evidence
    assert f"futu_scan_started_at=2026-10-13T{started}+08:00" in evidence
    assert f"futu_scan_finished_at=2026-10-13T{finished}+08:00" in evidence
    assert f"futu_scan_started_before_cutoff={start_before}" in evidence
    assert f"futu_scan_finished_before_cutoff={finish_before}" in evidence
    assert "futu_scan_clock_status=RECORDED" in evidence
    assert "futu_scan_clock_scope=LOCAL_BRIDGE_INVOCATION" in evidence
    assert "futu_full_chain_pit_status=CANNOT_CONFIRM" in evidence
    assert result.status == "PARTIAL_WITH_ROWS"
    assert result.rows[0]["temporal_cutoff_safe"] is True


def test_empty_afternoon_result_keeps_invocation_clock(monkeypatch):
    clocks = iter(datetime.fromisoformat(value) for value in (
        "2026-10-13T13:15:01+08:00", "2026-10-13T13:15:02+08:00",
    ))
    monkeypatch.setattr(hk_minute, "_hk_futu_scan_clock", lambda: next(clocks))
    result, _ = collect("STAGE_1300_1315", empty=True)
    assert not result.rows
    assert "futu_scan_clock_status=RECORDED" in result.source_evidence
    assert "futu_scan_finished_before_cutoff=false" in result.source_evidence


@pytest.mark.parametrize(
    "started,finished",
    [
        ("2026-10-13T13:14:00", "2026-10-13T13:14:01"),
        ("2026-10-12T13:14:00+08:00", "2026-10-12T13:14:01+08:00"),
        ("2026-10-13T13:14:01+08:00", "2026-10-13T13:14:00+08:00"),
    ],
)
def test_invalid_invocation_clock_cannot_confirm_cutoff(started, finished):
    plan = SimpleNamespace(stage_id="STAGE_1300_1315", trade_date="20261013")
    evidence = _hk_futu_scan_evidence(
        vars(live), plan, datetime.fromisoformat(started), datetime.fromisoformat(finished), 1.0,
    )
    assert "futu_scan_clock_status=CANNOT_CONFIRM" in evidence
    assert "futu_scan_started_before_cutoff=CANNOT_CONFIRM" in evidence
    assert "futu_scan_finished_before_cutoff=CANNOT_CONFIRM" in evidence


def test_invocation_clock_normalizes_utc_to_cutoff_timezone():
    plan = SimpleNamespace(stage_id="STAGE_1445_1500", trade_date="20261013")
    evidence = _hk_futu_scan_evidence(
        vars(live), plan,
        datetime.fromisoformat("2026-10-13T06:59:50+00:00"),
        datetime.fromisoformat("2026-10-13T06:59:59+00:00"), 9.0,
    )
    assert "futu_scan_started_at=2026-10-13T14:59:50+08:00" in evidence
    assert "futu_scan_cutoff_at=2026-10-13T15:00:00+08:00" in evidence
    assert "futu_scan_clock_status=RECORDED" in evidence
    assert "futu_scan_finished_before_cutoff=true" in evidence
