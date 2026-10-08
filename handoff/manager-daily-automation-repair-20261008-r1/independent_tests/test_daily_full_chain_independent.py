"""Independent daily-chain probes over the exact local owners.

All data is synthetic and offline. One test attempts the actual renderer and
binding validator. Current source inventory is missing required `apps/__init__.py`,
so the owner-path probes use an explicitly unvalidated synthetic binding and
patch only the validator boundary. To isolate the known eager scheduling import
gap, the supervisor leaf is loaded by filename; the missing Stage dependency is
not stubbed or treated as a successful clean import.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from threading import Event
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REVIEWER_DIR = Path(__file__).resolve().parent
if str(REVIEWER_DIR) not in sys.path:
    sys.path.insert(0, str(REVIEWER_DIR))
from _source_root import source_root  # noqa: E402

REPO = source_root(__file__)
for import_root in (REPO, REPO / "upstreams"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))
TESTS = REPO / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
HK = ZoneInfo("Asia/Hong_Kong")


def _load_exact(name: str, path: Path):
    current = sys.modules.get(name)
    if current is not None:
        return current
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


supervisor = _load_exact(
    "infrastructure.scheduling.manager_announcement_supervisor",
    REPO / "infrastructure/scheduling/manager_announcement_supervisor.py",
)
supervisor_fixture = _load_exact(
    "reviewer_test_manager_announcement_supervisor",
    TESTS / "test_manager_announcement_supervisor.py",
)
announcement_fixture = _load_exact(
    "reviewer_test_manager_announcement_parity_20261008",
    TESTS / "test_manager_announcement_parity_20261008.py",
)

from ops import render_manager_announcement_binding as renderer  # noqa: E402
from ops import run_manager_announcement_cycle as cycle  # noqa: E402
from v4.manager_research import plan_owner_dispatch as dispatch  # noqa: E402
from v4.manager_research import workspace as workspace_owner  # noqa: E402
from v4.manager_research import workspace_history  # noqa: E402
from v4.manager_research.service import ManagerResearchJobService  # noqa: E402
from v4.manager_research.store import ManagerResearchStore  # noqa: E402


DAILY_SLOTS = ["10:00", "12:30", "15:45", "18:30", "22:30"]
PLAN = {"enabled": True, "start_local": "16:00", "end_local": "23:00",
        "max_attempts_per_target_date": 3, "retry_backoff_seconds": 600,
        "status": "PROPOSAL_ONLY"}
PREOPEN = {"enabled": True, "lead_seconds": 180, "status": "PROPOSAL_ONLY"}
MORNING_CONFIG = {"enabled": True, "interval_seconds": 300, "status": "PROPOSAL_ONLY"}


def _write_same_root_synthetic_canary(tmp_path: Path, state_root: Path) -> Path:
    """Write a synthetic offline canary bound to this exact app root."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    target, run_id = "20260929", "1" * 32
    product_sha, identity = "2" * 64, "3" * 64
    owner = "ManagerResearchJobService.refresh_workspace_plan"
    evidence = {}
    product = {"status": "CURRENT", "run_id": run_id, "sha256": product_sha,
        "original_owner": owner, "execution_kind": "MANUAL_REFRESH"}
    for name, method, url in (
        ("refresh", "POST", f"http://127.0.0.1:8873/api/v4/manager/research/workspace/refresh?date={target}"),
        ("readback", "GET", f"http://127.0.0.1:8873/api/v4/manager/research/workspace?date={target}"),
    ):
        body_path = tmp_path / f"{name}-body.json"
        body = b"{}"
        body_path.write_bytes(body)
        readback = {"target_trade_date": target, "plan_product": product}
        if name == "refresh":
            readback.update({
                "store_latest_matches_http_plan_product": True,
                "persisted_store": {"target_trade_date": target, "run_id": run_id,
                    "product_sha256": product_sha, "execution_kind": "MANUAL_REFRESH",
                    "owner": owner, "RESEARCH_ONLY": True, "production_allowed": False,
                    "buy_gate_updated": False, "orders_sent": False},
                "workspace_plan_attempt": {"execution_kind": "MANUAL_REFRESH", "state": "PARTIAL"},
                "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                    "buy_gate_updated": False, "orders_sent": False},
            })
        receipt = {"schema_version": "manager_daily_chain.manual_refresh_receipt.v1"
                if name == "refresh" else "manager_daily_chain.http_readback_receipt.v1",
            "http_status": 200, "content_type": "application/json",
            "request": {"method": method, "url": url},
            "response": {"path": str(body_path), "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest()},
            "readback": readback}
        receipt_path = tmp_path / f"{name}-receipt.json"
        raw_receipt = json.dumps(receipt, sort_keys=True).encode()
        receipt_path.write_bytes(raw_receipt)
        evidence[name] = {"path": str(receipt_path),
            "sha256": hashlib.sha256(raw_receipt).hexdigest()}
    canary = {
        "schema_version": supervisor.PLAN_CANARY_SCHEMA,
        "status": supervisor.PLAN_CANARY_STATUS,
        "app_root": str(REPO.resolve()), "manager_state_root": str(state_root.resolve()),
        "policy_status": "PROPOSAL_ONLY", "scope": supervisor.PLAN_CANARY_NEXT_SCOPE,
        "plan_material_refresh_only": True,
        "candidate_binding_app_root": str(REPO.resolve()),
        "owner_execution_app_root": str(REPO.resolve()),
        "execution_mode": "HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK",
        "hook_executed": False, "announcement_collection_enabled": False,
        "announcement_network_requests": 0, "research_only": True,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "target_trade_date": target, "run_id": run_id,
        "product_sha256": product_sha, "input_identity": identity,
        "execution_kind": "MANUAL_REFRESH", "owner": owner,
        "owner_attempt_state": "PARTIAL", "formal_recommendation_count": 0,
        "owner_evidence": evidence,
    }
    path = (tmp_path / "plan-canary-same-root.json").resolve()
    path.write_text(json.dumps(canary, sort_keys=True), encoding="utf-8")
    return path


def _render_daily_binding(tmp_path: Path, *, state_root: Path | None = None,
                          master_root: Path | None = None) -> tuple[dict, Path, str]:
    state = (state_root or (tmp_path / "manager-state")).resolve()
    state.mkdir(parents=True, exist_ok=True)
    master = (master_root or (tmp_path / "security-master")).resolve()
    master.mkdir(parents=True, exist_ok=True)
    canary = _write_same_root_synthetic_canary(tmp_path, state)
    binding_path = (tmp_path / "daily-binding.json").resolve()
    status = renderer.main([
        "--app-root", str(REPO.resolve()),
        "--manager-state-root", str(state),
        "--security-master-root", str(master),
        "--python", sys.executable,
        "--output", str(binding_path),
        "--enabled", "--plan-material-refresh-only", "--daily-automation",
        "--plan-activation-receipt", str(canary),
    ])
    assert status == 0
    raw = binding_path.read_bytes()
    value = json.loads(raw)
    assert supervisor.validate_binding(value, REPO.resolve()) == value
    return value, binding_path, hashlib.sha256(raw).hexdigest()


def _actual_daily_client(service: ManagerResearchJobService) -> TestClient:
    from apps.api.v35_api import manager_research_router
    app = FastAPI()
    app.include_router(manager_research_router.create_manager_research_router(service))
    return TestClient(app)


def _unvalidated_daily_binding(tmp_path: Path) -> tuple[dict, Path, str]:
    """Synthetic dispatch binding for owner-path tests when source inventory blocks renderer."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    state = (tmp_path / "daily-state").resolve()
    master = (tmp_path / "daily-master").resolve()
    state.mkdir(parents=True, exist_ok=True)
    master.mkdir(parents=True, exist_ok=True)
    value = {
        "schema_version": supervisor.BINDING_SCHEMA, "enabled": True,
        "policy_status": "PROPOSAL_ONLY", "policy": "BALANCED_V1",
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "research_only": True, "app_root": str(REPO.resolve()),
        "manager_state_root": str(state), "security_master_root": str(master),
        "python": sys.executable, "python_resolved": str(Path(sys.executable).resolve()),
        "python_sha256": hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
        "plan_material_refresh_only": True, "announcement_collection_enabled": False,
        "preopen_plan": PREOPEN, "morning_plan": MORNING_CONFIG,
        "plan_material_refresh": PLAN,
        "daily_automation": {"enabled": True,
            "same_day_catchup_slots_local": list(DAILY_SLOTS),
            "us_mapping_budget_seconds": 5, "max_attempts_per_target_date": 5,
            "status": "PROPOSAL_ONLY"},
    }
    path = (tmp_path / "unvalidated-daily-binding.json").resolve()
    raw = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(raw)
    return value, path, hashlib.sha256(raw).hexdigest()


def _accept_test_binding(monkeypatch):
    # Functional owner-chain probes still execute the exact RPC, dispatch,
    # service and store code. This is a synthetic dependency-boundary binding;
    # actual renderer/validator coverage remains the separate test above.
    monkeypatch.setattr(supervisor, "validate_binding", lambda value, **_: value)


def _import_reviewed_product(service, *, target="20261008"):
    product, registration = announcement_fixture._fixture(service, target=target)
    client = announcement_fixture._client(service)
    imported = announcement_fixture._import(client, registration)
    assert imported["consumption_validation"]["validation_status"] == "VERIFIED"
    return product, registration, client


def _freeze_api_clock(monkeypatch, when: datetime) -> None:
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return when.astimezone(tz) if tz else when.replace(tzinfo=None)
    monkeypatch.setattr(announcement_fixture.api, "datetime", Clock)
    announcement_fixture.NOW = when


def test_actual_renderer_and_validator_enable_morning_and_daily_catchup(tmp_path):
    value, binding_path, _ = _render_daily_binding(tmp_path)
    assert Path(value["app_root"]) == REPO.resolve()
    assert value["morning_plan"] == MORNING_CONFIG
    assert value["daily_automation"]["enabled"] is True
    assert value["daily_automation"]["same_day_catchup_slots_local"] == DAILY_SLOTS

    frozen = datetime(2026, 10, 8, 7, 0, tzinfo=HK)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(cycle, "datetime", Clock)
        monkeypatch.chdir(REPO)
        # The actual worker entry, with dry-run, must resolve a morning target
        # from the rendered binding without performing a request or write.
        assert cycle.main(["--binding", str(binding_path), "--dry-run"]) == 0
    finally:
        monkeypatch.undo()


def test_daily_rpc_consumes_original_reviewed_import_and_preserves_preopen_history(
        tmp_path, monkeypatch):
    value, binding_path, binding_sha = _unvalidated_daily_binding(tmp_path)
    _accept_test_binding(monkeypatch)
    state = Path(value["manager_state_root"])
    service = announcement_fixture._FixtureService(state)
    service._workspace_security_master_root = Path(value["security_master_root"])
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(binding_path))
    monkeypatch.setattr(dispatch, "clock_now", lambda: datetime(2026, 10, 8, 10, 0, tzinfo=HK))

    preopen_at = datetime(2026, 10, 8, 9, 27, tzinfo=HK)
    monkeypatch.setattr(workspace_owner, "_now", lambda: "2026-10-08T01:28:00+00:00")
    preopen = service.refresh_workspace_plan("20261008", execution_kind="SCHEDULED_PREOPEN",
        now=preopen_at, deadline=datetime(2026, 10, 8, 9, 30, tzinfo=HK))
    old_run = preopen["plan_product"]["run_id"]
    old_path = state / "workspace_plans" / "20261008" / f"{old_run}.json"
    old_bytes = old_path.read_bytes()
    before_read_at = datetime(2026, 10, 8, 9, 28, tzinfo=HK)
    before = service.get_workspace("20261008", view="dynamic", now=before_read_at)

    imported_at = datetime(2026, 10, 8, 9, 45, tzinfo=HK)
    _freeze_api_clock(monkeypatch, imported_at)
    product, registration, import_client = _import_reviewed_product(service)
    assert registration["product_sha256"] == product["sha256"]
    after_import = service.get_workspace("20261008", view="dynamic", now=imported_at)
    # The exact ordinary GET must replay the sealed pre-open cutoff. An owner
    # import after 09:27 cannot be projected into that immutable plan, even
    # though a fresh evaluation at 09:45 can consume it.
    assert after_import["plan_product"]["run_id"] == old_run
    assert after_import["plan_product"]["status"] == "CURRENT"
    assert after_import["input_identity"] == before["input_identity"]
    assert product["sha256"] not in after_import["announcement_reviewed_analysis"]["consumed_product_sha256s"]
    delayed = next(item for item in after_import["announcement_reviewed_analysis"]["products"]
        if item.get("product_sha256") == product["sha256"])
    assert delayed["status"] == "NOT_CONSUMED_AFTER_CUTOFF"
    assert old_path.read_bytes() == old_bytes

    # Exercise the original read owner with saved-plan use disabled to prove
    # the source is valid and readable at its real later availability time.
    fresh = workspace_owner.get_workspace(service, "20261008", view="dynamic",
        now=imported_at, include_saved=False)
    assert fresh["input_identity"] != before["input_identity"]
    assert fresh["announcement_reviewed_analysis"]["status"] == "READY"
    assert product["sha256"] in fresh["announcement_reviewed_analysis"]["consumed_product_sha256s"]

    now = datetime(2026, 10, 8, 10, 5, tzinfo=HK)
    monkeypatch.setattr(workspace_owner, "_now", lambda: "2026-10-08T02:00:01+00:00")
    _freeze_api_clock(monkeypatch, now)
    monkeypatch.setattr(dispatch, "clock_now", lambda: datetime(2026, 10, 8, 10, 0, tzinfo=HK))
    with _actual_daily_client(service) as client:
        response = client.post("/api/v4/manager/research/workspace/daily-cycle",
            params={"date": "20261008", "binding_sha256": binding_sha})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["branch"] == "SAME_DAY_CATCHUP"
        assert result["plan_result"]["execution_kind"] == "MANUAL_REFRESH"
        assert result["plan_result"]["execution_context"]["timing"] == "LATE_CATCHUP"
        assert result["plan_result"]["execution_context"]["natural_run_verified"] is False
        assert result["parent_trigger_receipt"]["owner_readback_status"] == "VERIFIED"
        assert result["plan_result"]["run_id"] != old_run
        assert result["plan_result"]["product_sha256"]
        assert old_path.read_bytes() == old_bytes

        # This is the same dynamic page route used by the ordinary consumer.
        page = client.get("/api/v4/manager/research/workspace",
            params={"date": "20261008", "view": "dynamic"})
        assert page.status_code == 200, page.text
        page_value = page.json()
        assert page_value["plan_product"]["run_id"] == result["plan_result"]["run_id"]
        assert page_value["announcement_reviewed_analysis"]["status"] == "READY"
        assert product["sha256"] in page_value["announcement_reviewed_analysis"]["consumed_product_sha256s"]

    # The latest dynamic late catch-up is ineligible for history. The selector
    # should still find the immutable, qualified pre-open product.
    boundary = workspace_history.boundary_context("20261008")
    selected = workspace_history.select_plan(service.store, "20261008", boundary)
    assert selected is not None and selected["run_id"] == old_run
    assert old_path.read_bytes() == old_bytes
    import_client.close()
    service.close()


def test_manual_refresh_http_route_keeps_retro_execution_truth_separate_from_target_cutoff(
        tmp_path, monkeypatch):
    state = tmp_path / "manual-state"
    service = announcement_fixture._FixtureService(state)
    actual = datetime(2026, 10, 9, 10, 0, tzinfo=HK)
    _freeze_api_clock(monkeypatch, actual)
    monkeypatch.setattr(workspace_owner, "_now", lambda: "2026-10-09T02:00:01+00:00")
    with announcement_fixture._client(service) as client:
        response = client.post("/api/v4/manager/research/workspace/refresh",
            params={"date": "20261008"}, headers={"Origin": "http://testserver"})
    assert response.status_code == 200, response.text
    saved = workspace_owner._read_plan(service.store, "20261008")
    assert saved["execution_kind"] == "MANUAL_REFRESH"
    assert saved["execution_context"]["trigger_kind"] == "MANUAL"
    assert saved["execution_context"]["timing"] == "RETROSPECTIVE"
    assert saved["execution_context"]["natural_run_verified"] is False
    started = datetime.fromisoformat(saved["execution_context"]["started_at"])
    generated = datetime.fromisoformat(saved["generated_at"])
    plan_cutoff = datetime.fromisoformat(saved["workspace"]["plan_context"]["research_cutoff"])
    assert started.astimezone(HK).date() == actual.date()
    assert generated.astimezone(HK).date() == actual.date()
    assert plan_cutoff.astimezone(HK).date() == actual.date()
    assert workspace_history.select_plan(
        service.store, "20261008", workspace_history.boundary_context("20261008")) is None
    service.close()


@pytest.mark.parametrize("branch,slot,admission", [
    ("MORNING", "20261008T0700", datetime(2026, 10, 8, 7, 0, 58, tzinfo=HK)),
    ("SAME_DAY_CATCHUP", "20261008T1000", datetime(2026, 10, 8, 10, 0, 58, tzinfo=HK)),
])
def test_real_daily_dispatch_carries_admitted_minute_across_bounded_us_prep(
        tmp_path, monkeypatch, branch, slot, admission):
    value, binding_path, binding_sha = _unvalidated_daily_binding(tmp_path)
    _accept_test_binding(monkeypatch)
    service = announcement_fixture._FixtureService(value["manager_state_root"])
    service._workspace_security_master_root = Path(value["security_master_root"])
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(binding_path))
    clock = {"now": admission}
    monkeypatch.setattr(dispatch, "clock_now", lambda: clock["now"])
    us_calls = []
    def bounded_synthetic_us_owner(date, **kwargs):
        us_calls.append((date, kwargs))
        clock["now"] = admission + timedelta(seconds=3)
        return {"schema_version": "v4.manager_research.us_mapping_research_daily.v1",
            "status": "FAILED", "target_trade_date": date,
            "execution_status": "SYNTHETIC_SOURCE_GAP", "matches": [],
            "coverage": {"matched_us_symbol_count": None},
            "gaps": ["SYNTHETIC_SOURCE_GAP"], "RESEARCH_ONLY": True,
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    service.refresh_us_mapping_research = bounded_synthetic_us_owner
    # Let the real store-backed original plan owner build and publish. Only
    # its source reads are fixture-empty in this service, so it remains partial.
    monkeypatch.setattr(workspace_owner, "_now", lambda: clock["now"].astimezone(HK).isoformat())
    result = dispatch.execute_bound_daily_cycle(service, "20261008", binding_sha)
    assert result["branch"] == branch
    assert result["plan_result"]["target_trade_date"] == "20261008"
    assert result["plan_result"].get("execution_kind") == (
        "SCHEDULED_MORNING" if branch == "MORNING" else "MANUAL_REFRESH"), result
    assert result["parent_trigger_receipt"]["owner_readback_status"] == "VERIFIED"
    assert len(us_calls) == 1
    assert us_calls[0][1]["timeout_seconds"] == 5
    assert clock["now"] == admission + timedelta(seconds=3)
    service.close()


def test_same_day_catchup_budget_does_not_count_morning_receipts(tmp_path):
    value, binding_path, _ = _unvalidated_daily_binding(tmp_path)
    service = SimpleNamespace(store=ManagerResearchStore(value["manager_state_root"]))
    date = "20261008"
    sha = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    for index, minute in enumerate((0, 5, 10, 15, 20), 1):
        slot = f"{date}T07{minute:02d}"
        identity = dispatch._parent_trigger_identity(date, date, "MORNING", sha,
            scheduled_slot=slot)
        row = dispatch._seal_dispatch({"schema_version": dispatch.DISPATCH_SCHEMA,
            "state": "COMPLETED", "target_trade_date": date,
            "parent_trigger_identity": identity, "sequence": 1,
            "started_at": f"2026-10-08T07:{minute:02d}:00+08:00",
            "finished_at": f"2026-10-08T07:{minute:02d}:01+08:00",
            "response": {"status": "PARTIAL"}, "RESEARCH_ONLY": True,
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False})
        path = service.store.root / "workspace_plan_dispatch" / date / identity["trigger_id"] / "0001.json"
        service.store._write_atomic(path, row)
    assert dispatch._daily_catchup_attempt_count(service, date) == 0

    for index, slot_time in enumerate(DAILY_SLOTS, 1):
        hh, mm = slot_time.split(":")
        identity = dispatch._parent_trigger_identity(date, date, "SAME_DAY_CATCHUP", sha,
            scheduled_slot=f"{date}T{hh}{mm}")
        row = dispatch._seal_dispatch({"schema_version": dispatch.DISPATCH_SCHEMA,
            "state": "COMPLETED", "target_trade_date": date,
            "parent_trigger_identity": identity, "sequence": 1,
            "started_at": f"2026-10-08T{hh}:{mm}:00+08:00",
            "finished_at": f"2026-10-08T{hh}:{mm}:01+08:00",
            "response": {"status": "PARTIAL"}, "RESEARCH_ONLY": True,
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False})
        path = service.store.root / "workspace_plan_dispatch" / date / identity["trigger_id"] / "0001.json"
        service.store._write_atomic(path, row)
    assert dispatch._daily_catchup_attempt_count(service, date) == 5


def test_two_consecutive_hk_sessions_skip_native_holiday_without_cross_date_plan_reuse(
        tmp_path, monkeypatch):
    value, binding_path, binding_sha = _unvalidated_daily_binding(tmp_path)
    _accept_test_binding(monkeypatch)
    service = announcement_fixture._FixtureService(value["manager_state_root"])
    service._workspace_security_master_root = Path(value["security_master_root"])
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(binding_path))
    clock = {"now": datetime(2026, 10, 8, 10, 0, tzinfo=HK)}
    monkeypatch.setattr(dispatch, "clock_now", lambda: clock["now"])
    monkeypatch.setattr(workspace_owner, "_now", lambda: clock["now"].astimezone(HK).isoformat())
    owner_calls = []
    original_owner = service.refresh_workspace_plan
    def counted_owner(date, **kwargs):
        owner_calls.append((date, kwargs.get("execution_kind")))
        return original_owner(date, **kwargs)
    service.refresh_workspace_plan = counted_owner

    first = dispatch.execute_bound_daily_cycle(service, "20261008", binding_sha)
    first_saved = workspace_owner._read_plan(service.store, "20261008")
    clock["now"] = datetime(2026, 10, 9, 10, 0, tzinfo=HK)
    second = dispatch.execute_bound_daily_cycle(service, "20261009", binding_sha)
    second_saved = workspace_owner._read_plan(service.store, "20261009")
    assert first["target_trade_date"] == "20261008"
    assert second["target_trade_date"] == "20261009"
    assert first_saved["run_id"] != second_saved["run_id"]
    assert first_saved["target_trade_date"] == "20261008"
    assert second_saved["target_trade_date"] == "20261009"

    before_holiday_calls = len(owner_calls)
    clock["now"] = datetime(2026, 10, 10, 10, 0, tzinfo=HK)
    with pytest.raises(ValueError, match="TARGET_DATE_OR_WINDOW_MISMATCH"):
        dispatch.execute_bound_daily_cycle(service, "20261010", binding_sha)
    assert len(owner_calls) == before_holiday_calls

    clock["now"] = datetime(2026, 10, 12, 10, 0, tzinfo=HK)
    monday = dispatch.execute_bound_daily_cycle(service, "20261012", binding_sha)
    monday_saved = workspace_owner._read_plan(service.store, "20261012")
    assert monday["target_trade_date"] == monday_saved["target_trade_date"] == "20261012"
    assert len(owner_calls) == before_holiday_calls + 1
    service.close()


def test_evening_same_date_catchup_runs_one_original_plan_owner_not_two(tmp_path, monkeypatch):
    value, binding_path, binding_sha = _unvalidated_daily_binding(tmp_path)
    _accept_test_binding(monkeypatch)
    service = announcement_fixture._FixtureService(value["manager_state_root"])
    service._workspace_security_master_root = Path(value["security_master_root"])
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(binding_path))
    clock = datetime(2026, 10, 8, 18, 30, tzinfo=HK)
    monkeypatch.setattr(dispatch, "clock_now", lambda: clock)
    monkeypatch.setattr(workspace_owner, "_now", lambda: clock.isoformat())
    calls = []
    original_owner = service.refresh_workspace_plan
    def counted_owner(date, **kwargs):
        calls.append(kwargs.get("execution_kind"))
        return original_owner(date, **kwargs)
    service.refresh_workspace_plan = counted_owner
    monkeypatch.setattr(cycle, "run_next_hk_session_plan_material_refresh",
        lambda *a, **k: pytest.fail("same-date catchup must not also run next-session owner"))

    result = dispatch.execute_bound_daily_cycle(service, "20261008", binding_sha)
    assert result["branch"] == "SAME_DAY_CATCHUP"
    assert calls == ["MANUAL_REFRESH"]
    service.close()


def test_same_slot_restart_replays_completed_dispatch_without_rewriting_plan_owner(
        tmp_path, monkeypatch):
    value, binding_path, binding_sha = _unvalidated_daily_binding(tmp_path)
    _accept_test_binding(monkeypatch)
    state = Path(value["manager_state_root"])
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(binding_path))
    monkeypatch.setattr(dispatch, "clock_now", lambda: datetime(2026, 10, 8, 10, 0, tzinfo=HK))
    monkeypatch.setattr(workspace_owner, "_now", lambda: "2026-10-08T10:00:02+08:00")

    calls = []
    first_service = announcement_fixture._FixtureService(state)
    first_service._workspace_security_master_root = Path(value["security_master_root"])
    first_owner = first_service.refresh_workspace_plan
    def count_first_owner(*args, **kwargs):
        calls.append("first-process")
        return first_owner(*args, **kwargs)
    first_service.refresh_workspace_plan = count_first_owner
    first = dispatch.execute_bound_daily_cycle(first_service, "20261008", binding_sha)
    saved = workspace_owner._read_plan(first_service.store, "20261008")
    plan_path = state / "workspace_plans" / "20261008" / f"{saved['run_id']}.json"
    latest_path = state / "workspace_plans" / "20261008" / "latest.json"
    receipt_path = state / first["dispatch_receipt"]["path"]
    plan_bytes, latest_bytes, receipt_bytes = (
        plan_path.read_bytes(), latest_path.read_bytes(), receipt_path.read_bytes())
    first_service.close()

    # A new service instance models an API process restart with the same bound
    # state root and an exact replay of the same phase/slot trigger.
    second_service = announcement_fixture._FixtureService(state)
    second_service._workspace_security_master_root = Path(value["security_master_root"])
    second_owner = second_service.refresh_workspace_plan
    def count_second_owner(*args, **kwargs):
        calls.append("second-process")
        return second_owner(*args, **kwargs)
    second_service.refresh_workspace_plan = count_second_owner
    second = dispatch.execute_bound_daily_cycle(second_service, "20261008", binding_sha)
    assert second["branch"] == "SAME_DAY_CATCHUP"
    assert second["plan_result"]["run_id"] == first["plan_result"]["run_id"]
    assert second["dispatch_receipt"] == first["dispatch_receipt"]
    assert calls == ["first-process"]
    assert plan_path.read_bytes() == plan_bytes
    assert latest_path.read_bytes() == latest_bytes
    assert receipt_path.read_bytes() == receipt_bytes
    second_service.close()


def test_interrupted_dispatch_reconciles_original_owner_commit_after_restart(
        tmp_path, monkeypatch):
    value, binding_path, binding_sha = _unvalidated_daily_binding(tmp_path)
    _accept_test_binding(monkeypatch)
    state = Path(value["manager_state_root"])
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(binding_path))
    now = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
    monkeypatch.setattr(dispatch, "clock_now", lambda: now)
    monkeypatch.setattr(workspace_owner, "_now", lambda: now.isoformat())
    first_service = announcement_fixture._FixtureService(state)
    first_service._workspace_security_master_root = Path(value["security_master_root"])
    calls = []
    original_owner = first_service.refresh_workspace_plan
    def count_owner(*args, **kwargs):
        calls.append("first-process")
        return original_owner(*args, **kwargs)
    first_service.refresh_workspace_plan = count_owner

    original_branch_runner = dispatch._run_owner_branches
    owner_results = []
    class SimulatedProcessTermination(BaseException):
        pass
    def interrupt_after_owner_commit(*args, **kwargs):
        result = original_branch_runner(*args, **kwargs)
        owner_results.append(result)
        raise SimulatedProcessTermination("crash after original owner commit")
    monkeypatch.setattr(dispatch, "_run_owner_branches", interrupt_after_owner_commit)
    with pytest.raises(SimulatedProcessTermination):
        dispatch.execute_bound_daily_cycle(first_service, "20261008", binding_sha)
    assert len(owner_results) == 1 and calls == ["first-process"]
    saved = workspace_owner._read_plan(first_service.store, "20261008")
    assert saved is not None
    old_run = saved["run_id"]
    plan_path = state / "workspace_plans" / "20261008" / f"{old_run}.json"
    plan_bytes = plan_path.read_bytes()
    plan_context = saved["execution_context"]
    assert plan_context["trigger_id"]
    dispatch_dir = state / "workspace_plan_dispatch" / "20261008" / plan_context["trigger_id"]
    started_path = dispatch_dir / "0001.json"
    started = json.loads(started_path.read_text())
    assert started["state"] == "RUNNING"
    assert started["parent_trigger_identity"]["trigger_id"] == plan_context["trigger_id"]
    assert saved["execution_kind"] == "MANUAL_REFRESH"
    first_service.close()

    # Restart with the same slot/binding. A matching committed owner product
    # is deterministic evidence to reconcile; a second owner invocation is a
    # failure, while an ambiguous/mismatched owner product must stay blocked.
    second_service = announcement_fixture._FixtureService(state)
    second_service._workspace_security_master_root = Path(value["security_master_root"])
    def forbidden_owner(*_args, **_kwargs):
        pytest.fail("reconciliation must read the exact original owner product, not rerun it")
    second_service.refresh_workspace_plan = forbidden_owner
    monkeypatch.setattr(dispatch, "_run_owner_branches",
        lambda *_args, **_kwargs: pytest.fail("must not re-enter owner branches during reconciliation"))
    recovered = dispatch.execute_bound_daily_cycle(second_service, "20261008", binding_sha)
    assert recovered["status"] in {"SUCCEEDED", "PARTIAL"}, recovered
    assert recovered["plan_result"]["run_id"] == old_run
    assert recovered["plan_result"]["product_sha256"] == saved["sha256"]
    assert recovered["plan_result"]["execution_context"]["trigger_id"] == plan_context["trigger_id"]
    assert recovered["parent_trigger_receipt"]["owner_readback_status"] == "VERIFIED"
    terminal = json.loads(started_path.read_text())
    assert terminal["state"] == "COMPLETED"
    assert terminal["response"]["plan_result"]["run_id"] == old_run
    assert plan_path.read_bytes() == plan_bytes
    assert workspace_owner._read_plan(second_service.store, "20261008")["run_id"] == old_run
    assert calls == ["first-process"]
    second_service.close()


def test_missing_running_owner_evidence_stays_blocked_but_next_slot_can_continue(
        tmp_path, monkeypatch):
    value, binding_path, binding_sha = _unvalidated_daily_binding(tmp_path)
    _accept_test_binding(monkeypatch)
    state = Path(value["manager_state_root"])
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(binding_path))
    clock = {"now": datetime(2026, 10, 8, 10, 0, tzinfo=HK)}
    monkeypatch.setattr(dispatch, "clock_now", lambda: clock["now"])
    monkeypatch.setattr(workspace_owner, "_now", lambda: clock["now"].isoformat())
    first_service = announcement_fixture._FixtureService(state)
    first_service._workspace_security_master_root = Path(value["security_master_root"])
    owner_calls = []
    real_branch_runner = dispatch._run_owner_branches
    class SimulatedProcessTermination(BaseException):
        pass
    def interrupt_before_owner(*_args, **_kwargs):
        raise SimulatedProcessTermination("crash before original owner");
    monkeypatch.setattr(dispatch, "_run_owner_branches", interrupt_before_owner)
    with pytest.raises(SimulatedProcessTermination):
        dispatch.execute_bound_daily_cycle(first_service, "20261008", binding_sha)
    first_receipt = next((state / "workspace_plan_dispatch" / "20261008").glob("*/0001.json"))
    prior_bytes = first_receipt.read_bytes()
    first_service.close()

    second_service = announcement_fixture._FixtureService(state)
    second_service._workspace_security_master_root = Path(value["security_master_root"])
    def counted_owner(*args, **kwargs):
        owner_calls.append(clock["now"])
        return second_original_owner(*args, **kwargs)
    second_original_owner = second_service.refresh_workspace_plan
    second_service.refresh_workspace_plan = counted_owner
    monkeypatch.setattr(dispatch, "_run_owner_branches", real_branch_runner)
    blocked = dispatch.execute_bound_daily_cycle(second_service, "20261008", binding_sha)
    assert blocked["status"] == "FAILED"
    assert "PLAN_OWNER_RECONCILIATION_REQUIRED" in blocked["failure_reasons"]
    assert owner_calls == []
    assert first_receipt.read_bytes() == prior_bytes
    assert workspace_owner._read_plan(second_service.store, "20261008") is None

    # The next distinct admitted slot is a new bounded trigger and may make
    # progress without repairing or rewriting the ambiguous prior attempt.
    clock["now"] = datetime(2026, 10, 8, 12, 30, tzinfo=HK)
    continued = dispatch.execute_bound_daily_cycle(second_service, "20261008", binding_sha)
    assert continued["branch"] == "SAME_DAY_CATCHUP"
    assert continued["status"] in {"SUCCEEDED", "PARTIAL"}
    assert len(owner_calls) == 1
    assert first_receipt.read_bytes() == prior_bytes
    assert workspace_owner._read_plan(second_service.store, "20261008") is not None
    second_service.close()


def test_later_same_date_slot_keeps_source_membership_while_recording_new_plan_cutoff(
        tmp_path, monkeypatch):
    value, binding_path, binding_sha = _unvalidated_daily_binding(tmp_path)
    _accept_test_binding(monkeypatch)
    service = announcement_fixture._FixtureService(value["manager_state_root"])
    service._workspace_security_master_root = Path(value["security_master_root"])
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(binding_path))
    clock = {"now": datetime(2026, 10, 8, 10, 0, tzinfo=HK)}
    monkeypatch.setattr(dispatch, "clock_now", lambda: clock["now"])
    monkeypatch.setattr(workspace_owner, "_now", lambda: clock["now"].isoformat())

    first = dispatch.execute_bound_daily_cycle(service, "20261008", binding_sha)
    saved_first = workspace_owner._read_plan(service.store, "20261008")
    first_run_path = (service.store.root / "workspace_plans" / "20261008"
        / f"{saved_first['run_id']}.json")
    first_run_bytes = first_run_path.read_bytes()
    # A later fixed slot gets a new bounded attempt with a genuinely later
    # plan cutoff. It may produce a new immutable plan, while source membership
    # and product hashes remain stable when no input has changed.
    clock["now"] = datetime(2026, 10, 8, 12, 30, tzinfo=HK)
    second = dispatch.execute_bound_daily_cycle(service, "20261008", binding_sha)
    saved_second = workspace_owner._read_plan(service.store, "20261008")
    assert first["branch"] == second["branch"] == "SAME_DAY_CATCHUP"
    assert saved_first["workspace"]["plan_context"]["research_cutoff"] == "2026-10-08T10:00:00+08:00"
    assert saved_second["workspace"]["plan_context"]["research_cutoff"] == "2026-10-08T12:30:00+08:00"
    def source_membership(row):
        workspace = row["workspace"]
        return {
            "materials": workspace.get("materials"),
            "material_bindings": workspace.get("existing_material_bindings"),
            "reviewed_analysis_hashes": workspace.get("announcement_reviewed_analysis", {}).get(
                "consumed_product_sha256s"),
            "research_attention_identity": workspace.get("research_attention", {}).get("input_identity"),
            "us_mapping_daily": {
                key: (workspace.get("us_mapping_research", {}).get("daily_run") or {}).get(key)
                for key in ("status", "run_id", "artifact_sha256", "matches")},
        }
    assert source_membership(saved_second) == source_membership(saved_first)
    assert saved_second["run_id"] != saved_first["run_id"]
    assert saved_second["execution_context"]["natural_run_verified"] is False
    assert saved_second["execution_context"]["timing"] == "LATE_CATCHUP"
    assert first_run_path.read_bytes() == first_run_bytes
    ordinary = service.get_workspace("20261008", view="dynamic",
        now=datetime(2026, 10, 8, 12, 30, tzinfo=HK))
    assert ordinary["plan_product"]["run_id"] == saved_second["run_id"]
    service.close()


def test_same_cutoff_failed_us_telemetry_does_not_change_original_plan_identity(
        tmp_path, monkeypatch):
    identities = []
    for label, override_trigger in (("first", False), ("second", True)):
        value, binding_path, binding_sha = _unvalidated_daily_binding(tmp_path / label)
        _accept_test_binding(monkeypatch)
        service = announcement_fixture._FixtureService(value["manager_state_root"])
        service._workspace_security_master_root = Path(value["security_master_root"])
        monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(binding_path))
        cutoff = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
        monkeypatch.setattr(dispatch, "clock_now", lambda cutoff=cutoff: cutoff)
        monkeypatch.setattr(workspace_owner, "_now", lambda cutoff=cutoff: cutoff.isoformat())
        if override_trigger:
            original_us_owner = service.refresh_us_mapping_research
            def same_cutoff_distinct_us_dispatch(date, **kwargs):
                context = dict(kwargs.get("execution_context") or {})
                context["trigger_id"] = "f" * 64
                kwargs["execution_context"] = context
                return original_us_owner(date, **kwargs)
            service.refresh_us_mapping_research = same_cutoff_distinct_us_dispatch
        result = dispatch.execute_bound_daily_cycle(service, "20261008", binding_sha)
        saved = workspace_owner._read_plan(service.store, "20261008")
        assert result["us_mapping_research"]["status"] == "FAILED"
        assert result["plan_result"]["execution_context"]["natural_run_verified"] is False
        assert saved["workspace"]["plan_context"]["research_cutoff"] == cutoff.isoformat()
        identities.append(saved["input_identity"])
        service.close()
    assert identities[0] == identities[1], (
        "same target/cutoff/source inputs differed only by failed-US dispatch trigger metadata",
        identities)


def test_original_supervisor_hook_reaches_1545_catchup_and_skips_blackout(tmp_path):
    calls = []
    def runner(path, cancel):
        calls.append((path, cancel))
    supervisor_hook = supervisor.AnnouncementSupervisor("synthetic-binding.json", runner=runner)
    try:
        supervisor_hook.tick(datetime(2026, 10, 8, 15, 30, tzinfo=HK))
        assert calls == []
        supervisor_hook.tick(datetime(2026, 10, 8, 15, 45, tzinfo=HK))
        deadline = time.monotonic() + 1
        while not calls and time.monotonic() < deadline:
            time.sleep(0.005)
        assert len(calls) == 1
        # Resolve the worker's real config at the reached hook time.
        branch, slot = cycle.daily_cycle_branch("20261008", now=datetime(2026, 10, 8, 15, 45, tzinfo=HK),
            plan_config=PLAN, preopen_config=PREOPEN,
            morning_plan_config=MORNING_CONFIG,
            daily_config={"enabled": True, "same_day_catchup_slots_local": DAILY_SLOTS,
                "us_mapping_budget_seconds": 5, "max_attempts_per_target_date": 5,
                "status": "PROPOSAL_ONLY"})
        assert (branch, slot) == ("SAME_DAY_CATCHUP", "20261008T1545")
    finally:
        supervisor_hook.stop()
        if supervisor_hook.thread is not None:
            supervisor_hook.thread.join(1)


def test_daily_rpc_transport_timeout_has_headroom_over_independent_owner_budgets(
        tmp_path, monkeypatch):
    _value, binding_path, _binding_sha = _unvalidated_daily_binding(tmp_path)
    seen_timeouts = []
    class Response:
        status = 503
        def getheader(self, name, default=""):
            return "application/json" if name.lower() == "content-type" else default
        def read(self, _limit):
            return b'{"detail":"synthetic transport rejection"}'
    class NoNetworkConnection:
        def __init__(self, host, port, *, timeout):
            assert host == "127.0.0.1" and port == 8873
            seen_timeouts.append(timeout)
        def request(self, *_args, **_kwargs):
            pass
        def getresponse(self):
            return Response()
        def close(self):
            pass
    monkeypatch.setattr(dispatch.http.client, "HTTPConnection", NoNetworkConnection)

    morning = datetime(2026, 10, 8, 7, 0, tzinfo=HK)
    monkeypatch.setattr(dispatch, "clock_now", lambda: morning)
    legacy = dispatch.request_bound_plan_cycle(binding_path, "20261008")
    assert legacy["status"] == "FAILED"
    assert seen_timeouts == [35.0]

    seen_timeouts.clear()
    catchup = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
    monkeypatch.setattr(dispatch, "clock_now", lambda: catchup)
    daily = dispatch.request_bound_daily_cycle(binding_path, "20261008")
    assert daily["status"] == "FAILED"
    assert seen_timeouts == [40.0]

