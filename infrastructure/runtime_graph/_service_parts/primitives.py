"""infrastructure.runtime_graph.service: primitives (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __bounded_evidence_summary_body(_v4_scope, /, evidence):
    if not _v4_global(_v4_scope, 'isinstance')(evidence, _v4_global(_v4_scope, 'list')):
        return []
    summary: list[dict[str, Any]] = []
    for item in evidence:
        if not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')):
            continue
        details = item.get("details")
        record: dict[str, Any] = {
            "layer": item.get("layer"),
            "status": item.get("status"),
            "reason": _v4_global(_v4_scope, '_bounded_text')(item.get("reason")),
        }
        if _v4_global(_v4_scope, 'isinstance')(details, _v4_global(_v4_scope, 'Mapping')):
            for key in ("receipt_path", "artifact_path", "manifest_path", "artifact_sha256", "manifest_sha256", "receipt_sha256", "date_role"):
                value = details.get(key)
                if _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'int'), _v4_global(_v4_scope, 'bool'))):
                    record[key] = value
        summary.append(record)
    return summary


def __receipt_path_templates_body(_v4_scope, /, value):
    """Collect declared receipt locators without reading or creating artifacts."""
    paths: list[str] = []
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        for key, item in value.items():
            if key == "receipt_path" and _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str')) and item:
                paths.append(item)
            else:
                paths.extend(_v4_global(_v4_scope, '_receipt_path_templates')(item))
    elif _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'list') | _v4_global(_v4_scope, 'tuple')):
        for item in value:
            paths.extend(_v4_global(_v4_scope, '_receipt_path_templates')(item))
    return paths




def _RuntimeGraphService__runtime_topology_for_write_body(_v4_scope, /, self, now):
    topology = _v4_global(_v4_scope, 'json').loads(_v4_global(_v4_scope, 'json').dumps(self.contract["topology"], ensure_ascii=False))
    topology["generated_at"] = now.isoformat(timespec="seconds")
    topology = _v4_global(_v4_scope, 'load_topology_from_contract')(topology)
    path = self.runtime_root / "topology" / "current.json"
    _v4_global(_v4_scope, '_ensure_directory')(self.runtime_root, allowed_root=self.data_root.parent)
    _v4_global(_v4_scope, '_assert_safe_path')(self.runtime_root, self.data_root)
    _v4_global(_v4_scope, '_ensure_directory')(path.parent, allowed_root=self.runtime_root)
    _v4_global(_v4_scope, 'AtomicSnapshotStore')(
        path,
        allowed_root=self.runtime_root,
        expected_schema="v3_runtime_topology.v1",
    ).write(topology)
    return _v4_global(_v4_scope, 'load_topology')(path)


def _RuntimeGraphService__json_shape_body(_v4_scope, /, value):
    if value is None or _v4_global(_v4_scope, 'type')(value) in {_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'int'), _v4_global(_v4_scope, 'bool')}:
        return True
    if _v4_global(_v4_scope, 'type')(value) is _v4_global(_v4_scope, 'float'):
        return _v4_global(_v4_scope, 'math').isfinite(value)
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'list')):
        return _v4_global(_v4_scope, 'all')(_v4_global(_v4_scope, 'RuntimeGraphService')._json_shape(item) for item in value)
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        return _v4_global(_v4_scope, 'all')(
            _v4_global(_v4_scope, 'isinstance')(key, _v4_global(_v4_scope, 'str')) and _v4_global(_v4_scope, 'RuntimeGraphService')._json_shape(item)
            for key, item in value.items()
        )
    return False


def _load_topology_from_contract_body(_v4_scope, /, topology):
    """Validate the frozen cardinalities before the topology enters runtime."""
    loaded = _v4_global(_v4_scope, 'load_topology_payload')(topology)
    modules = _v4_global(_v4_scope, 'Counter')(_v4_global(_v4_scope, 'str')(node.get("module")) for node in loaded["nodes"])
    if _v4_global(_v4_scope, 'len')(loaded["nodes"]) != 34 or _v4_global(_v4_scope, 'len')(loaded["edges"]) != 20 or modules != _v4_global(_v4_scope, 'Counter')({
        "stage_selection": 5,
        "preselection": 5,
        "research": 8,
        "review": 7,
        "tasks": 3,
        "auxiliary": 6,
    }):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_FROZEN_TOPOLOGY_INVALID")
    return loaded
