from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
PIPELINE = HERE.parents[1]
sys.path.insert(0, str(PIPELINE))
SPEC = importlib.util.spec_from_file_location("recent_day_freeze", HERE / "recent_day_freeze.py")
HELPER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(HELPER)

import announcement_queue
import automatic_canary_server
import batch_runner


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path):
    return json.loads(path.read_bytes())


class RecentDayFlashAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = HERE / "candidate-172" / "ready-v2"
        cls.manifest_path = cls.root / "candidate-manifest.json"
        cls.manifest_raw = cls.manifest_path.read_bytes()
        cls.manifest = json.loads(cls.manifest_raw)
        cls.contract = batch_runner.load_active_contract()

    def test_full_172_batch_and_zero_attempt_queue_match_triage(self):
        manifest = self.manifest
        batch_path = Path(manifest["queue"]["validated_batch_path"])
        batch_raw = batch_path.read_bytes()
        self.assertEqual(_sha(batch_raw), manifest["queue"]["validated_batch_sha256"])
        batch = json.loads(batch_raw)
        articles = batch_runner.validate_batch(batch)
        self.assertEqual(len(articles), 172)

        records_path = Path(manifest["source_inputs"]["source_window_records_path"])
        records_raw = records_path.read_bytes()
        self.assertEqual(_sha(records_raw), manifest["source_inputs"]["source_window_records_sha256"])
        record_by_code = {x["art_code"]: x for x in (json.loads(line) for line in records_raw.splitlines())}
        triage = _read_json(Path(manifest["source_inputs"]["triage_manifest_path"]))
        route_by_code = {x["art_code"]: x["route"] for x in triage["article_triage"]}
        queued_codes = {x["article_id"].split(":", 1)[1] for x in articles}
        self.assertEqual(len(queued_codes), 172)
        self.assertEqual(queued_codes, {code for code, route in route_by_code.items() if route.startswith("RETAIN_")})
        self.assertFalse(queued_codes & set(manifest["isolated_ids"]["low_priority"]))
        self.assertFalse(queued_codes & set(manifest["isolated_ids"]["body_or_source_exceptions"]))

        for article in articles:
            code = article["article_id"].split(":", 1)[1]
            source = record_by_code[code]
            self.assertEqual(article["source_sha256"], source["source_sha256"])
            self.assertEqual(article["body_sha256"], source["body_text_sha256"])
            self.assertEqual(article["article_body"], source["body_text"])
            self.assertGreaterEqual(len(article["article_metadata"]["source_origins"]), 2)
            self.assertEqual(article["article_metadata"]["pit_status"], "CANNOT_CONFIRM")

        queue = announcement_queue.SerialAnnouncementQueue(
            manifest["queue"]["state_root"], manifest["queue"]["queue_id"],
            manifest["model_request_policy"]["model_id"], max_attempts=manifest["queue"]["max_attempts"],
        )
        snapshot = queue.snapshot()
        self.assertEqual(len(snapshot["items"]), 172)
        frozen_queue = _read_json(Path(manifest["queue"]["zero_attempt_queue_path"]))
        self.assertEqual(frozen_queue["article_count"], 172)
        self.assertEqual(frozen_queue["counts"]["PENDING"], 172)
        self.assertEqual(frozen_queue["attempt_count_total"], 0)
        self.assertEqual(manifest["counts"]["isolated_low_priority_articles"], 163)
        self.assertEqual(manifest["counts"]["body_or_source_exception_articles"], 5)

    def test_direct_queue_leaves_context_overflow_pending_for_complete_chunking(self):
        manifest = self.manifest
        preflight = manifest["preflight"]
        direct_ids = set(preflight["direct_eligible_ids"])
        chunk_ids = set(preflight["awaiting_full_body_chunking_ids"])
        all_ids = {row["article_id"] for row in manifest["articles"]}
        self.assertEqual(len(direct_ids), 170)
        self.assertEqual(len(chunk_ids), 2)
        self.assertFalse(direct_ids & chunk_ids)
        self.assertEqual(direct_ids | chunk_ids, all_ids)
        self.assertEqual(manifest["counts"]["direct_single_request_articles"], 170)
        self.assertEqual(manifest["counts"]["awaiting_full_body_chunking_articles"], 2)
        for row in manifest["articles"]:
            if row["execution_admission"] == "DIRECT_SINGLE_REQUEST":
                self.assertLessEqual(row["prompt_tokens_exact"], row["context_limit_tokens"])
            else:
                self.assertGreater(row["prompt_tokens_exact"], row["context_limit_tokens"])

        queue = announcement_queue.SerialAnnouncementQueue(
            manifest["queue"]["state_root"], manifest["queue"]["queue_id"],
            manifest["model_request_policy"]["model_id"], max_attempts=manifest["queue"]["max_attempts"],
        )
        snapshot = queue.snapshot()
        frozen_queue = _read_json(Path(manifest["queue"]["zero_attempt_queue_path"]))
        frozen_by_key = {item["idempotency_key"]: item for item in frozen_queue["items"]}
        direct_keys = set()
        raw_state = queue._load_state()
        for item in raw_state["jobs"].values():
            if manifest["queue"]["queue_id"] not in item.get("queue_ids", [item.get("queue_id")]):
                continue
            payload = queue._read_payload(item)
            frozen = frozen_by_key[item["idempotency_key"]]
            self.assertEqual(frozen["status"], "PENDING")
            self.assertEqual(frozen["attempt_count"], 0)
            if payload["article_id"] in direct_ids:
                self.assertEqual(payload["execution_admission"], "DIRECT_SINGLE_REQUEST")
                direct_keys.add(item["idempotency_key"])
            else:
                self.assertEqual(payload["execution_admission"], "AWAITING_FULL_BODY_CHUNKING")
                self.assertEqual(payload["context_admission"], "INPUT_EXCEEDS_CONTEXT")
        self.assertEqual(len(direct_keys), 170)
        self.assertEqual(len(frozen_by_key), 172)

    def test_zero_temperature_thinking_off_and_original_schema_are_frozen(self):
        policy = self.manifest["model_request_policy"]
        self.assertEqual(policy["request_temperature"], 0.0)
        self.assertIs(policy["enable_thinking"], False)
        self.assertEqual(automatic_canary_server.SIMPLE_WORKFLOW_REQUEST_TEMPERATURE, 0.0)
        self.assertEqual(automatic_canary_server._verified_simple_workflow_sampling_policy(), policy["sampling_policy"])
        self.assertEqual(policy["reader_schema_sha256"], _sha(batch_runner.canonical_json_bytes(self.contract.reader_schema)))
        self.assertEqual(policy["structured_output_schema_sha256"], _sha(batch_runner.canonical_json_bytes(batch_runner.build_simple_workflow_schema(self.contract))))
        self.assertEqual(policy["wire_reader_schema_sha256"], _sha(batch_runner.canonical_json_bytes(batch_runner.build_simple_reader_wire_schema(self.contract))))
        self.assertTrue(policy["schema_unchanged_from_active_contract"])

    def test_temporary_prompt_assigns_changes_to_model_without_old_empty_rule(self):
        prompt = HELPER._recent_day_system_prompt(self.contract)
        self.assertIn("facts 必须输出空数组", prompt)
        self.assertIn("changes 由你根据完整正文填写经营/业绩变化", prompt)
        self.assertIn("程序仅将该引用投影成原文 quote 和 locator", prompt)
        self.assertNotIn("facts 和 changes 均为 []", prompt)
        self.assertNotIn("changes 必须都输出空数组", prompt)

    def test_projection_injects_script_facts_and_preserves_model_changes(self):
        body = "证券代号：12345\n\n正文披露经营变化。\n"
        body_sha = _sha(body.encode("utf-8"))
        unit_map = batch_runner.build_source_unit_map(body, body_sha)
        metadata = {"pit_status": "CANNOT_CONFIRM", "pit_reason": None}
        ledger = batch_runner.simple_fixed_facts.extract_fixed_facts(body, unit_map, metadata)
        self.assertTrue(ledger["reader_facts"])
        model_claim = "正文披露经营变化"
        model_unit = unit_map["units"][-1]
        reader = {
            "facts": [],
            "changes": [{"claim": model_claim, "source_unit_id": model_unit["source_unit_id"]}],
            "impact": [{"claim": "正文披露经营变化", "source_unit_id": model_unit["source_unit_id"]}],
            "confirmation_conditions": [],
            "counter_evidence": [],
            "disposition": "NOT_ASSESSED",
            "selection_basis": "NOT_ASSESSED",
            "direction": "UNKNOWN",
            "evidence_sufficiency": "INSUFFICIENT_EXISTING_FACTS",
            "reason": "模型理由原样保留",
            "risk_notes": ["模型风险原样保留"],
            "source_sha256": "",
            "body_sha256": "",
        }
        article = {
            "article_id": "EASTMONEY:SYNTHETIC-TEST",
            "source_sha256": "a" * 64,
            "body_sha256": body_sha,
            "article_body": body,
            "article_metadata": metadata,
            "fixed_fact_ledger": ledger,
        }
        envelope = {"action": "complete", "lookup_request": None, "reader_output": reader}
        projected, receipt = HELPER._project_recent_day_simple_output(
            envelope, article, self.contract, unit_map["source_unit_map_sha256"]
        )
        output = projected["results"][0]["reader_output"]
        self.assertEqual([row["claim"] for row in output["facts"]], [row["claim"] for row in ledger["reader_facts"]])
        self.assertEqual(output["facts"][0]["locator"], f"article_body[codepoint:{unit_map['units'][0]['start_cp']}:{unit_map['units'][0]['end_cp']}]")
        self.assertEqual(output["facts"][0]["quote"], unit_map["units"][0]["text"])
        self.assertEqual(output["changes"][0]["claim"], model_claim)
        self.assertEqual(output["changes"][0]["quote"], model_unit["text"])
        self.assertEqual(output["impact"][0]["claim"], "正文披露经营变化")
        self.assertEqual(output["impact"][0]["quote"], model_unit["text"])
        self.assertEqual(output["reason"], reader["reason"])
        self.assertEqual(output["disposition"], reader["disposition"])
        self.assertEqual(output["risk_notes"][0], "模型风险原样保留")
        self.assertIn("pit_status=CANNOT_CONFIRM", output["risk_notes"][-1])
        self.assertEqual(output["source_sha256"], article["source_sha256"])
        self.assertEqual(output["body_sha256"], body_sha)
        self.assertEqual(receipt["model_changes_preserved_count"], 1)
        batch_runner._validate_json_schema(output, self.contract.reader_schema)

    def test_runtime_error_parser_recognizes_live_sse_and_http_error_shapes(self):
        sse_error = (
            b'data: {"error":{"message":"oMLX prefill memory guard rejected this prompt",'
            b'"type":"invalid_request_error","code":"prefill_memory_exceeded",'
            b'"omlx_code":"prefill_memory_exceeded","estimated_bytes":84924584494,'
            b'"limit_bytes":83807712331}}\n\ndata: [DONE]\n'
        )
        http_error = (
            b'{"error":{"message":"oMLX prefill memory guard rejected this prompt",'
            b'"type":"invalid_request_error","code":"prefill_memory_exceeded",'
            b'"omlx_code":"prefill_memory_exceeded","estimated_bytes":84575909423,'
            b'"limit_bytes":83900521137}}'
        )
        for raw in (sse_error, http_error):
            with self.subTest(shape="sse" if raw.startswith(b"data:") else "http-json"):
                parsed = HELPER._runtime_error_from_raw_response(raw)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed["error_code"], "prefill_memory_exceeded")
                self.assertEqual(parsed["omlx_code"], "prefill_memory_exceeded")
                self.assertIn("estimated_bytes", parsed)
                self.assertIn("limit_bytes", parsed)

    def test_system_failure_persists_first_cause_and_stops_remaining_queue(self):
        sse_error = (
            b'data: {"error":{"message":"prefill memory rejected",'
            b'"type":"invalid_request_error","code":"prefill_memory_exceeded",'
            b'"omlx_code":"prefill_memory_exceeded","estimated_bytes":84924584494,'
            b'"limit_bytes":83807712331}}\n\ndata: [DONE]\n'
        )
        class FakeQueue:
            def __init__(self):
                self.items = [
                    {"identity": {"article_id": "EASTMONEY:TEST-1"}, "idempotency_key": "test-key-1", "status": "PENDING", "attempt_count": 0, "max_attempts": 2},
                    {"identity": {"article_id": "EASTMONEY:TEST-2"}, "idempotency_key": "test-key-2", "status": "PENDING", "attempt_count": 0, "max_attempts": 2},
                ]
                self.run_calls = 0

            def snapshot(self):
                counts = {}
                for item in self.items:
                    counts[item["status"]] = counts.get(item["status"], 0) + 1
                return {"items": self.items, "status_counts": counts}

            def run_next(self, executor, _validator, *, wait_for_model_slot, idempotency_keys):
                self.run_calls += 1
                self.assert_nonblocking = wait_for_model_slot is False
                item = next(x for x in self.items if x["status"] == "PENDING" and x["idempotency_key"] in idempotency_keys)
                item["status"] = "RUNNING"
                item["attempt_count"] += 1
                job = SimpleNamespace(
                    idempotency_key=item["idempotency_key"],
                    attempt=item["attempt_count"],
                    identity=item["identity"],
                    payload={"article_id": item["identity"]["article_id"], "context_admission": "INPUT_FITS", "messages": [], "structured_output_schema": {}},
                )
                try:
                    executor(job)
                except announcement_queue.ExecutorFailure as exc:
                    item["status"] = "FAILED"
                    item["last_error"] = {"code": exc.code}
                    return {"identity": item["identity"], "status": item["status"], "last_error": item["last_error"]}
                raise AssertionError("simulated system rejection must stop in the executor")
        http_error = (
            b'{"error":{"message":"prefill memory rejected",'
            b'"type":"invalid_request_error","code":"prefill_memory_exceeded",'
            b'"omlx_code":"prefill_memory_exceeded","estimated_bytes":84575909423,'
            b'"limit_bytes":83900521137}}'
        )

        for response_mode, raw_error in (("sse-error-event", sse_error), ("http-error-json", http_error)):
            with self.subTest(response_mode=response_mode), tempfile.TemporaryDirectory(prefix="recent-day-system-stop-") as temp:
                class FakeTransport:
                    instances = []

                    def __init__(self, _api_key, evidence_root):
                        self.evidence_root = Path(evidence_root)
                        self._attempt_dir = None
                        self.finish_calls = []
                        self.__class__.instances.append(self)

                    def begin_job(self, job):
                        self._attempt_dir = self.evidence_root / "streams" / job.idempotency_key / "attempt-0001"
                        self._attempt_dir.mkdir(parents=True, exist_ok=True)
                        (self._attempt_dir / "round-01.raw.sse").write_bytes(raw_error)

                    def complete_batch(self, *_args, **_kwargs):
                        if response_mode == "http-error-json":
                            raise batch_runner.TransportError("CHAT_HTTP_STATUS:400")
                        return SimpleNamespace(final_text="", wall_seconds=0.1, usage=None)

                    def finish_job(self, *, status, code=None, completion=None):
                        self.finish_calls.append({"status": status, "code": code, "completion": completion is not None})

                    def close(self):
                        pass

                ui = object.__new__(HELPER._RecentDayUI)
                ui.root = Path(temp)
                ui.manifest = {"queue": {"queue_id": "test-queue"}}
                ui.queue = FakeQueue()
                ui.lock = threading.RLock()
                ui.stop_requested = False
                ui.state = "RUNNING"
                ui.start_block_code = None
                ui.system_failure = None
                ui.current = None
                ui.partial_by_key = {}
                ui.finished_at = None
                ui.model_requests_started = 0
                ui.article_meta = {
                    "EASTMONEY:TEST-1": {"execution_admission": "DIRECT_SINGLE_REQUEST", "title": "test one"},
                    "EASTMONEY:TEST-2": {"execution_admission": "DIRECT_SINGLE_REQUEST", "title": "test two"},
                }
                ui.contract = None
                with mock.patch.object(automatic_canary_server, "GatedStreamingTransport", FakeTransport):
                    ui._run_queue("test-api-key-placeholder")

                self.assertEqual(ui.queue.run_calls, 1)
                self.assertEqual([x["status"] for x in ui.queue.items], ["FAILED", "PENDING"])
                self.assertEqual(ui.state, "STOPPED_SYSTEM_FAILURE")
                self.assertEqual(ui.start_block_code, "prefill_memory_exceeded")
                self.assertEqual(FakeTransport.instances[-1].finish_calls[0]["code"], "prefill_memory_exceeded")
                receipt = json.loads((ui.root / "system-failure-stop.json").read_bytes())
                self.assertEqual(receipt["error_code"], "prefill_memory_exceeded")
                self.assertEqual(receipt["article_id"], "EASTMONEY:TEST-1")
                self.assertEqual(receipt["raw_response_sha256"], _sha(raw_error))
                if response_mode == "http-error-json":
                    self.assertEqual(receipt["error"]["http_status"], 400)
                self.assertEqual(ui.start(), (False, "SYSTEM_FAILURE_STOPPED"))
                self.assertEqual(ui.queue.run_calls, 1)


if __name__ == "__main__":
    unittest.main()
