#!/usr/bin/env python3
"""Offline shape-only smoke. It never consumes market or owner data."""
from __future__ import annotations
import json
from pathlib import Path

FIXTURE = Path(__file__).with_name("synthetic_workspace_contract.json")
EXPECTED_CHANNELS = {"ANNOUNCEMENT", "HK_CONNECT", "OVERSOLD"}
def main() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["fixture_kind"] == "SYNTHETIC_CONTRACT_ONLY_NOT_MARKET_DATA"
    assert payload["target_trade_date"] == "20261009"
    assert payload["date_bindings"] == {
        "plan_date": "20261009",
        "selection_date": "20261009",
        "announcement_date": "20261008",
    }
    channels = payload["channels"]
    assert {row["channel"] for row in channels} == EXPECTED_CHANNELS
    for row in channels:
        assert row["status"] == "CANNOT_CONFIRM"
        assert row["row_count"] == 0
        assert row["run_id"] is None
        assert row["gaps"]
    plan = payload["plan_product"]
    assert plan["status"] == "NOT_MATERIALIZED"
    assert plan["consumed"] is False and plan["run_id"] is None
    assert plan["stock_count"] == 0 and plan["input_identity"] is None
    assert payload["safety"] == {
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    print("CONTRACT_SMOKE=PASS (synthetic fail-closed envelope only)")
if __name__ == "__main__":
    main()
