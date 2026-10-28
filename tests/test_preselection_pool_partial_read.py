from __future__ import annotations

import hashlib

import pytest

from domains.stage_input_producer import StageInputProducer
from infrastructure.data_store import NativeDataStore
from infrastructure.owned_io import OwnedIOError
from infrastructure.preselection_pool_store import (
    PreselectionPoolIntegrityError,
    PreselectionPoolStore,
)
from infrastructure.stage_store import StageStore


DATE = "20260730"


def _pool(pool_id: str, symbol: str) -> dict:
    market = "HK" if pool_id == "hkconnect_d1_top100" else "A"
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": DATE,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": market,
        "status": "READY",
        "producer_id": "TEST",
        "source_role": "RAW_SOURCE",
        "source_path": f"fixture/{pool_id}.json",
        "source_sha256": hashlib.sha256(pool_id.encode()).hexdigest(),
        "rows": [
            {
                "symbol": symbol,
                "market": market,
                "pool_id": pool_id,
                "pool_rank": 1,
                "trade_date": DATE,
                "target_date": DATE,
                "recommendation_status": "WATCH_ONLY",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        ],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


class NoQuotes:
    def snapshot(self, *args, **kwargs) -> dict:
        raise AssertionError("quote provider must not run after source acquisition fails")


def test_pool_integrity_is_quarantined_but_root_and_lock_failures_abort(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    store = PreselectionPoolStore(root)
    store.materialize(_pool("a_d1_premarket_pool", "A.000001"))
    bad = store.materialize(_pool("a_share_baimao_research_map", "A.000004"))
    (root / bad["receipt_path"]).write_bytes(b'{"wrong":true}')

    snapshots, errors = store.read_all_with_quarantine(DATE)

    assert [snapshot["artifact"]["pool_id"] for snapshot in snapshots] == [
        "a_d1_premarket_pool"
    ]
    assert len(errors) == 1
    assert isinstance(errors[0], PreselectionPoolIntegrityError)
    assert errors[0].pool_id == "a_share_baimao_research_map"
    assert "receipt" in errors[0].reason.lower()

    data_store = NativeDataStore(root)
    stage_store = StageStore(root)
    producer = StageInputProducer(data_store, stage_store, NoQuotes())

    def fail_root(*args, **kwargs):
        raise OwnedIOError("OWNED_ROOT_REPLACED")

    monkeypatch.setattr(PreselectionPoolStore, "read_pool_snapshot", fail_root)
    with pytest.raises(OwnedIOError, match="OWNED_ROOT_REPLACED"):
        producer.produce(DATE, "STAGE_0925")
    assert not (root / "stage_inputs" / DATE / "STAGE_0925.json").exists()

    monkeypatch.undo()

    def fail_lock(*args, **kwargs):
        raise TimeoutError("data-root import lock timeout")

    monkeypatch.setattr(
        "infrastructure.preselection_pool_store.owned_interprocess_lock",
        fail_lock,
    )
    with pytest.raises(TimeoutError, match="data-root import lock timeout"):
        producer.produce(DATE, "STAGE_0925")
    assert not (root / "stage_inputs" / DATE / "STAGE_0925.json").exists()


def test_pool_preflight_failure_is_not_quarantined_or_published(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    store = PreselectionPoolStore(root)
    store.materialize(_pool("a_d1_premarket_pool", "A.000001"))
    data_store = NativeDataStore(root)
    producer = StageInputProducer(data_store, StageStore(root), NoQuotes())

    def fail_preflight(self, trade_date: str, pool_ids) -> None:
        raise PermissionError("preflight refused pending-read recovery")

    monkeypatch.setattr(
        PreselectionPoolStore,
        "_preflight_pending_read_recovery",
        fail_preflight,
    )

    with pytest.raises(PermissionError, match="preflight refused"):
        producer.produce(DATE, "STAGE_0925")
    assert not (root / "stage_inputs" / DATE / "STAGE_0925.json").exists()


def test_preflight_file_error_is_not_treated_as_a_missing_pool(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    store = PreselectionPoolStore(root)
    store.materialize(_pool("a_d1_premarket_pool", "A.000001"))
    data_store = NativeDataStore(root)
    stage_store = StageStore(root)
    producer = StageInputProducer(data_store, stage_store, NoQuotes())
    monkeypatch.setattr(
        data_store,
        "read_payload",
        lambda _trade_date: {
            "a_all_pool_rows": [],
            "rows": [],
            "producer_status": "PARTIAL",
            "canonical_main_pool_confirmed": False,
            "cannot_confirm": ["FALLBACK_MUST_NOT_BE_USED"],
        },
    )

    def fail_preflight(self, trade_date: str, pool_ids) -> None:
        raise FileNotFoundError("preflight read failed")

    monkeypatch.setattr(
        PreselectionPoolStore,
        "_preflight_pending_read_recovery",
        fail_preflight,
    )

    with pytest.raises(FileNotFoundError, match="preflight read failed"):
        producer.produce(DATE, "STAGE_0925")
    assert not (root / "stage_inputs" / DATE / "STAGE_0925.json").exists()
