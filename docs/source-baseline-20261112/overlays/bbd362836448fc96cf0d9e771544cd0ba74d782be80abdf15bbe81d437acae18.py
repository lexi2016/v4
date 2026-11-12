from __future__ import annotations

import errno
import fcntl
import hashlib
import multiprocessing
import os
import re
import socket
import stat
from pathlib import Path

import pytest

from infrastructure.secure_evidence_fs import (
    ReadBytesResult,
    SecureEvidenceConflict,
    SecureEvidenceError,
    SecureEvidenceRoot,
    SecureEvidenceUnavailable,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fds() -> set[int]:
    return {int(name) for name in os.listdir("/dev/fd") if name.isdigit()}


def _read_in_child(root: str, relative: str, queue) -> None:
    store = SecureEvidenceRoot(root, max_file_bytes=128)
    try:
        store.read_regular_bytes(relative)
    except Exception as error:  # pragma: no cover - asserted by the parent
        queue.put((type(error).__name__, getattr(error, "status", None)))
    else:  # pragma: no cover - a blocking special file must never reach here
        queue.put(("ok", None))
    finally:
        store.close()


def _create_in_child(root: str, payload: bytes, ready, queue) -> None:
    store = SecureEvidenceRoot(root, max_file_bytes=max(len(payload), 1) + 32)
    try:
        ready.wait(timeout=5)
        digest = store.create_immutable_bytes("same/payload.bin", payload)
        queue.put(("ok", digest))
    except Exception as error:  # pragma: no cover - asserted by the parent
        queue.put((type(error).__name__, getattr(error, "status", None)))
    finally:
        store.close()


def _join_processes(processes: list[multiprocessing.Process]) -> None:
    for process in processes:
        process.join(timeout=5)
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)


def _swap_parent_after_barrier(parent: str, moved: str, outside: str, ready, swapped) -> None:
    ready.wait(timeout=5)
    Path(parent).rename(moved)
    Path(parent).symlink_to(outside, target_is_directory=True)
    swapped.wait(timeout=5)


def _swap_final_after_barrier(target: str, moved: str, outside: str, ready, swapped) -> None:
    ready.wait(timeout=5)
    Path(target).rename(moved)
    Path(target).symlink_to(outside)
    swapped.wait(timeout=5)


def test_constructor_opens_and_attests_one_root_directory(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = SecureEvidenceRoot(root, max_file_bytes=0)
    try:
        assert isinstance(store._root_fd, int)
        assert fcntl.fcntl(store._root_fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
    finally:
        store.close()
        store.close()
    assert store._root_fd is None


@pytest.mark.parametrize("value", [-1, 1.0, True, False, "1", None])
def test_constructor_rejects_nonnegative_integer_contract_violations(tmp_path: Path, value) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(SecureEvidenceError):
        SecureEvidenceRoot(root, max_file_bytes=value)


def test_max_file_bytes_is_keyword_only(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(TypeError):
        SecureEvidenceRoot(root, 100)


def test_root_symlink_is_rejected_without_resolution(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "root"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SecureEvidenceUnavailable) as raised:
        SecureEvidenceRoot(link, max_file_bytes=100)
    assert raised.value.status == "CANNOT_CONFIRM"


def test_existing_root_descriptor_stays_anchored_after_path_swap(tmp_path: Path) -> None:
    root = tmp_path / "root"
    moved = tmp_path / "moved-root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "evidence.bin").write_bytes(b"anchored")
    (outside / "evidence.bin").write_bytes(b"escaped")
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        root.rename(moved)
        root.symlink_to(outside, target_is_directory=True)
        assert store.read_regular_bytes("evidence.bin").data == b"anchored"
        with pytest.raises(SecureEvidenceUnavailable):
            SecureEvidenceRoot(root, max_file_bytes=100)
    finally:
        store.close()


@pytest.mark.parametrize("relative", [None, Path("file.bin"), "", "a\x00b", "/absolute.bin", "a\\b", "C:/drive.bin", "C:drive.bin", "a//b", "a/./b", "a/../b", "../escape.bin", "a/"])
def test_malformed_relative_paths_are_rejected_before_walk(tmp_path: Path, relative) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        with pytest.raises(SecureEvidenceError):
            store.read_regular_bytes(relative)
    finally:
        store.close()


def test_write_surface_exposes_only_the_gate3b_operations(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        assert callable(store.create_immutable_bytes)
        assert callable(store.replace_current_cas)
    finally:
        store.close()


@pytest.mark.parametrize("payload", [b"binary\x00\xff\x01", b""])
def test_read_regular_bytes_returns_attested_values(tmp_path: Path, payload: bytes) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "nested" / "record.bin"
    target.parent.mkdir()
    target.write_bytes(payload)
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        result = store.read_regular_bytes("nested/record.bin")
        assert result == ReadBytesResult(payload, _digest(payload), len(payload), result.device, result.inode)
        assert result.data == payload
        assert result.sha256 == _digest(payload)
        assert result.size == len(payload)
        assert result.device == target.stat().st_dev
        assert result.inode == target.stat().st_ino
    finally:
        store.close()


def test_missing_parent_is_fail_closed_and_read_creates_nothing(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        with pytest.raises(SecureEvidenceUnavailable) as raised:
            store.read_regular_bytes("missing/record.bin")
        assert raised.value.status == "CANNOT_CONFIRM"
        assert not (root / "missing").exists()
    finally:
        store.close()


def test_immutable_create_returns_raw_sha_and_securely_publishes_nested_bytes(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    payload = b"immutable\x00payload"
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        digest = store.create_immutable_bytes("a/b/payload.bin", payload)
        assert digest == _digest(payload)
        result = store.read_regular_bytes("a/b/payload.bin")
        assert result.data == payload
        assert stat.S_IMODE((root / "a").stat().st_mode) == 0o700
        assert stat.S_IMODE((root / "a" / "b").stat().st_mode) == 0o700
        assert stat.S_IMODE((root / "a" / "b" / "payload.bin").stat().st_mode) == 0o600
        assert not list(root.rglob("*.tmp"))
    finally:
        store.close()


def test_immutable_create_is_idempotent_for_same_raw_bytes_and_conflicts_for_different_bytes(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        first = store.create_immutable_bytes("payload.bin", b"first")
        first_result = store.read_regular_bytes("payload.bin")
        assert store.create_immutable_bytes("payload.bin", b"first") == first == _digest(b"first")
        with pytest.raises(SecureEvidenceConflict):
            store.create_immutable_bytes("payload.bin", b"second")
        current = store.read_regular_bytes("payload.bin")
        assert current.data == b"first"
        assert current.inode == first_result.inode
        assert not list(root.glob("*.tmp"))
    finally:
        store.close()


def test_immutable_create_validates_bytes_and_size_before_mkdir(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = SecureEvidenceRoot(root, max_file_bytes=3)
    try:
        with pytest.raises(SecureEvidenceError):
            store.create_immutable_bytes("new/path.bin", bytearray(b"abc"))
        with pytest.raises(SecureEvidenceError):
            store.create_immutable_bytes("new/path.bin", b"abcd")
        assert not (root / "new").exists()
    finally:
        store.close()


def test_immutable_create_rejects_existing_symlink_fifo_and_hardlink_without_replacement(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "payload.bin").write_bytes(b"outside")
    (root / "symlink.bin").symlink_to(outside / "payload.bin")
    os.mkfifo(root / "fifo.bin")
    (root / "hard.bin").write_bytes(b"payload")
    os.link(root / "hard.bin", root / "hard-2.bin")
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        for relative in ("symlink.bin", "fifo.bin", "hard.bin"):
            with pytest.raises(SecureEvidenceUnavailable):
                store.create_immutable_bytes(relative, b"payload")
        assert (outside / "payload.bin").read_bytes() == b"outside"
        assert (root / "hard.bin").read_bytes() == b"payload"
        assert not list(root.glob("*.tmp"))
    finally:
        store.close()


def test_immutable_create_completes_partial_writes_and_removes_temp_on_durability_failure(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    payload = b"partial-write-payload"
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    original_write = os.write

    def partial_write(fd: int, data) -> int:
        view = memoryview(data)
        return original_write(fd, view[: max(1, len(view) // 2)])

    monkeypatch.setattr(os, "write", partial_write)
    try:
        assert store.create_immutable_bytes("partial.bin", payload) == _digest(payload)
        assert store.read_regular_bytes("partial.bin").data == payload
    finally:
        store.close()

    root2 = tmp_path / "root2"
    root2.mkdir()
    store = SecureEvidenceRoot(root2, max_file_bytes=100)
    original_fsync = os.fsync

    def fail_fsync(_fd: int) -> None:
        raise OSError(errno.EIO, "injected fsync failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    try:
        with pytest.raises(SecureEvidenceUnavailable):
            store.create_immutable_bytes("durability.bin", b"payload")
        assert not list(root2.glob("*.tmp"))
    finally:
        monkeypatch.setattr(os, "fsync", original_fsync)
        store.close()


def test_temp_open_is_exclusive_nofollow_cloexec_and_0600(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    original_open = os.open
    observed: list[tuple[str, int, int, int | None]] = []

    def capture_open(path, flags, mode=0o777, *, dir_fd=None):
        if isinstance(path, str) and path.startswith(".") and path.endswith(".tmp"):
            observed.append((path, flags, mode, dir_fd))
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", capture_open)
    try:
        assert store.create_immutable_bytes("payload.bin", b"") == _digest(b"")
        assert len(observed) == 1
        _name, flags, mode, parent_fd = observed[0]
        required = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        assert flags & required == required
        assert mode == 0o600
        assert parent_fd == store._root_fd
        assert not list(root.glob("*.tmp"))
    finally:
        store.close()


def test_concurrent_equal_immutable_creates_share_one_inode(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    payload = b"same payload"
    context = multiprocessing.get_context("fork")
    ready = context.Barrier(2)
    queue = context.Queue()
    processes = [context.Process(target=_create_in_child, args=(str(root), payload, ready, queue)) for _ in range(2)]
    for process in processes:
        process.start()
    try:
        _join_processes(processes)
        results = [queue.get(timeout=2) for _ in processes]
        assert all(process.exitcode == 0 for process in processes)
        assert all(item == ("ok", _digest(payload)) for item in results)
        reader = SecureEvidenceRoot(root, max_file_bytes=100)
        try:
            assert reader.read_regular_bytes("same/payload.bin").data == payload
        finally:
            reader.close()
        assert not list(root.rglob("*.tmp"))
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)


def test_concurrent_different_immutable_creates_have_one_conflict_winner(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    context = multiprocessing.get_context("fork")
    ready = context.Barrier(2)
    queue = context.Queue()
    payloads = (b"first", b"second")
    processes = [context.Process(target=_create_in_child, args=(str(root), payload, ready, queue)) for payload in payloads]
    for process in processes:
        process.start()
    try:
        _join_processes(processes)
        results = [queue.get(timeout=2) for _ in processes]
        statuses = [item[0] for item in results]
        assert all(process.exitcode == 0 for process in processes)
        assert statuses.count("ok") == 1
        assert statuses.count("SecureEvidenceConflict") == 1
        assert (root / "same" / "payload.bin").read_bytes() in set(payloads)
        assert not list(root.rglob("*.tmp"))
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)


def test_cas_returns_raw_sha_and_enforces_expected_current_bytes(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        created = store.replace_current_cas("current.bin", expected_current_bytes_sha256=None, new_bytes=b"one")
        assert created == _digest(b"one")
        replaced = store.replace_current_cas("current.bin", expected_current_bytes_sha256=created, new_bytes=b"two")
        assert replaced == _digest(b"two")
        assert store.replace_current_cas("current.bin", expected_current_bytes_sha256=replaced, new_bytes=b"two") == replaced
        with pytest.raises(SecureEvidenceConflict):
            store.replace_current_cas("current.bin", expected_current_bytes_sha256=created, new_bytes=b"stale")
        with pytest.raises(SecureEvidenceConflict):
            store.replace_current_cas("current.bin", expected_current_bytes_sha256=None, new_bytes=b"other")
        assert store.read_regular_bytes("current.bin").data == b"two"
    finally:
        store.close()


def test_cas_replace_uses_anchored_parent_fd_after_root_and_parent_swap(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    parent = root / "parent"
    outside_root = tmp_path / "outside-root"
    outside_parent = outside_root / "parent"
    moved_root = tmp_path / "moved-root"
    moved_parent = tmp_path / "moved-parent"
    root.mkdir()
    parent.mkdir()
    outside_parent.mkdir(parents=True)
    target = parent / "current.bin"
    target.write_bytes(b"old")
    (outside_parent / "current.bin").write_bytes(b"outside-old")
    parent_identity = parent.stat()
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    original_replace = os.replace
    captured: list[tuple[int | None, int | None, int, int]] = []

    def swap_paths_then_replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        descriptor = os.fstat(src_dir_fd)
        captured.append((src_dir_fd, dst_dir_fd, descriptor.st_dev, descriptor.st_ino))
        parent.rename(moved_parent)
        parent.symlink_to(outside_parent, target_is_directory=True)
        root.rename(moved_root)
        root.symlink_to(outside_root, target_is_directory=True)
        return original_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "replace", swap_paths_then_replace)
    try:
        digest = store.replace_current_cas("parent/current.bin", expected_current_bytes_sha256=_digest(b"old"), new_bytes=b"new")
        assert digest == _digest(b"new")
        assert len(captured) == 1
        src_fd, dst_fd, device, inode = captured[0]
        assert src_fd == dst_fd
        assert (device, inode) == (parent_identity.st_dev, parent_identity.st_ino)
        assert (moved_parent / "current.bin").read_bytes() == b"new"
        assert (outside_parent / "current.bin").read_bytes() == b"outside-old"
        assert not list(moved_parent.glob("*.tmp"))
    finally:
        store.close()


def test_cas_validates_expected_digest_and_can_create_missing_parents(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        with pytest.raises(SecureEvidenceError):
            store.replace_current_cas("new/path.bin", expected_current_bytes_sha256="not-a-digest", new_bytes=b"x")
        with pytest.raises(SecureEvidenceError):
            store.replace_current_cas("new/path.bin", expected_current_bytes_sha256=None, new_bytes=bytearray(b"x"))
        with pytest.raises(SecureEvidenceConflict):
            store.replace_current_cas("missing/path.bin", expected_current_bytes_sha256="0" * 64, new_bytes=b"x")
        assert store.replace_current_cas("new/path.bin", expected_current_bytes_sha256=None, new_bytes=b"x") == _digest(b"x")
        assert (root / "new" / "path.bin").read_bytes() == b"x"
    finally:
        store.close()


@pytest.mark.parametrize(
    "invalid",
    [
        "+" + "a" * 63,
        "a" * 63 + " ",
        "a" * 31 + "_" + "a" * 32,
        "0x" + "a" * 62,
        "١" + "a" * 63,
        "a" * 63,
        "a" * 65,
        "g" + "a" * 63,
    ],
)
def test_cas_expected_digest_requires_ascii_hex_fullmatch(tmp_path: Path, invalid: str) -> None:
    assert re.fullmatch(r"[0-9a-fA-F]{64}", invalid) is None
    root = tmp_path / "root"
    root.mkdir()
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        with pytest.raises(SecureEvidenceError) as raised:
            store.replace_current_cas("new/path.bin", expected_current_bytes_sha256=invalid, new_bytes=b"x")
        assert type(raised.value) is SecureEvidenceError
        assert not (root / "new").exists()
    finally:
        store.close()


@pytest.mark.parametrize("replacement", [b"changed", b"old"])
def test_cas_rereads_sha_and_identity_before_replace(tmp_path: Path, monkeypatch, replacement: bytes) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "current.bin"
    target.write_bytes(b"old")
    original_inode = target.stat().st_ino
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    original_read = store._read_from_parent
    original_replace = os.replace
    calls = 0
    replacements: list[tuple[object, object]] = []

    def read_then_swap(parent_fd: int, name: str):
        nonlocal calls
        result = original_read(parent_fd, name)
        calls += 1
        if calls == 1:
            incoming = root / "incoming.bin"
            incoming.write_bytes(replacement)
            os.rename(incoming, target)
        return result

    def track_replace(*args, **kwargs):
        replacements.append((args, kwargs))
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(store, "_read_from_parent", read_then_swap)
    monkeypatch.setattr(os, "replace", track_replace)
    try:
        with pytest.raises(SecureEvidenceConflict):
            store.replace_current_cas("current.bin", expected_current_bytes_sha256=_digest(b"old"), new_bytes=b"new")
        assert calls == 2
        assert replacements == []
        current = store.read_regular_bytes("current.bin")
        assert current.data == replacement
        if replacement == b"old":
            assert current.inode != original_inode
    finally:
        store.close()


def test_cas_unsafe_or_stale_current_never_calls_replace(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "current.bin").write_bytes(b"outside")
    (root / "symlink.bin").symlink_to(outside / "current.bin")
    (root / "hard.bin").write_bytes(b"stable")
    os.link(root / "hard.bin", root / "hard-2.bin")
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    original_replace = os.replace
    replaced = False

    def track_replace(*args, **kwargs):
        nonlocal replaced
        replaced = True
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(os, "replace", track_replace)
    try:
        with pytest.raises(SecureEvidenceUnavailable):
            store.replace_current_cas("symlink.bin", expected_current_bytes_sha256=None, new_bytes=b"new")
        with pytest.raises(SecureEvidenceUnavailable):
            store.replace_current_cas("hard.bin", expected_current_bytes_sha256=None, new_bytes=b"new")
        with pytest.raises(SecureEvidenceConflict):
            store.replace_current_cas("missing.bin", expected_current_bytes_sha256=_digest(b"old"), new_bytes=b"new")
        assert not replaced
        assert (outside / "current.bin").read_bytes() == b"outside"
        assert (root / "hard.bin").read_bytes() == b"stable"
    finally:
        store.close()


def test_immutable_link_success_then_parent_fsync_failure_is_cannot_confirm_and_cleans_up(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    original_fsync = os.fsync
    baseline = _fds()

    def fail_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "injected directory fsync failure")
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    try:
        with pytest.raises(SecureEvidenceUnavailable) as raised:
            store.create_immutable_bytes("published.bin", b"payload")
        assert raised.value.status == "CANNOT_CONFIRM"
        assert (root / "published.bin").read_bytes() == b"payload"
        assert not list(root.glob("*.tmp"))
    finally:
        store.close()
    assert _fds() <= baseline


def test_cas_replace_success_then_parent_fsync_failure_is_cannot_confirm_and_cleans_up(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "current.bin"
    target.write_bytes(b"old")
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    original_fsync = os.fsync
    baseline = _fds()

    def fail_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "injected directory fsync failure")
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    try:
        with pytest.raises(SecureEvidenceUnavailable) as raised:
            store.replace_current_cas("current.bin", expected_current_bytes_sha256=_digest(b"old"), new_bytes=b"new")
        assert raised.value.status == "CANNOT_CONFIRM"
        assert target.read_bytes() == b"new"
        assert not list(root.glob("*.tmp"))
    finally:
        store.close()
    assert _fds() <= baseline


def test_cas_postreplace_secure_verification_failure_is_cannot_confirm_and_keeps_no_temp(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "current.bin"
    target.write_bytes(b"old")
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    original_read = store._read_from_parent
    calls = 0
    baseline = _fds()

    def fail_postverify(parent_fd: int, name: str):
        nonlocal calls
        calls += 1
        if calls == 3:
            return None
        return original_read(parent_fd, name)

    monkeypatch.setattr(store, "_read_from_parent", fail_postverify)
    try:
        with pytest.raises(SecureEvidenceUnavailable) as raised:
            store.replace_current_cas("current.bin", expected_current_bytes_sha256=_digest(b"old"), new_bytes=b"new")
        assert raised.value.status == "CANNOT_CONFIRM"
        assert calls == 3
        assert target.read_bytes() == b"new"
        assert not list(root.glob("*.tmp"))
    finally:
        store.close()
    assert _fds() <= baseline


def test_cas_docstring_requires_caller_held_interprocess_lock(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        doc = store.replace_current_cas.__doc__ or ""
        assert "caller-held" in doc
        assert "interprocess lock" in doc
    finally:
        store.close()


def test_parent_and_final_symlinks_are_rejected_without_following(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "payload.bin").write_bytes(b"outside")
    (root / "parent").symlink_to(outside, target_is_directory=True)
    (root / "final.bin").symlink_to(outside / "payload.bin")
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        with pytest.raises(SecureEvidenceUnavailable):
            store.read_regular_bytes("parent/payload.bin")
        with pytest.raises(SecureEvidenceUnavailable):
            store.read_regular_bytes("final.bin")
    finally:
        store.close()


def test_parent_swap_between_validation_and_final_open_is_not_escaped(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    parent = root / "parent"
    moved_parent = tmp_path / "moved-parent"
    outside = tmp_path / "outside"
    root.mkdir()
    parent.mkdir()
    outside.mkdir()
    (parent / "payload.bin").write_bytes(b"anchored")
    (outside / "payload.bin").write_bytes(b"escaped")
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    context = multiprocessing.get_context("fork")
    ready = context.Barrier(2)
    swapped = context.Barrier(2)
    process = context.Process(
        target=_swap_parent_after_barrier,
        args=(str(parent), str(moved_parent), str(outside), ready, swapped),
    )
    process.start()
    original_open = os.open
    barrier_used = False

    def open_with_barrier(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal barrier_used
        if dir_fd == store._root_fd and flags & os.O_DIRECTORY and not barrier_used:
            barrier_used = True
            ready.wait(timeout=5)
            swapped.wait(timeout=5)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", open_with_barrier)
    try:
        try:
            result = store.read_regular_bytes("parent/payload.bin")
        except SecureEvidenceUnavailable:
            pass
        else:
            assert result.data == b"anchored"
        assert barrier_used
    finally:
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
        assert process.exitcode == 0
        store.close()


def test_final_swap_between_validation_and_read_is_not_escaped(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    parent = root / "parent"
    moved_parent = tmp_path / "moved-parent"
    outside = tmp_path / "outside"
    root.mkdir()
    parent.mkdir()
    moved_parent.mkdir()
    outside.mkdir()
    target = parent / "payload.bin"
    moved_target = moved_parent / "payload.bin"
    target.write_bytes(b"anchored")
    (outside / "payload.bin").write_bytes(b"escaped")
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    context = multiprocessing.get_context("fork")
    ready = context.Barrier(2)
    swapped = context.Barrier(2)
    process = context.Process(
        target=_swap_final_after_barrier,
        args=(str(target), str(moved_target), str(outside / "payload.bin"), ready, swapped),
    )
    process.start()
    original_read = os.read
    barrier_used = False

    def read_with_barrier(fd: int, count: int) -> bytes:
        nonlocal barrier_used
        if not barrier_used:
            barrier_used = True
            ready.wait(timeout=5)
            swapped.wait(timeout=5)
        return original_read(fd, count)

    monkeypatch.setattr(os, "read", read_with_barrier)
    try:
        result = store.read_regular_bytes("parent/payload.bin")
        assert result.data == b"anchored"
        assert barrier_used
    finally:
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
        assert process.exitcode == 0
        store.close()


@pytest.mark.parametrize("kind", ["fifo", "socket"])
def test_special_files_are_rejected_promptly_in_bounded_child(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / f"{kind}.node"
    listener = None
    if kind == "fifo":
        os.mkfifo(target)
    else:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(target))
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    process = context.Process(target=_read_in_child, args=(str(root), target.name, queue))
    process.start()
    process.join(timeout=1)
    try:
        assert not process.is_alive(), "special-file open blocked despite O_NONBLOCK"
        assert queue.get(timeout=1) == ("SecureEvidenceUnavailable", "CANNOT_CONFIRM")
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
        if listener is not None:
            listener.close()


def test_device_node_is_rejected_or_reports_explicit_platform_gap(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "device.node"
    try:
        os.mknod(target, stat.S_IFCHR | 0o600, os.makedev(1, 3))
    except OSError as error:
        if error.errno in {errno.EPERM, errno.EACCES, errno.ENOTSUP}:
            pytest.skip("CANNOT_CONFIRM_DEVICE_TEST_UNAVAILABLE")
        raise
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        with pytest.raises(SecureEvidenceUnavailable):
            store.read_regular_bytes(target.name)
    finally:
        store.close()


def test_hardlink_and_oversize_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "large.bin").write_bytes(b"12345")
    (root / "hard.bin").write_bytes(b"same")
    os.link(root / "hard.bin", root / "hard-link.bin")
    store = SecureEvidenceRoot(root, max_file_bytes=4)
    try:
        with pytest.raises(SecureEvidenceUnavailable):
            store.read_regular_bytes("large.bin")
        with pytest.raises(SecureEvidenceUnavailable):
            store.read_regular_bytes("hard.bin")
    finally:
        store.close()


def test_growth_after_eof_is_rejected_from_same_descriptor(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "growing.bin"
    target.write_bytes(b"stable")
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    original_read = os.read
    grown = False

    def read_then_grow(fd: int, count: int) -> bytes:
        nonlocal grown
        chunk = original_read(fd, count)
        if not chunk and not grown:
            grown = True
            with target.open("ab") as stream:
                stream.write(b"growth")
        return chunk

    monkeypatch.setattr(os, "read", read_then_grow)
    try:
        with pytest.raises(SecureEvidenceUnavailable):
            store.read_regular_bytes(target.name)
    finally:
        store.close()


@pytest.mark.parametrize("operation", ["fstat", "read"])
def test_final_fd_closes_when_post_open_operation_raises(tmp_path: Path, monkeypatch, operation: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "record.bin").write_bytes(b"payload")
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    original_open = os.open
    original_fstat = os.fstat
    original_read = os.read
    original_close = os.close
    final_fd: int | None = None
    closed: list[int] = []

    def capture_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal final_fd
        fd = original_open(path, flags, mode, dir_fd=dir_fd)
        if dir_fd is not None and not flags & os.O_DIRECTORY:
            final_fd = fd
        return fd

    def capture_close(fd: int) -> None:
        closed.append(fd)
        original_close(fd)

    monkeypatch.setattr(os, "open", capture_open)
    monkeypatch.setattr(os, "close", capture_close)
    if operation == "fstat":

        def fail_fstat(fd: int):
            if fd == final_fd:
                raise OSError(errno.EIO, "injected fstat failure")
            return original_fstat(fd)

        monkeypatch.setattr(os, "fstat", fail_fstat)
    else:

        def fail_read(fd: int, count: int) -> bytes:
            if fd == final_fd:
                raise OSError(errno.EIO, "injected read failure")
            return original_read(fd, count)

        monkeypatch.setattr(os, "read", fail_read)
    try:
        with pytest.raises(SecureEvidenceUnavailable):
            store.read_regular_bytes("record.bin")
        assert final_fd is not None
        assert final_fd in closed
        with pytest.raises(OSError):
            original_fstat(final_fd)
    finally:
        store.close()


def test_read_failures_do_not_leak_descriptors_and_close_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    os.mkfifo(root / "real-fifo.node")
    store = SecureEvidenceRoot(root, max_file_bytes=4)
    baseline = _fds()
    try:
        for relative in ("missing/record.bin", "real-fifo.node", "record.bin"):
            with pytest.raises(SecureEvidenceUnavailable):
                store.read_regular_bytes(relative)
        assert _fds() <= baseline | {store._root_fd}
    finally:
        store.close()
        store.close()
    assert _fds() <= baseline


def test_final_descriptor_is_cloexec(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "record.bin").write_bytes(b"payload")
    original_open = os.open
    captured: list[tuple[str, int, int]] = []

    def open_capture(path, flags, mode=0o777, *, dir_fd=None):
        fd = original_open(path, flags, mode, dir_fd=dir_fd)
        captured.append((str(path), flags, fcntl.fcntl(fd, fcntl.F_GETFD)))
        return fd

    monkeypatch.setattr(os, "open", open_capture)
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    try:
        store.read_regular_bytes("record.bin")
    finally:
        store.close()
    assert len(captured) == 2
    assert all(flags & os.O_CLOEXEC for _path, flags, _fdflags in captured)
    assert all(fdflags & fcntl.FD_CLOEXEC for _path, _flags, fdflags in captured)


def test_methods_after_close_fail_and_context_manager_closes(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "record.bin").write_bytes(b"payload")
    store = SecureEvidenceRoot(root, max_file_bytes=100)
    store.close()
    with pytest.raises(SecureEvidenceUnavailable):
        store.read_regular_bytes("record.bin")
    with pytest.raises(SecureEvidenceUnavailable):
        store.__enter__()
    with SecureEvidenceRoot(root, max_file_bytes=100) as entered:
        assert entered.read_regular_bytes("record.bin").data == b"payload"
    with pytest.raises(SecureEvidenceUnavailable):
        entered.read_regular_bytes("record.bin")
