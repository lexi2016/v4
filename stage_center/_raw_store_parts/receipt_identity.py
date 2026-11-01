"""stage_center.raw_store: receipt_identity (review candidate, not deployment)."""
from __future__ import annotations
from typing import Mapping
from stage_center.raw_store import RAW_FIELDS, RawStoreError, _MARKET_CODE, _parse_timestamp, _validate_date, _window_bounds


def _validate_rows_body(rows, *, trade_date, stage_id, market,
    allow_temporal_false_observation=False,
):
    """Validate the frozen 19-field raw shape without dropping evidence."""
    _validate_date(trade_date)
    expected_market = _MARKET_CODE.get(market)
    if expected_market is None:
        raise RawStoreError(f"unknown market {market!r}")
    lower, upper = _window_bounds(trade_date, stage_id, market)
    validated: list[dict[str, Any]] = []
    issues: list[str] = []
    for index, source in enumerate(rows):
        if not isinstance(source, Mapping) or set(source) != set(RAW_FIELDS):
            issues.append(f"row {index}: raw row must contain exactly 19 fields")
            continue
        row = dict(source)
        code = str(row.get("code") or "").upper()
        if not expected_market.fullmatch(code):
            issues.append(f"row {index}: invalid {market} code")
            continue
        try:
            update = _parse_timestamp(row.get("update_time"), "update_time")
            window_start = _parse_timestamp(row.get("window_start"), "window_start")
            window_end = _parse_timestamp(row.get("window_end"), "window_end")
        except RawStoreError as error:
            issues.append(f"row {index}: {error}")
            continue
        if any(
            timestamp.strftime("%Y%m%d") != trade_date
            for timestamp in (update, window_start, window_end)
        ):
            issues.append(f"row {index}: date mismatch")
            continue
        if not lower <= window_start <= window_end <= upper or update != window_end:
            issues.append(f"row {index}: temporal cutoff/window violation")
            continue
        if row.get("temporal_cutoff_safe") is not True and not (
            allow_temporal_false_observation is True
            and row.get("temporal_cutoff_safe") is False
        ):
            issues.append(f"row {index}: temporal_cutoff_safe must be true")
            continue
        validated.append(row)
    return validated, issues
