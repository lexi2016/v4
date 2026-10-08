from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

APP_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
SUPERVISOR_TEST = APP_ROOT / "tests/test_manager_announcement_supervisor.py"
HELPER = Path(__file__).resolve().parents[1] / "run_plan_only_historical_canary.py"
DAEMON_TEST = Path(__file__).resolve().parent / "test_plan_canary_runtime_validator.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seal_canary(value: dict, canary: dict) -> None:
    canary_path = Path(value["plan_activation_receipt"]["path"])
    raw = json.dumps(canary, sort_keys=True).encode("utf-8")
    canary_path.write_bytes(raw)
    value["plan_activation_receipt"]["sha256"] = hashlib.sha256(raw).hexdigest()


def _normalize_python(value: dict) -> None:
    python = Path(value["python"]).resolve(strict=True)
    value["python"] = str(python)
    value["python_resolved"] = str(python)
    value["python_sha256"] = hashlib.sha256(python.read_bytes()).hexdigest()


def _retarget_fixture(value: dict, canary: dict, target: str) -> None:
    canary["target_trade_date"] = target
    for name in ("refresh", "readback"):
        ref = canary["owner_evidence"][name]
        receipt_path = Path(ref["path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["request"]["url"] = receipt["request"]["url"].rsplit("=", 1)[0] + "=" + target
        readback = receipt["readback"]
        readback["target_trade_date"] = target
        persisted = readback.get("persisted_store")
        if isinstance(persisted, dict):
            persisted["target_trade_date"] = target
        raw = json.dumps(receipt, sort_keys=True).encode("utf-8")
        receipt_path.write_bytes(raw)
        ref["sha256"] = hashlib.sha256(raw).hexdigest()
    _seal_canary(value, canary)


def _validate(value: dict) -> None:
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    validate_binding(value, Path(value["app_root"]))


def test_historical_scope_accepts_only_a_past_native_hk_session(tmp_path):
    fixture = _load_module(SUPERVISOR_TEST, "d1_historical_scope_fixture")
    value, canary = fixture._plan_only_binding(tmp_path / "valid", same_owner_root=True)
    _normalize_python(value)
    canary["scope"] = "HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK"
    _seal_canary(value, canary)
    _validate(value)

    same_day, same_day_canary = fixture._plan_only_binding(tmp_path / "same-day", same_owner_root=True)
    _normalize_python(same_day)
    today = datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y%m%d")
    same_day_canary["scope"] = "HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK"
    _retarget_fixture(same_day, same_day_canary, today)
    with pytest.raises(ValueError, match="PLAN_REFRESH_CANARY_HISTORICAL_TARGET_NOT_PAST"):
        _validate(same_day)

    future, future_canary = fixture._plan_only_binding(tmp_path / "future", same_owner_root=True)
    _normalize_python(future)
    tomorrow = (datetime.now(ZoneInfo("Asia/Hong_Kong")).date() + timedelta(days=1)).strftime("%Y%m%d")
    future_canary["scope"] = "HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK"
    _retarget_fixture(future, future_canary, tomorrow)
    with pytest.raises(ValueError, match="PLAN_REFRESH_CANARY_HISTORICAL_TARGET_NOT_PAST"):
        _validate(future)


def test_historical_scope_rejects_weekend_target_but_keeps_legacy_scope(tmp_path):
    fixture = _load_module(SUPERVISOR_TEST, "d1_historical_scope_weekend_fixture")
    weekend, weekend_canary = fixture._plan_only_binding(tmp_path / "weekend", same_owner_root=True)
    _normalize_python(weekend)
    weekend_canary["scope"] = "HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK"
    _retarget_fixture(weekend, weekend_canary, "20260926")
    with pytest.raises(ValueError, match="PLAN_REFRESH_CANARY_HISTORICAL_TARGET_NOT_HK_SESSION"):
        _validate(weekend)

    legacy, _ = fixture._plan_only_binding(tmp_path / "legacy", same_owner_root=True)
    _normalize_python(legacy)
    _validate(legacy)


def test_scheduler_daemon_uses_the_same_historical_date_and_session_guard(tmp_path, monkeypatch):
    fixture_module = _load_module(DAEMON_TEST, "d1_historical_daemon_fixture")
    fixture = fixture_module._same_root_fixture(tmp_path, monkeypatch)
    daemon = fixture_module.daemon
    canary = json.loads(fixture["canary_path"].read_text(encoding="utf-8"))
    canary["scope"] = "HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK"
    fixture_module._refresh_canary_pins(fixture, canary)
    monkeypatch.setenv(daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV,
                       fixture["environment"][daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV])
    assert daemon._load_announcement_binding(fixture["environment"])["plan_material_refresh_only"] is True

    fixture = fixture_module._same_root_fixture(tmp_path / "weekend", monkeypatch)
    canary = json.loads(fixture["canary_path"].read_text(encoding="utf-8"))
    canary["scope"] = "HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK"
    canary["target_trade_date"] = "20260926"
    for name in ("refresh", "readback"):
        ref = canary["owner_evidence"][name]
        evidence_path = Path(ref["path"])
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["request"]["url"] = evidence["request"]["url"].rsplit("=", 1)[0] + "=20260926"
        evidence["readback"]["target_trade_date"] = "20260926"
        persisted = evidence["readback"].get("persisted_store")
        if isinstance(persisted, dict):
            persisted["target_trade_date"] = "20260926"
        raw = json.dumps(evidence, sort_keys=True).encode("utf-8")
        evidence_path.write_bytes(raw)
        ref["sha256"] = hashlib.sha256(raw).hexdigest()
    fixture_module._refresh_canary_pins(fixture, canary)
    monkeypatch.setenv(daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV,
                       fixture["environment"][daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV])
    with pytest.raises(daemon.DaemonConfigurationError):
        daemon._load_announcement_binding(fixture["environment"])


def test_plan_refresh_post_exposes_verified_owner_store_readback(tmp_path):
    import httpx
    from fastapi import FastAPI
    from apps.api.v35_api.manager_research_router import create_manager_research_router

    target = "20260925"
    run_id = "1" * 32
    product_sha = "2" * 64
    identity = "3" * 64
    owner = "ManagerResearchJobService.refresh_workspace_plan"
    persisted = {
        "target_trade_date": target, "run_id": run_id, "sha256": product_sha,
        "input_identity": identity, "execution_kind": "MANUAL_REFRESH", "owner": owner,
        "RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
    }

    class Service:
        def refresh_workspace_plan(self, date_value):
            assert date_value == target
            return {
                "input_identity": identity,
                "plan_product": {"status": "CURRENT", "consumed": True,
                    "run_id": run_id, "sha256": product_sha, "original_owner": owner},
                "workspace_plan_attempt": {"run_id": run_id, "execution_kind": "MANUAL_REFRESH",
                    "state": "PARTIAL"},
            }

        def get_workspace_plan(self, date_value):
            assert date_value == target
            return persisted

    app = FastAPI()
    app.include_router(create_manager_research_router(Service()))

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://127.0.0.1:8873") as client:
            return await client.post(
                f"/api/v4/manager/research/workspace/refresh?date={target}",
                headers={"Origin": "http://127.0.0.1:8873"},
            )

    response = asyncio.run(request())
    assert response.status_code == 200
    result = response.json()
    assert result["target_trade_date"] == target
    assert result["store_latest_matches_http_plan_product"] is True
    assert result["formal_recommendation_count"] == 0
    assert result["persisted_store"]["product_sha256"] == product_sha
    assert result["safety"] == {
        "RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
    }


def test_historical_canary_helper_defaults_to_no_http_or_write(capsys):
    module = _load_module(HELPER, "d1_historical_canary_helper")
    assert module.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "DRY_RUN_NO_HTTP_NO_WRITE"
    assert output["http_calls"] == []
    assert output["manager_state_root"] == str(module.FORMAL_MANAGER_STATE)
    assert output["target_trade_date"] == "20260925"
    assert output["safety"]["production_allowed"] is False


def test_canary_helper_revalidates_disabled_binding_and_api_python_pin(tmp_path, monkeypatch):
    fixture = _load_module(SUPERVISOR_TEST, "d1_disabled_binding_fixture")
    binding, _ = fixture._plan_only_binding(tmp_path / "binding", same_owner_root=True)
    exact_python = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python")
    resolved_python = exact_python.resolve(strict=True)
    binding.update(python=str(exact_python), python_resolved=str(resolved_python),
                   python_sha256=hashlib.sha256(resolved_python.read_bytes()).hexdigest())
    binding.update(enabled=False, plan_material_refresh_only=False,
                   announcement_collection_enabled=False)
    binding.pop("plan_material_refresh", None)
    binding.pop("plan_activation_receipt", None)
    binding["activation_receipt"] = None

    helper = _load_module(HELPER, "d1_binding_pin_helper")
    monkeypatch.setattr(helper, "API_ROOT", Path(binding["app_root"]))
    monkeypatch.setattr(helper, "FORMAL_MANAGER_STATE", Path(binding["manager_state_root"]))
    monkeypatch.setattr(helper, "BINDING_PATH", tmp_path / "manager-plan-binding.json")
    environment = {
        "V35_APP_ROOT": binding["app_root"],
        "V4_MANAGER_RESEARCH_STATE_ROOT": binding["manager_state_root"],
        "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(helper.BINDING_PATH),
    }
    program_arguments = ["/usr/bin/env", binding["python"], "-m", "uvicorn"]

    helper._validate_disabled_binding(binding, environment, program_arguments)

    with pytest.raises(ValueError, match="D1_API_PYTHON_BINDING_MISMATCH"):
        helper._validate_disabled_binding(binding, environment,
                                          ["/usr/bin/env", str(Path(binding["python"]).parent / "other-python")])

    tampered = copy.deepcopy(binding)
    tampered["files"]["ops/run_manager_announcement_cycle.py"] = "0" * 64
    with pytest.raises(ValueError, match="ANNOUNCEMENT_BINDING_CLOSED_INVENTORY_MISMATCH"):
        helper._validate_disabled_binding(tampered, environment, program_arguments)
