"""Detached bounded thread execution; persisted attempts, not HTTP request tasks."""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable
from uuid import uuid4

from .contracts import HK, JobRecord, JobState, RunContext, job_scope
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
        self._active: dict[str, tuple[str, str]] = {}
        self.store.recover_orphan_attempts()

    @staticmethod
    def _scope(context: RunContext) -> str:
        return job_scope(context)

    def submit(self, context: RunContext, worker: Callable[[JobRecord], tuple[str, JobState]], *,
               retry_job_id: str | None = None) -> JobRecord:
        scope = self._scope(context)
        with self._mutex, self.store.lock("submission:" + scope):
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
                                state=JobState.QUEUED, step="QUEUED")
            job.attempt_id = uuid4().hex
            # Only this attempt's host owns the work; retain non-host evidence.
            job.execution_refs = [r for r in job.execution_refs if r.get("kind") != "host"]
            job.execution_refs.append({"kind": "host", "pid": os.getpid(), "attempt_id": job.attempt_id})
            self.store.save_job(job, replace_attempt=True)
            try:
                self.store.set_claim(scope, job.job_id, attempt_id=job.attempt_id)
                self._active[scope] = (job.job_id, job.attempt_id)
                self.pool.submit(self._execute, job, worker, scope)
            except Exception:
                self._active.pop(scope, None)
                job.failure_code = "ENQUEUE_FAILED"
                job.retryable = True
                self.update(job, state=JobState.INTERRUPTED, finished=True)
                self.store.clear_claim(scope, job.job_id, job.attempt_id)
                raise
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
                if self._active.get(scope) == (job.job_id, job.attempt_id):
                    del self._active[scope]
                self.store.clear_claim(scope, job.job_id, job.attempt_id)

    def update(self, job: JobRecord, *, state: JobState | None = None,
               step: str | None = None, finished: bool = False) -> None:
        if state:
            job.state = state
        if step:
            job.step = step
        instant = now()
        if not job.started_at and job.state == JobState.RUNNING:
            job.started_at = instant
        job.last_progress_at = instant
        if finished:
            job.finished_at = instant
        self.store.save_job(job, expected_attempt_id=job.attempt_id)

    def get(self, id_: str) -> JobRecord:
        job = self.store.get_job(id_)
        if job is None:
            raise KeyError("JOB_NOT_FOUND")
        return job

    def stop(self) -> None:
        self.pool.shutdown(wait=True)

