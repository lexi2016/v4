from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

def test_scheduler_keeps_post_close_preselection_slots_recoverable() -> None:
    from ops.run_v35_macos_scheduler import POST_CLOSE_CATCHUP_SLOTS

    assert "1730" in POST_CLOSE_CATCHUP_SLOTS
    assert "1800" in POST_CLOSE_CATCHUP_SLOTS
    assert POST_CLOSE_CATCHUP_SLOTS.index("1730") < POST_CLOSE_CATCHUP_SLOTS.index("1800")


def test_retryable_failure_is_not_permanently_blocked_after_upstream_changes(
    tmp_path: Path,
) -> None:
    from ops.run_v35_macos_scheduler import _slot_blocks_retry

    receipt_root = tmp_path / "receipts"
    slot_root = receipt_root / "20260820" / "1730"
    slot_root.mkdir(parents=True)
    for index in range(3):
        (slot_root / f"{index}.dispatch-receipt.json").write_text(
            json.dumps(
                {
                    "status": "FAILED",
                    "failure_class": "UPSTREAM_NOT_READY",
                    "upstream_fingerprint": "old-pointer",
                    "release_id": "old-release",
                    "finished_at": "2026-08-20T09:00:00Z",
                }
            ),
            encoding="utf-8",
        )

    assert _slot_blocks_retry(
        receipt_root,
        "20260820",
        "1730",
        moment=datetime.fromisoformat("2026-08-20T17:40:00+08:00"),
        upstream_fingerprint="new-pointer",
        release_id="new-release",
    ) is False


def test_retryable_failure_can_retry_after_backoff_without_pointer_change(
    tmp_path: Path,
) -> None:
    from ops.run_v35_macos_scheduler import _slot_blocks_retry

    slot_root = tmp_path / "receipts" / "20260820" / "1730"
    slot_root.mkdir(parents=True)
    for index in range(4):
        (slot_root / f"{index}.dispatch-receipt.json").write_text(
            json.dumps(
                {
                    "status": "FAILED",
                    "failure_class": "UPSTREAM_NOT_READY",
                    "upstream_fingerprint": "same-pointer",
                    "release_id": "same-release",
                    "finished_at": f"2026-08-20T{17 + index // 60:02d}:{30 + index:02d}:00+08:00",
                }
            ),
            encoding="utf-8",
        )
    assert _slot_blocks_retry(
        tmp_path / "receipts",
        "20260820",
        "1730",
        moment=datetime.fromisoformat("2026-08-20T18:00:00+08:00"),
        upstream_fingerprint="same-pointer",
        release_id="same-release",
    ) is False


def _bind_current_release_identity_for_dispatch_test(monkeypatch, tmp_path: Path) -> dict[str, str]:
    """Pin the real isolated source bytes so this test reaches executor/ledger behavior."""
    import hashlib

    from infrastructure.scheduling import dispatcher as dispatcher_module

    app_root = Path(__file__).resolve().parents[1]
    entries = []
    for relative in dispatcher_module._RUNTIME_IDENTITY_FILES:
        content = (app_root / relative).read_bytes()
        entries.append({
            "path": relative,
            "kind": "file",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        })
    inventory = {
        "entries": entries,
        "entry_count": len(entries),
        "aggregate_sha256": hashlib.sha256(json.dumps(
            entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest(),
    }
    manifest_path = tmp_path / "release-manifest.json"
    raw = json.dumps({
        "schema_version": "v4.release_candidate.v1",
        "candidate": {"app_root": str(app_root), "release_id": "release-test"},
        "application_inventory": inventory,
    }, sort_keys=True).encode()
    manifest_path.write_bytes(raw)
    binding = {
        "V35_APP_ROOT": str(app_root),
        "V35_RELEASE_ID": "release-test",
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": hashlib.sha256(raw).hexdigest(),
    }
    for name, value in binding.items():
        monkeypatch.setenv(name, value)
    return binding


def _materialize_canonical_hk_d1_top100(root: Path, trade_date: str):
    """Write a canonical, store-backed HK D-1 pool using the frozen calendar."""
    import hashlib

    from contracts.trading_calendar import load_market_calendar, previous_session
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    signal_date = previous_session(
        load_market_calendar(), trade_date, market="hk_connect"
    )
    codes = tuple(f"HK.{index:05d}" for index in range(1, 101))
    safety_flags = {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    pool = {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "pool_id": "hkconnect_d1_top100",
        "display_name": "synthetic calendar-bound exact D-1",
        "market": "HK",
        "status": "STRICT_0_2_READY",
        "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "SHARED_VERIFIED_HK_0_2",
        "source_path": "synthetic/exact-d1.csv",
        "source_sha256": hashlib.sha256(
            f"synthetic exact D-1 {signal_date}->{trade_date}".encode()
        ).hexdigest(),
        "rows": [
            {
                "symbol": code,
                "code": code,
                "name": "fixture",
                "market": "HK",
                "pool_id": "hkconnect_d1_top100",
                "signal_date": signal_date,
                "trade_date": trade_date,
                "target_date": trade_date,
                "selected_strategy": "prob_active",
                "prob_active": 0.5,
                "data_cutoff": f"{signal_date} close",
                **safety_flags,
            }
            for code in codes
        ],
        "cannot_confirm": [],
        **safety_flags,
    }
    PreselectionPoolStore(root).materialize(pool)
    artifact = root / "preselection_pools" / trade_date / "hkconnect_d1_top100.json"
    return signal_date, codes, artifact


def test_dispatch_failure_receipt_carries_retry_identity(monkeypatch, tmp_path: Path) -> None:
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from infrastructure.scheduling.catalog import load_workload_catalog
    from infrastructure.scheduling.dispatcher import dispatch_due
    from infrastructure.scheduling.execution_ledger import ExecutionLedger

    monkeypatch.setenv("V35_RELEASE_ID", "release-test")
    monkeypatch.setenv("V35_UPSTREAM_FINGERPRINT", "pointer-test")
    release_binding = _bind_current_release_identity_for_dispatch_test(monkeypatch, tmp_path)
    request = DispatchRequest(
        scheduled_date="20260820",
        business_date="20260820",
        target_date="20260820",
        slot="1200",
        mode=DispatchMode.LIVE,
    )

    executor_calls: list[str] = []

    def executor(workload, *_args):
        executor_calls.append(workload.workload_id)
        return {
            "status": "FAILED",
            "failure_class": "UPSTREAM_NOT_READY",
            "stderr": "exact-date selector input is not ready",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    receipt = dispatch_due(
        request,
        load_workload_catalog(),
        executor,
        ledger=ExecutionLedger(tmp_path / "ledger"),
    )
    assert receipt.status == "FAILED"
    assert receipt.failure_class == "UPSTREAM_NOT_READY"
    assert receipt.release_id == release_binding["V35_RELEASE_ID"]
    assert executor_calls == list(receipt.selected_workload_ids)
    assert len(receipt.workload_results) == len(receipt.selected_workload_ids) > 0
    assert "exact-date selector input is not ready" in receipt.workload_results[0]["stderr"]
    stored_receipts = ExecutionLedger(tmp_path / "ledger").list_receipts("20260820")
    assert len(stored_receipts) == 1
    stored = stored_receipts[0]
    assert stored["failure_class"] == "UPSTREAM_NOT_READY"
    assert stored["release_id"] == "release-test"
    assert stored["release_manifest_sha256"] == release_binding["V35_RELEASE_MANIFEST_SHA256"]
    assert stored["upstream_fingerprint"] == "pointer-test"
    assert stored["attempt"] == 1
    assert stored["retry_after"]


def test_stage_center_a_missing_does_not_abort_hk_lane() -> None:
    from stage_center.acquisition import StageUniverseBinding
    from stage_center.runner import lane_status_bundle

    a = StageUniverseBinding.unavailable(
        market="A_SHARE", trade_date="20260820", reason="candidate current.json missing"
    )
    hk = StageUniverseBinding.ready(
        market="HK_CONNECT",
        trade_date="20260820",
        role="HK_FULL_UNIVERSE",
        codes=("HK.00003", "HK.09993"),
        source_run_id="hk-run",
        sha256="a" * 64,
    )
    result = lane_status_bundle(a, hk)
    assert result["A_SHARE"]["status"] == "CANNOT_CONFIRM"
    assert result["HK_CONNECT"]["status"] == "READY"
    assert result["overall_status"] == "PARTIAL_WITH_ROWS"


def test_historical_backfill_uses_immutable_namespace_without_live_overwrite(tmp_path: Path) -> None:
    """A historical failure receipt must not replace the live slot evidence."""
    from datetime import datetime
    from stage_center.runner import RunnerConfig, StageCenterRunner
    from zoneinfo import ZoneInfo

    live_receipt = tmp_path / "receipts" / "20260820" / "STAGE_0930_0935" / "receipt.json"
    live_receipt.parent.mkdir(parents=True)
    live_receipt.write_text('{"status":"LIVE_SENTINEL"}\n', encoding="utf-8")
    live_raw_latest = tmp_path / "raw" / "latest.json"
    live_raw_latest.parent.mkdir(parents=True)
    live_raw_latest.write_text('{"status":"LIVE_RAW_SENTINEL"}\n', encoding="utf-8")
    live_selection_latest = tmp_path / "selection" / "selection_latest.json"
    live_selection_latest.parent.mkdir(parents=True)
    live_selection_latest.write_text('{"status":"LIVE_SELECTION_SENTINEL"}\n', encoding="utf-8")

    config = RunnerConfig(
        candidate_acquisition_root=tmp_path / "missing-candidate",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
    )
    result = StageCenterRunner(config).tick(
        "20260820",
        datetime(2026, 8, 20, 9, 35, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
        stage_id="STAGE_0930_0935",
        historical_backfill=True,
    )

    assert result["status"] == "CANNOT_CONFIRM"
    assert json.loads(live_receipt.read_text(encoding="utf-8"))["status"] == "LIVE_SENTINEL"
    assert json.loads(live_raw_latest.read_text(encoding="utf-8"))["status"] == "LIVE_RAW_SENTINEL"
    assert json.loads(live_selection_latest.read_text(encoding="utf-8"))["status"] == "LIVE_SELECTION_SENTINEL"
    backfill_receipts = list((tmp_path / "receipts" / "backfill").glob("*/20260820/STAGE_0930_0935/receipt.json"))
    assert len(backfill_receipts) == 1
    backfill = json.loads(backfill_receipts[0].read_text(encoding="utf-8"))
    assert backfill["mode"] == "BACKFILL"
    assert backfill["backfill_run_id"] == backfill_receipts[0].parents[2].name
    assert backfill["latest_updated"] is False
    assert backfill["current_updated"] is False


def _preselection_registry_fixture(tmp_path: Path, runner):
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry

    shared_package_root = tmp_path / "shared-package"
    scripts_root = shared_package_root / "scripts"
    scripts_root.mkdir(parents=True)
    for name in (
        "capture_public_fupan.py",
        "materialize_v192_selector.py",
        "update_hk_0_2_panel.py",
        "acquire_hk_security_master.py",
        "materialize_hk_0_2.py",
    ):
        (scripts_root / name).write_text("# fixture entry\n", encoding="utf-8")
    ops_root = tmp_path / "ops"
    ops_root.mkdir()
    (ops_root / "ensure_hk_security_master.py").write_text(
        "# fixture entry\n", encoding="utf-8"
    )
    return FixedExecutorRegistry(
        data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared-data",
        hk_universe_root=tmp_path / "hk-universe",
        shared_package_root=shared_package_root,
        selector_data_root=tmp_path / "selector",
        preselection_input_root=tmp_path / "preselection-input",
        stage_selection_root=tmp_path / "stage-selection",
        repo_root=tmp_path,
        runner=runner,
    )


def _preselection_request():
    from contracts.runtime_tasks import DispatchMode, DispatchRequest

    return DispatchRequest(
        scheduled_date="20260819",
        business_date="20260819",
        target_date="20260820",
        slot="1800",
        mode=DispatchMode.LIVE,
    )


def test_preselection_hk_lane_survives_missing_a_selector(tmp_path: Path) -> None:
    """A missing selector skips only its A producer, preserving other lanes."""
    calls: list[tuple[str, list[str]]] = []

    def fake_runner(command, *, cwd, timeout_seconds, env):
        module = str(command[2])
        calls.append((module, list(command[3:])))
        if (
            module == "ops.materialize_shared_v192_preselection"
            and "V3_SHARED_SELECTOR_READY_PANEL" not in (env or {})
        ):
            raise KeyError("V3_SHARED_SELECTOR_READY_PANEL")
        return __import__("subprocess").CompletedProcess(command, 0, "", "")

    registry = _preselection_registry_fixture(tmp_path, fake_runner)
    registry.selector_data_root = tmp_path / "missing-selector"
    request = _preselection_request()

    result = registry._preselection_pools(request)

    assert result["status"] == "SUCCEEDED"
    modules = [module for module, _arguments in calls]
    assert "scripts.capture_public_fupan" in modules
    assert "ops.materialize_shared_v192_preselection" not in modules
    assert "scripts.update_hk_0_2_panel" in modules
    assert "ops.ensure_hk_security_master" in modules
    assert "scripts.materialize_hk_0_2" in modules
    final_arguments = next(
        arguments for module, arguments in calls if module == "ops.materialize_scheduled_preselection"
    )
    assert "--selector" not in final_arguments
    assert result["a_selector_status"] == "CANNOT_CONFIRM"
    assert result["hk_lane_status"] == "SUCCEEDED"
    a_gap = result["a_lane_degradations"][0]
    assert a_gap["status"] == "CANNOT_CONFIRM"
    assert a_gap["signal_date"] == request.business_date
    assert a_gap["target_date"] == request.target_date
    assert a_gap["first_gate"] == "SOURCE_PANEL"
    assert a_gap["producer_called"] is False


def test_preselection_a_lane_survives_hk_update_failure(tmp_path: Path, monkeypatch) -> None:
    """An HK acquisition failure must not turn an otherwise completed A run into a fake global failure."""
    import subprocess
    from infrastructure.scheduling import executor_registry as registry_module

    selector = tmp_path / "selector.parquet"
    selector.write_bytes(b"fixture")
    monkeypatch.setattr(registry_module, "resolve_selector_panel", lambda *_args: selector)
    calls: list[str] = []

    def fake_runner(command, *, cwd, timeout_seconds, env):
        module = str(command[2])
        calls.append(module)
        if module == "scripts.update_hk_0_2_panel":
            return subprocess.CompletedProcess(command, 1, "", "HK exact update unavailable")
        return subprocess.CompletedProcess(command, 0, "", "")

    registry = _preselection_registry_fixture(tmp_path, fake_runner)
    result = registry._preselection_pools(_preselection_request())

    assert result["status"] == "SUCCEEDED"
    assert "scripts.capture_public_fupan" in calls
    assert "ops.materialize_scheduled_preselection" in calls
    assert result["a_selector_status"] == "READY"
    assert result["hk_lane_status"] == "CANNOT_CONFIRM"
    assert result["hk_lane_degradations"][0]["lane"] == "HK_CONNECT"


def test_preselection_missing_hk_runtime_is_lane_local(tmp_path: Path, monkeypatch) -> None:
    """A missing HK interpreter must not abort the independent A lane."""
    import subprocess
    from infrastructure.scheduling import executor_registry as registry_module

    selector = tmp_path / "selector.parquet"
    selector.write_bytes(b"fixture")
    monkeypatch.setattr(registry_module, "resolve_selector_panel", lambda *_args: selector)

    # Keep the default runner identity so this exercises the production guard;
    # replace only the subprocess seam so no external process is started.
    registry = _preselection_registry_fixture(tmp_path, None)
    registry.hk_0_2_python_executable = tmp_path / "missing-hk-python"

    def fake_run(module, _arguments, **_kwargs):
        return {
            "status": "SUCCEEDED",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    registry._run = fake_run
    result = registry._preselection_pools(_preselection_request())

    assert result["status"] == "SUCCEEDED"
    assert result["a_selector_status"] == "READY"
    assert result["hk_lane_status"] == "CANNOT_CONFIRM"
    assert any(
        "HK 0.2 Python runtime missing" in str(item.get("stderr"))
        for item in result["hk_lane_degradations"]
    )


def test_preselection_v192_uses_contract_timeout_only_for_a_lane(
    tmp_path: Path, monkeypatch
) -> None:
    """The A V1.9.2 producer gets its 1800s contract timeout, not a global bump."""
    import subprocess
    from infrastructure.scheduling import executor_registry as registry_module

    selector = tmp_path / "selector.parquet"
    selector.write_bytes(b"fixture")
    monkeypatch.setattr(registry_module, "resolve_selector_panel", lambda *_args: selector)
    calls: list[tuple[str, int]] = []

    def fake_runner(command, *, cwd, timeout_seconds, env):
        del cwd, env
        calls.append((str(command[2]), timeout_seconds))
        return subprocess.CompletedProcess(command, 0, "", "")

    registry = _preselection_registry_fixture(tmp_path, fake_runner)
    registry.timeout_seconds = 600
    result = registry._preselection_pools(_preselection_request())

    assert result["status"] == "SUCCEEDED"
    timeout_by_module = dict(calls)
    assert timeout_by_module["ops.materialize_shared_v192_preselection"] == 1800
    assert timeout_by_module["scripts.capture_public_fupan"] == 600
    assert timeout_by_module["ops.materialize_scheduled_preselection"] == 600


def _fake_hk_pool(trade_date: str, signal_date: str):
    from types import SimpleNamespace

    rows = [
        {
            "code_norm": f"{index:05d}",
            "rank": index,
            "score_prob_active": float(101 - index),
            "signal_date": signal_date,
            "target_date": trade_date,
            "d1_freshness_status": "PASS",
            "selected_strategy": "prob_active",
            "name": f"港股{index:03d}",
        }
        for index in range(1, 101)
    ]
    verification = {
        "run_id": "hk-run",
        "artifact_relative": f"runs/{trade_date}/HK_0_2/{'hk-run'}/artifact.json",
        "artifact_sha256": "a" * 64,
        "row_count": 100,
    }
    receipt = {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    return SimpleNamespace(
        rows=rows,
        run=SimpleNamespace(verification=verification, receipt=receipt),
    )


def _fake_a_pool(trade_date: str, signal_date: str):
    from types import SimpleNamespace
    from domains.preselection_materializer import (
        SHARED_V192_FORMULA_SOURCE,
        SHARED_V192_RANK_BOUNDARY,
        SHARED_V192_ENTRY_FIELDS,
    )

    row = {
        "ts_code": "000001.SZ",
        "review_rank_v19": 1,
        "signal_date": signal_date,
        "target_date": trade_date,
        "rank_usage_boundary": SHARED_V192_RANK_BOUNDARY,
        "formal_recommendation_allowed": "false",
        "formula_source": SHARED_V192_FORMULA_SOURCE,
        "premarket_pool_score": 1.0,
        "stock_name": "平安银行",
    }
    for field in SHARED_V192_ENTRY_FIELDS:
        row.setdefault(field, "none" if field in {"gold_brick_context", "brick_resonance_context"} else 0)
    verification = {
        "run_id": "a-run",
        "artifact_relative": f"runs/{trade_date}/A_SHARE_V192_PREMARKET_POOL_V3/a-run/artifact.csv",
        "artifact_sha256": "b" * 64,
        "row_count": 1,
    }
    receipt = {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    return SimpleNamespace(
        rows=[row],
        run=SimpleNamespace(verification=verification, receipt=receipt),
    )


def test_materializer_keeps_hk_pool_when_a_shared_reader_is_missing(tmp_path: Path, monkeypatch) -> None:
    import ops.materialize_scheduled_preselection as materializer

    monkeypatch.setattr(
        materializer,
        "build_hourly_research_pool",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("research")),
    )

    trade_date, signal_date = "20260820", "20260819"

    def missing_a(*_args, **_kwargs):
        raise FileNotFoundError("A exact v1.9.2 input missing")

    artifacts = materializer.build_scheduled_artifacts(
        trade_date=trade_date,
        signal_date=signal_date,
        selector=None,
        input_root=tmp_path / "input",
        shared_data_root=tmp_path / "shared",
        shared_package_root=tmp_path / "package",
        data_root=tmp_path / "data",
        pool_reader=missing_a,
        hk_pool_reader=lambda *_args, **_kwargs: _fake_hk_pool(trade_date, signal_date),
    )

    assert len(artifacts) == 7
    by_id = {artifact["pool_id"]: artifact for artifact in artifacts}
    assert by_id["a_d1_premarket_pool"]["status"] == "CANNOT_CONFIRM"
    assert by_id["hkconnect_d1_top100"]["status"] == "STRICT_0_2_READY"
    assert len(by_id["hkconnect_d1_top100"]["rows"]) == 100


def test_materializer_keeps_a_pool_when_hk_shared_reader_is_missing(tmp_path: Path, monkeypatch) -> None:
    import ops.materialize_scheduled_preselection as materializer

    monkeypatch.setattr(
        materializer,
        "build_hourly_research_pool",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("research")),
    )

    trade_date, signal_date = "20260820", "20260819"

    def missing_hk(*_args, **_kwargs):
        raise FileNotFoundError("HK exact 0.2 input missing")

    artifacts = materializer.build_scheduled_artifacts(
        trade_date=trade_date,
        signal_date=signal_date,
        selector=None,
        input_root=tmp_path / "input",
        shared_data_root=tmp_path / "shared",
        shared_package_root=tmp_path / "package",
        data_root=tmp_path / "data",
        pool_reader=lambda *_args, **_kwargs: _fake_a_pool(trade_date, signal_date),
        hk_pool_reader=missing_hk,
    )

    assert len(artifacts) == 7
    by_id = {artifact["pool_id"]: artifact for artifact in artifacts}
    assert by_id["a_d1_premarket_pool"]["status"] == "V192_CANDIDATE_READY"
    assert len(by_id["a_d1_premarket_pool"]["rows"]) == 1
    assert by_id["hkconnect_d1_top100"]["status"] == "CANNOT_CONFIRM"


def test_materializer_keeps_hk_pool_when_a_reader_contract_is_invalid(tmp_path: Path, monkeypatch) -> None:
    """A verified-input contract failure is lane-local, not a sibling abort."""
    import ops.materialize_scheduled_preselection as materializer

    monkeypatch.setattr(
        materializer,
        "build_hourly_research_pool",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("research")),
    )

    trade_date, signal_date = "20260820", "20260819"

    def invalid_a(*_args, **_kwargs):
        raise ValueError("A exact-date SHA mismatch")

    artifacts = materializer.build_scheduled_artifacts(
        trade_date=trade_date,
        signal_date=signal_date,
        selector=None,
        input_root=tmp_path / "input",
        shared_data_root=tmp_path / "shared",
        shared_package_root=tmp_path / "package",
        data_root=tmp_path / "data",
        pool_reader=invalid_a,
        hk_pool_reader=lambda *_args, **_kwargs: _fake_hk_pool(trade_date, signal_date),
    )

    by_id = {artifact["pool_id"]: artifact for artifact in artifacts}
    assert by_id["a_d1_premarket_pool"]["status"] == "CANNOT_CONFIRM"
    assert "A_V192_EXACT_INPUT_CONTRACT_INVALID:A exact-date SHA mismatch" in by_id[
        "a_d1_premarket_pool"
    ]["cannot_confirm"]
    assert by_id["hkconnect_d1_top100"]["status"] == "STRICT_0_2_READY"
    assert len(by_id["hkconnect_d1_top100"]["rows"]) == 100


def test_materializer_keeps_hk_pool_when_a_shared_store_has_no_latest_run(
    tmp_path: Path, monkeypatch
) -> None:
    """An isolated shared StoreError is an A-lane missing-input result."""
    import ops.materialize_scheduled_preselection as materializer

    monkeypatch.setattr(
        materializer,
        "build_hourly_research_pool",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("research")),
    )

    trade_date, signal_date = "20260821", "20260820"
    store_error = type(
        "StoreError",
        (Exception,),
        {"__module__": "_v35_shared_data_test.store"},
    )

    def missing_a(*_args, **_kwargs):
        raise store_error("no latest run for 20260821 / A_SHARE_V192_PREMARKET_POOL_V3")

    artifacts = materializer.build_scheduled_artifacts(
        trade_date=trade_date,
        signal_date=signal_date,
        selector=None,
        input_root=tmp_path / "input",
        shared_data_root=tmp_path / "shared",
        shared_package_root=tmp_path / "package",
        data_root=tmp_path / "data",
        pool_reader=missing_a,
        hk_pool_reader=lambda *_args, **_kwargs: _fake_hk_pool(trade_date, signal_date),
    )

    by_id = {artifact["pool_id"]: artifact for artifact in artifacts}
    assert by_id["a_d1_premarket_pool"]["status"] == "CANNOT_CONFIRM"
    assert by_id["a_d1_premarket_pool"]["cannot_confirm"] == [
        "A_V192_EXACT_INPUT_MISSING:no latest run for 20260821 / A_SHARE_V192_PREMARKET_POOL_V3"
    ]
    assert by_id["hkconnect_d1_top100"]["status"] == "STRICT_0_2_READY"
    assert len(by_id["hkconnect_d1_top100"]["rows"]) == 100


def test_materializer_keeps_a_pool_when_hk_reader_contract_is_invalid(tmp_path: Path, monkeypatch) -> None:
    """An HK contract failure cannot erase a valid A exact-date pool."""
    import ops.materialize_scheduled_preselection as materializer

    monkeypatch.setattr(
        materializer,
        "build_hourly_research_pool",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("research")),
    )

    trade_date, signal_date = "20260820", "20260819"

    def invalid_hk(*_args, **_kwargs):
        raise ValueError("HK source SHA mismatch")

    artifacts = materializer.build_scheduled_artifacts(
        trade_date=trade_date,
        signal_date=signal_date,
        selector=None,
        input_root=tmp_path / "input",
        shared_data_root=tmp_path / "shared",
        shared_package_root=tmp_path / "package",
        data_root=tmp_path / "data",
        pool_reader=lambda *_args, **_kwargs: _fake_a_pool(trade_date, signal_date),
        hk_pool_reader=invalid_hk,
    )

    by_id = {artifact["pool_id"]: artifact for artifact in artifacts}
    assert by_id["a_d1_premarket_pool"]["status"] == "V192_CANDIDATE_READY"
    assert len(by_id["a_d1_premarket_pool"]["rows"]) == 1
    assert by_id["hkconnect_d1_top100"]["status"] == "CANNOT_CONFIRM"
    assert "HK_0_2_EXACT_INPUT_CONTRACT_INVALID:HK source SHA mismatch" in by_id[
        "hkconnect_d1_top100"
    ]["cannot_confirm"]


def test_stage_center_runner_publishes_hk_when_a_current_is_missing(tmp_path: Path) -> None:
    """Exercise the real tick seam, including raw/selection stores and receipt."""
    import sys
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from stage_center.acquisition import SourceResult
    from stage_center.runner import RunnerConfig, StageCenterRunner
    from stage_center.scheduler import evaluate_due

    trade_date = "20260915"
    stage_id = "STAGE_0930_0935"
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    d1_root = tmp_path / "hk-d1"
    signal_date, expected_hk_codes, d1_file = _materialize_canonical_hk_d1_top100(
        d1_root, trade_date
    )
    from contracts.trading_calendar import load_market_calendar, previous_session

    expected_signal_date = previous_session(
        load_market_calendar(), trade_date, market="hk_connect"
    )
    d1_payload = json.loads(d1_file.read_text(encoding="utf-8"))
    expected_d1_path = d1_root / "preselection_pools" / trade_date / d1_file.name
    assert (
        d1_payload.get("schema_version") == "v3_5.preselection_pool.v1"
        and d1_file == expected_d1_path
        and {row.get("signal_date") for row in d1_payload.get("rows", [])}
        == {expected_signal_date}
        and signal_date == expected_signal_date
    ), {
        "schema_version": d1_payload.get("schema_version"),
        "actual_path": str(d1_file),
        "expected_path": str(expected_d1_path),
        "expected_signal_date": expected_signal_date,
        "actual_signal_dates": sorted(
            {str(row.get("signal_date")) for row in d1_payload.get("rows", [])}
        ),
    }

    def raw_row(code: str, name: str) -> dict[str, object]:
        return {
            "batch_index": 0,
            "code": code,
            "name": name,
            "update_time": "2026-09-15 09:35:05",
            "last_price": 10.5,
            "open_price": 10.0,
            "high_price": 10.7,
            "low_price": 9.9,
            "prev_close_price": 10.0,
            "turnover": 1000000.0,
            "volume": 100000.0,
            "bid_price": 10.49,
            "ask_price": 10.51,
            "bid_vol": 1000.0,
            "ask_vol": 900.0,
            "window_start": "2026-09-15 09:30:00",
            "window_end": "2026-09-15 09:35:05",
            "bar_count": 1,
            "temporal_cutoff_safe": True,
            "pct_chg": 5.0,
            "candidate_lanes": ["LIVE_HKCONNECT_GAINER"],
        }

    hk_rows = (raw_row("HK.00001", "样本港股"), raw_row("HK.00002", "第二港股"))
    hk_collector_codes: list[tuple[str, ...]] = []

    def hk_collector(plan, market: str) -> SourceResult:
        assert market == "HK_CONNECT"
        codes = tuple(plan.codes_for(market))
        hk_collector_codes.append(codes)
        assert codes == expected_hk_codes
        return SourceResult(
            source_id="fixture_hk",
            status="READY",
            rows=hk_rows,
            requested_rows=len(codes),
            source_evidence=(
                "fixture=canonical_hk_d1_top100",
                f"signal_date={signal_date}",
            ),
        )

    def a_collector(_plan, market: str) -> SourceResult:
        raise AssertionError(f"A collector must not run when its current is missing: {market}")

    config = RunnerConfig(
        candidate_acquisition_root=candidate_root,
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        hk_d1_root=d1_root,
        v4_research_data_root=tmp_path / "research",
        v4_morning_news_root=tmp_path / "morning-news",
        shared_data_root=tmp_path / "shared",
        python_path=Path(sys.executable),
    )
    runner = StageCenterRunner(
        config,
        collectors={"A_SHARE": a_collector, "HK_CONNECT": hk_collector},
    )
    decision = evaluate_due(
        stage_id,
        trade_date,
        datetime(2026, 9, 15, 9, 35, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
        historical_backfill=True,
    )
    result = runner.tick(
        trade_date,
        datetime(2026, 9, 15, 9, 35, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
        stage_id=stage_id,
        historical_backfill=True,
    )

    assert decision.status == "HISTORICAL_BACKFILL"
    assert result["status"] == "PARTIAL_WITH_ROWS"
    assert result["markets"]["A_SHARE"]["selection_status"] == "CANNOT_CONFIRM"
    assert result["markets"]["HK_CONNECT"]["selected_rows"] == 2
    assert result["markets"]["HK_CONNECT"]["selection_status"] == "PARTIAL_WITH_ROWS"
    assert hk_collector_codes == [expected_hk_codes]
    assert not (config.raw_root / "latest.json").exists()
    assert not (config.selection_root / "selection_latest.json").exists()
    backfill_receipts = list(
        (config.receipt_root / "backfill").glob(
            f"*/{trade_date}/{stage_id}/receipt.json"
        )
    )
    assert len(backfill_receipts) == 1
    backfill_root = backfill_receipts[0].parents[2].name
    assert json.loads(backfill_receipts[0].read_text())["status"] == "PARTIAL_WITH_ROWS"
    assert json.loads(backfill_receipts[0].read_text())["backfill_run_id"] == backfill_root
    assert (config.raw_root / "backfill" / backfill_root / "latest.json").is_file()
    assert (config.selection_root / "backfill" / backfill_root / "selection_latest.json").is_file()


def test_stage_center_rejects_canonical_hk_d1_pool_under_wrong_source_date_path(
    tmp_path: Path,
) -> None:
    from stage_center.runner import RunnerError, _validate_hk_d1

    trade_date = "20260915"
    d1_root = tmp_path / "hk-d1"
    signal_date, expected_codes, canonical_path = _materialize_canonical_hk_d1_top100(
        d1_root, trade_date
    )
    assert signal_date == "20260914"
    assert len(expected_codes) == 100
    misplaced_path = (
        d1_root / "preselection_pools" / signal_date / canonical_path.name
    )
    misplaced_path.parent.mkdir(parents=True)
    misplaced_path.write_bytes(canonical_path.read_bytes())

    with pytest.raises(RunnerError, match="HK D1 canonical snapshot path invalid"):
        _validate_hk_d1(misplaced_path, trade_date)


def test_stage_center_rejects_canonical_hk_d1_pool_with_wrong_signal_date(
    tmp_path: Path,
) -> None:
    from infrastructure.data_store import _canonical_bytes, _sha256
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    from stage_center.runner import RunnerError, _validate_hk_d1

    trade_date = "20260915"
    d1_root = tmp_path / "hk-d1"
    signal_date, expected_codes, d1_path = _materialize_canonical_hk_d1_top100(
        d1_root, trade_date
    )
    assert signal_date == "20260914"
    assert len(expected_codes) == 100

    # Keep the store receipt and manifest valid so validation reaches the
    # calendar-bound row contract rather than failing on artifact integrity.
    store = PreselectionPoolStore(d1_root)
    payload = store.read_pool(trade_date, "hkconnect_d1_top100")
    payload["rows"][0]["signal_date"] = "20260911"
    artifact_relative, receipt_relative = store._relative(
        trade_date, "hkconnect_d1_top100"
    )
    artifact_sha = _sha256(payload)
    receipt = store._receipt(
        trade_date=trade_date,
        pool_id="hkconnect_d1_top100",
        artifact_path=artifact_relative,
        artifact_sha256=artifact_sha,
        payload=payload,
    )
    (d1_root / artifact_relative).write_bytes(_canonical_bytes(payload))
    (d1_root / receipt_relative).write_bytes(_canonical_bytes(receipt))
    manifest_path = d1_root / "preselection_pools" / trade_date / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["hkconnect_d1_top100"] = artifact_sha
    manifest_path.write_bytes(_canonical_bytes(manifest))

    with pytest.raises(RunnerError, match="HK D1 row market/signal_date mismatch"):
        _validate_hk_d1(d1_path, trade_date)


@pytest.mark.parametrize(
    ("hk_snapshot_evidence", "refresh_mode"),
    (
        ((), "not_called"),
        (
            (
                "active_snapshot_sha256=" + "a" * 64,
                "active_snapshot_codes_sha256=" + "b" * 64,
                "active_snapshot_temporal_cutoff_safe=false",
            ),
            "not_called",
        ),
        (
            (
                "active_snapshot_sha256=" + "a" * 64,
                "active_snapshot_codes_sha256=" + "b" * 64,
                "active_snapshot_temporal_cutoff_safe=false",
                "active_snapshot_degraded_to_pytdx_observation=true",
            ),
            "observation",
        ),
        (
            (
                "active_snapshot_sha256=" + "a" * 64,
                "active_snapshot_codes_sha256=" + "b" * 64,
                "active_snapshot_temporal_cutoff_safe=true",
            ),
            "mismatch",
        ),
        (
            (
                "active_snapshot_sha256=" + "a" * 64,
                "active_snapshot_codes_sha256=" + "b" * 64,
                "active_snapshot_temporal_cutoff_safe=true",
            ),
            "matching",
        ),
    ),
)
def test_stage_center_runner_isolates_hk_active_recovery_from_a(
    tmp_path: Path,
    monkeypatch,
    hk_snapshot_evidence: tuple[str, ...],
    refresh_mode: str,
) -> None:
    """HK recovery gaps stay lane-local while the verified A publisher runs."""
    import hashlib
    import sys
    from dataclasses import replace

    from stage_center import live_collectors, research_context, runner as runner_module
    from stage_center.candidate_input import CandidateInput
    from stage_center.raw_store import RawStore
    from stage_center.runner import RunnerConfig, StageCenterRunner
    from stage_center.scheduler import DueDecision
    from stage_center.selection import SelectionStore

    trade_date = "20260915"
    stage_id = "STAGE_0930_0935"
    candidate_sha = "c" * 64

    d1_root = tmp_path / "hk-d1"
    signal_date, d1_codes, d1_path = _materialize_canonical_hk_d1_top100(
        d1_root, trade_date
    )
    hk_d1_sha = hashlib.sha256(d1_path.read_bytes()).hexdigest()
    assert signal_date == "20260914"
    assert d1_path == d1_root / "preselection_pools" / trade_date / "hkconnect_d1_top100.json"
    assert all(
        row["signal_date"] == signal_date
        for row in json.loads(d1_path.read_text(encoding="utf-8"))["rows"]
    )

    def raw_row(code: str) -> dict[str, object]:
        return {
            "batch_index": 0,
            "code": code,
            "name": "Fixture",
            "update_time": "2026-09-15 09:35:05",
            "last_price": 10.5,
            "open_price": 10.0,
            "high_price": 10.7,
            "low_price": 9.9,
            "prev_close_price": 10.0,
            "turnover": 1000000.0,
            "volume": 100000.0,
            "bid_price": 10.49,
            "ask_price": 10.51,
            "bid_vol": 1000.0,
            "ask_vol": 900.0,
            "window_start": "2026-09-15 09:30:00",
            "window_end": "2026-09-15 09:35:05",
            "bar_count": 1,
            "temporal_cutoff_safe": True,
        }

    raw_root = tmp_path / "raw"
    raw_store = RawStore(raw_root)
    raw_store.publish(
        trade_date=trade_date,
        stage_id=stage_id,
        market="A_SHARE",
        source_id="fixture_a",
        source_status="READY",
        rows=[raw_row("A.000001")],
        requested_rows=1,
        source_evidence=(f"candidate_current_sha256={candidate_sha}",),
        window="09:30-09:35",
        cutoff_at="09:35:05",
    )
    raw_store.publish(
        trade_date=trade_date,
        stage_id=stage_id,
        market="HK_CONNECT",
        source_id="fixture_hk",
        source_status="PARTIAL_WITH_ROWS" if refresh_mode == "observation" else "READY",
        rows=[raw_row("HK.00001")],
        requested_rows=1,
        source_evidence=(
            f"hk_d1_json_sha256={hk_d1_sha}",
            f"hk_d1_sha256={hk_d1_sha}",
            "active_snapshot_status=FUTU_HKCONNECT_FULL_SCAN",
            f"active_snapshot_trade_date={trade_date}",
            "active_snapshot_cutoff=09:35:05",
            *hk_snapshot_evidence,
        ),
        window="09:30-09:35",
        cutoff_at="09:35:05",
    )

    candidate = CandidateInput(
        root=tmp_path / "candidate",
        trade_date=trade_date,
        current_relative="current.json",
        current_sha256=candidate_sha,
        run_id="fixture-candidate",
        codes=("A.000001",),
        artifact_sha256="d" * 64,
        manifest_sha256="e" * 64,
        receipt_sha256="f" * 64,
        source_projection_sha256="g" * 64,
        source_evidence=("fixture=candidate",),
    )
    monkeypatch.setattr(runner_module, "read_candidate_input", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(
        research_context,
        "load_research_context",
        lambda *_args, **_kwargs: research_context.ResearchContext(
            trade_date=trade_date,
            stage_cutoff="09:35:05",
            selected_slot="0930",
            by_code={
                "A.000001": research_context.ResearchScore(
                    news_quality_score=1.0,
                    research_quality_score=1.0,
                    research_delta_hits=0,
                )
            },
            source_evidence=("fixture=research",),
        ),
    )
    calls: list[str] = []
    recovery_codes: list[tuple[str, ...]] = []

    def refresh(source, **kwargs):
        calls.append("refresh")
        recovery_codes.append(tuple(kwargs["codes"]))
        if refresh_mode == "not_called":
            raise AssertionError("unsafe or incomplete HK evidence must not refresh")
        if refresh_mode == "matching":
            return replace(
                source,
                rows=tuple(
                    {
                        **row,
                        "candidate_lanes": ["LIVE_HKCONNECT_GAINER"],
                    }
                    for row in source.rows
                ),
            )
        return replace(
            source,
            source_evidence=tuple(
                item.replace("=" + "a" * 64, "=" + "d" * 64)
                if str(item).startswith("active_snapshot_sha256=")
                else item
                for item in source.source_evidence
            ),
        )

    monkeypatch.setattr(live_collectors, "refresh_hk_active_lanes", refresh)
    config = RunnerConfig(
        candidate_acquisition_root=candidate.root,
        raw_root=raw_root,
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        v4_research_data_root=tmp_path / "research",
        v4_morning_news_root=tmp_path / "morning-news",
        hk_d1_root=d1_root,
        shared_data_root=tmp_path / "shared",
        python_path=Path(sys.executable),
    )
    runner = StageCenterRunner(
        config,
        collectors={"A_SHARE": lambda *_args: None, "HK_CONNECT": lambda *_args: None},
    )
    decision = DueDecision(
        stage_id=stage_id,
        trade_date=trade_date,
        status="DUE",
        scheduled_at=None,
        idempotency_key="fixture",
        calendar={},
    )

    result = runner._run_one(decision)

    assert result["status"] == "PARTIAL_WITH_ROWS"
    assert result["markets"]["A_SHARE"]["selected_rows"] == 1
    assert result["markets"]["A_SHARE"]["selection_status"] == "PARTIAL_WITH_ROWS"
    if refresh_mode == "observation":
        assert result["markets"]["HK_CONNECT"]["selection_status"] == "PARTIAL_WITH_ROWS"
        assert result["markets"]["HK_CONNECT"]["selected_rows"] == 1
        assert any(
            item == "hk_selection_mode=TDXPY_EXHQ_D1_TOP100_OBSERVATION"
            for item in result["markets"]["HK_CONNECT"]["source_evidence"]
        )
    elif refresh_mode == "matching":
        assert result["markets"]["HK_CONNECT"]["selection_status"] == "READY"
        assert result["markets"]["HK_CONNECT"]["selected_rows"] == 1
    else:
        assert result["markets"]["HK_CONNECT"]["selection_status"] == "CANNOT_CONFIRM"
        assert any(
            "HK_ACTIVE_SNAPSHOT" in str(item)
            or "HK_ACTIVE_SELECTION_RECOVERY_FAILED" in str(item)
            for item in result["markets"]["HK_CONNECT"]["cannot_confirm"]
        )
    assert (calls == []) is (refresh_mode in {"not_called", "observation"})
    assert len(calls) == (0 if refresh_mode in {"not_called", "observation"} else 1)
    assert recovery_codes == ([d1_codes] if calls else [])
    assert SelectionStore(config.selection_root).read_verified(
        trade_date, stage_id, "A_SHARE"
    )["selected_rows"] == 1


def test_hourly_recovery_is_immutable_and_links_superseded_input(tmp_path: Path) -> None:
    from ops.collect_hourly_research_input import _atomic_json

    destination = tmp_path / "1200.json"
    original = {"stock_research_timeline": [{"code": "000001"}]}
    recovery = {
        "stock_research_timeline": [{"code": "000001"}, {"code": "000002"}],
        "cannot_confirm": [{"reason": "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"}],
        "retry_of_sha256": "b" * 64,
        "trade_date": "20260820",
        "source_manifest": {
            "hourly_slot": "1200",
            "source_receipts": ["receipts/zsxq-1200.json"],
        },
    }
    _atomic_json(destination, original)
    recovery_path = _atomic_json(destination, recovery)
    assert recovery_path != destination
    assert recovery_path.name.startswith("1200.recovery-")
    payload = json.loads(recovery_path.read_text(encoding="utf-8"))
    assert payload["retry_of_sha256"] == "b" * 64
    assert payload["supersedes"] == __import__("hashlib").sha256(
        json.dumps(original, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert payload["recovery_metadata"]["supersedes"] == payload["supersedes"]
    assert payload["recovery_metadata"]["pit_cutoff"] == "2026-08-20T12:00:59+08:00"
    assert payload["recovery_metadata"]["source_receipts"] == ["receipts/zsxq-1200.json"]
    assert json.loads(destination.read_text(encoding="utf-8")) == original
