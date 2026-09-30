"""Stage slot lock adapter over the existing owned POSIX mutex protocol."""
from __future__ import annotations

import os
import threading
from infrastructure.interprocess_lock import owned_interprocess_lock, assert_owned_interprocess_lock
from ._namespace import read_global as _v4_global


class _SlotLockBusy(ValueError):
    """Only contention/unknown legacy ownership maps to acquire=False."""


def _SlotLock_acquire_body(_v4_scope, /, self):
    if self._owned:
        assert_owned_interprocess_lock(self._lease, self.path)
        return True
    context = owned_interprocess_lock(
        self.path,
        timeout_seconds=0.0,
        timeout_message="slot lock is already held",
        timeout_error=_SlotLockBusy,
    )
    try:
        lease = context.__enter__()
    except _SlotLockBusy:
        return False
    self._lock_context = context
    self._lease = lease
    self._owned = True
    return True


def _SlotLock_release_body(_v4_scope, /, self):
    if not self._owned:
        return
    # A forked child must not unlock an inherited parent mutex descriptor.
    if self._lease.pid != os.getpid() or self._lease.thread_id != threading.get_ident():
        raise _v4_global(_v4_scope, 'RunnerError')("slot lock belongs to another process or thread")
    context = self._lock_context
    try:
        context.__exit__(None, None, None)
    finally:
        self._lock_context = None
        self._lease = None
        self._owned = False
