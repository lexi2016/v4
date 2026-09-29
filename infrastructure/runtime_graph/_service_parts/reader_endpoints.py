"""infrastructure.runtime_graph.service: reader_endpoints (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _RuntimeGraphService_snapshot_body(_v4_scope, /, self):
    try:
        state = self._load_readable_snapshot_state()
        payload = _v4_global(_v4_scope, 'dict')(state.payload)
        payload.setdefault("snapshot_identity", {
            "business_date": payload.get("business_date"),
            "topology_version_sha": payload.get("topology_version_sha"),
            "snapshot_sha256": _v4_global(_v4_scope, 'hashlib').sha256(state.raw).hexdigest(),
        })
        return payload
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'KeyError')) as error:
        return {
            "ok": False,
            "status": _v4_global(_v4_scope, 'GraphStatus').EVIDENCE_GAP.value,
            "reason": _v4_global(_v4_scope, 'str')(error) or "SNAPSHOT_UNAVAILABLE",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }


def _RuntimeGraphService_status_body(_v4_scope, /, self):
    try:
        state = self._load_readable_snapshot_state()
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'KeyError')) as error:
        return {
            "ok": False,
            "status": _v4_global(_v4_scope, 'GraphStatus').EVIDENCE_GAP.value,
            "reason": _v4_global(_v4_scope, 'str')(error) or "SNAPSHOT_UNAVAILABLE",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    payload = state.payload
    counts = _v4_global(_v4_scope, 'Counter')(_v4_global(_v4_scope, 'str')(node.get("status")) for node in payload.get("nodes", []) if _v4_global(_v4_scope, 'isinstance')(node, _v4_global(_v4_scope, 'dict')))
    counts["total"] = _v4_global(_v4_scope, 'len')(payload.get("nodes", []))
    age = (_v4_global(_v4_scope, '_parse_now')(self.now_provider()) - _v4_global(_v4_scope, '_parse_now')(payload["generated_at"])).total_seconds()
    return {
        "ok": payload.get("status") != _v4_global(_v4_scope, 'GraphStatus').EVIDENCE_GAP.value,
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "business_date": payload.get("business_date"),
        "generated_at": payload.get("generated_at"),
        "topology_version_sha": payload.get("topology_version_sha"),
        "age_seconds": _v4_global(_v4_scope, 'round')(_v4_global(_v4_scope, 'max')(0.0, age), 3),
        "counts": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'sorted')(counts.items())),
        "snapshot_sha256": _v4_global(_v4_scope, 'hashlib').sha256(state.raw).hexdigest(),
        "snapshot_projection": payload.get("snapshot_projection"),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _RuntimeGraphService_events_body(_v4_scope, /, self, node_id, limit):
    try:
        events = _v4_global(_v4_scope, 'list_events_read_only')(
            self.runtime_root / "state" / "graph_state.db",
            allowed_root=self.runtime_root,
            node_id=node_id,
            limit=limit,
        )
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError')):
        return {"ok": False, "status": _v4_global(_v4_scope, 'GraphStatus').EVIDENCE_GAP.value, "reason": "EVENT_STORE_UNAVAILABLE", "events": []}
    descriptor = _v4_global(_v4_scope, 'next')(
        (item for item in self.topology["nodes"] if _v4_global(_v4_scope, 'str')(item.get("node_id")) == node_id),
        None,
    )
    binding = _v4_global(_v4_scope, 'overlay_node_evidence')(
        descriptor or {},
        self.evidence_bindings.get(node_id),
    )
    receipt_paths = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, '_receipt_path_templates')(binding)))
    projected_events = []
    for event in events:
        projected = _v4_global(_v4_scope, 'dict')(event)
        projected["receipt_paths"] = receipt_paths
        projected["receipt_path"] = receipt_paths[0] if receipt_paths else None
        projected_events.append(projected)
    dates = _v4_global(_v4_scope, 'sorted')({_v4_global(_v4_scope, 'str')(item.get("business_date")) for item in projected_events})
    invalid = [
        item for item in projected_events
        if item.get("status") in {_v4_global(_v4_scope, 'GraphStatus').FAIL.value, _v4_global(_v4_scope, 'GraphStatus').DEGRADED.value, _v4_global(_v4_scope, 'GraphStatus').EVIDENCE_GAP.value}
        or "CANNOT_CONFIRM" in _v4_global(_v4_scope, 'str')(item.get("reason") or "")
        or "INVALID" in _v4_global(_v4_scope, 'str')(item.get("reason") or "")
    ]
    return {
        "ok": True,
        "status": _v4_global(_v4_scope, 'GraphStatus').EVIDENCE_GAP.value if invalid else _v4_global(_v4_scope, 'GraphStatus').PASS.value,
        "reason": "EVENTS_READ_WITH_CANNOT_CONFIRM" if invalid else "EVENTS_READ",
        "node_id": node_id,
        "topology_version_sha": self.topology_version_sha,
        "business_dates": dates,
        "receipt_paths": receipt_paths,
        "events": projected_events,
        "cannot_confirm": [
            f"EVENT_{item.get('id')}:{item.get('reason')}" for item in invalid
        ],
    }
