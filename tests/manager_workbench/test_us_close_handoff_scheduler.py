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


def _resolved_owner_handoff_fixture(monkeypatch, *, panel=True):
    """Real context/submit/Native path; only resolution and job/store edges are inert.

    Pins describe synthetic CANNOT_CONFIRM material, never VERIFIED financial facts.
    No provider, JobCoordinator, worker or physical Store is constructed/executed.
    """
    from copy import deepcopy
    import socket
    import subprocess
    from v4.manager_workbench import engines, service as service_module
    from v4.manager_workbench.inputs import native, source_bindings

    def forbidden(*args, **kwargs):
        raise AssertionError("network/provider/process/live job or Store is forbidden")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(JobCoordinator, "__init__", forbidden)
    monkeypatch.setattr(WorkbenchStore, "__init__", forbidden)
    monkeypatch.setattr(native, "previous_session", lambda *args, **kwargs: "20261016")
    owners = {
        "us_mapping": _pin(quote_source_cutoff=None),
        "membership": {"projection": {"owner": "FIXTURE_OBSERVED_ONLY", "codes": [], "effective_from": None}},
        "security_master": {"status": "CANNOT_CONFIRM", "source_cutoff": None},
        "other_owner": {"opaque": ["keep", {"source_cutoff": None}]},
    }
    if panel:
        owners["hk_panel"] = {"owner": "FIXTURE_HK_PANEL", "readiness": "CANNOT_CONFIRM", "source_cutoff": None}
    gaps = {"membership": "TARGET_EFFECTIVE_PERIOD_UNCONFIRMED", "security_master": "POINT_IN_TIME_UNCONFIRMED"}
    if not panel:
        gaps["hk_panel"] = "HK_PANEL_OWNER_NOT_BOUND"
    expected = deepcopy((owners, gaps))
    resolved = []
    current = {"owners": owners, "gaps": gaps}

    def resolve(config, context):
        resolved.append(context.model_dump(mode="json"))
        return deepcopy(current["owners"]), deepcopy(current["gaps"])

    monkeypatch.setattr(source_bindings, "resolve_bindings", resolve)

    class ObservedNative(native.NativeAdapters):
        def prepare_context(self, context):
            prepared = super().prepare_context(context)
            self.prepared_contexts.append(prepared.model_copy(deep=True))
            return prepared

    adapters = ObservedNative.__new__(ObservedNative)
    adapters.config = SimpleNamespace(us_root=Path("/unused-fixture-owner"), dynamic_source_bindings=True,
                                      capture_root=None, source_bindings={})
    adapters.calendar = None
    adapters._us_session = lambda cutoff: "20261016"
    adapters.prepared_contexts = []

    class MemoryStore:
        def __init__(self):
            self.cursors, self.plans, self.frozen = {}, [], None

        def cursor(self, key):
            return deepcopy(self.cursors.get(key))

        def set_cursor(self, key, value):
            self.cursors[key] = deepcopy(value)

        def list_plans(self, *args):
            return self.plans

        def get_plan(self, *args):
            return self.frozen

        def commit_plan(self, snapshot, *, freeze=False):
            assert freeze
            self.frozen = snapshot
            return snapshot

    class InertJobs:
        def __init__(self):
            self.submitted = []

        def submit(self, context, work):
            # The genuine ManagerService._work callback is captured, never run.
            assert work.__func__ is service_module.ManagerService._work
            job = SimpleNamespace(job_id="a" * 32, run_id="b" * 32, context=context,
                                  state=JobState.QUEUED, retryable=False)
            self.submitted.append(job)
            return job

        def get(self, job_id):
            return next(job for job in self.submitted if job.job_id == job_id)

    service = service_module.ManagerService.__new__(service_module.ManagerService)
    service.config = SimpleNamespace(rules_version="POSITIVE_OPERATING_RESEARCH_V1_OVERSOLD_PRICE40_V2")
    service.adapters, service.store, service.jobs = adapters, MemoryStore(), InertJobs()
    service.capture_jobs = None
    service.engines = engines
    return SimpleNamespace(service=service, adapters=adapters, resolved=resolved, expected=expected,
                           current=current, local=datetime(2026, 10, 17, 4, 20, tzinfo=HK),
                           deepcopy=deepcopy, service_module=service_module)


def test_real_handoff_preserves_resolved_owners_gaps_and_exact_us_pin(monkeypatch):
    fixture = _resolved_owner_handoff_fixture(monkeypatch)
    result = _us_close_handoff(fixture.service, calendar=Calendar(), local=fixture.local)
    assert result and result[0]["state"] == "SUBMITTED"
    context = fixture.service.jobs.submitted[0].context
    owners, gaps = fixture.expected
    assert context.scope_refs["owner_bindings"] == owners
    assert context.scope_refs["owner_binding_gaps"] == gaps
    assert context.scope_refs["owner_bindings"]["us_mapping"] == owners["us_mapping"]
    assert context.scope_refs["source_cutoff"] == owners["us_mapping"]["capture_cutoff"]
    assert context.cutoff == fixture.local.isoformat()
    assert context.source_sessions == {"hk_price": "20261016", "us": "20261016"}
    assert context.scope_refs["requested_lanes"] == ["US_MAPPING"]
    # Submit carries the exact already-resolved US pin; it cannot resolve a newer input.
    assert len(fixture.resolved) == 1
    assert len(fixture.adapters.prepared_contexts) == 2
    assert fixture.adapters.prepared_contexts[0].scope_refs["owner_bindings"] == owners
    assert fixture.current["owners"] == owners and fixture.current["gaps"] == gaps
    assert context.scope_refs["US_MAPPING_RUN_CONTRACT_V1"]["state"] == "CANNOT_CONFIRM"
    assert context.scope_refs["US_MAPPING_RUN_CONTRACT_V1"]["owners"]["connect"]["target_eligibility"] == "CANNOT_CONFIRM"
    before = context.model_dump(mode="json")
    published = fixture.service_module._publication_context(context, "2026-10-17T04:25:00+08:00")
    assert published.scope_refs["decision_input_cutoff"] == published.scope_refs["source_execution_cutoff"] == context.cutoff
    assert published.scope_refs["source_cutoff"] == owners["us_mapping"]["capture_cutoff"]
    assert published.scope_refs["processing_cutoff"] == "2026-10-17T04:25:00+08:00"
    assert published.scope_refs["owner_bindings"] == owners
    assert context.model_dump(mode="json") == before
    assert _us_close_handoff(fixture.service, calendar=Calendar(), local=fixture.local) == []
    assert len(fixture.service.jobs.submitted) == 1


def test_real_handoff_preopen_inherits_same_source_context_without_repair(monkeypatch):
    fixture = _resolved_owner_handoff_fixture(monkeypatch)
    assert _us_close_handoff(fixture.service, calendar=Calendar(), local=fixture.local)
    job = fixture.service.jobs.submitted[0]
    context = fixture.service_module._publication_context(job.context, "2026-10-17T04:25:00+08:00")
    lane = LaneResult(lane=Lane.US_MAPPING, state=LaneState.INPUT_MISSING, rows=[],
                      coverage=Coverage(scope_count=None, observed_count=None, assessed_count=None, unassessed_count=None),
                      input_sha256="d" * 64, rules_version=context.rules_version, run_id=job.run_id,
                      gaps=["FIXTURE_FINANCIAL_MATERIAL_UNCONFIRMED"])
    snapshot = seal_snapshot({"context": context.model_dump(mode="json"), "run_id": job.run_id,
        "input_sha256": "e" * 64, "generated_at": context.cutoff, "available_at": context.cutoff,
        "lanes": [lane.model_dump(mode="json")], "stocks": [], "counts": Counts().model_dump(mode="json"),
        "gaps": ["FIXTURE_FINANCIAL_MATERIAL_UNCONFIRMED"]})
    before = snapshot.model_dump(mode="json")
    fixture.service.store.plans = [snapshot]
    # A fresh PREOPEN resolution must not replace the saved US source context.
    fixture.current["owners"] = {"us_mapping": _pin(quote_sha256="9" * 64), "hk_panel": {"owner": "NEWER_UNCONFIRMED"}}
    fixture.current["gaps"] = {"hk_panel": "NEWER_OWNER_UNCONFIRMED"}
    monkeypatch.setattr(fixture.service_module, "now", lambda: "2026-10-20T09:25:00+08:00")
    frozen = fixture.service.freeze_preopen("20261020", cutoff=datetime(2026, 10, 20, 9, 25, tzinfo=HK))
    owners, gaps = fixture.expected
    assert frozen.context.scope_refs["owner_bindings"] == owners
    assert frozen.context.scope_refs["owner_binding_gaps"] == gaps
    assert frozen.context.cutoff == "2026-10-20T09:25:00+08:00"
    for key in ("source_cutoff", "source_execution_cutoff", "decision_input_cutoff", "processing_cutoff"):
        assert frozen.context.scope_refs[key] == context.scope_refs[key]
    assert frozen.context.source_sessions == context.source_sessions
    assert frozen.changes["phase_lane_contexts"]["US_MAPPING"]["scope_refs"]["owner_bindings"] == owners
    assert snapshot.model_dump(mode="json") == before
    assert frozen.stocks == [] and "PREOPEN_PARTIAL" in frozen.gaps


def test_real_handoff_keeps_missing_panel_and_material_unconfirmed(monkeypatch):
    fixture = _resolved_owner_handoff_fixture(monkeypatch, panel=False)
    assert _us_close_handoff(fixture.service, calendar=Calendar(), local=fixture.local)
    context = fixture.service.jobs.submitted[0].context
    assert "hk_panel" not in context.scope_refs["owner_bindings"]
    assert context.scope_refs["owner_binding_gaps"] == fixture.expected[1]
    assert context.scope_refs["owner_bindings"]["security_master"]["source_cutoff"] is None
    assert context.scope_refs["owner_bindings"]["us_mapping"]["quote_source_cutoff"] is None
    assert context.scope_refs["US_MAPPING_RUN_CONTRACT_V1"]["state"] == "CANNOT_CONFIRM"
