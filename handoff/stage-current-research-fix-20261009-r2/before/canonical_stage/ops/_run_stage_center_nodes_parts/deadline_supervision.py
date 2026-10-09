"""ops.run_stage_center_nodes: deadline_supervision (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __bounded_wait_until_body(_v4_scope, /, target, now, *, sleep, max_wait_seconds):
    """Wait only for an exact cutoff inside the five-second calendar window."""

    current = _v4_global(_v4_scope, '_as_shanghai')(now)
    cutoff = _v4_global(_v4_scope, '_as_shanghai')(target)
    delta = (cutoff - current).total_seconds()
    # The caller may pass a smaller test window, but never enlarge the
    # coordinator's production wait budget through a config or seam value.
    wait_window = _v4_global(_v4_scope, 'min')(_v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'float')(max_wait_seconds), 0.0), _v4_global(_v4_scope, 'MAX_CALENDAR_WAIT_SECONDS'))
    if 0 < delta <= wait_window:
        _v4_global(_v4_scope, '_deadline').event("CALENDAR_WAIT_START", wait_seconds=delta)
        sleep(delta)
        _v4_global(_v4_scope, '_deadline').checkpoint("CALENDAR_WAIT_END")
        return cutoff, delta
    return current, 0.0
