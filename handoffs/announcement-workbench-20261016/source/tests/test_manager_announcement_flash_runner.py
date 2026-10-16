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

    progress = []
    result = bridge._run(
        {"target_date": "20261016", "capture_product": {"artifact_ref": capture_ref, "sha256": capture_sha}},
        state_root=tmp_path / "state", capture_root=capture_root,
        job_id="a" * 32, progress=progress.append,
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
