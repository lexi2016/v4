from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest

from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from domains.preselection import date_catalog
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import PreselectionPoolStore


def _independent_pool_artifact(date: str, pool_id: str, rows: list[dict]) -> dict:
    normalized_rows = []
    for rank, row in enumerate(rows, start=1):
        normalized_rows.append({
            **row,
            "pool_id": pool_id,
            "pool_rank": rank,
            "recommendation_status": row.get("recommendation_status", "WATCH_ONLY"),
        })
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": date,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": "HK" if pool_id == "hkconnect_d1_top100" else "A",
        "status": "READY" if normalized_rows else "CANNOT_CONFIRM",
        "producer_id": "test_independent_pool_producer",
        "source_role": "RAW_SOURCE" if normalized_rows else "EXPECTED_MISSING",
        "source_path": f"test/{date}/{pool_id}.json" if normalized_rows else "",
        "source_sha256": hashlib.sha256(f"{date}:{pool_id}".encode()).hexdigest(),
        "rows": normalized_rows,
        "cannot_confirm": [] if normalized_rows else ["EXPECTED_MISSING"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _materialize_independent_pools(
    store: NativeDataStore,
    date: str,
    pools: dict[str, list[dict]],
) -> None:
    independent = PreselectionPoolStore(store.root)
    for pool_id, rows in pools.items():
        independent.materialize(_independent_pool_artifact(date, pool_id, rows))


def _payload(date: str, rows: list[dict]) -> dict:
    watch_rows = [{**row, "recommendation_status": row.get("recommendation_status", "WATCH_ONLY")} for row in rows]
    return {"schema_version": "v3_preselection_pools.v1", "trade_date": date, "producer_status": "CANONICAL_COMPLETE", "data_status": "READY_WITH_ROWS", "module_id": "unified_preselection_pools", "write_policy": "read_only", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False, "recommendation_status": "WATCH_ONLY_BACKTEST_GATED", "canonical_main_pool_confirmed": True, "source_lane": "CANONICAL_MAIN", "selector_status": "READY", "strict_0_2_status": "STRICT_0_2_READY", "pools": [{"pool_id": "main", "rows": deepcopy(watch_rows)}], "unified_rows": deepcopy(watch_rows), "a_source_only_rows": [], "a_all_pool_rows": deepcopy(watch_rows), "rows": deepcopy(watch_rows), "startup_ensure": {}, "evidence_paths": ["receipts/source.json"], "cannot_confirm": []}


def test_native_store_and_api_enforce_dates_statuses_limits_and_receipts(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog({"schema_version": "v3_trade_calendar.v1", "system_date": "20260618", "stage_dates": ["20260617", "20260618"], "future_target_dates": ["20260622"], "materialized_rows": {"20260617": 2, "20260618": 0}})
    _materialize_independent_pools(
        store,
        "20260617",
        {"a_d1_premarket_pool": [{"symbol": "A.000001"}, {"symbol": "A.000002"}]},
    )
    app = create_app(data_root=store.root, current_date="20260618")
    client = TestClient(app)

    assert client.get("/api/v1/runs/date-list").json()["default_date"] == "20260617"
    assert client.get("/api/v1/runs/date-list").json()["dates"] == ["20260622", "20260618", "20260617"]
    response = client.get("/api/v3/preselection-pools", params={"date": "20260617", "limit": 1})
    assert response.status_code == 200
    assert response.json()["data_status"] == "PARTIAL_WITH_ROWS"
    assert response.json()["row_count"] == 2
    assert len(response.json()["rows"]) == 1
    assert len(response.json()["unified_rows"]) == 1
    assert len(response.json()["a_all_pool_rows"]) == 1
    assert len(response.json()["pools"][0]["rows"]) == 1
    assert response.json()["unified_row_count"] == 2
    assert response.json()["a_all_pool_row_count"] == 2
    assert response.json()["production_allowed"] is False
    assert response.json()["buy_gate_updated"] is False
    assert response.json()["orders_sent"] is False
    missing = client.get("/api/v3/preselection-pools", params={"date": "20260618"}).json()
    assert missing["data_status"] == "DATA_BLOCKED_EMPTY"
    assert missing["cannot_confirm"]
    assert missing["production_allowed"] is False
    assert missing["buy_gate_updated"] is False
    assert missing["orders_sent"] is False
    assert client.get("/api/v1/runs/date-list", params={"date": "20261399"}).status_code == 422


def test_store_fails_closed_on_receipt_sha_mismatch_and_idempotent_import(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    payload = _payload("20260618", [{"symbol": "A.000001"}])
    first = store.import_payload(payload)
    assert store.import_payload(payload) == first
    with pytest.raises(ValueError, match="conflicting"):
        store.import_payload(_payload("20260618", [{"symbol": "A.000002"}]))
    with (store.root / first["receipt_path"]).open("r+", encoding="utf-8") as receipt:
        content = json.load(receipt)
        content["source_sha256"] = "0" * 64
        receipt.seek(0); json.dump(content, receipt); receipt.truncate()
    try:
        store.read_payload("20260618")
    except ValueError as error:
        assert "receipt" in str(error)
    else:
        raise AssertionError("tampered receipt was accepted")


def test_weekends_and_20260619_are_excluded_and_partial_rows_stay_partial(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog({"schema_version": "v3_trade_calendar.v1", "system_date": "20260622", "stage_dates": ["20260619", "20260620", "20260622"], "future_target_dates": [], "materialized_rows": {"20260622": 1}})
    _materialize_independent_pools(
        store,
        "20260622",
        {"a_d1_premarket_pool": [{"symbol": "A.000003"}]},
    )
    client = TestClient(create_app(data_root=store.root, current_date="20260622"))
    catalog = client.get("/api/v1/runs/date-list").json()
    assert catalog["stage_dates"] == ["20260622"]
    assert catalog["dates"] == ["20260622"]
    assert client.get("/api/v3/preselection-pools", params={"date": "20260622"}).json()["data_status"] == "PARTIAL_WITH_ROWS"


@pytest.mark.parametrize("unsafe", [
    {"producer_status": "BLOCKED"},
    {"rows": [{"symbol": "HK.1", "recommendation_status": "BUY"}]},
    {"production_allowed": True},
])
def test_import_rejects_unproven_or_trading_unsafe_payloads_without_writes(tmp_path, unsafe) -> None:
    store = NativeDataStore(tmp_path / "data")
    payload = _payload("20260622", [{"symbol": "HK.1", "recommendation_status": "WATCH_ONLY"}])
    payload.update(unsafe)
    with pytest.raises(ValueError): store.import_payload(payload)
    assert not store.root.exists()


def test_read_is_pure_and_default_uses_all_positive_materialized_dates(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog({"schema_version": "v3_trade_calendar.v1", "system_date": "20260622", "stage_dates": ["20260618"], "future_target_dates": [], "materialized_rows": {"20260619": 2, "20260622": 3}})
    catalog = store.read_catalog()
    assert catalog["materialized_rows"]["20260622"] == 3
    assert date_catalog(store)["default_date"] == "20260622"
    assert "20260622" in date_catalog(store)["stage_dates"]
    (store.root / "manifest.json").unlink()
    with pytest.raises(ValueError): store.read_catalog()


def test_empty_materialization_still_exposes_the_current_trading_date(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog({"schema_version": "v3_trade_calendar.v1", "system_date": "20260730", "stage_dates": [], "future_target_dates": [], "materialized_rows": {}})
    payload = date_catalog(store, current_date="20260730")
    assert payload["default_date"] == ""
    assert payload["dates"] == ["20260730"]


def test_three_day_api_matrix_keeps_history_current_and_future_outputs_isolated(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog({
        "schema_version": "v3_trade_calendar.v1",
        "system_date": "20260730",
        "stage_dates": ["20260729", "20260730"],
        "future_target_dates": ["20260731"],
        "materialized_rows": {"20260729": 1, "20260730": 1},
    })
    _materialize_independent_pools(
        store,
        "20260729",
        {"a_d1_premarket_pool": [{"symbol": "HK.00029", "market": "HK", "stock_name": "仅属于20260729"}]},
    )
    _materialize_independent_pools(
        store,
        "20260730",
        {"a_d1_premarket_pool": [{"symbol": "HK.00030", "market": "HK", "stock_name": "仅属于20260730"}]},
    )
    client = TestClient(create_app(data_root=store.root, current_date="20260730"))

    catalog = client.get("/api/v1/runs/date-list").json()
    assert catalog["dates"] == ["20260731", "20260730", "20260729"]
    assert catalog["default_date"] == "20260730"

    bodies = {
        date: client.get("/api/v3/preselection-pools", params={"date": date}).json()
        for date in ("20260729", "20260730", "20260731")
    }
    assert {date: body["trade_date"] for date, body in bodies.items()} == {
        "20260729": "20260729",
        "20260730": "20260730",
        "20260731": "20260731",
    }
    assert [row["symbol"] for row in bodies["20260729"]["rows"]] == ["HK.00029"]
    assert [row["symbol"] for row in bodies["20260730"]["rows"]] == ["HK.00030"]
    assert bodies["20260731"]["data_status"] == "DATA_BLOCKED_EMPTY"
    assert bodies["20260731"]["rows"] == []
    assert all(body["production_allowed"] is False for body in bodies.values())


def test_mixed_market_preview_applies_limit_per_market_instead_of_hiding_hk(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog({
        "schema_version": "v3_trade_calendar.v1",
        "system_date": "20260730",
        "stage_dates": ["20260730"],
        "future_target_dates": [],
        "materialized_rows": {"20260730": 4},
    })
    _materialize_independent_pools(
        store,
        "20260730",
        {
            "a_d1_premarket_pool": [
                {"symbol": "A.000001", "market": "A"},
                {"symbol": "A.000002", "market": "A"},
                {"symbol": "HK.00001", "market": "HK"},
                {"symbol": "HK.00002", "market": "HK"},
            ],
        },
    )

    response = TestClient(create_app(data_root=store.root)).get(
        "/api/v3/preselection-pools",
        params={"date": "20260730", "limit": 1},
    ).json()

    assert [row["symbol"] for row in response["rows"]] == [
        "A.000001",
        "HK.00001",
    ]


def test_partial_flat_migration_is_rejected_instead_of_synthesizing_pool_groups(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog({
        "schema_version": "v3_trade_calendar.v1",
        "system_date": "20260730",
        "stage_dates": ["20260730"],
        "future_target_dates": [],
        "materialized_rows": {"20260730": 5},
    })
    rows = [
        {
            "symbol": "A.300001",
            "market": "A",
            "pool_id": "a_d1_premarket_pool",
            "stock_name": "A主池一",
            "pool_rank": 1,
            "recommendation_status": "WATCH_ONLY",
        },
        {
            "symbol": "A.300001",
            "market": "A",
            "pool_id": "a_d1_fupan_watchlist_pool",
            "stock_name": "A主池一",
            "pool_rank": 8,
            "recommendation_status": "WATCH_ONLY",
        },
        {
            "symbol": "A.300002",
            "market": "A",
            "pool_id": "a_d1_fupan_watchlist_pool",
            "stock_name": "A来源池二",
            "pool_rank": 2,
            "recommendation_status": "WATCH_ONLY",
        },
        {
            "symbol": "HK.00001",
            "market": "HK",
            "pool_id": "hkconnect_d1_top100",
            "pool_rank": 1,
            "recommendation_status": "WATCH_ONLY",
        },
        {
            "symbol": "HK.00002",
            "market": "HK",
            "pool_id": "hkconnect_d1_top100",
            "pool_rank": 2,
            "recommendation_status": "WATCH_ONLY",
        },
    ]
    flat = {
        **_payload("20260730", rows),
        "producer_status": "PARTIAL",
        "data_status": "PARTIAL_WITH_ROWS",
        "canonical_main_pool_confirmed": False,
        "source_lane": "NON_CANONICAL_OBSERVATION",
        "selector_status": "CANNOT_CONFIRM",
        "strict_0_2_status": "CANNOT_CONFIRM",
        "pools": [{"pool_id": "legacy_partial_migration", "rows": deepcopy(rows)}],
        "unified_rows": deepcopy(rows),
        "a_source_only_rows": deepcopy(rows[:3]),
        "a_all_pool_rows": deepcopy(rows[:3]),
    }
    store.import_payload(flat)

    response = TestClient(create_app(data_root=store.root)).get(
        "/api/v3/preselection-pools",
        params={"date": "20260730", "limit": 200},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["pools"] == []
    assert payload["pool_count"] == 0
    assert payload["blocking_reasons"] == [
        "V3.5 independent preselection producers have not materialized this date."
    ]


@pytest.mark.parametrize("field,value", [
    ("recommendation_status", "SELL"), ("orders_sent", 1), ("selector_status", "STALE"),
    ("source_lane", "WECHAT_RESEARCH"), ("canonical_main_pool_confirmed", False),
])
def test_complete_proof_contract_rejects_bypass_variants(tmp_path, field, value) -> None:
    store = NativeDataStore(tmp_path / "data")
    payload = _payload("20260623", [{"symbol": "HK.1", "recommendation_status": "WATCH_ONLY"}])
    payload.update({"data_status": "READY_WITH_ROWS", "module_id": "unified_preselection_pools", "write_policy": "read_only", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False, "recommendation_status": "WATCH_ONLY_BACKTEST_GATED", "canonical_main_pool_confirmed": True, "source_lane": "CANONICAL_MAIN", "selector_status": "READY", "strict_0_2_status": "STRICT_0_2_READY"})
    payload[field] = value
    with pytest.raises(ValueError): store.import_payload(payload)


def test_manifest_last_interruption_is_fail_closed_then_recovers_on_same_retry(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data"); payload = _payload("20260623", [{"symbol": "HK.1", "recommendation_status": "WATCH_ONLY"}])
    store._write("preselection/20260623.json", payload)
    store._write("receipts/20260623.json", {"schema_version": "v3_import_receipt.v1", "payload_path": "preselection/20260623.json", "source_sha256": __import__("hashlib").sha256(__import__("json").dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "trade_date": "20260623"})
    with pytest.raises(ValueError): store.read_payload("20260623")
    store.import_payload(payload)
    assert store.read_payload("20260623")["trade_date"] == "20260623"
    assert not list(store.root.rglob("*.tmp"))


@pytest.mark.parametrize("failing_write", [1, 2, 3])
def test_each_publish_failure_is_fail_closed_and_retryable(tmp_path, monkeypatch, failing_write) -> None:
    store = NativeDataStore(tmp_path / "data")
    payload = _payload("20260625", [{"symbol": "HK.5"}])
    real_write = store._write
    calls = 0

    def fail_at_write(relative, value):
        nonlocal calls
        calls += 1
        if calls == failing_write:
            raise OSError("injected publish failure")
        real_write(relative, value)

    monkeypatch.setattr(store, "_write", fail_at_write)
    with pytest.raises(OSError, match="injected"):
        store.import_payload(payload)
    monkeypatch.setattr(store, "_write", real_write)
    with pytest.raises((FileNotFoundError, ValueError)):
        store.read_payload("20260625")

    store.import_payload(payload)
    assert store.read_payload("20260625")["rows"][0]["symbol"] == "HK.5"
    assert not list(store.root.rglob("*.tmp"))
    assert not (store.root / ".import.lock").exists()


def test_concurrent_dates_preserve_manifest_and_same_date_conflicts(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    one, two = _payload("20260623", [{"symbol": "HK.1", "recommendation_status": "WATCH_ONLY"}]), _payload("20260624", [{"symbol": "HK.2", "recommendation_status": "WATCH_ONLY"}])
    with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(store.import_payload, [one, two]))
    manifest = store._manifest(); assert set(manifest) == {"preselection/20260623.json", "preselection/20260624.json"}
    conflict = _payload("20260623", [{"symbol": "HK.9"}])
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda value: _attempt(store, value), [one, conflict]))
    assert results.count("ok") == 1 and results.count("error") == 1
    assert store.read_payload("20260623") == one


def test_read_revalidates_business_safety_even_with_matching_hashes(tmp_path) -> None:
    store = NativeDataStore(tmp_path / "data")
    payload = _payload("20260626", [{"symbol": "HK.6"}])
    result = store.import_payload(payload)
    payload_path = store.root / "preselection" / "20260626.json"
    tampered = json.loads(payload_path.read_text(encoding="utf-8"))
    tampered["rows"][0]["recommendation_status"] = "SELL"
    store._write("preselection/20260626.json", tampered)
    digest = __import__("hashlib").sha256(json.dumps(tampered, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest = store._manifest()
    manifest["preselection/20260626.json"] = digest
    store._write_manifest(manifest)
    receipt = json.loads((store.root / result["receipt_path"]).read_text(encoding="utf-8"))
    receipt["source_sha256"] = digest
    store._write(result["receipt_path"], receipt)
    with pytest.raises(ValueError, match="WATCH_ONLY"):
        store.read_payload("20260626")


def _attempt(store, value):
    try: store.import_payload(value); return "ok"
    except ValueError: return "error"
