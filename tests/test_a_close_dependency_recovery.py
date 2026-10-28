"""The observed A-close missing-panel failure is a bounded data dependency."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from types import SimpleNamespace

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling import executor_registry as registry_module
from infrastructure.scheduling.dispatcher import (
    capture_retry_source_identity, dispatch_due, _failure_class,
)
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry, WorkloadExecutionError
from ops.run_v4_macos_scheduler_due import _slot_blocks_retry



@pytest.fixture(autouse=True)
def _bind_actual_source_identity_when_required(tmp_path, monkeypatch):
    from infrastructure.scheduling import dispatcher
    if hasattr(dispatcher, 'validate_release_identity'):
        from tests.test_v4_source_scheduler_closure import bind_release
        bind_release(tmp_path, monkeypatch)


def _request():
    return DispatchRequest(scheduled_date="20261028", business_date="20261028",
        target_date="20261028", slot="1605", mode=DispatchMode.LIVE)


def test_absent_a_close_panel_is_input_missing_without_invoking_builder(tmp_path, monkeypatch):
    registry = FixedExecutorRegistry(data_root=tmp_path / "data", selector_data_root=tmp_path / "selector")
    def missing(*args):
        raise FileNotFoundError("no selector panel with max trade_date >= 20261028")
    monkeypatch.setattr(registry_module, "resolve_selector_panel", missing)
    monkeypatch.setattr(registry, "_run", lambda *args: pytest.fail("builder must not run"))
    with pytest.raises(WorkloadExecutionError) as caught:
        registry._a_share_close_review(_request())
    result = caught.value.result
    assert result["failure_class"] == "INPUT_MISSING"
    assert _failure_class((result,)) == "INPUT_MISSING"
    assert result["reason"] == "A_CLOSE_SELECTOR_PANEL_UNAVAILABLE"
    assert "selector panel unresolved:" in result["stderr"]
    assert all(result[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert not (tmp_path / "data").exists()


def test_a_close_pointer_change_reopens_only_data_dependency_retry(tmp_path):
    selector = tmp_path / "selector"
    pointer = selector / "data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt"
    executor = SimpleNamespace(selector_data_root=selector)
    source = capture_retry_source_identity(executor, _request(), ("a_share_close_review",))
    assert source["status"] == "IDENTIFIED"
    assert source["items"][0]["state"] == "MISSING"
    assert len(source["descriptors"]) == 1
    assert source["descriptors"][0]["path"] == str(pointer)
    ledger = ExecutionLedger(tmp_path / "ledger")
    receipt_path = "receipts/live/20261028/1605/previous.dispatch-receipt.json"
    receipt = dict(status="FAILED", failure_class="INPUT_MISSING", source_identity=source,
        finished_at="2026-10-28T08:09:15Z", retry_after="2026-10-28T08:14:15Z")
    ledger.write_receipt(receipt_path, receipt)
    before = (ledger.root / receipt_path).read_bytes()
    now = datetime(2026, 10, 28, 19, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert _slot_blocks_retry(ledger.root, "20261028", "1605", moment=now)
    pointer.parent.mkdir(parents=True)
    pointer.write_text("/verified/current/selector_to_20261028.parquet")
    assert not _slot_blocks_retry(ledger.root, "20261028", "1605", moment=now)
    assert (ledger.root / receipt_path).read_bytes() == before
    # Genuine contract failures remain terminal even when this pointer changes.
    ledger.write_receipt(receipt_path, {**receipt, "failure_class": "CONTRACT"})
    assert _slot_blocks_retry(ledger.root, "20261028", "1605", moment=now)


def test_manual_fixed_slot_preserves_failed_receipt_and_appends_late_attempt(tmp_path, monkeypatch):
    registry = FixedExecutorRegistry(data_root=tmp_path / "data", selector_data_root=tmp_path / "selector")
    ledger = ExecutionLedger(tmp_path / "ledger")
    catalog = load_workload_catalog()
    # Freeze to the actual existing A-close owner, avoiding unrelated 16:05 nodes.
    from dataclasses import replace
    workload = next(w for w in catalog.workloads if w.workload_id == "a_share_close_review")
    catalog = replace(catalog, workloads=(workload,))
    available = False
    panel = tmp_path / "selector_to_20261028.parquet"
    def resolver(*args):
        if not available:
            raise FileNotFoundError("no selector panel with max trade_date >= 20261028")
        return panel
    monkeypatch.setattr(registry_module, "resolve_selector_panel", resolver)
    calls = []
    def run(module, arguments):
        calls.append((module, arguments))
        return dict(status="SUCCEEDED", exit_code=0, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    monkeypatch.setattr(registry, "_run", run)
    first = dispatch_due(_request(), catalog, registry, ledger=ledger)
    assert first.status == "FAILED" and first.failure_class == "INPUT_MISSING"
    preserved = (ledger.root / first.receipt_path).read_bytes()
    available = True
    second = dispatch_due(_request(), catalog, registry, ledger=ledger)
    assert second.status == "SUCCEEDED" and second.attempt == 2
    assert first.run_id != second.run_id
    assert (ledger.root / first.receipt_path).read_bytes() == preserved
    assert calls[0][0] == "ops.build_a_share_close_review"
    assert calls[0][1][calls[0][1].index("--date") + 1] == "20261028"
    assert (registry.data_root / ".dispatcher_tmp/selector_panel_pointer.txt").read_text() == str(panel)
    # Existing successful ownership prevents any third builder execution.
    third = dispatch_due(_request(), catalog, registry, ledger=ledger)
    assert third.status == "CONCURRENCY_SKIPPED"
    assert len(calls) == 1


def test_a_close_other_contract_errors_are_not_reclassified(tmp_path, monkeypatch):
    registry = FixedExecutorRegistry(data_root=tmp_path / "data", selector_data_root=tmp_path / "selector")
    def invalid(*args):
        raise ValueError("panel contract mismatch")
    monkeypatch.setattr(registry_module, "resolve_selector_panel", invalid)
    with pytest.raises(ValueError, match="contract mismatch"):
        registry._a_share_close_review(_request())
