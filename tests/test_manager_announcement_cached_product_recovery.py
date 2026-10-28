from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4.manager_workbench import api
from v4.manager_workbench import announcement_update as update_module
from v4.manager_workbench.announcement_update import AnnouncementUpdate
from v4.manager_workbench.contracts import JobState, Phase, RunContext


class MemoryStore:
    def __init__(self, root: Path):
        self.root = str(root)
        self.files: dict[str, bytes] = {}
        self.values: dict[str, dict] = {}
        self.io = SimpleNamespace(read_bytes=self._read, write_bytes=self._write)

    def _read(self, ref: str, **_kwargs) -> bytes:
        try:
            return self.files[ref]
        except KeyError as exc:
            raise FileNotFoundError(ref) from exc

    def _write(self, ref: str, raw: bytes, **_kwargs) -> None:
        self.files[ref] = raw

    def lock(self, _key: str):
        return nullcontext()

    def cursor(self, key: str):
        return self.values.get(key)

    def set_cursor(self, key: str, value: dict) -> None:
        self.values[key] = value


class MemoryJobs:
    def __init__(self, source_job):
        self.jobs = {source_job.job_id: source_job}
        self.submissions = []

    def get(self, job_id: str):
        try:
            return self.jobs[job_id]
        except KeyError as exc:
            raise KeyError("JOB_NOT_FOUND") from exc

    def submit(self, context, worker):
        job_id = f"{len(self.jobs) + 1:032x}"
        job = SimpleNamespace(job_id=job_id, state=JobState.QUEUED, step="QUEUED", context=context,
                              completed_count=0, total_count=None, execution_refs=[], failure_code=None,
                              retryable=False, failed_steps=[], last_progress_at=None)
        self.jobs[job_id] = job
        self.submissions.append((context, worker))
        return job

    def update(self, job, *, state=None, step=None, finished=False):
        if state is not None:
            job.state = state
        if step is not None:
            job.step = step


def _product():
    return {
        "schema_version": "mwb.capture.window.v1",
        "owner": "v4.manager_workbench.capture_announcements",
        "source": "EASTMONEY_HK",
        "saved_ref": None,
        "target_trade_date": update_module.CACHED_PRODUCT_RECOVERY_TARGET_DATE,
        "window": {"research_cutoff": update_module.CACHED_PRODUCT_RECOVERY_CUTOFF},
        "rows": [],
    }


def _service(tmp_path: Path, product: dict | None = None):
    product = product or _product()
    raw = update_module._canonical(product)
    product_sha = update_module._sha(raw)
    capture_root = tmp_path / "capture"
    product_path = capture_root / "products" / f"{product_sha}.json"
    product_path.parent.mkdir(parents=True)
    product_path.write_bytes(raw)
    source_id = update_module.CACHED_PRODUCT_RECOVERY_SOURCE_JOB_ID
    target_date = update_module.CACHED_PRODUCT_RECOVERY_TARGET_DATE
    cutoff = update_module.CACHED_PRODUCT_RECOVERY_CUTOFF
    source_context = RunContext(
        target_date=target_date, phase=Phase.MANUAL, cutoff=cutoff, trigger="MANUAL",
        rules_version="V4_ANNOUNCEMENT_FLASH_INCREMENTAL_V1",
        scope_refs={"requested_lanes": [], "capture_operation": "ANNOUNCEMENT_FLASH_INCREMENTAL",
                    "capture_input_sha256": update_module.digest(
                        {"target_date": target_date, "manual_slot": cutoff})},
    )
    source_job = SimpleNamespace(
        job_id=source_id, state=JobState.FAILED, step=update_module.CACHED_PRODUCT_RECOVERY_FAILURE_STEP,
        failure_code=update_module.CACHED_PRODUCT_RECOVERY_FAILURE_CODE, retryable=False,
        failed_steps=[update_module.CACHED_PRODUCT_RECOVERY_FAILURE_STEP], context=source_context,
    )
    store = MemoryStore(tmp_path / "state")
    store.set_cursor("announcement_flash_latest", {"job_id": source_id, "target_date": target_date,
                                                    "slot": cutoff, "state": "QUEUED"})
    service = SimpleNamespace(
        config=SimpleNamespace(capture_root=capture_root, capture_lease_root=None,
                               shared_root=tmp_path / "shared"),
        store=store,
        jobs=MemoryJobs(source_job),
    )
    return service, source_job, product_path, raw, product_sha


def _post(app: FastAPI, payload: dict):
    with TestClient(app) as client:
        return client.post(api.PREFIX + "/announcement-flash/recover-cached-product", json=payload)


def test_cached_product_route_submits_one_new_idempotent_job_with_exact_binding(tmp_path, monkeypatch):
    service, source_job, product_path, raw, product_sha = _service(tmp_path)
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", product_sha)
    app = FastAPI()
    app.include_router(api.create_router(service))
    payload = {"failed_job_id": source_job.job_id, "product_sha256": product_sha}

    first = _post(app, payload)
    assert first.status_code == 202, first.text
    first_data = first.json()["data"]
    new_job_id = first_data["job_id"]
    assert new_job_id != source_job.job_id
    assert first_data["source_job_id"] == source_job.job_id
    assert first_data["capture_product_sha256"] == product_sha
    context = service.jobs.get(new_job_id).context
    recovery = context.scope_refs["announcement_cached_product_recovery"]
    assert context.scope_refs["capture_operation"] == update_module.CACHED_PRODUCT_RECOVERY_OPERATION
    assert context.scope_refs["capture_input_sha256"] == update_module.digest(recovery)
    assert recovery == {
        "schema": update_module.CACHED_PRODUCT_RECOVERY_SCHEMA,
        "source_job_id": source_job.job_id,
        "source_failure_code": update_module.CACHED_PRODUCT_RECOVERY_FAILURE_CODE,
        "source_failure_step": update_module.CACHED_PRODUCT_RECOVERY_FAILURE_STEP,
        "capture_product_sha256": product_sha,
        "target_date": update_module.CACHED_PRODUCT_RECOVERY_TARGET_DATE,
        "cutoff": update_module.CACHED_PRODUCT_RECOVERY_CUTOFF,
    }
    assert "announcement_recovery_parent" not in context.scope_refs
    assert service.store.values["announcement_flash_latest"]["job_id"] == new_job_id
    assert product_path.read_bytes() == raw
    assert f"announcement_flash/jobs/{source_job.job_id}/input.json" not in service.store.files
    assert f"announcement_flash/jobs/{source_job.job_id}/result.json" not in service.store.files

    second = _post(app, payload)
    assert second.status_code == 202, second.text
    assert second.json()["data"]["job_id"] == new_job_id
    assert len(service.jobs.submissions) == 1

    extra = _post(app, {**payload, "artifact_ref": f"products/{product_sha}.json"})
    assert extra.status_code == 422
    assert len(service.jobs.submissions) == 1


@pytest.mark.parametrize("field,value", [
    ("schema_version", "mwb.capture.window.invalid"),
    ("owner", "other.owner"),
    ("source", "HKEX_OFFICIAL"),
    ("target_trade_date", "20261015"),
    ("saved_ref", {"artifact_ref": "products/forbidden.json"}),
])
def test_cached_product_identity_mismatch_rejects_before_submission(tmp_path, monkeypatch, field, value):
    product = _product()
    product[field] = value
    service, source_job, _product_path, _raw, product_sha = _service(tmp_path, product)
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", product_sha)
    with pytest.raises(ValueError, match="CACHE_RECOVERY_PRODUCT_IDENTITY_INVALID"):
        AnnouncementUpdate(service).start_cached_product_recovery(source_job.job_id, product_sha)
    assert service.jobs.submissions == []
    assert service.store.values["announcement_flash_latest"]["job_id"] == source_job.job_id


@pytest.mark.parametrize("request_field", ["failed_job_id", "product_sha256"])
def test_cached_product_route_rejects_unbound_request_identity(tmp_path, monkeypatch, request_field):
    service, source_job, _product_path, _raw, product_sha = _service(tmp_path)
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", product_sha)
    value = "f" * (32 if request_field == "failed_job_id" else 64)
    with pytest.raises(ValueError, match="CACHE_RECOVERY_REQUEST_BINDING_INVALID"):
        AnnouncementUpdate(service).start_cached_product_recovery(
            value if request_field == "failed_job_id" else source_job.job_id,
            value if request_field == "product_sha256" else product_sha)
    assert service.jobs.submissions == []


@pytest.mark.parametrize("mutation", [
    "state", "failure_code", "step", "retryable", "target_date", "cutoff", "operation", "rules_version",
])
def test_cached_product_route_rejects_nonmatching_failed_attempt(tmp_path, monkeypatch, mutation):
    service, source_job, _product_path, _raw, product_sha = _service(tmp_path)
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", product_sha)
    if mutation == "state":
        source_job.state = JobState.RUNNING
    elif mutation == "failure_code":
        source_job.failure_code = "OTHER_FAILURE"
    elif mutation == "step":
        source_job.step = "FLASH_SELECTION"
    elif mutation == "retryable":
        source_job.retryable = True
    elif mutation == "target_date":
        source_job.context.target_date = "20261015"
    elif mutation == "cutoff":
        source_job.context.cutoff = "2026-10-17T22:59:00+08:00"
    elif mutation == "operation":
        source_job.context.scope_refs["capture_operation"] = "ANNOUNCEMENT_FLASH_RECOVERY"
    else:
        source_job.context.rules_version = "OTHER_VERSION"
    with pytest.raises(ValueError, match="CACHE_RECOVERY_SOURCE_JOB_IDENTITY_INVALID"):
        AnnouncementUpdate(service).start_cached_product_recovery(source_job.job_id, product_sha)
    assert service.jobs.submissions == []


def test_cached_product_route_requires_original_latest_cursor_before_first_submission(tmp_path, monkeypatch):
    service, source_job, _product_path, _raw, product_sha = _service(tmp_path)
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", product_sha)
    service.store.set_cursor("announcement_flash_latest", {"job_id": "f" * 32,
                                                            "target_date": source_job.context.target_date,
                                                            "slot": source_job.context.cutoff})
    with pytest.raises(ValueError, match="CACHE_RECOVERY_LATEST_BINDING_INVALID"):
        AnnouncementUpdate(service).start_cached_product_recovery(source_job.job_id, product_sha)
    assert service.jobs.submissions == []


def test_cached_product_route_rejects_missing_tampered_and_oversized_objects(tmp_path, monkeypatch):
    service, source_job, product_path, raw, product_sha = _service(tmp_path)
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", product_sha)
    product_path.unlink()
    with pytest.raises(ValueError, match="CACHE_RECOVERY_PRODUCT_UNAVAILABLE"):
        AnnouncementUpdate(service).start_cached_product_recovery(source_job.job_id, product_sha)
    assert service.jobs.submissions == []

    service, source_job, product_path, raw, product_sha = _service(tmp_path / "tampered")
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", product_sha)
    product_path.write_bytes(raw + b"tamper")
    with pytest.raises(ValueError, match="CACHE_RECOVERY_PRODUCT_SHA_MISMATCH"):
        AnnouncementUpdate(service).start_cached_product_recovery(source_job.job_id, product_sha)
    assert service.jobs.submissions == []

    from v4.manager_workbench.inputs import capture_store

    service, source_job, _product_path, _raw, product_sha = _service(tmp_path / "oversized")
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", product_sha)
    monkeypatch.setattr(capture_store, "PRODUCT_MAX_BYTES", 10)
    with pytest.raises(ValueError, match="CACHE_RECOVERY_PRODUCT_UNAVAILABLE"):
        AnnouncementUpdate(service).start_cached_product_recovery(source_job.job_id, product_sha)
    assert service.jobs.submissions == []


def test_cached_product_cutoff_and_old_attempt_artifact_mismatches_reject_before_submission(tmp_path, monkeypatch):
    product = _product()
    product["window"]["research_cutoff"] = "2026-10-17T22:59:00+08:00"
    service, source_job, _product_path, _raw, product_sha = _service(tmp_path, product)
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", product_sha)
    with pytest.raises(ValueError, match="CACHE_RECOVERY_PRODUCT_IDENTITY_INVALID"):
        AnnouncementUpdate(service).start_cached_product_recovery(source_job.job_id, product_sha)
    assert service.jobs.submissions == []

    valid_service, valid_source, _path, _raw, valid_sha = _service(tmp_path / "second")
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", valid_sha)
    valid_service.store.files[f"announcement_flash/jobs/{valid_source.job_id}/input.json"] = b"{}"
    with pytest.raises(ValueError, match="CACHE_RECOVERY_SOURCE_ARTIFACT_EXISTS"):
        AnnouncementUpdate(valid_service).start_cached_product_recovery(valid_source.job_id, valid_sha)
    assert valid_service.jobs.submissions == []
    assert valid_service.store.files[f"announcement_flash/jobs/{valid_source.job_id}/input.json"] == b"{}"


@pytest.mark.parametrize("basename", ["input.json", "progress.json", "result.json", "capture-product.json"])
def test_any_existing_source_job_artifact_rejects_cached_recovery(tmp_path, monkeypatch, basename):
    service, source_job, _product_path, _raw, product_sha = _service(tmp_path)
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", product_sha)
    ref = f"announcement_flash/jobs/{source_job.job_id}/{basename}"
    service.store.files[ref] = b"{}"
    with pytest.raises(ValueError, match="CACHE_RECOVERY_SOURCE_ARTIFACT_EXISTS"):
        AnnouncementUpdate(service).start_cached_product_recovery(source_job.job_id, product_sha)
    assert service.jobs.submissions == []
    assert service.store.files[ref] == b"{}"


def test_cache_recovery_worker_uses_full_product_runner_path_without_capture_or_resume(tmp_path, monkeypatch):
    service, source_job, product_path, raw, product_sha = _service(tmp_path)
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", product_sha)
    update = AnnouncementUpdate(service, popen=lambda *_args, **_kwargs: None, sleep=lambda _seconds: None)
    job = update.start_cached_product_recovery(source_job.job_id, product_sha)
    membership = {"status": "CANNOT_CONFIRM", "target_date": job.context.target_date,
                  "cutoff": job.context.cutoff, "market": "HK_CONNECT"}

    from v4.manager_workbench import announcement_membership
    from v4.manager_workbench.inputs import capture, capture_store
    import requests

    def forbidden(*_args, **_kwargs):
        raise AssertionError("cached product recovery must not capture or open an HTTP session")

    monkeypatch.setattr(capture_store.CaptureStore, "grant", forbidden)
    monkeypatch.setattr(capture, "capture_window", forbidden)
    monkeypatch.setattr(requests, "Session", forbidden)
    monkeypatch.setattr(announcement_membership, "resolve_membership_gate", lambda *_args: dict(membership))
    commands = []

    class FinishedProcess:
        returncode = 0

        def poll(self):
            return self.returncode

    def fake_popen(command, **_kwargs):
        commands.append(command)
        assert "--resume-pending" not in command
        assert command[command.index("--job-id") + 1] == job.job_id
        input_value = json.loads(service.store.files[f"announcement_flash/jobs/{job.job_id}/input.json"])
        assert input_value["capture_product"] == {
            "artifact_ref": f"products/{product_sha}.json", "sha256": product_sha,
            "owner": "v4.manager_workbench.capture_announcements", "source": "EASTMONEY_HK",
        }
        assert input_value["membership_gate"] == membership
        assert "recovery_lock" not in input_value
        result = {"schema": "v4.manager_workbench.announcement_flash_result.v1", "job_id": job.job_id,
                  "target_trade_date": job.context.target_date, "state": "PARTIAL",
                  "membership_gate": membership,
                  "counts": {"queue": {"succeeded": 0, "failed": 0, "pending": 0}},
                  "provenance": {"current_capture_bindings": {
                      "EASTMONEY:SYNTHETIC": {"capture_product_sha256": product_sha}}}}
        service.store.io.write_bytes(update._job_ref(job.job_id, "result.json"),
                                      update_module._canonical(result) + b"\n")
        return FinishedProcess()

    update.popen = fake_popen
    run_id, state = update._work(job)
    assert run_id == job.job_id
    assert state == JobState.PARTIAL
    job.state = state
    assert len(commands) == 1
    assert commands[0][2] == str(update_module.RUNNER_SCRIPT)
    assert product_path.read_bytes() == raw
    assert service.store.values["announcement_flash_latest"]["job_id"] == job.job_id
    assert service.store.values["announcement_flash_latest"]["source_job_id"] == source_job.job_id
    assert service.store.values["announcement_flash_latest"]["capture_product_sha256"] == product_sha
    assert service.store.values["announcement_flash_result_index"]["items"][0]["job_id"] == job.job_id
    assert source_job.state == JobState.FAILED
    assert f"announcement_flash/jobs/{source_job.job_id}/input.json" not in service.store.files
    assert f"announcement_flash/jobs/{source_job.job_id}/result.json" not in service.store.files

    pinned = {"state": "PARTIAL", "source_date": "20261015", "target_trade_date": "CANNOT_CONFIRM",
              "updated_at": None, "stocks": [], "failures": [], "pending": [], "gaps": [],
              "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                         "buy_gate_updated": False, "orders_sent": False},
              "counts": {"source_catalogue_articles": 0, "model_succeeded": 0,
                         "selected_model_articles": 0, "model_candidate_stocks": 0,
                         "reused_reviewed_stocks": 0, "failed": 0, "pending": 0,
                         "body_gaps": 0, "displayed_stocks": 0}}
    monkeypatch.setattr(update_module, "read_pinned_candidates", lambda: dict(pinned))
    app = FastAPI()
    app.include_router(api.create_router(service))
    with TestClient(app) as client:
        response = client.get(api.PREFIX + "/announcement-flash", params={"target_date": job.context.target_date})
    assert response.status_code == 200, response.text
    view = response.json()["data"]
    assert view["job"]["job_id"] == job.job_id
    assert view["incremental"]["job_id"] == job.job_id
    assert view["incremental"]["membership_gate"]["status"] == "CANNOT_CONFIRM"
    assert view["incremental"]["provenance"]["current_capture_bindings"]["EASTMONEY:SYNTHETIC"][
        "capture_product_sha256"] == product_sha


def test_cached_product_changed_after_submit_fails_closed_without_capture_fallback(tmp_path, monkeypatch):
    service, source_job, product_path, _raw, product_sha = _service(tmp_path)
    monkeypatch.setattr(update_module, "CACHED_PRODUCT_RECOVERY_PRODUCT_SHA256", product_sha)
    update = AnnouncementUpdate(service, popen=lambda *_args, **_kwargs: pytest.fail("runner must not launch"))
    job = update.start_cached_product_recovery(source_job.job_id, product_sha)
    product_path.write_bytes(b"changed after submission")

    from v4.manager_workbench.inputs import capture, capture_store

    def forbidden(*_args, **_kwargs):
        raise AssertionError("cache mismatch must not fall back to capture")

    monkeypatch.setattr(capture_store.CaptureStore, "grant", forbidden)
    monkeypatch.setattr(capture, "capture_window", forbidden)
    with pytest.raises(update_module.StepFailure, match="CACHE_RECOVERY_PRODUCT_SHA_MISMATCH"):
        update._work(job)
    assert f"announcement_flash/jobs/{job.job_id}/input.json" not in service.store.files
    assert source_job.state == JobState.FAILED
