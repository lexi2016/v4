"""Deterministic synthetic bridge/selection tests; no market-data acceptance."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from stage_center import live_collectors as live
from stage_center.acquisition import SourceResult
from stage_center.contracts import EIGHT_STAGES, SAFETY_FLAGS
from stage_center.selection import SelectionStore

INTRADAY = [s.stage_id for s in EIGHT_STAGES
            if s.stage_id not in {"STAGE_0925", "STAGE_1545_1555"}]


def synthetic_source():
    return SourceResult("pytdx_exhq", "READY", tuple(
        {"code": f"HK.{i:05d}", "trade_date": "20260928", "name": f"SYNTHETIC {i}",
         "open_price": 10.0, "last_price": 10.1, "prev_close_price": 10.0,
         "high_price": 10.2, "low_price": 9.9, "turnover": 30_000_000,
         "update_time": "2026-09-28T09:35:00+08:00"} for i in range(1, 13)),
        requested_rows=12, source_evidence=("fixture=SYNTHETIC_NOT_MARKET_DATA",))


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    calls = []
    source = synthetic_source()
    monkeypatch.setattr(live, "_shared_scripts_root", lambda root: tmp_path)
    monkeypatch.setattr(live, "_scoped_process_runner", lambda root, runner: runner)
    def collect(*args, **kwargs):
        calls.append((args, kwargs))
        return source
    monkeypatch.setattr(live, "_load_shared_module", lambda *args:
                        SimpleNamespace(collect_pytdx_exhq_minute=collect))
    monkeypatch.setattr(live, "_to_source", lambda result, **kwargs: result)
    def probe(*args, **kwargs):
        return {}, ("active_snapshot_temporal_cutoff_safe=false",), (
            "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",)
    monkeypatch.setattr(live, "_futu_hkconnect_active_snapshot", probe)
    return source, calls


@pytest.mark.parametrize("stage_id", INTRADAY)
def test_historical_bars_reach_original_selector_and_store(bridge, tmp_path, stage_id):
    source, calls = bridge
    original = deepcopy(source.rows)
    codes = tuple(r["code"] for r in source.rows)
    plan = SimpleNamespace(trade_date="20260928", stage_id=stage_id, historical_backfill=True)
    actual = live.collect_hk_minute(plan, codes=codes, python_path="synthetic-python",
                                  shared_root=tmp_path)
    assert actual.status == "PARTIAL_WITH_ROWS"
    assert len(actual.rows) == 12
    assert "HK_FUTU_HISTORICAL_ACTIVE_SNAPSHOT_UNAVAILABLE" in actual.cannot_confirm
    assert "active_snapshot_degraded_to_pytdx_observation=true" in actual.source_evidence
    assert all(r.get("candidate_lanes") == [] for r in actual.rows)
    assert source.rows == original
    assert calls[0][0][1:4] == (plan.trade_date, stage_id, list(codes))
    raw = {"artifact_sha256": "a" * 64, "status": actual.status,
           "requested_rows": 12, "missing_symbols": [], "cannot_confirm": actual.cannot_confirm,
           "source_evidence": actual.source_evidence, "cutoff_at": "15:00:00"}
    result = live.production_selection_builders(stage_id)["HK_CONNECT"](actual, plan, raw)
    assert result["source_rows"] == 12
    assert len(result["rows"]) == 10
    assert result["selection_status"] == "PARTIAL_WITH_ROWS"
    assert "hk_selection_mode=TDXPY_EXHQ_D1_TOP100_OBSERVATION" in result["source_evidence"]
    assert all(r["action_level"] == "NO_BUY" and r["formal_eligible"] is False for r in result["rows"])
    assert {r["trade_status"] for r in result["rows"]} == {"NO_TRADE"}
    assert all(result[k] is False for k in SAFETY_FLAGS)
    store = SelectionStore(tmp_path / "selection" / stage_id)
    store.publish(result, market="HK_CONNECT")
    assert store.read_verified(plan.trade_date, stage_id, "HK_CONNECT") == result


def test_natural_run_still_rejects_unsafe_active_snapshot(bridge, tmp_path):
    source, _ = bridge
    plan = SimpleNamespace(trade_date="20260928", stage_id=INTRADAY[0], historical_backfill=False)
    actual = live.collect_hk_minute(plan, codes=[r["code"] for r in source.rows],
                                  python_path="synthetic", shared_root=tmp_path)
    assert actual.status == "CANNOT_CONFIRM" and actual.rows == ()
    assert "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in actual.cannot_confirm
    assert "active_snapshot_degraded_to_pytdx_observation=true" not in actual.source_evidence


def test_live_valid_snapshot_keeps_existing_trigger(bridge, monkeypatch, tmp_path):
    source, _ = bridge
    monkeypatch.setattr(live, "_futu_hkconnect_active_snapshot", lambda *args, **kw:
                        ({"HK.00001": {"volume_ratio": 2}}, (), ()))
    actual = live.refresh_hk_active_lanes(source, codes=["HK.00001"], python_path="synthetic",
                                        shared_root=tmp_path, trade_date="20260928",
                                        stage_id=INTRADAY[0], cutoff_at="09:35:00")
    assert actual.rows[0]["candidate_lanes"] == ["LIVE_HKCONNECT_GAINER"]
    assert actual.rows[0]["active_gainer_pass"] is True


def test_hk_stage8_does_not_fall_back_to_exhq(bridge, monkeypatch, tmp_path):
    source, calls = bridge
    expected = SourceResult("hk_stage8", "CANNOT_CONFIRM", cannot_confirm=("MISSING_REPLAY",))
    monkeypatch.setattr(live, "_collect_hk_stage8_replay", lambda *args, **kwargs: expected)
    actual = live.collect_hk_minute(SimpleNamespace(stage_id="STAGE_1545_1555", historical_backfill=True),
                                  codes=["HK.00001"], python_path="synthetic", shared_root=tmp_path)
    assert actual is expected and calls == []


def test_historical_mode_does_not_promote_failed_source(bridge, tmp_path):
    source, _ = bridge
    actual = live.refresh_hk_active_lanes(replace(source, status="CANNOT_CONFIRM"),
        codes=[r["code"] for r in source.rows], python_path="synthetic", shared_root=tmp_path,
        trade_date="20260928", stage_id=INTRADAY[0], cutoff_at="09:35:00", historical_backfill=True)
    assert actual.status == "CANNOT_CONFIRM" and actual.rows == ()
