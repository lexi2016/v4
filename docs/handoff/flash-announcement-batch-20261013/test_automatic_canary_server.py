from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import httpx

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import announcement_queue as queue_module
import automatic_canary_server as app
import batch_runner as runner
import build_length_canary as length_canary
import test_batch_runner as fixtures


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sse(chunks: list[dict[str, Any]], *, crlf: bool = False) -> bytes:
    separator = "\r\n" if crlf else "\n"
    payload = "".join("data: " + json.dumps(value, ensure_ascii=False) + separator + separator for value in chunks)
    return (payload + "data: [DONE]" + separator + separator).encode("utf-8")


def queue_payload() -> dict[str, Any]:
    batch = fixtures.synthetic_batch()
    article = batch["articles"][0]
    metadata = article["article_metadata"]
    return {
        **{name: article[name] for name in ("article_id", "source_sha256", "body_sha256", "article_body")},
        "date": metadata["publication_date"],
        "market": "HK",
        "prompt_sha256": sha(b"prompt"),
        "model_id": app.MODEL_ID,
        "configuration_sha256": sha(b"config"),
        "rules": app.ARTICLE_RULES,
        "role": app.ARTICLE_ROLE,
        "stage": app.ARTICLE_STAGE,
        "article_metadata": metadata,
    }


def fake_plan(root: Path, *, article_count: int = 1) -> app.FrozenPlan:
    records = []
    article_rows = []
    canary_ids = []
    for i in range(article_count):
        article_id = f"TEST:SYNTH-{i}:HK.{2000 + i:05d}"
        key = sha(article_id.encode())
        records.append({
            "article_id": article_id,
            "article_metadata": {"title": f"fixture {i}"},
        })
        article_rows.append({
            "article_id": article_id,
            "idempotency_key": key,
            "context_admission": "READY",
            "prompt_tokens_exact": 100,
        })
        canary_ids.append(article_id)
    return app.FrozenPlan(
        records=tuple(records),
        cohorts={"canary_A_and_B_union": tuple(canary_ids), "pressure_batch_03": ()},
        metadata={"articles": article_rows, "input_manifest_sha256": sha(b"manifest")},
        manifest_path=root / "automatic-input-manifest.json",
    )


def phase_plan(root: Path) -> app.FrozenPlan:
    base = fake_plan(root, article_count=34)
    article_ids = tuple(row["article_id"] for row in base.metadata["articles"])
    return app.FrozenPlan(
        records=base.records,
        cohorts={
            "canary_A_and_B_union": article_ids[:6],
            "pressure_batch_03": (article_ids[0], *article_ids[6:]),
        },
        metadata=base.metadata,
        manifest_path=base.manifest_path,
    )


class EmptyQueue:
    def __init__(self, root: Path, items: list[dict[str, Any]] | None = None, results: list[dict[str, Any]] | None = None):
        self.state_root = root
        self.items = items or []
        self.results = list(results or [])
        self.run_calls = 0

    def snapshot(self) -> dict[str, Any]:
        counts = {name: 0 for name in queue_module.STATUSES}
        for item in self.items:
            counts[item["status"]] += 1
        return {"items": self.items, "status_counts": counts}

    def run_next(self, executor, validator, **kwargs):
        self.run_calls += 1
        return self.results.pop(0) if self.results else None


class PhaseTrackingQueue:
    def __init__(self, root: Path, plan: app.FrozenPlan):
        self.state_root = root
        self.queue_id = "phase-test-queue"
        self.items = [
            {
                "article_id": row["article_id"],
                "idempotency_key": row["idempotency_key"],
                "status": "PENDING",
                "attempt_count": 0,
                "max_attempts": 2,
                "last_error": None,
                "raw_path": None,
                "raw_sha256": None,
                "validated_sha256": None,
                "attempts": [],
            }
            for row in plan.metadata["articles"]
        ]
        self.by_key = {item["idempotency_key"]: item for item in self.items}
        self.run_calls = 0
        self.executed_keys: list[str] = []

    def snapshot(self) -> dict[str, Any]:
        counts = {name: 0 for name in queue_module.STATUSES}
        for item in self.items:
            counts[item["status"]] += 1
        return {"items": self.items, "status_counts": counts}

    def run_next(self, executor, validator, **kwargs):
        self.run_calls += 1
        allowed = kwargs.get("idempotency_keys")
        item = next((x for x in self.items if x["status"] == "PENDING" and (allowed is None or x["idempotency_key"] in allowed)), None)
        if item is None:
            return None
        item["status"] = "SUCCEEDED"
        item["attempt_count"] += 1
        item["raw_sha256"] = sha(b"fixture raw")
        item["validated_sha256"] = sha(b"fixture validated")
        item["attempts"].append({"duration_seconds": 0.01})
        self.executed_keys.append(item["idempotency_key"])
        return item


class AutomaticCanaryServerTests(unittest.TestCase):
    def test_ui_metric_label_names_first_sse_event_not_first_character(self) -> None:
        self.assertEqual(app.HTML.count("首流事件（非首字）"), 2)
        self.assertNotIn("TTFT", app.HTML)
        self.assertIn("s.current.ttft_seconds", app.HTML)

    def test_only_stable_error_codes_reach_ui(self) -> None:
        self.assertEqual(app._stable_failure_code(RuntimeError("secret-bearing error text"), "MODEL_REQUEST_FAILED"), "MODEL_REQUEST_FAILED")
        self.assertEqual(app._stable_failure_code(runner.TransportError("CHAT_NO_PROGRESS_TIMEOUT:ReadTimeout"), "MODEL_REQUEST_FAILED"), "CHAT_NO_PROGRESS_TIMEOUT")

    def test_existing_exact_token_counts_are_reused_with_actual_completion_limit(self) -> None:
        source_manifest = app.EVIDENCE_ROOT / "automatic-input-manifest.json"
        frozen = json.loads(source_manifest.read_text())
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp) / "evidence"
            output_root.mkdir(mode=0o700)
            target_manifest = output_root / "automatic-input-manifest.json"
            shutil.copyfile(source_manifest, target_manifest)
            target_manifest.chmod(0o600)
            with mock.patch.object(app.runner, "prepare_batch", side_effect=AssertionError("tokenization repeated")):
                plan = app.build_frozen_plan(
                    source_dir=app.SOURCE_DIR,
                    length_manifest_path=app.LENGTH_MANIFEST,
                    output_root=output_root,
                    runtime_limits=frozen["runtime_limits"],
                )
            manifest = json.loads(plan.manifest_path.read_text())
        self.assertEqual(manifest["deduped_union_count"], 34)
        canary = set(manifest["cohorts"]["canary_A_and_B_union"]["article_ids"])
        pressure = set(manifest["cohorts"]["pressure_batch_03"]["article_ids"])
        self.assertEqual(len(canary), 6)
        self.assertEqual(len(pressure), 29)
        self.assertEqual(len(canary & pressure), 1)
        self.assertEqual(len(manifest["articles"]), 34)
        self.assertEqual(manifest["runtime_limits"]["context_limit_tokens"], 262144)
        self.assertEqual(manifest["request_policy"]["max_completion_tokens"], 32768)
        self.assertEqual(manifest["prompt_profile"], "decision_grounded")
        self.assertEqual(manifest["system_prompt_sha256"], "107fb203c20440ed904763d12f90bee4ca6984c43292527dfc61ba6f8384f772")
        self.assertEqual(manifest["tool_schema_sha256"], sha(runner.canonical_json_bytes(runner.make_tool_schema())))
        for row in manifest["articles"]:
            self.assertEqual(row["max_completion_tokens"], 32768)
            self.assertEqual(
                row["context_admission"],
                "READY" if row["prompt_tokens_exact"] + 32768 <= row["context_limit_tokens"] else "CONTEXT_ITEM_UNFIT",
            )

    def test_authorized_grounded_profile_uses_locked_system_prompt(self) -> None:
        contract = runner.load_active_contract()
        prompt = runner.build_system_prompt(contract, "decision_grounded")
        self.assertEqual(sha(prompt.encode("utf-8")), "107fb203c20440ed904763d12f90bee4ca6984c43292527dfc61ba6f8384f772")
        self.assertEqual(app.PROFILE, "decision_grounded")

    def test_canary_pauses_for_explicit_pressure_gate_and_persists_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = phase_plan(root)
            queue = PhaseTrackingQueue(root / "queue-state", plan)

            class MockTransport:
                def close(self):
                    return None

            def make_controller():
                return app.AutomaticCanaryController(
                    plan,
                    queue=queue,
                    activity_probe=lambda: (0, 0),
                    model_ready_probe=lambda: True,
                    api_key="unit-secret",
                    transport_factory=lambda *_args: MockTransport(),
                )

            controller = make_controller()
            server = app.create_server(controller)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            client = httpx.Client(trust_env=False)

            def post(current_server, path: str, body: dict[str, Any]) -> httpx.Response:
                url = f"http://127.0.0.1:{current_server.server_address[1]}"
                return client.post(
                    url + path,
                    json=body,
                    headers={"Origin": url, "X-Canary-CSRF": current_server.canary_csrf_token},
                )

            try:
                before_canary = post(server, "/api/approve-pressure", {"confirmation": app.PRESSURE_CONFIRMATION_PHRASE})
                self.assertEqual(before_canary.status_code, 409)
                self.assertEqual(queue.executed_keys, [])

                started = post(server, "/api/start", {})
                self.assertEqual(started.status_code, 202)
                controller._worker.join(timeout=5)
                self.assertFalse(controller._worker.is_alive())
                canary_state = controller.snapshot()
                self.assertEqual(canary_state["state"], "WAITING_QUALITY_REVIEW")
                self.assertEqual(canary_state["phases"]["canary_A_and_B_union"], "WAITING_QUALITY_REVIEW")
                self.assertEqual(canary_state["phase_progress"]["canary_A_and_B_union"]["succeeded"], 6)
                self.assertEqual(canary_state["phases"]["pressure_batch_03"], "NOT_STARTED")
                self.assertEqual(len(queue.executed_keys), 6)
                self.assertEqual(queue.run_calls, 7)  # Six completions and one drain check.

                duplicate_start = post(server, "/api/start", {})
                self.assertEqual(duplicate_start.status_code, 409)
                self.assertEqual(len(queue.executed_keys), 6)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            restarted = make_controller()
            persisted = restarted.snapshot()
            self.assertEqual(persisted["state"], "WAITING_QUALITY_REVIEW")
            self.assertTrue(persisted["pressure_gate_available"])
            self.assertFalse(persisted["pressure_gate_accepted"])
            self.assertEqual(len(queue.executed_keys), 6)

            server2 = app.create_server(restarted)
            thread2 = threading.Thread(target=server2.serve_forever, daemon=True)
            thread2.start()
            try:
                no_implicit_pressure = post(server2, "/api/start", {})
                self.assertEqual(no_implicit_pressure.status_code, 409)
                self.assertEqual(len(queue.executed_keys), 6)
                wrong_confirmation = post(server2, "/api/approve-pressure", {"confirmation": "run pressure"})
                self.assertEqual(wrong_confirmation.status_code, 409)
                self.assertEqual(len(queue.executed_keys), 6)
                accepted = post(server2, "/api/approve-pressure", {"confirmation": app.PRESSURE_CONFIRMATION_PHRASE})
                self.assertEqual(accepted.status_code, 202)
                restarted._worker.join(timeout=5)
                self.assertFalse(restarted._worker.is_alive())
                pressure_state = restarted.snapshot()
                self.assertEqual(pressure_state["state"], "PRESSURE_FINISHED")
                self.assertTrue(pressure_state["pressure_gate_accepted"])
                self.assertEqual(pressure_state["phase_progress"]["pressure_batch_03"]["succeeded"], 29)
                self.assertEqual(pressure_state["phase_progress"]["pressure_batch_03"]["reused_successes"], 1)
                self.assertEqual(len(queue.executed_keys), 34)
                overlap_key = plan.metadata["articles"][0]["idempotency_key"]
                self.assertEqual(queue.executed_keys.count(overlap_key), 1)
                total_before_duplicate = queue.run_calls
                duplicate_gate = post(server2, "/api/approve-pressure", {"confirmation": app.PRESSURE_CONFIRMATION_PHRASE})
                self.assertEqual(duplicate_gate.status_code, 409)
                self.assertEqual(queue.run_calls, total_before_duplicate)
            finally:
                restarted.stop()
                server2.shutdown()
                server2.server_close()
                thread2.join(timeout=5)

            final_restart = make_controller()
            final_state = final_restart.snapshot()
            self.assertEqual(final_state["state"], "PRESSURE_FINISHED")
            self.assertTrue(final_state["pressure_gate_accepted"])
            self.assertEqual(len(queue.executed_keys), 34)

            # Simulate a process ending after the explicit gate was persisted
            # but before its phase completion state reached disk.
            with final_restart._lock:
                final_restart._phase = "PRESSURE_RUNNING"
                final_restart._phase_states["pressure_batch_03"] = "RUNNING"
                final_restart._active_phase = "pressure_batch_03"
                final_restart._persist_state_locked()
            interrupted_restart = make_controller()
            interrupted_state = interrupted_restart.snapshot()
            self.assertEqual(interrupted_state["state"], "PRESSURE_INTERRUPTED_AWAITING_RESUME")
            self.assertTrue(interrupted_state["pressure_gate_accepted"])
            calls_before_resume = queue.run_calls
            self.assertTrue(interrupted_restart.start())
            interrupted_restart._worker.join(timeout=5)
            self.assertFalse(interrupted_restart._worker.is_alive())
            self.assertEqual(interrupted_restart.snapshot()["state"], "PRESSURE_FINISHED")
            self.assertEqual(queue.run_calls, calls_before_resume + 1)  # Drain check only; successes are not repeated.
            self.assertEqual(len(queue.executed_keys), 34)

    def test_canary_failure_keeps_pressure_gate_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = phase_plan(root)
            queue = PhaseTrackingQueue(root / "queue-state", plan)
            canary_ids = set(plan.cohorts["canary_A_and_B_union"])
            canary_rows = [row for row in plan.metadata["articles"] if row["article_id"] in canary_ids]
            for index, row in enumerate(canary_rows):
                item = queue.by_key[row["idempotency_key"]]
                item["status"] = "FAILED" if index == 0 else "SUCCEEDED"
            controller = app.AutomaticCanaryController(
                plan,
                queue=queue,
                activity_probe=lambda: (0, 0),
                model_ready_probe=lambda: True,
                api_key="unit-secret",
                transport_factory=lambda *_args: self.fail("pressure must not create a transport"),
            )
            with controller._lock:
                controller._phase = "CANARY_FAILED_WAITING_REVIEW"
                controller._phase_states["canary_A_and_B_union"] = "FAILED_WAITING_REVIEW"
                controller._persist_state_locked()
            self.assertFalse(controller.snapshot()["pressure_gate_available"])
            self.assertFalse(controller.authorize_pressure(app.PRESSURE_CONFIRMATION_PHRASE))
            state = controller.snapshot()
        self.assertFalse(state["pressure_gate_accepted"])
        self.assertEqual(state["phase_progress"]["canary_A_and_B_union"]["failed"], 1)
        self.assertEqual(state["phases"]["pressure_batch_03"], "NOT_STARTED")

    def test_mock_sse_is_streamed_with_finite_timeout_and_recorded_byte_for_byte(self) -> None:
        answer = sse([
            {"choices": [{"delta": {"content": "{\"ok\":"}, "finish_reason": None}], "model": app.MODEL_ID},
            {"choices": [{"delta": {"content": "true}"}, "finish_reason": "stop"}], "model": app.MODEL_ID},
            {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11}, "model": app.MODEL_ID},
        ], crlf=True)
        request_timeouts = []

        def handler(request: httpx.Request) -> httpx.Response:
            request_timeouts.append(request.extensions["timeout"])
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=answer)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = queue_module.QueueJob("a" * 64, "test-q", app.MODEL_ID, {}, {}, 1)
            transport = app.GatedStreamingTransport(
                "unit-secret", root, http_transport=httpx.MockTransport(handler)
            )
            transport.begin_job(job)
            result = transport.complete_batch([{"role": "user", "content": "fixture body"}])
            transport.finish_job(status="RESPONSE_RECEIVED", completion=result)
            trace = next((root / "streams").rglob("round-01.raw.sse"))
            receipt = json.loads(next((root / "streams").rglob("stream-receipt.json")).read_text())
            trace_bytes = trace.read_bytes()
            transport.close()
        self.assertEqual(result.final_text, "{\"ok\":true}")
        self.assertEqual(result.usage["completion_tokens"], 2)
        self.assertEqual(trace_bytes, answer)
        self.assertEqual(receipt["rounds"][0]["raw_sse_sha256"], sha(answer))
        self.assertEqual(request_timeouts[0]["read"], app.NO_PROGRESS_TIMEOUT_SECONDS)

    def test_executor_request_matches_the_frozen_input_sha_and_keeps_the_full_body(self) -> None:
        batch = fixtures.synthetic_batch("  frozen full body\nwith exact spacing.  ")
        article = batch["articles"][0]
        batch_id = "AUTO_" + sha(article["article_id"].encode("utf-8"))[:20]
        frozen_batch = length_canary.make_batch([article], batch_id)
        contract = runner.load_active_contract()
        expected_messages = runner.build_messages(frozen_batch, contract, "decision_grounded")
        expected_input_sha = runner._input_batch_sha(frozen_batch)
        answer = sse([{"choices": [{"delta": {"content": "{\"results\":[]}"}, "finish_reason": "stop"}], "model": app.MODEL_ID}])
        sent = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=answer)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            key = "e" * 64
            plan = app.FrozenPlan(
                records=(article,),
                cohorts={"canary_A_and_B_union": (article["article_id"],), "pressure_batch_03": ()},
                metadata={
                    "articles": [{"article_id": article["article_id"], "idempotency_key": key, "input_sha256": expected_input_sha}],
                    "input_manifest_sha256": sha(b"manifest"),
                },
                manifest_path=root / "automatic-input-manifest.json",
            )
            payload = {
                **{name: article[name] for name in ("article_id", "source_sha256", "body_sha256", "article_body")},
                "article_metadata": article["article_metadata"],
            }
            job = queue_module.QueueJob(key, "test-q", app.MODEL_ID, {}, payload, 1)
            controller = app.AutomaticCanaryController(
                plan,
                queue=EmptyQueue(root / "queue-state"),
                activity_probe=lambda: (0, 0),
                model_ready_probe=lambda: True,
                api_key="unit-secret",
            )
            transport = app.GatedStreamingTransport(
                "unit-secret", root, http_transport=httpx.MockTransport(handler)
            )
            raw = controller._execute(transport, job)
            receipt_path = next((root / "streams").rglob("stream-receipt.json"))
            receipt_raw = receipt_path.read_bytes()
            transport.close()
        self.assertEqual(raw, "{\"results\":[]}")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["messages"], expected_messages)
        self.assertEqual(sha(sent[0]["messages"][0]["content"].encode("utf-8")), "107fb203c20440ed904763d12f90bee4ca6984c43292527dfc61ba6f8384f772")
        embedded = json.loads(sent[0]["messages"][1]["content"].removeprefix("ARTICLE_DATA_BEGIN\n").removesuffix("\nARTICLE_DATA_END"))
        self.assertEqual(embedded["articles"][0]["article_body"], article["article_body"])
        self.assertEqual(sent[0]["max_tokens"], app.MAX_COMPLETION_TOKENS)
        self.assertIs(sent[0]["enable_thinking"], False)
        self.assertNotIn(b"unit-secret", receipt_raw)

    def test_timeout_retains_partial_sse_and_failure_receipt(self) -> None:
        partial = b'data: {"choices":[{"delta":{"content":"partial"'

        class Interrupted(httpx.SyncByteStream):
            def __iter__(self):
                yield partial
                raise httpx.ReadTimeout("fixture timeout")

            def close(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = queue_module.QueueJob("b" * 64, "test-q", app.MODEL_ID, {}, {}, 1)
            transport = app.GatedStreamingTransport(
                "unit-secret",
                root,
                http_transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=Interrupted())),
            )
            transport.begin_job(job)
            with self.assertRaises(runner.TransportError) as caught:
                transport.complete_batch([{"role": "user", "content": "fixture"}])
            transport.finish_job(status="FAILED", code=str(caught.exception).split(":", 1)[0])
            trace = next((root / "streams").rglob("round-01.raw.sse"))
            receipt = json.loads(next((root / "streams").rglob("stream-receipt.json")).read_text())
            trace_bytes = trace.read_bytes()
            transport.close()
        self.assertIn("CHAT_NO_PROGRESS_TIMEOUT", str(caught.exception))
        self.assertEqual(trace_bytes, partial)
        self.assertEqual(receipt["rounds"][0]["raw_sse_sha256"], sha(partial))
        self.assertEqual(receipt["rounds"][0]["status"], "FAILED")

    def test_missing_web_contract_is_denied_and_model_can_continue(self) -> None:
        first = sse([{
            "choices": [{
                "delta": {"tool_calls": [{
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": json.dumps({"query": "generic market performance"})},
                }]},
                "finish_reason": "tool_calls",
            }],
            "model": app.MODEL_ID,
        }])
        final = sse([{"choices": [{"delta": {"content": "{\"answer\":\"based on supplied body\"}"}, "finish_reason": "stop"}], "model": app.MODEL_ID}])
        completion_requests = []
        web_requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/chat/completions":
                completion_requests.append(json.loads(request.content))
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=first if len(completion_requests) == 1 else final)
            web_requests.append(request)
            return httpx.Response(200, json={"ok": True, "results": []})

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = queue_module.QueueJob("c" * 64, "test-q", app.MODEL_ID, {}, {}, 1)
            transport = app.GatedStreamingTransport("unit-secret", root, http_transport=httpx.MockTransport(handler))
            transport.begin_job(job)
            result = transport.complete_batch([{"role": "user", "content": "complete supplied body fact"}])
            receipt = result.tool_receipts[0]
            transport.close()
        self.assertEqual(result.final_text, "{\"answer\":\"based on supplied body\"}")
        self.assertEqual(len(completion_requests), 2)
        self.assertEqual(web_requests, [])
        self.assertEqual(receipt["status"], "failed")
        self.assertIsNone(receipt["input_sha256"])
        self.assertIn("web_lookup_contract_missing", completion_requests[1]["messages"][-1]["content"])
        self.assertIn("complete supplied body fact", completion_requests[1]["messages"][0]["content"])

    def test_one_web_failure_is_saved_and_repeated_lookup_is_suppressed(self) -> None:
        route_calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            route_calls.append(request)
            return httpx.Response(503, content=b"upstream fixture failure")

        properties = runner.load_active_contract().reader_schema["properties"]
        field = next(iter(properties))
        query1 = f"MISSING_FACT: filing date\nREADER_FIELD: {field}\nQUERY: issuer filing date"
        query2 = f"MISSING_FACT: exchange date\nREADER_FIELD: {field}\nQUERY: exchange publication date"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job = queue_module.QueueJob("d" * 64, "test-q", app.MODEL_ID, {}, {}, 1)
            transport = app.GatedStreamingTransport("unit-secret", root, http_transport=httpx.MockTransport(handler))
            transport.begin_job(job)
            first, first_receipt = transport._call_web_tool("web_search", {"query": query1}, lambda _e: None)
            second, second_receipt = transport._call_web_tool("web_search", {"query": query2}, lambda _e: None)
            raw_path = root / first_receipt["raw_source_path"]
            raw = raw_path.read_bytes()
            transport.close()
        self.assertFalse(first["ok"])
        self.assertFalse(second["ok"])
        self.assertEqual(len(route_calls), 1)
        self.assertEqual(second_receipt["input_sha256"], None)
        self.assertEqual(raw, b"upstream fixture failure")
        self.assertEqual(first_receipt["raw_source_sha256"], sha(raw))

    def test_empty_or_context_failure_raw_is_saved_by_existing_queue(self) -> None:
        for executor_result, expected_code in ((b"", None), (queue_module.ExecutorFailure("CONTEXT_ITEM_UNFIT", code="CONTEXT_ITEM_UNFIT", raw_response=b""), "CONTEXT_ITEM_UNFIT")):
            with self.subTest(expected_code=expected_code), tempfile.TemporaryDirectory() as temp:
                queue = queue_module.SerialAnnouncementQueue(Path(temp), "test-q", app.MODEL_ID, max_attempts=1)
                queued = queue.enqueue(queue_payload())

                def execute(_job):
                    if isinstance(executor_result, Exception):
                        raise executor_result
                    return executor_result

                result = queue.run_next(execute, lambda _job, parsed: parsed, wait_for_model_slot=False)
                item = next(row for row in queue.snapshot()["items"] if row["idempotency_key"] == queued["idempotency_key"])
                raw_path = Path(item["raw_path"])
                self.assertTrue(raw_path.is_file())
                self.assertEqual(raw_path.read_bytes(), b"")
                self.assertEqual(item["raw_sha256"], sha(b""))
                if expected_code:
                    self.assertEqual((result.get("last_error") or {}).get("code"), expected_code)

    def test_visible_start_is_required_and_duplicate_start_does_not_duplicate_work(self) -> None:
        secret = "unit-secret-must-not-be-rendered"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = fake_plan(root, article_count=1)
            article = plan.records[0]
            key = plan.metadata["articles"][0]["idempotency_key"]
            item = {"article_id": article["article_id"], "idempotency_key": key, "status": "PENDING", "attempt_count": 0, "max_attempts": 2}
            queue = EmptyQueue(root / "queue-state", [item])
            calls = {"activity": 0, "model_ready": 0, "transport_factory": 0}

            def activity():
                calls["activity"] += 1
                return 0, 0

            def model_ready():
                calls["model_ready"] += 1
                return True

            class MockTransport:
                def __init__(self):
                    pass

                def close(self):
                    return None

            def transport_factory(_key, _root):
                calls["transport_factory"] += 1
                return MockTransport()

            controller = app.AutomaticCanaryController(
                plan,
                queue=queue,
                activity_probe=activity,
                model_ready_probe=model_ready,
                api_key=secret,
                transport_factory=transport_factory,
            )
            server = app.create_server(controller)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            client = httpx.Client(trust_env=False)
            try:
                url = f"http://127.0.0.1:{server.server_address[1]}"
                page = client.get(url + "/").text
                self.assertNotIn(secret, page)
                self.assertEqual(calls["transport_factory"], 0)
                self.assertEqual(queue.run_calls, 0)
                missing_csrf = client.post(url + "/api/start", json={})
                self.assertEqual(missing_csrf.status_code, 403)
                headers = {
                    "Origin": url,
                    "X-Canary-CSRF": server.canary_csrf_token,
                }
                accepted = client.post(url + "/api/start", json={}, headers=headers)
                self.assertEqual(accepted.status_code, 202)
                worker = controller._worker
                self.assertIsNotNone(worker)
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                duplicate = client.post(url + "/api/start", json={}, headers=headers)
                self.assertEqual(duplicate.status_code, 409)
            finally:
                controller.stop()
                server.shutdown()
                server.server_close()
                client.close()
                thread.join(timeout=5)
            self.assertEqual(calls["transport_factory"], 1)
            self.assertEqual(calls["activity"], 2)
            self.assertEqual(calls["model_ready"], 1)
            self.assertEqual(queue.run_calls, 1)

    def test_failed_request_stops_when_admin_activity_cannot_be_proven_idle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = fake_plan(root, article_count=2)
            keys = [row["idempotency_key"] for row in plan.metadata["articles"]]
            items = [
                {"article_id": plan.metadata["articles"][0]["article_id"], "idempotency_key": keys[0], "status": "FAILED", "attempt_count": 1, "max_attempts": 2, "last_error": {"code": "CHAT_NO_PROGRESS_TIMEOUT"}},
                {"article_id": plan.metadata["articles"][1]["article_id"], "idempotency_key": keys[1], "status": "PENDING", "attempt_count": 0, "max_attempts": 2, "last_error": None},
            ]
            queue = EmptyQueue(root / "queue-state", items, results=[{
                "status": "FAILED",
                "idempotency_key": keys[0],
                "attempt_count": 1,
                "last_error": {"code": "CHAT_NO_PROGRESS_TIMEOUT"},
                "raw_sha256": sha(b"partial stream"),
                "validated_sha256": None,
                "attempts": [{"duration_seconds": 1.0}],
            }])
            activity_values = iter([(0, 0), (0, 0), (1, 0)])

            class MockTransport:
                def close(self):
                    return None

            controller = app.AutomaticCanaryController(
                plan,
                queue=queue,
                activity_probe=lambda: next(activity_values),
                model_ready_probe=lambda: True,
                api_key="unit-secret",
                transport_factory=lambda *_args: MockTransport(),
                idle_timeout_seconds=0,
            )
            self.assertTrue(controller.start())
            controller._worker.join(timeout=5)
            self.assertFalse(controller._worker.is_alive())
            state = controller.snapshot()
            receipt = json.loads((root / "automatic-run-receipt.json").read_text())
        self.assertEqual(queue.run_calls, 1)
        self.assertEqual(state["state"], "PAUSED_ACTIVITY_UNVERIFIED")
        self.assertEqual(state["stop_code"], "EXTERNAL_OR_STUCK_ACTIVITY_PRESENT")
        self.assertEqual(state["queue_status_counts"]["PENDING"], 1)
        self.assertEqual(receipt["scheduled_unique_count"], 2)
        self.assertEqual(receipt["semantic_quality"], "NOT_ASSESSED_BY_AUTOMATION")


if __name__ == "__main__":
    unittest.main()
