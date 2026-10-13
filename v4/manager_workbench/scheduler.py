"""One-shot scheduler tick for existing Mac scheduler to invoke (no daemon)."""
from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .contracts import HK, Lane, Phase, validate_date
from .service import ManagerService


class CalendarUnavailable(RuntimeError):
    pass


def _require_calendar(calendar: Any, day: str) -> bool:
    if calendar is None or not callable(getattr(calendar, "is_hk_session", None)):
        raise CalendarUnavailable("HK_CALENDAR_NOT_BOUND")
    value = calendar.is_hk_session(day)
    if type(value) is not bool:
        raise CalendarUnavailable("HK_CALENDAR_UNKNOWN")
    return value


def tick(service: ManagerService, *, calendar: Any, stage_feed: Any,
         at: datetime | None = None) -> dict[str, Any]:
    """Idempotently assess 09:25, changed Stage runs, and 16:30 next-day due.

    Half-day/weekend status is entirely delegated to the authoritative calendar.
    Run this from the existing supervisor; it never installs a scheduler/service.
    """
    instant = at or datetime.now(HK)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("SCHEDULER_TIMEZONE_REQUIRED")
    local = instant.astimezone(HK)
    day = local.strftime("%Y%m%d")
    if not _require_calendar(calendar,day):
        return {"state":"NOT_APPLICABLE", "date":day,"reason":"HK_NON_TRADING_SESSION","jobs":[]}
    jobs: list[dict[str, str]] = []
    at925 = datetime.combine(local.date(), time(9,25), HK)
    at1630 = datetime.combine(local.date(), time(16,30), HK)
    if local >= at925:
        frozen = service.store.get_plan(day,Phase.PREOPEN.value)
        if frozen is None:
            plan = service.freeze_preopen(day, cutoff=at925)
            jobs.append({"phase":"PREOPEN","run_id":plan.run_id,"timing":"LATE_CATCHUP" if local>at925 else "ON_SLOT"})
    if not callable(getattr(stage_feed, "completed_runs",None)):
        raise CalendarUnavailable("STAGE_FEED_NOT_BOUND")
    stage_runs = stage_feed.completed_runs(day)
    if not isinstance(stage_runs,list):
        raise CalendarUnavailable("STAGE_RUNS_UNKNOWN")
    for item in stage_runs:
        if not isinstance(item,dict) or not item.get("run_id") or not item.get("input_sha256"):
            raise CalendarUnavailable("STAGE_RECEIPT_INVALID")
        key = "stage_"+item["run_id"]
        # Clock/rules scope is stored on the generated job. The producer is never modified.
        signature = item["input_sha256"]
        current = service.store.cursor(key)
        if current and current.get("sha256") == signature:
            continue
        job = service.submit(day, Phase.INTRADAY, trigger="SCHEDULED",cutoff=local,
                             scope_refs={"stage_run_id":item["run_id"],"stage_input_sha256":signature,
                                         "timing_status":"ON_SLOT"})
        service.store.set_cursor(key,{"sha256":signature,"job_id":job.job_id})
        jobs.append({"phase":"INTRADAY","run_id":job.run_id,"job_id":job.job_id})
    if local >= at1630:
        if not callable(getattr(calendar,"next_hk_session",None)):
            raise CalendarUnavailable("HK_NEXT_SESSION_NOT_BOUND")
        next_day = calendar.next_hk_session(day)
        validate_date(next_day)
        if not _require_calendar(calendar,next_day) or next_day <= day:
            raise CalendarUnavailable("HK_NEXT_SESSION_INVALID")
        key = "nextday_"+day
        if not service.store.cursor(key):
            job = service.submit(next_day,Phase.NEXT_DAY,trigger="SCHEDULED",cutoff=local,
                                 scope_refs={"source_hk_session":day,
                                             "timing_status":"LATE_CATCHUP" if local>at1630 else "ON_SLOT"})
            service.store.set_cursor(key,{"job_id":job.job_id,"target_date":next_day,"cutoff":local.isoformat()})
            jobs.append({"phase":"NEXT_DAY","run_id":job.run_id,"job_id":job.job_id})
    return {"state":"DUE_EVALUATED","date":day,"jobs":jobs}
