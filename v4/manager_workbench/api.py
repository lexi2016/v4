"""Mounted-only FastAPI router. Every GET is read-only and version-scoped."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contracts import Decision, Lane, Phase, envelope, validate_date
from .jobs import JobConflict
from .legacy import LegacyHistory
from .service import ManagerService
from .announcement_update import AnnouncementUpdate
from .store import StorageConflict, StorageUnavailable
from .display_read import saved_names, display_stock, us_summary, lane_projection, lane_stock
from .display import selection_view, canonical_lane_projection
from .engines.common import US_FACTOR_RULES_VERSION
from v4.hk_research_history import OwnedHKResearchHistory

from .us_mapping_catalog import CatalogValidationError, CatalogStore

PREFIX = "/api/v4/manager-workbench"
_US_MAPPING_CATALOG_STORE = CatalogStore()
US_MAPPING_REVIEW_OVERLAY_PATH = Path(__file__).resolve().parent / "research_data" / "us_hk_667_review_overlay_20261015.json"
US_MAPPING_CATALOG_PATH = Path(__file__).resolve().parent / "research_data" / "us_hk_667_catalog_20261015.json"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_date: str
    phase: Literal["MANUAL", "RETROSPECTIVE"]
    lanes: list[Lane] | None = Field(default=None,min_length=1,max_length=5)

    @field_validator("lanes")
    @classmethod
    def unique_lanes(cls,value):
        if value and len(value)!=len(set(value)):raise ValueError("DUPLICATE_LANES")
        return value

    @field_validator("target_date")
    @classmethod
    def check_date(cls, value: str) -> str:
        return validate_date(value)


class AnnouncementFlashUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_date: str

    @field_validator("target_date")
    @classmethod
    def check_date(cls, value: str) -> str:
        return validate_date(value)


class AnnouncementPreprocessedExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    phase: Literal["FIRST", "CONTINUE", "RECOVER_FAILED", "CONTINUE_REMAINING"]
    first_delivery_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    extension_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class AnnouncementFlashCachedProductRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    failed_job_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    product_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AnnouncementFlashResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_date: str
    source_job_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_progress_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_queue_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resume_action: str = Field(pattern=r"^(CANARY|CONTINUE)$")

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
        if str(exc).startswith("HK_HISTORY_RESOLUTION"):
            raise HTTPException(503, "HK_HISTORY_RESOLUTION_UNAVAILABLE") from exc
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


class WorkbenchRoute(APIRoute):
    def get_route_handler(self):
        original=super().get_route_handler()
        async def wrapped(request):
            try:return await original(request)
            except RequestValidationError:
                return JSONResponse(envelope("FAILED",None,["REQUEST_VALIDATION_FAILED"]),status_code=422)
            except HTTPException as exc:
                detail=exc.detail if isinstance(exc.detail,str) and re.fullmatch(r"[A-Z0-9_]{1,128}",exc.detail) else "REQUEST_FAILED"
                return JSONResponse(envelope("FAILED",None,[detail]),status_code=exc.status_code)
        return wrapped


def create_router(service: ManagerService) -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["manager-workbench"],route_class=WorkbenchRoute)
    announcement_update = AnnouncementUpdate(service) if service is not None else None

    @router.get("/announcement-flash")
    def read_announcement_flash(target_date: str | None = Query(None, pattern=r"^[0-9]{8}$")):
        if announcement_update is None:
            raise HTTPException(503, "ANNOUNCEMENT_FLASH_UNAVAILABLE")
        day = _date(target_date) if target_date else None
        def read():
            value = announcement_update.read(day)
            state = value.get("state", "UNAVAILABLE")
            return envelope(state, _public(value), value.get("gaps", []))
        return _safe_errors(read)

    @router.post("/announcement-flash/update", status_code=202)
    def update_announcement_flash(payload: AnnouncementFlashUpdateRequest):
        if announcement_update is None:
            raise HTTPException(503, "ANNOUNCEMENT_FLASH_UNAVAILABLE")
        def update():
            job = announcement_update.start(payload.target_date)
            state = job.state.value
            return envelope("QUEUED" if state == "QUEUED" else state, {
                "job_id": job.job_id,
                "target_date": job.context.target_date,
                "requested_target_date": payload.target_date,
                "step": job.step,
                "status_url": f"{PREFIX}/announcement-flash?target_date={job.context.target_date}",
            })
        return _safe_errors(update)

    @router.post("/announcement-flash/recover-cached-product", status_code=202)
    def recover_cached_announcement_product(payload: AnnouncementFlashCachedProductRecoveryRequest):
        if announcement_update is None:
            raise HTTPException(503, "ANNOUNCEMENT_FLASH_UNAVAILABLE")
        def recover():
            job = announcement_update.start_cached_product_recovery(
                payload.failed_job_id, payload.product_sha256)
            state = job.state.value
            return envelope("QUEUED" if state == "QUEUED" else state, {
                "job_id": job.job_id,
                "source_job_id": payload.failed_job_id,
                "capture_product_sha256": payload.product_sha256,
                "target_date": job.context.target_date,
                "step": job.step,
                "status_url": f"{PREFIX}/announcement-flash?target_date={job.context.target_date}",
            })
        return _safe_errors(recover)

    @router.post("/announcement-flash/{job_id}/execute-preprocessed", status_code=202)
    def execute_preprocessed_announcement(job_id: str, payload: AnnouncementPreprocessedExecuteRequest):
        if announcement_update is None:
            raise HTTPException(503, "ANNOUNCEMENT_FLASH_UNAVAILABLE")
        def execute():
            job = announcement_update.execute_preprocessed(job_id, payload.report_sha256,
                    payload.phase, payload.first_delivery_sha256, payload.extension_sha256)
            return envelope(job.state.value, {"job_id": job.job_id, "phase": payload.phase,
                                              "report_sha256": payload.report_sha256})
        return _safe_errors(execute)

    @router.post("/announcement-flash/{job_id}/stop", status_code=202)
    def stop_announcement_flash(job_id: str):
        if announcement_update is None:
            raise HTTPException(503, "ANNOUNCEMENT_FLASH_UNAVAILABLE")
        def stop():
            value = announcement_update.stop(job_id)
            return envelope(value["state"], value)
        return _safe_errors(stop)

    @router.post("/announcement-flash/resume", status_code=202)
    def resume_announcement_flash(payload: AnnouncementFlashResumeRequest):
        if announcement_update is None:
            raise HTTPException(503, "ANNOUNCEMENT_FLASH_UNAVAILABLE")
        def resume():
            job = announcement_update.start_resume(
                payload.target_date, payload.source_job_id,
                payload.source_input_sha256, payload.source_progress_sha256,
                payload.source_queue_state_sha256, payload.resume_action)
            return envelope("QUEUED" if job.state.value == "QUEUED" else job.state.value, {
                "job_id": job.job_id,
                "source_job_id": payload.source_job_id,
                "resume_action": payload.resume_action,
                "target_date": job.context.target_date,
                "step": job.step,
                "status_url": f"{PREFIX}/announcement-flash?target_date={job.context.target_date}",
            })
        return _safe_errors(resume)

    @router.get("/mapping-catalog")
    def read_us_hk_mapping_catalog(
        q: str | None = Query(None, max_length=128),
        research_use: str | None = Query(None, pattern="^(PENDING_REVIEW|CONDITIONAL_OBSERVATION|BACKGROUND_HISTORICAL|EXCLUDED_CURRENT)$"),
        offset: int = Query(0, ge=0),
        limit: int = Query(25, ge=1, le=200),
    ):
        def read():
            try:
                data = _US_MAPPING_CATALOG_STORE.search(
                    US_MAPPING_CATALOG_PATH, US_MAPPING_REVIEW_OVERLAY_PATH, q,
                    offset=offset, limit=limit, research_use=research_use)
            except CatalogValidationError as exc:
                raise HTTPException(503, "US_HK_MAPPING_CATALOG_INVALID") from exc
            return envelope("STRUCTURE_VALID", data, [
                "SOURCE_FACTS_NOT_INDEPENDENTLY_VERIFIED",
                "PREDICTION_UNTESTED",
                "HISTORICAL_PIT_NOT_VALIDATED",
            ])
        return _safe_errors(read)

    @router.get("/hk-history")
    def read_hk_history(
        symbol: str = Query(..., pattern=r"^HK\.[0-9]{5}$"),
        start: str = Query(...),
        end: str = Query(...),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
        mode: Literal["usable", "audit"] = Query("usable"),
        fields: str = Query("open,high,low,close,amount,trade", max_length=64),
    ):
        if not fields or any(field not in ("open","high","low","close","amount","trade") for field in fields.split(",")):
            raise HTTPException(422, "FIELDS_INVALID")
        if int(symbol[3:]) < 1:
            raise HTTPException(422, "SYMBOL_INVALID")
        if re.fullmatch(r"[0-9]{8}", start) is None or re.fullmatch(r"[0-9]{8}", end) is None:
            raise HTTPException(422, "DATE_INVALID")
        start_day = _date(start)
        end_day = _date(end)

        def read():
            history = OwnedHKResearchHistory.from_shared_root(service.config.shared_root)
            data = history.query_union(
                symbol,
                start_day,
                end_day,
                offset=offset,
                limit=limit,
                mode=mode, required_fields=tuple(fields.split(",")),
            )
            return envelope("READY", _public(data), [
                "RESEARCH_ONLY_RAW_HISTORY",
                "RAW_UNITS_UNKNOWN",
                "CURRENCY_BASIS_UNKNOWN",
                "ADJUSTMENT_BASIS_UNKNOWN",
                "PIT_SAFETY_UNKNOWN",
                "SCORING_DISABLED",
            ])
        return _safe_errors(read)

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
            names = saved_names(snap,service.config.shared_root)
            stocks = [display_stock(stock,names) for stock in snap.stocks]
            if decision:
                stocks = [s for s in stocks if s['decision'] == decision.value]
            if lane:
                stocks = [s for s in stocks if lane.value in s['lane_decisions']]
            if q:
                term = q.casefold()
                stocks = [s for s in stocks if term in s['symbol'].casefold() or term in (s.get('name') or "").casefold()]
            meta=snap.model_dump(mode="json")
            meta.pop("stocks",None)
            meta["lanes"]=[{"lane":l.lane.value,"state":l.state.value,
                            "coverage":l.coverage.model_dump(mode="json"),"rows_count":len(l.rows),
                            "input_sha256":l.input_sha256,"gaps":l.gaps} for l in snap.lanes]
            return envelope("PARTIAL" if snap.gaps else "READY", {
                "snapshot": _public(meta),
                "stocks": _public(stocks[offset:offset+limit]),
                "display_projection":{"display_only":True,"snapshot_hash_basis":"ORIGINAL_SAVED_SNAPSHOT"},
                "us_mapping_summary":_public(us_summary(snap,names)),
                "counts": snap.counts.model_dump(mode="json"),
                "versions":versions,"pagination":{"total":len(stocks),"offset":offset,"limit":limit}},snap.gaps)
        return _safe_errors(read)

    @router.get("/days/{date}/recommendations/{lane}")
    def read_recommendations(date: str, lane: Literal['US_MAPPING','OVERSOLD'],
                             phase: Phase | None = None, run_id: str | None = None,
                             offset: int = Query(0,ge=0),limit: int = Query(50,ge=1,le=200),
                             decision: Decision | None = None,q: str | None = Query(None,max_length=128),
                             view: Literal['compact','diagnostics'] | None = None,
                             symbol: str | None = Query(None,pattern=r'^HK\.[0-9]{5}$'),
                             relationship_offset: int = Query(0,ge=0),
                             relationship_limit: int = Query(50,ge=1,le=200)):
        day=_date(date)
        def read():
            snap=service.store.get_plan(day,phase.value if phase else None,run_id)
            versions=[_index(p) for p in service.store.list_plans(day)]
            if snap is None:return envelope('NOT_RUN',dict(snapshot=None,stocks=[],counts=None,versions=versions,pagination=dict(total=0,offset=offset,limit=limit)),['NO_SAVED_PLAN'])
            names=saved_names(snap,service.config.shared_root)
            saved_lane=next((l for l in snap.lanes if l.lane.value==lane),None)
            industry_default=(lane=='US_MAPPING' and saved_lane and saved_lane.selection
                and saved_lane.selection.listing_mode=='INDUSTRY_MATCH')
            if view or industry_default:
                projection=selection_view(snap,lane,names,view=view or 'compact',offset=offset,limit=limit,
                    decision=decision.value if decision else None,q=q,symbol=symbol,
                    relationship_offset=relationship_offset,relationship_limit=relationship_limit)
                if projection is None:return envelope('NOT_RUN',dict(snapshot=None,stocks=[],counts=None,versions=versions,pagination=dict(total=0,offset=offset,limit=limit)),['LANE_NOT_SAVED'])
                projection['versions']=versions
                return envelope(projection['lane_state'],_public(projection),next(l.gaps for l in snap.lanes if l.lane.value==lane))
            projection=canonical_lane_projection(snap,lane,names,decision.value if decision else None,q)
            meta=snap.model_dump(mode='json');meta.pop('stocks',None)
            meta['lanes']=[dict(lane=l.lane.value,state=l.state.value,coverage=l.coverage.model_dump(mode='json'),rows_count=len(l.rows),gaps=l.gaps) for l in snap.lanes]
            if projection is None:return envelope('NOT_RUN',_public(dict(snapshot=meta,stocks=[],counts=None,versions=versions,pagination=dict(total=0,offset=offset,limit=limit))),['LANE_NOT_SAVED'])
            total=len(projection['stocks']);projection['stocks']=projection['stocks'][offset:offset+limit]
            projection['recommendation_counts']={name:(value['counts'] if (value:=canonical_lane_projection(snap,name,names)) is not None else None) for name in ['US_MAPPING','OVERSOLD']}
            projection.update(snapshot=meta,versions=versions,pagination=dict(total=total,offset=offset,limit=limit),us_mapping_summary=us_summary(snap,names) if lane=='US_MAPPING' else None)
            return envelope(projection['lane_state'],_public(projection),next(l.gaps for l in snap.lanes if l.lane.value==lane))
        return _safe_errors(read)

    @router.get("/stocks/{symbol}")
    def read_stock(symbol: str, date: str, run_id: str,
                   lane: Literal['US_MAPPING','OVERSOLD'] | None = None,row_id: str | None = None):
        day = _date(date)
        if re.fullmatch(r"HK\.[0-9]{5}",symbol) is None:raise HTTPException(422,"SYMBOL_INVALID")

        def read():
            snap = service.store.get_plan(day, run_id=run_id)
            if not snap:
                raise _not_found()
            names=saved_names(snap,service.config.shared_root)
            item = next((s for s in snap.stocks if s.symbol == symbol),None)
            if item is None and not lane:
                raise _not_found()
            selected=None
            if lane:
                chosen=next((l for l in snap.lanes if l.lane.value==lane),None)
                if chosen is None or not row_id or re.fullmatch(re.escape(lane)+r':[0-9]+',row_id) is None:raise HTTPException(422,'LANE_ROW_IDENTITY_INVALID')
                index=int(row_id.split(':')[1])
                if index>=len(chosen.rows) or chosen.rows[index].get('symbol')!=symbol:raise HTTPException(422,'LANE_ROW_IDENTITY_INVALID')
                selected=lane_stock(snap,chosen,index,names)
            details=[{"lane":l.lane.value,"rows":[display_stock(r,names) for r in l.rows if r.get("symbol")==symbol],
                      "evidence_refs":[e.model_dump(mode="json") for e in l.evidence_refs if e.evidence_id in (selected['evidence_ids'] if selected else item.evidence_ids)]}
                     for l in snap.lanes if not lane or l.lane.value==lane]
            if selected and not (lane == 'US_MAPPING' and snap.context.rules_version == US_FACTOR_RULES_VERSION):
                details[0]['rows']=[chosen.rows[index]]
            return envelope("READY", _public({"plan_run_id":snap.run_id,"stock":selected or display_stock(item,saved_names(snap,service.config.shared_root)),
                                               "recommendation_lane":lane,
                                               "display_projection":{"display_only":True,"snapshot_hash_basis":"ORIGINAL_SAVED_SNAPSHOT"},
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
            existing = service.jobs.get(id)
            scope = getattr(existing.context, "scope_refs", {})
            operation = scope.get("capture_operation") if isinstance(scope, dict) else None
            if isinstance(operation, str) and operation.startswith("ANNOUNCEMENT_FLASH"):
                raise JobConflict("ANNOUNCEMENT_FLASH_RESUME_REQUIRED")
            record = service.retry(id)
            return envelope(record.state.value,{"job_id":record.job_id,"run_id":record.run_id,
                             "status_url":f"{PREFIX}/runs/{record.job_id}"})
        return _safe_errors(run)

    return router

