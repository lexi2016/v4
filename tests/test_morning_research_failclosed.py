from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.research_store import HourlyResearchStore
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.executor_registry import (
    FixedExecutorRegistry,
    WorkloadExecutionError,
)
from ops.run_hourly_research import run_hourly_research_file


def _request(slot: str) -> DispatchRequest:
    return DispatchRequest(
        scheduled_date="20260824",
        business_date="20260824",
        target_date="20260824",
        slot=slot,
        mode=DispatchMode.LIVE,
    )


def _workload(workload_id: str):
    return next(
        item
        for item in load_workload_catalog().workloads
        if item.workload_id == workload_id
    )


def _runner_for_empty_collect(calls: list[list[str]]):
    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        module = command[2]
        if module == "ops.run_zsxq_hourly_delta":
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"status": "READY_EMPTY", "topic_count": 0}),
                "",
            )
        if module == "ops.materialize_research_peripherals":
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"status": "READY"}), ""
            )
        if module == "ops.collect_hourly_research_input":
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"status": "READY_EMPTY", "row_count": 0}),
                "",
            )
        if module == "ops.run_hourly_research":
            pytest.fail("empty collector input must not invoke hourly runner")
        return subprocess.CompletedProcess(
            command, 0, json.dumps({"status": "READY"}), ""
        )

    return runner


@pytest.mark.parametrize("slot", ("0700", "0800"))
def test_hourly_empty_collector_is_not_materialized(
    tmp_path: Path, slot: str
) -> None:
    calls: list[list[str]] = []
    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path,
        runner=_runner_for_empty_collect(calls),
    )

    with pytest.raises(WorkloadExecutionError) as raised:
        registry(_workload("hourly_research"), _request(slot))

    result = raised.value.result
    assert result["status"] == "NOT_MATERIALIZED"
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert result["reason"] == "HOURLY_RESEARCH_INPUT_NOT_MATERIALIZED"
    assert result["row_count"] == 0
    assert result["hourly_artifact_status"] == "NOT_MATERIALIZED"
    assert all(
        result[field] is False
        for field in ("production_allowed", "buy_gate_updated", "orders_sent")
    )
    assert [command[2] for command in calls] == [
        "ops.materialize_research_peripherals",
        "ops.collect_hourly_research_input",
    ]


def test_zsxq_0830_empty_collector_is_not_materialized(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path,
        runner=_runner_for_empty_collect(calls),
    )

    with pytest.raises(WorkloadExecutionError) as raised:
        registry(_workload("zsxq_0830"), _request("0830"))

    result = raised.value.result
    assert result["status"] == "NOT_MATERIALIZED"
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert result["reason"] == "HOURLY_RESEARCH_INPUT_NOT_MATERIALIZED"
    assert result["row_count"] == 0
    assert result["hourly_artifact_status"] == "NOT_MATERIALIZED"
    assert [command[2] for command in calls] == [
        "ops.run_zsxq_hourly_delta",
        "ops.collect_hourly_research_input",
    ]


def test_dispatch_receipt_fail_closes_empty_hourly_input_without_artifact(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    ledger_root = tmp_path / "ledger"
    calls: list[list[str]] = []
    registry = FixedExecutorRegistry(
        data_root=data_root,
        repo_root=tmp_path,
        runner=_runner_for_empty_collect(calls),
    )

    receipt = dispatch_due(
        _request("0700"),
        load_workload_catalog(),
        registry,
        ledger=ExecutionLedger(ledger_root),
    )

    assert receipt.status == "FAILED"
    assert receipt.failure_class == "UPSTREAM_NOT_READY"
    assert receipt.started_workload_ids == ()
    assert receipt.workload_results[0]["status"] == "NOT_MATERIALIZED"
    assert receipt.workload_results[0]["failure_class"] == "UPSTREAM_NOT_READY"
    aggregate = json.loads(
        (ledger_root / receipt.receipt_path).read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "FAILED"
    assert aggregate["failure_class"] == "UPSTREAM_NOT_READY"
    assert not (data_root / "research" / "hourly").exists()
    assert not (data_root / "research" / "hourly" / "latest.json").exists()
    assert [command[2] for command in calls] == [
        "ops.materialize_research_peripherals",
        "ops.collect_hourly_research_input",
    ]


def test_non_empty_hourly_collector_keeps_existing_runner_path(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        module = command[2]
        if module == "ops.materialize_research_peripherals":
            payload = {"status": "READY"}
        elif module == "ops.collect_hourly_research_input":
            payload = {
                "status": "READY_WITH_RESEARCH_POOL",
                "row_count": 3,
                "source_path": "research/incoming/20260824/0700.json",
            }
        elif module == "ops.run_hourly_research":
            payload = {
                "status": "SUCCEEDED",
                "runtime_status": "READY_WITH_RESEARCH_POOL",
            }
        else:
            payload = {"status": "READY"}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path,
        runner=runner,
    )
    result = registry(_workload("hourly_research"), _request("0700"))

    assert result["status"] == "SUCCEEDED"
    assert [command[2] for command in calls] == [
        "ops.materialize_research_peripherals",
        "ops.collect_hourly_research_input",
        "ops.run_hourly_research",
    ]


def _write_empty_source(path: Path, slot: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "v3_research_lane.v2",
                "trade_date": "20260824",
                "source_manifest": {
                    "generated_at": f"2026-08-24T{slot[:2]}:{slot[2:]}:00+08:00",
                    "hourly_slot": slot,
                },
                "raw_items": [],
                "research_items": [],
                "research_cards": [],
                "stock_research_timeline": [],
                "stock_research_daily": [],
                "research_pool_bridge": [],
                "cannot_confirm": ["ZSXQ_STATUS_NOT_AVAILABLE_BY_SLOT"],
            }
        ),
        encoding="utf-8",
    )


def test_direct_hourly_runner_empty_source_is_not_materialized(tmp_path: Path) -> None:
    source = tmp_path / "empty.json"
    _write_empty_source(source, "0700")

    result = run_hourly_research_file(
        data_root=tmp_path / "data",
        source=source,
        business_date="20260824",
        target_date="20260824",
        slot="0700",
        mode="LIVE",
    )

    assert result["status"] == "NOT_MATERIALIZED"
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert result["reason"] == "HOURLY_RESEARCH_INPUT_NOT_MATERIALIZED"
    assert result["hourly_artifact_status"] == "NOT_MATERIALIZED"
    assert all(
        result[field] is False
        for field in ("production_allowed", "buy_gate_updated", "orders_sent")
    )
    assert HourlyResearchStore(tmp_path / "data").read_exact(
        "20260824", "0700", mode="LIVE"
    ) is None
    assert HourlyResearchStore(tmp_path / "data").read_latest() is None


def test_direct_hourly_runner_cli_empty_source_exits_2(tmp_path: Path) -> None:
    source = tmp_path / "empty.json"
    _write_empty_source(source, "0800")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ops.run_hourly_research",
            "--data-root",
            str(tmp_path / "data"),
            "--date",
            "20260824",
            "--target-date",
            "20260824",
            "--slot",
            "0800",
            "--mode",
            "LIVE",
            "--source",
            str(source),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**dict(os.environ), "PYTHONPATH": "."},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "NOT_MATERIALIZED"
    assert payload["failure_class"] == "UPSTREAM_NOT_READY"
    assert not (tmp_path / "data" / "research" / "hourly").exists()
