"""infrastructure.runtime_graph.store: event_store (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _RuntimeEventStore_list_events_body(_v4_scope, /, self, node_id, limit):
    if not _v4_global(_v4_scope, 'isinstance')(node_id, _v4_global(_v4_scope, 'str')) or not node_id or _v4_global(_v4_scope, 'isinstance')(limit, _v4_global(_v4_scope, 'bool')) or not _v4_global(_v4_scope, 'isinstance')(limit, _v4_global(_v4_scope, 'int')) or not 1 <= limit <= 1000:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_LIST_INVALID")
    connection, handles = self._connect()
    try:
        rows = connection.execute(
            "SELECT id, business_date, topology_version_sha, node_id, status, reason, observed_at FROM runtime_node_events WHERE node_id = ? ORDER BY id ASC LIMIT ?",
            (node_id, limit),
        ).fetchall()
        return [_v4_global(_v4_scope, 'dict')(row) for row in rows]
    finally:
        try:
            connection.close()
        finally:
            self._close_ancestry(handles)


def __event_database_state_body(_v4_scope, /, store, expected):
    identities = store._validate_database_leaves(require_database=True)
    if _v4_global(_v4_scope, 'set')(identities) != {"database"}:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_SIDECAR_PRESENT")
    try:
        metadata = _v4_global(_v4_scope, 'os').lstat(store.path)
    except _v4_global(_v4_scope, 'OSError') as exc:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_READ_UNAVAILABLE") from exc
    state = (_v4_global(_v4_scope, '_file_identity')(metadata), _v4_global(_v4_scope, 'int')(metadata.st_size), _v4_global(_v4_scope, 'int')(metadata.st_mtime_ns))
    if expected is not None and state != expected:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_DATABASE_CHANGED")
    return state


def __acquire_sqlite_read_guard_body(_v4_scope, /, database):
    handle = None
    try:
        handle = database.open("rb")
        handle.seek(_v4_global(_v4_scope, '_SQLITE_SHARED_FIRST'))
        if _v4_global(_v4_scope, 'os').name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBRLCK, 1)
        else:  # pragma: no cover - the canonical runtime is Windows
            import fcntl

            fcntl.lockf(
                handle.fileno(),
                fcntl.LOCK_SH | fcntl.LOCK_NB,
                1,
                _v4_global(_v4_scope, '_SQLITE_SHARED_FIRST'),
                _v4_global(_v4_scope, 'os').SEEK_SET,
            )
        return handle
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as exc:
        if handle is not None:
            handle.close()
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_DATABASE_BUSY") from exc


def __release_sqlite_read_guard_body(_v4_scope, /, handle):
    error: OSError | ValueError | None = None
    try:
        handle.seek(_v4_global(_v4_scope, '_SQLITE_SHARED_FIRST'))
        if _v4_global(_v4_scope, 'os').name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover - the canonical runtime is Windows
            import fcntl

            fcntl.lockf(
                handle.fileno(),
                fcntl.LOCK_UN,
                1,
                _v4_global(_v4_scope, '_SQLITE_SHARED_FIRST'),
                _v4_global(_v4_scope, 'os').SEEK_SET,
            )
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as exc:
        error = exc
    finally:
        handle.close()
    if error is not None:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_GUARD_RELEASE_FAILED") from error




def __validated_event_body(_v4_scope, /, row, node_id):
    event = _v4_global(_v4_scope, 'dict')(row)
    event_id = event.get("id")
    date = event.get("business_date")
    version = event.get("topology_version_sha")
    actual_node = event.get("node_id")
    status = event.get("status")
    reason = event.get("reason")
    observed_at = event.get("observed_at")
    if _v4_global(_v4_scope, 'type')(event_id) is not _v4_global(_v4_scope, 'int') or event_id <= 0:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_TYPE_INVALID")
    if not _v4_global(_v4_scope, 'isinstance')(date, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_DATE_RE').fullmatch(date):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_DATE_INVALID")
    try:
        _v4_global(_v4_scope, 'datetime').strptime(date, "%Y%m%d")
    except _v4_global(_v4_scope, 'ValueError') as exc:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_DATE_INVALID") from exc
    if not _v4_global(_v4_scope, 'isinstance')(version, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_SHA_RE').fullmatch(version):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_SHA_INVALID")
    if not _v4_global(_v4_scope, 'isinstance')(actual_node, _v4_global(_v4_scope, 'str')) or actual_node != node_id:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_NODE_INVALID")
    if not _v4_global(_v4_scope, 'isinstance')(status, _v4_global(_v4_scope, 'str')) or status not in {item.value for item in _v4_global(_v4_scope, 'GraphStatus')}:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_STATUS_INVALID")
    if not _v4_global(_v4_scope, 'isinstance')(reason, _v4_global(_v4_scope, 'str')):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_REASON_INVALID")
    if not _v4_global(_v4_scope, 'isinstance')(observed_at, _v4_global(_v4_scope, 'str')):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_TIME_INVALID")
    try:
        observed = _v4_global(_v4_scope, 'datetime').fromisoformat(observed_at.replace("Z", "+00:00"))
    except _v4_global(_v4_scope, 'ValueError') as exc:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_TIME_INVALID") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_TIME_INVALID")
    values = (date, version, actual_node, status, reason, observed_at)
    if _v4_global(_v4_scope, 'any')(
        _v4_global(_v4_scope, 'len')(value.encode("utf-8")) > maximum
        for value, maximum in _v4_global(_v4_scope, 'zip')(values, _v4_global(_v4_scope, '_EVENT_TEXT_BYTE_LIMITS'))
    ):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_FIELD_TOO_LARGE")
    return event


def __query_events_immutable_body(_v4_scope, /, database, node_id, limit):
    connection = None
    try:
        connection = _v4_global(_v4_scope, 'sqlite3').connect(
            f"{database.as_uri()}?mode=ro&immutable=1",
            uri=True,
            timeout=0.1,
            isolation_level=None,
        )
        connection.row_factory = _v4_global(_v4_scope, 'sqlite3').Row
        _v4_global(_v4_scope, '_set_sqlite_read_limits')(connection)
        connection.execute("PRAGMA query_only = ON")
        schema = connection.execute("PRAGMA table_info(runtime_node_events)").fetchall()
        if _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'str')(row["name"]) for row in schema) != _v4_global(_v4_scope, '_EVENT_COLUMNS'):
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_SCHEMA_INVALID")
        expected_ids = _v4_global(_v4_scope, '_preflight_event_window')(connection, node_id, limit)
        rows = connection.execute(
            "SELECT id, business_date, topology_version_sha, node_id, status, reason, observed_at "
            "FROM runtime_node_events WHERE node_id = ? ORDER BY id ASC LIMIT ?",
            (node_id, limit),
        ).fetchall()
        events = [_v4_global(_v4_scope, '_validated_event')(row, node_id) for row in rows]
        if _v4_global(_v4_scope, 'tuple')(event["id"] for event in events) != expected_ids:
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_WINDOW_CHANGED")
        encoded = _v4_global(_v4_scope, 'json').dumps(
            events,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if _v4_global(_v4_scope, 'len')(encoded) > _v4_global(_v4_scope, '_MAX_EVENT_JSON_BYTES'):
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_JSON_TOO_LARGE")
        return events
    finally:
        if connection is not None:
            connection.close()


def _list_events_read_only_body(_v4_scope, /, path, *, allowed_root, node_id, limit):
    """Read events without creating SQLite files, sidecars, or schema."""
    if (
        not _v4_global(_v4_scope, 'isinstance')(node_id, _v4_global(_v4_scope, 'str'))
        or not node_id
        or _v4_global(_v4_scope, 'isinstance')(limit, _v4_global(_v4_scope, 'bool'))
        or not _v4_global(_v4_scope, 'isinstance')(limit, _v4_global(_v4_scope, 'int'))
        or not 1 <= limit <= 500
    ):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_LIST_INVALID")

    store = _v4_global(_v4_scope, 'RuntimeEventStore')(path, allowed_root=allowed_root)
    guard = None
    try:
        before = _v4_global(_v4_scope, '_event_database_state')(store)
        database = _v4_global(_v4_scope, '_absolute')(_v4_global(_v4_scope, 'Path')(path))
        guard = _v4_global(_v4_scope, '_acquire_sqlite_read_guard')(database)
        result = _v4_global(_v4_scope, '_query_events_immutable')(database, node_id, limit)
        _v4_global(_v4_scope, '_event_database_state')(store, before)
        return result
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'sqlite3').Error) as exc:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_READ_UNAVAILABLE") from exc
    finally:
        if guard is not None:
            _v4_global(_v4_scope, '_release_sqlite_read_guard')(guard)
