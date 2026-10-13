"""Mounted-only FastAPI router. Every GET is read-only and version-scoped."""
from __future__ import annotations

from typing import Any, Literal
import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contracts import Decision, Lane, Phase, envelope, validate_date
from .jobs import JobConflict
from .legacy import LegacyHistory
from .service import ManagerService
from .store import StorageConflict, StorageUnavailable

PREFIX = "/api/v4/manager-workbench"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_date: str
    phase: Literal["MANUAL", "RETROSPECTIVE"]
    lanes: list[Lane] | None = None

    @field_validator("target_date")
    @classmethod
    def check_date(cls, value: str) -> str:
        return validate_date(value)


def _date(value: str) -> str:
    try:
        return validate_date(value)
    except ValueError as exc:
        raise HTTPException(422, "DATE_INVALID") from exc


def _not_found() -> HTTPException:
    return HTTPException(404, "ENTITY_NOT_FOUND")


def _safe_errors(f):
    try:
        return f()
    except (StorageConflict, JobConflict) as exc:
        raise HTTPException(409, str(exc)) from exc
    except (StorageUnavailable, OSError) as exc:
        raise HTTPException(503, "STATE_CHANNEL_UNAVAILABLE") from exc
    except KeyError as exc:
        raise _not_found() from exc
    except ValueError as exc:
        raise HTTPException(422, "PARAMETER_INVALID") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "WORKBENCH_READ_UNAVAILABLE") from exc


def _public(value: Any) -> Any:
    """No file paths, private content or process traces in HTTP responses."""
    denied = ("secret", "password", "token", "cookie", "credential", "authorization",
              "file_path", "local_path", "stderr", "stack", "traceback", "raw_body",
              "prompt", "private_key")
    if isinstance(value, dict):
        return {key:_public(item) for key,item in value.items()
                if not any(part in str(key).lower() for part in denied)}
    if isinstance(value,list):
        return [_public(item) for item in value]
    if isinstance(value,str) and (value.startswith(("/", "file://", "~/", "\\")) or
                                    re.search(r"(?:[A-Z]:\\Users\\|/Users/|/home/|/private/)",value)):
        return "[REDACTED_LOCAL_REFERENCE]"
    return value


def _index(s) -> dict[str, Any]:
    return {"origin":"NEW", "run_id":s.run_id, "phase":s.context.phase.value,
            "generated_at":s.generated_at,"product_sha256":s.product_sha256,
            "input_sha256":s.input_sha256, "state":"PARTIAL" if s.gaps else "READY"}


def create_router(service: ManagerService) -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["manager-workbench"])

    @router.get("/days/{date}")
    def read_day(date: str, phase: Phase | None = None, run_id: str | None = None,
                 offset: int = Query(0,ge=0), limit: int = Query(50,ge=1,le=200),
                 decision: Decision | None = None, lane: Lane | None = None,
                 q: str | None = Query(None,max_length=128)):
        day = _date(date)

        def read():
            snap = service.store.get_plan(day,phase.value if phase else None,run_id)
            versions = [_index(p) for p in service.store.list_plans(day)]
            if snap is None:
                return envelope("NOT_RUN", {"snapshot":None,"stocks":[],
                           "counts":None,"versions":versions,
                           "pagination":{"total":0,"offset":offset,"limit":limit}},["NO_SAVED_PLAN"])
            stocks = list(snap.stocks)
            if decision:
                stocks = [s for s in stocks if s.decision == decision]
            if lane:
                stocks = [s for s in stocks if lane.value in s.lane_decisions]
            if q:
                term = q.casefold()
                stocks = [s for s in stocks if term in s.symbol.casefold() or term in (s.name or "").casefold()]
            meta=snap.model_dump(mode="json")
            meta.pop("stocks",None)
            meta["lanes"]=[{"lane":l.lane.value,"state":l.state.value,
                            "coverage":l.coverage.model_dump(mode="json"),"rows_count":len(l.rows),
                            "input_sha256":l.input_sha256,"gaps":l.gaps} for l in snap.lanes]
            return envelope("PARTIAL" if snap.gaps else "READY", {
                "snapshot": _public(meta),
                "stocks": _public([x.model_dump(mode="json") for x in stocks[offset:offset+limit]]),
                "counts": snap.counts.model_dump(mode="json"),
                "versions":versions,"pagination":{"total":len(stocks),"offset":offset,"limit":limit}},snap.gaps)
        return _safe_errors(read)

    @router.get("/stocks/{symbol}")
    def read_stock(symbol: str, date: str, run_id: str):
        day = _date(date)

        def read():
            snap = service.store.get_plan(day, run_id=run_id)
            if not snap:
                raise _not_found()
            item = next((s for s in snap.stocks if s.symbol == symbol),None)
            if item is None:
                raise _not_found()
            details=[{"lane":l.lane.value,"rows":[r for r in l.rows if r.get("symbol")==symbol],
                      "evidence_refs":[e.model_dump(mode="json") for e in l.evidence_refs if e.evidence_id in item.evidence_ids]}
                     for l in snap.lanes]
            return envelope("READY", _public({"plan_run_id":snap.run_id,"stock":item.model_dump(mode="json"),
                                               "lane_details":details}))
        return _safe_errors(read)

    @router.get("/history")
    def read_history(date: str):
        day = _date(date)

        def read():
            old = LegacyHistory(service.config.legacy_root).read_index(day)
            entries = [_index(s) for s in service.store.list_plans(day)] + old
            return envelope("READY" if entries else "NOT_RUN",{"date":day,"versions":entries})
        return _safe_errors(read)

    @router.get("/reviews/{date}")
    def read_review(date: str, plan_run_id: str):
        day = _date(date)

        def read():
            plan = service.store.get_plan(day,run_id=plan_run_id)
            if plan is None:
                raise _not_found()
            review = service.store.get_review(day,plan_run_id)
            if review is None:
                return envelope("NOT_RUN",None,["SAME_DATE_CLOSE_INPUT_UNAVAILABLE"])
            return envelope("READY",_public(review.model_dump(mode="json")),review.gaps)
        return _safe_errors(read)

    @router.post("/runs",status_code=202)
    def create_run(payload: RunRequest):
        def run():
            record = service.submit(payload.target_date,Phase(payload.phase),trigger="MANUAL",lanes=payload.lanes)
            return envelope("QUEUED" if record.state.value=="QUEUED" else record.state.value,
                     {"job_id":record.job_id,"run_id":record.run_id,"status_url":f"{PREFIX}/runs/{record.job_id}"})
        return _safe_errors(run)

    @router.get("/runs/{id}")
    def read_job(id: str):
        def read():
            job=service.jobs.get(id)
            return envelope(job.state.value,_public(job.model_dump(mode="json")))
        return _safe_errors(read)

    @router.post("/runs/{id}/retry",status_code=202)
    def retry_run(id: str):
        def run():
            record = service.retry(id)
            return envelope(record.state.value,{"job_id":record.job_id,"run_id":record.run_id,
                             "status_url":f"{PREFIX}/runs/{record.job_id}"})
        return _safe_errors(run)

    return router
