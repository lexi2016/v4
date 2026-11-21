"""Focused isolated checks for the natural producer proof overlay."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
R4_APP = ROOT / "artifacts/v4_main_autorun_r4_release_readiness_20261121/private/bundle/staging/v4-main-r4-release-20261121/app"
BASE = Path(__file__).resolve().parent / "base"
sys.path.insert(0, str(R4_APP))


def load_overlay(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = load_overlay(
    "natural_executor_registry_review_overlay",
    BASE / "infrastructure/scheduling/executor_registry_review.py",
)
governance = load_overlay(
    "natural_storage_governance_overlay",
    BASE / "ops/research_storage_governance.py",
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


def test_natural_receipt_requires_raw_provider_and_finished_qfq_claim():
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
    qfq = {
        "schema": "v4.qfq_natural_execution.v1", "status": "CLAIM_FINISHED_READY",
        "task_key": "1" * 64, "attempt": 1, "claim_token_sha256": "2" * 64,
        "claim_owner": producer, "registry_row_sha256": "3" * 64,
        "target_date": date, "generation_id": generation, "input_sha256": input_sha,
        "already_current": False, "dispatch": dispatch, "provider_invocation": provider,
        "candidate_receipt": {"path": "/tmp/candidate.json", "sha256": "4" * 64},
        "ready_receipt": {"path": "/tmp/ready.json", "sha256": "5" * 64},
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
    run_dir = tmp_path / "qfq-run"
    candidate_ref = save_json(run_dir / "candidate_receipt.json", {
        "status": "CANDIDATE_READY", "target_date": int(date), "generation_id": generation, "input_sha256": input_sha,
    })
    ready_ref = save_json(run_dir / "stage_status.json", {
        "status": "READY", "target_date": int(date), "generation_id": generation, "input_sha256": input_sha,
    })
    summary = {
        "generation_id": generation, "target_date": int(date),
        "complete_owner_receipt": candidate_ref, "ready_owner_receipt": ready_ref,
    }
    task_key, token = "a" * 64, "b" * 32
    row = {
        "state": "READY", "owner": owner, "token": token, "attempts": 2,
        "directory": str(run_dir), "result": summary,
    }

    class Registry:
        root = tmp_path / "registry"

        def read(self):
            return {"tasks": {task_key: row}}

    claim = SimpleNamespace(
        finalized=True, recording_failed=False, owner=owner, key=task_key, token=token,
        registry=Registry(),
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
