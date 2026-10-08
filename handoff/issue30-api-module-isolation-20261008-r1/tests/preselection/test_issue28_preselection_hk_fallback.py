"""Issue #28 exact-date HK fallback with local A ownership preserved.

Run inside the complete candidate app, alongside the unchanged frozen
test_preselection_source_root_20261008.py. These are synthetic storage/API
fixtures; passing them never certifies a real HK producer or natural slot.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scope_api_harness import create_app
from infrastructure.data_store import _canonical_bytes
from infrastructure.preselection_pool_store import PreselectionPoolStore
from test_preselection_source_root_20261008 import (
    DATE,
    _pool_artifact,
    _strict_hk_artifact,
    _write_released_materialize_lock,
)


def _dated_hk_pool(*, target: str = DATE, signal: str = "20261007") -> dict:
    pool = _strict_hk_artifact()
    run_id = f"{target}-hk-connect-top100-test"
    source_path = f"runs/{target}/HK_CONNECT_D1_TOP100_0_2/{run_id}/artifact.csv"
    pool.update(trade_date=target, target_date=target, signal_date=signal,
                source_run_id=run_id, source_path=source_path)
    provenance = pool["historical_provenance"]
    provenance.update(
        price_signal_date=signal,
        eligibility_source_date="20260930",
        eligibility_source_captured_at="2026-09-30T17:20:08+08:00",
        d1_source_run_id=run_id,
        d1_source_artifact_relative=source_path,
    )
    for row in pool["rows"]:
        row.update(trade_date=target, target_date=target, signal_date=signal)
    return pool


def _authoritative_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "preselection_pools").rglob("*.json"))
    }


def _fixture(tmp_path: Path, hk_pool: dict) -> tuple[TestClient, Path, Path]:
    local = tmp_path / "api-root"
    source = tmp_path / "configured-root"
    PreselectionPoolStore(local).materialize(
        _pool_artifact(
            "a_d1_premarket_pool",
            [{"symbol": "A.000010"}, {"symbol": "A.000011"}],
        )
    )
    source_store = PreselectionPoolStore(source)
    source_store.materialize(
        _pool_artifact("a_d1_premarket_pool", [{"symbol": "A.000020"}])
    )
    source_store.materialize(hk_pool)
    _write_released_materialize_lock(source)
    client = TestClient(
        create_app(data_root=local, preselection_source_root=source, current_date=DATE)
    )
    return client, local, source


def _get(client: TestClient, *, offset: int = 0) -> dict:
    response = client.get(
        "/api/v3/preselection-pools",
        params={"date": DATE, "limit": 1, "offset": offset},
    )
    assert response.status_code == 200
    return response.json()


def test_local_a_survives_split_date_hk_fallback_pagination_and_repeat_read(tmp_path: Path) -> None:
    client, local, source = _fixture(tmp_path, _dated_hk_pool())
    before = (_authoritative_hashes(local), _authoritative_hashes(source))
    first = _get(client)
    second = _get(client, offset=1)
    repeated = _get(client)

    assert first["configured_hk_pool_fallback"]["applied"] is True
    assert first["market_totals"] == {"A": 2, "HK": 100}
    assert first["a_all_pool_row_count"] == 2
    assert first["data_status"] == "PARTIAL_WITH_ROWS"
    assert [row["symbol"] for row in first["a_all_pool_rows"]] == ["A.000010"]
    assert [row["symbol"] for row in second["a_all_pool_rows"]] == ["A.000011"]
    assert first["pagination"]["arrays"]["a_all_pool_rows"]["total_rows"] == 2
    assert first["pagination"]["arrays"]["a_all_pool_rows"]["has_more"] is True
    hk = next(pool for pool in first["pools"] if pool["pool_id"] == "hkconnect_d1_top100")
    assert hk["pool_size"] == 100
    assert hk["rows"][0]["signal_date"] == "20261007"
    assert hk["historical_provenance"]["eligibility_source_date"] == "20260930"
    assert first["input_fingerprint"] == second["input_fingerprint"] == repeated["input_fingerprint"]
    for payload in (first, second, repeated):
        assert all(payload[name] is False for name in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert before == (_authoritative_hashes(local), _authoritative_hashes(source))


@pytest.mark.parametrize("failure", ["other_target_date", "manifest_sha", "receipt_sha"])
def test_unverified_or_other_date_hk_does_not_replace_valid_local_a(tmp_path: Path, failure: str) -> None:
    pool = _dated_hk_pool(
        target="20261007" if failure == "other_target_date" else DATE,
        signal="20261006" if failure == "other_target_date" else "20261007",
    )
    client, local, source = _fixture(tmp_path, pool)
    directory = source / "preselection_pools" / DATE
    if failure == "manifest_sha":
        path = directory / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["hkconnect_d1_top100"] = "0" * 64
        path.write_bytes(_canonical_bytes(manifest))
    elif failure == "receipt_sha":
        path = directory / "receipts" / "hkconnect_d1_top100.json"
        receipt = json.loads(path.read_text())
        receipt["artifact_sha256"] = "0" * 64
        path.write_bytes(_canonical_bytes(receipt))
    before = (_authoritative_hashes(local), _authoritative_hashes(source))

    response = _get(client)
    assert response["market_totals"] == {"A": 2, "HK": 0}
    assert response["a_all_pool_row_count"] == 2
    assert [row["symbol"] for row in response["a_all_pool_rows"]] == ["A.000010"]
    assert response.get("configured_hk_pool_fallback", {}).get("applied") is not True
    if failure != "other_target_date":
        assert response["configured_hk_pool_fallback"]["status"] == "CANNOT_CONFIRM"
        assert response["configured_hk_pool_fallback"]["reason"] == "source_integrity_unconfirmed"
    assert before == (_authoritative_hashes(local), _authoritative_hashes(source))
