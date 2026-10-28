"""infrastructure.runtime_graph.store: store_state (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _AtomicSnapshotStore__open_temp_posix_body(_v4_scope, /, temp, parent_handle):
    flags = _v4_global(_v4_scope, 'os').O_RDWR | _v4_global(_v4_scope, 'os').O_CREAT | _v4_global(_v4_scope, 'os').O_EXCL | _v4_global(_v4_scope, 'getattr')(_v4_global(_v4_scope, 'os'), "O_NOFOLLOW", 0)
    descriptor = _v4_global(_v4_scope, 'os').open(temp.name, flags, 0o600, dir_fd=parent_handle)
    try:
        metadata = _v4_global(_v4_scope, 'os').fstat(descriptor)
        if (
            _v4_global(_v4_scope, '_reparse')(metadata)
            or not _v4_global(_v4_scope, 'stat').S_ISREG(metadata.st_mode)
            or _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(metadata, "st_nlink", 1)) != 1
        ):
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")
        return _v4_global(_v4_scope, 'os').fdopen(descriptor, "r+b")
    except _v4_global(_v4_scope, 'Exception'):
        with _v4_global(_v4_scope, 'suppress')(_v4_global(_v4_scope, 'OSError')):
            _v4_global(_v4_scope, 'os').unlink(temp.name, dir_fd=parent_handle)
        with _v4_global(_v4_scope, 'suppress')(_v4_global(_v4_scope, 'OSError')):
            _v4_global(_v4_scope, 'os').close(descriptor)
        raise


def _RuntimeEventStore__validate_body(_v4_scope, /, snapshot):
    if not _v4_global(_v4_scope, 'isinstance')(snapshot, _v4_global(_v4_scope, 'Mapping')) or snapshot.get("schema_version") != _v4_global(_v4_scope, '_SNAPSHOT_SCHEMA'):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_SNAPSHOT_INVALID")
    date = snapshot.get("business_date")
    version = snapshot.get("topology_version_sha")
    nodes = snapshot.get("nodes")
    if not _v4_global(_v4_scope, 'isinstance')(date, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_DATE_RE').fullmatch(date) or not _v4_global(_v4_scope, 'isinstance')(version, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_SHA_RE').fullmatch(version) or not _v4_global(_v4_scope, 'isinstance')(nodes, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_SNAPSHOT_INVALID")
    try:
        _v4_global(_v4_scope, 'datetime').strptime(date, "%Y%m%d")
    except _v4_global(_v4_scope, 'ValueError') as exc:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_SNAPSHOT_INVALID") from exc
    rows: list[tuple[str, str, str]] = []
    identifiers: set[str] = _v4_global(_v4_scope, 'set')()
    for node in nodes:
        if not _v4_global(_v4_scope, 'isinstance')(node, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_SNAPSHOT_INVALID")
        node_id, status, reason = node.get("node_id"), node.get("status"), node.get("reason")
        if not _v4_global(_v4_scope, 'isinstance')(node_id, _v4_global(_v4_scope, 'str')) or not node_id or node_id in identifiers:
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_SNAPSHOT_INVALID")
        if not _v4_global(_v4_scope, 'isinstance')(status, _v4_global(_v4_scope, 'str')) or status not in {item.value for item in _v4_global(_v4_scope, 'GraphStatus')} or not _v4_global(_v4_scope, 'isinstance')(reason, _v4_global(_v4_scope, 'str')):
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_EVENT_SNAPSHOT_INVALID")
        identifiers.add(node_id)
        rows.append((node_id, status, reason))
    return rows


def _RuntimeEventStore__validate_database_leaves_body(_v4_scope, /, self, expected, *, require_database):
    """Reject links and identity replacement for SQLite's database files.

        Directory handles bind the ancestry; SQLite also opens three leaf files
        whose names can otherwise be redirected with a hardlink or a replace.
        Keep their identities stable for the full connect/schema setup window.
        """
    if self.allowed_root is None:
        return {}
    leaves = {
        "database": self.path,
        "wal": self.path.with_name(f"{self.path.name}-wal"),
        "shm": self.path.with_name(f"{self.path.name}-shm"),
    }
    identities: dict[str, tuple[int, int]] = {}
    for name, leaf in leaves.items():
        _v4_global(_v4_scope, '_assert_safe_path')(leaf, self.allowed_root)
        try:
            metadata = _v4_global(_v4_scope, 'os').lstat(leaf)
        except _v4_global(_v4_scope, 'FileNotFoundError'):
            if name == "database" and require_database:
                raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
            continue
        except _v4_global(_v4_scope, 'OSError') as exc:
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE") from exc
        if _v4_global(_v4_scope, '_reparse')(metadata) or not _v4_global(_v4_scope, 'stat').S_ISREG(metadata.st_mode) or _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(metadata, "st_nlink", 1)) != 1:
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
        identity = _v4_global(_v4_scope, '_file_identity')(metadata)
        if expected is not None and name in expected and expected[name] != identity:
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
        identities[name] = identity
    return identities


def _RuntimeEventStore__connect_body(_v4_scope, /, self):
    handles: list[int] = []
    if self.allowed_root is not None:
        _v4_global(_v4_scope, '_assert_safe_path')(self.path, self.allowed_root)
    self.path.parent.mkdir(parents=True, exist_ok=True)
    if self.allowed_root is not None:
        _v4_global(_v4_scope, '_assert_safe_path')(self.path, self.allowed_root)
        handles = self._lock_allowed_ancestry()
    try:
        if self.allowed_root is not None:
            self._validate_database_leaves()
        connection = _v4_global(_v4_scope, 'sqlite3').connect(self.path, timeout=5.0, isolation_level=None)
    except _v4_global(_v4_scope, 'Exception'):
        self._close_ancestry(handles)
        raise
    if self.allowed_root is not None:
        try:
            _v4_global(_v4_scope, '_assert_safe_path')(self.path, self.allowed_root)
            identities = self._validate_database_leaves(require_database=True)
        except _v4_global(_v4_scope, 'Exception'):
            try:
                connection.close()
            finally:
                self._close_ancestry(handles)
            raise
    try:
        connection.row_factory = _v4_global(_v4_scope, 'sqlite3').Row
        connection.execute("PRAGMA busy_timeout = 5000")
        with _v4_global(_v4_scope, 'suppress')(_v4_global(_v4_scope, 'sqlite3').DatabaseError):
            connection.execute("PRAGMA journal_mode=WAL")
        if self.allowed_root is not None:
            identities = self._validate_database_leaves(identities, require_database=True)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS runtime_node_state (business_date TEXT NOT NULL, topology_version_sha TEXT NOT NULL, node_id TEXT NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY (business_date, topology_version_sha, node_id))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS runtime_node_events (id INTEGER PRIMARY KEY AUTOINCREMENT, business_date TEXT NOT NULL, topology_version_sha TEXT NOT NULL, node_id TEXT NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL, observed_at TEXT NOT NULL)"
        )
        if self.allowed_root is not None:
            self._validate_database_leaves(identities, require_database=True)
    except _v4_global(_v4_scope, 'Exception'):
        try:
            connection.close()
        finally:
            self._close_ancestry(handles)
        raise
    return connection, handles


def _RuntimeEventStore_record_transitions_body(_v4_scope, /, self, snapshot):
    rows = self._validate(snapshot)
    observed_at = self._observed_at(self.observed_at())
    date = _v4_global(_v4_scope, 'str')(snapshot["business_date"])
    version = _v4_global(_v4_scope, 'str')(snapshot["topology_version_sha"])
    connection, handles = self._connect()
    events = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        for node_id, status, reason in rows:
            current = connection.execute(
                "SELECT status, reason FROM runtime_node_state WHERE business_date = ? AND topology_version_sha = ? AND node_id = ?",
                (date, version, node_id),
            ).fetchone()
            if current is None or current["status"] != status or current["reason"] != reason:
                connection.execute(
                    "INSERT INTO runtime_node_events (business_date, topology_version_sha, node_id, status, reason, observed_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (date, version, node_id, status, reason, observed_at),
                )
                events += 1
            connection.execute(
                "INSERT INTO runtime_node_state (business_date, topology_version_sha, node_id, status, reason) VALUES (?, ?, ?, ?, ?) ON CONFLICT(business_date, topology_version_sha, node_id) DO UPDATE SET status = excluded.status, reason = excluded.reason",
                (date, version, node_id, status, reason),
            )
        connection.execute("COMMIT")
        return events
    except _v4_global(_v4_scope, 'Exception'):
        with _v4_global(_v4_scope, 'suppress')(_v4_global(_v4_scope, 'sqlite3').DatabaseError):
            connection.execute("ROLLBACK")
        raise
    finally:
        try:
            connection.close()
        finally:
            self._close_ancestry(handles)
