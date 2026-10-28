from __future__ import annotations

import hashlib
import json
from datetime import datetime as RealDatetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import stage_center.live_collectors as live_collectors
import ops.run_hk_morning_cached_recovery as recovery_cli
from stage_center._live_collectors_parts.hk_minute import (
    _build_hk_morning_cached_source,
)
from stage_center.acquisition import build_plan
from stage_center.live_collectors import collect_hk_minute
from stage_center.runner import _build_hk_stage_binding, _candidate_from_hk_binding


TRADE_DATE = "20261015"
D1_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data")
CAPTURE = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/raw/"
    ".futu_minute_captures/20261015/STAGE_0945_1030/"
    "45fdc5d16d1dec2e7f087dfdb802f3c5b92e67d4e380aa6c49ddea15881ab455.json"
)
SHARED_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "node-minute-stage-20261014-r1/app/upstreams/v3_shared_data"
)
PYTHON_PATH = Path(__file__).resolve().parents[1] / ".venv/bin/python"
CAPTURE_ENV = "V4_HK_MORNING_CACHED_CAPTURE"


@pytest.fixture(scope="module")
def input_context(tmp_path_factory):
    binding = _build_hk_stage_binding(D1_ROOT, TRADE_DATE)
    candidate = _candidate_from_hk_binding(
        root=tmp_path_factory.mktemp("hk-morning-candidate"),
        trade_date=TRADE_DATE,
        binding=binding,
    )
    plan = build_plan(
        candidate.root,
        TRADE_DATE,
        "STAGE_0930_0935",
        candidate=candidate,
        universe_bindings={"HK_CONNECT": binding},
        historical_backfill=True,
    )
    payload = json.loads(CAPTURE.read_text(encoding="utf-8"))
    return binding, plan, payload


def _build(plan, payload, capture_sha=None):
    raw = CAPTURE.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    return _build_hk_morning_cached_source(
        vars(live_collectors),
        plan,
        codes=plan.codes_for("HK_CONNECT"),
        shared_root=SHARED_ROOT,
        capture_path=CAPTURE,
        capture_sha256=capture_sha or actual_sha,
        dataset=payload,
    )


def test_cached_futu_window_is_idempotent_and_keeps_afterfact_boundary(
    input_context, monkeypatch
):
    _, plan, _ = input_context
    monkeypatch.setenv(CAPTURE_ENV, str(CAPTURE))
    first = collect_hk_minute(
        plan,
        codes=plan.codes_for("HK_CONNECT"),
        python_path=PYTHON_PATH,
        shared_root=SHARED_ROOT,
    )
    second = collect_hk_minute(
        plan,
        codes=plan.codes_for("HK_CONNECT"),
        python_path=PYTHON_PATH,
        shared_root=SHARED_ROOT,
    )
    assert first.status == second.status == "PARTIAL_WITH_ROWS"
    assert len(first.rows) == len(second.rows) == 100
    assert first.rows == second.rows
    assert first.source_evidence == second.source_evidence
    assert all(row["bar_count"] == 5 for row in first.rows)
    assert all(row["temporal_cutoff_safe"] is False for row in first.rows)
    assert all(row["update_time"] == "2026-10-15 09:35:00" for row in first.rows)
    assert all(
        row["window_start"] == "2026-10-15 09:31:00"
        and row["window_end"] == "2026-10-15 09:35:00"
        for row in first.rows
    )
    assert "futu_capture_stage_id=STAGE_0945_1030" in first.source_evidence
    assert "futu_capture_captured_at=2026-10-15T10:31:03.491290+08:00" in first.source_evidence
    assert "futu_capture_orderbook_available=false" in first.source_evidence
    assert "futu_afterfact_pit_safe=false" in first.source_evidence
    assert "futu_afterfact_formal_stage_eligibility=CANNOT_CONFIRM" in first.source_evidence


def test_wrong_capture_sha_fails_closed(input_context, monkeypatch, tmp_path):
    _, plan, _ = input_context
    payload = CAPTURE.read_bytes()
    changed = bytes([payload[0] ^ 1]) + payload[1:]
    wrong_capture = tmp_path / "wrong-sha.json"
    wrong_capture.write_bytes(changed)
    monkeypatch.setenv(CAPTURE_ENV, str(wrong_capture))
    source = collect_hk_minute(
        plan,
        codes=plan.codes_for("HK_CONNECT"),
        python_path=PYTHON_PATH,
        shared_root=SHARED_ROOT,
    )
    assert source.status == "CANNOT_CONFIRM"
    assert any("HK_MORNING_CACHED_CAPTURE_INVALID" in item for item in source.cannot_confirm)


@pytest.mark.parametrize(
    ("field", "value"),
    (("trade_date", "20261014"), ("stage_id", "STAGE_0935_0940")),
)
def test_wrong_capture_date_or_stage_fails_closed(input_context, field, value):
    _, plan, payload = input_context
    changed = dict(payload)
    changed[field] = value
    source = _build(plan, changed)
    assert source.status == "CANNOT_CONFIRM"
    assert "HK_MORNING_CACHED_CAPTURE_IDENTITY_MISMATCH" in source.cannot_confirm


def test_replacing_a_target_window_bar_with_a_future_bar_is_rejected(input_context):
    _, plan, payload = input_context
    changed = dict(payload)
    rows = list(payload["rows"])
    target_index = next(
        index
        for index, row in enumerate(rows)
        if row.get("time_key") == "2026-10-15 09:31:00"
    )
    rows[target_index] = {**rows[target_index], "time_key": "2026-10-15 09:36:00"}
    changed["rows"] = rows
    source = _build(plan, changed)
    assert source.status == "CANNOT_CONFIRM"
    assert "HK_MORNING_CACHED_WINDOW_COVERAGE_MISMATCH" in source.cannot_confirm


def test_offline_canary_uses_and_records_live_shanghai_clock(tmp_path, monkeypatch):
    start = RealDatetime(2026, 10, 15, 11, 39, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    clock_values = [start + timedelta(seconds=offset) for offset in range(6)]
    clock_calls = iter(clock_values)

    class FixedClockDatetime(RealDatetime):
        @classmethod
        def now(cls, tz=None):
            value = next(clock_calls)
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(recovery_cli, "datetime", FixedClockDatetime)
    output_root = tmp_path / "offline-canary"
    summary = recovery_cli.run_offline_canary(output_root=output_root)

    expected_evaluations = {
        stage: clock_values[index + 1].isoformat()
        for index, stage in enumerate(recovery_cli.STAGES)
    }
    assert summary["clock_timezone"] == "Asia/Shanghai"
    assert summary["run_started_at"] == clock_values[0].isoformat()
    assert summary["runner_evaluated_at_by_stage"] == expected_evaluations
    assert summary["receipt_captured_at"] == clock_values[5].isoformat()
    assert all("10:32:00" not in value for value in expected_evaluations.values())
    assert {
        item["stage_id"]: item["runner_evaluated_at"]
        for item in summary["stage_results"]
    } == expected_evaluations


def test_offline_output_root_symlink_alias_into_runtime_state_is_rejected(
    tmp_path, monkeypatch
):
    runtime_root = tmp_path / "runtime-state"
    runtime_root.mkdir()
    alias = tmp_path / "runtime-alias"
    alias.symlink_to(runtime_root, target_is_directory=True)
    monkeypatch.setattr(recovery_cli, "RUNTIME_STATE_ROOT", runtime_root)

    with pytest.raises(ValueError, match="active runtime state"):
        recovery_cli.run_offline_canary(output_root=alias / "new-canary")

    assert not (runtime_root / "new-canary").exists()
