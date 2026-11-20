"""Temp-store regression checks for retries, persisted claims and legacy recovery."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import os

import pytest

from v4.manager_workbench import jobs as job_module
from v4.manager_workbench.contracts import JobRecord, JobState, Phase, RunContext
from v4.manager_workbench.jobs import JobConflict, JobCoordinator
from v4.manager_workbench.store import StorageConflict, WorkbenchStore


@pytest.fixture(autouse=True)
def no_runtime_notifications(monkeypatch):
    # Deployed-overlay verification must never publish runtime graph events.
    if hasattr(job_module, "_graph_notify"):
        monkeypatch.setattr(job_module, "_graph_notify", lambda *a, **k: None)


def context():
    return RunContext(target_date="20261120", phase=Phase.MANUAL,
        cutoff="2026-11-20T10:00:00+08:00", trigger="MANUAL", rules_version="test")


def old_job(store, state=JobState.FAILED, *, pid=-1, claim=False):
    job = JobRecord(job_id="legacy", run_id="legacy", context=context(), state=state,
        step="RUN_LANES", retryable=True, execution_refs=[{"kind": "host", "pid": pid}])
    store.save_job(job)
    if claim:
        store.set_claim(JobCoordinator._scope(job.context), job.job_id)
    return job


def test_retry_refreshes_owner_and_remains_active_across_instances(tmp_path):
    store = WorkbenchStore(tmp_path)
    original = old_job(store)
    entered, release = Event(), Event()
    first = JobCoordinator(store)
    second = JobCoordinator(WorkbenchStore(tmp_path))
    calls = []
    def worker(job):
        calls.append(job.attempt_id)
        entered.set()
        assert release.wait(5)
        return job.run_id, JobState.SUCCEEDED
    try:
        retried = first.submit(original.context, worker, retry_job_id=original.job_id)
        assert entered.wait(5)
        assert retried.attempt_id
        assert retried.execution_refs == [{"kind": "host", "pid": os.getpid(), "attempt_id": retried.attempt_id}]
        assert second.store.recover_orphan_attempts() == 0
        saved = second.submit(original.context, worker)
        assert saved.job_id == retried.job_id and saved.attempt_id == retried.attempt_id
        with pytest.raises(JobConflict, match="ACTIVE_JOB_CONFLICT"):
            second.submit(original.context, worker, retry_job_id=original.job_id)
        claim = store._claim(first._scope(original.context))
        assert claim["attempt_id"] == retried.attempt_id and claim["pid"] == os.getpid()
        assert calls == [retried.attempt_id]
    finally:
        release.set()
        first.stop()
        second.stop()


def test_recovery_waits_for_retry_record_and_claim_transaction(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path)
    original = old_job(store)
    coordinator = JobCoordinator(store)
    queued, release = Event(), Event()
    saved = store.save_job
    def pause_after_save(job, **kwargs):
        saved(job, **kwargs)
        if job.state == JobState.QUEUED:
            queued.set()
            assert release.wait(5)
    monkeypatch.setattr(store, "save_job", pause_after_save)
    other = WorkbenchStore(tmp_path)
    with ThreadPoolExecutor(2) as pool:
        submitted = pool.submit(coordinator.submit, original.context,
            lambda job: (job.run_id, JobState.SUCCEEDED), retry_job_id=original.job_id)
        assert queued.wait(5)
        recovering = pool.submit(other.recover_orphan_attempts)
        release.set()
        try:
            submitted.result(5)
            assert recovering.result(5) == 0
        finally:
            coordinator.stop()
    assert store.get_job(original.job_id).state == JobState.SUCCEEDED


def test_enqueue_failure_is_retryable_and_releases_claim(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path)
    coordinator = JobCoordinator(store)
    def fail(*a, **k):
        raise RuntimeError("executor unavailable")
    monkeypatch.setattr(coordinator.pool, "submit", fail)
    try:
        with pytest.raises(RuntimeError, match="executor unavailable"):
            coordinator.submit(context(), lambda job: pytest.fail("worker started"))
        row = next((store.root / "attempts").glob("*.json"))
        saved = store.get_job(row.stem)
        assert saved.state == JobState.INTERRUPTED
        assert saved.retryable and saved.failure_code == "ENQUEUE_FAILED"
        assert not store._claim(coordinator._scope(context()))["job_id"]
    finally:
        coordinator.stop()


def test_claim_write_failure_cannot_leave_live_queued_attempt(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path)
    coordinator = JobCoordinator(store)
    def fail(*a, **k):
        raise OSError("claim storage unavailable")
    monkeypatch.setattr(store, "set_claim", fail)
    try:
        with pytest.raises(OSError, match="claim storage unavailable"):
            coordinator.submit(context(), lambda job: pytest.fail("worker started"))
        row = next((store.root / "attempts").glob("*.json"))
        assert store.get_job(row.stem).state == JobState.INTERRUPTED
    finally:
        coordinator.stop()


def test_crash_before_claim_is_recovered_after_owner_dies(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path)
    coordinator = JobCoordinator(store)
    def crash(*a, **k):
        raise KeyboardInterrupt("simulated process loss")
    monkeypatch.setattr(store, "set_claim", crash)
    try:
        with pytest.raises(KeyboardInterrupt):
            coordinator.submit(context(), lambda job: pytest.fail("worker started"))
        other = WorkbenchStore(tmp_path)
        monkeypatch.setattr(other, "_pid_alive", lambda pid: False)
        assert other.recover_orphan_attempts() == 1
        row = next((store.root / "attempts").glob("*.json"))
        assert other.get_job(row.stem).state == JobState.INTERRUPTED
    finally:
        coordinator.stop()


@pytest.mark.parametrize("claim", [False, True])
def test_legacy_live_work_is_not_interrupted_or_duplicated(tmp_path, claim):
    store = WorkbenchStore(tmp_path)
    legacy = old_job(store, JobState.RUNNING, pid=os.getpid() if not claim else -1, claim=claim)
    coordinator = JobCoordinator(store)
    try:
        assert store.get_job(legacy.job_id).state == JobState.RUNNING
        existing = coordinator.submit(context(), lambda job: pytest.fail("duplicate worker"))
        assert existing.job_id == legacy.job_id
    finally:
        coordinator.stop()


def test_old_attempt_cannot_overwrite_retry_or_release_new_claim(tmp_path):
    store = WorkbenchStore(tmp_path)
    old = old_job(store)
    old.attempt_id = "old"
    store.save_job(old, replace_attempt=True)
    new = old.model_copy(deep=True)
    new.attempt_id = "new"
    new.state = JobState.QUEUED
    store.save_job(new, replace_attempt=True)
    scope = JobCoordinator._scope(new.context)
    store.set_claim(scope, new.job_id, attempt_id=new.attempt_id)
    with pytest.raises(StorageConflict, match="STALE_JOB_ATTEMPT"):
        store.save_job(old, expected_attempt_id=old.attempt_id)
    with pytest.raises(StorageConflict, match="STALE_JOB_ATTEMPT"):
        store.save_job(old)  # direct worker progress writes are fenced too
    store.clear_claim(scope, old.job_id, old.attempt_id)
    assert store._claim(scope)["attempt_id"] == "new"
    assert store.get_job(new.job_id).state == JobState.QUEUED
