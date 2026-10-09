"""Existing plan-owner dispatch with synthetic receipts and temporary state only."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

# Load this actual binding validator by filename. The frozen scheduling package
# __init__ eagerly imports unrelated Stage executors whose split-module closure
# was not supplied. No Stage module or owner behavior is replaced here.
_supervisor_name = "infrastructure.scheduling.manager_announcement_supervisor"
supervisor = sys.modules.get(_supervisor_name)
if supervisor is None:
    _supervisor_spec = importlib.util.spec_from_file_location(
        _supervisor_name, Path(__file__).resolve().parents[1]
        / "infrastructure/scheduling/manager_announcement_supervisor.py")
    supervisor = importlib.util.module_from_spec(_supervisor_spec)
    sys.modules[_supervisor_name] = supervisor
    _supervisor_spec.loader.exec_module(supervisor)
from ops import run_manager_announcement_cycle as cycle
from v4.manager_research import plan_owner_dispatch as dispatch
from v4.manager_research import workspace
from v4.manager_research import workspace_plan_autorun as autorun
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS, HK
from v4.manager_research.workspace_read_control import ReadCoordinator
from manager_r3_assessed_fixture import assessed_projection


DATE = "20261008"
OWNER = "ManagerResearchJobService.refresh_workspace_plan"
PREOPEN = datetime(2026, 10, 8, 9, 27, tzinfo=HK)
MORNING = datetime(2026, 10, 8, 7, 0, tzinfo=HK)
EVENING = {"enabled": True, "max_attempts_per_target_date": 3,
           "retry_backoff_seconds": 600}
MORNING_CONFIG = {"enabled": True, "interval_seconds": 300, "status": "PROPOSAL_ONLY"}


def owner_value(*, date=DATE, now=PREOPEN, kind="SCHEDULED_PREOPEN", state="SUCCEEDED",
                run_id="1" * 32, identity="3" * 64):
    failures = ["SYNTHETIC_INDEPENDENT_LANE_GAP"] if state == "PARTIAL" else []
    attempt = workspace.seal_attempt({
        "schema_version": workspace.ATTEMPT_SCHEMA,
        "owner": OWNER, "target_trade_date": date, "run_id": run_id,
        "state": state, "execution_kind": kind,
        "started_at": now.isoformat(), "finished_at": (now + timedelta(seconds=1)).isoformat(),
        "failure_reasons": failures, "input_identity": identity, **FLAGS,
    })
    return {
        "target_trade_date": date, "input_identity": identity,
        "plan_context": {"research_cutoff": now.isoformat()},
        "plan_product": {"status": "CURRENT", "run_id": run_id, "sha256": "2" * 64,
                         "generated_at": (now + timedelta(seconds=1)).isoformat(),
                         "execution_kind": kind, "original_owner": OWNER, "consumed": True},
        "workspace_plan_attempt": attempt,
    }


class SyntheticOwner:
    def __init__(self, tmp_path, *, state="SUCCEEDED"):
        self.store = ManagerResearchStore(tmp_path / "state")
        self._workspace_security_master_root = tmp_path / "master"
        self._workspace_security_master_root.mkdir()
        self._existing_research_source = object()
        self._workspace_us_market_reader = None
        self._workspace_reads = ReadCoordinator()
        self.calls = []
        self.state = state

    def refresh_workspace_plan(self, date, **kwargs):
        self.calls.append((date, kwargs))
        return owner_value(date=date, now=kwargs["now"], kind=kwargs["execution_kind"], state=self.state)


def bound_service(tmp_path, monkeypatch, *, now=PREOPEN, state="SUCCEEDED"):
    service = SyntheticOwner(tmp_path, state=state)
    binding = {"enabled": True, "manager_state_root": str(service.store.root),
               "security_master_root": str(service._workspace_security_master_root),
               "preopen_plan": {"enabled": True, "lead_seconds": 180},
               "morning_plan": MORNING_CONFIG, "plan_material_refresh": EVENING}
    raw = json.dumps(binding, sort_keys=True).encode()
    path = tmp_path / "binding.json"
    path.write_bytes(raw)
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(path))
    monkeypatch.setattr(supervisor, "validate_binding", lambda value, **_: value)
    monkeypatch.setattr(dispatch, "clock_now", lambda: now)
    return service, hashlib.sha256(raw).hexdigest(), path


def test_partial_owner_remains_partial_in_preopen():
    value = owner_value(state="PARTIAL")
    service = SimpleNamespace(refresh_workspace_plan=lambda *_, **__: deepcopy(value))
    result = autorun.run_scheduled_preopen_plan(service, DATE, now=PREOPEN)
    assert result["status"] == "PARTIAL"
    assert result["owner_attempt_state"] == "PARTIAL"
    assert result["owner_attempt_run_id"] == result["run_id"]
    assert result["failure_reasons"] == ["SYNTHETIC_INDEPENDENT_LANE_GAP"]


@pytest.mark.parametrize("damage", ["manual_kind", "missing_kind", "wrong_run", "bad_attempt_sha"])
def test_preopen_never_invents_or_accepts_mismatched_owner_identity(damage):
    value = owner_value(kind="MANUAL_REFRESH" if damage == "manual_kind" else "SCHEDULED_PREOPEN")
    if damage == "missing_kind":
        value["plan_product"].pop("execution_kind")
    elif damage == "wrong_run":
        value["workspace_plan_attempt"] = workspace.seal_attempt({
            **value["workspace_plan_attempt"], "run_id": "4" * 32})
    elif damage == "bad_attempt_sha":
        value["workspace_plan_attempt"]["sha256"] = "0" * 64
    service = SimpleNamespace(refresh_workspace_plan=lambda *_, **__: value)
    result = autorun.run_scheduled_preopen_plan_safe(service, DATE, now=PREOPEN)
    assert result["status"] == "FAILED"
    assert result["blocks_announcement"] is False


def test_existing_morning_branch_reaches_same_owner(tmp_path):
    service = SyntheticOwner(tmp_path)
    result = cycle.run_scheduled_plan_target(
        service, DATE, DATE, now=MORNING, plan_config=EVENING,
        morning_plan_config=MORNING_CONFIG)
    assert result["branch"] == "MORNING"
    assert result["status"] == "SUCCEEDED"
    assert service.calls[0][1]["execution_kind"] == "SCHEDULED_MORNING"
    assert result["plan_result"]["owner_attempt_run_id"] == result["plan_result"]["run_id"]


@pytest.mark.parametrize("now,kind", [(MORNING, "SCHEDULED_MORNING"), (PREOPEN, "SCHEDULED_PREOPEN")])
def test_missing_us_dependency_does_not_block_independent_plan_owner(tmp_path, monkeypatch, now, kind):
    service, sha, _ = bound_service(tmp_path, monkeypatch, now=now)
    result = dispatch.execute_bound_plan_cycle(service, DATE, sha)
    assert len(service.calls) == 1
    assert service.calls[0][1]["execution_kind"] == kind
    assert result["status"] == "PARTIAL"
    assert result["us_mapping_research"]["status"] == "CANNOT_CONFIRM"
    assert result["parent_trigger_receipt"]["owner_readback_status"] == "VERIFIED"
    assert result["parent_trigger_receipt"]["owner_execution_kind"] == kind
    ref = result["dispatch_receipt"]
    saved = service.store._read(service.store.root / ref["path"])
    assert saved["sha256"] == ref["sha256"]
    assert saved["response"]["parent_trigger_receipt"]["trigger_id"] == result["parent_trigger_receipt"]["trigger_id"]
    assert saved["response"]["plan_result"]["run_id"] == result["plan_result"]["run_id"]


def test_us_mutating_owner_is_not_called_from_independent_plan_rpc(tmp_path, monkeypatch):
    service, sha, _ = bound_service(tmp_path, monkeypatch)
    service._workspace_us_market_reader = object()
    calls = []
    def failed_mapping(*_, **__):
        calls.append(1)
        raise ImportError("synthetic missing owner dependency")
    service.refresh_us_mapping_research = failed_mapping
    result = dispatch.execute_bound_plan_cycle(service, DATE, sha)
    assert service.calls
    assert calls == []
    assert result["status"] == "PARTIAL"
    assert result["us_mapping_research"]["status"] == "NOT_ATTEMPTED"
    assert result["us_mapping_research"]["execution_attempted"] is False
    assert result["us_mapping_research"]["matches"] is None
    assert result["us_mapping_research"]["gaps"] == ["US_MAPPING_REQUIRES_INDEPENDENT_OWNER_DISPATCH"]


def test_evening_attempt_budget_does_not_reset_when_input_identity_changes(tmp_path, monkeypatch):
    service = SyntheticOwner(tmp_path)
    monkeypatch.setattr(workspace, "_read_plan", lambda *args: None)
    monkeypatch.setattr(workspace, "get_workspace", lambda *args, **kwargs: {"input_identity": "a" * 64})
    failed = {"state": "FAILED", "input_identity": "b" * 64,
              "started_at": "2026-10-08T16:00:00+08:00", "finished_at": "2026-10-08T16:00:01+08:00"}
    monkeypatch.setattr(cycle, "_attempts_today", lambda *args: [failed, failed, failed])
    result = cycle.run_next_hk_session_plan_material_refresh(
        service, DATE, now=PREOPEN.replace(hour=18, minute=0), config=EVENING)
    assert result["status"] == "RETRY_LIMIT_REACHED"
    assert service.calls == []


def test_repeated_dispatch_failures_are_durably_bounded(tmp_path, monkeypatch):
    service, sha, _ = bound_service(tmp_path, monkeypatch)
    calls = []
    def broken_owner(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("synthetic owner failure")
    service.refresh_workspace_plan = broken_owner
    results = []
    for seconds in (0, 60, 120, 179):
        monkeypatch.setattr(dispatch, "clock_now", lambda seconds=seconds: PREOPEN + timedelta(seconds=seconds))
        results.append(dispatch.execute_bound_plan_cycle(service, DATE, sha))
    assert len(calls) == 3
    assert results[-1]["failure_reasons"] == ["PLAN_OWNER_RETRY_LIMIT_REACHED"]
    assert results[-1]["status"] == "FAILED"


def test_wrong_date_or_closed_window_never_calls_owner(tmp_path, monkeypatch):
    service, sha, _ = bound_service(tmp_path, monkeypatch, now=PREOPEN.replace(minute=30))
    with pytest.raises(ValueError, match="TARGET_DATE_OR_WINDOW_MISMATCH"):
        dispatch.execute_bound_plan_cycle(service, DATE, sha)
    assert service.calls == []


def test_client_does_not_accept_manual_product_as_preopen(tmp_path, monkeypatch):
    _, sha, path = bound_service(tmp_path, monkeypatch)
    identity = dispatch._parent_trigger_identity(DATE, DATE, "PREOPEN", sha)
    plan = {"status": "MATERIALIZED", "run_id": "1" * 32, "product_sha256": "2" * 64,
            "input_identity": "3" * 64, "execution_kind": "MANUAL_REFRESH",
            "execution_kind_source": "OWNER_READBACK", "owner_attempt_state": "SUCCEEDED",
            "owner_attempt_run_id": "1" * 32, "owner_attempt_sha256": "4" * 64,
            "owner": OWNER, "target_trade_date": DATE, "failure_reasons": []}
    result = {"schema_version": dispatch.SCHEMA, "owner": OWNER, "binding_sha256": sha,
              "target_trade_date": DATE, "status": "SUCCEEDED", "branch": "PREOPEN",
              "plan_result": plan, **FLAGS}
    result["parent_trigger_receipt"] = dispatch._parent_trigger_receipt(identity, now=PREOPEN, result=result)
    result["parent_trigger_receipt"]["owner_readback_status"] = "VERIFIED"
    result["dispatch_receipt"] = {
        "path": f"workspace_plan_dispatch/{DATE}/{identity['trigger_id']}/0001.json",
        "sha256": "5" * 64, "status": "READBACK_VERIFIED"}
    raw = json.dumps(result).encode()
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self):
            return SimpleNamespace(status=200, getheader=lambda *args: "application/json", read=lambda *args: raw)
        def close(self): pass
    monkeypatch.setattr(dispatch.http.client, "HTTPConnection", Connection)
    returned = dispatch.request_bound_plan_cycle(path, DATE)
    assert returned["status"] == "FAILED"
    assert returned["parent_trigger_receipt"]["failure_code"] == "PLAN_OWNER_RPC_PARENT_TRIGGER_READBACK_INVALID"


def test_unfinished_dispatch_requires_reconciliation_before_another_owner_call(tmp_path, monkeypatch):
    service, sha, _ = bound_service(tmp_path, monkeypatch)
    class SimulatedProcessTermination(BaseException): pass
    calls = []
    def interrupted(*args, **kwargs):
        calls.append(1)
        raise SimulatedProcessTermination()
    service.refresh_workspace_plan = interrupted
    with pytest.raises(SimulatedProcessTermination):
        dispatch.execute_bound_plan_cycle(service, DATE, sha)
    result = dispatch.execute_bound_plan_cycle(service, DATE, sha)
    assert calls == [1]
    assert result["failure_reasons"] == ["PLAN_OWNER_RECONCILIATION_REQUIRED"]
    assert result["parent_trigger_receipt"]["owner_readback_status"] == "UNVERIFIED"


def test_daily_running_receipt_recovers_exact_committed_owner_without_reentry(tmp_path, monkeypatch):
    now = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
    service, _sha, binding_path = bound_service(tmp_path, monkeypatch, now=now)
    binding = json.loads(binding_path.read_bytes())
    binding["daily_automation"] = {"enabled": True,
        "same_day_catchup_slots_local": ["10:00", "12:30", "15:45", "18:30", "22:30"],
        "us_mapping_budget_seconds": 5, "max_attempts_per_target_date": 5,
        "status": "PROPOSAL_ONLY"}
    binding_path.write_text(json.dumps(binding, sort_keys=True), encoding="utf-8")
    sha = hashlib.sha256(binding_path.read_bytes()).hexdigest()

    assessed = assessed_projection(tmp_path, monkeypatch, now=now)
    def current(*_args, **kwargs):
        value = deepcopy(assessed)
        value["plan_context"]["research_cutoff"] = kwargs["now"].isoformat()
        return value

    monkeypatch.setattr(workspace, "get_workspace", current)
    monkeypatch.setattr(workspace, "_now", lambda: "2026-10-08T02:00:01+00:00")
    owner_calls = []

    def persist_once(date, **kwargs):
        owner_calls.append((date, kwargs))
        return workspace.refresh_workspace_plan(service, date, **kwargs)

    service.refresh_workspace_plan = persist_once
    original_run_owner = dispatch._run_owner_branches

    class SimulatedProcessTermination(BaseException):
        pass

    def interrupt_after_original_owner(*args, **kwargs):
        original_run_owner(*args, **kwargs)
        raise SimulatedProcessTermination()

    monkeypatch.setattr(dispatch, "_run_owner_branches", interrupt_after_original_owner)
    with pytest.raises(SimulatedProcessTermination):
        dispatch.execute_bound_daily_cycle(service, DATE, sha)

    saved_product = workspace._read_plan(service.store, DATE)
    assert saved_product is not None
    saved_attempt = service.store._read(service.store.root / "workspace_plan_runs" / DATE /
                                        (saved_product["run_id"] + ".json"))
    product_bytes = (service.store.root / "workspace_plans" / DATE /
                     (saved_product["run_id"] + ".json")).read_bytes()
    attempt_bytes = (service.store.root / "workspace_plan_runs" / DATE /
                     (saved_product["run_id"] + ".json")).read_bytes()
    monkeypatch.setattr(dispatch, "_run_owner_branches", original_run_owner)

    recovered = dispatch.execute_bound_daily_cycle(service, DATE, sha)
    assert len(owner_calls) == 1
    assert recovered["status"] == "PARTIAL"
    assert recovered["branch"] == "SAME_DAY_CATCHUP"
    assert recovered["plan_result"]["run_id"] == saved_product["run_id"]
    assert recovered["parent_trigger_receipt"]["owner_readback_status"] == "VERIFIED"
    assert recovered["parent_trigger_receipt"]["owner_attempt_sha256"] == saved_attempt["sha256"]
    assert (service.store.root / "workspace_plans" / DATE /
            (saved_product["run_id"] + ".json")).read_bytes() == product_bytes
    assert (service.store.root / "workspace_plan_runs" / DATE /
            (saved_product["run_id"] + ".json")).read_bytes() == attempt_bytes
    dispatch_ref = recovered["dispatch_receipt"]
    terminal = service.store._read(service.store.root / dispatch_ref["path"])
    assert terminal["state"] == "COMPLETED"
    assert terminal["response"]["plan_result"]["run_id"] == saved_product["run_id"]


def test_failed_dispatch_backoff_does_not_call_owner_again(tmp_path, monkeypatch):
    service, sha, _ = bound_service(tmp_path, monkeypatch)
    calls = []
    def broken(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("synthetic")
    service.refresh_workspace_plan = broken
    dispatch.execute_bound_plan_cycle(service, DATE, sha)
    result = dispatch.execute_bound_plan_cycle(service, DATE, sha)
    assert calls == [1]
    assert result["failure_reasons"] == ["PLAN_OWNER_RETRY_BACKOFF"]


def test_tampered_dispatch_receipt_blocks_new_writes(tmp_path, monkeypatch):
    service, sha, _ = bound_service(tmp_path, monkeypatch)
    result = dispatch.execute_bound_plan_cycle(service, DATE, sha)
    path = service.store.root / result["dispatch_receipt"]["path"]
    row = service.store._read(path)
    row["response"]["status"] = "FAILED"
    service.store._write_atomic(path, row)
    with pytest.raises(ValueError, match="DISPATCH_RECEIPT_INVALID"):
        dispatch.execute_bound_plan_cycle(service, DATE, sha)
    assert len(service.calls) == 1


def test_real_plan_owner_duplicate_keeps_single_product_and_same_attempt(tmp_path, monkeypatch):
    service, sha, _ = bound_service(tmp_path, monkeypatch)
    assessed = assessed_projection(tmp_path, monkeypatch, now=PREOPEN)
    def current(*args, **kwargs):
        return deepcopy(assessed)
    monkeypatch.setattr(workspace, "get_workspace", current)
    monkeypatch.setattr(workspace, "_now", lambda: (PREOPEN + timedelta(seconds=1)).isoformat())
    owner_calls = []
    def refresh_once(date, **kwargs):
        owner_calls.append((date, kwargs))
        return workspace.refresh_workspace_plan(service, date, **kwargs)
    service.refresh_workspace_plan = refresh_once
    first = dispatch.execute_bound_plan_cycle(service, DATE, sha)
    monkeypatch.setattr(dispatch, "clock_now", lambda: PREOPEN + timedelta(seconds=2))
    second = dispatch.execute_bound_plan_cycle(service, DATE, sha)
    assert first["parent_trigger_receipt"]["owner_readback_status"] == "VERIFIED"
    assert second["plan_result"]["owner_product_status"] == first["plan_result"]["owner_product_status"]
    assert second["plan_result"]["run_id"] == first["plan_result"]["run_id"]
    assert second["plan_result"]["owner_attempt_sha256"] == first["plan_result"]["owner_attempt_sha256"]
    assert second["dispatch_receipt"] == first["dispatch_receipt"]
    assert len(owner_calls) == 1
    products = [path for path in (service.store.root / "workspace_plans" / DATE).glob("*.json")
                if path.name != "latest.json"]
    assert len(products) == 1


@pytest.mark.parametrize("now,kind", [(MORNING, "SCHEDULED_MORNING"), (PREOPEN, "SCHEDULED_PREOPEN")])
def test_bound_client_server_wire_preserves_exact_owner_receipt(tmp_path, monkeypatch, now, kind):
    service, _, path = bound_service(tmp_path, monkeypatch, now=now)
    from urllib.parse import parse_qs, urlparse
    calls = []
    class ExistingApiTransport:
        def __init__(self, host, port, timeout):
            assert (host, port) == ("127.0.0.1", 8873)
        def request(self, method, target, **kwargs):
            assert method == "POST"
            parsed = urlparse(target)
            assert parsed.path == "/api/v4/manager/research/workspace/scheduled-cycle"
            query = parse_qs(parsed.query)
            calls.append(target)
            self.body = json.dumps(dispatch.execute_bound_plan_cycle(
                service, query["date"][0], query["binding_sha256"][0])).encode()
        def getresponse(self):
            return SimpleNamespace(status=200, getheader=lambda *args: "application/json", read=lambda *args: self.body)
        def close(self): pass
    monkeypatch.setattr(dispatch.http.client, "HTTPConnection", ExistingApiTransport)
    result = dispatch.request_bound_plan_cycle(path, DATE)
    assert len(calls) == 1
    assert result["status"] == "PARTIAL"
    assert result["plan_result"]["execution_kind"] == kind
    assert result["parent_trigger_receipt"]["owner_attempt_run_id"] == result["plan_result"]["run_id"]
    assert result["dispatch_receipt"]["status"] == "READBACK_VERIFIED"


def test_daily_client_has_more_transport_headroom_than_legacy_client(tmp_path, monkeypatch):
    _, _, path = bound_service(tmp_path, monkeypatch, now=MORNING)
    value = json.loads(path.read_bytes())
    value["daily_automation"] = {"enabled": True,
        "same_day_catchup_slots_local": ["10:00", "12:30", "15:45", "18:30", "22:30"],
        "us_mapping_budget_seconds": 5, "max_attempts_per_target_date": 5,
        "status": "PROPOSAL_ONLY"}
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(dispatch, "clock_now", lambda: MORNING)
    timeouts = []

    class BoundedTransport:
        def __init__(self, host, port, timeout):
            timeouts.append(timeout)
        def request(self, *_args, **_kwargs):
            raise OSError("synthetic transport boundary")
        def close(self):
            pass

    monkeypatch.setattr(dispatch.http.client, "HTTPConnection", BoundedTransport)
    dispatch.request_bound_daily_cycle(path, DATE)
    dispatch.request_bound_plan_cycle(path, DATE)
    assert timeouts == [40.0, 35.0]


def test_worker_plan_only_uses_bound_rpc_and_never_builds_collection_service(tmp_path, monkeypatch, capsys):
    _, _, path = bound_service(tmp_path, monkeypatch, now=MORNING)
    value = json.loads(path.read_bytes())
    value.update(plan_material_refresh_only=True, announcement_collection_enabled=False)
    monkeypatch.setattr(supervisor, "load_binding", lambda *args: value)
    monkeypatch.chdir(cycle.APP_ROOT)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return MORNING
    monkeypatch.setattr(cycle, "datetime", Clock)
    calls = []
    monkeypatch.setattr(dispatch, "request_bound_plan_cycle",
        lambda binding, target: calls.append((binding, target)) or {"status": "PARTIAL"})
    assert cycle.main(["--binding", str(path)]) == 0
    assert calls == [(str(path), DATE)]
    result = json.loads(capsys.readouterr().out)
    assert result["announcement_network_requests"] == 0
    assert result["status"] == "PARTIAL"


@pytest.mark.parametrize("now,kind,cutoff", [
    (MORNING, "SCHEDULED_MORNING", MORNING.replace(hour=9, minute=25)),
    (PREOPEN, "SCHEDULED_PREOPEN", PREOPEN.replace(minute=30)),
])
def test_slow_us_preparation_cannot_consume_plan_window(tmp_path, monkeypatch, now, kind, cutoff):
    service, sha, _ = bound_service(tmp_path, monkeypatch, now=now)
    service._workspace_us_market_reader = object()
    clock = {"now": now}
    us_calls = []
    def slow_preparation(*args, **kwargs):
        us_calls.append(1)
        clock["now"] = cutoff + timedelta(seconds=31)
        raise TimeoutError("synthetic US latency beyond both the owner window and RPC budget")
    service.refresh_us_mapping_research = slow_preparation
    monkeypatch.setattr(dispatch, "clock_now", lambda: clock["now"])
    assessed = assessed_projection(tmp_path, monkeypatch, now=now)
    monkeypatch.setattr(workspace, "get_workspace", lambda *args, **kwargs: deepcopy(assessed))
    def owner_completion_clock():
        clock["now"] = now + timedelta(seconds=1)
        return clock["now"].isoformat()
    monkeypatch.setattr(workspace, "_now", owner_completion_clock)
    service.refresh_workspace_plan = lambda date, **kwargs: workspace.refresh_workspace_plan(service, date, **kwargs)
    result = dispatch.execute_bound_plan_cycle(service, DATE, sha)
    assert us_calls == []
    assert result["status"] == "PARTIAL"
    assert result["plan_result"]["execution_kind"] == kind
    assert result["parent_trigger_receipt"]["owner_readback_status"] == "VERIFIED"
    saved = workspace._read_plan(service.store, DATE)
    assert saved["run_id"] == result["plan_result"]["run_id"]
    assert datetime.fromisoformat(saved["generated_at"]) < cutoff
    dispatch_row = service.store._read(service.store.root / result["dispatch_receipt"]["path"])
    assert dispatch_row["state"] == "COMPLETED"
    assert dispatch_row["response"]["us_mapping_research"]["execution_attempted"] is False
    clock["now"] = cutoff
    with pytest.raises(ValueError, match="TARGET_DATE_OR_WINDOW_MISMATCH"):
        dispatch.execute_bound_plan_cycle(service, DATE, sha)
    assert workspace._read_plan(service.store, DATE)["run_id"] == saved["run_id"]


def test_repeated_plan_triggers_do_not_launch_us_preparation_or_retries(tmp_path, monkeypatch):
    service, sha, _ = bound_service(tmp_path, monkeypatch)
    service._workspace_us_market_reader = object()
    calls = []
    def broken_us(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("synthetic independent US failure")
    service.refresh_us_mapping_research = broken_us
    rows = []
    for seconds in (0, 30, 60, 120, 178):
        monkeypatch.setattr(dispatch, "clock_now", lambda seconds=seconds: PREOPEN + timedelta(seconds=seconds))
        rows.append(dispatch.execute_bound_plan_cycle(service, DATE, sha))
    assert calls == []
    assert len(service.calls) == 1
    assert len({row["dispatch_receipt"]["sha256"] for row in rows}) == 1
    assert all(row["us_mapping_research"]["status"] == "NOT_ATTEMPTED" for row in rows)
    assert all(row["us_mapping_research"]["execution_attempted"] is False for row in rows)
    assert all(row["us_mapping_research"]["gaps"] == ["US_MAPPING_REQUIRES_INDEPENDENT_OWNER_DISPATCH"]
               for row in rows)
    assert rows[-1]["status"] == "PARTIAL"


def test_separate_owner_instances_share_kernel_admission_and_single_product(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    service, sha, _ = bound_service(tmp_path, monkeypatch)
    second = SimpleNamespace(
        store=ManagerResearchStore(service.store.root),
        _workspace_security_master_root=service._workspace_security_master_root,
        _existing_research_source=None, _workspace_us_market_reader=None,
        _workspace_reads=ReadCoordinator())
    assessed = assessed_projection(tmp_path, monkeypatch, now=PREOPEN)
    def current(*args, **kwargs):
        return deepcopy(assessed)
    monkeypatch.setattr(workspace, "get_workspace", current)
    clock = {"now": PREOPEN}
    monkeypatch.setattr(dispatch, "clock_now", lambda: clock["now"])
    def owner_completion_clock():
        clock["now"] = PREOPEN + timedelta(seconds=1)
        return clock["now"].isoformat()
    monkeypatch.setattr(workspace, "_now", owner_completion_clock)
    service.refresh_workspace_plan = lambda date, **kwargs: workspace.refresh_workspace_plan(service, date, **kwargs)
    second.refresh_workspace_plan = lambda date, **kwargs: workspace.refresh_workspace_plan(second, date, **kwargs)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda owner: dispatch.execute_bound_plan_cycle(owner, DATE, sha), [service, second]))
    assert rows[0]["plan_result"]["run_id"] == rows[1]["plan_result"]["run_id"]
    assert all(row["parent_trigger_receipt"]["owner_readback_status"] == "VERIFIED" for row in rows)
    assert rows[0]["dispatch_receipt"] == rows[1]["dispatch_receipt"]
    assert len(list((service.store.root / "workspace_plan_dispatch" / DATE).glob("*/*.json"))) == 1
