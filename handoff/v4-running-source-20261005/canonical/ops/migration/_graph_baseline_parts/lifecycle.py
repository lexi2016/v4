"""ops.migration.graph_baseline: lifecycle (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_lifecycle_body(_v4_scope, /, record, context):
    if record.get("disposition") not in _v4_global(_v4_scope, '_DISPOSITIONS'):
        raise _v4_global(_v4_scope, 'GraphBaselineError')(f"invalid disposition in {context}")
    if record.get("status") not in _v4_global(_v4_scope, '_STATUSES'):
        raise _v4_global(_v4_scope, 'GraphBaselineError')(f"invalid status in {context}")
    evidence = record.get("replacement_evidence")
    if not _v4_global(_v4_scope, 'isinstance')(evidence, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'GraphBaselineError')(f"invalid replacement evidence in {context}")
    for item in evidence:
        if (
            not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping'))
            or not _v4_global(_v4_scope, 'isinstance')(item.get("kind"), _v4_global(_v4_scope, 'str'))
            or not item["kind"]
        ):
            raise _v4_global(_v4_scope, 'GraphBaselineError')(f"invalid replacement evidence in {context}")
        _v4_global(_v4_scope, '_relative_path')(item.get("path"), context=f"replacement evidence in {context}")
        if "line" in item and (
            _v4_global(_v4_scope, 'type')(item["line"]) is not _v4_global(_v4_scope, 'int') or item["line"] < 1
        ):
            raise _v4_global(_v4_scope, 'GraphBaselineError')(f"invalid replacement evidence in {context}")
    if record.get("status") == "PENDING" and evidence:
        raise _v4_global(_v4_scope, 'GraphBaselineError')(f"PENDING record has replacement evidence in {context}")
    if record.get("status") == "COMPLETE" and not evidence:
        raise _v4_global(_v4_scope, 'GraphBaselineError')(
            f"COMPLETE record requires replacement evidence in {context}"
        )
    graph_node_ids = record.get("graph_node_ids")
    if (
        not _v4_global(_v4_scope, 'isinstance')(graph_node_ids, _v4_global(_v4_scope, 'list'))
        or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or not value for value in graph_node_ids)
        or graph_node_ids != _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(graph_node_ids))
    ):
        raise _v4_global(_v4_scope, 'GraphBaselineError')(f"invalid graph_node_ids in {context}")
