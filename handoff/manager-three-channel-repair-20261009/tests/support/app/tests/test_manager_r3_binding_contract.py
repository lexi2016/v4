"""R3 role-bound admission; synthetic files, clocks and in-memory HTTP only.

The production changes these tests guard are role-confused root validation,
unverified owner source/canary identity, and lost or overclaimed RPC failures.
No listener, live POST, collector, launchd or business state is used.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_manager_daily_dispatch_20261008 import (
    cycle, dispatch, owner_value, supervisor,
)
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS, HK
from v4.manager_research.workspace_read_control import ReadCoordinator


DATE = "20261009"
NOW = datetime(2026, 10, 9, 9, 27, tzinfo=HK)
OWNER_SCHEMA = "v4.manager_research.plan_owner_binding.v1"
REJECTION_SCHEMA = "v4.manager_research.plan_owner_rejection.v1"
OWNER_HK_SUPPLEMENT = "v3_shared_data/shared_data/hk_daily_supplement.py"


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _write_json(path, value):
    raw = _json_bytes(value)
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _source_binding(root):
    # Source files here are inert identity fixtures, never imported as owners.
    # Both inventories are calculated by the real bounded production scanner.
    # This tests the binding contract, not completeness of a Mac release.
    app = root / "worker"
    for directory in ("v4/manager_research", "infrastructure", "contracts", "domains",
                      "stage_center", "upstreams/v3_shared_data/shared_data"):
        (app / directory).mkdir(parents=True)
    for relative in (*supervisor.REQUIRED_FILES,
                     "v4/manager_research/plan_owner_dispatch.py",
                     "v4/manager_research/workspace_plan.py",
                     "v4/manager_research/workspace_plan_autorun.py",
                     "v4/manager_research/us_mapping_research.py"):
        path = app / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# SYNTHETIC SOURCE IDENTITY: " + relative + "\n")
    master = root / "master"
    master.mkdir()
    python = Path(sys.executable).absolute()
    return {"schema_version": supervisor.BINDING_SCHEMA, "enabled": False,
        "policy_status": "PROPOSAL_ONLY", "policy": "BALANCED_V1", "app_root": str(app),
        "manager_state_root": str(root / "state"), "security_master_root": str(master),
        "python": str(python), "python_resolved": str(python.resolve()),
        "python_sha256": hashlib.sha256(python.read_bytes()).hexdigest(), "priority_codes": [],
        "files": supervisor.binding_inventory(app), "research_only": True,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def _canary(root, binding, *, historical=False, explicit_owner=True):
    """Create complete synthetic response bodies, receipts and code identity."""
    target = "20261008" if historical else "20260929"
    owner_root = binding.get("plan_owner", {}).get("app_root", binding["app_root"])
    run, sha, inputs = "1" * 32, "2" * 64, "3" * 64
    evidence = {}
    for name, method, endpoint in (
        ("refresh", "POST", "/api/v4/manager/research/workspace/refresh?date=" + target),
        ("readback", "GET", "/api/v4/manager/research/workspace?date=" + target
         + ("&view=dynamic" if historical and explicit_owner else "")),
    ):
        body = {"target_trade_date": target, "input_identity": inputs,
            "plan_product": {"status": "CURRENT", "run_id": run, "sha256": sha,
                "original_owner": dispatch.OWNER, "execution_kind": "MANUAL_REFRESH"}}
        if name == "refresh":
            body.update(store_latest_matches_http_plan_product=True,
                persisted_store={"target_trade_date": target, "run_id": run,
                    "product_sha256": sha, "execution_kind": "MANUAL_REFRESH",
                    "owner": dispatch.OWNER, **FLAGS},
                workspace_plan_attempt={"execution_kind": "MANUAL_REFRESH",
                    "state": "PARTIAL", "run_id": run, "input_identity": inputs},
                safety=dict(FLAGS))
        body_ref = _write_json(root / (name + "-body.json"), body)
        body_ref["bytes"] = len(_json_bytes(body))
        evidence[name] = _write_json(root / (name + "-receipt.json"), {
            "http_status": 200, "content_type": "application/json",
            "request": {"method": method, "url": "http://127.0.0.1:8873" + endpoint},
            "response": body_ref, "readback": body,
        })
    canary = {"schema_version": supervisor.PLAN_CANARY_SCHEMA,
        "status": supervisor.PLAN_CANARY_STATUS, "app_root": binding["app_root"],
        "manager_state_root": binding["manager_state_root"], "policy_status": "PROPOSAL_ONLY",
        "candidate_binding_app_root": binding["app_root"], "owner_execution_app_root": owner_root,
        "scope": supervisor.PLAN_CANARY_HISTORICAL_SCOPE if historical else supervisor.PLAN_CANARY_NEXT_SCOPE,
        "plan_material_refresh_only": True, "announcement_collection_enabled": False,
        "announcement_network_requests": 0, "execution_mode": "HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK",
        "hook_executed": False, "research_only": True,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "target_trade_date": target, "run_id": run, "product_sha256": sha,
        "input_identity": inputs, "execution_kind": "MANUAL_REFRESH", "owner": dispatch.OWNER,
        "owner_attempt_state": "PARTIAL", "formal_recommendation_count": 0,
        "owner_evidence": evidence}
    if explicit_owner:
        canary["owner_source_inventory_sha256"] = hashlib.sha256(
            _json_bytes(binding["plan_owner"]["files"])).hexdigest()
    binding["plan_activation_receipt"] = _write_json(root / "canary.json", canary)
    return canary


def _fixture(tmp_path, monkeypatch, *, daily=False, historical=False, dual=True):
    binding = _source_binding(tmp_path)
    worker = Path(binding["app_root"])
    owner_root = tmp_path / "api-owner" if dual else worker
    if dual:
        shutil.copytree(worker, owner_root)
        supplement = owner_root / OWNER_HK_SUPPLEMENT
        supplement.parent.mkdir(parents=True)
        supplement.write_text("# SYNTHETIC API HK SUPPLEMENT SOURCE IDENTITY\n")
    binding.update(enabled=True, plan_material_refresh_only=True,
        announcement_collection_enabled=False,
        plan_material_refresh={"enabled": True, "start_local": "16:00", "end_local": "23:00",
            "max_attempts_per_target_date": 3, "retry_backoff_seconds": 600, "status": "PROPOSAL_ONLY"},
        preopen_plan={"enabled": True, "lead_seconds": 180, "status": "PROPOSAL_ONLY"},
        morning_plan={"enabled": False, "interval_seconds": 300, "status": "PROPOSAL_ONLY"},
        daily_automation=supervisor.daily_automation_config({"enabled": daily}))
    if dual:
        binding["plan_owner"] = {"schema_version": OWNER_SCHEMA,
            "owner": dispatch.OWNER, "app_root": str(owner_root),
            "files": supervisor.binding_inventory(owner_root)}
    canary = _canary(tmp_path, binding, historical=historical, explicit_owner=dual)
    path = tmp_path / "binding.json"
    sha = _write_json(path, binding)["sha256"]
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(path))
    monkeypatch.setattr(dispatch, "APP_ROOT", owner_root)
    monkeypatch.setattr(dispatch, "clock_now", lambda: NOW)
    events = []

    def refresh(date, **kwargs):
        events.append(("plan", date, kwargs))
        return owner_value(date=date, now=kwargs["now"], kind=kwargs["execution_kind"])

    service = SimpleNamespace(store=ManagerResearchStore(Path(binding["manager_state_root"])),
        _workspace_security_master_root=Path(binding["security_master_root"]),
        _workspace_us_market_reader=None, _existing_research_source=object(),
        _workspace_reads=ReadCoordinator(), refresh_workspace_plan=refresh)
    return SimpleNamespace(binding=binding, path=path, sha=sha, worker=worker,
        owner_root=owner_root, canary=canary, service=service, events=events, root=tmp_path)


def _client(service):
    from apps.api.v35_api.manager_research_router import create_manager_research_router
    app = FastAPI()
    app.include_router(create_manager_research_router(service))
    return TestClient(app)


def _memory_transport(monkeypatch, client, *, timeout=False, body_override=None):
    calls = []
    class Connection:
        def __init__(self, host, port, **kwargs):
            assert (host, port) == ("127.0.0.1", 8873)
        def request(self, method, path, **kwargs):
            calls.append((method, path))
            if timeout:
                raise TimeoutError("synthetic unknown remote completion")
            self.response = client.post(path, content=b"")
        def getresponse(self):
            response = self.response
            return SimpleNamespace(status=response.status_code,
                getheader=lambda key, default="": response.headers.get(key, default),
                read=lambda maximum: (response.content if body_override is None
                    else _json_bytes(body_override))[:maximum])
        def close(self):
            pass
    monkeypatch.setattr(dispatch.http.client, "HTTPConnection", Connection)
    return calls


def _scheduler_loader():
    """Execute the unchanged loader closure, excluding unrelated Stage imports.

    The actual daemon loader and its five stdlib dependencies are extracted
    verbatim from the checked-in AST; none of its validation is mocked.
    """
    path = Path(__file__).resolve().parents[1] / "ops/run_v35_macos_scheduler_daemon.py"
    tree = ast.parse(path.read_bytes())
    selected = []
    names = {"_load_announcement_binding", "_exact_path", "_sha256_file",
             "_read_bounded_bytes", "_unique_json_object", "DaemonConfigurationError"}
    for node in tree.body:
        if isinstance(node, ast.Import) or (isinstance(node, ast.ImportFrom) and node.module != "ops"):
            selected.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                and target.id.startswith("ANNOUNCEMENT_") for target in node.targets):
            selected.append(node)
    namespace = {"__file__": str(path)}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace["_load_announcement_binding"]


@pytest.mark.parametrize("daily", [False, True])
def test_one_binding_passes_unchanged_scheduler_worker_and_distinct_api_owner(tmp_path, monkeypatch, daily):
    f = _fixture(tmp_path, monkeypatch, daily=daily)
    assert OWNER_HK_SUPPLEMENT not in f.binding["files"]
    assert f.binding["plan_owner"]["files"][OWNER_HK_SUPPLEMENT] == hashlib.sha256(
        (f.owner_root / OWNER_HK_SUPPLEMENT).read_bytes()).hexdigest()
    environment = {"V4_MANAGER_ANNOUNCEMENT_BINDING": str(f.path),
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": str(f.worker),
        "V4_MANAGER_ANNOUNCEMENT_PYTHON": f.binding["python"],
        "V4_MANAGER_ANNOUNCEMENT_PYTHON_SHA256": f.binding["python_sha256"],
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": f.binding["files"]["ops/run_manager_announcement_cycle.py"],
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": f.binding["plan_activation_receipt"]["sha256"]}
    assert _scheduler_loader()(environment)["binding_sha256"] == f.sha
    with _client(f.service) as client:
        calls = _memory_transport(monkeypatch, client)
        result = (dispatch.request_bound_daily_cycle if daily else dispatch.request_bound_plan_cycle)(f.path, DATE)
    assert result["status"] == "PARTIAL"  # Independent US reader remains absent.
    assert len(calls) == len(f.events) == 1
    assert supervisor.validate_binding(f.binding, f.worker) is f.binding
    assert result["binding_sha256"] == f.sha
    assert result["parent_trigger_receipt"]["owner_readback_status"] == "VERIFIED"
    assert result["parent_trigger_receipt"]["owner_run_id"] == result["plan_result"]["run_id"]
    assert all(result[key] is value for key, value in FLAGS.items())


@pytest.mark.parametrize("daily", [False, True])
@pytest.mark.parametrize("damage,reason", [
    ("sha", "PLAN_OWNER_BINDING_SHA_MISMATCH"),
    ("root", "PLAN_OWNER_BINDING_API_ROOT_MISMATCH"),
    ("disabled", "PLAN_OWNER_DAILY_BINDING_DISABLED"),
    ("owner_inventory", "PLAN_OWNER_BINDING_CLOSED_INVENTORY_MISMATCH"),
])
def test_admission_rejects_before_either_owner_and_returns_bounded_reason(tmp_path, monkeypatch, daily, damage, reason):
    f = _fixture(tmp_path, monkeypatch, daily=daily)
    f.service.refresh_us_mapping_research = lambda *a, **k: pytest.fail("gate invoked US owner")
    if damage == "sha":
        f.sha = "f" * 64
    elif damage == "root":
        monkeypatch.setattr(dispatch, "APP_ROOT", f.worker)
    elif damage == "disabled":
        f.binding["enabled"] = False
        f.sha = _write_json(f.path, f.binding)["sha256"]
        if not daily:
            reason = "PLAN_OWNER_BINDING_DISABLED"
    else:
        (f.owner_root / "v4/manager_research/store.py").write_text("# changed owner source\n")
    with _client(f.service) as client:
        endpoint = "daily-cycle" if daily else "scheduled-cycle"
        response = client.post("/api/v4/manager/research/workspace/" + endpoint,
            params={"date": DATE, "binding_sha256": f.sha})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert isinstance(detail, dict), "the API collapsed the admission failure into an opaque string"
    assert detail["schema_version"] == REJECTION_SCHEMA
    assert detail["reason"] == reason
    assert detail["owner_execution_status"] == "OWNER_NOT_CALLED"
    assert detail["binding_sha256"] == f.sha
    assert f.events == []
    assert list(f.service.store.root.rglob("*.json")) == []


def test_gate_reason_survives_rpc_and_transport_timeout_does_not_claim_owner_not_called(tmp_path, monkeypatch):
    f = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(dispatch, "APP_ROOT", f.worker)
    with _client(f.service) as client:
        calls = _memory_transport(monkeypatch, client)
        result = dispatch.request_bound_plan_cycle(f.path, DATE)
        assert len(calls) == 1
        assert result["parent_trigger_receipt"]["failure_code"] == "PLAN_OWNER_BINDING_API_ROOT_MISMATCH"
        assert result["owner_execution_status"] == "OWNER_NOT_CALLED"
        assert result["failure_stage"] == "ADMISSION"
        calls = _memory_transport(monkeypatch, client, timeout=True)
        result = dispatch.request_bound_plan_cycle(f.path, DATE)
    assert len(calls) == 1
    assert result["owner_execution_status"] == "CANNOT_CONFIRM"
    assert result["failure_stage"] == "TRANSPORT"
    assert f.events == []


def test_legacy_same_root_remains_strictly_supported(tmp_path, monkeypatch):
    f = _fixture(tmp_path, monkeypatch, dual=False)
    result = dispatch.execute_bound_plan_cycle(f.service, DATE, f.sha)
    assert result["plan_result"]["owner_attempt_state"] == "SUCCEEDED"
    assert len(f.events) == 1


@pytest.mark.parametrize("damage", ["worker_file", "owner_file", "canary_root", "canary_inventory", "response_sha"])
def test_dual_root_inventory_and_fresh_owner_canary_are_real_checks(tmp_path, monkeypatch, damage):
    f = _fixture(tmp_path, monkeypatch)
    if damage in {"worker_file", "owner_file"}:
        root = f.worker if damage == "worker_file" else f.owner_root
        (root / "v4/manager_research/new_unlisted_source.py").write_text("# extra source\n")
    elif damage == "response_sha":
        receipt = json.loads(Path(f.canary["owner_evidence"]["readback"]["path"]).read_bytes())
        Path(receipt["response"]["path"]).write_bytes(b"{}")
    else:
        if damage == "canary_root":
            f.canary["owner_execution_app_root"] = str(f.worker)
        else:
            f.canary["owner_source_inventory_sha256"] = "0" * 64
        f.binding["plan_activation_receipt"] = _write_json(f.root / "canary.json", f.canary)
    with pytest.raises((ValueError, OSError)):
        supervisor.validate_binding(f.binding, f.worker)
    assert f.events == []


def test_explicit_owner_historical_canary_requires_dynamic_readback(tmp_path, monkeypatch):
    f = _fixture(tmp_path, monkeypatch, historical=True)
    assert supervisor.validate_binding(f.binding, f.worker) is f.binding
    reference = f.canary["owner_evidence"]["readback"]
    receipt = json.loads(Path(reference["path"]).read_bytes())
    receipt["request"]["url"] = receipt["request"]["url"].replace("&view=dynamic", "")
    f.canary["owner_evidence"]["readback"] = _write_json(Path(reference["path"]), receipt)
    f.binding["plan_activation_receipt"] = _write_json(f.root / "canary.json", f.canary)
    with pytest.raises(ValueError, match="PLAN_REFRESH_CANARY_HTTP_EVIDENCE_INVALID"):
        supervisor.validate_binding(f.binding, f.worker)


def test_renderer_generates_reviewable_dual_root_without_dropping_inventory(tmp_path, monkeypatch):
    f = _fixture(tmp_path, monkeypatch)
    from ops.render_manager_announcement_binding import main
    output = tmp_path / "rendered.json"
    main(["--app-root", str(f.worker), "--plan-owner-app-root", str(f.owner_root),
        "--manager-state-root", f.binding["manager_state_root"],
        "--security-master-root", f.binding["security_master_root"],
        "--python", f.binding["python"], "--output", str(output), "--enabled",
        "--plan-material-refresh-only", "--plan-activation-receipt", f.binding["plan_activation_receipt"]["path"]])
    rendered = json.loads(output.read_bytes())
    assert rendered["schema_version"] == supervisor.BINDING_SCHEMA
    assert rendered["plan_owner"] == f.binding["plan_owner"]
    assert supervisor.validate_binding(rendered, f.worker) is rendered
    assert f.events == []


def test_unknown_execution_error_is_not_admission_or_secret_text(tmp_path, monkeypatch):
    f = _fixture(tmp_path, monkeypatch)
    def fail(*a, **k):
        raise ValueError("PLAN_OWNER_BINDING_SHA_MISMATCH")
    monkeypatch.setattr(dispatch, "_execute_serialized_cycle", fail)
    with _client(f.service) as client:
        calls = _memory_transport(monkeypatch, client)
        result = dispatch.request_bound_plan_cycle(f.path, DATE)
    assert len(calls) == 1
    assert result["owner_execution_status"] == "CANNOT_CONFIRM"
    assert result["parent_trigger_receipt"]["failure_code"] == "SCHEDULED_WORKSPACE_OWNER_FAILED"
    assert "PLAN_OWNER_BINDING_SHA_MISMATCH" not in json.dumps(result)


def test_cycle_missing_binding_reports_local_admission_without_network(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(dispatch.http.client, "HTTPConnection", lambda *a, **k: pytest.fail("unexpected transport"))
    assert cycle.main(["--binding", str(missing), "--dry-run"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["owner_execution_status"] == "OWNER_NOT_CALLED"
    assert result["failure_stage"] == "ADMISSION"
    assert result["network_requests"] == result["state_writes"] == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("damage", ["sha", "date", "unknown", "reason_object", "extra_field", "unsafe"])
def test_unverified_409_cannot_claim_owner_was_not_called(tmp_path, monkeypatch, damage):
    f = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(dispatch, "APP_ROOT", f.worker)
    detail = {"schema_version": REJECTION_SCHEMA, "status": "GATE_REJECTED", "owner": dispatch.OWNER,
        "reason": "PLAN_OWNER_BINDING_API_ROOT_MISMATCH", "failure_stage": "ADMISSION",
        "owner_execution_status": "OWNER_NOT_CALLED", "target_trade_date": DATE,
        "binding_sha256": f.sha, **FLAGS}
    if damage == "sha":
        detail["binding_sha256"] = "f" * 64
    elif damage == "date":
        detail["target_trade_date"] = "20261008"
    elif damage == "unknown":
        detail["reason"] = "PRIVATE_UPPERCASE_DETAIL"
    elif damage == "reason_object":
        detail["reason"] = {"unexpected": True}
    elif damage == "extra_field":
        detail["unbounded_error"] = "private details"
    else:
        detail["orders_sent"] = True
    with _client(f.service) as client:
        _memory_transport(monkeypatch, client, body_override={"detail": detail})
        result = dispatch.request_bound_plan_cycle(f.path, DATE)
    assert result["owner_execution_status"] == "CANNOT_CONFIRM"
    assert "PRIVATE_UPPERCASE_DETAIL" not in json.dumps(result)
    assert "private details" not in json.dumps(result)


@pytest.mark.parametrize("disabled", [False, True])
def test_worker_distinguishes_disabled_from_not_due_without_business_io(tmp_path, monkeypatch, capsys, disabled):
    f = _fixture(tmp_path, monkeypatch)
    f.binding["enabled"] = not disabled
    _write_json(f.path, f.binding)
    monkeypatch.setattr(cycle, "APP_ROOT", f.worker)
    monkeypatch.chdir(f.worker)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.replace(hour=11, minute=0)
    monkeypatch.setattr(cycle, "datetime", Clock)
    monkeypatch.setattr(dispatch.http.client, "HTTPConnection", lambda *a, **k: pytest.fail("unexpected transport"))
    assert cycle.main(["--binding", str(f.path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == ("DISABLED" if disabled else "NOT_DUE")
    assert result["owner_execution_status"] == "OWNER_NOT_CALLED"
    assert result["network_requests"] == result["state_writes"] == 0
    assert list(f.service.store.root.rglob("*.json")) == []


@pytest.mark.parametrize("kind,outcome", [("input", "INPUT_NOT_READY"),
    ("error", "OWNER_FAILED"), ("timeout", "CANNOT_CONFIRM")])
def test_dispatched_owner_outcome_preserves_input_gaps_and_timeout_uncertainty(tmp_path, monkeypatch, kind, outcome):
    f = _fixture(tmp_path, monkeypatch)
    def downstream(service, binding, identity, **kwargs):
        if kind == "error":
            raise ValueError("PRIVATE_UPPERCASE_DETAIL")
        if kind == "timeout":
            raise TimeoutError("synthetic uncertain completion")
        return {"status": "FAILED", "branch": identity["branch"],
            "plan_result": {"status": "CANNOT_CONFIRM", "target_trade_date": DATE,
                "failure_reasons": ["HK_UNIVERSE_V2_ARTIFACT_MISSING"]}}
    monkeypatch.setattr(dispatch, "_run_owner_branches", downstream)
    with _client(f.service) as client:
        _memory_transport(monkeypatch, client)
        result = dispatch.request_bound_plan_cycle(f.path, DATE)
    assert result["status"] == "FAILED"
    assert result["dispatch_outcome"] == outcome
    assert "PRIVATE_UPPERCASE_DETAIL" not in json.dumps(result)
    if kind == "input":
        assert result["plan_result"]["status"] == "CANNOT_CONFIRM"
        assert result["plan_result"]["failure_reasons"] == ["HK_UNIVERSE_V2_ARTIFACT_MISSING"]
    assert result["plan_result"].get("run_id") is None
    assert result["plan_result"].get("product_sha256") is None
    assert result["parent_trigger_receipt"]["owner_readback_status"] == "UNVERIFIED"


def test_worker_call_exception_does_not_publish_arbitrary_uppercase_text(tmp_path, monkeypatch, capsys):
    f = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(cycle, "APP_ROOT", f.worker)
    monkeypatch.chdir(f.worker)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(cycle, "datetime", Clock)
    def fail(*a, **k):
        raise ValueError("PRIVATE_UPPERCASE_DETAIL")
    monkeypatch.setattr(dispatch, "request_bound_plan_cycle", fail)
    assert cycle.main(["--binding", str(f.path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert "PRIVATE_UPPERCASE_DETAIL" not in json.dumps(result)
    assert result["owner_execution_status"] == "CANNOT_CONFIRM"


@pytest.mark.parametrize("relative", ["v4/manager_research/plan_owner_dispatch.py",
                                     "v4/manager_research/workspace_plan_autorun.py"])
def test_owner_inventory_cannot_omit_required_owner_entry_even_with_matching_pins(tmp_path, monkeypatch, relative):
    f = _fixture(tmp_path, monkeypatch)
    (f.owner_root / relative).unlink()
    del f.binding["plan_owner"]["files"][relative]
    # Re-pin all declarative metadata: a closed inventory still needs its
    # mandatory owner entry points, not only agreement with surviving files.
    f.canary["owner_source_inventory_sha256"] = hashlib.sha256(
        _json_bytes(f.binding["plan_owner"]["files"])).hexdigest()
    f.binding["plan_activation_receipt"] = _write_json(f.root / "canary.json", f.canary)
    with pytest.raises(ValueError, match="PLAN_OWNER_BINDING_INVENTORY_INVALID"):
        supervisor.validate_binding(f.binding, f.worker)
    assert f.events == []


@pytest.mark.parametrize("remove_pin", [False, True])
def test_nested_hk_owner_consumer_is_required_even_if_file_and_pin_are_removed(tmp_path, monkeypatch, remove_pin):
    f = _fixture(tmp_path, monkeypatch)
    (f.owner_root / OWNER_HK_SUPPLEMENT).unlink()
    if remove_pin:
        f.binding["plan_owner"]["files"].pop(OWNER_HK_SUPPLEMENT, None)
    f.canary["owner_source_inventory_sha256"] = hashlib.sha256(
        _json_bytes(f.binding["plan_owner"]["files"])).hexdigest()
    f.binding["plan_activation_receipt"] = _write_json(f.root / "canary.json", f.canary)
    reason = ("PLAN_OWNER_BINDING_INVENTORY_INVALID" if remove_pin
        else "PLAN_OWNER_BINDING_CLOSED_INVENTORY_MISMATCH")
    with pytest.raises(ValueError, match=reason):
        supervisor.validate_binding(f.binding, f.worker)
    assert f.events == []


@pytest.mark.parametrize("field", ["status", "owner_attempt_state"])
def test_malformed_200_owner_receipt_is_bounded_unknown_completion(tmp_path, monkeypatch, field):
    f = _fixture(tmp_path, monkeypatch)
    body = dispatch.execute_bound_plan_cycle(f.service, DATE, f.sha)
    body["plan_result"][field] = {"invalid": True}
    with _client(f.service) as client:
        _memory_transport(monkeypatch, client, body_override=body)
        result = dispatch.request_bound_plan_cycle(f.path, DATE)
    assert result["status"] == "FAILED"
    assert result["owner_execution_status"] == "CANNOT_CONFIRM"
    assert result["parent_trigger_receipt"]["failure_code"] == "PLAN_OWNER_RPC_PARENT_TRIGGER_READBACK_INVALID"


@pytest.mark.parametrize("error_type,message,outcome,code", [
    (TimeoutError, "synthetic completion is unknown", "CANNOT_CONFIRM", "PLAN_OWNER_EXECUTION_TIMEOUT"),
    (TimeoutError, "SYNTHETIC_PRIVATE_UPPERCASE_DETAIL", "CANNOT_CONFIRM", "PLAN_OWNER_EXECUTION_TIMEOUT"),
    (ValueError, "SYNTHETIC_PRIVATE_UPPERCASE_DETAIL", "OWNER_FAILED", "PLAN_OWNER_EXECUTION_FAILED"),
    (ValueError, "PLAN_TWO_COMPLETED_HK_SESSIONS_UNAVAILABLE", "OWNER_FAILED", "PLAN_OWNER_EXECUTION_FAILED"),
])
def test_real_preopen_wrapper_preserves_exception_category_without_private_detail(
        tmp_path, monkeypatch, error_type, message, outcome, code):
    f = _fixture(tmp_path, monkeypatch)

    def failed_owner(date, **kwargs):
        f.events.append(("plan", date, kwargs))
        raise error_type(message)

    f.service.refresh_workspace_plan = failed_owner
    # Keep the real branch selector and PREOPEN safe wrapper. Only the final
    # original owner method raises; bypassing _run_owner_branches hid this bug.
    with _client(f.service) as client:
        _memory_transport(monkeypatch, client)
        result = dispatch.request_bound_plan_cycle(f.path, DATE)
    assert len(f.events) == 1
    assert result["status"] == "FAILED"
    assert result["dispatch_outcome"] == outcome
    assert result["plan_result"]["failure_code"] == code
    assert code in result["plan_result"]["failure_reasons"]
    assert "SYNTHETIC_PRIVATE_UPPERCASE_DETAIL" not in json.dumps(result)
    if message == "PLAN_TWO_COMPLETED_HK_SESSIONS_UNAVAILABLE":
        assert message in result["plan_result"]["failure_reasons"]
    assert result["plan_result"].get("run_id") is None
    assert result["plan_result"].get("product_sha256") is None
    assert result["parent_trigger_receipt"]["owner_readback_status"] == "UNVERIFIED"


def test_real_preopen_wrapper_retains_original_partial_input_gap(tmp_path, monkeypatch):
    f = _fixture(tmp_path, monkeypatch)

    def partial_owner(date, **kwargs):
        f.events.append(("plan", date, kwargs))
        return owner_value(date=date, now=kwargs["now"], kind=kwargs["execution_kind"], state="PARTIAL")

    f.service.refresh_workspace_plan = partial_owner
    with _client(f.service) as client:
        _memory_transport(monkeypatch, client)
        result = dispatch.request_bound_plan_cycle(f.path, DATE)
    assert len(f.events) == 1
    assert result["status"] == "PARTIAL"
    assert result["dispatch_outcome"] == "OWNER_RESULT"
    assert result["plan_result"]["owner_attempt_state"] == "PARTIAL"
    assert result["plan_result"]["failure_reasons"] == ["SYNTHETIC_INDEPENDENT_LANE_GAP"]
    assert result["parent_trigger_receipt"]["owner_readback_status"] == "VERIFIED"
