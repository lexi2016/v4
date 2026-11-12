from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stage_center import runner as stage_runner
from stage_center.acquisition import AcquisitionPlan
from stage_center.calendar import TradingDayState
from stage_center.candidate_input import CandidateInput
from stage_center.contracts import SAFETY_FLAGS
from stage_center.hk_stage8 import (
    _atomic_snapshot_create,
    _canonical_snapshot_codes,
    _snapshot_codes_sha,
    _snapshot_path,
    _snapshot_rows_sha,
    _collect_hk_stage8_natural,
    load_hk_active_snapshot,
    production_natural_collectors,
    should_use_natural_route,
)


TRADE_DATE = "20260911"
STAGE_ID = "STAGE_1545_1555"
SHANGHAI = ZoneInfo("Asia/Shanghai")
CODES = tuple(f"HK.{index:05d}" for index in range(1, 11))
D1_CODES = tuple(f"HK.{index:05d}" for index in range(1, 101))


def _snapshot_rows(
    codes: tuple[str, ...] = CODES,
    *,
    update_time: str = "2026-09-11 15:50:00",
) -> list[dict[str, object]]:
    return [
        {
            "code": code,
            "prev_close_price": 10.0,
            "last_price": 11.0,
            "turnover": 30_000_000.0,
            "volume_ratio": 2.0,
            "update_time": update_time,
        }
        for code in codes
    ]


def _write_snapshot(
    root: Path,
    codes: tuple[str, ...] = CODES,
    *,
    captured_at: str = "2026-09-11T15:50:00+08:00",
    update_time: str = "2026-09-11 15:50:00",
) -> Path:
    rows = _snapshot_rows(codes, update_time=update_time)
    path = _snapshot_path(root, TRADE_DATE, STAGE_ID)
    payload = {
        "schema_version": "stage_center.hk_active_snapshot.v1",
        "trade_date": TRADE_DATE,
        "stage_id": STAGE_ID,
        "market": "HK_CONNECT",
        "source_role": "FUTU_HKCONNECT_FULL_SCAN",
        "codes": list(codes),
        "codes_sha256": _snapshot_codes_sha(codes),
        "requested_rows": len(codes),
        "returned_rows": len(rows),
        "full_coverage": True,
        "rows": rows,
        "snapshot_sha256": _snapshot_rows_sha(rows),
        "captured_at": captured_at,
        "cutoff_at": "2026-09-11T15:55:00",
        "temporal_cutoff_safe": True,
        **SAFETY_FLAGS,
    }
    assert _atomic_snapshot_create(path, payload)
    return path


def _plan(root: Path, trade_date: str = TRADE_DATE) -> AcquisitionPlan:
    candidate = CandidateInput(
        root=root,
        trade_date=trade_date,
        current_relative="current.json",
        current_sha256="a" * 64,
        run_id="stage8-fixture",
        codes=CODES,
        artifact_sha256="a" * 64,
        manifest_sha256="a" * 64,
        receipt_sha256="a" * 64,
        source_projection_sha256="a" * 64,
        source_evidence=(),
    )
    return AcquisitionPlan(
        trade_date=trade_date,
        stage_id=STAGE_ID,
        markets=("HK_CONNECT",),
        candidate_input=candidate,
        a_share_route=None,
        hk_route="stage8_natural_rtd_data_or_exact_replay",
    )


def test_0911_snapshot_fixture_roundtrips_ten_exact_rows(tmp_path: Path) -> None:
    _write_snapshot(tmp_path)

    result = load_hk_active_snapshot(
        tmp_path,
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        codes=CODES,
        cutoff_at="15:55:00",
    )

    assert result["status"] == "READY"
    assert len(result["rows"]) == 10
    assert tuple(row["code"] for row in result["rows"]) == _canonical_snapshot_codes(CODES)
    assert result["temporal_cutoff_safe"] is True
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def _write_d1(root: Path, codes: tuple[str, ...] = D1_CODES) -> Path:
    path = root / TRADE_DATE / "hkconnect_d1_top100.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "STRICT_0_2_READY",
        "target_date": TRADE_DATE,
        "rows": [{"code": code, "target_date": TRADE_DATE} for code in codes],
        **SAFETY_FLAGS,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_stage8_normal_a_plan_carries_the_exact_d1_membership(tmp_path: Path) -> None:
    _write_d1(tmp_path / "d1")
    binding = stage_runner._build_hk_d1_binding(tmp_path / "d1", TRADE_DATE)

    candidate = CandidateInput(
        root=tmp_path / "candidate",
        trade_date=TRADE_DATE,
        current_relative="current.json",
        current_sha256="a" * 64,
        run_id="a-stage8-fixture",
        codes=("A.000001", "A.000002"),
        artifact_sha256="b" * 64,
        manifest_sha256="c" * 64,
        receipt_sha256="d" * 64,
        source_projection_sha256="e" * 64,
        source_evidence=(),
    )
    plan = stage_runner.build_plan(
        tmp_path / "candidate",
        TRADE_DATE,
        STAGE_ID,
        candidate=candidate,
        universe_bindings={"HK_CONNECT": binding},
    )

    assert plan.codes_for("A_SHARE") == ("A.000001", "A.000002")
    assert plan.codes_for("HK_CONNECT") == D1_CODES
    assert binding.role == "HK_CONNECT_D1_TOP100"


def test_normal_a_stage8_natural_collector_receives_all_100_d1_codes(tmp_path: Path) -> None:
    _write_d1(tmp_path / "d1")
    binding = stage_runner._build_hk_d1_binding(tmp_path / "d1", TRADE_DATE)
    candidate = CandidateInput(
        root=tmp_path / "candidate",
        trade_date=TRADE_DATE,
        current_relative="current.json",
        current_sha256="a" * 64,
        run_id="a-stage8-natural-fixture",
        codes=("A.000001", "A.000002"),
        artifact_sha256="b" * 64,
        manifest_sha256="c" * 64,
        receipt_sha256="d" * 64,
        source_projection_sha256="e" * 64,
        source_evidence=(),
    )
    plan = AcquisitionPlan(
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        markets=("A_SHARE", "HK_CONNECT"),
        candidate_input=candidate,
        a_share_route=None,
        hk_route="stage8_natural_rtd_data_or_exact_replay",
        universe_bindings={"HK_CONNECT": binding},
    )
    _write_snapshot(tmp_path / "raw", codes=D1_CODES)
    calls: list[tuple[str, ...]] = []

    def provider(codes: tuple[str, ...], **_kwargs: object) -> dict[str, object]:
        calls.append(tuple(codes))
        return {
            "rows": [
                {
                    "code": code,
                    "time": "2026-09-11 15:50:00",
                    "cur_price": 11.0,
                    "last_close": 10.0,
                    "turnover": 30_000_000.0,
                    "volume": 100.0,
                    "high": 11.0,
                    "low": 11.0,
                }
                for code in codes
            ],
            "errors": (),
            "cleanup_warnings": (),
        }

    result = _collect_hk_stage8_natural(
        plan,
        codes=plan.codes_for("HK_CONNECT"),
        snapshot_root=tmp_path / "raw",
        rtdata_provider=provider,
        natural_now=datetime(2026, 9, 11, 15, 56, tzinfo=SHANGHAI),
    )

    assert calls == [D1_CODES]
    assert result.status == "READY"
    assert result.requested_rows == 100
    assert len(result.rows) == 100


def test_snapshot_loader_rejects_envelope_and_time_boundary_violations(tmp_path: Path) -> None:
    cases = (
        ({"market": "A_SHARE"}, "HK_ACTIVE_SNAPSHOT_MARKET_MISMATCH"),
        ({"source_role": "OTHER_SOURCE"}, "HK_ACTIVE_SNAPSHOT_SOURCE_ROLE_MISMATCH"),
        ({"requested_rows": 999}, "HK_ACTIVE_SNAPSHOT_REQUESTED_ROWS_MISMATCH"),
        ({"returned_rows": 0}, "HK_ACTIVE_SNAPSHOT_RETURNED_ROWS_MISMATCH"),
        ({"full_coverage": False}, "HK_ACTIVE_SNAPSHOT_FULL_COVERAGE_MISSING"),
        ({"temporal_cutoff_safe": False}, "HK_ACTIVE_SNAPSHOT_TEMPORAL_FLAG_MISMATCH"),
    )
    for index, (overrides, expected) in enumerate(cases):
        path = _write_snapshot(tmp_path / f"metadata-{index}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.update(overrides)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        result = load_hk_active_snapshot(
            tmp_path / f"metadata-{index}",
            trade_date=TRADE_DATE,
            stage_id=STAGE_ID,
            codes=CODES,
            cutoff_at="15:55:00",
        )
        assert result["status"] == "CANNOT_CONFIRM"
        assert expected in result["cannot_confirm"]

    early_root = tmp_path / "early-capture"
    _write_snapshot(early_root, captured_at="2026-09-11T09:00:00+08:00")
    early = load_hk_active_snapshot(
        early_root,
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        codes=CODES,
        cutoff_at="15:55:00",
    )
    assert early["status"] == "CANNOT_CONFIRM"
    assert "HK_ACTIVE_SNAPSHOT_CAPTURE_WINDOW_UNSAFE" in early["cannot_confirm"]

    offset_root = tmp_path / "utc-offset"
    offset_path = _write_snapshot(offset_root)
    offset_payload = json.loads(offset_path.read_text(encoding="utf-8"))
    offset_payload["rows"][0]["update_time"] = "2026-09-11T15:55:00Z"
    offset_payload["snapshot_sha256"] = _snapshot_rows_sha(offset_payload["rows"])
    offset_path.write_text(json.dumps(offset_payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    offset = load_hk_active_snapshot(
        offset_root,
        trade_date=TRADE_DATE,
        stage_id=STAGE_ID,
        codes=CODES,
        cutoff_at="15:55:00",
    )
    assert offset["status"] == "CANNOT_CONFIRM"
    assert "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in offset["cannot_confirm"]


def test_same_day_route_is_natural_and_historical_route_is_not() -> None:
    current = datetime(2026, 9, 11, 15, 55, 30, tzinfo=SHANGHAI)

    assert should_use_natural_route(
        TRADE_DATE,
        historical_backfill=False,
        natural_now=current,
    ) is True
    assert should_use_natural_route(
        TRADE_DATE,
        historical_backfill=True,
        natural_now=current,
    ) is False
    assert should_use_natural_route(
        "20260910",
        historical_backfill=False,
        natural_now=current,
    ) is False


def test_natural_builder_keeps_the_v4_snapshot_root_and_missing_0914_is_unconfirmed(
    tmp_path: Path,
) -> None:
    calls: list[object] = []

    def provider(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append(True)
        return {"rows": (), "errors": ()}

    collectors = production_natural_collectors(
        snapshot_root=tmp_path / "raw",
        natural_now=datetime(2026, 9, 14, 15, 56, tzinfo=SHANGHAI),
    )
    assert set(collectors) == {"HK_CONNECT"}

    result = _collect_hk_stage8_natural(
        _plan(tmp_path, "20260914"),
        codes=CODES,
        snapshot_root=tmp_path / "raw",
        rtdata_provider=provider,
        natural_now=datetime(2026, 9, 14, 15, 56, tzinfo=SHANGHAI),
    )

    assert result.status == "CANNOT_CONFIRM"
    assert "HK_ACTIVE_SNAPSHOT_UNAVAILABLE" in result.cannot_confirm
    assert "HK_STAGE8_ACTIVE_SNAPSHOT_UNAVAILABLE" in result.cannot_confirm
    assert calls == []


def test_runner_precapture_is_before_due_decision_and_exact_window(
    monkeypatch, tmp_path: Path
) -> None:
    config = stage_runner.RunnerConfig(
        candidate_acquisition_root=tmp_path / "candidate",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        hk_d1_root=tmp_path / "d1",
        hk_full_universe_root=tmp_path / "hk",
        shared_data_root=tmp_path / "shared",
        python_path=tmp_path / "python",
    )
    runner = stage_runner.StageCenterRunner(config)
    events: list[str] = []

    monkeypatch.setattr(
        stage_runner,
        "_validate_hk_d1",
        lambda *_args: (tmp_path / "hkconnect_d1_top100.json", "f" * 64),
    )
    monkeypatch.setattr(
        stage_runner,
        "_hk_selection_codes",
        lambda *_args: (set(CODES), "f" * 64),
    )
    full_validator_calls: list[bool] = []
    monkeypatch.setattr(
        stage_runner,
        "_validate_hk_full_universe",
        lambda *_args: full_validator_calls.append(True)
        or (tmp_path / "HK_CONNECT_FULL_MARKET.json", CODES, "3" * 64),
    )
    monkeypatch.setattr(
        "stage_center.hk_stage8.prepare_hk_active_snapshot",
        lambda *args, **kwargs: events.append(
            f"prepare:{kwargs['trade_date']}:{kwargs['stage_id']}"
        )
        or {"status": "READY", "stage_id": kwargs["stage_id"]},
    )
    monkeypatch.setattr(
        "stage_center.hk_stage8.precapture.resolve_market_states",
        lambda _trade_date: {
            "hk_securities": TradingDayState.FULL_TRADING_DAY,
            "hk_connect": TradingDayState.FULL_TRADING_DAY,
        },
    )

    assert runner._prepare_hk_active_snapshots(
        TRADE_DATE,
        datetime(2026, 9, 11, 15, 49, 59, tzinfo=SHANGHAI),
        stage_id=STAGE_ID,
    ) == []
    captured = runner._prepare_hk_active_snapshots(
        TRADE_DATE,
        datetime(2026, 9, 11, 15, 50, tzinfo=SHANGHAI),
        stage_id=STAGE_ID,
    )
    assert captured == [{
        "status": "READY",
        "stage_id": STAGE_ID,
        "trade_date": TRADE_DATE,
        "hk_d1_top100_sha256": "f" * 64,
        "capture_window_start": "2026-09-11T15:50:00+08:00",
        "capture_window_end": "2026-09-11T15:55:00+08:00",
        "hk_d1_source_trade_date": TRADE_DATE,
        "hk_d1_source_signal_date": None,
        "hk_d1_source_sha256": "f" * 64,
        "hk_observation_trade_date": TRADE_DATE,
        "source_evidence": [
            f"hk_d1_json={tmp_path / 'hkconnect_d1_top100.json'}",
            f"hk_d1_sha256={'f' * 64}",
            "hk_d1_membership=exact_date_top100",
        ],
    }]
    assert events == [f"prepare:{TRADE_DATE}:{STAGE_ID}"]
    assert full_validator_calls == []


def test_runner_precapture_rejects_full_market_fallback_without_d1(
    monkeypatch, tmp_path: Path
) -> None:
    config = stage_runner.RunnerConfig(
        candidate_acquisition_root=tmp_path / "candidate",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        hk_full_universe_root=tmp_path / "hk",
        shared_data_root=tmp_path / "shared",
        python_path=tmp_path / "python",
    )
    runner = stage_runner.StageCenterRunner(config)
    monkeypatch.setattr(
        "stage_center.hk_stage8.precapture.resolve_market_states",
        lambda _trade_date: {
            "hk_securities": TradingDayState.FULL_TRADING_DAY,
            "hk_connect": TradingDayState.FULL_TRADING_DAY,
        },
    )
    full_validator_calls: list[bool] = []
    monkeypatch.setattr(
        stage_runner,
        "_validate_hk_full_universe",
        lambda *_args: full_validator_calls.append(True)
        or (tmp_path / "HK_CONNECT_FULL_MARKET.json", CODES, "3" * 64),
    )

    result = runner._prepare_hk_active_snapshots(
        TRADE_DATE,
        datetime(2026, 9, 11, 15, 50, tzinfo=SHANGHAI),
        stage_id=STAGE_ID,
    )

    assert len(result) == 1
    assert result[0]["status"] == "CANNOT_CONFIRM"
    assert "HK D1 Top100 root is required" in result[0]["error"]
    assert full_validator_calls == []


def test_outer_tick_exposes_precapture_before_due_work(monkeypatch, tmp_path: Path) -> None:
    config = stage_runner.RunnerConfig(
        candidate_acquisition_root=tmp_path / "candidate",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
    )
    runner = stage_runner.StageCenterRunner(config)
    events: list[str] = []
    monkeypatch.setattr(
        runner,
        "_prepare_hk_active_snapshots",
        lambda *_args, **_kwargs: events.append("pre_capture") or [{"status": "READY"}],
    )
    monkeypatch.setattr(
        runner,
        "due_decisions",
        lambda *_args, **_kwargs: events.append("due_decisions") or (),
    )

    result = runner.tick(
        TRADE_DATE,
        datetime(2026, 9, 11, 15, 50, tzinfo=SHANGHAI),
    )

    assert events == ["pre_capture", "due_decisions"]
    assert result["pre_captures"] == [{"status": "READY"}]
