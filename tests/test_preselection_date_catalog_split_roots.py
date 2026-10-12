from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from infrastructure.data_store import NativeDataStore, _sha256
from infrastructure.preselection_pool_store import PreselectionPoolStore


CURRENT_DATE = "20261011"
PERSISTED_DATE = "20261009"
TARGET_DATE = "20261012"


def _a_pool(date: str, *, symbol: str = "A.000001") -> dict:
    pool_id = "a_d1_premarket_pool"
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": date,
        "target_date": date,
        "pool_id": pool_id,
        "display_name": "A D-1 fixture",
        "market": "A",
        "status": "READY",
        "producer_id": "split_root_fixture",
        "source_role": "RAW_SOURCE",
        "source_path": f"fixture/{date}/{pool_id}.csv",
        "source_sha256": hashlib.sha256(f"{date}:{symbol}".encode()).hexdigest(),
        "rows": [
            {
                "symbol": symbol,
                "market": "A",
                "pool_id": pool_id,
                "pool_rank": 1,
                "trade_date": date,
                "target_date": date,
                "recommendation_status": "WATCH_ONLY",
            }
        ],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _recommendation_pool(date: str) -> dict:
    pool = _a_pool(date, symbol="A.000002")
    pool["pool_id"] = "a_share_research_recommendation_pool"
    pool["display_name"] = "A recommendation fixture"
    pool["source_path"] = f"fixture/{date}/a_share_research_recommendation_pool.csv"
    pool["rows"][0]["pool_id"] = "a_share_research_recommendation_pool"
    return pool


def _hk_pool(date: str = TARGET_DATE, **metadata) -> dict:
    pool_id = "hkconnect_d1_top100"
    run_id = f"{date}-hk-connect-d1-top100-0-2-d6f38622b186"
    rows = [
        {
            "symbol": f"HK.{index:05d}",
            "market": "HK",
            "pool_id": pool_id,
            "pool_rank": index,
            "trade_date": date,
            "target_date": date,
            "signal_date": "20261009",
            "selected_strategy": "prob_active",
            "d1_freshness_status": "PASS",
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        for index in range(1, 101)
    ]
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": date,
        "pool_id": pool_id,
        "display_name": "HK D-1 fixture",
        "market": "HK",
        "status": "STRICT_0_2_READY",
        "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "SHARED_VERIFIED_HK_0_2",
        "source_path": f"runs/{date}/HK_CONNECT_D1_TOP100_0_2/{run_id}/artifact.csv",
        "source_sha256": "a" * 64,
        "source_run_id": run_id,
        "source_row_count": len(rows),
        "rows": rows,
        "cannot_confirm": ["RESEARCH_ONLY_NOT_BUY_GATE"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        **metadata,
    }


def _store_with_catalog(root: Path) -> NativeDataStore:
    store = NativeDataStore(root)
    store.import_catalog(
        {
            "schema_version": "v3_trade_calendar.v1",
            "system_date": PERSISTED_DATE,
            "stage_dates": [PERSISTED_DATE],
            "future_target_dates": [],
            "materialized_rows": {PERSISTED_DATE: 1},
        }
    )
    return store


def _write_misdated_trio(root: Path, directory_date: str, payload: dict) -> None:
    store = PreselectionPoolStore(root)
    pool_id = str(payload["pool_id"])
    artifact_path = f"preselection_pools/{directory_date}/{pool_id}.json"
    receipt_path = f"preselection_pools/{directory_date}/receipts/{pool_id}.json"
    digest = _sha256(payload)
    store._write(artifact_path, payload)
    store._write(
        receipt_path,
        store._receipt(
            trade_date=directory_date,
            pool_id=pool_id,
            artifact_path=artifact_path,
            artifact_sha256=digest,
            payload=payload,
        ),
    )
    store._write(f"preselection_pools/{directory_date}/manifest.json", {pool_id: digest})


def _write_released_materialize_lock(root: Path) -> None:
    lock_path = root / "preselection_pools" / ".materialize.lock"
    payload = {
        "schema_version": "v3_5_interprocess_lock.v1",
        "pid": 2147483647,
        "token": "RELEASED",
    }
    descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, separators=(",", ":")))


def _remove_pool_identity_field(
    root: Path, date: str, pool_id: str, field: str
) -> None:
    store = PreselectionPoolStore(root)
    artifact_path = f"preselection_pools/{date}/{pool_id}.json"
    artifact = store._read(artifact_path)
    artifact.pop(field)
    store._write(artifact_path, artifact)
    manifest_path = f"preselection_pools/{date}/manifest.json"
    manifest = store._read(manifest_path)
    manifest[pool_id] = _sha256(artifact)
    store._write(manifest_path, manifest)


def test_date_list_reads_verified_future_pool_from_split_source_and_keeps_a_partial_rows(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "api-data"
    source_root = tmp_path / "pool-source"
    store = _store_with_catalog(data_root)
    PreselectionPoolStore(source_root).materialize(_a_pool(TARGET_DATE))
    _write_released_materialize_lock(source_root)

    client = TestClient(
        create_app(
            data_root=data_root,
            preselection_source_root=source_root,
            current_date=CURRENT_DATE,
        )
    )
    catalog = client.get("/api/v1/runs/date-list").json()

    assert TARGET_DATE in catalog["future_target_dates"]
    assert catalog["dates"].count(TARGET_DATE) == 1
    requested = client.get(
        "/api/v1/runs/date-list", params={"date": TARGET_DATE}
    ).json()
    assert requested["requested_date"] == TARGET_DATE
    assert requested["selected_date"] == TARGET_DATE


@pytest.mark.parametrize("missing_field", ["source_sha256", "source_role"])
def test_date_catalog_quarantines_secondary_missing_identity_field_and_keeps_sibling(
    tmp_path: Path,
    missing_field: str,
) -> None:
    data_root = tmp_path / "api-data"
    source_root = tmp_path / "pool-source"
    _store_with_catalog(data_root)
    source_store = PreselectionPoolStore(source_root)
    source_store.materialize(_a_pool(TARGET_DATE))
    source_store.materialize(_recommendation_pool(TARGET_DATE))
    _remove_pool_identity_field(
        source_root,
        TARGET_DATE,
        "a_share_research_recommendation_pool",
        missing_field,
    )
    _write_released_materialize_lock(source_root)

    client = TestClient(
        create_app(
            data_root=data_root,
            preselection_source_root=source_root,
            current_date=CURRENT_DATE,
        )
    )
    response = client.get("/api/v1/runs/date-list").json()

    assert TARGET_DATE in response["future_target_dates"]
    evidence = response["independent_pool_evidence"][TARGET_DATE]
    assert evidence["trade_date"] == TARGET_DATE
    assert evidence["pools"]["a_d1_premarket_pool"]["status"] == "VERIFIED"
    assert evidence["pools"]["a_d1_premarket_pool"]["source_sha256"] == hashlib.sha256(
        f"{TARGET_DATE}:A.000001".encode()
    ).hexdigest()
    quarantined = evidence["pools"]["a_share_research_recommendation_pool"]
    assert quarantined["status"] == "CANNOT_CONFIRM"
    assert quarantined["source_sha256"] is None
    assert any(
        diagnostic.startswith(
            "PRESELECTION_POOL_INTEGRITY:a_share_research_recommendation_pool:"
        )
        for diagnostic in quarantined["diagnostics"]
    )


def test_a_partial_pool_rows_remain_partial_with_the_single_root_contract(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "api-data"
    _store_with_catalog(data_root)
    PreselectionPoolStore(data_root).materialize(_a_pool(TARGET_DATE))

    client = TestClient(
        create_app(
            data_root=data_root,
            current_date=CURRENT_DATE,
        )
    )
    partial = client.get(
        "/api/v3/preselection-pools", params={"date": TARGET_DATE}
    ).json()

    assert partial["data_status"] == "PARTIAL_WITH_ROWS", partial.get(
        "blocking_reasons"
    )
    assert partial["a_all_pool_row_count"] == 1
    assert partial["market_totals"] == {"A": 1, "HK": 0}


def test_date_catalog_ignores_bad_sha_and_wrong_date_trios_and_deduplicates_roots(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "api-data"
    source_root = tmp_path / "pool-source"
    store = _store_with_catalog(data_root)
    source_store = PreselectionPoolStore(source_root)
    source_store.materialize(_a_pool(TARGET_DATE))

    bad_sha_date = "20261013"
    source_store.materialize(_a_pool(bad_sha_date))
    source_store._write(
        f"preselection_pools/{bad_sha_date}/manifest.json",
        {"a_d1_premarket_pool": "0" * 64},
    )

    _write_misdated_trio(source_root, "20261014", _a_pool("20261015"))

    duplicate_date = "20261016"
    PreselectionPoolStore(data_root).materialize(_a_pool(duplicate_date, symbol="A.000002"))
    source_store.materialize(_a_pool(duplicate_date, symbol="A.000003"))
    _write_released_materialize_lock(source_root)

    catalog = create_app(
        data_root=data_root,
        preselection_source_root=source_root,
        current_date=CURRENT_DATE,
    )
    response = TestClient(catalog).get("/api/v1/runs/date-list").json()

    assert TARGET_DATE in response["future_target_dates"]
    assert "20261013" not in response["future_target_dates"]
    assert "20261014" not in response["future_target_dates"]
    assert response["future_target_dates"].count(duplicate_date) == 1
    evidence = response["independent_pool_evidence"][TARGET_DATE]
    assert evidence["trade_date"] == TARGET_DATE
    assert evidence["pools"]["a_d1_premarket_pool"]["status"] == "VERIFIED"
    assert evidence["pools"]["a_d1_premarket_pool"]["source_sha256"] == hashlib.sha256(
        f"{TARGET_DATE}:A.000001".encode()
    ).hexdigest()
    assert len(evidence["pools"]["a_d1_premarket_pool"]["pool_sha256"]) == 64
    assert evidence["pools"]["a_share_baimao_research_map"]["status"] == "MISSING"
