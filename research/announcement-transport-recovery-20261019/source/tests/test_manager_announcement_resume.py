from __future__ import annotations

from contextlib import nullcontext
import hashlib
import importlib.util
import json
import re
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


def _bind_resume_part_payload(payload, *, part_index=1, part_count=1, source_unit_map_sha256=None,
                              chunk_plan_sha256=None, part_sha256=None):
    payload.update({
        "queue_task_kind": "announcement_reader_part",
        "source_unit_map_sha256": source_unit_map_sha256 or "e" * 64,
        "chunk_plan_sha256": chunk_plan_sha256 or "f" * 64,
        "part_descriptor": {
            "part_index": part_index, "part_count": part_count,
            "part_sha256": part_sha256 or "9" * 64,
            "start_source_unit_id": f"U{part_index:06d}",
            "end_source_unit_id": f"U{part_index:06d}",
            "source_unit_ids": [f"U{part_index:06d}"],
            "unit_start_index": part_index - 1, "unit_end_index": part_index,
        },
    })
    source_suffix = re.search(
        r"(\+long-body-part:v1\+plan:[0-9a-f]{64}\+part:[0-9]+/[0-9]+"
        r"\+part-sha:[0-9a-f]{64}\+part-prompt:[0-9a-f]{64}"
        r"\+part-addendum:[0-9a-f]{64})$", payload.get("rules", ""))
    if source_suffix is None:
        suffix = (f"+long-body-part:v1+plan:{payload['chunk_plan_sha256']}"
                  f"+part:{part_index}/{part_count}+part-sha:{payload['part_descriptor']['part_sha256']}"
                  f"+part-prompt:{payload['prompt_sha256']}+part-addendum:{'a' * 64}")
        payload["rules"] += suffix
    else:
        suffix = source_suffix.group(1)
    payload["frozen_source_rules_suffix"] = suffix
    return payload


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
        self.read_calls: list[tuple[str, int]] = []

    def read_bytes(self, ref: str, max_bytes: int = 64 * 1024 * 1024, **_kwargs) -> bytes:
        try:
            raw = self._files[ref]
        except KeyError as exc:
            raise FileNotFoundError(ref) from exc
        self.read_calls.append((ref, max_bytes))
        if len(raw) > max_bytes:
            raise ValueError("FILE_TOO_LARGE")
        return raw

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
                    source_publication_date="2026-10-16", capture_target_date="20261016",
                    source_job_id="a" * 32, running_part_index=None, plan_part_counts=None):
    source_id = source_job_id
    capture_root = tmp_path / "capture"
    capture_root.mkdir()
    plan_part_counts = list(plan_part_counts or (45,))
    if not plan_part_counts or sum(plan_part_counts) != 45 or any(type(count) is not int or count < 1
                                                                   for count in plan_part_counts):
        raise ValueError("PLAN_PART_COUNTS_INVALID")
    prompt_sha = "c" * 64
    configuration_sha = "d" * 64
    unit_map_sha = "e" * 64
    ledger_sha = "f" * 64
    part_addendum_sha = "1" * 64
    articles = []
    global_index = 0
    for article_index, part_count in enumerate(plan_part_counts):
        article_code = ("AN202610141830470198" if source_publication_date == "2026-10-14"
                        else "AN202610161830470198")
        if article_index:
            article_code = article_code[:-1] + str(int(article_code[-1]) + article_index)
        article_id = "EASTMONEY:" + article_code
        source_sha = f"{article_index + 10:x}" * 64
        article_body = "frozen-batch-body" if article_index == 0 else f"frozen-batch-body-{article_index + 1}"
        body_sha = _sha(article_body.encode("utf-8"))
        parts = []
        for index in range(1, part_count + 1):
            parts.append({"part_index": index, "part_count": part_count,
                          "part_sha256": f"{global_index + index:064x}",
                          "start_source_unit_id": f"U{global_index + index:06d}",
                          "end_source_unit_id": f"U{global_index + index:06d}"})
        plan_material = {"schema": "v4.manager_workbench.announcement_chunk_plan.v1",
                         "article_id": article_id, "source_sha256": source_sha, "body_sha256": body_sha,
                         "prompt_sha256": prompt_sha, "configuration_sha256": configuration_sha,
                         "source_unit_map_sha256": unit_map_sha, "fixed_fact_ledger_sha256": ledger_sha,
                         "part_addendum_sha256": part_addendum_sha, "parts": parts}
        plan_sha = _sha(_json_bytes(plan_material))
        plan = {**plan_material, "plan_sha256": plan_sha}
        plan_name = f"{article_id.replace(':', '_')}-{plan_sha}.json"
        articles.append({"article_code": article_code, "article_id": article_id,
                         "source_sha": source_sha, "article_body": article_body, "body_sha": body_sha,
                         "parts": parts, "plan": plan, "plan_name": plan_name})
        global_index += part_count
    product = {"schema_version": "mwb.capture.window.v1", "owner": "v4.manager_workbench.capture_announcements",
               "source": "EASTMONEY_HK", "saved_ref": None, "target_trade_date": capture_target_date,
               "rows": [{"art_code": article["article_code"],
                         "publication_date": source_publication_date,
                         "source_sha256": article["source_sha"],
                         "body_text": article["article_body"], "body_text_sha256": article["body_sha"],
                         "body_artifact_ref": f"products/{article['source_sha']}.json", "body_complete": True}
                        for article in articles]}
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
    statuses = ["SUCCEEDED"] * 24 + ["FAILED"] * 15 + ["PENDING"] * 5 + ["RUNNING"]
    if running_part_index is not None:
        if type(running_part_index) is not int or not 1 <= running_part_index <= plan_part_counts[0]:
            raise ValueError("RUNNING_PART_INDEX_INVALID")
        statuses[running_part_index - 1], statuses[-1] = "RUNNING", "SUCCEEDED"
    global_index = 0
    for article in articles:
        for part in article["parts"]:
            status = statuses[global_index]
            rules = ("recent_day_reader_v2+profile:decision_simple_facts_unit_ranges_v2"
                     f"+unit-map:{unit_map_sha}+fixed-ledger:{ledger_sha}+schema:{'2' * 64}"
                     f"+temperature:0.0+thinking:off+long-body-part:v1+plan:{article['plan']['plan_sha256']}"
                     f"+part:{part['part_index']}/{part['part_count']}+part-sha:{part['part_sha256']}"
                     f"+part-prompt:{prompt_sha}+part-addendum:{part_addendum_sha}")
            identity = {"date": source_publication_date, "market": "HK", "article_id": article["article_id"],
                        "source_sha256": article["source_sha"], "body_sha256": article["body_sha"],
                        "prompt_sha256": prompt_sha, "model_id": "qwen3_8_flash_next",
                        "configuration_sha256": configuration_sha, "rules": rules,
                        "role": "announcement_reader_part",
                        "stage": "v4_manager_announcement_flash_long_body_part_v1"}
            key = _sha(_json_bytes(identity))
            if status == "RUNNING":
                running_key = key
            payload = {**identity, "article_body": article["article_body"],
                       "article_metadata": {"publication_date": source_publication_date},
                       "fixed_fact_ledger": {"ledger_sha256": ledger_sha},
                       "chunk_plan_sha256": article["plan"]["plan_sha256"],
                       "source_unit_map_sha256": unit_map_sha, "part_descriptor": part}
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
            global_index += 1
    queue_value = {"schema": "v4.announcement-engine-queue/v1", "jobs": queue_jobs}
    source = SimpleNamespace(job_id=source_id, state=JobState.INTERRUPTED,
                             context=SimpleNamespace(target_date="20261016", cutoff=input_value["cutoff"],
                                                     scope_refs={"capture_operation": "ANNOUNCEMENT_FLASH_INCREMENTAL"}))
    store = _Store(tmp_path / "workbench")
    store.values["announcement_flash_latest"] = {"job_id": source_id, "target_date": "20261016"}
    store.io._files[f"announcement_flash/jobs/{source_id}/input.json"] = _json_bytes(input_value)
    store.io._files[f"announcement_flash/jobs/{source_id}/progress.json"] = _json_bytes(progress_value)
    for article in articles:
        store.io._files[f"announcement_flash/jobs/{source_id}/long-body/{article['plan_name']}"] = _json_bytes(article["plan"])
    for item in queue_jobs.values():
        store.io._files[item.pop("_test_payload_ref")] = item.pop("_test_payload_raw")
    store.io._files["announcement_flash/queue/queue-state.json"] = _json_bytes(queue_value)
    if saved_orphan_result is not None:
        store.io._files[f"announcement_flash/queue/jobs/{running_key}/attempt-0001.validated.json"] = saved_orphan_result
    jobs = _Jobs(source)
    service = SimpleNamespace(config=SimpleNamespace(capture_root=str(capture_root)), store=store, jobs=jobs)
    return service, source_id


def _mark_transport_system_stop(service, source_id):
    store = service.store
    input_ref = f"announcement_flash/jobs/{source_id}/input.json"
    source_input = json.loads(store.io._files[input_ref])
    capture_root = Path(service.config.capture_root)
    capture_product = json.loads((capture_root / source_input["capture_product"]["artifact_ref"]).read_bytes())
    rows = [
        ("AN202610161830609970", "失败文章正文", "a" * 64, "HK.09963"),
        ("AN202610161830609971", "待处理文章正文", "b" * 64, "HK.09964"),
    ]
    for article_code, body, source_sha, _code in rows:
        capture_product["rows"].append({
            "art_code": article_code, "publication_date": "2026-10-16", "source_sha256": source_sha,
            "body_text": body, "body_text_sha256": _sha(body.encode()),
            "body_artifact_ref": f"products/{source_sha}.json", "body_complete": True,
        })
    capture_raw = _json_bytes(capture_product)
    capture_sha = _sha(capture_raw)
    capture_ref = f"products/{capture_sha}.json"
    (capture_root / capture_ref).parent.mkdir(parents=True, exist_ok=True)
    (capture_root / capture_ref).write_bytes(capture_raw)
    authority = "c" * 64
    source_input["capture_product"] = {"artifact_ref": capture_ref, "sha256": capture_sha}
    source_input["membership_gate"] = {
        "schema": "v4.manager_workbench.announcement_connect_membership.v1",
        "status": "VERIFIED", "market": "HK_CONNECT", "target_date": "20261016",
        "cutoff": source_input["cutoff"], "authority_sha256": authority,
        "codes": ["HK.09963", "HK.09964"],
    }
    store.io._files[input_ref] = _json_bytes(source_input)

    queue_ref = "announcement_flash/queue/queue-state.json"
    queue_value = json.loads(store.io._files[queue_ref])
    jobs = queue_value["jobs"]
    for item in jobs.values():
        item.update({"status": "PENDING", "attempt_count": 0, "max_attempts": 1, "attempts": []})
    failed_key = pending_key = None
    for index, (article_code, body, source_sha, code) in enumerate(rows):
        body_sha = _sha(body.encode())
        identity = {
            "date": "2026-10-16", "market": "HK", "article_id": "EASTMONEY:" + article_code,
            "source_sha256": source_sha, "body_sha256": body_sha, "prompt_sha256": "3" * 64,
            "model_id": "qwen3_8_flash_next", "configuration_sha256": "4" * 64,
            "rules": "frozen-rules", "role": "announcement_reader",
            "stage": "v4_manager_announcement_flash_incremental",
        }
        metadata = {
            "publication_date": "2026-10-16", "available_at": "2026-10-16T10:00:00+08:00",
            "article_membership_status": "IN", "membership_authority_sha256": authority,
            "source_issuer_codes": [{"code": code}],
            "source_issuer_membership": [{"code": code, "membership_status": "IN",
                                          "market": "HK_CONNECT", "authority_sha256": authority}],
            "source_origins": [
                {"role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_product_sha256": capture_sha},
                {"role": "VERIFIED_FULL_NOTICE_BODY_PRODUCT", "source_product_sha256": source_sha},
            ],
        }
        payload = {**identity, "article_body": body, "article_metadata": metadata}
        payload_raw = _json_bytes(payload)
        key = _sha(_json_bytes(identity))
        input_path = f"jobs/{key}/input.json"
        store.io._files["announcement_flash/queue/" + input_path] = payload_raw
        status = "FAILED" if index == 0 else "PENDING"
        jobs[key] = {
            "idempotency_key": key, "queue_id": update_module.FLASH_QUEUE_ID,
            "model_id": identity["model_id"], "status": status,
            "attempt_count": 1 if status == "FAILED" else 0, "max_attempts": 1,
            "identity": identity, "input_path": input_path, "payload_sha256": _sha(payload_raw),
            "attempts": ([{"status": "FAILED", "number": 1,
                           "error": {"stage": "executor", "code": "TransportError"}}]
                         if status == "FAILED" else []),
        }
        if status == "FAILED":
            failed_key = key
        else:
            pending_key = key
    store.io._files[queue_ref] = _json_bytes(queue_value)
    store.io._files[f"announcement_flash/jobs/{source_id}/progress.json"] = _json_bytes({
        "step": "DONE", "result_state": "PARTIAL", "completed": 0, "total": 2, "queue_counts": None,
    })
    store.io._files[f"announcement_flash/jobs/{source_id}/result.json"] = _json_bytes({
        "schema": "v4.manager_workbench.announcement_flash_result.v1",
        "job_id": source_id, "target_trade_date": "20261016", "state": "PARTIAL",
        "system_stop": {"failure_code": "TransportError", "stage": "executor",
                        "attempt": 1, "queue_action": "STOPPED_NO_AUTOMATIC_RETRY"},
        "counts": {"queue": {"succeeded": 0, "failed": 1, "pending": 1}},
        "failures": [{"article_id": "EASTMONEY:" + rows[0][0],
                      "stage": "executor", "failure_code": "TransportError"}],
        "pending": [{"article_id": "EASTMONEY:" + rows[1][0],
                     "queue_reason": "STOPPED_AFTER_SYSTEM_FAILURE"}],
    })
    service.jobs.get(source_id).state = JobState.PARTIAL
    store.values["announcement_flash_latest"] = {"job_id": source_id, "target_date": "20261016"}
    return failed_key, pending_key


def test_active_flash_attempt_scan_reads_valid_unrelated_large_terminal_record(tmp_path):
    service, _source_id = _resume_service(tmp_path)
    projection = [{"symbol": f"US{i:04d}", "name": "x" * 6600} for i in range(1003)]
    attempt = {
        "job_id": "c" * 32,
        "state": "PARTIAL",
        "step": "DONE",
        "retryable": False,
        "context": {
            "target_date": "20261020",
            "scope_refs": {
                "capture_operation": None,
                "requested_lanes": ["ANNOUNCEMENT", "US_MAPPING"],
                "US_MAPPING": {"full_overlay_projection": projection},
            },
            "owner_bindings": {"us_mapping": {"full_overlay_projection": projection}},
        },
    }
    raw = _json_bytes(attempt)
    assert len(raw) > 8 * 1024 * 1024
    ref = f"attempts/{attempt['job_id']}.json"
    service.store.io._files[ref] = raw

    assert AnnouncementUpdate(service)._active_flash_attempts() == []
    assert (ref, 64 * 1024 * 1024) in service.store.io.read_calls


def test_active_flash_attempt_scan_still_reports_active_flash_capture(tmp_path):
    service, _source_id = _resume_service(tmp_path)
    attempt = {
        "job_id": "d" * 32,
        "state": "RUNNING",
        "context": {
            "target_date": "20261016",
            "scope_refs": {"capture_operation": "ANNOUNCEMENT_FLASH_INCREMENTAL"},
        },
    }
    service.store.io._files[f"attempts/{attempt['job_id']}.json"] = _json_bytes(attempt)

    assert AnnouncementUpdate(service)._active_flash_attempts() == [
        {"job_id": attempt["job_id"], "target_date": "20261016", "state": "RUNNING"}
    ]


def test_active_flash_attempt_scan_fails_closed_at_store_size_limit(tmp_path, monkeypatch):
    service, _source_id = _resume_service(tmp_path)
    service.store.io._files["attempts/oversized.json"] = b"{}"
    original_read_bytes = service.store.io.read_bytes

    def reject_over_limit(ref, *, max_bytes=64 * 1024 * 1024, **kwargs):
        if ref == "attempts/oversized.json":
            assert max_bytes == 64 * 1024 * 1024
            raise ValueError("FILE_TOO_LARGE")
        return original_read_bytes(ref, max_bytes=max_bytes, **kwargs)

    monkeypatch.setattr(service.store.io, "read_bytes", reject_over_limit)
    with pytest.raises(JobConflict, match="ANNOUNCEMENT_FLASH_ATTEMPT_SCAN_UNVERIFIED"):
        AnnouncementUpdate(service)._active_flash_attempts()


def test_active_flash_attempt_scan_fails_closed_on_invalid_json(tmp_path):
    service, _source_id = _resume_service(tmp_path)
    service.store.io._files["attempts/invalid.json"] = b"{not-json"

    with pytest.raises(JobConflict, match="ANNOUNCEMENT_FLASH_ATTEMPT_SCAN_UNVERIFIED"):
        AnnouncementUpdate(service)._active_flash_attempts()


def _mark_legacy_failed_canary(service, source_id):
    store = service.store
    source_input_ref = f"announcement_flash/jobs/{source_id}/input.json"
    source_input = json.loads(store.io._files[source_input_ref])
    root_id = "b" * 32
    root_input = {**source_input, "job_id": root_id}
    root_input_raw = _json_bytes(root_input)
    root_sha = _sha(root_input_raw)
    root_input_ref = f"announcement_flash/jobs/{root_id}/input.json"
    store.io._files[root_input_ref] = root_input_raw
    plan_prefix = f"announcement_flash/jobs/{source_id}/long-body/"
    plan_items = [(name, raw) for name, raw in store.io._files.items() if name.startswith(plan_prefix)]
    assert len(plan_items) == 1
    plan_name = plan_items[0][0].split(plan_prefix, 1)[1]
    store.io._files[f"announcement_flash/jobs/{root_id}/long-body/{plan_name}"] = plan_items[0][1]
    source_input["resume_root"] = {"source_job_id": root_id, "source_input_sha256": root_sha}
    source_input["resume_source"] = {
        "schema": update_module.FROZEN_RESUME_SCHEMA, "mode": "INITIAL_CANARY",
        "source_job_id": root_id, "source_input_sha256": root_sha,
        "resume_action": "CANARY", "legacy_failed_canary": None,
    }
    source_input_raw = _json_bytes(source_input)
    store.io._files[source_input_ref] = source_input_raw

    queue_ref = "announcement_flash/queue/queue-state.json"
    queue = json.loads(store.io._files[queue_ref])
    jobs = queue["jobs"]
    running_item = next(item for item in jobs.values() if item.get("status") == "RUNNING")
    running_item["status"] = "FAILED"
    running_item["attempt_count"] = 1
    running_item["max_attempts"] = 1
    running_item["attempts"] = [{"status": "FAILED", "number": 1,
                                 "error": {"stage": "executor", "code": "PROCESS_INTERRUPTED"}}]
    failed_base = next(item for item in jobs.values() if item.get("status") == "FAILED")
    base_payload = json.loads(store.io._files["announcement_flash/queue/" + failed_base["input_path"]])
    legacy_payload = {**base_payload,
                      "rules": base_payload["rules"] + "+legacy-pre-contract-canary:v1",
                      "queue_task_kind": "announcement_reader_part",
                      "frozen_resume_binding": {
                          "source_job_id": root_id, "source_input_sha256": root_sha,
                          "target_date": "20261016", "cutoff": source_input["cutoff"],
                          "capture_product_sha256": source_input["capture_product"]["sha256"],
                          "membership_authority_sha256": None,
                      }}
    identity = {field: legacy_payload[field] for field in update_module.FLASH_QUEUE_IDENTITY_FIELDS}
    legacy_key = _sha(_json_bytes(identity))
    legacy_input_ref = f"jobs/{legacy_key}/input.json"
    legacy_raw_ref = f"jobs/{legacy_key}/attempt-0001.raw"
    legacy_raw = _json_bytes({"action": "complete", "lookup_request": None,
                              "reader_output": {"facts": [], "changes": [{"claim": "rejected"}]}})
    legacy_payload_raw = _json_bytes(legacy_payload)
    store.io._files["announcement_flash/queue/" + legacy_input_ref] = legacy_payload_raw
    store.io._files["announcement_flash/queue/" + legacy_raw_ref] = legacy_raw
    legacy_job = {
        "idempotency_key": legacy_key, "queue_id": update_module.FLASH_QUEUE_ID,
        "model_id": identity["model_id"], "status": "FAILED", "attempt_count": 1,
        "max_attempts": 1, "identity": identity, "input_path": legacy_input_ref,
        "payload_sha256": _sha(legacy_payload_raw), "raw_path": legacy_raw_ref,
        "raw_sha256": _sha(legacy_raw),
        "attempts": [{"status": "FAILED", "number": 1,
                       "error": {"stage": "validator", "code": "PART_FIXED_FIELDS_MUST_BE_EMPTY"},
                       "raw_path": legacy_raw_ref, "raw_sha256": _sha(legacy_raw)}],
    }
    jobs[legacy_key] = legacy_job
    store.io._files[queue_ref] = _json_bytes(queue)
    store.io._files[f"announcement_flash/jobs/{source_id}/progress.json"] = _json_bytes({
        "step": "DONE", "queue_counts": {"SUCCEEDED": 24, "FAILED": 16, "PENDING": 5, "RUNNING": 0},
        "total": 45,
    })
    store.io._files[f"announcement_flash/jobs/{source_id}/result.json"] = _json_bytes({
        "schema": "v4.manager_workbench.announcement_flash_result.v1", "state": "PARTIAL",
        "resume": {"mode": "FROZEN_BATCH", "resume_action": "CANARY", "canary_passed": False,
                   "canary_status": "FAILED", "canary_model_calls": 1, "max_model_calls": 1,
                   "canary_key": legacy_key,
                   "canary_validation": {"status": "FAIL", "failure_code": "FROZEN_RESUME_CANARY_NOT_SUCCEEDED",
                                         "key": legacy_key}},
    })
    service.jobs.get(source_id).state = JobState.PARTIAL
    store.values["announcement_flash_latest"] = {"job_id": source_id, "target_date": "20261016"}
    return legacy_key


def _mark_precontract_orphan_failed_canary(service, source_id, *, root_job_id="b" * 32):
    """Reproduce the immutable pre-contract R2 result/input/queue shape from 29983573dff34359bfd34f054641a1d6."""
    store = service.store
    source_input_ref = f"announcement_flash/jobs/{source_id}/input.json"
    source_input = json.loads(store.io._files[source_input_ref])
    root_id = root_job_id
    root_input = {**source_input, "job_id": root_id}
    root_input_raw = _json_bytes(root_input)
    root_sha = _sha(root_input_raw)
    root_input_ref = f"announcement_flash/jobs/{root_id}/input.json"
    store.io._files[root_input_ref] = root_input_raw
    source_progress_raw = store.io._files[f"announcement_flash/jobs/{source_id}/progress.json"]
    source_queue_raw = store.io._files["announcement_flash/queue/queue-state.json"]
    root_progress_sha = _sha(source_progress_raw)
    root_queue_sha = _sha(source_queue_raw)
    store.io._files[f"announcement_flash/jobs/{root_id}/progress.json"] = source_progress_raw
    plan_prefix = f"announcement_flash/jobs/{source_id}/long-body/"
    for ref, raw in list(store.io._files.items()):
        if ref.startswith(plan_prefix):
            store.io._files[ref.replace(f"jobs/{source_id}/", f"jobs/{root_id}/", 1)] = raw
    source_input["resume_root"] = {"source_job_id": root_id, "source_input_sha256": root_sha}
    source_input["resume_source"] = {
        "schema": update_module.FROZEN_RESUME_SCHEMA, "mode": "INITIAL_CANARY",
        "source_job_id": root_id, "source_input_sha256": root_sha,
        "source_progress_sha256": root_progress_sha, "source_queue_state_sha256": root_queue_sha,
        "source_result_sha256": None, "capture_product_sha256": source_input["capture_product"]["sha256"],
        "queue_status_counts": {"FAILED": 15, "PENDING": 5, "RUNNING": 1, "SUCCEEDED": 24},
        "canary_passed": False, "max_model_calls": 1, "target_date": "20261016",
    }
    store.io._files[source_input_ref] = _json_bytes(source_input)

    queue_ref = "announcement_flash/queue/queue-state.json"
    queue = json.loads(source_queue_raw)
    jobs = queue["jobs"]
    source_item = next(item for item in jobs.values() if item.get("status") == "RUNNING")
    source_key = source_item["idempotency_key"]
    source_item.update({"status": "FAILED", "attempt_count": 1, "max_attempts": 1,
                        "attempts": [{"status": "INTERRUPTED", "number": 1,
                                      "error": {"stage": "recovery", "code": "PROCESS_INTERRUPTED"}}]})
    source_payload = json.loads(store.io._files[
        "announcement_flash/queue/" + source_item["input_path"]])
    source_payload["queue_task_kind"] = "announcement_reader_part"
    source_payload_raw = _json_bytes(source_payload)
    store.io._files["announcement_flash/queue/" + source_item["input_path"]] = source_payload_raw
    source_item["payload_sha256"] = _sha(source_payload_raw)
    plan = json.loads(store.io._files[
        f"announcement_flash/jobs/{source_id}/long-body/"
        f"{source_payload['article_id'].replace(':', '_')}-{source_payload['chunk_plan_sha256']}.json"])
    descriptor = source_payload["part_descriptor"]
    recovery = {
        "schema": "v4.manager_workbench.announcement_flash_orphan_recovery.v1",
        "source_idempotency_key": source_key, "source_job_id": root_id,
        "source_input_sha256": root_sha, "source_payload_sha256": source_item["payload_sha256"],
        "source_attempt_count": 1, "chunk_plan_sha256": source_payload["chunk_plan_sha256"],
        "part_sha256": descriptor["part_sha256"],
        "source_unit_map_sha256": source_payload["source_unit_map_sha256"],
    }
    orphan_payload = dict(source_payload)
    orphan_payload["rules"] += "+explicit-orphan-resume:v1"
    orphan_payload["stage"] = "v4_manager_announcement_flash_long_body_part_orphan_resume_v1"
    orphan_payload["interrupted_attempt_recovery"] = recovery
    identity = {field: orphan_payload[field] for field in update_module.FLASH_QUEUE_IDENTITY_FIELDS}
    canary_key = _sha(_json_bytes(identity))
    canary_payload_raw = _json_bytes(orphan_payload)
    canary_input_ref = f"jobs/{canary_key}/input.json"
    raw_ref = f"jobs/{canary_key}/attempt-0001.raw"
    raw_response = _json_bytes({"action": "complete", "lookup_request": None,
                                "reader_output": {"facts": [], "changes": [{"claim": "rejected"}]}})
    store.io._files["announcement_flash/queue/" + canary_input_ref] = canary_payload_raw
    store.io._files["announcement_flash/queue/" + raw_ref] = raw_response
    jobs[canary_key] = {
        "idempotency_key": canary_key, "queue_id": update_module.FLASH_QUEUE_ID,
        "model_id": identity["model_id"], "status": "FAILED", "attempt_count": 1,
        "max_attempts": 1, "identity": identity, "input_path": canary_input_ref,
        "payload_sha256": _sha(canary_payload_raw), "raw_path": raw_ref,
        "raw_sha256": _sha(raw_response),
        "attempts": [{"status": "FAILED", "number": 1,
                      "error": {"stage": "validator", "code": "PART_FIXED_FIELDS_MUST_BE_EMPTY"},
                      "raw_path": raw_ref, "raw_sha256": _sha(raw_response)}],
    }
    store.io._files[queue_ref] = _json_bytes(queue)
    store.io._files[f"announcement_flash/jobs/{source_id}/progress.json"] = _json_bytes({
        "step": "DONE", "queue_counts": {"SUCCEEDED": 24, "FAILED": 16, "PENDING": 5, "RUNNING": 0},
        "total": 45,
    })
    resume = {
        "mode": "FROZEN_BATCH", "source_job_id": root_id, "source_input_sha256": root_sha,
        "source_input_sha256_binding": root_sha,
        "initial_part_status_counts": {"succeeded": 24, "failed": 15, "pending": 5, "running": 1},
        "initial_part_total": 45, "pending_eligible": 0, "failed_preserved": 15,
        "succeeded_preserved": 24, "historical_success_conflicts": 5,
        "orphan_candidates": [{"idempotency_key": canary_key, "source_idempotency_key": source_key,
                               "status": "PENDING", "attempt_count": 0,
                               "binding_sha256": _sha(_json_bytes(recovery))}],
        "recoverable_orphan_count": 0, "max_model_calls": 1, "model_calls": 1,
        "canary_key": canary_key, "canary_status": "FAILED", "canary_model_calls": None,
        "canary_passed": False, "continue_eligible": False, "dispatched_keys": [canary_key],
    }
    # The old result shape predates canary_model_calls; keep only its exact observed fields.
    resume.pop("canary_model_calls")
    store.io._files[f"announcement_flash/jobs/{source_id}/result.json"] = _json_bytes({
        "schema": "v4.manager_workbench.announcement_flash_result.v1", "job_id": source_id,
        "target_trade_date": "20261016", "state": "PARTIAL", "resume": resume,
    })
    service.jobs.get(source_id).state = JobState.PARTIAL
    store.values["announcement_flash_latest"] = {"job_id": source_id, "target_date": "20261016"}
    assert plan["plan_sha256"] == source_payload["chunk_plan_sha256"]
    return canary_key, source_key, root_id


def _append_synthesis_success(service):
    identity = {
        "date": "2026-10-16", "market": "HK",
        "article_id": "EASTMONEY:AN202610161830621605",
        "source_sha256": "2" * 64, "body_sha256": "3" * 64,
        "prompt_sha256": "4" * 64, "model_id": "qwen3_8_flash_next",
        "configuration_sha256": "5" * 64, "rules": "test-synthesis-resume",
        "role": "announcement_reader_synthesis",
        "stage": "v4_manager_announcement_flash_long_body_synthesis_v1",
    }
    key = _sha(_json_bytes(identity))
    payload = {**identity, "queue_task_kind": "announcement_reader_synthesis"}
    payload_raw = _json_bytes(payload)
    validated_raw = _json_bytes({"results": [{"article_id": identity["article_id"],
                                               "reader_output": {"source_sha256": identity["source_sha256"],
                                                                 "body_sha256": identity["body_sha256"]}}]})
    raw_response = _json_bytes({"action": "complete", "lookup_request": None,
                                "reader_output": {"source_sha256": "", "body_sha256": ""}})
    payload_ref = f"jobs/{key}/input.json"
    validated_ref = f"jobs/{key}/attempt-0001.validated.json"
    raw_ref = f"jobs/{key}/attempt-0001.raw"
    queue_ref = "announcement_flash/queue/queue-state.json"
    queue = json.loads(service.store.io._files[queue_ref])
    queue["jobs"][key] = {
        "idempotency_key": key, "queue_id": update_module.FLASH_QUEUE_ID,
        "model_id": identity["model_id"], "status": "SUCCEEDED", "attempt_count": 1,
        "max_attempts": 1, "identity": identity, "input_path": payload_ref,
        "payload_sha256": _sha(payload_raw), "validated_path": validated_ref,
        "validated_sha256": _sha(validated_raw), "raw_path": raw_ref,
        "raw_sha256": _sha(raw_response),
    }
    prefix = "announcement_flash/queue/"
    service.store.io._files[prefix + payload_ref] = payload_raw
    service.store.io._files[prefix + validated_ref] = validated_raw
    service.store.io._files[prefix + raw_ref] = raw_response
    service.store.io._files[queue_ref] = _json_bytes(queue)
    return key, _sha(payload_raw), _sha(validated_raw), _sha(raw_response)


def _append_post_c039_pdf_queue_extension(service):
    queue_ref = "announcement_flash/queue/queue-state.json"
    queue = json.loads(service.store.io._files[queue_ref])
    queue_id = update_module.FAILED_DISPATCH_CANARY_REENTRY_PDF_QUEUE_ID
    identity = {
        "date": "20261018", "market": "PDF", "article_id": "ZSXQ-PDF-test-source",
        "source_sha256": "1" * 64, "body_sha256": _sha(b"pdf classification body"),
        "prompt_sha256": "2" * 64, "model_id": "qwen3_8_flash_next",
        "configuration_sha256": "3" * 64,
        "rules": "v4_zsxq_pdf_local_classification_v1",
        "role": "document_classifier", "stage": "local_pdf_classification",
    }
    key = _sha(update_module._canonical(identity))
    payload = {**identity, "article_body": "pdf classification body",
               "messages": [], "page_count": 1,
               "structured_output_schema": {"type": "object"}, "text_truncated": False}
    payload_raw = _json_bytes(payload)
    created_at = "2026-10-18T07:42:44.688Z"
    started_at = "2026-10-18T07:42:44.777Z"
    finished_at = "2026-10-18T07:42:44.786Z"
    error = {"code": "MODEL_TRANSPORT_FAILED", "message": "TransportError",
             "stage": "executor", "type": "ExecutorFailure"}
    item = {
        "attempt_count": 1,
        "attempts": [{"consumer_queue_id": queue_id, "duration_seconds": 0.001125,
                      "error": error, "finished_at": finished_at, "number": 1,
                      "raw_length_bytes": None, "raw_path": None, "raw_sha256": None,
                      "started_at": started_at, "status": "FAILED",
                      "validated_path": None, "validated_sha256": None}],
        "body_length_bytes": len(payload["article_body"].encode()),
        "created_at": created_at, "idempotency_key": key, "identity": identity,
        "input_path": f"jobs/{key}/input.json", "last_error": error,
        "max_attempts": 1, "missing_material": [], "model_id": identity["model_id"],
        "payload_sha256": _sha(payload_raw), "queue_id": queue_id, "queue_ids": [queue_id],
        "queue_policy": {"max_attempts": 1, "max_body_bytes": None},
        "raw_path": None, "raw_sha256": None, "status": "FAILED",
        "updated_at": finished_at, "validated_path": None, "validated_sha256": None,
    }
    queue["jobs"][key] = item
    queue["events"].extend([
        {"at": created_at, "attempt": 0, "body_length_bytes": item["body_length_bytes"],
         "event": "item_enqueued", "idempotency_key": key, "missing_material": [],
         "model_id": item["model_id"], "queue_id": queue_id, "status": "PENDING"},
        {"at": started_at, "attempt": 1, "body_length_bytes": item["body_length_bytes"],
         "event": "attempt_started", "idempotency_key": key, "model_id": item["model_id"],
         "queue_id": queue_id, "status": "RUNNING"},
        {"at": finished_at, "attempt": 1, "duration_seconds": 0.001125,
         "error": error, "event": "attempt_failed", "idempotency_key": key,
         "model_id": item["model_id"], "queue_id": queue_id, "status": "FAILED"},
    ])
    service.store.io._files[queue_ref] = _json_bytes(queue)
    service.store.io._files[f"announcement_flash/queue/jobs/{key}/input.json"] = payload_raw
    return key


def _build_c039_reentry_fixture(tmp_path, monkeypatch):
    source_id = update_module.FAILED_DISPATCH_CANARY_REENTRY_SOURCE_JOB_ID
    service, source_id = _resume_service(
        tmp_path, source_job_id=source_id, running_part_index=17,
        source_publication_date="2026-10-14", plan_part_counts=(22, 23))
    queue_ref = "announcement_flash/queue/queue-state.json"
    queue_state = json.loads(service.store.io._files[queue_ref])
    queue_state.setdefault("created_at", "2026-10-18T06:00:00Z")
    queue_state.setdefault("events", [])
    service.store.io._files[queue_ref] = _json_bytes(queue_state)
    canary_key, source_part_key, root_id = _mark_precontract_orphan_failed_canary(
        service, source_id, root_job_id=update_module.FAILED_DISPATCH_CANARY_REENTRY_ROOT_JOB_ID)
    update = AnnouncementUpdate(service)
    parent_snapshot = update._resume_source_artifacts(source_id, "20261016")
    old_update, _old_snapshot, old_wrapper = _make_failed_nameerror_resume_wrapper(service, source_id)
    old_request = old_wrapper.context.scope_refs["announcement_flash_resume_request"]
    old_slot = "announcement_flash_resume_" + update_module.digest(old_request)
    old_cursor = dict(service.store.values[old_slot])
    old_attempt = service.store.io._files[f"attempts/{old_wrapper.job_id}.json"]

    parent_input_raw = service.store.io._files[f"announcement_flash/jobs/{source_id}/input.json"]
    parent_progress_raw = service.store.io._files[f"announcement_flash/jobs/{source_id}/progress.json"]
    parent_result_raw = service.store.io._files[f"announcement_flash/jobs/{source_id}/result.json"]
    parent_input = json.loads(parent_input_raw)
    source_binding = {key: parent_snapshot.get(key) for key in (
        "schema", "mode", "source_job_id", "target_date", "source_input_sha256",
        "source_progress_sha256", "source_queue_state_sha256", "source_result_sha256",
        "capture_product_sha256", "canary_passed", "canary_key", "canary_status",
        "canary_model_calls", "legacy_failed_canary", "resume_action", "max_model_calls",
        "queue_status_counts")}
    legacy = parent_snapshot["legacy_failed_canary"]
    source_binding["canary_validation"] = {
        "status": "LEGACY_FAILED_FIXED_FIELDS",
        "failure_code": "PART_FIXED_FIELDS_MUST_BE_EMPTY", "key": canary_key,
        "payload_sha256": legacy["payload_sha256"], "raw_sha256": legacy["raw_sha256"],
    }
    source_binding = {key: source_binding[key] for key in (
        "schema", "mode", "source_job_id", "target_date", "source_input_sha256",
        "source_progress_sha256", "source_queue_state_sha256", "source_result_sha256",
        "capture_product_sha256", "canary_passed", "canary_key", "canary_status",
        "canary_model_calls", "canary_validation", "legacy_failed_canary", "resume_action",
        "max_model_calls", "queue_status_counts")}
    synthesis_key, synthesis_payload_sha, synthesis_validated_sha, synthesis_raw_sha = \
        _append_synthesis_success(service)
    current_queue_sha = _sha(service.store.io._files["announcement_flash/queue/queue-state.json"])
    c039_id = update_module.FAILED_DISPATCH_CANARY_REENTRY_JOB_ID
    c039_input = {"schema": "v4.manager_workbench.announcement_flash_input.v1", "job_id": c039_id,
                  "target_date": "20261016", "cutoff": parent_input["cutoff"],
                  "capture_product": parent_input["capture_product"],
                  "membership_gate": parent_input["membership_gate"],
                  "resume_root": parent_input["resume_root"], "resume_source": source_binding}
    c039_progress = {"step": "DONE", "total": 6}
    c039_resume = {
        "mode": "FROZEN_BATCH", "resume_action": "CANARY", "canary_passed": False,
        "canary_key": None, "canary_status": None, "canary_model_calls": 0,
        "canary_validation": {"failure_code": "FROZEN_RESUME_CANARY_NOT_SUCCEEDED",
                              "key": None, "status": "FAIL"},
        "max_model_calls": 1, "model_calls": 1, "dispatched_keys": [synthesis_key],
        "source_job_id": root_id, "source_input_sha256": parent_input["resume_root"]["source_input_sha256"],
        "source_input_sha256_binding": _sha(parent_input_raw),
        "initial_part_status_counts": {"failed": 16, "pending": 5, "succeeded": 24},
        "initial_part_total": 45, "failed_preserved": 16, "succeeded_preserved": 24,
        "pending_eligible": 0, "recoverable_orphan_count": 0, "continue_eligible": False,
    }
    c039_result = {"schema": "v4.manager_workbench.announcement_flash_result.v1", "job_id": c039_id,
                   "target_trade_date": "20261016", "state": "PARTIAL", "resume": c039_resume}
    c039_input_raw = _json_bytes(c039_input)
    c039_progress_raw = _json_bytes(c039_progress)
    c039_result_raw = _json_bytes(c039_result)
    service.store.io._files[f"announcement_flash/jobs/{c039_id}/input.json"] = c039_input_raw
    service.store.io._files[f"announcement_flash/jobs/{c039_id}/progress.json"] = c039_progress_raw
    service.store.io._files[f"announcement_flash/jobs/{c039_id}/result.json"] = c039_result_raw
    plan_prefix = f"announcement_flash/jobs/{source_id}/long-body/"
    for ref, raw in list(service.store.io._files.items()):
        if ref.startswith(plan_prefix):
            service.store.io._files[ref.replace(f"jobs/{source_id}/", f"jobs/{c039_id}/", 1)] = raw
    c039_job = SimpleNamespace(job_id=c039_id, state=JobState.PARTIAL,
                               context=SimpleNamespace(target_date="20261016", cutoff=parent_input["cutoff"],
                                   scope_refs={"capture_operation": update_module.FROZEN_RESUME_OPERATION}))
    service.jobs.jobs[c039_id] = c039_job
    service.store.io._files[f"attempts/{c039_id}.json"] = _json_bytes({
        "job_id": c039_id, "state": "PARTIAL", "step": "DONE", "retryable": False,
        "started_at": "2026-10-18T14:24:55.729040+08:00",
        "finished_at": update_module.FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_FINISHED_AT,
        "context": {"target_date": "20261016", "cutoff": parent_input["cutoff"],
                    "scope_refs": {"capture_operation": update_module.FROZEN_RESUME_OPERATION}}})
    _append_post_c039_pdf_queue_extension(service)
    service.store.values["announcement_flash_latest"] = {"job_id": c039_id, "target_date": "20261016"}

    pins = {
        "FAILED_DISPATCH_CANARY_REENTRY_INPUT_SHA256": _sha(c039_input_raw),
        "FAILED_DISPATCH_CANARY_REENTRY_PROGRESS_SHA256": _sha(c039_progress_raw),
        "FAILED_DISPATCH_CANARY_REENTRY_RESULT_SHA256": _sha(c039_result_raw),
        "FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256": current_queue_sha,
        "FAILED_DISPATCH_CANARY_REENTRY_ATTEMPT_SHA256": _sha(
            service.store.io._files[f"attempts/{c039_id}.json"]),
        "FAILED_DISPATCH_CANARY_REENTRY_PARENT_INPUT_SHA256": _sha(parent_input_raw),
        "FAILED_DISPATCH_CANARY_REENTRY_PARENT_PROGRESS_SHA256": _sha(parent_progress_raw),
        "FAILED_DISPATCH_CANARY_REENTRY_PARENT_RESULT_SHA256": _sha(parent_result_raw),
        "FAILED_DISPATCH_CANARY_REENTRY_PARENT_QUEUE_SHA256": parent_snapshot["source_queue_state_sha256"],
        "FAILED_DISPATCH_CANARY_REENTRY_ROOT_INPUT_SHA256": parent_input["resume_root"]["source_input_sha256"],
        "FAILED_DISPATCH_CANARY_REENTRY_KEY": canary_key,
        "FAILED_DISPATCH_CANARY_REENTRY_SOURCE_PART_KEY": source_part_key,
        "FAILED_DISPATCH_CANARY_REENTRY_PART_INDEX": legacy["part_descriptor"]["part_index"],
        "FAILED_DISPATCH_CANARY_REENTRY_PART_COUNT": legacy["part_descriptor"]["part_count"],
        "FAILED_DISPATCH_CANARY_REENTRY_CANARY_PAYLOAD_SHA256": legacy["payload_sha256"],
        "FAILED_DISPATCH_CANARY_REENTRY_CANARY_RAW_SHA256": legacy["raw_sha256"],
        "FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY": synthesis_key,
        "FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_PAYLOAD_SHA256": synthesis_payload_sha,
        "FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_VALIDATED_SHA256": synthesis_validated_sha,
        "FAILED_DISPATCH_CANARY_REENTRY_SYNTHESIS_RAW_SHA256": synthesis_raw_sha,
    }
    for name, value in pins.items():
        monkeypatch.setattr(update_module, name, value)
    return service, update, c039_id, old_wrapper, old_slot, old_cursor, old_attempt, pins


def _make_failed_nameerror_resume_wrapper(service, source_id):
    update = AnnouncementUpdate(service)
    snapshot = update.resume_snapshot("20261016")
    assert snapshot["eligible"] is True
    first = update.start_resume("20261016", source_id, snapshot["source_input_sha256"],
                                snapshot["source_progress_sha256"],
                                snapshot["source_queue_state_sha256"], "CANARY")
    old_id = first.job_id
    del service.jobs.jobs[old_id]
    first.job_id = update_module.FAILED_CANARY_REENTRY_JOB_ID
    first.state = JobState.FAILED
    first.step = "FLASH_SELECTION"
    first.failure_code = "FLASH_PIPELINE_NAMEERROR"
    first.failed_steps = ["FLASH_SELECTION"]
    first.retryable = False
    first.completed_count = 0
    service.jobs.jobs[first.job_id] = first
    for cursor_name, cursor in list(service.store.values.items()):
        if isinstance(cursor, dict) and cursor.get("job_id") == old_id:
            service.store.values[cursor_name] = {**cursor, "job_id": first.job_id}

    binding = first.context.scope_refs["announcement_flash_resume"]
    source_input = json.loads(service.store.io._files[
        f"announcement_flash/jobs/{source_id}/input.json"])
    resume_source = {key: binding.get(key) for key in (
        "schema", "mode", "source_job_id", "target_date", "source_input_sha256",
        "source_progress_sha256", "source_queue_state_sha256", "capture_product_sha256",
        "source_result_sha256", "canary_passed", "canary_key", "canary_status",
        "canary_model_calls", "canary_validation", "legacy_failed_canary", "resume_action",
        "max_model_calls", "queue_status_counts")}
    wrapper_input = {"schema": "v4.manager_workbench.announcement_flash_input.v1",
                     "job_id": first.job_id, "target_date": "20261016",
                     "cutoff": first.context.cutoff,
                     "capture_product": source_input["capture_product"],
                     "membership_gate": source_input["membership_gate"],
                     "resume_root": binding["resume_root"], "resume_source": resume_source}
    service.store.io._files[
        f"announcement_flash/jobs/{first.job_id}/input.json"] = _json_bytes(wrapper_input)
    service.store.io._files[
        f"announcement_flash/jobs/{first.job_id}/progress.json"] = _json_bytes({
            "step": "FAILED", "failure_code": "FLASH_PIPELINE_NAMEERROR",
            "diagnostic": {"exception_type": "NameError",
                           "stack_frames": update_module.FAILED_CANARY_REENTRY_STACK}})
    service.store.io._files[f"attempts/{first.job_id}.json"] = _json_bytes({
        "job_id": first.job_id, "state": "FAILED", "step": "FLASH_SELECTION",
        "failure_code": "FLASH_PIPELINE_NAMEERROR", "failed_steps": ["FLASH_SELECTION"],
        "retryable": False, "completed_count": 0,
        "context": {"target_date": "20261016", "cutoff": first.context.cutoff,
                    "scope_refs": first.context.scope_refs}})
    return update, snapshot, first


def _pin_failed_wrapper_fixture_hashes(monkeypatch, service, wrapper_id):
    for name, ref in (
        ("FAILED_CANARY_REENTRY_INPUT_SHA256", f"announcement_flash/jobs/{wrapper_id}/input.json"),
        ("FAILED_CANARY_REENTRY_PROGRESS_SHA256", f"announcement_flash/jobs/{wrapper_id}/progress.json"),
        ("FAILED_CANARY_REENTRY_ATTEMPT_SHA256", f"attempts/{wrapper_id}.json"),
    ):
        monkeypatch.setattr(update_module, name, _sha(service.store.io._files[ref]))


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


def test_resume_snapshot_binds_transport_failure_canary_and_original_pending_tasks(tmp_path):
    service, source_id = _resume_service(tmp_path)
    failed_key, pending_key = _mark_transport_system_stop(service, source_id)

    snapshot = AnnouncementUpdate(service).resume_snapshot("20261016")

    assert snapshot["eligible"] is True
    assert snapshot["resume_action"] == "CANARY"
    assert snapshot["transport_recovery"]["failed_task"]["key"] == failed_key
    assert [item["key"] for item in snapshot["transport_recovery"]["pending_tasks"]] == [pending_key]


def test_transport_resume_post_carries_the_hash_bound_recovery_plan(tmp_path):
    service, source_id = _resume_service(tmp_path)
    _mark_transport_system_stop(service, source_id)
    update = AnnouncementUpdate(service)
    snapshot = update.resume_snapshot("20261016")
    queue_ref = "announcement_flash/queue/queue-state.json"
    queue_sha_before = _sha(service.store.io._files[queue_ref])

    job = update.start_resume("20261016", source_id, snapshot["source_input_sha256"],
                              snapshot["source_progress_sha256"],
                              snapshot["source_queue_state_sha256"], "CANARY")

    binding = job.context.scope_refs["announcement_flash_resume"]
    request = job.context.scope_refs["announcement_flash_resume_request"]
    assert binding["transport_recovery"] == snapshot["transport_recovery"]
    assert binding["resume_action"] == "CANARY"
    assert binding["max_model_calls"] == 1
    assert request["source_job_id"] == source_id
    assert request["source_input_sha256"] == snapshot["source_input_sha256"]
    assert _sha(service.store.io._files[queue_ref]) == queue_sha_before


def test_resume_snapshot_rejects_non_transport_system_stop(tmp_path):
    service, source_id = _resume_service(tmp_path)
    _mark_transport_system_stop(service, source_id)
    result_ref = f"announcement_flash/jobs/{source_id}/result.json"
    result = json.loads(service.store.io._files[result_ref])
    result["system_stop"]["failure_code"] = "VALIDATOR_REJECTED"
    service.store.io._files[result_ref] = _json_bytes(result)

    snapshot = AnnouncementUpdate(service).resume_snapshot("20261016")
    assert snapshot["eligible"] is False
    assert snapshot["reason"] == "RESUME_TRANSPORT_SYSTEM_STOP_NOT_EXACT"


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


def test_resume_snapshot_admits_only_exact_legacy_fixed_field_failure_for_new_canary(tmp_path):
    service, source_id = _resume_service(tmp_path)
    failed_key = _mark_legacy_failed_canary(service, source_id)

    snapshot = AnnouncementUpdate(service).resume_snapshot("20261016")

    assert snapshot["eligible"] is True
    assert snapshot["mode"] == "INITIAL_CANARY"
    assert snapshot["resume_action"] == "CANARY"
    assert snapshot["canary_passed"] is False
    assert snapshot["canary_key"] == failed_key
    assert snapshot["legacy_failed_canary"]["key"] == failed_key
    assert snapshot["legacy_failed_canary"]["source_job_id"] == source_id
    assert snapshot["legacy_failed_canary"]["source_part_key"]
    assert snapshot["queue_status_counts"] == {"SUCCEEDED": 24, "FAILED": 16, "PENDING": 5}


def test_resume_snapshot_admits_only_the_exact_precontract_orphan_canary_artifact_chain(tmp_path):
    service, source_id = _resume_service(tmp_path, source_publication_date="2026-10-14")
    # Production config models expose capture_root as pathlib.Path.
    service.config.capture_root = Path(service.config.capture_root)
    canary_key, source_part_key, root_id = _mark_precontract_orphan_failed_canary(service, source_id)

    snapshot = AnnouncementUpdate(service).resume_snapshot("20261016")

    assert snapshot["eligible"] is True
    assert snapshot["mode"] == "INITIAL_CANARY"
    assert snapshot["resume_action"] == "CANARY"
    assert snapshot["max_model_calls"] == 1
    assert snapshot["canary_key"] == canary_key
    assert snapshot["legacy_failed_canary"]["key"] == canary_key
    assert snapshot["legacy_failed_canary"]["root_job_id"] == root_id
    assert snapshot["legacy_failed_canary"]["source_part_key"] == source_part_key
    assert snapshot["legacy_failed_canary"]["part_descriptor"]["part_index"] == 45
    assert snapshot["queue_status_counts"] == {"SUCCEEDED": 24, "FAILED": 16, "PENDING": 5}


def test_resume_snapshot_rejects_precontract_orphan_canary_if_root_plan_no_longer_matches(tmp_path):
    service, source_id = _resume_service(tmp_path, source_publication_date="2026-10-14")
    _canary_key, _source_part_key, root_id = _mark_precontract_orphan_failed_canary(service, source_id)
    plan_ref = next(ref for ref in service.store.io._files
                    if ref.startswith(f"announcement_flash/jobs/{root_id}/long-body/"))
    plan = json.loads(service.store.io._files[plan_ref])
    plan["parts"][0]["part_sha256"] = "0" * 64
    service.store.io._files[plan_ref] = _json_bytes(plan)

    snapshot = AnnouncementUpdate(service).resume_snapshot("20261016")

    assert snapshot["eligible"] is False
    assert snapshot["reason"] == "RESUME_LEGACY_ORPHAN_SOURCE_BINDING_UNVERIFIED"


def test_resume_snapshot_rejects_legacy_failure_with_different_validator_code(tmp_path):
    service, source_id = _resume_service(tmp_path)
    failed_key = _mark_legacy_failed_canary(service, source_id)
    queue_ref = "announcement_flash/queue/queue-state.json"
    queue = json.loads(service.store.io._files[queue_ref])
    queue["jobs"][failed_key]["attempts"][0]["error"]["code"] = "OTHER_VALIDATOR_FAILURE"
    service.store.io._files[queue_ref] = _json_bytes(queue)
    service.store.values["announcement_flash_latest"] = {"job_id": source_id, "target_date": "20261016"}

    snapshot = AnnouncementUpdate(service).resume_snapshot("20261016")

    assert snapshot["eligible"] is False
    assert snapshot["reason"] == "RESUME_LEGACY_CANARY_FAILURE_NOT_EXACT"


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
                                snapshot["source_progress_sha256"], snapshot["source_queue_state_sha256"], "CANARY")
    second = update.start_resume("20261016", source_id, snapshot["source_input_sha256"],
                                 snapshot["source_progress_sha256"], snapshot["source_queue_state_sha256"], "CANARY")

    assert first is second
    assert len(service.jobs.submissions) == 1
    assert first.context.scope_refs["capture_operation"] == "ANNOUNCEMENT_FLASH_RESUME"
    assert first.context.scope_refs["announcement_flash_resume"]["max_model_calls"] == 1
    assert first.context.scope_refs["announcement_flash_resume"]["resume_action"] == "CANARY"
    assert first.context.scope_refs["announcement_flash_resume"]["resume_root"] == {
        "source_job_id": source_id, "source_input_sha256": snapshot["source_input_sha256"]}


def test_exact_zero_dispatch_nameerror_wrapper_reopens_existing_resume_path_once(tmp_path, monkeypatch):
    source_id = "29983573dff34359bfd34f054641a1d6"
    service, source_id = _resume_service(tmp_path, source_job_id=source_id)
    _canary_key, _source_key, root_id = _mark_precontract_orphan_failed_canary(service, source_id)
    root_input_sha256 = _sha(service.store.io._files[f"announcement_flash/jobs/{root_id}/input.json"])
    update, initial_snapshot, failed_wrapper = _make_failed_nameerror_resume_wrapper(service, source_id)
    wrapper_id = failed_wrapper.job_id
    _pin_failed_wrapper_fixture_hashes(monkeypatch, service, wrapper_id)
    old_attempt_raw = service.store.io._files[f"attempts/{wrapper_id}.json"]
    old_request = failed_wrapper.context.scope_refs["announcement_flash_resume_request"]
    old_slot = "announcement_flash_resume_" + update_module.digest(old_request)
    old_cursor = dict(service.store.values[old_slot])
    queue_ref = "announcement_flash/queue/queue-state.json"
    queue_sha_before = _sha(service.store.io._files[queue_ref])

    snapshot = update.resume_snapshot("20261016")
    assert snapshot["eligible"] is True
    assert snapshot["source_job_id"] == source_id
    assert snapshot["legacy_failed_canary"]["source_part_key"]

    first = update.start_resume("20261016", source_id, snapshot["source_input_sha256"],
                                snapshot["source_progress_sha256"],
                                snapshot["source_queue_state_sha256"], "CANARY")
    submitted_worker = service.jobs.submissions[-1][1]
    second = update.start_resume("20261016", source_id, snapshot["source_input_sha256"],
                                 snapshot["source_progress_sha256"],
                                 snapshot["source_queue_state_sha256"], "CANARY")

    new_request = first.context.scope_refs["announcement_flash_resume_request"]
    new_slot = "announcement_flash_resume_" + update_module.digest(new_request)
    assert first is second
    assert first.job_id != wrapper_id
    assert len(service.jobs.submissions) == 2
    assert new_request["reentry_from_job_id"] == wrapper_id
    assert new_request["reentry_contract"] == update_module.FAILED_CANARY_REENTRY_CONTRACT
    assert re.fullmatch(r"[0-9a-f]{64}", new_request["reentry_evidence_sha256"])
    assert first.context.scope_refs["announcement_flash_resume"]["source_job_id"] == source_id
    assert first.context.scope_refs["announcement_flash_resume"]["legacy_failed_canary"]["source_part_key"] == \
        snapshot["legacy_failed_canary"]["source_part_key"]
    assert first.context.scope_refs["announcement_flash_resume"]["resume_root"] == {
        "source_job_id": root_id, "source_input_sha256": root_input_sha256}
    assert submitted_worker.__self__ is update
    assert submitted_worker.__func__ is AnnouncementUpdate._work
    assert service.jobs.get(wrapper_id).state is JobState.FAILED
    assert service.store.values[old_slot] == old_cursor
    assert service.store.io._files[f"attempts/{wrapper_id}.json"] == old_attempt_raw
    assert service.store.values[new_slot]["job_id"] == first.job_id
    assert _sha(service.store.io._files[queue_ref]) == queue_sha_before


@pytest.mark.parametrize("mutation, expected_reason", [
    ("dispatched", "RESUME_FAILED_WRAPPER_NOT_PRE_DISPATCH_CRASH"),
    ("source", "RESUME_FAILED_WRAPPER_BINDING_UNVERIFIED"),
    ("queue", "RESUME_SOURCE_SHA_CHANGED"),
])
def test_failed_canary_reentry_rejects_dispatch_source_or_queue_mismatch(
        tmp_path, monkeypatch, mutation, expected_reason):
    source_id = "29983573dff34359bfd34f054641a1d6"
    service, source_id = _resume_service(tmp_path, source_job_id=source_id)
    _mark_precontract_orphan_failed_canary(service, source_id)
    update, initial_snapshot, failed_wrapper = _make_failed_nameerror_resume_wrapper(service, source_id)
    attempt_ref = f"attempts/{failed_wrapper.job_id}.json"
    _pin_failed_wrapper_fixture_hashes(monkeypatch, service, failed_wrapper.job_id)
    attempt = json.loads(service.store.io._files[attempt_ref])
    if mutation == "dispatched":
        attempt["completed_count"] = 1
        failed_wrapper.completed_count = 1
        service.store.io._files[attempt_ref] = _json_bytes(attempt)
        monkeypatch.setattr(update_module, "FAILED_CANARY_REENTRY_ATTEMPT_SHA256",
                            _sha(service.store.io._files[attempt_ref]))
    elif mutation == "source":
        scope = failed_wrapper.context.scope_refs
        scope["announcement_flash_resume_request"]["source_job_id"] = "c" * 32
        attempt["context"]["scope_refs"] = scope
        service.store.io._files[attempt_ref] = _json_bytes(attempt)
        monkeypatch.setattr(update_module, "FAILED_CANARY_REENTRY_ATTEMPT_SHA256",
                            _sha(service.store.io._files[attempt_ref]))
    else:
        service.store.io._files["announcement_flash/queue/queue-state.json"] += b" "

    snapshot = update.resume_snapshot("20261016")

    assert snapshot["eligible"] is False
    assert snapshot["reason"] == expected_reason
    with pytest.raises(JobConflict, match=expected_reason):
        update.start_resume("20261016", source_id, initial_snapshot["source_input_sha256"],
                            initial_snapshot["source_progress_sha256"],
                            initial_snapshot["source_queue_state_sha256"], "CANARY")
    assert len(service.jobs.submissions) == 1


def test_c039_reentry_verifies_2998_root_target_and_uses_new_idempotent_page_slot(tmp_path, monkeypatch):
    (service, update, source_id, old_wrapper, old_slot, old_cursor,
     old_attempt, pins) = _build_c039_reentry_fixture(tmp_path, monkeypatch)
    queue_ref = "announcement_flash/queue/queue-state.json"
    queue_sha_before = _sha(service.store.io._files[queue_ref])

    snapshot = update.resume_snapshot("20261016")

    assert snapshot["eligible"] is True
    assert snapshot["source_job_id"] == source_id
    assert snapshot["mode"] == "INITIAL_CANARY"
    assert snapshot["resume_action"] == "CANARY"
    assert snapshot["canary_key"] == pins["FAILED_DISPATCH_CANARY_REENTRY_KEY"]
    assert snapshot["legacy_failed_canary"]["source_job_id"] == update_module.FAILED_DISPATCH_CANARY_REENTRY_SOURCE_JOB_ID
    assert snapshot["legacy_failed_canary"]["root_job_id"] == update_module.FAILED_DISPATCH_CANARY_REENTRY_ROOT_JOB_ID
    assert snapshot["legacy_failed_canary"]["source_part_key"] == pins["FAILED_DISPATCH_CANARY_REENTRY_SOURCE_PART_KEY"]
    assert snapshot["legacy_failed_canary"]["part_descriptor"]["part_index"] == 17
    assert snapshot["legacy_failed_canary"]["part_descriptor"]["part_count"] == 22
    assert snapshot["queue_status_counts"] == {"SUCCEEDED": 24, "FAILED": 16, "PENDING": 5}
    reconstruction = snapshot["queue_reconstruction"]
    assert reconstruction["baseline_sha256"] == pins["FAILED_DISPATCH_CANARY_REENTRY_QUEUE_SHA256"]
    assert reconstruction["reconstructed_sha256"] == reconstruction["baseline_sha256"]
    assert reconstruction["current_sha256"] == snapshot["source_queue_state_sha256"]
    assert len(reconstruction["excluded_jobs"]) == 1
    assert reconstruction["excluded_jobs"][0]["queue_id"] == update_module.FAILED_DISPATCH_CANARY_REENTRY_PDF_QUEUE_ID
    assert reconstruction["excluded_jobs"][0]["event_count"] == 3

    state_root = tmp_path / "runner-state"
    for ref, raw in service.store.io._files.items():
        path = state_root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    runner = _runner()
    for name, value in pins.items():
        if hasattr(runner, name):
            monkeypatch.setattr(runner, name, value)
    runner_hashes = {
        "source_input_sha256": _sha(service.store.io._files[
            f"announcement_flash/jobs/{source_id}/input.json"]),
        "source_progress_sha256": _sha(service.store.io._files[
            f"announcement_flash/jobs/{source_id}/progress.json"]),
        "source_queue_state_sha256": queue_sha_before,
    }
    verified_input, verified_queue, verified_legacy = runner._verify_resume_source(
        runner.SafeRoot(state_root), Path(service.config.capture_root), source_id,
        "20261016", runner_hashes,
        expected_queue_reconstruction=snapshot["queue_reconstruction"])
    assert verified_input["resume_source"]["source_job_id"] == update_module.FAILED_DISPATCH_CANARY_REENTRY_SOURCE_JOB_ID
    assert verified_input["resume_root"]["source_job_id"] == update_module.FAILED_DISPATCH_CANARY_REENTRY_ROOT_JOB_ID
    assert verified_legacy["key"] == snapshot["legacy_failed_canary"]["key"]
    assert verified_legacy["source_part_key"] == snapshot["legacy_failed_canary"]["source_part_key"]
    assert verified_legacy["part_descriptor"]["part_index"] == 17
    assert verified_legacy["part_descriptor"]["part_count"] == 22
    assert verified_queue["jobs"][pins["FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY"]]["status"] == "SUCCEEDED"
    changed_proof = dict(snapshot["queue_reconstruction"])
    changed_proof["baseline_sha256"] = "0" * 64
    with pytest.raises(runner.FlashRunError, match="FROZEN_RESUME_C039_QUEUE_RECONSTRUCTION_BINDING_CHANGED"):
        runner._verify_resume_source(
            runner.SafeRoot(state_root), Path(service.config.capture_root), source_id,
            "20261016", runner_hashes, expected_queue_reconstruction=changed_proof)

    first = update.start_resume("20261016", source_id, snapshot["source_input_sha256"],
                                snapshot["source_progress_sha256"],
                                snapshot["source_queue_state_sha256"], "CANARY")
    second = update.start_resume("20261016", source_id, snapshot["source_input_sha256"],
                                 snapshot["source_progress_sha256"],
                                 snapshot["source_queue_state_sha256"], "CANARY")
    new_request = first.context.scope_refs["announcement_flash_resume_request"]
    new_binding = first.context.scope_refs["announcement_flash_resume"]
    new_slot = "announcement_flash_resume_" + update_module.digest(new_request)
    assert first is second
    assert first.job_id != old_wrapper.job_id
    assert new_request["source_job_id"] == source_id
    assert new_request["source_queue_state_sha256"] == snapshot["source_queue_state_sha256"]
    assert new_binding["queue_reconstruction"] == snapshot["queue_reconstruction"]
    assert "reentry_from_job_id" not in new_request
    assert new_slot != old_slot
    assert len(service.jobs.submissions) == 2
    assert service.jobs.get(old_wrapper.job_id).state is JobState.FAILED
    assert service.store.values[old_slot] == old_cursor
    assert service.store.io._files[f"attempts/{old_wrapper.job_id}.json"] == old_attempt
    assert service.store.values[new_slot]["job_id"] == first.job_id
    assert _sha(service.store.io._files[queue_ref]) == queue_sha_before


@pytest.mark.parametrize("mutation", ["protected_record", "target_queue_addition", "unrelated_event"])
def test_c039_reentry_rejects_queue_changes_outside_verified_pdf_additions(tmp_path, monkeypatch, mutation):
    (service, update, _source_id, _old_wrapper, _old_slot, _old_cursor,
     _old_attempt, pins) = _build_c039_reentry_fixture(tmp_path, monkeypatch)
    queue_ref = "announcement_flash/queue/queue-state.json"
    queue = json.loads(service.store.io._files[queue_ref])
    if mutation == "protected_record":
        key = pins["FAILED_DISPATCH_CANARY_REENTRY_PRESERVED_SYNTHESIS_KEY"]
        queue["jobs"][key]["status"] = "FAILED"
    elif mutation == "target_queue_addition":
        key = "a" * 64
        queue["jobs"][key] = {"idempotency_key": key, "queue_id": update_module.FLASH_QUEUE_ID,
                              "status": "PENDING", "attempt_count": 0}
    else:
        queue["events"].append({"at": "2026-10-18T07:42:45.000Z", "attempt": 1,
                                "event": "unexpected", "idempotency_key": "b" * 64,
                                "model_id": "qwen3_8_flash_next", "queue_id": "other-queue",
                                "status": "FAILED"})
    service.store.io._files[queue_ref] = _json_bytes(queue)

    snapshot = update.resume_snapshot("20261016")

    assert snapshot["eligible"] is False
    assert snapshot["reason"] == "RESUME_C039_QUEUE_BASE_SHA_MISMATCH"
    with pytest.raises(JobConflict, match="RESUME_C039_QUEUE_BASE_SHA_MISMATCH"):
        update.start_resume("20261016", update_module.FAILED_DISPATCH_CANARY_REENTRY_JOB_ID,
                            pins["FAILED_DISPATCH_CANARY_REENTRY_INPUT_SHA256"],
                            pins["FAILED_DISPATCH_CANARY_REENTRY_PROGRESS_SHA256"],
                            _sha(service.store.io._files[queue_ref]), "CANARY")
    assert len(service.jobs.submissions) == 1


def test_resume_post_rejects_changed_queue_sha_before_submission(tmp_path):
    service, source_id = _resume_service(tmp_path)
    update = AnnouncementUpdate(service)
    snapshot = update.resume_snapshot("20261016")
    service.store.io._files["announcement_flash/queue/queue-state.json"] += b" "

    with pytest.raises(JobConflict, match="RESUME_SOURCE_SHA_CHANGED"):
        update.start_resume("20261016", source_id, snapshot["source_input_sha256"],
                            snapshot["source_progress_sha256"], snapshot["source_queue_state_sha256"], "CANARY")

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
               "source_queue_state_sha256": "3" * 64, "resume_action": "CANARY"}

    response = client.post(api.PREFIX + "/announcement-flash/resume", json=payload)

    assert response.status_code == 202
    assert response.json()["data"]["source_job_id"] == source_id
    assert calls == [("20261016", source_id, "1" * 64, "2" * 64, "3" * 64, "CANARY")]


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
    _bind_resume_part_payload(payload)
    identity_fields = bridge.QUEUE_IDENTITY_FIELDS
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
    _bind_resume_part_payload(payload, part_index=17, part_count=22,
                              source_unit_map_sha256="f249b6761e8bd725cfa45d4ae19b3b0a72c0683ff2aab412214f1c81014724fc",
                              chunk_plan_sha256="95b16ef29a386487561b277b1cfe67316c162da28de68deffa5883b076d895b1",
                              part_sha256="b07893a143bd84e8b7fa36eca9af901ef36032b4227d99aa85d8d89866499571")
    identity_fields = bridge.QUEUE_IDENTITY_FIELDS
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
    _bind_resume_part_payload(payload)
    identity_fields = bridge.QUEUE_IDENTITY_FIELDS
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


def test_canary_selection_requires_a_failed_part_repair_and_excludes_pending_orphans():
    bridge = _runner()
    failed = {"kind": "part", "article_id": "A", "part_index": 1, "base_status": "FAILED",
              "key": "failed-repair", "base_key": "failed", "runnable": True,
              "repair_status": "REPAIR_CANARY_ENQUEUED", "job": {"status": "PENDING"}}
    orphan = {"kind": "part", "article_id": "A", "part_index": 2, "base_status": "FAILED",
              "key": "orphan-recovery", "base_key": "orphan", "runnable": True,
              "orphan_recovery": {"status": "PENDING"}}
    pending = {"kind": "part", "article_id": "A", "part_index": 3, "base_status": "PENDING",
               "key": "pending", "base_key": "pending", "runnable": True}
    conflict = {"kind": "part", "article_id": "A", "part_index": 0, "base_status": "PENDING",
                "key": "conflict", "base_key": "conflict", "runnable": True,
                "base_failure_code": "HISTORICAL_SUCCESS_PROVENANCE_MISMATCH"}

    assert bridge._frozen_resume_canary([failed, orphan, pending, conflict]) is failed
    assert bridge._frozen_resume_canary([orphan, pending, conflict]) is None
    assert bridge._frozen_resume_canary([{**failed, "runnable": False,
                                          "job": {"status": "FAILED"}}]) is None


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
    _bind_resume_part_payload(payload, source_unit_map_sha256="e" * 64,
                              chunk_plan_sha256="7" * 64, part_sha256="8" * 64)
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
    saved_canary_payload = {**payload, "article_id": "EASTMONEY:VERIFIED_CANARY",
                            "rules": payload["rules"] + "+saved-validated-canary"}
    saved_canary_identity = queue._identity(saved_canary_payload)
    saved_canary_key = _sha(_json_bytes(saved_canary_identity))
    saved_canary_ref = f"jobs/{saved_canary_key}/input.json"
    saved_canary_raw = _json_bytes(saved_canary_payload)
    saved_canary_path = queue_root / saved_canary_ref
    saved_canary_path.parent.mkdir(parents=True, exist_ok=True)
    saved_canary_path.write_bytes(saved_canary_raw)
    jobs[saved_canary_key] = {
        "idempotency_key": saved_canary_key, "queue_id": "v4-manager-flash-incremental",
        "identity": saved_canary_identity, "payload_sha256": _sha(saved_canary_raw),
        "input_path": saved_canary_ref, "status": "SUCCEEDED", "attempt_count": 1,
        "max_attempts": 1, "model_id": payload["model_id"], "attempts": [],
    }
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
        resume_action="CONTINUE",
        saved_canary_key=saved_canary_key,
        count_prompt_tokens=lambda _messages: 1,
    )
    selected = bridge._frozen_resume_canary(records)
    assert selected is None
    orphan_record = records[0]
    assert orphan_record["orphan_recovery"]["status"] == "PENDING"
    assert allowed == {orphan_record["key"]}
    assert len(queue.enqueued) == 1
    result = queue.run_next(lambda _job: "", lambda *_args: None,
                            idempotency_keys=allowed, wait_for_model_slot=False)
    assert result["idempotency_key"] == orphan_record["key"]
    assert requests == [orphan_record["key"]]

    allowed_again, records_again = bridge._enqueue_long_body_parts(
        spec, queue, queue_root, allow_same_batch_pending=True, recovery_lock=None,
        membership_gate=None, resume_cutoff=None, prompt_token_cap=50000,
        hard_prompt_token_cap=100000, allow_new_repairs=False, allow_enqueue=True,
        resume_frozen_batch=True, source_job_id="a" * 32, source_input_sha256="2" * 64,
        resume_action="CONTINUE",
        saved_canary_key=saved_canary_key,
        count_prompt_tokens=lambda _messages: 1,
    )
    assert allowed_again == set()
    assert bridge._frozen_resume_canary(records_again) is None
    assert len(queue.enqueued) == 1
    assert requests == [orphan_record["key"]]


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
        _bind_resume_part_payload(current_payload, part_index=index, part_count=5,
                                  source_unit_map_sha256="e" * 64,
                                  chunk_plan_sha256="8" * 64,
                                  part_sha256=descriptor["part_sha256"])
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
    ("PENDING", 0, False),
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
    _bind_resume_part_payload(payload, part_index=1, part_count=2,
                              source_unit_map_sha256="e" * 64,
                              chunk_plan_sha256="f" * 64, part_sha256="9" * 64)
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
        resume_action="CANARY",
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


def test_runner_reproves_exact_legacy_fixed_field_failure_from_saved_source_artifacts(tmp_path):
    bridge = _runner()
    service, source_id = _resume_service(tmp_path)
    failed_key = _mark_legacy_failed_canary(service, source_id)
    state_root = tmp_path / "state"
    for ref, raw in service.store.io._files.items():
        destination = state_root / ref
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    refs = {
        "source_input_sha256": f"announcement_flash/jobs/{source_id}/input.json",
        "source_progress_sha256": f"announcement_flash/jobs/{source_id}/progress.json",
        "source_queue_state_sha256": "announcement_flash/queue/queue-state.json",
    }
    hashes = {name: _sha((state_root / ref).read_bytes()) for name, ref in refs.items()}
    before = {str(path): _sha(path.read_bytes()) for path in state_root.rglob("*") if path.is_file()}

    source_input, queue_value, verified = bridge._verify_resume_source(
        bridge.SafeRoot(state_root), Path(service.config.capture_root), source_id, "20261016", hashes)

    after = {str(path): _sha(path.read_bytes()) for path in state_root.rglob("*") if path.is_file()}
    assert after == before
    assert source_input["job_id"] == source_id
    assert failed_key in queue_value["jobs"]
    assert verified["key"] == failed_key
    assert verified["source_job_id"] == source_id
    assert verified["root_job_id"] == "b" * 32
    assert verified["part_descriptor"]["part_index"] >= 25


def test_runner_reproves_precontract_orphan_canary_without_writing_queue_or_state(tmp_path):
    bridge = _runner()
    service, source_id = _resume_service(tmp_path, source_publication_date="2026-10-14")
    canary_key, source_part_key, root_id = _mark_precontract_orphan_failed_canary(service, source_id)
    state_root = tmp_path / "state"
    for ref, raw in service.store.io._files.items():
        destination = state_root / ref
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    refs = {
        "source_input_sha256": f"announcement_flash/jobs/{source_id}/input.json",
        "source_progress_sha256": f"announcement_flash/jobs/{source_id}/progress.json",
        "source_queue_state_sha256": "announcement_flash/queue/queue-state.json",
    }
    hashes = {name: _sha((state_root / ref).read_bytes()) for name, ref in refs.items()}
    before = {str(path): _sha(path.read_bytes()) for path in state_root.rglob("*") if path.is_file()}

    source_input, queue_value, verified = bridge._verify_resume_source(
        bridge.SafeRoot(state_root), Path(service.config.capture_root), source_id, "20261016", hashes)

    after = {str(path): _sha(path.read_bytes()) for path in state_root.rglob("*") if path.is_file()}
    assert after == before
    assert source_input["job_id"] == source_id
    assert canary_key in queue_value["jobs"]
    assert verified["key"] == canary_key
    assert verified["root_job_id"] == root_id
    assert verified["source_part_key"] == source_part_key
    assert verified["part_descriptor"]["part_index"] == 45


def _saved_transport_service_case(tmp_path, monkeypatch):
    # Reuse the ordinary wire-shape fixture across both entry points.
    spec = importlib.util.spec_from_file_location(
        "saved_transport_runner_fixture", Path(__file__).with_name("test_manager_announcement_flash_runner.py"))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    values = fixture._saved_transport_readback_case(tmp_path, monkeypatch)
    bridge, child, result, plan, queue, state_root, capture_root = values
    monkeypatch.setitem(__import__("sys").modules, "ops.run_manager_flash_announcements", bridge)
    service = SimpleNamespace(config=SimpleNamespace(capture_root=capture_root),
                              store=SimpleNamespace(io=bridge.SafeRoot(state_root)))
    return AnnouncementUpdate(service), values


@pytest.mark.parametrize("saved_flag", [False, True])
def test_saved_transport_service_and_runner_derive_same_readonly_continue_receipt(tmp_path, monkeypatch, saved_flag):
    update, (bridge, child, result, plan, queue, state_root, capture_root) = \
        _saved_transport_service_case(tmp_path, monkeypatch)
    if saved_flag:
        job = queue.jobs[result["resume"]["canary_key"]]
        receipt = bridge._validated_transport_canary_result(
            queue.root, job, bridge._queue_payload(queue.root, job), plan)
        result["resume"].update(canary_passed=True, continue_eligible=True, canary_validation=receipt)
    before = {str(path): path.read_bytes() for path in state_root.rglob("*") if path.is_file()}
    original_result = bridge.canonical(result)
    derived = update._completed_transport_canary(child["job_id"], "20261016", child, result,
                                                 {"jobs": queue.jobs}, {}, state_root, plan)
    bridge._verify_saved_transport_canary(bridge.SafeRoot(state_root), capture_root, child["job_id"],
                                          "20261016", child, result, {"jobs": queue.jobs}, plan)
    assert derived["mode"] == "CONTINUE_AFTER_CANARY"
    assert derived["canary_passed"] is True
    assert derived["canary_validation"]["status"] == "PASS"
    assert result["resume"]["canary_passed"] is saved_flag
    assert bridge.canonical(result) == original_result
    assert {str(path): path.read_bytes() for path in state_root.rglob("*") if path.is_file()} == before
    assert queue.dispatched == [result["resume"]["canary_key"]]


@pytest.mark.parametrize("mutation", ["raw", "missing_sha", "wrong_article", "semantic", "multicall", "failure"])
def test_saved_transport_service_rejects_invalid_or_nonexact_failure(tmp_path, monkeypatch, mutation):
    update, (bridge, child, result, plan, queue, state_root, _capture_root) = \
        _saved_transport_service_case(tmp_path, monkeypatch)
    key = result["resume"]["canary_key"]
    job = queue.jobs[key]
    if mutation == "raw":
        (queue.root / job["raw_path"]).write_bytes(b"{}")
    elif mutation == "missing_sha":
        del job["raw_sha256"]
    elif mutation == "wrong_article":
        path = queue.root / job["validated_path"]
        value = json.loads(path.read_bytes())
        value["results"][0]["article_id"] = "EASTMONEY:OTHER"
        path.write_bytes(bridge.canonical(value))
        job["validated_sha256"] = job["attempts"][0]["validated_sha256"] = bridge.sha(path.read_bytes())
    elif mutation == "semantic":
        def reject(_job, _parsed):
            raise ValueError("SEMANTIC_REJECTED")
        monkeypatch.setattr(bridge, "_validator", lambda *_args: reject)
    elif mutation == "multicall":
        result["resume"]["model_calls"] = 2
    elif mutation == "failure":
        result["resume"]["canary_validation"]["failure_code"] = "SEMANTIC_REJECTED"
    with pytest.raises(JobConflict):
        update._completed_transport_canary(child["job_id"], "20261016", child, result,
                                           {"jobs": queue.jobs}, {}, state_root, plan)
    assert queue.dispatched == [key]


@pytest.mark.parametrize("verified", [True, False])
def test_memory_transition_service_requires_exact_authorization_before_resume_submission(tmp_path, monkeypatch, verified):
    bridge = _runner()
    source_id = bridge.MEMORY_IDENTITY_TRANSITION["source_job_id"]
    service, _source_id = _resume_service(tmp_path, source_job_id=source_id)
    _mark_transport_system_stop(service, source_id)
    calls = []

    def verify(state_root, plan):
        calls.append((state_root, plan))
        if not verified:
            raise bridge.FlashRunError("AUTHORIZED_MEMORY_TRANSITION_UNVERIFIED")
        return {"runtime_memory_transition": {"receipt_sha256": "a" * 64}}

    monkeypatch.setattr(bridge, "_current_transport_request_material", verify)
    monkeypatch.setitem(__import__("sys").modules, "ops.run_manager_flash_announcements", bridge)
    update = AnnouncementUpdate(service)
    snapshot = update.resume_snapshot("20261016")
    assert calls and calls[0][0] == service.store.root
    assert calls[0][1]["source_job_id"] == source_id
    assert snapshot["eligible"] is verified
    if not verified:
        assert snapshot["reason"] == "RESUME_AUTHORIZED_MEMORY_TRANSITION_UNVERIFIED"
    assert service.jobs.submissions == []
