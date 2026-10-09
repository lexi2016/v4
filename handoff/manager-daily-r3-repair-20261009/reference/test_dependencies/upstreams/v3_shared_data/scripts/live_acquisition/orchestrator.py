"""Shared live A-share minute orchestration: priority selection + persistence.

Deterministic core only: no network bridge, no OpenD, no subprocess.
``run_source_priority`` freezes the exact Futu -> PyTDX -> QMT call order and
fallback rules. ``persist_stage_result`` validates everything before any write,
writes a deterministic UTF-8-SIG artifact CSV into a temporary directory, then
injects a trusted SourceSpec into the existing SafeRootStore (single writer
``v3_shared_data``; V3/V3.5 remain read-only consumers). Idempotency/conflict
come from the store; the temporary directory is always cleaned up.
"""
from __future__ import annotations

import csv
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from shared_data.allowlist import AllowlistRegistry, SourceSpec
from shared_data.constants import CANNOT_CONFIRM, READY, READY_EMPTY
from shared_data.hashing import sha256_json
from shared_data.paths import validate_date
from shared_data.store import SafeRootStore

from .contracts import (
    ARTIFACT_FIELDS,
    NORMALIZED_MINUTE_FIELDS,
    SOURCE_PRIORITY,
    STAGE_WINDOWS,
    StageSourceResult,
    market_role,
)

OWNER = "v3_shared_data"
_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def run_source_priority(
    runners: Mapping[str, Callable[[], StageSourceResult]],
) -> tuple[StageSourceResult, list[StageSourceResult]]:
    """Call sources in frozen priority order until one is READ_OK.

    ``runners`` must map exactly the three fixed source ids (SOURCE_PRIORITY)
    to zero-argument callables returning StageSourceResult. A result whose
    ``source_id`` does not match its key is rejected. Returns ``(selected,
    results)``: results in call order; selected is the first READ_OK, otherwise
    the first result with rows, otherwise the first result. Never invents a
    result and never calls a runner twice.
    """
    if set(runners) != set(SOURCE_PRIORITY):
        raise ValueError(f"runners must map exactly {SOURCE_PRIORITY!r}, got {sorted(runners)!r}")
    results: list[StageSourceResult] = []
    for source_id in SOURCE_PRIORITY:
        result = runners[source_id]()
        if result.source_id != source_id:
            raise ValueError(f"runner {source_id!r} returned a result for {result.source_id!r}")
        results.append(result)
        if result.status == "READ_OK":
            break
    selected = next((result for result in results if result.status == "READ_OK"), None)
    if selected is None:
        selected = next((result for result in results if result.rows), None)
    if selected is None:
        selected = results[0]
    return selected, results


def persist_stage_result(
    store_root: Path | str,
    trade_date: str,
    stage_id: str,
    selected: StageSourceResult,
    dry_run: bool = False,
    *,
    market: str = "A_SHARE",
    historical_backfill: bool = False,
    expected_previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one selected live stage result into the shared SafeRootStore.

    Fails closed (ValueError, before any write) on invalid date, unknown
    stage, malformed row (missing/extra keys, non-dict), update_time not on
    trade_date, or bar_time past the stage cutoff. A dry run validates and
    returns a preview but creates neither store_root nor any temporary file.

    The artifact CSV carries exactly the 21 ARTIFACT_FIELDS: trade_date and
    bar_time (time-of-day of each preserved row's update_time) prefixed to the
    exact 19 V3 values, which are never transformed. Nested manifest
    provenance carries v3_fidelity / v3_source_id / v3_display_name and is
    path-neutral.
    """
    store_root = Path(store_root)
    trade_date = validate_date(trade_date)
    window = STAGE_WINDOWS.get(stage_id)
    if window is None:
        raise ValueError(f"unknown stage {stage_id!r}")
    rows = _validate_rows(selected.rows, trade_date, window[0], window[2])
    role = market_role(market, stage_id)
    status = _derive_status(selected, rows)
    if dry_run:
        return {
            "dry_run": True,
            "status": status,
            "trade_date": trade_date,
            "stage_id": stage_id,
            "role": role,
            "source_id": selected.source_id,
            "row_count": len(rows),
        }

    temp_root = Path(tempfile.mkdtemp(prefix="v3_live_acq_"))
    try:
        source_path = temp_root / f"adapter_{selected.source_id}_{stage_id}.csv"
        _write_artifact(source_path, trade_date, rows)
        spec = SourceSpec(
            source_id=selected.source_id,
            role=role,
            trade_date=trade_date,
            market=market,
            stages=(stage_id,),
            cutoff_at=window[2],
            source_path=source_path,
            required_columns=("trade_date", "bar_time"),
            bar_time_column="bar_time",
            expected_input_sha256=None,
            expected_row_count=None,
            cannot_confirm=tuple(selected.cannot_confirm or ()),
            provenance={
                "v3_fidelity": selected.fidelity,
                "v3_source_id": selected.source_id,
                "v3_display_name": selected.display_name,
                "shared_market": market,
                "requested_code_count": str(selected.requested_code_count or len(rows)),
                "completed_code_count": str(selected.completed_code_count or len(rows)),
                "no_data_code_count": str(len(selected.no_data_codes)),
                "no_data_codes_sha256": sha256_json(sorted(selected.no_data_codes)),
                "name_dictionary_sha256": selected.name_dictionary_sha256,
            },
        )
        store = SafeRootStore(
            root=store_root,
            allowlist=AllowlistRegistry(entries={(trade_date, role): (spec,)}),
        )
        return store.replay_file(
            owner=OWNER,
            trade_date=trade_date,
            role=role,
            source_id=selected.source_id,
            stage_id=stage_id,
            historical_backfill=historical_backfill,
            expected_previous=expected_previous,
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _validate_rows(
    rows: list[Any], trade_date: str, window_start_at: str, cutoff_at: str
) -> list[dict[str, Any]]:
    """Validate the 19-field rows; returns the rows unchanged on success."""
    expected_keys = set(NORMALIZED_MINUTE_FIELDS)
    expected_day = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("live rows must be dicts")
        if set(row) != expected_keys:
            raise ValueError("live row must carry exactly the 19 NORMALIZED_MINUTE_FIELDS")
        parsed: dict[str, datetime] = {}
        for field in ("update_time", "window_start", "window_end"):
            try:
                parsed[field] = datetime.strptime(str(row[field] or ""), _TIME_FMT)
            except ValueError as error:
                raise ValueError(f"malformed {field} {row[field]!r}") from error
            if parsed[field].strftime("%Y-%m-%d") != expected_day:
                raise ValueError(f"{field} {row[field]!r} is not on trade_date {trade_date}")
        lower = datetime.strptime(f"{expected_day} {window_start_at}", _TIME_FMT) + timedelta(minutes=1)
        upper = datetime.strptime(f"{expected_day} {cutoff_at}", _TIME_FMT)
        if not lower <= parsed["window_start"] <= parsed["window_end"] <= upper:
            raise ValueError("row window falls outside the frozen stage interval")
        if parsed["update_time"] != parsed["window_end"]:
            raise ValueError("update_time must equal window_end for an aggregated row")
    return rows


def _derive_status(selected: StageSourceResult, rows: list[dict[str, Any]]) -> str:
    """Explicit status: READY only for READ_OK rows without evidence."""
    if selected.status != "READ_OK" or selected.cannot_confirm:
        return CANNOT_CONFIRM
    if not rows:
        return READY_EMPTY
    return READY


def _write_artifact(path: Path, trade_date: str, rows: list[dict[str, Any]]) -> None:
    """Deterministic UTF-8-SIG CSV: 21-field header, preserved row order."""
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(ARTIFACT_FIELDS)
        for row in rows:
            bar_time = datetime.strptime(row["update_time"], _TIME_FMT).strftime("%H:%M:%S")
            writer.writerow([trade_date, bar_time] + [row[field] for field in NORMALIZED_MINUTE_FIELDS])
