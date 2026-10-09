"""Real R2 create_app wiring against labelled, temporary owner artifacts.

All calendar, captured membership, source files and stores are offline test
fixtures. The production readers, private manager package and HTTP routes run
unchanged; no fixture substitutes a membership validator or plan owner.
"""
from datetime import datetime
import hashlib
import importlib
from pathlib import Path
import socket

from fastapi.testclient import TestClient
import pytest

from apps.api.v35_api import app as app_module
from apps.api.v35_api import manager_research_router as router
from tests.test_manager_four_hk_readers import (
    ENV_KEYS,
    publish_test_v2,
    synthetic_hk_calendar,
    synthetic_authority_observation_clock,
)


TARGET = "20261009"
PARAMS = {"date": TARGET, "selection_date": TARGET, "announcement_date": "20261008"}
ENV_FIELDS = dict(zip(ENV_KEYS, (
    "universe_root", "authority_owner_root", "authority_owner_sha256",
    "capture_receipt_root", "dispatch_receipt_root",
)))


@pytest.fixture
def build_app(tmp_path, monkeypatch, synthetic_hk_calendar, synthetic_authority_observation_clock):
    services = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime.fromisoformat("2026-10-09T09:00:00+08:00")
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    def forbid_network(*args, **kwargs):
        pytest.fail("App-wired offline regression attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(router, "datetime", Clock)
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key in ("V4_MANAGER_SECURITY_MASTER_ROOT", "V4_MANAGER_SCREEN_AUTHORITY_ROOT",
                "V4_MANAGER_NEWS_DATA_ROOT", "V4_MANAGER_NEWS_OWNER_ROOT"):
        monkeypatch.setenv(key, str(tmp_path / "unavailable-other-owner" / key))

    def build(name, **kwargs):
        root = tmp_path / name
        app = app_module.create_app(
            data_root=root / "data", shared_data_root=root / "shared",
            ledger_root=root / "ledger", stage_center_selection_root=root / "stage",
            manager_research_state_root=root / "manager", current_date=TARGET,
            research_data_root=root / "research", research_ledger_root=root / "research-ledger",
            morning_news_data_root=root / "morning-news", preselection_source_root=root / "preselection",
            **kwargs,
        )
        service = app.state.manager_research_service
        services.append(service)
        runtime = type(service).__module__.rsplit(".", 1)[0]
        monkeypatch.setattr(importlib.import_module(runtime + ".workspace"), "datetime", Clock)
        return app, service

    yield build
    for service in services:
        service.close()


def read(app):
    with TestClient(app) as client:
        result = client.get("/api/v4/manager/research/workspace", params=PARAMS)
    assert result.status_code == 200, result.text
    value = result.json()
    for key, flag in (("RESEARCH_ONLY", True), ("production_allowed", False),
                      ("buy_gate_updated", False), ("orders_sent", False)):
        assert value[key] is flag
    return value


def membership(value):
    return value["selection_diagnostics"]["membership"]


def configure_environment(monkeypatch, binding):
    for env_key, field in ENV_FIELDS.items():
        if field in binding:
            monkeypatch.setenv(env_key, str(binding[field]))
        else:
            monkeypatch.delenv(env_key, raising=False)


def test_explicit_app_binding_reaches_existing_reader_and_http_channel(tmp_path, monkeypatch, build_app):
    binding, built = publish_test_v2(tmp_path / "explicit-authority")
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_ROOT", str(tmp_path / "wrong-ambient-root"))
    app, service = build_app("explicit-app", workspace_connect_binding=binding)

    value = read(app)

    scope = membership(value)
    assert scope["status"] == "OWNER_VERIFIED", scope["gaps"]
    assert scope["codes"] == ["HK.01234", "HK.05678"]
    assert scope["source"]["run_id"] == built["run_id"]
    assert scope["source"]["sha256"] == built["artifact_sha256"]
    channel = next(c for c in value["daily_channels"]["channels"] if c["channel"] == "HK_CONNECT")
    assert channel["authority"]["source"]["run_id"] == built["run_id"]
    assert service.store.root == tmp_path / "explicit-app" / "manager"


def test_each_app_retains_its_construction_time_environment_binding(tmp_path, monkeypatch, build_app):
    a, first = publish_test_v2(tmp_path / "authority-a", codes=("HK.01234",))
    b, second = publish_test_v2(tmp_path / "authority-b", codes=("HK.05678",))
    configure_environment(monkeypatch, a)
    app_a, _ = build_app("app-a")
    configure_environment(monkeypatch, b)
    app_b, _ = build_app("app-b")

    assert membership(read(app_a))["source"]["run_id"] == first["run_id"]
    assert membership(read(app_a))["codes"] == ["HK.01234"]
    assert membership(read(app_b))["source"]["run_id"] == second["run_id"]
    assert membership(read(app_b))["codes"] == ["HK.05678"]


def test_mutating_callers_binding_does_not_retarget_existing_app(tmp_path, build_app):
    binding, first = publish_test_v2(tmp_path / "authority-a", codes=("HK.01234",))
    other, _ = publish_test_v2(tmp_path / "authority-b", codes=("HK.05678",))
    app, _ = build_app("owned-binding", workspace_connect_binding=binding)
    binding.update(other)

    assert membership(read(app))["source"]["run_id"] == first["run_id"]
    assert membership(read(app))["codes"] == ["HK.01234"]


def test_explicit_empty_app_binding_never_borrows_valid_environment(tmp_path, monkeypatch, build_app):
    binding, _ = publish_test_v2(tmp_path / "ambient-authority")
    configure_environment(monkeypatch, binding)
    app, _ = build_app("unbound", workspace_connect_binding={})

    scope = membership(read(app))

    assert scope["status"] == "CANNOT_CONFIRM"
    assert scope["codes"] == []
    assert scope["gaps"] == ["HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND"]


def test_app_preserves_owner_sha_rejection(tmp_path, build_app):
    binding, _ = publish_test_v2(tmp_path / "authority")
    binding["authority_owner_sha256"] = "0" * 64
    app, _ = build_app("bad-pin", workspace_connect_binding=binding)

    scope = membership(read(app))

    assert scope["status"] == "CANNOT_CONFIRM"
    assert scope["codes"] == []
    assert "HK_CONNECT_TARGET_AUTHORITY_UNVERIFIED:HK_UNIVERSE_OWNER_SHA_MISMATCH" in scope["gaps"]


def test_existing_app_post_saves_plan_and_get_revalidates_same_owner_store(tmp_path, build_app):
    binding, built = publish_test_v2(tmp_path / "authority")
    app, service = build_app("same-owner", workspace_connect_binding=binding)
    with TestClient(app) as client:
        response = client.post("/api/v4/manager/research/workspace/refresh", params=PARAMS,
                               headers={"Origin": "http://testserver"})
    assert response.status_code == 200, response.text
    refreshed = response.json()
    saved = service.get_workspace_plan(TARGET)
    assert refreshed["store_latest_matches_http_plan_product"] is True
    assert refreshed["plan_product"]["run_id"] == saved["run_id"]
    assert refreshed["plan_product"]["sha256"] == saved["sha256"]
    assert refreshed["input_identity"] == saved["input_identity"]
    assert membership(refreshed)["source"]["run_id"] == built["run_id"]
    before = {str(p.relative_to(service.store.root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in service.store.root.rglob("*") if p.is_file()}

    value = read(app)

    assert value["plan_product"]["status"] == "CURRENT"
    assert value["plan_product"]["consumed"] is True
    assert value["plan_product"]["run_id"] == saved["run_id"]
    assert value["plan_product"]["run_readback"]["status"] == "VERIFIED"
    assert value["input_identity"] == saved["input_identity"]
    assert membership(value)["source"]["run_id"] == built["run_id"]
    after = {str(p.relative_to(service.store.root)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in service.store.root.rglob("*") if p.is_file()}
    assert after == before
