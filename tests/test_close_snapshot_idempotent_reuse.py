from __future__ import annotations

from datetime import datetime

import pytest

from infrastructure.hkconnect_close_store import CloseSnapshotStore
from ops.collect_hkconnect_close_snapshot import collect_close_snapshot


def _snapshot(trade_date: str = "20260820") -> dict:
    rows = [
        {
            "trade_date": trade_date,
            "code": f"HK.{index:05d}",
            "name": f"Stock {index}",
            "close": 100.0 + index,
            "pre_close": 100.0,
            "amount": float(index),
        }
        for index in range(1, 601)
    ]
    return {
        "schema_version": "v3_5.hkconnect_close_snapshot.v1",
        "trade_date": trade_date,
        "status": "READY",
        "source_mode": "FUTU_FULL_HKCONNECT_CLOSE_SNAPSHOT",
        "source_input_sha256": "a" * 64,
        "universe_count": 600,
        "same_date_row_count": 600,
        "coverage_ratio": 1.0,
        "rows": rows,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def test_historical_verified_snapshot_is_reused_without_quote_context(tmp_path):
    store = CloseSnapshotStore(tmp_path)
    store.import_snapshot(_snapshot())

    def forbidden_quote_factory():
        raise AssertionError("historical verified snapshot must not call Futu")

    result = collect_close_snapshot(
        "20260820",
        data_root=tmp_path,
        now=datetime(2026, 8, 21, 16, 20, 0),
        quote_context_factory=forbidden_quote_factory,
    )

    assert result["snapshot"]["trade_date"] == "20260820"
    assert result["publication"]["status"] == "IDEMPOTENT_REUSE"
    assert result["publication"]["reused_existing_snapshot"] is True
    assert result["publication"]["write_performed"] is False
    assert result["publication"]["production_allowed"] is False
    assert result["publication"]["buy_gate_updated"] is False
    assert result["publication"]["orders_sent"] is False


def test_historical_missing_snapshot_keeps_current_date_error(tmp_path):
    with pytest.raises(ValueError, match="restricted to the current trade date"):
        collect_close_snapshot(
            "20260820",
            data_root=tmp_path,
            now=datetime(2026, 8, 21, 16, 20, 0),
            quote_context_factory=lambda: (_ for _ in ()).throw(
                AssertionError("must not call Futu for historical missing input")
            ),
        )


def test_invalid_existing_snapshot_is_not_reused(tmp_path, monkeypatch):
    bad = _snapshot()
    bad["coverage_ratio"] = 0.5

    monkeypatch.setattr(
        CloseSnapshotStore,
        "read_snapshot",
        lambda self, _trade_date: (bad, "b" * 64),
    )
    with pytest.raises(ValueError, match="restricted to the current trade date"):
        collect_close_snapshot(
            "20260820",
            data_root=tmp_path,
            now=datetime(2026, 8, 21, 16, 20, 0),
            quote_context_factory=lambda: (_ for _ in ()).throw(
                AssertionError("invalid historical input must not call Futu")
            ),
        )
