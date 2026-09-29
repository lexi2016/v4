"""Lock-protocol regressions on the merged hardening base (audit F01/F15).

The lock is a POSIX kernel mutex (flock, auto-released on process death)
bridged to a legacy PID/token owner record.  A live owner is never removed
by age; a decoded dead owner's record is reclaimed; empty or undecodable
legacy residue fails closed for manual recovery; a release never deletes a
successor's record; and the macOS directory-entry visibility lag is retried
inside owned_io instead of surfacing as FileNotFoundError (that race was
found by running the adopted package on this macOS/Python 3.14 machine).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from infrastructure import a_share_review_store as a_share_review_module
from infrastructure import interprocess_lock as locks
from infrastructure import research_store as research_store_module
from infrastructure.owned_io import SafeRoot
from stage_center import raw_store as raw_store_module
from stage_center import selection as selection_module
from stage_center.raw_store import RawStore
from stage_center.selection import SelectionStore


def _owner(pid: int, token: str = "probe") -> bytes:
    return locks._owner_bytes(pid, token)


def _age(path: Path, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


def _shorten_timeout(module, monkeypatch: pytest.MonkeyPatch, timeout: float = 0.1) -> None:
    original = module.owned_interprocess_lock

    def wrapper(*args, **kwargs):
        kwargs["timeout_seconds"] = timeout
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "owned_interprocess_lock", wrapper)


# ---------------------------------------------------------------------------
# Shared protocol
# ---------------------------------------------------------------------------


def test_live_owner_lock_is_not_stolen_by_old_mtime(tmp_path: Path) -> None:
    path = tmp_path / "live.lock"
    path.write_bytes(_owner(os.getpid(), "live"))
    _age(path, 3600)
    with pytest.raises(ValueError, match="timeout"):
        with locks.owned_interprocess_lock(path, timeout_seconds=0.1, timeout_message="timeout"):
            pass
    assert path.read_bytes() == _owner(os.getpid(), "live")


def test_dead_owner_lock_is_recovered(tmp_path: Path) -> None:
    path = tmp_path / "dead.lock"
    path.write_bytes(_owner(999_999_999))
    with locks.owned_interprocess_lock(path, timeout_seconds=2, timeout_message="timeout"):
        pass
    assert not path.exists()


def test_empty_or_corrupt_legacy_residue_fails_closed(tmp_path: Path) -> None:
    for name, raw in (("empty.lock", b""), ("corrupt.lock", b"{not-json")):
        path = tmp_path / name
        path.write_bytes(raw)
        with pytest.raises(ValueError, match="timeout"):
            with locks.owned_interprocess_lock(path, timeout_seconds=0.1, timeout_message="timeout"):
                pass
        assert path.read_bytes() == raw


def test_release_never_deletes_a_successors_record(tmp_path: Path) -> None:
    path = tmp_path / "handoff.lock"
    with locks.owned_interprocess_lock(path, timeout_seconds=2, timeout_message="timeout"):
        path.unlink()
        path.write_bytes(_owner(os.getpid() + 1, "successor"))
    assert path.read_bytes() == _owner(os.getpid() + 1, "successor")


def test_second_holder_waits_while_first_holds(tmp_path: Path) -> None:
    path = tmp_path / "serial.lock"
    with locks.owned_interprocess_lock(path, timeout_seconds=2, timeout_message="timeout"):
        with pytest.raises(ValueError, match="timeout"):
            with locks.owned_interprocess_lock(path, timeout_seconds=0.1, timeout_message="timeout"):
                pass


def test_cross_process_contention_serializes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    path = tmp_path / "xproc.lock"
    script = tmp_path / "holder.py"
    script.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "from infrastructure.interprocess_lock import owned_interprocess_lock\n"
        "with owned_interprocess_lock(Path(sys.argv[1]), timeout_seconds=5, timeout_message='holder-timeout'):\n"
        "    print('HELD', flush=True)\n"
        "    time.sleep(0.8)\n",
        encoding="utf-8",
    )
    proc = subprocess.Popen(
        [sys.executable, str(script), str(path), str(repo_root)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "HELD"
        start = time.monotonic()
        with locks.owned_interprocess_lock(path, timeout_seconds=5, timeout_message="timeout"):
            waited = time.monotonic() - start
        assert waited >= 0.5
    finally:
        proc.wait(timeout=10)


def test_macos_visibility_lag_concurrent_locks_do_not_raise(tmp_path: Path) -> None:
    # Regression for the macOS directory-entry visibility lag: concurrent
    # lock acquisition on a fresh root must never surface FileNotFoundError
    # from the mutex open, which owned_io retries internally.
    root = SafeRoot(tmp_path)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(25):
                with root.kernel_lock("contended.mutex", timeout=10, poll=0.001):
                    pass
        except BaseException as exc:  # collected for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert errors == []


# ---------------------------------------------------------------------------
# The four store call sites: a live owner record with an ancient mtime is
# still not stolen and the record survives the failed acquire attempt.
# ---------------------------------------------------------------------------


def _assert_live_record_not_stolen(lock_path: Path) -> None:
    assert lock_path.read_bytes() == _owner(os.getpid(), "live")


def test_selection_store_does_not_steal_live_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _shorten_timeout(selection_module, monkeypatch)
    store = SelectionStore(tmp_path / "selection")
    store.lock_path.parent.mkdir(parents=True, exist_ok=True)
    store.lock_path.write_bytes(_owner(os.getpid(), "live"))
    _age(store.lock_path, 3600)
    with pytest.raises(ValueError):
        with store._lock():
            pass
    _assert_live_record_not_stolen(store.lock_path)


def test_raw_store_does_not_steal_live_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _shorten_timeout(raw_store_module, monkeypatch)
    store = RawStore(tmp_path / "raw")
    store.lock_path.parent.mkdir(parents=True, exist_ok=True)
    store.lock_path.write_bytes(_owner(os.getpid(), "live"))
    _age(store.lock_path, 3600)
    with pytest.raises(ValueError):
        with store._lock():
            pass
    _assert_live_record_not_stolen(store.lock_path)


def test_a_share_review_store_does_not_steal_live_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shorten_timeout(a_share_review_module, monkeypatch)
    store = a_share_review_module.AShareReviewStore(tmp_path / "reviews")
    lock_path = store._path("a_share_reviews/.import.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_bytes(_owner(os.getpid(), "live"))
    _age(lock_path, 3600)
    with pytest.raises(ValueError):
        with store._lock():
            pass
    _assert_live_record_not_stolen(lock_path)


def test_research_selection_store_does_not_steal_live_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shorten_timeout(research_store_module, monkeypatch)
    store = research_store_module.ResearchSelectionStore(tmp_path / "research")
    lock_path = store._path("research/selection/.import.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_bytes(_owner(os.getpid(), "live"))
    _age(lock_path, 3600)
    with pytest.raises(ValueError):
        with store._lock():
            pass
    _assert_live_record_not_stolen(lock_path)
