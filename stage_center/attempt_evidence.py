"""Non-authoritative immutable attempt diagnostics. Does not grant a retry.

Real wall clocks are distinct from evaluated_at. File mtime is never used as
market time. Diagnostic I/O failure is reported, not used to authorize selection.
"""
from __future__ import annotations

import contextvars
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo
from infrastructure.owned_io import SafeRoot

_ACTIVE: contextvars.ContextVar["AttemptJournal | None"] = contextvars.ContextVar("stage_attempt_evidence", default=None)


def wall_now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="microseconds")


class AttemptJournal:
    def __init__(self, stage_root: Path, *, trade_date: str, stage_id: str,
                 attempt_number: int, evaluated_at: str, due_status: str):
        self.io = SafeRoot(Path(stage_root))
        self.attempt_id = uuid4().hex
        self.base = {"schema": "stage.attempt_diagnostic.v1", "attempt_id": self.attempt_id,
                     "trade_date": trade_date, "stage_id": stage_id,
                     "attempt_number": attempt_number, "evaluated_at": evaluated_at,
                     "due_status": due_status, "pid": os.getpid(), "ppid": os.getppid(),
                     "python_executable": sys.executable,
                     "authorizes_selection": False, "grants_retry": False}
        self.started = time.monotonic()
        self.index = 0
        self.errors: list[str] = []
        self.finished = False
        self.paths: list[str] = []

    def emit(self, event: str, detail: Mapping[str, Any]) -> None:
        self.index += 1
        relative = f"attempt_evidence/{self.attempt_id}/{self.index:03d}_{event}.json"
        payload = {**self.base, "event": event, "observed_at": wall_now(),
                   "elapsed_seconds": time.monotonic() - self.started, "detail": dict(detail)}
        try:
            raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
            self.io.write_bytes(relative, raw, require_absent=True)
            self.paths.append(relative)
        except (OSError, ValueError, TypeError) as exc:
            self.errors.append(f"{event}:{type(exc).__name__}:{exc}")

    def finish(self, result: Mapping[str, Any]) -> None:
        self.emit("RETURN", {key: result.get(key) for key in
                  ("status", "error", "blocked_layer", "first_failed_layer", "due_status")})
        self.finished = True

    def summary(self) -> dict[str, Any]:
        return {"schema": "stage.attempt_diagnostic_summary.v1", "attempt_id": self.attempt_id,
                "status": "INCOMPLETE" if self.errors else "RECORDED",
                "relative_paths": list(self.paths), "errors": list(self.errors),
                "hk_snapshot_events": sum(path.endswith("_HK_SNAPSHOT.json") for path in self.paths),
                "row_evidence_status": "OBSERVED" if any(path.endswith("_HK_SNAPSHOT.json") for path in self.paths) else "NOT_OBSERVED",
                "authorizes_selection": False, "grants_retry": False}


@contextmanager
def capture_attempt(stage_root: Path, **fields: Any) -> Iterator[AttemptJournal]:
    journal = AttemptJournal(stage_root, **fields)
    token = _ACTIVE.set(journal)
    journal.emit("START", {})
    try:
        yield journal
    except BaseException as exc:
        journal.emit("RAISED", {"type": type(exc).__name__, "message": str(exc)})
        raise
    finally:
        if not journal.finished and not journal.errors:
            # EXIT does not assert business success or termination safety.
            journal.emit("EXIT", {"return_recorded": False})
        _ACTIVE.reset(token)


def emit_snapshot(detail: Mapping[str, Any]) -> None:
    journal = _ACTIVE.get()
    if journal is not None:
        journal.emit("HK_SNAPSHOT", detail)


def temporal_diagnostic(rows, *, trade_date, cutoff_at, parse_timestamp,
                        fetch_started_at, fetch_finished_at, snapshot_sha256,
                        requested_codes_sha256, bridge_errors):
    """Explain the existing timestamp parser/predicate, never replace its verdict."""
    cutoff = parse_timestamp(cutoff_at, trade_date)
    cutoff_ok = cutoff is not None and cutoff.strftime("%Y%m%d") == trade_date
    report = []
    for row in rows:
        value = row.get("update_time") or row.get("update_time_us") or row.get("time")
        parsed = parse_timestamp(value, trade_date)
        if not cutoff_ok:
            reason = "INVALID_CUTOFF"
        elif parsed is None:
            reason = "MISSING_OR_UNPARSEABLE"
        elif parsed.strftime("%Y%m%d") != trade_date:
            reason = "WRONG_TRADE_DATE"
        elif parsed > cutoff:
            reason = "AFTER_CUTOFF"
        else:
            reason = "WITHIN_CUTOFF"
        report.append({"code": str(row.get("code", "")), "update_time": str(value or ""),
                       "parsed_by_existing_gate": parsed.isoformat() if parsed else None,
                       "reason": reason})
    return {"schema": "stage.hk_temporal_diagnostic.v1", "trade_date": trade_date,
            "cutoff_at": cutoff_at, "cutoff_parsed_by_existing_gate": cutoff.isoformat() if cutoff else None,
            "fetch_started_at": fetch_started_at, "fetch_finished_at": fetch_finished_at,
            "snapshot_sha256": snapshot_sha256, "requested_codes_sha256": requested_codes_sha256,
            "bridge_errors": list(bridge_errors), "rows": report,
            "parser_policy": "EXISTING_GATE_UNCHANGED", "authorizes_selection": False}
