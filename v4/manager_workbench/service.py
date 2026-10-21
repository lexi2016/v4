"""Injected A engine orchestration and immutable plan lifecycle."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from .config import WorkbenchConfig
from .contracts import (
    HK, Counts, Decision, InputBatch, JobRecord, JobState, Lane, LaneResult,
    LaneState, Phase, PlanSnapshot, ReviewSummary, RunContext, StockDecision,
    digest, seal_snapshot, validate_date,
)
from .jobs import JobConflict, JobCoordinator, StepFailure, now
from .executors.codex import AuditedExecutor, SemanticFailure
from .store import StorageConflict, StorageUnavailable, WorkbenchStore

ALL_LANES = tuple(Lane)


def validate_selected_evidence(snapshot):
    evidence = {e.evidence_id:e for lane in snapshot.lanes for e in lane.evidence_refs}
    cutoff = datetime.fromisoformat(snapshot.context.cutoff)
    for stock in snapshot.stocks:
        if stock.decision != Decision.SELECTED: continue
        if not stock.evidence_ids or any(eid not in evidence or evidence[eid].verification.value != "VERIFIED"
                or not evidence[eid].available_at or datetime.fromisoformat(evidence[eid].available_at) > cutoff
                for eid in stock.evidence_ids):
            raise ValueError("SELECTED_EVIDENCE_AFTER_CUTOFF_OR_UNKNOWN")


def count_rows(rows: list[StockDecision]) -> Counts:
    return Counts(
        selected=sum(s.decision == Decision.SELECTED for s in rows),
        watch=sum(s.decision == Decision.CONDITIONAL_WATCH for s in rows),
        unassessed=sum(s.decision == Decision.UNASSESSED for s in rows),
        observation_only=sum(s.decision == Decision.OBSERVATION_ONLY for s in rows),
        not_selected=sum(s.decision == Decision.NOT_SELECTED for s in rows),
    )


def sort_stocks(rows: list[StockDecision], lanes: list[LaneResult]) -> list[StockDecision]:
    available = {}
    for l in lanes:
        for e in l.evidence_refs:
            if e.verification.value == "VERIFIED" and e.available_at:
                available[e.evidence_id] = datetime.fromisoformat(e.available_at).timestamp()
    rank = {Decision.SELECTED: 0, Decision.CONDITIONAL_WATCH: 1,
            Decision.UNASSESSED: 2, Decision.OBSERVATION_ONLY: 3, Decision.NOT_SELECTED: 4}
    return sorted(rows, key=lambda s: (rank[s.decision],
                    -max((available[x] for x in s.evidence_ids if x in available), default=-1), s.symbol))


class ManagerService:
    def __init__(self, config: WorkbenchConfig, adapters: Any, engines: Any, executor: Any, *, capture_transport=None,capture_clock=None):
        self.config = config
        self.adapters = adapters
        self.engines = engines
        self.executor = executor
        self.store = WorkbenchStore(config.state_root)
        self.jobs = JobCoordinator(self.store, workers=config.workers)
        self.oversold_daily=None
        if config.scheduled_lanes is not None and Lane.OVERSOLD in config.scheduled_lanes:
            from .oversold_daily import OversoldDaily
            self.oversold_daily=OversoldDaily(self)
        self.capture_jobs=None
        if config.capture_enabled:
            from .inputs.capture_jobs import CaptureJobs
            self.capture_jobs=CaptureJobs(self,transport=capture_transport,clock=capture_clock)

    def context(self, target_date: str, phase: Phase, *, trigger: str,
                cutoff: datetime | None = None, lanes: list[Lane] | None = None,
                scope_refs: dict[str, Any] | None = None) -> RunContext:
        validate_date(target_date)
        ts = cutoff or datetime.now(HK)
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError("CUTOFF_TZ_REQUIRED")
        context = RunContext(target_date=target_date, phase=phase, cutoff=ts.astimezone(HK).isoformat(),
                          trigger=trigger, source_sessions={}, rules_version=self.config.rules_version,
                          scope_refs={**(scope_refs or {}), "requested_lanes": [p.value for p in (lanes or ALL_LANES)]})
        if hasattr(self.adapters, "prepare_context"):
            context = self.adapters.prepare_context(context)
        return context

    def submit(self, target_date: str, phase: Phase, *, trigger: str = "MANUAL",
               lanes: list[Lane] | None = None, cutoff: datetime | None = None,
               scope_refs: dict[str, Any] | None = None) -> JobRecord:
        context = self.context(target_date, phase, trigger=trigger, lanes=lanes, cutoff=cutoff, scope_refs=scope_refs)
        job=self.jobs.submit(context, self._work)
        if (self.capture_jobs and not context.scope_refs.get("capture_incremental")
                and Lane.ANNOUNCEMENT.value in context.scope_refs["requested_lanes"]
                and phase!=Phase.RETROSPECTIVE):
            capture=self.request_capture(context)
            if capture:
                # The research job remains the initial response; callers can
                # separately read the persisted acquisition progress.
                job.execution_refs.append({"kind":"capture_job","job_id":capture.job_id,
                    "status_url":"/api/v4/manager-workbench/runs/"+capture.job_id})
                self.store.save_job(job)
        return job

    def request_capture(self,context):
        if not self.capture_jobs:return None
        try:return self.capture_jobs.submit(context)
        except (OSError,ValueError) as exc:
            # Source failure cannot hold up or cancel an already submitted plan.
            self.capture_gap="CAPTURE_OWNER_UNAVAILABLE" if "EXCLUSIVE_OWNER" in str(exc) else "CAPTURE_BINDING_UNAVAILABLE"
            return None

    def stop(self):
        if self.capture_jobs:self.capture_jobs.stop()
        if getattr(self,"oversold_daily",None):self.oversold_daily.stop()
        self.jobs.stop()

    def _merge_phase_lane_snapshots(self, previous, incoming):
        if incoming.context.phase != Phase.NEXT_DAY:
            raise StorageConflict("PHASE_LANE_MERGE_PHASE_INVALID")
        if previous is not None and (previous.context.target_date!=incoming.context.target_date
                or previous.context.phase!=incoming.context.phase or previous.context.market!=incoming.context.market
                or previous.context.rules_version!=incoming.context.rules_version
                or previous.context.source_sessions.get("hk_price")!=incoming.context.source_sessions.get("hk_price")):
            raise StorageConflict("PHASE_LANE_MERGE_CONTEXT_MISMATCH")
        lanes={}
        sources={}
        inputs={}
        cutoffs={}
        sessions={}
        fingerprints={}
        requested=set(incoming.context.scope_refs.get("requested_lanes",[]))
        if previous is not None:
            requested.update(previous.context.scope_refs.get("requested_lanes",[]))
            previous_sources=previous.changes.get("phase_lane_sources",{})
            previous_inputs=previous.changes.get("phase_lane_inputs",{})
            previous_cutoffs=previous.changes.get("phase_lane_cutoffs",{})
            previous_sessions=previous.changes.get("phase_lane_source_sessions",{})
            previous_fingerprints=previous.changes.get("phase_lane_fingerprints",{})
            for lane in previous.lanes:
                lanes[lane.lane.value]=lane
                sources[lane.lane.value]=previous_sources.get(lane.lane.value,previous.run_id)
                inputs[lane.lane.value]=previous_inputs.get(lane.lane.value,lane.input_sha256)
                cutoffs[lane.lane.value]=previous_cutoffs.get(lane.lane.value,
                    previous.context.scope_refs.get("source_cutoff",previous.context.cutoff))
                sessions[lane.lane.value]=previous_sessions.get(lane.lane.value,previous.context.source_sessions)
                fingerprints[lane.lane.value]=previous_fingerprints.get(lane.lane.value,
                    previous.changes.get("fingerprint"))
        requested.update(lane.lane.value for lane in incoming.lanes)
        for lane in incoming.lanes:
            lanes[lane.lane.value]=lane
            sources[lane.lane.value]=incoming.changes.get("phase_lane_sources",{}).get(lane.lane.value,incoming.run_id)
            inputs[lane.lane.value]=lane.input_sha256
            cutoffs[lane.lane.value]=incoming.context.scope_refs.get("source_cutoff",incoming.context.cutoff)
            sessions[lane.lane.value]=incoming.context.source_sessions
            fingerprints[lane.lane.value]=incoming.changes.get("fingerprint")
        if previous is not None and previous.run_id==incoming.run_id:
            prior={lane.lane.value:lane for lane in previous.lanes}
            if all(name in prior and prior[name].input_sha256==lane.input_sha256
                   for name,lane in ((item.lane.value,item) for item in incoming.lanes)):
                return previous
            raise StorageConflict("PHASE_LANE_RUN_REUSE_CONFLICT")
        ctx=incoming.context.model_copy(deep=True)
        ctx.scope_refs["requested_lanes"]=sorted(requested)
        merged_lanes=[lane.model_copy(update={"run_id":incoming.run_id},deep=True)
            for _,lane in sorted(lanes.items())]
        stocks=[StockDecision.model_validate(row) for row in self.engines.merge_decisions(ctx,merged_lanes)]
        stocks=sort_stocks(stocks,merged_lanes)
        incomplete=len(merged_lanes)<len(requested)
        partial=incomplete or any(lane.state in (LaneState.NOT_RUN,LaneState.RUNNING,LaneState.PARTIAL,
            LaneState.INPUT_MISSING,LaneState.FAILED) for lane in merged_lanes)
        gaps=list(dict.fromkeys([gap for lane in merged_lanes for gap in lane.gaps]))
        if incomplete:gaps.append("LANE_RESULTS_INCOMPLETE")
        if partial and not gaps:gaps.append("LANE_PARTIAL")
        changes=dict(incoming.changes)
        changes.update(phase_lane_sources=sources,phase_lane_inputs=inputs,phase_lane_cutoffs=cutoffs,
            phase_lane_source_sessions=sessions,phase_lane_fingerprints=fingerprints)
        body=incoming.model_dump(mode="json")
        body.update(context=ctx.model_dump(mode="json"),input_sha256=digest({"phase_lane_inputs":inputs}),
            lanes=[lane.model_dump(mode="json") for lane in merged_lanes],
            stocks=[stock.model_dump(mode="json") for stock in stocks],
            counts=(Counts() if not stocks and partial else count_rows(stocks)).model_dump(mode="json"),
            changes=changes,gaps=list(dict.fromkeys(gaps)))
        merged=seal_snapshot(body)
        validate_selected_evidence(merged)
        return merged

    def _commit_plan(self,snapshot):
        merger=self._merge_phase_lane_snapshots if snapshot.context.scope_refs.get("merge_phase_lanes") else None
        return self.store.commit_plan(snapshot,merger=merger)

    def retry(self, job_id: str) -> JobRecord:
        previous = self.jobs.get(job_id)
        if previous.context.scope_refs.get("capture_operation"):
            if not self.capture_jobs:raise JobConflict("CAPTURE_DISABLED")
            if previous.state in (JobState.QUEUED,JobState.RUNNING):return previous
            if not previous.retryable:raise JobConflict("NOT_RETRYABLE")
            return self.capture_jobs.retry(previous)
        if previous.state in (JobState.QUEUED, JobState.RUNNING):
            return previous
        if previous.state not in (JobState.FAILED, JobState.INTERRUPTED, JobState.PARTIAL) or not previous.retryable:
            raise JobConflict("NOT_RETRYABLE")
        if previous.state == JobState.PARTIAL:
            resume_context = previous.context.model_copy(deep=True)
            resume_context.scope_refs["resume_from_job"] = previous.job_id
            return self.jobs.submit(resume_context,self._work)
        return self.jobs.submit(previous.context, self._work, retry_job_id=job_id)

    def _work(self, job: JobRecord) -> tuple[str, JobState]:
        # A is the sole owner of business prompts, inclusion rules and inputs.
        ctx = job.context.model_copy(deep=True)
        ctx.scope_refs["mwb_run_id"] = job.run_id
        ctx.scope_refs["run_id"] = job.run_id
        previous = self.store.load_checkpoint(job.job_id, "PUBLISH")
        if previous:
            snap = PlanSnapshot.model_validate(previous)
            if snap.run_id != job.run_id:
                raise StepFailure("CHECKPOINT_RUN_MISMATCH")
            self.jobs.update(job, step="PUBLISH")
            try:
                saved = self._commit_plan(snap)
            except (StorageUnavailable, OSError) as exc:
                raise StepFailure("PUBLISH_UNAVAILABLE", retryable=True) from exc
            return saved.run_id, JobState.PARTIAL if saved.gaps else JobState.SUCCEEDED

        resume_job = ctx.scope_refs.get("resume_from_job",job.job_id)
        frozen_input = self.store.load_checkpoint(resume_job,"LOAD_INPUTS")
        try:
            if frozen_input:
                saved_context = RunContext.model_validate(frozen_input["context"])
                # Preserve original source cutoff/scope and replace only execution identity.
                ctx = saved_context.model_copy(deep=True)
                ctx.scope_refs.update(run_id=job.run_id,mwb_run_id=job.run_id)
                inputs_raw = [InputBatch.model_validate(b).model_copy(update={"context":ctx}) for b in frozen_input["batches"]]
            else:
                inputs_raw = self.engines.load_inputs(ctx, self.adapters)
            inputs = [InputBatch.model_validate(b) for b in (inputs_raw.values() if isinstance(inputs_raw, dict) else inputs_raw)]
            inputs = [b for b in inputs if b.lane.value in ctx.scope_refs["requested_lanes"]]
        except Exception as exc:
            raise StepFailure("LOAD_INPUTS_FAILED", retryable=True) from exc
        # Input owner SHA and provenance live in a derived, non-authoritative snapshot.
        # A may resolve market sessions only by returning a consistent actual context.
        if inputs:
            sessions = inputs[0].context.source_sessions
            for batch in inputs:
                ic = batch.context
                if (ic.target_date != ctx.target_date or ic.phase != ctx.phase or
                    ic.market != ctx.market or ic.cutoff != ctx.cutoff or
                    ic.rules_version != ctx.rules_version or ic.source_sessions != sessions):
                    raise StepFailure("INPUT_CONTEXT_MISMATCH")
            ctx.source_sessions = dict(sessions)
        allowed = set(ctx.scope_refs["requested_lanes"])
        if len({i.lane.value for i in inputs}) != len(inputs) or any(i.context.target_date != ctx.target_date or i.lane.value not in allowed for i in inputs):
            raise StepFailure("INPUT_CONTRACT_MISMATCH")
        input_body = {"derivative": True, "authority": "ORIGINAL_OWNERS_ONLY", "context": ctx.model_dump(mode="json"),
                      "batches": [b.model_dump(mode="json") for b in inputs]}
        input_snapshot_sha = digest(input_body)
        self.store.save_input(input_snapshot_sha, input_body)
        self.store.save_checkpoint(job.job_id,"LOAD_INPUTS",input_body)
        # Volatile job identifiers and server cutoff are not producer-input identity.
        # A must reflect any actual as-of evidence changes in each InputBatch SHA.
        input_sha = digest({"target_date": ctx.target_date, "phase": ctx.phase.value,
                            "sources": sorted((i.lane.value, i.input_sha256) for i in inputs),
                            "stage": ctx.scope_refs.get("stage_input_sha256")})
        signature = digest({"target_date": ctx.target_date, "phase": ctx.phase.value,
                            "input_sha": input_sha, "rules": ctx.rules_version,
                            "prompt": self.config.prompt_version, "model": self.config.model,
                            "reasoning_effort":self.config.announcement_reasoning_effort,
                            "stage": ctx.scope_refs.get("stage_run_id"),
                            "canary_article_id": ctx.scope_refs.get("canary_article_id")})
        reuse = self.store.find_reusable(ctx.target_date, ctx.phase.value, signature)
        if reuse:
            return reuse.run_id, JobState.PARTIAL if reuse.gaps else JobState.SUCCEEDED
        self.jobs.update(job, step="RUN_LANES")
        audit = AuditedExecutor(self.executor,store=self.store,job_id=job.job_id,resume_job_id=resume_job)
        if resume_job != job.job_id:
            old_job=self.store.get_job(resume_job)
            if old_job:
                audit.refs.extend(r for r in old_job.execution_refs if r.get("role") and r.get("success"))
        try:
            # A consumes a keyed batch; B accepts either keyed or list LaneResults.
            engine_inputs = {i.lane.value:i for i in inputs} if getattr(self.engines,"__name__","").startswith("v4.manager_workbench.engines") else inputs
            if getattr(self.engines,"__name__","").startswith("v4.manager_workbench.engines"):
                previous_lanes = []
                remaining = {}
                for lane_name, value in engine_inputs.items():
                    cached = self.store.load_checkpoint(resume_job,"lane_"+lane_name)
                    if cached:
                        previous_lanes.append(LaneResult.model_validate(cached).model_copy(update={"run_id":job.run_id}))
                    else:
                        remaining[lane_name] = value
                execution_context = ctx.model_copy(deep=True)
                execution_context.scope_refs["requested_lanes"] = list(remaining)
                remaining = {k:v.model_copy(update={"context":execution_context}) for k,v in remaining.items()}
                produced = self.engines.run_lanes(execution_context,remaining,audit) if remaining else {}
                lanes_raw = [*previous_lanes,*produced.values()]
            else:
                lanes_raw = self.engines.run_lanes(ctx, engine_inputs, audit)
            lanes = [LaneResult.model_validate(l) for l in (lanes_raw.values() if isinstance(lanes_raw,dict) else lanes_raw)]
            announcement_rows = any(l.lane == Lane.ANNOUNCEMENT and any(r.get("decision") in {"SELECTED","CONDITIONAL_WATCH","NOT_SELECTED"} for r in l.rows) and
                                    l.state in (LaneState.READY, LaneState.PARTIAL) for l in lanes)
            audit.assert_independent_review(announcement_rows)
            for lane_result in lanes:
                if lane_result.state in (LaneState.READY,LaneState.READY_EMPTY,LaneState.NOT_APPLICABLE):
                    self.store.save_checkpoint(job.job_id,"lane_"+lane_result.lane.value,lane_result.model_dump(mode="json"))
        except Exception as exc:
            raise StepFailure("RUN_LANES_FAILED", retryable=False) from exc
        finally:
            job.execution_refs.extend(audit.refs)
            self.store.save_job(job)
        if ctx.phase != Phase.PREOPEN:
            ctx.scope_refs["source_cutoff"] = ctx.cutoff
            ctx.cutoff = now()
        job.total_count = len(inputs)
        job.completed_count = sum(l.state in (LaneState.READY,LaneState.READY_EMPTY,LaneState.NOT_APPLICABLE) for l in lanes)
        retry_lanes = [l.lane.value for l in lanes if l.state == LaneState.FAILED or any(r.get("failure_code") for r in l.rows)]
        job.failed_steps = retry_lanes
        job.retryable = bool(retry_lanes)
        job.failure_code = "LANE_STEPS_INCOMPLETE" if retry_lanes else None
        # Preserve failure lanes from A. Never synthesize a READY status from row presence.
        by_input = {i.lane: i.input_sha256 for i in inputs}
        if len({l.lane for l in lanes}) != len(lanes):
            raise StepFailure("DUPLICATE_LANE")
        for l in lanes:
            if l.run_id != job.run_id or l.rules_version != ctx.rules_version:
                raise StepFailure("LANE_RUN_MISMATCH")
            if l.lane not in by_input or l.input_sha256 != by_input[l.lane]:
                raise StepFailure("LANE_INPUT_SHA_MISMATCH")
            if l.lane.value not in allowed:
                raise StepFailure("LANE_NOT_REQUESTED")
        self.jobs.update(job, step="MERGE_DECISIONS")
        try:
            stocks = [StockDecision.model_validate(s) for s in self.engines.merge_decisions(ctx, lanes)]
        except Exception as exc:
            raise StepFailure("MERGE_FAILED") from exc
        stocks = sort_stocks(stocks, lanes)
        partial = any(l.state in (LaneState.NOT_RUN, LaneState.RUNNING, LaneState.PARTIAL, LaneState.INPUT_MISSING, LaneState.FAILED) for l in lanes) or len(lanes) < len(allowed)
        gaps = [g for l in lanes for g in l.gaps]
        if len(lanes) < len(allowed):
            gaps.append("LANE_RESULTS_INCOMPLETE")
        if partial and not gaps:
            gaps.append("LANE_PARTIAL")
        ts = now()
        data = {"context": ctx.model_dump(mode="json"), "run_id": job.run_id,
                "input_sha256": input_sha, "generated_at": ts, "available_at": ts,
                "lanes": [l.model_dump(mode="json") for l in lanes],
                "stocks": [s.model_dump(mode="json") for s in stocks],
                "counts": (Counts() if not stocks and partial else count_rows(stocks)).model_dump(mode="json"),
                "changes": {"fingerprint": signature, "prompt_version": self.config.prompt_version,
                            "model": self.config.model, "input_snapshot_sha256": input_snapshot_sha,
                            "stage_run_id": ctx.scope_refs.get("stage_run_id")},
                "review_refs": audit.refs, "gaps": gaps}
        snap = seal_snapshot(data)
        validate_selected_evidence(snap)
        self.store.save_checkpoint(job.job_id, "PUBLISH", snap.model_dump(mode="json"))
        self.jobs.update(job, step="PUBLISH")
        try:
            saved = self._commit_plan(snap)
        except (StorageUnavailable, OSError) as exc:
            raise StepFailure("PUBLISH_UNAVAILABLE", retryable=True) from exc
        return saved.run_id, JobState.PARTIAL if partial else JobState.SUCCEEDED

    def save_review(self, plan_run_id: str, close_inputs: Any) -> ReviewSummary:
        plan = self.store.read_plan(plan_run_id)
        result = ReviewSummary.model_validate(self.engines.evaluate_review(plan, close_inputs))
        if result.plan_run_id != plan_run_id or result.target_date != plan.context.target_date:
            raise StorageConflict("REVIEW_RUN_MISMATCH")
        if result.mode != "NOT_EVALUATED":
            self.store.save_review(result)
        return result

    def freeze_preopen(self, date: str, *, cutoff: datetime) -> PlanSnapshot:
        """One-shot 09:25 latch; never calls a model or changes a frozen pointer."""
        validate_date(date)
        existing = self.store.get_plan(date, Phase.PREOPEN.value)
        if existing:
            return existing
        ctx = self.context(date, Phase.PREOPEN, trigger="SCHEDULED", cutoff=cutoff)
        # Only already committed, fully ready lanes with verified evidence before cutoff are admissible.
        candidates = [p for p in self.store.list_plans(date) if p.context.phase in (Phase.INTRADAY,Phase.NEXT_DAY)
                      and datetime.fromisoformat(p.generated_at)<=cutoff and datetime.fromisoformat(p.available_at)<=cutoff]
        current = candidates[0] if candidates else None
        acceptable: list[LaneResult] = []
        names = set()
        filter_diagnostics = {}
        if current and (datetime.fromisoformat(current.generated_at) <= cutoff and
                        datetime.fromisoformat(current.available_at) <= cutoff):
            for lane in current.lanes:
                if lane.state not in (LaneState.READY, LaneState.READY_EMPTY,LaneState.PARTIAL):
                    continue
                refs={e.evidence_id:e for e in lane.evidence_refs if e.verification.value=="VERIFIED" and e.available_at
                      and datetime.fromisoformat(e.available_at)<=cutoff}
                completed=[]
                rejected_reasons = {}
                source_reasons = {}
                for row in lane.rows:
                    available=row.get("available_at")
                    reviewed=row.get("semantic",{}).get("reviewed_at")
                    reasons = []
                    if row.get("decision") not in {"SELECTED","CONDITIONAL_WATCH","NOT_SELECTED","OBSERVATION_ONLY"}:
                        reasons.append("PREOPEN_DECISION_INCOMPLETE")
                    if not row.get("evidence_ids"):
                        reasons.append("PREOPEN_ROW_EVIDENCE_MISSING")
                    elif not set(row["evidence_ids"]).issubset(refs):
                        reasons.append("PREOPEN_ROW_EVIDENCE_UNVERIFIED_OR_AFTER_CUTOFF")
                    if not available or datetime.fromisoformat(available)>cutoff:
                        reasons.append("PREOPEN_ROW_AVAILABLE_AFTER_CUTOFF_OR_UNKNOWN")
                    if reviewed and datetime.fromisoformat(reviewed)>cutoff:
                        reasons.append("PREOPEN_ROW_REVIEW_AFTER_CUTOFF")
                    if not reasons:
                        completed.append(row)
                    else:
                        for reason in reasons:
                            rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
                        row_reasons = row.get("reasons")
                        row_reasons = row_reasons if isinstance(row_reasons, list) else []
                        source_reason = row.get("reason")
                        if isinstance(source_reason, str):
                            row_reasons = [*row_reasons, source_reason]
                        for reason in {value for value in row_reasons if isinstance(value, str)}:
                            source_reasons[reason] = source_reasons.get(reason, 0) + 1
                filter_diagnostics[lane.lane.value] = dict(
                    source_run_id=current.run_id, source_state=lane.state.value,
                    input_sha256=lane.input_sha256, source_coverage=lane.coverage.model_dump(mode="json"),
                    source_row_count=len(lane.rows), accepted_row_count=len(completed),
                    filtered_row_count=len(lane.rows)-len(completed),
                    rejection_reason_counts=rejected_reasons, filtered_source_reason_counts=source_reasons,
                    source_gaps=list(lane.gaps),
                    excluded_evidence=[dict(evidence_id=e.evidence_id, verification=e.verification.value,
                        available_at=e.available_at, gaps=list(e.gaps)) for e in lane.evidence_refs
                        if e.evidence_id not in refs])
                accepted=lane.model_copy(update={"rows":completed,"evidence_refs":list(refs.values())},deep=True)
                if len(completed)!=len(lane.rows) or lane.state==LaneState.PARTIAL:
                    accepted.state=LaneState.PARTIAL
                    accepted.gaps=list(dict.fromkeys([*accepted.gaps,"PREOPEN_ROWS_INCOMPLETE",
                        *(["PREOPEN_ALL_ROWS_FILTERED"] if lane.rows and not completed else [])]))
                    if not completed:
                        accepted.coverage=lane.coverage.model_copy(update={"assessed_count":0,
                            "unassessed_count":None,"gaps":list(dict.fromkeys([
                                *lane.coverage.gaps,*accepted.gaps]))},deep=True)
                acceptable.append(accepted)
                names.add(lane.lane)
            ctx.source_sessions=dict(current.context.source_sessions)
            ctx.scope_refs={**current.context.scope_refs,"requested_lanes":[l.value for l in ALL_LANES]}
        run_id = uuid4().hex
        lanes = [l.model_copy(update={"run_id":run_id}, deep=True) for l in acceptable]
        lanes += [LaneResult(lane=lane, state=LaneState.NOT_RUN, rows=[], coverage={
                 "scope_count":None, "observed_count":None,"assessed_count":None,"unassessed_count":None,
                 "gaps":["PREOPEN_LANE_INCOMPLETE"]}, input_sha256="0"*64, rules_version=ctx.rules_version,
                 run_id=run_id, gaps=["PREOPEN_LANE_INCOMPLETE"]) for lane in ALL_LANES if lane not in names]
        # A owns classification; we never reclassify. Only rows supported by frozen lanes survive.
        ids = {e.evidence_id for l in acceptable for e in l.evidence_refs}
        if current and getattr(self.engines,"__name__","").startswith("v4.manager_workbench.engines"):
            stocks=self.engines.merge_decisions(ctx,lanes)
        else:
            stocks = [s for s in current.stocks if s.evidence_ids and set(s.evidence_ids).issubset(ids)] if current else []
        ts = now()
        ctx.scope_refs["timing_status"] = "LATE_CATCHUP" if datetime.fromisoformat(ts)>cutoff else "ON_SLOT"
        snap = seal_snapshot({"context":ctx.model_dump(mode="json"), "run_id":run_id,
                  "input_sha256":current.input_sha256 if current else "0"*64,
                  "generated_at":ts, "available_at":ts, "lanes":[l.model_dump(mode="json") for l in lanes],
                  "stocks":[s.model_dump(mode="json") for s in stocks],
                  "counts":(Counts() if not stocks and len(names)<len(ALL_LANES) else count_rows(stocks)).model_dump(mode="json"),
                  "changes":{"freeze_cutoff":ctx.cutoff,"source_run_id":current.run_id if current else None,
                      "preopen_filter_diagnostics":filter_diagnostics},
                  "gaps":["PREOPEN_PARTIAL"] if len(names) < len(ALL_LANES) or any(l.state==LaneState.PARTIAL for l in lanes) else []})
        validate_selected_evidence(snap)
        try:
            return self.store.commit_plan(snap, freeze=True)
        except StorageConflict as exc:
            if str(exc) == "PREOPEN_FROZEN":
                prev = self.store.get_plan(date, Phase.PREOPEN.value)
                if prev:
                    return prev
            raise


def create_service(config: WorkbenchConfig, adapters: Any, engines: Any, executor: Any, **kwargs) -> ManagerService:
    return ManagerService(config, adapters, engines, executor, **kwargs)

