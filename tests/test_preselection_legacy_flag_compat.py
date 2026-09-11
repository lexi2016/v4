"""Declared legacy ``research_only`` spelling in HK 0.2 pool rows.

Real-data find: the HK 0.2 lane serialized the boolean as the string
"True" inside ``hkconnect_d1_top100`` pool rows, which the newly strict
shared guard rejected, blocking the whole pools surface.  The pool
boundary now tolerates exactly that truthy spelling for its guard view
while every other value keeps failing closed.
"""
from __future__ import annotations

import pytest

from infrastructure.preselection_pool_store import validate_pool_artifact


def _payload(research_only: object) -> dict:
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": "20260910",
        "pool_id": "hkconnect_d1_top100",
        "display_name": "HK D1 TOP100",
        "market": "HK_CONNECT",
        "status": "READY",
        "producer_id": "fixture",
        "source_role": "SHARED_VERIFIED_HK_0_2",
        "source_path": "x",
        "source_sha256": "a" * 64,
        "rows": [{"code": "HK.00700", "research_only": research_only}],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def test_legacy_string_true_flag_is_accepted() -> None:
    assert validate_pool_artifact(_payload("True")) == "20260910"
    assert validate_pool_artifact(_payload(True)) == "20260910"


def test_other_research_flag_values_still_fail_closed() -> None:
    for bad in ("false", "no", 0, None):
        with pytest.raises(ValueError):
            validate_pool_artifact(_payload(bad))
