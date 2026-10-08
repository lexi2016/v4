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
def source_read_lease(self, trade_date: str, *, timeout_seconds: float, _api: PoolAPI):
    """Use the deployed V3.5 shared lock inode read-only when secondary."""
    root = self.root_for_date(trade_date)
    if root == self.root:
        yield
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
    except (KeyError, TypeError) as error:
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


