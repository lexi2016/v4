import hashlib
import json
import os

import pytest

from ops import research_panel_qfq as qfq


def snapshot_path(tmp_path):
    return tmp_path / "data" / "qfq_adjustment_input.json"


def serialized_snapshot(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def test_snapshot_current_and_both_immutable_names_share_one_inode(tmp_path):
    current = snapshot_path(tmp_path)
    value = {"schema": "test", "asof_date": 20261119, "symbols": {"600001.SH": {"events": []}}}

    result = qfq.publish_adjustment_snapshot(current, value)

    raw = serialized_snapshot(value)
    digest = hashlib.sha256(raw).hexdigest()
    canonical = current.parent / "adjustment_snapshots" / (qfq.canonical_sha(value) + ".json")
    by_bytes = current.parent / "adjustment_snapshots" / (digest + ".json")
    assert result["same_inode"] is True
    assert current.read_bytes() == canonical.read_bytes() == by_bytes.read_bytes() == raw
    assert qfq.sha(current) == digest
    identities = {(path.stat().st_dev, path.stat().st_ino) for path in (current, canonical, by_bytes)}
    assert len(identities) == 1
    assert current.stat().st_nlink == 3

    # This is the byte-SHA name consumed by run_daily_rebuild for its
    # immutable arrow-block generation input.
    downstream_ref = current.parent / "adjustment_snapshots" / (qfq.sha(current) + ".json")
    assert downstream_ref == by_bytes


def test_interrupted_alias_publication_retries_without_rewriting_original_current(tmp_path, monkeypatch):
    current = snapshot_path(tmp_path)
    current.parent.mkdir(parents=True)
    old_bytes = b"previous complete snapshot\n"
    current.write_bytes(old_bytes)
    value = {"schema": "test", "asof_date": 20261119, "symbols": {"600001.SH": {"events": []}}}
    original_replace = qfq._replace_adjustment_current_with_link

    def stop_before_current(root, source, destination):
        raise OSError("simulated interruption after immutable aliases")

    monkeypatch.setattr(qfq, "_replace_adjustment_current_with_link", stop_before_current)
    with pytest.raises(OSError, match="simulated interruption"):
        qfq.publish_adjustment_snapshot(current, value)

    assert current.read_bytes() == old_bytes
    monkeypatch.setattr(qfq, "_replace_adjustment_current_with_link", original_replace)
    result = qfq.publish_adjustment_snapshot(current, value)
    assert result["same_inode"] is True
    assert current.read_bytes() == serialized_snapshot(value)
    assert current.stat().st_nlink == 3
    assert not list(current.parent.glob(".adjustment-current-*.pending"))


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

    assert result["same_inode"] is False
    assert (canonical.stat().st_ino, by_bytes.stat().st_ino) == original_inodes
    assert (canonical.read_bytes(), by_bytes.read_bytes()) == original_bytes
    assert current.read_bytes() == raw
    assert os.stat(current).st_ino == canonical.stat().st_ino


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
