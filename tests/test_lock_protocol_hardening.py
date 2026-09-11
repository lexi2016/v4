"""Regression tests for the hardened shared lock protocol (audit F01/F15).

Converted from the independent audit probes R07 and R15: crash residue
(empty owner records, dead reclaim owners) must be recoverable, while a
live owner's lock must never be stolen no matter how old its mtime, and a
release must never delete a successor's lock.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from infrastructure import a_share_review_store as a_share_review_module
from infrastructure import interprocess_lock as locks
from infrastructure import research_store as research_store_module
from stage_center import raw_store as raw_store_module
from stage_center import selection as selection_module
from stage_center.raw_store import RawStore, RawStoreError
from stage_center.selection import SelectionError, SelectionStore


def _owner(pid: int, token: str = "probe") -> bytes:
    return locks._owner_bytes(pid, token)


def _age(path: Path, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


def _shorten_timeout(module, monkeypatch: pytest.MonkeyPatch, timeout: float = 0.05) -> None:
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
    with pytest.raises(ValueError, match="held by live pid"):
        with locks.owned_interprocess_lock(path, timeout_seconds=0.05, timeout_message="timeout"):
            pass
    assert path.read_bytes() == _owner(os.getpid(), "live")


def test_empty_lock_residue_is_recovered(tmp_path: Path) -> None:
    path = tmp_path / "empty.lock"
    path.write_bytes(b"")
    with locks.owned_interprocess_lock(path, timeout_seconds=1, timeout_message="timeout"):
        pass
    assert not path.exists()


def test_dead_owner_lock_is_recovered(tmp_path: Path) -> None:
    path = tmp_path / "dead.lock"
    path.write_bytes(_owner(999_999_999))
    with locks.owned_interprocess_lock(path, timeout_seconds=1, timeout_message="timeout"):
        pass
    assert not path.exists()


def test_dead_reclaim_owner_does_not_block_recovery(tmp_path: Path) -> None:
    path = tmp_path / "dead.lock"
    path.write_bytes(_owner(999_999_999))
    path.with_name(f"{path.name}.reclaim").write_bytes(_owner(999_999_998, "dead-reclaimer"))
    with locks.owned_interprocess_lock(path, timeout_seconds=1, timeout_message="timeout"):
        pass
    assert not path.exists()


def test_live_reclaimer_blocks_reclaim(tmp_path: Path) -> None:
    path = tmp_path / "dead.lock"
    path.write_bytes(_owner(999_999_999))
    path.with_name(f"{path.name}.reclaim").write_bytes(_owner(os.getpid(), "live-reclaimer"))
    with pytest.raises(ValueError, match="timeout"):
        with locks.owned_interprocess_lock(path, timeout_seconds=0.05, timeout_message="timeout"):
            pass


def test_corrupt_owner_is_fail_closed_with_recovery_hint(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.lock"
    path.write_bytes(b"{not-a-valid-owner")
    with pytest.raises(ValueError, match="manual recovery required"):
        with locks.owned_interprocess_lock(path, timeout_seconds=0.05, timeout_message="timeout"):
            pass
    assert path.read_bytes() == b"{not-a-valid-owner"


def test_release_never_deletes_a_successors_lock(tmp_path: Path) -> None:
    path = tmp_path / "handoff.lock"
    with locks.owned_interprocess_lock(path, timeout_seconds=1, timeout_message="timeout"):
        path.unlink()
        path.write_bytes(_owner(os.getpid() + 1, "successor"))
    assert path.read_bytes() == _owner(os.getpid() + 1, "successor")


def test_second_holder_waits_while_first_holds(tmp_path: Path) -> None:
    path = tmp_path / "serial.lock"
    with locks.owned_interprocess_lock(path, timeout_seconds=1, timeout_message="timeout"):
        with pytest.raises(ValueError, match="timeout"):
            with locks.owned_interprocess_lock(path, timeout_seconds=0.05, timeout_message="timeout"):
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


# ---------------------------------------------------------------------------
# The four store call sites: a live owner with an ancient mtime is still not
# stolen, and the lock file survives the failed acquire attempt.
# ---------------------------------------------------------------------------


def _live_owner_file(path: Path, tmp_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_owner(os.getpid(), "live"))
    _age(path, 3600)


def _assert_not_stolen(path: Path) -> None:
    assert path.read_bytes() == _owner(os.getpid(), "live")


def test_selection_store_does_not_steal_live_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _shorten_timeout(selection_module, monkeypatch)
    store = SelectionStore(tmp_path / "selection")
    _live_owner_file(store.lock_path, tmp_path)
    with pytest.raises(SelectionError, match="live pid"):
        with store._lock():
            pass
    _assert_not_stolen(store.lock_path)


def test_raw_store_does_not_steal_live_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _shorten_timeout(raw_store_module, monkeypatch)
    store = RawStore(tmp_path / "raw")
    _live_owner_file(store.lock_path, tmp_path)
    with pytest.raises(RawStoreError, match="live pid"):
        with store._lock():
            pass
    _assert_not_stolen(store.lock_path)


def test_a_share_review_store_does_not_steal_live_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shorten_timeout(a_share_review_module, monkeypatch)
    store = a_share_review_module.AShareReviewStore(tmp_path / "reviews")
    lock_path = store._path("a_share_reviews/.import.lock")
    _live_owner_file(lock_path, tmp_path)
    with pytest.raises(ValueError, match="live pid"):
        with store._lock():
            pass
    _assert_not_stolen(lock_path)


def test_research_selection_store_does_not_steal_live_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shorten_timeout(research_store_module, monkeypatch)
    store = research_store_module.ResearchSelectionStore(tmp_path / "research")
    lock_path = store._path("research/selection/.import.lock")
    _live_owner_file(lock_path, tmp_path)
    with pytest.raises(ValueError, match="live pid"):
        with store._lock():
            pass
    _assert_not_stolen(lock_path)
