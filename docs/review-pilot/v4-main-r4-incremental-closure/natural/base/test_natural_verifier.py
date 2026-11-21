"""Dated natural proof fixtures; no daemon, provider, or API is started."""
import hashlib
import json
import os
import plistlib
import shutil
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

import verify_top200_readonly as v


def raw_sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": raw_sha(raw)}


def row_sha(row):
    return raw_sha(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def artifact_logical_sha(selector_sha, backtest_sha):
    return raw_sha(f"selector:{selector_sha}\nbacktest:{backtest_sha}\n".encode("ascii"))


@pytest.fixture
def sample(tmp_path, monkeypatch):
    date, slot, run = "20261123", "1610", "9" * 32
    gen, source = "a" * 64, "b" * 64
    daemon_started = "2026-11-23T15:00:00+08:00"
    manifest_sha = "1" * 64
    work = tmp_path / "product/daily_products/a_share"
    ledger = tmp_path / "ledger"
    root = tmp_path / "receipts"
    registry_root = tmp_path / "registry"
    qfq_return_root = tmp_path / "qfq-return-root"
    qfq_return_root.mkdir()
    policy_path = tmp_path / "policy.json"
    policy = {"run_root": str(qfq_return_root),
              "governance": {"registry_root": str(registry_root), "pool_id": "fixture-pool"}}
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_raw = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    policy_path.write_bytes(policy_raw)
    env = {
        "V4_DISPATCH_LEDGER_ROOT": str(ledger),
        "V4_RESEARCH_PANEL_RECEIPT_ROOT": str(root),
        "V4_A_SHARE_DAILY_PRODUCT_ROOT": str(tmp_path / "product"),
        "V4_RESEARCH_RETENTION_POLICY": str(policy_path),
        "V4_RESEARCH_RETENTION_POLICY_SHA256": raw_sha(policy_raw),
        "V4_RELEASE_ID": "v4-main-r4-release-20261121",
        "V4_DAEMON_MODE": "persistent-minute",
    }
    for role in ("selector", "backtest"):
        path = root / (role + ".parquet")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((role + " bytes").encode())
        pointer = root / (role + ".txt")
        pointer.write_text(str(path), encoding="utf-8")
        env["V4_RESEARCH_PANEL_A_" + role.upper() + "_POINTER"] = str(pointer)
    selector, backtest = root / "selector.parquet", root / "backtest.parquet"
    selector_sha, backtest_sha = v.sha(selector), v.sha(backtest)
    logical_sha = artifact_logical_sha(selector_sha, backtest_sha)

    flags = dict(v.FLAGS)
    dispatch_claim = {
        "schema_version": "v3_5.dispatch_claim.v1", "run_id": run,
        "pid": 333, "created_at": "2026-11-23T16:10:06+08:00",
        "scheduled_date": date, "business_date": date, "target_date": date,
        "slot": slot, "mode": "LIVE",
    }
    workload_claim = {
        "schema_version": "v3_5.workload_claim.v1", "run_id": run,
        "workload_id": v.WORKLOAD, "pid": 333,
        "created_at": "2026-11-23T16:10:06+08:00",
        "scheduled_date": date, "business_date": date, "target_date": date,
        "slot": slot, "mode": "LIVE",
    }
    suffix = Path("live") / date / slot
    dispatch_claim_ref = save(ledger / "claims" / suffix / "dispatch.claim.json", dispatch_claim)
    workload_ref = save(ledger / "workloads" / suffix / (v.WORKLOAD + ".workload-claim.json"), workload_claim)
    context = {
        "schema": "v4.natural_dispatch_context.v1", "mode": "LIVE",
        "business_date": date, "target_date": date, "slot": slot,
        "run_id": run, "workload_id": v.WORKLOAD, "dispatcher_pid": 333,
        "dispatch_claim_sha256": dispatch_claim_ref["sha256"],
        "workload_claim_sha256": workload_ref["sha256"],
        "dispatch_claim_created_at": dispatch_claim["created_at"],
        "workload_claim_created_at": workload_claim["created_at"],
    }
    owner = {"pid": 555, "started": "Mon Nov 23 16:10:05 2026"}
    provider = {
        "schema": "v4.natural_source_provider_invocation.v1",
        "provider_task_name": "tdxpy_daily_vipdoc_sync_v1",
        "provider_run_id": date + "-" + "f" * 16 + "-123456789",
        "target_date": date, "status": "PASS", "exit_code": 0,
        "producer_process": owner, "parent_dispatcher_pid": 333, "dispatch": context,
    }
    qfq_run = qfq_return_root / ("qfq_" + gen[:20])
    candidates = {"selector": str(selector), "backtest": str(backtest)}
    candidate_sha = {"selector": selector_sha, "backtest": backtest_sha}
    candidate_doc = {
        "status": "CANDIDATE_READY", "target_date": int(date), "run_dir": str(qfq_run),
        "generation_id": gen, "input_sha256": source, "candidates": candidates,
        "candidate_sha256": candidate_sha, **flags,
    }
    ready_doc = {
        "status": "READY", "target_date": int(date), "run_dir": str(qfq_run),
        "generation_id": gen, "input_sha256": source, "candidates": candidates,
        "candidate_sha256": candidate_sha, "selector_pointer_ready": True,
        "backtest_pointer_ready": True, **flags,
    }
    candidate_ref = save(qfq_run / "candidate_receipt.json", candidate_doc)
    ready_ref = save(qfq_run / "stage_status.json", ready_doc)
    task_key, token, attempt = "c" * 64, "d" * 32, 2
    owner_summary = {
        "schema": "qfq_registry_owner_receipt_summary.v1", "status": "READY",
        "generation_id": gen, "target_date": int(date),
        "selector": str(selector), "backtest": str(backtest),
        "candidate_sha256": candidate_sha,
        "complete_owner_receipt": candidate_ref, "ready_owner_receipt": ready_ref,
        **flags,
    }
    row = {
        "state": "READY", "owner": owner, "token": token,
        "attempts": attempt, "directory": str(qfq_return_root), "result": owner_summary,
        "qfq_identity": {"schema": "v4.qfq_operation_identity.v2", "key": task_key, "target": int(date)},
        "artifacts": [
            {"path": str(selector), "sha256": selector_sha},
            {"path": str(backtest), "sha256": backtest_sha},
        ],
    }
    registry_root.mkdir(parents=True, exist_ok=True)
    save(registry_root / "registry.json", {
        "schema": "v4_storage_governance_v2", "pool_id": "fixture-pool",
        "tasks": {task_key: row}, "resident_baseline_paths": None,
    })
    qfq = {
        "schema": "v4.qfq_natural_execution.v2", "status": "CLAIM_FINISHED_READY",
        "task_key": task_key, "attempt": attempt,
        "claim_token_sha256": raw_sha(token.encode("ascii")), "claim_owner": owner,
        "registry_root": str(registry_root), "registry_row_sha256": row_sha(row),
        "return_root": str(qfq_return_root), "run_dir": str(qfq_run),
        "target_date": date, "generation_id": gen, "input_sha256": source,
        "already_current": False, "dispatch": context, "provider_invocation": provider,
        "candidate_receipt": candidate_ref, "ready_receipt": ready_ref,
    }
    official = {
        "status": "READY", "target_date": date, "sha256": logical_sha,
        "selector": str(selector), "selector_sha256": selector_sha,
        "backtest": str(backtest), "backtest_sha256": backtest_sha,
        "sync": {"target_date": date, "natural_dispatch_context": context,
                 "provider_invocation": provider, **flags},
        "formula": {"authority": {"generation_id": gen, "source_sha256": source},
                    "natural_execution": qfq},
        **flags,
    }
    official_path = root / ("a-" + date + ".json")
    save(official_path, official)
    official_sha = v.sha(official_path)

    numeric_ref = save(work / "numeric.json", {
        "data_date": date, "source_generation": gen, "input_sha256": source,
        "sample_only": False, "artifact": {"fixture": "verified"}, **flags,
    })
    top_ref = save(work / "top.json", {
        "data_date": date, "source_generation": gen, "input_sha256": source,
        "numeric_manifest": numeric_ref, "top200_count": 200,
        "top200": [{"symbol": f"{i:06d}.SZ"} for i in range(200)], **flags,
    })
    index = {"dates": {date: numeric_ref}, "top200": {date: top_ref}}
    ix = save(work / "index-before-advancement.json", index)
    save(work / "index.json", {**index, "attempts": {"later": "changed"}})
    event_ref = save(work / "event-original.json", {
        "data_date": date, "source_generation": gen, "input_sha256": source,
        "manifest": numeric_ref, "top200": top_ref,
        "artifact": {"fixture": "verified"}, **flags,
    })
    derivative = {
        "status": "COMPLETE_DESCRIPTIVE_NONPIT", "data_date": date,
        "source_generation": gen, **flags,
        "top200": {"status": "PUBLISHED_TOP200", "event": event_ref,
                   "index": {"path": ix["path"], "sha256": ix["sha256"]}, **flags},
    }
    derivative["attempt"] = save(root / "attempt.json", derivative)
    source_lane = {
        "status": "READY", "target_date": date, "sha256": logical_sha,
        "sync": official["sync"], "formula": official["formula"], **flags,
    }
    outcome = {
        "status": "SUCCEEDED", "workload_id": v.WORKLOAD, "lane": "A",
        "target_date": date, "migration_reuse": False,
        "provider_invoked": True, "source_recomputed": True,
        "dated_source_receipt": {"path": str(official_path), "sha256": official_sha},
        "source_result": {"natural_dispatch_context": context, "lanes": {"A": source_lane}},
        "daily_derivatives": derivative, **flags,
    }
    common = {
        "scheduled_date": date, "business_date": date, "target_date": date,
        "slot": slot, "mode": "LIVE", "run_id": run,
    }
    dispatch = {
        "schema_version": "v3_5.dispatch.v1", "status": "SUCCEEDED", **common,
        "release_id": env["V4_RELEASE_ID"], "attempt": 1,
        "invoked_workload_ids": [v.WORKLOAD], "succeeded_workload_ids": [v.WORKLOAD],
        "workload_results": [outcome], "finished_at": "2026-11-23T16:12:00+08:00",
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    dispatch["ledger_sha256"] = v.ledger_hash(dispatch)
    dispatch_path = ledger / "receipts" / suffix / (run + ".dispatch-receipt.json")
    save(dispatch_path, dispatch)
    observation = {
        "pid": 333, "slot": slot, "business_date": date, "lane": "A_LONG",
        "schema_version": "v4.scheduler_observation.v1",
        "planned_at": "2026-11-23T16:10:00+08:00",
        "cutoff_at": "2026-11-23T16:30:00+08:00",
        "actual_started_at": "2026-11-23T16:10:05+08:00",
        "daemon_pid": 444, "daemon_started_at": daemon_started,
        "release_manifest_sha256": manifest_sha,
    }
    observation_root = ledger / "scheduler_observations" / suffix
    save(observation_root / "a.observation.json", {**observation, "status": "RUNNING"})
    save(observation_root / "b.observation.json", {
        **observation, "status": "FINISHED", "run_id": run,
        "return_code": 0, "result_status": "SUCCEEDED",
        "observed_at": "2026-11-23T16:12:05+08:00",
    })
    env["V4_RESEARCH_PANEL_RECEIPT_ROOT"] = str(root)
    env["V4_A_SHARE_DAILY_PRODUCT_ROOT"] = str(tmp_path / "product")
    env["V4_RESEARCH_RETENTION_POLICY"] = str(policy_path)
    for role in ("selector", "backtest"):
        env["V4_RESEARCH_PANEL_A_" + role.upper() + "_POINTER"] = str(root / (role + ".txt"))
    api = {
        "requested_date": date, "selected_source_status": "SAME_SNAPSHOT_RECONCILED",
        "safety_flags": flags,
        "detail_projection": {"source_generation": gen, "top200_artifact": top_ref, "numeric_manifest": numeric_ref},
        "dates": [{"date": date, "status": "PARTIAL", "top200": {"top_count": 200},
                   "stage_coverage": {"available": 7, "total": 7, "missing_stages": []}}],
    }
    response_raw = json.dumps(api, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    app_root = Path(v.__file__).resolve().parents[1] / "app"
    contract_path = app_root / "ops/qfq_directory_contract.py"

    def fake_fetch(requested_date, response_output=None, env=None):
        assert requested_date == date
        if response_output is not None:
            v._store_api_response(response_output, response_raw, env)
        return api, raw_sha(response_raw)

    monkeypatch.setattr(v, "fetch_api", fake_fetch)
    monkeypatch.setattr(v, "loaded_identity", lambda *_: {
        "fixture": True, "manifest_sha256": manifest_sha,
        "daemon_pid": 444, "daemon_started_at": daemon_started,
        "daemon_mode": "persistent-minute",
        "app_root": str(app_root),
        "qfq_directory_contract_sha256": raw_sha(contract_path.read_bytes()),
    })
    evidence = tmp_path / "future-evidence"
    evidence.mkdir()
    args = SimpleNamespace(
        date=date, slot=slot, run_id=run, release_id=env["V4_RELEASE_ID"],
        publication_index_copy=Path(ix["path"]), publication_event_copy=None,
        api_response_output=evidence / "api-response.raw",
    )
    return args, env, api, dispatch, dispatch_path, official_path, outcome, response_raw


@pytest.mark.parametrize("variant,reason", [
    ("positive", None),
    ("six-stages", "EXACT_7_OF_7_STAGES"),
    ("stale-date", "FORMAL_API_EXACT_DATE_SOURCE"),
    ("bad-generation", "FORMAL_API_EXACT_GENERATION"),
    ("return-code-bool", "NATURAL_DAEMON_RUN_AND_FINISH_REQUIRED"),
    ("executor-id-bool", "CLAIM_EXECUTOR_ID_TYPE_INVALID"),
    ("observation-executor-bool", "OBSERVATION_EXECUTOR_ID_TYPE_INVALID"),
    ("bad-daemon", "OBSERVED_DAEMON_MAIN_IDENTITY_MISMATCH"),
    ("wrong-observation-run", "NATURAL_DAEMON_TIMELINE"),
    ("missing-provider-flag", "NATURAL_PRODUCER_FLAGS_MUST_BE_EXPLICIT_TRUE"),
    ("null-provider-flag", "NATURAL_PRODUCER_FLAGS_MUST_BE_EXPLICIT_TRUE"),
    ("zero-provider-flag", "NATURAL_PRODUCER_FLAGS_MUST_BE_EXPLICIT_TRUE"),
    ("wrong-type-provider-flag", "NATURAL_PRODUCER_FLAGS_MUST_BE_EXPLICIT_TRUE"),
    ("false-recompute-flag", "NATURAL_PRODUCER_FLAGS_MUST_BE_EXPLICIT_TRUE"),
    ("missing-migration-flag", "NATURAL_PRODUCER_FLAGS_MUST_BE_EXPLICIT_TRUE"),
    ("manual-reuse", "NATURAL_PRODUCER_FLAGS_MUST_BE_EXPLICIT_TRUE"),
    ("missing-qfq", "QFQ_NATURAL_EXECUTION_PROOF_REQUIRED"),
    ("qfq-null-attempt", "QFQ_TASK_KEY_ATTEMPT_TOKEN_REQUIRED"),
    ("qfq-zero-attempt", "QFQ_TASK_KEY_ATTEMPT_TOKEN_REQUIRED"),
    ("qfq-bool-attempt", "QFQ_TASK_KEY_ATTEMPT_TOKEN_REQUIRED"),
    ("qfq-cross-task", "QFQ_TASK_ROW_MISSING"),
    ("qfq-cross-date", "QFQ_TASK_DATE_MISMATCH"),
    ("qfq-cross-run", "NATURAL_QFQ_PRODUCER_BINDING_MISMATCH"),
    ("qfq-generation", "QFQ_OWNER_RECEIPT_GENERATION_OR_INPUT_MISMATCH"),
    ("qfq-wrong-root", "QFQ_RETURN_ROOT_POLICY_BINDING"),
    ("qfq-wrong-generation-child", "QFQ_GENERATION_DIRECTORY_BINDING"),
    ("qfq-symlink-root", "QFQ_GENERATION_DIRECTORY_BINDING"),
    ("qfq-row-directory", "QFQ_RETURN_ROOT_REGISTRY_ROW_MISMATCH"),
    ("qfq-policy-root", "QFQ_RETURN_ROOT_POLICY_BINDING"),
    ("qfq-wrong-receipt-parent", "QFQ_OWNER_RECEIPT_GENERATION_OR_INPUT_MISMATCH"),
    ("qfq-reused", "QFQ_FRESH_FINISHED_CLAIM_REQUIRED"),
    ("missing-source-proof", "NATURAL_RAW_PROVIDER_INVOCATION_REQUIRED"),
    ("source-cross-date", "NATURAL_RAW_PROVIDER_INVOCATION_REQUIRED"),
    ("raw-receipt-sha", "DISPATCH_DATED_RECEIPT_RAW_SHA_BINDING"),
    ("logical-sha", "A_DAILY_LOGICAL_SHA_CONTRACT_MISMATCH"),
    ("manual-flags", "NATURAL_PRODUCER_FLAGS_MUST_BE_EXPLICIT_TRUE"),
])
def test_dated_natural_contract(sample, variant, reason):
    args, env, api, dispatch, dispatch_path, official_path, outcome, response_raw = sample
    if variant == "six-stages":
        api["dates"][0]["stage_coverage"]["available"] = 6
    elif variant == "stale-date":
        api["requested_date"] = "20261120"
    elif variant == "bad-generation":
        api["detail_projection"]["source_generation"] = "e" * 64
    elif variant == "return-code-bool":
        path = Path(env["V4_DISPATCH_LEDGER_ROOT"]) / "scheduler_observations/live/20261123/1610/b.observation.json"
        item = v.read(path); item["return_code"] = False; save(path, item)
    elif variant == "executor-id-bool":
        path = Path(env["V4_DISPATCH_LEDGER_ROOT"]) / "workloads/live/20261123/1610/research_panel_daily_a.workload-claim.json"
        item = v.read(path); item["executor_id"] = False; save(path, item)
    elif variant == "observation-executor-bool":
        path = Path(env["V4_DISPATCH_LEDGER_ROOT"]) / "scheduler_observations/live/20261123/1610/a.observation.json"
        item = v.read(path); item["executor_id"] = False; save(path, item)
    elif variant == "bad-daemon":
        path = Path(env["V4_DISPATCH_LEDGER_ROOT"]) / "scheduler_observations/live/20261123/1610/b.observation.json"
        item = v.read(path); item["daemon_pid"] = 445; save(path, item)
    elif variant == "wrong-observation-run":
        path = Path(env["V4_DISPATCH_LEDGER_ROOT"]) / "scheduler_observations/live/20261123/1610/b.observation.json"
        item = v.read(path); item["run_id"] = "8" * 32; save(path, item)
    elif variant in {"missing-provider-flag", "null-provider-flag", "zero-provider-flag", "wrong-type-provider-flag",
                     "false-recompute-flag", "missing-migration-flag", "manual-reuse", "manual-flags"}:
        if variant == "missing-provider-flag":
            outcome.pop("provider_invoked")
        elif variant == "null-provider-flag":
            outcome["provider_invoked"] = None
        elif variant == "zero-provider-flag":
            outcome["provider_invoked"] = 0
        elif variant == "wrong-type-provider-flag":
            outcome["provider_invoked"] = "true"
        elif variant == "false-recompute-flag":
            outcome["source_recomputed"] = False
        elif variant == "missing-migration-flag":
            outcome.pop("migration_reuse")
        else:
            outcome["migration_reuse"] = True
            outcome["provider_invoked"] = False
            outcome["source_recomputed"] = False
    elif variant in {"missing-qfq", "qfq-null-attempt", "qfq-zero-attempt", "qfq-bool-attempt",
                     "qfq-cross-task", "qfq-cross-date", "qfq-cross-run", "qfq-generation",
                     "qfq-wrong-root", "qfq-wrong-generation-child", "qfq-symlink-root",
                     "qfq-row-directory", "qfq-policy-root", "qfq-wrong-receipt-parent", "qfq-reused"}:
        qfq = v.read(official_path)["formula"]["natural_execution"]
        if variant == "missing-qfq":
            official = v.read(official_path); official["formula"].pop("natural_execution"); save(official_path, official)
        elif variant == "qfq-null-attempt":
            qfq["attempt"] = None
        elif variant == "qfq-zero-attempt":
            qfq["attempt"] = 0
        elif variant == "qfq-bool-attempt":
            qfq["attempt"] = True
        elif variant == "qfq-cross-task":
            qfq["task_key"] = "f" * 64
        elif variant == "qfq-cross-date":
            qfq["target_date"] = "20261122"
        elif variant == "qfq-cross-run":
            qfq["dispatch"]["run_id"] = "8" * 32
        elif variant == "qfq-generation":
            qfq["generation_id"] = "e" * 64
        elif variant == "qfq-wrong-root":
            other_root = Path(qfq["return_root"]).parent / "other-return-root"
            other_root.mkdir()
            qfq["return_root"] = str(other_root)
        elif variant == "qfq-wrong-generation-child":
            run_dir = Path(qfq["run_dir"])
            sibling = run_dir.parent / ("qfq_" + "e" * 20)
            sibling.mkdir()
            qfq["run_dir"] = str(sibling)
        elif variant == "qfq-symlink-root":
            root_path = Path(qfq["return_root"])
            alias = root_path.parent / "return-root-link"
            alias.symlink_to(root_path, target_is_directory=True)
            qfq["return_root"] = str(alias)
            qfq["run_dir"] = str(alias / Path(qfq["run_dir"]).name)
            policy_path = Path(env["V4_RESEARCH_RETENTION_POLICY"])
            policy = v.read(policy_path)
            policy["run_root"] = str(alias)
            save(policy_path, policy)
            env["V4_RESEARCH_RETENTION_POLICY_SHA256"] = v.sha(policy_path)
        elif variant == "qfq-row-directory":
            registry_path = Path(qfq["registry_root"]) / "registry.json"
            state = v.read(registry_path)
            row = state["tasks"][qfq["task_key"]]
            row["directory"] = qfq["run_dir"]
            save(registry_path, state)
            qfq["registry_row_sha256"] = row_sha(row)
        elif variant == "qfq-policy-root":
            policy_path = Path(env["V4_RESEARCH_RETENTION_POLICY"])
            policy = v.read(policy_path)
            other_root = Path(policy["run_root"]).parent / "different-approved-root"
            other_root.mkdir()
            policy["run_root"] = str(other_root)
            save(policy_path, policy)
            env["V4_RESEARCH_RETENTION_POLICY_SHA256"] = v.sha(policy_path)
        elif variant == "qfq-wrong-receipt-parent":
            qfq["ready_receipt"] = dict(qfq["candidate_receipt"])
        elif variant == "qfq-reused":
            qfq["already_current"] = True
        if variant != "missing-qfq":
            official = v.read(official_path); official["formula"]["natural_execution"] = qfq; save(official_path, official)
        else:
            official = v.read(official_path)
        dispatch["workload_results"][0]["source_result"]["lanes"]["A"]["formula"] = official["formula"]
    elif variant == "missing-source-proof":
        official = v.read(official_path); official["sync"].pop("provider_invocation"); save(official_path, official)
    elif variant == "source-cross-date":
        official = v.read(official_path); official["sync"]["provider_invocation"]["target_date"] = "20261122"; save(official_path, official)
    elif variant == "raw-receipt-sha":
        outcome["dated_source_receipt"]["sha256"] = "e" * 64
    elif variant == "logical-sha":
        official = v.read(official_path); official["sha256"] = "f" * 64; save(official_path, official)
    if variant in {"missing-qfq", "qfq-null-attempt", "qfq-zero-attempt", "qfq-bool-attempt",
                   "qfq-cross-task", "qfq-cross-date", "qfq-cross-run", "qfq-generation",
                   "qfq-wrong-root", "qfq-wrong-generation-child", "qfq-symlink-root",
                   "qfq-row-directory", "qfq-policy-root", "qfq-wrong-receipt-parent", "qfq-reused",
                   "missing-source-proof", "source-cross-date", "logical-sha"}:
        official = v.read(official_path)
        lane = outcome["source_result"]["lanes"]["A"]
        lane["sync"] = official.get("sync")
        lane["formula"] = official.get("formula")
        lane["sha256"] = official.get("sha256")
        outcome["dated_source_receipt"]["sha256"] = v.sha(official_path)
    if variant not in {"positive", "six-stages", "stale-date", "bad-generation"}:
        dispatch["ledger_sha256"] = v.ledger_hash(dispatch)
        save(dispatch_path, dispatch)
    if reason:
        with pytest.raises(ValueError, match=reason):
            v.verify_natural(args, env)
    else:
        result = v.verify_natural(args, env)
        assert result["acceptance"] == "NATURAL_SCHEDULE_AND_API_VERIFIED"
        assert result["api_response_file_sha256"] == result["response_sha256"]
        assert Path(result["api_response_bytes_path"]).read_bytes() == response_raw
        assert result["a_daily_logical_sha256"] != result["a_dated_receipt_file_sha256"]


def test_api_response_output_refuses_live_roots_and_existing_files(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    (live / "nested").mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    env = {"V4_RESEARCH_PANEL_RECEIPT_ROOT": str(live)}
    with pytest.raises(ValueError, match="API_RESPONSE_OUTPUT_INSIDE_LIVE_ROOT"):
        v._store_api_response(live / "nested" / "response.raw", b"raw", env)
    destination = evidence / "response.raw"
    assert v._store_api_response(destination, b"raw", env) == raw_sha(b"raw")
    assert destination.read_bytes() == b"raw"
    with pytest.raises(ValueError, match="API_RESPONSE_OUTPUT_MUST_BE_NEW"):
        v._store_api_response(destination, b"different", env)


def _loaded_main_fixture(tmp_path, monkeypatch, *, command=None, plist_launcher=None,
                         loaded_launcher=None, daemon_mode="persistent-minute",
                         manifest_launcher_sha=None, manifest_daemon_sha=None,
                         manifest_daemon_mode=None, plist_program=None,
                         loaded_program="/bin/bash"):
    app_root = tmp_path / "candidate app root with spaces"
    runtime_root = tmp_path / "runtime root with spaces"
    launcher = app_root / v.MAIN_LAUNCHER_RELATIVE
    daemon = app_root / v.MAIN_DAEMON_RELATIVE
    qfq_contract = app_root / v.QFQ_DIRECTORY_CONTRACT_RELATIVE
    launcher.parent.mkdir(parents=True)
    daemon.parent.mkdir(parents=True, exist_ok=True)
    qfq_contract.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_bytes(b"#!/bin/bash\nexec python daemon\n")
    daemon.write_bytes(b"# candidate daemon bytes\n")
    contract_source = Path(v.__file__).resolve().parents[1] / "app" / v.QFQ_DIRECTORY_CONTRACT_RELATIVE
    shutil.copyfile(contract_source, qfq_contract)
    launcher.chmod(0o755)
    daemon.chmod(0o644)
    executable = runtime_root / "venvs/v4-mac/bin/python"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"python executable fixture")
    executable.chmod(0o755)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    entries = []
    for relative, path in ((v.MAIN_LAUNCHER_RELATIVE, launcher), (v.MAIN_DAEMON_RELATIVE, daemon),
                           (v.QFQ_DIRECTORY_CONTRACT_RELATIVE, qfq_contract)):
        entries.append({
            "path": relative, "kind": "file",
            "sha256": (manifest_launcher_sha if relative == v.MAIN_LAUNCHER_RELATIVE and manifest_launcher_sha
                       else manifest_daemon_sha if relative == v.MAIN_DAEMON_RELATIVE and manifest_daemon_sha
                       else digest(path)),
            "size": path.stat().st_size,
            "mode": (manifest_daemon_mode if relative == v.MAIN_DAEMON_RELATIVE and manifest_daemon_mode
                     else format(path.stat().st_mode & 0o7777, "04o")),
        })
    release_id = "v4-main-r4-test-release"
    manifest = {"app_root": str(app_root), "release_id": release_id,
                "application_inventory": {"entries": entries}}
    manifest_path = app_root / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    manifest_sha = digest(manifest_path)
    plist_path = tmp_path / "Library/LaunchAgents/com.lexi.v4.scheduler.plist"
    plist_path.parent.mkdir(parents=True)
    expected_launcher = str(launcher)
    args_launcher = plist_launcher or expected_launcher
    plist = {"ProgramArguments": ["/bin/bash", args_launcher]}
    if plist_program is not None:
        plist["Program"] = plist_program
    plist_path.write_bytes(plistlib.dumps(plist))
    monkeypatch.setattr(v, "MAIN_PLIST", plist_path)
    environment = {
        "V4_APP_ROOT": str(app_root), "V4_RUNTIME_ROOT": str(runtime_root),
        "V4_RELEASE_ID": release_id, "V4_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V4_RELEASE_MANIFEST_SHA256": manifest_sha, "V4_DAEMON_MODE": daemon_mode,
    }
    argv_launcher = loaded_launcher or expected_launcher
    job = "\n".join([
        "gui/501/com.lexi.v4.scheduler = {",
        f"\tpath = {plist_path}",
        f"\tprogram = {loaded_program}",
        "\targuments = {",
        "\t\t/bin/bash",
        f"\t\t{argv_launcher}",
        "\t}",
        f"\tworking directory = {app_root}",
        "\tpid = 4321",
        "\tenvironment = {",
        f"\t\tV4_APP_ROOT => {app_root}",
        f"\t\tV4_RELEASE_ID => {release_id}",
        f"\t\tV4_RELEASE_MANIFEST_PATH => {manifest_path}",
        f"\t\tV4_RELEASE_MANIFEST_SHA256 => {manifest_sha}",
        f"\t\tV4_DAEMON_MODE => {daemon_mode}",
        "\t}",
        "}",
    ])
    expected_command = (str(executable) + " -X pycache_prefix=" + v.MAIN_CACHE_PREFIX
                        + " -B -S -m " + v.MAIN_DAEMON_MODULE
                        + " --data-root /tmp/research data")
    command = expected_command if command is None else command

    def fake_run(args, **kwargs):
        if args[0] == "/bin/launchctl":
            return SimpleNamespace(stdout=job, returncode=0)
        if args[0] == "/bin/ps":
            assert args[1] == "-ww"
            start = "Mon Nov 23 15:00:00 2026"
            assert len(start) == 24
            return SimpleNamespace(stdout=start + command, returncode=0)
        raise AssertionError("unexpected subprocess call")

    monkeypatch.setattr(v.subprocess, "run", fake_run)
    started = datetime(2026, 11, 25, tzinfo=timezone.utc)
    return environment, started, expected_command


def test_loaded_identity_accepts_manifest_bound_persistent_daemon_with_spaces(tmp_path, monkeypatch):
    env, started, _ = _loaded_main_fixture(tmp_path, monkeypatch)
    identity = v.loaded_identity(env, started)
    assert identity["daemon_pid"] == 4321
    assert identity["manifest_sha256"] == env["V4_RELEASE_MANIFEST_SHA256"]
    assert identity["daemon_mode"] == "persistent-minute"
    assert identity["app_root"] == env["V4_APP_ROOT"]
    assert identity["qfq_directory_contract_sha256"] == v.sha(
        Path(env["V4_APP_ROOT"]) / v.QFQ_DIRECTORY_CONTRACT_RELATIVE)


@pytest.mark.parametrize("bad_command", [
    " -c print(1)",
    " -X pycache_prefix=/tmp/other -B -S -m ops.run_v4_macos_scheduler_daemon",
    " -X pycache_prefix=/dev/null/v4-main-r4-source-only-pycache -S -B -m ops.run_v4_macos_scheduler_daemon",
    " -X pycache_prefix=/dev/null/v4-main-r4-source-only-pycache -B -S -m ops.wrong_daemon",
])
def test_loaded_identity_rejects_wrong_python_argv(tmp_path, monkeypatch, bad_command):
    executable = str(tmp_path / "runtime root with spaces/venvs/v4-mac/bin/python")
    command = executable + bad_command
    env, started, _ = _loaded_main_fixture(tmp_path, monkeypatch, command=command)
    with pytest.raises(ValueError, match="LOADED_MAIN_EXECUTOR_OR_START_MISMATCH"):
        v.loaded_identity(env, started)


def test_loaded_identity_rejects_wrong_interpreter_path(tmp_path, monkeypatch):
    command = ("/tmp/other/python -X pycache_prefix=" + v.MAIN_CACHE_PREFIX
               + " -B -S -m " + v.MAIN_DAEMON_MODULE)
    env, started, _ = _loaded_main_fixture(tmp_path, monkeypatch, command=command)
    with pytest.raises(ValueError, match="LOADED_MAIN_EXECUTOR_OR_START_MISMATCH"):
        v.loaded_identity(env, started)


@pytest.mark.parametrize("kwargs,reason", [
    ({"plist_launcher": "/tmp/other/ops/launch_v4_macos_scheduler.sh"}, "MAIN_PLIST_LAUNCHER_ARGUMENTS_MISMATCH"),
    ({"loaded_launcher": "/tmp/other/ops/launch_v4_macos_scheduler.sh"}, "LOADED_MAIN_LAUNCHER_ARGUMENTS_MISMATCH"),
    ({"loaded_program": "/bin/sh"}, "LOADED_MAIN_LAUNCHER_ARGUMENTS_MISMATCH"),
    ({"daemon_mode": "one-shot-calendar"}, "LOADED_MAIN_MANIFEST_OR_WORKDIR_DRIFT"),
    ({"manifest_launcher_sha": "0" * 64}, "LOADED_MAIN_APPLICATION_FILE_DRIFT"),
    ({"manifest_daemon_sha": "0" * 64}, "LOADED_MAIN_APPLICATION_FILE_DRIFT"),
    ({"manifest_daemon_mode": "0755"}, "LOADED_MAIN_APPLICATION_FILE_DRIFT"),
    ({"plist_program": "/bin/bash"}, "MAIN_PLIST_LAUNCHER_ARGUMENTS_MISMATCH"),
])
def test_loaded_identity_rejects_unbound_launcher_or_manifest(tmp_path, monkeypatch, kwargs, reason):
    env, started, _ = _loaded_main_fixture(tmp_path, monkeypatch, **kwargs)
    with pytest.raises(ValueError, match=reason):
        v.loaded_identity(env, started)
