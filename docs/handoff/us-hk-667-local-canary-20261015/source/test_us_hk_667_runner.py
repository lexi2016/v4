from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

EVIDENCE_DIR = Path(__file__).resolve().parents[1]
PIPELINE_ROOT = EVIDENCE_DIR.parents[1]
if str(EVIDENCE_DIR) not in sys.path:
    sys.path.insert(0, str(EVIDENCE_DIR))
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

import us_hk_667_runner as subject


class UsHk667RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="test-candidate-", dir=EVIDENCE_DIR)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "candidate"

    def test_package_candidate_identity_and_zero_request_resume(self):
        packet = subject.load_package()
        self.assertEqual(packet["archive_sha256"], subject.PACKAGE_ZIP_SHA256)
        self.assertEqual(len(packet["rows"]), 667)
        self.assertEqual(len({row["港股代码"] for row in packet["rows"]}), 667)
        self.assertTrue(packet["xlsx_equals_csv"])

        root = subject.prepare_candidate(self.root)
        manifest_path = root / "candidate-manifest.json"
        manifest_sha = subject._sha(manifest_path.read_bytes())
        state = json.loads((root / "queue-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["model_requests_started"], 0)
        self.assertTrue(all(item["status"] == "NOT_REVIEWED" for item in state["items"]))
        self.assertEqual(state["canary_codes"], ["00005", "00883", "00002"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["request_policy"]["protocol_id"], subject.ACTION_PROTOCOL_ID)
        self.assertEqual(manifest["request_policy"]["action_schema_sha256"], subject._sha(subject._canonical_bytes(subject.ACTION_SCHEMA)))
        loaded = subject.CandidateApp(root, attempt_fn=lambda *_args: self.fail("must not run"))
        self.assertEqual(loaded.status()["total"], 667)
        self.assertEqual(loaded.status()["model_requests_started"], 0)

        self.assertEqual(subject.prepare_candidate(self.root), root)
        self.assertEqual(subject._sha(manifest_path.read_bytes()), manifest_sha)
        resumed = json.loads((root / "queue-state.json").read_text(encoding="utf-8"))
        self.assertEqual(resumed["model_requests_started"], 0)
        self.assertEqual(len(resumed["items"]), 667)

    def test_candidate_refuses_modified_frozen_source_input(self):
        root = subject.prepare_candidate(self.root)
        source_path = root / "inputs" / "stock-list.csv"
        source_path.write_bytes(source_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "FROZEN_CANDIDATE_INPUT_CHANGED"):
            subject.CandidateApp(root, attempt_fn=lambda *_args: self.fail("must not run"))

    def test_missing_local_transport_credential_is_classified_as_system_failure(self):
        root = subject.prepare_candidate(self.root)
        app = subject.CandidateApp(root, attempt_fn=lambda *_args: self.fail("must not run"))
        item = next(row for row in app.state["items"] if row["stock_code"] == "00005")
        attempt_dir = root / "attempts" / "00005" / "attempt-01"
        attempt_dir.mkdir(parents=True)
        with mock.patch.object(
            subject.runner, "load_local_api_key",
            side_effect=subject.runner.TransportError("LOCAL_OMLX_API_KEY_UNAVAILABLE"),
        ):
            with self.assertRaisesRegex(subject.SystemFailure, "LOCAL_OMLX_API_KEY_UNAVAILABLE"):
                app._infer_one(item, attempt_dir, lambda _event: None)
        self.assertTrue((attempt_dir / "model-input.messages.json").is_file())
        self.assertFalse((attempt_dir / "round-01.request.json").exists())

    def test_only_explicit_canary_action_runs_and_system_failure_stops_pending_items(self):
        root = subject.prepare_candidate(self.root)
        calls = []

        def fake_attempt(item, _attempt_dir, on_event):
            calls.append(item["stock_code"])
            on_event({"type": "request_started", "round": 1})
            if item["stock_code"] == "00005":
                raise ValueError("mock article-local processing error")
            raise subject.SystemFailure("MOCK_SHARED_TRANSPORT_FAILURE")

        app = subject.CandidateApp(root, attempt_fn=fake_attempt)
        self.assertEqual(calls, [])
        self.assertEqual(app.status()["model_requests_started"], 0)
        ok, code = app.start_canary()
        self.assertTrue(ok, code)
        self.assertIsNotNone(app.thread)
        app.thread.join(timeout=10)
        self.assertFalse(app.thread.is_alive())

        state = json.loads((root / "queue-state.json").read_text(encoding="utf-8"))
        by_code = {item["stock_code"]: item for item in state["items"]}
        self.assertEqual(calls, ["00005", "00883"])
        self.assertEqual(by_code["00005"]["status"], "IN_PROGRESS")
        self.assertEqual(by_code["00883"]["status"], "FAILED_SYSTEM")
        self.assertEqual(by_code["00002"]["status"], "NOT_REVIEWED")
        self.assertEqual(state["model_requests_started"], 2)
        self.assertEqual(state["system_failure"]["code"], "MOCK_SHARED_TRANSPORT_FAILURE")

        reloaded = subject.CandidateApp(root, attempt_fn=fake_attempt)
        self.assertEqual(calls, ["00005", "00883"])
        self.assertEqual(reloaded.status()["items"][-1]["status"], "NOT_REVIEWED")
        self.assertEqual(reloaded.start_canary(), (False, "SYSTEM_FAILURE_REQUIRES_EXPLICIT_RECOVERY_ACK"))

    def test_a_to_j_contract_and_fetch_text_required_for_citations(self):
        packet = subject.load_package()
        row = packet["rows"][0]
        item = {
            "source_index": 1, "stock_code": row["港股代码"],
            "stock_name": row["中文简称"], "universe_date": subject.UNIVERSE_DATE,
        }
        report = {
            "schema": "us_hk_667_stock_review.v1",
            "stock_code": item["stock_code"], "stock_name": item["stock_name"],
            "universe_date": subject.UNIVERSE_DATE, "report_status": "IN_PROGRESS",
            "relationships": [],
        }
        for letter in "ABCDEFGHIJ":
            report[letter] = {"assessment": "待核验", "claims": [], "unknowns": ["CANNOT_CONFIRM"]}
        citation = {
            "url": "https://example.com/annual-report",
            "title": "Annual report", "publication_date_or_period": "2025",
            "quote": "Revenue was reported for the year.",
        }
        report["A"]["claims"].append({
            "kind": "VERIFIED_FACT", "claim": "财务披露包含营业收入信息。", "evidence": [citation],
        })
        self.assertEqual(subject.validate_report_structure(report, item), [])
        fetch = {
            "name": "fetch_url", "args": {"url": citation["url"]},
            "payload": {"ok": True, "content": "Revenue was reported for the year."},
            "receipt": {"raw_response_path": "tool-01.raw.json", "raw_response_sha256": "a" * 64},
        }
        self.assertEqual(subject.validate_report_evidence(report, [fetch])["status"], "PASS")
        search_only = {
            "name": "web_search", "args": {"query": "annual report"},
            "payload": {"ok": True, "results": [{"snippet": citation["quote"], "url": citation["url"]}]},
            "receipt": {},
        }
        result = subject.validate_report_evidence(report, [search_only])
        self.assertEqual(result["status"], "EVIDENCE_INSUFFICIENT")
        self.assertEqual(result["errors"][0]["status"], "URL_NOT_FETCHED")

    def test_request_policy_and_html_do_not_trigger_or_inject_canary_answer_types(self):
        packet = subject.load_package()
        row = next(item for item in packet["rows"] if item["港股代码"] == "00005")
        item = {
            "stock_code": row["港股代码"], "stock_name": row["中文简称"],
            "universe_date": subject.UNIVERSE_DATE, "row": row,
        }
        messages = subject.build_messages(item, packet["requirements_raw"].decode("utf-8"))
        request = subject.build_action_chat_request(messages)
        self.assertEqual(request["model"], "qwen3_8_flash_next")
        self.assertEqual(request["temperature"], 0.0)
        self.assertFalse(request["enable_thinking"])
        self.assertNotIn("tools", request)
        self.assertNotIn("response_format", request)
        self.assertEqual(request["structured_outputs"], {"json": subject.ACTION_SCHEMA})
        self.assertEqual(subject.ACTION_SCHEMA["properties"]["action"]["enum"], ["search", "fetch", "complete"])
        self.assertIn("task_instructions_verbatim", messages[1]["content"])
        self.assertIn("action_envelope_schema", messages[1]["content"])
        self.assertNotIn("canary_type", messages[1]["content"])
        self.assertNotIn("expected_answer", messages[1]["content"])
        self.assertNotIn("innerHTML", subject.HTML_PAGE)
        self.assertNotIn("/api/start-canary", subject.HTML_PAGE.split("refresh();setInterval(refresh,1500)")[0].split("async function refresh()")[0])

    def test_explicit_json_actions_dispatch_and_preserve_the_complete_report(self):
        with subject.EvidenceTransport("test-key", self.root, lambda _event: None) as transport:
            outputs = [
                {"action": "search", "query": "official annual report", "url": "", "report": None},
                {"action": "fetch", "query": "", "url": "https://example.com/report", "report": None},
                {"action": "complete", "query": "", "url": "", "report": {"raw": "unchanged"}},
            ]
            request_options = []

            def fake_stream(_messages, _on_event, *, tools=None, structured_outputs=None):
                transport.round_number += 1
                request_options.append((tools, structured_outputs))
                turn = subject.runner._StreamTurn()
                turn.content = [json.dumps(outputs[transport.round_number - 1], separators=(",", ":"))]
                turn.response_model = subject.MODEL_ID
                turn.usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
                return turn

            transport._stream_completion = fake_stream
            transport._call_web_tool = mock.Mock(side_effect=[
                ({"ok": True, "results": [{"url": "https://example.com/report"}]}, {"name": "web_search", "status": "ok"}),
                ({"ok": True, "content": "report body"}, {"name": "fetch_url", "status": "ok"}),
            ])
            result = transport.complete_review([{"role": "user", "content": "research"}], lambda _event: None)

        self.assertEqual(result["report"], {"raw": "unchanged"})
        self.assertEqual(result["final_text"], json.dumps(outputs[-1], separators=(",", ":")))
        self.assertEqual([call.args[0] for call in transport._call_web_tool.call_args_list], ["web_search", "fetch_url"])
        self.assertEqual(request_options, [([], {"json": subject.ACTION_SCHEMA})] * 3)
        self.assertEqual(result["metadata"]["request_rounds"], 3)
        self.assertEqual(result["metadata"]["usage"]["total_tokens"], 45)
        self.assertEqual((self.root / "round-01.action.raw").read_text(encoding="utf-8"), json.dumps(outputs[0], separators=(",", ":")))
        self.assertEqual((self.root / "round-03.action.raw").read_text(encoding="utf-8"), result["final_text"])

    def test_old_native_tool_like_array_is_rejected_without_dispatch(self):
        with subject.EvidenceTransport("test-key", self.root, lambda _event: None) as transport:
            def fake_stream(_messages, _on_event, *, tools=None, structured_outputs=None):
                transport.round_number += 1
                self.assertEqual(tools, [])
                self.assertEqual(structured_outputs, {"json": subject.ACTION_SCHEMA})
                turn = subject.runner._StreamTurn()
                turn.content = ['[{"name":"web_search","arguments":{"query":"query"}}]']
                turn.response_model = subject.MODEL_ID
                return turn

            transport._stream_completion = fake_stream
            transport._call_web_tool = mock.Mock()
            with self.assertRaisesRegex(subject.ModelProtocolFailure, "MODEL_ACTION_ENVELOPE_INVALID"):
                transport.complete_review([{"role": "user", "content": "research"}], lambda _event: None)

        transport._call_web_tool.assert_not_called()
        self.assertTrue((self.root / "round-01.action.raw").is_file())

    def test_native_tools_plus_json_mode_request_is_blocked_before_transport(self):
        with subject.EvidenceTransport("test-key", self.root, lambda _event: None) as transport:
            with self.assertRaisesRegex(subject.SystemFailure, "ACTION_REQUEST_POLICY_MISMATCH"):
                transport._stream_completion(
                    [{"role": "user", "content": "research"}],
                    lambda _event: None,
                    tools=subject.runner.make_tool_schema(),
                    structured_outputs=None,
                )
        self.assertFalse((self.root / "round-01.request.json").exists())
        self.assertFalse((self.root / "round-01.raw.sse").exists())

    def test_fetch_requires_public_https_search_result_url(self):
        self.assertEqual(
            subject._https_normalized_url("https://example.com/path?q=1#section"),
            "https://example.com/path?q=1",
        )
        for url in (
            "http://example.com/page",
            "https://localhost/private",
            "https://127.0.0.1/admin",
            "https://192.168.1.10/private",
        ):
            with self.subTest(url=url), self.assertRaises(subject.runner.BatchError):
                subject._https_normalized_url(url)

        transport = object.__new__(subject.EvidenceTransport)
        transport.qualified_search_urls = set()
        events = []
        payload, receipt = transport._call_web_tool(
            "fetch_url", {"url": "https://example.com/not-searched"}, events.append
        )
        self.assertEqual(payload["error"]["code"], "WEB_FETCH_URL_NOT_FROM_SEARCH")
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["error_code"], "WEB_FETCH_URL_NOT_FROM_SEARCH")

    def test_mojeek_tls_search_error_allows_only_a_distinct_model_query(self):
        failed = {
            "ok": False,
            "error": {
                "code": "provider_unavailable",
                "message": "DuckDuckGo search failed: RequestError('https://www.mojeek.com/search?q=broken > tls handshake eof')",
                "user_action_required": False,
            },
        }
        succeeded = {"ok": True, "provider": "ddgs", "results": [{"title": "Annual report", "url": "https://example.com/report", "snippet": "Official report"}]}
        responses = []
        for payload in (failed, succeeded):
            response = mock.Mock()
            response.status_code = 200
            response.json.return_value = payload
            response.content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            responses.append(response)

        with subject.EvidenceTransport("test-key", self.root, lambda _event: None, max_tool_calls=2) as transport:
            with mock.patch.object(transport._client, "post", side_effect=responses) as post:
                payload, receipt = transport._call_web_tool(
                    "web_search", {"query": "first query"}, lambda _event: None
                )
                self.assertEqual(payload["error"]["code"], "provider_unavailable")
                self.assertEqual(receipt["recovery_policy"], "ONE_DISTINCT_MODEL_QUERY_ALLOWED")
                with self.assertRaisesRegex(subject.ModelProtocolFailure, "WEB_SEARCH_QUERY_REPEATED_AFTER_PROVIDER_FAILURE"):
                    transport._call_web_tool("web_search", {"query": " FIRST   QUERY "}, lambda _event: None)
                next_payload, next_receipt = transport._call_web_tool(
                    "web_search", {"query": "a materially different query"}, lambda _event: None
                )
                self.assertTrue(next_payload["ok"])
                self.assertIsNone(next_receipt["recovery_policy"])
                self.assertEqual(post.call_count, 2)

        self.assertEqual(len(transport.tool_records), 2)
        self.assertTrue((self.root / "tool-01.raw.json").is_file())
        self.assertTrue((self.root / "tool-01.receipt.json").is_file())
        self.assertTrue((self.root / "tool-02.raw.json").is_file())
        self.assertTrue((self.root / "tool-02.receipt.json").is_file())

    def test_second_search_provider_unavailable_stops_after_recording_both_failures(self):
        failure_one = {
            "ok": False,
            "error": {"code": "provider_unavailable", "message": "https://www.mojeek.com/search?q=one > tls handshake eof"},
        }
        failure_two = {
            "ok": False,
            "error": {"code": "provider_unavailable", "message": "provider timed out"},
        }
        responses = []
        for payload in (failure_one, failure_two):
            response = mock.Mock()
            response.status_code = 200
            response.json.return_value = payload
            response.content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            responses.append(response)

        with subject.EvidenceTransport("test-key", self.root, lambda _event: None, max_tool_calls=2) as transport:
            with mock.patch.object(transport._client, "post", side_effect=responses) as post:
                _, first_receipt = transport._call_web_tool("web_search", {"query": "first query"}, lambda _event: None)
                self.assertEqual(first_receipt["recovery_policy"], "ONE_DISTINCT_MODEL_QUERY_ALLOWED")
                with self.assertRaisesRegex(subject.SystemFailure, "WEB_SEARCH_PROVIDER_UNAVAILABLE_AFTER_RECOVERY"):
                    transport._call_web_tool("web_search", {"query": "different query"}, lambda _event: None)
                self.assertEqual(post.call_count, 2)

        self.assertEqual(len(transport.tool_records), 2)
        self.assertTrue((self.root / "tool-02.raw.json").is_file())
        second_receipt = json.loads((self.root / "tool-02.receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(second_receipt["error_code"], "provider_unavailable")

    def test_unrelated_search_provider_unavailable_stops_without_retry(self):
        failure = {
            "ok": False,
            "error": {"code": "provider_unavailable", "message": "search backend unavailable"},
        }
        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = failure
        response.content = json.dumps(failure, separators=(",", ":")).encode("utf-8")

        with subject.EvidenceTransport("test-key", self.root, lambda _event: None) as transport:
            with mock.patch.object(transport._client, "post", return_value=response) as post:
                with self.assertRaisesRegex(
                    subject.SystemFailure, "WEB_SEARCH_PROVIDER_UNAVAILABLE_UNRECOVERABLE"
                ):
                    transport._call_web_tool(
                        "web_search", {"query": "one query"}, lambda _event: None
                    )
                self.assertEqual(post.call_count, 1)

        receipt = json.loads((self.root / "tool-01.receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["error_code"], "provider_unavailable")
        self.assertIsNone(receipt["recovery_policy"])
        self.assertTrue((self.root / "tool-01.raw.json").is_file())


if __name__ == "__main__":
    unittest.main()
