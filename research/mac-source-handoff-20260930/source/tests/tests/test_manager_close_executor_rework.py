"""Focused compatibility checks for the monolithic scheduler source tree."""

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest


APP_ROOT = Path(os.environ.get("V4_TEST_APP_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(APP_ROOT))

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling import manager_close_executor as manager_close
from infrastructure.scheduling.executor_registry import WorkloadExecutionError

assert Path(manager_close.__file__).resolve().is_relative_to(APP_ROOT)

HK = ZoneInfo("Asia/Hong_Kong")
DATE = "20260924"


def test_late_close_recapture_uses_pytdx_and_stays_out_of_1530(tmp_path):
    from infrastructure.manager_input_attestation import digest, encoded
    from ops import materialize_manager_close_discovery as materializer
    from apps.api.v35_api.manager_workbench_router import ManagerWorkbenchResearchReader
    from v4.manager_research.workspace_plan import plan_context
    from v4.manager_research.workspace_projection import build_workspace

    source_date, plan_date = "20260928", "20260929"
    universe = tmp_path / "universe"
    store = universe / ".runtime/data"
    state = tmp_path / "manager_state"
    run_id = "20260928-hk-connect-d1-top100-0-2-fixture"
    run_dir = store / "runs" / source_date / "HK_CONNECT_D1_TOP100_0_2" / run_id
    run_dir.mkdir(parents=True)
    rows = []
    for rank in range(1, 101):
        rows.append({"trade_date": source_date, "bar_time": "17:30", "rank": rank,
                     "code": f"HK.{rank:05d}", "name": f"stock-{rank}",
                     "signal_date": "20260924", "target_date": source_date,
                     "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
                     "production_allowed": "False", "score_prob_active": "0.5"})
    import io
    buffer = io.StringIO(newline="")
    writer = __import__("csv").DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    artifact = buffer.getvalue().encode()
    (run_dir / "artifact.csv").write_bytes(artifact)
    artifact_rel = f"runs/{source_date}/HK_CONNECT_D1_TOP100_0_2/{run_id}/artifact.csv"
    manifest = {"schema_version": "v3_shared_data.manifest.v1", "market": "HK_CONNECT",
        "stage_id": "D1_PREMARKET", "trade_date": source_date, "row_count": 100,
        "source_id": "hkconnect_0_2_frozen_prob_active", "signal_date": "20260924",
        "captured_at": "2026-09-24T17:30:43+08:00", "artifact_relative": artifact_rel,
        "artifact_sha256": digest(artifact), "provenance": {"source_contract": "tdx_vipdoc_71_day_prob_active"}}
    manifest_raw = encoded(manifest)
    (run_dir / "manifest.json").write_bytes(manifest_raw)
    receipt = {"schema_version": "v3_shared_data.receipt.v1", "status": "READY",
        "owner": "v3_shared_data", "role": "HK_CONNECT_D1_TOP100_0_2", "trade_date": source_date,
        "run_id": run_id, "artifact_sha256": digest(artifact), "manifest_sha256": digest(manifest_raw),
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    (run_dir / "receipt.json").write_bytes(encoded(receipt))

    now = iter((datetime(2026, 9, 29, 0, 0, 5, tzinfo=HK),
                datetime(2026, 9, 29, 0, 0, 10, tzinfo=HK),
                datetime(2026, 9, 29, 0, 0, 10, 500000, tzinfo=HK),
                datetime(2026, 9, 29, 0, 0, 11, tzinfo=HK)))
    requested = []

    def collector(python, trade_date, stage_id, codes, **kwargs):
        requested.append((trade_date, stage_id, list(codes), kwargs["market"]))
        source_rows = [{"code": code, "update_time": "2026-09-28 15:46:00",
            "open_price": 10.0, "high_price": 10.5, "low_price": 9.9, "last_price": 10.2,
            "prev_close_price": 10.0, "turnover": 1000.0, "volume": 100,
            "window_start": "2026-09-28 15:46:00", "window_end": "2026-09-28 15:46:00",
            "bar_count": 1, "temporal_cutoff_safe": True} for code in codes]
        return SimpleNamespace(status="READ_OK", rows=source_rows, requested_code_count=100,
            completed_code_count=100, no_data_codes=[], cannot_confirm=[])

    outcome = materializer.recapture_close_minutes(
        manager_state_root=state, universe_root=universe,
        pytdx_python=Path(sys.executable), trade_date=source_date,
        provider_root=APP_ROOT / "upstreams/v3_shared_data",
        clock=lambda: next(now), pytdx_collector=collector,
    )
    assert outcome["status"] == "MATERIALIZED", (
        outcome.get("reason"), outcome.get("exception_type"), outcome.get("failure_diagnostic")
    )
    assert outcome["source_trade_date"] == source_date
    assert outcome["plan_trade_date"] == plan_date
    assert outcome["candidate_count"] == 100
    assert requested == [(source_date, "STAGE_1545_1555", [f"HK.{n:05d}" for n in range(1, 101)], "HK_CONNECT")]
    assert not (state / "workbench_research" / source_date / "1530.json").exists()
    assert not (state / "workbench_research" / source_date / "inputs" / "1530_futu_snapshot.json").exists()

    readback = ManagerWorkbenchResearchReader(state).read_close_recapture(source_date)
    assert readback["status"] == "READY"
    assert readback["target_trade_date"] == plan_date
    assert readback["candidate_overlay_verified"] is True
    assert readback["candidate_overlay"]["count"] == 100
    quote_sha = "a" * 64
    existing_close_quote = {
        "symbol": "HK.00001", "session_date": source_date, "verification": "OWNER_VERIFIED",
        "currency": "HKD", "session_kind": "FULL_DAY_CLOSE", "price_basis": "RAW",
        "source_refs": [{"payload_sha256": quote_sha}], "close": 30.0, "low": 28.0,
        "high": 31.0, "pre_close": 29.0,
    }
    cutoff = datetime(2026, 9, 29, 0, 0, 12, tzinfo=HK)
    workspace = build_workspace(plan_date,
        catalyst={"status": "READY", "target_trade_date": plan_date, "cards": []},
        close_recapture=readback,
        plan_context=plan_context(plan_date, now=cutoff),
        price_quotes={"HK.00001": existing_close_quote},
    )
    assert workspace["close_recapture_evidence"]["planner_availability"] == "AVAILABLE_BEFORE_CUTOFF"
    assert workspace["close_recapture_evidence"]["planner_eligible_context"] is True
    assert workspace["summary"]["formal_recommendation_count"] == 0
    assert len(workspace["stocks"]) == 100
    first_plan = workspace["stocks"][0]["plan"]
    assert first_plan["late_tail_observation"]["source_trade_date"] == source_date
    assert first_plan["late_tail_observation"]["plan_trade_date"] == plan_date
    assert first_plan["late_tail_observation"]["capture_artifact_sha256"] == readback["receipt"]["artifact_sha256"]
    assert first_plan["late_tail_observation"]["captured_at"] == readback["request"]["captured_at"]
    assert first_plan["late_tail_observation"]["price_semantics"] == "LATE_TAIL_MINUTE_OBSERVATION_NOT_FULL_DAY_CLOSE"
    assert first_plan["late_tail_observation"]["observation"]["last_price"] == 10.2
    assert first_plan["price_provenance"]["inputs"]["close"] == 30.0
    assert first_plan["trigger_price"] == 30.0
    assert workspace["stocks"][0]["plan"]["qualified"] is False

    before_available = datetime(2026, 9, 29, 0, 0, 9, tzinfo=HK)
    early_workspace = build_workspace(plan_date,
        catalyst={"status": "READY", "target_trade_date": plan_date, "cards": []},
        close_recapture=readback,
        plan_context=plan_context(plan_date, now=before_available),
    )
    assert early_workspace["close_recapture_evidence"]["planner_availability"] == "AFTER_CUTOFF"
    assert early_workspace["stocks"] == []


def _request(slot: str) -> DispatchRequest:
    return DispatchRequest(
        scheduled_date=DATE,
        business_date=DATE,
        target_date=DATE,
        slot=slot,
        mode=DispatchMode.LIVE,
    )


def _bound_setup(tmp_path, monkeypatch):
    owner_root = Path(
        os.environ.get("V4_TEST_OWNER_ROOT", Path(__file__).resolve().parents[1])
    ).resolve()
    owner_path = owner_root / "stage_center/hk_universe_preflight.py"
    assert owner_path.is_file()
    owner_sha = hashlib.sha256(owner_path.read_bytes()).hexdigest()
    app = Path(os.environ.get("V4_TEST_MANAGER_APP_ROOT", APP_ROOT)).resolve()
    child = app / "ops/materialize_manager_close_discovery.py"
    assert child.is_file()
    state = tmp_path / "manager_state"
    monkeypatch.setenv("V4_MANAGER_MATERIALIZER_APP_ROOT", str(app))
    monkeypatch.setenv("V4_MANAGER_MATERIALIZER_SHA256", hashlib.sha256(child.read_bytes()).hexdigest())
    monkeypatch.setenv("V4_MANAGER_RESEARCH_STATE_ROOT", str(state))
    monkeypatch.delenv("V4_MANAGER_UNIVERSE_OWNER_ROOT", raising=False)
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_SHA256", owner_sha)
    monkeypatch.delenv("V4_CLOSE_REBOUND_AUTHORITY_ROOT", raising=False)
    calls = []

    def runner(module, args, **kwargs):
        calls.append((module, args, kwargs))
        return {}

    manager = SimpleNamespace(
        repo_root=owner_root,
        data_root=tmp_path / "data",
        hk_universe_root=tmp_path / "universe",
        shared_futu_python_executable=Path(sys.executable),
        _run=runner,
    )
    return manager, calls, app, state, owner_root, owner_sha


def test_1500_preflight_keeps_repo_root_owner_fallback_and_60s_timeout(tmp_path, monkeypatch):
    manager, calls, app, _state, owner_root, owner_sha = _bound_setup(tmp_path, monkeypatch)
    child_sha = hashlib.sha256(
        (app / "ops/materialize_manager_close_discovery.py").read_bytes()
    ).hexdigest()

    def runner(module, args, **kwargs):
        calls.append((module, args, kwargs))
        return {
            "status": "SUCCEEDED",
            "exit_code": 0,
            "stdout": __import__("json").dumps(
                {
                    "schema_version": "v4.manager_close_materialization_result.v1",
                    "status": "UNIVERSE_READY",
                    "trade_date": DATE,
                    "slot": "1530",
                    "module_origin": str(app / "ops/materialize_manager_close_discovery.py"),
                    "module_sha256": child_sha,
                    "state_root": str(tmp_path / "manager_state"),
                    "universe_owner_sha256": owner_sha,
                    "code_count": 693,
                    "authority_sha256": "a" * 64,
                    "authority_run_id": "b" * 24,
                    "RESEARCH_ONLY": True,
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            ),
        }

    manager._run = runner
    outcome = manager_close._manager_universe_dependency(manager, _request("1500"))
    assert outcome["status"] == "SUCCEEDED"
    assert outcome["snapshot_requested"] is False
    assert outcome["candidate_publication_requested"] is False
    assert len(calls) == 1
    module, args, kwargs = calls[0]
    assert module == "ops.materialize_manager_close_discovery"
    assert args[args.index("--universe-owner-root") + 1] == str(owner_root)
    assert args[args.index("--universe-owner-sha256") + 1] == owner_sha
    assert "--universe-only" in args
    assert kwargs["timeout_seconds"] == 60


def test_1530_timeout_is_capped_and_reported_without_owner_root_binding(tmp_path, monkeypatch):
    manager, calls, _app, _state, owner_root, owner_sha = _bound_setup(tmp_path, monkeypatch)
    at = datetime(2026, 9, 24, 15, 30, tzinfo=HK)
    monkeypatch.setattr(manager_close, "_manager_close_hk_now", lambda: at)

    def runner(module, args, **kwargs):
        calls.append((module, args, kwargs))
        return {
            "status": "TIMEOUT",
            "exit_code": 124,
            "exception_type": "TimeoutExpired",
            "stdout": "",
        }

    manager._run = runner
    with pytest.raises(WorkloadExecutionError) as caught:
        manager_close._manager_close_1530(manager, _request("1530"))

    assert len(calls) == 1
    _, args, kwargs = calls[0]
    assert args[args.index("--universe-owner-root") + 1] == str(owner_root)
    assert args[args.index("--universe-owner-sha256") + 1] == owner_sha
    assert kwargs["timeout_seconds"] == 30
    assert caught.value.result["reason"] == "MANAGER_CHILD_TIMEOUT"
    assert caught.value.result["child_status"] == "TIMEOUT"
    assert caught.value.result["child_exception_type"] == "TimeoutExpired"
    assert caught.value.result["child_timeout_seconds"] == 30


def test_1530_child_timeout_never_crosses_exclusive_1532_deadline():
    before_deadline = datetime(2026, 9, 24, 15, 31, 40, tzinfo=HK)
    assert manager_close._manager_close_child_timeout_seconds(
        _request("1530"), now=before_deadline
    ) == 20
    final_fractional_second = datetime(2026, 9, 24, 15, 31, 59, 500000, tzinfo=HK)
    with pytest.raises(ValueError, match="EXACT_1530_SNAPSHOT_WINDOW_MISSED"):
        manager_close._manager_close_child_timeout_seconds(
            _request("1530"), now=final_fractional_second
        )
