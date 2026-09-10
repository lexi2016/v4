from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.executor_registry import (
    FixedExecutorRegistry,
    WorkloadExecutionError,
)


CATALOG_PATH = Path(__file__).resolve().parents[1] / "contracts" / "runtime_workloads.json"
HOURLY_SLOTS = tuple(f"{hour:02d}00" for hour in range(7, 24))


def _request(slot: str, date: str = "20260815") -> DispatchRequest:
    return DispatchRequest(
        scheduled_date=date,
        business_date=date,
        target_date=date,
        slot=slot,
        mode=DispatchMode.LIVE,
    )


def _runner(calls: list[list[str]], *, collect_status: str = "READY_WITH_RESEARCH_POOL"):
    def run(
        command: list[str], *, cwd: Path | None, timeout_seconds: int, env: dict[str, str] | None
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout_seconds, env
        calls.append(command)
        module = command[2]
        if module == "ops.run_zsxq_hourly_delta":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"status": "READY", "topic_count": 75}),
                stderr="",
            )
        if module == "ops.collect_hourly_research_input":
            return subprocess.CompletedProcess(
                command,
                0 if collect_status == "READY_WITH_RESEARCH_POOL" else 1,
                stdout=json.dumps(
                    {
                        "status": collect_status,
                        "row_count": 257 if collect_status == "READY_WITH_RESEARCH_POOL" else 0,
                    }
                ),
                stderr="",
            )
        if module == "ops.run_hourly_research":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "status": "READY",
                        "row_count": 257,
                        "source_slot": "0830",
                        "research_date": "20260815",
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "READY"}),
            stderr="",
        )

    return run


def test_hourly_catalog_has_natural_day_every_hour_and_weekend_dry_run_selection():
    catalog = load_workload_catalog(CATALOG_PATH)
    hourly = next(row for row in catalog.workloads if row.workload_id == "hourly_research")

    assert hourly.slots == HOURLY_SLOTS
    assert hourly.run_policy.value == "NATURAL_DAY"
    for slot in HOURLY_SLOTS:
        receipt = dispatch_due(
            _request(slot, date="20260816"),
            catalog,
            lambda *_args: pytest.fail("dry-run must not execute a workload"),
            dry_run=True,
        )
        assert receipt.status == "DRY_RUN_SELECTED"
        assert "hourly_research" in receipt.selected_workload_ids


def test_hourly_research_refreshes_paginated_zsxq_before_building_the_slot():
    catalog = load_workload_catalog(CATALOG_PATH)
    hourly = next(row for row in catalog.workloads if row.workload_id == "hourly_research")
    calls: list[list[str]] = []
    registry = FixedExecutorRegistry(
        data_root=Path("/tmp/v35-hourly-research-test-data"),
        repo_root=Path("/tmp/v35-hourly-research-test-repo"),
        runner=_runner(calls),
    )

    result = registry(hourly, _request("1800"), None)

    assert result["status"] == "SUCCEEDED"
    assert result["workload_id"] == "hourly_research"
    assert result["modules"] == [
        "ops.run_zsxq_hourly_delta",
        "ops.materialize_research_peripherals",
        "ops.collect_hourly_research_input",
        "ops.run_hourly_research",
    ]
    assert [command[2] for command in calls] == result["modules"]
    assert "--timeout" in calls[1]
    assert calls[1][calls[1].index("--timeout") + 1] == "10"
    assert "--slot" in calls[-1] and calls[-1][calls[-1].index("--slot") + 1] == "1800"


def _publish_exact_peripherals(data_root: Path, trade_date: str) -> None:
    store = ResearchPeripheralStore(data_root)
    common = {
        "schema_version": "v3_5.research_peripheral.v1",
        "trade_date": trade_date,
        "status": "CANNOT_CONFIRM",
        "fetched_at": "2026-08-17T12:00:00+08:00",
        "raw_item_count": 0,
        "item_count": 0,
        "overview": [],
        "details": [],
        "items": [],
        "cannot_confirm": ["UPSTREAM_TEMPORARILY_UNAVAILABLE"],
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    store.publish(
        {
            **common,
            "source": "external_finance",
            "source_url": "https://news.google.com/rss/search",
        }
    )
    store.publish(
        {
            **common,
            "source": "ai_news",
            "source_url": "https://aihot.example.test/",
        }
    )


def test_hourly_research_reuses_verified_exact_date_peripherals_after_refresh_timeout(tmp_path):
    catalog = load_workload_catalog(CATALOG_PATH)
    hourly = next(row for row in catalog.workloads if row.workload_id == "hourly_research")
    data_root = tmp_path / "data"
    _publish_exact_peripherals(data_root, "20260815")
    calls: list[list[str]] = []

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, env
        calls.append(command)
        if command[2] == "ops.materialize_research_peripherals":
            raise subprocess.TimeoutExpired(command, timeout_seconds)
        return _runner([])(command, cwd=None, timeout_seconds=timeout_seconds, env=None)

    registry = FixedExecutorRegistry(
        data_root=data_root,
        repo_root=tmp_path / "repo",
        runner=runner,
    )

    result = registry(hourly, _request("1800"), None)

    assert result["status"] == "SUCCEEDED"
    assert result["degraded_inputs"]["reason"] == "PERIPHERAL_REFRESH_TIMEOUT_REUSED_EXACT_DATE"
    assert result["degraded_inputs"]["source_fetched_at"] == {
        "ai_news": "2026-08-17T12:00:00+08:00",
        "external_finance": "2026-08-17T12:00:00+08:00",
    }
    assert [command[2] for command in calls] == [
        "ops.run_zsxq_hourly_delta",
        "ops.materialize_research_peripherals",
        "ops.collect_hourly_research_input",
        "ops.run_hourly_research",
    ]


def test_hourly_research_refresh_timeout_fails_closed_without_exact_date_peripherals(tmp_path):
    catalog = load_workload_catalog(CATALOG_PATH)
    hourly = next(row for row in catalog.workloads if row.workload_id == "hourly_research")

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, env
        raise subprocess.TimeoutExpired(command, timeout_seconds)

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        runner=runner,
    )

    with pytest.raises(WorkloadExecutionError):
        registry(hourly, _request("1800"), None)


def test_hourly_research_fails_closed_when_same_day_source_is_missing():
    catalog = load_workload_catalog(CATALOG_PATH)
    hourly = next(row for row in catalog.workloads if row.workload_id == "hourly_research")
    calls: list[list[str]] = []
    registry = FixedExecutorRegistry(
        data_root=Path("/tmp/v35-hourly-research-test-data"),
        repo_root=Path("/tmp/v35-hourly-research-test-repo"),
        runner=_runner(calls, collect_status="FAILED"),
    )

    with pytest.raises(WorkloadExecutionError):
        registry(hourly, _request("1800"), None)

    assert [command[2] for command in calls] == [
        "ops.run_zsxq_hourly_delta",
        "ops.materialize_research_peripherals",
        "ops.collect_hourly_research_input",
    ]


def test_hourly_research_records_verified_artifact_but_requires_zsxq_refresh_retry(tmp_path):
    catalog = load_workload_catalog(CATALOG_PATH)
    hourly = next(row for row in catalog.workloads if row.workload_id == "hourly_research")
    calls: list[list[str]] = []

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        module = command[2]
        if module == "ops.run_zsxq_hourly_delta":
            return subprocess.CompletedProcess(
                command,
                1,
                stdout=json.dumps(
                    {
                        "status": "CANNOT_CONFIRM",
                        "reason": "MCP transport: lookup mcp.zsxq.com: no such host",
                    }
                ),
                stderr="",
            )
        if module == "ops.collect_hourly_research_input":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "status": "READY_WITH_RESEARCH_POOL",
                        "row_count": 575,
                        "source_path": "research/incoming/20260815/0900.json",
                    }
                ),
                stderr="",
            )
        if module == "ops.run_hourly_research":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "status": "SUCCEEDED",
                        "runtime_status": "READY_WITH_RESEARCH_POOL",
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "READY"}),
            stderr="",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        runner=runner,
    )

    with pytest.raises(WorkloadExecutionError) as error:
        registry(hourly, _request("0900"), None)

    result = error.value.result
    assert result["status"] == "FAILED"
    assert result["reason"] == "RESEARCH_SOURCE_REFRESH_RETRY_REQUIRED"
    assert result["retryable_sources"] == ["zsxq"]
    assert result["hourly_artifact_status"] == "SUCCEEDED"
    assert result["zsxq_degraded_input"] == {
        "reason": "ZSXQ_REFRESH_FAILED_REUSED_VERIFIED_SAME_DAY_INPUT",
        "refresh_exit_code": 1,
        "fallback_row_count": 575,
        "fallback_source_path": "research/incoming/20260815/0900.json",
    }
    assert [command[2] for command in calls] == [
        "ops.run_zsxq_hourly_delta",
        "ops.materialize_research_peripherals",
        "ops.collect_hourly_research_input",
        "ops.run_hourly_research",
    ]


def test_hourly_research_refresh_failure_stays_closed_without_verified_same_day_rows(
    tmp_path,
):
    catalog = load_workload_catalog(CATALOG_PATH)
    hourly = next(row for row in catalog.workloads if row.workload_id == "hourly_research")
    calls: list[list[str]] = []

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        module = command[2]
        if module == "ops.run_zsxq_hourly_delta":
            return subprocess.CompletedProcess(
                command,
                1,
                stdout=json.dumps({"status": "CANNOT_CONFIRM", "reason": "DNS failure"}),
                stderr="",
            )
        if module == "ops.collect_hourly_research_input":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"status": "READY_EMPTY", "row_count": 0}),
                stderr="",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "READY"}),
            stderr="",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        runner=runner,
    )

    with pytest.raises(WorkloadExecutionError) as caught:
        registry(hourly, _request("0900"), None)

    assert caught.value.result["reason"] == "ZSXQ_REFRESH_FAILED_NO_VERIFIED_SAME_DAY_INPUT"
    assert [command[2] for command in calls] == [
        "ops.run_zsxq_hourly_delta",
        "ops.materialize_research_peripherals",
        "ops.collect_hourly_research_input",
    ]


def test_hourly_research_passes_versioned_recovery_input_to_the_transformer(tmp_path):
    catalog = load_workload_catalog(CATALOG_PATH)
    hourly = next(row for row in catalog.workloads if row.workload_id == "hourly_research")
    calls: list[list[str]] = []

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        module = command[2]
        if module == "ops.collect_hourly_research_input":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "status": "READY_WITH_RESEARCH_POOL",
                        "row_count": 575,
                        "source_path": "research/incoming/20260815/1000.recovery-abcd.json",
                        "recovery": True,
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "READY"}),
            stderr="",
        )

    data_root = tmp_path / "data"
    registry = FixedExecutorRegistry(
        data_root=data_root,
        repo_root=tmp_path / "repo",
        runner=runner,
    )

    result = registry(hourly, _request("1000"), None)

    assert result["status"] == "SUCCEEDED"
    run_command = next(command for command in calls if command[2] == "ops.run_hourly_research")
    assert run_command[run_command.index("--source") + 1] == str(
        data_root / "research/incoming/20260815/1000.recovery-abcd.json"
    )


def test_independent_0830_registration_remains_retired_and_non_dispatchable():
    catalog = load_workload_catalog(CATALOG_PATH)
    registration = next(
        row
        for row in catalog.task_registrations
        if row.legacy_task_id == "OpeningAdvisorV3_0830_ZsxqResearch"
    )

    assert registration.status == "RETIRED_BY_EXACT_CATALOG_OWNER"
    assert registration.enabled is False
    assert registration.execution_allowed is False
