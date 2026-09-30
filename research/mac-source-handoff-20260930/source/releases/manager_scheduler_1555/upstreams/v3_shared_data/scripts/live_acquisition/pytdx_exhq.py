"""Fail-closed wrapper around the fixed PyTDX ExHQ HK minute probe."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .contracts import STAGE_WINDOWS, StageSourceResult, market_role
from .futu_minute import aggregate_futu_minute_window_rows
from .pytdx_exhq_probe import MARKER

PYTDX_EXHQ_BATCH_SIZE = 64
PYTDX_EXHQ_BATCH_TIMEOUT_SECONDS = 180.0


def _failure(
    status: str,
    *,
    error: str,
    cannot_confirm: list[str],
    rows: list[dict[str, Any]] | None = None,
    requested: int = 0,
    completed: int = 0,
    no_data_codes: list[str] | None = None,
) -> StageSourceResult:
    return StageSourceResult(
        source_id="pytdx",
        display_name="TDXPy ExHQ",
        fidelity="TDXPY_EXHQ_HK_1MIN_CUTOFF_SAFE",
        status=status,
        rows=list(rows or []),
        error=error,
        cannot_confirm=cannot_confirm,
        requested_code_count=requested,
        completed_code_count=completed,
        no_data_codes=list(no_data_codes or []),
    )


def _parse_payload(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        if line.startswith(MARKER):
            value = json.loads(line[len(MARKER):])
            if not isinstance(value, dict):
                raise ValueError("PyTDX marker payload must be an object")
            return value
    raise ValueError(f"PyTDX stdout missing {MARKER}")


def _collect_pytdx_exhq_batch(
    python_path: Path | str,
    trade_date: str,
    stage_id: str,
    codes: list[str],
    *,
    market: str = "HK_CONNECT",
    process_runner: Callable[..., Any],
    timeout_seconds: float = 180,
) -> StageSourceResult:
    if market != "HK_CONNECT":
        raise ValueError("PyTDX ExHQ collector is HK_CONNECT only")
    if stage_id not in STAGE_WINDOWS:
        raise ValueError(f"unknown stage {stage_id!r}")
    market_role(market, stage_id)
    python_path = Path(python_path)
    if not python_path.is_file():
        raise ValueError(f"python_path is not a file: {python_path}")
    if not codes or len(set(codes)) != len(codes) or any(
        not isinstance(code, str) or not code.startswith("HK.") or len(code) != 8
        for code in codes
    ):
        raise ValueError("codes must be unique HK.##### symbols")

    stdin = json.dumps(
        {"trade_date": trade_date, "stage_id": stage_id, "codes": codes},
        ensure_ascii=False,
    )
    try:
        proc = process_runner(
            [str(python_path), "-m", "scripts.live_acquisition.pytdx_exhq_probe"],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
        )
    except Exception as exc:
        return _failure(
            "READ_FAILED",
            error=f"PyTDX probe execution failed: {exc}",
            cannot_confirm=["PyTDX ExHQ probe execution failed"],
            requested=len(codes),
        )
    if proc.returncode != 0:
        evidence = str(proc.stderr or proc.stdout or "")[-1200:]
        return _failure(
            "READ_FAILED",
            error=f"PyTDX probe exit code {proc.returncode}: {evidence}",
            cannot_confirm=["PyTDX ExHQ probe returned an error"],
            requested=len(codes),
        )
    try:
        payload = _parse_payload(proc.stdout)
        raw_rows = payload.get("raw_rows")
        errors = payload.get("errors")
        no_data_codes = payload.get("no_data_codes")
        requested = int(payload.get("requested_code_count"))
        completed = int(payload.get("completed_code_count"))
        if not isinstance(raw_rows, list) or not isinstance(errors, list) or not isinstance(no_data_codes, list):
            raise ValueError("PyTDX coverage payload is malformed")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failure(
            "READ_FAILED",
            error=f"PyTDX payload invalid: {exc}",
            cannot_confirm=["PyTDX ExHQ output cannot be verified"],
            requested=len(codes),
        )

    aggregated = aggregate_futu_minute_window_rows(trade_date, stage_id, raw_rows)
    full_coverage = (
        requested == len(codes)
        and completed == len(codes)
        and not errors
        and set(row["code"] for row in aggregated).union(no_data_codes) == set(codes)
    )
    if full_coverage:
        return _failure(
            "READ_OK",
            error=(
                f"source_host={payload.get('source_host')}; "
                f"requested={requested}; rows={len(aggregated)}; no_data={len(no_data_codes)}"
            ),
            cannot_confirm=[],
            rows=aggregated,
            requested=requested,
            completed=completed,
            no_data_codes=no_data_codes,
        )
    return _failure(
        "DATA_PARTIAL" if aggregated else "READ_FAILED",
        error=json.dumps(errors, ensure_ascii=False)[:1200] or "PyTDX full-market coverage incomplete",
        cannot_confirm=[
            f"PyTDX full-market coverage incomplete: completed={completed}/{requested}"
        ],
        rows=aggregated,
        requested=requested,
        completed=completed,
        no_data_codes=no_data_codes,
    )


def _merge_batch_results(
    results: list[StageSourceResult],
    requested_codes: list[str],
) -> StageSourceResult:
    rows_by_code: dict[str, dict[str, Any]] = {}
    for result in results:
        for row in result.rows:
            code = str(row.get("code") or "")
            if code in requested_codes and code not in rows_by_code:
                rows_by_code[code] = row

    rows = [rows_by_code[code] for code in requested_codes if code in rows_by_code]
    no_data_codes = list(dict.fromkeys(
        code
        for result in results
        for code in result.no_data_codes
        if code in requested_codes
    ))
    cannot_confirm = list(dict.fromkeys(
        reason
        for result in results
        for reason in result.cannot_confirm
        if reason
    ))
    source_evidence = [
        f"batch_{index + 1}: {result.error}"
        for index, result in enumerate(results)
        if result.error
    ]
    completed = sum(max(0, int(result.completed_code_count or 0)) for result in results)
    full_coverage = (
        len(rows) == len(requested_codes)
        and all(result.status == "READ_OK" and not result.cannot_confirm for result in results)
        and not no_data_codes
    )
    if full_coverage:
        return _failure(
            "READ_OK",
            error="; ".join(source_evidence) or f"rows={len(rows)}",
            cannot_confirm=[],
            rows=rows,
            requested=len(requested_codes),
            completed=completed,
            no_data_codes=[],
        )

    cannot_confirm.append(
        f"PyTDX ExHQ batch coverage incomplete: completed={completed}/{len(requested_codes)}"
    )
    return _failure(
        "DATA_PARTIAL" if rows else "READ_FAILED",
        error="; ".join(source_evidence) or "PyTDX ExHQ batch probes returned no rows",
        cannot_confirm=list(dict.fromkeys(cannot_confirm)),
        rows=rows,
        requested=len(requested_codes),
        completed=completed,
        no_data_codes=no_data_codes,
    )


def collect_pytdx_exhq_minute(
    python_path: Path | str,
    trade_date: str,
    stage_id: str,
    codes: list[str],
    *,
    market: str = "HK_CONNECT",
    process_runner: Callable[..., Any],
    timeout_seconds: float = 180,
) -> StageSourceResult:
    """Collect exact-date HK minutes in bounded independent batches."""

    if not codes or len(set(codes)) != len(codes) or any(
        not isinstance(code, str) or not code.startswith("HK.") or len(code) != 8
        for code in codes
    ):
        raise ValueError("codes must be unique HK.##### symbols")
    batch_timeout = min(float(timeout_seconds), PYTDX_EXHQ_BATCH_TIMEOUT_SECONDS)
    results = [
        _collect_pytdx_exhq_batch(
            python_path,
            trade_date,
            stage_id,
            codes[index:index + PYTDX_EXHQ_BATCH_SIZE],
            market=market,
            process_runner=process_runner,
            timeout_seconds=batch_timeout,
        )
        for index in range(0, len(codes), PYTDX_EXHQ_BATCH_SIZE)
    ]
    return _merge_batch_results(results, list(codes))

