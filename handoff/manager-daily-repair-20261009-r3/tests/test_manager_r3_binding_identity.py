"""R3 binding contracts using synthetic roots/receipts and temporary state only.

No fixture calls a live HTTP endpoint, executes its synthetic source files,
collects research data, or reads an actual plan/state directory.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


_supervisor_name = "infrastructure.scheduling.manager_announcement_supervisor"
supervisor = sys.modules.get(_supervisor_name)
if supervisor is None:
    _spec = importlib.util.spec_from_file_location(
        _supervisor_name, Path(__file__).resolve().parents[1]
        / "infrastructure/scheduling/manager_announcement_supervisor.py")
    supervisor = importlib.util.module_from_spec(_spec)
    sys.modules[_supervisor_name] = supervisor
    _spec.loader.exec_module(supervisor)

from ops import run_manager_announcement_cycle as cycle
from v4.manager_research import plan_owner_dispatch as dispatch
from v4.manager_research import workspace
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS, HK
from v4.manager_research.workspace_read_control import ReadCoordinator


DATE = "20261009"
NOW = datetime(2026, 10, 9, 9, 27, tzinfo=HK)
OWNER = "ManagerResearchJobService.refresh_workspace_plan"
IDENTITY_SCHEMA = "v4.manager_research.plan_owner_identity.v1"
API_ENTRY_FILES = (
    "apps/api/v35_api/app.py",
    "apps/api/v35_api/manager_workbench_router.py",
    "apps/api/v35_api/preselection_router.py",
    "apps/api/v35_api/preselection_service.py",
    "v3_shared_data/shared_data/hk_daily_supplement.py",
)


def _json_file(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _source_root(path):
    """A closed inventory of inert fixture bytes; never imported or executed."""
    for root in ("v4/manager_research", "infrastructure", "contracts", "domains",
                 "stage_center", "upstreams/v3_shared_data/shared_data"):
        (path / root).mkdir(parents=True, exist_ok=True)
    for rel in set(supervisor.REQUIRED_FILES) | set(supervisor.PLAN_OWNER_SOURCE_FILES) | set(API_ENTRY_FILES) | {
        "v4/manager_research/plan_owner_dispatch.py",
        "v4/manager_research/workspace_projection.py",
    }:
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# inert synthetic binding fixture: " + path.name + "/" + rel + "\n", encoding="utf-8")
    return path


def _owner_inventory(app):
    # The expected contract extends the existing closed inventory with the
    # actual API injection entry point and its protected Issue32 neighbours.
    paths = set(API_ENTRY_FILES) | {str(path.relative_to(app))
        for path in (app / "v3_shared_data").rglob("*")
        if path.is_file() and path.suffix in {".py", ".json"}}
    return {**supervisor.binding_inventory(app), **{
        rel: hashlib.sha256((app / rel).read_bytes()).hexdigest() for rel in paths}}


def _owner_identity(app):
    return {"schema_version": IDENTITY_SCHEMA, "owner": OWNER,
            "app_root": str(app), "files": _owner_inventory(app)}


def _identity_sha(identity):
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def _canary(root, worker, owner, state, *, legacy_migration=False):
    product = {"status": "CURRENT", "run_id": "1" * 32, "sha256": "2" * 64,
               "original_owner": OWNER, "execution_kind": "MANUAL_REFRESH"}
    readback = {
        "target_trade_date": "20261008", "store_latest_matches_http_plan_product": True,
        "plan_product": product,
        "persisted_store": {"target_trade_date": "20261008", "run_id": "1" * 32,
            "product_sha256": "2" * 64, "execution_kind": "MANUAL_REFRESH", "owner": OWNER, **FLAGS},
        "workspace_plan_attempt": {"state": "SUCCEEDED", "execution_kind": "MANUAL_REFRESH"},
        "safety": dict(FLAGS),
    }
    evidence = {}
    for name, method, endpoint in (
        ("refresh", "POST", "/api/v4/manager/research/workspace/refresh?date=20261008"),
        ("readback", "GET", "/api/v4/manager/research/workspace?date=20261008"),
    ):
        body = _json_file(root / (name + "-body.json"), readback)
        evidence[name] = _json_file(root / (name + "-receipt.json"), {
            "http_status": 200, "content_type": "application/json",
            "request": {"method": method, "url": "http://127.0.0.1:8873" + endpoint},
            "response": {**body, "bytes": Path(body["path"]).stat().st_size},
            "readback": readback,
        })
    value = {
        "schema_version": supervisor.PLAN_CANARY_SCHEMA,
        "status": supervisor.PLAN_CANARY_STATUS,
        "scope": supervisor.PLAN_CANARY_NEXT_SCOPE,
        "app_root": str(worker), "candidate_binding_app_root": str(worker),
        "owner_execution_app_root": str(owner), "manager_state_root": str(state),
        "policy_status": "PROPOSAL_ONLY", "plan_material_refresh_only": True,
        "execution_mode": "HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK",
        "hook_executed": False, "announcement_collection_enabled": False,
        "announcement_network_requests": 0, "research_only": True,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "target_trade_date": "20261008", "run_id": "1" * 32,
        "product_sha256": "2" * 64, "input_identity": "3" * 64,
        "execution_kind": "MANUAL_REFRESH", "owner": OWNER,
        "formal_recommendation_count": 0, "owner_attempt_state": "SUCCEEDED",
        "owner_evidence": evidence,
    }
    if worker != owner and not legacy_migration:
        value["owner_binding_identity_sha256"] = _identity_sha(_owner_identity(owner))
    elif worker != owner:
        value["source_migration_receipt"] = _json_file(root / "migration.json", {
            "schema_version": "manager_daily_chain.plan_owner_source_migration.v1",
            "source_app_root": str(owner), "candidate_app_root": str(worker),
            "manager_state_root": str(state), "owner": OWNER,
            "owner_sources": {rel: hashlib.sha256((owner / rel).read_bytes()).hexdigest()
                              for rel in supervisor.PLAN_OWNER_SOURCE_FILES},
        })
    return _json_file(root / "canary.json", value)


def synthetic_binding(tmp_path, *, dual=True, enabled=True):
    worker = _source_root(tmp_path / "worker-app")
    owner = _source_root(tmp_path / "api-app") if dual else worker
    state, master = tmp_path / "state", tmp_path / "master"
    state.mkdir(); master.mkdir()
    interpreter = Path(sys.executable)
    value = {
        "schema_version": supervisor.BINDING_SCHEMA, "enabled": enabled,
        "policy_status": "PROPOSAL_ONLY", "policy": "BALANCED_V1",
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "research_only": True, "app_root": str(worker),
        "manager_state_root": str(state), "security_master_root": str(master),
        "python": str(interpreter), "python_resolved": str(interpreter.resolve()),
        "python_sha256": hashlib.sha256(interpreter.read_bytes()).hexdigest(),
        "priority_codes": [], "files": supervisor.binding_inventory(worker),
        "plan_material_refresh_only": True, "announcement_collection_enabled": False,
        "preopen_plan": {"enabled": True, "lead_seconds": 180, "status": "PROPOSAL_ONLY"},
        "morning_plan": {"enabled": True, "interval_seconds": 300, "status": "PROPOSAL_ONLY"},
        "plan_material_refresh": {"enabled": True, "start_local": "16:00", "end_local": "23:00",
            "max_attempts_per_target_date": 3, "retry_backoff_seconds": 600,
            "status": "PROPOSAL_ONLY"},
        "daily_automation": {"enabled": True,
            "same_day_catchup_slots_local": ["10:00", "12:30", "15:45", "18:30", "22:30"],
            "us_mapping_budget_seconds": 5, "max_attempts_per_target_date": 5,
            "status": "PROPOSAL_ONLY"},
        "plan_activation_receipt": _canary(tmp_path / "evidence", worker, owner, state),
    }
    if dual:
        value["plan_owner_binding"] = _owner_identity(owner)
    return value, worker, owner


class SyntheticOwner:
    def __init__(self, binding):
        self.store = ManagerResearchStore(Path(binding["manager_state_root"]))
        self._workspace_security_master_root = Path(binding["security_master_root"])
        self._existing_research_source = object()
        self._workspace_us_market_reader = None
        self._workspace_reads = ReadCoordinator()
        self.owner_calls = []
        self.writes = []
        original_write = self.store._write_atomic
        def write(path, value):
            self.writes.append(path)
            return original_write(path, value)
        self.store._write_atomic = write

    def refresh_workspace_plan(self, date, **kwargs):
        self.owner_calls.append((date, kwargs))
        now, kind = kwargs["now"], kwargs["execution_kind"]
        attempt = workspace.seal_attempt({
            "schema_version": workspace.ATTEMPT_SCHEMA, "owner": OWNER,
            "target_trade_date": date, "run_id": "4" * 32,
            "state": "SUCCEEDED", "execution_kind": kind,
            "started_at": now.isoformat(), "finished_at": (now + timedelta(seconds=1)).isoformat(),
            "failure_reasons": [], "input_identity": "6" * 64, **FLAGS,
        })
        return {"target_trade_date": date, "input_identity": "6" * 64,
            "plan_context": {"research_cutoff": now.isoformat()},
            "plan_product": {"status": "CURRENT", "run_id": "4" * 32, "sha256": "5" * 64,
                "generated_at": (now + timedelta(seconds=1)).isoformat(),
                "execution_kind": kind, "original_owner": OWNER, "consumed": True},
            "workspace_plan_attempt": attempt}


def bound_owner(tmp_path, monkeypatch, *, dual=True, enabled=True):
    binding, worker, owner = synthetic_binding(tmp_path, dual=dual, enabled=enabled)
    service = SyntheticOwner(binding)
    ref = _json_file(tmp_path / "binding.json", binding)
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", ref["path"])
    monkeypatch.setattr(dispatch, "APP_ROOT", owner)
    monkeypatch.setattr(dispatch, "clock_now", lambda: NOW)
    return service, binding, worker, owner, ref


@pytest.mark.parametrize("daily", [False, True])
def test_dual_roots_admit_the_same_raw_binding_and_echo_original_owner_identity(tmp_path, monkeypatch, daily):
    service, binding, worker, owner, ref = bound_owner(tmp_path, monkeypatch)
    assert worker != owner
    assert (worker / "v4/manager_research/service.py").read_bytes() != (owner / "v4/manager_research/service.py").read_bytes()
    # The worker still validates the top-level root and every closed source pin.
    assert supervisor.validate_binding(binding, expected_app=worker) == binding
    execute = dispatch.execute_bound_daily_cycle if daily else dispatch.execute_bound_plan_cycle
    result = execute(service, DATE, ref["sha256"])
    assert len(service.owner_calls) == 1
    assert result["binding_sha256"] == ref["sha256"]
    assert result["target_trade_date"] == DATE
    assert result["plan_result"]["run_id"] == "4" * 32
    assert result["plan_result"]["product_sha256"] == "5" * 64
    assert result["plan_result"]["input_identity"] == "6" * 64
    assert result["parent_trigger_receipt"]["binding_sha256"] == ref["sha256"]
    assert result["parent_trigger_receipt"]["owner_readback_status"] == "VERIFIED"
    assert result["dispatch_outcome"] == "OWNER_RESULT"
    assert all(result[key] is flag for key, flag in FLAGS.items())


@pytest.mark.parametrize("damage,code", [
    ("sha", "PLAN_OWNER_BINDING_SHA_MISMATCH"),
    ("api_root", "PLAN_OWNER_BINDING_API_ROOT_MISMATCH"),
    ("disabled", "PLAN_OWNER_BINDING_DISABLED"),
    ("worker_file", "ANNOUNCEMENT_BINDING_CLOSED_INVENTORY_MISMATCH"),
    ("api_file", "PLAN_OWNER_BINDING_CLOSED_INVENTORY_MISMATCH"),
    ("owner_file_missing", "PLAN_OWNER_BINDING_CLOSED_INVENTORY_MISMATCH"),
    ("owner_file_extra", "PLAN_OWNER_BINDING_CLOSED_INVENTORY_MISMATCH"),
    ("owner_name", "PLAN_OWNER_BINDING_IDENTITY_INVALID"),
    ("owner_fields", "PLAN_OWNER_BINDING_IDENTITY_INVALID"),
    ("owner_symlink", "PLAN_OWNER_BINDING_PATH_NOT_EXACT"),
    ("owner_source_symlink", "PLAN_OWNER_BINDING_INVENTORY_UNAVAILABLE"),
    ("api_consumer", "PLAN_OWNER_BINDING_CLOSED_INVENTORY_MISMATCH"),
    ("api_consumer_missing", "PLAN_OWNER_BINDING_INVENTORY_UNAVAILABLE"),
    ("owner_overlap", "PLAN_OWNER_BINDING_ROOTS_OVERLAP"),
    ("canary_owner", "PLAN_REFRESH_CANARY_OWNER_APP_ROOT_MISMATCH"),
    ("canary_identity_missing", "PLAN_REFRESH_CANARY_OWNER_IDENTITY_MISMATCH"),
    ("canary_identity_wrong", "PLAN_REFRESH_CANARY_OWNER_IDENTITY_MISMATCH"),
    ("canary_migration", "PLAN_REFRESH_CANARY_SOURCE_MIGRATION_UNEXPECTED"),
    ("master", "PLAN_OWNER_STATE_OR_MASTER_ROOT_MISMATCH"),
])
@pytest.mark.parametrize("daily", [False, True])
def test_gate_rejection_preserves_code_and_never_enters_owner_or_writes(tmp_path, monkeypatch, damage, code, daily):
    service, binding, worker, owner, ref = bound_owner(tmp_path, monkeypatch)
    sha = ref["sha256"]
    if damage == "sha":
        sha = "0" * 64
    elif damage == "api_root":
        other = tmp_path / "actual-other-api"; other.mkdir()
        monkeypatch.setattr(dispatch, "APP_ROOT", other)
    elif damage == "disabled":
        binding["enabled"] = False
    elif damage == "worker_file":
        (worker / "ops/run_manager_announcement_cycle.py").write_text("# changed worker\n")
    elif damage == "api_file":
        (owner / "v4/manager_research/plan_owner_dispatch.py").write_text("# changed API\n")
    elif damage == "owner_file_missing":
        binding["plan_owner_binding"]["files"].pop("apps/api/v35_api/app.py")
    elif damage == "owner_file_extra":
        binding["plan_owner_binding"]["files"]["apps/api/v35_api/unpinned.py"] = "a" * 64
    elif damage == "owner_name":
        binding["plan_owner_binding"]["owner"] = "OtherOwner"
    elif damage == "owner_fields":
        binding["plan_owner_binding"]["expected_app"] = str(owner)
    elif damage == "owner_symlink":
        link = tmp_path / "api-link"; link.symlink_to(owner, target_is_directory=True)
        binding["plan_owner_binding"]["app_root"] = str(link)
    elif damage == "owner_source_symlink":
        source = owner / "apps/api/v35_api/app.py"
        source.unlink(); source.symlink_to(worker / "apps/api/v35_api/app.py")
    elif damage == "api_consumer":
        (owner / "v3_shared_data/shared_data/hk_daily_supplement.py").write_text("# changed real API consumer\n")
    elif damage == "api_consumer_missing":
        (owner / "v3_shared_data/shared_data/hk_daily_supplement.py").unlink()
    elif damage == "owner_overlap":
        binding["plan_owner_binding"]["app_root"] = binding["manager_state_root"]
    elif damage == "canary_owner":
        # Replace the pinned evidence consistently; the new root binding must
        # still reject a canary executed by another API release.
        binding["plan_activation_receipt"] = _canary(tmp_path / "wrong-evidence", worker, worker, service.store.root)
    elif damage.startswith("canary_identity") or damage == "canary_migration":
        canary_path = Path(binding["plan_activation_receipt"]["path"])
        canary = json.loads(canary_path.read_bytes())
        if damage == "canary_identity_missing":
            canary.pop("owner_binding_identity_sha256")
        elif damage == "canary_identity_wrong":
            canary["owner_binding_identity_sha256"] = "0" * 64
        else:
            canary["source_migration_receipt"] = {"path": str(tmp_path / "unexpected.json"), "sha256": "a" * 64}
        binding["plan_activation_receipt"] = _json_file(canary_path, canary)
    elif damage == "master":
        service._workspace_security_master_root = tmp_path / "other-master"
    if damage not in {"sha", "api_root", "worker_file", "api_file", "master",
                      "owner_source_symlink", "api_consumer", "api_consumer_missing"}:
        ref = _json_file(Path(ref["path"]), binding)
        sha = ref["sha256"]
    execute = dispatch.execute_bound_daily_cycle if daily else dispatch.execute_bound_plan_cycle
    with pytest.raises(ValueError) as captured:
        execute(service, DATE, sha)
    expected = "PLAN_OWNER_DAILY_BINDING_DISABLED" if daily and damage == "disabled" else code
    assert str(captured.value) == expected
    assert type(captured.value).__name__ == "PlanOwnerAdmissionError"
    assert service.owner_calls == []
    assert service.writes == []
    assert not list(service.store.root.glob("workspace_plans/**/*.json"))
    assert not list(service.store.root.glob("workspace_plan_dispatch/**/*.json"))


def test_legacy_single_root_keeps_its_exact_root_gate(tmp_path, monkeypatch):
    service, binding, worker, owner, ref = bound_owner(tmp_path, monkeypatch, dual=False)
    result = dispatch.execute_bound_plan_cycle(service, DATE, ref["sha256"])
    assert result["plan_result"]["run_id"] == "4" * 32
    assert len(service.owner_calls) == 1
    monkeypatch.setattr(dispatch, "APP_ROOT", tmp_path)
    with pytest.raises(ValueError, match="ANNOUNCEMENT_BINDING_CWD_MISMATCH"):
        dispatch.execute_bound_plan_cycle(service, DATE, ref["sha256"])
    assert len(service.owner_calls) == 1


def test_daily_disabled_is_rejected_even_when_shared_binding_is_enabled(tmp_path, monkeypatch):
    service, binding, _, _, ref = bound_owner(tmp_path, monkeypatch, dual=False)
    binding["daily_automation"]["enabled"] = False
    ref = _json_file(Path(ref["path"]), binding)
    with pytest.raises(ValueError, match="PLAN_OWNER_DAILY_BINDING_DISABLED"):
        dispatch.execute_bound_daily_cycle(service, DATE, ref["sha256"])
    assert service.owner_calls == []
    assert service.writes == []


@pytest.mark.parametrize("daily", [False, True])
def test_router_keeps_a_safe_admission_reason_instead_of_collapsing_it(tmp_path, monkeypatch, daily):
    from fastapi import HTTPException
    from starlette.requests import Request
    from apps.api.v35_api.manager_research_router import create_manager_research_router
    service, _, _, _, ref = bound_owner(tmp_path, monkeypatch)
    router = create_manager_research_router(service)
    suffix = "/daily-cycle" if daily else "/scheduled-cycle"
    endpoint = next(route.endpoint for route in router.routes if route.path.endswith(suffix))
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    request = Request({"type": "http", "method": "POST", "path": suffix,
        "headers": [], "query_string": b"", "scheme": "http",
        "server": ("fixture.invalid", 80), "client": ("fixture", 1)}, receive=receive)
    with pytest.raises(HTTPException) as captured:
        asyncio.run(endpoint(request, date=DATE, binding_sha256="0" * 64))
    assert captured.value.status_code == 409
    assert captured.value.detail == "PLAN_OWNER_BINDING_SHA_MISMATCH"
    assert service.owner_calls == []
    assert service.writes == []


@pytest.mark.parametrize("detail,expected_code,expected_outcome", [
    ("PLAN_OWNER_BINDING_SHA_MISMATCH", "PLAN_OWNER_BINDING_SHA_MISMATCH", "GATE_REJECTED"),
    ("PLAN_OWNER_BINDING_API_ROOT_MISMATCH", "PLAN_OWNER_BINDING_API_ROOT_MISMATCH", "GATE_REJECTED"),
    ("PLAN_OWNER_BINDING_DISABLED", "PLAN_OWNER_BINDING_DISABLED", "GATE_REJECTED"),
    ("/secret/path arbitrary exception", "PLAN_OWNER_RPC_HTTP_409", "READBACK_UNCONFIRMED"),
])
def test_client_preserves_only_allowlisted_admission_codes(tmp_path, monkeypatch, detail, expected_code, expected_outcome):
    _, _, _, _, ref = bound_owner(tmp_path, monkeypatch, dual=False)
    requests = []
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, method, path, **kwargs): requests.append((method, path))
        def getresponse(self):
            return SimpleNamespace(status=409, getheader=lambda *_: "application/json",
                read=lambda *_: json.dumps({"detail": detail}).encode())
        def close(self): pass
    monkeypatch.setattr(dispatch.http.client, "HTTPConnection", Connection)
    result = dispatch.request_bound_plan_cycle(ref["path"], DATE)
    assert len(requests) == 1
    assert result["parent_trigger_receipt"]["failure_code"] == expected_code
    assert result["dispatch_outcome"] == expected_outcome
    assert result["binding_sha256"] == ref["sha256"]
    assert result["target_trade_date"] == DATE
    assert "secret" not in json.dumps(result)


def test_transport_failure_keeps_owner_execution_unconfirmed(tmp_path, monkeypatch):
    _, _, _, _, ref = bound_owner(tmp_path, monkeypatch, dual=False)
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): raise TimeoutError("synthetic transport timeout")
        def close(self): pass
    monkeypatch.setattr(dispatch.http.client, "HTTPConnection", Connection)
    result = dispatch.request_bound_plan_cycle(ref["path"], DATE)
    assert result["dispatch_outcome"] == "READBACK_UNCONFIRMED"
    assert result["parent_trigger_receipt"]["owner_readback_status"] == "NOT_CONFIRMED"
    assert "run_id" not in result and "product_sha256" not in result


def test_input_not_ready_is_distinct_from_original_owner_failure():
    identity = dispatch._parent_trigger_identity(DATE, DATE, "PREOPEN", "a" * 64)
    missing = dispatch._cycle_result(identity, NOW, {
        "status": "PARTIAL", "branch": "PREOPEN", "plan_result": {
            "status": "CANNOT_CONFIRM", "target_trade_date": DATE,
            "failure_reasons": ["HK_UNIVERSE_V2_ARTIFACT_MISSING"]}})
    failed = dispatch._cycle_result(identity, NOW, {
        "status": "FAILED", "branch": "PREOPEN", "plan_result": {
            "status": "FAILED", "target_trade_date": DATE,
            "failure_reasons": ["PLAN_OWNER_FAILED:RuntimeError"]}})
    assert missing["dispatch_outcome"] == "INPUT_NOT_READY"
    assert missing["plan_result"]["failure_reasons"] == ["HK_UNIVERSE_V2_ARTIFACT_MISSING"]
    assert failed["dispatch_outcome"] == "OWNER_FAILED"
    for result in (missing, failed):
        assert result["parent_trigger_receipt"]["owner_readback_status"] == "UNVERIFIED"
        assert result["parent_trigger_receipt"]["owner_run_id"] is None
        assert result["parent_trigger_receipt"]["owner_product_sha256"] is None


def test_renderer_pins_both_roots_in_one_reviewable_raw_binding(tmp_path):
    from ops import render_manager_announcement_binding as renderer
    binding, worker, owner = synthetic_binding(tmp_path)
    output = tmp_path / "rendered.json"
    assert renderer.main([
        "--app-root", str(worker), "--plan-owner-app-root", str(owner),
        "--manager-state-root", binding["manager_state_root"],
        "--security-master-root", binding["security_master_root"],
        "--python", binding["python"], "--output", str(output),
        "--enabled", "--plan-material-refresh-only", "--daily-automation",
        "--plan-activation-receipt", binding["plan_activation_receipt"]["path"],
    ]) == 0
    rendered = json.loads(output.read_bytes())
    assert rendered["app_root"] == str(worker)
    assert rendered["files"] == supervisor.binding_inventory(worker)
    assert rendered["plan_owner_binding"] == binding["plan_owner_binding"]
    assert rendered["plan_activation_receipt"] == binding["plan_activation_receipt"]


def _request_fixture():
    from starlette.requests import Request
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/fixture",
        "headers": [], "query_string": b"", "scheme": "http",
        "server": ("fixture.invalid", 80), "client": ("fixture", 1)}, receive=receive)


def test_manual_router_preserves_input_missing_without_persisted_product_read():
    from apps.api.v35_api.manager_research_router import create_manager_research_router
    owner_calls, stored_reads = [], []
    result = {"target_trade_date": DATE, "status": "CANNOT_CONFIRM",
        "reason": "WORKSPACE_PLAN_INPUTS_NOT_READY",
        "failure_reasons": ["HK_UNIVERSE_V2_ARTIFACT_MISSING"],
        "plan_product": {"status": "CANNOT_CONFIRM", "consumed": False, "run_id": None, "sha256": None},
        "workspace_plan_attempt": None, **FLAGS}
    def refresh(date, **kwargs):
        owner_calls.append((date, kwargs))
        return deepcopy(result)
    def persisted(*args):
        stored_reads.append(args)
        raise ValueError("a missing input has no stored successful plan")
    service = SimpleNamespace(refresh_workspace_plan=refresh, get_workspace_plan=persisted)
    router = create_manager_research_router(service)
    endpoint = next(route.endpoint for route in router.routes if route.path.endswith("/workspace/refresh"))
    returned = asyncio.run(endpoint(_request_fixture(), date=DATE))
    assert returned["status"] == "CANNOT_CONFIRM"
    assert returned["failure_reasons"] == ["HK_UNIVERSE_V2_ARTIFACT_MISSING"]
    assert returned["plan_product"]["run_id"] is None
    assert returned["store_latest_matches_http_plan_product"] is False
    assert len(owner_calls) == 1
    assert stored_reads == []


@pytest.mark.parametrize("damage", ["run_id", "product_sha256", "input_identity", "dispatch_outcome"])
def test_http_200_still_rejects_mismatched_owner_identity(tmp_path, monkeypatch, damage):
    service, _, _, _, ref = bound_owner(tmp_path, monkeypatch, dual=False)
    value = dispatch.execute_bound_plan_cycle(service, DATE, ref["sha256"])
    if damage == "dispatch_outcome":
        value["dispatch_outcome"] = "GATE_REJECTED"
    else:
        value["plan_result"][damage] = "b" * (32 if damage == "run_id" else 64)
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self):
            return SimpleNamespace(status=200, getheader=lambda *_: "application/json",
                read=lambda *_: json.dumps(value).encode())
        def close(self): pass
    monkeypatch.setattr(dispatch.http.client, "HTTPConnection", Connection)
    returned = dispatch.request_bound_plan_cycle(ref["path"], DATE)
    assert returned["status"] == "FAILED"
    assert returned["dispatch_outcome"] == "READBACK_UNCONFIRMED"
    assert returned["parent_trigger_receipt"]["failure_code"] == "PLAN_OWNER_RPC_PARENT_TRIGGER_READBACK_INVALID"


def test_router_does_not_disclose_unclassified_exception_text(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from apps.api.v35_api.manager_research_router import create_manager_research_router
    service, _, _, _, ref = bound_owner(tmp_path, monkeypatch)
    def unknown(*args, **kwargs):
        raise ValueError("/secret/path arbitrary exception")
    monkeypatch.setattr(dispatch, "execute_bound_plan_cycle", unknown)
    router = create_manager_research_router(service)
    endpoint = next(route.endpoint for route in router.routes if route.path.endswith("/scheduled-cycle"))
    with pytest.raises(HTTPException) as captured:
        asyncio.run(endpoint(_request_fixture(), date=DATE, binding_sha256=ref["sha256"]))
    assert captured.value.status_code == 409
    assert captured.value.detail == "SCHEDULED_WORKSPACE_OWNER_FAILED"


def test_legacy_cross_root_canary_still_requires_identical_owner_sources(tmp_path):
    binding, worker, owner = synthetic_binding(tmp_path)
    binding.pop("plan_owner_binding")
    binding["plan_activation_receipt"] = _canary(tmp_path / "legacy-evidence", worker, owner,
        Path(binding["manager_state_root"]), legacy_migration=True)
    with pytest.raises(ValueError, match="PLAN_REFRESH_CANARY_SOURCE_MIGRATION_MISMATCH"):
        supervisor.validate_binding(binding, expected_app=worker)


def test_explicit_rpc_canary_pins_api_sources_without_migrating_worker_sources(tmp_path):
    binding, worker, owner = synthetic_binding(tmp_path)
    assert (worker / "v4/manager_research/service.py").read_bytes() != (owner / "v4/manager_research/service.py").read_bytes()
    # Use the implementation's closed inventory here so this test isolates
    # the RPC canary contract from the separate consumer-inventory regression.
    binding["plan_owner_binding"]["files"] = supervisor.plan_owner_inventory(owner)
    canary_path = Path(binding["plan_activation_receipt"]["path"])
    canary = json.loads(canary_path.read_bytes())
    canary["owner_binding_identity_sha256"] = _identity_sha(binding["plan_owner_binding"])
    assert "source_migration_receipt" not in canary
    binding["plan_activation_receipt"] = _json_file(canary_path, canary)
    assert supervisor.validate_binding(binding, expected_app=worker) == binding


def test_owner_inventory_pins_actual_api_consumer_package_and_new_files(tmp_path):
    owner = _source_root(tmp_path / "api")
    extra = owner / "v3_shared_data/shared_data/new_consumer.py"
    extra.write_text("# synthetic additional imported module\n")
    inventory = supervisor.plan_owner_inventory(owner)
    for path in (extra, owner / "v3_shared_data/shared_data/hk_daily_supplement.py"):
        assert inventory.get(str(path.relative_to(owner))) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_owner_entry_files_share_the_existing_total_source_byte_budget(tmp_path, monkeypatch):
    owner = _source_root(tmp_path / "api")
    count = len(supervisor.binding_inventory(owner))
    payload = b"x" * (64 * 1024 * 1024 // (count + 1))
    monkeypatch.setattr(supervisor.SafeRoot, "read_bytes", lambda *_args, **_kwargs: payload)
    with pytest.raises(ValueError, match="SOURCE_BYTE_BUDGET"):
        supervisor.plan_owner_inventory(owner)


def test_known_gate_code_on_http_500_still_leaves_execution_unconfirmed(tmp_path, monkeypatch):
    _, _, _, _, ref = bound_owner(tmp_path, monkeypatch, dual=False)
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self):
            return SimpleNamespace(status=500, getheader=lambda *_: "application/json",
                read=lambda *_: b'{"detail":"PLAN_OWNER_BINDING_DISABLED"}')
        def close(self): pass
    monkeypatch.setattr(dispatch.http.client, "HTTPConnection", Connection)
    result = dispatch.request_bound_plan_cycle(ref["path"], DATE)
    assert result["dispatch_outcome"] == "READBACK_UNCONFIRMED"


@pytest.mark.parametrize("daily", [False, True])
def test_input_not_ready_can_retry_after_backoff_then_cache_verified_partial(tmp_path, monkeypatch, daily):
    from test_manager_r3_cycle_outcomes import missing_input
    service, _, _, _, ref = bound_owner(tmp_path, monkeypatch)
    original_refresh = service.refresh_workspace_plan
    ready = False
    def refresh(date, **kwargs):
        if ready:
            return original_refresh(date, **kwargs)
        service.owner_calls.append((date, kwargs))
        return missing_input(date)
    service.refresh_workspace_plan = refresh
    execute = dispatch.execute_bound_daily_cycle if daily else dispatch.execute_bound_plan_cycle
    first = execute(service, DATE, ref["sha256"])
    assert first["status"] == "PARTIAL"
    assert first["dispatch_outcome"] == "INPUT_NOT_READY"
    assert workspace._read_plan(service.store, DATE) is None
    writes = len(service.writes)

    ready = True
    monkeypatch.setattr(dispatch, "clock_now", lambda: NOW + timedelta(seconds=59))
    blocked = execute(service, DATE, ref["sha256"])
    assert blocked["failure_reasons"] == ["PLAN_OWNER_RETRY_BACKOFF"]
    assert len(service.owner_calls) == 1 and len(service.writes) == writes

    monkeypatch.setattr(dispatch, "clock_now", lambda: NOW + timedelta(minutes=1))
    second = execute(service, DATE, ref["sha256"])
    assert len(service.owner_calls) == 2
    assert second["dispatch_outcome"] == "OWNER_RESULT"
    assert second["status"] == "PARTIAL"  # Independent US gap, verified plan.
    assert second["parent_trigger_receipt"]["owner_readback_status"] == "VERIFIED"
    assert second["plan_result"]["run_id"] == "4" * 32
    assert second["dispatch_receipt"] != first["dispatch_receipt"]
    assert (second["parent_trigger_receipt"]["trigger_id"]
            == first["parent_trigger_receipt"]["trigger_id"])

    monkeypatch.setattr(dispatch, "clock_now", lambda: NOW + timedelta(minutes=2))
    third = execute(service, DATE, ref["sha256"])
    assert third["dispatch_receipt"] == second["dispatch_receipt"]
    assert third["plan_result"] == second["plan_result"]
    assert len(service.owner_calls) == 2


@pytest.mark.parametrize("daily", [False, True])
@pytest.mark.parametrize("branch", ["PREOPEN", "EVENING_NEXT_SESSION"])
def test_input_not_ready_uses_original_bounded_retry_budget(tmp_path, monkeypatch, branch, daily):
    from test_manager_r3_cycle_outcomes import missing_input
    service, _, _, _, ref = bound_owner(tmp_path, monkeypatch)
    def refresh(date, **kwargs):
        service.owner_calls.append((date, kwargs))
        return missing_input(date)
    service.refresh_workspace_plan = refresh
    monkeypatch.setattr(workspace, "get_workspace", lambda *_a, **_k: {"input_identity": "a" * 64})
    start = NOW if branch == "PREOPEN" else datetime(2026, 10, 8, 16, 0, tzinfo=HK)
    backoff = 60 if branch == "PREOPEN" else 600
    execute = dispatch.execute_bound_daily_cycle if daily else dispatch.execute_bound_plan_cycle
    references = []
    for attempt in range(3):
        monkeypatch.setattr(dispatch, "clock_now", lambda attempt=attempt: start + timedelta(seconds=attempt * backoff))
        response = execute(service, DATE, ref["sha256"])
        assert response["branch"] == branch
        assert response["dispatch_outcome"] == "INPUT_NOT_READY"
        assert len(service.owner_calls) == attempt + 1
        references.append(response["dispatch_receipt"]["path"])
        if attempt == 0:
            writes = len(service.writes)
            monkeypatch.setattr(dispatch, "clock_now", lambda: start + timedelta(seconds=backoff - 1))
            blocked = execute(service, DATE, ref["sha256"])
            assert blocked["failure_reasons"] == ["PLAN_OWNER_RETRY_BACKOFF"]
            assert len(service.owner_calls) == 1 and len(service.writes) == writes
    assert len(set(references)) == 3
    writes = len(service.writes)
    monkeypatch.setattr(dispatch, "clock_now", lambda: start + timedelta(seconds=2 * backoff + 30))
    exhausted = execute(service, DATE, ref["sha256"])
    assert exhausted["failure_reasons"] == ["PLAN_OWNER_RETRY_LIMIT_REACHED"]
    assert exhausted["dispatch_outcome"] == "GATE_REJECTED"
    assert len(service.owner_calls) == 3 and len(service.writes) == writes
    assert workspace._read_plan(service.store, DATE) is None
    assert not (service.store.root / "workspace_plan_runs").exists()


def test_input_not_ready_and_owner_failure_share_one_retry_budget(tmp_path, monkeypatch):
    from test_manager_r3_cycle_outcomes import missing_input
    service, _, _, _, ref = bound_owner(tmp_path, monkeypatch)
    def refresh(date, **kwargs):
        service.owner_calls.append((date, kwargs))
        if len(service.owner_calls) == 2:
            raise RuntimeError("synthetic owner failure")
        return missing_input(date)
    service.refresh_workspace_plan = refresh
    outcomes = []
    for attempt in range(3):
        monkeypatch.setattr(dispatch, "clock_now", lambda attempt=attempt: NOW + timedelta(minutes=attempt))
        outcomes.append(dispatch.execute_bound_plan_cycle(service, DATE, ref["sha256"])["dispatch_outcome"])
    assert outcomes == ["INPUT_NOT_READY", "OWNER_FAILED", "INPUT_NOT_READY"]
    writes = len(service.writes)
    monkeypatch.setattr(dispatch, "clock_now", lambda: NOW + timedelta(minutes=2, seconds=30))
    response = dispatch.execute_bound_plan_cycle(service, DATE, ref["sha256"])
    assert response["failure_reasons"] == ["PLAN_OWNER_RETRY_LIMIT_REACHED"]
    assert len(service.owner_calls) == 3 and len(service.writes) == writes


@pytest.mark.parametrize("daily", [False, True])
def test_window_expiring_before_owner_is_not_triggered(tmp_path, monkeypatch, daily):
    service, _, _, _, ref = bound_owner(tmp_path, monkeypatch)
    admitted = NOW.replace(minute=29, second=59)
    expired = NOW.replace(minute=30, second=0)
    ticks = iter([admitted, admitted, expired, expired])
    monkeypatch.setattr(dispatch, "clock_now", lambda: next(ticks))
    execute = dispatch.execute_bound_daily_cycle if daily else dispatch.execute_bound_plan_cycle
    result = execute(service, DATE, ref["sha256"])
    assert result["dispatch_outcome"] == "NOT_TRIGGERED"
    assert result["parent_trigger_receipt"]["dispatch_outcome"] == "NOT_TRIGGERED"
    assert result["plan_result"]["status"] == "EXPIRED_NO_BACKFILL"
    assert result["failure_reasons"] == ["PLAN_OWNER_WINDOW_EXPIRED_BEFORE_EXECUTION"]
    assert service.owner_calls == []
    assert workspace._read_plan(service.store, DATE) is None


def test_cycle_explicit_unconfirmed_readback_is_preserved_by_dispatch(monkeypatch):
    from v4.manager_research import workspace_plan_autorun as autorun
    monkeypatch.setattr(autorun, "run_scheduled_preopen_plan_safe", lambda *_a, **_k: {
        "status": "MATERIALIZED", "target_trade_date": DATE})
    branch = cycle.run_scheduled_plan_target(object(), DATE, DATE, now=NOW,
        plan_config={"enabled": True}, preopen_config={"enabled": True, "lead_seconds": 180})
    assert branch["dispatch_outcome"] == "READBACK_UNCONFIRMED"
    identity = dispatch._parent_trigger_identity(DATE, DATE, "PREOPEN", "a" * 64)
    response = dispatch._cycle_result(identity, NOW, branch)
    assert response["dispatch_outcome"] == "READBACK_UNCONFIRMED"
    assert response["parent_trigger_receipt"]["dispatch_outcome"] == "READBACK_UNCONFIRMED"
    assert response["parent_trigger_receipt"]["owner_readback_status"] == "UNVERIFIED"
    assert response["failure_reasons"] == ["PLAN_OWNER_PRODUCT_READBACK_INVALID"]


def _historical_canary_url(binding, url):
    canary_path = Path(binding["plan_activation_receipt"]["path"])
    canary = json.loads(canary_path.read_bytes())
    canary["scope"] = supervisor.PLAN_CANARY_HISTORICAL_SCOPE
    receipt_path = Path(canary["owner_evidence"]["readback"]["path"])
    receipt = json.loads(receipt_path.read_bytes())
    receipt["request"]["url"] = url
    canary["owner_evidence"]["readback"] = _json_file(receipt_path, receipt)
    binding["plan_activation_receipt"] = _json_file(canary_path, canary)


@pytest.mark.parametrize("query", ["date=20261008&view=dynamic", "view=dynamic&date=20261008"])
def test_explicit_historical_canary_requires_exact_dynamic_readback(tmp_path, query):
    binding, worker, _ = synthetic_binding(tmp_path)
    _historical_canary_url(binding, "http://127.0.0.1:8873/api/v4/manager/research/workspace?" + query)
    assert supervisor.validate_binding(binding, expected_app=worker) == binding


@pytest.mark.parametrize("query", [
    "date=20261008", "date=20261008&view=auto", "date=20261008&view=",
    "date=20261009&view=dynamic", "view=dynamic",
    "date=20261008&date=20261008&view=dynamic",
    "date=20261008&view=dynamic&view=dynamic",
    "date=20261008&view=dynamic&extra=true",
    "date=20261008&view=dynamic&", "date=20261008&view=dynamic#ignored",
])
def test_explicit_historical_canary_rejects_missing_duplicate_or_unknown_query(tmp_path, query):
    binding, worker, _ = synthetic_binding(tmp_path)
    _historical_canary_url(binding, "http://127.0.0.1:8873/api/v4/manager/research/workspace?" + query)
    with pytest.raises(ValueError, match="PLAN_REFRESH_CANARY_HTTP_EVIDENCE_INVALID"):
        supervisor.validate_binding(binding, expected_app=worker)


@pytest.mark.parametrize("origin", [
    "http://localhost:8873", "https://127.0.0.1:8873", "http://127.0.0.1:8874",
    "http://user@127.0.0.1:8873", "\thttp://127.0.0.1:8873",
])
def test_explicit_historical_canary_keeps_exact_loopback_origin(tmp_path, origin):
    binding, worker, _ = synthetic_binding(tmp_path)
    _historical_canary_url(binding, origin + "/api/v4/manager/research/workspace?date=20261008&view=dynamic")
    with pytest.raises(ValueError, match="PLAN_REFRESH_CANARY_HTTP_EVIDENCE_INVALID"):
        supervisor.validate_binding(binding, expected_app=worker)


@pytest.mark.parametrize("dynamic", [False, True])
def test_legacy_historical_canary_keeps_original_exact_url_contract(tmp_path, dynamic):
    binding, worker, _ = synthetic_binding(tmp_path, dual=False)
    _historical_canary_url(binding,
        "http://127.0.0.1:8873/api/v4/manager/research/workspace?date=20261008"
        + ("&view=dynamic" if dynamic else ""))
    if dynamic:
        with pytest.raises(ValueError, match="PLAN_REFRESH_CANARY_HTTP_EVIDENCE_INVALID"):
            supervisor.validate_binding(binding, expected_app=worker)
    else:
        assert supervisor.validate_binding(binding, expected_app=worker) == binding

