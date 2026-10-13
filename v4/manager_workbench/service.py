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
        return RunContext(target_date=target_date, phase=phase, cutoff=ts.astimezone(HK).isoformat(),
                          trigger=trigger, source_sessions={}, rules_version=self.config.rules_version,
                          scope_refs={**(scope_refs or {}), "requested_lanes": [p.value for p in (lanes or ALL_LANES)]})

    def submit(self, target_date: str, phase: Phase, *, trigger: str = "MANUAL",
               lanes: list[Lane] | None = None, cutoff: datetime | None = None,
               scope_refs: dict[str, Any] | None = None) -> JobRecord:
        context = self.context(target_date, phase, trigger=trigger, lanes=lanes, cutoff=cutoff, scope_refs=scope_refs)
        return self.jobs.submit(context, self._work)

    def retry(self, job_id: str) -> JobRecord:
        previous = self.jobs.get(job_id)
        if previous.state not in (JobState.FAILED, JobState.INTERRUPTED, JobState.PARTIAL) or not previous.retryable:
            raise JobConflict("NOT_RETRYABLE")
        return self.jobs.submit(previous.context, self._work, retry_job_id=job_id)

    def _work(self, job: JobRecord) -> tuple[str, JobState]:
        """A native keyed-lane boundary with per-lane/semantic checkpoints.

        A supplies source/analysis semantics; B validates and persists their
        identities. An explicit partial retry leaves the prior plan immutable.
        """
        ctx = job.context.model_copy(deep=True)
        ctx.scope_refs["run_id"] = job.run_id  # required by A/inputs & A/engines
        ctx.scope_refs["mwb_run_id"] = job.run_id  # old B mock compatibility only
        wanted = set(ctx.scope_refs["requested_lanes"])
        prior_failed = set(job.failed_steps)
        previous = self.store.load_checkpoint(job.job_id, "PUBLISH_" + job.run_id)
        if previous and "PUBLISH" in prior_failed:
            snap = PlanSnapshot.model_validate(previous)
            if snap.run_id != job.run_id:
                raise StepFailure("CHECKPOINT_RUN_MISMATCH")
            self.jobs.update(job, step="PUBLISH")
            try:
                saved = self.store.commit_plan(snap)
            except (StorageUnavailable, OSError) as exc:
                raise StepFailure("PUBLISH_UNAVAILABLE", retryable=True) from exc
            return saved.run_id, JobState.PARTIAL if saved.gaps else JobState.SUCCEEDED

        try:
            raw = self.engines.load_inputs(ctx, self.adapters)
            if isinstance(raw, dict):
                # A's actual native input interface, not a list of InputBatch.
                input_map = {str(key.value if isinstance(key,Lane) else key):InputBatch.model_validate(value)
                             for key,value in raw.items()}
                mapping_mode = True
            else:
                batches = [InputBatch.model_validate(value) for value in raw]
                input_map = {b.lane.value:b for b in batches}
                if len(input_map) != len(batches):raise ValueError("DUPLICATE_INPUT_BATCH")
                mapping_mode = False
        except Exception as exc:
            raise StepFailure("LOAD_INPUTS_FAILED", retryable=True) from exc
        # B's intended scope, not A's other available owner material.
        if set(input_map)-set(Lane._value2member_map_) or not wanted.issubset(input_map):
            raise StepFailure("INPUT_CONTRACT_MISMATCH")
        inputs = {name:input_map[name] for name in sorted(wanted)}
        for name, batch in inputs.items():
            ic = batch.context
            if (batch.lane.value != name or ic.target_date != ctx.target_date or
                ic.phase != ctx.phase or ic.market != ctx.market or
                ic.cutoff != ctx.cutoff or ic.rules_version != ctx.rules_version or
                ic.source_sessions != ctx.source_sessions or ic.scope_refs != ctx.scope_refs):
                raise StepFailure("INPUT_CONTEXT_MISMATCH")
        input_body = {"derivative":True,"authority":"ORIGINAL_OWNERS_ONLY",
                      "context":ctx.model_dump(mode="json"),
                      "batches": {name:batch.model_dump(mode="json") for name,batch in inputs.items()}}
        input_snapshot_sha = digest(input_body)
        self.store.save_input(input_snapshot_sha, input_body)
        # Placeholder A input hashes may include volatile A run_id; treat a
        # missing *unbound* authority as unchanged only if the shape/gaps agree.
        def stable_input(name: str, batch: InputBatch) -> str:
            if batch.universe_ref is None and not batch.records and not batch.evidence_refs:
                return digest({"lane":name,"missing":batch.gaps,"scope":batch.scope_description,
                               "coverage":batch.coverage.model_dump(mode="json")})
            return batch.input_sha256
        input_sha = digest({"target_date":ctx.target_date,"phase":ctx.phase.value,
                            "sources": sorted((name,stable_input(name,b)) for name,b in inputs.items()),
                            "stage":ctx.scope_refs.get("stage_input_sha256")})
        signature = digest({"target_date":ctx.target_date,"phase":ctx.phase.value,
                            "input_sha":input_sha,"rules":ctx.rules_version,
                            "prompt":self.config.prompt_version,"model":self.config.model,
                            "reasoning_effort":self.config.reasoning_effort,
                            "stage":ctx.scope_refs.get("stage_run_id"),
                            "canary_article_id":ctx.scope_refs.get("canary_article_id")})
        if not prior_failed:
            reusable = self.store.find_reusable(ctx.target_date,ctx.phase.value,signature)
            if reusable and not reusable.gaps and all(l.state in
                    (LaneState.READY, LaneState.READY_EMPTY, LaneState.NOT_APPLICABLE) for l in reusable.lanes):
                return reusable.run_id, JobState.PARTIAL if reusable.gaps else JobState.SUCCEEDED
        self.jobs.update(job,step="RUN_LANES")
        # Retry only expressly failed lanes, against identical original owner SHA.
        resume: dict[str,LaneResult] = {}
        if prior_failed and all(f.startswith("LANE:") for f in prior_failed):
            for name, batch in inputs.items():
                if "LANE:" + name in prior_failed:continue
                saved = self.store.load_checkpoint(job.job_id,"LANE_" + name)
                if saved is None or saved.get("input_sha256") != batch.input_sha256 or saved.get("rules_version") != ctx.rules_version:
                    raise StepFailure("RETRY_COMPLETED_LANE_IDENTITY_CHANGED")
                resume[name]=LaneResult.model_validate(saved).model_copy(update={"run_id":job.run_id})
        # On a publication failure, PUBLISH checkpoint always wins above;
        # a brand-new attempt does not replay any previous success implicitly.
        remaining = {name:batch for name,batch in inputs.items() if name not in resume}
        audit = AuditedExecutor(self.executor,config=self.config,store=self.store,job_id=job.job_id)
        try:
            if remaining:
                arg = remaining if mapping_mode else list(remaining.values())
                raw_lanes = self.engines.run_lanes(ctx, arg, audit)
                if isinstance(raw_lanes,dict):
                    # A's core emits all lane keys including unrequested blanks.
                    if set(raw_lanes)-set(Lane._value2member_map_):
                        raise StepFailure("UNKNOWN_A_LANE")
                    processed = {str(name):LaneResult.model_validate(value)
                                 for name,value in raw_lanes.items() if str(name) in remaining}
                    if set(processed) != set(remaining):
                        raise StepFailure("MISSING_A_LANE")
                else:
                    values=[LaneResult.model_validate(value) for value in raw_lanes]
                    processed={row.lane.value:row for row in values}
                    if len(processed)!=len(values):raise StepFailure("DUPLICATE_LANE")
            else:
                processed={}
            selected_ann = any(r.get("decision") in ("SELECTED","CONDITIONAL_WATCH")
                               for lane in processed.values() if lane.lane == Lane.ANNOUNCEMENT for r in lane.rows)
            audit.assert_independent_review(selected_ann)
        except StepFailure:
            raise
        except Exception as exc:
            raise StepFailure("RUN_LANES_FAILED",retryable=False) from exc
        finally:
            seen={r.get("execution_id") for r in job.execution_refs if r.get("execution_id")}
            for ref in audit.refs:
                if ref.get("execution_id") not in seen:
                    job.execution_refs.append(ref)
                    seen.add(ref.get("execution_id"))
            self.store.save_job(job)
        # A intentionally maps one-off executor exceptions to UNASSESSED.
        # Distinguish recoverable execution errors from genuine negative research.
        if audit.failures:
            ann=processed.get("ANNOUNCEMENT")
            if ann:
                ann=ann.model_copy(deep=True)
                ann.state=LaneState.FAILED
                # Any permanent failure in a multi-article lane prevents blind
                # retry of that lane, even if another article timed out.
                label=("SEMANTIC_EXECUTION_TRANSIENT_FAILURE" if all(f["retryable"] for f in audit.failures)
                       else "SEMANTIC_EXECUTION_FAILED_PERMANENT")
                ann.gaps=list(dict.fromkeys([*ann.gaps,label]))
                ann.coverage.gaps=list(dict.fromkeys([*ann.coverage.gaps,label]))
                processed["ANNOUNCEMENT"]=ann
        merged_lanes = {**resume, **processed}
        by_input = {name:i.input_sha256 for name,i in inputs.items()}
        if set(merged_lanes)!=wanted:
            raise StepFailure("LANE_RESULTS_INCOMPLETE")
        for name, lane in merged_lanes.items():
            if lane.lane.value != name or lane.run_id != job.run_id or lane.rules_version != ctx.rules_version:
                raise StepFailure("LANE_RUN_MISMATCH")
            if lane.input_sha256 != by_input[name]:
                raise StepFailure("LANE_INPUT_SHA_MISMATCH")
            if name in ("STAGE_REFERENCE","CLOSE_REFERENCE") and any(
                    x.get("decision") in ("SELECTED","CONDITIONAL_WATCH") for x in lane.rows):
                raise StepFailure("REFERENCE_LANE_PROMOTED_TO_RESEARCH")
            if name in processed and lane.state in (LaneState.READY,LaneState.READY_EMPTY,LaneState.PARTIAL):
                self.store.save_checkpoint(job.job_id,"LANE_" + name,lane.model_dump(mode="json"))
        self.jobs.update(job,step="MERGE_DECISIONS")
        try:
            lane_argument=merged_lanes if mapping_mode else list(merged_lanes.values())
            stocks=[StockDecision.model_validate(s) for s in self.engines.merge_decisions(ctx,lane_argument)]
        except Exception as exc:
            raise StepFailure("MERGE_FAILED") from exc
        lanes=[merged_lanes[name] for name in sorted(merged_lanes)]
        stocks=sort_stocks(stocks,lanes)
        partial=any(l.state in (LaneState.NOT_RUN,LaneState.RUNNING,LaneState.PARTIAL,
                                LaneState.INPUT_MISSING,LaneState.FAILED) for l in lanes)
        gaps=[g for l in lanes for g in l.gaps]
        if partial and not gaps:gaps.append("LANE_PARTIAL")
        failed_lanes=[lane for lane in lanes if lane.state == LaneState.FAILED]
        if failed_lanes:
            job.failed_steps=["LANE:" + lane.lane.value for lane in failed_lanes]
            transient_codes={"TRANSIENT_PROVIDER_FAILURE","SOURCE_TEMPORARILY_UNAVAILABLE",
                             "MODEL_TIMEOUT","SEMANTIC_EXECUTION_TRANSIENT_FAILURE","AUTHORITY_TEMPORARILY_UNAVAILABLE"}
            job.retryable=all(bool(transient_codes.intersection(set(lane.gaps))) for lane in failed_lanes)
            job.failure_code="RECOVERABLE_LANE_FAILURE" if job.retryable else "LANE_FAILURE_NOT_RETRYABLE"
        else:
            job.failed_steps=[]
            job.retryable=False
            job.failure_code=None
        self.store.save_job(job)
        ts=now()
        refs=[r for r in job.execution_refs if r.get("role") in ("READER","REVIEWER")]
        data={"context":ctx.model_dump(mode="json"),"run_id":job.run_id,
              "input_sha256":input_sha,"generated_at":ts,"available_at":ts,
              "lanes":[l.model_dump(mode="json") for l in lanes],
              "stocks":[s.model_dump(mode="json") for s in stocks],
              "counts":count_rows(stocks).model_dump(mode="json"),
              "changes":{"fingerprint":signature,"prompt_version":self.config.prompt_version,
                         "model":self.config.model,"input_snapshot_sha256":input_snapshot_sha,
                         "stage_run_id":ctx.scope_refs.get("stage_run_id")},
              "review_refs":refs,"gaps":gaps}
        snap=seal_snapshot(data)
        self.store.save_checkpoint(job.job_id,"PUBLISH_" + job.run_id,snap.model_dump(mode="json"))
        self.jobs.update(job,step="PUBLISH")
        try:
            saved=self.store.commit_plan(snap)
        except (StorageUnavailable,OSError) as exc:
            raise StepFailure("PUBLISH_UNAVAILABLE",retryable=True) from exc
        return saved.run_id, JobState.PARTIAL if partial else JobState.SUCCEEDED

    def save_review(self, plan_run_id: str, close_inputs: Any) -> ReviewSummary:
        plan = self.store.read_plan(plan_run_id)
        result = ReviewSummary.model_validate(self.engines.evaluate_review(plan, close_inputs))
        if result.plan_run_id != plan_run_id or result.target_date != plan.context.target_date:
            raise StorageConflict("REVIEW_RUN_MISMATCH")
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
        candidates = self.store.list_plans(date, Phase.INTRADAY.value)
        current = candidates[0] if candidates else None
        acceptable: list[LaneResult] = []
        names = set()
        if current and (datetime.fromisoformat(current.generated_at) <= cutoff and
                        datetime.fromisoformat(current.available_at) <= cutoff):
            for lane in current.lanes:
                if lane.state not in (LaneState.READY, LaneState.READY_EMPTY):
                    continue
                if (lane.rows and not lane.evidence_refs) or any(e.verification.value != "VERIFIED" or not e.available_at or
                       datetime.fromisoformat(e.available_at) > cutoff for e in lane.evidence_refs):
                    continue
                acceptable.append(lane)
                names.add(lane.lane)
        run_id = uuid4().hex
        lanes = [l.model_copy(update={"run_id":run_id}, deep=True) for l in acceptable]
        lanes += [LaneResult(lane=lane, state=LaneState.NOT_RUN, rows=[], coverage={
                 "scope_count":None, "observed_count":None,"assessed_count":None,"unassessed_count":None,
                 "gaps":["PREOPEN_LANE_INCOMPLETE"]}, input_sha256="0"*64, rules_version=ctx.rules_version,
                 run_id=run_id, gaps=["PREOPEN_LANE_INCOMPLETE"]) for lane in ALL_LANES if lane not in names]
        # A owns classification; we never reclassify. Only rows supported by frozen lanes survive.
        ids = {e.evidence_id for l in acceptable for e in l.evidence_refs}
        stocks = [s for s in current.stocks if s.evidence_ids and set(s.evidence_ids).issubset(ids)] if current else []
        ts = now()
        snap = seal_snapshot({"context":ctx.model_dump(mode="json"), "run_id":run_id,
                  "input_sha256":current.input_sha256 if current else "0"*64,
                  "generated_at":ts, "available_at":ts, "lanes":[l.model_dump(mode="json") for l in lanes],
                  "stocks":[s.model_dump(mode="json") for s in stocks],
                  "counts":count_rows(stocks).model_dump(mode="json"),
                  "changes":{"freeze_cutoff":ctx.cutoff,"source_run_id":current.run_id if current else None},
                  "gaps":["PREOPEN_PARTIAL"] if len(names) < len(ALL_LANES) else []})
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
