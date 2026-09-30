"""Collector registry and the ``file_replay`` collector.

Pure Python file I/O only — no subprocess, no shell, no network. The collector
reads a source pinned by an injected allowlist spec, scans it into a
row/temporal/provenance summary and hands raw bytes to the store. A zero-row
or unproven input never yields status READY (it becomes READY_EMPTY or
CANNOT_CONFIRM).

Persisted metadata is path-neutral: no absolute host paths, no companion
payload dumps — only source_id plus minimal provenance (e.g. companion
filename) supplied by the allowlist spec.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .constants import CANNOT_CONFIRM, READY, READY_EMPTY
from .hashing import sha256_file
from .allowlist import SourceSpec

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


@dataclass
class ScanResult:
    input_sha256: str
    row_count: int
    max_bar_time: str
    temporal_cutoff_safe: bool
    header: list[str]
    status: str
    reason: str = ""
    issues: list[str] = field(default_factory=list)
    cannot_confirm: list[str] = field(default_factory=list)


def _normalize_time(value: str) -> str | None:
    match = _TIME_RE.match(value.strip())
    if not match:
        return None
    hour, minute, second = match.group(1), match.group(2), match.group(3) or "00"
    return f"{int(hour):02d}:{minute}:{second}"


def scan_csv(source_path: Path, spec: SourceSpec) -> ScanResult:
    """Stream the CSV: header validation, row width/date/time checks.

    Status rules (fail-closed, explicit evidence in ``issues``):
      - no header / decode error                      -> CANNOT_CONFIRM
      - row too short for required indices            -> CANNOT_CONFIRM
      - row trade_date != spec.trade_date             -> CANNOT_CONFIRM
      - unparseable bar_time                          -> CANNOT_CONFIRM
      - valid header, zero rows                       -> READY_EMPTY
      - any bar_time exceeds cutoff                   -> CANNOT_CONFIRM
      - row_count != frozen pin                       -> CANNOT_CONFIRM
      - spec cannot_confirm evidence present          -> CANNOT_CONFIRM (never READY)
      - otherwise                                     -> READY
    """
    input_sha256 = sha256_file(source_path)
    issues: list[str] = []
    cannot_confirm: list[str] = list(spec.cannot_confirm)
    bar_index = -1
    trade_index = -1
    header: list[str] = []
    row_count = 0
    max_bar_time = ""
    temporal_cutoff_safe = True
    status = CANNOT_CONFIRM
    reason = ""
    cutoff = _normalize_time(spec.cutoff_at)
    if cutoff is None:
        issues.append(f"invalid cutoff_at: {spec.cutoff_at!r}")

    try:
        with open(source_path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None or not any(str(cell).strip() for cell in header):
                issues.append("no header row")
            else:
                header = [str(cell).strip() for cell in header]
                missing = [col for col in spec.required_columns if col not in header]
                if missing:
                    issues.append(f"missing required columns: {','.join(missing)}")
                # Required columns absent -> status stays CANNOT_CONFIRM, but
                # still stream/count every nonblank data row so the manifest
                # row_count matches the artifact's actual nonblank count. No
                # time/date indexing while the required indices are unknown.
                indexed = not missing
                bar_index = header.index(spec.bar_time_column) if indexed else -1
                trade_index = header.index("trade_date") if indexed else -1
                for line_no, row in enumerate(reader, start=2):
                    if not row or all(not str(cell).strip() for cell in row):
                        continue
                    row_count += 1
                    if not indexed:
                        continue
                    max_index = max(trade_index, bar_index)
                    if max_index >= len(row):
                        issues.append(f"line {line_no}: row too short for required indices")
                        continue
                    raw_date = str(row[trade_index]).strip()
                    if raw_date != spec.trade_date:
                        issues.append(f"line {line_no}: trade_date {raw_date!r} != {spec.trade_date!r}")
                        continue
                    raw_time = str(row[bar_index]).strip()
                    normalized = _normalize_time(raw_time)
                    if normalized is None:
                        issues.append(f"line {line_no}: unparseable bar_time {raw_time!r}")
                        continue
                    if normalized > max_bar_time:
                        max_bar_time = normalized
                    if normalized > (cutoff or "23:59:59"):
                        temporal_cutoff_safe = False
    except (UnicodeDecodeError, OSError) as error:
        return ScanResult(
            input_sha256, 0, "", False, [], CANNOT_CONFIRM,
            reason=f"read/decode failure: {error}", issues=[f"read/decode failure: {error}"],
            cannot_confirm=cannot_confirm,
        )

    if issues:
        status = CANNOT_CONFIRM
        reason = "; ".join(issues)
    elif row_count == 0:
        status = READY_EMPTY
    elif not temporal_cutoff_safe:
        status = CANNOT_CONFIRM
        reason = "bar_time exceeds cutoff_at; rows cannot be confirmed in-window"
    else:
        status = READY

    # DS2B: a spec carrying explicit cannot_confirm evidence may never upgrade
    # to READY; the existing evidence is reused verbatim as the reason.
    if spec.cannot_confirm and status != CANNOT_CONFIRM:
        status = CANNOT_CONFIRM
        reason = "; ".join(spec.cannot_confirm)

    if spec.expected_row_count is not None and row_count != spec.expected_row_count:
        pin_note = f"row_count {row_count} != frozen oracle {spec.expected_row_count}"
        reason = (reason + "; " + pin_note) if reason else pin_note
        status = CANNOT_CONFIRM
        cannot_confirm.append(pin_note)

    return ScanResult(
        input_sha256=input_sha256,
        row_count=row_count,
        max_bar_time=max_bar_time,
        temporal_cutoff_safe=temporal_cutoff_safe,
        header=header,
        status=status,
        reason=reason,
        issues=issues,
        cannot_confirm=cannot_confirm,
    )


@dataclass(frozen=True)
class CollectOutput:
    scan: ScanResult
    manifest_payload: dict[str, Any]


def collect_file_replay(spec: SourceSpec, *, captured_at: str) -> CollectOutput:
    """Scan the allowlisted source; caller streams bytes to the artifact."""
    scan = scan_csv(spec.source_path, spec)
    manifest_payload = {
        "schema_version": "v3_shared_data.manifest.v1",
        "collector": spec.collector,
        "source_id": spec.source_id,
        "source_filename": spec.source_path.name,
        "market": spec.market,
        "trade_date": spec.trade_date,
        "signal_date": spec.provenance.get("signal_date", spec.trade_date),
        "stage_id": spec.stages[0] if spec.stages else "",
        "cutoff_at": spec.cutoff_at,
        "captured_at": captured_at,
        "row_count": scan.row_count,
        "input_sha256": scan.input_sha256,
        "max_bar_time": scan.max_bar_time,
        "temporal_cutoff_safe": scan.temporal_cutoff_safe,
        "provenance": dict(spec.provenance),
        "cannot_confirm": scan.cannot_confirm,
        "issues": scan.issues,
    }
    return CollectOutput(scan=scan, manifest_payload=manifest_payload)


# name -> callable(spec, *, captured_at) -> CollectOutput
COLLECTOR_REGISTRY: dict[str, Callable[..., CollectOutput]] = {
    "file_replay": collect_file_replay,
}


def get_collector(name: str) -> Callable[..., CollectOutput]:
    collector = COLLECTOR_REGISTRY.get(name)
    if collector is None:
        raise ValueError(f"unknown collector {name!r}; registry is fixed")
    return collector
