"""Exact frozen GET route + real persistence/consumer, in-process HTTP only."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from api_route_harness import create_isolated_workbench
from test_a_auction_prev_close import (
    OMIT, DATE, STAGE, auction_row, through_adapter, publish_and_read, store_bytes,
)


@pytest.mark.parametrize("previous,pct,reason", [
    (100, 5, None),
    (OMIT, None, "PREV_CLOSE_PRICE_MISSING"),
    (None, None, "PREV_CLOSE_PRICE_MISSING"),
    (0, None, "PREV_CLOSE_PRICE_INVALID"),
    (-100, None, "PREV_CLOSE_PRICE_INVALID"),
    (float("nan"), None, "PREV_CLOSE_PRICE_INVALID"),
    (float("inf"), None, "PREV_CLOSE_PRICE_INVALID"),
], ids=["100-to-105", "absent", "null", "zero", "negative", "nan", "infinite"])
def test_workbench_http_preserves_auction_evidence_and_identity(tmp_path, previous, pct, reason):
    envelope = through_adapter([auction_row(previous=previous, price=105)])
    verified, _, store = publish_and_read(tmp_path, envelope)
    before = store_bytes(store.root)
    app = create_isolated_workbench(store.root)
    with TestClient(app) as client:
        response = client.get("/api/v3/workbench/stage", params={"date": DATE, "stage": STAGE, "limit": 10})
    assert response.status_code == 200
    payload = response.json()
    # Decode as strict JSON too: no NaN or Infinity may leak to the wire.
    json.loads(response.text, parse_constant=lambda value: pytest.fail(f"nonfinite JSON: {value}"))
    for row in (payload["selection_markets"]["A_SHARE"]["rows"][0],
                payload["markets"]["A"]["rows"][0], payload["unified_rows"][0]):
        assert row["prev_close_price"] == (100 if pct == 5 else None)
        assert row["current_change_pct"] == row["qmt_gap_pct"] == pct
        assert row.get("current_change_pct_missing_reason") == reason
    assert payload["selection_markets"]["A_SHARE"]["run_id"] == verified["run_id"]
    assert payload["markets"]["A"]["artifact_id"] == verified["artifact_id"]
    assert payload["selected_a_rows"] == 1
    assert payload["status"] == "PARTIAL_WITH_ROWS"  # Synthetic store has no HK artifact.
    assert payload["markets"]["HK"]["status"] == "CANNOT_CONFIRM"
    assert payload["selected_hk_rows"] is None
    assert payload["write_performed"] is False
    assert all(payload[flag] is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert store_bytes(store.root) == before


def test_http_flat_auction_keeps_observed_zero(tmp_path):
    _, _, store = publish_and_read(tmp_path, through_adapter([auction_row(previous=100, price=100)]))
    with TestClient(create_isolated_workbench(store.root)) as client:
        response = client.get("/api/v3/workbench/stage", params={"date": DATE, "stage": STAGE, "limit": 10})
    assert response.status_code == 200
    row = response.json()["unified_rows"][0]
    assert row["prev_close_price"] == 100
    assert row["current_change_pct"] == row["qmt_gap_pct"] == 0
    assert row.get("current_change_pct_missing_reason") is None
