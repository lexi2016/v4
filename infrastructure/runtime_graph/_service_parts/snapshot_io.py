"""infrastructure.runtime_graph.service: snapshot_io (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __read_snapshot_bytes_body(_v4_scope, /, runtime_root):
    path = runtime_root / "snapshots" / "current.json"
    try:
        _v4_global(_v4_scope, '_assert_safe_path')(path, runtime_root)
        before = _v4_global(_v4_scope, 'os').lstat(path)
    except _v4_global(_v4_scope, 'FileNotFoundError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_MISSING") from error
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_PATH_UNSAFE") from error
    if _v4_global(_v4_scope, '_reparse')(before) or not _v4_global(_v4_scope, 'stat').S_ISREG(before.st_mode) or _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(before, "st_nlink", 1)) != 1:
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_PATH_UNSAFE")
    if before.st_size > _v4_global(_v4_scope, 'MAX_SNAPSHOT_BYTES'):
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_TOO_LARGE")
    identity = _v4_global(_v4_scope, '_file_identity')(before)
    try:
        with path.open("rb") as handle:
            opened = _v4_global(_v4_scope, 'os').fstat(handle.fileno())
            raw = handle.read(_v4_global(_v4_scope, 'MAX_SNAPSHOT_BYTES') + 1)
            closed = _v4_global(_v4_scope, 'os').fstat(handle.fileno())
        after = _v4_global(_v4_scope, 'os').lstat(path)
    except _v4_global(_v4_scope, 'OSError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_UNREADABLE") from error
    if (
        _v4_global(_v4_scope, 'len')(raw) > _v4_global(_v4_scope, 'MAX_SNAPSHOT_BYTES')
        or _v4_global(_v4_scope, '_reparse')(after)
        or not _v4_global(_v4_scope, 'stat').S_ISREG(after.st_mode)
        or _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(after, "st_nlink", 1)) != 1
        or _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, '_file_identity')(item) != identity for item in (opened, closed, after))
    ):
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_PATH_UNSAFE")
    return raw






def __read_snapshot_projection_bytes_body(_v4_scope, /, runtime_root):
    """Read one immutable snapshot through a distinct bounded projection cap."""
    path = runtime_root / "snapshots" / "current.json"
    try:
        _v4_global(_v4_scope, '_assert_safe_path')(path, runtime_root)
        before = _v4_global(_v4_scope, 'os').lstat(path)
    except _v4_global(_v4_scope, 'FileNotFoundError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_MISSING") from error
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_PATH_UNSAFE") from error
    if _v4_global(_v4_scope, '_reparse')(before) or not _v4_global(_v4_scope, 'stat').S_ISREG(before.st_mode) or _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(before, "st_nlink", 1)) != 1:
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_PATH_UNSAFE")
    if before.st_size > _v4_global(_v4_scope, 'MAX_SNAPSHOT_PROJECTION_BYTES'):
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_PROJECTION_TOO_LARGE")
    identity = _v4_global(_v4_scope, '_file_identity')(before)
    try:
        with path.open("rb") as handle:
            opened = _v4_global(_v4_scope, 'os').fstat(handle.fileno())
            raw = handle.read(_v4_global(_v4_scope, 'MAX_SNAPSHOT_PROJECTION_BYTES') + 1)
            closed = _v4_global(_v4_scope, 'os').fstat(handle.fileno())
        after = _v4_global(_v4_scope, 'os').lstat(path)
    except _v4_global(_v4_scope, 'OSError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_UNREADABLE") from error
    if (
        _v4_global(_v4_scope, 'len')(raw) > _v4_global(_v4_scope, 'MAX_SNAPSHOT_PROJECTION_BYTES')
        or _v4_global(_v4_scope, '_reparse')(after)
        or not _v4_global(_v4_scope, 'stat').S_ISREG(after.st_mode)
        or _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(after, "st_nlink", 1)) != 1
        or _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, '_file_identity')(item) != identity for item in (opened, closed, after))
    ):
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_PATH_UNSAFE")
    return raw


def __bounded_snapshot_projection_body(_v4_scope, /, payload, raw):
    """Keep topology identity and node evidence locators while dropping bulk details."""
    nodes = payload.get("nodes")
    projected_nodes: list[dict[str, Any]] = []
    if _v4_global(_v4_scope, 'isinstance')(nodes, _v4_global(_v4_scope, 'list')):
        for node in nodes:
            if not _v4_global(_v4_scope, 'isinstance')(node, _v4_global(_v4_scope, 'Mapping')):
                continue
            projected = {
                key: _v4_global(_v4_scope, '_bounded_text')(value)
                for key, value in node.items()
                if key != "evidence"
            }
            projected["evidence_count"] = _v4_global(_v4_scope, 'len')(node.get("evidence") or []) if _v4_global(_v4_scope, 'isinstance')(node.get("evidence"), _v4_global(_v4_scope, 'list')) else 0
            projected["evidence"] = _v4_global(_v4_scope, '_bounded_evidence_summary')(node.get("evidence"))
            projected_nodes.append(projected)
    projection = {
        key: _v4_global(_v4_scope, '_bounded_text')(payload.get(key))
        for key in (
            "schema_version", "business_date", "generated_at", "topology_schema_version",
            "topology_authority_root", "topology_version_sha", "edges", "status", "reason",
            *_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        )
        if key in payload
    }
    projection["nodes"] = projected_nodes
    projection["snapshot_projection"] = {
        "bounded": True,
        "source_bytes": _v4_global(_v4_scope, 'len')(raw),
        "source_sha256": _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest(),
        "dropped_fields": ["evidence.details"],
        "max_bytes": _v4_global(_v4_scope, 'MAX_SNAPSHOT_PROJECTION_BYTES'),
        "semantic_status": "CANNOT_CONFIRM_FULL_DETAILS",
    }
    return projection


def _RuntimeGraphService__load_bounded_snapshot_state_body(_v4_scope, /, self):
    raw = _v4_global(_v4_scope, '_read_snapshot_projection_bytes')(self.runtime_root)
    payload = _v4_global(_v4_scope, '_decode_snapshot_payload')(raw)
    required = _v4_global(_v4_scope, '_SNAPSHOT_CORE_FIELDS') | _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'SAFETY_FLAGS'))
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
        or payload["topology_version_sha"] != self.topology_version_sha
    ):
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_SCHEMA_INVALID")
    if payload["topology_version_sha"] != self.topology_version_sha:
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_TOPOLOGY_MISMATCH")
    generated_at = _v4_global(_v4_scope, '_parse_snapshot_time')(payload.get("generated_at"))
    age = (_v4_global(_v4_scope, '_parse_now')(self.now_provider()) - generated_at).total_seconds()
    if age < -_v4_global(_v4_scope, 'SNAPSHOT_FUTURE_SKEW_SECONDS'):
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_FUTURE")
    if age > _v4_global(_v4_scope, 'float')(self.contract["freshness_seconds"]["runtime_snapshot"]):
        raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_STALE")
    # Drop verbose evidence details only after the immutable source passes
    # the exact semantic, topology, node-count, and safety checks used by
    # the normal full snapshot reader.
    self._validate_snapshot_semantics(payload)
    return _v4_global(_v4_scope, 'SnapshotState')(raw=raw, payload=_v4_global(_v4_scope, '_bounded_snapshot_projection')(payload, raw))
