"""stage_center.raw_store: codec (review candidate, not deployment)."""
from __future__ import annotations
from stage_center.contracts import SAFETY_FLAGS
from typing import Mapping
from stage_center.raw_store import RAW_BUNDLE_LATEST_SCHEMA_VERSION, RAW_LATEST_SCHEMA_VERSION, RAW_STATUSES, RawStoreError, _parse_timestamp, _read_json, _stage


def __window_bounds_body(trade_date, stage_id, market):
    stage = _stage(stage_id)
    if market not in stage.markets:
        raise RawStoreError(f"market {market!r} is not scheduled for {stage_id!r}")
    if stage_id == "STAGE_0925":
        start, cutoff = (
            ("09:20:00", "09:25:05")
            if market == "A_SHARE"
            else ("09:15:00", "09:20:05")
        )
    else:
        start, cutoff = stage.window.split("-")[0], stage.cutoff
        start = start if len(start) == 8 else f"{start}:00"
        cutoff = cutoff if len(cutoff) == 8 else f"{cutoff}:00"
    day = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    return (
        _parse_timestamp(f"{day} {start}", "window start"),
        _parse_timestamp(f"{day} {cutoff}", "window cutoff"),
    )


def __status_body(source_status, rows, issues, cannot_confirm):
    if source_status == "READ_OK":
        source_status = "READY"
    elif source_status == "READ_FAILED":
        source_status = "CANNOT_CONFIRM"
    if source_status not in RAW_STATUSES:
        raise RawStoreError(f"unknown source status {source_status!r}")
    if not rows:
        return "READY_EMPTY" if source_status == "READY" and not issues and not cannot_confirm else "CANNOT_CONFIRM"
    # Invalid rows are never silently downgraded to an apparently healthy
    # partial result.  Missing symbols supplied by an adapter are explicit
    # partial evidence; malformed rows are fail-closed CANNOT_CONFIRM.
    if issues or source_status == "CANNOT_CONFIRM":
        return "CANNOT_CONFIRM"
    if source_status == "READY":
        return "READY" if not cannot_confirm else "CANNOT_CONFIRM"
    return "PARTIAL_WITH_ROWS"


def _RawStore__load_latest_body(self):
    if not self.latest_path.exists():
        return {
            "schema_version": RAW_LATEST_SCHEMA_VERSION,
            "owner": "stage_center",
            "entries": {},
            **SAFETY_FLAGS,
        }
    latest = _read_json(self.latest_path)
    if latest.get("schema_version") != RAW_LATEST_SCHEMA_VERSION or latest.get("owner") != "stage_center":
        raise RawStoreError("latest.json schema/owner mismatch")
    if not isinstance(latest.get("entries"), Mapping):
        raise RawStoreError("latest.json entries missing")
    for key in SAFETY_FLAGS:
        if latest.get(key) is not False:
            raise RawStoreError(f"latest safety flag {key!r} must be false")
    return latest


def _RawStore__load_bundle_latest_body(self):
    path = self.root / "bundle_latest.json"
    if not path.exists():
        return {
            "schema_version": RAW_BUNDLE_LATEST_SCHEMA_VERSION,
            "owner": "stage_center",
            "entries": {},
            **SAFETY_FLAGS,
        }
    latest = _read_json(path)
    if latest.get("schema_version") != RAW_BUNDLE_LATEST_SCHEMA_VERSION or latest.get("owner") != "stage_center":
        raise RawStoreError("bundle_latest schema/owner mismatch")
    if not isinstance(latest.get("entries"), Mapping):
        raise RawStoreError("bundle_latest entries missing")
    for key in SAFETY_FLAGS:
        if latest.get(key) is not False:
            raise RawStoreError(f"bundle_latest safety flag {key!r} must be false")
    return latest
