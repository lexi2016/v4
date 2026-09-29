"""stage_center.raw_store: receipt_identity (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _validate_rows_body(_v4_scope, /, rows, *, trade_date, stage_id, market):
    """Validate the frozen 19-field raw shape without dropping evidence."""
    _v4_global(_v4_scope, '_validate_date')(trade_date)
    expected_market = _v4_global(_v4_scope, '_MARKET_CODE').get(market)
    if expected_market is None:
        raise _v4_global(_v4_scope, 'RawStoreError')(f"unknown market {market!r}")
    lower, upper = _v4_global(_v4_scope, '_window_bounds')(trade_date, stage_id, market)
    validated: list[dict[str, Any]] = []
    issues: list[str] = []
    for index, source in _v4_global(_v4_scope, 'enumerate')(rows):
        if not _v4_global(_v4_scope, 'isinstance')(source, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(source) != _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'RAW_FIELDS')):
            issues.append(f"row {index}: raw row must contain exactly 19 fields")
            continue
        row = _v4_global(_v4_scope, 'dict')(source)
        code = _v4_global(_v4_scope, 'str')(row.get("code") or "").upper()
        if not expected_market.fullmatch(code):
            issues.append(f"row {index}: invalid {market} code")
            continue
        try:
            update = _v4_global(_v4_scope, '_parse_timestamp')(row.get("update_time"), "update_time")
            window_start = _v4_global(_v4_scope, '_parse_timestamp')(row.get("window_start"), "window_start")
            window_end = _v4_global(_v4_scope, '_parse_timestamp')(row.get("window_end"), "window_end")
        except _v4_global(_v4_scope, 'RawStoreError') as error:
            issues.append(f"row {index}: {error}")
            continue
        if _v4_global(_v4_scope, 'any')(
            timestamp.strftime("%Y%m%d") != trade_date
            for timestamp in (update, window_start, window_end)
        ):
            issues.append(f"row {index}: date mismatch")
            continue
        if not lower <= window_start <= window_end <= upper or update != window_end:
            issues.append(f"row {index}: temporal cutoff/window violation")
            continue
        if row.get("temporal_cutoff_safe") is not True:
            issues.append(f"row {index}: temporal_cutoff_safe must be true")
            continue
        validated.append(row)
    return validated, issues
