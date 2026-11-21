"""Focused isolated checks for the natural producer proof overlay."""
import hashlib
import importlib.util
import json
import os
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
from contextlib import contextmanager

import pytest

ROOT = Path(__file__).resolve().parents[3]
R4_APP = ROOT / "artifacts/v4_main_autorun_r4_release_readiness_20261121/private/bundle/staging/v4-main-r4-release-20261121/app"
NATURAL = Path(__file__).resolve().parent
APP_OVERLAY = NATURAL / "app"
BASE = NATURAL / "base"
sys.path.insert(0, str(R4_APP))
import ops  # noqa: F401


def load_overlay(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load_overlay(
    "ops.qfq_directory_contract",
    APP_OVERLAY / "ops/qfq_directory_contract.py",
)
executor = load_overlay(
    "natural_executor_registry_review_overlay",
    APP_OVERLAY / "infrastructure/scheduling/executor_registry_review.py",
)
governance = load_overlay(
    "natural_storage_governance_overlay",
    APP_OVERLAY / "ops/research_storage_governance.py",
)


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def dispatch_context(pid, run_id="a" * 32):
    return {
        "schema": "v4.natural_dispatch_context.v1",
        "mode": "LIVE",
        "business_date": "20261123",
        "target_date": "20261123",
        "slot": "1610",
        "run_id": run_id,
        "workload_id": "research_panel_daily_a",
        "dispatcher_pid": pid,
        "dispatch_claim_sha256": "b" * 64,
        "workload_claim_sha256": "c" * 64,
    }


def test_dispatch_context_uses_exact_live_claims(tmp_path, monkeypatch):
    root = tmp_path / "ledger"
    suffix = Path("live/20261123/1610")
    common = {
        "run_id": "a" * 32,
        "pid": os.getpid(),
        "created_at": "2026-11-23T16:10:00+08:00",
        "scheduled_date": "20261123",
        "business_date": "20261123",
        "target_date": "20261123",
        "slot": "1610",
        "mode": "LIVE",
    }
    save_json(root / "claims" / suffix / "dispatch.claim.json", {
        "schema_version": "v3_5.dispatch_claim.v1", **common,
    })
    save_json(root / "workloads" / suffix / "research_panel_daily_a.workload-claim.json", {
        "schema_version": "v3_5.workload_claim.v1", "workload_id": "research_panel_daily_a", **common,
    })
    monkeypatch.setenv("V4_DISPATCH_LEDGER_ROOT", str(root))
    request = SimpleNamespace(
        mode=SimpleNamespace(value="LIVE"), business_date="20261123", target_date="20261123", slot="1610"
    )
    context, error = executor._natural_dispatch_context(request)
    assert error is None
    assert context["run_id"] == common["run_id"]
    assert context["dispatcher_pid"] == os.getpid()
    assert len(context["dispatch_claim_sha256"]) == len(context["workload_claim_sha256"]) == 64


@pytest.mark.parametrize("damage", ["run", "pid", "workload", "schema", "mode"])
def test_dispatch_context_rejects_mismatched_claims(tmp_path, monkeypatch, damage):
    root = tmp_path / "ledger"
    suffix = Path("live/20261123/1610")
    common = {
        "run_id": "a" * 32, "pid": os.getpid(), "created_at": "t",
        "scheduled_date": "20261123", "business_date": "20261123",
        "target_date": "20261123", "slot": "1610", "mode": "LIVE",
    }
    dispatch = {"schema_version": "v3_5.dispatch_claim.v1", **common}
    workload = {"schema_version": "v3_5.workload_claim.v1", "workload_id": "research_panel_daily_a", **common}
    if damage == "run":
        workload["run_id"] = "d" * 32
    elif damage == "pid":
        workload["pid"] = True
    elif damage == "workload":
        workload["workload_id"] = "other"
    elif damage == "schema":
        dispatch["schema_version"] = "wrong"
    elif damage == "mode":
        dispatch["mode"] = "DRY_RUN"
    save_json(root / "claims" / suffix / "dispatch.claim.json", dispatch)
    save_json(root / "workloads" / suffix / "research_panel_daily_a.workload-claim.json", workload)
    monkeypatch.setenv("V4_DISPATCH_LEDGER_ROOT", str(root))
    request = SimpleNamespace(
        mode=SimpleNamespace(value="LIVE"), business_date="20261123", target_date="20261123", slot="1610"
    )
    assert executor._natural_dispatch_context(request)[0] is None


def test_natural_receipt_requires_raw_provider_and_finished_qfq_claim(tmp_path):
    date, generation, input_sha = "20261123", "d" * 64, "e" * 64
    dispatch = dispatch_context(200)
    producer = {"pid": 300, "started": "Mon Nov 23 16:10:00 2026"}
    provider = {
        "schema": "v4.natural_source_provider_invocation.v1",
        "provider_task_name": "tdxpy_daily_vipdoc_sync_v1",
        "provider_run_id": date + "-" + "f" * 16 + "-123",
        "target_date": date, "status": "PASS", "exit_code": 0,
        "producer_process": producer, "parent_dispatcher_pid": 200, "dispatch": dispatch,
    }
    return_root = tmp_path / "return-root"
    run_dir = return_root / ("qfq_" + generation[:20])
    run_dir.mkdir(parents=True)
    qfq = {
        "schema": "v4.qfq_natural_execution.v2", "status": "CLAIM_FINISHED_READY",
        "task_key": "1" * 64, "attempt": 1, "claim_token_sha256": "2" * 64,
        "claim_owner": producer, "registry_row_sha256": "3" * 64,
        "return_root": str(return_root), "run_dir": str(run_dir),
        "target_date": date, "generation_id": generation, "input_sha256": input_sha,
        "already_current": False, "dispatch": dispatch, "provider_invocation": provider,
        "candidate_receipt": {"path": str(run_dir / "candidate_receipt.json"), "sha256": "4" * 64},
        "ready_receipt": {"path": str(run_dir / "stage_status.json"), "sha256": "5" * 64},
    }
    receipt = {
        "status": "READY", "target_date": date,
        "sync": {"target_date": date, "natural_dispatch_context": dispatch, "provider_invocation": provider},
        "formula": {"authority": {"generation_id": generation, "source_sha256": input_sha}, "natural_execution": qfq},
    }
    assert executor._verified_natural_receipt(receipt, dispatch, date)
    for bad_value in (None, "true", False):
        damaged = json.loads(json.dumps(receipt))
        damaged["sync"]["provider_invocation"]["exit_code"] = bad_value
        damaged["formula"]["natural_execution"]["provider_invocation"]["exit_code"] = bad_value
        assert not executor._verified_natural_receipt(damaged, dispatch, date)
    damaged = json.loads(json.dumps(receipt))
    damaged["formula"]["natural_execution"].pop("return_root")
    assert not executor._verified_natural_receipt(damaged, dispatch, date)
    damaged = json.loads(json.dumps(receipt))
    damaged["formula"]["natural_execution"]["run_dir"] = str(return_root / ("qfq_" + "f" * 20))
    assert not executor._verified_natural_receipt(damaged, dispatch, date)
    for field in ("provider_invocation", "natural_dispatch_context"):
        damaged = json.loads(json.dumps(receipt))
        if field == "provider_invocation":
            del damaged["sync"][field]
        else:
            del damaged["sync"][field]
        assert not executor._verified_natural_receipt(damaged, dispatch, date)


def test_qfq_proof_requires_finished_claim_and_binds_token_attempt(tmp_path, monkeypatch):
    date, generation, input_sha = "20261123", "d" * 64, "e" * 64
    owner = {"pid": os.getpid(), "started": "Mon Nov 23 16:10:00 2026"}
    dispatch = dispatch_context(200)
    provider = {
        "schema": "v4.natural_source_provider_invocation.v1",
        "provider_task_name": "tdxpy_daily_vipdoc_sync_v1",
        "provider_run_id": date + "-" + "f" * 16 + "-123",
        "target_date": date, "status": "PASS", "exit_code": 0,
        "producer_process": owner, "parent_dispatcher_pid": 200, "dispatch": dispatch,
    }
    monkeypatch.setenv("V4_NATURAL_SOURCE_PROVIDER_INVOCATION_JSON", json.dumps(provider))
    return_root = tmp_path / "qfq-return-root"
    run_dir = return_root / ("qfq_" + generation[:20])
    run_dir.mkdir(parents=True)
    candidate_ref = save_json(run_dir / "candidate_receipt.json", {
        "status": "CANDIDATE_READY", "target_date": int(date), "run_dir": str(run_dir),
        "generation_id": generation, "input_sha256": input_sha,
    })
    ready_ref = save_json(run_dir / "stage_status.json", {
        "status": "READY", "target_date": int(date), "run_dir": str(run_dir),
        "generation_id": generation, "input_sha256": input_sha,
    })
    summary = {
        "generation_id": generation, "target_date": int(date),
        "complete_owner_receipt": candidate_ref, "ready_owner_receipt": ready_ref,
    }
    task_key, token = "a" * 64, "b" * 32
    row = {
        "state": "READY", "owner": owner, "token": token, "attempts": 2,
        "directory": str(return_root), "result": summary,
    }

    class Registry:
        root = tmp_path / "registry"

        def read(self):
            return {"tasks": {task_key: row}}

    claim = SimpleNamespace(
        finalized=True, recording_failed=False, owner=owner, key=task_key, token=token,
        registry=Registry(), directory=str(return_root),
    )
    result = {
        "status": "READY", "target_date": int(date), "run_dir": str(run_dir),
        "selector": str(run_dir / "selector.parquet"), "backtest": str(run_dir / "backtest.parquet"),
        "authority": {"generation_id": generation, "source_sha256": input_sha},
    }
    proof = governance._natural_qfq_execution(claim, result, summary, int(date))
    assert proof["task_key"] == task_key
    assert proof["attempt"] == 2
    assert proof["claim_token_sha256"] == hashlib.sha256(token.encode()).hexdigest()
    assert proof["registry_row_sha256"] == hashlib.sha256(
        json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    claim.finalized = False
    assert governance._natural_qfq_execution(claim, result, summary, int(date)) is None


def test_real_claim_records_return_root_while_receipts_bind_generation_child(tmp_path, monkeypatch):
    date = "20261123"
    generation, input_sha = "d" * 64, "e" * 64
    return_root = tmp_path / "managed-return-root"
    return_root.mkdir()
    run_dir = return_root / ("qfq_" + generation[:20])
    run_dir.mkdir()
    selector, backtest = run_dir / "selector.parquet", run_dir / "backtest.parquet"
    selector.write_bytes(b"isolated selector candidate")
    backtest.write_bytes(b"isolated backtest candidate")
    selector_sha = hashlib.sha256(selector.read_bytes()).hexdigest()
    backtest_sha = hashlib.sha256(backtest.read_bytes()).hexdigest()
    candidates = {"selector": str(selector), "backtest": str(backtest)}
    candidate_sha = {"selector": selector_sha, "backtest": backtest_sha}
    flags = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    candidate_ref = save_json(run_dir / "candidate_receipt.json", {
        "status": "CANDIDATE_READY", "target_date": int(date), "run_dir": str(run_dir),
        "generation_id": generation, "input_sha256": input_sha, "candidates": candidates,
        "candidate_sha256": candidate_sha, **flags,
    })
    ready_ref = save_json(run_dir / "stage_status.json", {
        "status": "READY", "target_date": int(date), "run_dir": str(run_dir),
        "generation_id": generation, "input_sha256": input_sha, "candidates": candidates,
        "candidate_sha256": candidate_sha, "selector_pointer_ready": True,
        "backtest_pointer_ready": True, **flags,
    })
    summary = {
        "schema": "qfq_registry_owner_receipt_summary.v1", "status": "READY",
        "generation_id": generation, "target_date": int(date),
        "selector": str(selector), "backtest": str(backtest),
        "candidate_sha256": candidate_sha,
        "complete_owner_receipt": candidate_ref, "ready_owner_receipt": ready_ref,
        **flags,
    }

    class IsolatedRegistry:
        def __init__(self):
            self.root = tmp_path / "registry"
            self.config = {
                "pool_id": "isolated-natural-test", "accounting_roots": {"debug": []},
                "creation_roots": [], "max_attempts": 3,
                "max_debug_job_bytes": 256 * 1024**2,
            }
            self.state = {
                "schema": "v4_storage_governance_v2", "pool_id": self.config["pool_id"],
                "tasks": {}, "resident_baseline_paths": None,
            }

        @contextmanager
        def transaction(self):
            yield

        def read(self):
            return copy.deepcopy(self.state)

        def save(self, state, *, admitting=False):
            self.state = copy.deepcopy(state)

        def space(self, state, key, remaining, **kwargs):
            return {"free_bytes": 1_000_000_000, "total_bytes": 2_000_000_000,
                    "remaining_bytes": remaining, "other_remaining_bytes": 0,
                    "ratio_denominator": "isolated-test-only"}

        def remaining(self, row):
            return max(0, row["reserved_bytes"] - row.get("written_bytes", 0))

    registry = IsolatedRegistry()
    task_key = "a" * 64
    claim = governance.Claim(
        registry, task_key, return_root, 1_000_000, category="debug",
        qfq_context={"target": int(date), "classified_rows": {}},
    )
    claim.begin(reuse_ready=False)
    claim.finish(summary, [selector, backtest])
    producer = dict(claim.owner)
    dispatch = dispatch_context(os.getpid())
    provider = {
        "schema": "v4.natural_source_provider_invocation.v1",
        "provider_task_name": "tdxpy_daily_vipdoc_sync_v1",
        "provider_run_id": date + "-" + "f" * 16 + "-123456789",
        "target_date": date, "status": "PASS", "exit_code": 0,
        "producer_process": producer, "parent_dispatcher_pid": dispatch["dispatcher_pid"],
        "dispatch": dispatch,
    }
    monkeypatch.setenv("V4_NATURAL_SOURCE_PROVIDER_INVOCATION_JSON", json.dumps(provider))
    result = {
        "status": "READY", "target_date": int(date), "run_dir": str(run_dir),
        "selector": str(selector), "backtest": str(backtest),
        "authority": {"generation_id": generation, "source_sha256": input_sha},
    }
    proof = governance._natural_qfq_execution(claim, result, summary, int(date))
    assert proof is not None
    assert proof["schema"] == "v4.qfq_natural_execution.v2"
    assert proof["return_root"] == str(return_root)
    assert proof["run_dir"] == str(run_dir)
    row = registry.read()["tasks"][task_key]
    assert row["directory"] == str(return_root)
    assert row["qfq_identity"]["key"] == task_key
    assert row["qfq_identity"]["target"] == int(date)
    assert proof["registry_row_sha256"] == hashlib.sha256(
        json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()

    wrong_root_claim = SimpleNamespace(**claim.__dict__)
    wrong_root_claim.directory = str(run_dir)
    assert governance._natural_qfq_execution(wrong_root_claim, result, summary, int(date)) is None
