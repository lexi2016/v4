from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import stage_center.live_collectors as live_collectors


TRADE_DATE = "20260928"
STAGE_ID = "STAGE_0930_0935"
ROW = {
    "code": "HK.00001",
    "open_price": 10.0,
    "last_price": 10.5,
    "volume": 100,
    "update_time": "2026-09-28 09:35:06",
}


def _plan(*, historical_backfill: bool) -> SimpleNamespace:
    return SimpleNamespace(
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        historical_backfill=historical_backfill,
    )


def _install_unsafe_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(live_collectors, "_shared_scripts_root", lambda _root: Path("/synthetic"))
    monkeypatch.setattr(live_collectors, "_scoped_process_runner", lambda _root, runner: runner)
    monkeypatch.setattr(
        live_collectors,
        "_load_shared_module",
        lambda *_args: SimpleNamespace(
            collect_pytdx_exhq_minute=lambda *_args, **_kwargs: SimpleNamespace(
                status="READY",
                rows=(dict(ROW),),
                requested_code_count=1,
            )
        ),
    )

    def unsafe(*_args, **_kwargs):
        return {}, (
            "active_snapshot_status=FUTU_HKCONNECT_FULL_SCAN",
            "active_snapshot_trade_date=20260928",
            "active_snapshot_cutoff=09:35:05",
            "active_snapshot_codes_sha256=" + "a" * 64,
            "active_snapshot_sha256=" + "b" * 64,
            "active_snapshot_temporal_cutoff_safe=false",
        ), ("HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",)

    monkeypatch.setattr(live_collectors, "_futu_hkconnect_active_snapshot", unsafe)


def _collect(monkeypatch, *, historical_backfill: bool):
    _install_unsafe_snapshot(monkeypatch)
    return live_collectors.collect_hk_minute(
        _plan(historical_backfill=historical_backfill),
        codes=("HK.00001",),
        python_path="synthetic-python",
        shared_root=Path("/synthetic"),
        process_runner=lambda *_args, **_kwargs: None,
    )


def test_historical_backfill_keeps_exhq_rows_as_partial_observation(monkeypatch):
    result = _collect(monkeypatch, historical_backfill=True)

    assert result.status == "PARTIAL_WITH_ROWS"
    assert result.rows == (ROW,)
    assert "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in result.cannot_confirm
    assert "active_snapshot_degraded_to_pytdx_observation=true" in result.source_evidence
    assert "active_snapshot_sha256=" + "b" * 64 in result.source_evidence
    assert "active_snapshot_codes_sha256=" + "a" * 64 in result.source_evidence
    assert "LIVE_HKCONNECT_GAINER" not in str(result.rows)
    assert "candidate_lanes" not in result.rows[0]
    assert "volume_ratio" not in result.rows[0]
    assert "active_gainer_pass" not in result.rows[0]
    assert "active_snapshot_status" not in result.rows[0]


def test_natural_run_still_discards_exhq_rows_on_unsafe_snapshot(monkeypatch):
    result = _collect(monkeypatch, historical_backfill=False)

    assert result.status == "CANNOT_CONFIRM"
    assert result.rows == ()
    assert "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in result.cannot_confirm
    assert "active_snapshot_degraded_to_pytdx_observation=true" not in result.source_evidence
