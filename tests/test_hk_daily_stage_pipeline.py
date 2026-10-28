from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from stage_center.acquisition import SourceResult
from stage_center.calendar import TradingDayState
from stage_center.contracts import EIGHT_STAGES, HK_SNAPSHOT_SCHEDULE, SAFETY_FLAGS
from stage_center.hk_stage8.precapture import prepare_due_snapshot
from stage_center.hk_stage8.snapshot import (
    _atomic_snapshot_create,
    _snapshot_codes_sha,
    _snapshot_path,
    _snapshot_rows_sha,
    load_hk_active_snapshot,
    prepare_hk_active_snapshot,
)
import stage_center.hk_stage8.snapshot as snapshot_module
from stage_center.live_collectors import refresh_hk_active_lanes
from ops.run_stage_center_nodes import (
    NODE_BY_ID,
    NODE_IDS,
    NODE_MINUTES,
    PRECAPTURE_NODE_STAGE_BY_ID,
    _node_due,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
POOL_ARTIFACT_SHA = "c" * 64
STAGE_CODES = {
    "STAGE_0930_0935": ("HK.00001", "HK.00002"),
    "STAGE_0935_0940": ("HK.00003", "HK.00004"),
}


def _write_snapshot(
    root: Path,
    trade_date: str,
    stage_id: str,
    codes: tuple[str, ...],
    *,
    pool_artifact_sha256: str = POOL_ARTIFACT_SHA,
) -> Path:
    rows = [
        {
            "code": codes[0],
            "prev_close_price": 10.0,
            "last_price": 11.0,
            "turnover": 30_000_000.0,
            "volume_ratio": 2.0,
            "update_time": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} 09:34:00",
        },
        {
            "code": codes[1],
            "prev_close_price": 10.0,
            "last_price": 10.0,
            "turnover": 1_000_000.0,
            "volume_ratio": 0.5,
            "update_time": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} 09:34:00",
        },
    ]
    schedule = HK_SNAPSHOT_SCHEDULE[stage_id]
    provider_time = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T{schedule[0]}+08:00"
    path = _snapshot_path(root, trade_date, stage_id)
    payload = {
        "schema_version": "stage_center.hk_active_snapshot.v2",
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": "HK_CONNECT",
        "source_role": "FUTU_HKCONNECT_FULL_SCAN",
        "pool_artifact_sha256": pool_artifact_sha256,
        "codes": list(codes),
        "codes_sha256": _snapshot_codes_sha(codes),
        "requested_rows": len(codes),
        "returned_rows": len(rows),
        "full_coverage": True,
        "rows": rows,
        "snapshot_sha256": _snapshot_rows_sha(rows),
        "provider_started_at": provider_time,
        "provider_finished_at": provider_time,
        "captured_at": provider_time,
        "cutoff_at": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T{schedule[2]}",
        "temporal_cutoff_safe": True,
        **SAFETY_FLAGS,
    }
    assert _atomic_snapshot_create(path, payload)
    return path


def test_snapshot_schedule_preserves_stage_cutoffs_and_separates_auction() -> None:
    stage_cutoffs = {stage.stage_id: stage.cutoff for stage in EIGHT_STAGES}
    assert stage_cutoffs == {
        "STAGE_0925": "09:25:05",
        "STAGE_0930_0935": "09:35:05",
        "STAGE_0935_0940": "09:40:05",
        "STAGE_0940_0945": "09:45:05",
        "STAGE_0945_1030": "10:30:00",
        "STAGE_1300_1315": "13:15:00",
        "STAGE_1445_1500": "15:00:00",
        "STAGE_1545_1555": "15:55:05",
    }
    assert "STAGE_0925" not in HK_SNAPSHOT_SCHEDULE
    assert HK_SNAPSHOT_SCHEDULE == {
        "STAGE_0930_0935": ("09:34:00", "09:35:05", "09:35:05"),
        "STAGE_0935_0940": ("09:39:00", "09:40:05", "09:40:05"),
        "STAGE_0940_0945": ("09:44:00", "09:45:05", "09:45:05"),
        "STAGE_0945_1030": ("10:29:00", "10:30:00", "10:30:00"),
        "STAGE_1300_1315": ("13:14:00", "13:15:00", "13:15:00"),
        "STAGE_1445_1500": ("14:59:00", "15:00:00", "15:00:00"),
        "STAGE_1545_1555": ("15:50:00", "15:55:00", "15:55:00"),
    }


def test_stage_precapture_nodes_run_only_inside_the_exact_stage_window() -> None:
    ordinary_node_id = "PRECAPTURE_STAGE_0930_0935"
    stage8_node_id = "PRECAPTURE_1550"
    assert len(NODE_IDS) == 16
    assert PRECAPTURE_NODE_STAGE_BY_ID[ordinary_node_id] == "STAGE_0930_0935"
    assert NODE_MINUTES[ordinary_node_id] == (9, 34)
    assert NODE_MINUTES[stage8_node_id] == (15, 50)
    ordinary = NODE_BY_ID[ordinary_node_id]
    assert _node_due(ordinary, "20260911", datetime(2026, 9, 11, 9, 33, 59, tzinfo=SHANGHAI)) is False
    assert _node_due(ordinary, "20260911", datetime(2026, 9, 11, 9, 34, 0, tzinfo=SHANGHAI)) is True
    assert _node_due(ordinary, "20260911", datetime(2026, 9, 11, 9, 35, 5, tzinfo=SHANGHAI)) is True
    assert _node_due(ordinary, "20260911", datetime(2026, 9, 11, 9, 35, 6, tzinfo=SHANGHAI)) is False
    stage8 = NODE_BY_ID[stage8_node_id]
    assert _node_due(stage8, "20260911", datetime(2026, 9, 11, 15, 55, 0, tzinfo=SHANGHAI)) is True
    assert _node_due(stage8, "20260911", datetime(2026, 9, 11, 15, 55, 1, tzinfo=SHANGHAI)) is False


def test_snapshot_capture_rechecks_actual_clock_after_bridge_import_before_provider(
    monkeypatch, tmp_path: Path
) -> None:
    fetch_calls: list[object] = []
    runner_calls: list[object] = []

    def fetch(codes, *, process_runner):
        fetch_calls.append(tuple(codes))
        process_runner(["provider"])
        return [], []

    monkeypatch.setattr(
        snapshot_module,
        "_load_shared_module",
        lambda *_args: SimpleNamespace(fetch_futu_snapshot=fetch),
    )
    # This is the first wall-clock read after bridge import. The scheduler's
    # earlier evaluated_at remains inside the window, but the provider must
    # not be invoked at the exact exclusive cutoff.
    result = prepare_hk_active_snapshot(
        tmp_path / "raw",
        trade_date="20260911",
        stage_id="STAGE_0930_0935",
        codes=STAGE_CODES["STAGE_0930_0935"],
        python_path=tmp_path / "python",
        shared_root=tmp_path / "shared",
        evaluated_at="2026-09-11T09:34:59+08:00",
        cutoff_at="09:35:05",
        pool_artifact_sha256=POOL_ARTIFACT_SHA,
        process_runner=lambda *_args, **_kwargs: runner_calls.append(True),
        clock=lambda: datetime(2026, 9, 11, 9, 35, 5, tzinfo=SHANGHAI),
    )

    assert result["status"] == "CANNOT_CONFIRM"
    assert "HK_ACTIVE_SNAPSHOT_PROVIDER_WINDOW_EXPIRED" in result["cannot_confirm"]
    assert fetch_calls == []
    assert runner_calls == []
    assert "active_snapshot_provider_boundary_at=2026-09-11T09:35:05+08:00" in result["source_evidence"]
    assert not any("active_snapshot_provider_started_at=" in item for item in result["source_evidence"])
    assert not Path(result["snapshot_path"]).exists()


def test_snapshot_capture_rechecks_clock_at_external_runner_boundary(monkeypatch, tmp_path: Path) -> None:
    times = iter((
        datetime(2026, 9, 11, 9, 34, 59, tzinfo=SHANGHAI),
        datetime(2026, 9, 11, 9, 35, 5, tzinfo=SHANGHAI),
    ))
    fetch_calls: list[object] = []
    runner_calls: list[object] = []

    def fetch(codes, *, process_runner):
        fetch_calls.append(tuple(codes))
        process_runner(["provider"])
        return [], []

    monkeypatch.setattr(
        snapshot_module,
        "_load_shared_module",
        lambda *_args: SimpleNamespace(fetch_futu_snapshot=fetch),
    )
    result = prepare_hk_active_snapshot(
        tmp_path / "raw",
        trade_date="20260911",
        stage_id="STAGE_0930_0935",
        codes=STAGE_CODES["STAGE_0930_0935"],
        python_path=tmp_path / "python",
        shared_root=tmp_path / "shared",
        evaluated_at="2026-09-11T09:34:59+08:00",
        cutoff_at="09:35:05",
        pool_artifact_sha256=POOL_ARTIFACT_SHA,
        process_runner=lambda *_args, **_kwargs: runner_calls.append(True),
        clock=lambda: next(times),
    )

    assert result["status"] == "CANNOT_CONFIRM"
    assert "HK_ACTIVE_SNAPSHOT_PROVIDER_WINDOW_EXPIRED" in result["cannot_confirm"]
    assert fetch_calls == [STAGE_CODES["STAGE_0930_0935"]]
    assert runner_calls == []
    assert "active_snapshot_provider_boundary_at=2026-09-11T09:35:05+08:00" in result["source_evidence"]
    assert not any("active_snapshot_provider_started_at=" in item for item in result["source_evidence"])
    assert not Path(result["snapshot_path"]).exists()


def test_snapshot_capture_rejects_provider_result_at_cutoff_with_actual_times(
    monkeypatch, tmp_path: Path
) -> None:
    safe = datetime(2026, 9, 11, 9, 34, 59, tzinfo=SHANGHAI)
    cutoff = datetime(2026, 9, 11, 9, 35, 5, tzinfo=SHANGHAI)
    times = iter((safe, safe, datetime(2026, 9, 11, 9, 35, 4, tzinfo=SHANGHAI), cutoff))
    runner_calls: list[object] = []

    def fetch(codes, *, process_runner):
        process_runner(["provider"])
        return [
            {
                "code": code,
                "prev_close_price": 10,
                "last_price": 11,
                "turnover": 30_000_000,
                "volume_ratio": 2,
                "update_time": "2026-09-11 09:34:58",
            }
            for code in codes
        ], []

    monkeypatch.setattr(
        snapshot_module,
        "_load_shared_module",
        lambda *_args: SimpleNamespace(fetch_futu_snapshot=fetch),
    )
    result = prepare_hk_active_snapshot(
        tmp_path / "raw",
        trade_date="20260911",
        stage_id="STAGE_0930_0935",
        codes=STAGE_CODES["STAGE_0930_0935"],
        python_path=tmp_path / "python",
        shared_root=tmp_path / "shared",
        evaluated_at="2026-09-11T09:34:59+08:00",
        cutoff_at="09:35:05",
        pool_artifact_sha256=POOL_ARTIFACT_SHA,
        process_runner=lambda *_args, **_kwargs: runner_calls.append(True),
        clock=lambda: next(times),
    )

    assert result["status"] == "CANNOT_CONFIRM"
    assert "HK_ACTIVE_SNAPSHOT_PROVIDER_WINDOW_EXPIRED" in result["cannot_confirm"]
    assert runner_calls == [True]
    assert "active_snapshot_provider_started_at=2026-09-11T09:34:59+08:00" in result["source_evidence"]
    assert "active_snapshot_provider_finished_at=2026-09-11T09:35:05+08:00" in result["source_evidence"]
    assert not Path(result["snapshot_path"]).exists()


def test_snapshot_capture_persists_actual_provider_times_and_pool_artifact_sha(monkeypatch, tmp_path: Path) -> None:
    times = iter((
        datetime(2026, 9, 11, 9, 34, 30, tzinfo=SHANGHAI),
        datetime(2026, 9, 11, 9, 34, 31, tzinfo=SHANGHAI),
        datetime(2026, 9, 11, 9, 34, 50, tzinfo=SHANGHAI),
        datetime(2026, 9, 11, 9, 34, 51, tzinfo=SHANGHAI),
    ))

    def fetch(codes, *, process_runner):
        process_runner(["provider"])
        return [
            {
                "code": code,
                "prev_close_price": 10,
                "last_price": 11,
                "turnover": 30_000_000,
                "volume_ratio": 2,
                "update_time": "2026-09-11 09:34:40",
            }
            for code in codes
        ], []

    monkeypatch.setattr(
        snapshot_module,
        "_load_shared_module",
        lambda *_args: SimpleNamespace(fetch_futu_snapshot=fetch),
    )
    result = prepare_hk_active_snapshot(
        tmp_path / "raw",
        trade_date="20260911",
        stage_id="STAGE_0930_0935",
        codes=STAGE_CODES["STAGE_0930_0935"],
        python_path=tmp_path / "python",
        shared_root=tmp_path / "shared",
        evaluated_at="2026-09-11T09:34:12+08:00",
        cutoff_at="09:35:05",
        pool_artifact_sha256=POOL_ARTIFACT_SHA,
        process_runner=lambda *_args, **_kwargs: object(),
        clock=lambda: next(times),
    )

    assert result["status"] == "READY"
    payload = json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8"))
    assert payload["pool_artifact_sha256"] == POOL_ARTIFACT_SHA
    assert payload["provider_started_at"] == "2026-09-11T09:34:31+08:00"
    assert payload["provider_finished_at"] == "2026-09-11T09:34:51+08:00"
    assert payload["captured_at"] == payload["provider_finished_at"]
    loaded = load_hk_active_snapshot(
        tmp_path / "raw",
        trade_date="20260911",
        stage_id="STAGE_0930_0935",
        codes=STAGE_CODES["STAGE_0930_0935"],
        cutoff_at="09:35:05",
        pool_artifact_sha256=POOL_ARTIFACT_SHA,
    )
    assert loaded["status"] == "READY"


def test_precapture_uses_actual_time_and_per_stage_cutoff_for_multiple_dates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "stage_center.hk_stage8.precapture.resolve_market_states",
        lambda _date: {
            "hk_securities": TradingDayState.FULL_TRADING_DAY,
            "hk_connect": TradingDayState.FULL_TRADING_DAY,
        },
    )
    config = SimpleNamespace(
        injected_test_mode=False,
        hk_d1_root=tmp_path / "d1",
        hk_full_universe_root=None,
        shared_data_root=tmp_path / "shared",
        python_path=tmp_path / "python",
        raw_root=tmp_path / "raw",
    )
    prepared: list[dict[str, object]] = []

    def universe_loader():
        return tmp_path / "pool.json", STAGE_CODES["STAGE_0930_0935"], "a" * 64

    def snapshot_preparer(root, **kwargs):
        prepared.append({"root": root, **kwargs})
        return {"status": "READY", "write_performed": True}

    first = prepare_due_snapshot(
        config,
        "20260911",
        datetime(2026, 9, 11, 9, 34, 12, tzinfo=SHANGHAI),
        stage_id="STAGE_0930_0935",
        historical_backfill=False,
        universe_loader=universe_loader,
        snapshot_preparer=snapshot_preparer,
    )
    second = prepare_due_snapshot(
        config,
        "20260914",
        datetime(2026, 9, 14, 9, 39, 7, tzinfo=SHANGHAI),
        stage_id="STAGE_0935_0940",
        historical_backfill=False,
        universe_loader=universe_loader,
        snapshot_preparer=snapshot_preparer,
    )
    before = prepare_due_snapshot(
        config,
        "20260914",
        datetime(2026, 9, 14, 9, 38, 59, tzinfo=SHANGHAI),
        stage_id="STAGE_0935_0940",
        historical_backfill=False,
        universe_loader=universe_loader,
        snapshot_preparer=snapshot_preparer,
    )
    after = prepare_due_snapshot(
        config,
        "20260914",
        datetime(2026, 9, 14, 9, 40, 6, tzinfo=SHANGHAI),
        stage_id="STAGE_0935_0940",
        historical_backfill=False,
        universe_loader=universe_loader,
        snapshot_preparer=snapshot_preparer,
    )

    assert len(first) == len(second) == 1
    assert first[0]["capture_window_start"] == "2026-09-11T09:34:00+08:00"
    assert first[0]["capture_window_end"] == "2026-09-11T09:35:05+08:00"
    assert second[0]["capture_window_start"] == "2026-09-14T09:39:00+08:00"
    assert second[0]["capture_window_end"] == "2026-09-14T09:40:05+08:00"
    assert prepared[0]["evaluated_at"] == "2026-09-11T09:34:12+08:00"
    assert prepared[0]["pool_artifact_sha256"] == "a" * 64
    assert prepared[0]["cutoff_at"] == "09:35:05"
    assert prepared[1]["evaluated_at"] == "2026-09-14T09:39:07+08:00"
    assert prepared[1]["cutoff_at"] == "09:40:05"
    assert before == after == []
    assert len(prepared) == 2


def test_normal_and_recovery_reuse_one_persisted_snapshot_without_provider_calls(tmp_path: Path) -> None:
    trade_date = "20260911"
    stage_id = "STAGE_0930_0935"
    codes = STAGE_CODES[stage_id]
    path = _write_snapshot(tmp_path / "raw", trade_date, stage_id, codes)
    loaded = load_hk_active_snapshot(
        tmp_path / "raw",
        trade_date=trade_date,
        stage_id=stage_id,
        codes=codes,
        cutoff_at="09:35:05",
        pool_artifact_sha256=POOL_ARTIFACT_SHA,
    )
    assert loaded["status"] == "READY"

    def forbidden_provider(*_args, **_kwargs):
        raise AssertionError("normal/recovery consumers must not call Futu inline")

    source = SourceResult(
        source_id="pytdx_exhq",
        status="READY",
        requested_rows=len(codes),
        rows=tuple({"code": code, "candidate_lanes": ["STALE"]} for code in codes),
    )
    kwargs = {
        "codes": codes,
        "python_path": tmp_path / "python",
        "shared_root": tmp_path / "shared",
        "snapshot_root": tmp_path / "raw",
        "process_runner": forbidden_provider,
        "trade_date": trade_date,
        "stage_id": stage_id,
        "cutoff_at": "09:35:05",
        "pool_artifact_sha256": POOL_ARTIFACT_SHA,
    }
    normal = refresh_hk_active_lanes(source, **kwargs)
    recovery = refresh_hk_active_lanes(normal, **kwargs)

    assert path.is_file()
    assert normal.status == recovery.status == "READY"
    assert normal.rows[0]["candidate_lanes"] == ["LIVE_HKCONNECT_GAINER"]
    assert normal.rows[1]["candidate_lanes"] == []
    assert recovery.rows[0]["candidate_lanes"] == normal.rows[0]["candidate_lanes"]
    assert recovery.rows[1]["candidate_lanes"] == []
    expected = f"active_snapshot_sha256={loaded['active_snapshot_sha256']}"
    assert expected in normal.source_evidence
    assert expected in recovery.source_evidence
    assert "active_snapshot_source=PERSISTED_EXACT_STAGE" in normal.source_evidence


def test_same_codes_with_different_d1_pool_artifact_sha_are_rejected(tmp_path: Path) -> None:
    trade_date = "20260911"
    stage_id = "STAGE_0930_0935"
    codes = STAGE_CODES[stage_id]
    _write_snapshot(tmp_path / "raw", trade_date, stage_id, codes)
    changed_pool_sha = "d" * 64
    loaded = load_hk_active_snapshot(
        tmp_path / "raw",
        trade_date=trade_date,
        stage_id=stage_id,
        codes=codes,
        cutoff_at="09:35:05",
        pool_artifact_sha256=changed_pool_sha,
    )
    assert loaded["status"] == "CANNOT_CONFIRM"
    assert "HK_ACTIVE_SNAPSHOT_POOL_ARTIFACT_SHA_MISMATCH" in loaded["cannot_confirm"]

    source = SourceResult(
        source_id="pytdx_exhq",
        status="READY",
        rows=tuple(
            {"code": code, "candidate_lanes": ["LIVE_HKCONNECT_GAINER"], "active_gainer_pass": True}
            for code in codes
        ),
    )
    recovered = refresh_hk_active_lanes(
        source,
        codes=codes,
        python_path=tmp_path / "python",
        shared_root=tmp_path / "shared",
        snapshot_root=tmp_path / "raw",
        trade_date=trade_date,
        stage_id=stage_id,
        cutoff_at="09:35:05",
        pool_artifact_sha256=changed_pool_sha,
    )
    assert "HK_ACTIVE_SNAPSHOT_POOL_ARTIFACT_SHA_MISMATCH" in recovered.cannot_confirm
    assert all(row["candidate_lanes"] == [] for row in recovered.rows)
    assert all(row.get("active_gainer_pass") is None for row in recovered.rows)


def test_missing_or_wrong_snapshot_fails_closed_and_clears_stale_active_lane(tmp_path: Path) -> None:
    source = SourceResult(
        source_id="pytdx_exhq",
        status="READY",
        rows=(
            {
                "code": "HK.00001",
                "candidate_lanes": ["LIVE_HKCONNECT_GAINER"],
                "active_gainer_pass": True,
                "active_snapshot_status": "FUTU_HKCONNECT_FULL_SCAN",
                "volume_ratio": 3.0,
            },
        ),
    )
    missing = refresh_hk_active_lanes(
        source,
        codes=STAGE_CODES["STAGE_0930_0935"],
        python_path=tmp_path / "python",
        shared_root=tmp_path / "shared",
        snapshot_root=tmp_path / "missing",
        trade_date="20260911",
        stage_id="STAGE_0930_0935",
        cutoff_at="09:35:05",
        pool_artifact_sha256=POOL_ARTIFACT_SHA,
    )
    wrong_cutoff = refresh_hk_active_lanes(
        source,
        codes=STAGE_CODES["STAGE_0930_0935"],
        python_path=tmp_path / "python",
        shared_root=tmp_path / "shared",
        snapshot_root=tmp_path / "missing",
        trade_date="20260911",
        stage_id="STAGE_0930_0935",
        cutoff_at="09:40:05",
        pool_artifact_sha256=POOL_ARTIFACT_SHA,
    )
    assert missing.rows[0]["candidate_lanes"] == []
    assert missing.rows[0].get("active_gainer_pass") is None
    assert missing.rows[0].get("active_snapshot_status") is None
    assert "HK_ACTIVE_SNAPSHOT_UNAVAILABLE" in missing.cannot_confirm
    assert wrong_cutoff.rows[0]["candidate_lanes"] == []
    assert "HK_ACTIVE_SNAPSHOT_CUTOFF_MISMATCH" in wrong_cutoff.cannot_confirm
