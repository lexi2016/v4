"""ops.a_share_daily_sync: scope_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __deadline_guard_body(_v4_scope, /, seconds, *, scope):
    """Interrupt one synchronous SDK call without leaving a worker thread.

    The native lane is serial and runs on the main thread.  ``SIGALRM`` is
    therefore the only cancellation mechanism used here: it interrupts the
    socket or provider call in place and is always restored in ``finally``.
    A caller without that native main-thread deadline primitive fails before
    entering the provider call; a post-call check cannot truthfully claim an
    in-call wall-clock bound.
    """
    budget = _v4_global(_v4_scope, '_positive_budget')(seconds, "deadline_seconds")
    started = _v4_global(_v4_scope, 'time').monotonic()
    can_alarm = (
        _v4_global(_v4_scope, 'threading').current_thread() is _v4_global(_v4_scope, 'threading').main_thread()
        and _v4_global(_v4_scope, 'hasattr')(_v4_global(_v4_scope, 'signal'), "SIGALRM")
        and _v4_global(_v4_scope, 'hasattr')(_v4_global(_v4_scope, 'signal'), "setitimer")
    )
    if not can_alarm:
        raise _v4_global(_v4_scope, 'SyncTimeoutError')(
            f"{scope}_UNSUPPORTED_CONTEXT",
            budget,
            0.0,
            unsupported_context=True,
        )
    previous_handler: Any = None
    previous_timer: tuple[float, float] | None = None
    if can_alarm:
        previous_handler = _v4_global(_v4_scope, 'signal').getsignal(_v4_global(_v4_scope, 'signal').SIGALRM)
        previous_timer = _v4_global(_v4_scope, 'signal').getitimer(_v4_global(_v4_scope, 'signal').ITIMER_REAL)

        def _alarm_handler(_signum: int, _frame: Any) -> None:
            raise _v4_global(_v4_scope, 'SyncTimeoutError')(scope, budget, _v4_global(_v4_scope, 'time').monotonic() - started)

        _v4_global(_v4_scope, 'signal').signal(_v4_global(_v4_scope, 'signal').SIGALRM, _alarm_handler)
        _v4_global(_v4_scope, 'signal').setitimer(_v4_global(_v4_scope, 'signal').ITIMER_REAL, budget)
    try:
        yield
    finally:
        elapsed = _v4_global(_v4_scope, 'time').monotonic() - started
        if can_alarm:
            _v4_global(_v4_scope, 'signal').setitimer(_v4_global(_v4_scope, 'signal').ITIMER_REAL, 0.0)
            _v4_global(_v4_scope, 'signal').signal(_v4_global(_v4_scope, 'signal').SIGALRM, previous_handler)
            if previous_timer and previous_timer[0] > 0:
                _v4_global(_v4_scope, 'signal').setitimer(_v4_global(_v4_scope, 'signal').ITIMER_REAL, *previous_timer)
        if elapsed > budget:
            raise _v4_global(_v4_scope, 'SyncTimeoutError')(scope, budget, elapsed)


def __target_scope_fingerprint_body(_v4_scope, /, targets):
    descriptors = [
        {
            "code": _v4_global(_v4_scope, 'str')(item.code),
            "market": _v4_global(_v4_scope, 'int')(item.market),
            "path": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(item.path).resolve()),
        }
        for item in targets
    ]
    descriptors.sort(key=lambda item: (item["code"], item["market"], item["path"]))
    encoded = _v4_global(_v4_scope, 'json').dumps(descriptors, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _v4_global(_v4_scope, 'hashlib').sha256(encoded).hexdigest()


def __path_has_symlink_component_body(_v4_scope, /, path):
    """Return whether a target path or any existing ancestor is a symlink.

    ``Path.exists()`` is false for a dangling symlink, so callers must inspect
    the link bit before using existence or opening the path.  Checking every
    component also prevents a regular-looking leaf from writing through a
    linked directory into an unrelated source tree.
    """
    candidate = _v4_global(_v4_scope, 'Path')(path).expanduser()
    if not candidate.is_absolute():
        candidate = _v4_global(_v4_scope, 'Path').cwd() / candidate
    current = _v4_global(_v4_scope, 'Path')(candidate.anchor or "/")
    for part in candidate.parts[1:] if candidate.anchor else candidate.parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except _v4_global(_v4_scope, 'OSError'):
            return True
    return False
