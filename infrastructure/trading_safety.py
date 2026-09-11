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


def assert_safe_tree(value: Any, *, label: str = "artifact") -> None:
    """Reject trading state in every JSON-serializable container, fail closed."""
    active: set[int] = set()
    def visit(item: Any, depth: int) -> None:
        if depth > 128:
            raise ValueError(f"unsafe {label} nesting")
        if isinstance(item, (Mapping, list, tuple)):
            identity = id(item)
            if identity in active:
                raise ValueError(f"unsafe {label} cyclic value")
            active.add(identity)
            try:
                if isinstance(item, Mapping):
                    for key, nested in item.items():
                        if not isinstance(key, str):
                            raise ValueError(f"unsafe {label} non-string key")
                        folded = key.casefold()
                        if folded in ACTION_KEYS and nested not in _ALLOWED_ACTION_VALUES:
                            raise ValueError(f"unsafe {label} trading action")
                        if folded in FALSE_ONLY_KEYS and nested not in _ALLOWED_FALSE_VALUES:
                            raise ValueError(f"unsafe {label} trading state")
                        if folded == "research_only" and nested is not True:
                            raise ValueError(f"unsafe {label} research state")
                        visit(nested, depth + 1)
                else:
                    for nested in item:
                        visit(nested, depth + 1)
            finally:
                active.remove(identity)
        elif item is not None and not isinstance(item, (str, bool, int, float)):
            raise ValueError(f"unsafe {label} non-JSON value")
    visit(value, 0)
