from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.v4_api.app import create_app
from domains.preselection import date_catalog
from infrastructure.data_store import NativeDataStore

DATE_LIST_CLIENT_KEYS = (
    "dates",
    "stage_dates",
    "future_target_dates",
    "review_dates",
    "research_dates",
    "hk_observation_only_dates",
    "navigation_date",
    "default_date",
    "system_date",
    "runtime_identity",
)


def _store(tmp_path: Path) -> NativeDataStore:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog(
        {
            "schema_version": "v3_trade_calendar.v1",
            "system_date": "20260818",
            "stage_dates": ["20260818"],
            "future_target_dates": [],
            "materialized_rows": {"20260818": 2},
        }
    )
    return store


def _count_body_calls(monkeypatch) -> dict[str, int]:
    import domains._preselection_parts.date_catalog as body_module

    calls = {"n": 0}
    original = body_module._date_catalog_body

    def counted(scope, store, **kwargs):
        calls["n"] += 1
        return original(scope, store, **kwargs)

    monkeypatch.setattr(body_module, "_date_catalog_body", counted)
    return calls


def test_catalog_cache_reuses_body_within_ttl(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("V4_DATE_CATALOG_TTL_SECONDS", "30")
    calls = _count_body_calls(monkeypatch)
    store = _store(tmp_path)

    first = date_catalog(store, current_date="20260818", use_cache=True)
    second = date_catalog(store, current_date="20260818", use_cache=True)

    assert calls["n"] == 1
    assert second == first
    assert second is not first


def test_catalog_cache_is_opt_in(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("V4_DATE_CATALOG_TTL_SECONDS", "30")
    calls = _count_body_calls(monkeypatch)
    store = _store(tmp_path)

    date_catalog(store, current_date="20260818", use_cache=False)
    date_catalog(store, current_date="20260818", use_cache=False)

    assert calls["n"] == 2


def test_catalog_cache_invalidates_when_store_changes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("V4_DATE_CATALOG_TTL_SECONDS", "30")
    calls = _count_body_calls(monkeypatch)
    store = _store(tmp_path)

    date_catalog(store, current_date="20260818", use_cache=True)
    (store.root / "preselection_pools").mkdir(exist_ok=True)
    date_catalog(store, current_date="20260818", use_cache=True)

    assert calls["n"] == 2


def test_catalog_cache_can_be_disabled_by_zero_ttl(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("V4_DATE_CATALOG_TTL_SECONDS", "0")
    calls = _count_body_calls(monkeypatch)
    store = _store(tmp_path)

    date_catalog(store, current_date="20260818", use_cache=True)
    date_catalog(store, current_date="20260818", use_cache=True)

    assert calls["n"] == 2


def test_domain_catalog_keeps_projection_payloads(tmp_path: Path) -> None:
    store = _store(tmp_path)
    catalog = date_catalog(store, current_date="20260818")

    assert "stage_artifacts" in catalog
    assert "independent_pool_evidence" in catalog


def test_date_list_response_omits_unused_projection_payloads(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = TestClient(create_app(data_root=store.root, current_date="20260818"))

    response = client.get("/api/v1/runs/date-list")

    assert response.status_code == 200
    payload = response.json()
    assert "stage_artifacts" not in payload
    assert "independent_pool_evidence" not in payload
    for key in DATE_LIST_CLIENT_KEYS:
        assert key in payload, key
