"""Deterministic eight-stage scheduler and dry-run receipt writer."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from hashlib import sha256

from .candidate_input import CandidateInputError, read_candidate_input
from .contracts import EIGHT_STAGES, SAFETY_FLAGS
from .calendar import TradingDayState, calendar_provenance, resolve_market_states


class DueDecision:
    __slots__ = ("stage_id", "trade_date", "status", "scheduled_at", "idempotency_key", "calendar", "calendar_provenance")

    def __init__(self, *, stage_id: str, trade_date: str, status: str, scheduled_at: datetime | None, idempotency_key: str, calendar: dict[str, str]):
        self.stage_id = stage_id
        self.trade_date = trade_date
        self.status = status
        self.scheduled_at = scheduled_at
        self.idempotency_key = idempotency_key
        self.calendar = calendar
        self.calendar_provenance = calendar_provenance()


def _idempotency_key(stage_id: str, trade_date: str) -> str:
    return sha256(f"stage_center:{trade_date}:{stage_id}".encode("ascii")).hexdigest()


def evaluate_due(
    stage_id: str,
    trade_date: str,
    evaluated_at: datetime,
    *,
    historical_backfill: bool = False,
) -> DueDecision:
    """Pure due/catch-up decision; no filesystem or collector side effects."""
    stage = next((item for item in EIGHT_STAGES if item.stage_id == stage_id), None)
    key = _idempotency_key(stage_id, trade_date)
    if stage is None:
        return DueDecision(stage_id=stage_id, trade_date=trade_date, status="CANNOT_CONFIRM", scheduled_at=None, idempotency_key=key, calendar={})
    states = resolve_market_states(trade_date)
    calendar = {name: state.value for name, state in states.items()}
    if any(state is TradingDayState.UNKNOWN for state in states.values()):
        return DueDecision(stage_id=stage_id, trade_date=trade_date, status="CANNOT_CONFIRM", scheduled_at=None, idempotency_key=key, calendar=calendar)
    if (
        states["a_share"] is TradingDayState.NON_TRADING_DAY
        and states["hk_securities"] is TradingDayState.NON_TRADING_DAY
    ):
        return DueDecision(stage_id=stage_id, trade_date=trade_date, status="SKIPPED_NON_TRADING_DAY", scheduled_at=None, idempotency_key=key, calendar=calendar)
    try:
        scheduled_at = datetime.strptime(f"{trade_date} {stage.cutoff}", "%Y%m%d %H:%M:%S").replace(tzinfo=evaluated_at.tzinfo)
    except ValueError:
        return DueDecision(stage_id=stage_id, trade_date=trade_date, status="CANNOT_CONFIRM", scheduled_at=None, idempotency_key=key, calendar=calendar)
    if historical_backfill:
        status = "HISTORICAL_BACKFILL"
    elif evaluated_at.date() < scheduled_at.date():
        status = "NOT_DUE"
    elif evaluated_at.date() > scheduled_at.date():
        status = "CANNOT_CONFIRM"
    elif evaluated_at < scheduled_at:
        status = "NOT_DUE"
    elif evaluated_at == scheduled_at:
        status = "DUE"
    else:
        status = "LATE_CATCHUP_REPLAY"
    return DueDecision(stage_id=stage_id, trade_date=trade_date, status=status, scheduled_at=scheduled_at, idempotency_key=key, calendar=calendar)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def dry_run_schedule(*, candidate_input_root: Path | str, trade_date: str, output_root: Path | str) -> dict[str, Any]:
    """Validate one explicit candidate root and emit a no-collection schedule.

    The output is intentionally a dry-run receipt.  It never imports a V3/V3.5
    selector, starts a collector, updates a pointer, or writes live state.
    """
    try:
        candidate = read_candidate_input(candidate_input_root, trade_date)
    except CandidateInputError as error:
        result = {"ok": False, "status": "CANNOT_CONFIRM", "error": str(error), "calendar_provenance": calendar_provenance(), **SAFETY_FLAGS}
        _atomic_json(Path(output_root) / trade_date / "schedule.json", result)
        return result
    states = resolve_market_states(trade_date)
    if any(state is TradingDayState.UNKNOWN for state in states.values()):
        result = {"ok": False, "status": "CANNOT_CONFIRM", "error": "market calendar unknown for trade_date", "calendar": {key: value.value for key, value in states.items()}, "calendar_provenance": calendar_provenance(), **SAFETY_FLAGS}
        _atomic_json(Path(output_root) / trade_date / "schedule.json", result)
        return result
    if all(
        state is TradingDayState.NON_TRADING_DAY
        for state in (states["a_share"], states["hk_securities"])
    ):
        result = {
            "schema_version": "stage_center.schedule_receipt.v1",
            "ok": False,
            "status": "SKIPPED_NON_TRADING_DAY",
            "trade_date": trade_date,
            "calendar": {key: value.value for key, value in states.items()},
            "calendar_provenance": calendar_provenance(),
            "stages": [],
            **SAFETY_FLAGS,
        }
        _atomic_json(Path(output_root) / trade_date / "schedule.json", result)
        return result
    stages = []
    for stage in EIGHT_STAGES:
        stages.append(
            {
                "stage_id": stage.stage_id,
                "cutoff": stage.cutoff,
                "window": stage.window,
                "markets": list(stage.markets),
                "status": "DRY_RUN_READY",
                "candidate_input_current": candidate.current_relative,
                "candidate_input_current_sha256": candidate.current_sha256,
                "candidate_run_id": candidate.run_id,
                **SAFETY_FLAGS,
            }
        )
    result = {
        "schema_version": "stage_center.schedule_receipt.v1",
        "ok": True,
        "status": "DRY_RUN_READY",
        "trade_date": trade_date,
        "generated_at": date.today().isoformat(),
        "candidate_input_root": str(candidate.root),
        "candidate_input_current": candidate.current_relative,
        "candidate_input_current_sha256": candidate.current_sha256,
        "candidate_codes": len(candidate.codes),
        "calendar_provenance": calendar_provenance(),
        "stages": stages,
        **SAFETY_FLAGS,
    }
    _atomic_json(Path(output_root) / trade_date / "schedule.json", result)
    return result
