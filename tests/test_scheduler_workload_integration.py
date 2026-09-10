from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry, WorkloadExecutionError
from ops import run_v35_macos_scheduler as scheduler


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_catalog_registers_exact_recovery_workloads() -> None:
    catalog = load_workload_catalog()
    by_id = {item.workload_id: item for item in catalog.workloads}

    assert by_id["wechat_preselection_sync"].slots == ("0901", "2001")
    assert by_id["wechat_preselection_sync"].target_date_role == "TARGET_DATE"
    assert by_id["review_core_pool_pipeline"].slots == ("2115",)
    assert by_id["research_panel_runtime_evidence"].slots == ("1730",)
    assert by_id["research_panel_daily_a"].slots == ("1700",)
    assert by_id["research_panel_daily_a"].market_scope.value == "A_SHARE"
    assert by_id["research_panel_daily_hk"].slots == ("1720",)
    assert by_id["research_panel_daily_hk"].market_scope.value == "HK_CONNECT"
    assert all(item.safety.production_allowed is False for item in by_id.values())


def test_research_panel_slots_are_chronological() -> None:
    positions = [scheduler.ALL_SLOTS.index(slot) for slot in ("1700", "1710", "1720", "1730")]

    assert positions == sorted(positions)


@pytest.mark.parametrize(
    ("workload_id", "slot", "lane", "expected_status_key"),
    (
        ("research_panel_daily_a", "1700", "A", "A"),
        ("research_panel_daily_hk", "1720", "HK", "HK"),
    ),
)
def test_registry_dispatches_research_panel_daily_lanes_to_exact_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workload_id: str,
    slot: str,
    lane: str,
    expected_status_key: str,
) -> None:
    calls: list[list[str]] = []

    for name in (
        "V35_RESEARCH_PANEL_RECEIPT_ROOT",
        "V35_RESEARCH_PANEL_A_TDX_ROOT",
        "V35_RESEARCH_PANEL_HK_TDX_ROOT",
        "V35_RESEARCH_PANEL_A_SYNC_SCRIPT",
        "V35_RESEARCH_PANEL_A_FORMULA_SCRIPT",
        "V35_RESEARCH_PANEL_A_SEED_PANEL",
        "V35_RESEARCH_PANEL_A_DATA_ROOT",
        "V35_RESEARCH_PANEL_A_SELECTOR_POINTER",
        "V35_RESEARCH_PANEL_A_BACKTEST_POINTER",
        "V35_RESEARCH_PANEL_A_SELECTOR_SEED",
        "V35_RESEARCH_PANEL_A_BACKTEST_SEED",
        "V35_RESEARCH_PANEL_A_CONTRACT_CSV",
        "V35_RESEARCH_PANEL_A_CANONICAL_FORMULA",
        "V35_RESEARCH_PANEL_A_RETURN_ROOT",
        "V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT",
        "V35_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE",
        "V35_RESEARCH_PANEL_HK_ASSET_ROOT",
    ):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        status = {"A": "NOT_REQUESTED", "HK": "NOT_REQUESTED"}
        status[lane] = "READY"
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"overall_status": "READY", "lanes": {key: {"status": value} for key, value in status.items()}}),
            "",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        hk_0_2_python_executable=tmp_path / "hk02-python",
        repo_root=tmp_path,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260821",
        slot=slot,
        mode=DispatchMode.LIVE,
    )
    workload = next(item for item in load_workload_catalog().workloads if item.workload_id == workload_id)

    result = registry(workload, request)

    assert result["status"] == "SUCCEEDED"
    assert result["lane"] == expected_status_key
    assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))
    argv = calls[0]
    assert argv[1:4] == ["-m", "ops.macos_research_panel_daily", "--date"]
    assert argv[argv.index("--lane") + 1] == lane
    assert argv[argv.index("--date") + 1] == "20260821"


def test_scheduler_recovers_a_fixed_minute_slot_after_a_300_second_wake(tmp_path: Path) -> None:
    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 21, 9, 5, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
        catchup_window_minutes=10,
    )

    assert due["slot"] == "0901"
    assert due["catchup"] is True
    assert due["lag_minutes"] == 4


def test_scheduler_fixed_slot_idempotency_blocks_second_catchup(tmp_path: Path) -> None:
    receipt = tmp_path / "receipts" / "live" / "20260821" / "0901" / "ok.dispatch-receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps({"status": "SUCCEEDED", "finished_at": "2026-08-21T01:01:30Z"}),
        encoding="utf-8",
    )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 21, 9, 5, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
        catchup_window_minutes=10,
    )

    assert due["slot"] == "0900"
    assert due["catchup"] is True


def test_wechat_morning_probe_is_same_day_but_evening_sync_targets_next_trade_day() -> None:
    morning = scheduler.compute_dates(business_date="20260824", slot="0901")
    research_a = scheduler.compute_dates(business_date="20260824", slot="1700")
    research_hk = scheduler.compute_dates(business_date="20260824", slot="1720")
    evening = scheduler.compute_dates(business_date="20260824", slot="2001")

    assert morning["target_date"] == "20260824"
    assert research_a["target_date"] == "20260824"
    assert research_hk["target_date"] == "20260824"
    assert evening["target_date"] == "20260825"


def test_registry_dispatches_research_panel_evidence_to_fixed_entry(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []

    def runner(command, *, cwd, timeout_seconds, env):
        del timeout_seconds
        calls.append((command, cwd, env))
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "lanes": {
                        "A": {"status": "PARTIAL"},
                        "HK": {"status": "READY"},
                    }
                }
            ),
            "",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        selector_data_root=tmp_path / "selector",
        repo_root=tmp_path,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260821",
        slot="1730",
        mode=DispatchMode.LIVE,
    )
    workload = next(
        item for item in load_workload_catalog().workloads
        if item.workload_id == "research_panel_runtime_evidence"
    )

    result = registry(workload, request)

    assert result["status"] == "SUCCEEDED"
    assert result["evidence_status"] == "PARTIAL"
    assert calls[0][0][1:4] == ["-m", "ops.publish_research_panel_runtime_receipt", "--date"]
    assert "--producer-receipt-root" in calls[0][0]
    assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))


def test_registry_dispatches_wechat_exact_pair_missing_is_retryable(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            1,
            json.dumps({"status": "CANNOT_CONFIRM", "cannot_confirm": ["WECHAT_EXACT_DATE_INPUT_MISSING"]}),
            "",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        preselection_input_root=tmp_path / "data" / "preselection_inputs",
        repo_root=tmp_path,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260824",
        slot="2001",
        mode=DispatchMode.LIVE,
    )
    workload = next(
        item for item in load_workload_catalog().workloads
        if item.workload_id == "wechat_preselection_sync"
    )

    with pytest.raises(WorkloadExecutionError) as raised:
        registry(workload, request)

    result = raised.value.result
    assert result["status"] == "FAILED"
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert result["lane_status"] == "CANNOT_CONFIRM"
    assert result["target_date"] == "20260824"
    assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))
    argv = calls[0]
    assert argv[argv.index("--input-root") + 1] == str(tmp_path / "data" / "preselection_inputs")
    assert argv[argv.index("--data-root") + 1] != argv[argv.index("--input-root") + 1]


def test_wechat_sync_rejects_historical_pool_output_as_future_source(tmp_path: Path) -> None:
    def runner(command, *, cwd, timeout_seconds, env):
        del command, cwd, timeout_seconds, env
        raise AssertionError("rejected source must not invoke the sync module")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        preselection_input_root=tmp_path / "data" / "preselection_pools",
        repo_root=tmp_path,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260824",
        slot="0901",
        mode=DispatchMode.LIVE,
    )
    workload = next(
        item for item in load_workload_catalog().workloads
        if item.workload_id == "wechat_preselection_sync"
    )

    with pytest.raises(WorkloadExecutionError) as raised:
        registry(workload, request)

    assert raised.value.result["failure_class"] == "CONTRACT"
    assert "preselection_inputs" in raised.value.result["stderr"]


def test_registry_dispatches_review_core_partial_is_retryable(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '{"status":"PARTIAL","exit_code":2}', "")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared",
        shared_package_root=tmp_path / "shared-package",
        repo_root=tmp_path,
        runner=runner,
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260824",
        slot="2115",
        mode=DispatchMode.LIVE,
    )
    workload = next(
        item for item in load_workload_catalog().workloads
        if item.workload_id == "review_core_pool_pipeline"
    )

    with pytest.raises(WorkloadExecutionError) as raised:
        registry(workload, request)

    result = raised.value.result
    assert result["status"] == "FAILED"
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert result["pipeline_status"] == "PARTIAL"
    assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert calls[0][1:4] == ["-m", "ops.run_review_core_natural_pool_pipeline", "--trade-date"]


def test_retryable_wechat_receipt_retries_and_succeeds_after_exact_pair_ready(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    responses = iter(
        (
            subprocess.CompletedProcess(
                [],
                1,
                json.dumps({"status": "CANNOT_CONFIRM", "reason": "WECHAT_EXACT_DATE_INPUT_MISSING"}),
                "",
            ),
            subprocess.CompletedProcess([], 0, json.dumps({"status": "READY"}), ""),
        )
    )

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(command)
        response = next(responses)
        return subprocess.CompletedProcess(command, response.returncode, response.stdout, response.stderr)

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path,
        runner=runner,
    )
    catalog = load_workload_catalog()
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260824",
        slot="0901",
        mode=DispatchMode.LIVE,
    )
    ledger = ExecutionLedger(tmp_path / "ledger")

    first = dispatch_due(request, catalog, registry, ledger=ledger)
    assert first.status == "FAILED"
    assert first.failure_class == "UPSTREAM_NOT_READY"
    assert first.retry_after
    assert first.production_allowed is False
    assert first.buy_gate_updated is False
    assert first.orders_sent is False

    second = dispatch_due(request, catalog, registry, ledger=ledger)
    assert second.status == "SUCCEEDED"
    assert second.started_workload_ids == ("wechat_preselection_sync",)
    assert second.production_allowed is False
    assert second.buy_gate_updated is False
    assert second.orders_sent is False
    assert len(calls) == 2
