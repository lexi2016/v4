"""One-shot scheduler tick for existing Mac scheduler to invoke (no daemon)."""
from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .contracts import HK, Lane, Phase, validate_date, digest
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


def _us_close_handoff(service: ManagerService, *, calendar: Any,
                      local: datetime) -> list[dict[str, str]]:
    """Consume a verified exact-session US close through the existing selector.

    The scheduler is already resident on the existing manager owner. This
    hook adds no producer or service: it submits the existing US_MAPPING lane
    only after the native owner binding verifies a post-close artifact/receipt.
    The cursor includes the exact payload SHA so repeated delivery is
    idempotent while a corrected immutable artifact can be consumed separately.
    """
    adapters = getattr(service, "adapters", None)
    config = getattr(adapters, "config", None)
    resolver = getattr(adapters, "_us_session", None)
    if config is None or not getattr(config, "us_root", None) or not callable(resolver):
        return []
    try:
        session = resolver(local.isoformat())
        target = calendar.next_hk_session(session)
        validate_date(session)
        validate_date(target)
        if target <= session or not _require_calendar(calendar, target):
            return []
        context = service.context(
            target, Phase.NEXT_DAY, trigger="SCHEDULED", cutoff=local,
            lanes=[Lane.US_MAPPING],
            scope_refs={"us_close_handoff": True, "us_session_date": session},
        )
        pin = (context.scope_refs.get("owner_bindings") or {}).get("us_mapping")
        if (not isinstance(pin, dict)
                or pin.get("capture_phase") != "POST_CLOSE"
                or pin.get("capture_status") not in {"READY", "READY_EMPTY"}
                or pin.get("capture_session_date") != session
                or not isinstance(pin.get("quote_sha256"), str)
                or len(pin["quote_sha256"]) != 64
                or not isinstance(pin.get("owner_receipt_sha256"), str)
                or len(pin["owner_receipt_sha256"]) != 64):
            return []
        artifact_sha = pin["quote_sha256"]
        cursor_key = f"us_close_{session}_{target}_{artifact_sha}"
        if service.store.cursor(cursor_key):
            return []
        job = service.submit(
            target, Phase.NEXT_DAY, trigger="SCHEDULED",
            lanes=[Lane.US_MAPPING], cutoff=local,
            scope_refs={
                "us_close_handoff": True,
                "us_session_date": session,
                "owner_artifact_sha256": artifact_sha,
                "owner_receipt_sha256": pin["owner_receipt_sha256"],
                "owner_manifest_sha256": pin.get("owner_manifest_sha256"),
                "source_cutoff": pin.get("capture_cutoff"),
            },
        )
        service.store.set_cursor(cursor_key, {
            "job_id": job.job_id,
            "run_id": job.run_id,
            "target_date": target,
            "us_session_date": session,
            "artifact_sha256": artifact_sha,
            "receipt_sha256": pin["owner_receipt_sha256"],
        })
        return [{"phase": "NEXT_DAY", "lane": "US_MAPPING",
                 "state": "SUBMITTED", "job_id": job.job_id,
                 "run_id": job.run_id, "target_date": target,
                 "us_session_date": session}]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Missing/partial owner input stays missing; no stale-session fallback.
        return []


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
    # US close may complete while HK is closed (for example Saturday 04:15 HKT).
    # Check the exact-session owner receipt before the HK-session-only jobs.
    jobs: list[dict[str, str]] = _us_close_handoff(service, calendar=calendar, local=local)
    if not _require_calendar(calendar,day):
        return {"state":"NOT_APPLICABLE", "date":day,
                "reason":"HK_NON_TRADING_SESSION","jobs":jobs}
    scheduled = getattr(getattr(service, "config", None), "scheduled_lanes", None)
    # A new configured scope cannot retry an older all-lane claim and thereby
    # restore paused research. Default keys/behavior remain compatible.
    suffix = "_"+digest(sorted(l.value for l in scheduled))[:16] if scheduled is not None else ""
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
        key = "stage_"+item["run_id"]+suffix
        # Clock/rules scope is stored on the generated job. The producer is never modified.
        signature = item["input_sha256"]
        current = service.store.cursor(key)
        if current and current.get("sha256") == signature:
            previous = service.jobs.get(current["job_id"])
            if previous.retryable and previous.state.value in {"FAILED","INTERRUPTED","PARTIAL"}:
                retry=service.retry(previous.job_id)
                service.store.set_cursor(key,{"sha256":signature,"job_id":retry.job_id})
                jobs.append({"phase":"INTRADAY","run_id":retry.run_id,"job_id":retry.job_id})
            continue
        job = service.submit(day, Phase.INTRADAY, trigger="SCHEDULED",cutoff=local,lanes=scheduled,
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
        split_oversold = scheduled is not None and Lane.OVERSOLD in scheduled
        if split_oversold:
            # Keep the existing 16:30 work moving while OVERSOLD waits for the
            # exact-date HK panel/master and any existing-owner TDX61 repair.
            other_lanes=[lane for lane in scheduled if lane!=Lane.OVERSOLD]
            if other_lanes:
                key="nextday_other_"+day+suffix
                if not service.store.cursor(key):
                    job=service.submit(next_day,Phase.NEXT_DAY,trigger="SCHEDULED",cutoff=local,lanes=other_lanes,
                        scope_refs={"source_hk_session":day,"merge_phase_lanes":True,
                            "timing_status":"LATE_CATCHUP" if local>at1630 else "ON_SLOT"})
                    service.store.set_cursor(key,{"job_id":job.job_id,"target_date":next_day,"cutoff":local.isoformat(),
                        "lanes":[lane.value for lane in other_lanes]})
                    jobs.append({"phase":"NEXT_DAY","run_id":job.run_id,"job_id":job.job_id})
            driver=getattr(service,"oversold_daily",None)
            if driver is not None:
                try:
                    progress=driver.tick(source_day=day,target_date=next_day,at=local)
                    jobs.append({"phase":"NEXT_DAY","lane":"OVERSOLD","state":str(progress.get("state","SCHEDULED"))})
                except Exception:
                    jobs.append({"phase":"NEXT_DAY","lane":"OVERSOLD","state":"CANNOT_CONFIRM"})
        else:
            key = "nextday_"+day+suffix
            if not service.store.cursor(key):
                job = service.submit(next_day,Phase.NEXT_DAY,trigger="SCHEDULED",cutoff=local,lanes=scheduled,
                                     scope_refs={"source_hk_session":day,
                                                 "timing_status":"LATE_CATCHUP" if local>at1630 else "ON_SLOT"})
                service.store.set_cursor(key,{"job_id":job.job_id,"target_date":next_day,"cutoff":local.isoformat()})
                jobs.append({"phase":"NEXT_DAY","run_id":job.run_id,"job_id":job.job_id})
    # Preserve the preopen latch above before any background capture enqueue.
    if getattr(service,"capture_jobs",None) and (scheduled is None or Lane.ANNOUNCEMENT in scheduled):
        capture_day=next_day if local>=at1630 else day
        capture_phase=Phase.NEXT_DAY if local>=at1630 else Phase.INTRADAY
        bucket=int(local.timestamp())//service.config.capture_poll_seconds
        key='capture_poll_'+str(bucket)
        if not service.store.cursor(key):
            context=service.context(capture_day,capture_phase,trigger='SCHEDULED',cutoff=local,lanes=[Lane.ANNOUNCEMENT])
            captured=service.request_capture(context)
            if captured:
                service.store.set_cursor(key,{'job_id':captured.job_id})
                jobs.append({'phase':capture_phase.value,'operation':'CAPTURE_MATERIAL','job_id':captured.job_id,'run_id':captured.run_id})
    return {"state":"DUE_EVALUATED","date":day,"jobs":jobs,
            "session_state":calendar.session_state(day) if hasattr(calendar,"session_state") else None}

