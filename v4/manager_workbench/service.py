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
    def __init__(self, config: WorkbenchConfig, adapters: Any, engines: Any, executor: Any):
        self.config = config
        self.adapters = adapters
        self.engines = engines
        self.executor = executor
        self.store = WorkbenchStore(config.state_root)
        self.jobs = JobCoordinator(self.store, workers=config.workers)

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
        return self.jobs.submit(context, self._work)

    def retry(self, job_id: str) -> JobRecord:
        previous = self.jobs.get(job_id)
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
                saved = self.store.commit_plan(snap)
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
            saved = self.store.commit_plan(snap)
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
        if current and (datetime.fromisoformat(current.generated_at) <= cutoff and
                        datetime.fromisoformat(current.available_at) <= cutoff):
            for lane in current.lanes:
                if lane.state not in (LaneState.READY, LaneState.READY_EMPTY,LaneState.PARTIAL):
                    continue
                refs={e.evidence_id:e for e in lane.evidence_refs if e.verification.value=="VERIFIED" and e.available_at
                      and datetime.fromisoformat(e.available_at)<=cutoff}
                completed=[]
                for row in lane.rows:
                    available=row.get("available_at")
                    reviewed=row.get("semantic",{}).get("reviewed_at")
                    if (row.get("decision") in {"SELECTED","CONDITIONAL_WATCH","NOT_SELECTED","OBSERVATION_ONLY"}
                            and row.get("evidence_ids") and set(row["evidence_ids"]).issubset(refs)
                            and available and datetime.fromisoformat(available)<=cutoff
                            and (not reviewed or datetime.fromisoformat(reviewed)<=cutoff)):
                        completed.append(row)
                if lane.rows and not completed:continue
                if lane.state==LaneState.PARTIAL and not completed:continue
                accepted=lane.model_copy(update={"rows":completed,"evidence_refs":list(refs.values())},deep=True)
                if len(completed)!=len(lane.rows):
                    accepted.state=LaneState.PARTIAL
                    accepted.gaps=list(dict.fromkeys([*accepted.gaps,"PREOPEN_ROWS_INCOMPLETE"]))
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
                  "changes":{"freeze_cutoff":ctx.cutoff,"source_run_id":current.run_id if current else None},
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


def create_service(config: WorkbenchConfig, adapters: Any, engines: Any, executor: Any) -> ManagerService:
    return ManagerService(config, adapters, engines, executor)

