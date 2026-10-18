from datetime import datetime
from pathlib import Path
from threading import Event
import time
from types import SimpleNamespace

from v4.manager_workbench.contracts import (
    HK, Counts, Coverage, JobState, Lane, LaneResult, LaneState, Phase, RunContext,
    seal_snapshot,
)
from v4.manager_workbench.jobs import JobCoordinator, StepFailure
from v4.manager_workbench.scheduler import _us_close_handoff
from v4.manager_workbench.store import WorkbenchStore


class Calendar:
    def next_hk_session(self, day):
        assert day == "20261016"
        return "20261020"

    def is_hk_session(self, day):
        return day == "20261020"


def _pin(**updates):
    return {
        "capture_phase": "POST_CLOSE",
        "capture_status": "READY",
        "capture_session_date": "20261016",
        "quote_sha256": "a" * 64,
        "quote_relative": "research/peripherals/20261017/external_finance.json",
        "owner_receipt_sha256": "b" * 64,
        "owner_receipt_relative": "receipts/research/peripherals/20261017/external_finance.json",
        "owner_manifest_sha256": "c" * 64,
        "owner_manifest_ref": "research/peripherals/manifest.json",
        "capture_cutoff": "2026-10-16T16:18:00-04:00",
        **updates,
    }


class Service:
    """Small service adapter using the real JobCoordinator and WorkbenchStore."""

    def __init__(self, root: Path, pin, worker):
        self.adapters = SimpleNamespace(
            config=SimpleNamespace(us_root=Path("/unused-test-root")),
            _us_session=lambda cutoff: "20261016",
        )
        self.pin = pin
        self.store = WorkbenchStore(root)
        self.jobs = JobCoordinator(self.store, workers=2)
        self.worker = worker
        self.submissions = []

    def context(self, target, phase, **kwargs):
        return SimpleNamespace(scope_refs={"owner_bindings": {"us_mapping": self.pin}})

    def _make_context(self, target, phase, cutoff, scope_refs, lanes):
        refs = dict(scope_refs)
        refs["requested_lanes"] = [lane.value for lane in lanes]
        return RunContext(
            target_date=target,
            phase=phase,
            cutoff=cutoff.astimezone(HK).isoformat(),
            trigger="SCHEDULED",
            source_sessions={"us": "20261016"},
            rules_version="TEST_HANDOFF",
            scope_refs=refs,
        )

    def submit(self, target, phase, *, trigger="SCHEDULED", cutoff, lanes, scope_refs):
        context = self._make_context(target, phase, cutoff, scope_refs, lanes)
        job = self.jobs.submit(context, self.worker)
        self.submissions.append(job.job_id)
        return job

    def retry(self, job_id):
        previous = self.jobs.get(job_id)
        if previous.state == JobState.PARTIAL:
            context = previous.context.model_copy(deep=True)
            context.scope_refs["resume_from_job"] = previous.job_id
            job = self.jobs.submit(context, self.worker)
        else:
            job = self.jobs.submit(previous.context, self.worker, retry_job_id=job_id)
        self.submissions.append(job.job_id)
        return job

    def stop(self):
        self.jobs.stop()


def _succeed(job):
    return job.run_id, JobState.SUCCEEDED


def _saved_partial_plan(service, job):
    context = job.context.model_copy(deep=True)
    context.scope_refs["run_id"] = job.run_id
    context.scope_refs["mwb_run_id"] = job.run_id
    lane = LaneResult(
        lane=Lane.US_MAPPING,
        state=LaneState.FAILED,
        rows=[{"failure_code": "TEST_RETRYABLE"}],
        coverage=Coverage(scope_count=1, observed_count=0, assessed_count=0, unassessed_count=1),
        input_sha256="d" * 64,
        rules_version=context.rules_version,
        run_id=job.run_id,
    )
    snapshot = seal_snapshot({
        "context": context.model_dump(mode="json"),
        "run_id": job.run_id,
        "input_sha256": "e" * 64,
        "generated_at": "2026-10-17T04:20:00+08:00",
        "available_at": "2026-10-17T04:20:00+08:00",
        "lanes": [lane.model_dump(mode="json")],
        "stocks": [],
        "counts": Counts(unassessed=0).model_dump(mode="json"),
        "gaps": ["LANE_STEPS_INCOMPLETE"],
    })
    service.store.commit_plan(snapshot)
    job.retryable = True
    job.failed_steps = [Lane.US_MAPPING.value]
    service.store.save_job(job)


def _wait_for_state(service, job_id, expected):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.jobs.get(job_id)
        if job.state == expected:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {expected.value}")


def _wait_for_scope_release(service, job_id):
    scope = service.jobs._scope(service.jobs.get(job_id).context)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if scope not in service.jobs._active:
            return
        time.sleep(0.01)
    raise AssertionError(f"job scope {scope} remained active")


def test_new_artifact_stays_pending_while_old_same_lane_job_is_active(tmp_path):
    release_old = Event()
    old_pin = _pin(quote_sha256="d" * 64, owner_receipt_sha256="e" * 64)
    service = Service(tmp_path, _pin(), _succeed)
    local = datetime.fromisoformat("2026-10-17T04:20:00+08:00")
    old_context = service._make_context(
        "20261020", Phase.NEXT_DAY, local,
        {
            "owner_bindings": {"us_mapping": old_pin},
            "us_close_handoff_key": "older-input-key",
            "owner_artifact_sha256": old_pin["quote_sha256"],
            "owner_receipt_sha256": old_pin["owner_receipt_sha256"],
            "owner_manifest_sha256": old_pin["owner_manifest_sha256"],
            "source_cutoff": old_pin["capture_cutoff"],
        },
        [Lane.US_MAPPING],
    )

    def blocked_worker(job):
        assert release_old.wait(5)
        return job.run_id, JobState.SUCCEEDED

    try:
        old_job = service.jobs.submit(old_context, blocked_worker)

        # JobCoordinator._scope ignores the changed owner SHA and returns this
        # active same-target/phase/lane job. The scheduler must not cursor it.
        assert _us_close_handoff(service, calendar=Calendar(), local=local) == []
        assert list((service.store.root / "cursors").glob("*.json")) == []
        assert service.submissions == [old_job.job_id]

        release_old.set()
        _wait_for_state(service, old_job.job_id, JobState.SUCCEEDED)
        _wait_for_scope_release(service, old_job.job_id)
        submitted = _us_close_handoff(service, calendar=Calendar(), local=local)

        assert len(submitted) == 1
        assert submitted[0]["target_date"] == "20261020"
        assert submitted[0]["job_id"] != old_job.job_id
        assert service.submissions == [old_job.job_id, submitted[0]["job_id"]]
        cursor = service.store.cursor("us_close_" + submitted[0]["input_key"])
        assert cursor["artifact_sha256"] == "a" * 64
        assert cursor["receipt_sha256"] == "b" * 64
        _wait_for_state(service, submitted[0]["job_id"], JobState.SUCCEEDED)
        assert _us_close_handoff(service, calendar=Calendar(), local=local) == []
    finally:
        release_old.set()
        service.stop()


def test_retryable_job_retries_exact_input_and_remains_idempotent(tmp_path):
    attempts = 0

    def fail_once(job):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise StepFailure("TEST_RETRYABLE", retryable=True)
        return job.run_id, JobState.SUCCEEDED

    service = Service(tmp_path, _pin(), fail_once)
    local = datetime.fromisoformat("2026-10-17T04:20:00+08:00")
    try:
        first = _us_close_handoff(service, calendar=Calendar(), local=local)
        assert len(first) == 1
        _wait_for_state(service, first[0]["job_id"], JobState.FAILED)

        retried = _us_close_handoff(service, calendar=Calendar(), local=local)
        assert len(retried) == 1
        assert retried[0]["state"] == "RETRY_SUBMITTED"
        assert retried[0]["job_id"] == first[0]["job_id"]
        _wait_for_state(service, retried[0]["job_id"], JobState.SUCCEEDED)

        assert _us_close_handoff(service, calendar=Calendar(), local=local) == []
        assert attempts == 2
        assert len(service.submissions) == 2
    finally:
        service.stop()


def test_cursor_write_failure_recovers_saved_retryable_partial_plan(tmp_path, monkeypatch):
    attempts = 0
    service = Service(tmp_path, _pin(), _succeed)
    local = datetime.fromisoformat("2026-10-17T04:20:00+08:00")
    original_set_cursor = service.store.set_cursor

    def partial_then_success(job):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            _saved_partial_plan(service, job)
            return job.run_id, JobState.PARTIAL
        return job.run_id, JobState.SUCCEEDED

    service.worker = partial_then_success

    def fail_cursor_once(key, value):
        if key.startswith("us_close_"):
            monkeypatch.setattr(service.store, "set_cursor", original_set_cursor)
            raise OSError("simulated cursor persistence failure")
        original_set_cursor(key, value)

    monkeypatch.setattr(service.store, "set_cursor", fail_cursor_once)
    try:
        assert _us_close_handoff(service, calendar=Calendar(), local=local) == []
        first_job_id = service.submissions[0]
        _wait_for_state(service, first_job_id, JobState.PARTIAL)
        _wait_for_scope_release(service, first_job_id)
        assert len(service.store.list_plans("20261020", Phase.NEXT_DAY.value)) == 1
        first_job = service.jobs.get(first_job_id)
        assert first_job.state == JobState.PARTIAL
        assert first_job.retryable is True

        retry = _us_close_handoff(service, calendar=Calendar(), local=local)
        assert len(retry) == 1
        assert retry[0]["state"] == "RETRY_SUBMITTED"
        assert retry[0]["job_id"] != first_job.job_id
        assert service.store.cursor("us_close_" + retry[0]["input_key"])["job_id"] == retry[0]["job_id"]
        _wait_for_state(service, retry[0]["job_id"], JobState.SUCCEEDED)

        assert _us_close_handoff(service, calendar=Calendar(), local=local) == []
        assert attempts == 2
        assert len(service.submissions) == 2
    finally:
        service.stop()


def test_missing_or_non_post_close_owner_artifact_does_not_submit(tmp_path):
    service = Service(tmp_path, _pin(capture_status="PARTIAL"), _succeed)
    local = datetime.fromisoformat("2026-10-17T04:20:00+08:00")
    try:
        assert _us_close_handoff(service, calendar=Calendar(), local=local) == []
        assert service.submissions == []
        assert service.store.list_plans("20261020", Phase.NEXT_DAY.value) == []
    finally:
        service.stop()
