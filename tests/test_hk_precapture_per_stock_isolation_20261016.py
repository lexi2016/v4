from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import stage_center.hk_stage8.snapshot as snapshot_module
from stage_center.acquisition import SourceResult
from stage_center.hk_stage8 import load_hk_active_snapshot, prepare_hk_active_snapshot
from stage_center.live_collectors import production_selection_builders, refresh_hk_active_lanes


SHANGHAI = ZoneInfo("Asia/Shanghai")
TRADE_DATE = "20261016"
STAGE_ID = "STAGE_0930_0935"
POOL_SHA = "b" * 64
CODES = tuple(f"HK.{number:05d}" for number in range(1, 101))


def _prepare_snapshot(monkeypatch, root: Path, *, invalid_timestamp: str, missing_code: bool = False, errors=()):
    times = iter((
        datetime(2026, 10, 16, 9, 34, 10, tzinfo=SHANGHAI),
        datetime(2026, 10, 16, 9, 34, 11, tzinfo=SHANGHAI),
        datetime(2026, 10, 16, 9, 34, 12, tzinfo=SHANGHAI),
        datetime(2026, 10, 16, 9, 34, 13, tzinfo=SHANGHAI),
    ))

    def fetch(codes, *, process_runner):
        process_runner(["provider"])
        requested = list(codes)
        if missing_code:
            requested = requested[:-1]
        rows = [
            {
                "code": code,
                "prev_close_price": 10,
                "last_price": 11,
                "turnover": 30_000_000,
                "volume_ratio": 2,
                "update_time": invalid_timestamp if code == CODES[3] else "2026-10-16 09:34:00",
            }
            for code in requested
        ]
        return rows, list(errors)

    monkeypatch.setattr(
        snapshot_module,
        "_load_shared_module",
        lambda *_args: SimpleNamespace(fetch_futu_snapshot=fetch),
    )
    return prepare_hk_active_snapshot(
        root,
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        codes=CODES,
        python_path=root / "python",
        shared_root=root / "shared",
        evaluated_at="2026-10-16T09:34:09+08:00",
        cutoff_at="09:35:05",
        pool_artifact_sha256=POOL_SHA,
        process_runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
        clock=lambda: next(times),
    )


def test_single_stale_quote_is_retained_audited_and_excluded_from_selection(monkeypatch, tmp_path):
    stale_code = CODES[3]
    prepared = _prepare_snapshot(
        monkeypatch,
        tmp_path / "raw",
        invalid_timestamp="2026-10-15 16:07:44",
    )

    assert prepared["status"] == "PARTIAL_WITH_ROWS"
    assert (prepared["requested_rows"], prepared["returned_rows"]) == (100, 100)
    assert (prepared["eligible_rows_count"], prepared["excluded_rows_count"]) == (99, 1)
    assert prepared["exclusions"] == [{"code": stale_code, "reason": "wrong_trade_date"}]

    loaded = load_hk_active_snapshot(
        tmp_path / "raw",
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        codes=CODES,
        cutoff_at="09:35:05",
        pool_artifact_sha256=POOL_SHA,
    )
    assert loaded["status"] == "PARTIAL_WITH_ROWS"
    assert len(loaded["rows"]) == 100
    assert len(loaded["eligible_rows"]) == 99
    assert len(loaded["excluded_rows"]) == 1
    assert loaded["by_code"][stale_code]["active_snapshot_eligible"] is False
    assert loaded["by_code"][stale_code]["active_snapshot_exclusion_reason"] == "wrong_trade_date"

    source = SourceResult(
        source_id="pytdx_exhq",
        status="READY",
        requested_rows=100,
        rows=tuple({
            "code": code,
            "prev_close_price": 10,
            "last_price": 11,
            "turnover": 30_000_000,
            "volume_ratio": 2,
        } for code in CODES),
    )
    refreshed = refresh_hk_active_lanes(
        source,
        codes=CODES,
        python_path=tmp_path / "python",
        shared_root=tmp_path / "shared",
        snapshot_root=tmp_path / "raw",
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        cutoff_at="09:35:05",
        pool_artifact_sha256=POOL_SHA,
    )
    assert refreshed.status == "PARTIAL_WITH_ROWS"
    assert len(refreshed.rows) == 100
    assert sum(row.get("active_snapshot_eligible") is True for row in refreshed.rows) == 99
    assert sum(row.get("active_snapshot_eligible") is False for row in refreshed.rows) == 1
    assert refreshed.missing_symbols == ()

    builder = production_selection_builders(STAGE_ID)["HK_CONNECT"]
    selection = builder(
        refreshed,
        SimpleNamespace(trade_date=TRADE_DATE, stage_id=STAGE_ID),
        {
            "status": "READY",
            "artifact_sha256": "c" * 64,
            "requested_rows": 100,
            "missing_symbols": (),
            "cannot_confirm": (),
            "source_evidence": (),
        },
    )
    assert selection["selection_status"] == "PARTIAL_WITH_ROWS"
    assert selection["requested_rows"] == 100
    assert selection["source_rows"] == 99
    assert selection["selected_rows"] <= 10
    assert stale_code not in {row["code"] for row in selection["rows"]}
    assert selection["missing_symbols"] == []
    assert "active_snapshot_eligible_rows=99" in selection["source_evidence"]
    assert "active_snapshot_excluded_rows=1" in selection["source_evidence"]
    assert any("wrong_trade_date" in item and stale_code in item for item in selection["source_evidence"])


@pytest.mark.parametrize(
    ("invalid_timestamp", "reason"),
    [
        ("2026-10-15 16:07:44", "wrong_trade_date"),
        ("2026-10-16 10:30:06", "after_cutoff"),
    ],
)
def test_zero_eligible_rows_remains_fail_closed_without_snapshot_write(
    monkeypatch, tmp_path, invalid_timestamp, reason
):
    # Every quote is invalid for this exact stage cutoff, including the first
    # row whose timestamp is the parameterized failure case.
    times = iter((
        datetime(2026, 10, 16, 9, 34, 10, tzinfo=SHANGHAI),
        datetime(2026, 10, 16, 9, 34, 11, tzinfo=SHANGHAI),
        datetime(2026, 10, 16, 9, 34, 12, tzinfo=SHANGHAI),
        datetime(2026, 10, 16, 9, 34, 13, tzinfo=SHANGHAI),
    ))

    def fetch(codes, *, process_runner):
        process_runner(["provider"])
        timestamp = invalid_timestamp if reason == "wrong_trade_date" else "2026-10-16 09:35:06"
        return [
            {
                "code": code,
                "prev_close_price": 10,
                "last_price": 11,
                "turnover": 30_000_000,
                "volume_ratio": 2,
                "update_time": timestamp,
            }
            for code in codes
        ], []

    monkeypatch.setattr(
        snapshot_module,
        "_load_shared_module",
        lambda *_args: SimpleNamespace(fetch_futu_snapshot=fetch),
    )
    raw_root = tmp_path / "raw"
    result = prepare_hk_active_snapshot(
        raw_root,
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        codes=CODES,
        python_path=tmp_path / "python",
        shared_root=tmp_path / "shared",
        evaluated_at="2026-10-16T09:34:09+08:00",
        cutoff_at="09:35:05",
        pool_artifact_sha256=POOL_SHA,
        process_runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
        clock=lambda: next(times),
    )

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["eligible_rows_count"] == 0
    assert result["excluded_rows_count"] == 100
    assert "HK_ACTIVE_SNAPSHOT_NO_ELIGIBLE_ROWS" in result["cannot_confirm"]
    assert not Path(result["snapshot_path"]).exists()


@pytest.mark.parametrize(
    ("missing_code", "errors", "reason"),
    [
        (True, (), "HK_ACTIVE_SNAPSHOT_FULL_COVERAGE_MISSING"),
        (False, ("provider_unavailable",), "provider_unavailable"),
    ],
)
def test_incomplete_coverage_or_provider_errors_still_fail_closed(
    monkeypatch, tmp_path, missing_code, errors, reason
):
    result = _prepare_snapshot(
        monkeypatch,
        tmp_path / "raw",
        invalid_timestamp="2026-10-15 16:07:44",
        missing_code=missing_code,
        errors=errors,
    )
    assert result["status"] == "CANNOT_CONFIRM"
    assert reason in result["cannot_confirm"]
    assert not Path(result["snapshot_path"]).exists()

