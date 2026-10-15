from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import os
import threading
from types import SimpleNamespace

from v4.manager_workbench.contracts import (
    HK, Counts, JobState, Lane, LaneResult, LaneState, Phase, RunContext, seal_snapshot,
)
from v4.manager_workbench.oversold_daily import OversoldDaily
from v4.manager_workbench.scheduler import tick
from v4.manager_workbench.service import ManagerService
from v4.manager_workbench.store import WorkbenchStore


SOURCE="20261016"
TARGET="20261019"


class MemoryStore:
    def __init__(self):
        self.values={}
        self.jobs={}
        self.plans={}
        self.guard=threading.RLock()
        self.changed=threading.Event()

    @contextmanager
    def lock(self,key):
        with self.guard:yield

    def cursor(self,key):
        value=self.values.get(key)
        return dict(value) if value else None

    def set_cursor(self,key,value):
        self.values[key]=dict(value)
        self.changed.set()

    @staticmethod
    def _pid_alive(pid):
        return pid==os.getpid()

    def get_job(self,job_id):return self.jobs.get(job_id)

    def read_plan(self,run_id):
        if run_id not in self.plans:raise KeyError(run_id)
        return self.plans[run_id]


class FakeClock:
    def __init__(self,value):self.value=value;self.guard=threading.Lock()
    def __call__(self):
        with self.guard:
            value=self.value
            self.value+=timedelta(seconds=1)
            return value
    def set(self,value):
        with self.guard:self.value=value


class DailyService:
    def __init__(self,store,*,ready=False,gap_codes=None,submit_block=None):
        self.store=store
        self.ready=ready
        self.gap_codes=gap_codes or []
        self.submissions=[]
        self.submit_block=submit_block
        self.tdx_pin=None
        self.adapters=SimpleNamespace(panel_gap_plan=self.panel_gap_plan)

    def context(self,target_date,phase,*,trigger,cutoff,lanes,scope_refs=None):
        bindings={}
        gaps={}
        if self.ready:
            bindings={"hk_panel":{"manifest_sha256":"p"*64,"available_at":cutoff.isoformat()},
                "security_master":{"manifest_sha256":"m"*64,"captured_at":cutoff.isoformat()}}
            if self.tdx_pin:bindings["hk_panel"]["tdxpy_history"]={"manifest_sha256":self.tdx_pin}
        else:
            gaps={"hk_panel":"EXACT_DATE_HK_PANEL_UNAVAILABLE"}
        refs=dict(scope_refs or {})
        refs.update(requested_lanes=[lane.value for lane in lanes],owner_bindings=bindings,owner_binding_gaps=gaps)
        return RunContext(target_date=target_date,phase=phase,cutoff=cutoff.isoformat(),trigger=trigger,
            source_sessions={"hk_price":SOURCE,"us":"20261015"},rules_version="TEST_RULES",scope_refs=refs)

    def panel_gap_plan(self,context):
        return {"gap_codes":list(self.gap_codes),"target_date":context.target_date,
            "cutoff":context.cutoff,"panel_identity":{"manifest_sha256":"p"*64}}

    def submit(self,target_date,phase,*,trigger,lanes,cutoff,scope_refs):
        if self.submit_block:self.submit_block.wait(2)
        job=SimpleNamespace(job_id=f"job-{len(self.submissions)+1}",run_id=f"run-{len(self.submissions)+1}",state=JobState.QUEUED)
        self.submissions.append({"target_date":target_date,"phase":phase,"trigger":trigger,
            "lanes":list(lanes),"cutoff":cutoff,"scope_refs":dict(scope_refs),"job":job})
        self.store.jobs[job.job_id]=job
        return job


def wait_for_state(store,key,wanted,timeout=2):
    import time
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=store.cursor(key) or {}
        if value.get("state")==wanted:return value
        store.changed.wait(.02)
        store.changed.clear()
    raise AssertionError(f"expected {wanted}, saw {store.cursor(key)}")


def test_nextday_other_lane_runs_at_1630_and_oversold_waits_separately():
    class Calendar:
        def is_hk_session(self,day):return day in {SOURCE,TARGET}
        def next_hk_session(self,day):return TARGET
        def session_state(self,day):return "HALF_TRADING_DAY_AM"

    class Store:
        def __init__(self):self.values={}
        def get_plan(self,*args):return None
        def cursor(self,key):return self.values.get(key)
        def set_cursor(self,key,value):self.values[key]=dict(value)

    class Driver:
        def __init__(self):self.calls=[]
        def tick(self,**kwargs):self.calls.append(kwargs);return {"state":"WAITING_FOR_PANEL_MASTER"}

    class Service:
        def __init__(self):
            self.config=SimpleNamespace(scheduled_lanes=[Lane.US_MAPPING,Lane.OVERSOLD])
            self.store=Store();self.oversold_daily=Driver();self.submissions=[];self.capture_jobs=None
        def freeze_preopen(self,*args,**kwargs):return SimpleNamespace(run_id="preopen")
        def submit(self,target,phase,**kwargs):
            self.submissions.append((target,phase,kwargs))
            return SimpleNamespace(run_id="us-run",job_id="us-job")

    service=Service()
    instant=datetime(2026,10,16,16,30,tzinfo=HK)
    result=tick(service,calendar=Calendar(),stage_feed=SimpleNamespace(completed_runs=lambda day:[]),at=instant)
    assert service.submissions[0][0:2]==(TARGET,Phase.NEXT_DAY)
    assert service.submissions[0][2]["lanes"]==[Lane.US_MAPPING]
    assert service.submissions[0][2]["scope_refs"]["merge_phase_lanes"] is True
    assert service.submissions[0][2]["cutoff"]==instant
    assert service.oversold_daily.calls==[{"source_day":SOURCE,"target_date":TARGET,"at":instant}]
    assert any(item.get("lane")=="OVERSOLD" and item.get("state")=="WAITING_FOR_PANEL_MASTER"
               for item in result["jobs"])


def test_scheduler_holiday_skips_and_weekend_next_session_is_calendar_owned():
    class Calendar:
        def is_hk_session(self,day):return day in {"20261016",TARGET}
        def next_hk_session(self,day):return TARGET
        def session_state(self,day):return "HALF_TRADING_DAY_AM"

    class Store:
        def get_plan(self,*args):return object()
        def cursor(self,key):return None
        def set_cursor(self,key,value):pass

    class Service:
        config=SimpleNamespace(scheduled_lanes=[Lane.US_MAPPING,Lane.OVERSOLD])
        store=Store();submissions=[];capture_jobs=None;oversold_daily=None
        def submit(self,target,phase,**kwargs):
            self.submissions.append((target,phase,kwargs));return SimpleNamespace(run_id="run",job_id="job")

    service=Service()
    calendar=Calendar()
    weekend=tick(service,calendar=calendar,stage_feed=SimpleNamespace(completed_runs=lambda day:[]),
        at=datetime(2026,10,17,16,30,tzinfo=HK))
    assert weekend["state"]=="NOT_APPLICABLE" and not service.submissions
    friday=tick(service,calendar=calendar,stage_feed=SimpleNamespace(completed_runs=lambda day:[]),
        at=datetime(2026,10,16,16,30,tzinfo=HK))
    assert friday["date"]=="20261016"
    assert service.submissions[0][0]==TARGET  # The authoritative calendar skips the weekend.


def test_daily_wait_is_not_a_done_cursor_and_uses_a_fresh_cutoff_when_ready():
    clock=FakeClock(datetime(2026,10,16,16,30,tzinfo=HK))
    store=MemoryStore();service=DailyService(store,ready=False)
    daily=OversoldDaily(service,clock=clock)
    key=daily.cursor_key(SOURCE,TARGET)
    try:
        assert daily.tick(source_day=SOURCE,target_date=TARGET,at=clock()) ["state"]=="RUNNING"
        wait_for_state(store,key,"WAITING_FOR_PANEL_MASTER")
        assert not service.submissions
        state=store.cursor(key)
        assert state["state"]!="SUCCEEDED" and state["state"]!="PARTIAL_TERMINAL"
        service.ready=True
        clock.set(datetime(2026,10,16,17,35,tzinfo=HK))
        assert daily.tick(source_day=SOURCE,target_date=TARGET,at=clock())["state"]=="RUNNING"
        state=wait_for_state(store,key,"JOB_PENDING")
        assert service.submissions[0]["cutoff"]>datetime(2026,10,16,16,30,tzinfo=HK)
        assert service.submissions[0]["target_date"]==TARGET
        assert service.submissions[0]["lanes"]==[Lane.OVERSOLD]
        assert service.submissions[0]["scope_refs"]["merge_phase_lanes"] is True
        assert service.submissions[0]["scope_refs"]["source_hk_session"]==SOURCE
        assert state["job_attempts"]==1
    finally:
        daily.stop()


def test_capture_failures_have_three_attempts_and_visible_exhaustion(monkeypatch):
    import v4.manager_workbench.oversold_daily as module
    monkeypatch.setattr(module,"RETRY_DELAYS",(0,))
    clock=FakeClock(datetime(2026,10,16,17,35,tzinfo=HK))
    store=MemoryStore();service=DailyService(store,ready=True,gap_codes=["HK.00001"])
    calls=[]
    def fail_capture(source,context,plan):
        calls.append((source,plan["gap_codes"]))
        raise ConnectionError("transient")
    daily=OversoldDaily(service,clock=clock,capture=fail_capture,max_capture_attempts=3)
    key=daily.cursor_key(SOURCE,TARGET)
    try:
        for count in range(1,4):
            daily.tick(source_day=SOURCE,target_date=TARGET,at=clock())
            state=wait_for_state(store,key,"RETRY_WAIT")
            assert state["capture_attempts"]==count
            state["next_retry_at"]=(clock.value-timedelta(seconds=1)).isoformat()
            store.set_cursor(key,state)
        assert daily.tick(source_day=SOURCE,target_date=TARGET,at=clock())["state"]=="RETRY_EXHAUSTED"
        assert len(calls)==3 and not service.submissions
        assert store.cursor(key)["last_error"]=="CONNECTIONERROR"
        assert store.cursor(key).get("finished_at") is None
        service.tdx_pin="e"*64
        service.gap_codes=[]
        clock.set(datetime(2026,10,16,18,0,tzinfo=HK))
        assert daily.tick(source_day=SOURCE,target_date=TARGET,at=clock())["state"]=="RUNNING"
        state=wait_for_state(store,key,"JOB_PENDING")
        assert state["capture_attempts"]==0 and len(service.submissions)==1
    finally:
        daily.stop()


def _capture_pin(service,index):
    manifest_sha=hex(index)[2:]*64
    service.tdx_pin=manifest_sha
    return dict(run_id=f"capture-{index}",manifest_sha256=manifest_sha,raw_sha256="f"*64,
        source_local_path="/tmp/fake-tdx",manifest_relative=f"runs/{SOURCE}/capture-{index}/manifest.json",
        raw_relative=f"runs/{SOURCE}/capture-{index}/raw_capture.json",available_at="2026-10-16T17:35:00+08:00",
        target_date=SOURCE)


def _capture_evidence(error_type=None,error=None):
    row={"code":"HK.00001","status":"UNASSESSED","errors":[] if error_type is None else [
        {"endpoint":"116.205.143.214:7727","error_type":error_type,"error":error}]}
    if error_type is None:row={"code":"HK.00001","status":"READY","errors":[]}
    return {"manifest":{"unassessed_count":0 if error_type is None else 1},"records":[row]}


def test_normal_return_partial_transport_gap_retries_before_submission(monkeypatch):
    import v4.manager_workbench.oversold_daily as module
    monkeypatch.setattr(module,"RETRY_DELAYS",(0,))
    clock=FakeClock(datetime(2026,10,16,17,35,tzinfo=HK))
    store=MemoryStore();service=DailyService(store,ready=True,gap_codes=["HK.00001"])
    captures=[]
    def capture(source,context,plan):
        pin=_capture_pin(service,len(captures)+1);captures.append(pin)
        return pin
    def inspect(source,context,panel,master,pin):
        return _capture_evidence("TimeoutError","timed out") if len(captures)==1 else _capture_evidence()
    daily=OversoldDaily(service,clock=clock,capture=capture,inspect_capture=inspect,max_capture_attempts=3)
    key=daily.cursor_key(SOURCE,TARGET)
    try:
        daily.tick(source_day=SOURCE,target_date=TARGET,at=clock())
        state=wait_for_state(store,key,"RETRY_WAIT")
        assert state["capture_attempts"]==1
        assert state["last_error"]=="TDXPY_PARTIAL_TRANSPORT_GAPS"
        assert state["capture_evidence_disposition"]=="PARTIAL_TRANSPORT_RETRY_PENDING"
        assert len(captures)==1 and not service.submissions
        state["next_retry_at"]=(clock.value-timedelta(seconds=1)).isoformat();store.set_cursor(key,state)
        daily.tick(source_day=SOURCE,target_date=TARGET,at=clock())
        state=wait_for_state(store,key,"JOB_PENDING")
        assert len(captures)==2 and len(service.submissions)==1
        assert service.submissions[0]["scope_refs"]["tdxpy_manifest_sha256"]==captures[1]["manifest_sha256"]
        assert state["capture_evidence_disposition"]=="COMPLETE"
    finally:
        daily.stop()


def test_stable_partial_quarantine_submits_without_capture_retry():
    clock=FakeClock(datetime(2026,10,16,17,35,tzinfo=HK))
    store=MemoryStore();service=DailyService(store,ready=True,gap_codes=["HK.00001"])
    captures=[]
    def capture(source,context,plan):
        pin=_capture_pin(service,len(captures)+1);captures.append(pin);return pin
    def inspect(source,context,panel,master,pin):
        return _capture_evidence("ValueError","TDXPY_EXACT_61_SESSION_INCOMPLETE")
    daily=OversoldDaily(service,clock=clock,capture=capture,inspect_capture=inspect,max_capture_attempts=3)
    key=daily.cursor_key(SOURCE,TARGET)
    try:
        daily.tick(source_day=SOURCE,target_date=TARGET,at=clock())
        state=wait_for_state(store,key,"JOB_PENDING")
        assert state["capture_attempts"]==1 and len(captures)==1
        assert state["capture_evidence_disposition"]=="PARTIAL_SUBMITTED_NO_RETRYABLE_TRANSPORT"
        assert len(service.submissions)==1
    finally:
        daily.stop()


def test_transport_partial_after_capture_exhaustion_is_submitted_and_retained(monkeypatch):
    import v4.manager_workbench.oversold_daily as module
    monkeypatch.setattr(module,"RETRY_DELAYS",(0,))
    clock=FakeClock(datetime(2026,10,16,17,35,tzinfo=HK))
    store=MemoryStore();service=DailyService(store,ready=True,gap_codes=["HK.00001"])
    captures=[]
    def capture(source,context,plan):
        pin=_capture_pin(service,len(captures)+1);captures.append(pin);return pin
    def inspect(source,context,panel,master,pin):
        return _capture_evidence("ConnectionError","transient")
    daily=OversoldDaily(service,clock=clock,capture=capture,inspect_capture=inspect,max_capture_attempts=2)
    key=daily.cursor_key(SOURCE,TARGET)
    try:
        daily.tick(source_day=SOURCE,target_date=TARGET,at=clock())
        state=wait_for_state(store,key,"RETRY_WAIT")
        state["next_retry_at"]=(clock.value-timedelta(seconds=1)).isoformat();store.set_cursor(key,state)
        daily.tick(source_day=SOURCE,target_date=TARGET,at=clock())
        state=wait_for_state(store,key,"JOB_PENDING")
        assert len(captures)==2 and len(service.submissions)==1
        assert state["capture_evidence_disposition"]=="PARTIAL_TRANSPORT_RETRIES_EXHAUSTED"
        assert state["capture_attempts"]==2
        job=service.submissions[0]["job"]
        job.state=JobState.PARTIAL;job.finished_at="2026-10-16T17:36:00+08:00"
        store.plans[job.run_id]=SimpleNamespace(run_id=job.run_id,
            lanes=[SimpleNamespace(lane=Lane.OVERSOLD,state=LaneState.PARTIAL)])
        assert daily.tick(source_day=SOURCE,target_date=TARGET,at=clock())["state"]=="PARTIAL_TERMINAL"
        assert store.cursor(key)["terminal_reason"]=="STABLE_OWNER_GAPS_RETAINED"
    finally:
        daily.stop()


def test_restart_recovers_dead_worker_claim_and_duplicate_tick_is_idempotent():
    clock=FakeClock(datetime(2026,10,16,17,35,tzinfo=HK))
    store=MemoryStore();service=DailyService(store,ready=True)
    daily=OversoldDaily(service,clock=clock)
    key=daily.cursor_key(SOURCE,TARGET)
    store.set_cursor(key,{"source_hk_session":SOURCE,"target_date":TARGET,"state":"RUNNING",
        "pid":99999999,"capture_attempts":0,"job_attempts":0,"preflight_failures":0,"check_count":1})
    try:
        daily.tick(source_day=SOURCE,target_date=TARGET,at=clock())
        wait_for_state(store,key,"JOB_PENDING")
        assert store.cursor(key)["last_error"] is None
        # A second scheduler tick sees the persisted job claim and never resubmits.
        assert daily.tick(source_day=SOURCE,target_date=TARGET,at=clock())["state"]=="JOB_PENDING"
        assert len(service.submissions)==1
    finally:
        daily.stop()


def test_concurrent_driver_instances_share_one_durable_claim():
    clock=FakeClock(datetime(2026,10,16,17,35,tzinfo=HK))
    store=MemoryStore();service=DailyService(store,ready=True)
    context_entered=threading.Event();release_context=threading.Event()
    original_context=service.context
    def blocked_context(*args,**kwargs):
        context_entered.set()
        assert release_context.wait(2)
        return original_context(*args,**kwargs)
    service.context=blocked_context
    first=OversoldDaily(service,clock=clock)
    second=OversoldDaily(service,clock=clock)
    key=first.cursor_key(SOURCE,TARGET)
    try:
        assert first.tick(source_day=SOURCE,target_date=TARGET,at=clock())['state']=="RUNNING"
        assert context_entered.wait(2)
        result=[]
        duplicate=threading.Thread(target=lambda:result.append(
            second.tick(source_day=SOURCE,target_date=TARGET,at=clock())))
        duplicate.start();duplicate.join(2)
        assert not duplicate.is_alive()
        assert result and result[0]['state']=="RUNNING"
        release_context.set()
        wait_for_state(store,key,"JOB_PENDING")
        assert len(service.submissions)==1
    finally:
        release_context.set()
        first.stop();second.stop()


def test_phase_pointer_merges_lane_results_without_rewriting_history(tmp_path):
    class Engines:
        @staticmethod
        def merge_decisions(context,lanes):return []

    service=object.__new__(ManagerService)
    service.engines=Engines()
    service.store=WorkbenchStore(tmp_path)

    def make_plan(run_id,lane,cutoff,fingerprint):
        context=RunContext(target_date=TARGET,phase=Phase.NEXT_DAY,cutoff=cutoff.isoformat(),trigger="SCHEDULED",
            source_sessions={"hk_price":SOURCE},rules_version="TEST_RULES",
            scope_refs={"requested_lanes":[lane.value],"source_hk_session":SOURCE,"merge_phase_lanes":True})
        result=LaneResult(lane=lane,state=LaneState.READY,rows=[],coverage={},input_sha256=("c" if lane==Lane.US_MAPPING else "d")*64,
            rules_version="TEST_RULES",run_id=run_id)
        return seal_snapshot({"context":context.model_dump(mode="json"),"run_id":run_id,
            "input_sha256":("a" if lane==Lane.US_MAPPING else "b")*64,
            "generated_at":cutoff.isoformat(),"available_at":cutoff.isoformat(),
            "lanes":[result.model_dump(mode="json")],"stocks":[],
            "counts":Counts(selected=0,watch=0,unassessed=0,observation_only=0,not_selected=0).model_dump(mode="json"),
            "changes":{"fingerprint":fingerprint},"review_refs":[],"gaps":[]})

    first=make_plan("us-run",Lane.US_MAPPING,datetime(2026,10,16,16,30,tzinfo=HK),"us-fp")
    second=make_plan("oversold-run",Lane.OVERSOLD,datetime(2026,10,16,17,35,tzinfo=HK),"oversold-fp")
    first_saved=service._commit_plan(first)
    historical_sha=service.store.read_plan("us-run").product_sha256
    latest=service._commit_plan(second)
    pointed=service.store.get_plan(TARGET,Phase.NEXT_DAY.value)
    assert pointed.run_id=="oversold-run"==latest.run_id
    assert {lane.lane for lane in pointed.lanes}=={Lane.US_MAPPING,Lane.OVERSOLD}
    assert {lane.run_id for lane in pointed.lanes}=={"oversold-run"}
    assert pointed.changes["phase_lane_sources"]=={"US_MAPPING":"us-run","OVERSOLD":"oversold-run"}
    assert service.store.read_plan("us-run").product_sha256==historical_sha
    assert first_saved.run_id=="us-run"

