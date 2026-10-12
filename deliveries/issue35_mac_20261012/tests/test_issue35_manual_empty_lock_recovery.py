from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

import pytest


TASK_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/"
    "V4_ISSUE35_AUTOCONTINUE_MAC_20261011_R1"
)
HELPER_PATH = TASK_ROOT / "E/tools/issue35_manual_empty_lock_recovery.py"
SPEC = importlib.util.spec_from_file_location("issue35_manual_empty_lock_recovery", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
recovery = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = recovery
SPEC.loader.exec_module(recovery)


def stat_pin(path: Path):
    return recovery._stat_fields(os.stat(path, follow_symlinks=False))


def build_profile(tmp_path: Path, *, owner_bytes: bytes = b""):
    launch_agents = tmp_path / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, mode=0o700)
    launch_agents.chmod(0o700)
    owner = launch_agents / ".api.release.lock"
    mutex = launch_agents / ".api.release.lock.mutex"
    target = launch_agents / ".api.release.lock.issue35-preserved-empty-r1"
    for path, body in ((owner, owner_bytes), (mutex, b"")):
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            if body:
                os.write(fd, body)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(path, 0o600)

    api_plist = tmp_path / "plists" / "api.plist"
    scheduler_plist = tmp_path / "plists" / "scheduler.plist"
    api_plist.parent.mkdir(mode=0o700)
    api_plist.write_bytes(b"api-preimage")
    scheduler_plist.write_bytes(b"scheduler-preimage")
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir(mode=0o700)
    parent_meta = os.stat(launch_agents, follow_symlinks=False)
    parent_pin = {
        "dev": parent_meta.st_dev,
        "ino": parent_meta.st_ino,
        "mode": stat.S_IMODE(parent_meta.st_mode),
        "uid": parent_meta.st_uid,
        "gid": parent_meta.st_gid,
    }
    profile = recovery.LockProfile(
        owner_path=owner,
        target_path=target,
        mutex_path=mutex,
        owner_preimage=stat_pin(owner),
        mutex_preimage=stat_pin(mutex),
        parent_preimage=parent_pin,
        live_plists={
            str(api_plist): hashlib.sha256(api_plist.read_bytes()).hexdigest(),
            str(scheduler_plist): hashlib.sha256(scheduler_plist.read_bytes()).hexdigest(),
        },
        receipt_path=receipt_dir / "operation.json",
    )
    return profile


def preserve(profile, *, lsof=None, processes=None, before_rename=None, rename_fn=None):
    return recovery.preserve_exact_lock(
        profile,
        lsof_probe=lsof or (lambda path, pid: {pid}),
        process_snapshot=processes or (lambda: []),
        before_rename=before_rename,
        rename_fn=rename_fn or recovery._rename_exclusive_same_directory,
    )


def test_preserves_exact_inode_and_writes_receipt(tmp_path):
    profile = build_profile(tmp_path)
    before = os.stat(profile.owner_path, follow_symlinks=False)

    result = preserve(profile)

    after = os.stat(profile.target_path, follow_symlinks=False)
    assert not profile.owner_path.exists()
    assert profile.target_path.read_bytes() == b""
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode) == 0o600
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
    assert result["directory_fsync"] == "PASS"
    assert result["owner_file_deleted"] is False
    receipt = json.loads(profile.receipt_path.read_text())
    assert receipt["status"] == "PRESERVED_EXACT_EMPTY_LEGACY_OWNER_INODE"
    assert receipt["quarantine_path"] == str(profile.target_path)
    assert hashlib.sha256(profile.receipt_path.read_bytes()).hexdigest() == result[
        "_operation_receipt_file_sha256"
    ]


def test_default_lsof_probe_sees_held_temp_inode(tmp_path):
    path = tmp_path / "owner"
    path.write_bytes(b"")
    fd = os.open(path, os.O_RDWR)
    try:
        assert recovery._default_lsof_probe(path, os.getpid()) == {os.getpid()}
    finally:
        os.close(fd)


def test_nonempty_owner_is_rejected_without_rename(tmp_path):
    profile = build_profile(tmp_path, owner_bytes=b"not-empty")
    with pytest.raises(recovery.RecoveryBlocked, match="LEGACY_OWNER_NOT_EMPTY"):
        preserve(profile)
    assert profile.owner_path.read_bytes() == b"not-empty"
    assert not profile.target_path.exists()
    assert not profile.receipt_path.exists()


def test_changed_owner_mode_is_rejected_without_rename(tmp_path):
    profile = build_profile(tmp_path)
    os.chmod(profile.owner_path, 0o640)
    with pytest.raises(recovery.RecoveryBlocked, match="LEGACY_OWNER_PREIMAGE_MISMATCH"):
        preserve(profile)
    assert profile.owner_path.exists()
    assert not profile.target_path.exists()


@pytest.mark.parametrize("target_kind", ["file", "symlink"])
def test_occupied_or_symlink_quarantine_path_is_rejected(tmp_path, target_kind):
    profile = build_profile(tmp_path)
    if target_kind == "file":
        profile.target_path.write_bytes(b"keep")
    else:
        profile.target_path.symlink_to(profile.owner_path)
    with pytest.raises(recovery.RecoveryBlocked, match="QUARANTINE_DESTINATION_OCCUPIED"):
        preserve(profile)
    assert profile.owner_path.read_bytes() == b""
    assert not profile.receipt_path.exists()


def test_owner_symlink_is_rejected_without_following_it(tmp_path):
    profile = build_profile(tmp_path)
    original = tmp_path / "original-owner"
    os.rename(profile.owner_path, original)
    profile.owner_path.symlink_to(original)
    with pytest.raises(OSError):
        preserve(profile)
    assert profile.owner_path.is_symlink()
    assert original.read_bytes() == b""
    assert not profile.target_path.exists()


def test_held_canonical_mutex_is_rejected_without_waiting(tmp_path):
    profile = build_profile(tmp_path)
    holder = os.open(profile.mutex_path, os.O_RDWR)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(recovery.RecoveryBlocked, match="CANONICAL_MUTEX_BUSY"):
            preserve(profile)
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)
    assert profile.owner_path.exists()
    assert not profile.target_path.exists()


def test_held_owner_inode_flock_is_rejected_without_waiting(tmp_path):
    profile = build_profile(tmp_path)
    holder = os.open(profile.owner_path, os.O_RDWR)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(recovery.RecoveryBlocked, match="LEGACY_OWNER_FLOCK_BUSY"):
            preserve(profile)
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)
    assert profile.owner_path.exists()
    assert not profile.target_path.exists()


@pytest.mark.parametrize("pids", [set(), {123456789}])
def test_lsof_missing_self_or_other_holder_is_rejected(tmp_path, pids):
    profile = build_profile(tmp_path)
    with pytest.raises(recovery.RecoveryBlocked, match="LEGACY_OWNER_HAS_OTHER_OR_UNKNOWN_HOLDER"):
        preserve(profile, lsof=lambda path, pid: pids)
    assert profile.owner_path.exists()
    assert not profile.target_path.exists()


def test_known_publication_writer_process_is_rejected(tmp_path):
    profile = build_profile(tmp_path)
    lines = [
        "2345 /usr/bin/python3 -B /tmp/run_daily_chain_canary.py --target-date 20261013 --execute"
    ]
    with pytest.raises(recovery.RecoveryBlocked, match="ACTIVE_PUBLICATION_WRITER"):
        preserve(profile, processes=lambda: lines)
    assert profile.owner_path.exists()
    assert not profile.target_path.exists()


def test_changed_live_plist_is_rejected(tmp_path):
    profile = build_profile(tmp_path)
    plist = Path(next(iter(profile.live_plists)))
    plist.write_bytes(b"changed")
    with pytest.raises(recovery.RecoveryBlocked, match="LIVE_PLIST_PREIMAGE_MISMATCH"):
        preserve(profile)
    assert profile.owner_path.exists()
    assert not profile.target_path.exists()


def test_parent_inode_mismatch_is_rejected(tmp_path):
    profile = build_profile(tmp_path)
    profile.parent_preimage["ino"] += 1
    with pytest.raises(recovery.RecoveryBlocked, match="LOCK_PARENT_IDENTITY_MISMATCH"):
        preserve(profile)
    assert profile.owner_path.exists()
    assert not profile.target_path.exists()


def test_destination_race_is_atomic_no_overwrite(tmp_path):
    profile = build_profile(tmp_path)

    def install_competitor(parent_fd, source_name, target_name):
        profile.target_path.write_bytes(b"do-not-overwrite")
        recovery._rename_exclusive_same_directory(parent_fd, source_name, target_name)

    with pytest.raises(recovery.RecoveryBlocked, match="QUARANTINE_DESTINATION_RACE"):
        preserve(profile, rename_fn=install_competitor)
    assert profile.owner_path.read_bytes() == b""
    assert profile.target_path.read_bytes() == b"do-not-overwrite"
    assert not profile.receipt_path.exists()


def test_pre_rename_evidence_guard_failure_leaves_inode_in_place(tmp_path):
    profile = build_profile(tmp_path)

    def stop():
        raise recovery.RecoveryBlocked("PINNED_EVIDENCE_CHANGED")

    with pytest.raises(recovery.RecoveryBlocked, match="PINNED_EVIDENCE_CHANGED"):
        recovery.preserve_exact_lock(
            profile,
            lsof_probe=lambda path, pid: {pid},
            process_snapshot=lambda: [],
            pre_rename_guard=stop,
        )
    assert profile.owner_path.read_bytes() == b""
    assert not profile.target_path.exists()
    assert not profile.receipt_path.exists()


def test_parent_path_replacement_is_rejected(tmp_path):
    profile = build_profile(tmp_path)
    old_parent = profile.owner_path.parent
    moved_parent = old_parent.with_name(old_parent.name + "-old")

    def replace_parent():
        os.rename(old_parent, moved_parent)
        old_parent.mkdir(mode=0o700)

    with pytest.raises(recovery.RecoveryBlocked, match="LOCK_PARENT_PATH_REPLACED"):
        preserve(profile, before_rename=replace_parent)
    assert (moved_parent / profile.owner_path.name).read_bytes() == b""
    assert not (moved_parent / profile.target_path.name).exists()
    assert not profile.receipt_path.exists()
