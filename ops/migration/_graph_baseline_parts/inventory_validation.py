"""ops.migration.graph_baseline: inventory_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _validate_inventory_v2_body(_v4_scope, /, inventory, *, baseline):
    _v4_global(_v4_scope, 'validate_graph_baseline')(baseline)
    if not _v4_global(_v4_scope, 'isinstance')(inventory, _v4_global(_v4_scope, 'Mapping')) or inventory.get("schema_version") != _v4_global(_v4_scope, 'INVENTORY_SCHEMA'):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("unknown inventory v2 schema")
    inventory_semantic_hash = inventory.get("inventory_semantic_hash")
    if not _v4_global(_v4_scope, '_is_sha256')(inventory_semantic_hash):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid inventory semantic hash")
    unhashed = {
        key: _v4_global(_v4_scope, 'deepcopy')(value)
        for key, value in inventory.items()
        if key != "inventory_semantic_hash"
    }
    if _v4_global(_v4_scope, '_digest_bytes')(_v4_global(_v4_scope, '_canonical_bytes')(unhashed)) != inventory_semantic_hash:
        raise _v4_global(_v4_scope, 'GraphBaselineError')("inventory semantic hash mismatch")
    if inventory.get("graph_baseline_semantic_hash") != baseline.get("semantic_hash"):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("inventory graph baseline hash mismatch")
    counts = inventory.get("counts")
    if not _v4_global(_v4_scope, 'isinstance')(counts, _v4_global(_v4_scope, 'Mapping')) or counts != baseline.get("inventory_v2_counts"):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("inventory counts do not match graph baseline")
    registered_graph_nodes = _v4_global(_v4_scope, 'set')(baseline["graph_node_registry"]["ids"])
    for group in _v4_global(_v4_scope, '_GROUPS'):
        records = inventory.get(group)
        if not _v4_global(_v4_scope, 'isinstance')(records, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(records) != counts.get(group):
            raise _v4_global(_v4_scope, 'GraphBaselineError')(f"wrong {group} count")
        for record in records:
            if not _v4_global(_v4_scope, 'isinstance')(record, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'GraphBaselineError')(f"invalid record in {group}")
            _v4_global(_v4_scope, '_validate_lifecycle')(record, group)
            unknown_graph_nodes = _v4_global(_v4_scope, 'sorted')(
                _v4_global(_v4_scope, 'set')(record["graph_node_ids"]) - registered_graph_nodes
            )
            if unknown_graph_nodes:
                raise _v4_global(_v4_scope, 'GraphBaselineError')(
                    f"unknown graph node in {group}: {unknown_graph_nodes[0]}"
                )
    source_ids: set[str] = _v4_global(_v4_scope, 'set')()
    for source in inventory["sources"]:
        identity = source.get("atlas_file_id")
        if not _v4_global(_v4_scope, 'isinstance')(identity, _v4_global(_v4_scope, 'str')) or identity in source_ids:
            raise _v4_global(_v4_scope, 'GraphBaselineError')("duplicate or missing atlas_file_id")
        source_ids.add(identity)
        _v4_global(_v4_scope, '_relative_path')(source.get("old_source"), context="inventory source")
        if not _v4_global(_v4_scope, '_is_sha256')(source.get("atlas_sha256")):
            raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid Atlas SHA in inventory source")
        if source.get("source_state") not in _v4_global(_v4_scope, '_SOURCE_STATES'):
            raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid source state")
        if source["source_state"] == "MISSING":
            if source.get("sha256") is not None:
                raise _v4_global(_v4_scope, 'GraphBaselineError')("missing source has a SHA")
        elif not _v4_global(_v4_scope, '_is_sha256')(source.get("sha256")):
            raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid current source SHA")
    entrypoint_ids: set[str] = _v4_global(_v4_scope, 'set')()
    for entrypoint in inventory["entrypoints"]:
        identity = entrypoint.get("atlas_entrypoint_id")
        if not _v4_global(_v4_scope, 'isinstance')(identity, _v4_global(_v4_scope, 'str')) or identity in entrypoint_ids:
            raise _v4_global(_v4_scope, 'GraphBaselineError')("duplicate or missing atlas_entrypoint_id")
        entrypoint_ids.add(identity)
        evidence = entrypoint.get("source_evidence")
        if not _v4_global(_v4_scope, 'isinstance')(evidence, _v4_global(_v4_scope, 'list')) or not evidence:
            raise _v4_global(_v4_scope, 'GraphBaselineError')("entrypoint source evidence is required")
        for item in evidence:
            if not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid entrypoint source evidence")
            _v4_global(_v4_scope, '_relative_path')(item.get("path"), context="entrypoint evidence")
    runtime_keys: set[tuple[str, str]] = _v4_global(_v4_scope, 'set')()
    for runtime_task in inventory["runtime_tasks"]:
        key = (_v4_global(_v4_scope, 'str')(runtime_task.get("record_type")), _v4_global(_v4_scope, 'str')(runtime_task.get("task_name")))
        if not _v4_global(_v4_scope, 'all')(key) or key in runtime_keys:
            raise _v4_global(_v4_scope, 'GraphBaselineError')("duplicate or missing runtime task key")
        runtime_keys.add(key)
        if not _v4_global(_v4_scope, 'isinstance')(runtime_task.get("feature_ids"), _v4_global(_v4_scope, 'list')) or not runtime_task["feature_ids"]:
            raise _v4_global(_v4_scope, 'GraphBaselineError')("runtime task feature_ids are required")
    feature_ids: set[str] = _v4_global(_v4_scope, 'set')()
    for feature in inventory["features"]:
        feature_id = feature.get("feature_id")
        if not _v4_global(_v4_scope, 'isinstance')(feature_id, _v4_global(_v4_scope, 'str')) or not feature_id or feature_id in feature_ids:
            raise _v4_global(_v4_scope, 'GraphBaselineError')("duplicate or missing feature_id")
        feature_ids.add(feature_id)
        if not _v4_global(_v4_scope, 'isinstance')(feature.get("source_gaps"), _v4_global(_v4_scope, 'list')):
            raise _v4_global(_v4_scope, 'GraphBaselineError')("feature source_gaps are required")
    if inventory.get("safety") != baseline.get("safety"):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("unsafe inventory v2")
