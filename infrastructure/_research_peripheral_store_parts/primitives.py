"""infrastructure.research_peripheral_store: primitives (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_item_list_body(_v4_scope, /, value, field):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid research peripheral {field}")
    rows: list[dict[str, Any]] = []
    for row in value:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid research peripheral {field} row")
        normalized = _v4_global(_v4_scope, 'dict')(row)
        if normalized.get("recommendation_status") not in (None, "RESEARCH_ONLY"):
            raise _v4_global(_v4_scope, 'ValueError')("unsafe research peripheral recommendation")
        for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
            if key in normalized and normalized[key] is not False:
                raise _v4_global(_v4_scope, 'ValueError')("unsafe research peripheral safety flag")
        rows.append(normalized)
    return rows
