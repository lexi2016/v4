"""ops.a_share_daily_sync: progress (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __local_history_status_body(_v4_scope, /, path, target_date):
    """Validate existing source bytes before an accepted-only handoff.

    The formula reader currently keeps the last duplicate key.  This gate
    audits the source in its original order first, so a malformed local file
    is quarantined instead of being silently repaired by a downstream reader.
    """
    path_failure = _v4_global(_v4_scope, '_local_path_failure')(path)
    if path_failure is not None:
        return [], path_failure
    if not path.exists():
        return [], None
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size % _v4_global(_v4_scope, 'DAY_STRUCT').size:
            return [], f"{_v4_global(_v4_scope, 'INVALID_BAR')}:source_file_shape"
        bars = _v4_global(_v4_scope, 'read_hq_day_bars')(path)
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'struct').error) as error:
        return [], f"{_v4_global(_v4_scope, 'INVALID_BAR')}:source_read:{error!r}"
    dates: list[int] = []
    previous_close: float | None = None
    for bar in bars:
        valid, reason = _v4_global(_v4_scope, 'valid_hq_bar')(bar)
        if not valid:
            return bars, f"{_v4_global(_v4_scope, 'INVALID_BAR')}:source_{reason}"
        date_value = _v4_global(_v4_scope, 'day_int')(bar)
        if dates and date_value == dates[-1]:
            return bars, _v4_global(_v4_scope, 'DUPLICATE_DATE')
        if dates and date_value < dates[-1]:
            return bars, _v4_global(_v4_scope, 'NON_MONOTONIC_DATE')
        if date_value > target_date:
            return bars, _v4_global(_v4_scope, 'OUT_OF_SCOPE_AFTER_TARGET_DATE')
        close = _v4_global(_v4_scope, 'float')(bar["close"])
        if previous_close is not None:
            ratio = close / previous_close
            if ratio > _v4_global(_v4_scope, 'MAX_CROSS_DAY_CLOSE_RATIO') or ratio < 1.0 / _v4_global(_v4_scope, 'MAX_CROSS_DAY_CLOSE_RATIO'):
                return bars, _v4_global(_v4_scope, 'CROSS_DAY_CLOSE_RATIO')
        dates.append(date_value)
        previous_close = close
    return bars, None


def __new_progress_body(_v4_scope, /, target_int, targets, *, dry_run):
    return {
        "schema_version": _v4_global(_v4_scope, 'PROGRESS_SCHEMA_VERSION'),
        "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
        "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
        "target_date": _v4_global(_v4_scope, 'str')(target_int),
        "target_count": _v4_global(_v4_scope, 'len')(targets),
        "target_fingerprint": _v4_global(_v4_scope, '_target_scope_fingerprint')(targets),
        "dry_run": _v4_global(_v4_scope, 'bool')(dry_run),
        "completed_symbols": [],
        "symbol_progress": {},
        "failed_hosts": [],
        "host_events": [],
        "last_event": None,
    }


def __load_progress_body(_v4_scope, /, path, target_int, targets, *, dry_run):
    expected = _v4_global(_v4_scope, '_new_progress')(target_int, targets, dry_run=dry_run)
    if not path.exists():
        return expected
    try:
        loaded = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_UNREADABLE:{path}") from error
    if not _v4_global(_v4_scope, 'isinstance')(loaded, _v4_global(_v4_scope, 'dict')):
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_INVALID:{path}")
    if _v4_global(_v4_scope, 'str')(loaded.get("schema_version")) != _v4_global(_v4_scope, 'PROGRESS_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_SCHEMA_MISMATCH:{path}")
    if _v4_global(_v4_scope, 'str')(loaded.get("target_date")) != _v4_global(_v4_scope, 'str')(target_int):
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_DATE_MISMATCH:{path}")
    if _v4_global(_v4_scope, 'str')(loaded.get("target_fingerprint")) != expected["target_fingerprint"]:
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_SCOPE_MISMATCH:{path}")
    if _v4_global(_v4_scope, 'bool')(loaded.get("dry_run", False)) != _v4_global(_v4_scope, 'bool')(dry_run):
        raise _v4_global(_v4_scope, 'RuntimeError')(f"A_SYNC_PROGRESS_MODE_MISMATCH:{path}")
    completed = loaded.get("completed_symbols", [])
    loaded["completed_symbols"] = _v4_global(_v4_scope, 'sorted')({_v4_global(_v4_scope, 'str')(value) for value in completed if _v4_global(_v4_scope, 'str')(value).strip()})
    loaded.setdefault("symbol_progress", {})
    loaded.setdefault("failed_hosts", [])
    loaded.setdefault("host_events", [])
    loaded.setdefault("last_event", None)
    return loaded


def __resume_target_order_body(_v4_scope, /, targets, progress, target_int):
    """Prioritize exact-target local files while preserving all other order.

    The last-date read is only a scheduling hint.  Every target still enters
    the unchanged local history, field, date, continuity, and source-identity
    gates below; a malformed or drifted exact-target file is rejected there.
    ``progress`` remains part of this seam for receipt compatibility, but
    durable pending/retry labels must not starve an already-current file.
    """
    if target_int is None:
        try:
            target_int = _v4_global(_v4_scope, 'int')(progress["target_date"])
        except (_v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
            return _v4_global(_v4_scope, 'list')(targets)

    current: list[DailyTarget] = []
    remainder: list[DailyTarget] = []
    for target in targets:
        try:
            is_current = _v4_global(_v4_scope, 'read_last_date')(_v4_global(_v4_scope, 'Path')(target.path)) == target_int
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'struct').error):
            is_current = False
        (current if is_current else remainder).append(target)
    return current + remainder
