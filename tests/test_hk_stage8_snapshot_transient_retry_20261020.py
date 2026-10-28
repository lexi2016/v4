"""Offline real snapshot entry; only the external process and wall clock are fake.

The frozen Git baseline lacks the Stage8 package. Until integration, explicitly
pin V4_STAGE8_TEST_DEPENDENCY_ROOT to the reviewed runtime release; load the
candidate file below by absolute path, never the release's snapshot module.
"""
from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_ROOT = Path(os.environ.get("V4_STAGE8_TEST_DEPENDENCY_ROOT", ROOT)).resolve()
if DEPENDENCY_ROOT != ROOT:
    sys.path.insert(0, str(DEPENDENCY_ROOT))
import stage_center.hk_stage8  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "stage_center.hk_stage8.network_retry_candidate",
    ROOT / "stage_center/hk_stage8/snapshot.py",
)
assert SPEC and SPEC.loader
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)

DAY = "20261020"
STAGE = "STAGE_1545_1555"
ZONE = ZoneInfo("Asia/Shanghai")
CODES = ["HK.00001", "HK.00002"]
POOL_SHA = "a" * 64
PYTHON = Path(sys.executable)


class WallClock:
    def __init__(self, value="2026-10-20T15:50:01+08:00"):
        self.value = datetime.fromisoformat(value)
        self.sleeps = []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += timedelta(seconds=seconds)


def rows():
    return [dict(code=code, prev_close_price=10, last_price=11,
                 turnover=30_000_000, volume_ratio=2,
                 update_time="2026-10-20 15:50:00") for code in CODES]


def bridge(clock, responses):
    """Exercise the real shared fetch/JSON decoder without opening OpenD."""
    starts = []

    def run(argv, **kwargs):
        assert argv[0] == str(PYTHON)
        request = json.loads(kwargs["input"])
        assert request["codes"] == CODES
        starts.append(clock.value)
        value = responses[min(len(starts) - 1, len(responses) - 1)]
        clock.value += timedelta(milliseconds=100)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(returncode=0, stderr="", stdout=(
            "__FUTU_HK_AUCTION_JSON__" + json.dumps(value)
        ))

    return run, starts


NETWORK = {"rows": [], "errors": ["网络中断"]}
SUCCESS = {"rows": rows(), "errors": []}


def prepare(tmp_path, clock, run, *, stage=STAGE, sleeper=True, **kwargs):
    arguments = dict(
        trade_date=DAY, stage_id=stage, codes=CODES, python_path=PYTHON,
        shared_root=DEPENDENCY_ROOT / "upstreams/v3_shared_data",
        evaluated_at="2026-10-20T15:50:00+08:00", cutoff_at="15:55:00",
        pool_artifact_sha256=POOL_SHA, process_runner=run, clock=clock,
    )
    if sleeper:
        arguments["sleeper"] = clock.sleep
    arguments.update(kwargs)
    return snapshot.prepare_hk_active_snapshot(tmp_path, **arguments)


def test_real_entry_retries_empty_network_then_publishes_one_immutable_snapshot(tmp_path):
    clock = WallClock()
    run, starts = bridge(clock, [NETWORK, SUCCESS])
    result = prepare(tmp_path, clock, run, sleeper=False)
    assert result["status"] == "READY"
    assert len(starts) == 2
    files = list(tmp_path.rglob("snapshot.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["returned_rows"] == 2
    assert payload["capture_attempts"][0]["cannot_confirm"][0] == "网络中断"
    assert "active_snapshot_transport_raw_status=VERIFIED" in payload["capture_attempts"][0]["source_evidence"]
    assert "active_snapshot_transport_raw_rows=0" in payload["capture_attempts"][0]["source_evidence"]
    assert payload["capture_attempts"][1]["cannot_confirm"] == []
    assert all(payload[key] is False for key in (
        "production_allowed", "buy_gate_updated", "orders_sent"))
    original = files[0].read_bytes()
    again = prepare(tmp_path, clock, run)
    assert again["status"] == "NOOP_ALREADY_VERIFIED"
    assert len(starts) == 2
    assert files[0].read_bytes() == original


def test_three_network_failures_preserve_each_diagnostic_and_write_nothing(tmp_path):
    clock = WallClock()
    run, starts = bridge(clock, [NETWORK])
    result = prepare(tmp_path, clock, run)
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["write_performed"] is False
    assert len(starts) == 3
    assert len(result["capture_attempts"]) == 3
    assert all(attempt["cannot_confirm"][0] == "网络中断"
               for attempt in result["capture_attempts"])
    assert all(attempt["provider_started_at"] == start.isoformat()
               for attempt, start in zip(result["capture_attempts"], starts))
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("response", [
    {"rows": [], "errors": ["permission denied"]},
    {"rows": [], "errors": []},
    {"rows": rows(), "errors": ["网络中断"]},
    {"rows": rows()[:1], "errors": ["网络中断"]},
    {"rows": [], "errors": ["网络中断", "permission denied"]},
    {"rows": [], "errors": ["HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"]},
])
def test_non_network_or_semantically_bad_response_is_not_retried(tmp_path, response):
    clock = WallClock()
    run, starts = bridge(clock, [response, SUCCESS])
    result = prepare(tmp_path, clock, run)
    assert result["status"] == "CANNOT_CONFIRM"
    assert len(starts) == 1
    assert not list(tmp_path.rglob("*"))


def test_transient_connection_exception_retries_but_value_error_does_not(tmp_path):
    for error, expected in [(ConnectionResetError("peer reset"), 2),
                            (ValueError("malformed provider payload"), 1)]:
        clock = WallClock()
        run, starts = bridge(clock, [error, SUCCESS])
        result = prepare(tmp_path / type(error).__name__, clock, run)
        assert len(starts) == expected
        assert result["status"] == ("READY" if expected == 2 else "CANNOT_CONFIRM")


def test_detail_free_connection_reset_retries_through_real_bridge(tmp_path):
    clock = WallClock()
    run, starts = bridge(clock, [ConnectionResetError(), SUCCESS])
    result = prepare(tmp_path, clock, run)
    assert result["status"] == "READY"
    assert len(starts) == 2
    assert len(list(tmp_path.rglob("snapshot.json"))) == 1
    assert result["capture_attempts"][0]["cannot_confirm"] == [
        "HK_ACTIVE_SNAPSHOT_BRIDGE_ERROR:ConnectionResetError"
    ]
    assert "active_snapshot_transport_raw_status=NO_RESPONSE" in result["capture_attempts"][0]["source_evidence"]


def test_malformed_nonempty_bridge_rows_with_network_error_are_not_retried(tmp_path):
    clock = WallClock()
    malformed = {"rows": [{"unexpected": "bad semantic row"}], "errors": ["网络中断"]}
    run, starts = bridge(clock, [malformed, SUCCESS])
    result = prepare(tmp_path, clock, run)
    assert result["status"] == "CANNOT_CONFIRM"
    assert len(starts) == 1
    assert "active_snapshot_bridge_returned_rows=1" in result["source_evidence"]
    assert result["returned_rows"] == 0
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("original_rows", [
    ["bad semantic row"], [None], [{}], [{"code": ""}],
    [["nested invalid row"]], [None, "bad semantic row", {}],
    [*rows(), None],
])
def test_transport_original_nonempty_rows_never_retry_after_wrapper_filtering(
    tmp_path, original_rows
):
    clock = WallClock()
    run, starts = bridge(clock, [{"rows": original_rows, "errors": ["网络中断"]}, SUCCESS])
    result = prepare(tmp_path, clock, run)
    assert result["status"] == "CANNOT_CONFIRM"
    assert len(starts) == 1
    assert f"active_snapshot_transport_raw_rows={len(original_rows)}" in result["source_evidence"]
    assert "active_snapshot_transport_raw_status=VERIFIED" in result["source_evidence"]
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("payload", [
    {"rows": None, "errors": ["网络中断"]},
    {"errors": ["网络中断"]},
    {"rows": {}, "errors": ["网络中断"]},
    {"rows": "", "errors": ["网络中断"]},
])
def test_unknown_transport_rows_are_not_treated_as_proven_empty(tmp_path, payload):
    clock = WallClock()
    run, starts = bridge(clock, [payload, SUCCESS])
    result = prepare(tmp_path, clock, run)
    assert result["status"] == "CANNOT_CONFIRM"
    assert len(starts) == 1
    assert "active_snapshot_transport_raw_status=UNKNOWN" in result["source_evidence"]
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("now", ["2026-10-20T15:49:59+08:00",
                                  "2026-10-20T15:55:00+08:00",
                                  "2026-10-21T15:50:00+08:00"])
def test_actual_wall_clock_overrides_stale_evaluated_at(tmp_path, now):
    clock = WallClock(now)
    run, starts = bridge(clock, [SUCCESS])
    result = prepare(tmp_path, clock, run)
    assert result["status"] == "CANNOT_CONFIRM"
    assert starts == []
    assert not list(tmp_path.rglob("*"))


def test_retry_sleep_reaching_cutoff_stops_before_next_provider(tmp_path):
    clock = WallClock("2026-10-20T15:54:59+08:00")
    run, starts = bridge(clock, [NETWORK, SUCCESS])
    result = prepare(tmp_path, clock, run)
    assert result["status"] == "CANNOT_CONFIRM"
    assert len(starts) == 1
    assert not list(tmp_path.rglob("*"))


def test_provider_crossing_cutoff_cannot_publish_or_retry(tmp_path):
    clock = WallClock("2026-10-20T15:54:59.950000+08:00")
    run, starts = bridge(clock, [SUCCESS])
    result = prepare(tmp_path, clock, run)
    assert result["status"] == "CANNOT_CONFIRM"
    assert len(starts) == 1
    assert not list(tmp_path.rglob("*"))


def test_clock_crossing_cutoff_during_final_processing_prevents_write(tmp_path, monkeypatch):
    clock = WallClock()
    run, starts = bridge(clock, [SUCCESS])
    original = snapshot._snapshot_temporal_partition_evidence
    calls = []

    def partition(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(1)
        if len(calls) == 2:
            clock.value = datetime(2026, 10, 20, 15, 55, tzinfo=ZONE)
        return result

    monkeypatch.setattr(snapshot, "_snapshot_temporal_partition_evidence", partition)
    result = prepare(tmp_path, clock, run)
    assert result["status"] == "CANNOT_CONFIRM"
    assert len(starts) == 1
    assert not list(tmp_path.rglob("*"))


def test_other_stage_keeps_one_attempt_and_original_result_shape(tmp_path):
    clock = WallClock("2026-10-20T14:59:01+08:00")
    run, starts = bridge(clock, [NETWORK, SUCCESS])
    result = prepare(tmp_path, clock, run, stage="STAGE_1445_1500",
                     cutoff_at="15:00:00", sleeper=False)
    assert result["status"] == "CANNOT_CONFIRM"
    assert len(starts) == 1
    assert "capture_attempts" not in result
    assert not list(tmp_path.rglob("*"))
