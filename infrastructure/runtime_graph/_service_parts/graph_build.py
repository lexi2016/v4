"""infrastructure.runtime_graph.service: graph_build (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _RuntimeGraphService__write_snapshot_body(_v4_scope, /, self, payload):
    path = self.runtime_root / "snapshots" / "current.json"
    _v4_global(_v4_scope, '_ensure_directory')(self.runtime_root, allowed_root=self.data_root.parent)
    _v4_global(_v4_scope, '_assert_safe_path')(self.runtime_root, self.data_root)
    _v4_global(_v4_scope, '_ensure_directory')(path.parent, allowed_root=self.runtime_root)
    _v4_global(_v4_scope, '_assert_safe_path')(path.parent, self.runtime_root)
    _v4_global(_v4_scope, 'AtomicSnapshotStore')(path, allowed_root=self.runtime_root, expected_schema="v3_runtime_snapshot.v1").write(payload)
    try:
        raw = path.read_bytes()
    except _v4_global(_v4_scope, 'OSError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_WRITE_UNCONFIRMED") from error
    return _v4_global(_v4_scope, 'SnapshotState')(raw=raw, payload=payload)


def _RuntimeGraphService_collect_body(_v4_scope, /, self, business_date, *, now, api_base, http_get, read_text, path_exists, path_lstat, _publication_lock_held):
    date = _v4_global(_v4_scope, '_valid_date')(business_date or self._business_date())
    generated_at = _v4_global(_v4_scope, '_parse_now')(now if now is not None else self.now_provider())
    getter = http_get or _v4_global(_v4_scope, 'make_http_get')(api_base)
    if _publication_lock_held:
        return self._collect_locked(
            date,
            generated_at,
            getter,
            read_text=read_text,
            path_exists=path_exists,
            path_lstat=path_lstat,
        )
    _v4_global(_v4_scope, '_ensure_directory')(self.runtime_root, allowed_root=self.data_root.parent)
    _v4_global(_v4_scope, '_assert_safe_path')(self.runtime_root, self.data_root)
    _v4_global(_v4_scope, '_ensure_directory')(self.runtime_root / "state", allowed_root=self.runtime_root)
    lock = _v4_global(_v4_scope, '_InterProcessFileLock')(self.runtime_root / "state" / "publication.lock")
    acquired = lock.acquire(blocking=True)
    if not acquired:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_PUBLICATION_BUSY")
    try:
        return self._collect_locked(
            date,
            generated_at,
            getter,
            read_text=read_text,
            path_exists=path_exists,
            path_lstat=path_lstat,
        )
    finally:
        lock.release()


def _RuntimeGraphService__collect_locked_body(_v4_scope, /, self, date, generated_at, getter, *, read_text, path_exists, path_lstat):
    try:
        current = _v4_global(_v4_scope, '_read_snapshot_state')(self.runtime_root)
        if (
            current.payload.get("business_date") == date
            and current.payload.get("topology_version_sha") == self.topology_version_sha
            and _v4_global(_v4_scope, '_parse_snapshot_time')(current.payload.get("generated_at")) > generated_at
        ):
            self._validate_snapshot_semantics(current.payload)
            return _v4_global(_v4_scope, 'RuntimeGraphBuild')(
                state=current,
                snapshot_published=False,
                events_recorded=False,
                event_count=0,
            )
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
        pass
    topology = self._runtime_topology_for_write(generated_at)
    snapshot = _v4_global(_v4_scope, 'compose_snapshot')(
        topology=topology,
        evidence_by_node=self._evidence(
            date,
            generated_at,
            topology,
            http_get=getter,
            read_text=read_text,
            path_exists=path_exists,
            path_lstat=path_lstat,
        ),
        business_date=date,
        generated_at=generated_at,
        topology_freshness_seconds=self.contract['freshness_seconds']['topology'],
    )
    state = self._write_snapshot(snapshot)
    events_recorded = False
    event_count = 0
    try:
        _v4_global(_v4_scope, '_ensure_directory')(self.runtime_root / 'state', allowed_root=self.runtime_root)
        event_count = _v4_global(_v4_scope, 'RuntimeEventStore')(
            self.runtime_root / 'state' / 'graph_state.db',
            observed_at=lambda: generated_at,
            allowed_root=self.runtime_root,
        ).record_transitions(snapshot)
        events_recorded = True
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'RuntimeError'), _v4_global(_v4_scope, 'sqlite3').Error):
        # The snapshot remains truthful; events are separately reported as a gap.
        pass
    return _v4_global(_v4_scope, 'RuntimeGraphBuild')(
        state=state,
        snapshot_published=True,
        events_recorded=events_recorded,
        event_count=event_count,
    )


def _RuntimeGraphService_rebuild_body(_v4_scope, /, self, business_date, *, now, api_base, http_get, read_text, path_exists, path_lstat, _publication_lock_held):
    return self.collect(
        business_date,
        now=now,
        api_base=api_base,
        http_get=http_get,
        read_text=read_text,
        path_exists=path_exists,
        path_lstat=path_lstat,
        _publication_lock_held=_publication_lock_held,
    ).state
