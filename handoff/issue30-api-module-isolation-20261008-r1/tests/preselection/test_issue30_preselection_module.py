"""Module-boundary regressions, using synthetic immutable pool trios only.

Two-hunk repair behavior is revalidated, not counted as new Issue #28 work.
The new module assertions cover app registration, independent instance roots,
request date/page behavior and preserving a pending HK source with valid A.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from infrastructure.data_store import _canonical_bytes
from infrastructure.preselection_pool_store import PreselectionPoolStore
from scope_api_harness import create_app
from test_preselection_source_root_20261008 import (
    DATE, _pool_artifact, _strict_hk_artifact, _write_released_materialize_lock,
)


def _hashes(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*.json")) if path.is_file()}


def _client(tmp_path: Path, symbols: list[str], *, with_hk: bool = False) -> tuple[TestClient, Path]:
    source = tmp_path / "configured-root"
    pool_store = PreselectionPoolStore(source)
    pool_store.materialize(_pool_artifact("a_d1_premarket_pool", [{"symbol": symbol} for symbol in symbols]))
    if with_hk:
        pool_store.materialize(_strict_hk_artifact())
    _write_released_materialize_lock(source)
    return TestClient(create_app(data_root=tmp_path / "empty-api-root",
                                 preselection_source_root=source, current_date=DATE)), source


def test_reused_two_hunk_contract_preserves_configured_a_with_empty_local_pools(tmp_path: Path) -> None:
    client, source = _client(tmp_path, ["A.000001", "A.000002"], with_hk=True)
    before = _hashes(source)
    response = client.get("/api/v3/preselection-pools", params={"date": DATE, "limit": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["market_totals"] == {"A": 2, "HK": 100}
    assert payload["a_all_pool_row_count"] == 2
    assert payload["data_status"] == "PARTIAL_WITH_ROWS"
    assert [row["symbol"] for row in payload["a_all_pool_rows"]] == ["A.000001"]
    assert payload.get("configured_hk_pool_fallback", {}).get("applied") is not True
    assert payload["requested_date"] == payload["selected_date"] == DATE
    assert all(payload[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert _hashes(source) == before


def test_registered_modules_keep_per_app_source_and_catalog_isolation(tmp_path: Path) -> None:
    first, first_source = _client(tmp_path / "first", ["A.000010"])
    second, second_source = _client(tmp_path / "second", ["A.000020"])
    before = (_hashes(first_source), _hashes(second_source))
    one = first.get("/api/v3/preselection-pools").json()
    two = second.get("/api/v3/preselection-pools").json()
    again = first.get("/api/v3/preselection-pools").json()
    assert [row["symbol"] for row in one["a_all_pool_rows"]] == ["A.000010"]
    assert [row["symbol"] for row in two["a_all_pool_rows"]] == ["A.000020"]
    assert one["requested_date"] is None
    assert one["selected_date"] == two["selected_date"] == DATE
    assert one["input_fingerprint"] == again["input_fingerprint"]
    assert one["input_fingerprint"] != two["input_fingerprint"]
    assert (_hashes(first_source), _hashes(second_source)) == before


def test_router_page_overrides_offset_without_truncating_full_input_identity(tmp_path: Path) -> None:
    client, source = _client(tmp_path, ["A.000001", "A.000002", "A.000003"])
    before = _hashes(source)
    page = client.get("/api/v3/preselection-pools", params={"date": DATE, "limit": 1, "page": 2, "offset": 0}).json()
    full = client.get("/api/v3/preselection-pools", params={"date": DATE, "limit": 300}).json()
    assert [row["symbol"] for row in page["a_all_pool_rows"]] == ["A.000002"]
    assert page["page"] == 2
    assert page["a_all_pool_row_count"] == full["a_all_pool_row_count"] == 3
    assert page["input_fingerprint"] == full["input_fingerprint"]
    assert _hashes(source) == before


def test_router_retains_calendar_validation_and_explicit_date_isolation(tmp_path: Path) -> None:
    client, source = _client(tmp_path, ["A.000001"])
    before = _hashes(source)
    assert client.get("/api/v3/preselection-pools", params={"date": "20260230"}).status_code == 422
    other = client.get("/api/v3/preselection-pools", params={"date": "20261007"}).json()
    assert other["requested_date"] == other["selected_date"] == "20261007"
    assert other["a_all_pool_row_count"] == 0
    assert other["data_status"] == "DATA_BLOCKED_EMPTY"
    assert _hashes(source) == before


def test_pending_hk_fallback_does_not_hide_valid_local_a(tmp_path: Path) -> None:
    local = tmp_path / "local"
    source = tmp_path / "configured"
    PreselectionPoolStore(local).materialize(_pool_artifact("a_d1_premarket_pool", [{"symbol": "A.000010"}]))
    source_store = PreselectionPoolStore(source)
    source_store.materialize(_strict_hk_artifact())
    pending = source / source_store._pending_relative(trade_date=DATE, pool_id="hkconnect_d1_top100")
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text('{"test_only_pending":true}\n')
    before = (_hashes(local), _hashes(source))
    client = TestClient(create_app(data_root=local, preselection_source_root=source, current_date=DATE))
    response = client.get("/api/v3/preselection-pools", params={"date": DATE}).json()
    assert response["market_totals"] == {"A": 1, "HK": 0}
    assert response["configured_hk_pool_fallback"]["applied"] is False
    assert response["configured_hk_pool_fallback"]["reason"] == "source_pending_commit"
    assert (_hashes(local), _hashes(source)) == before


def _corrupt_manifest(source: Path, pool_id: str = "a_d1_premarket_pool") -> None:
    path = source / "preselection_pools" / DATE / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest[pool_id] = "0" * 64
    path.write_bytes(_canonical_bytes(manifest))


def test_sha_quarantine_recovery_preserves_good_a_and_pending_hk_bytes(tmp_path: Path) -> None:
    client, source = _client(tmp_path, ["A.000001"], with_hk=True)
    pool_store = PreselectionPoolStore(source)
    pool_store.materialize(_pool_artifact("a_share_research_recommendation_pool", [{"symbol": "A.000020"}]))
    _corrupt_manifest(source)
    pending = source / pool_store._pending_relative(trade_date=DATE, pool_id="hkconnect_d1_top100")
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text('{"test_only_pending":true}\n')
    before = _hashes(source)
    payload = client.get("/api/v3/preselection-pools", params={"date": DATE}).json()
    assert payload["data_status"] == "PARTIAL_WITH_ROWS"
    assert payload["market_totals"] == {"A": 1, "HK": 0}
    assert [row["symbol"] for row in payload["a_all_pool_rows"]] == ["A.000020"]
    assert payload["source_quarantine_recovery"]["applied"] is True
    pending_pool = next(pool for pool in payload["pools"] if pool["pool_id"] == "hkconnect_d1_top100")
    assert "POOL_SOURCE_PENDING_COMMIT:hkconnect_d1_top100" in pending_pool["cannot_confirm"]
    assert _hashes(source) == before


def test_all_bad_sources_remain_blocked_without_fabricated_success(tmp_path: Path) -> None:
    client, source = _client(tmp_path, ["A.000001"])
    _corrupt_manifest(source)
    before = _hashes(source)
    payload = client.get("/api/v3/preselection-pools", params={"date": DATE}).json()
    assert payload["data_status"] == "DATA_BLOCKED_EMPTY"
    assert payload["ok"] is False
    assert payload["a_all_pool_row_count"] == 0
    assert payload.get("source_quarantine_recovery", {}).get("applied") is not True
    assert _hashes(source) == before


def test_bad_pool_on_other_date_never_recovers_current_request(tmp_path: Path) -> None:
    client, source = _client(tmp_path, ["A.000001"])
    PreselectionPoolStore(source).materialize(_pool_artifact("a_share_research_recommendation_pool", [{"symbol": "A.000020"}]))
    _corrupt_manifest(source)
    before = _hashes(source)
    payload = client.get("/api/v3/preselection-pools", params={"date": "20261007"}).json()
    assert payload["data_status"] == "DATA_BLOCKED_EMPTY"
    assert payload["a_all_pool_row_count"] == 0
    assert payload["requested_date"] == payload["selected_date"] == "20261007"
    assert payload.get("source_quarantine_recovery", {}).get("applied") is not True
    assert _hashes(source) == before


def test_unreleased_source_lease_prevents_sha_quarantine_recovery(tmp_path: Path) -> None:
    client, source = _client(tmp_path, ["A.000001"])
    PreselectionPoolStore(source).materialize(_pool_artifact("a_share_research_recommendation_pool", [{"symbol": "A.000020"}]))
    _corrupt_manifest(source)
    (source / "preselection_pools/.materialize.lock").write_text('{"token":"not-released"}\n')
    before = _hashes(source)
    payload = client.get("/api/v3/preselection-pools", params={"date": DATE}).json()
    assert payload["data_status"] == "DATA_BLOCKED_EMPTY"
    assert payload["a_all_pool_row_count"] == 0
    assert payload.get("source_quarantine_recovery", {}).get("applied") is not True
    assert _hashes(source) == before


def test_undeclared_domain_block_is_not_reinterpreted_as_bad_pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.v35_api import preselection_service

    client, source = _client(tmp_path, ["A.000001"])
    reason = "UNDECLARED_MODEL_OR_PROVENANCE_GATE_FAILURE"
    blocked = preselection_service.preselection_domain._blocked(DATE, reason)
    monkeypatch.setattr(preselection_service, "preselection", lambda *args, **kwargs: dict(blocked))
    before = _hashes(source)
    payload = client.get("/api/v3/preselection-pools", params={"date": DATE}).json()
    assert payload["data_status"] == "DATA_BLOCKED_EMPTY"
    assert payload["blocking_reasons"] == [reason]
    assert payload["a_all_pool_row_count"] == 0
    assert payload.get("source_quarantine_recovery", {}).get("applied") is not True
    assert _hashes(source) == before


def test_undeclared_exception_is_not_swallowed_by_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.v35_api import preselection_service

    client, source = _client(tmp_path, ["A.000001"])

    def broken_read(*args: object, **kwargs: object) -> dict:
        raise RuntimeError("UNDECLARED_READ_FAILURE")

    monkeypatch.setattr(preselection_service, "preselection", broken_read)
    before = _hashes(source)
    with pytest.raises(RuntimeError, match="UNDECLARED_READ_FAILURE"):
        client.get("/api/v3/preselection-pools", params={"date": DATE})
    assert _hashes(source) == before


@pytest.mark.parametrize("wrong_field", ["market", "trade_date", "target_date"])
def test_sha_recovery_rejects_inconsistent_a_row_identity(tmp_path: Path, wrong_field: str) -> None:
    client, source = _client(tmp_path, ["A.000001"])
    invalid = _pool_artifact("a_share_research_recommendation_pool", [{"symbol": "A.000020"}])
    invalid["rows"][0][wrong_field] = "HK" if wrong_field == "market" else "20261007"
    # The historical generic artifact writer validates the pool identity and
    # trio. The new recovery path must also respect explicit per-row identity.
    PreselectionPoolStore(source).materialize(invalid)
    _corrupt_manifest(source)
    before = _hashes(source)
    payload = client.get("/api/v3/preselection-pools", params={"date": DATE}).json()
    assert payload["data_status"] == "DATA_BLOCKED_EMPTY"
    assert payload["a_all_pool_row_count"] == 0
    assert payload.get("source_quarantine_recovery", {}).get("applied") is not True
    assert _hashes(source) == before


def test_unknown_snapshot_error_declines_recovery_with_original_failure_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, source = _client(tmp_path, ["A.000001"])
    PreselectionPoolStore(source).materialize(_pool_artifact("a_share_research_recommendation_pool", [{"symbol": "A.000020"}]))
    _corrupt_manifest(source)
    original = PreselectionPoolStore.read_pool_snapshot

    def fail_one_reader(self: PreselectionPoolStore, trade_date: str, pool_id: str, *, lock_lease: object | None = None) -> dict:
        if pool_id == "a_share_research_recommendation_pool":
            raise ValueError("UNDECLARED_POOL_READER_FAILURE")
        return original(self, trade_date, pool_id, lock_lease=lock_lease)

    monkeypatch.setattr(PreselectionPoolStore, "read_pool_snapshot", fail_one_reader)
    before = _hashes(source)
    payload = client.get("/api/v3/preselection-pools", params={"date": DATE}).json()
    assert payload["data_status"] == "DATA_BLOCKED_EMPTY"
    assert payload["blocking_reasons"] == [
        "V3.5 independent pool receipt cannot be confirmed: preselection-pool manifest or receipt SHA mismatch"
    ]
    assert payload["source_quarantine_recovery"]["applied"] is False
    assert payload["source_quarantine_recovery"]["detail"] == "UNDECLARED_POOL_READER_FAILURE"
    assert _hashes(source) == before
