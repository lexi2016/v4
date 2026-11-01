"""Frozen runtime governance behavior; all mutations stay in tmp fixtures."""
from contextlib import nullcontext
from datetime import datetime
import importlib
import json
from pathlib import Path
import plistlib
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from infrastructure.review_generation import materialize_once
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling import dispatcher
from contracts.runtime_tasks import DispatchRequest










def test_generation_noop_and_new_generation_retains_history(tmp_path):
    state = {"input": "one", "current": None}; calls = []
    def build(current):
        calls.append(state["input"]); state["current"] = {"product": state["input"]}
        return {"review": state["current"], "publication": {"sha256": state["input"]}}
    def run(builder="a" * 64):
        return materialize_once(root=tmp_path, market="HK", date="20261030", builder=builder,
            inputs=lambda: state["input"], read_current=lambda: state["current"], build=build)
    first = run(); second = run()
    assert second["status"] == "NOOP" and len(calls) == 1
    state["input"] = "two"; third = run()
    assert third["generation"] != first["generation"] and len(calls) == 2
    fourth = run("b" * 64)
    assert fourth["generation"] != third["generation"] and len(list(tmp_path.glob("review_generations/HK/20261030/*.json"))) == 3


def test_real_a_builder_same_generation_skips_model_and_changed_input_supersedes(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from ops import build_a_share_close_review as builder
    panel = tmp_path / "panel.parquet"; pointer = tmp_path / "pointer.txt"; pointer.write_text(str(panel))
    rows = [{"trade_date": "20261030", "ts_code": code, "name": code, "pct_chg": pct, "amount": 100000000., "bar_close_pos": .5, "tdx_industry_code": "1", "tdx_industry_name": "test"} for code, pct in (("600000.SH", 2.), ("000001.SZ", -1.), ("920001.BJ", .1))]
    pq.write_table(pa.Table.from_pylist(rows), panel)
    first = builder.build_review_from_panel(tmp_path / "data", "20261030", panel_pointer=pointer)
    original = builder.build_close_model
    monkeypatch.setattr(builder, "build_close_model", lambda *a: pytest.fail("same generation rebuilt model"))
    assert builder.build_review_from_panel(tmp_path / "data", "20261030", panel_pointer=pointer)["status"] == "NOOP"
    monkeypatch.setattr(builder, "build_close_model", original)
    rows[0]["pct_chg"] = 3.; pq.write_table(pa.Table.from_pylist(rows), panel)
    second = builder.build_review_from_panel(tmp_path / "data", "20261030", panel_pointer=pointer)
    assert second["generation"] != first["generation"]
    assert second["publication"]["previous_sha256"] == first["publication"]["sha256"]


def test_stage_completion_and_cron_share_only_workload_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatcher, "validate_release_identity", lambda: {}, raising=False)
    request = DispatchRequest("20261030", "20261030", "20261030", "1500", "LIVE")
    ledger = ExecutionLedger(tmp_path); catalog = load_workload_catalog(); calls = []
    def executor(workload, *args):
        calls.append(workload.workload_id)
        return {"status": "SUCCEEDED", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    event = dispatcher.dispatch_due(request, catalog, executor, ledger=ledger, completion_workload_ids=("fupan_close_materials",))
    assert event.status == "SUCCEEDED" and calls == ["fupan_close_materials"]
    from ops.run_v4_macos_scheduler_due import _slot_blocks_retry
    assert not _slot_blocks_retry(tmp_path, "20261030", "1500", moment=datetime(2026, 10, 30, 15, 1, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert not (tmp_path / "claims/live/20261030/1500/dispatch.claim.json").exists()
    cron = dispatcher.dispatch_due(request, catalog, executor, ledger=ledger)
    assert calls.count("fupan_close_materials") == 1
    assert "hourly_research" in calls
    assert cron.status == "DUPLICATE_WORKLOAD_SKIPPED"
    with pytest.raises(ValueError, match="COMPLETION_WORKLOAD_SCOPE_INVALID"):
        dispatcher.dispatch_due(request, catalog, executor, ledger=ledger, completion_workload_ids=("hourly_research",))


def test_tdx_same_request_reuses_raw_sha_and_preserves_window_amount():
    from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider
    calls = []
    class API:
        def get_history_minute_time_data(self, *args):
            calls.append(args); return [{"price": 10., "vol": 1.} for _ in range(240)]
        def disconnect(self): pass
    provider = TdxMinuteReplayProvider(api_factory=API)
    args = dict(trade_date="20261030", stage_id="STAGE_1445_1500", cutoff_at="2026-10-30T15:00:00+08:00")
    first = provider.snapshot(["A.600000"], **args); second = provider.snapshot(["A.600000"], **args)
    assert first == second and len(calls) == 1
    assert first["rows"][0]["turnover"] == 15000.
    provider.snapshot(["A.600000"], **{**args, "cutoff_at": "2026-10-30T14:59:00+08:00"})
    assert len(calls) == 2


def test_hk_reuse_does_not_accept_manager_or_daily_source():
    from ops.collect_hkconnect_close_snapshot import _reusable_snapshot
    snapshot = {"trade_date": "20261030", "status": "READY", "rows": [{}], "source_mode": "MANAGER_PYTDX_CLOSE",
        "universe_count": 1, "same_date_row_count": 1, "coverage_ratio": 1., "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    assert not _reusable_snapshot(snapshot, trade_date="20261030", min_universe_count=1, required_coverage_ratio=1.)


def test_recovery_three_paths_preserve_original_and_raw_errors(tmp_path, monkeypatch):
    from ops.recover_stage_data import recover
    from stage_center.acquisition import SourceResult
    from stage_center.raw_store import RawStore
    import stage_center.runner as runner
    config = {k: str(tmp_path / k) for k in ("raw_root", "selection_root", "receipt_root")}
    original = tmp_path / "receipt_root/20261030/STAGE_1445_1500/receipt.json"
    original.parent.mkdir(parents=True); original.write_bytes(b'{"status":"FAILED"}')
    monkeypatch.setattr(RawStore, "verify_latest", lambda *a: {"verified": {"artifact_sha256": "a" * 64}})
    monkeypatch.setattr(runner, "_read_verified_raw_source", lambda *a: SourceResult("original", "READY", rows=({"code": "600000"},)))
    args = dict(config=config, trade_date="20261030", stage_id="STAGE_1445_1500", market="A_SHARE", output=tmp_path / "recovery")
    replay = recover(**args, action="replay-original")
    assert replay["status"] == "ORIGINAL_RAW_REPLAYED" and replay["network_invocations"] == 0
    gap = recover(**args, action="record-gap")
    assert gap["status"] == "CANNOT_CONFIRM" and gap["original_receipt_unchanged"]
    from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider
    class API:
        def get_history_minute_time_data(self, *a): return [{"price": 10., "vol": 1.}] * 240
        def disconnect(self): pass
    historical = recover(**args, action="historical-minute", symbols=("A.600000",), provider=TdxMinuteReplayProvider(api_factory=API))
    assert historical["status"] == "AFTERFACT_MINUTE_OBSERVATION"
    assert historical["afterfact"] and not historical["pit_safe"] and historical["raw_response_sha256"]
    assert original.read_bytes() == b'{"status":"FAILED"}'
    assert len(list((tmp_path / "recovery").glob("*/*/*/recovery_receipt.json"))) == 3


def test_outside_real_session_canary_does_not_query(tmp_path):
    from ops.verify_tdx_trade_window_canary import run
    result = run(tmp_path, now=datetime(2026, 11, 2, 1, 0, tzinfo=ZoneInfo("Asia/Shanghai")), api_factory=lambda: pytest.fail("non-session network"))
    assert result["reason"] == "OUTSIDE_REAL_TRADING_WINDOW" and result["network_invocations"] == 0
    assert [r["market"] for r in result["samples"]] == ["SH", "SZ", "BJ"]


def test_real_hk_builder_reuses_verified_product_on_second_call(tmp_path, monkeypatch):
    from infrastructure.hkconnect_close_store import CloseSnapshotStore
    from ops import build_close_review as builder
    snapshot = {"schema_version": "v3_5.hkconnect_close_snapshot.v1", "trade_date": "20261030", "status": "READY",
        "source_mode": "ISOLATED_FIXTURE_ONLY", "source_input_sha256": "a" * 64, "universe_count": 600,
        "same_date_row_count": 600, "coverage_ratio": 1., "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "rows": [{"code": f"HK.{i:05d}", "trade_date": "20261030", "close": 10 + i / 100, "pre_close": 10., "amount": 1000000.} for i in range(1, 601)]}
    CloseSnapshotStore(tmp_path).import_snapshot(snapshot)
    first = builder.build_close_review(tmp_path, "20261030")
    monkeypatch.setattr(builder, "build_native_close_review", lambda *a, **k: pytest.fail("same generation HK builder invoked"))
    second = builder.build_close_review(tmp_path, "20261030")
    assert second["status"] == "NOOP" and second["review"] == first["review"]


def test_completion_hooks_are_default_off_and_preserve_receipt_on_failure(monkeypatch):
    from infrastructure.stage_completion_hooks import deliver
    import sys
    calls = []
    def callback(**kwargs): calls.append(kwargs); raise RuntimeError("fixture consumer failure")
    monkeypatch.setitem(sys.modules, "infrastructure.report_evidence_sidecar", SimpleNamespace(on_stage_completed=callback))
    receipt = {"status": "READY", "markets": {"A_SHARE": {"run_id": "exact"}}}
    before = json.dumps(receipt, sort_keys=True)
    args = dict(trade_date="20261030", stage_id="STAGE_1445_1500", receipt=receipt, settled=True, mode="NATURAL")
    assert deliver(config={}, **args) == [] and not calls
    result = deliver(config={"report_evidence_sidecar_enabled": True}, **args)
    assert result[0]["status"] == "CANNOT_CONFIRM" and json.dumps(receipt, sort_keys=True) == before
    assert deliver(config={"report_evidence_sidecar_enabled": True}, **{**args, "mode": "BACKFILL"}) == []


def test_natural_completion_uses_verified_store_and_runner_without_display_backfill_flags(tmp_path, monkeypatch):
    from ops import consume_close_stage_completion as completion
    envelope = {"run_id": "exact-run", "artifact_id": "exact-artifact"}
    selected = {"trade_date": "20261030", "stage_id": "STAGE_1445_1500", "status": "PARTIAL_WITH_ROWS",
        "markets": {"A_SHARE": {**envelope, "status": "PARTIAL_WITH_ROWS"}},
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    class Consumer:
        store = SimpleNamespace(read_verified=lambda *a: envelope)
        def __init__(self, *a): pass
        def get(self, *a, **k): return selected
    monkeypatch.setattr(completion, "StageSelectionConsumer", Consumer)
    runner = tmp_path / "receipts/20261030/STAGE_1445_1500/receipt.json"; runner.parent.mkdir(parents=True)
    runner_payload = {**selected, "schema_version": "stage_center.runner.receipt.v1", "dispatch_mode": "NATURAL"}
    runner.write_text(json.dumps(runner_payload))
    calls = []
    monkeypatch.setattr(completion, "dispatch_due", lambda *a, **k: calls.append(k["completion_workload_ids"]) or SimpleNamespace(to_dict=lambda: {"status": "SUCCEEDED"}))
    args = dict(trade_date="20261030", stage_id="STAGE_1445_1500", selection_root=tmp_path / "selection", receipt_root=tmp_path / "receipts",
        data_root=tmp_path / "data", ledger_root=tmp_path / "ledger", registry=lambda *a: None,
        now=datetime(2026, 10, 30, 15, 0, 10, tzinfo=ZoneInfo("Asia/Shanghai")))
    result = completion.consume(**args)
    assert result["status"] == "SUCCEEDED" and calls == [("fupan_close_materials",)]
    runner_payload["markets"]["A_SHARE"]["run_id"] = "foreign-run"; runner.write_text(json.dumps(runner_payload))
    assert completion.consume(**args)["status"] == "CANNOT_CONFIRM" and len(calls) == 1


def test_event_failure_does_not_release_foreign_cron_claim_or_close_busy_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatcher, "validate_release_identity", lambda: {}, raising=False)
    request = DispatchRequest("20261030", "20261030", "20261030", "1500", "LIVE")
    ledger = ExecutionLedger(tmp_path); catalog = load_workload_catalog(); calls = []
    def cron_executor(workload, *a):
        calls.append(workload.workload_id)
        return {"status": "SUCCEEDED"}
    def event_executor(workload, *a):
        nested = dispatcher.dispatch_due(request, catalog, cron_executor, ledger=ledger)
        assert nested.status == "FAILED" and nested.failure_class == "UPSTREAM_NOT_READY"
        assert "fupan_close_materials" not in calls
        return {"status": "FAILED", "failure_class": "UPSTREAM_NOT_READY"}
    first = dispatcher.dispatch_due(request, catalog, event_executor, ledger=ledger, completion_workload_ids=("fupan_close_materials",))
    assert first.status == "FAILED"
    assert not (tmp_path / "workloads/live/20261030/1500/fupan_close_materials.workload-claim.json").exists()
    retry = dispatcher.dispatch_due(request, catalog, cron_executor, ledger=ledger)
    assert retry.status == "DUPLICATE_WORKLOAD_SKIPPED" and calls.count("fupan_close_materials") == 1


def test_concurrent_event_and_cron_receipts_keep_single_hash_chain(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    ledger = ExecutionLedger(tmp_path)
    def write(i): ledger.write_receipt(f"receipts/live/20261030/1500/{i}.dispatch-receipt.json", {"run_id": str(i), "business_date": "20261030", "slot": "1500", "mode": "LIVE", "status": "FAILED"})
    with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(write, (1, 2)))
    rows = [json.loads(p.read_bytes()) for p in (tmp_path / "receipts/live/20261030/1500").glob("*.dispatch-receipt.json")]
    assert sum(row["prev_ledger_sha256"] == "" for row in rows) == 1
    head = next(row for row in rows if row["prev_ledger_sha256"] == "")
    assert next(row for row in rows if row is not head)["prev_ledger_sha256"] == head["ledger_sha256"]
