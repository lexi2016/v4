"""Detached bounded thread execution; persisted attempts, not HTTP request tasks."""
from __future__ import annotations
from infrastructure.runtime_graph.notifications import notify as _graph_notify

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable
from uuid import uuid4

from .contracts import HK, JobRecord, JobState, RunContext
from .store import WorkbenchStore


class JobConflict(Exception):
    pass


class StepFailure(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def now() -> str:
    return datetime.now(HK).isoformat()


class JobCoordinator:
    def __init__(self, store: WorkbenchStore, workers: int = 2):
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mwb-worker")
        self._mutex = threading.RLock()
        self._active: dict[str, str] = {}
        self.store.recover_orphan_attempts()

    @staticmethod
    def _scope(context: RunContext) -> str:
        lanes = ",".join(sorted(context.scope_refs.get("requested_lanes", [])))
        stage = str(context.scope_refs.get("stage_run_id", "")) + ":" + str(context.scope_refs.get("stage_input_sha256", ""))
        canary = str(context.scope_refs.get("canary_article_id", ""))
        capture = str(context.scope_refs.get("capture_operation", "")) + ":" + str(context.scope_refs.get("capture_input_sha256", "")) + ":" + str(context.scope_refs.get("capture_analysis_identity", ""))
        base = f"{context.target_date}:{context.phase.value}:{lanes}:{stage}:{canary}"
        if context.scope_refs.get("capture_operation"):
            return f"{capture}:{context.cutoff}:{base}"
        return f"{capture}:{base}" if context.scope_refs.get("capture_input_sha256") else base

    def submit(self, context: RunContext, worker: Callable[[JobRecord], tuple[str, JobState]], *,
               retry_job_id: str | None = None) -> JobRecord:
        scope = self._scope(context)
        with self._mutex, self.store.lock("submission:" + scope):
            if scope in self._active:
                candidate = self.store.get_job(self._active[scope])
                if candidate and candidate.state in (JobState.QUEUED, JobState.RUNNING):
                    if retry_job_id:
                        raise JobConflict("ACTIVE_JOB_CONFLICT")
                    return candidate
            shared = self.store.active_claim(scope)
            if shared is not None:
                if retry_job_id:
                    raise JobConflict("ACTIVE_JOB_CONFLICT")
                return shared
            if retry_job_id:
                current = self.store.get_job(retry_job_id)
                if current is None:
                    raise KeyError("JOB_NOT_FOUND")
                if current.context != context or current.state not in (JobState.FAILED, JobState.INTERRUPTED, JobState.PARTIAL) or not current.retryable:
                    raise JobConflict("NOT_RETRYABLE")
                current.state = JobState.QUEUED
                current.finished_at = None
                current.failure_code = None
                current.started_at = None
                current.step = "RETRY_QUEUED"
                job = current
            else:
                id_ = uuid4().hex
                job = JobRecord(job_id=id_, run_id=id_, context=context,
                                state=JobState.QUEUED, step="QUEUED", execution_refs=[{"kind":"host", "pid":os.getpid()}])
            self.store.save_job(job)
            self.store.set_claim(scope,job.job_id)
            self._active[scope] = job.job_id
            self.pool.submit(self._execute, job, worker, scope)
            return job

    def _execute(self, job: JobRecord, worker: Callable[[JobRecord], tuple[str, JobState]], scope: str) -> None:
        try:
            self.update(job, state=JobState.RUNNING, step="LOAD_INPUTS")
            result_run_id, result_state = worker(job)
            job.run_id = result_run_id
            self.update(job, state=result_state, step="DONE", finished=True)
        except StepFailure as e:
            job.failed_steps = list(dict.fromkeys([*job.failed_steps, job.step]))
            job.failure_code = e.code
            job.retryable = e.retryable
            self.update(job, state=JobState.FAILED, finished=True)
        except Exception:
            # Never return arbitrary exception messages, paths, or prompts to HTTP clients.
            job.failed_steps = list(dict.fromkeys([*job.failed_steps, job.step]))
            job.failure_code = "UNEXPECTED_WORKER_ERROR"
            job.retryable = False
            self.update(job, state=JobState.FAILED, finished=True)
        finally:
            with self._mutex, self.store.lock("submission:" + scope):
                if self._active.get(scope) == job.job_id:
                    del self._active[scope]
                claim = self.store.active_claim(scope)
                if claim is None or claim.job_id == job.job_id:
                    self.store.set_claim(scope,None)

    def update(self, job: JobRecord, *, state: JobState | None = None,
               step: str | None = None, finished: bool = False) -> None:
        if state:
            job.state = state
        if step:
            job.step = step
        instant = now()
        _graph_started = not job.started_at and job.state == JobState.RUNNING
        if not job.started_at and job.state == JobState.RUNNING:
            job.started_at = instant
        job.last_progress_at = instant
        if finished:
            job.finished_at = instant
        self.store.save_job(job)
        if _graph_started or finished:
            _graph_notify("MANAGER_WORKBENCH_API", "manager_workbench_api", job.context.target_date,
                          "COMMITTED" if finished else "EXECUTOR_ENTERED", run_id=job.job_id,
                          source_path=self.store.root / "attempts" / (job.job_id + ".json"))

    def get(self, id_: str) -> JobRecord:
        job = self.store.get_job(id_)
        if job is None:
            raise KeyError("JOB_NOT_FOUND")
        return job

    def stop(self) -> None:
        self.pool.shutdown(wait=True)

