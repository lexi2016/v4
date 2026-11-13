from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from v4.manager_workbench.contracts import (
    HK, Coverage, InputBatch, JobRecord, JobState, Lane, LaneResult, LaneState,
    Phase, RunContext,
)
from v4.manager_workbench.jobs import JobCoordinator, StepFailure
from v4.manager_workbench.service import ManagerService
from v4.manager_workbench.store import StorageUnavailable, WorkbenchStore


def _input_body():
    return {
        "derivative": True,
        "authority": "ORIGINAL_OWNERS_ONLY",
        "context": {"scope_refs": {"requested_lanes": [Lane.US_MAPPING.value]}},
        "batches": [{"records": [{"text": "x" * 128_000}]}],
    }


def test_input_checkpoint_keeps_legacy_inline_json(tmp_path):
    store = WorkbenchStore(tmp_path)
    body = _input_body()

    input_sha = store.save_input_checkpoint("new-job", body)
    assert store.load_checkpoint("new-job", "LOAD_INPUTS") == body
    assert store.load_input_checkpoint("new-job") == (body, input_sha)
    assert store._path("input_snapshots", input_sha).stat().st_size > 100_000
    assert store._path("checkpoints", "new-job", "LOAD_INPUTS").stat().st_size > 100_000


def test_input_checkpoint_rejects_malformed_legacy_payload(tmp_path):
    store = WorkbenchStore(tmp_path)
    store.save_checkpoint("job", "LOAD_INPUTS", {"changed": True})
    with pytest.raises(StorageUnavailable, match="INPUT_CHECKPOINT_INVALID"):
        store.load_input_checkpoint("job")


def test_large_publish_checkpoint_fingerprint_exceeds_default_read_limit(tmp_path):
    store = WorkbenchStore(tmp_path)
    payload = {"rows": "x" * (64 * 1024 * 1024 + 1)}
    store.save_checkpoint("job", "PUBLISH", payload)

    fingerprint = store._file_fingerprint(
        store._path("checkpoints", "job", "PUBLISH"), max_bytes=128 * 1024 * 1024)
    assert fingerprint is not None
    assert fingerprint[0] > 64 * 1024 * 1024
    assert store.remove_publish_checkpoint_if_plan(
        "job", "20261113", "MANUAL", "job") is False
    assert store.load_checkpoint("job", "PUBLISH") == payload


def test_nonmatching_published_peer_keeps_pending_checkpoint(tmp_path):
    store = WorkbenchStore(tmp_path)
    pending = {"rows": "pending"}
    store.save_checkpoint("job", "PUBLISH", pending)
    store._write(store._path("snapshots", "job"), {"rows": "committed"}, immutable=True)
    store._write(store._path("catalog", "20261113", "MANUAL", "job"), {
        "run_id": "job", "product_sha256": "a" * 64,
    }, immutable=True)

    assert store.remove_publish_checkpoint_if_plan(
        "job", "20261113", "MANUAL", "job") is False
    assert store.load_checkpoint("job", "PUBLISH") == pending


class _Jobs:
    @staticmethod
    def update(job, *, step=None):
        if step:
            job.step = step


class _Engines:
    __name__ = "test_engines"

    def __init__(self):
        self.input_calls = 0
        self.lane_calls = 0

    def load_inputs(self, context, _adapters):
        self.input_calls += 1
        return [InputBatch(
            context=context,
            lane=Lane.US_MAPPING,
            universe_ref=None,
            records=[{"symbol": "HK.00001", "text": "x" * 32_000}],
            evidence_refs=[],
            input_sha256="a" * 64,
            scope_description="test input",
            coverage=Coverage(scope_count=1, observed_count=1, assessed_count=1, unassessed_count=0),
        )]

    def run_lanes(self, context, inputs, _audit):
        self.lane_calls += 1
        return [LaneResult(
            lane=Lane.US_MAPPING,
            state=LaneState.READY,
            rows=[],
            coverage=Coverage(scope_count=1, observed_count=1, assessed_count=1, unassessed_count=0),
            input_sha256=inputs[0].input_sha256,
            rules_version=context.rules_version,
            run_id=context.scope_refs["run_id"],
        )]

    @staticmethod
    def merge_decisions(_context, _lanes):
        return []


def _service(tmp_path):
    service = object.__new__(ManagerService)
    service.config = SimpleNamespace(
        prompt_version="test-prompt", model="test-model", announcement_reasoning_effort="low")
    service.adapters = object()
    service.engines = _Engines()
    service.executor = object()
    service.store = WorkbenchStore(tmp_path)
    service.jobs = _Jobs()
    return service


def _job(job_id=None):
    job_id = job_id or uuid4().hex
    context = RunContext(
        target_date="20261113",
        phase=Phase.MANUAL,
        cutoff=datetime(2026, 11, 13, 10, 0, tzinfo=HK).isoformat(),
        trigger="MANUAL",
        rules_version="test-rules",
        scope_refs={"requested_lanes": [Lane.US_MAPPING.value]},
    )
    return JobRecord(
        job_id=job_id,
        run_id=job_id,
        context=context,
        state=JobState.RUNNING,
        step="LOAD_INPUTS",
    )


def test_reused_result_does_not_create_an_input_copy_or_resume_checkpoint(tmp_path):
    service = _service(tmp_path)
    first = _job()
    first_run, state = service._work(first)
    assert state == JobState.SUCCEEDED
    assert service.store.load_checkpoint(first.job_id, "PUBLISH") is not None

    second = _job()
    second_run, second_state = service._work(second)

    assert (second_run, second_state) == (first_run, JobState.SUCCEEDED)
    assert service.engines.input_calls == 2
    assert service.engines.lane_calls == 1
    assert len(list((service.store.root / "input_snapshots").glob("*.json"))) == 1
    assert service.store.load_checkpoint(second.job_id, "LOAD_INPUTS") is None
    assert service.store.load_checkpoint(second.job_id, "PUBLISH") is None


def test_publish_checkpoint_remains_until_job_is_durably_done(tmp_path):
    service = _service(tmp_path)
    first = _job()
    run_id, _ = service._work(first)
    replayed = service._work(first)
    assert replayed == (run_id, JobState.SUCCEEDED)
    assert service.engines.lane_calls == 1
    assert service.store.load_checkpoint(first.job_id, "PUBLISH") is not None
    original_commit = service._commit_plan

    def fail_commit(_snapshot):
        raise OSError("fixture publication interruption")

    service._commit_plan = fail_commit
    with pytest.raises(StepFailure, match="PUBLISH_UNAVAILABLE"):
        service._work(first)
    assert service.store.load_checkpoint(first.job_id, "PUBLISH") is not None

    service._commit_plan = original_commit
    service._work(first)
    assert service.store.load_checkpoint(first.job_id, "PUBLISH") is not None


def test_terminal_done_retires_exact_checkpoint_peers_after_persist(tmp_path, monkeypatch):
    service = _service(tmp_path)
    job = _job()
    run_id, state = service._work(job)
    assert state == JobState.SUCCEEDED
    input_sha = service.store.load_input_checkpoint(job.job_id)[1]
    assert service.store.load_checkpoint(job.job_id, "LOAD_INPUTS") is not None
    assert service.store.load_checkpoint(job.job_id, "PUBLISH") is not None
    coordinator = JobCoordinator(service.store, workers=1)
    original_input_remove = service.store.remove_input_checkpoint_if_snapshot
    original_publish_remove = service.store.remove_publish_checkpoint_if_plan
    removed = []

    def checked_input_remove(job_id):
        saved_job = service.store.get_job(job_id)
        assert saved_job is not None and saved_job.step == "DONE"
        assert saved_job.state == JobState.SUCCEEDED
        removed.append("LOAD_INPUTS")
        return original_input_remove(job_id)

    def checked_publish_remove(job_id, date, phase, published_run_id):
        saved_job = service.store.get_job(job_id)
        assert saved_job is not None and saved_job.step == "DONE"
        assert saved_job.state == JobState.SUCCEEDED
        removed.append("PUBLISH")
        return original_publish_remove(job_id, date, phase, published_run_id)

    monkeypatch.setattr(service.store, "remove_input_checkpoint_if_snapshot", checked_input_remove)
    monkeypatch.setattr(service.store, "remove_publish_checkpoint_if_plan", checked_publish_remove)
    coordinator._execute(job, lambda _job: (run_id, JobState.SUCCEEDED), "scope")

    assert removed == ["LOAD_INPUTS", "PUBLISH"]
    assert service.store.get_job(job.job_id).state == JobState.SUCCEEDED
    assert service.store.load_checkpoint(job.job_id, "LOAD_INPUTS") is None
    assert service.store.load_checkpoint(job.job_id, "PUBLISH") is None
    assert service.store.load_input(input_sha) is not None
    coordinator.stop()


def test_retryable_partial_keeps_resume_checkpoints(tmp_path):
    store = WorkbenchStore(tmp_path)
    job = _job()
    store.save_input_checkpoint(job.job_id, _input_body())
    publish = {"rows": "pending output"}
    store.save_checkpoint(job.job_id, "PUBLISH", publish)
    coordinator = JobCoordinator(store, workers=1)

    def partial(_job):
        _job.retryable = True
        return "partial-run", JobState.PARTIAL

    coordinator._execute(job, partial, "scope")

    assert store.get_job(job.job_id).state == JobState.PARTIAL
    assert store.load_checkpoint(job.job_id, "LOAD_INPUTS") is not None
    assert store.load_checkpoint(job.job_id, "PUBLISH") == publish
    coordinator.stop()
