"""Asynchronous NEXT_DAY owner wait and existing TDX61 supplement orchestration."""
from __future__ import annotations

import os
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .contracts import HK, JobState, Lane, LaneState, Phase, digest, validate_date

MAX_CAPTURE_ATTEMPTS=3
MAX_JOB_ATTEMPTS=3
RETRY_DELAYS=(60,300,900)
RETRY_PROBE_SECONDS=900
TERMINAL_STATES={"SUCCEEDED","PARTIAL_TERMINAL","OWNER_READINESS_EXPIRED"}
_CLASSIFIER_MIGRATION_ID="tdxpy-response-header-recv-fails-20261016-r1"
_CLASSIFIER_MIGRATION_SOURCE={
    "source_hk_session":"20261015",
    "target_date":"20261016",
    "job_id":"0c72d7ade78249d280b03418e71db681",
    "run_id":"0c72d7ade78249d280b03418e71db681",
    "capture_run_id":"9780a44c5cb6d6f02137d35c",
    "capture_manifest_sha256":"a4ee2b1fc23e85650a0937355881c6c54b3557c219d69bb27ec5919cc1b0d68f",
    "tdxpy_manifest_sha256":"a4ee2b1fc23e85650a0937355881c6c54b3557c219d69bb27ec5919cc1b0d68f",
    "panel_manifest_sha256":"bf80f6869862c9363f132d8ca0b134e613d919bc0441b52550efcc417726fba0",
    "master_manifest_sha256":"57e15f3cd79535ea7d566a2b1f560692b148ef932b72d8fa14c662ef853b2898",
    "parent_signature":"755903e3fdba1227a157e5329bb728f1853ade1603da1cb8f1bf9ba8dbe5f0f8",
    "capture_attempts":1,
    "job_attempts":1,
}


def _now():
    return datetime.now(HK)


def _iso(value):
    return value.astimezone(HK).isoformat()


def _parse(value):
    return datetime.fromisoformat(value) if value else None


def _failure_code(error):
    message=str(error)
    if isinstance(error,ValueError) and message.isidentifier():
        return message
    return type(error).__name__.upper()


def _is_transport_error(error_type,error):
    from upstreams.v3_shared_data.shared_data.hk_daily_supplement import is_tdxpy_transport_error
    return is_tdxpy_transport_error(error_type,error)


def _retryable_partial_transport(evidence):
    """Only classify transport evidence attached to unresolved owner records."""
    records=evidence.get("records",[])
    unresolved=[record for record in records if record.get("status")!="READY"]
    if not unresolved:return []
    found=[]
    for record in unresolved:
        errors=record.get("errors",[])
        if not isinstance(errors,list):continue
        for error in errors:
            if not isinstance(error,dict):continue
            if _is_transport_error(error.get("error_type"),error.get("error")):
                found.append(dict(code=record.get("code"),endpoint=error.get("endpoint"),
                    error_type=str(error.get("error_type"))))
    # A failed catalogue page can leave a valid, partial catalogue in the owner
    # cache. Associate its transport error with the unresolved rows; the owner
    # refresh path below is responsible for making that cache retryable.
    unresolved_codes={record.get("code") for record in unresolved}
    unresolved_endpoints={error.get("endpoint") for record in unresolved for error in record.get("errors",[])
        if isinstance(error,dict)}
    refresh_by_endpoint={item.get("endpoint"):item for item in evidence.get("catalogue_cache_refreshes",[])}
    for catalogue in evidence.get("catalogues",[]):
        if catalogue.get("endpoint") not in unresolved_endpoints:continue
        refresh=refresh_by_endpoint.get(catalogue.get("endpoint"))
        if refresh:
            status=refresh.get("status")
            refresh_error_type=refresh.get("error_type",refresh.get("refreshed_error_type"))
            refresh_error=refresh.get("error",refresh.get("refreshed_error"))
            if status in {"RECOVERED","PARTIAL_REFRESHED_STABLE"}:
                continue
            if status in {"FAILED","PARTIAL_NOT_SUPERSET_RETAINED"}:
                if not _is_transport_error(refresh_error_type,refresh_error):
                    continue
                found.append(dict(code=",".join(sorted(unresolved_codes)),endpoint=catalogue.get("endpoint"),
                    error_type=str(refresh_error_type),scope="CATALOGUE_REFRESH"))
                continue
        for gap in catalogue.get("coverage_gaps",[]):
            failure=gap.get("error") if gap.get("code")=="TDXPY_CATALOGUE_CAPTURE_ERROR" else None
            if isinstance(failure,dict) and _is_transport_error(failure.get("error_type"),failure.get("error")):
                found.append(dict(code=",".join(sorted(unresolved_codes)),endpoint=catalogue.get("endpoint"),
                    error_type=str(failure.get("error_type")),scope="CATALOGUE"))
    for error in evidence.get("failed_catalogues",[]):
        if error.get("endpoint") not in unresolved_endpoints:continue
        if _is_transport_error(error.get("error_type"),error.get("error")):
            found.append(dict(code=",".join(sorted(unresolved_codes)),endpoint=error.get("endpoint"),
                error_type=str(error.get("error_type")),scope="CATALOGUE"))
    unique={ (item.get("code"),item.get("endpoint"),item.get("error_type"),item.get("scope")):item for item in found }
    return list(unique.values())


class OversoldDaily:
    """One per existing service; the scheduler tick only queues this background work."""
    def __init__(self,service,*,clock=None,capture=None,inspect_capture=None,max_capture_attempts=MAX_CAPTURE_ATTEMPTS,
                 max_job_attempts=MAX_JOB_ATTEMPTS):
        self.service=service
        self.clock=clock or _now
        self.capture=capture or self._capture_owner
        self.inspect_capture=inspect_capture or self._inspect_capture
        self.max_capture_attempts=max_capture_attempts
        self.max_job_attempts=max_job_attempts
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix="mwb-oversold-daily")
        self.guard=threading.RLock()
        self.futures={}

    @staticmethod
    def cursor_key(source_day,target_date):
        validate_date(source_day);validate_date(target_date)
        return f"oversold_daily_{source_day}_{target_date}"

    def _write(self,key,value):
        with self.service.store.lock("oversold-daily-state:"+key):
            current=self.service.store.cursor(key) or {}
            current.update(value)
            self.service.store.set_cursor(key,current)
            return current

    def _read(self,key):
        return self.service.store.cursor(key) or {}

    def _schedule(self,key,source_day,target_date,at,state):
        state=dict(state)
        exhausted_probe=state.get("state")=="RETRY_EXHAUSTED"
        state.update(state="RUNNING",operation="PREFLIGHT",pid=os.getpid(),worker_started_at=_iso(self.clock()),
            last_error=None,next_retry_at=None,check_count=state.get("check_count",0)+1,
            exhausted_probe=exhausted_probe)
        self.service.store.set_cursor(key,state)
        future=self.pool.submit(self._attempt,key,source_day,target_date)
        self.futures[key]=future
        return {"state":"RUNNING","cursor_key":key}

    def tick(self,*,source_day,target_date,at=None):
        """Queue at most one exact-source-date task; return immediately to scheduler."""
        validate_date(source_day);validate_date(target_date)
        instant=at or self.clock()
        if instant.tzinfo is None or instant.utcoffset() is None:raise ValueError("OVERSOLD_DAILY_TIMEZONE_REQUIRED")
        key=self.cursor_key(source_day,target_date)
        with self.guard,self.service.store.lock("oversold-daily-claim:"+key):
            state=self._read(key)
            if state and (state.get("source_hk_session")!=source_day or state.get("target_date")!=target_date):
                return {"state":"CURSOR_IDENTITY_MISMATCH","cursor_key":key}
            if state.get("state") in TERMINAL_STATES:
                if self._classifier_migration_eligible(state,source_day,target_date):
                    state.update(state="RETRY_WAIT",operation=None,retry_operation="CAPTURE",
                        next_retry_at=_iso(instant),classifier_migration_id=_CLASSIFIER_MIGRATION_ID,
                        classifier_migration_attempts=1,classifier_migration_source_verified=False,
                        classifier_migration_started_at=_iso(instant),
                        last_error="TDXPY_TRANSPORT_CLASSIFIER_MIGRATION")
                    self.service.store.set_cursor(key,state)
                else:
                    return {"state":state["state"],"cursor_key":key}
            if state.get("state")=="JOB_PENDING":
                state=self._reconcile_job(key,state)
                if state.get("state") in TERMINAL_STATES or state.get("state")=="JOB_PENDING":
                    return {"state":state["state"],"cursor_key":key}
            if state.get("state")=="RUNNING":
                pid=state.get("pid")
                if isinstance(pid,int) and self.service.store._pid_alive(pid):
                    return {"state":"RUNNING","cursor_key":key}
                state.update(state="RETRY_WAIT",operation=None,pid=None,last_error="WORKER_PROCESS_INTERRUPTED",
                    next_retry_at=_iso(instant))
                self.service.store.set_cursor(key,state)
            if state.get("state")=="RETRY_WAIT":
                op=state.get("retry_operation")
                if op=="CAPTURE" and state.get("capture_attempts",0)>=self.max_capture_attempts:
                    state.update(state="RETRY_EXHAUSTED",next_retry_at=None,
                        next_probe_at=_iso(instant+timedelta(seconds=RETRY_PROBE_SECONDS)))
                    self.service.store.set_cursor(key,state)
                    return {"state":"RETRY_EXHAUSTED","cursor_key":key}
                if op=="JOB" and state.get("job_attempts",0)>=self.max_job_attempts:
                    state.update(state="RETRY_EXHAUSTED",next_retry_at=None,
                        next_probe_at=_iso(instant+timedelta(seconds=RETRY_PROBE_SECONDS)))
                    self.service.store.set_cursor(key,state)
                    return {"state":"RETRY_EXHAUSTED","cursor_key":key}
                if op=="PREFLIGHT" and state.get("preflight_failures",0)>=self.max_job_attempts:
                    state.update(state="RETRY_EXHAUSTED",next_retry_at=None,
                        next_probe_at=_iso(instant+timedelta(seconds=RETRY_PROBE_SECONDS)))
                    self.service.store.set_cursor(key,state)
                    return {"state":"RETRY_EXHAUSTED","cursor_key":key}
            next_retry=_parse(state.get("next_retry_at"))
            if next_retry and instant.astimezone(HK)<next_retry.astimezone(HK):
                return {"state":state.get("state","RETRY_WAIT"),"cursor_key":key}
            if state.get("state")=="RETRY_EXHAUSTED":
                next_probe=_parse(state.get("next_probe_at"))
                if next_probe and instant.astimezone(HK)<next_probe.astimezone(HK):
                    return {"state":"RETRY_EXHAUSTED","cursor_key":key}
            if not state:
                state={"schema_version":"v4.manager_workbench.oversold_daily.v1",
                    "source_hk_session":source_day,"target_date":target_date,
                    "capture_attempts":0,"job_attempts":0,"preflight_failures":0,"check_count":0}
            return self._schedule(key,source_day,target_date,instant,state)

    @staticmethod
    def _classifier_migration_eligible(state,source_day,target_date):
        if (source_day!=_CLASSIFIER_MIGRATION_SOURCE["source_hk_session"]
                or target_date!=_CLASSIFIER_MIGRATION_SOURCE["target_date"]
                or state.get("state")!="PARTIAL_TERMINAL"
                or state.get("terminal_reason")!="STABLE_OWNER_GAPS_RETAINED"
                or state.get("capture_evidence_disposition")!="PARTIAL_SUBMITTED_NO_RETRYABLE_TRANSPORT"
                or state.get("capture_retryable_error_count")!=0
                or state.get("classifier_migration_attempts",0)!=0):
            return False
        return all(state.get(key)==value for key,value in _CLASSIFIER_MIGRATION_SOURCE.items())

    def _reconcile_job(self,key,state):
        job=self.service.store.get_job(state.get("job_id",""))
        if job is None:
            return self._retry_state(key,state,"JOB","JOB_RECEIPT_MISSING")
        if job.state in (JobState.QUEUED,JobState.RUNNING):return state
        try:
            plan=self.service.store.read_plan(job.run_id)
            lane=next((item for item in plan.lanes if item.lane==Lane.OVERSOLD),None)
        except (KeyError,ValueError):
            lane=None
        if job.state in (JobState.SUCCEEDED,JobState.PARTIAL) and lane is not None:
            if lane.state==LaneState.PARTIAL:
                return self._write(key,dict(state="PARTIAL_TERMINAL",operation="DONE",pid=None,
                    finished_at=job.finished_at,run_id=plan.run_id,lane_state=lane.state.value,
                    terminal_reason="STABLE_OWNER_GAPS_RETAINED"))
            if lane.state in (LaneState.READY,LaneState.READY_EMPTY,LaneState.NOT_APPLICABLE):
                return self._write(key,dict(state="SUCCEEDED",operation="DONE",pid=None,
                    finished_at=job.finished_at,run_id=plan.run_id,lane_state=lane.state.value))
        attempts=state.get("job_attempts",0)
        if attempts>=self.max_job_attempts:
            return self._write(key,dict(state="RETRY_EXHAUSTED",operation="DONE",pid=None,
                finished_at=job.finished_at,last_error=job.failure_code or "OVERSOLD_LANE_NOT_TERMINAL",
                retry_operation="JOB",next_probe_at=_iso(self.clock()+timedelta(seconds=RETRY_PROBE_SECONDS))))
        return self._retry_state(key,state,"JOB",job.failure_code or "OVERSOLD_LANE_NOT_TERMINAL")

    def _retry_state(self,key,state,operation,reason):
        count=state.get("capture_attempts",0) if operation=="CAPTURE" else state.get("job_attempts",0)
        delay=RETRY_DELAYS[min(max(count-1,0),len(RETRY_DELAYS)-1)]
        next_retry=self.clock()+timedelta(seconds=delay)
        return self._write(key,dict(state="RETRY_WAIT",operation=None,retry_operation=operation,pid=None,
            last_error=reason,next_retry_at=_iso(next_retry)))

    def _inspect_capture(self,source_day,context,panel_pin,master_pin,capture_pin):
        from upstreams.v3_shared_data.shared_data.hk_daily_supplement import (
            _read_master_identity,_read_panel_identity,read_tdxpy_window_supplement,
        )
        from upstreams.v3_shared_data.shared_data.paths import resolve_under

        root=Path(self.service.config.shared_root).resolve()
        panel_identity=_read_panel_identity(root,source_day,
            manifest_relative=panel_pin["manifest_relative"],manifest_sha256=panel_pin["manifest_sha256"])
        master_identity,codes=_read_master_identity(root,source_day)
        if (panel_identity["panel_manifest_relative"]!=panel_pin["manifest_relative"]
                or panel_identity["panel_manifest_sha256"]!=panel_pin["manifest_sha256"]
                or master_identity["manifest_relative"]!=master_pin["manifest_relative"]
                or master_identity["manifest_sha256"]!=master_pin["manifest_sha256"]):
            raise ValueError("TDXPY_CAPTURE_PARENT_BINDING_MISMATCH")
        manifest,records=read_tdxpy_window_supplement(capture_pin,target_date=source_day,
            cutoff=capture_pin["available_at"],expected_panel_sha=panel_identity["panel_sha256"],
            expected_master_sha=master_identity["artifact_sha256"],expected_codes=codes,
            expected_panel_manifest_sha=panel_identity["panel_manifest_sha256"],
            expected_master_manifest_sha=master_identity["manifest_sha256"])
        if (manifest.get("capture_scope")!="PANEL_GAPS"
                or manifest.get("run_id")!=capture_pin.get("run_id")
                or manifest.get("available_at")!=capture_pin.get("available_at")):
            raise ValueError("TDXPY_CAPTURE_RETURN_BINDING_MISMATCH")
        raw_path=resolve_under(Path(capture_pin["source_local_path"]).resolve(),capture_pin["raw_relative"])
        raw_bytes=raw_path.read_bytes()
        if hashlib.sha256(raw_bytes).hexdigest()!=capture_pin.get("raw_sha256"):
            raise ValueError("TDXPY_CAPTURE_RAW_SHA_MISMATCH")
        raw=json.loads(raw_bytes)
        return dict(manifest=manifest,records=records,catalogues=raw.get("catalogues",[]),
            failed_catalogues=raw.get("failed_catalogues",[]),
            catalogue_cache_refreshes=raw.get("catalogue_cache_refreshes",[]))

    def _verify_classifier_migration_source(self,source_day,target_date,context,panel_pin,master_pin,state):
        from upstreams.v3_shared_data.shared_data.paths import resolve_under

        expected=_CLASSIFIER_MIGRATION_SOURCE
        if (source_day!=expected["source_hk_session"] or target_date!=expected["target_date"]
                or state.get("parent_signature")!=expected["parent_signature"]
                or panel_pin.get("manifest_sha256")!=expected["panel_manifest_sha256"]
                or master_pin.get("manifest_sha256")!=expected["master_manifest_sha256"]
                or state.get("classifier_migration_id")!=_CLASSIFIER_MIGRATION_ID):
            raise ValueError("OVERSOLD_CLASSIFIER_MIGRATION_PARENT_MISMATCH")
        output=Path(self.service.config.shared_root).resolve()/"assets/hk_0_2/daily_supplements/tdxpy61"
        manifest_relative=f"runs/{source_day}/{expected['capture_run_id']}/manifest.json"
        manifest_path=resolve_under(output,manifest_relative)
        manifest_bytes=manifest_path.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest()!=expected["capture_manifest_sha256"]:
            raise ValueError("OVERSOLD_CLASSIFIER_MIGRATION_MANIFEST_SHA_MISMATCH")
        manifest=json.loads(manifest_bytes)
        if (manifest.get("run_id")!=expected["capture_run_id"]
                or manifest.get("target_date")!=source_day
                or manifest.get("capture_scope")!="PANEL_GAPS"):
            raise ValueError("OVERSOLD_CLASSIFIER_MIGRATION_MANIFEST_IDENTITY_INVALID")
        raw_relative=manifest.get("raw_relative")
        raw_bytes=resolve_under(output,raw_relative).read_bytes()
        raw_sha=hashlib.sha256(raw_bytes).hexdigest()
        if raw_sha!=manifest.get("raw_sha256"):
            raise ValueError("OVERSOLD_CLASSIFIER_MIGRATION_RAW_SHA_MISMATCH")
        pin=dict(source_local_path=str(output),manifest_relative=manifest_relative,
            manifest_sha256=expected["capture_manifest_sha256"],raw_relative=raw_relative,
            raw_sha256=raw_sha,run_id=manifest["run_id"],available_at=manifest["available_at"],
            target_date=manifest["target_date"])
        evidence=self.inspect_capture(source_day,context,panel_pin,master_pin,pin)
        if (evidence.get("manifest",{}).get("unassessed_count",0)<=0
                or not _retryable_partial_transport(evidence)):
            raise ValueError("OVERSOLD_CLASSIFIER_MIGRATION_TRANSPORT_EVIDENCE_MISSING")
        return True

    def _attempt(self,key,source_day,target_date):
        try:
            first_cutoff=self.clock()
            scope={"source_hk_session":source_day,"merge_phase_lanes":True,
                "oversold_daily_cursor_key":key}
            context=self.service.context(target_date,Phase.NEXT_DAY,trigger="SCHEDULED",cutoff=first_cutoff,
                lanes=[Lane.OVERSOLD],scope_refs=scope)
            if context.source_sessions.get("hk_price")!=source_day:
                raise ValueError("OVERSOLD_DAILY_SOURCE_SESSION_MISMATCH")
            bindings=context.scope_refs.get("owner_bindings",{})
            gaps=context.scope_refs.get("owner_binding_gaps",{})
            panel_pin=bindings.get("hk_panel")
            master_pin=bindings.get("security_master")
            parent_signature=digest({"panel_manifest_sha256":(panel_pin or {}).get("manifest_sha256"),
                "master_manifest_sha256":(master_pin or {}).get("manifest_sha256"),
                "tdxpy_manifest_sha256":((panel_pin or {}).get("tdxpy_history") or {}).get("manifest_sha256")})
            prior=self._read(key)
            if prior.get("classifier_migration_attempts")==1 and (not panel_pin or not master_pin):
                reason="EXACT_DATE_HK_PANEL_UNAVAILABLE" if not panel_pin else "EXACT_DATE_HK_MASTER_UNAVAILABLE"
                self._write(key,dict(state="WAITING_FOR_PANEL_MASTER",operation="WAITING",pid=None,
                    last_error=gaps.get("hk_panel" if not panel_pin else "security_master",reason),
                    checked_at=_iso(first_cutoff),next_retry_at=None))
                return
            if prior.get("classifier_migration_attempts")==1 and not prior.get("classifier_migration_source_verified"):
                try:
                    self._verify_classifier_migration_source(source_day,target_date,context,panel_pin,master_pin,
                        prior)
                except Exception as error:
                    self._write(key,dict(state="PARTIAL_TERMINAL",operation="DONE",pid=None,
                        terminal_reason="CLASSIFIER_MIGRATION_SOURCE_NOT_VERIFIED",
                        classifier_migration_source_verified=False,last_error=_failure_code(error)))
                    return
                self._write(key,dict(classifier_migration_source_verified=True,
                    classifier_migration_source_verified_at=_iso(self.clock())))
            if prior.get("exhausted_probe"):
                if parent_signature==prior.get("parent_signature"):
                    self._write(key,dict(state="RETRY_EXHAUSTED",operation="WAITING_FOR_PARENT_CHANGE",pid=None,
                        exhausted_probe=False,next_probe_at=_iso(self.clock()+timedelta(seconds=RETRY_PROBE_SECONDS))))
                    return
                self._write(key,dict(state="RUNNING",operation="PREFLIGHT",exhausted_probe=False,
                    parent_signature=parent_signature))
            else:
                self._write(key,dict(parent_signature=parent_signature,exhausted_probe=False))
            if not panel_pin or not master_pin:
                reason="EXACT_DATE_HK_PANEL_UNAVAILABLE" if not panel_pin else "EXACT_DATE_HK_MASTER_UNAVAILABLE"
                self._write(key,dict(state="WAITING_FOR_PANEL_MASTER",operation="WAITING",pid=None,
                    last_error=gaps.get("hk_panel" if not panel_pin else "security_master",reason),
                    checked_at=_iso(first_cutoff),next_retry_at=None))
                return
            self._write(key,dict(operation="CHECKING_PANEL_WINDOW",panel_manifest_sha256=panel_pin.get("manifest_sha256"),
                master_manifest_sha256=master_pin.get("manifest_sha256"),checked_at=_iso(first_cutoff)))
            gap_plan=self.service.adapters.panel_gap_plan(context)
            gap_codes=gap_plan.get("gap_codes")
            if not isinstance(gap_codes,list):raise ValueError("OVERSOLD_PANEL_GAP_PLAN_INVALID")
            capture_pin=None
            if gap_codes:
                with self.service.store.lock("oversold-daily-state:"+key):
                    state=self.service.store.cursor(key) or {}
                    attempts=state.get("capture_attempts",0)
                    if attempts>=self.max_capture_attempts:
                        state.update(state="RETRY_EXHAUSTED",operation="DONE",pid=None,
                            retry_operation="CAPTURE",last_error=state.get("last_error") or "TDXPY_RETRY_EXHAUSTED",
                            next_probe_at=_iso(self.clock()+timedelta(seconds=RETRY_PROBE_SECONDS)))
                        self.service.store.set_cursor(key,state)
                        return
                    state.update(state="RUNNING",operation="CAPTURING_TDXPY61",capture_attempts=attempts+1,
                        panel_gap_plan_sha256=digest(gap_plan))
                    self.service.store.set_cursor(key,state)
                capture_result=self.capture(source_day,context,gap_plan)
                if capture_result.get("status")=="NO_PANEL_GAPS":
                    gap_codes=[]
                else:
                    capture_pin=capture_result
                    evidence=self.inspect_capture(source_day,context,panel_pin,master_pin,capture_pin)
                    manifest=evidence.get("manifest",{})
                    retryable=_retryable_partial_transport(evidence) if manifest.get("unassessed_count",0)>0 else []
                    if retryable:
                        current=self._read(key)
                        attempts=current.get("capture_attempts",0)
                        disposition="PARTIAL_TRANSPORT_RETRY_PENDING" if attempts<self.max_capture_attempts else "PARTIAL_TRANSPORT_RETRIES_EXHAUSTED"
                        self._write(key,dict(capture_run_id=capture_pin.get("run_id"),
                            capture_manifest_sha256=capture_pin.get("manifest_sha256"),
                            capture_available_at=capture_pin.get("available_at"),
                            capture_evidence_disposition=disposition,
                            capture_retryable_error_count=len(retryable),
                            capture_retryable_endpoints=sorted({item.get("endpoint") for item in retryable if item.get("endpoint")})))
                        if attempts<self.max_capture_attempts:
                            self._retry_state(key,current,"CAPTURE","TDXPY_PARTIAL_TRANSPORT_GAPS")
                            return
                    elif manifest.get("unassessed_count",0)>0:
                        self._write(key,dict(capture_evidence_disposition="PARTIAL_SUBMITTED_NO_RETRYABLE_TRANSPORT",
                            capture_retryable_error_count=0,capture_retryable_endpoints=[]))
                    else:
                        self._write(key,dict(capture_evidence_disposition="COMPLETE",
                            capture_retryable_error_count=0,capture_retryable_endpoints=[]))
                self._write(key,dict(capture_run_id=(capture_pin or {}).get("run_id"),
                    capture_manifest_sha256=(capture_pin or {}).get("manifest_sha256"),
                    capture_available_at=(capture_pin or {}).get("available_at"),operation="REBINDING_AFTER_CAPTURE"))
            final_cutoff=self.clock()
            final_context=self.service.context(target_date,Phase.NEXT_DAY,trigger="SCHEDULED",cutoff=final_cutoff,
                lanes=[Lane.OVERSOLD],scope_refs=scope)
            if final_context.source_sessions.get("hk_price")!=source_day:
                raise ValueError("OVERSOLD_DAILY_SOURCE_SESSION_MISMATCH")
            final_bindings=final_context.scope_refs.get("owner_bindings",{})
            if not final_bindings.get("hk_panel") or not final_bindings.get("security_master"):
                self._write(key,dict(state="WAITING_FOR_PANEL_MASTER",operation="WAITING",pid=None,
                    last_error="EXACT_DATE_PARENT_CHANGED_DURING_TDX_CAPTURE",checked_at=_iso(final_cutoff)))
                return
            if gap_codes and not final_bindings.get("hk_panel",{}).get("tdxpy_history"):
                raise ValueError("TDXPY_EXACT_PARENT_MANIFEST_NOT_BOUND")
            final_plan_sha=None
            if gap_codes:
                final_plan=self.service.adapters.panel_gap_plan(final_context)
                final_plan_sha=digest(final_plan)
                # A changed panel/master invalidates the just-finished capture. Keep
                # the current run unsubmitted and re-evaluate against the new parents.
                final_pin=final_bindings["hk_panel"].get("tdxpy_history",{})
                if final_pin.get("manifest_sha256")!=(capture_pin or {}).get("manifest_sha256"):
                    raise ValueError("TDXPY_CAPTURE_PARENT_REVISION_CHANGED")
            final_scope=dict(final_context.scope_refs)
            final_scope.update(source_hk_session=source_day,merge_phase_lanes=True,
                oversold_daily_cursor_key=key,panel_gap_plan_sha256=final_plan_sha or digest(gap_plan))
            if final_bindings.get("hk_panel",{}).get("tdxpy_history"):
                final_scope["tdxpy_manifest_sha256"]=final_bindings["hk_panel"]["tdxpy_history"]["manifest_sha256"]
            state=self._read(key)
            job_attempts=state.get("job_attempts",0)
            if job_attempts>=self.max_job_attempts:
                self._write(key,dict(state="RETRY_EXHAUSTED",operation="DONE",pid=None,
                    retry_operation="JOB",last_error=state.get("last_error") or "JOB_RETRY_EXHAUSTED",
                    next_probe_at=_iso(self.clock()+timedelta(seconds=RETRY_PROBE_SECONDS))))
                return
            self._write(key,dict(state="RUNNING",operation="SUBMITTING_NEXT_DAY",job_attempts=job_attempts+1,
                cutoff=_iso(final_cutoff),panel_manifest_sha256=final_bindings["hk_panel"].get("manifest_sha256"),
                master_manifest_sha256=final_bindings["security_master"].get("manifest_sha256"),
                tdxpy_manifest_sha256=final_bindings.get("hk_panel",{}).get("tdxpy_history",{}).get("manifest_sha256")))
            job=self.service.submit(target_date,Phase.NEXT_DAY,trigger="SCHEDULED",lanes=[Lane.OVERSOLD],
                cutoff=final_cutoff,scope_refs=final_scope)
            self._write(key,dict(state="JOB_PENDING",operation="WAITING_FOR_JOB",pid=None,job_id=job.job_id,
                run_id=job.run_id,job_attempts=job_attempts+1,cutoff=_iso(final_cutoff)))
        except Exception as error:
            state=self._read(key)
            operation=state.get("operation")
            if operation=="CAPTURING_TDXPY61":
                self._retry_state(key,state,"CAPTURE",_failure_code(error))
            elif operation=="REBINDING_AFTER_CAPTURE":
                self._retry_state(key,state,"CAPTURE",_failure_code(error))
            elif operation=="SUBMITTING_NEXT_DAY":
                self._retry_state(key,state,"JOB",_failure_code(error))
            else:
                failures=state.get("preflight_failures",0)+1
                if failures>=self.max_job_attempts:
                    self._write(key,dict(state="RETRY_EXHAUSTED",operation="DONE",pid=None,
                        preflight_failures=failures,last_error=_failure_code(error),retry_operation="PREFLIGHT",
                        next_probe_at=_iso(self.clock()+timedelta(seconds=RETRY_PROBE_SECONDS))))
                else:
                    self._write(key,dict(state="RETRY_WAIT",operation=None,retry_operation="PREFLIGHT",pid=None,
                        preflight_failures=failures,last_error=_failure_code(error),
                        next_retry_at=_iso(self.clock()+timedelta(seconds=RETRY_DELAYS[failures-1]))))

    def _capture_owner(self,source_day,context,gap_plan):
        from upstreams.v3_shared_data.shared_data.hk_daily_supplement import capture_tdxpy_window_supplement
        def connector(endpoint):
            from pytdx.hq import TdxHq_API
            host,port=endpoint.rsplit(":",1)
            api=TdxHq_API(heartbeat=False,auto_retry=False,raise_exception=True)
            if not api.connect(host,int(port),time_out=2.0):
                try:api.disconnect()
                finally:raise ConnectionError("TDXPY_CONNECT_FAILED")
            return api
        panel=gap_plan["panel_identity"]
        return capture_tdxpy_window_supplement(self.service.config.shared_root,target_date=source_day,
            connector=connector,clock=lambda:datetime.now(timezone.utc),
            panel_binding=dict(manifest_relative=panel["panel_manifest_relative"],
                manifest_sha256=panel["panel_manifest_sha256"]),panel_gap_plan=gap_plan)

    def stop(self):
        self.pool.shutdown(wait=True)
