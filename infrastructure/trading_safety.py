"""Shared trading-semantics guards for artifact stores.

Single implementation for the store modules that previously carried
divergent recursive "no trading semantics" filters.  The key sets here are
the strict superset of the previous variants: action-like keys must be
absent or WATCH_ONLY/falsey, and promotion/order flags must be absent or
falsey.
"""
from __future__ import annotations

from typing import Any, Mapping

ACTION_KEYS = frozenset(
    {"buy", "sell", "order", "trade", "side", "action", "signal", "order_status"}
)
FALSE_ONLY_KEYS = frozenset(
    {
        "production_allowed",
        "buy_gate_updated",
        "orders_sent",
        "order_sent",
        "order_allowed",
        "opens_buy_gate",
        "formal_pool_write",
        "buy_gate_write",
    }
)
_ALLOWED_ACTION_VALUES = (False, 0, None, "", "WATCH_ONLY")
_ALLOWED_FALSE_VALUES = (False, 0, None, "")


def assert_safe_tree(
    value: Any,
    *,
    label: str = "artifact",
    node_check=None,
    extra_allowed_action_values: tuple = (),
) -> None:
    """Reject promotion/order semantics anywhere in a payload tree.

    Walk every mapping/list/tuple node.  ``node_check`` lets a caller add
    per-node constraints (e.g. lane/selector identity) while sharing this
    single recursive implementation.  ``extra_allowed_action_values`` lets a
    caller declare domain-specific research vocabularies (e.g. the manager
    research advice labels); everything else stays fail-closed.
    """

    allowed_action_values = _ALLOWED_ACTION_VALUES + tuple(extra_allowed_action_values)
    if isinstance(value, Mapping):
        for key, nested in value.items():
            folded = str(key).casefold()
            if folded in ACTION_KEYS and nested not in allowed_action_values:
                raise ValueError(f"unsafe {label} trading action")
            if folded in FALSE_ONLY_KEYS and nested not in _ALLOWED_FALSE_VALUES:
                raise ValueError(f"unsafe {label} trading state")
            if node_check is not None:
                node_check(folded, nested)
            assert_safe_tree(
                nested,
                label=label,
                node_check=node_check,
                extra_allowed_action_values=extra_allowed_action_values,
            )
    elif isinstance(value, (list, tuple)):
        for nested in value:
            assert_safe_tree(
                nested,
                label=label,
                node_check=node_check,
                extra_allowed_action_values=extra_allowed_action_values,
            )
