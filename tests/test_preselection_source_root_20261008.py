from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from infrastructure.data_store import NativeDataStore, _canonical_bytes
from infrastructure.preselection_pool_store import PreselectionPoolStore


DATE = "20261008"


def _pool_artifact(pool_id: str, rows: list[dict[str, object]]) -> dict[str, object]:
    market = "HK" if pool_id == "hkconnect_d1_top100" else "A"
    normalized = [
        {
            **row,
            "market": market,
            "pool_id": pool_id,
            "pool_rank": rank,
            "trade_date": DATE,
            "target_date": DATE,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        for rank, row in enumerate(rows, start=1)
    ]
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": DATE,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": market,
        "status": "READY" if normalized else "CANNOT_CONFIRM",
        "producer_id": "test_preselection_source_root",
        "source_role": "RAW_SOURCE" if normalized else "EXPECTED_MISSING",
        "source_path": f"test/{DATE}/{pool_id}.json" if normalized else "",
        "source_sha256": hashlib.sha256(pool_id.encode()).hexdigest(),
        "rows": normalized,
        "cannot_confirm": [] if normalized else ["EXPECTED_MISSING"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _write_released_materialize_lock(source_root: Path) -> None:
    lock_path = source_root / "preselection_pools" / ".materialize.lock"
    lock_payload = {
        "schema_version": "v3_5_interprocess_lock.v1",
        "pid": 2147483647,
        "token": "RELEASED",
    }
    descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
        lock_file.write(json.dumps(lock_payload, separators=(",", ":")))


def _remove_pool_identity_field(
    source_root: Path, pool_id: str, field: str
) -> None:
    store = PreselectionPoolStore(source_root)
    artifact_path = source_root / "preselection_pools" / DATE / f"{pool_id}.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact.pop(field)
    store._write(f"preselection_pools/{DATE}/{pool_id}.json", artifact)
    manifest_path = source_root / "preselection_pools" / DATE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[pool_id] = hashlib.sha256(_canonical_bytes(artifact)).hexdigest()
    store._write(f"preselection_pools/{DATE}/manifest.json", manifest)


def _strict_hk_artifact() -> dict[str, object]:
    source_sha = "1" * 64
    source_manifest_sha = "2" * 64
    source_receipt_sha = "3" * 64
    source_run_id = f"{DATE}-hk-connect-top100-test"
    source_path = f"runs/{DATE}/HK_CONNECT_D1_TOP100_0_2/{source_run_id}/artifact.csv"
    signal_date = "20260930"
    rows = [
        {
            "symbol": f"HK.{rank:05d}",
            "code": f"HK.{rank:05d}",
            "market": "HK",
            "pool_id": "hkconnect_d1_top100",
            "pool_rank": rank,
            "trade_date": DATE,
            "target_date": DATE,
            "signal_date": signal_date,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        for rank in range(1, 101)
    ]
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": DATE,
        "pool_id": "hkconnect_d1_top100",
        "display_name": "HK Connect D-1 Top 100",
        "market": "HK",
        "status": "STRICT_0_2_READY",
        "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "SHARED_VERIFIED_HK_0_2",
        "source_path": source_path,
        "source_sha256": source_sha,
        "source_run_id": source_run_id,
        "source_manifest_sha256": source_manifest_sha,
        "source_receipt_sha256": source_receipt_sha,
        "signal_date": signal_date,
        "target_date": DATE,
        "stage_selection_eligible": True,
        "historical_provenance": {
            "schema_version": "v4.hk_d1_split_date_provenance.v1",
            "d1_source_artifact_relative": source_path,
            "d1_source_artifact_sha256": source_sha,
            "d1_source_manifest_sha256": source_manifest_sha,
            "d1_source_receipt_sha256": source_receipt_sha,
            "d1_source_run_id": source_run_id,
            "eligibility_source_artifact_sha256": "4" * 64,
            "eligibility_source_captured_at": "2026-09-30T17:20:08+08:00",
            "eligibility_source_date": "20260929",
            "eligibility_source_run_id": "hk-eligibility-source-test",
            "price_signal_date": signal_date,
        },
        "rows": rows,
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _client(tmp_path: Path, pools: dict[str, list[dict[str, object]]]) -> tuple[TestClient, Path]:
    source_root = tmp_path / "source-root"
    source_store = PreselectionPoolStore(source_root)
    for pool_id, rows in pools.items():
        source_store.materialize(_pool_artifact(pool_id, rows))
    _write_released_materialize_lock(source_root)
    client = TestClient(
        create_app(
            data_root=tmp_path / "api-root",
            preselection_source_root=source_root,
            current_date=DATE,
        )
    )
    return client, source_root


@pytest.fixture
def a_rows() -> dict[str, list[dict[str, object]]]:
    return {
        "a_d1_premarket_pool": [
            {"symbol": "A.000001"},
            {"symbol": "A.000002"},
            {"symbol": "A.000003"},
        ],
        "a_share_research_recommendation_pool": [
            {"symbol": "A.000002"},
            {"symbol": "A.000004"},
            {"symbol": "A.000005"},
        ],
    }


def test_api_reads_exact_source_date_dedupes_a_pools_and_keeps_hk_separate(
    tmp_path: Path,
    a_rows: dict[str, list[dict[str, object]]],
) -> None:
    pools = {
        **a_rows,
        "hkconnect_d1_top100": [
            {"symbol": "HK.00001"},
            {"symbol": "HK.00002"},
        ],
    }
    client, _source_root = _client(tmp_path, pools)

    first = client.get(
        "/api/v3/preselection-pools",
        params={"date": DATE, "limit": 2, "offset": 0},
    ).json()
    assert first["data_status"] == "PARTIAL_WITH_ROWS"
    assert first["a_all_pool_row_count"] == 5
    assert first["unified_row_count"] == 3
    assert first["market_totals"] == {"A": 5, "HK": 2}
    assert len(first["a_all_pool_rows"]) == 2
    assert first["pagination"]["arrays"]["a_all_pool_rows"]["total_rows"] == 5
    assert first["pagination"]["arrays"]["a_all_pool_rows"]["has_more"] is True
    assert first["optional_pool_status"] == "CANNOT_CONFIRM"
    assert not any(row["symbol"].startswith("HK.") for row in first["a_all_pool_rows"])
    assert all(row["market"] == "A" for row in first["unified_rows"])
    bindings = first["pool_source_bindings"]
    assert set(bindings) == {
        "a_d1_premarket_pool",
        "a_share_research_recommendation_pool",
        "hkconnect_d1_top100",
    }
    binding = bindings["a_d1_premarket_pool"]
    assert binding["physical_source_root"] == str(_source_root)
    assert binding["artifact_relative"] == (
        f"preselection_pools/{DATE}/a_d1_premarket_pool.json"
    )
    assert binding["manifest_relative"] == f"preselection_pools/{DATE}/manifest.json"
    assert binding["receipt_relative"] == (
        f"preselection_pools/{DATE}/receipts/a_d1_premarket_pool.json"
    )
    for field in (
        "artifact_raw_sha256",
        "manifest_raw_sha256",
        "receipt_raw_sha256",
    ):
        assert len(binding[field]) == 64
    assert binding["source_sha256"] == hashlib.sha256(
        "a_d1_premarket_pool".encode()
    ).hexdigest()
    assert binding["source_role"] == "RAW_SOURCE"
    assert binding["physical_status"] == "TRIO_VERIFIED"
    assert binding["projection_source_matches"] is True
    assert binding["cannot_confirm"] == []
    assert binding["stage_reuse_status"] == "REQUIRES_STAGE_CONTRACT_VALIDATION"
    assert first["pool_source_evidence"]["pools"]["a_d1_premarket_pool"][
        "status"
    ] == "VERIFIED"

    second = client.get(
        "/api/v3/preselection-pools",
        params={"date": DATE, "limit": 2, "offset": 2},
    ).json()
    third = client.get(
        "/api/v3/preselection-pools",
        params={"date": DATE, "limit": 2, "offset": 4},
    ).json()
    assert [row["symbol"] for row in second["a_all_pool_rows"]] == [
        "A.000003",
        "A.000004",
    ]
    assert [row["symbol"] for row in third["a_all_pool_rows"]] == ["A.000005"]
    assert third["pagination"]["arrays"]["a_all_pool_rows"]["complete"] is True

    missing_date = client.get(
        "/api/v3/preselection-pools",
        params={"date": "20261007", "limit": 2},
    ).json()
    assert missing_date["data_status"] == "DATA_BLOCKED_EMPTY"
    assert missing_date["a_all_pool_row_count"] == 0


def test_primary_exact_date_owns_a_pools_when_configured_source_also_has_a_rows(
    tmp_path: Path,
) -> None:
    api_root = tmp_path / "api-root"
    local_store = PreselectionPoolStore(api_root)
    local_store.materialize(
        _pool_artifact("a_d1_premarket_pool", [{"symbol": "A.000010"}])
    )
    source_root = tmp_path / "source-root"
    source_store = PreselectionPoolStore(source_root)
    source_store.materialize(
        _pool_artifact("a_d1_premarket_pool", [{"symbol": "A.000020"}])
    )
    source_store.materialize(
        _pool_artifact("a_share_research_recommendation_pool", [{"symbol": "A.000021"}])
    )
    _write_released_materialize_lock(source_root)

    client = TestClient(
        create_app(
            data_root=api_root,
            preselection_source_root=source_root,
            current_date=DATE,
        )
    )
    response = client.get(
        "/api/v3/preselection-pools",
        params={"date": DATE, "limit": 20},
    ).json()

    assert response["a_all_pool_row_count"] == 1
    assert [row["symbol"] for row in response["a_all_pool_rows"]] == ["A.000010"]


def test_primary_a_pool_can_use_only_exact_configured_hk_fallback(tmp_path: Path) -> None:
    api_root = tmp_path / "api-root"
    local_store = PreselectionPoolStore(api_root)
    local_store.materialize(
        _pool_artifact("a_d1_premarket_pool", [{"symbol": "A.000010"}])
    )

    source_root = tmp_path / "source-root"
    source_store = PreselectionPoolStore(source_root)
    source_store.materialize(
        _pool_artifact("a_d1_premarket_pool", [{"symbol": "A.000020"}])
    )
    source_store.materialize(
        _pool_artifact("a_share_research_recommendation_pool", [{"symbol": "A.000021"}])
    )
    source_store.materialize(_strict_hk_artifact())
    _write_released_materialize_lock(source_root)

    client = TestClient(
        create_app(
            data_root=api_root,
            preselection_source_root=source_root,
            current_date=DATE,
        )
    )
    response = client.get(
        "/api/v3/preselection-pools",
        params={"date": DATE, "limit": 200},
    ).json()

    assert response["configured_hk_pool_fallback"]["applied"] is True
    assert response["a_all_pool_row_count"] == 1
    assert [row["symbol"] for row in response["a_all_pool_rows"]] == ["A.000010"]
    assert response["market_totals"] == {"A": 1, "HK": 100}
    assert response["production_allowed"] is False
    assert response["buy_gate_updated"] is False
    assert response["orders_sent"] is False


def test_configured_source_lock_failure_is_not_projected_as_empty_or_quarantined(
    tmp_path: Path,
    a_rows: dict[str, list[dict[str, object]]],
) -> None:
    client, source_root = _client(tmp_path, a_rows)
    lock_path = source_root / "preselection_pools" / ".materialize.lock"
    lock_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="confirmed released flock"):
        client.get(
            "/api/v3/preselection-pools",
            params={"date": DATE, "limit": 200},
        )


def test_primary_malformed_pool_is_quarantined_without_hiding_valid_siblings(
    tmp_path: Path,
) -> None:
    api_root = tmp_path / "api-root"
    store = PreselectionPoolStore(api_root)
    store.materialize(_pool_artifact("a_d1_premarket_pool", [{"symbol": "A.000010"}]))
    store.materialize(
        _pool_artifact(
            "a_share_research_recommendation_pool", [{"symbol": "A.000021"}]
        )
    )
    (api_root / f"preselection_pools/{DATE}/a_d1_premarket_pool.json").write_bytes(
        _canonical_bytes({})
    )
    client = TestClient(create_app(data_root=api_root, current_date=DATE))

    response = client.get(
        "/api/v3/preselection-pools",
        params={"date": DATE, "limit": 200},
    ).json()

    bad = next(pool for pool in response["pools"] if pool["pool_id"] == "a_d1_premarket_pool")
    assert response["data_status"] == "PARTIAL_WITH_ROWS"
    assert response["a_all_pool_row_count"] == 1
    assert [row["symbol"] for row in response["a_all_pool_rows"]] == ["A.000021"]
    assert bad["status"] == "CANNOT_CONFIRM"
    assert bad["rows"] == []


@pytest.mark.parametrize(
    ("bad_pool_id", "tamper"),
    [
        ("a_d1_premarket_pool", "manifest_sha"),
        ("a_share_research_recommendation_pool", "receipt_sha"),
        ("a_share_baimao_research_map", "manifest_sha"),
        ("a_share_baimao_research_map", "receipt_sha"),
    ],
)
def test_bad_source_pool_is_quarantined_without_hiding_valid_a_rows(
    tmp_path: Path,
    a_rows: dict[str, list[dict[str, object]]],
    bad_pool_id: str,
    tamper: str,
) -> None:
    pools = {**a_rows, "a_share_baimao_research_map": [{"symbol": "A.000006"}]}
    client, source_root = _client(tmp_path, pools)
    pool_dir = source_root / "preselection_pools" / DATE
    if tamper == "manifest_sha":
        path = pool_dir / "manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload[bad_pool_id] = "0" * 64
    else:
        path = pool_dir / "receipts" / f"{bad_pool_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["artifact_sha256"] = "0" * 64
    path.write_bytes(_canonical_bytes(payload))

    response = client.get(
        "/api/v3/preselection-pools",
        params={"date": DATE, "limit": 200},
    ).json()
    quarantined = next(pool for pool in response["pools"] if pool["pool_id"] == bad_pool_id)

    assert response["data_status"] == "PARTIAL_WITH_ROWS"
    assert response["a_all_pool_row_count"] > 0
    assert quarantined["status"] == "CANNOT_CONFIRM"
    assert quarantined["rows"] == []
    assert any(
        f"POOL_SOURCE_INTEGRITY_UNCONFIRMED:{bad_pool_id}" in reason
        for reason in quarantined["cannot_confirm"]
    )
    pool_evidence = response["pool_source_evidence"]
    assert pool_evidence["trade_date"] == DATE
    assert pool_evidence["pools"][bad_pool_id]["status"] == "CANNOT_CONFIRM"
    assert any(
        reason.startswith(f"PRESELECTION_POOL_INTEGRITY:{bad_pool_id}:")
        for reason in pool_evidence["pools"][bad_pool_id]["diagnostics"]
    )
    assert pool_evidence["pools"][bad_pool_id]["pool_sha256"] is None
    verified_sibling = next(
        pool_id
        for pool_id in (
            "a_d1_premarket_pool",
            "a_share_research_recommendation_pool",
            "a_share_baimao_research_map",
        )
        if pool_id != bad_pool_id
    )
    legacy_bindings = response["pool_source_bindings"]
    assert bad_pool_id not in legacy_bindings
    assert legacy_bindings[verified_sibling]["physical_status"] == "TRIO_VERIFIED"
    assert len(legacy_bindings[verified_sibling]["artifact_raw_sha256"]) == 64
    assert len(
        pool_evidence["pools"][verified_sibling]["pool_sha256"]
    ) == 64
    assert pool_evidence["pools"][verified_sibling]["status"] == "VERIFIED"
    assert pool_evidence["pools"][verified_sibling]["source_sha256"] == hashlib.sha256(
        verified_sibling.encode()
    ).hexdigest()
    assert len(pool_evidence["pools"][verified_sibling]["pool_sha256"]) == 64
    assert response["production_allowed"] is False
    assert response["buy_gate_updated"] is False
    assert response["orders_sent"] is False


def test_configured_source_date_list_recovers_verified_pool_evidence(
    tmp_path: Path,
) -> None:
    client, source_root = _client(
        tmp_path,
        {"a_d1_premarket_pool": [{"symbol": "A.000001"}]},
    )

    response = client.get(
        "/api/v1/runs/date-list",
        params={"date": DATE},
    ).json()

    assert response["ok"] is True
    assert response["requested_date"] == DATE
    assert DATE in response["dates"]
    evidence = response["independent_pool_evidence"][DATE]
    assert evidence["pools"]["a_d1_premarket_pool"]["status"] == "VERIFIED"
    assert evidence["pools"]["a_d1_premarket_pool"]["physical_source_root"] == str(
        source_root
    )


@pytest.mark.parametrize("missing_field", ["source_sha256", "source_role"])
def test_secondary_missing_identity_field_is_quarantined_without_hiding_valid_a_rows(
    tmp_path: Path,
    a_rows: dict[str, list[dict[str, object]]],
    missing_field: str,
) -> None:
    client, source_root = _client(tmp_path, a_rows)
    bad_pool_id = "a_d1_premarket_pool"
    _remove_pool_identity_field(source_root, bad_pool_id, missing_field)

    response = client.get(
        "/api/v3/preselection-pools",
        params={"date": DATE, "limit": 200},
    ).json()
    quarantined = next(
        pool for pool in response["pools"] if pool["pool_id"] == bad_pool_id
    )

    assert response["data_status"] == "PARTIAL_WITH_ROWS"
    assert response["a_all_pool_row_count"] == 3
    assert [row["symbol"] for row in response["a_all_pool_rows"]] == [
        "A.000002",
        "A.000004",
        "A.000005",
    ]
    assert quarantined["status"] == "CANNOT_CONFIRM"
    assert quarantined["rows"] == []
    assert any(
        reason.startswith(f"PRESELECTION_POOL_INTEGRITY:{bad_pool_id}:")
        for reason in quarantined["cannot_confirm"]
    )
    evidence = response["pool_source_evidence"]
    assert evidence["pools"][bad_pool_id]["status"] == "CANNOT_CONFIRM"
    assert evidence["pools"][bad_pool_id]["source_sha256"] is None
    assert any(
        reason.startswith(f"PRESELECTION_POOL_INTEGRITY:{bad_pool_id}:")
        for reason in evidence["pools"][bad_pool_id]["diagnostics"]
    )
    sibling = evidence["pools"]["a_share_research_recommendation_pool"]
    assert sibling["status"] == "VERIFIED"
    assert len(sibling["pool_sha256"]) == 64
    assert response["production_allowed"] is False
    assert response["buy_gate_updated"] is False
    assert response["orders_sent"] is False
