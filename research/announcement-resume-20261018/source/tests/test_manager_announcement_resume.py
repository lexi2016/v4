from __future__ import annotations

from contextlib import nullcontext
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4.manager_workbench import api
from v4.manager_workbench import announcement_update as update_module
from v4.manager_workbench.announcement_update import AnnouncementUpdate
from v4.manager_workbench.contracts import JobState
from v4.manager_workbench.jobs import JobConflict


RUNNER_PATH = Path(__file__).resolve().parents[1] / "ops/run_manager_flash_announcements.py"


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _runner():
    spec = importlib.util.spec_from_file_location("announcement_resume_runner_test", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _part_result(payload):
    descriptor = payload["part_descriptor"]
    return {
        "schema": "v4.manager_workbench.announcement_chunk_part_result.v1",
        "article_id": payload["article_id"],
        "source_sha256": payload["source_sha256"],
        "body_sha256": payload["body_sha256"],
        "plan_sha256": payload["chunk_plan_sha256"],
        "part_index": descriptor["part_index"],
        "part_count": descriptor["part_count"],
        "part_sha256": descriptor["part_sha256"],
        "source_unit_map_sha256": payload["source_unit_map_sha256"],
        "reader_output": {
            "body_sha256": "", "changes": [], "confirmation_conditions": [],
            "counter_evidence": [], "direction": "UNKNOWN", "disposition": "UNKNOWN",
            "evidence_sufficiency": "UNKNOWN", "facts": [], "impact": "UNKNOWN",
            "reason": "test fixture", "risk_notes": [], "selection_basis": "UNKNOWN",
            "source_sha256": "",
        },
        "citation_ranges": [],
    }


class _StoreIO:
    def __init__(self, root: Path):
        self.root = root
        self._files: dict[str, bytes] = {}

    def read_bytes(self, ref: str, **_kwargs) -> bytes:
        try:
            return self._files[ref]
        except KeyError as exc:
            raise FileNotFoundError(ref) from exc

    def write_bytes(self, ref: str, raw: bytes, **_kwargs) -> None:
        self._files[ref] = raw

    def files_under(self, prefix: str) -> list[str]:
        return [name for name in self._files if name.startswith(prefix)]

    def files(self, prefix: str) -> list[str]:
        marker = prefix.rstrip("/") + "/"
        return [name[len(marker):] for name in self.files_under(marker)
                if "/" not in name[len(marker):]]


class _Store:
    def __init__(self, root: Path):
        self.root = root
        self.io = _StoreIO(root)
        self.values: dict[str, object] = {}

    def cursor(self, key):
        return self.values.get(key)

    def set_cursor(self, key, value):
        self.values[key] = value

    def lock(self, _key):
        return nullcontext()


class _Jobs:
    def __init__(self, source):
        self.jobs = {source.job_id: source}
        self.submissions = []

    def get(self, job_id):
        return self.jobs[job_id]

    def submit(self, context, worker):
        job = SimpleNamespace(job_id=f"{len(self.jobs) + 1:032x}", state=JobState.QUEUED,
                              step="QUEUED", context=context, completed_count=0, total_count=None)
        self.jobs[job.job_id] = job
        self.submissions.append((context, worker))
        return job


def _resume_service(tmp_path: Path, *, counts=None, saved_orphan_result=None,
                    source_publication_date="2026-10-16", capture_target_date="20261016"):
    source_id = "a" * 32
    capture_root = tmp_path / "capture"
    capture_root.mkdir()
    article_code = "AN202610141830470198" if source_publication_date == "2026-10-14" else "AN202610161830470198"
    article_id = "EASTMONEY:" + article_code
    source_sha = "a" * 64
    article_body = "frozen-batch-body"
    body_sha = _sha(article_body.encode("utf-8"))
    prompt_sha = "c" * 64
    configuration_sha = "d" * 64
    unit_map_sha = "e" * 64
    ledger_sha = "f" * 64
    part_addendum_sha = "1" * 64
    parts = []
    for index in range(1, 46):
        parts.append({"part_index": index, "part_count": 45,
                      "part_sha256": f"{index:064x}", "start_source_unit_id": f"U{index:06d}",
                      "end_source_unit_id": f"U{index:06d}"})
    plan_material = {"schema": "v4.manager_workbench.announcement_chunk_plan.v1",
                     "article_id": article_id, "source_sha256": source_sha, "body_sha256": body_sha,
                     "prompt_sha256": prompt_sha, "configuration_sha256": configuration_sha,
                     "source_unit_map_sha256": unit_map_sha, "fixed_fact_ledger_sha256": ledger_sha,
                     "part_addendum_sha256": part_addendum_sha, "parts": parts}
    plan_sha = _sha(_json_bytes(plan_material))
    plan = {**plan_material, "plan_sha256": plan_sha}
    plan_name = f"{article_id.replace(':', '_')}-{plan_sha}.json"
    product = {"schema_version": "mwb.capture.window.v1", "owner": "v4.manager_workbench.capture_announcements",
               "source": "EASTMONEY_HK", "saved_ref": None, "target_trade_date": capture_target_date,
               "rows": [{"art_code": article_code,
                         "publication_date": source_publication_date, "source_sha256": source_sha,
                         "body_text": article_body, "body_text_sha256": body_sha,
                         "body_artifact_ref": f"products/{source_sha}.json", "body_complete": True}]}
    product_raw = _json_bytes(product)
    product_sha = _sha(product_raw)
    artifact_ref = f"products/{product_sha}.json"
    product_path = capture_root / artifact_ref
    product_path.parent.mkdir(parents=True)
    product_path.write_bytes(product_raw)
    input_value = {"schema": "v4.manager_workbench.announcement_flash_input.v1", "job_id": source_id,
                   "target_date": "20261016", "cutoff": "2026-10-18T09:34:00+08:00",
                   "capture_product": {"artifact_ref": artifact_ref, "sha256": product_sha},
                   "membership_gate": {"schema": "v4.manager_workbench.announcement_connect_membership.v1",
                                       "status": "CANNOT_CONFIRM"}}
    progress_value = {"step": "FAILED", "queue_counts": counts or {
        "SUCCEEDED": 24, "FAILED": 15, "PENDING": 5, "RUNNING": 1}, "total": 45}
    queue_jobs = {}
    running_key = None
    for index, status in enumerate(["SUCCEEDED"] * 24 + ["FAILED"] * 15 + ["PENDING"] * 5 + ["RUNNING"]):
        part = parts[index]
        rules = ("recent_day_reader_v2+profile:decision_simple_facts_unit_ranges_v2"
                 f"+unit-map:{unit_map_sha}+fixed-ledger:{ledger_sha}+schema:{'2' * 64}"
                 f"+temperature:0.0+thinking:off+long-body-part:v1+plan:{plan_sha}"
                 f"+part:{part['part_index']}/{part['part_count']}+part-sha:{part['part_sha256']}"
                 f"+part-prompt:{prompt_sha}+part-addendum:{part_addendum_sha}")
        identity = {"date": source_publication_date, "market": "HK", "article_id": article_id,
                    "source_sha256": source_sha, "body_sha256": body_sha, "prompt_sha256": prompt_sha,
                    "model_id": "qwen3_8_flash_next", "configuration_sha256": configuration_sha,
                    "rules": rules, "role": "announcement_reader_part",
                    "stage": "v4_manager_announcement_flash_long_body_part_v1"}
        key = _sha(_json_bytes(identity))
        if status == "RUNNING":
            running_key = key
        payload = {**identity, "article_body": article_body,
                   "article_metadata": {"publication_date": source_publication_date},
                   "fixed_fact_ledger": {"ledger_sha256": ledger_sha},
                   "chunk_plan_sha256": plan_sha, "source_unit_map_sha256": unit_map_sha,
                   "part_descriptor": part}
        payload_raw = _json_bytes(payload)
        input_ref = f"jobs/{key}/input.json"
        item = {"idempotency_key": key, "queue_id": update_module.FLASH_QUEUE_ID,
                "model_id": "qwen3_8_flash_next", "status": status,
                "attempt_count": 1 if status == "RUNNING" else 0,
                "identity": identity, "input_path": input_ref, "payload_sha256": _sha(payload_raw)}
        queue_jobs[key] = item
        store_ref = f"announcement_flash/queue/{input_ref}"
        # Store these payloads after the WorkbenchStore is created below.
        item["_test_payload_ref"] = store_ref
        item["_test_payload_raw"] = payload_raw
        if status == "RUNNING" and saved_orphan_result is not None:
            item["validated_path"] = f"jobs/{key}/attempt-0001.validated.json"
            item["validated_sha256"] = _sha(saved_orphan_result)
    queue_value = {"schema": "v4.announcement-engine-queue/v1", "jobs": queue_jobs}
    source = SimpleNamespace(job_id=source_id, state=JobState.INTERRUPTED,
                             context=SimpleNamespace(target_date="20261016", cutoff=input_value["cutoff"],
                                                     scope_refs={"capture_operation": "ANNOUNCEMENT_FLASH_INCREMENTAL"}))
    store = _Store(tmp_path / "workbench")
    store.values["announcement_flash_latest"] = {"job_id": source_id, "target_date": "20261016"}
    store.io._files[f"announcement_flash/jobs/{source_id}/input.json"] = _json_bytes(input_value)
    store.io._files[f"announcement_flash/jobs/{source_id}/progress.json"] = _json_bytes(progress_value)
    store.io._files[f"announcement_flash/jobs/{source_id}/long-body/{plan_name}"] = _json_bytes(plan)
    for item in queue_jobs.values():
        store.io._files[item.pop("_test_payload_ref")] = item.pop("_test_payload_raw")
    store.io._files["announcement_flash/queue/queue-state.json"] = _json_bytes(queue_value)
    if saved_orphan_result is not None:
        store.io._files[f"announcement_flash/queue/jobs/{running_key}/attempt-0001.validated.json"] = saved_orphan_result
    jobs = _Jobs(source)
    service = SimpleNamespace(config=SimpleNamespace(capture_root=str(capture_root)), store=store, jobs=jobs)
    return service, source_id


def test_resume_snapshot_exposes_hash_bound_single_canary_and_frozen_counts(tmp_path):
    service, source_id = _resume_service(tmp_path)

    snapshot = AnnouncementUpdate(service).resume_snapshot("20261016")

    assert snapshot["eligible"] is True
    assert snapshot["mode"] == "INITIAL_CANARY"
    assert snapshot["source_job_id"] == source_id
    assert snapshot["queue_status_counts"] == {"SUCCEEDED": 24, "FAILED": 15, "PENDING": 5, "RUNNING": 1}
    assert snapshot["orphan_count"] == 1
    assert snapshot["recoverable_orphan_count"] == 1
    assert snapshot["orphan_result_status"] == ["NONE"]
    assert snapshot["max_model_calls"] == 1
    assert "source_input" not in snapshot


def test_resume_snapshot_uses_frozen_plan_when_source_date_precedes_target_date(tmp_path):
    service, _source_id = _resume_service(tmp_path, source_publication_date="2026-10-14")

    snapshot = AnnouncementUpdate(service).resume_snapshot("20261016")

    assert snapshot["eligible"] is True
    assert snapshot["queue_status_counts"] == {"SUCCEEDED": 24, "FAILED": 15, "PENDING": 5, "RUNNING": 1}
    assert snapshot["orphan_count"] == 1
    assert snapshot["recoverable_orphan_count"] == 1
    assert snapshot["orphan_result_status"] == ["NONE"]


def test_resume_snapshot_rejects_capture_product_for_different_target_date(tmp_path):
    service, _source_id = _resume_service(tmp_path, capture_target_date="20261015")

    snapshot = AnnouncementUpdate(service).resume_snapshot("20261016")

    assert snapshot["eligible"] is False
    assert snapshot["reason"] == "RESUME_CAPTURE_TARGET_MISMATCH"


def test_resume_snapshot_rejects_complete_saved_orphan_result(tmp_path):
    output = {"article_id": "EASTMONEY:AN202610161830470198", "source_sha256": "a" * 64,
              "body_sha256": _sha(b"frozen-batch-body")}
    saved = _json_bytes({"results": [{"reader_output": output}]})
    service, _source_id = _resume_service(tmp_path, saved_orphan_result=saved)

    snapshot = AnnouncementUpdate(service).resume_snapshot("20261016")

    assert snapshot["eligible"] is False
    assert snapshot["reason"] == "RESUME_ORPHAN_NOT_ELIGIBLE"


def test_resume_snapshot_rejects_cross_date_active_announcement(tmp_path):
    service, _source_id = _resume_service(tmp_path)
    service.store.io._files["attempts/other-date.json"] = _json_bytes({
        "job_id": "f" * 32, "state": "RUNNING",
        "context": {"target_date": "20261015",
                    "scope_refs": {"capture_operation": "ANNOUNCEMENT_FLASH_INCREMENTAL"}},
    })

    snapshot = AnnouncementUpdate(service).resume_snapshot("20261016")

    assert snapshot["eligible"] is False
    assert snapshot["reason"] == "ANNOUNCEMENT_FLASH_BUSY_ALL_TARGET_DATES"


def test_resume_snapshot_rejects_live_model_lock_owner(tmp_path, monkeypatch):
    service, _source_id = _resume_service(tmp_path)
    monkeypatch.setattr(update_module, "_queue_model_lock_busy", lambda *_args: True)

    snapshot = AnnouncementUpdate(service).resume_snapshot("20261016")

    assert snapshot["eligible"] is False
    assert snapshot["reason"] == "RESUME_MODEL_OWNER_ACTIVE"


def test_resume_post_is_hash_bound_and_duplicate_click_returns_same_job(tmp_path):
    service, source_id = _resume_service(tmp_path)
    update = AnnouncementUpdate(service)
    snapshot = update.resume_snapshot("20261016")

    first = update.start_resume("20261016", source_id, snapshot["source_input_sha256"],
                                snapshot["source_progress_sha256"], snapshot["source_queue_state_sha256"])
    second = update.start_resume("20261016", source_id, snapshot["source_input_sha256"],
                                 snapshot["source_progress_sha256"], snapshot["source_queue_state_sha256"])

    assert first is second
    assert len(service.jobs.submissions) == 1
    assert first.context.scope_refs["capture_operation"] == "ANNOUNCEMENT_FLASH_RESUME"
    assert first.context.scope_refs["announcement_flash_resume"]["max_model_calls"] == 1
    assert first.context.scope_refs["announcement_flash_resume"]["resume_root"] == {
        "source_job_id": source_id, "source_input_sha256": snapshot["source_input_sha256"]}


def test_resume_post_rejects_changed_queue_sha_before_submission(tmp_path):
    service, source_id = _resume_service(tmp_path)
    update = AnnouncementUpdate(service)
    snapshot = update.resume_snapshot("20261016")
    service.store.io._files["announcement_flash/queue/queue-state.json"] += b" "

    with pytest.raises(JobConflict, match="RESUME_SOURCE_SHA_CHANGED"):
        update.start_resume("20261016", source_id, snapshot["source_input_sha256"],
                            snapshot["source_progress_sha256"], snapshot["source_queue_state_sha256"])

    assert service.jobs.submissions == []


def test_resume_api_passes_only_the_hash_bound_request_to_resume_service(monkeypatch, tmp_path):
    calls = []

    class ResumeUpdate:
        def __init__(self, _service):
            pass

        def start_resume(self, *args):
            calls.append(args)
            return SimpleNamespace(job_id="b" * 32, state=JobState.QUEUED,
                                   step="QUEUED", context=SimpleNamespace(target_date=args[0]))

    monkeypatch.setattr(api, "AnnouncementUpdate", ResumeUpdate)
    service, source_id = _resume_service(tmp_path)
    app = FastAPI()
    app.include_router(api.create_router(service))
    client = TestClient(app)
    payload = {"target_date": "20261016", "source_job_id": source_id,
               "source_input_sha256": "1" * 64, "source_progress_sha256": "2" * 64,
               "source_queue_state_sha256": "3" * 64}

    response = client.post(api.PREFIX + "/announcement-flash/resume", json=payload)

    assert response.status_code == 202
    assert response.json()["data"]["source_job_id"] == source_id
    assert calls == [("20261016", source_id, "1" * 64, "2" * 64, "3" * 64)]


def test_frozen_resume_runner_args_use_the_hash_bound_membership_source_root(tmp_path):
    source_root = tmp_path / "original-shared-root"
    current_root = tmp_path / "current-service-shared-root"
    source_root.mkdir()
    current_root.mkdir()
    membership_gate = {
        "schema": "v4.manager_workbench.announcement_connect_membership.v1",
        "status": "VERIFIED", "target_date": "20261016", "cutoff": "2026-10-18T09:34:00+08:00",
        "authority_pin": {"source_local_path": str(source_root),
                           "checked_files": [{"source_local_path": str(source_root),
                                              "relative": "universes/pinned.json"}]},
    }
    update = AnnouncementUpdate(SimpleNamespace())
    command = [str(update_module.RUNNER_PYTHON), "-B", str(update_module.RUNNER_SCRIPT),
               "--resume-frozen-batch"]
    command.extend(update._runner_shared_root_args(
        SimpleNamespace(shared_root=current_root), frozen_resume=True,
        membership_gate=membership_gate, target_date="20261016",
        cutoff="2026-10-18T09:34:00+08:00"))

    assert command[command.index("--shared-root") + 1] == str(source_root)


def test_frozen_resume_surfaces_membership_failure_before_queue_planning():
    bridge = _runner()

    with pytest.raises(bridge.FlashRunError, match="MEMBERSHIP_GATE_BINDING_CHANGED"):
        bridge._require_frozen_resume_membership(
            {"status": "CANNOT_CONFIRM", "failure_code": "MEMBERSHIP_GATE_BINDING_CHANGED"},
            resume_frozen_batch=True)


def test_generic_retry_route_rejects_announcement_capture_jobs(tmp_path):
    service, source_id = _resume_service(tmp_path)
    source = service.jobs.get(source_id)
    source.context.scope_refs["capture_operation"] = "ANNOUNCEMENT_FLASH_INCREMENTAL"
    service.retry = lambda _job_id: (_ for _ in ()).throw(AssertionError("generic retry must not recapture"))
    app = FastAPI()
    app.include_router(api.create_router(service))

    response = TestClient(app).post(api.PREFIX + f"/runs/{source_id}/retry")

    assert response.status_code == 409
    assert response.json()["gaps"] == ["ANNOUNCEMENT_FLASH_RESUME_REQUIRED"]


def test_frozen_orphan_probe_requires_exact_current_payload_and_never_recovers_in_dry_run(tmp_path, monkeypatch):
    bridge = _runner()
    payload = {"date": "2026-10-16", "market": "HK", "article_id": "EASTMONEY:NOTICE1",
               "source_sha256": "a" * 64, "body_sha256": "b" * 64, "prompt_sha256": "c" * 64,
               "model_id": "qwen3_8_flash_next", "configuration_sha256": "d" * 64,
               "rules": "rules", "role": "announcement_reader_part", "stage": "part"}
    identity_fields = tuple(payload)
    key = _sha(_json_bytes({field: payload[field] for field in identity_fields}))
    queue_root = tmp_path / "queue"
    input_path = queue_root / "jobs" / key / "input.json"
    input_path.parent.mkdir(parents=True)
    payload_raw = _json_bytes(payload)
    input_path.write_bytes(payload_raw)
    job = {"idempotency_key": key, "queue_id": "v4-manager-flash-incremental",
           "identity": {field: payload[field] for field in identity_fields},
           "payload_sha256": _sha(payload_raw), "input_path": f"jobs/{key}/input.json",
           "status": "RUNNING", "attempt_count": 1, "model_id": payload["model_id"]}

    class Queue:
        model_id = payload["model_id"]
        def _identity(self, value):
            return {field: value[field] for field in identity_fields}
        def _load_state(self):
            return {"jobs": {key: job}}
        def recover_interrupted(self, **_kwargs):
            raise AssertionError("dry-run must not recover or mutate the orphan")

    monkeypatch.setattr(bridge, "queue_model_lock_busy", lambda *_args: False)
    recovered, blocked, candidates = bridge._frozen_resume_orphans(
        {"EASTMONEY:NOTICE1": {"part_payloads": [payload]}}, Queue(), queue_root,
        target_date="20261016", dry_run=True)

    assert recovered == set()
    assert blocked == set()
    assert candidates == {key: "OWNER_CLEAR_NO_RESULT"}


def test_frozen_orphan_probe_binds_source_date_to_current_task_by_plan_key(tmp_path, monkeypatch):
    bridge = _runner()
    payload = {
        "date": "2026-10-14", "market": "HK", "article_id": "EASTMONEY:AN202610141830470198",
        "source_sha256": "06b2b177e8bba135c3892094597537866abdf1a7efe5544dd24474dc6aa93df7",
        "body_sha256": "dfdd93797e5db185ebc4aefff951f2e6c00be8c6cbcf2c7b95969102da4a2917",
        "prompt_sha256": "ef71f38b2ba243f2b52ac0ea72adf11dd79850edb1394c4317f13d0eb9cb2f0f",
        "model_id": "qwen3_8_flash_next",
        "configuration_sha256": "1e7b16001a12f29f04bf1e2b7600631643072c9ae2d7695271bf675d80d76ed9",
        "rules": ("recent_day_reader_v2+profile:decision_simple_facts_unit_ranges_v2"
                  "+unit-map:f249b6761e8bd725cfa45d4ae19b3b0a72c0683ff2aab412214f1c81014724fc"
                  "+fixed-ledger:3e3b0cf64b6ef8a2cb5a0e9c34365a62f9b132485f3fe12716c628339bd3ffc"
                  "+long-body-part:v1+plan:95b16ef29a386487561b277b1cfe67316c162da28de68deffa5883b076d895b1"
                  "+part:17/22+part-sha:b07893a143bd84e8b7fa36eca9af901ef36032b4227d99aa85d8d89866499571"
                  "+part-prompt:ef71f38b2ba243f2b52ac0ea72adf11dd79850edb1394c4317f13d0eb9cb2f0f"
                  "+part-addendum:b8f5caf460f9d0e6d3195dbc697b1ae4906f1bd4867453da8509091b7873470b"),
        "role": "announcement_reader_part",
        "stage": "v4_manager_announcement_flash_long_body_part_v1",
    }
    identity_fields = tuple(payload)
    key = _sha(_json_bytes({field: payload[field] for field in identity_fields}))
    queue_root = tmp_path / "queue"
    input_path = queue_root / "jobs" / key / "input.json"
    input_path.parent.mkdir(parents=True)
    payload_raw = _json_bytes(payload)
    input_path.write_bytes(payload_raw)
    job = {"idempotency_key": key, "queue_id": "v4-manager-flash-incremental",
           "identity": {field: payload[field] for field in identity_fields},
           "payload_sha256": _sha(payload_raw), "input_path": f"jobs/{key}/input.json",
           "status": "RUNNING", "attempt_count": 1, "model_id": payload["model_id"]}

    class Queue:
        model_id = payload["model_id"]
        def _identity(self, value):
            return {field: value[field] for field in identity_fields}
        def _load_state(self):
            return {"jobs": {key: job}}
        def recover_interrupted(self, **_kwargs):
            raise AssertionError("dry-run must not recover or mutate the orphan")

    monkeypatch.setattr(bridge, "queue_model_lock_busy", lambda *_args: False)
    recovered, blocked, candidates = bridge._frozen_resume_orphans(
        {"EASTMONEY:AN202610141830470198": {"part_payloads": [payload]}}, Queue(), queue_root,
        target_date="20261016", dry_run=True)

    assert recovered == set()
    assert blocked == set()
    assert candidates == {key: "OWNER_CLEAR_NO_RESULT"}


def test_frozen_orphan_probe_rejects_unmatched_running_job_before_canary(tmp_path, monkeypatch):
    bridge = _runner()
    queue_root = tmp_path / "queue"
    queue_root.mkdir()
    key = "f" * 64
    job = {"idempotency_key": key, "queue_id": "v4-manager-flash-incremental",
           "identity": {"date": "2026-10-16", "article_id": "OTHER:NOTICE"},
           "status": "RUNNING", "attempt_count": 1, "model_id": "qwen3_8_flash_next"}

    class Queue:
        model_id = "qwen3_8_flash_next"
        def _load_state(self):
            return {"jobs": {key: job}}

    with pytest.raises(bridge.FlashRunError, match="FROZEN_RESUME_ORPHAN_IDENTITY_UNVERIFIED"):
        bridge._frozen_resume_orphans({}, Queue(), queue_root, target_date="20261016", dry_run=True)


def test_frozen_orphan_probe_keeps_non_target_same_model_running_row_blocked(tmp_path):
    bridge = _runner()
    queue_root = tmp_path / "queue"
    queue_root.mkdir()
    key = "e" * 64
    job = {"idempotency_key": key, "queue_id": "v4-manager-flash-incremental",
           "identity": {"date": "2026-10-14", "article_id": "OTHER:NOTICE"},
           "status": "RUNNING", "attempt_count": 1, "model_id": "qwen3_8_flash_next"}

    class Queue:
        model_id = "qwen3_8_flash_next"
        def _load_state(self):
            return {"jobs": {key: job}}

    with pytest.raises(bridge.FlashRunError, match="FROZEN_RESUME_MODEL_OWNER_ACTIVE"):
        bridge._frozen_resume_orphans({}, Queue(), queue_root, target_date="20261016", dry_run=True)


def test_frozen_orphan_probe_rejects_live_model_owner(tmp_path, monkeypatch):
    bridge = _runner()
    payload = {"date": "2026-10-16", "market": "HK", "article_id": "EASTMONEY:NOTICE1",
               "source_sha256": "a" * 64, "body_sha256": "b" * 64, "prompt_sha256": "c" * 64,
               "model_id": "qwen3_8_flash_next", "configuration_sha256": "d" * 64,
               "rules": "rules", "role": "announcement_reader_part", "stage": "part"}
    identity_fields = tuple(payload)
    key = _sha(_json_bytes({field: payload[field] for field in identity_fields}))
    queue_root = tmp_path / "queue"
    input_path = queue_root / "jobs" / key / "input.json"
    input_path.parent.mkdir(parents=True)
    payload_raw = _json_bytes(payload)
    input_path.write_bytes(payload_raw)
    job = {"idempotency_key": key, "queue_id": "v4-manager-flash-incremental",
           "identity": {field: payload[field] for field in identity_fields},
           "payload_sha256": _sha(payload_raw), "input_path": f"jobs/{key}/input.json",
           "status": "RUNNING", "attempt_count": 1, "model_id": payload["model_id"]}

    class Queue:
        model_id = payload["model_id"]
        def _identity(self, value):
            return {field: value[field] for field in identity_fields}
        def _load_state(self):
            return {"jobs": {key: job}}
        def recover_interrupted(self, **_kwargs):
            raise AssertionError("live owner must prevent orphan recovery")

    monkeypatch.setattr(bridge, "queue_model_lock_busy", lambda *_args: True)

    with pytest.raises(bridge.FlashRunError, match="FROZEN_RESUME_MODEL_OWNER_ACTIVE"):
        bridge._frozen_resume_orphans(
            {"EASTMONEY:NOTICE1": {"part_payloads": [payload]}}, Queue(), queue_root,
            target_date="20261016", dry_run=False)


def test_canary_selection_prefers_one_ordinary_pending_part_and_excludes_failures():
    bridge = _runner()
    failed = {"kind": "part", "article_id": "A", "part_index": 1, "base_status": "FAILED",
              "key": "failed", "base_key": "failed", "runnable": False}
    orphan = {"kind": "part", "article_id": "A", "part_index": 2, "base_status": "FAILED",
              "key": "orphan-recovery", "base_key": "orphan", "runnable": True,
              "orphan_recovery": {"status": "PENDING"}}
    pending = {"kind": "part", "article_id": "A", "part_index": 3, "base_status": "PENDING",
               "key": "pending", "base_key": "pending", "runnable": True}
    conflict = {"kind": "part", "article_id": "A", "part_index": 0, "base_status": "PENDING",
                "key": "conflict", "base_key": "conflict", "runnable": True,
                "base_failure_code": "HISTORICAL_SUCCESS_PROVENANCE_MISMATCH"}

    assert bridge._frozen_resume_canary([failed, orphan, pending, conflict]) is pending
    assert bridge._frozen_resume_canary([failed, orphan, conflict]) is orphan
    assert bridge._frozen_resume_canary([failed, conflict]) is None


def test_frozen_resume_reports_read_only_orphan_recoverability_without_canary():
    bridge = _runner()
    source_hashes = {"source_input_sha256": "1" * 64,
                     "source_progress_sha256": "2" * 64,
                     "source_queue_state_sha256": "3" * 64}
    report = bridge._resume_dry_run_report({"resume": {
        "initial_part_status_counts": {"succeeded": 24, "failed": 15, "pending": 5, "running": 1},
        "initial_part_total": 45, "succeeded_preserved": 24, "failed_preserved": 15,
        "pending_eligible": 0, "historical_success_conflicts": 5,
        "orphan_candidates": [{"status": "OWNER_CLEAR_NO_RESULT", "eligible": True}],
        "recoverable_orphan_count": 1, "canary_key": None, "continue_eligible": False,
    }}, source_job_id="a" * 32, source_hashes=source_hashes,
        queue_sha_after=source_hashes["source_queue_state_sha256"])

    assert report["recoverable_orphan_count"] == 1
    assert report["canary_candidate"] is None
    assert report["model_calls"] == 0
    assert report["historical_success_conflicts"] == 5
    assert report["queue_state_unchanged"] is True


def test_frozen_orphan_recovery_admits_one_request_and_never_repeats(tmp_path, monkeypatch):
    bridge = _runner()
    identity_fields = ("date", "market", "article_id", "source_sha256", "body_sha256", "prompt_sha256",
                       "model_id", "configuration_sha256", "rules", "role", "stage")
    payload = {"date": "2026-10-14", "market": "HK", "article_id": "EASTMONEY:NOTICE1",
               "source_sha256": "a" * 64, "body_sha256": "b" * 64, "prompt_sha256": "c" * 64,
               "model_id": "qwen3_8_flash_next", "configuration_sha256": "d" * 64,
               "rules": "rules+unit-map:e+fixed-ledger:f+long-body-part:v1+plan:g+part:1/1",
               "role": "announcement_reader_part", "stage": "v4_manager_announcement_flash_long_body_part_v1",
               "queue_task_kind": "announcement_reader_part", "source_unit_map_sha256": "e" * 64,
               "chunk_plan_sha256": "g" * 64,
               "part_descriptor": {"part_index": 1, "part_count": 1, "part_sha256": "h" * 64,
                                   "source_unit_ids": ["U000001"]},
               "article_body": "frozen body", "fixed_fact_ledger": {"ledger_sha256": "f" * 64},
               "article_metadata": {"publication_date": "2026-10-14", "title": "title",
                                    "symbol": "HK.09963", "observed_at": "2026-10-14T10:00:00+08:00",
                                    "available_at": "2026-10-14T10:00:00+08:00",
                                    "pit_status": "CANNOT_CONFIRM", "pit_reason": "test",
                                    "article_membership_status": "IN", "membership_authority_sha256": "1" * 64,
                                    "source_issuer_codes": [], "source_issuer_membership": []}}
    queue_root = tmp_path / "queue"
    jobs = {}
    requests = []

    class Queue:
        model_id = payload["model_id"]
        def __init__(self):
            self.key = None
            self.enqueued = []
            self._add(payload, "RUNNING", 1)
        def _identity(self, value):
            return {field: value[field] for field in identity_fields}
        def _key(self, value):
            return _sha(_json_bytes(self._identity(value)))
        def _add(self, value, status, attempt_count):
            key = self._key(value)
            raw = _json_bytes(value)
            ref = f"jobs/{key}/input.json"
            path = queue_root / ref
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            jobs[key] = {"idempotency_key": key, "queue_id": "v4-manager-flash-incremental",
                         "identity": self._identity(value), "payload_sha256": _sha(raw),
                         "input_path": ref, "status": status, "attempt_count": attempt_count,
                         "max_attempts": 1, "model_id": self.model_id, "attempts": []}
            return key
        def _load_state(self):
            return {"jobs": jobs}
        def recover_interrupted(self, *, wait_for_model_slot):
            assert wait_for_model_slot is False
            item = jobs[self.key]
            item["status"] = "FAILED"
            item["attempts"] = [{"status": "INTERRUPTED", "error": {"code": "PROCESS_INTERRUPTED"}}]
            return [{"idempotency_key": self.key}]
        def enqueue(self, value):
            self.enqueued.append(value)
            return self._add(value, "PENDING", 0)
        def run_next(self, _executor, _validator, *, idempotency_keys, wait_for_model_slot):
            assert wait_for_model_slot is False
            assert len(idempotency_keys) == 1
            key = next(iter(idempotency_keys))
            requests.append(key)
            jobs[key]["status"] = "FAILED"
            jobs[key]["attempt_count"] = 1
            jobs[key]["attempts"] = [{"status": "FAILED", "error": {"code": "CANARY_TEST_FAILURE"}}]
            return {"idempotency_key": key, "status": "FAILED"}

    queue = Queue()
    queue.key = queue._key(payload)
    monkeypatch.setattr(bridge, "queue_model_lock_busy", lambda *_args: False)
    recovered, blocked, candidates = bridge._frozen_resume_orphans(
        {payload["article_id"]: {"part_payloads": [payload]}}, queue, queue_root,
        target_date="20261016", dry_run=False)

    assert recovered == {queue.key}
    assert blocked == set()
    assert candidates == {queue.key: "OWNER_CLEAR_NO_RESULT"}
    assert jobs[queue.key]["status"] == "FAILED"
    assert jobs[queue.key]["attempts"][-1]["error"]["code"] == "PROCESS_INTERRUPTED"

    spec = {payload["article_id"]: {"part_payloads": [payload]}}
    allowed, records = bridge._enqueue_long_body_parts(
        spec, queue, queue_root, allow_same_batch_pending=True, recovery_lock=None,
        membership_gate=None, resume_cutoff=None, prompt_token_cap=50000,
        hard_prompt_token_cap=100000, allow_new_repairs=False, allow_enqueue=True,
        resume_frozen_batch=True, recovered_orphan_keys=recovered, orphan_candidates=candidates,
        source_job_id="a" * 32, source_input_sha256="2" * 64,
        count_prompt_tokens=lambda _messages: 1,
    )
    selected = bridge._frozen_resume_canary(records)
    assert selected is not None and selected["orphan_recovery"]["status"] == "PENDING"
    assert allowed == {selected["key"]}
    assert len(queue.enqueued) == 1
    result = queue.run_next(lambda _job: "", lambda *_args: None,
                            idempotency_keys=allowed, wait_for_model_slot=False)
    assert result["idempotency_key"] == selected["key"]
    assert requests == [selected["key"]]

    allowed_again, records_again = bridge._enqueue_long_body_parts(
        spec, queue, queue_root, allow_same_batch_pending=True, recovery_lock=None,
        membership_gate=None, resume_cutoff=None, prompt_token_cap=50000,
        hard_prompt_token_cap=100000, allow_new_repairs=False, allow_enqueue=True,
        resume_frozen_batch=True, source_job_id="a" * 32, source_input_sha256="2" * 64,
        count_prompt_tokens=lambda _messages: 1,
    )
    assert allowed_again == set()
    assert bridge._frozen_resume_canary(records_again) is None
    assert len(queue.enqueued) == 1
    assert requests == [selected["key"]]


def test_same_part_historical_success_with_different_source_is_blocked_as_cannot_confirm(tmp_path):
    bridge = _runner()
    identity_fields = ("date", "market", "article_id", "source_sha256", "body_sha256", "prompt_sha256",
                       "model_id", "configuration_sha256", "rules", "role", "stage")

    class Queue:
        def __init__(self, jobs):
            self.jobs = jobs
        def _identity(self, payload):
            return {field: payload[field] for field in identity_fields}
        def _load_state(self):
            return {"jobs": self.jobs}

    descriptor = {"part_index": 1, "part_count": 2, "part_sha256": "c" * 64,
                  "source_unit_ids": ["u1", "u2"]}
    prior_payload = {"date": "2026-10-16", "market": "HK", "article_id": "EASTMONEY:NOTICE1",
                     "source_sha256": "a" * 64, "body_sha256": "b" * 64, "prompt_sha256": "c" * 64,
                     "model_id": "qwen3_8_flash_next", "configuration_sha256": "d" * 64,
                     "rules": "rules", "role": "announcement_reader_part", "stage": "part",
                     "queue_task_kind": "announcement_reader_part", "source_unit_map_sha256": "e" * 64,
                     "chunk_plan_sha256": "f" * 64, "part_descriptor": descriptor}
    current_payload = {**prior_payload, "source_sha256": "9" * 64, "chunk_plan_sha256": "8" * 64}
    root = tmp_path / "queue"
    identity = {field: prior_payload[field] for field in identity_fields}
    key = _sha(_json_bytes(identity))
    payload_raw = _json_bytes(prior_payload)
    input_path = root / "jobs" / key / "input.json"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(payload_raw)
    result_raw = _json_bytes(_part_result(prior_payload))
    result_path = root / "jobs" / key / "attempt-0001.validated.json"
    result_path.write_bytes(result_raw)
    job = {"idempotency_key": key, "queue_id": "v4-manager-flash-incremental", "identity": identity,
           "payload_sha256": _sha(payload_raw), "input_path": f"jobs/{key}/input.json",
           "status": "SUCCEEDED", "attempt_count": 1,
           "validated_path": f"jobs/{key}/attempt-0001.validated.json",
           "validated_sha256": _sha(result_raw)}
    conflict = bridge._historical_success_part_conflict(current_payload, "0" * 64,
                                                        Queue({key: job}), root)

    assert conflict is not None
    assert conflict["historical_result_status"] == "VERIFIED_PRIOR_RESULT"
    assert conflict["verification"] == "CANNOT_CONFIRM_PROVENANCE_BRIDGE"
    assert {"source_sha256", "chunk_plan_sha256"}.issubset(
        set(conflict["provenance_mismatch_fields"]))
    assert conflict["prior_idempotency_key"] == key


def test_frozen_resume_blocks_and_counts_five_verified_historical_successes(tmp_path):
    bridge = _runner()
    identity_fields = ("date", "market", "article_id", "source_sha256", "body_sha256", "prompt_sha256",
                       "model_id", "configuration_sha256", "rules", "role", "stage")
    queue_root = tmp_path / "queue"
    jobs = {}
    payloads = []
    prior_keys = []
    for index in range(1, 6):
        descriptor = {"part_index": index, "part_count": 5, "part_sha256": f"{index:064x}",
                      "source_unit_ids": [f"U{index:06d}"]}
        prior_payload = {"date": "2026-10-14", "market": "HK",
                         "article_id": "EASTMONEY:AN202610141830470198",
                         "source_sha256": "a" * 64, "body_sha256": "b" * 64,
                         "prompt_sha256": "c" * 64, "model_id": "qwen3_8_flash_next",
                         "configuration_sha256": "d" * 64, "rules": f"rules+plan:{'f' * 64}+part:{index}/5",
                         "role": "announcement_reader_part", "stage": "part",
                         "queue_task_kind": "announcement_reader_part",
                         "source_unit_map_sha256": "e" * 64,
                         "chunk_plan_sha256": "f" * 64, "part_descriptor": descriptor,
                         "article_body": "frozen body"}
        current_payload = {**prior_payload, "source_sha256": "9" * 64,
                           "rules": f"rules+plan:{'8' * 64}+part:{index}/5",
                           "chunk_plan_sha256": "8" * 64}
        payloads.append(current_payload)
        prior_identity = {field: prior_payload[field] for field in identity_fields}
        prior_key = _sha(_json_bytes(prior_identity))
        prior_keys.append(prior_key)
        prior_raw = _json_bytes(prior_payload)
        prior_input_ref = f"jobs/{prior_key}/input.json"
        prior_input_path = queue_root / prior_input_ref
        prior_input_path.parent.mkdir(parents=True, exist_ok=True)
        prior_input_path.write_bytes(prior_raw)
        result_raw = _json_bytes(_part_result(prior_payload))
        prior_result_ref = f"jobs/{prior_key}/attempt-0001.validated.json"
        prior_result_path = queue_root / prior_result_ref
        prior_result_path.write_bytes(result_raw)
        jobs[prior_key] = {"idempotency_key": prior_key, "queue_id": "v4-manager-flash-incremental",
                           "identity": prior_identity, "payload_sha256": _sha(prior_raw),
                           "input_path": prior_input_ref, "status": "SUCCEEDED", "attempt_count": 1,
                           "validated_path": prior_result_ref, "validated_sha256": _sha(result_raw)}

    class Queue:
        model_id = "qwen3_8_flash_next"
        def __init__(self):
            self.enqueued = []
            for payload in payloads:
                identity = self._identity(payload)
                key = _sha(_json_bytes(identity))
                raw = _json_bytes(payload)
                ref = f"jobs/{key}/input.json"
                path = queue_root / ref
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                jobs[key] = {"idempotency_key": key, "queue_id": "v4-manager-flash-incremental",
                             "identity": identity, "payload_sha256": _sha(raw), "input_path": ref,
                             "status": "PENDING", "attempt_count": 0}
        def _identity(self, payload):
            return {field: payload[field] for field in identity_fields}
        def _load_state(self):
            return {"jobs": jobs}
        def enqueue(self, payload):
            self.enqueued.append(payload)
            raise AssertionError("frozen historical parts must not be enqueued")

    queue = Queue()
    before = {key: (item["status"], item.get("attempt_count")) for key, item in jobs.items()}
    allowed, records = bridge._enqueue_long_body_parts(
        {"EASTMONEY:AN202610141830470198": {"part_payloads": payloads}}, queue, queue_root,
        allow_same_batch_pending=True, recovery_lock=None, membership_gate=None,
        resume_cutoff=None, prompt_token_cap=50000, hard_prompt_token_cap=100000,
        allow_new_repairs=False, allow_enqueue=False, resume_frozen_batch=True,
        source_job_id="a" * 32, source_input_sha256="2" * 64,
        count_prompt_tokens=lambda _messages: 1,
    )

    assert allowed == set()
    assert len(records) == 5
    assert [record["historical_success_conflict"]["prior_idempotency_key"]
            for record in records] == prior_keys
    assert all(record["historical_success_conflict"]["historical_result_status"]
               == "VERIFIED_PRIOR_RESULT" for record in records)
    assert all(record["runnable"] is False
               and record["base_failure_code"] == "HISTORICAL_SUCCESS_PROVENANCE_MISMATCH"
               for record in records)
    assert sum(record.get("historical_success_conflict") is not None for record in records) == 5
    assert queue.enqueued == []
    assert before == {key: (item["status"], item.get("attempt_count")) for key, item in jobs.items()}


@pytest.mark.parametrize(("status", "attempt_count", "expected_runnable"), [
    ("FAILED", 1, False),
    ("PENDING", 0, True),
])
def test_frozen_resume_keeps_failed_terminal_and_existing_pending_read_only(
        tmp_path, status, attempt_count, expected_runnable):
    bridge = _runner()
    identity_fields = ("date", "market", "article_id", "source_sha256", "body_sha256", "prompt_sha256",
                       "model_id", "configuration_sha256", "rules", "role", "stage")
    payload = {"date": "2026-10-16", "market": "HK", "article_id": "EASTMONEY:NOTICE1",
               "source_sha256": "a" * 64, "body_sha256": "b" * 64, "prompt_sha256": "c" * 64,
               "model_id": "qwen3_8_flash_next", "configuration_sha256": "d" * 64,
               "rules": "rules", "role": "announcement_reader_part", "stage": "part",
               "queue_task_kind": "announcement_reader_part", "source_unit_map_sha256": "e" * 64,
               "chunk_plan_sha256": "f" * 64, "part_descriptor": {"part_index": 1, "part_count": 2,
                   "part_sha256": "9" * 64, "source_unit_ids": ["u1"]},
               "article_metadata": {"publication_date": "2026-10-16", "title": "标题", "symbol": "HK.09963",
                                    "observed_at": "2026-10-16T10:00:00+08:00",
                                    "available_at": "2026-10-16T10:00:00+08:00", "pit_status": "CANNOT_CONFIRM",
                                    "pit_reason": "OFFICIAL_FIRST_PUBLICATION_TIME_NOT_BOUND",
                                    "article_membership_status": "IN", "membership_authority_sha256": "1" * 64,
                                    "source_issuer_codes": [], "source_issuer_membership": []}}
    identity = {field: payload[field] for field in identity_fields}
    key = _sha(_json_bytes(identity))
    queue_root = tmp_path / "queue"
    input_path = queue_root / "jobs" / key / "input.json"
    input_path.parent.mkdir(parents=True)
    payload_raw = _json_bytes(payload)
    input_path.write_bytes(payload_raw)
    saved_job = {"idempotency_key": key, "queue_id": "v4-manager-flash-incremental", "identity": identity,
                 "payload_sha256": _sha(payload_raw), "input_path": f"jobs/{key}/input.json",
                 "status": status, "attempt_count": attempt_count, "max_attempts": 1, "attempts": []}

    class Queue:
        model_id = payload["model_id"]
        def __init__(self):
            self.enqueued = []
        def _identity(self, value):
            return {field: value[field] for field in identity_fields}
        def _load_state(self):
            return {"jobs": {key: saved_job}}
        def enqueue(self, value):
            self.enqueued.append(value)

    queue = Queue()
    _allowed, records = bridge._enqueue_long_body_parts(
        {"EASTMONEY:NOTICE1": {"part_payloads": [payload]}}, queue, queue_root,
        allow_same_batch_pending=True, recovery_lock=None, membership_gate=None,
        resume_cutoff=None, prompt_token_cap=50000, hard_prompt_token_cap=100000,
        allow_new_repairs=False, allow_enqueue=True, resume_frozen_batch=True,
        source_job_id="a" * 32, source_input_sha256="2" * 64,
        count_prompt_tokens=lambda _messages: 1,
    )

    assert queue.enqueued == []
    assert records[0]["base_status"] == status
    assert records[0]["runnable"] is expected_runnable


def test_resume_source_sha_verification_is_read_only_and_rejects_bad_queue_hash(tmp_path):
    bridge = _runner()
    source_id = "a" * 32
    state_root = tmp_path / "state"
    capture_root = tmp_path / "capture"
    capture_root.mkdir()
    capture_raw = _json_bytes({"schema_version": "mwb.capture.window.v1",
                               "owner": "v4.manager_workbench.capture_announcements",
                               "source": "EASTMONEY_HK", "saved_ref": None, "rows": []})
    capture_sha = _sha(capture_raw)
    capture_ref = f"products/{capture_sha}.json"
    capture_path = capture_root / capture_ref
    capture_path.parent.mkdir(parents=True)
    capture_path.write_bytes(capture_raw)
    job_root = state_root / "announcement_flash" / "jobs" / source_id
    job_root.mkdir(parents=True)
    input_raw = _json_bytes({"schema": "v4.manager_workbench.announcement_flash_input.v1",
                             "job_id": source_id, "target_date": "20261016",
                             "capture_product": {"artifact_ref": capture_ref, "sha256": capture_sha}})
    progress_raw = _json_bytes({"step": "FAILED"})
    queue_raw = _json_bytes({"schema": "v4.announcement-engine-queue/v1", "jobs": {}})
    (job_root / "input.json").write_bytes(input_raw)
    (job_root / "progress.json").write_bytes(progress_raw)
    queue_path = state_root / "announcement_flash" / "queue" / "queue-state.json"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_bytes(queue_raw)
    (state_root / "attempts").mkdir()
    (state_root / "attempts" / f"{source_id}.json").write_bytes(_json_bytes({"state": "INTERRUPTED"}))
    hashes = {"source_input_sha256": _sha(input_raw), "source_progress_sha256": _sha(progress_raw),
              "source_queue_state_sha256": "0" * 64}
    before = {str(path): _sha(path.read_bytes()) for path in state_root.rglob("*") if path.is_file()}

    with pytest.raises(bridge.FlashRunError, match="FROZEN_RESUME_SOURCE_SHA_CHANGED"):
        bridge._verify_resume_source(bridge.SafeRoot(state_root), capture_root, source_id, "20261016", hashes)

    after = {str(path): _sha(path.read_bytes()) for path in state_root.rglob("*") if path.is_file()}
    assert after == before
