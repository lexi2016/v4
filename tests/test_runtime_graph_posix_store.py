from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _snapshot(status: str = "PASS") -> dict[str, object]:
    return {
        "schema_version": "v3_runtime_snapshot.v1",
        "business_date": "20260823",
        "topology_version_sha": "a" * 64,
        "nodes": [{"node_id": "node-a", "status": status, "reason": "test"}],
    }


def test_posix_snapshot_roundtrip_is_atomic_and_no_replace(tmp_path: Path) -> None:
    from infrastructure.runtime_graph.store import AtomicSnapshotStore

    root = tmp_path / "runtime"
    target = root / "snapshots" / "current.json"
    target.parent.mkdir(parents=True)
    store = AtomicSnapshotStore(target, allowed_root=root)

    store.write(_snapshot())
    assert json.loads(target.read_text(encoding="utf-8"))["schema_version"] == "v3_runtime_snapshot.v1"

    with pytest.raises(FileExistsError):
        store.write(_snapshot("FAIL"), require_absent=True)

    assert json.loads(target.read_text(encoding="utf-8"))["nodes"][0]["status"] == "PASS"
    assert not list(target.parent.glob("*.tmp"))


def test_posix_snapshot_rejects_symlinked_ancestor(tmp_path: Path) -> None:
    from infrastructure.runtime_graph.store import AtomicSnapshotStore

    root = tmp_path / "runtime"
    real = root / "real"
    real.mkdir(parents=True)
    linked = root / "linked"
    linked.symlink_to(real, target_is_directory=True)
    target = linked / "snapshots" / "current.json"
    target.parent.mkdir(parents=True)

    with pytest.raises(ValueError, match="PATH_UNSAFE"):
        AtomicSnapshotStore(target, allowed_root=root).write(_snapshot())


def test_posix_snapshot_rejects_hardlinked_existing_target(tmp_path: Path) -> None:
    from infrastructure.runtime_graph.store import AtomicSnapshotStore

    root = tmp_path / "runtime"
    target = root / "snapshots" / "current.json"
    target.parent.mkdir(parents=True)
    external = tmp_path / "external.json"
    external.write_text("{\"existing\":true}", encoding="utf-8")
    target.hardlink_to(external)

    with pytest.raises(ValueError, match="IDENTITY_INVALID"):
        AtomicSnapshotStore(target, allowed_root=root).write(_snapshot())
    assert external.read_text(encoding="utf-8") == "{\"existing\":true}"


def test_posix_snapshot_cleans_temp_when_post_open_validation_fails(tmp_path: Path) -> None:
    from infrastructure.runtime_graph.store import AtomicSnapshotStore

    root = tmp_path / "runtime"
    target = root / "snapshots" / "current.json"
    target.parent.mkdir(parents=True)
    store = AtomicSnapshotStore(target, allowed_root=root)

    def fail_validation(_path: Path) -> None:
        raise ValueError("INJECTED_VERIFY_FAILURE")

    store._verify_temp = fail_validation  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="INJECTED_VERIFY_FAILURE"):
        store.write(_snapshot())
    assert not list(target.parent.glob("*.tmp"))


def test_posix_event_store_writes_and_reads_sqlite_events(tmp_path: Path) -> None:
    from infrastructure.runtime_graph.store import RuntimeEventStore, list_events_read_only

    root = tmp_path / "runtime"
    database = root / "state" / "graph_state.db"
    database.parent.mkdir(parents=True)
    store = RuntimeEventStore(
        database,
        allowed_root=root,
        observed_at=lambda: datetime(2026, 8, 23, 2, 0, tzinfo=timezone.utc),
    )

    assert store.record_transitions(_snapshot()) == 1
    events = store.list_events("node-a")
    assert len(events) == 1
    assert events[0]["status"] == "PASS"
    assert list_events_read_only(database, allowed_root=root, node_id="node-a", limit=10) == events
