from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

BRIDGE_PATH = Path(__file__).resolve().parents[1] / "ops/run_manager_flash_announcements.py"


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class _AdmissionQueue:
    IDENTITY_FIELDS = ("date", "market", "article_id", "source_sha256", "body_sha256", "prompt_sha256",
                       "model_id", "configuration_sha256", "rules", "role", "stage")

    def __init__(self, jobs=None):
        self.jobs = dict(jobs or {})
        self.enqueued = []

    def _identity(self, payload):
        return {key: payload[key] for key in self.IDENTITY_FIELDS}

    def _load_state(self):
        return {"jobs": self.jobs}

    def enqueue(self, payload):
        identity = self._identity(payload)
        key = _sha(_json_bytes(identity))
        item = {"idempotency_key": key, "identity": identity, "status": "PENDING", "attempt_count": 0,
                "max_attempts": 1}
        self.jobs[key] = item
        self.enqueued.append(payload)
        return item


class _PersistingAdmissionQueue(_AdmissionQueue):
    """In-memory queue state with temp-only payload persistence for version-binding tests."""

    def __init__(self, root, jobs=None):
        super().__init__(jobs)
        self.root = Path(root)

    def enqueue(self, payload):
        identity = self._identity(payload)
        key = _sha(_json_bytes(identity))
        raw = _json_bytes(payload)
        payload_sha256 = _sha(raw)
        if key in self.jobs:
            prior = self.jobs[key]
            if prior.get("payload_sha256") != payload_sha256:
                raise ValueError("IDEMPOTENCY_CONFLICT")
            return prior
        input_path = self.root / "jobs" / key / "input.json"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_bytes(raw)
        item = {"idempotency_key": key, "queue_id": "v4-manager-flash-incremental",
                "identity": identity, "payload_sha256": payload_sha256,
                "input_path": f"jobs/{key}/input.json", "status": "PENDING",
                "attempt_count": 0, "max_attempts": 1, "attempts": [], "queue_policy": {}}
        self.jobs[key] = item
        self.enqueued.append(payload)
        return item


def _recovery_version_fixture(tmp_path):
    body = "冻结的完整公告正文"
    body_sha = _sha(body.encode())
    article_id = "EASTMONEY:AN202610150099"
    cutoff = "2026-10-16T14:57:00+08:00"
    authority = "a" * 64
    capture_sha = "b" * 64
    source_code = "HK.09963"
    identity = {"date": "2026-10-15", "market": "HK", "article_id": article_id,
                "source_sha256": "1" * 64, "body_sha256": body_sha, "prompt_sha256": "3" * 64,
                "model_id": "qwen3_8_flash_next", "configuration_sha256": "4" * 64,
                "rules": "recent_day_reader_v2+profile:p+citation:c+unit-map:u+fixed-ledger:l",
                "role": "announcement_reader", "stage": "v4_manager_announcement_flash_incremental"}
    source_codes = [{"code": source_code, "name": "测试公司"}]
    old_meta = {"publication_date": "2026-10-15", "title": "同一公告", "symbol": source_code,
                "available_at": "2026-10-15T18:31:00+08:00", "article_membership_status": "CANNOT_CONFIRM",
                "membership_authority_sha256": None, "source_issuer_codes": source_codes,
                "source_issuer_membership": []}
    old_payload = {**identity, "article_body": body, "article_metadata": old_meta,
                   "fixed_fact_ledger": {"ledger_sha256": "5" * 64}, "messages": [{"role": "user", "content": "old"}],
                   "structured_output_schema": {"type": "object"}, "source_unit_map_sha256": "6" * 64,
                   "workflow_profile": "decision_simple_facts_unit_ranges_v2", "citation_protocol": "protocol-v2"}
    new_source = "7" * 64
    current_meta = {**old_meta, "available_at": "2026-10-15T18:32:00+08:00",
                    "article_membership_status": "IN", "membership_authority_sha256": authority,
                    "source_issuer_membership": [{"code": source_code, "membership_status": "IN",
                                                  "market": "HK_CONNECT", "authority_sha256": authority}],
                    "source_origins": [
                        {"role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_product_sha256": capture_sha},
                        {"role": "VERIFIED_FULL_NOTICE_BODY_PRODUCT", "source_product_sha256": new_source},
                    ]}
    current_payload = {**old_payload, "source_sha256": new_source,
                       "article_metadata": current_meta,
                       "messages": [{"role": "user", "content": "current verified metadata"}]}
    lock = {"schema": "v4.manager_workbench.announcement_flash_recovery_lock.v1",
            "target_date": "20261016", "cutoff": cutoff,
            "root_batch_job_id": "c" * 32, "parent_job_id": "d" * 32,
            "parent_input_sha256": "e" * 64, "parent_result_sha256": "f" * 64,
            "row_manifest_sha256": "8" * 64, "eligible_article_ids_sha256": "9" * 64,
            "capture_product_sha256": capture_sha, "membership_authority_sha256": authority,
            "eligible_article_ids": [article_id], "eligible_count": 1,
            "current_body_sha256": {article_id: body_sha}, "expected_body_sha256": {article_id: body_sha}}
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1", "status": "VERIFIED",
            "target_date": "20261016", "cutoff": cutoff, "market": "HK_CONNECT",
            "authority_sha256": authority, "codes": [source_code]}
    queue_root = tmp_path / "queue"
    queue = _PersistingAdmissionQueue(queue_root)
    old_key = _sha(_json_bytes(queue._identity(old_payload)))
    old_raw = _json_bytes(old_payload)
    old_input = queue_root / "jobs" / old_key / "input.json"
    old_input.parent.mkdir(parents=True, exist_ok=True)
    old_input.write_bytes(old_raw)
    old_job = {"idempotency_key": old_key, "queue_id": "v4-manager-flash-incremental",
               "identity": queue._identity(old_payload), "payload_sha256": _sha(old_raw),
               "input_path": f"jobs/{old_key}/input.json", "status": "PENDING",
               "attempt_count": 0, "max_attempts": 1, "attempts": [], "queue_policy": {}}
    queue.jobs[old_key] = old_job
    old_job_before = json.loads(json.dumps(old_job))
    return queue, queue_root, old_key, old_job_before, current_payload, lock, gate, cutoff


def _identity_payload(identity):
    return {**identity, "article_body": "正文不可外传", "article_metadata": {"symbol": "HK.09963", "title": "测试公告"},
            "fixed_fact_ledger": {}}


def _bridge_module():
    spec = importlib.util.spec_from_file_location("manager_flash_runner_test_module", BRIDGE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_context_exceed_stays_pending_without_truncation_or_model_call(tmp_path, monkeypatch):
    bridge = _bridge_module()
    pipeline_root = bridge.PIPELINE_ROOT
    assert pipeline_root.is_dir()
    monkeypatch.syspath_prepend(str(pipeline_root))
    batch_runner = importlib.import_module("batch_runner")
    length_canary = importlib.import_module("build_length_canary")
    canary_module = importlib.import_module("automatic_canary_server")

    class Queue:
        def __init__(self, *_args, **_kwargs):
            pass

        def _load_state(self):
            return {"jobs": {}}

        def enqueue(self, _payload):
            raise AssertionError("context-exceed input must remain outside the model queue")

        def snapshot(self):
            return {"items": []}

    queue_module = ModuleType("announcement_queue")
    queue_module.SerialAnnouncementQueue = Queue
    def model_call_forbidden(*_args, **_kwargs):
        raise AssertionError("context-exceed input must not call the model transport")
    monkeypatch.setattr(canary_module, "GatedStreamingTransport", model_call_forbidden)
    monkeypatch.setitem(sys.modules, "announcement_queue", queue_module)
    monkeypatch.setitem(sys.modules, "automatic_canary_server", canary_module)
    monkeypatch.setitem(sys.modules, "batch_runner", batch_runner)
    monkeypatch.setitem(sys.modules, "build_length_canary", length_canary)

    tokenizer = SimpleNamespace(apply_chat_template=lambda *_args, **_kwargs: [1, 2, 3])
    transformers = ModuleType("transformers")
    transformers.AutoTokenizer = SimpleNamespace(from_pretrained=lambda *_args, **_kwargs: tokenizer)
    monkeypatch.setitem(sys.modules, "transformers", transformers)

    helper = bridge._load_helper()
    original_material = helper._full_day_request_material
    def material_with_small_context(contract):
        value = original_material(contract)
        value["runtime_limits"] = {**value["runtime_limits"], "context_limit_tokens": 1}
        return value
    monkeypatch.setattr(helper, "_full_day_request_material", material_with_small_context)
    monkeypatch.setattr(bridge, "_load_helper", lambda: helper)

    capture_root = tmp_path / "capture"
    capture_root.mkdir()
    body = "公告正文：公司披露一项新业务安排，具体影响仍需人工核实。"
    body_sha = _sha(body.encode())
    body_product = {"body_text": body, "body_text_sha256": body_sha, "body_complete": True}
    body_raw = _json_bytes(body_product)
    body_product_sha = _sha(body_raw)
    body_ref = f"products/{body_product_sha}.json"
    (capture_root / body_ref).parent.mkdir(parents=True)
    (capture_root / body_ref).write_bytes(body_raw)

    raw_row = {"art_code": "AN202610150001", "title": "测试公告", "notice_date": "2026-10-15",
               "display_time": "2026-10-15 10:00:00", "codes": [{"stock_code": "09963", "market_code": "116",
               "ann_type": "H", "short_name": "测试公司"}]}
    listing_raw = _json_bytes({"data": {"list": [raw_row]}})
    listing_sha = _sha(listing_raw)
    listing_ref = f"objects/{listing_sha}.bin"
    (capture_root / listing_ref).parent.mkdir(parents=True)
    (capture_root / listing_ref).write_bytes(listing_raw)
    row = {
        "art_code": raw_row["art_code"], "title": raw_row["title"], "publication_date": "2026-10-15",
        "display_time": "2026-10-15T10:00:00+08:00", "available_at": "2026-10-15T10:00:01+08:00",
        "source_issuer_codes": [{"code": "HK.09963", "source_stock_code": "09963", "market_code": "116",
                                 "ann_type": "H", "name": "测试公司"}],
        "raw_row": raw_row,
        "listing_source_ref": {"artifact_ref": listing_ref, "sha256": listing_sha},
        "body_text": body, "body_text_sha256": body_sha, "body_complete": True,
        "body_artifact_ref": body_ref, "source_sha256": body_product_sha,
    }
    capture_product = {"schema_version": "mwb.capture.window.v1",
                       "owner": "v4.manager_workbench.capture_announcements", "source": "EASTMONEY_HK",
                       "window": {"publication_dates": ["2026-10-15"]}, "rows": [row]}
    capture_raw = _json_bytes(capture_product)
    capture_sha = _sha(capture_raw)
    capture_ref = f"products/{capture_sha}.json"
    (capture_root / capture_ref).parent.mkdir(parents=True, exist_ok=True)
    (capture_root / capture_ref).write_bytes(capture_raw)

    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1", "status": "VERIFIED",
            "target_date": "20261016", "cutoff": "2026-10-16T13:02:00+08:00", "market": "HK_CONNECT",
            "owner": "v35_dispatcher.research_panel_daily_hk", "authority_sha256": "a" * 64,
            "authority_version": "v1", "effective_from": "20261001", "effective_to": "20261031",
            "available_at": "2026-10-12T19:58:59.501065+08:00", "member_count": 1,
            "members_sha256": "b" * 64, "codes": ["HK.09963"]}
    from v4.manager_workbench import announcement_membership
    monkeypatch.setattr(announcement_membership, "revalidate_membership_gate", lambda *_args: dict(gate))

    progress = []
    result = bridge._run(
        {"target_date": "20261016", "cutoff": gate["cutoff"], "membership_gate": gate,
         "capture_product": {"artifact_ref": capture_ref, "sha256": capture_sha}},
        state_root=tmp_path / "state", capture_root=capture_root,
        job_id="a" * 32, progress=progress.append, shared_root=tmp_path / "shared",
    )

    assert result["state"] == "PARTIAL"
    assert result["counts"]["capture_rows"] == 1
    assert result["counts"]["context_pending"] == 1
    assert result["counts"]["queue"].get("succeeded", 0) == 0
    assert result["pending"][0]["queue_reason"] == "INPUT_EXCEEDS_CONTEXT"
    assert result["pending"][0]["prompt_tokens"] == 3
    assert result["pending"][0]["context_limit_tokens"] == 1
    assert "article_body" not in result["pending"][0]
    assert progress


def test_clean_cli_loads_pipeline_imports_before_validating_capture(tmp_path):
    runtime_python = Path(
        "/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python"
    )
    release_app = Path(
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-workbench-api-20261016-r4/app"
    )
    assert runtime_python.is_file()
    assert release_app.is_dir()

    job_id = "e" * 32
    state_root = tmp_path / "state"
    job_root = state_root / "announcement_flash" / "jobs" / job_id
    job_root.mkdir(parents=True)
    capture_product = {
        "schema_version": "mwb.capture.window.v1",
        "owner": "v4.manager_workbench.capture_announcements",
        "source": "EASTMONEY_HK",
        "saved_ref": None,
        "window": {"publication_dates": ["2026-10-16"]},
        "rows": [{"art_code": "AN202610160000", "window_consumption_status": "EXCLUDED_OUTSIDE_WINDOW"}],
    }
    capture_raw = _json_bytes(capture_product)
    capture_sha = _sha(capture_raw)
    capture_ref = f"products/{capture_sha}.json"
    capture_path = tmp_path / "capture" / capture_ref
    capture_path.parent.mkdir(parents=True)
    capture_path.write_bytes(capture_raw)
    input_value = {
        "schema": "v4.manager_workbench.announcement_flash_input.v1",
        "job_id": job_id,
        "target_date": "20261016",
        "capture_product": {"artifact_ref": capture_ref, "sha256": capture_sha},
    }
    (job_root / "input.json").write_bytes(_json_bytes(input_value))
    capture_root = tmp_path / "capture"
    environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    assert "PYTHONPATH" not in environment

    process = subprocess.run(
        [str(runtime_python), "-B", str(BRIDGE_PATH), "--state-root", str(state_root),
         "--capture-root", str(capture_root), "--job-id", job_id],
        cwd=release_app,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    progress = json.loads((job_root / "progress.json").read_text())
    result = json.loads((job_root / "result.json").read_text())
    assert process.returncode == 0, process.stderr
    assert progress["step"] == "DONE"
    assert result["counts"]["excluded_outside_window"] == 1
    assert result["membership_gate"]["status"] == "CANNOT_CONFIRM"
    assert result["counts"]["queue"]["new_model_calls_allowed"] == 0
    assert result["counts"]["queue"].get("new_enqueued", 0) == 0


def test_fixed_candidate_history_verifies_and_exposes_all_original_statuses():
    bridge = _bridge_module()
    history = bridge._pinned_candidate_history()

    counts = {}
    for item in history:
        counts[(item["source"], item["status"])] = counts.get((item["source"], item["status"]), 0) + 1
    assert counts == {
        ("PINNED_CANDIDATE", "SUCCEEDED"): 367,
        ("PINNED_CANDIDATE", "FAILED"): 18,
        ("PINNED_CANDIDATE", "PENDING"): 5,
        ("PRIOR_REVIEWED_RESULT", "SUCCEEDED"): 1,
    }
    assert all(item["candidate_manifest_sha256"] == "15de0845513f21cdadd98162a7720d8963bde3290b2839765d1794dce11bd121"
               for item in history if item["source"] == "PINNED_CANDIDATE")


def test_same_article_body_new_capture_source_reuses_prior_result_without_model_call():
    bridge = _bridge_module()
    historical = {"date": "2026-10-16", "market": "HK", "article_id": "EASTMONEY:AN202610160001",
                  "source_sha256": "1" * 64, "body_sha256": "2" * 64, "prompt_sha256": "3" * 64,
                  "model_id": "qwen3_8_flash_next", "configuration_sha256": "4" * 64,
                  "rules": "recent_day_reader_v2+profile:p+citation:c+unit-map:u+fixed-ledger:l",
                  "role": "announcement_reader", "stage": "v4_manager_announcement_flash_incremental"}
    first_capture = _identity_payload(historical)
    first_capture["article_metadata"].update({"available_at": "2026-10-16T10:00:01+08:00",
                                              "source_origins": [{"source_ref": "objects/old.bin",
                                                                  "source_product_sha256": "6" * 64}]})
    old_key = _sha(_json_bytes(_AdmissionQueue()._identity(first_capture)))
    old_job = {"idempotency_key": old_key, "identity": _AdmissionQueue()._identity(first_capture),
               "status": "SUCCEEDED", "attempt_count": 1, "max_attempts": 1}
    second_identity = {**historical, "source_sha256": "5" * 64,
                       "stage": "v4_manager_announcement_flash_incremental"}
    second_capture = _identity_payload(second_identity)
    second_capture["article_metadata"].update({"available_at": "2026-10-16T10:05:01+08:00",
                                               "source_origins": [{"source_ref": "objects/new.bin",
                                                                   "source_product_sha256": "7" * 64}]})
    old_article = {"article_id": historical["article_id"], "source_sha256": historical["source_sha256"],
                   "body_sha256": historical["body_sha256"], "article_body": "正文不可外传",
                   "article_metadata": first_capture["article_metadata"], "fixed_fact_ledger": {}}
    old_output = {"article_id": historical["article_id"], "source_sha256": historical["source_sha256"],
                  "body_sha256": historical["body_sha256"], "disposition": "SELECTED_EVENT",
                  "direction": "POSITIVE", "reason": "原队列已完成的模型理由。", "impact": []}
    old_record = {"source": "INCREMENTAL_QUEUE", "status": "SUCCEEDED", "identity": old_job["identity"],
                  "job": old_job, "article": old_article, "output": old_output}
    queue = _AdmissionQueue()

    plan = bridge._admit_incremental_payloads([second_capture], queue, [old_record], Path("/tmp/unused-queue"))
    model_calls = 0
    if plan["allowed_keys"]:
        model_calls += 1

    assert bridge._stable_queue_identity(queue, first_capture) != bridge._stable_queue_identity(queue, second_capture)
    assert bridge._semantic_identity(queue._identity(first_capture)) == bridge._semantic_identity(queue._identity(second_capture))
    assert plan["allowed_keys"] == set()
    assert plan["matched"][0]["record"]["source"] == "INCREMENTAL_QUEUE"
    assert plan["matched"][0]["record"]["status"] == "SUCCEEDED"
    assert queue.enqueued == []
    assert model_calls == 0
    reused_article, reused_output = bridge._history_payload_and_output(plan["matched"][0]["record"])
    current_binding = bridge._current_capture_binding(second_capture, "8" * 64)
    assert reused_article["source_sha256"] == "1" * 64
    assert reused_article["article_metadata"]["source_origins"][0]["source_ref"] == "objects/old.bin"
    assert reused_output["reason"] == "原队列已完成的模型理由。"
    assert current_binding["source_sha256"] == "5" * 64
    assert current_binding["source_origins"][0]["source_ref"] == "objects/new.bin"


def test_pinned_success_and_failed_pending_states_are_skipped_not_reenqueued():
    bridge = _bridge_module()
    history = bridge._pinned_candidate_history()
    for target_status in ("SUCCEEDED", "FAILED", "PENDING"):
        old = next(item for item in history if item["source"] == "PINNED_CANDIDATE" and item["status"] == target_status)
        changed_source = {**old["identity"], "source_sha256": "f" * 64}
        queue = _AdmissionQueue()

        plan = bridge._admit_incremental_payloads([_identity_payload(changed_source)], queue, history, Path("/tmp/unused-queue"))

        assert plan["allowed_keys"] == set()
        assert queue.enqueued == []
        assert plan["matched"][0]["record"]["source"] == "PINNED_CANDIDATE"
        assert plan["matched"][0]["record"]["status"] == target_status
        if target_status == "SUCCEEDED":
            current_payload = plan["matched"][0]["current_payload"]
            current_payload["article_metadata"] = {"symbol": "HK.09963", "title": "本次采集标题",
                                                     "source_origins": [{"source_ref": "objects/current.bin",
                                                                         "source_product_sha256": "e" * 64}]}
            current = bridge._current_capture_binding(current_payload, "d" * 64)
            original = plan["matched"][0]["record"]["article"]
            assert original["source_sha256"] != current["source_sha256"]
            assert original["article_metadata"]["source_origins"] != current["source_origins"]


def test_historical_success_failure_and_pending_remain_queryable_with_separate_sources():
    bridge = _bridge_module()
    history = bridge._pinned_candidate_history()
    selected = next(item for item in history if item["source"] == "PINNED_CANDIDATE"
                    and item["status"] == "SUCCEEDED"
                    and item["output"].get("disposition") in {"SELECTED_EVENT", "SELECTED_PERFORMANCE"}
                    and item["output"].get("direction") == "POSITIVE")
    failed = next(item for item in history if item["source"] == "PINNED_CANDIDATE" and item["status"] == "FAILED")
    pending = next(item for item in history if item["source"] == "PINNED_CANDIDATE" and item["status"] == "PENDING")

    matches = []
    for item in (selected, failed, pending):
        identity = {**item["identity"], "source_sha256": "f" * 64}
        current = _identity_payload(identity)
        current["article_metadata"].update({"source_origins": [{"source_ref": "objects/current.bin",
                                                                "source_product_sha256": "e" * 64}]})
        matches.append({"record": item, "current_payload": current, "rules_match": True})

    projected = bridge._project_historical_matches(matches, "d" * 64)

    assert len(projected["selected"]) == 1
    selected_article = projected["selected"][0]
    selected_id = selected["identity"]["article_id"]
    assert selected_article["source_sha256"] == selected["identity"]["source_sha256"]
    assert selected_article["source_origins"] == [
        {key: origin.get(key) for key in ("role", "source_ref", "source_product_sha256", "row_fingerprint_sha256")}
        for origin in selected["article"]["article_metadata"]["source_origins"]
    ]
    assert projected["current_capture_bindings"][selected_id]["source_sha256"] == "f" * 64
    assert projected["current_capture_bindings"][selected_id]["capture_product_sha256"] == "d" * 64
    assert projected["failures"][0]["prior_status"] == "FAILED"
    assert projected["failures"][0]["skip_reason"] == "PRIOR_FAILED_RESULT_NOT_RETRIED"
    assert projected["pending"][0]["queue_status"] == "PENDING"
    assert projected["pending"][0]["queue_reason"] == "PRIOR_QUEUE_PENDING_NOT_RETRIED"
    assert {item["status"] for item in projected["outcomes"]} == {"SUCCEEDED", "FAILED", "PENDING"}


def test_old_pending_attempt_zero_is_not_allowed_even_when_source_sha_changes():
    bridge = _bridge_module()
    identity = {"date": "2026-10-16", "market": "HK", "article_id": "EASTMONEY:AN202610160002",
                "source_sha256": "1" * 64, "body_sha256": "2" * 64, "prompt_sha256": "3" * 64,
                "model_id": "qwen3_8_flash_next", "configuration_sha256": "4" * 64,
                "rules": "recent_day_reader_v2+profile:p+citation:c+unit-map:u+fixed-ledger:l",
                "role": "announcement_reader", "stage": "v4_manager_announcement_flash_incremental"}
    old_payload = _identity_payload(identity)
    key = _sha(_json_bytes(_AdmissionQueue()._identity(old_payload)))
    job = {"idempotency_key": key, "identity": _AdmissionQueue()._identity(old_payload),
           "status": "PENDING", "attempt_count": 0, "max_attempts": 1}
    new_payload = _identity_payload({**identity, "source_sha256": "5" * 64})
    queue = _AdmissionQueue({key: job})

    plan = bridge._admit_incremental_payloads([new_payload], queue, [], Path("/tmp/unused-queue"))

    assert plan["allowed_keys"] == set()
    assert plan["matched"][0]["record"]["status"] == "PENDING"
    assert job["attempt_count"] == 0
    assert queue.enqueued == []


def test_frozen_recovery_versions_verified_current_pending_without_mutating_old_queue_item(tmp_path):
    bridge = _bridge_module()
    queue, queue_root, old_key, old_job_before, current, lock, gate, cutoff = _recovery_version_fixture(tmp_path)
    old_input_before = _sha((queue_root / queue.jobs[old_key]["input_path"]).read_bytes())

    plan = bridge._admit_incremental_payloads(
        [current], queue, [], queue_root, resume_same_batch_pending=True,
        resume_cutoff=cutoff, recovery_lock=lock, membership_gate=gate,
    )

    new_key = next(iter(plan["allowed_keys"]))
    assert new_key != old_key
    assert plan["new_enqueued"] == 1
    assert plan["resumed_pending"] == 0
    assert plan["articles_by_key"][new_key]["source_sha256"] == current["source_sha256"]
    assert queue.jobs[old_key] == old_job_before
    assert _sha((queue_root / queue.jobs[old_key]["input_path"]).read_bytes()) == old_input_before
    new_item = queue.jobs[new_key]
    new_payload = json.loads((queue_root / new_item["input_path"]).read_text())
    binding = new_payload["recovery_version_binding"]
    assert binding["old_idempotency_key"] == old_key
    assert binding["old_payload_sha256"] == old_job_before["payload_sha256"]
    assert binding["new_idempotency_key"] == new_key
    assert binding["new_source_sha256"] == current["source_sha256"]
    assert binding["membership_authority_sha256"] == gate["authority_sha256"]
    assert plan["version_associations"][0]["new_payload_sha256"] == new_item["payload_sha256"]

    repeated = bridge._admit_incremental_payloads(
        [current], queue, [], queue_root, resume_same_batch_pending=True,
        resume_cutoff=cutoff, recovery_lock=lock, membership_gate=gate,
    )
    assert repeated["allowed_keys"] == {new_key}
    assert repeated["new_enqueued"] == 0
    assert repeated["resumed_pending"] == 1
    assert len(queue.enqueued) == 1
    assert queue.jobs[old_key] == old_job_before


def test_frozen_recovery_version_rejects_changed_body_authority_membership_and_cutoff(tmp_path):
    bridge = _bridge_module()
    for mutation in ("body", "authority", "membership", "cutoff"):
        case_root = tmp_path / mutation
        queue, queue_root, old_key, old_job_before, current, lock, gate, cutoff = _recovery_version_fixture(case_root)
        if mutation == "body":
            current["article_body"] += "被篡改"
        elif mutation == "authority":
            current["article_metadata"]["membership_authority_sha256"] = "c" * 64
        elif mutation == "membership":
            current["article_metadata"]["article_membership_status"] = "OUT"
        else:
            current["article_metadata"]["available_at"] = "2026-10-16T14:58:00+08:00"

        plan = bridge._admit_incremental_payloads(
            [current], queue, [], queue_root, resume_same_batch_pending=True,
            resume_cutoff=cutoff, recovery_lock=lock, membership_gate=gate,
        )

        assert plan["allowed_keys"] == set()
        assert plan["new_enqueued"] == 0
        assert plan["conflicts"][0]["failure_code"] == "RECOVERY_CURRENT_VERSION_BINDING_INVALID"
        assert queue.jobs[old_key] == old_job_before
        assert queue.enqueued == []


def test_successful_current_version_is_reused_without_reenqueue(tmp_path):
    bridge = _bridge_module()
    queue, queue_root, old_key, _old_job_before, current, lock, gate, cutoff = _recovery_version_fixture(tmp_path)
    first = bridge._admit_incremental_payloads(
        [current], queue, [], queue_root, resume_same_batch_pending=True,
        resume_cutoff=cutoff, recovery_lock=lock, membership_gate=gate,
    )
    new_key = next(iter(first["allowed_keys"]))
    queue.jobs[new_key]["status"] = "SUCCEEDED"
    queue.jobs[new_key]["attempt_count"] = 1
    raw_value = {"raw": "saved model response"}
    saved_value = {"result": "validated"}
    raw_path = queue_root / "jobs" / new_key / "attempt-0001.raw"
    validated_path = queue_root / "jobs" / new_key / "attempt-0001.validated.json"
    raw_path.write_bytes(_json_bytes(raw_value))
    validated_path.write_bytes(_json_bytes(saved_value))
    queue.jobs[new_key].update({"raw_path": f"jobs/{new_key}/attempt-0001.raw",
                                "raw_sha256": _sha(_json_bytes(raw_value)),
                                "validated_path": f"jobs/{new_key}/attempt-0001.validated.json",
                                "validated_sha256": _sha(_json_bytes(saved_value))})

    def validator(job, parsed):
        assert job.payload == current
        assert parsed == raw_value
        return saved_value

    repeated = bridge._admit_incremental_payloads(
        [current], queue, [], queue_root, resume_same_batch_pending=True,
        resume_cutoff=cutoff, recovery_lock=lock, membership_gate=gate, validator=validator,
    )

    assert repeated["allowed_keys"] == set()
    assert repeated["matched"][0]["record"]["idempotency_key"] == new_key
    assert repeated["matched"][0]["record"]["status"] == "SUCCEEDED"
    assert repeated["version_associations"][0]["disposition"] == "CURRENT_VERSION_SUCCEEDED_REUSED"
    assert len(queue.enqueued) == 1
    raw_path.write_bytes(b'{"raw":"tampered"}')
    tampered = bridge._admit_incremental_payloads(
        [current], queue, [], queue_root, resume_same_batch_pending=True,
        resume_cutoff=cutoff, recovery_lock=lock, membership_gate=gate, validator=validator,
    )
    assert tampered["allowed_keys"] == set()
    assert tampered["conflicts"][0]["failure_code"] == "RECOVERY_VERSION_BINDING_INVALID"
    assert len(queue.enqueued) == 1


def test_failed_current_version_is_preserved_and_never_resumed(tmp_path):
    bridge = _bridge_module()
    queue, queue_root, old_key, old_job_before, current, lock, gate, cutoff = _recovery_version_fixture(tmp_path)
    first = bridge._admit_incremental_payloads(
        [current], queue, [], queue_root, resume_same_batch_pending=True,
        resume_cutoff=cutoff, recovery_lock=lock, membership_gate=gate,
    )
    new_key = next(iter(first["allowed_keys"]))
    queue.jobs[new_key].update({"status": "FAILED", "attempt_count": 1,
                                "attempts": [{"number": 1,
                                              "error": {"stage": "validator", "code": "SAVED_VALIDATION_FAILURE"}}]})

    repeated = bridge._admit_incremental_payloads(
        [current], queue, [], queue_root, resume_same_batch_pending=True,
        resume_cutoff=cutoff, recovery_lock=lock, membership_gate=gate,
    )

    assert repeated["allowed_keys"] == set()
    assert repeated["matched"][0]["record"]["status"] == "FAILED"
    assert repeated["version_associations"][0]["disposition"] == "CURRENT_VERSION_FAILED_REUSED"
    assert queue.jobs[new_key]["attempt_count"] == 1
    assert queue.jobs[old_key] == old_job_before
    assert len(queue.enqueued) == 1


def _version_provenance_payload(bridge, *, capture_sha, source_sha="d" * 64, body_sha="c" * 64,
                                article_body="冻结的完整公告正文", row_index=7):
    article_id = "EASTMONEY:AN202610150099"
    body_product_sha = source_sha
    source_origins = [
        {"role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_product_sha256": capture_sha,
         "source_ref": f"products/{capture_sha}.json#/rows/{row_index}",
         "source_row_index": row_index, "row_fingerprint_sha256": "1" * 64},
        {"role": "FULL_DATE_DIRECTORY_PAGE", "source_product_sha256": "2" * 64,
         "source_ref": "objects/" + "2" * 64 + ".bin#data/list/4", "source_row_index": 4,
         "row_fingerprint_sha256": "3" * 64},
        {"role": "VERIFIED_FULL_NOTICE_BODY_PRODUCT", "source_product_sha256": body_product_sha,
         "source_ref": f"products/{body_product_sha}.json#notice", "source_row_index": 0,
         "row_fingerprint_sha256": body_product_sha},
    ]
    metadata = {"publication_date": "2026-10-15", "title": "同一公告", "symbol": "HK.09963",
                "available_at": "2026-10-15T18:32:00+08:00", "observed_at": "2026-10-15T18:32:00+08:00",
                "article_membership_status": "IN", "membership_authority_sha256": "a" * 64,
                "source_issuer_codes": [{"code": "HK.09963", "name": "测试公司"}],
                "source_issuer_membership": [{"code": "HK.09963", "membership_status": "IN",
                                              "market": "HK_CONNECT", "authority_sha256": "a" * 64}],
                "source_origins": source_origins}
    products = {}
    for origin in source_origins:
        products[origin["source_product_sha256"]] = {
            "source_ref": origin["source_ref"].split("#", 1)[0],
            "sha256": origin["source_product_sha256"],
        }
    batch = {"schema": "v4.test.batch.v1", "batch_id": "same", "expected_count": 1,
             "articles": [{"article_id": article_id, "source_sha256": source_sha,
                           "body_sha256": body_sha, "article_body": article_body,
                           "article_metadata": metadata}],
             "source_products": sorted(products.values(), key=lambda item: (item["source_ref"], item["sha256"]))}
    return {"article_id": article_id, "source_sha256": source_sha, "body_sha256": body_sha,
            "article_body": article_body, "article_metadata": metadata,
            "fixed_fact_ledger": {"ledger_sha256": "5" * 64}, "date": "2026-10-15", "market": "HK",
            "prompt_sha256": "3" * 64, "model_id": "frozen-model", "configuration_sha256": "4" * 64,
            "rules": "frozen-rules", "role": "announcement_reader", "stage": "frozen-stage",
            "source_unit_map_sha256": "6" * 64, "validated_article_batch": batch,
            "messages": [{"role": "system", "content": "frozen prompt"},
                         {"role": "user", "content": "frozen article input"}]}


def test_recovery_version_capture_drift_normalizes_only_verified_row_provenance():
    bridge = _bridge_module()
    old = _version_provenance_payload(bridge, capture_sha="b" * 64)
    current = json.loads(json.dumps(old))
    current_capture = "e" * 64
    old_origins = old["article_metadata"]["source_origins"]
    current_origins = current["article_metadata"]["source_origins"]
    current_origins[0].update({"source_product_sha256": current_capture,
                               "source_ref": f"products/{current_capture}.json#/rows/11",
                               "source_row_index": 11, "row_fingerprint_sha256": "7" * 64})
    current["validated_article_batch"]["articles"][0]["article_metadata"] = current["article_metadata"]
    products = {}
    for origin in current_origins:
        products[origin["source_product_sha256"]] = {
            "source_ref": origin["source_ref"].split("#", 1)[0],
            "sha256": origin["source_product_sha256"],
        }
    current["validated_article_batch"]["source_products"] = sorted(
        products.values(), key=lambda item: (item["source_ref"], item["sha256"]))

    saved_normalized = bridge._version_payload_with_capture_provenance_normalized(old, "b" * 64)
    current_normalized = bridge._version_payload_with_capture_provenance_normalized(current, current_capture)
    assert saved_normalized is not None and current_normalized is not None
    assert saved_normalized == current_normalized

    current["messages"][1]["content"] += " changed"
    changed_prompt = bridge._version_payload_with_capture_provenance_normalized(current, current_capture)
    assert changed_prompt is not None and saved_normalized != changed_prompt


def test_current_capture_row_binding_checks_row_hash_and_complete_body():
    bridge = _bridge_module()
    capture_sha = "b" * 64
    payload = _version_provenance_payload(bridge, capture_sha=capture_sha, source_sha="d" * 64,
                                          body_sha="c" * 64, row_index=0)
    row = {"art_code": "AN202610150099", "title": "同一公告", "publication_date": "2026-10-15",
           "available_at": "2026-10-15T18:32:00+08:00", "display_time": "2026-10-15 18:32",
           "source_issuer_codes": payload["article_metadata"]["source_issuer_codes"],
           "body_text": payload["article_body"], "body_text_sha256": payload["body_sha256"],
           "source_sha256": payload["source_sha256"], "body_complete": True}
    capture_product = {"rows": [row]}
    payload["article_metadata"]["source_display_time"] = row["display_time"]
    payload["article_metadata"]["source_origins"][0]["row_fingerprint_sha256"] = _sha(_json_bytes(row))
    payload["validated_article_batch"]["articles"][0]["article_metadata"] = payload["article_metadata"]
    lock = {"capture_product_sha256": capture_sha}
    capture_ref = {"artifact_ref": f"products/{capture_sha}.json", "sha256": capture_sha}
    assert bridge._current_capture_row_matches_payload(payload, capture_product, capture_ref, lock)
    payload["article_metadata"]["source_origins"][0]["row_fingerprint_sha256"] = "f" * 64
    assert not bridge._current_capture_row_matches_payload(payload, capture_product, capture_ref, lock)


def test_explicit_resume_only_admits_exact_zero_attempt_pending_hk_connect_input(tmp_path):
    bridge = _bridge_module()
    body = "frozen complete body"
    identity = {"date": "2026-10-15", "market": "HK", "article_id": "EASTMONEY:AN202610150002",
                "source_sha256": "1" * 64, "body_sha256": _sha(body.encode()), "prompt_sha256": "3" * 64,
                "model_id": "qwen3_8_flash_next", "configuration_sha256": "4" * 64,
                "rules": "recent_day_reader_v2+profile:p+citation:c+unit-map:u+fixed-ledger:l",
                "role": "announcement_reader", "stage": "v4_manager_announcement_flash_incremental"}
    metadata = {
        "publication_date": "2026-10-15", "title": "同一公告", "symbol": "HK.09963",
        "available_at": "2026-10-15T18:31:00+08:00",
        "article_membership_status": "IN", "membership_authority_sha256": "a" * 64,
        "source_issuer_codes": [{"code": "HK.09963"}],
        "source_issuer_membership": [{"code": "HK.09963", "membership_status": "IN",
                                      "market": "HK_CONNECT", "authority_sha256": "a" * 64}],
    }
    old_payload = {**identity, "article_body": body, "article_metadata": metadata,
                   "fixed_fact_ledger": {}, "messages": [{"role": "user", "content": body}],
                   "structured_output_schema": {"type": "object"}, "source_unit_map_sha256": "b" * 64}
    queue = _AdmissionQueue()
    key = _sha(_json_bytes(queue._identity(old_payload)))
    queue_root = tmp_path / "queue"
    input_path = queue_root / "jobs" / key / "input.json"
    input_path.parent.mkdir(parents=True)
    raw_payload = _json_bytes(old_payload)
    input_path.write_bytes(raw_payload)
    job = {"idempotency_key": key, "identity": queue._identity(old_payload), "status": "PENDING",
           "attempt_count": 0, "max_attempts": 1, "queue_id": "v4-manager-flash-incremental",
           "input_path": f"jobs/{key}/input.json", "payload_sha256": _sha(raw_payload)}
    queue.jobs[key] = job
    current_payload = {**old_payload, "source_sha256": "5" * 64}
    current_payload["article_metadata"] = dict(metadata)

    plan = bridge._admit_incremental_payloads(
        [current_payload], queue, [], queue_root, resume_same_batch_pending=True,
        resume_cutoff="2026-10-16T14:57:00+08:00")

    assert plan["allowed_keys"] == {key}
    assert plan["new_enqueued"] == 0
    assert plan["resumed_pending"] == 1
    assert plan["articles_by_key"][key]["source_sha256"] == "1" * 64
    assert plan["resumed_payloads_by_key"][key]["source_sha256"] == "5" * 64
    assert queue.enqueued == []
    assert job["attempt_count"] == 0


def test_explicit_pending_resume_still_rejects_out_membership_and_attempted_jobs(tmp_path):
    bridge = _bridge_module()
    cases = (("PENDING", 0, "OUT", "2026-10-15T18:31:00+08:00"),
             ("PENDING", 1, "IN", "2026-10-15T18:31:00+08:00"),
             ("RUNNING", 0, "IN", "2026-10-15T18:31:00+08:00"),
             ("PENDING", 0, "IN", "2026-10-16T14:58:00+08:00"))
    for status, attempt_count, membership, available_at in cases:
        body = "frozen complete body"
        identity = {"date": "2026-10-15", "market": "HK", "article_id": "EASTMONEY:AN202610150003",
                    "source_sha256": "1" * 64, "body_sha256": _sha(body.encode()), "prompt_sha256": "3" * 64,
                    "model_id": "qwen3_8_flash_next", "configuration_sha256": "4" * 64,
                    "rules": "recent_day_reader_v2+profile:p+citation:c+unit-map:u+fixed-ledger:l",
                    "role": "announcement_reader", "stage": "v4_manager_announcement_flash_incremental"}
        metadata = {"publication_date": "2026-10-15", "title": "同一公告", "symbol": "HK.09963",
                    "available_at": available_at,
                    "article_membership_status": membership, "membership_authority_sha256": "a" * 64,
                    "source_issuer_codes": [{"code": "HK.09963"}],
                    "source_issuer_membership": [{"code": "HK.09963", "membership_status": membership,
                                                  "market": "HK_CONNECT", "authority_sha256": "a" * 64}]}
        old_payload = {**identity, "article_body": body, "article_metadata": metadata,
                       "fixed_fact_ledger": {}, "messages": [{"role": "user", "content": body}],
                       "structured_output_schema": {"type": "object"}, "source_unit_map_sha256": "b" * 64}
        queue = _AdmissionQueue()
        key = _sha(_json_bytes(queue._identity(old_payload)))
        queue_root = tmp_path / f"queue-{status}-{attempt_count}-{membership}"
        input_path = queue_root / "jobs" / key / "input.json"
        input_path.parent.mkdir(parents=True)
        raw_payload = _json_bytes(old_payload)
        input_path.write_bytes(raw_payload)
        job = {"idempotency_key": key, "identity": queue._identity(old_payload), "status": status,
               "attempt_count": attempt_count, "max_attempts": 1, "queue_id": "v4-manager-flash-incremental",
               "input_path": f"jobs/{key}/input.json", "payload_sha256": _sha(raw_payload)}
        queue.jobs[key] = job
        current_payload = {**old_payload, "source_sha256": "5" * 64}

        plan = bridge._admit_incremental_payloads(
            [current_payload], queue, [], queue_root, resume_same_batch_pending=True,
            resume_cutoff="2026-10-16T14:57:00+08:00")

        assert plan["allowed_keys"] == set()
        assert plan["resumed_pending"] == 0
        assert plan["matched"][0]["record"]["status"] == status
        assert job["attempt_count"] == attempt_count
        assert queue.enqueued == []


def test_prior_reviewed_same_content_is_excluded_when_rules_change():
    bridge = _bridge_module()
    history = bridge._pinned_candidate_history()
    reviewed = next(item for item in history if item["source"] == "PRIOR_REVIEWED_RESULT")
    identity = {**reviewed["identity"], "source_sha256": "f" * 64,
                "rules": reviewed["identity"]["rules"] + "+different-rule"}
    queue = _AdmissionQueue()

    plan = bridge._admit_incremental_payloads([_identity_payload(identity)], queue, history, Path("/tmp/unused-queue"))

    assert plan["allowed_keys"] == set()
    assert plan["matched"][0]["record"]["source"] == "PRIOR_REVIEWED_RESULT"
    assert plan["matched"][0]["rules_match"] is False
    assert queue.enqueued == []


def test_generic_runner_failure_persists_safe_diagnostic_and_reraises(tmp_path, monkeypatch):
    bridge = _bridge_module()
    job_id = "b" * 32
    state_root = tmp_path / "state"
    job_dir = state_root / "announcement_flash" / "jobs" / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "input.json").write_text(json.dumps({
        "schema": "v4.manager_workbench.announcement_flash_input.v1",
        "job_id": job_id,
        "target_date": "20261016",
    }), encoding="utf-8")
    secret_like_text = "DO_NOT_PERSIST_KEY_BODY_OR_RESPONSE"

    def fail_before_pipeline(*_args, **_kwargs):
        raise RuntimeError(secret_like_text)

    monkeypatch.setattr(bridge, "_run", fail_before_pipeline)
    try:
        bridge.main(["--state-root", str(state_root), "--capture-root", str(tmp_path / "capture"),
                     "--job-id", job_id])
    except RuntimeError as exc:
        assert str(exc) == secret_like_text
    else:
        raise AssertionError("generic runner exceptions must be re-raised after recording safe diagnostics")

    raw_progress = (job_dir / "progress.json").read_text(encoding="utf-8")
    progress = json.loads(raw_progress)
    assert progress["step"] == "FAILED"
    assert progress["failure_code"] == "FLASH_PIPELINE_RUNTIMEERROR"
    assert progress["diagnostic"]["exception_type"] == "RuntimeError"
    frames = progress["diagnostic"]["stack_frames"]
    assert frames
    assert all(set(frame) == {"file", "function", "line"} for frame in frames)
    assert all("/" not in frame["file"] and isinstance(frame["line"], int) and frame["line"] > 0
               for frame in frames)
    assert secret_like_text not in raw_progress


def test_runner_main_requires_explicit_opt_in_for_same_batch_pending_resume(tmp_path, monkeypatch):
    bridge = _bridge_module()
    job_id = "c" * 32
    state_root = tmp_path / "state"
    job_dir = state_root / "announcement_flash" / "jobs" / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "input.json").write_text(json.dumps({
        "schema": "v4.manager_workbench.announcement_flash_input.v1",
        "job_id": job_id,
        "target_date": "20261016",
    }), encoding="utf-8")
    received = []

    def fake_run(_input, *, resume_same_batch_pending=False, **_kwargs):
        received.append(resume_same_batch_pending)
        return {"job_id": job_id, "state": "PARTIAL",
                "counts": {"queue": {"succeeded": 0, "failed": 0, "pending": 0}}}

    monkeypatch.setattr(bridge, "_run", fake_run)
    base_args = ["--state-root", str(state_root), "--capture-root", str(tmp_path / "capture"),
                 "--job-id", job_id]

    assert bridge.main(base_args) == 0
    assert bridge.main([*base_args, "--resume-pending"]) == 0
    assert received == [False, True]


def test_recovery_lock_revalidates_frozen_rows_membership_bodies_and_cutoff_provenance():
    bridge = _bridge_module()
    from v4.manager_workbench.announcement_membership import capture_recovery_manifest
    from v4.manager_workbench.contracts import digest

    cutoff = "2026-10-16T14:57:00+08:00"
    body = "冻结正文"
    body_sha = _sha(body.encode("utf-8"))
    def row(article, symbol, *, complete):
        raw = {"art_code": article, "title": article, "notice_date": "2026-10-15 10:00:00",
               "display_time": "2026-10-15 10:00:00", "codes": [{"stock_code": symbol[3:],
               "market_code": "116", "ann_type": "H", "short_name": article}]}
        value = {"art_code": article, "title": article, "publication_date": "2026-10-15",
                 "display_time": "2026-10-15T10:00:00+08:00", "source_issuer_codes": [
                     {"code": symbol, "source_stock_code": symbol[3:], "market_code": "116",
                      "ann_type": "H", "name": article}], "raw_row": raw,
                 "window_consumption_status": "ELIGIBLE_SOURCE_TIME",
                 "listing_source_ref": {"sha256": "c" * 64}, "body_complete": complete}
        if complete:
            value.update(body_text=body, body_text_sha256=body_sha, content_page_count=1,
                         pages=[{"page_number": 1, "page_total": 1, "text": body,
                                 "source_ref": {"available_at": "2026-10-16T14:40:00+08:00",
                                                "reused_from": {"request_sha256": "d" * 64}}}])
        else:
            value.update(body_text=None, body_text_sha256=None, content_page_count=None, pages=[])
        return value

    rows = [row("AN202610150001", "HK.12345", complete=True),
            row("AN202610150002", "HK.99999", complete=False)]
    gate = {"status": "VERIFIED", "target_date": "20261016", "cutoff": cutoff,
            "authority_sha256": "e" * 64, "codes": ["HK.12345"]}
    manifest = capture_recovery_manifest(rows, gate)
    current_bodies = {article_id: value for article_id, value in manifest["body_sha256"].items()
                      if article_id in set(manifest["eligible_article_ids"])}
    capture_sha = "f" * 64
    capture_ref = {"artifact_ref": f"products/{capture_sha}.json", "sha256": capture_sha}
    recovery_lock = {
        "schema": "v4.manager_workbench.announcement_flash_recovery_lock.v1",
        "root_batch_job_id": "a" * 32, "parent_job_id": "b" * 32,
        "parent_input_sha256": "1" * 64, "parent_result_sha256": "2" * 64,
        "parent_capture_product_sha256": "3" * 64,
        "target_date": "20261016", "cutoff": cutoff, "membership_authority_sha256": "e" * 64,
        "capture_product_sha256": capture_sha,
        "row_count": manifest["row_count"], "article_ids_sha256": manifest["article_ids_sha256"],
        "row_manifest_sha256": manifest["row_manifest_sha256"],
        "eligible_article_ids": manifest["eligible_article_ids"],
        "eligible_article_ids_sha256": manifest["eligible_article_ids_sha256"],
        "eligible_count": manifest["eligible_count"], "expected_body_sha256": current_bodies,
        "eligible_missing_body_article_ids": [], "current_body_sha256": current_bodies,
        "current_body_sha256_digest": digest(current_bodies),
    }
    input_value = {"target_date": "20261016", "cutoff": cutoff, "recovery_lock": recovery_lock}

    bridge._validate_recovery_lock(input_value, capture_ref, {"rows": rows}, gate)

    changed_lock = dict(recovery_lock, eligible_article_ids=["EASTMONEY:AN202610150002"])
    try:
        bridge._validate_recovery_lock({**input_value, "recovery_lock": changed_lock},
                                       capture_ref, {"rows": rows}, gate)
    except bridge.FlashRunError as exc:
        assert exc.code == "RECOVERY_BATCH_BINDING_MISMATCH"
    else:
        raise AssertionError("recovery lock must reject an altered eligible article set")

    no_newline_digest = dict(recovery_lock,
                             current_body_sha256_digest=_sha(_json_bytes(current_bodies)))
    try:
        bridge._validate_recovery_lock({**input_value, "recovery_lock": no_newline_digest},
                                       capture_ref, {"rows": rows}, gate)
    except bridge.FlashRunError as exc:
        assert exc.code == "RECOVERY_BODY_BINDING_INVALID"
    else:
        raise AssertionError("V4 body-map digest must include the canonical trailing newline")

    wrong_body_map = dict(current_bodies)
    wrong_body_map["EASTMONEY:AN202610150001"] = "9" * 64
    changed_body_lock = dict(recovery_lock, current_body_sha256=wrong_body_map,
                             current_body_sha256_digest=digest(wrong_body_map))
    try:
        bridge._validate_recovery_lock({**input_value, "recovery_lock": changed_body_lock},
                                       capture_ref, {"rows": rows}, gate)
    except bridge.FlashRunError as exc:
        assert exc.code == "RECOVERY_BODY_BINDING_MISMATCH"
    else:
        raise AssertionError("a changed current body hash must remain rejected")


def test_hk_connect_gate_filters_before_queue_and_preserves_expected_article_and_stock_counts():
    from v4.manager_workbench.announcement_membership import filter_payloads, project_stocks

    members = [f"HK.{value:05d}" for value in range(1, 16)]
    outsiders = [f"HK.{value:05d}" for value in range(90001, 90006)]
    gate = {"status": "VERIFIED", "authority_sha256": "a" * 64, "codes": members}
    payloads = []
    for index in range(76):
        code = members[index % len(members)]
        payloads.append({"article_id": f"EASTMONEY:IN{index:03d}", "date": "20261015", "market": "HK",
                         "source_sha256": _sha(f"src-in-{index}".encode()),
                         "body_sha256": _sha(f"body-in-{index}".encode()), "prompt_sha256": "b" * 64,
                         "model_id": "qwen3_8_flash_next", "configuration_sha256": "c" * 64,
                         "rules": "r1", "role": "announcement_reader", "stage": "incremental",
                         "article_body": "body", "article_metadata": {"symbol": code,
                         "source_issuer_codes": [{"code": code}], "title": "in"},
                         "fixed_fact_ledger": {}})
    for index in range(78):
        code = outsiders[index % len(outsiders)]
        payloads.append({"article_id": f"EASTMONEY:OUT{index:03d}", "article_metadata": {
            "symbol": code, "source_issuer_codes": [{"code": code}], "title": "out"}})
    payloads.extend([
        {"article_id": "EASTMONEY:UNKNOWN1", "article_metadata": {"symbol": "CANNOT_CONFIRM",
         "source_issuer_codes": [], "title": "unknown"}},
        {"article_id": "EASTMONEY:UNKNOWN2", "article_metadata": {"symbol": "CANNOT_CONFIRM",
         "source_issuer_codes": [{"code": "HK.00001"}, {"code": "US.ABC"}], "title": "ambiguous"}},
    ])

    admitted, exclusions = filter_payloads(payloads, gate)
    status_counts = {status: sum(item["membership_status"] == status for item in exclusions)
                     for status in ("OUT", "UNKNOWN")}
    assert len(admitted) == 76
    assert status_counts == {"OUT": 78, "UNKNOWN": 2}
    assert all(item["article_id"].endswith(tuple(f"IN{i:03d}" for i in range(76))) for item in admitted)

    bridge = _bridge_module()
    queue = _AdmissionQueue()
    plan = bridge._admit_incremental_payloads(admitted, queue, [], Path("/tmp/unused-queue"))
    assert len(queue.enqueued) == 76
    assert len(plan["allowed_keys"]) == 76
    stock_rows = [{"symbol": code, "articles": []} for code in members + outsiders]
    eligible, excluded_stocks, unknown_stocks = project_stocks(stock_rows, gate)
    assert (len(eligible), len(excluded_stocks), len(unknown_stocks)) == (15, 5, 0)


def test_hk_connect_out_and_unknown_only_run_skips_enqueue_queue_run_and_transport(tmp_path, monkeypatch):
    bridge = _bridge_module()
    pipeline_root = bridge.PIPELINE_ROOT
    assert pipeline_root.is_dir()
    monkeypatch.syspath_prepend(str(pipeline_root))
    batch_runner = importlib.import_module("batch_runner")
    length_canary = importlib.import_module("build_length_canary")
    canary_module = importlib.import_module("automatic_canary_server")
    calls = {"enqueue": 0, "run_next": 0, "transport": 0}

    class Queue:
        def __init__(self, *_args, **_kwargs):
            pass

        def _load_state(self):
            return {"jobs": {}}

        def enqueue(self, _payload):
            calls["enqueue"] += 1
            raise AssertionError("OUT/UNKNOWN payloads must not be enqueued")

        def run_next(self, *_args, **_kwargs):
            calls["run_next"] += 1
            raise AssertionError("OUT/UNKNOWN-only input must not call run_next")

        def snapshot(self):
            return {"items": []}

    queue_module = ModuleType("announcement_queue")
    queue_module.SerialAnnouncementQueue = Queue

    def forbidden_transport(*_args, **_kwargs):
        calls["transport"] += 1
        raise AssertionError("OUT/UNKNOWN-only input must not construct model transport")

    monkeypatch.setattr(canary_module, "GatedStreamingTransport", forbidden_transport)
    monkeypatch.setitem(sys.modules, "announcement_queue", queue_module)
    monkeypatch.setitem(sys.modules, "automatic_canary_server", canary_module)
    monkeypatch.setitem(sys.modules, "batch_runner", batch_runner)
    monkeypatch.setitem(sys.modules, "build_length_canary", length_canary)
    tokenizer = SimpleNamespace(apply_chat_template=lambda *_args, **_kwargs: [1, 2, 3])
    transformers = ModuleType("transformers")
    transformers.AutoTokenizer = SimpleNamespace(from_pretrained=lambda *_args, **_kwargs: tokenizer)
    monkeypatch.setitem(sys.modules, "transformers", transformers)

    helper = bridge._load_helper()
    monkeypatch.setattr(bridge, "_load_helper", lambda: helper)
    monkeypatch.setattr(bridge, "_pinned_candidate_history", lambda: [])
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1", "status": "VERIFIED",
            "target_date": "20261016", "cutoff": "2026-10-16T13:02:00+08:00", "market": "HK_CONNECT",
            "owner": "owner", "authority_sha256": "a" * 64, "authority_version": "v1",
            "effective_from": "20261001", "effective_to": "20261031",
            "available_at": "2026-10-12T19:58:59+08:00", "member_count": 1,
            "members_sha256": "b" * 64, "codes": ["HK.00001"]}
    from v4.manager_workbench import announcement_membership
    monkeypatch.setattr(announcement_membership, "revalidate_membership_gate", lambda *_args: dict(gate))

    capture_product = {"schema_version": "mwb.capture.window.v1",
                       "owner": "v4.manager_workbench.capture_announcements", "source": "EASTMONEY_HK",
                       "window": {"publication_dates": ["2026-10-16"]},
                       "rows": [
                           {"art_code": "ANOUT0001", "title": "范围外公告", "body_complete": True,
                            "body_text": "已采集正文", "source_issuer_codes": [{"code": "HK.09963"}]},
                           {"art_code": "ANUNKNOWN1", "title": "资格未知公告", "body_complete": True,
                            "body_text": "已采集正文", "source_issuer_codes": []},
                       ]}
    capture_raw = _json_bytes(capture_product)
    capture_sha = _sha(capture_raw)
    capture_ref = f"products/{capture_sha}.json"
    capture_root = tmp_path / "capture"
    capture_path = capture_root / capture_ref
    capture_path.parent.mkdir(parents=True)
    capture_path.write_bytes(capture_raw)

    result = bridge._run(
        {"target_date": "20261016", "cutoff": gate["cutoff"], "membership_gate": gate,
         "capture_product": {"artifact_ref": capture_ref, "sha256": capture_sha}},
        state_root=tmp_path / "state", capture_root=capture_root,
        job_id="f" * 32, progress=lambda _event: None, shared_root=tmp_path / "shared",
    )

    assert result["counts"]["membership_articles"] == {"in": 0, "out": 1, "unknown": 1}
    assert result["counts"]["queue"]["new_enqueued"] == 0
    assert result["counts"]["queue"]["new_model_calls_allowed"] == 0
    assert {item["membership_status"] for item in result["membership_exclusions"]} == {"OUT", "UNKNOWN"}
    assert calls == {"enqueue": 0, "run_next": 0, "transport": 0}


def test_hk_connect_membership_gate_fails_closed_for_missing_stale_or_changed_authority(monkeypatch):
    from v4.manager_workbench import announcement_membership as membership

    good = {"schema": membership.SCHEMA, "status": "VERIFIED", "target_date": "20261016",
            "cutoff": "2026-10-16T13:02:00+08:00", "market": "HK_CONNECT", "owner": "owner",
            "authority_sha256": "a" * 64, "authority_version": "v1", "effective_from": "20261001",
            "effective_to": "20261031", "available_at": "2026-10-12T19:58:59.501065+08:00",
            "member_count": 1, "members_sha256": "b" * 64, "codes": ["HK.00001"]}
    monkeypatch.setattr(membership, "resolve_membership_gate", lambda *_args: dict(good))

    assert membership.revalidate_membership_gate(None, good, "20261016", good["cutoff"])["status"] == "VERIFIED"
    assert membership.revalidate_membership_gate(None, None, "20261016", good["cutoff"])["status"] == "CANNOT_CONFIRM"
    assert membership.revalidate_membership_gate(None, good, "20261017", good["cutoff"])["status"] == "CANNOT_CONFIRM"
    assert membership.revalidate_membership_gate(None, good, "20261016", "2026-10-16T13:03:00+08:00")["status"] == "CANNOT_CONFIRM"
    changed = {**good, "authority_sha256": "c" * 64}
    monkeypatch.setattr(membership, "resolve_membership_gate", lambda *_args: changed)
    result = membership.revalidate_membership_gate(None, good, "20261016", good["cutoff"])
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["failure_code"] == "MEMBERSHIP_GATE_BINDING_CHANGED"


def test_article_payload_carries_verified_connect_membership_without_side_eligibility(monkeypatch):
    bridge = _bridge_module()
    monkeypatch.setattr(bridge, "_capture_origin", lambda *_args, **_kwargs: [])
    gate = {"status": "VERIFIED", "authority_sha256": "a" * 64, "codes": ["HK.09963"]}
    body = "公告正文"
    body_sha = _sha(body.encode())
    row = {"body_complete": True, "body_text": body, "body_text_sha256": body_sha,
           "source_sha256": "c" * 64, "source_issuer_codes": [{"code": "HK.09963", "name": "测试公司"}],
           "title": "测试公告", "publication_date": "2026-10-15"}
    fake_runner = SimpleNamespace(
        build_source_unit_map=lambda *_args: {"unit_map": []},
        simple_fixed_facts=SimpleNamespace(extract_fixed_facts=lambda *_args: {}),
    )

    article = bridge._article(row, 0, {}, {"row_index": 0}, None, fake_runner, gate)

    metadata = article["article_metadata"]
    assert metadata["article_membership_status"] == "IN"
    assert metadata["membership_authority_sha256"] == gate["authority_sha256"]
    assert metadata["source_issuer_membership"] == [{
        "code": "HK.09963", "membership_status": "IN", "market": "HK_CONNECT",
        "authority_sha256": gate["authority_sha256"],
    }]
    assert not {"buy_eligible", "sell_eligible", "orders_sent", "buy_gate_updated"}.intersection(metadata)


def _chunk_unit_map(body, cuts):
    from v4.manager_workbench import announcement_chunks as chunks

    points = [0, *cuts, len(body)]
    units = []
    for index, (start, end) in enumerate(zip(points, points[1:]), 1):
        text = body[start:end]
        units.append({"source_unit_id": f"U{index:06d}", "start_cp": start, "end_cp": end,
                      "unit_sha256": _sha(text.encode()), "text": text})
    body_sha = _sha(body.encode())
    map_material = {"protocol": "test-map-v1", "boundary_policy": "test-fixed-cuts-v1",
                    "body_sha256": body_sha,
                    "units": [{key: unit[key] for key in ("source_unit_id", "start_cp", "end_cp", "unit_sha256")}
                              for unit in units]}
    return body_sha, {**map_material, "units": units,
                      "source_unit_map_sha256": _sha(chunks.canonical(map_material))}


def _failed_part_fixture(tmp_path, index, status="FAILED", *, shared=None):
    if shared is None:
        bridge = _bridge_module()
        queue, queue_root, _old_key, _old_job, current, lock, gate, cutoff = _recovery_version_fixture(tmp_path)
    else:
        bridge, queue, queue_root, current, lock, gate, cutoff = shared
    from v4.manager_workbench import announcement_chunks as chunks

    payload = {**current,
               "prompt_sha256": "a" * 64,
               "rules": current["rules"] + f"+long-body-part:v1+part:{index}/3",
               "role": "announcement_reader_part",
               "stage": "v4_manager_announcement_flash_long_body_part_v1",
               "queue_task_kind": "announcement_reader_part",
               "chunk_plan_sha256": "b" * 64,
               "part_descriptor": {"part_index": index, "part_count": 3,
                                   "start_source_unit_id": f"U{index:06d}",
                                   "end_source_unit_id": f"U{index:06d}",
                                   "source_unit_ids": [f"U{index:06d}"],
                                   "part_sha256": _sha(f"part-{index}".encode())},
               "source_unit_map_sha256": "6" * 64,
               "messages": [{"role": "system", "content": "完整原始Reader规则\n\n" + chunks.PART_ADDENDUM},
                            {"role": "user", "content": f"原始分片{index}及其局部账本"}],
               "structured_output_schema": {"type": "object", "properties": {"reader_output": {"type": "object", "properties": {
                   "facts": {"type": "array", "items": {"type": "object"}},
                   "changes": {"type": "array", "items": {"type": "object"}}}}}},
               "input_schema": chunks.PART_INPUT_SCHEMA,
               "prompt_tokens_exact": 50, "prompt_token_cap": 64_000,
               "context_limit_tokens": 262_144, "completion_reserve_tokens": 32_768,
               "token_safety_margin": 1_024, "batch_binding_sha256": "9" * 64}
    item = queue.enqueue(payload)
    if status == "FAILED":
        raw_ref = f"jobs/{item['idempotency_key']}/attempt-0001.raw"
        raw = _json_bytes({"action": "complete", "lookup_request": None,
                           "reader_output": {"facts": [], "changes": [
                               {"claim": "原始回答里的受拒绝变化", "start_source_unit_id": "EASTMONEY:AN202610150099::U000001",
                                "end_source_unit_id": "EASTMONEY:AN202610150099::U000001"}]}})
        (queue_root / raw_ref).write_bytes(raw)
        item.update({"status": "FAILED", "attempt_count": 1, "raw_path": raw_ref,
                     "raw_sha256": _sha(raw), "last_error": {"code": "PART_FIXED_FIELDS_MUST_BE_EMPTY",
                     "stage": "validator"},
                     "attempts": [{"status": "FAILED", "number": 1,
                                   "error": {"code": "PART_FIXED_FIELDS_MUST_BE_EMPTY", "stage": "validator"},
                                   "raw_path": raw_ref, "raw_sha256": _sha(raw)}]})
    elif status == "SUCCEEDED":
        item.update({"status": "SUCCEEDED", "attempt_count": 1, "validated_sha256": "e" * 64})
    return bridge, queue, queue_root, payload, item, lock, gate, cutoff, current


def _frozen_legacy_failed_canary_fixture(tmp_path, *, second_failed_part=False,
                                         part_index=1, part_count=3):
    bridge, _old_queue, _old_root, current, _old_job, lock, gate, cutoff, _base = _failed_part_fixture(
        tmp_path, part_index)
    from copy import deepcopy
    import re
    from v4.manager_workbench import announcement_chunks as chunks

    root_binding = {
        "source_job_id": "c" * 32, "source_input_sha256": "d" * 64,
        "target_date": "20261016", "cutoff": cutoff,
        "capture_product_sha256": lock["capture_product_sha256"],
        "membership_authority_sha256": gate["authority_sha256"],
    }
    current["part_descriptor"].update(part_count=part_count, unit_start_index=0, unit_end_index=1,
                                       prompt_tokens_exact=17)
    prefix = current["rules"].split("+long-body-part:v1", 1)[0]
    suffix = (f"+long-body-part:v1+plan:{current['chunk_plan_sha256']}"
              f"+part:{part_index}/{part_count}+part-sha:{current['part_descriptor']['part_sha256']}"
              f"+part-prompt:{current['prompt_sha256']}+part-addendum:{chunks.PART_ADDENDUM_SHA256}")

    def bind_capture_origin(payload):
        origin = payload["article_metadata"]["source_origins"][0]
        origin.update(source_ref=f"products/{lock['capture_product_sha256']}.json#/rows/0",
                      source_row_index=0, row_fingerprint_sha256="e" * 64)
        payload["frozen_resume_binding"] = deepcopy(root_binding)

    current = deepcopy(current)
    current["rules"] = prefix + f"+fixed-fields-contract:{chunks.PART_FIXED_FIELDS_CONTRACT_VERSION}" + suffix
    current["frozen_source_rules_suffix"] = suffix
    bind_capture_origin(current)
    assert bridge._current_frozen_resume_payload_valid(current, gate, root_binding)

    queue_root = tmp_path / "frozen-legacy-queue"
    queue = _PersistingAdmissionQueue(queue_root)

    def save_failed(payload, *, rules, raw_fields):
        value = deepcopy(payload)
        value["rules"] = rules
        bind_capture_origin(value)
        job = queue.enqueue(value)
        raw_ref = f"jobs/{job['idempotency_key']}/attempt-0001.raw"
        raw_value = {"action": "complete", "lookup_request": None,
                     "reader_output": {"facts": raw_fields.get("facts", []),
                                        "changes": raw_fields.get("changes", [])}}
        raw = _json_bytes(raw_value)
        (queue_root / raw_ref).parent.mkdir(parents=True, exist_ok=True)
        (queue_root / raw_ref).write_bytes(raw)
        job.update({"status": "FAILED", "attempt_count": 1, "max_attempts": 1,
                    "raw_path": raw_ref, "raw_sha256": _sha(raw),
                    "attempts": [{"status": "FAILED", "number": 1,
                                  "error": {"stage": "validator", "code": "PART_FIXED_FIELDS_MUST_BE_EMPTY"},
                                  "raw_path": raw_ref, "raw_sha256": _sha(raw)}]})
        return job, value

    source_job, source_payload = save_failed(
        current, rules=prefix + suffix, raw_fields={"changes": []})
    legacy_job, legacy_payload = save_failed(
        current, rules=prefix + "+fixed-fields-contract:v1" + suffix + "+validator-feedback-repair:v1",
        raw_fields={"changes": [{"claim": "legacy rejection"}]})
    legacy = {
        "key": legacy_job["idempotency_key"], "payload_sha256": legacy_job["payload_sha256"],
        "raw_sha256": legacy_job["raw_sha256"], "source_job_id": "b" * 32,
        "source_input_sha256": "f" * 64, "root_job_id": root_binding["source_job_id"],
        "root_input_sha256": root_binding["source_input_sha256"],
        "article_id": current["article_id"], "source_sha256": current["source_sha256"],
        "body_sha256": current["body_sha256"], "chunk_plan_sha256": current["chunk_plan_sha256"],
        "source_unit_map_sha256": current["source_unit_map_sha256"],
        "part_descriptor": deepcopy(current["part_descriptor"]),
        "source_part_key": source_job["idempotency_key"],
    }
    specs = {current["article_id"]: {"part_payloads": [current],
                                     "frozen_resume_binding": deepcopy(root_binding)}}
    if second_failed_part:
        _b, _q, _qr, second, _item, _lock, _gate, _cutoff, _current = _failed_part_fixture(
            tmp_path, 2, shared=(bridge, queue, queue_root, current, lock, gate, cutoff))
        second = deepcopy(second)
        second_suffix = (f"+long-body-part:v1+plan:{second['chunk_plan_sha256']}"
                         f"+part:2/3+part-sha:{second['part_descriptor']['part_sha256']}"
                         f"+part-prompt:{second['prompt_sha256']}+part-addendum:{chunks.PART_ADDENDUM_SHA256}")
        second["rules"] = prefix + f"+fixed-fields-contract:{chunks.PART_FIXED_FIELDS_CONTRACT_VERSION}" + second_suffix
        second["frozen_source_rules_suffix"] = second_suffix
        bind_capture_origin(second)
        second_source, _payload = save_failed(second, rules=prefix + second_suffix,
                                              raw_fields={"changes": []})
        specs[current["article_id"]]["part_payloads"].append(second)
    return bridge, queue, queue_root, current, source_job, legacy_job, legacy, specs, lock, gate, cutoff


def _frozen_legacy_orphan_canary_fixture(tmp_path, *, part_index=1, part_count=3):
    (bridge, queue, queue_root, current, source_job, _old_legacy_job, _old_legacy, specs,
     lock, gate, cutoff) = _frozen_legacy_failed_canary_fixture(
         tmp_path, part_index=part_index, part_count=part_count)
    from copy import deepcopy

    source_path = queue_root / source_job["input_path"]
    frozen_source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    frozen_source_payload.pop("frozen_resume_binding", None)
    frozen_source_raw = _json_bytes(frozen_source_payload)
    source_path.write_bytes(frozen_source_raw)
    source_job["payload_sha256"] = _sha(frozen_source_raw)

    orphan_payload = bridge._orphan_recovery_payload(
        frozen_source_payload, source_job, source_job_id="b" * 32,
        source_input_sha256="f" * 64, source_key=source_job["idempotency_key"],
    )
    legacy_job = queue.enqueue(orphan_payload)
    raw_ref = f"jobs/{legacy_job['idempotency_key']}/attempt-0001.raw"
    raw_value = {"action": "complete", "lookup_request": None,
                 "reader_output": {"facts": [], "changes": [{"claim": "legacy fixed-field failure"}]}}
    raw = _json_bytes(raw_value)
    (queue_root / raw_ref).parent.mkdir(parents=True, exist_ok=True)
    (queue_root / raw_ref).write_bytes(raw)
    legacy_job.update({"status": "FAILED", "attempt_count": 1, "max_attempts": 1,
                       "raw_path": raw_ref, "raw_sha256": _sha(raw),
                       "attempts": [{"status": "FAILED", "number": 1,
                                     "error": {"stage": "validator", "code": "PART_FIXED_FIELDS_MUST_BE_EMPTY"},
                                     "raw_path": raw_ref, "raw_sha256": _sha(raw)}]})
    legacy = {
        "key": legacy_job["idempotency_key"], "payload_sha256": legacy_job["payload_sha256"],
        "raw_sha256": legacy_job["raw_sha256"], "source_job_id": "b" * 32,
        "source_input_sha256": "f" * 64,
        "root_job_id": specs[current["article_id"]]["frozen_resume_binding"]["source_job_id"],
        "root_input_sha256": specs[current["article_id"]]["frozen_resume_binding"]["source_input_sha256"],
        "article_id": current["article_id"], "source_sha256": current["source_sha256"],
        "body_sha256": current["body_sha256"], "chunk_plan_sha256": current["chunk_plan_sha256"],
        "source_unit_map_sha256": current["source_unit_map_sha256"],
        "part_descriptor": deepcopy(current["part_descriptor"]),
        "source_part_key": source_job["idempotency_key"],
    }
    return (bridge, queue, queue_root, current, source_job, legacy_job, legacy, specs,
            lock, gate, cutoff)


def test_run_frozen_resume_copies_binding_before_any_queue_admission(tmp_path, monkeypatch):
    bridge = _bridge_module()
    from v4.manager_workbench import announcement_chunks as chunks
    from v4.manager_workbench import announcement_membership

    calls = {"enqueue": 0, "run_next": 0, "transport": 0}

    class Queue:
        def __init__(self, *_args, **_kwargs):
            pass

        def _load_state(self):
            return {"jobs": {}}

        def enqueue(self, *_args, **_kwargs):
            calls["enqueue"] += 1
            raise AssertionError("planning must stop before queue admission")

        def run_next(self, *_args, **_kwargs):
            calls["run_next"] += 1
            raise AssertionError("planning must stop before model dispatch")

    queue_module = ModuleType("announcement_queue")
    queue_module.SerialAnnouncementQueue = Queue
    canary_module = ModuleType("automatic_canary_server")

    def forbidden_transport(*_args, **_kwargs):
        calls["transport"] += 1
        raise AssertionError("planning must not construct model transport")

    canary_module.GatedStreamingTransport = forbidden_transport
    runner = SimpleNamespace(
        MODEL_ID="qwen3_8_flash_next", SIMPLE_WORKFLOW_RANGE_PROFILE="profile-v1",
        SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL="citation-v1",
        OMLX_TOKENIZER_PATH="unused", load_active_contract=lambda: object(),
        _simple_model_fixed_fact_ledger_for_article=lambda *_args: {},
    )
    length_canary = SimpleNamespace(make_batch=lambda articles, batch_id: {"articles": articles, "batch_id": batch_id})
    monkeypatch.setitem(sys.modules, "announcement_queue", queue_module)
    monkeypatch.setitem(sys.modules, "automatic_canary_server", canary_module)
    monkeypatch.setitem(sys.modules, "batch_runner", runner)
    monkeypatch.setitem(sys.modules, "build_length_canary", length_canary)

    cutoff = "2026-10-16T13:02:00+08:00"
    authority_sha = "a" * 64
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1", "status": "VERIFIED",
            "target_date": "20261016", "cutoff": cutoff, "market": "HK_CONNECT",
            "authority_sha256": authority_sha, "codes": ["HK.00001"]}
    request_material = {
        "workflow_profile": runner.SIMPLE_WORKFLOW_RANGE_PROFILE,
        "citation_protocol": "citation-v1", "sampling_policy": {"request_temperature": 0.0},
        "configuration_material": {"model_id": runner.MODEL_ID, "request_temperature": 0.0,
                                    "enable_thinking": False, "max_completion_tokens": 0},
        "runtime_limits": {"context_limit_tokens": 200_000}, "max_completion_tokens": 0,
        "prompt": "frozen reader prompt", "prompt_sha256": "1" * 64,
        "configuration_sha256": "2" * 64, "schema_sha256": "3" * 64,
        "runtime_settings_sha256": "4" * 64, "model_settings_sha256": "5" * 64,
        "schema": {"type": "object"},
    }
    helper = SimpleNamespace(
        _full_day_request_material=lambda _contract: request_material,
        _messages_for_article=lambda *_args, **_kwargs: [{"role": "user", "content": "article"}],
        _token_count=lambda _tokenizer, _messages: 17,
    )
    monkeypatch.setattr(bridge, "_load_helper", lambda: helper)
    monkeypatch.setattr(bridge, "_validator", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(bridge, "_verify_resume_root_input", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bridge, "_needs_chunk_plan", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(bridge, "_load_frozen_resume_plan", lambda *_args, **_kwargs: ({
        "plan_sha256": "6" * 64, "prompt_sha256": "7" * 64,
        "part_addendum_sha256": chunks.PART_ADDENDUM_SHA256,
        "parts": [{"part_index": 1, "part_count": 1, "unit_start_index": 0,
                   "unit_end_index": 1, "part_sha256": "8" * 64, "prompt_tokens_exact": 17}],
    }, "long-body/frozen-plan.json"))
    monkeypatch.setattr(bridge, "_part_messages", lambda *_args, **_kwargs: [
        {"role": "system", "content": "reader instructions"},
        {"role": "user", "content": "part"},
    ])
    monkeypatch.setattr(bridge, "_part_prompt_token_preflight_valid", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(bridge, "_pinned_candidate_history", lambda: [])
    monkeypatch.setattr(announcement_membership, "revalidate_membership_gate", lambda *_args: dict(gate))
    monkeypatch.setattr(chunks, "verify_part_coverage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chunks, "project_part_ledger", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(chunks, "empty_reader_fixed_fields_schema", lambda _schema: {"type": "object"})
    monkeypatch.setattr(chunks, "reader_task_system_prompt", lambda _prompt, task: f"system-{task}")

    body = "冻结正文"
    body_sha = _sha(body.encode())
    source_sha = "9" * 64
    unit_map = {"units": [{"source_unit_id": "U000001"}], "source_unit_map_sha256": "b" * 64}
    article_id = "EASTMONEY:AN202610160001"
    article = {
        "article_id": article_id, "source_sha256": source_sha, "body_sha256": body_sha,
        "article_body": body,
        "article_metadata": {"publication_date": "2026-10-16", "symbol": "HK.00001",
                             "title": "测试公告", "membership_authority_sha256": authority_sha},
        "fixed_fact_ledger": {"ledger_sha256": "c" * 64}, "_source_unit_map": unit_map,
    }
    monkeypatch.setattr(bridge, "_article", lambda *_args, **_kwargs: dict(article))

    class PlanningReached(Exception):
        pass

    observed = []

    def stop_before_source_lookup(payload, *_args, **_kwargs):
        observed.append(payload)
        raise PlanningReached

    monkeypatch.setattr(bridge, "_find_frozen_source_part", stop_before_source_lookup)
    tokenizer = SimpleNamespace(encode=lambda *_args, **_kwargs: [1])
    transformers = ModuleType("transformers")
    transformers.AutoTokenizer = SimpleNamespace(from_pretrained=lambda *_args, **_kwargs: tokenizer)
    monkeypatch.setitem(sys.modules, "transformers", transformers)

    capture_product = {
        "schema_version": "mwb.capture.window.v1",
        "owner": "v4.manager_workbench.capture_announcements", "source": "EASTMONEY_HK",
        "saved_ref": None, "window": {"publication_dates": ["2026-10-16"]},
        "rows": [{"art_code": "AN202610160001", "title": "测试公告",
                  "source_issuer_codes": [{"code": "HK.00001"}], "body_complete": True, "body_text": body}],
    }
    capture_raw = _json_bytes(capture_product)
    capture_sha = _sha(capture_raw)
    capture_ref = f"products/{capture_sha}.json"
    capture_root = tmp_path / "capture"
    capture_path = capture_root / capture_ref
    capture_path.parent.mkdir(parents=True)
    capture_path.write_bytes(capture_raw)
    input_value = {
        "target_date": "20261016", "cutoff": cutoff, "membership_gate": gate,
        "capture_product": {"artifact_ref": capture_ref, "sha256": capture_sha},
        "resume_root": {"source_job_id": "d" * 32, "source_input_sha256": "e" * 64},
    }

    with __import__("pytest").raises(PlanningReached):
        bridge._run(
            input_value, state_root=tmp_path / "state", capture_root=capture_root,
            job_id="f" * 32, progress=lambda _event: None, shared_root=tmp_path / "shared",
            resume_frozen_batch=True, resume_action="CANARY", max_model_calls=1,
            resume_source_job_id="1" * 32, resume_source_input_sha256="2" * 64,
        )

    assert len(observed) == 1
    assert observed[0]["frozen_resume_binding"] == {
        "source_job_id": "d" * 32, "source_input_sha256": "e" * 64,
        "target_date": "20261016", "cutoff": cutoff,
        "capture_product_sha256": capture_sha, "membership_authority_sha256": authority_sha,
    }
    assert calls == {"enqueue": 0, "run_next": 0, "transport": 0}


def _part_repair_capture_provenance_reuse_fixture(tmp_path):
    import copy

    bridge = _bridge_module()
    from v4.manager_workbench import announcement_chunks as chunks
    from v4.manager_workbench.contracts import digest as v4_digest

    body = "冻结的完整公告正文"
    body_sha = _sha(body.encode())
    article_id = "EASTMONEY:AN202610150099"
    authority = "a" * 64
    source_sha = "7" * 64
    listing_sha = "8" * 64
    old_capture_sha = "9" * 64
    current_capture_sha = "0" * 64
    root_id, old_parent_id, current_parent_id = "c" * 32, "b" * 32, "d" * 32
    cutoff = "2026-10-16T14:57:00+08:00"
    capture_origin = lambda product_sha: {
        "role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_product_sha256": product_sha,
        "source_ref": f"products/{product_sha}.json#/rows/3", "source_row_index": 3,
        "row_fingerprint_sha256": "1" * 64,
    }
    listing_origin = {
        "role": "FULL_DATE_DIRECTORY_PAGE", "source_product_sha256": listing_sha,
        "source_ref": f"objects/{listing_sha}.bin#data/list/0", "source_row_index": 0,
        "row_fingerprint_sha256": "2" * 64,
    }
    body_origin = {
        "role": "VERIFIED_FULL_NOTICE_BODY_PRODUCT", "source_product_sha256": source_sha,
        "source_ref": f"products/{source_sha}.json#notice", "source_row_index": 0,
        "row_fingerprint_sha256": source_sha,
    }
    base_metadata = {
        "publication_date": "2026-10-15", "title": "同一冻结公告", "symbol": "HK.09963",
        "available_at": "2026-10-15T18:32:00+08:00", "article_membership_status": "IN",
        "membership_authority_sha256": authority,
        "source_issuer_codes": [{"code": "HK.09963", "name": "测试公司"}],
        "source_issuer_membership": [{"code": "HK.09963", "membership_status": "IN",
                                       "market": "HK_CONNECT", "authority_sha256": authority}],
    }
    body_sha, unit_map = _chunk_unit_map(body, [])
    part = {"part_index": 1, "part_count": 1, "start_source_unit_id": "U000001",
            "end_source_unit_id": "U000001", "source_unit_ids": ["U000001"],
            "part_sha256": _sha(body.encode())}
    base_messages = [
        {"role": "system", "content": "Frozen Reader system prompt\n\n" + chunks.PART_ADDENDUM},
        {"role": "user", "content": "Frozen article units and local ledger"},
    ]

    def products(origins):
        values = {}
        for origin in origins:
            product_ref = origin["source_ref"].split("#", 1)[0]
            values[origin["source_product_sha256"]] = {
                "sha256": origin["source_product_sha256"], "source_ref": product_ref,
            }
        return sorted(values.values(), key=lambda item: (item["source_ref"], item["sha256"]))

    def payload_for(capture_sha):
        metadata = copy.deepcopy(base_metadata)
        metadata["source_origins"] = [capture_origin(capture_sha), listing_origin, body_origin]
        article = {"article_id": article_id, "source_sha256": source_sha,
                   "body_sha256": body_sha, "article_body": body,
                   "article_metadata": metadata, "fixed_fact_ledger": {"ledger_sha256": "3" * 64}}
        batch = {"schema": "v4.test.announcement_batch.v1", "batch_id": "frozen-batch",
                 "expected_count": 1, "articles": [copy.deepcopy(article)],
                 "source_products": products(metadata["source_origins"])}
        return {
            **article, "date": "2026-10-15", "market": "HK", "prompt_sha256": "4" * 64,
            "model_id": "qwen3_8_flash_next", "configuration_sha256": "5" * 64,
            "rules": "recent_day_reader_v2+frozen-profile+part:1/1",
            "role": "announcement_reader_part", "stage": "v4_manager_announcement_flash_long_body_part_v1",
            "queue_task_kind": "announcement_reader_part", "chunk_plan_sha256": "6" * 64,
            "part_descriptor": part, "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
            "validated_article_batch": batch, "messages": copy.deepcopy(base_messages),
            "structured_output_schema": {"type": "object", "properties": {"reader_output": {"type": "object", "properties": {
                "facts": {"type": "array", "items": {"type": "object"}},
                "changes": {"type": "array", "items": {"type": "object"}}}}}},
            "workflow_profile": "decision_simple_facts_unit_ranges_v2",
            "citation_protocol": "protocol-v2", "input_schema": chunks.PART_INPUT_SCHEMA,
            "prompt_tokens_exact": 50, "prompt_token_cap": 64_000,
            "context_limit_tokens": 262_144, "completion_reserve_tokens": 32_768,
            "token_safety_margin": chunks.TOKEN_SAFETY_MARGIN, "batch_binding_sha256": "a" * 64,
        }

    old_part = payload_for(old_capture_sha)
    current_part = payload_for(current_capture_sha)
    mid_parent_id, root_capture_sha, mid_capture_sha = "e" * 32, "2" * 64, "6" * 64
    current_bodies = {article_id: body_sha}
    frozen_lock = {"schema": "v4.manager_workbench.announcement_flash_recovery_lock.v1",
                   "target_date": "20261016", "cutoff": cutoff, "root_batch_job_id": root_id,
                   "row_manifest_sha256": "e" * 64, "eligible_article_ids_sha256": "f" * 64,
                   "membership_authority_sha256": authority, "eligible_article_ids": [article_id],
                   "eligible_count": 1, "current_body_sha256": current_bodies,
                   "current_body_sha256_digest": v4_digest(current_bodies),
                   "expected_body_sha256": {article_id: body_sha}}
    old_lock = {**frozen_lock, "parent_job_id": old_parent_id,
                "capture_product_sha256": old_capture_sha,
                "parent_capture_product_sha256": mid_capture_sha}
    mid_lock = {**frozen_lock, "parent_job_id": old_parent_id,
                "capture_product_sha256": old_capture_sha,
                "parent_capture_product_sha256": mid_capture_sha}
    d_lock = {**frozen_lock, "parent_job_id": mid_parent_id,
              "capture_product_sha256": current_capture_sha,
              "parent_capture_product_sha256": old_capture_sha}
    current_lock = {**frozen_lock, "parent_job_id": current_parent_id,
                    "capture_product_sha256": current_capture_sha,
                    "parent_capture_product_sha256": current_capture_sha}
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1", "status": "VERIFIED",
            "target_date": "20261016", "cutoff": cutoff, "market": "HK_CONNECT",
            "authority_sha256": authority, "codes": ["HK.09963"]}

    state_root = tmp_path / "state"
    jobs_root = state_root / "announcement_flash" / "jobs"
    verified_gate = {"status": "VERIFIED", "target_date": "20261016", "cutoff": cutoff,
                     "authority_sha256": authority}
    root_input = {"job_id": root_id, "target_date": "20261016", "cutoff": cutoff,
                  "capture_product": {"sha256": root_capture_sha},
                  "membership_gate": verified_gate}
    root_result = {"job_id": root_id, "target_trade_date": "20261016", "state": "PARTIAL",
                   "membership_gate": verified_gate}
    root_input_raw, root_result_raw = _json_bytes(root_input), _json_bytes(root_result)
    root_dir = jobs_root / root_id
    root_dir.mkdir(parents=True)
    (root_dir / "input.json").write_bytes(root_input_raw)
    (root_dir / "result.json").write_bytes(root_result_raw)

    b_lock = {**frozen_lock, "parent_job_id": root_id,
              "capture_product_sha256": mid_capture_sha,
              "parent_capture_product_sha256": root_capture_sha,
              "parent_input_sha256": _sha(root_input_raw),
              "parent_result_sha256": _sha(root_result_raw)}
    b_input = {"job_id": old_parent_id, "target_date": "20261016", "cutoff": cutoff,
               "capture_product": {"sha256": mid_capture_sha}, "membership_gate": verified_gate,
               "recovery_lock": b_lock}
    b_result = {"job_id": old_parent_id, "target_trade_date": "20261016", "state": "PARTIAL",
                "membership_gate": verified_gate}
    b_input_raw, b_result_raw = _json_bytes(b_input), _json_bytes(b_result)
    b_dir = jobs_root / old_parent_id
    b_dir.mkdir()
    (b_dir / "input.json").write_bytes(b_input_raw)
    (b_dir / "result.json").write_bytes(b_result_raw)
    old_lock.update(parent_input_sha256=_sha(b_input_raw), parent_result_sha256=_sha(b_result_raw))

    mid_lock.update(parent_input_sha256=_sha(b_input_raw), parent_result_sha256=_sha(b_result_raw))
    mid_input = {"job_id": mid_parent_id, "target_date": "20261016", "cutoff": cutoff,
                 "capture_product": {"sha256": old_capture_sha}, "membership_gate": verified_gate,
                 "recovery_lock": mid_lock}
    failed_at = "2026-10-16T15:00:00+08:00"
    saved_stop = {"failure_code": "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT",
                  "stage": "FLASH_SELECTION", "queue_action": "SAVED_RESULTS_ONLY_NO_RETRY",
                  "failed_at": failed_at}
    safe_stop_counts = {"failed": 1, "new_candidate_stocks": 11,
                        "queue": {"new_enqueued": 0, "new_model_calls_allowed": 0}}
    mid_result = {"job_id": mid_parent_id, "target_trade_date": "20261016", "state": "PARTIAL",
                  "system_stop": saved_stop, "counts": safe_stop_counts,
                  "membership_gate": verified_gate}
    mid_input_raw, mid_result_raw = _json_bytes(mid_input), _json_bytes(mid_result)
    mid_dir = jobs_root / mid_parent_id
    mid_dir.mkdir()
    (mid_dir / "input.json").write_bytes(mid_input_raw)
    (mid_dir / "result.json").write_bytes(mid_result_raw)
    (mid_dir / "progress.json").write_bytes(_json_bytes({
        "step": "FAILED", "failure_code": "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT",
        "updated_at": failed_at}))

    d_lock.update(parent_input_sha256=_sha(mid_input_raw), parent_result_sha256=_sha(mid_result_raw))
    d_input = {"job_id": current_parent_id, "target_date": "20261016", "cutoff": cutoff,
               "capture_product": {"sha256": current_capture_sha}, "membership_gate": verified_gate,
               "recovery_lock": d_lock}
    d_result = {"job_id": current_parent_id, "target_trade_date": "20261016", "state": "PARTIAL",
                "system_stop": saved_stop, "counts": {**safe_stop_counts, "new_candidate_stocks": 0},
                "membership_gate": verified_gate}
    d_input_raw, d_result_raw = _json_bytes(d_input), _json_bytes(d_result)
    d_dir = jobs_root / current_parent_id
    d_dir.mkdir()
    (d_dir / "input.json").write_bytes(d_input_raw)
    (d_dir / "result.json").write_bytes(d_result_raw)
    (d_dir / "progress.json").write_bytes(_json_bytes({
        "step": "FAILED", "failure_code": "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT",
        "updated_at": failed_at}))
    current_lock.update(parent_input_sha256=_sha(d_input_raw), parent_result_sha256=_sha(d_result_raw))

    queue_root = tmp_path / "queue"
    queue = _PersistingAdmissionQueue(queue_root)
    failed = queue.enqueue(old_part)
    raw = _json_bytes({"action": "complete", "lookup_request": None,
                       "reader_output": {"facts": [], "changes": [{"claim": "rejected"}]}})
    raw_ref = f"jobs/{failed['idempotency_key']}/attempt-0001.raw"
    (queue_root / raw_ref).write_bytes(raw)
    failed.update({"status": "FAILED", "attempt_count": 1, "raw_path": raw_ref,
                   "raw_sha256": _sha(raw), "last_error": {"code": "PART_FIXED_FIELDS_MUST_BE_EMPTY",
                   "stage": "validator"},
                   "attempts": [{"status": "FAILED", "number": 1,
                                 "error": {"code": "PART_FIXED_FIELDS_MUST_BE_EMPTY", "stage": "validator"},
                                 "raw_path": raw_ref, "raw_sha256": _sha(raw)}]})
    old_repair, _old_binding = bridge._part_repair_payload(
        old_part, failed, queue_root, old_lock, gate, cutoff, 160_000)
    current_repair, _current_binding = bridge._part_repair_payload(
        current_part, failed, queue_root, current_lock, gate, cutoff, 160_000)
    assert old_repair is not None and current_repair is not None
    old_repair["prompt_tokens_exact"] = current_repair["prompt_tokens_exact"] = 51
    prior = queue.enqueue(old_repair)
    prior_raw = _json_bytes({"action": "complete", "lookup_request": None,
                             "reader_output": {"saved": "raw response"}})
    prior_validated = _json_bytes({"schema": chunks.PART_RESULT_SCHEMA, "saved": "validated"})
    prior_raw_path = f"jobs/{prior['idempotency_key']}/attempt-0001.raw"
    prior_validated_path = f"jobs/{prior['idempotency_key']}/validated.json"
    (queue_root / prior_raw_path).write_bytes(prior_raw)
    (queue_root / prior_validated_path).write_bytes(prior_validated)
    prior.update({"status": "SUCCEEDED", "attempt_count": 1,
                  "raw_path": prior_raw_path, "raw_sha256": _sha(prior_raw),
                  "validated_path": prior_validated_path, "validated_sha256": _sha(prior_validated),
                  "attempts": [{"status": "SUCCEEDED", "number": 1,
                                "raw_path": prior_raw_path, "raw_sha256": _sha(prior_raw),
                                "validated_path": prior_validated_path,
                                "validated_sha256": _sha(prior_validated)}]})
    return bridge, queue, queue_root, failed, prior, old_repair, current_part, current_repair, current_lock, gate, cutoff, state_root


def test_part_repair_capture_provenance_drift_reuses_only_verified_ancestor_success(tmp_path):
    (bridge, queue, queue_root, failed, prior, stored, current_part, current, lock, gate,
     cutoff, state_root) = _part_repair_capture_provenance_reuse_fixture(tmp_path)

    assert not bridge._internal_payload_matches(stored, current)
    assert bridge._part_repair_payload_matches_capture_provenance_drift(
        stored, current, recovery_lock=lock, membership_gate=gate,
        resume_cutoff=cutoff, state_root=state_root)
    before = {name: (queue_root / prior[name]).read_bytes()
              for name in ("input_path", "raw_path", "validated_path")}
    reused = bridge._reuse_succeeded_part_repair_after_capture_provenance_drift(
        current, queue, queue_root, recovery_lock=lock, membership_gate=gate,
        resume_cutoff=cutoff, hard_prompt_token_cap=160_000,
        count_prompt_tokens=lambda _messages: 51, state_root=state_root)
    assert reused == (prior["idempotency_key"], prior, False, False)
    assert prior["status"] == "SUCCEEDED" and prior["attempt_count"] == 1
    assert failed["status"] == "FAILED" and failed["attempt_count"] == 1
    assert all((queue_root / prior[name]).read_bytes() == raw for name, raw in before.items())

    enqueue_count = len(queue.enqueued)
    specs = {current_part["article_id"]: {"part_payloads": [current_part]}}
    allowed, records = bridge._enqueue_long_body_parts(
        specs, queue, queue_root, allow_same_batch_pending=True,
        recovery_lock=lock, membership_gate=gate, resume_cutoff=cutoff,
        prompt_token_cap=64_000, hard_prompt_token_cap=160_000,
        state_root=state_root, count_prompt_tokens=lambda _messages: 51,
    )
    assert allowed == set()
    assert records[0]["key"] == prior["idempotency_key"]
    assert records[0]["repair_status"] == "REPAIRED_SUCCESS_REUSED"
    assert len(queue.enqueued) == enqueue_count

    changed_body = json.loads(json.dumps(current))
    changed_body["article_body"] += "变更"
    assert bridge._reuse_succeeded_part_repair_after_capture_provenance_drift(
        changed_body, queue, queue_root, recovery_lock=lock, membership_gate=gate,
        resume_cutoff=cutoff, hard_prompt_token_cap=160_000,
        count_prompt_tokens=lambda _messages: 51, state_root=state_root) is None
    changed_model_input = json.loads(json.dumps(current))
    changed_model_input["messages"][1]["content"] += " changed"
    assert bridge._reuse_succeeded_part_repair_after_capture_provenance_drift(
        changed_model_input, queue, queue_root, recovery_lock=lock, membership_gate=gate,
        resume_cutoff=cutoff, hard_prompt_token_cap=160_000,
        count_prompt_tokens=lambda _messages: 51, state_root=state_root) is None
    wrong_lineage = {**lock, "parent_job_id": "e" * 32}
    assert bridge._reuse_succeeded_part_repair_after_capture_provenance_drift(
        current, queue, queue_root, recovery_lock=wrong_lineage, membership_gate=gate,
        resume_cutoff=cutoff, hard_prompt_token_cap=160_000,
        count_prompt_tokens=lambda _messages: 51, state_root=state_root) is None

    saved_parent_id = stored["part_repair_binding"]["parent_job_id"]
    saved_parent_input_path = (state_root / "announcement_flash" / "jobs" /
                               saved_parent_id / "input.json")
    saved_parent_input = json.loads(saved_parent_input_path.read_bytes())
    saved_parent_input["recovery_lock"]["parent_result_sha256"] = "f" * 64
    saved_parent_input_path.write_bytes(_json_bytes(saved_parent_input))
    assert not bridge._repair_parent_is_in_verified_lineage(
        state_root, lock, saved_parent_id, stored["part_repair_binding"]["capture_product_sha256"])


def test_part_repair_is_versioned_source_complete_and_leaves_validator_strict(tmp_path):
    bridge, queue, queue_root, payload, failed, lock, gate, cutoff, _current = _failed_part_fixture(tmp_path, 1)
    original_payload_sha = failed["payload_sha256"]
    original_raw_sha = failed["raw_sha256"]
    original_system = payload["messages"][0]["content"]
    original_schema = json.loads(json.dumps(payload["structured_output_schema"]))

    repair = bridge._part_repair_payload(payload, failed, queue_root, lock, gate, cutoff, 160_000)
    assert repair is not None
    repaired_payload, binding = repair

    assert repaired_payload["article_body"] == payload["article_body"]
    assert repaired_payload["fixed_fact_ledger"] == payload["fixed_fact_ledger"]
    assert repaired_payload["part_descriptor"] == payload["part_descriptor"]
    repaired_reader_schema = repaired_payload["structured_output_schema"]["properties"]["reader_output"]
    original_reader_schema = original_schema["properties"]["reader_output"]
    assert repaired_reader_schema["properties"]["facts"]["maxItems"] == 0
    assert repaired_reader_schema["properties"]["changes"]["maxItems"] == 0
    assert "maxItems" not in original_reader_schema["properties"]["facts"]
    assert "maxItems" not in original_reader_schema["properties"]["changes"]
    assert repaired_payload["messages"][0]["content"].startswith(original_system)
    assert "reader_output.facts、reader_output.changes 必须为 []" in repaired_payload["messages"][0]["content"]
    assert "fixed_fact_ledger.reader_changes" in repaired_payload["messages"][0]["content"]
    assert repaired_payload["prompt_sha256"] != payload["prompt_sha256"]
    assert repaired_payload["rules"].endswith("+repair-addendum:" + binding["feedback_addendum_sha256"])
    assert binding["failed_idempotency_key"] == failed["idempotency_key"]
    assert binding["failed_payload_sha256"] == original_payload_sha
    assert binding["failed_raw_response_sha256"] == original_raw_sha
    assert binding["nonempty_fixed_fields"] == ["changes"]
    assert binding["source_sha256"] == payload["source_sha256"]
    assert binding["membership_authority_sha256"] == gate["authority_sha256"]
    assert binding["part_target_token_cap"] == 64_000
    assert binding["repair_prompt_hard_cap_tokens"] == 160_000
    assert failed["status"] == "FAILED" and failed["attempt_count"] == 1
    assert _sha((queue_root / failed["input_path"]).read_bytes()) == original_payload_sha
    assert _sha((queue_root / failed["raw_path"]).read_bytes()) == original_raw_sha

    from v4.manager_workbench import announcement_chunks as chunks
    body = "甲乙"
    body_sha, unit_map = _chunk_unit_map(body, [1])
    with __import__("pytest").raises(ValueError, match="PART_FIXED_FIELDS_MUST_BE_EMPTY"):
        chunks.validate_part_envelope(
            {"action": "complete", "lookup_request": None,
             "reader_output": {"facts": [], "changes": [{"claim": "x"}]}},
            article_id="EASTMONEY:TEST", source_sha256="1" * 64,
            body_sha256=body_sha, plan_sha256="2" * 64,
            part={"part_index": 1, "part_count": 1, "source_unit_ids": ["U000001"]},
            unit_map=unit_map, body=body, validate_schema=lambda _output: None,
        )


def test_frozen_resume_admits_only_exact_legacy_failed_part_as_one_contract_canary(tmp_path):
    (bridge, queue, queue_root, current, source_job, legacy_job, legacy, specs,
     _lock, gate, cutoff) = _frozen_legacy_failed_canary_fixture(tmp_path, second_failed_part=True)
    source_payload_sha = source_job["payload_sha256"]
    legacy_payload_sha = legacy_job["payload_sha256"]
    legacy_raw_sha = legacy_job["raw_sha256"]

    allowed, records = bridge._enqueue_long_body_parts(
        specs, queue, queue_root, allow_same_batch_pending=True,
        recovery_lock=None, membership_gate=gate, resume_cutoff=cutoff,
        prompt_token_cap=64_000, hard_prompt_token_cap=160_000,
        allow_multiple_new_repairs=False, allow_new_repairs=True, allow_enqueue=True,
        resume_frozen_batch=True, resume_action="CANARY", legacy_failed_canary=legacy,
        source_job_id="b" * 32, source_input_sha256="f" * 64,
        count_prompt_tokens=lambda _messages: 51,
    )

    assert len(allowed) == 1
    assert len(records) == 2
    canary_record = next(record for record in records if record["part_index"] == 1)
    deferred_record = next(record for record in records if record["part_index"] == 2)
    canary_payload = next(payload for payload in queue.enqueued if payload.get("part_repair_binding"))
    assert canary_record["repair_status"] == "REPAIR_CANARY_ENQUEUED"
    assert canary_record["repair_source_key"] == legacy["key"]
    assert canary_record["repair_binding_sha256"] == canary_payload["part_repair_binding"]["binding_sha256"]
    assert canary_payload["part_repair_binding"]["failed_idempotency_key"] == legacy["key"]
    assert canary_payload["part_repair_binding"]["failed_payload_sha256"] == legacy_payload_sha
    assert canary_payload["part_repair_binding"]["failed_raw_response_sha256"] == legacy_raw_sha
    assert canary_payload["rules"].find("fixed-fields-contract:v2") >= 0
    assert deferred_record["repair_status"] == "LEGACY_CANARY_PART_DEFERRED"
    assert deferred_record["runnable"] is False
    assert source_job["status"] == "FAILED" and source_job["payload_sha256"] == source_payload_sha
    assert legacy_job["status"] == "FAILED" and legacy_job["attempt_count"] == 1
    assert len([payload for payload in queue.enqueued if payload.get("part_repair_binding")]) == 1


def test_frozen_resume_maps_exact_legacy_orphan_to_one_repair_target(tmp_path):
    (bridge, queue, queue_root, current, source_job, legacy_job, legacy, specs,
     _lock, gate, cutoff) = _frozen_legacy_orphan_canary_fixture(tmp_path)
    root_binding = specs[current["article_id"]]["frozen_resume_binding"]

    target = bridge._frozen_resume_legacy_canary_target(
        specs, legacy, queue, queue_root,
        root_job_id=root_binding["source_job_id"],
        root_input_sha256=root_binding["source_input_sha256"],
        membership_gate=gate, hard_prompt_token_cap=160_000,
        count_prompt_tokens=lambda _messages: 51,
    )
    assert target == {"article_id": current["article_id"], "part_index": 1,
                      "base_key": source_job["idempotency_key"],
                      "legacy_key": legacy_job["idempotency_key"]}

    before_enqueued = len(queue.enqueued)
    allowed, records = bridge._enqueue_long_body_parts(
        specs, queue, queue_root, allow_same_batch_pending=True,
        recovery_lock=None, membership_gate=gate, resume_cutoff=cutoff,
        prompt_token_cap=64_000, hard_prompt_token_cap=160_000,
        allow_multiple_new_repairs=False, allow_new_repairs=True, allow_enqueue=True,
        resume_frozen_batch=True, resume_action="CANARY", legacy_failed_canary=legacy,
        source_job_id="b" * 32, source_input_sha256="f" * 64,
        count_prompt_tokens=lambda _messages: 51,
    )
    assert len(allowed) == 1
    assert len(records) == 1
    assert records[0]["base_key"] == target["base_key"]
    assert records[0]["repair_source_key"] == target["legacy_key"]
    assert records[0]["repair_status"] == "REPAIR_CANARY_ENQUEUED"
    assert len(queue.enqueued) == before_enqueued + 1
    assert queue.enqueued[-1]["part_repair_binding"]["failed_idempotency_key"] == target["legacy_key"]


def test_frozen_resume_legacy_orphan_target_mismatch_fails_before_queue_admission(tmp_path):
    (bridge, queue, queue_root, current, _source_job, _legacy_job, legacy, specs,
     _lock, gate, _cutoff) = _frozen_legacy_orphan_canary_fixture(tmp_path)
    wrong_legacy = dict(legacy, source_part_key="e" * 64)
    before_enqueued = list(queue.enqueued)

    with __import__("pytest").raises(RuntimeError, match="FROZEN_RESUME_CANARY_TARGET_NOT_UNIQUE"):
        bridge._frozen_resume_legacy_canary_target(
            specs, wrong_legacy, queue, queue_root,
            root_job_id=specs[current["article_id"]]["frozen_resume_binding"]["source_job_id"],
            root_input_sha256=specs[current["article_id"]]["frozen_resume_binding"]["source_input_sha256"],
            membership_gate=gate, hard_prompt_token_cap=160_000,
            count_prompt_tokens=lambda _messages: 51,
        )

    assert queue.enqueued == before_enqueued


def _run_isolated_legacy_orphan_canary(tmp_path, monkeypatch, *, missing_target=False):
    import shutil
    from copy import deepcopy
    from v4.manager_workbench import announcement_chunks as chunks
    from v4.manager_workbench import announcement_membership

    (bridge, fixture_queue, fixture_queue_root, current, _source_job, _legacy_job, legacy,
     _specs, _lock, gate, cutoff) = _frozen_legacy_orphan_canary_fixture(
         tmp_path / "frozen", part_index=17, part_count=22)
    root_binding = {"source_job_id": legacy["root_job_id"],
                    "source_input_sha256": legacy["root_input_sha256"],
                    "target_date": "20261016", "cutoff": cutoff,
                    "capture_product_sha256": _lock["capture_product_sha256"],
                    "membership_authority_sha256": gate["authority_sha256"]}
    state_root = tmp_path / "state"
    run_queue_root = state_root / "announcement_flash" / "queue"
    run_queue_root.mkdir(parents=True)
    shutil.copytree(fixture_queue_root / "jobs", run_queue_root / "jobs")

    calls = {"enqueue": 0, "run_next": 0, "transport": 0, "run_keys": []}

    class ValidationRejected(ValueError):
        pass

    class DispatchQueue(_PersistingAdmissionQueue):
        def __init__(self):
            super().__init__(run_queue_root, jobs=deepcopy(fixture_queue.jobs))
            self.model_id = "qwen3_8_flash_next"

        def enqueue(self, payload):
            calls["enqueue"] += 1
            return super().enqueue(payload)

        def snapshot(self):
            return {"items": list(self.jobs.values())}

        def run_next(self, executor, validator, *, idempotency_keys, wait_for_model_slot):
            calls["run_next"] += 1
            ready = sorted(key for key in idempotency_keys
                           if self.jobs.get(key, {}).get("status") == "PENDING")
            if not ready:
                return None
            key = ready[0]
            job_data = self.jobs[key]
            payload = json.loads((self.root / job_data["input_path"]).read_text(encoding="utf-8"))
            job = SimpleNamespace(payload=payload, idempotency_key=key)
            raw_text = executor(job)
            calls["run_keys"].append(key)
            raw = raw_text.encode("utf-8")
            raw_path = f"jobs/{key}/attempt-0001.raw"
            path = self.root / raw_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            try:
                validated = validator(job, json.loads(raw_text))
            except ValidationRejected as exc:
                job_data.update({"status": "FAILED", "attempt_count": 1,
                                 "raw_path": raw_path, "raw_sha256": _sha(raw),
                                 "attempts": [{"status": "FAILED", "number": 1,
                                               "error": {"stage": "validator", "code": str(exc)},
                                               "raw_path": raw_path, "raw_sha256": _sha(raw),
                                               "raw_length_bytes": len(raw)}]})
                return {"idempotency_key": key, "status": "FAILED"}
            job_data.update({"status": "SUCCEEDED", "attempt_count": 1,
                             "raw_path": raw_path, "raw_sha256": _sha(raw),
                             "validated_sha256": _sha(_json_bytes(validated)),
                             "attempts": [{"status": "SUCCEEDED", "number": 1,
                                           "raw_path": raw_path, "raw_sha256": _sha(raw),
                                           "raw_length_bytes": len(raw)}]})
            return {"idempotency_key": key, "status": "SUCCEEDED"}

    queue = DispatchQueue()
    queue_module = ModuleType("announcement_queue")
    queue_module.ValidationRejected = ValidationRejected
    queue_module.SerialAnnouncementQueue = lambda *_args, **_kwargs: queue
    canary_module = ModuleType("automatic_canary_server")

    class FakeTransport:
        def __init__(self, *_args, **_kwargs):
            calls["transport"] += 1

        def begin_job(self, _job):
            return None

        def complete_batch(self, *_args, **_kwargs):
            response = {"action": "complete", "lookup_request": None,
                        "reader_output": {"facts": [], "changes": []}}
            return SimpleNamespace(final_text=json.dumps(response))

        def finish_job(self, **_kwargs):
            return None

        def close(self):
            return None

    canary_module.GatedStreamingTransport = FakeTransport
    runner = SimpleNamespace(
        MODEL_ID="qwen3_8_flash_next", SIMPLE_WORKFLOW_RANGE_PROFILE="profile-v1",
        SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL="citation-v1", OMLX_TOKENIZER_PATH="unused",
        load_active_contract=lambda: object(), load_local_api_key=lambda: "test-only",
        _simple_model_fixed_fact_ledger_for_article=lambda *_args: {},
    )
    length_canary = SimpleNamespace(
        make_batch=lambda articles, batch_id: {"articles": articles, "batch_id": batch_id})
    monkeypatch.setitem(sys.modules, "announcement_queue", queue_module)
    monkeypatch.setitem(sys.modules, "automatic_canary_server", canary_module)
    monkeypatch.setitem(sys.modules, "batch_runner", runner)
    monkeypatch.setitem(sys.modules, "build_length_canary", length_canary)

    request_material = {
        "workflow_profile": runner.SIMPLE_WORKFLOW_RANGE_PROFILE,
        "citation_protocol": "citation-v1", "sampling_policy": {"request_temperature": 0.0},
        "configuration_material": {"model_id": runner.MODEL_ID, "request_temperature": 0.0,
                                    "enable_thinking": False, "max_completion_tokens": 0},
        "runtime_limits": {"context_limit_tokens": 200_000}, "max_completion_tokens": 0,
        "prompt": "frozen reader prompt", "prompt_sha256": "1" * 64,
        "configuration_sha256": "2" * 64, "schema_sha256": "3" * 64,
        "runtime_settings_sha256": "4" * 64, "model_settings_sha256": "5" * 64,
        "schema": {"type": "object"},
    }
    helper = SimpleNamespace(
        _full_day_request_material=lambda _contract: request_material,
        _messages_for_article=lambda *_args, **_kwargs: [{"role": "user", "content": "article"}],
        _token_count=lambda _tokenizer, _messages: 17,
    )
    monkeypatch.setattr(bridge, "_load_helper", lambda: helper)
    monkeypatch.setattr(bridge, "_validator",
                        lambda *_args, **_kwargs: lambda _job, parsed: parsed)
    monkeypatch.setattr(bridge, "_verify_completed_part_repair_canary",
                        lambda *_args, **_kwargs: (True, None))
    monkeypatch.setattr(bridge, "_verify_resume_root_input", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bridge, "_needs_chunk_plan", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(bridge, "_pinned_candidate_history", lambda: [])
    monkeypatch.setattr(bridge, "_current_frozen_resume_payload_valid", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(announcement_membership, "revalidate_membership_gate", lambda *_args: dict(gate))
    monkeypatch.setattr(announcement_membership, "classify_capture_row",
                        lambda row, _gate: {"article_id": "EASTMONEY:" + row["art_code"],
                                            "membership_status": "IN", "symbol": "HK.09963"})
    monkeypatch.setattr(announcement_membership, "public_gate", lambda value: dict(value))
    monkeypatch.setattr(chunks, "verify_part_coverage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chunks, "project_part_ledger", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(chunks, "empty_reader_fixed_fields_schema", lambda _schema: {"type": "object"})
    monkeypatch.setattr(chunks, "reader_task_system_prompt", lambda _prompt, task: f"system-{task}")
    monkeypatch.setattr(bridge, "_part_messages", lambda *_args, **_kwargs: [
        {"role": "system", "content": "reader instructions"},
        {"role": "user", "content": "part"},
    ])

    article = {key: current[key] for key in (
        "article_id", "source_sha256", "body_sha256", "article_body", "article_metadata", "fixed_fact_ledger")}
    unit_map = {"units": [{"source_unit_id": "U000017", "start_cp": 0, "end_cp": 1,
                           "unit_sha256": "9" * 64, "text": "冻"}],
                "source_unit_map_sha256": current["source_unit_map_sha256"]}
    article["_source_unit_map"] = unit_map
    monkeypatch.setattr(bridge, "_article", lambda *_args, **_kwargs: deepcopy(article))
    tokenizer = SimpleNamespace(encode=lambda *_args, **_kwargs: [1])
    transformers = ModuleType("transformers")
    transformers.AutoTokenizer = SimpleNamespace(from_pretrained=lambda *_args, **_kwargs: tokenizer)
    monkeypatch.setitem(sys.modules, "transformers", transformers)

    descriptor = dict(current["part_descriptor"])
    plan = {
        "schema": chunks.PART_PLAN_SCHEMA, "article_id": current["article_id"],
        "source_sha256": current["source_sha256"], "body_sha256": current["body_sha256"],
        "source_unit_map_sha256": current["source_unit_map_sha256"],
        "fixed_fact_ledger_sha256": current["fixed_fact_ledger"]["ledger_sha256"],
        "plan_sha256": current["chunk_plan_sha256"], "prompt_sha256": current["prompt_sha256"],
        "part_addendum_sha256": chunks.PART_ADDENDUM_SHA256,
        "parts": [descriptor],
    }
    plan_dir = state_root / "announcement_flash" / "jobs" / root_binding["source_job_id"] / "long-body"
    plan_dir.mkdir(parents=True)
    plan_path = plan_dir / f"{current['article_id'].replace(':', '_')}-{plan['plan_sha256']}.json"
    plan_path.write_bytes(_json_bytes(plan))

    capture_product = {
        "schema_version": "mwb.capture.window.v1", "owner": "v4.manager_workbench.capture_announcements",
        "source": "EASTMONEY_HK", "saved_ref": None, "target_trade_date": "2026-10-16",
        "window": {"publication_dates": ["2026-10-15"]},
        "rows": [{"art_code": current["article_id"].split(":", 1)[1],
                  "title": current["article_metadata"]["title"], "body_complete": True,
                  "body_text": current["article_body"], "source_issuer_codes": [{"code": "HK.09963"}]}],
    }
    capture_raw = _json_bytes(capture_product)
    capture_sha = _sha(capture_raw)
    capture_ref = f"products/{capture_sha}.json"
    capture_root = tmp_path / "capture"
    capture_path = capture_root / capture_ref
    capture_path.parent.mkdir(parents=True)
    capture_path.write_bytes(capture_raw)
    root_binding["capture_product_sha256"] = capture_sha
    root_binding["membership_authority_sha256"] = gate["authority_sha256"]
    input_legacy = dict(legacy)
    if missing_target:
        input_legacy["source_part_key"] = "e" * 64
    resume_source = {"resume_action": "CANARY", "canary_passed": False,
                     "canary_status": "FAILED", "canary_key": legacy["key"],
                     "source_job_id": legacy["source_job_id"],
                     "source_input_sha256": legacy["source_input_sha256"],
                     "legacy_failed_canary": input_legacy}
    input_value = {
        "target_date": "20261016", "cutoff": cutoff, "membership_gate": gate,
        "capture_product": {"artifact_ref": capture_ref, "sha256": capture_sha},
        "resume_root": root_binding, "resume_source": resume_source,
    }
    if missing_target:
        input_value["resume_source"]["canary_key"] = input_legacy["key"]
    result = None
    error = None
    try:
        result = bridge._run(
            input_value, state_root=state_root, capture_root=capture_root,
            job_id="f" * 32, progress=lambda _event: None, shared_root=tmp_path / "shared",
            resume_frozen_batch=True, resume_action="CANARY", max_model_calls=1,
            resume_source_job_id=legacy["source_job_id"],
            resume_source_input_sha256=legacy["source_input_sha256"],
        )
    except Exception as exc:
        error = exc
    return {"bridge": bridge, "queue": queue, "calls": calls, "result": result,
            "error": error, "legacy": legacy, "input_value": input_value}


def test_run_frozen_resume_dispatches_only_exact_legacy_orphan_target(tmp_path, monkeypatch):
    outcome = _run_isolated_legacy_orphan_canary(tmp_path, monkeypatch)
    assert outcome["error"] is None, getattr(outcome["error"], "code", outcome["error"])
    result = outcome["result"]
    assert result["resume"]["model_calls"] == 1
    assert result["resume"]["canary_passed"] is True
    assert len(result["resume"]["dispatched_keys"]) == 1
    repair_key = result["resume"]["dispatched_keys"][0]
    repair = outcome["queue"].jobs[repair_key]
    repair_payload = json.loads((outcome["queue"].root / repair["input_path"]).read_text(encoding="utf-8"))
    assert repair_payload["part_repair_binding"]["failed_idempotency_key"] == outcome["legacy"]["key"]
    assert repair_payload["part_descriptor"]["part_index"] == 17
    assert repair_payload["part_descriptor"]["part_count"] == 22
    assert outcome["calls"]["run_keys"] == [repair_key]
    assert outcome["calls"]["enqueue"] == 1
    assert outcome["calls"]["run_next"] == 1
    assert outcome["calls"]["transport"] == 1


def test_run_frozen_resume_missing_legacy_target_fails_before_queue_dispatch(tmp_path, monkeypatch):
    outcome = _run_isolated_legacy_orphan_canary(tmp_path, monkeypatch, missing_target=True)
    assert outcome["result"] is None
    assert getattr(outcome["error"], "code", None) == "FROZEN_RESUME_CANARY_TARGET_NOT_UNIQUE"
    assert outcome["calls"]["enqueue"] == 0
    assert outcome["calls"]["run_next"] == 0
    assert outcome["calls"]["transport"] == 0
    assert outcome["calls"]["run_keys"] == []


def test_frozen_continue_reuses_saved_contract_canary_without_recomputing_same_part(tmp_path):
    (bridge, queue, queue_root, current, source_job, legacy_job, _legacy, specs,
     _lock, gate, cutoff) = _frozen_legacy_failed_canary_fixture(tmp_path)
    root_binding = specs[current["article_id"]]["frozen_resume_binding"]
    canary = bridge._part_repair_payload(
        current, legacy_job, queue_root, None, gate, cutoff, 160_000,
        frozen_resume_binding=root_binding)
    assert canary is not None
    canary_payload, canary_binding = canary
    canary_payload["prompt_tokens_exact"] = 51
    saved_canary = queue.enqueue(canary_payload)
    saved_canary["status"] = "SUCCEEDED"
    saved_canary["attempt_count"] = 1
    before = len(queue.enqueued)

    allowed, records = bridge._enqueue_long_body_parts(
        specs, queue, queue_root, allow_same_batch_pending=True,
        recovery_lock=None, membership_gate=gate, resume_cutoff=cutoff,
        prompt_token_cap=64_000, hard_prompt_token_cap=160_000,
        allow_multiple_new_repairs=True, allow_new_repairs=True, allow_enqueue=True,
        resume_frozen_batch=True, resume_action="CONTINUE", saved_canary_key=saved_canary["idempotency_key"],
        source_job_id="c" * 32, source_input_sha256="d" * 64,
        count_prompt_tokens=lambda _messages: 51,
    )

    assert allowed == set()
    assert len(records) == 1
    assert records[0]["key"] == saved_canary["idempotency_key"]
    assert records[0]["repair_source_key"] == legacy_job["idempotency_key"]
    assert records[0]["repair_status"] == "REPAIR_CANARY_VERIFIED_REUSED"
    assert records[0]["runnable"] is False
    assert source_job["status"] == "FAILED"
    assert legacy_job["status"] == "FAILED" and legacy_job["attempt_count"] == 1
    assert saved_canary["status"] == "SUCCEEDED" and saved_canary["attempt_count"] == 1
    assert canary_binding["failed_idempotency_key"] == legacy_job["idempotency_key"]
    assert len(queue.enqueued) == before


def test_saved_frozen_canary_revalidation_rebinds_legacy_failure_to_exact_plan(monkeypatch, tmp_path):
    (bridge, queue, queue_root, current, _source_job, legacy_job, _legacy, specs,
     _lock, gate, cutoff) = _frozen_legacy_failed_canary_fixture(tmp_path)
    root_binding = specs[current["article_id"]]["frozen_resume_binding"]
    repair = bridge._part_repair_payload(
        current, legacy_job, queue_root, None, gate, cutoff, 160_000,
        frozen_resume_binding=root_binding)
    assert repair is not None
    repair_payload, repair_binding = repair
    repair_payload["prompt_tokens_exact"] = 51
    saved_canary = queue.enqueue(repair_payload)
    saved_canary.update({"status": "SUCCEEDED", "attempt_count": 1,
                         "validated_sha256": "7" * 64, "raw_sha256": "8" * 64})
    recorded = []
    monkeypatch.setattr(bridge, "_verify_completed_part_repair_canary",
                        lambda _spec, record, *_args, **_kwargs: (recorded.append(record) or True, None))
    receipt = {"status": "PASS", "key": saved_canary["idempotency_key"],
               "binding_sha256": repair_binding["binding_sha256"],
               "validated_sha256": saved_canary["validated_sha256"],
               "raw_sha256": saved_canary["raw_sha256"]}
    resume_source = {"resume_action": "CONTINUE", "canary_passed": True,
                     "canary_status": "SUCCEEDED", "canary_model_calls": 1,
                     "canary_key": saved_canary["idempotency_key"], "canary_validation": receipt}

    ok, failure = bridge._verify_saved_frozen_resume_canary(
        specs, resume_source, queue, queue_root,
        prompt_token_cap=64_000, hard_prompt_token_cap=160_000,
        membership_gate=gate, count_prompt_tokens=lambda _messages: 51,
        runner=None, contract=None, state_root=tmp_path, request_material={},
    )

    assert (ok, failure) == (True, None)
    assert len(recorded) == 1
    assert recorded[0]["base_key"] == _source_job["idempotency_key"]
    assert recorded[0]["repair_source_key"] == legacy_job["idempotency_key"]
    assert recorded[0]["repair_binding_sha256"] == repair_binding["binding_sha256"]


def test_canary_reconstruction_uses_current_bound_part_when_failed_base_has_prior_capture_ref(tmp_path):
    bridge, queue, queue_root, current_part, failed, lock, gate, cutoff, _current = _failed_part_fixture(tmp_path, 1)
    stored_base = bridge._queue_payload(queue_root, failed)
    old_capture_sha = "0" * 64
    stored_base["article_metadata"]["source_origins"][0]["source_product_sha256"] = old_capture_sha
    stored_base["article_metadata"]["source_origins"][0]["source_ref"] = (
        f"products/{old_capture_sha}.json#/rows/0")
    base_raw = _json_bytes(stored_base)
    (queue_root / failed["input_path"]).write_bytes(base_raw)
    failed["payload_sha256"] = _sha(base_raw)

    assert bridge._internal_payload_matches(stored_base, current_part)
    assert bridge._part_repair_payload(
        stored_base, failed, queue_root, lock, gate, cutoff, 160_000) is None
    repair = bridge._part_repair_payload(
        current_part, failed, queue_root, lock, gate, cutoff, 160_000)

    assert repair is not None
    repair_payload, binding = repair
    assert binding["failed_idempotency_key"] == failed["idempotency_key"]
    assert binding["failed_payload_sha256"] == _sha(base_raw)
    assert binding["capture_product_sha256"] == lock["capture_product_sha256"]
    assert repair_payload["article_metadata"]["source_origins"][0]["source_product_sha256"] == \
        lock["capture_product_sha256"]


def test_part_repair_canary_success_auto_continues_remaining_parts_in_same_run(tmp_path, monkeypatch):
    bridge, queue, queue_root, part1, _job1, lock, gate, cutoff, current = _failed_part_fixture(tmp_path, 1)
    shared = (bridge, queue, queue_root, current, lock, gate, cutoff)
    _bridge, _queue, _root, part2, _job2, _lock, _gate, _cutoff, _current = _failed_part_fixture(
        tmp_path, 2, shared=shared)
    _bridge, _queue, _root, part3, _job3, _lock, _gate, _cutoff, _current = _failed_part_fixture(
        tmp_path, 3, status="SUCCEEDED", shared=shared)

    specs = {part1["article_id"]: {"part_payloads": [part1, part2, part3]}}
    token_count = lambda _messages: 64_001
    allowed, records = bridge._enqueue_long_body_parts(
        specs, queue, queue_root, allow_same_batch_pending=True,
        recovery_lock=lock, membership_gate=gate, resume_cutoff=cutoff,
        prompt_token_cap=64_000, hard_prompt_token_cap=160_000,
        count_prompt_tokens=token_count,
    )
    first_repair_key = specs[part1["article_id"]]["part_keys"][0]
    assert allowed == {first_repair_key}
    assert records[0]["repair_status"] == "REPAIR_CANARY_ENQUEUED"
    assert records[1]["repair_status"] == "GATED_AFTER_ONE_NEW_REPAIR"
    assert records[2]["repair_status"] == "NOT_REQUIRED"
    assert queue.jobs[records[0]["base_key"]]["status"] == "FAILED"
    assert queue.jobs[records[1]["base_key"]]["status"] == "FAILED"
    assert queue.jobs[records[2]["base_key"]]["status"] == "SUCCEEDED"
    assert len([item for item in queue.enqueued if item.get("part_repair_binding")]) == 1
    repair_payload = next(item for item in queue.enqueued if item.get("part_repair_binding"))
    assert repair_payload["prompt_tokens_exact"] == 64_001
    assert repair_payload["prompt_token_cap"] == 64_000
    assert repair_payload["repair_prompt_hard_cap_tokens"] == 160_000
    from v4.manager_workbench import announcement_chunks as chunks
    assert bridge._part_prompt_token_preflight_valid(repair_payload, chunks)
    too_large = json.loads(json.dumps(repair_payload))
    too_large["prompt_tokens_exact"] = 160_001
    assert not bridge._part_prompt_token_preflight_valid(too_large, chunks)
    unbound_cap = json.loads(json.dumps(repair_payload))
    unbound_cap["repair_prompt_hard_cap_tokens"] = 228_352
    assert not bridge._part_prompt_token_preflight_valid(unbound_cap, chunks)

    queue.jobs[first_repair_key]["status"] = "SUCCEEDED"
    queue.jobs[first_repair_key]["attempt_count"] = 1
    monkeypatch.setattr(bridge, "_verify_completed_part_repair_canary", lambda *_args, **_kwargs: (True, None))
    phase_b_calls = []

    def run_queue_keys(keys):
        phase_b_calls.append(set(keys))
        for key in keys:
            queue.jobs[key]["status"] = "SUCCEEDED"
            queue.jobs[key]["attempt_count"] = 1

    phase_b_allowed, phase_b_records, disposition = bridge._continue_long_body_repairs_after_canary(
        specs, records, queue, queue_root,
        allow_same_batch_pending=True, recovery_lock=lock, membership_gate=gate,
        resume_cutoff=cutoff, prompt_token_cap=64_000, hard_prompt_token_cap=160_000,
        count_prompt_tokens=token_count, runner=None, contract=None, request_material={},
        run_queue_keys=run_queue_keys, system_stopped=lambda: False,
    )
    second_repair_key = specs[part1["article_id"]]["part_keys"][1]
    assert phase_b_allowed == {second_repair_key}
    assert phase_b_calls == [{second_repair_key}]
    assert disposition["status"] == "AUTO_CONTINUATION_DISPATCHED"
    assert disposition["phase_b_repair_count"] == 1
    assert [record["repair_status"] for record in phase_b_records] == [
        "REPAIR_CANARY_VERIFIED", "REPAIR_AUTO_CONTINUATION_SUCCEEDED", "NOT_REQUIRED",
    ]
    assert [record["repair_status"] for record in specs[part1["article_id"]]["part_records"]] == [
        "REPAIR_CANARY_VERIFIED", "REPAIR_AUTO_CONTINUATION_SUCCEEDED", "NOT_REQUIRED",
    ]
    assert len([item for item in queue.enqueued if item.get("part_repair_binding")]) == 2


def test_part_repair_canary_failure_stops_continuation_and_repeat_adds_no_version(tmp_path, monkeypatch):
    bridge, queue, queue_root, part1, _job1, lock, gate, cutoff, current = _failed_part_fixture(tmp_path, 1)
    shared = (bridge, queue, queue_root, current, lock, gate, cutoff)
    _bridge, _queue, _root, part2, _job2, _lock, _gate, _cutoff, _current = _failed_part_fixture(
        tmp_path, 2, shared=shared)
    specs = {part1["article_id"]: {"part_payloads": [part1, part2]}}
    token_count = lambda _messages: 64_001
    phase_a_allowed, phase_a_records = bridge._enqueue_long_body_parts(
        specs, queue, queue_root, allow_same_batch_pending=True,
        recovery_lock=lock, membership_gate=gate, resume_cutoff=cutoff,
        prompt_token_cap=64_000, hard_prompt_token_cap=160_000,
        count_prompt_tokens=token_count,
    )
    canary_key = next(iter(phase_a_allowed))
    queue.jobs[canary_key]["status"] = "FAILED"
    queue.jobs[canary_key]["attempt_count"] = 1
    monkeypatch.setattr(bridge, "_verify_completed_part_repair_canary",
                        lambda *_args, **_kwargs: (False, "PART_FIXED_FIELDS_MUST_BE_EMPTY"))
    phase_b_calls = []
    args = dict(allow_same_batch_pending=True, recovery_lock=lock, membership_gate=gate,
                resume_cutoff=cutoff, prompt_token_cap=64_000, hard_prompt_token_cap=160_000,
                count_prompt_tokens=token_count, runner=None, contract=None, request_material={},
                run_queue_keys=lambda keys: phase_b_calls.append(set(keys)),
                system_stopped=lambda: False)

    phase_b_allowed, phase_b_records, disposition = bridge._continue_long_body_repairs_after_canary(
        specs, phase_a_records, queue, queue_root, **args,
    )
    assert phase_b_allowed == set() and phase_b_records == []
    assert phase_b_calls == []
    assert disposition["status"] == "REPAIR_CANARY_FAILED_STOP"
    assert phase_a_records[0]["repair_status"] == "REPAIR_CANARY_FAILED_STOP"
    assert len([item for item in queue.enqueued if item.get("part_repair_binding")]) == 1

    # A subsequent invocation sees the failed repair version as terminal and does not create another.
    next_allowed, next_records = bridge._enqueue_long_body_parts(
        specs, queue, queue_root, allow_same_batch_pending=True,
        recovery_lock=lock, membership_gate=gate, resume_cutoff=cutoff,
        prompt_token_cap=64_000, hard_prompt_token_cap=160_000,
        count_prompt_tokens=token_count,
    )
    assert next_allowed == set()
    assert next_records[0]["repair_status"] == "REPAIR_FAILED_TERMINAL"
    assert next_records[1]["repair_status"] == "GATED_AFTER_ONE_NEW_REPAIR"
    assert len([item for item in queue.enqueued if item.get("part_repair_binding")]) == 1


def test_part_repair_above_true_hard_cap_stays_context_pending(tmp_path):
    bridge, queue, queue_root, part1, _job1, lock, gate, cutoff, current = _failed_part_fixture(tmp_path, 1)
    shared = (bridge, queue, queue_root, current, lock, gate, cutoff)
    _bridge, _queue, _root, part2, _job2, _lock, _gate, _cutoff, _current = _failed_part_fixture(
        tmp_path, 2, shared=shared)
    specs = {part1["article_id"]: {"part_payloads": [part1, part2]}}
    allowed, records = bridge._enqueue_long_body_parts(
        specs, queue, queue_root, allow_same_batch_pending=True,
        recovery_lock=lock, membership_gate=gate, resume_cutoff=cutoff,
        prompt_token_cap=64_000, hard_prompt_token_cap=160_000,
        count_prompt_tokens=lambda _messages: 160_001,
    )
    assert allowed == set()
    assert [record["repair_status"] for record in records] == [
        "REPAIR_CONTEXT_PENDING", "REPAIR_CONTEXT_PENDING",
    ]
    assert not [item for item in queue.enqueued if item.get("part_repair_binding")]


def test_long_body_part_plan_is_exact_lossless_and_local_ledger_only():
    from v4.manager_workbench import announcement_chunks as chunks

    body = "甲乙丙丁戊己庚辛壬癸"
    body_sha, unit_map = _chunk_unit_map(body, [2, 4, 6, 8])
    source_sha = "1" * 64
    ledger = {"protocol": "fixed-ledger-v1", "body_sha256": body_sha,
              "source_unit_map_sha256": unit_map["source_unit_map_sha256"], "ledger_sha256": "2" * 64,
              "records": [
                  {"record_id": "local-1", "source_refs": [{"source_unit_id": "U000001"}]},
                  {"record_id": "cross", "source_refs": [{"source_unit_id": "U000002"},
                                                            {"source_unit_id": "U000003"}]},
              ], "daily_trade_rows": [], "calculations": [], "reader_facts": [], "reader_changes": []}

    def render(units, part_index, part_count):
        return len("".join(unit["text"] for unit in units)) + 5

    plan = chunks.plan_parts(
        article_id="EASTMONEY:TEST", source_sha256=source_sha, body=body, body_sha256=body_sha,
        unit_map=unit_map, fixed_fact_ledger=ledger, prompt_sha256="3" * 64,
        synthesis_prompt_sha256="4" * 64, configuration_sha256="5" * 64,
        batch_binding_sha256="6" * 64, token_cap=9, render_tokens=render,
        token_counter=len, model_ledger=lambda value: value,
    )
    chunks.verify_part_coverage(body, body_sha, unit_map, plan)
    assert b"".join(body[part["start_cp"]:part["end_cp"]].encode() for part in plan["parts"]) == body.encode()
    assert all(part["prompt_tokens_exact"] <= 9 for part in plan["parts"])
    part = plan["parts"][0]
    local = chunks.project_part_ledger(ledger, part["source_unit_ids"], lambda value: value)
    assert [item["record_id"] for item in local["records"]] == ["local-1"]
    cross = chunks.cross_part_ledger(ledger, unit_map, plan)
    assert [item["record_id"] for item in cross["records"]] == ["cross"]
    assert cross["records"][0]["source_unit_quotes"]


def test_synthesis_prompt_keeps_original_reader_rules_and_forbids_part_voting(monkeypatch):
    bridge = _bridge_module()
    monkeypatch.syspath_prepend(str(bridge.PIPELINE_ROOT))
    runner = importlib.import_module("batch_runner")
    from v4.manager_workbench import announcement_chunks as chunks

    helper = bridge._load_helper()
    original_prompt = helper._full_day_request_material(runner.load_active_contract())["prompt"]
    prompt = chunks.reader_task_system_prompt(original_prompt, "synthesis") + "\n\n" + chunks.SYNTHESIS_ADDENDUM
    expected_full_rules = original_prompt.replace(
        chunks.ORIGINAL_READER_PREAMBLE, chunks.SYNTHESIS_READER_PREAMBLE, 1).replace(
            "先通读完整正文，再结合账本核对固定事实",
            "先按序综合全部分片报告及其精确引证，再结合跨分片账本核对固定事实", 1).replace(
                "- wire JSON 中 facts 必须输出空数组；程序会在保存原始模型响应后，从冻结账本生成 facts 字段及其精确引文。"
                "你负责经营/业绩判断及理由、风险、影响、条件、反面证据，并在 changes 中填写正文披露且符合既有标准的经营/业绩变化。"
                "每条 changes claim 必须完整原子化，其全部细节由所引用的连续正文范围支持；使用 start_source_unit_id/end_source_unit_id 标记端点。"
                "程序只投影范围、生成 quote/locator，不会从固定账本生成、删除、替换或改写 changes；其余模型判断字段保持原样。",
                "- 本次分片/综合 Reader wire JSON 中 facts 和 changes 均必须输出空数组 []。"
                "程序会从冻结 fixed_fact_ledger.reader_facts 和 fixed_fact_ledger.reader_changes 确定性注入最终 facts/changes；"
                "不要将账本字段复制到 wire JSON，也不要改写账本。你仍负责原有经营/业绩判断及理由、风险、影响、条件、反面证据，"
                "并按原规则使用连续 source-unit 范围端点引证；其余模型判断字段保持原样。", 1).replace(
                    "facts 必须为 []，由程序从冻结账本注入；changes 由模型依据完整正文填写，使用连续 source-unit 范围端点引证，"
                    "没有符合既有 Reader 标准的有据变化时留空。",
                    "facts 和 changes 必须均为 []，由程序从冻结 fixed_fact_ledger.reader_facts 和 "
                    "fixed_fact_ledger.reader_changes 确定性注入；分片及综合模型不得填写或改写这两个字段。", 1)
    assert prompt.startswith(expected_full_rules)
    assert runner.SIMPLE_WORKFLOW_RANGE_PROCESS_ADDENDUM in prompt
    assert chunks.SYNTHESIS_READER_PREAMBLE in prompt
    assert "SELECTED_EVENT 必须有正文直接支持的经营事件" in prompt
    assert "股份分母不能代替现金流分母" in prompt
    assert "只在确实影响判断时说明具体未披露事项" in prompt
    assert "不是投票、计数、加权或多数规则" in prompt
    assert "任何一个正面分片都不能自动使全文成为候选" in prompt
    assert "最终 disposition 和 direction 必须由综合模型按原标准判断" in prompt


def test_synthesis_token_overflow_is_not_enqueued_or_sent_to_transport(tmp_path):
    bridge = _bridge_module()
    pytest = __import__("pytest")

    class ForbiddenQueue:
        def _identity(self, _payload):
            raise AssertionError("over-cap synthesis must not reach queue identity")

        def _load_state(self):
            raise AssertionError("over-cap synthesis must not inspect or mutate queue state")

        def enqueue(self, _payload):
            raise AssertionError("over-cap synthesis must not be enqueued")

    result = bridge._admit_synthesis_if_within_budget(
        {"queue_task_kind": "announcement_reader_synthesis", "prompt_tokens_exact": 160_001,
         "prompt_token_cap": 160_000, "context_limit_tokens": 262_144,
         "completion_reserve_tokens": 32_768, "token_safety_margin": 1_024},
        160_001, 160_000,
        ForbiddenQueue(), tmp_path, allow_same_batch_pending=False,
    )
    assert result == (None, None, False, False)
    with pytest.raises(bridge.FlashRunError, match="SYNTHESIS_TOKEN_PREFLIGHT_INVALID"):
        bridge._admit_synthesis_if_within_budget(
            {"queue_task_kind": "announcement_reader_synthesis"}, 64_000, 160_000,
            ForbiddenQueue(), tmp_path, allow_same_batch_pending=False,
        )


def test_existing_standard_pending_input_is_preserved_while_new_long_input_is_chunked():
    bridge = _bridge_module()
    identity = {
        "date": "20261016", "market": "HK", "article_id": "EASTMONEY:AN202610151830480612",
        "source_sha256": "a" * 64, "body_sha256": "b" * 64,
        "prompt_sha256": "c" * 64, "model_id": "frozen-model",
        "configuration_sha256": "d" * 64, "rules": "recent_day_reader_v2+profile:frozen",
        "role": "announcement_reader", "stage": "v4_manager_announcement_flash_incremental",
    }
    key = _sha(_json_bytes(identity))
    queue = _AdmissionQueue({key: {"idempotency_key": key, "identity": identity,
                                   "status": "PENDING", "attempt_count": 0}})
    payload = {**identity, "article_body": "frozen existing input"}

    assert bridge._has_existing_semantic_queue_job(queue, payload)
    assert not bridge._needs_chunk_plan(137_637, part_target_tokens=64_000,
                                        hard_cap_tokens=160_000, existing_standard_job=True)
    assert bridge._needs_chunk_plan(137_637, part_target_tokens=64_000,
                                    hard_cap_tokens=160_000, existing_standard_job=False)
    assert bridge._needs_chunk_plan(375_132, part_target_tokens=64_000,
                                    hard_cap_tokens=160_000, existing_standard_job=True)


def test_positive_part_disposition_is_never_a_candidate_result():
    bridge = _bridge_module()
    assert not bridge._is_final_candidate_task("announcement_reader_part")
    assert bridge._is_final_candidate_task("announcement_reader_synthesis")
    assert bridge._is_final_candidate_task(None)


def test_synthesis_citation_allowlist_covers_only_validated_part_ranges():
    from v4.manager_workbench import announcement_chunks as chunks

    body = "甲乙丙丁"
    body_sha, unit_map = _chunk_unit_map(body, [1, 2, 3])
    article_id = "EASTMONEY:TEST"
    reports = []
    for index in range(1, 3):
        unit_id = f"U{index:06d}"
        reports.append({
            "part_index": index, "part_count": 2,
            "part_result_sha256": str(index) * 64, "part_raw_response_sha256": str(index + 2) * 64,
            "part_descriptor": {"part_index": index, "part_count": 2,
                                "source_unit_ids": [unit_id]},
            "citation_ranges": [{"start_source_unit_id": article_id + "::" + unit_id,
                                 "end_source_unit_id": article_id + "::" + unit_id}],
        })
    intervals = chunks.synthesis_intervals_from_reports(reports, article_id=article_id, unit_map=unit_map)
    assert intervals == [[0, 0], [1, 1]]
    invalid = [dict(reports[0]), dict(reports[1])]
    invalid[1] = {**invalid[1], "part_descriptor": {"part_index": 2, "part_count": 2,
                                                   "source_unit_ids": ["U000003"]}}
    with __import__("pytest").raises(ValueError, match="SYNTHESIS_PART_CITATION_RANGE_INVALID"):
        chunks.synthesis_intervals_from_reports(invalid, article_id=article_id, unit_map=unit_map)


def test_synthesis_bare_citation_normalization_requires_unique_exact_part_range():
    from v4.manager_workbench import announcement_chunks as chunks

    body = "甲乙"
    body_sha, unit_map = _chunk_unit_map(body, [1])
    article_id = "EASTMONEY:AN202610141830470198"
    report = {"part_index": 1, "part_count": 1,
              "part_result_sha256": "a" * 64, "part_raw_response_sha256": "b" * 64,
              "part_descriptor": {"part_index": 1, "part_count": 1,
                                  "source_unit_ids": ["U000001"]},
              "citation_ranges": [{"start_source_unit_id": article_id + "::U000001",
                                   "end_source_unit_id": article_id + "::U000001"}]}
    raw = {"action": "complete", "lookup_request": None,
           "reader_output": {"facts": [], "changes": [], "impact": [],
                             "confirmation_conditions": [],
                             "counter_evidence": [{"claim": "已验证", "start_source_unit_id": "U000001",
                                                   "end_source_unit_id": "U000001"}],
                             "source_sha256": "c" * 64, "body_sha256": body_sha}}
    raw_before = json.loads(json.dumps(raw))
    normalized, edits = chunks.normalize_synthesis_citation_ids(
        raw, article_id=article_id, unit_map=unit_map, part_reports=[report])
    assert raw == raw_before
    assert len(edits) == 1 and edits[0]["part_index"] == 1
    assert normalized["reader_output"]["counter_evidence"][0]["start_source_unit_id"] == (
        article_id + "::U000001")
    assert chunks.synthesis_intervals_from_reports([report], article_id=article_id,
                                                   unit_map=unit_map) == [[0, 0]]
    chunks.validate_synthesis_citations(
        normalized, article_id=article_id, unit_map=unit_map, allowed_intervals=[(0, 0)],
        source_sha256="c" * 64, body_sha256=body_sha, validate_schema=lambda _output: None)
    with __import__("pytest").raises(ValueError, match="SYNTHESIS_CITATION_ARTICLE_MISMATCH"):
        chunks.validate_synthesis_citations(
            raw, article_id=article_id, unit_map=unit_map, allowed_intervals=[(0, 0)],
            source_sha256="c" * 64, body_sha256=body_sha, validate_schema=lambda _output: None)

    unknown = json.loads(json.dumps(raw))
    unknown["reader_output"]["counter_evidence"][0]["start_source_unit_id"] = "U999999"
    with __import__("pytest").raises(ValueError, match="UNIQUE_SOURCE_REQUIRED"):
        chunks.normalize_synthesis_citation_ids(
            unknown, article_id=article_id, unit_map=unit_map, part_reports=[report])

    foreign = json.loads(json.dumps(raw))
    foreign_citation = foreign["reader_output"]["counter_evidence"][0]
    foreign_citation["start_source_unit_id"] = "OTHER:ARTICLE::U000001"
    with __import__("pytest").raises(ValueError, match="SYNTHESIS_CITATION_ARTICLE_MISMATCH"):
        chunks.normalize_synthesis_citation_ids(
            foreign, article_id=article_id, unit_map=unit_map, part_reports=[report])

    ambiguous_reports = [{**report, "part_count": 2,
                          "part_descriptor": {"part_index": 1, "part_count": 2,
                                              "source_unit_ids": ["U000001"]}},
                         {**report, "part_index": 2, "part_count": 2,
                          "part_descriptor": {"part_index": 2, "part_count": 2,
                                              "source_unit_ids": ["U000001"]}}]
    with __import__("pytest").raises(ValueError, match="UNIQUE_SOURCE_REQUIRED"):
        chunks.normalize_synthesis_citation_ids(
            raw, article_id=article_id, unit_map=unit_map, part_reports=ambiguous_reports)

    no_range = {**report, "citation_ranges": []}
    with __import__("pytest").raises(ValueError, match="UNIQUE_VALIDATED_RANGE_REQUIRED"):
        chunks.normalize_synthesis_citation_ids(
            raw, article_id=article_id, unit_map=unit_map, part_reports=[no_range])


def _synthesis_provenance_reuse_fixture(tmp_path):
    bridge = _bridge_module()
    from v4.manager_workbench import announcement_chunks as chunks

    article_id = "EASTMONEY:AN202610151830520340"
    authority = "a" * 64
    capture_sha = "b" * 64
    body_sha = "c" * 64
    source_sha = "d" * 64
    old_capture_sha = "e" * 64
    old_metadata = {
        "publication_date": "2026-10-15", "title": "冻结公告", "symbol": "HK.00001",
        "article_membership_status": "IN", "membership_authority_sha256": authority,
        "source_issuer_codes": [{"code": "HK.00001", "name": "样例"}],
        "source_issuer_membership": [{"code": "HK.00001", "membership_status": "IN",
                                       "market": "HK_CONNECT", "authority_sha256": authority}],
        "source_origins": [{"role": "CAPTURE_WINDOW_PRODUCT_ROW",
                             "source_product_sha256": old_capture_sha,
                             "source_ref": f"products/{old_capture_sha}.json#/rows/0"}],
    }
    current_metadata = json.loads(json.dumps(old_metadata))
    current_metadata["source_origins"][0] = {
        "role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_product_sha256": capture_sha,
        "source_ref": f"products/{capture_sha}.json#/rows/0",
    }
    def batch_for(metadata):
        products = {}
        for origin in metadata["source_origins"]:
            products[origin["source_product_sha256"]] = {
                "source_ref": origin["source_ref"].split("#", 1)[0],
                "sha256": origin["source_product_sha256"],
            }
        return {"schema": "v4.test.batch.v1", "batch_id": "frozen-batch", "expected_count": 1,
                "articles": [{"article_id": article_id, "source_sha256": source_sha,
                              "body_sha256": body_sha, "article_body": "完整冻结正文",
                              "article_metadata": metadata}],
                "source_products": sorted(products.values(),
                                           key=lambda item: (item["source_ref"], item["sha256"]))}
    report = {"part_index": 1, "part_count": 1, "part_result_sha256": "f" * 64,
              "part_raw_response_sha256": "0" * 64,
              "part_descriptor": {"part_index": 1, "part_count": 1,
                                  "part_sha256": "1" * 64, "source_unit_ids": ["U000001"]},
              "reader_report": {}, "citation_ranges": []}
    synthesis_input = {
        "schema": chunks.SYNTHESIS_INPUT_SCHEMA, "article_id": article_id,
        "source_sha256": source_sha, "body_sha256": body_sha,
        "source_unit_map_sha256": "2" * 64, "plan_sha256": "3" * 64,
        "batch_binding_sha256": "4" * 64,
        "frozen_recovery_manifest_sha256": "5" * 64, "root_batch_job_id": "6" * 32,
        "target_date": "20261016", "cutoff": "2026-10-16T14:57:00+08:00",
        "membership_authority_sha256": authority, "part_count": 1,
        "part_reports": [report], "cross_part_fixed_fact_ledger": {},
    }
    synthesis_input["synthesis_input_sha256"] = _sha(_json_bytes(synthesis_input))
    base_payload = {
        "article_id": article_id, "source_sha256": source_sha, "body_sha256": body_sha,
        "article_body": "完整冻结正文", "article_metadata": current_metadata,
        "fixed_fact_ledger": {"ledger_sha256": "7" * 64},
        "date": "2026-10-15", "market": "HK", "prompt_sha256": "8" * 64,
        "model_id": "frozen-model", "configuration_sha256": "9" * 64,
        "rules": "recent_day_reader_v2+long-body-synthesis:v1", "role": "announcement_reader_synthesis",
        "stage": "v4_manager_announcement_flash_long_body_synthesis_v1",
        "queue_task_kind": "announcement_reader_synthesis", "chunk_plan_sha256": "3" * 64,
        "synthesis_input_sha256": synthesis_input["synthesis_input_sha256"],
        "part_result_sha256s": ["f" * 64], "synthesis_input": synthesis_input,
        "allowed_source_intervals": [[0, 0]], "source_unit_map_sha256": "2" * 64,
        "validated_article_batch": batch_for(current_metadata),
        "structured_output_schema": {"type": "object"}, "workflow_profile": "profile-v2",
        "citation_protocol": "protocol-v2", "input_schema": chunks.SYNTHESIS_INPUT_SCHEMA,
        "prompt_tokens_exact": 119, "prompt_token_cap": 160_000,
        "context_limit_tokens": 262_144, "completion_reserve_tokens": 32_768,
        "token_safety_margin": 1_024, "batch_binding_sha256": "4" * 64,
    }
    current_payload = {**base_payload, "messages": bridge._synthesis_messages(
        system_prompt="frozen full system prompt", article_id=article_id,
        article_metadata=current_metadata, synthesis_input=synthesis_input,
        input_schema=chunks.SYNTHESIS_INPUT_SCHEMA)}
    stored_payload = {**base_payload, "article_metadata": old_metadata,
                      "prompt_tokens_exact": 100,
                      "prompt_token_cap": 64_000,
                      "validated_article_batch": batch_for(old_metadata),
                      "messages": bridge._synthesis_messages(
                          system_prompt="frozen full system prompt", article_id=article_id,
                          article_metadata=old_metadata, synthesis_input=synthesis_input,
                          input_schema=chunks.SYNTHESIS_INPUT_SCHEMA)}

    queue_root = tmp_path / "queue"
    queue = _PersistingAdmissionQueue(queue_root)
    item = queue.enqueue(stored_payload)
    key = item["idempotency_key"]
    raw_value = {"raw": "previously validated model envelope"}
    saved_value = {"validated": "same projected result"}
    job_dir = queue_root / "jobs" / key
    raw_path, validated_path = job_dir / "raw.json", job_dir / "validated.json"
    raw_path.write_bytes(_json_bytes(raw_value))
    validated_path.write_bytes(_json_bytes(saved_value))
    item.update({"status": "SUCCEEDED", "attempt_count": 1,
                 "raw_path": f"jobs/{key}/raw.json", "raw_sha256": _sha(_json_bytes(raw_value)),
                 "validated_path": f"jobs/{key}/validated.json",
                 "validated_sha256": _sha(_json_bytes(saved_value))})
    lock = {
        "schema": "v4.manager_workbench.announcement_flash_recovery_lock.v1",
        "target_date": "20261016", "cutoff": "2026-10-16T14:57:00+08:00",
        "row_manifest_sha256": "5" * 64, "root_batch_job_id": "6" * 32,
        "membership_authority_sha256": authority, "capture_product_sha256": capture_sha,
        "eligible_article_ids": [article_id], "current_body_sha256": {article_id: body_sha},
        "expected_body_sha256": {article_id: body_sha},
    }
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1",
            "status": "VERIFIED", "target_date": "20261016", "authority_sha256": authority,
            "codes": ["HK.00001"]}

    def count_prompt_tokens(messages):
        text = messages[1]["content"]
        return 119 if capture_sha in text else 100

    def validator(job, parsed):
        assert job.payload == current_payload
        assert parsed == raw_value
        return saved_value

    return bridge, queue, queue_root, key, item, stored_payload, current_payload, lock, gate, \
        count_prompt_tokens, validator


def test_synthesis_provenance_only_drift_reuses_and_revalidates_immutable_success(tmp_path):
    (bridge, queue, queue_root, key, item, stored, current, lock, gate,
     count_prompt_tokens, validator) = _synthesis_provenance_reuse_fixture(tmp_path)
    assert count_prompt_tokens(stored["messages"]) == 100
    assert count_prompt_tokens(current["messages"]) == 119
    input_bytes = (queue_root / item["input_path"]).read_bytes()
    raw_bytes = (queue_root / item["raw_path"]).read_bytes()
    validated_bytes = (queue_root / item["validated_path"]).read_bytes()

    assert not bridge._internal_payload_matches(stored, current)
    reused = bridge._reuse_succeeded_synthesis_after_provenance_drift(
        current, queue, queue_root, recovery_lock=lock, membership_gate=gate,
        count_prompt_tokens=count_prompt_tokens, validator=validator)

    assert reused == (key, item, False, False)
    assert item["status"] == "SUCCEEDED" and item["attempt_count"] == 1
    assert queue.enqueued == [stored]
    assert (queue_root / item["input_path"]).read_bytes() == input_bytes
    assert (queue_root / item["raw_path"]).read_bytes() == raw_bytes
    assert (queue_root / item["validated_path"]).read_bytes() == validated_bytes


def test_synthesis_provenance_reuse_rejects_any_other_payload_or_token_drift(tmp_path):
    (bridge, queue, queue_root, key, item, stored, current, lock, gate,
     count_prompt_tokens, validator) = _synthesis_provenance_reuse_fixture(tmp_path)
    current["article_body"] += "改动"
    assert bridge._reuse_succeeded_synthesis_after_provenance_drift(
        current, queue, queue_root, recovery_lock=lock, membership_gate=gate,
        count_prompt_tokens=count_prompt_tokens, validator=validator) is None


def _failed_synthesis_raw_recovery_fixture(tmp_path, *, raw_value=None):
    bridge = _bridge_module()
    bridge._load_helper()
    runner = importlib.import_module("batch_runner")
    from v4.manager_workbench import announcement_chunks as chunks

    article_id = "EASTMONEY:AN202610141830470198"
    body = "冻结完整公告正文"
    body_sha = _sha(body.encode())
    source_sha = "d" * 64
    unit_map = runner.build_source_unit_map(body, body_sha)
    unit_id = unit_map["units"][0]["source_unit_id"]
    authority, capture_sha, old_capture_sha = "a" * 64, "b" * 64, "c" * 64
    code = "HK.09963"
    current_metadata = {
        "publication_date": "2026-10-15", "title": "冻结公告", "symbol": code,
        "issuer_name": "样例公司", "article_membership_status": "IN",
        "membership_authority_sha256": authority,
        "source_issuer_codes": [{"code": code, "name": "样例公司"}],
        "source_issuer_membership": [{"code": code, "membership_status": "IN",
                                       "market": "HK_CONNECT", "authority_sha256": authority}],
        "source_origins": [{"role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_product_sha256": capture_sha,
                             "source_ref": f"products/{capture_sha}.json#/rows/0"}],
    }
    old_metadata = json.loads(json.dumps(current_metadata))
    old_metadata["source_origins"][0] = {
        "role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_product_sha256": old_capture_sha,
        "source_ref": f"products/{old_capture_sha}.json#/rows/0",
    }
    result_sha, raw_part_sha, plan_sha, batch_binding_sha = "1" * 64, "2" * 64, "3" * 64, "4" * 64
    report = {"part_index": 1, "part_count": 1, "part_result_sha256": result_sha,
              "part_raw_response_sha256": raw_part_sha,
              "part_descriptor": {"part_index": 1, "part_count": 1, "part_sha256": plan_sha,
                                  "source_unit_ids": [unit_id]},
              "reader_report": {},
              "citation_ranges": [{"start_source_unit_id": article_id + "::" + unit_id,
                                   "end_source_unit_id": article_id + "::" + unit_id}]}
    synthesis_input = {
        "schema": chunks.SYNTHESIS_INPUT_SCHEMA, "article_id": article_id,
        "source_sha256": source_sha, "body_sha256": body_sha,
        "source_unit_map_sha256": unit_map["source_unit_map_sha256"], "plan_sha256": plan_sha,
        "batch_binding_sha256": batch_binding_sha,
        "frozen_recovery_manifest_sha256": "5" * 64, "root_batch_job_id": "6" * 32,
        "target_date": "20261016", "cutoff": "2026-10-16T14:57:00+08:00",
        "membership_authority_sha256": authority, "part_count": 1,
        "part_reports": [report], "cross_part_fixed_fact_ledger": {},
    }
    synthesis_input["synthesis_input_sha256"] = _sha(chunks.canonical(synthesis_input))

    def batch_for(metadata):
        origin = metadata["source_origins"][0]
        return {"schema": "v4.test.batch.v1", "batch_id": "frozen-batch", "expected_count": 1,
                "articles": [{"article_id": article_id, "source_sha256": source_sha,
                              "body_sha256": body_sha, "article_body": body,
                              "article_metadata": metadata}],
                "source_products": [{"source_ref": origin["source_ref"].split("#", 1)[0],
                                     "sha256": origin["source_product_sha256"]}]}

    base_payload = {
        "article_id": article_id, "source_sha256": source_sha, "body_sha256": body_sha,
        "article_body": body, "article_metadata": current_metadata,
        "fixed_fact_ledger": {"ledger_sha256": "7" * 64},
        "date": "2026-10-15", "market": "HK", "prompt_sha256": "8" * 64,
        "model_id": "frozen-model", "configuration_sha256": "9" * 64,
        "rules": "recent_day_reader_v2+profile:profile-v2+citation:protocol-v2+unit-map:frozen",
        "role": "announcement_reader_synthesis", "stage": "v4_manager_announcement_flash_long_body_synthesis_v1",
        "queue_task_kind": "announcement_reader_synthesis", "chunk_plan_sha256": plan_sha,
        "synthesis_input_sha256": synthesis_input["synthesis_input_sha256"],
        "part_result_sha256s": [result_sha], "synthesis_input": synthesis_input,
        "allowed_source_intervals": [[0, 0]], "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
        "validated_article_batch": batch_for(current_metadata),
        "structured_output_schema": {"type": "object"}, "workflow_profile": "profile-v2",
        "citation_protocol": "protocol-v2", "input_schema": chunks.SYNTHESIS_INPUT_SCHEMA,
        "prompt_tokens_exact": 100, "prompt_token_cap": 160_000,
        "context_limit_tokens": 262_144, "completion_reserve_tokens": 32_768,
        "token_safety_margin": 1_024, "batch_binding_sha256": batch_binding_sha,
    }
    current = {**base_payload, "messages": bridge._synthesis_messages(
        system_prompt="frozen full system prompt", article_id=article_id,
        article_metadata=current_metadata, synthesis_input=synthesis_input,
        input_schema=chunks.SYNTHESIS_INPUT_SCHEMA)}
    stored = {**base_payload, "article_metadata": old_metadata,
              "validated_article_batch": batch_for(old_metadata),
              "messages": bridge._synthesis_messages(
                  system_prompt="frozen full system prompt", article_id=article_id,
                  article_metadata=old_metadata, synthesis_input=synthesis_input,
                  input_schema=chunks.SYNTHESIS_INPUT_SCHEMA)}
    if raw_value is None:
        raw_value = {"action": "complete", "lookup_request": None,
                     "reader_output": {"facts": [], "changes": [], "impact": [],
                                       "confirmation_conditions": [],
                                       "counter_evidence": [{"claim": "正文范围", "start_source_unit_id": unit_id,
                                                             "end_source_unit_id": unit_id}],
                                       "source_sha256": source_sha, "body_sha256": body_sha}}
    queue_root = tmp_path / "queue"
    queue = _PersistingAdmissionQueue(queue_root)
    item = queue.enqueue(stored)
    raw_path = queue_root / "jobs" / item["idempotency_key"] / "attempt-0001.raw"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_bytes = _json_bytes(raw_value)
    raw_path.write_bytes(raw_bytes)
    raw_ref = f"jobs/{item['idempotency_key']}/attempt-0001.raw"
    item.update({"status": "FAILED", "attempt_count": 1, "max_attempts": 1,
                 "raw_path": raw_ref, "raw_sha256": _sha(raw_bytes),
                 "validated_path": None, "validated_sha256": None,
                 "attempts": [{"number": 1, "status": "FAILED", "raw_path": raw_ref,
                               "raw_sha256": _sha(raw_bytes), "validated_path": None,
                               "validated_sha256": None,
                               "error": {"code": "SYNTHESIS_CITATION_ARTICLE_MISMATCH",
                                         "stage": "validator"}}]})
    lock = {"schema": "v4.manager_workbench.announcement_flash_recovery_lock.v1",
            "target_date": "20261016", "cutoff": "2026-10-16T14:57:00+08:00",
            "root_batch_job_id": "6" * 32, "row_manifest_sha256": "5" * 64,
            "membership_authority_sha256": authority, "capture_product_sha256": capture_sha,
            "eligible_article_ids": [article_id], "current_body_sha256": {article_id: body_sha},
            "expected_body_sha256": {article_id: body_sha}}
    gate = {"schema": "v4.manager_workbench.announcement_connect_membership.v1", "status": "VERIFIED",
            "target_date": "20261016", "authority_sha256": authority, "codes": [code]}

    def validate(job, parsed):
        assert job.payload == current
        assert parsed != raw_value
        assert parsed["reader_output"]["counter_evidence"][0]["start_source_unit_id"] == (
            article_id + "::" + unit_id)
        assert parsed["reader_output"]["counter_evidence"][0]["end_source_unit_id"] == (
            article_id + "::" + unit_id)
        intervals = chunks.synthesis_intervals_from_reports([report], article_id=article_id,
                                                            unit_map=unit_map)
        chunks.validate_synthesis_citations(
            parsed, article_id=article_id, unit_map=unit_map,
            allowed_intervals=[tuple(pair) for pair in intervals], source_sha256=source_sha,
            body_sha256=body_sha, validate_schema=lambda _output: None)
        return {"results": [{"article_id": article_id, "reader_output": {
            "disposition": "SELECTED_EVENT", "direction": "POSITIVE",
            "source_sha256": source_sha, "body_sha256": body_sha, "impact": []}}]}

    count_tokens = lambda _messages: 100
    return bridge, queue, queue_root, current, lock, gate, count_tokens, validate, item, raw_path


def test_failed_synthesis_saved_raw_recovery_is_read_only_and_hash_linked(tmp_path):
    (bridge, queue, queue_root, current, lock, gate, count_tokens, validator,
     item, raw_path) = _failed_synthesis_raw_recovery_fixture(tmp_path)
    original_item = json.loads(json.dumps(item))
    input_bytes = (queue_root / item["input_path"]).read_bytes()
    raw_bytes = raw_path.read_bytes()
    enqueue_count = len(queue.enqueued)
    recovered = bridge._recover_failed_synthesis_from_saved_raw(
        current, queue, queue_root, recovery_lock=lock, membership_gate=gate,
        count_prompt_tokens=count_tokens, validator=validator)

    assert recovered["status"] == "RECOVERED"
    assert recovered["key"] == item["idempotency_key"]
    assert recovered["trace"]["source_raw_sha256"] == _sha(raw_bytes)
    assert recovered["trace"]["normalized_envelope_sha256"]
    assert recovered["trace"]["derived_validated_result_sha256"] == _sha(
        __import__("v4.manager_workbench.announcement_chunks", fromlist=["canonical"]).canonical(
            recovered["result"]))
    assert recovered["trace"]["normalization_edits"]
    assert recovered["trace"]["model_calls"] == 0
    assert item == original_item and item["status"] == "FAILED" and item["attempt_count"] == 1
    assert item["attempts"] == original_item["attempts"]
    assert item["attempts"][0]["error"]["code"] == "SYNTHESIS_CITATION_ARTICLE_MISMATCH"
    assert (queue_root / item["input_path"]).read_bytes() == input_bytes
    assert raw_path.read_bytes() == raw_bytes
    assert len(queue.enqueued) == enqueue_count


def test_saved_raw_recovery_publication_binds_full_neutral_result_for_audit_without_candidate_status():
    bridge = _bridge_module()
    from v4.manager_workbench import announcement_chunks as chunks
    article_id = "EASTMONEY:AN202610141830470198"
    validated = {"results": [{"article_id": article_id, "reader_output": {
        "disposition": "NOT_SELECTED", "direction": "NEUTRAL",
        "source_sha256": "a" * 64, "body_sha256": "b" * 64,
    }}]}
    trace = {
        "status": "DERIVED_FROM_IMMUTABLE_FAILED_RAW",
        "failure_code": "SYNTHESIS_CITATION_ARTICLE_MISMATCH",
        "source_idempotency_key": "c" * 64,
        "source_payload_sha256": "d" * 64,
        "source_raw_path": "jobs/failed/attempt-0001.raw",
        "source_raw_sha256": "e" * 64,
        "normalized_envelope_sha256": "f" * 64,
        "normalization_edits_sha256": "1" * 64,
        "normalization_edits": [{"field": "counter_evidence", "citation_index": 0}],
        "derived_validated_result_sha256": _sha(chunks.canonical(validated)),
        "queue_status_preserved": "FAILED", "attempt_count_preserved": 1, "model_calls": 0,
    }

    publication, audit = bridge._saved_raw_recovery_publication(
        article_id, {"trace": trace, "result": validated})

    assert publication["publication_status"] == "VALIDATED_RESULT_INCLUDED_IN_RESULT_PAYLOAD"
    assert publication["validated_result"] == validated
    assert publication["validated_result_sha256"] == trace["derived_validated_result_sha256"]
    assert publication["queue_status_preserved"] == "FAILED"
    assert audit["status"] == "RECOVERED_NOT_SELECTED"
    assert audit["source"] == "SAVED_RAW_RECOVERY"
    assert audit["original_queue_status"] == "FAILED"
    assert audit["original_attempt_count"] == 1
    assert audit["direction"] == "NEUTRAL"


def test_ordinary_synthesis_validator_rejects_bare_citation_ids(tmp_path):
    bridge, _queue, _queue_root, current, _lock, _gate, _count_tokens, _validator, _item, raw_path = \
        _failed_synthesis_raw_recovery_fixture(tmp_path)
    bridge._load_helper()
    source_runner = importlib.import_module("batch_runner")
    queue_module = importlib.import_module("announcement_queue")

    class Runner:
        build_source_unit_map = staticmethod(source_runner.build_source_unit_map)
        _validate_json_schema = staticmethod(lambda _output, _schema: None)
        build_simple_reader_wire_schema = staticmethod(lambda _contract, _protocol: {"type": "object", "properties": {
            "facts": {"type": "array", "items": {"type": "object"}},
            "changes": {"type": "array", "items": {"type": "object"}}}})
        project_simple_workflow_output = staticmethod(
            lambda _parsed, _batch, _contract, **_kwargs: (
                {"results": [{"article_id": current["article_id"]}]}, {}))
        _validate_batch_output = staticmethod(
            lambda _raw_text, _batch, _contract: ({current["article_id"]: {}}, {}))

    validator = bridge._validator(
        queue_module, Runner, None, {"citation_protocol": "test-range-v1"}, None)
    raw_bytes = raw_path.read_bytes()
    raw_value = json.loads(raw_bytes)

    with __import__("pytest").raises(queue_module.ValidationRejected) as rejected:
        validator(SimpleNamespace(payload=current), raw_value)

    assert rejected.value.code == "SYNTHESIS_CITATION_ARTICLE_MISMATCH"
    assert raw_path.read_bytes() == raw_bytes


def test_failed_synthesis_saved_raw_recovery_fails_closed_on_ambiguous_or_untrusted_ids(tmp_path):
    bridge, queue, queue_root, current, lock, gate, count_tokens, validator, item, raw_path = \
        _failed_synthesis_raw_recovery_fixture(tmp_path / "ambiguous")
    duplicate = json.loads(json.dumps(item))
    duplicate["idempotency_key"] = "e" * 64
    duplicate["identity"] = {**duplicate["identity"], "source_sha256": "f" * 64}
    queue.jobs[duplicate["idempotency_key"]] = duplicate
    blocked = bridge._recover_failed_synthesis_from_saved_raw(
        current, queue, queue_root, recovery_lock=lock, membership_gate=gate,
        count_prompt_tokens=count_tokens, validator=validator)
    assert blocked["status"] == "BLOCKED"
    assert blocked["failure_code"] == "SAVED_SYNTHESIS_FAILURE_AMBIGUOUS"

    for name, raw_value, expected in (
            ("foreign", {"action": "complete", "lookup_request": None,
                          "reader_output": {"facts": [], "changes": [], "impact": [],
                                            "confirmation_conditions": [],
                                            "counter_evidence": [{"claim": "x",
                                                                  "start_source_unit_id": "OTHER::U000001",
                                                                  "end_source_unit_id": "OTHER::U000001"}],
                                            "source_sha256": current["source_sha256"],
                                            "body_sha256": current["body_sha256"]}},
             "SYNTHESIS_CITATION_ARTICLE_MISMATCH"),):
        (bridge, queue, queue_root, current, lock, gate, count_tokens, validator,
         item, raw_path) = _failed_synthesis_raw_recovery_fixture(tmp_path / name, raw_value=raw_value)
        before = raw_path.read_bytes()
        result = bridge._recover_failed_synthesis_from_saved_raw(
            current, queue, queue_root, recovery_lock=lock, membership_gate=gate,
            count_prompt_tokens=count_tokens, validator=validator)
        assert result["status"] == "BLOCKED"
        assert result["failure_code"] == expected
        assert raw_path.read_bytes() == before and item["status"] == "FAILED"

    for suffix, field, value in (
            ("prompt-cap", "prompt_token_cap", 63_000),
            ("context-cap", "context_limit_tokens", 159_000),
            ("model", "model_id", "different-model"),
            ("body", "article_body", "different-body")):
        (bridge, queue, queue_root, _key, _item, _stored, current, lock, gate,
         count_prompt_tokens, validator) = _synthesis_provenance_reuse_fixture(tmp_path / suffix)
        current[field] = value
        assert bridge._reuse_succeeded_synthesis_after_provenance_drift(
            current, queue, queue_root, recovery_lock=lock, membership_gate=gate,
            count_prompt_tokens=count_prompt_tokens, validator=validator) is None

    (bridge, queue, queue_root, key, item, stored, current, lock, gate,
     count_prompt_tokens, validator) = _synthesis_provenance_reuse_fixture(tmp_path / "token")
    current["prompt_tokens_exact"] += 2
    assert bridge._reuse_succeeded_synthesis_after_provenance_drift(
        current, queue, queue_root, recovery_lock=lock, membership_gate=gate,
        count_prompt_tokens=count_prompt_tokens, validator=validator) is None


def test_synthesis_admission_uses_frozen_160k_hard_cap_and_fails_closed_above_it(tmp_path):
    bridge = _bridge_module()
    from v4.manager_workbench import announcement_chunks as chunks

    payload = {"date": "2026-10-15", "market": "HK",
               "article_id": "EASTMONEY:AN202610151830520340", "source_sha256": "d" * 64,
               "body_sha256": "c" * 64, "prompt_sha256": "8" * 64,
               "model_id": "frozen-model", "configuration_sha256": "9" * 64,
               "rules": "frozen-synthesis", "role": "announcement_reader_synthesis",
               "stage": "v4_manager_announcement_flash_long_body_synthesis_v1",
               "prompt_tokens_exact": 81_804,
               "article_metadata": {"publication_date": "2026-10-15", "title": "冻结公告",
                                    "symbol": "HK.00001", "observed_at": "2026-10-15T10:00:00+08:00",
                                    "available_at": "2026-10-15T10:00:00+08:00", "pit_status": "CANNOT_CONFIRM",
                                    "pit_reason": "CANNOT_CONFIRM", "article_membership_status": "IN",
                                    "membership_authority_sha256": "a" * 64,
                                    "source_issuer_codes": [{"code": "HK.00001"}],
                                    "source_issuer_membership": [{"code": "HK.00001", "membership_status": "IN",
                                                                   "market": "HK_CONNECT",
                                                                   "authority_sha256": "a" * 64}]},
               "context_limit_tokens": 262_144, "completion_reserve_tokens": 32_768,
               "token_safety_margin": chunks.TOKEN_SAFETY_MARGIN,
               "prompt_token_cap": chunks.SYNTHESIS_TOKEN_CAP,
               "messages": [{"role": "system", "content": "system"},
                            {"role": "user", "content": "complete synthesis input"}]}
    queue_root = tmp_path / "queue"
    queue = _PersistingAdmissionQueue(queue_root)
    admitted = bridge._admit_synthesis_if_within_budget(
        payload, 81_804, chunks.SYNTHESIS_TOKEN_CAP, queue, queue_root,
        allow_same_batch_pending=False)
    assert admitted[0] is not None
    assert len(queue.enqueued) == 1

    over_cap_payload = {**payload, "article_id": "EASTMONEY:AN202610151830520341",
                        "prompt_tokens_exact": 160_001}
    pending = bridge._admit_synthesis_if_within_budget(
        over_cap_payload, 160_001, chunks.SYNTHESIS_TOKEN_CAP, queue, queue_root,
        allow_same_batch_pending=False)
    assert pending == (None, None, False, False)
    assert len(queue.enqueued) == 1

    with __import__("pytest").raises(bridge.FlashRunError, match="SYNTHESIS_TOKEN_PREFLIGHT_INVALID"):
        bridge._admit_synthesis_if_within_budget(
            {**payload, "prompt_token_cap": chunks.SYNTHESIS_TOKEN_CAP + 1},
            81_804, chunks.SYNTHESIS_TOKEN_CAP + 1, queue, queue_root,
            allow_same_batch_pending=False)


def _transport_recovery_runner_fixture(tmp_path):
    bridge = _bridge_module()
    cutoff = "2026-10-18T09:34:00+08:00"
    authority = "a" * 64
    articles = [
        ("AN202610161830609970", "失败文章正文", "1" * 64, "HK.09963"),
        ("AN202610161830609971", "待处理文章正文", "2" * 64, "HK.09964"),
    ]
    rows = []
    for article_id, body, source_sha, code in articles:
        body_sha = _sha(body.encode())
        rows.append({"art_code": article_id, "publication_date": "2026-10-16",
                     "source_sha256": source_sha, "body_text": body,
                     "body_text_sha256": body_sha, "body_artifact_ref": f"products/{source_sha}.json",
                     "body_complete": True})
    capture_product = {"schema_version": "mwb.capture.window.v1", "source": "EASTMONEY_HK",
                       "target_trade_date": "20261016", "rows": rows}
    capture_sha = _sha(_json_bytes(capture_product))
    source_id = "a" * 32
    source_input = {
        "schema": "v4.manager_workbench.announcement_flash_input.v1",
        "job_id": source_id, "target_date": "20261016", "cutoff": cutoff,
        "capture_product": {"artifact_ref": f"products/{capture_sha}.json", "sha256": capture_sha},
        "membership_gate": {
            "schema": "v4.manager_workbench.announcement_connect_membership.v1",
            "status": "VERIFIED", "market": "HK_CONNECT", "target_date": "20261016",
            "cutoff": cutoff, "authority_sha256": authority, "codes": ["HK.09963", "HK.09964"],
        },
    }
    queue_root = tmp_path / "queue"
    jobs = {}
    failed_key = None
    pending_key = None
    for index, (article_id, body, source_sha, code) in enumerate(articles):
        row = rows[index]
        body_sha = row["body_text_sha256"]
        metadata = {
            "publication_date": "2026-10-16", "available_at": "2026-10-16T10:00:00+08:00",
            "article_membership_status": "IN", "membership_authority_sha256": authority,
            "source_issuer_codes": [{"code": code}],
            "source_issuer_membership": [{"code": code, "membership_status": "IN",
                                          "market": "HK_CONNECT", "authority_sha256": authority}],
            "source_origins": [
                {"role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_product_sha256": capture_sha,
                 "source_ref": f"products/{capture_sha}.json#/rows/{index}",
                 "source_row_index": index, "row_fingerprint_sha256": "f" * 64},
                {"role": "VERIFIED_FULL_NOTICE_BODY_PRODUCT", "source_product_sha256": source_sha},
            ],
        }
        identity = {
            "date": "2026-10-16", "market": "HK", "article_id": "EASTMONEY:" + article_id,
            "source_sha256": source_sha, "body_sha256": body_sha, "prompt_sha256": "3" * 64,
            "model_id": "qwen3_8_flash_next", "configuration_sha256": "4" * 64,
            "rules": "frozen-rules", "role": "announcement_reader",
            "stage": "v4_manager_announcement_flash_incremental",
        }
        payload = {**identity, "article_body": body, "article_metadata": metadata}
        payload_raw = _json_bytes(payload)
        key = _sha(_json_bytes(identity))
        ref = f"jobs/{key}/input.json"
        path = queue_root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload_raw)
        status = "FAILED" if index == 0 else "PENDING"
        item = {
            "idempotency_key": key, "queue_id": "v4-manager-flash-incremental",
            "model_id": identity["model_id"], "status": status,
            "attempt_count": 1 if status == "FAILED" else 0, "max_attempts": 1,
            "identity": identity, "input_path": ref, "payload_sha256": _sha(payload_raw),
            "attempts": ([{"status": "FAILED", "number": 1,
                           "error": {"stage": "executor", "code": "TransportError"}}]
                         if status == "FAILED" else []),
        }
        jobs[key] = item
        if status == "FAILED":
            failed_key = key
        else:
            pending_key = key
    progress = {"step": "DONE", "result_state": "PARTIAL",
                "completed": 0, "total": 2, "queue_counts": None}
    result = {
        "schema": "v4.manager_workbench.announcement_flash_result.v1",
        "job_id": source_id, "target_trade_date": "20261016", "state": "PARTIAL",
        "system_stop": {"failure_code": "TransportError", "stage": "executor",
                        "attempt": 1, "queue_action": "STOPPED_NO_AUTOMATIC_RETRY"},
        "counts": {"queue": {"succeeded": 0, "failed": 1, "pending": 1}},
        "failures": [{"article_id": "EASTMONEY:" + articles[0][0],
                      "stage": "executor", "failure_code": "TransportError"}],
        "pending": [{"article_id": "EASTMONEY:" + articles[1][0],
                     "queue_reason": "STOPPED_AFTER_SYSTEM_FAILURE"}],
    }
    result_raw = _json_bytes(result)
    queue_value = {"jobs": jobs}
    hashes = {"source_input_sha256": _sha(_json_bytes(source_input)),
              "source_progress_sha256": _sha(_json_bytes(progress)),
              "source_queue_state_sha256": "5" * 64}
    return (bridge, source_id, source_input, progress, result, result_raw,
            queue_value, hashes, capture_product, queue_root, failed_key, pending_key)


def test_transport_recovery_plan_binds_one_failed_task_and_pending_only(tmp_path):
    (bridge, source_id, source_input, progress, result, result_raw, queue_value,
     hashes, capture_product, queue_root, failed_key, pending_key) = _transport_recovery_runner_fixture(tmp_path)

    plan = bridge._build_transport_recovery_plan(
        source_id, "20261016", source_input, progress, result, result_raw,
        queue_value, hashes, capture_product, queue_root)

    assert plan["failed_task"]["key"] == failed_key
    assert [item["key"] for item in plan["pending_tasks"]] == [pending_key]
    assert plan["queue_status_counts"] == {"SUCCEEDED": 0, "FAILED": 1, "PENDING": 1}
    assert plan["pending_manifest_sha256"] == _sha(_json_bytes(plan["pending_tasks"]))


def test_transport_recovery_plan_rejects_semantic_or_ambiguous_stop(tmp_path):
    (bridge, source_id, source_input, progress, result, result_raw, queue_value,
     hashes, capture_product, queue_root, _failed_key, _pending_key) = _transport_recovery_runner_fixture(tmp_path)
    result["system_stop"]["failure_code"] = "VALIDATOR_REJECTED"
    with __import__("pytest").raises(bridge.FlashRunError,
                                     match="FROZEN_RESUME_TRANSPORT_SYSTEM_STOP_NOT_EXACT"):
        bridge._build_transport_recovery_plan(
            source_id, "20261016", source_input, progress, result, result_raw,
            queue_value, hashes, capture_product, queue_root)


def test_transport_recovery_source_verification_recomputes_frozen_plan(tmp_path):
    (bridge, source_id, source_input, progress, result, result_raw, queue_value,
     _hashes, capture_product, fixture_queue_root, _failed_key, _pending_key) = \
        _transport_recovery_runner_fixture(tmp_path)
    state_root = tmp_path / "state"
    source_dir = state_root / "announcement_flash" / "jobs" / source_id
    source_dir.mkdir(parents=True)
    (source_dir / "input.json").write_bytes(_json_bytes(source_input))
    (source_dir / "progress.json").write_bytes(_json_bytes(progress))
    (source_dir / "result.json").write_bytes(result_raw)

    queue_root = state_root / "announcement_flash" / "queue"
    for key in queue_value["jobs"]:
        source = fixture_queue_root / "jobs" / key / "input.json"
        target = queue_root / "jobs" / key / "input.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    queue_state = {"schema": "v4.announcement-engine-queue/v1", "jobs": queue_value["jobs"]}
    queue_raw = _json_bytes(queue_state)
    (queue_root / "queue-state.json").write_bytes(queue_raw)

    capture_root = tmp_path / "capture"
    capture_ref = source_input["capture_product"]["artifact_ref"]
    capture_path = capture_root / capture_ref
    capture_path.parent.mkdir(parents=True)
    capture_raw = _json_bytes(capture_product)
    capture_path.write_bytes(capture_raw)
    hashes = {
        "source_input_sha256": _sha(_json_bytes(source_input)),
        "source_progress_sha256": _sha(_json_bytes(progress)),
        "source_queue_state_sha256": _sha(queue_raw),
    }
    plan = bridge._build_transport_recovery_plan(
        source_id, "20261016", source_input, progress, result, result_raw,
        queue_state, hashes, capture_product, queue_root)

    verified_input, verified_queue, verified_legacy = bridge._verify_resume_source(
        bridge.SafeRoot(state_root), capture_root, source_id, "20261016", hashes,
        expected_transport_recovery=plan)

    assert verified_input == source_input
    assert verified_queue == queue_state
    assert verified_legacy is None
    changed_plan = {**plan, "pending_manifest_sha256": "0" * 64}
    with __import__("pytest").raises(bridge.FlashRunError,
                                     match="FROZEN_RESUME_TRANSPORT_BINDING_CHANGED"):
        bridge._verify_resume_source(
            bridge.SafeRoot(state_root), capture_root, source_id, "20261016", hashes,
            expected_transport_recovery=changed_plan)


def _transport_canary_runtime_fixture(tmp_path, monkeypatch):
    from copy import deepcopy
    from v4.manager_workbench import announcement_chunks as chunks

    monkeypatch.setattr(chunks, "reader_task_system_prompt", lambda prompt, _task: prompt)
    bridge = _bridge_module()
    (_bridge, root_id, input_value, progress, result, _result_raw, _queue_value,
     _hashes, capture_product, _fixture_queue_root, _failed_key, _pending_key) = \
        _transport_recovery_runner_fixture(tmp_path / "seed")
    capture_product.update(owner="v4.manager_workbench.capture_announcements", saved_ref=None)
    capture_raw = bridge.canonical(capture_product)
    capture_sha = bridge.sha(capture_raw)
    input_value["capture_product"] = {
        "artifact_ref": f"products/{capture_sha}.json", "sha256": capture_sha,
    }
    state_root = tmp_path / "state"
    queue_root = state_root / "announcement_flash" / "queue"
    queue_root.mkdir(parents=True)
    capture_root = tmp_path / "capture"
    capture_path = capture_root / input_value["capture_product"]["artifact_ref"]
    capture_path.parent.mkdir(parents=True)
    capture_path.write_bytes(capture_raw)
    request_material = {
        "workflow_profile": "decision_simple_facts_unit_ranges_v2",
        "citation_protocol": "citation-v1",
        "sampling_policy": {"request_temperature": 0.0},
        "configuration_material": {"model_id": "qwen3_8_flash_next", "request_temperature": 0.0,
                                   "enable_thinking": False, "max_completion_tokens": 0},
        "runtime_limits": {"context_limit_tokens": 200000}, "max_completion_tokens": 0,
        "prompt": chunks.ORIGINAL_READER_PREAMBLE, "prompt_sha256": "3" * 64,
        "configuration_sha256": "4" * 64, "schema_sha256": "5" * 64,
        "runtime_settings_sha256": "6" * 64, "model_settings_sha256": "7" * 64,
        "schema": {"type": "object"},
    }
    payloads = {}
    for index, row in enumerate(capture_product["rows"]):
        code = input_value["membership_gate"]["codes"][index]
        metadata = {
            "publication_date": row["publication_date"],
            "available_at": "2026-10-16T10:00:00+08:00",
            "article_membership_status": "IN", "membership_authority_sha256": "a" * 64,
            "source_issuer_codes": [{"code": code}],
            "source_issuer_membership": [{"code": code, "membership_status": "IN",
                                           "market": "HK_CONNECT", "authority_sha256": "a" * 64}],
            "symbol": code, "title": "test",
            "source_origins": [
                {"role": "CAPTURE_WINDOW_PRODUCT_ROW", "source_product_sha256": capture_sha,
                 "source_ref": input_value["capture_product"]["artifact_ref"] + f"#/rows/{index}",
                 "source_row_index": index, "row_fingerprint_sha256": "f" * 64},
                {"role": "VERIFIED_FULL_NOTICE_BODY_PRODUCT", "source_product_sha256": row["source_sha256"]},
            ],
        }
        article = {
            "article_id": "EASTMONEY:" + row["art_code"],
            "source_sha256": row["source_sha256"], "body_sha256": row["body_text_sha256"],
            "article_body": row["body_text"], "article_metadata": metadata,
            "fixed_fact_ledger": {"ledger_sha256": "8" * 64},
        }
        unit_map = {"source_unit_map_sha256": "9" * 64, "units": []}
        rules = (f"recent_day_reader_v2+profile:{bridge.PROFILE}+citation:citation-v1"
                 f"+unit-map:{'9' * 64}+fixed-ledger:{'8' * 64}+schema:{'5' * 64}"
                 "+temperature:0.0+thinking:off")
        payloads[article["article_id"]] = {
            **article, "date": row["publication_date"], "market": "HK",
            "prompt_sha256": "3" * 64, "model_id": "qwen3_8_flash_next",
            "configuration_sha256": "4" * 64, "rules": rules,
            "role": "announcement_reader", "stage": "v4_manager_announcement_flash_incremental",
            "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
            "validated_article_batch": {"articles": [article],
                "batch_id": "V4_FLASH_" + bridge.sha(article["article_id"].encode())[:16]},
            "messages": [{"role": "user", "content": "reader"}],
            "structured_output_schema": {"type": "object"},
            "workflow_profile": bridge.PROFILE, "citation_protocol": "citation-v1",
            "prompt_tokens_exact": 17, "context_limit_tokens": 200000,
        }

    class Queue(_PersistingAdmissionQueue):
        def __init__(self):
            super().__init__(queue_root)
            self.dispatched = []
            self.model_id = "qwen3_8_flash_next"

        def snapshot(self):
            items = deepcopy(list(self.jobs.values()))
            for item in items:
                if item.get("validated_path"):
                    item["validated_path"] = str(self.root / item["validated_path"])
            return {"items": items}

        def run_next(self, _executor, _validator, *, idempotency_keys, wait_for_model_slot):
            keys = sorted(key for key in idempotency_keys if self.jobs[key]["status"] == "PENDING")
            if not keys:
                return None
            key = keys[0]
            item = self.jobs[key]
            payload = json.loads((self.root / item["input_path"]).read_bytes())
            output = {"results": [{"article_id": payload["article_id"], "reader_output": {
                "source_sha256": payload["source_sha256"],
                "body_sha256": payload["body_sha256"], "disposition": "UNKNOWN", "direction": "UNKNOWN",
            }}]}
            raw = bridge.canonical(output)
            validated_ref = f"jobs/{key}/attempt-0001.validated.json"
            raw_ref = f"jobs/{key}/attempt-0001.raw"
            (self.root / validated_ref).write_bytes(raw)
            (self.root / raw_ref).write_bytes(raw)
            item.update(status="SUCCEEDED", attempt_count=1, validated_path=validated_ref,
                        validated_sha256=bridge.sha(raw), raw_path=raw_ref, raw_sha256=bridge.sha(raw),
                        attempts=[{"status": "SUCCEEDED", "number": 1, "raw_path": raw_ref,
                                   "raw_sha256": bridge.sha(raw), "raw_length_bytes": len(raw),
                                   "validated_path": validated_ref, "validated_sha256": bridge.sha(raw)}])
            self.dispatched.append(key)
            return {"idempotency_key": key, "status": "SUCCEEDED"}

    queue = Queue()
    keys = []
    for index, payload in enumerate(payloads.values()):
        item = queue.enqueue(payload)
        keys.append(item["idempotency_key"])
        if index == 0:
            item.update(status="FAILED", attempt_count=1,
                        attempts=[{"status": "FAILED", "number": 1,
                                   "error": {"stage": "executor", "code": "TransportError"}}])
    older_success = deepcopy(next(iter(payloads.values())))
    older_success["source_sha256"] = "c" * 64
    older_success["rules"] += "+old"
    old_item = queue.enqueue(older_success)
    old_item.update(status="SUCCEEDED", attempt_count=1)
    semantic_failure = deepcopy(older_success)
    semantic_failure["article_id"] = "EASTMONEY:SEMANTIC"
    semantic_item = queue.enqueue(semantic_failure)
    semantic_item.update(status="FAILED", attempt_count=1,
                         attempts=[{"status": "FAILED", "number": 1,
                                    "error": {"stage": "validator", "code": "SEMANTIC_REJECTED"}}])

    plan_queue_state = {"jobs": queue.jobs}
    plan_hashes = {"source_input_sha256": bridge.sha(bridge.canonical(input_value)),
                   "source_progress_sha256": bridge.sha(bridge.canonical(progress)),
                   "source_queue_state_sha256": "5" * 64}
    plan = bridge._build_transport_recovery_plan(
        root_id, "20261016", input_value, progress, result, bridge.canonical(result),
        plan_queue_state, plan_hashes, capture_product, queue_root)
    source_dir = state_root / "announcement_flash" / "jobs" / root_id
    source_dir.mkdir(parents=True)
    for name, value in (("input", input_value), ("progress", progress), ("result", result)):
        (source_dir / f"{name}.json").write_bytes(bridge.canonical(value))

    queue_module = ModuleType("announcement_queue")
    queue_module.SerialAnnouncementQueue = lambda *_args, **_kwargs: queue
    monkeypatch.setitem(sys.modules, "announcement_queue", queue_module)
    transport_module = ModuleType("automatic_canary_server")
    transport_module.GatedStreamingTransport = lambda *_args, **_kwargs: SimpleNamespace(close=lambda: None)
    monkeypatch.setitem(sys.modules, "automatic_canary_server", transport_module)
    runner = SimpleNamespace(
        MODEL_ID="qwen3_8_flash_next", SIMPLE_WORKFLOW_RANGE_PROFILE=bridge.PROFILE,
        SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL="citation-v1", OMLX_TOKENIZER_PATH="unused",
        load_active_contract=lambda: None, load_local_api_key=lambda: "fake",
    )
    monkeypatch.setitem(sys.modules, "batch_runner", runner)
    monkeypatch.setitem(sys.modules, "build_length_canary", SimpleNamespace(
        make_batch=lambda articles, batch_id: {"articles": articles, "batch_id": batch_id}))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=lambda *_args, **_kwargs: None)))
    helper = SimpleNamespace(
        _full_day_request_material=lambda _contract: request_material,
        _messages_for_article=lambda *_args, **_kwargs: [{"role": "user", "content": "reader"}],
        _token_count=lambda _tokenizer, _messages: 17,
    )
    monkeypatch.setattr(bridge, "_load_helper", lambda: helper)
    monkeypatch.setattr(bridge, "_validator", lambda *_args: lambda _job, parsed: parsed)
    monkeypatch.setattr(bridge, "_transport_executor", lambda *_args: None)
    monkeypatch.setattr(bridge, "_pinned_candidate_history", lambda: [])
    monkeypatch.setattr(bridge, "_project_historical_matches", lambda matches, _sha: {
        "selected": [], "failures": [],
        "pending": [{"article_id": item["current_payload"]["article_id"], "queue_reason": "NOT_RUN"}
                    for item in matches if item["record"]["status"] == "PENDING"],
        "outcomes": [], "current_capture_bindings": {},
    })

    def article(row, *_args, **_kwargs):
        payload = payloads["EASTMONEY:" + row["art_code"]]
        value = {key: deepcopy(payload[key]) for key in (
            "article_id", "source_sha256", "body_sha256", "article_body", "article_metadata",
            "fixed_fact_ledger")}
        value["_source_unit_map"] = {"source_unit_map_sha256": "9" * 64, "units": []}
        return value

    monkeypatch.setattr(bridge, "_article", article)
    from v4.manager_workbench import announcement_membership as membership
    monkeypatch.setattr(membership, "revalidate_membership_gate", lambda *_args: deepcopy(input_value["membership_gate"]))
    monkeypatch.setattr(membership, "classify_capture_row", lambda row, _gate: {
        "article_id": "EASTMONEY:" + row["art_code"], "membership_status": "IN", "symbol": "HK.09963",
    })
    monkeypatch.setattr(membership, "filter_payloads", lambda values, _gate: (values, []))
    return bridge, input_value, request_material, plan, queue, state_root, capture_root, keys, deepcopy(queue.jobs)


def test_transport_canary_rejects_current_configuration_drift_before_enqueue(tmp_path, monkeypatch):
    (bridge, input_value, request_material, plan, queue, state_root, capture_root,
     _keys, original_jobs) = _transport_canary_runtime_fixture(tmp_path, monkeypatch)
    request_material["configuration_sha256"] = "e" * 64
    source = {**plan, "schema": "v4.manager_workbench.announcement_flash_resume.v1",
              "transport_recovery": plan, "resume_action": "CANARY", "canary_passed": False}
    child = {**input_value, "job_id": "b" * 32,
             "resume_root": {"source_job_id": input_value["job_id"],
                             "source_input_sha256": plan["source_input_sha256"]},
             "resume_source": source}
    enqueue_count = len(queue.enqueued)
    with __import__("pytest").raises(bridge.FlashRunError,
                                     match="FROZEN_RESUME_TRANSPORT_CANARY_CURRENT_PAYLOAD"):
        bridge._run(child, state_root=state_root, capture_root=capture_root, job_id=child["job_id"],
                    progress=lambda _event: None, shared_root=tmp_path / "shared",
                    resume_frozen_batch=True, resume_action="CANARY", max_model_calls=1,
                    resume_source_job_id=input_value["job_id"],
                    resume_source_input_sha256=plan["source_input_sha256"])
    assert queue.jobs == original_jobs
    assert len(queue.enqueued) == enqueue_count
    assert queue.dispatched == []


def test_transport_canary_accepts_exact_current_request_reconstruction(tmp_path, monkeypatch):
    (bridge, input_value, _request_material, plan, queue, state_root, capture_root,
     keys, original_jobs) = _transport_canary_runtime_fixture(tmp_path, monkeypatch)
    source = {**plan, "schema": "v4.manager_workbench.announcement_flash_resume.v1",
              "transport_recovery": plan, "resume_action": "CANARY", "canary_passed": False}
    child = {**input_value, "job_id": "b" * 32,
             "resume_root": {"source_job_id": input_value["job_id"],
                             "source_input_sha256": plan["source_input_sha256"]},
             "resume_source": source}
    result = bridge._run(child, state_root=state_root, capture_root=capture_root, job_id=child["job_id"],
                         progress=lambda _event: None, shared_root=tmp_path / "shared",
                         resume_frozen_batch=True, resume_action="CANARY", max_model_calls=1,
                         resume_source_job_id=input_value["job_id"],
                         resume_source_input_sha256=plan["source_input_sha256"])
    assert result["resume"]["canary_passed"] is True
    assert result["resume"]["model_calls"] == 1
    canary_key = result["resume"]["canary_key"]
    assert canary_key not in original_jobs
    assert queue.dispatched == [canary_key]
    assert all(queue.jobs[key] == value for key, value in original_jobs.items())
    canary_payload = json.loads((queue.root / queue.jobs[canary_key]["input_path"]).read_bytes())
    assert canary_payload["transport_recovery_binding"]["failed_idempotency_key"] == keys[0]


def test_transport_continuation_versions_all_63_pending_parts_without_mutating_sources(tmp_path):
    from copy import deepcopy
    from v4.manager_workbench import announcement_chunks as chunks

    (bridge, queue, queue_root, current, _source_job, _legacy_job, _legacy, specs,
     lock, gate, cutoff) = _frozen_legacy_failed_canary_fixture(tmp_path, part_count=63)
    queue.jobs = {}
    queue.enqueued = []
    prefix = current["rules"].split("+fixed-fields-contract:", 1)[0]
    payloads = []
    for index in range(1, 64):
        payload = deepcopy(current)
        descriptor = payload["part_descriptor"]
        descriptor.update(part_index=index, part_count=63,
                          start_source_unit_id=f"U{index:06d}",
                          end_source_unit_id=f"U{index:06d}",
                          source_unit_ids=[f"U{index:06d}"],
                          unit_start_index=index - 1, unit_end_index=index,
                          part_sha256=bridge.sha(f"part-{index}".encode()))
        suffix = (f"+long-body-part:v1+plan:{payload['chunk_plan_sha256']}"
                  f"+part:{index}/63+part-sha:{descriptor['part_sha256']}"
                  f"+part-prompt:{payload['prompt_sha256']}+part-addendum:{chunks.PART_ADDENDUM_SHA256}")
        payload["rules"] = prefix + suffix
        payload["frozen_source_rules_suffix"] = suffix
        queue.enqueue(payload)
        payload["rules"] = (prefix + f"+fixed-fields-contract:{chunks.PART_FIXED_FIELDS_CONTRACT_VERSION}"
                            + suffix)
        payloads.append(payload)
    specs[current["article_id"]]["part_payloads"] = payloads
    ordinary_canary = deepcopy(current)
    ordinary_canary.pop("part_descriptor")
    ordinary_canary.pop("queue_task_kind")
    ordinary_canary["role"] = "announcement_reader"
    ordinary_canary["stage"] = "v4_manager_announcement_flash_incremental"
    ordinary_canary["rules"] = "recent_day_reader_v2+explicit-transport-resume:v1"
    saved_canary = queue.enqueue(ordinary_canary)
    saved_canary.update(status="SUCCEEDED", attempt_count=1)
    source_jobs_before = deepcopy(queue.jobs)

    allowed, records = bridge._enqueue_long_body_parts(
        specs, queue, queue_root, allow_same_batch_pending=True, recovery_lock=None,
        membership_gate=gate, resume_cutoff=cutoff, prompt_token_cap=64_000,
        hard_prompt_token_cap=160_000, allow_multiple_new_repairs=False,
        allow_new_repairs=False, allow_enqueue=True, resume_frozen_batch=True,
        resume_action="CONTINUE", saved_canary_key=saved_canary["idempotency_key"],
        source_job_id="c" * 32, source_input_sha256="d" * 64,
        count_prompt_tokens=lambda _messages: 51,
    )

    assert len(allowed) == 63
    assert len(records) == 63
    assert all(record["runnable"]
               and record["repair_status"] == "FROZEN_PENDING_VERSION_ENQUEUED"
               for record in records)
    assert all(queue.jobs[key] == item for key, item in source_jobs_before.items())
    assert len(queue.jobs) == len(source_jobs_before) + 63


def _saved_transport_readback_case(tmp_path, monkeypatch):
    """An ordinary projection has row identity, never nested reader identity."""
    (bridge, input_value, _material, plan, queue, state_root, capture_root,
     _keys, _original_jobs) = _transport_canary_runtime_fixture(tmp_path, monkeypatch)
    child = {**input_value, "job_id": "b" * 32,
             "resume_root": {"source_job_id": input_value["job_id"],
                             "source_input_sha256": plan["source_input_sha256"]},
             "resume_source": {**plan, "schema": "v4.manager_workbench.announcement_flash_resume.v1",
                               "transport_recovery": plan, "resume_action": "CANARY", "canary_passed": False}}
    result = bridge._run(child, state_root=state_root, capture_root=capture_root, job_id=child["job_id"],
                         progress=lambda _event: None, shared_root=tmp_path / "shared",
                         resume_frozen_batch=True, resume_action="CANARY", max_model_calls=1,
                         resume_source_job_id=input_value["job_id"],
                         resume_source_input_sha256=plan["source_input_sha256"])
    key = result["resume"]["canary_key"]
    assert result["resume"]["canary_passed"] is True
    saved = json.loads((queue.root / queue.jobs[key]["validated_path"]).read_bytes())
    assert saved["results"][0]["article_id"] == plan["failed_task"]["article_id"]
    assert "article_id" not in saved["results"][0]["reader_output"]
    # Exact R2 failure from the former nested identity lookup; saved artifacts stay successful.
    result["resume"].update(canary_passed=False, continue_eligible=False,
        canary_validation={"status": "FAIL", "key": key,
                           "failure_code": "FROZEN_RESUME_TRANSPORT_CANARY_RESULT_UNVERIFIED"})
    return bridge, child, result, plan, queue, state_root, capture_root


def test_saved_transport_ordinary_readback_revalidates_without_dispatch_or_writes(tmp_path, monkeypatch):
    bridge, child, result, plan, queue, state_root, capture_root = _saved_transport_readback_case(tmp_path, monkeypatch)
    before = {str(path): path.read_bytes() for path in state_root.rglob("*") if path.is_file()}
    result_before = bridge.canonical(result)
    bridge._verify_saved_transport_canary(bridge.SafeRoot(state_root), capture_root, child["job_id"],
                                          "20261016", child, result, {"jobs": queue.jobs}, plan)
    assert bridge.canonical(result) == result_before
    assert {str(path): path.read_bytes() for path in state_root.rglob("*") if path.is_file()} == before
    assert queue.dispatched == [result["resume"]["canary_key"]]


@__import__("pytest").mark.parametrize("mutation", [
    "raw_bytes", "validated_bytes", "missing_raw", "missing_sha", "payload_bytes", "wrong_article",
    "second_attempt", "second_dispatch", "second_call", "semantic_failure", "other_failure", "wrong_key",
    "source_drift", "configuration_drift",
])
def test_saved_transport_ordinary_readback_keeps_invalid_results_blocked(tmp_path, monkeypatch, mutation):
    bridge, child, result, plan, queue, state_root, capture_root = _saved_transport_readback_case(tmp_path, monkeypatch)
    key = result["resume"]["canary_key"]
    job = queue.jobs[key]
    if mutation == "raw_bytes":
        (queue.root / job["raw_path"]).write_bytes(b"{}")
    elif mutation == "validated_bytes":
        (queue.root / job["validated_path"]).write_bytes(b"{}")
    elif mutation == "missing_raw":
        (queue.root / job["raw_path"]).unlink()
    elif mutation == "missing_sha":
        del job["raw_sha256"]
    elif mutation == "payload_bytes":
        (queue.root / job["input_path"]).write_bytes(b"{}")
    elif mutation == "wrong_article":
        saved_path = queue.root / job["validated_path"]
        saved = json.loads(saved_path.read_bytes())
        saved["results"][0]["article_id"] = "EASTMONEY:OTHER"
        saved_path.write_bytes(bridge.canonical(saved))
        job["validated_sha256"] = job["attempts"][0]["validated_sha256"] = bridge.sha(saved_path.read_bytes())
    elif mutation == "second_attempt":
        job["attempts"].append(dict(job["attempts"][0]))
    elif mutation == "second_dispatch":
        result["resume"]["dispatched_keys"].append(key)
    elif mutation == "second_call":
        result["resume"]["model_calls"] = 2
    elif mutation == "semantic_failure":
        def reject(_job, _parsed):
            raise ValueError("SEMANTIC_REJECTED")
        monkeypatch.setattr(bridge, "_validator", lambda *_args: reject)
    elif mutation == "other_failure":
        result["resume"]["canary_validation"]["failure_code"] = "SEMANTIC_REJECTED"
    elif mutation == "wrong_key":
        result["resume"]["canary_key"] = "0" * 64
    elif mutation == "source_drift":
        (state_root / "announcement_flash/jobs" / plan["source_job_id"] / "input.json").write_bytes(b"{}")
    elif mutation == "configuration_drift":
        helper = bridge._load_helper()
        material = helper._full_day_request_material(None)
        material["configuration_sha256"] = "0" * 64
    with __import__("pytest").raises(bridge.FlashRunError):
        bridge._verify_saved_transport_canary(bridge.SafeRoot(state_root), capture_root, child["job_id"],
                                              "20261016", child, result, {"jobs": queue.jobs}, plan)
    assert queue.dispatched == [key]
