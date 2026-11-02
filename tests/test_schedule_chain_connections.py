"""Cross-owner connections using real immutable stores and bounded local seams.

Run directly from an immutable candidate app (PYTHONPATH=app:app/upstreams) to
exercise its actual imports; no producer network, daemon, or existing data write.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

import pytest

from infrastructure.scheduling import dispatcher
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
from ops.consume_close_stage_completion import consume
from ops.run_stage_center_milestone import dispatch_reference, run_milestone
from stage_center.consumer import StageSelectionConsumer
from stage_center.selection import publish_selection, select_a_stage, select_hk_four_lane

DATE = "20261030"
STAGE = "STAGE_1445_1500"
SAFE = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)
NOW = datetime(2026, 10, 30, 15, 0, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def _files(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def _published(root):
    selection = root / "stage/selection"
    a = select_a_stage([dict(code="A.600000", name="fixture", first_open=10.,
        last_close=10.2, high=10.4, low=9.9, amount=1000000., bar_count=5,
        expected_rows=5, formal_eligible=True)], DATE, STAGE, "a" * 64)
    hk = select_hk_four_lane([dict(code="HK.00001", name="fixture", stage_id=STAGE,
        candidate_lanes=["LIVE_HKCONNECT_GAINER"], platform_circular_market_cap_hkd_yi=80.,
        offer_float_market_cap_hkd_yi=15., pct_chg=4., volume_ratio=1.5,
        turnover_hkd_yi=.2, turnover_rate=3.)], DATE, STAGE, "b" * 64)
    for market, value in (("A_SHARE", a), ("HK_CONNECT", hk)):
        publish_selection(selection, value, market=market)
    # Runner publication is a fixture, explicitly not a natural receipt.
    selected = StageSelectionConsumer(selection).get(DATE, STAGE)
    runner = root / "stage/receipts" / DATE / STAGE / "receipt.json"
    runner.parent.mkdir(parents=True)
    runner.write_text(json.dumps(dict(schema_version="stage_center.runner.receipt.v1",
        trade_date=DATE, stage_id=STAGE, dispatch_mode="NATURAL",
        markets={m: {"run_id": v["run_id"], "artifact_id": v["artifact_id"],
                     "selection_status": v["status"]} for m, v in selected["markets"].items()},
        **SAFE)))
    return selection, runner


def _registry(root, selection, calls, before_child=None, mutate_reference=None, legacy_full_stdout=False):
    def local_child(command, **kwargs):
        module = command[2]
        calls.append(module)
        assert module == "ops.run_stage_center_milestone"
        assert command[3:] == ["--node", "FUPAN_CLOSE_MATERIALS", "--data-root", str(root / "data"),
            "--date", DATE, "--stage-id", STAGE, "--selection-root", str(selection)]
        if before_child:
            before_child()
        value = run_milestone(node="FUPAN_CLOSE_MATERIALS", date=DATE,
            data_root=root / "data", selection_root=selection, retry_wait_seconds=0)
        output = value if legacy_full_stdout else dispatch_reference(value)
        if mutate_reference:
            mutate_reference(output)
        return subprocess.CompletedProcess(command,
            0 if value["status"] in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS"} else 1,
            json.dumps(output, ensure_ascii=False), "")
    # Acquisition/child transport seam only; registry routing, consumers,
    # publisher verification, dispatch claims and ledger are the real modules.
    return FixedExecutorRegistry(data_root=root / "data", stage_selection_root=selection,
        runner=local_child)


def _api_snapshot(root, selection):
    api_app = os.environ.get("SCHEDULE_CHAIN_API_APP")
    if api_app:
        # Final integration reads through the API role's own module, while the
        # producer/dispatcher above execute from the Main role's actual app.
        code = """import json,sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.api.v4_api.runtime_router import create_runtime_router
root,selection,date=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
app=FastAPI();app.include_router(create_runtime_router(root/'data',root/'ledger',selection,date))
with TestClient(app) as client:
    print(json.dumps(client.get('/api/v4/tasks/status',params={'date':date}).json()))
"""
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
            PYTHONPATH=str(api_app) + os.pathsep + str(Path(api_app) / "upstreams"))
        for name in ("V4_TASK_STATUS_US_LEDGER_ROOT", "V4_TASK_STATUS_EVIDENCE_ROOT", "V4_RUNTIME_GRAPH_INBOX"):
            env.pop(name, None)
        output = subprocess.run([sys.executable, "-B", "-c", code, str(root), str(selection), DATE],
            cwd=api_app, env=env, capture_output=True, text=True, timeout=15, check=True)
        return json.loads(output.stdout)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.v4_api.runtime_router import create_runtime_router
    app = FastAPI()
    app.include_router(create_runtime_router(root / "data", root / "ledger", selection, DATE))
    with TestClient(app) as client:
        return client.get("/api/v4/tasks/status", params={"date": DATE}).json()


def check_connections(root):
    from v4.manager_workbench.binding import StageFeed
    from v4.manager_workbench.config import WorkbenchConfig
    from v4.manager_workbench.inputs import NativeAdapters
    selection, runner = _published(root)
    originals = _files(root / "stage")
    calls = []
    registry = _registry(root, selection, calls)
    args = dict(trade_date=DATE, stage_id=STAGE, selection_root=selection,
        receipt_root=root / "stage/receipts", data_root=root / "data",
        ledger_root=root / "ledger", registry=registry, now=NOW)
    first = consume(**args)
    assert first["status"] == "SUCCEEDED", first
    assert calls == ["ops.run_stage_center_milestone"]
    initial = _api_snapshot(root, selection)
    initial_node = next(r for r in initial["timeline_nodes"] if r["node_id"] == "FUPAN_CLOSE_MATERIALS")
    assert initial_node["task_state"] == "READY", initial_node
    assert initial_node["binding_status"] == "BUSINESS_RECEIPT_BOUND_TO_DISPATCH_RUN"
    assert initial_node["run_id"] == first["run_id"]
    assert first["selection_run_id"] == StageSelectionConsumer(selection).get(
        DATE, STAGE, markets=("A_SHARE",))["markets"]["A_SHARE"]["run_id"]
    repeat = consume(**args)
    assert repeat["status"] == "DUPLICATE_WORKLOAD_SKIPPED"
    assert len(calls) == 1
    assert ExecutionLedger(root / "ledger").verify_receipt_chain(DATE, mode="LIVE")[0]
    receipt_path = root / "data/runtime_graph/evidence/scheduler_status" / DATE / "FUPAN_CLOSE_MATERIALS.json"
    milestone = json.loads(receipt_path.read_bytes())
    assert milestone["run_id"] == first["selection_run_id"]
    assert milestone["source_write_performed"] is False
    assert len(receipt_path.read_text()) > 2048
    first_dispatch = next(r for r in ExecutionLedger(root / "ledger").list_receipts(DATE)
        if r["run_id"] == first["run_id"])
    assert len(first_dispatch["workload_results"][0]["stdout"]) < 2048
    config = WorkbenchConfig(state_root=root / "manager", stage_root=selection)
    runs = StageFeed(NativeAdapters(config)).completed_runs(DATE)
    hk_run = StageSelectionConsumer(selection).get(DATE, STAGE, markets=("HK_CONNECT",))["run_id"]
    assert len(runs) == 1 and runs[0]["run_id"] == hk_run and len(runs[0]["input_sha256"]) == 64
    payload = _api_snapshot(root, selection)
    row = next(r for r in payload["groups"]["logical"] if r["workload_id"] == "fupan_close_materials")
    # Latest duplicate is process-level metadata; successful underlying run
    # remains independently identifiable in the immutable ledger.
    assert row["receipt_path"]
    assert row["result_code"] == "DUPLICATE_WORKLOAD_SKIPPED"
    assert _files(root / "stage") == originals
    return dict(status="PASS_ISOLATED_REAL_CONNECTIONS", first=first["status"], repeat=repeat["status"],
        selection_run_id=first["selection_run_id"], manager_run_id=hk_run,
        initial_api_task_state=initial_node["task_state"], initial_api_binding=initial_node["binding_status"],
        api_result_code=row["result_code"], source_bytes_unchanged=True,
        scope="fixture selection/runner -> completion -> dispatcher/ledger/registry -> milestone -> manager StageFeed/API; child transport seam; no acquisition/natural/deployment")


def test_real_stores_completion_milestone_manager_and_status_api(tmp_path, monkeypatch):
    if hasattr(dispatcher, "validate_release_identity"):
        monkeypatch.setattr(dispatcher, "validate_release_identity", lambda: {})
    monkeypatch.delenv("V4_STAGE_REPORT_EVIDENCE_ENABLED", raising=False)
    check_connections(tmp_path)


def test_completion_rejects_changed_runner_and_expired_event_without_claims(tmp_path):
    selection, runner = _published(tmp_path)
    payload = json.loads(runner.read_bytes())
    payload["markets"]["A_SHARE"]["run_id"] = "foreign"
    runner.write_text(json.dumps(payload))
    originals = _files(tmp_path / "stage")
    args = dict(trade_date=DATE, stage_id=STAGE, selection_root=selection,
        receipt_root=tmp_path / "stage/receipts", data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger", registry=lambda *a: (_ for _ in ()).throw(AssertionError("foreign event dispatched")), now=NOW)
    assert consume(**args)["reason"] == "COMMITTED_STAGE_COMPLETION_NOT_VERIFIED"
    assert consume(**{**args, "now": datetime(2026, 10, 31, 15, tzinfo=NOW.tzinfo)})["status"] == "EXPIRED"
    assert not (tmp_path / "ledger").exists()
    assert _files(tmp_path / "stage") == originals


@pytest.mark.parametrize("field,value", [
    ("receipt_sha256", "0" * 64), ("business_date", "20261029"),
    ("node_id", "FUPAN_REVIEW_START"), ("run_id", "foreign-run"),
    ("receipt_path", "/outside/never-read.json"),
    ("schema_version", "unknown-reference"), ("production_allowed", True),
])
def test_api_rejects_reference_identity_sha_and_outside_path(tmp_path, monkeypatch, field, value):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.v4_api.runtime_router import create_runtime_router
    if hasattr(dispatcher, "validate_release_identity"):
        monkeypatch.setattr(dispatcher, "validate_release_identity", lambda: {})
    monkeypatch.delenv("V4_STAGE_REPORT_EVIDENCE_ENABLED", raising=False)
    read_bytes = Path.read_bytes
    def no_reference_path_read(path):
        assert str(path) != "/outside/never-read.json", "stdout must not grant file-read authority"
        return read_bytes(path)
    monkeypatch.setattr(Path, "read_bytes", no_reference_path_read)
    selection, _ = _published(tmp_path)
    result = consume(trade_date=DATE, stage_id=STAGE, selection_root=selection,
        receipt_root=tmp_path / "stage/receipts", data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger", now=NOW,
        registry=_registry(tmp_path, selection, [], mutate_reference=lambda r: r.update({field: value})))
    assert result["status"] == "SUCCEEDED"
    app = FastAPI()
    app.include_router(create_runtime_router(tmp_path / "data", tmp_path / "ledger", selection, DATE))
    with TestClient(app) as client:
        payload = client.get("/api/v4/tasks/status", params={"date": DATE}).json()
    node = next(r for r in payload["timeline_nodes"] if r["node_id"] == "FUPAN_CLOSE_MATERIALS")
    assert node["task_state"] == "CANNOT_CONFIRM"
    assert node["binding_status"] != "BUSINESS_RECEIPT_BOUND_TO_DISPATCH_RUN"


def test_actual_executor_2048_cap_truncates_legacy_market_receipt(tmp_path, monkeypatch):
    if hasattr(dispatcher, "validate_release_identity"):
        monkeypatch.setattr(dispatcher, "validate_release_identity", lambda: {})
    monkeypatch.delenv("V4_STAGE_REPORT_EVIDENCE_ENABLED", raising=False)
    selection, _ = _published(tmp_path)
    result = consume(trade_date=DATE, stage_id=STAGE, selection_root=selection,
        receipt_root=tmp_path / "stage/receipts", data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger", now=NOW,
        registry=_registry(tmp_path, selection, [], legacy_full_stdout=True))
    stdout = result["workload_results"][0]["stdout"]
    assert len(stdout) > 2048 and "\n[truncated, total " in stdout[2048:]
    with pytest.raises(ValueError):
        json.loads(stdout)


def test_milestone_persists_optional_consumer_failure_before_reference(tmp_path, monkeypatch):
    from infrastructure import stage_completion_hooks
    selection, _ = _published(tmp_path)
    originals = _files(tmp_path / "stage")
    monkeypatch.setattr(stage_completion_hooks, "on_main_milestone", lambda **kw:
        dict(status="EVIDENCE_GAP", reason="ISOLATED_CONSUMER_FAILURE"))
    value = run_milestone(node="FUPAN_CLOSE_MATERIALS", date=DATE,
        data_root=tmp_path / "data", selection_root=selection, retry_wait_seconds=0)
    raw = Path(value["receipt_path"]).read_bytes()
    assert json.loads(raw) == value and value["status"] == "READY"
    assert value["report_evidence_sidecar"]["status"] == "EVIDENCE_GAP"
    assert dispatch_reference(value)["receipt_sha256"] == hashlib.sha256(raw).hexdigest()
    assert _files(tmp_path / "stage") == originals


def test_actual_milestone_cli_emits_small_reference_to_full_receipt(tmp_path, monkeypatch, capsys):
    from ops.run_stage_center_milestone import main
    monkeypatch.delenv("V4_STAGE_REPORT_EVIDENCE_ENABLED", raising=False)
    selection, _ = _published(tmp_path)
    assert main(["--node", "FUPAN_CLOSE_MATERIALS", "--date", DATE,
        "--stage-id", STAGE, "--data-root", str(tmp_path / "data"),
        "--selection-root", str(selection)]) == 0
    stdout = capsys.readouterr().out
    reference = json.loads(stdout)
    raw = Path(reference["receipt_path"]).read_bytes()
    assert len(stdout) < 2048 and len(raw) > 2048
    assert reference["schema_version"] == "v4.stage_milestone_dispatch_reference.v1"
    assert reference["receipt_sha256"] == hashlib.sha256(raw).hexdigest()
    assert reference["run_id"] == json.loads(raw)["run_id"]


@pytest.mark.parametrize("matches", [True, False])
def test_legacy_full_stdout_still_requires_exact_receipt(tmp_path, matches):
    from domains.task_status import build_task_status
    from infrastructure.scheduling.catalog import load_workload_catalog
    root = tmp_path / "data"
    path = root / "runtime_graph/evidence/scheduler_status" / DATE / "FUPAN_CLOSE_MATERIALS.json"
    path.parent.mkdir(parents=True)
    receipt = dict(schema_version="v3_5_stage_center_milestone_receipt.v1",
        node_id="FUPAN_CLOSE_MATERIALS", business_date=DATE, run_id="legacy-stage-run",
        status="READY", **SAFE)
    path.write_text(json.dumps(receipt))
    output = dict(receipt)
    if not matches:
        output["run_id"] = "foreign-run"
    ledger = ExecutionLedger(tmp_path / "ledger")
    ledger.write_receipt("receipts/live/20261030/1500/legacy.dispatch-receipt.json",
        dict(run_id="legacy", business_date=DATE, scheduled_date=DATE, target_date=DATE,
            slot="1500", mode="LIVE", status="SUCCEEDED", finished_at="2026-10-30T07:00:10Z",
            selected_workload_ids=["fupan_close_materials"], started_workload_ids=["fupan_close_materials"],
            workload_results=[dict(workload_id="fupan_close_materials", status="SUCCEEDED", stdout=json.dumps(output))], **SAFE))
    payload = build_task_status(load_workload_catalog(), ledger, DATE, data_root=root)
    node = next(r for r in payload["timeline_nodes"] if r["node_id"] == "FUPAN_CLOSE_MATERIALS")
    assert node["task_state"] == ("READY" if matches else "CANNOT_CONFIRM")


def test_consumer_failure_releases_only_failed_claim_and_retry_consumes_same_run(tmp_path, monkeypatch):
    if hasattr(dispatcher, "validate_release_identity"):
        monkeypatch.setattr(dispatcher, "validate_release_identity", lambda: {})
    monkeypatch.delenv("V4_STAGE_REPORT_EVIDENCE_ENABLED", raising=False)
    selection, runner = _published(tmp_path)
    originals = _files(tmp_path / "stage")
    pointer = json.loads((selection / "selection_latest.json").read_bytes())
    path = selection / pointer["entries"][DATE + "/" + STAGE + "/A_SHARE"]["artifact_relative"]
    raw = path.read_bytes()
    calls = []
    registry = _registry(tmp_path, selection, calls,
        before_child=lambda: path.write_bytes(raw + b"fixture damage\n"))
    args = dict(trade_date=DATE, stage_id=STAGE, selection_root=selection,
        receipt_root=tmp_path / "stage/receipts", data_root=tmp_path / "data",
        ledger_root=tmp_path / "ledger", registry=registry, now=NOW)
    failed = consume(**args)
    assert failed["status"] == "FAILED" and failed["failure_class"] == "UPSTREAM_NOT_READY"
    assert not (tmp_path / "ledger/workloads/live" / DATE / "1500/fupan_close_materials.workload-claim.json").exists()
    assert not (tmp_path / "ledger/claims/live" / DATE / "1500/dispatch.claim.json").exists()
    assert runner.read_bytes()  # Original runner is still retained after consumer failure.
    path.write_bytes(raw)  # Restore this test's artificial damage; never original data.
    args["registry"] = _registry(tmp_path, selection, calls)
    recovered = consume(**args)
    assert recovered["status"] == "SUCCEEDED"
    assert recovered["selection_run_id"] == failed["selection_run_id"]
    assert len(calls) == 2
    assert ExecutionLedger(tmp_path / "ledger").verify_receipt_chain(DATE, mode="LIVE")[0]
    assert _files(tmp_path / "stage") == originals


if __name__ == "__main__":
    with TemporaryDirectory(prefix="v4-schedule-chain-") as folder:
        print(json.dumps(check_connections(Path(folder).resolve()), sort_keys=True))
