from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4.manager_workbench import api
from v4.manager_workbench import announcement_update as update_module
from v4.manager_workbench.announcement_candidate import read_pinned_candidates
from v4.manager_workbench.announcement_update import AnnouncementUpdate
from v4.manager_workbench.contracts import HK, JobState


class FakeStore:
    def __init__(self):
        self.values = {}
        self.root = "/tmp/mwb-announcement-test"
        self.files = {}
        self.io = SimpleNamespace(read_bytes=self._read, write_bytes=self._write)

    def _read(self, ref, **_kwargs):
        try:
            return self.files[ref]
        except KeyError as exc:
            raise FileNotFoundError(ref) from exc

    def _write(self, ref, data, **_kwargs):
        self.files[ref] = data

    def lock(self, _key):
        return nullcontext()

    def cursor(self, key):
        return self.values.get(key)

    def set_cursor(self, key, value):
        self.values[key] = value


class FakeJobs:
    def __init__(self):
        self.jobs = {}
        self.submissions = []

    def submit(self, context, worker):
        job = SimpleNamespace(job_id=f"{len(self.jobs) + 1:032x}", state=JobState.QUEUED,
                              step="QUEUED", context=context, completed_count=0, total_count=None,
                              failure_code=None, last_progress_at=None)
        self.jobs[job.job_id] = job
        self.submissions.append((context, worker))
        return job

    def get(self, job_id):
        return self.jobs[job_id]


def service():
    return SimpleNamespace(
        config=SimpleNamespace(capture_root="/private/capture", capture_lease_root="/private/leases"),
        store=FakeStore(), jobs=FakeJobs(),
    )


def test_pinned_projection_has_verified_candidate_and_failure_population():
    result = read_pinned_candidates()
    assert len(result["stocks"]) == 20
    assert result["counts"] == {
        "source_catalogue_articles": 392,
        "model_succeeded": 367,
        "selected_model_articles": 21,
        "model_candidate_stocks": 19,
        "reused_reviewed_stocks": 1,
        "failed": 18,
        "pending": 5,
        "body_gaps": 1,
        "displayed_stocks": 20,
    }
    assert result["target_trade_date"] == "CANNOT_CONFIRM"
    assert all(stock["reasons"] and stock["articles"] for stock in result["stocks"])
    assert sum(len(stock["articles"]) for stock in result["stocks"]) == 22


def test_announcement_get_is_pure_and_returns_pinned_evidence(monkeypatch):
    svc = service()
    def forbidden_grant(*_args, **_kwargs):
        raise AssertionError("GET must not acquire a capture lease")
    monkeypatch.setattr("v4.manager_workbench.inputs.capture_store.CaptureStore.grant", forbidden_grant)

    app = FastAPI()
    app.include_router(api.create_router(svc))
    response = TestClient(app).get(api.PREFIX + "/announcement-flash?target_date=20261016")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["counts"]["displayed_stocks"] == 20
    assert payload["data"]["counts"]["failed"] == 18
    assert payload["data"]["counts"]["pending"] == 5
    assert payload["data"]["job"] is None
    assert svc.jobs.submissions == []
    assert "/private/" not in str(payload["data"])


def test_unavailable_pinned_candidate_keeps_counts_unknown(monkeypatch):
    svc = service()
    def unavailable():
        raise update_module.CandidateEvidenceError("PINNED_EVIDENCE_SHA_MISMATCH")
    monkeypatch.setattr(update_module, "read_pinned_candidates", unavailable)

    value = AnnouncementUpdate(svc).read("20261016")

    assert value["state"] == "UNAVAILABLE"
    assert value["target_trade_date"] == "CANNOT_CONFIRM"
    assert value["counts"]["displayed_stocks"] is None
    assert value["gaps"][0]["code"] == "PINNED_EVIDENCE_SHA_MISMATCH"


def test_safe_runner_failure_code_is_visible_in_announcement_status():
    svc = service()
    job_id = "c" * 32
    failure_code = "FLASH_PIPELINE_RUNTIMEERROR"
    svc.jobs.jobs[job_id] = SimpleNamespace(
        job_id=job_id, state=JobState.FAILED,
        context=SimpleNamespace(target_date="20261016"), step="FAILED",
        completed_count=0, total_count=None, failure_code=failure_code,
        last_progress_at="2026-10-16T11:23:53+08:00",
    )
    svc.store.values["announcement_flash_latest"] = {"job_id": job_id, "target_date": "20261016"}
    svc.store.files[f"announcement_flash/jobs/{job_id}/progress.json"] = update_module._canonical({
        "step": "FAILED", "failure_code": failure_code,
        "diagnostic": {"exception_type": "RuntimeError", "stack_frames": []},
    })

    value = AnnouncementUpdate(svc).read("20261016")

    assert value["job"]["failure_code"] == failure_code


def test_flash_runner_launch_disables_bytecode_cache(monkeypatch):
    svc = service()
    job_id = "d" * 32
    capture_raw = b"verified capture product"
    capture_sha = update_module._sha(capture_raw)
    saved_ref = {"artifact_ref": f"products/{capture_sha}.json", "sha256": capture_sha}
    command_calls = []

    class FakeCaptureStore:
        def __init__(self, *_args, **_kwargs):
            self.io = SimpleNamespace(read_bytes=lambda *_args, **_kwargs: capture_raw)

        def grant(self, **_kwargs):
            pass

        def revoke(self):
            pass

    class FinishedProcess:
        returncode = 0

        def poll(self):
            return self.returncode

    def fake_popen(command, **kwargs):
        command_calls.append((command, kwargs))
        return FinishedProcess()

    monkeypatch.setattr("v4.manager_workbench.inputs.capture_store.CaptureStore", FakeCaptureStore)
    monkeypatch.setattr("v4.manager_workbench.inputs.capture.capture_window",
                        lambda *_args, **_kwargs: {"saved_ref": saved_ref})
    svc.jobs = SimpleNamespace(update=lambda *_args, **_kwargs: None)
    job = SimpleNamespace(
        job_id=job_id,
        context=SimpleNamespace(model_copy=lambda **_kwargs: SimpleNamespace(target_date="20261016")),
        completed_count=0,
        total_count=None,
        execution_refs=[],
    )

    try:
        AnnouncementUpdate(svc, popen=fake_popen)._work(job)
    except update_module.StepFailure as exc:
        assert str(exc) == "FLASH_RESULT_INVALID"
    else:
        raise AssertionError("missing runner result should stop after launch")

    assert len(command_calls) == 1
    command, kwargs = command_calls[0]
    assert command[0] == str(update_module.RUNNER_PYTHON)
    assert command[1] == "-B"
    assert command[2] == str(update_module.RUNNER_SCRIPT)
    assert kwargs["env"] == {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}


def test_manual_update_post_is_idempotent_for_the_same_minute(monkeypatch):
    svc = service()
    now = datetime(2026, 10, 16, 10, 30, tzinfo=HK)
    update = AnnouncementUpdate(svc, clock=lambda: now)
    first = update.start("20261016")
    second = update.start("20261016")

    assert first.job_id == second.job_id
    assert len(svc.jobs.submissions) == 1
    context, worker = svc.jobs.submissions[0]
    assert context.scope_refs["capture_operation"] == "ANNOUNCEMENT_FLASH_INCREMENTAL"
    assert context.scope_refs["requested_lanes"] == []
    assert callable(worker)


def test_manual_update_rejects_a_different_target_while_job_is_active():
    svc = service()
    now = datetime(2026, 10, 16, 10, 30, tzinfo=HK)
    update = AnnouncementUpdate(svc, clock=lambda: now)
    active = update.start("20261015")

    try:
        update.start("20261016")
    except update_module.JobConflict as exc:
        assert "20261015" in str(exc)
    else:
        raise AssertionError("active job for another target date must not be accepted")

    assert active.state == JobState.QUEUED
    assert len(svc.jobs.submissions) == 1


def test_http_post_uses_the_announcement_route_and_never_codex_runs(monkeypatch):
    svc = service()
    now = datetime(2026, 10, 16, 10, 31, tzinfo=HK)
    original = api.AnnouncementUpdate

    class FixedClockUpdate(original):
        def __init__(self, service_arg):
            super().__init__(service_arg, clock=lambda: now)

    monkeypatch.setattr(api, "AnnouncementUpdate", FixedClockUpdate)
    app = FastAPI()
    app.include_router(api.create_router(svc))
    client = TestClient(app)
    response = client.post(api.PREFIX + "/announcement-flash/update", json={"target_date": "20261016"})

    assert response.status_code == 202
    assert response.json()["data"]["target_date"] == "20261016"
    assert len(svc.jobs.submissions) == 1
    readback = client.get(api.PREFIX + "/announcement-flash?target_date=20261016")
    assert readback.status_code == 200, readback.text
    assert len(svc.jobs.submissions) == 1


def test_http_post_rejects_cross_date_active_job_with_conflict(monkeypatch):
    svc = service()
    now = datetime(2026, 10, 16, 10, 32, tzinfo=HK)
    original = api.AnnouncementUpdate

    class FixedClockUpdate(original):
        def __init__(self, service_arg):
            super().__init__(service_arg, clock=lambda: now)

    monkeypatch.setattr(api, "AnnouncementUpdate", FixedClockUpdate)
    app = FastAPI()
    app.include_router(api.create_router(svc))
    client = TestClient(app)
    active = client.post(api.PREFIX + "/announcement-flash/update", json={"target_date": "20261015"})
    assert active.status_code == 202

    rejected = client.post(api.PREFIX + "/announcement-flash/update", json={"target_date": "20261016"})

    assert rejected.status_code == 409
    assert "20261015" in str(rejected.json())
    assert len(svc.jobs.submissions) == 1


def test_incremental_result_round_trips_through_get_with_new_reason():
    svc = service()
    job_id = "a" * 32
    article = {"article_id": "EASTMONEY:AN202610160099", "title": "新公告", "publication_date": "2026-10-16",
               "symbol": "HK.12345", "name": "新公司", "disposition": "SELECTED_EVENT", "direction": "POSITIVE",
               "selection_basis": "新增事件信息", "reason": "公司披露新增业务安排，具体影响需人工核实。", "impact": [],
               "body_sha256": "1" * 64, "source_sha256": "2" * 64, "source_origins": [],
               "review_status": "MODEL_CANDIDATE_UNREVIEWED", "reuse_status": None}
    result = {"schema": "v4.manager_workbench.announcement_flash_result.v1", "job_id": job_id,
              "state": "PARTIAL", "target_trade_date": "20261016", "updated_at": "2026-10-16T10:00:00+08:00",
              "counts": {"new_candidate_stocks": 1, "failed": 0, "queue_pending": 0, "body_gaps": 0},
              "stocks": [{"symbol": article["symbol"], "name": article["name"], "reasons": [article["reason"]],
                          "articles": [article], "review_status": article["review_status"], "reuse_status": None}],
              "failures": [], "pending": [], "gaps": [],
              "provenance": {"historical_outcomes": []}}
    raw = update_module._canonical(result) + b"\n"
    svc.store.files[f"announcement_flash/jobs/{job_id}/result.json"] = raw
    svc.store.values["announcement_flash_result_index"] = {
        "items": [{"job_id": job_id, "target_date": "20261016", "result_sha256": update_module._sha(raw)}]
    }

    view = AnnouncementUpdate(svc).read("20261016")

    assert view["incremental"]["job_id"] == job_id
    assert view["incremental"]["stocks"][0]["articles"][0]["reason"] == article["reason"]
    assert any(stock["symbol"] == "HK.12345" and article["reason"] in stock["reasons"]
               for stock in view["stocks"] for article in stock["articles"])
    assert view["counts"]["displayed_stocks"] == 21
