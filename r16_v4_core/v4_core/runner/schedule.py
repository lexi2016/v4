"""Authoritative daily owner windows and evidence deadlines in Beijing time."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable

from v4_core.runner.evidence import DatedInputs, EvidenceError, aware_time, iso_date, mapping, require


@dataclass(frozen=True)
class FoldedTask:
    name: str
    starts: str
    expires: str
    verify_at: str


@dataclass(frozen=True)
class MainStage:
    stage_id: str
    tasks: tuple[FoldedTask, ...]


MAIN_STAGES = {
    (9, 25): MainStage("STAGE_0925", (
        FoldedTask("prepare_hk_auction", "09:15", "09:24", "09:15"),
        FoldedTask("a_auction_deadline", "09:15", "09:24", "09:24"),
        FoldedTask("hk_visibility_deadline", "09:25", "09:27", "09:27"),
    )),
    (9, 35): MainStage("STAGE_0930_0935", (
        FoldedTask("prepare_opening_inputs", "09:34", "09:35", "09:34"),
        FoldedTask("opening_visibility_deadline", "09:35", "09:37", "09:37"),
    )),
    (9, 40): MainStage("STAGE_0935_0940", (
        FoldedTask("prepare_opening_inputs", "09:39", "09:40", "09:39"),
        FoldedTask("opening_visibility_deadline", "09:40", "09:41", "09:41"),
    )),
    (9, 45): MainStage("STAGE_0940_0945", (
        FoldedTask("prepare_opening_inputs", "09:44", "09:45", "09:44"),
        FoldedTask("opening_visibility_deadline", "09:45", "09:46", "09:46"),
    )),
    (10, 30): MainStage("STAGE_0945_1030", (
        FoldedTask("prepare_intraday_inputs", "10:29", "10:30", "10:29"),
        FoldedTask("intraday_visibility_deadline", "10:30", "10:31", "10:31"),
    )),
    (13, 15): MainStage("STAGE_1300_1315", (
        FoldedTask("prepare_intraday_inputs", "13:14", "13:15", "13:14"),
        FoldedTask("intraday_visibility_deadline", "13:15", "13:16", "13:16"),
    )),
    (15, 0): MainStage("STAGE_1445_1500", (
        FoldedTask("prepare_stage7_inputs", "14:59", "15:00", "14:59"),
        FoldedTask("stage7_visibility_deadline", "15:00", "15:01", "15:01"),
    )),
    (15, 55): MainStage("STAGE_1545_1555", (
        FoldedTask("prepare_close_inputs", "15:50", "15:55", "15:50"),
        FoldedTask("close_visibility_deadline", "15:55", "15:56", "15:56"),
    )),
}


_SOURCE_WAIT_DEADLINES = {"a_daily": "16:55", "hk_cache_write": "17:45", "evening": "19:05"}


def read_dispatch_inputs(root: Path | None, day: str) -> tuple[DatedInputs | None, str]:
    if root is None:
        return None, "DATED_INPUTS_UNAVAILABLE"
    try:
        return DatedInputs.load(root, day), ""
    except EvidenceError as exc:
        return None, str(exc)


def _available(inputs: DatedInputs | None, phase: str, asof: datetime) -> bool:
    if inputs is None:
        return False

    def ready(entry: dict, names: tuple[str, ...]) -> bool:
        return (aware_time(entry.get("observed_at")) <= asof
                and all(inputs.referenced_path(entry.get(name)).is_file() for name in names))

    try:
        if phase == "a_daily":
            daily = inputs.entry("a_daily")
            close = mapping(inputs.entry("workloads").get("hk_close"), "HK_CLOSE_NATIVE_SOURCES_UNBOUND")
            return ready(daily, ("bars", "authority", "coverage_receipt")) and ready(
                close, ("close_snapshot", "close_snapshot_receipt", "model_pool"),
            )
        if phase == "hk_cache_write":
            entry = inputs.entry("hk_cache")
            receipt = mapping(inputs.file(entry.get("receipt")).json(), "INVALID_HK_CACHE_RECEIPT")
            return aware_time(receipt.get("finished_at")) <= asof and all(
                inputs.referenced_path(entry.get(name)).is_file() for name in ("artifact", "manifest")
            )
        hourly = mapping(inputs.entry("workloads").get("hourly_announcements"), "HOURLY_NATIVE_SOURCE_UNBOUND")
        return ready(hourly, ("source",))
    except EvidenceError:
        # The dated index may be atomically replaced when its source completes.
        return False


def dispatch_evidence_deadline(start: datetime, phase: str) -> datetime | None:
    clock = _SOURCE_WAIT_DEADLINES.get(phase)
    return at_time(start, clock) if clock else None


def wait_for_dispatch_evidence(
    root: Path | None, start: datetime, phase: str, current: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> tuple[DatedInputs | None, str, datetime]:
    deadline = dispatch_evidence_deadline(start, phase) if root is not None else None
    while True:
        observed = current()
        inputs, gap = read_dispatch_inputs(root, start.date().isoformat())
        if deadline is not None and observed >= deadline:
            return inputs, gap, deadline
        if deadline is None or _available(inputs, phase, observed):
            return inputs, gap, observed
        sleep(min(5, (deadline - observed).total_seconds()))


def at_time(anchor: datetime, hhmm: str) -> datetime:
    return datetime.combine(anchor.date(), time.fromisoformat(hhmm), anchor.tzinfo)


def folded_readbacks(
    inputs: DatedInputs | None, stage: MainStage, asof: datetime,
) -> dict[str, dict[str, Any]]:
    result = {}
    for task in stage.tasks:
        binding = {
            "task": task.name, "starts_at": at_time(asof, task.starts).isoformat(),
            "expires_at": at_time(asof, task.expires).isoformat(), "verify_at": at_time(asof, task.verify_at).isoformat(),
            "stage_id": stage.stage_id,
        }
        if asof < at_time(asof, task.verify_at):
            result[task.verify_at] = {**binding, "status": "PENDING", "reason": "EVIDENCE_WINDOW_NOT_REACHED"}
            continue
        try:
            require(inputs is not None, "DATED_INPUTS_UNAVAILABLE")
            entry = mapping(inputs.entry("main_tasks").get(task.verify_at), "FOLDED_TASK_EVIDENCE_UNAVAILABLE")
            observed = aware_time(entry.get("observed_at"))
            require(at_time(asof, task.starts) <= observed <= at_time(asof, task.expires)
                    and observed <= asof, "FOLDED_TASK_EVIDENCE_OUTSIDE_VALIDITY")
            artifact = inputs.file(entry.get("artifact"))
            receipt_file = inputs.file(entry.get("receipt"))
            record = mapping(receipt_file.json(), "FOLDED_TASK_RECEIPT_INVALID")
            require(iso_date(record.get("trade_date")) == inputs.trade_date and record.get("stage_id") == stage.stage_id
                    and record.get("task") == task.name and record.get("status") == "READY"
                    and aware_time(record.get("observed_at")) == observed
                    and record.get("artifact_sha256") == artifact.sha256,
                    "FOLDED_TASK_EVIDENCE_IDENTITY_MISMATCH")
            require(all(record.get(key) is False for key in ("production_allowed", "buy_gate_updated", "orders_sent")),
                    "FOLDED_TASK_EVIDENCE_UNSAFE")
            result[task.verify_at] = {**binding, "status": "READY", "observed_at": observed.isoformat(),
                                      "artifact": artifact.identity(), "receipt": receipt_file.identity()}
        except EvidenceError as exc:
            result[task.verify_at] = {**binding, "status": "CANNOT_CONFIRM", "reason": str(exc)}
    return result
