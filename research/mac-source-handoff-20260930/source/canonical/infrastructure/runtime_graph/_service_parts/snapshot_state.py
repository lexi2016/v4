"""infrastructure.runtime_graph.service: snapshot_state (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _RuntimeGraphService__load_snapshot_state_body(_v4_scope, /, self):
    state = _v4_global(_v4_scope, '_read_snapshot_state')(self.runtime_root)
    payload = state.payload
    required = {
        "schema_version",
        "business_date",
        "generated_at",
        "topology_schema_version",
        "topology_authority_root",
        "topology_version_sha",
        "nodes",
        "edges",
        "status",
        "reason",
    }
    if payload.get("schema_version") != "v3_runtime_snapshot.v1" or not required <= _v4_global(_v4_scope, 'set')(payload):
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_SCHEMA_INVALID")
    business_date = payload.get("business_date")
    if not _v4_global(_v4_scope, 'isinstance')(business_date, _v4_global(_v4_scope, 'str')) or _v4_global(_v4_scope, '_DATE_RE').fullmatch(business_date) is None:
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_SCHEMA_INVALID")
    try:
        _v4_global(_v4_scope, 'datetime').strptime(business_date, "%Y%m%d")
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_SCHEMA_INVALID") from error
    if (
        not _v4_global(_v4_scope, 'isinstance')(payload.get("topology_version_sha"), _v4_global(_v4_scope, 'str'))
        or _v4_global(_v4_scope, '_SHA_RE').fullmatch(_v4_global(_v4_scope, 'str')(payload["topology_version_sha"])) is None
        or not _v4_global(_v4_scope, 'isinstance')(payload.get("nodes"), _v4_global(_v4_scope, 'list'))
        or not _v4_global(_v4_scope, 'isinstance')(payload.get("edges"), _v4_global(_v4_scope, 'list'))
        or payload.get("status") not in {item.value for item in _v4_global(_v4_scope, 'GraphStatus')}
        or not _v4_global(_v4_scope, 'isinstance')(payload.get("reason"), _v4_global(_v4_scope, 'str'))
    ):
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_SCHEMA_INVALID")
    generated_at = _v4_global(_v4_scope, '_parse_snapshot_time')(payload.get("generated_at"))
    age = (_v4_global(_v4_scope, '_parse_now')(self.now_provider()) - generated_at).total_seconds()
    if age < -_v4_global(_v4_scope, 'SNAPSHOT_FUTURE_SKEW_SECONDS'):
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_FUTURE")
    if age > _v4_global(_v4_scope, 'float')(self.contract["freshness_seconds"]["runtime_snapshot"]):
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_STALE")
    self._validate_snapshot_semantics(payload)
    return state
