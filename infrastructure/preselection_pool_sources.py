"""Private pool operations extracted from the exact d8b1 store baseline.

The public facade retains locks, gate checks and compatibility methods. This
module has no producer, scheduler or authority. Dependencies arrive explicitly
from that facade; it never imports the facade or binds mutable global services.
"""
from __future__ import annotations
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Mapping, TYPE_CHECKING
from infrastructure.interprocess_lock import owned_interprocess_lock
if TYPE_CHECKING:
    from infrastructure.preselection_pool_ports import PoolAPI

def root_for_date(self, trade_date: str, *, _api: PoolAPI) -> Path:
    date = _api._date(trade_date)
    for root in self._stores:
        parent = root / "preselection_pools"
        child = parent / date
        if parent.is_symlink() or child.is_symlink():
            raise ValueError("preselection date ownership cannot use symlinks")
        if parent.exists() and not parent.is_dir():
            raise ValueError("preselection source parent is not a directory")
        if child.exists():
            if not child.is_dir():
                raise ValueError("preselection date source is not a directory")
            return root
    return self.root


@contextmanager
def source_read_lease(
    self,
    trade_date: str,
    *,
    timeout_seconds: float,
    lock_primary_owner: bool = False,
    _api: PoolAPI,
):
    """Lease the source owner, optionally including the primary store writer lock."""
    root = self.root_for_date(trade_date)
    if root == self.root:
        if not lock_primary_owner:
            yield
            return
        store = self._stores[root]
        with owned_interprocess_lock(
            store.root / ".import.lock",
            timeout_seconds=timeout_seconds,
            timeout_message="preselection source read-lock timeout",
        ):
            if self.root_for_date(trade_date) != root:
                raise ValueError("preselection source owner changed before primary read lease")
            try:
                yield
            finally:
                if self.root_for_date(trade_date) != root:
                    raise ValueError("preselection source owner changed during primary read lease")
        return
    io = self._stores[root]._io
    relative = "preselection_pools/.materialize.lock"
    deadline = time.monotonic() + max(0., timeout_seconds)
    with io.parent(relative) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        locked = False
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EINTR):
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError("preselection source read-lock timeout") from error
                    time.sleep(min(.02, remaining))

            def validate() -> None:
                held = os.fstat(fd)
                visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (not stat.S_ISREG(held.st_mode) or stat.S_IMODE(held.st_mode) != 0o600
                        or held.st_nlink != 1 or (held.st_dev, held.st_ino) != (visible.st_dev, visible.st_ino)):
                    raise ValueError("preselection producer lock inode identity changed")
                os.lseek(fd, 0, os.SEEK_SET)
                raw = os.read(fd, 4097)
                expected = {"schema_version": "v3_5_interprocess_lock.v1", "pid": 2147483647, "token": "RELEASED"}
                if len(raw) > 4096 or json.loads(raw) != expected:
                    raise ValueError("preselection producer lock is not a confirmed released flock owner")
                with io.directory():
                    pass
                if self.root_for_date(trade_date) != root:
                    raise ValueError("preselection source owner changed under read lease")

            validate()
            try:
                yield
            finally:
                try:
                    validate()
                except (OSError, ValueError) as error:
                    raise ValueError("SOURCE_LEASE_CHANGED_POSTBODY_REVIEW_REQUIRED") from error
        finally:
            if locked:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def read_pool_snapshot(self, trade_date: str, pool_id: str, *, _api: PoolAPI) -> dict[str, Any]:
    root = self.root_for_date(trade_date)
    try:
        result = self._stores[root].read_pool_snapshot(trade_date, pool_id)
    except KeyError as error:
        field = error.args[0] if error.args else None
        if field in {"source_sha256", "source_role"}:
            raise _api.PreselectionPoolIntegrityError(
                pool_id, f"pool artifact is missing {field}"
            ) from error
        raise ValueError("preselection-pool required identity fields invalid") from error
    except TypeError as error:
        raise ValueError("preselection-pool required identity fields invalid") from error
    if self.root_for_date(trade_date) != root:
        raise ValueError("preselection date owner changed during read")
    return {**result, "physical_source_root": str(root)}


def read_pool(self, trade_date: str, pool_id: str, *, _api: PoolAPI) -> dict[str, Any]:
    return self.read_pool_snapshot(trade_date, pool_id)["artifact"]


def read_all(self, trade_date: str, *, _api: PoolAPI) -> list[dict[str, Any]]:
    date = _api._date(trade_date)
    root = self.root_for_date(date)
    rows: list[dict[str, Any]] = []
    for pool_id in _api.POOL_ORDER:
        try:
            rows.append(self.read_pool(date, pool_id))
        except FileNotFoundError:
            continue
    if self.root_for_date(date) != root:
        raise ValueError("preselection source owner changed during read")
    if not rows:
        raise FileNotFoundError(date)
    return rows


def read_all_with_quarantine(
    self, trade_date: str, *, _api: PoolAPI
) -> tuple[list[dict[str, Any]], list[Any]]:
    """Read one exact-date owner snapshot and isolate only typed pool damage.

    The native owner already provides an aggregate read under its import-lock
    lease. A configured secondary owner uses its shared producer lease and
    the same typed per-pool outcomes. Missing pool artifacts are omitted;
    directory, lock, shared-manifest, path-safety, and unclassified errors
    propagate to the caller.
    """
    date = _api._date(trade_date)
    root = self.root_for_date(date)
    store = self._stores[root]

    if root == self.root:
        class _PrimaryPoolReadStore(_api.PreselectionPoolStore):
            """Keep the store's one-lock aggregate while typing malformed lanes."""

            def read_pool_snapshot(self, trade_date, pool_id, *, lock_lease=None):
                try:
                    return super().read_pool_snapshot(
                        trade_date, pool_id, lock_lease=lock_lease
                    )
                except KeyError as error:
                    field = error.args[0] if error.args else None
                    if field not in {"source_sha256", "source_role"}:
                        raise
                    raise _api.PreselectionPoolIntegrityError(
                        pool_id, f"pool artifact is missing {field}"
                    ) from error

        # Instantiate over the same canonical root so the inherited aggregate
        # owns the ordinary import lock and still performs a single exact-date
        # snapshot. No resolver, root, or shared-lock failure is translated.
        primary_store = _PrimaryPoolReadStore(root)
        snapshots, integrity_errors = primary_store.read_all_with_quarantine(date)
        return (
            [
                {**snapshot, "physical_source_root": str(root)}
                for snapshot in snapshots
            ],
            integrity_errors,
        )

    snapshots: list[dict[str, Any]] = []
    integrity_errors: list[Any] = []
    with self.source_read_lease(date, timeout_seconds=10):
        if self.root_for_date(date) != root:
            raise ValueError("preselection source owner changed before aggregate read")
        with store._io.directory():
            pass
        with store._io.directory(f"preselection_pools/{date}"):
            pass
        for pool_id in _api.POOL_ORDER:
            try:
                snapshots.append(self.read_pool_snapshot(date, pool_id))
            except _api.PreselectionPoolArtifactMissing:
                continue
            except _api.PreselectionPoolIntegrityError as error:
                integrity_errors.append(error)
            except KeyError as error:
                # The current store reader builds its expected receipt before
                # schema validation. A canonical pool artifact missing one of
                # those two required identity fields therefore leaks KeyError
                # instead of the typed lane-local integrity error.
                field = error.args[0] if error.args else None
                if field not in {"source_sha256", "source_role"}:
                    raise
                integrity_errors.append(
                    _api.PreselectionPoolIntegrityError(
                        pool_id, f"pool artifact is missing {field}"
                    )
                )
    return snapshots, integrity_errors


def verified_dates(self, *, _api: PoolAPI) -> tuple[str, ...]:
    verified: list[str] = []
    for root in self._stores:
        parent = root / "preselection_pools"
        if not parent.is_dir() or parent.is_symlink():
            continue
        for child in sorted(parent.iterdir()):
            if not child.is_dir() or child.is_symlink():
                continue
            try:
                date = _api._date(child.name)
                self.read_pool_snapshot(date, "hkconnect_d1_top100")
            except (OSError, ValueError):
                continue
            verified.append(date)
            break
    return tuple(verified)
