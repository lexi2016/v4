from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stage_center import live_collectors as lc
from stage_center.acquisition import SourceResult
from stage_center.raw_store import RAW_FIELDS


TRADE_DATE = "20260921"
STAGE_ID = "STAGE_0930_0935"
ORIGINAL_CUTOFF = "09:35:05"
SHANGHAI = timezone(timedelta(hours=8))


def _stamp(clock: str, *, trade_date: str = TRADE_DATE) -> str:
    return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} {clock}"


def _minute_source(
    *,
    rows: tuple[dict, ...] | None = None,
    status: str = "READY",
    trade_date: str = TRADE_DATE,
    window_end: str = "09:34:00",
) -> SourceResult:
    if rows is None:
        rows = (
            {
                "code": "HK.00001",
                "update_time": _stamp(window_end, trade_date=trade_date),
                "window_start": _stamp("09:31:00", trade_date=trade_date),
                "window_end": _stamp(window_end, trade_date=trade_date),
                "bar_count": 4,
                "temporal_cutoff_safe": True,
                "last": 10.0,
                "prev_close": 9.0,
                "last_price": 10.0,
                "prev_close_price": 9.0,
                "turnover": 30_000_000.0,
                "volume_ratio": 1.5,
                "candidate_lanes": ["LIVE_HKCONNECT_GAINER"],
                "source_universe": "HK_CONNECT_D1_TOP100",
                "data_confidence": "STAGE_RTDATA_CONFIRMED",
                "active_gainer_pass": True,
                "active_snapshot_status": "FUTU_HKCONNECT_FULL_SCAN",
            },
        )
    return SourceResult(
        "pytdx_exhq",
        status,
        rows=rows,
        requested_rows=1,
        source_evidence=("route=shared_pytdx_exhq_hk_exact_d1_top100",),
    )


class _FakeAuctionModule:
    snapshot_rows: list[dict] = []
    called = 0

    @classmethod
    def fetch_futu_snapshot(cls, codes, *, process_runner):
        cls.called += 1
        return list(cls.snapshot_rows), []


def _refresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    source: SourceResult | None = None,
    stage_id: str = STAGE_ID,
    cutoff_at: str = ORIGINAL_CUTOFF,
    snapshot_time: str = "09:35:00",
    capture_times: tuple[str, str] = ("09:34:59", "09:35:00"),
    capture_trade_date: str = TRADE_DATE,
    allow_natural_capture: bool = True,
    auction_module=_FakeAuctionModule,
) -> SourceResult:
    _FakeAuctionModule.called = 0
    _FakeAuctionModule.snapshot_rows = [
        {
            "code": "HK.00001",
            "update_time": _stamp(snapshot_time),
            "last": 10.5,
            "prev_close": 10.0,
            "turnover": 30_000_000.0,
            "volume_ratio": 1.5,
        }
    ]
    monkeypatch.setattr(lc, "_load_shared_module", lambda _root, _name: auction_module)
    clocks = iter(
        datetime.fromisoformat(_stamp(value, trade_date=capture_trade_date)).replace(tzinfo=SHANGHAI)
        for value in capture_times
    )
    # ``raising=False`` keeps the pre-fix reproduction meaningful: the old
    # collector has no wall-clock capture seam and still clears the rows.
    monkeypatch.setattr(lc, "_now_shanghai", lambda: next(clocks), raising=False)
    return lc.refresh_hk_active_lanes(
        source or _minute_source(),
        codes=("HK.00001",),
        python_path=Path("/tmp/python"),
        shared_root=tmp_path,
        process_runner=lambda *args, **kwargs: None,
        trade_date=TRADE_DATE,
        stage_id=stage_id,
        cutoff_at=cutoff_at,
        allow_natural_capture=allow_natural_capture,
    )


def test_normal_capture_keeps_live_lane(monkeypatch, tmp_path):
    result = _refresh(monkeypatch, tmp_path)

    assert len(result.rows) == 1
    assert result.rows[0]["candidate_lanes"] == ["LIVE_HKCONNECT_GAINER"]
    assert result.rows[0]["active_snapshot_update_time"] == _stamp("09:35:00")
    assert "active_snapshot_temporal_cutoff_safe=true" in result.source_evidence
    assert "active_snapshot_original_cutoff=09:35:05" in result.source_evidence
    assert "active_snapshot_effective_cutoff=09:37:00" in result.source_evidence


def test_grace_deadline_is_inclusive_and_records_real_capture(monkeypatch, tmp_path):
    result = _refresh(
        monkeypatch,
        tmp_path,
        snapshot_time="09:37:00",
        capture_times=("09:36:59", "09:37:00"),
    )

    assert len(result.rows) == 1
    assert result.rows[0]["candidate_lanes"] == ["LIVE_HKCONNECT_GAINER"]
    assert "active_snapshot_effective_cutoff=09:37:00" in result.source_evidence
    assert "active_snapshot_capture_started_at=2026-09-21T09:36:59+08:00" in result.source_evidence
    assert "active_snapshot_captured_at=2026-09-21T09:37:00+08:00" in result.source_evidence


@pytest.mark.parametrize(
    ("stage_id", "pit_cutoff", "execution_cutoff"),
    (
        ("STAGE_0930_0935", "09:35:05", "09:37:00"),
        ("STAGE_0935_0940", "09:40:05", "09:41:00"),
        ("STAGE_0940_0945", "09:45:05", "09:46:00"),
        ("STAGE_0945_1030", "10:30:00", "10:31:00"),
        ("STAGE_1300_1315", "13:15:00", "13:16:00"),
        ("STAGE_1445_1500", "15:00:00", "15:01:00"),
    ),
)
def test_active_execution_cutoff_reuses_existing_deadline_table(
    stage_id,
    pit_cutoff,
    execution_cutoff,
):
    cutoff, grace, source = lc._active_execution_cutoff(TRADE_DATE, stage_id, pit_cutoff)

    assert cutoff is not None
    assert cutoff.strftime("%H:%M:%S") == execution_cutoff
    assert grace >= 0
    assert source in {
        "ops.run_stage_center_tick._DEADLINE_STAGE_BY_CLOCK",
        "stage_center_existing_deadline_fallback",
    }


def test_after_grace_keeps_exact_minute_observation_and_clears_old_active_fields(monkeypatch, tmp_path):
    source = _minute_source()
    source = SourceResult(
        source.source_id,
        source.status,
        rows=source.rows,
        requested_rows=source.requested_rows,
        source_evidence=source.source_evidence
        + (
            "active_snapshot_temporal_cutoff_safe=true",
            "active_snapshot_execution_status=PIT_CONFIRMED",
        ),
    )
    result = _refresh(
        monkeypatch,
        tmp_path,
        source=source,
        snapshot_time="09:37:01",
        capture_times=("09:37:00", "09:37:01"),
    )

    assert result.status == "PARTIAL_WITH_ROWS"
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["candidate_lanes"] == []
    for field in (
        "source_universe",
        "data_confidence",
        "active_gainer_pass",
        "active_snapshot_status",
        "active_snapshot_update_time",
    ):
        assert field not in row
    assert "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in result.cannot_confirm
    assert "active_snapshot_temporal_cutoff_safe=false" in result.source_evidence
    assert "active_snapshot_temporal_cutoff_safe=true" not in result.source_evidence
    assert "active_snapshot_degraded_to_pytdx_observation=true" in result.source_evidence


def test_future_snapshot_row_is_rejected_even_inside_effective_deadline(monkeypatch, tmp_path):
    result = _refresh(
        monkeypatch,
        tmp_path,
        snapshot_time="09:36:30",
        capture_times=("09:36:00", "09:36:00"),
    )

    assert result.status == "PARTIAL_WITH_ROWS"
    assert result.rows[0]["candidate_lanes"] == []
    assert "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in result.cannot_confirm
    assert "active_snapshot_rows_before_capture=false" in result.source_evidence


def test_capture_date_mismatch_cannot_be_live(monkeypatch, tmp_path):
    result = _refresh(
        monkeypatch,
        tmp_path,
        capture_times=("09:36:00", "09:36:01"),
        capture_trade_date="20260922",
    )

    assert result.status == "PARTIAL_WITH_ROWS"
    assert result.rows[0]["candidate_lanes"] == []
    assert "active_snapshot_capture_window_safe=false" in result.source_evidence


@pytest.mark.parametrize("bad_source", ("wrong_date", "wrong_window", "wrong_coverage"))
def test_invalid_minute_date_or_window_does_not_use_observation_fallback(monkeypatch, tmp_path, bad_source):
    source = _minute_source(trade_date="20260920") if bad_source == "wrong_date" else _minute_source()
    if bad_source == "wrong_window":
        row = dict(source.rows[0])
        row["window_start"] = _stamp("09:29:00")
        source = SourceResult(
            source.source_id,
            source.status,
            rows=(row,),
            requested_rows=source.requested_rows,
            source_evidence=source.source_evidence,
        )
    elif bad_source == "wrong_coverage":
        source = SourceResult(
            source.source_id,
            source.status,
            rows=source.rows,
            requested_rows=2,
            missing_symbols=(),
            source_evidence=source.source_evidence,
        )
    result = _refresh(
        monkeypatch,
        tmp_path,
        source=source,
        snapshot_time="09:37:06",
        capture_times=("09:37:05", "09:37:06"),
    )

    assert result.status == "CANNOT_CONFIRM"
    assert result.rows == ()
    assert "active_snapshot_degraded_to_pytdx_observation=true" not in result.source_evidence


def test_no_minute_rows_does_not_fill_from_active_snapshot(monkeypatch, tmp_path):
    source = _minute_source(rows=(), status="CANNOT_CONFIRM")
    result = _refresh(monkeypatch, tmp_path, source=source)

    assert result is source
    assert result.rows == ()
    assert _FakeAuctionModule.called == 0
    assert "active_snapshot_degraded_to_pytdx_observation=true" not in result.source_evidence


@pytest.mark.parametrize(
    ("stage_id", "cutoff_at", "snapshot_time", "capture_times"),
    (
        ("STAGE_0925", "09:25:05", "09:25:06", ("09:25:05", "09:25:06")),
        ("STAGE_1545_1555", "15:55:05", "15:55:06", ("15:55:05", "15:55:06")),
    ),
)
def test_0925_and_stage8_never_get_minute_grace_fallback(
    monkeypatch,
    tmp_path,
    stage_id,
    cutoff_at,
    snapshot_time,
    capture_times,
):
    result = _refresh(
        monkeypatch,
        tmp_path,
        stage_id=stage_id,
        cutoff_at=cutoff_at,
        snapshot_time=snapshot_time,
        capture_times=capture_times,
    )

    assert result.status == "CANNOT_CONFIRM"
    assert result.rows == ()
    assert "active_snapshot_degraded_to_pytdx_observation=true" not in result.source_evidence


def test_historical_capture_is_explicitly_forbidden(monkeypatch, tmp_path):
    source = _minute_source()

    def forbidden_fetch(*args, **kwargs):
        raise AssertionError("historical backfill must not fetch a natural active snapshot")

    forbidden_module = type("M", (), {"fetch_futu_snapshot": forbidden_fetch})
    result = _refresh(
        monkeypatch,
        tmp_path,
        source=source,
        allow_natural_capture=False,
        auction_module=forbidden_module,
    )

    assert result.status == "PARTIAL_WITH_ROWS"
    assert result.rows[0]["candidate_lanes"] == []
    assert "HK_ACTIVE_SNAPSHOT_NATURAL_CAPTURE_FORBIDDEN" in result.cannot_confirm
    assert "active_snapshot_capture_allowed=false" in result.source_evidence


def test_grace_origin_recovery_reuses_exact_minutes_without_futu(monkeypatch):
    source = _minute_source()
    source = SourceResult(
        source.source_id,
        source.status,
        rows=source.rows,
        requested_rows=source.requested_rows,
        source_evidence=source.source_evidence
        + (
            "active_snapshot_status=FUTU_HKCONNECT_FULL_SCAN",
            "active_snapshot_trade_date=20260921",
            "active_snapshot_cutoff=09:35:05",
            "active_snapshot_temporal_cutoff_safe=false",
            "active_snapshot_execution_cutoff_safe=true",
            "active_snapshot_execution_status=LIVE_EXECUTION_GRACE",
            "active_snapshot_capture_started_at=2026-09-21T09:36:59+08:00",
            "active_snapshot_captured_at=2026-09-21T09:37:00+08:00",
            "active_snapshot_sha256=" + "a" * 64,
            "active_snapshot_codes_sha256=" + "b" * 64,
        ),
    )
    raw_row = {field: source.rows[0].get(field, "") for field in RAW_FIELDS}
    raw_row.update(
        {
            "batch_index": 0,
            "name": "HK.00001",
            "open_price": 10.0,
            "high_price": 10.0,
            "low_price": 9.0,
            "volume": 100.0,
            "bid_price": "",
            "ask_price": "",
            "bid_vol": "",
            "ask_vol": "",
        }
    )
    source = SourceResult(
        source.source_id,
        source.status,
        rows=(raw_row,),
        requested_rows=source.requested_rows,
        source_evidence=source.source_evidence,
    )
    calls = []

    def forbidden_futu(*args, **kwargs):
        calls.append("futu")
        raise AssertionError("selection recovery must not request current Futu")

    monkeypatch.setattr(lc, "_futu_hkconnect_active_snapshot", forbidden_futu)
    recovered = lc._reuse_hk_minute_observation_for_recovery(
        source,
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        cutoff_at=ORIGINAL_CUTOFF,
    )

    assert calls == []
    assert recovered.status == "PARTIAL_WITH_ROWS"
    assert len(recovered.rows) == 1
    assert recovered.rows[0]["candidate_lanes"] == []
    assert "active_snapshot_execution_status=LIVE_EXECUTION_GRACE" in recovered.source_evidence
    assert "active_snapshot_execution_cutoff_safe=true" in recovered.source_evidence
    assert "active_snapshot_capture_started_at=2026-09-21T09:36:59+08:00" in recovered.source_evidence
    assert "active_snapshot_captured_at=2026-09-21T09:37:00+08:00" in recovered.source_evidence
    assert "active_snapshot_sha256=" + "a" * 64 in recovered.source_evidence
    assert "active_snapshot_codes_sha256=" + "b" * 64 in recovered.source_evidence
    assert "active_snapshot_degraded_to_pytdx_observation=true" in recovered.source_evidence


@pytest.mark.parametrize("bad_contract", ("source_id", "route", "window"))
def test_grace_origin_recovery_rejects_bad_exact_minute_contract(bad_contract):
    source = _minute_source()
    if bad_contract == "source_id":
        source = SourceResult(
            "fixture_hk",
            source.status,
            rows=source.rows,
            requested_rows=source.requested_rows,
            source_evidence=source.source_evidence,
        )
    elif bad_contract == "route":
        source = SourceResult(
            source.source_id,
            source.status,
            rows=source.rows,
            requested_rows=source.requested_rows,
            source_evidence=("route=unverified_hk_source",),
        )
    else:
        row = dict(source.rows[0])
        row["window_end"] = _stamp("09:36:00")
        source = SourceResult(
            source.source_id,
            source.status,
            rows=(row,),
            requested_rows=source.requested_rows,
            source_evidence=source.source_evidence,
        )

    recovered = lc._reuse_hk_minute_observation_for_recovery(
        source,
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        cutoff_at=ORIGINAL_CUTOFF,
    )

    assert recovered.status == "CANNOT_CONFIRM"
    assert recovered.rows == ()
    assert "HK_EXHQ_EXACT_WINDOW_UNSAFE" in recovered.cannot_confirm
    assert "active_snapshot_degraded_to_pytdx_observation=true" not in recovered.source_evidence


@pytest.mark.parametrize(
    "execution_status",
    ("LIVE_EXECUTION_GRACE", "MISSING", "WRONG"),
)
def test_runner_grace_recovery_never_reprobes_current_futu(monkeypatch, tmp_path, execution_status):
    from stage_center import live_collectors, runner as runner_module
    from stage_center.candidate_input import CandidateInput
    from stage_center.runner import RunnerConfig, StageCenterRunner
    from stage_center.scheduler import DueDecision
    from stage_center.acquisition import StageUniverseBinding
    from stage_center.selection import select_hk_four_lane

    candidate = CandidateInput(
        root=tmp_path / "candidate",
        trade_date=TRADE_DATE,
        current_relative="current.json",
        current_sha256="c" * 64,
        run_id="candidate-run",
        codes=("HK.00001",),
        artifact_sha256="d" * 64,
        manifest_sha256="e" * 64,
        receipt_sha256="f" * 64,
        source_projection_sha256="g" * 64,
        source_evidence=("fixture=candidate",),
    )
    binding = StageUniverseBinding.ready(
        market="HK_CONNECT",
        trade_date=TRADE_DATE,
        role="HK_CONNECT_D1_TOP100",
        codes=("HK.00001",),
        source_run_id="hk-d1-run",
        sha256="h" * 64,
    )
    source = _minute_source()
    source = SourceResult(
        source.source_id,
        source.status,
        rows=source.rows,
        requested_rows=source.requested_rows,
        source_evidence=source.source_evidence
        + (
            "active_snapshot_status=FUTU_HKCONNECT_FULL_SCAN",
            f"active_snapshot_trade_date={TRADE_DATE}",
            "active_snapshot_cutoff=09:35:05",
            "active_snapshot_temporal_cutoff_safe=false",
            "active_snapshot_execution_cutoff_safe=true",
            *(() if execution_status == "MISSING" else (f"active_snapshot_execution_status={execution_status}",)),
            "active_snapshot_capture_started_at=2026-09-21T09:36:59+08:00",
            "active_snapshot_captured_at=2026-09-21T09:37:00+08:00",
            "active_snapshot_sha256=" + "a" * 64,
            "active_snapshot_codes_sha256=" + "b" * 64,
        ),
    )
    raw_row = {field: source.rows[0].get(field, "") for field in RAW_FIELDS}
    raw_row.update(
        {
            "batch_index": 0,
            "name": "HK.00001",
            "open_price": 10.0,
            "high_price": 10.0,
            "low_price": 9.0,
            "volume": 100.0,
            "bid_price": "",
            "ask_price": "",
            "bid_vol": "",
            "ask_vol": "",
        }
    )
    source = SourceResult(
        source.source_id,
        source.status,
        rows=(raw_row,),
        requested_rows=source.requested_rows,
        source_evidence=source.source_evidence,
    )
    raw_entry = {
        "artifact_sha256": "1" * 64,
        "source_id": "pytdx_exhq",
        "status": "READY",
        "requested_rows": 1,
        "missing_symbols": [],
        "source_evidence": source.source_evidence,
    }
    futu_calls = []

    def forbidden_futu(*args, **kwargs):
        futu_calls.append("futu")
        raise AssertionError("grace-origin recovery must not request current Futu")

    class FakeRawStore:
        def __init__(self, root):
            self.root = root

        def publish_bundle(self, *, trade_date, stage_id, status, markets):
            return {"bundle_id": "bundle-recovery", "status": status, "markets": markets}

    class FakeSelectionStore:
        def __init__(self, root):
            self.root = root

        def publish(self, envelope, *, market):
            return dict(envelope)

    def builder(current, plan, raw):
        return select_hk_four_lane(
            current.rows,
            plan.trade_date,
            plan.stage_id,
            raw["artifact_sha256"],
            source_status=current.status,
            requested_rows=current.requested_rows,
            missing_symbols=current.missing_symbols,
            cannot_confirm=current.cannot_confirm,
            source_evidence=current.source_evidence,
        )

    monkeypatch.setattr(runner_module, "_stage_markets", lambda _stage_id: ("HK_CONNECT",))
    monkeypatch.setattr(runner_module, "read_candidate_input", lambda *args, **kwargs: candidate)
    monkeypatch.setattr(runner_module, "_build_hk_d1_binding", lambda *args, **kwargs: binding)
    monkeypatch.setattr(runner_module, "_validate_exact_selection_inputs", lambda *args, **kwargs: ("fixture_exact=1",))
    monkeypatch.setattr(runner_module, "_read_verified_raw_source", lambda *args, **kwargs: source)
    monkeypatch.setattr(runner_module, "_attach_hk_authority", lambda current, **kwargs: current)
    monkeypatch.setattr(runner_module, "RawStore", FakeRawStore)
    monkeypatch.setattr(runner_module, "SelectionStore", FakeSelectionStore)
    monkeypatch.setattr(live_collectors, "_futu_hkconnect_active_snapshot", forbidden_futu)
    monkeypatch.setattr(live_collectors, "refresh_hk_active_lanes", forbidden_futu)
    monkeypatch.setattr(live_collectors, "production_selection_builders", lambda _stage_id: {"HK_CONNECT": builder})

    config = RunnerConfig(
        candidate_acquisition_root=tmp_path / "candidate",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        hk_d1_root=tmp_path / "hk-d1",
        hk_full_universe_root=tmp_path / "hk-full",
        shared_data_root=tmp_path / "shared",
        python_path=Path("/tmp/python"),
    )
    runner = StageCenterRunner(
        config,
        collectors={"HK_CONNECT": lambda *_args: forbidden_futu()},
    )
    monkeypatch.setattr(
        runner,
        "_existing_slot",
        lambda *args, **kwargs: (
            "PARTIAL",
            {"raw_verified": {"HK_CONNECT": raw_entry}, "selections": {}},
        ),
    )
    result = runner._run_one(
        DueDecision(
            stage_id=STAGE_ID,
            trade_date=TRADE_DATE,
            status="DUE",
            scheduled_at=None,
            idempotency_key="recovery",
            calendar={},
        )
    )

    assert futu_calls == []
    if execution_status == "LIVE_EXECUTION_GRACE":
        assert result["status"] == "PARTIAL_WITH_ROWS"
        assert result["markets"]["HK_CONNECT"]["selection_status"] == "PARTIAL_WITH_ROWS"
        assert result["markets"]["HK_CONNECT"]["selected_rows"] == 1
        assert "active_snapshot_execution_status=LIVE_EXECUTION_GRACE" in result["markets"]["HK_CONNECT"]["source_evidence"]
        assert "hk_active_selection_recovery=DEGRADED_OBSERVATION_REUSE" in result["markets"]["HK_CONNECT"]["source_evidence"]
    else:
        assert result["status"] == "CANNOT_CONFIRM"
        assert result["markets"]["HK_CONNECT"]["status"] == "CANNOT_CONFIRM"
        assert "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in result["markets"]["HK_CONNECT"]["cannot_confirm"]
