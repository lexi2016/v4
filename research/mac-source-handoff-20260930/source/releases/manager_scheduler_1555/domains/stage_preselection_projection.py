"""Strict physical-pool projection used by stage-acquisition materialization.

``domains.preselection`` remains a presentation projection and may expose
explicit missing lanes.  This module is the separate stage-input reader: it
requires every graph-defined A pool and returns a deterministic, de-duplicated
union only after every artifact trio has passed the existing pool-store
identity checks.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from infrastructure.data_store import NativeDataStore, _date
from infrastructure.stage_acquisition_universe_contracts import (
    StageAcquisitionContractError,
    StrictAPreselectionSnapshot,
    read_strict_a_preselection_snapshot,
    validate_pool_rows,
    validate_pool_source_metadata,
    validate_stage_row,
)
from stage_center.input_contracts import (
    REQUIRED_A_STAGE_POOL_IDS,
)


_CONFIRMED_PROJECTION_STATUSES = frozenset(
    {"READY", "READY_WITH_ROWS", "CANONICAL_COMPLETE"}
)


class StagePreselectionProjectionError(ValueError):
    """A required physical stage-input pool cannot be confirmed."""


def _validate_pool(
    pool: Mapping[str, Any], trade_date: str, pool_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        canonical_pool, blocking, _notes = validate_pool_source_metadata(
            pool, trade_date, pool_id
        )
        if blocking:
            raise StageAcquisitionContractError(
                f"required A pool {pool_id} cannot be confirmed: {', '.join(blocking)}"
            )
        return canonical_pool, validate_pool_rows(pool, pool_id, trade_date)
    except StageAcquisitionContractError as error:
        raise StagePreselectionProjectionError(str(error)) from error


def _projection_status(projection: Mapping[str, Any]) -> str:
    data_status = projection.get("data_status")
    if data_status not in (None, ""):
        return str(data_status)
    return str(projection.get("status") or "")


def validate_complete_a_pool_set(
    projection: Mapping[str, Any], trade_date: str
) -> dict[str, Any]:
    """Validate a projection and return its canonical six-pool A projection."""

    if isinstance(projection, StrictAPreselectionSnapshot):
        try:
            target_date = _date(str(trade_date))
        except ValueError as error:
            raise StagePreselectionProjectionError(
                "required A pool trade date is invalid"
            ) from error
        if projection.trade_date != target_date:
            raise StagePreselectionProjectionError(
                "required A pool projection date mismatch"
            )
        return {
            "projection": projection.as_projection(),
            "pools": projection["pools"],
            "a_all_pool_rows": projection["a_all_pool_rows"],
            "a_all_pool_row_count": projection["a_all_pool_row_count"],
            "snapshot": projection,
        }

    if not isinstance(projection, Mapping):
        raise StagePreselectionProjectionError("preselection projection is not an object")
    try:
        target_date = _date(str(trade_date))
    except ValueError as error:
        raise StagePreselectionProjectionError("required A pool trade date is invalid") from error
    if str(projection.get("trade_date") or "") != target_date:
        raise StagePreselectionProjectionError("required A pool projection date mismatch")
    if projection.get("ok") is not True:
        raise StagePreselectionProjectionError("required A pool projection is not confirmed")
    status = _projection_status(projection)
    if status not in _CONFIRMED_PROJECTION_STATUSES:
        raise StagePreselectionProjectionError(
            f"required A pool projection status is not confirmed: {status or 'missing'}"
        )
    pools = projection.get("pools")
    if not isinstance(pools, list):
        raise StagePreselectionProjectionError("required A pool set is missing")
    by_id: dict[str, Mapping[str, Any]] = {}
    for pool in pools:
        if not isinstance(pool, Mapping):
            raise StagePreselectionProjectionError("required A pool artifact is invalid")
        pool_id = str(pool.get("pool_id") or "")
        if pool_id in by_id:
            raise StagePreselectionProjectionError(
                f"required A pool {pool_id} is duplicated"
            )
        by_id[pool_id] = pool
    missing = [pool_id for pool_id in REQUIRED_A_STAGE_POOL_IDS if pool_id not in by_id]
    if missing:
        raise StagePreselectionProjectionError(
            "required A pool set is incomplete: " + ", ".join(missing)
        )

    canonical_pools: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for pool_id in REQUIRED_A_STAGE_POOL_IDS:
        pool, rows = _validate_pool(by_id[pool_id], target_date, pool_id)
        canonical_pools.append(pool)
        for row in rows:
            code = row["symbol"]
            if code not in seen_codes:
                seen_codes.add(code)
                all_rows.append(row)

    source_rows = projection.get("a_all_pool_rows")
    if not isinstance(source_rows, list) or not source_rows:
        raise StagePreselectionProjectionError(
            "required A projection a_all_pool_rows is missing"
        )
    source_codes: list[str] = []
    source_seen: set[str] = set()
    for index, raw_row in enumerate(source_rows):
        if not isinstance(raw_row, Mapping):
            raise StagePreselectionProjectionError(
                f"required A projection row {index} is invalid"
            )
        row_pool_id = str(raw_row.get("pool_id") or "")
        if row_pool_id not in REQUIRED_A_STAGE_POOL_IDS:
            raise StagePreselectionProjectionError(
                f"required A projection row {index} pool identity is not bound"
            )
        try:
            canonical_row = validate_stage_row(
                raw_row, row_pool_id, target_date, index
            )
        except StageAcquisitionContractError as error:
            raise StagePreselectionProjectionError(str(error)) from error
        code = canonical_row["symbol"]
        if code in source_seen:
            raise StagePreselectionProjectionError(
                f"required A projection contains duplicate code {code}"
            )
        source_seen.add(code)
        source_codes.append(code)
    expected_codes = [row["symbol"] for row in all_rows]
    if source_codes != expected_codes:
        raise StagePreselectionProjectionError(
            "required A projection rows do not equal the six-pool union"
        )
    reported_count = projection.get("a_all_pool_row_count")
    if isinstance(reported_count, bool) or not isinstance(reported_count, int):
        raise StagePreselectionProjectionError(
            "required A projection row count is invalid"
        )
    if reported_count != len(expected_codes):
        raise StagePreselectionProjectionError(
            "required A projection row count does not equal the six-pool union"
        )
    return {
        "projection": {
            **dict(projection),
            "pools": canonical_pools,
            "a_all_pool_rows": all_rows,
            "a_all_pool_row_count": len(all_rows),
            "data_status": "READY_WITH_ROWS",
            "status": "READY_WITH_ROWS",
            "cannot_confirm": [],
        },
        "pools": canonical_pools,
        "a_all_pool_rows": all_rows,
        "a_all_pool_row_count": len(all_rows),
    }


def read_complete_a_set(
    store: NativeDataStore | Path | str,
    trade_date: str,
    _limit: int | None = None,
) -> StrictAPreselectionSnapshot:
    """Read all six exact-date physical A pool artifacts.

    ``_limit`` is accepted for compatibility with the presentation reader;
    physical stage inputs are never truncated.
    """

    try:
        return read_strict_a_preselection_snapshot(store, trade_date, _limit)
    except StageAcquisitionContractError as error:
        raise StagePreselectionProjectionError(str(error)) from error


__all__ = [
    "StagePreselectionProjectionError",
    "read_complete_a_set",
    "validate_complete_a_pool_set",
]
