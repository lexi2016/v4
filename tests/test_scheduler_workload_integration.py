from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
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
ROOT = Path(__file__).resolve().parents[1]


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


def test_scheduled_slot_wraps_one_registry_with_lazy_stage_guard(monkeypatch, tmp_path: Path) -> None:
    from types import SimpleNamespace
    from ops import run_scheduled_slot as slot_runner

    catalog = load_workload_catalog()
    workloads = {item.workload_id: item for item in catalog.workloads}
    registry_instances = []
    guard_calls = []
    execution_calls = []

    class FakeRegistry:
        def __init__(self, **_kwargs):
            registry_instances.append(self)

        def __call__(self, workload, request, _decision):
            execution_calls.append((id(self), workload.workload_id, request.slot))
            return {
                "status": "SUCCEEDED",
                "workload_id": workload.workload_id,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

    def guard(workload, _request, _decision):
        guard_calls.append(workload.workload_id)
        return {"status": "READY"} if workload.workload_id in scheduler.STAGE_WORKLOAD_IDS else None

    def fake_dispatch(request, _catalog, executor, *, ledger, dry_run):
        del ledger, dry_run
        executor(workloads["v4_intraday_research"], request, None)
        executor(workloads["fupan_close_materials"], request, None)
        executor(workloads["fupan_close_materials"], request, None)
        return SimpleNamespace(
            status="SUCCEEDED",
            run_id="run-1",
            selected_workload_ids=("v4_intraday_research", "fupan_close_materials"),
            started_workload_ids=("v4_intraday_research", "fupan_close_materials"),
            receipt_path="receipts/run-1.json",
            failure_class="",
            retry_after="",
            release_id="",
            app_root="",
            release_manifest_path="",
            release_manifest_sha256="",
            upstream_fingerprint="",
            attempt=1,
            production_allowed=False,
            buy_gate_updated=False,
            orders_sent=False,
        )

    monkeypatch.setattr(slot_runner, "FixedExecutorRegistry", FakeRegistry)
    monkeypatch.setattr(slot_runner, "dispatch_due", fake_dispatch)
    monkeypatch.setattr(slot_runner, "load_workload_catalog", lambda: catalog)

    result = slot_runner.run_scheduled_slot(
        data_root=tmp_path / "data",
        slot="1500",
        business_date="20260824",
        scheduled_date="20260824",
        target_date="20260824",
        ledger_root=tmp_path / "ledger",
        workload_guard=guard,
    )

    assert result["status"] == "SUCCEEDED"
    assert len(registry_instances) == 1
    assert execution_calls == [
        (id(registry_instances[0]), "v4_intraday_research", "1500"),
        (id(registry_instances[0]), "fupan_close_materials", "1500"),
        (id(registry_instances[0]), "fupan_close_materials", "1500"),
    ]
    assert guard_calls == [
        "v4_intraday_research",
        "fupan_close_materials",
        "fupan_close_materials",
    ]


def test_two_process_stage_retry_preserves_successful_workloads(tmp_path: Path) -> None:
    """A reclaimed failed dispatch retries only the workload that failed."""

    from infrastructure.scheduling import dispatcher as dispatcher_module

    entries = []
    for relative in dispatcher_module._RUNTIME_IDENTITY_FILES:
        source = ROOT / relative
        content = source.read_bytes()
        entries.append({
            "path": relative,
            "kind": "file",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        })
    inventory = {
        "entries": entries,
        "entry_count": len(entries),
        "aggregate_sha256": hashlib.sha256(
            json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    manifest_body = {
        "schema_version": "v4.release_candidate.v1",
        "candidate": {"app_root": str(ROOT), "release_id": "fixture-stage-retry"},
        "application_inventory": inventory,
    }
    manifest_raw = json.dumps(
        manifest_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    manifest = tmp_path / "release-manifest.json"
    manifest.write_bytes(manifest_raw)
    child_env = os.environ.copy()
    child_env.update(
        {
            "V35_APP_ROOT": str(ROOT),
            "V35_RELEASE_ID": "fixture-stage-retry",
            "V35_RELEASE_MANIFEST_PATH": str(manifest),
            "V35_RELEASE_MANIFEST_SHA256": hashlib.sha256(manifest_raw).hexdigest(),
        }
    )

    worker = r'''
import json
import sys
from pathlib import Path
from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger

counts = {}
def executor(workload, _request, _decision):
    workload_id = workload.workload_id
    counts[workload_id] = counts.get(workload_id, 0) + 1
    if workload_id == "fupan_close_materials":
        return {
            "status": "FAILED",
            "failure_class": "UPSTREAM_NOT_READY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    return {
        "status": "SUCCEEDED",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }

request = DispatchRequest("20260824", "20260824", "20260824", "1500", DispatchMode.LIVE)
receipt = dispatch_due(request, load_workload_catalog(), executor,
                       ledger=ExecutionLedger(Path(sys.argv[1])))
print(json.dumps({"counts": counts, "status": receipt.status,
                  "failure_class": receipt.failure_class,
                  "started": list(receipt.started_workload_ids)}, sort_keys=True))
    '''
    command = [sys.executable, "-c", worker, str(tmp_path / "ledger")]
    first = subprocess.run(command, cwd=ROOT, env=child_env, capture_output=True, text=True, check=False)
    second = subprocess.run(command, cwd=ROOT, env=child_env, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    first_payload = json.loads(first.stdout.strip().splitlines()[-1])
    second_payload = json.loads(second.stdout.strip().splitlines()[-1])
    assert first_payload["status"] == "FAILED"
    assert first_payload["counts"] == {
        "v4_intraday_research": 1,
        "hourly_research": 1,
        "fupan_close_materials": 1,
    }
    assert second_payload["status"] == "FAILED"
    assert second_payload["counts"] == {"fupan_close_materials": 1}
    assert second_payload["started"] == []


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
        # Contract-level subprocess fixture, not an updater E2E assertion.
        flags = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
        receipt_root = Path(os.environ["V35_RESEARCH_PANEL_RECEIPT_ROOT"])
        receipt_root.mkdir(parents=True, exist_ok=True)
        raw = json.dumps({"schema_version": "v3.macos.research_panel_receipt.v1",
                          "target_date": "20260821", "lane": lane, "status": "READY", **flags}).encode()
        (receipt_root / f"{lane.lower()}-20260821.json").write_bytes(raw)
        lanes = {key: {"status": value} for key, value in status.items()}
        lanes[lane].update(receipt_sha256=hashlib.sha256(raw).hexdigest(), receipt_bytes=len(raw))
        return subprocess.CompletedProcess(command, 0, json.dumps({
            "schema_version": "v3.macos.research_panel_authority_envelope.v1",
            "target_date": "20260821", "requested_lane": lane,
            "overall_status": "READY", "lanes": lanes, **flags}), "")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
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
    assert result["receipt_verified"] is True
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


def test_retryable_wechat_receipt_retries_and_succeeds_after_exact_pair_ready(tmp_path: Path, monkeypatch) -> None:
    from infrastructure.scheduling.dispatcher import _RUNTIME_IDENTITY_FILES

    entries = []
    for relative in _RUNTIME_IDENTITY_FILES:
        content = (ROOT / relative).read_bytes()
        entries.append({"path": relative, "kind": "file", "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest()})
    manifest_raw = json.dumps({
        "schema_version": "v4.release_candidate.v1",
        "candidate": {"app_root": str(ROOT), "release_id": "fixture-wechat-retry"},
        "application_inventory": {
            "entries": entries, "entry_count": len(entries),
            "aggregate_sha256": hashlib.sha256(json.dumps(
                entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest(),
        },
    }, sort_keys=True).encode()
    manifest_path = tmp_path / "wechat-release-manifest.json"
    manifest_path.write_bytes(manifest_raw)
    for key, value in {
        "V35_APP_ROOT": str(ROOT), "V35_RELEASE_ID": "fixture-wechat-retry",
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": hashlib.sha256(manifest_raw).hexdigest(),
    }.items():
        monkeypatch.setenv(key, value)
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
