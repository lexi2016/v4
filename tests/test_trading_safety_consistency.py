"""Cross-store consistency for the shared trading-semantics guard."""
from __future__ import annotations

import pytest

from infrastructure import data_store, trading_safety
from infrastructure.preselection_pool_store import _assert_safe as pool_guard
from infrastructure.stage_acquisition_universe_store import _assert_safe_tree as universe_guard
from infrastructure.stage_store import _assert_safe_tree as stage_guard

CANONICAL_VIOLATIONS = [
    ({"rows": [{"buy": "YES"}]}, "buy-in-rows"),
    ({"rows": [{"orders_sent": 1}]}, "orders-in-rows"),
    ({"meta": {"action": "BUY"}}, "action-in-meta"),
    ({"pools": [{"rows": [{"side": True}]}]}, "side-in-pools"),
    ({"meta": ({"orders_sent": True},)}, "tuple-nested"),
]


def _watch_only_guard(payload: dict) -> None:
    data_store._assert_watch_only(payload, expected_lane="lane", expected_selector="selector")


GUARDS = {
    "stage": stage_guard,
    "stage-acquisition": universe_guard,
    "preselection-pool": pool_guard,
    "watch-only": _watch_only_guard,
}


@pytest.mark.parametrize("name", sorted(GUARDS))
@pytest.mark.parametrize("payload,case_id", CANONICAL_VIOLATIONS, ids=[c for _, c in CANONICAL_VIOLATIONS])
def test_every_store_guard_rejects_canonical_trading_violations(name, payload, case_id) -> None:
    with pytest.raises(ValueError):
        GUARDS[name](payload)


@pytest.mark.parametrize("name", sorted(GUARDS))
def test_every_store_guard_allows_watch_only_rows(name) -> None:
    GUARDS[name](
        {
            "rows": [
                {
                    "symbol": "A.000001",
                    "recommendation_status": "WATCH_ONLY",
                    "buy": "WATCH_ONLY",
                    "orders_sent": False,
                }
            ]
        }
    )


def test_data_store_guard_delegates_to_shared_recursion() -> None:
    # data_store no longer carries its own recursion or key literals: the
    # shared guard walks mapping/list/tuple nodes, and the lane rules ride
    # along as a per-node check.
    with pytest.raises(ValueError, match="trading state"):
        data_store._assert_watch_only(
            {"meta": ({"orders_sent": True},)},
            expected_lane="lane",
            expected_selector="selector",
        )
    data_store._assert_watch_only(
        {"lane": "lane", "selector_status": "selector", "rows": [{"recommendation_status": "WATCH_ONLY"}]},
        expected_lane="lane",
        expected_selector="selector",
    )
    with pytest.raises(ValueError, match="unexpected selector status"):
        data_store._assert_watch_only(
            {"selector_status": "OTHER"},
            expected_lane="lane",
            expected_selector="selector",
        )


def test_shared_key_sets_cover_former_variants() -> None:
    # The pool guard previously missed action words entirely, and the stage
    # guards missed the four pool-only write flags; the shared superset must
    # cover both legacy sets.
    assert {"buy", "sell", "order", "trade", "side", "action", "signal"} <= trading_safety.ACTION_KEYS
    assert {"production_allowed", "buy_gate_updated", "orders_sent", "order_sent"} <= trading_safety.FALSE_ONLY_KEYS
    assert {
        "formal_pool_write",
        "buy_gate_write",
        "opens_buy_gate",
        "order_allowed",
    } <= trading_safety.FALSE_ONLY_KEYS


def test_data_store_watch_only_guard_rejects_action_words() -> None:
    with pytest.raises(ValueError):
        data_store._assert_watch_only({"buy": "YES"}, expected_lane="lane", expected_selector="selector")
