import hashlib
import json
import os
from pathlib import Path

import pytest

from ops import research_panel_qfq as qfq
from ops import research_storage_compaction as compaction
from ops import research_storage_retention as retention


def snapshot_path(tmp_path):
    return tmp_path / "data" / "qfq_adjustment_input.json"


def serialized_snapshot(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def test_snapshot_names_use_separate_single_link_apfs_clones(tmp_path):
    current = snapshot_path(tmp_path)
    value = {"schema": "test", "asof_date": 20261119, "payload": "x" * 12000,
             "symbols": {"600001.SH": {"events": []}}}

    result = qfq.publish_adjustment_snapshot(current, value)

    raw = serialized_snapshot(value)
    digest = hashlib.sha256(raw).hexdigest()
    canonical = current.parent / "adjustment_snapshots" / (qfq.canonical_sha(value) + ".json")
    by_bytes = current.parent / "adjustment_snapshots" / (digest + ".json")
    assert result["independent_paths"] is True
    assert result["every_path_single_link"] is True
    assert current.read_bytes() == canonical.read_bytes() == by_bytes.read_bytes() == raw
    assert qfq.sha(current) == digest
    identities = {(path.stat().st_dev, path.stat().st_ino) for path in (current, canonical, by_bytes)}
    assert len(identities) == 3
    assert all(path.stat().st_nlink == 1 for path in (current, canonical, by_bytes))
    assert all(retention.stamp(path)["size"] == len(raw) for path in (current, canonical, by_bytes))
    inventory = compaction.inventory([current.parent])
    assert {item["path"] for item in inventory} == {str(current), str(canonical), str(by_bytes)}
    assert all(item["eligible"] for item in inventory)
    downstream_ref = current.parent / "adjustment_snapshots" / (qfq.sha(current) + ".json")
    assert downstream_ref == by_bytes

    # Mutating the mutable current clone must trigger APFS copy-on-write and
    # leave both retained immutable names unchanged.
    canonical_bytes = canonical.read_bytes()
    with current.open("r+b") as handle:
        handle.seek(0)
        handle.write(b"z")
        handle.flush()
        os.fsync(handle.fileno())
    assert canonical.read_bytes() == by_bytes.read_bytes() == canonical_bytes

    assert not list(current.parent.glob(".adjustment-*-*.pending"))


def test_interrupted_snapshot_publication_retries_without_rewriting_current(tmp_path, monkeypatch):
    current = snapshot_path(tmp_path)
    current.parent.mkdir(parents=True)
    old_bytes = b"previous complete snapshot\n"
    current.write_bytes(old_bytes)
    value = {"schema": "test", "asof_date": 20261119, "symbols": {"600001.SH": {"events": []}}}
    original_replace = qfq._replace_adjustment_current_with_clone

    def stop_before_current(*args, **kwargs):
        raise OSError("simulated interruption after immutable aliases")

    monkeypatch.setattr(qfq, "_replace_adjustment_current_with_clone", stop_before_current)
    with pytest.raises(OSError, match="simulated interruption"):
        qfq.publish_adjustment_snapshot(current, value)

    assert current.read_bytes() == old_bytes
    monkeypatch.setattr(qfq, "_replace_adjustment_current_with_clone", original_replace)
    result = qfq.publish_adjustment_snapshot(current, value)
    assert result["independent_paths"] is True
    assert current.read_bytes() == serialized_snapshot(value)
    canonical = current.parent / "adjustment_snapshots" / (qfq.canonical_sha(value) + ".json")
    by_bytes = current.parent / "adjustment_snapshots" / (hashlib.sha256(serialized_snapshot(value)).hexdigest() + ".json")
    assert all(path.stat().st_nlink == 1 for path in (current, canonical, by_bytes))
    assert not list(current.parent.glob(".adjustment-*-*.pending"))


def test_matching_preexisting_immutable_files_are_preserved(tmp_path):
    current = snapshot_path(tmp_path)
    value = {"schema": "test", "asof_date": 20261119}
    raw = serialized_snapshot(value)
    snapshots = current.parent / "adjustment_snapshots"
    snapshots.mkdir(parents=True)
    canonical = snapshots / (qfq.canonical_sha(value) + ".json")
    by_bytes = snapshots / (hashlib.sha256(raw).hexdigest() + ".json")
    canonical.write_bytes(raw)
    by_bytes.write_bytes(raw)
    original_inodes = (canonical.stat().st_ino, by_bytes.stat().st_ino)
    original_bytes = (canonical.read_bytes(), by_bytes.read_bytes())

    result = qfq.publish_adjustment_snapshot(current, value)

    assert result["independent_paths"] is True
    assert (canonical.stat().st_ino, by_bytes.stat().st_ino) == original_inodes
    assert (canonical.read_bytes(), by_bytes.read_bytes()) == original_bytes
    assert current.read_bytes() == raw
    assert os.stat(current).st_ino != canonical.stat().st_ino
    assert all(path.stat().st_nlink == 1 for path in (current, canonical, by_bytes))


def test_same_byte_sha_reuses_current_without_rewriting_any_reference(tmp_path, monkeypatch):
    current = snapshot_path(tmp_path)
    value = {"schema": "test", "asof_date": 20261119, "payload": "x" * 12000}
    first = qfq.publish_adjustment_snapshot(current, value)
    paths = (current, Path(first["canonical_path"]), Path(first["byte_sha_path"]))
    before = {path: (path.stat().st_dev, path.stat().st_ino, path.stat().st_nlink,
                     path.stat().st_size, path.stat().st_mtime_ns, path.stat().st_ctime_ns)
              for path in paths}

    def should_not_clone_current(*_args, **_kwargs):
        raise AssertionError("matching current was rewritten")

    monkeypatch.setattr(qfq, "_replace_adjustment_current_with_clone", should_not_clone_current)
    second = qfq.publish_adjustment_snapshot(current, value)

    assert second["current_reused"] is True
    assert {path: (path.stat().st_dev, path.stat().st_ino, path.stat().st_nlink,
                   path.stat().st_size, path.stat().st_mtime_ns, path.stat().st_ctime_ns)
            for path in paths} == before


def test_conflicting_existing_byte_sha_path_fails_closed_and_preserves_current(tmp_path):
    current = snapshot_path(tmp_path)
    current.parent.mkdir(parents=True)
    old_bytes = b"previous current\n"
    current.write_bytes(old_bytes)
    value = {"schema": "test", "asof_date": 20261119}
    raw = serialized_snapshot(value)
    snapshots = current.parent / "adjustment_snapshots"
    snapshots.mkdir()
    byte_sha = hashlib.sha256(raw).hexdigest()
    (snapshots / (byte_sha + ".json")).write_bytes(b"conflicting preexisting content")

    with pytest.raises(ValueError, match="ADJUSTMENT_SNAPSHOT_IDENTITY_CONFLICT"):
        qfq.publish_adjustment_snapshot(current, value)

    assert current.read_bytes() == old_bytes
    assert (snapshots / (byte_sha + ".json")).read_bytes() == b"conflicting preexisting content"


def test_dead_writer_pending_clone_is_verified_and_reaped_on_retry(tmp_path):
    current = snapshot_path(tmp_path)
    value = {"schema": "test", "asof_date": 20261119, "payload": "x" * 12000}
    raw = serialized_snapshot(value)
    result = qfq.publish_adjustment_snapshot(current, value)
    canonical = Path(result["canonical_path"])
    digest = hashlib.sha256(raw).hexdigest()
    pending = current.parent / (".adjustment-current-" + digest + "-" + "a" * 32 + ".pending")
    with canonical.open("rb") as source:
        source_fd = os.open(canonical, os.O_RDONLY | os.O_NOFOLLOW)
        parent_fd = os.open(current.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            qfq._clonefileat(source_fd, parent_fd, pending.name)
        finally:
            os.close(source_fd)
            os.close(parent_fd)
    assert pending.exists() and pending.stat().st_nlink == 1

    retried = qfq.publish_adjustment_snapshot(current, value)

    assert retried["independent_paths"] is True
    assert not pending.exists()
    assert not list(current.parent.glob(".adjustment-*-*.pending"))
    for path in (current, canonical, Path(result["byte_sha_path"])):
        assert retention.stamp(path)["size"] == len(raw)
        assert path.stat().st_nlink == 1


def test_dead_writer_partial_private_stage_is_reaped_before_retry(tmp_path):
    current = snapshot_path(tmp_path)
    value = {"schema": "test", "asof_date": 20261119, "payload": "x" * 12000}
    raw = serialized_snapshot(value)
    digest = hashlib.sha256(raw).hexdigest()
    snapshots = current.parent / "adjustment_snapshots"
    snapshots.mkdir(parents=True)
    pending = snapshots / (".adjustment-snapshot-" + digest + "-" + str(len(raw)) + "-" + "b" * 32 + ".pending")
    pending.write_bytes(raw[:257])
    pending.chmod(0o600)

    result = qfq.publish_adjustment_snapshot(current, value)

    assert not pending.exists()
    assert current.read_bytes() == raw
    assert Path(result["canonical_path"]).read_bytes() == raw
    assert Path(result["byte_sha_path"]).read_bytes() == raw
    assert all(path.stat().st_nlink == 1 for path in
               (current, Path(result["canonical_path"]), Path(result["byte_sha_path"])))
