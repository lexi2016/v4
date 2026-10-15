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
        self.assertIn("fallback_on_empty", manifest["request_policy"]["search_route"]["empty_results"])
        self.assertIn("only_all_available_routes_empty", manifest["request_policy"]["search_route"]["empty_results"])
        self.assertEqual(
            manifest["request_policy"]["search_route"]["backend_order"][-1],
            "yahoo_loopback_system_https_proxy_once_on_error_or_empty",
        )
        self.assertIn("one_same_schema_complete_finalization_turn", manifest["request_policy"]["post_search_stop_policy"])
        self.assertEqual(
            manifest["request_policy"]["fetch_rate_limit_policy"]["shared_or_ambiguous_rate_limit"],
            "system_failure_stop",
        )
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
            "schema": subject.REPORT_SCHEMA_ID,
            "stock_code": item["stock_code"], "stock_name": item["stock_name"],
            "universe_date": subject.UNIVERSE_DATE, "report_status": "IN_PROGRESS",
            "relationships": [],
        }
        for letter in "ABCDEFGHIJ":
            report[letter] = {"assessment": "待核验", "claims": [], "unknowns": ["CANNOT_CONFIRM"]}
        source_text = "Revenue was reported for the year.\nThe report period ended in 2025."
        source_url = "https://example.com/annual-report"
        fetch_payload = {
            "ok": True, "title": "Annual report", "publication_date": "2025",
            "content": source_text,
        }
        fetch = {
            "name": "fetch_url", "args": {"url": source_url}, "payload": fetch_payload,
            "receipt": {"raw_response_path": "tool-01.raw.json", "raw_response_sha256": "a" * 64},
        }
        fetch["citation_sources"] = subject.build_citation_sources(fetch_payload, fetch)
        citation = {
            "source_id": fetch["citation_sources"][0]["source_id"],
            "unit_start_id": fetch["citation_sources"][0]["units"][0]["unit_id"],
            "unit_end_id": fetch["citation_sources"][0]["units"][0]["unit_id"],
        }
        report["A"]["claims"].append({
            "kind": "VERIFIED_FACT", "epistemic_status": "SUPPORTED_FACT",
            "claim": "财务披露包含营业收入信息。", "evidence": [citation],
        })
        report["E"]["claims"].append({
            "kind": "TRIGGER", "epistemic_status": "ASSUMPTION",
            "claim": "若后续披露显示订单增长，可作为待核触发条件。", "evidence": [],
        })
        self.assertEqual(subject.validate_report_structure(report, item), [])
        audit = subject.validate_report_evidence(report, [fetch])
        self.assertEqual(audit["status"], "PASS")
        projected = audit["projected_report"]
        projected_citation = projected["A"]["claims"][0]["evidence"][0]
        self.assertEqual(projected_citation["url"], source_url)
        self.assertEqual(projected_citation["title"], "Annual report")
        self.assertEqual(projected_citation["publication_date_or_period"], "2025")
        self.assertEqual(projected_citation["quote"], source_text)
        self.assertEqual(report["A"]["claims"][0]["evidence"][0], citation)
        self.assertEqual(audit["citation_projection_receipt"]["projections"][0]["fetch_response_sha256"], "a" * 64)

        search_only = {
            "name": "web_search", "args": {"query": "annual report"},
            "payload": {"ok": True, "results": [{"snippet": source_text, "url": source_url}]},
            "receipt": {},
        }
        result = subject.validate_report_evidence(report, [search_only])
        self.assertEqual(result["status"], "EVIDENCE_INSUFFICIENT")
        self.assertIn("SOURCE_ID_NOT_FETCHED_OR_INVALID", [error["status"] for error in result["errors"]])

    def test_epistemic_markers_keep_facts_and_relationships_evidence_bound(self):
        packet = subject.load_package()
        row = packet["rows"][0]
        item = {
            "source_index": 1, "stock_code": row["港股代码"],
            "stock_name": row["中文简称"], "universe_date": subject.UNIVERSE_DATE,
        }
        report = self._empty_report(item)
        report["A"]["claims"].append({
            "kind": "VERIFIED_FACT", "epistemic_status": "ASSUMPTION",
            "claim": "未经核实的事实。", "evidence": [],
        })
        errors = subject.validate_report_structure(report, item)
        self.assertTrue(any("VERIFIED_FACT_NOT_SOURCE_SUPPORTED" in error for error in errors))

        report = self._empty_report(item)
        report["A"]["claims"].append({
            "kind": "ANALYSIS", "epistemic_status": "INFERENCE",
            "claim": "推断但没有来源。", "evidence": [],
        })
        errors = subject.validate_report_structure(report, item)
        self.assertTrue(any("SUPPORTED_CLAIM_WITHOUT_EVIDENCE" in error for error in errors))

        report = self._empty_report(item)
        report["relationships"].append({
            "asset_identifier": "ABC", "asset_name": "Example", "exchange": "NYSE",
            "asset_class": "US_LISTED_COMPANY", "relation_type": "BUSINESS_PEER",
            "business_segment": "segment", "meaning": "specific relationship",
            "direction": "UNCERTAIN", "time_scale": "unknown", "invalidation": "unknown",
            "evidence_strength": "INSUFFICIENT", "evidence_reason": "pending source check",
            "action": "PENDING", "evidence": [],
        })
        errors = subject.validate_report_structure(report, item)
        self.assertIn("RELATIONSHIP_WITHOUT_EVIDENCE", errors)

    @staticmethod
    def _empty_report(item):
        report = {
            "schema": subject.REPORT_SCHEMA_ID,
            "stock_code": item["stock_code"], "stock_name": item["stock_name"],
            "universe_date": subject.UNIVERSE_DATE, "report_status": "IN_PROGRESS",
            "relationships": [],
        }
        for letter in "ABCDEFGHIJ":
            report[letter] = {"assessment": "待核验", "claims": [], "unknowns": ["CANNOT_CONFIRM"]}
        return report

    def test_source_unit_ranges_are_lossless_and_cannot_accept_model_quote_or_metadata(self):
        text = "开头。\n" + ("连续原文abc。" * 12) + "\n结尾。"
        first = subject.build_source_units(text, max_chars=24)
        second = subject.build_source_units(text, max_chars=24)
        self.assertEqual(first, second)
        self.assertEqual("".join(unit["text"] for unit in first), text)
        self.assertEqual(first[0]["char_start"], 0)
        self.assertEqual(first[-1]["char_end"], len(text))
        for left, right in zip(first, first[1:]):
            self.assertEqual(left["char_end"], right["char_start"])

        citation_with_untrusted_metadata = {
            "source_id": "fetch-01-text-01", "unit_start_id": "u0001",
            "unit_end_id": "u0001", "title": "", "publication_date_or_period": "",
            "quote": "fabricated ... stitched quote",
        }
        with self.assertRaisesRegex(ValueError, "ADDITIONAL_PROPERTIES"):
            subject.runner._validate_json_schema(citation_with_untrusted_metadata, subject.CITATION_SCHEMA)

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
        self.assertEqual(subject.CITATION_SCHEMA["required"][:3], ["source_id", "unit_start_id", "unit_end_id"])
        self.assertNotIn("quote", subject.CITATION_SCHEMA["properties"])
        self.assertNotIn("title", subject.CITATION_SCHEMA["properties"])
        self.assertNotIn("publication_date_or_period", subject.CITATION_SCHEMA["properties"])
        self.assertIn("epistemic_status", subject.CLAIM_SCHEMA["required"])
        self.assertIn("2026-10-15", messages[0]["content"])
        self.assertIn("2026-10-14", messages[0]["content"])
        self.assertIn("PDF_SOURCE_UNAVAILABLE", messages[0]["content"])
        self.assertIn("不能声称已读取 PDF 内容", messages[0]["content"])
        self.assertIn("task_instructions_verbatim", messages[1]["content"])
        self.assertIn("action_envelope_schema", messages[1]["content"])
        self.assertIn("或返回空结果", messages[0]["content"])
        self.assertIn("所有可用路由均返回空结果", messages[0]["content"])
        self.assertIn("只允许一轮 complete 收尾", messages[0]["content"])
        self.assertIn("共享 API 传输失败", messages[0]["content"])
        self.assertNotIn("canary_type", messages[1]["content"])
        self.assertNotIn("expected_answer", messages[1]["content"])
        self.assertNotIn("innerHTML", subject.HTML_PAGE)
        self.assertNotIn("/api/start-canary", subject.HTML_PAGE.split("refresh();setInterval(refresh,1500)")[0].split("async function refresh()")[0])

    def test_direct_results_stop_route_fallback_but_all_route_empty_is_non_error(self):
        rows = [{"title": "Annual report", "href": "https://example.com/report", "body": "Official source"}]
        direct_root = self.root / "direct"
        with subject.EvidenceTransport("test-key", direct_root, lambda _event: None) as transport:
            with mock.patch.object(subject, "_run_ddgs_text", return_value=rows) as search:
                with mock.patch.object(subject, "_loopback_system_https_proxy", side_effect=AssertionError("proxy not needed")):
                    payload, receipt = transport._call_web_tool(
                        "web_search", {"query": "annual report"}, lambda _event: None
                    )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["backend"], "duckduckgo")
            self.assertEqual(payload["results"][0]["url"], "https://example.com/report")
            self.assertEqual(receipt["selected_backend"], "duckduckgo")
            self.assertIsNone(receipt["selected_proxy_endpoint"])
            self.assertEqual(search.call_args.args, ("annual report", "duckduckgo"))
            self.assertEqual(search.call_args.kwargs, {"proxy": None})
        raw = json.loads((direct_root / "tool-01.raw.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["provider_results"][0]["href"], "https://example.com/report")
        receipt_file = json.loads((direct_root / "tool-01.receipt.json").read_text(encoding="utf-8"))
        self.assertNotIn("query", receipt_file)
        self.assertNotIn("results", receipt_file)

        empty_root = self.root / "empty"
        with subject.EvidenceTransport("test-key", empty_root, lambda _event: None) as transport:
            with mock.patch.object(subject, "_loopback_system_https_proxy", return_value="http://127.0.0.1:7897"):
                with mock.patch.object(subject, "_run_ddgs_text", return_value=[]) as empty_search:
                    payload, receipt = transport._call_web_tool(
                        "web_search", {"query": "no matching results"}, lambda _event: None
                    )
            self.assertEqual(empty_search.call_args_list, [
                mock.call("no matching results", "duckduckgo", proxy=None),
                mock.call("no matching results", "duckduckgo", proxy="http://127.0.0.1:7897"),
                mock.call("no matching results", "yahoo", proxy=None),
                mock.call("no matching results", "yahoo", proxy="http://127.0.0.1:7897"),
            ])
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["results"], [])
            self.assertEqual(receipt["status"], "ok")
            self.assertTrue(payload["allow_one_distinct_query_rewrite"])
            self.assertEqual([attempt["status"] for attempt in receipt["search_attempts"]], ["NO_RESULTS"] * 4)

    def test_same_query_empty_result_falls_through_existing_proxy_to_yahoo_results(self):
        rows = [{"title": "CLP Holdings annual report", "href": "https://example.com/clp", "body": "Official source"}]
        with subject.EvidenceTransport("test-key", self.root, lambda _event: None) as transport:
            with mock.patch.object(subject, "_loopback_system_https_proxy", return_value="http://127.0.0.1:7897"):
                with mock.patch.object(subject, "_run_ddgs_text", side_effect=[[], [], rows]) as search:
                    payload, receipt = transport._call_web_tool(
                        "web_search", {"query": "CLP Holdings 00002 annual report 2025 revenue segments"}, lambda _event: None
                    )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["backend"], "yahoo")
        self.assertEqual(payload["results"][0]["url"], "https://example.com/clp")
        self.assertEqual(search.call_args_list, [
            mock.call("CLP Holdings 00002 annual report 2025 revenue segments", "duckduckgo", proxy=None),
            mock.call("CLP Holdings 00002 annual report 2025 revenue segments", "duckduckgo", proxy="http://127.0.0.1:7897"),
            mock.call("CLP Holdings 00002 annual report 2025 revenue segments", "yahoo", proxy=None),
        ])
        self.assertEqual([attempt["status"] for attempt in receipt["search_attempts"]], ["NO_RESULTS", "NO_RESULTS", "RESULTS"])

    def test_same_query_yahoo_direct_error_falls_through_once_to_existing_proxy_results(self):
        rows = [{"title": "HSBC ADR information", "href": "https://example.com/adr", "body": "Ratio information"}]
        query = "HSBC Holdings ADS ratio NYSE ADR program"
        with subject.EvidenceTransport("test-key", self.root, lambda _event: None) as transport:
            with mock.patch.object(subject, "_loopback_system_https_proxy", return_value="http://127.0.0.1:7897"):
                with mock.patch.object(subject, "_run_ddgs_text", side_effect=[[], [], RuntimeError("DDGSException"), rows]) as search:
                    payload, receipt = transport._call_web_tool(
                        "web_search", {"query": query}, lambda _event: None
                    )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["backend"], "yahoo")
        self.assertEqual(payload["results"][0]["url"], "https://example.com/adr")
        self.assertEqual(search.call_args_list, [
            mock.call(query, "duckduckgo", proxy=None),
            mock.call(query, "duckduckgo", proxy="http://127.0.0.1:7897"),
            mock.call(query, "yahoo", proxy=None),
            mock.call(query, "yahoo", proxy="http://127.0.0.1:7897"),
        ])
        self.assertEqual(
            [attempt["status"] for attempt in receipt["search_attempts"]],
            ["NO_RESULTS", "NO_RESULTS", "ERROR", "RESULTS"],
        )
        self.assertEqual(receipt["search_attempts"][2]["error_type"], "DDGSException")
        self.assertEqual(receipt["selected_proxy_endpoint"], "http://127.0.0.1:7897")

    def test_stop_search_blocks_tool_action_and_allows_one_same_schema_finalization_turn(self):
        attempt_dir = self.root / "post-stop-finalization"
        attempt_dir.mkdir(parents=True)
        packet = subject.load_package()
        row = next(item for item in packet["rows"] if item["港股代码"] == "00005")
        item = {
            "stock_code": row["港股代码"], "stock_name": row["中文简称"],
            "universe_date": subject.UNIVERSE_DATE,
        }
        report = self._empty_report(item)
        blocked_search = json.dumps({
            "action": "search", "query": "third query after true empty", "url": "", "report": None,
        }, ensure_ascii=False)
        complete_action = json.dumps({
            "action": "complete", "query": "", "url": "", "report": report,
        }, ensure_ascii=False)
        existing_source = {
            "name": "fetch_url", "args": {"url": "https://example.com/source"},
            "payload": {"ok": True}, "receipt": {"raw_response_sha256": "a" * 64},
            "citation_sources": [{"source_id": "fetch-01-text-01", "units": []}],
        }
        observed_messages = []
        responses = iter([blocked_search, complete_action])
        with subject.EvidenceTransport("test-key", attempt_dir, lambda _event: None) as transport:
            transport.round_number = 7
            transport._empty_search_results = subject.MAX_EMPTY_SEARCHES
            transport.tool_records.append(existing_source)

            def fake_stream(messages, _on_event, **_kwargs):
                observed_messages.append([dict(message) for message in messages])
                transport.round_number += 1
                return mock.Mock(
                    content=[next(responses)], usage={}, response_model=subject.MODEL_ID,
                    first_event_at=None, first_content_at=None,
                )

            with mock.patch.object(transport, "_stream_completion", side_effect=fake_stream) as model_call:
                with mock.patch.object(transport, "_call_web_tool") as tool_call:
                    result = transport.complete_review([{"role": "user", "content": "frozen task"}], lambda _event: None)

        self.assertEqual(model_call.call_count, 2)
        tool_call.assert_not_called()
        self.assertEqual(result["metadata"]["request_rounds"], 9)
        self.assertEqual(result["metadata"]["finalization_only_rounds"], 1)
        self.assertEqual(result["metadata"]["tool_receipts"], [])
        self.assertEqual(result["report"], report)
        self.assertEqual(result["tool_records"], [existing_source])
        self.assertEqual((attempt_dir / "round-08.action.raw").read_text(), blocked_search)
        self.assertEqual((attempt_dir / "round-09.action.raw").read_text(), complete_action)
        self.assertEqual(observed_messages[1][-2], {"role": "assistant", "content": blocked_search})
        self.assertEqual(observed_messages[1][-1], {"role": "user", "content": subject.FINALIZATION_ONLY_MESSAGE})

    def test_finalization_turn_is_bounded_and_fetch_search_actions_are_not_dispatched(self):
        attempt_dir = self.root / "post-stop-finalization-bound"
        attempt_dir.mkdir(parents=True)
        blocked_fetch = json.dumps({
            "action": "fetch", "query": "", "url": "https://example.com/page", "report": None,
        })
        blocked_search = json.dumps({
            "action": "search", "query": "another query", "url": "", "report": None,
        })
        responses = iter([blocked_fetch, blocked_search])
        with subject.EvidenceTransport("test-key", attempt_dir, lambda _event: None) as transport:
            transport._empty_search_results = subject.MAX_EMPTY_SEARCHES

            def fake_stream(_messages, _on_event, **_kwargs):
                transport.round_number += 1
                return mock.Mock(
                    content=[next(responses)], usage={}, response_model=subject.MODEL_ID,
                    first_event_at=None, first_content_at=None,
                )

            with mock.patch.object(transport, "_stream_completion", side_effect=fake_stream) as model_call:
                with mock.patch.object(transport, "_call_web_tool") as tool_call:
                    with self.assertRaisesRegex(subject.ModelProtocolFailure, "FINALIZATION_ACTION_NOT_COMPLETE"):
                        transport.complete_review([{"role": "user", "content": "frozen task"}], lambda _event: None)
        self.assertEqual(model_call.call_count, 2)
        tool_call.assert_not_called()
        self.assertEqual((attempt_dir / "round-01.action.raw").read_text(), blocked_fetch)
        self.assertEqual((attempt_dir / "round-02.action.raw").read_text(), blocked_search)

    def test_in_progress_finalization_without_evidence_does_not_become_reviewed(self):
        root = subject.prepare_candidate(self.root)

        def fake_attempt(item, _attempt_dir, _on_event):
            report = self._empty_report(item)
            action = json.dumps({"action": "complete", "query": "", "url": "", "report": report}, ensure_ascii=False)
            return {
                "final_text": action,
                "report": report,
                "action_protocol_id": subject.ACTION_PROTOCOL_ID,
                "metadata": {"response_model": subject.MODEL_ID, "request_rounds": 1, "tool_receipts": []},
                "tool_records": [],
            }

        app = subject.CandidateApp(root, attempt_fn=fake_attempt)
        app._run_codes("RETRY_ONE", ["00005"])
        item = next(row for row in app.state["items"] if row["stock_code"] == "00005")
        self.assertEqual(item["status"], "IN_PROGRESS")
        self.assertEqual(item["latest_report_status"], "IN_PROGRESS")
        self.assertEqual(item["latest_evidence_status"], "EVIDENCE_INSUFFICIENT")
        self.assertFalse(app._canary_passed())

    def test_fetch_writes_source_units_bound_to_raw_response_sha(self):
        attempt_dir = self.root / "fetch-attempt"
        attempt_dir.mkdir(parents=True)
        source_url = "https://example.com/annual-report"
        payload = {
            "ok": True,
            "title": "Annual report",
            "publication_date": "2025",
            "content": "Revenue was reported.\nOperating profit improved.",
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        response = mock.Mock(status_code=200, content=raw)
        response.json.return_value = payload
        with subject.EvidenceTransport("test-key", attempt_dir, lambda _event: None) as transport:
            transport.qualified_search_urls.add(source_url)
            with mock.patch.object(transport._client, "post", return_value=response):
                fetched, receipt = transport._call_web_tool(
                    "fetch_url", {"url": source_url}, lambda _event: None
                )
        self.assertTrue(fetched["ok"])
        raw_sha = subject._sha(raw)
        self.assertEqual(receipt["raw_response_sha256"], raw_sha)
        source_path = attempt_dir / receipt["source_units_path"]
        source_bytes = source_path.read_bytes()
        self.assertEqual(subject._sha(source_bytes), receipt["source_units_sha256"])
        source_document = json.loads(source_bytes)
        self.assertEqual(source_document["fetch_response_sha256"], raw_sha)
        source = source_document["sources"][0]
        self.assertEqual(source["fetch_response_sha256"], raw_sha)
        self.assertEqual("".join(unit["text"] for unit in source["units"]), payload["content"])
        stored_receipt = json.loads((attempt_dir / "tool-01.receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(stored_receipt["citation_sources"][0]["text_sha256"], source["text_sha256"])

    def test_unsupported_pdf_fetch_is_recorded_as_source_gap_and_not_system_failure(self):
        attempt_dir = self.root / "pdf-attempt"
        attempt_dir.mkdir(parents=True)
        source_url = "https://example.com/annual-report.pdf"
        payload = {
            "ok": False,
            "error": {
                "code": "invalid_response",
                "message": "Content type 'application/pdf' is not supported",
            },
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        response = mock.Mock(status_code=200, content=raw)
        response.json.return_value = payload
        with subject.EvidenceTransport("test-key", attempt_dir, lambda _event: None) as transport:
            transport.qualified_search_urls.add(source_url)
            with mock.patch.object(transport._client, "post", return_value=response):
                fetched, receipt = transport._call_web_tool(
                    "fetch_url", {"url": source_url}, lambda _event: None
                )
        self.assertFalse(fetched["ok"])
        self.assertEqual(fetched["error"]["code"], "invalid_response")
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse(receipt.get("system_failure_code"))
        self.assertNotIn("source_units_path", receipt)
        self.assertEqual(transport.tool_records[0]["citation_sources"], [])

    def test_explicit_target_url_429_preserves_raw_gap_blocks_same_host_and_allows_other_hosts(self):
        attempt_dir = self.root / "target-url-429"
        attempt_dir.mkdir(parents=True)
        source_url = "https://ir.theice.com/press/news-details/2021/NYSE-to-Commence-Delisting-Proceedings/default.aspx"
        same_host_url = "https://ir.theice.com/another-source"
        other_host_url = "https://other.example/report"
        rate_limited_payload = {
            "ok": False,
            "error": {
                "code": "rate_limited",
                "message": subject.TARGET_URL_RATE_LIMIT_MESSAGE,
                "user_action_required": False,
            },
        }
        rate_limited_raw = json.dumps(rate_limited_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        rate_limited_response = mock.Mock(status_code=200, content=rate_limited_raw)
        rate_limited_response.json.return_value = rate_limited_payload
        other_payload = {
            "ok": True, "title": "Other source", "publication_date": "2025",
            "content": "The other source contains a readable fact.",
        }
        other_raw = json.dumps(other_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        other_response = mock.Mock(status_code=200, content=other_raw)
        other_response.json.return_value = other_payload

        with subject.EvidenceTransport("test-key", attempt_dir, lambda _event: None) as transport:
            transport.qualified_search_urls.update({source_url, same_host_url, other_host_url})
            with mock.patch.object(transport._client, "post", side_effect=[rate_limited_response, other_response]) as api:
                failed, receipt = transport._call_web_tool("fetch_url", {"url": source_url}, lambda _event: None)
                cached, cached_receipt = transport._call_web_tool("fetch_url", {"url": source_url}, lambda _event: None)
                blocked, blocked_receipt = transport._call_web_tool("fetch_url", {"url": same_host_url}, lambda _event: None)
                allowed, _allowed_receipt = transport._call_web_tool("fetch_url", {"url": other_host_url}, lambda _event: None)

        self.assertFalse(failed["ok"])
        self.assertEqual(failed["error"]["code"], "rate_limited")
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["error_code"], "rate_limited")
        self.assertEqual(receipt["http_status"], 200)
        self.assertEqual(receipt["recovery_policy"], "target_url_http_429_no_same_hostname_fetch_retry")
        self.assertEqual(cached["error"]["code"], "rate_limited")
        self.assertTrue(cached_receipt["reused_cached_result"])
        self.assertEqual(blocked["error"]["code"], "WEB_SOURCE_HOST_RATE_LIMITED_NO_RETRY")
        self.assertEqual(blocked_receipt["http_status"], None)
        self.assertTrue(allowed["ok"])
        self.assertEqual(api.call_count, 2)
        stored_raw = attempt_dir / "tool-01.raw.json"
        self.assertEqual(stored_raw.read_bytes(), rate_limited_raw)
        stored_receipt = json.loads((attempt_dir / "tool-01.receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(stored_receipt["raw_response_sha256"], subject._sha(rate_limited_raw))
        self.assertEqual(stored_receipt["recovery_policy"], "target_url_http_429_no_same_hostname_fetch_retry")

    def test_ambiguous_rate_limit_and_shared_http_429_remain_system_failures_with_raw_preserved(self):
        cases = [
            (
                "ambiguous-envelope",
                200,
                {"ok": False, "error": {"code": "rate_limited", "message": "Rate limit attribution unavailable"}},
                "WEB_ROUTE_SYSTEM_FAILURE:rate_limited",
            ),
            (
                "shared-http-429",
                429,
                {"ok": False, "error": {"code": "rate_limited", "message": "The shared fetch route is rate limited"}},
                "WEB_HTTP_STATUS_429",
            ),
        ]
        for name, status_code, payload, expected_failure in cases:
            with self.subTest(name=name):
                attempt_dir = self.root / name
                attempt_dir.mkdir(parents=True)
                raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                response = mock.Mock(status_code=status_code, content=raw)
                response.json.return_value = payload
                source_url = "https://example.com/target"
                with subject.EvidenceTransport("test-key", attempt_dir, lambda _event: None) as transport:
                    transport.qualified_search_urls.add(source_url)
                    with mock.patch.object(transport._client, "post", return_value=response):
                        with self.assertRaisesRegex(subject.SystemFailure, expected_failure):
                            transport._call_web_tool("fetch_url", {"url": source_url}, lambda _event: None)
                self.assertEqual((attempt_dir / "tool-01.raw.json").read_bytes(), raw)
                receipt = json.loads((attempt_dir / "tool-01.receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(receipt["status"], "failed")
                self.assertEqual(receipt["raw_response_sha256"], subject._sha(raw))

    def test_search_failover_is_bounded_and_uses_only_existing_loopback_proxy(self):
        rows = [{"title": "CNOOC report", "href": "https://example.com/cnooc", "body": "Official"}]
        with subject.EvidenceTransport("test-key", self.root, lambda _event: None) as transport:
            with mock.patch.object(subject, "_loopback_system_https_proxy", return_value="http://127.0.0.1:7897"):
                with mock.patch.object(
                    subject, "_run_ddgs_text",
                    side_effect=[RuntimeError("DDGSException"), RuntimeError("DDGSException"), rows],
                ) as search:
                    payload, receipt = transport._call_web_tool(
                        "web_search", {"query": "CNOOC annual report"}, lambda _event: None
                    )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["backend"], "yahoo")
        self.assertEqual(search.call_args_list, [
            mock.call("CNOOC annual report", "duckduckgo", proxy=None),
            mock.call("CNOOC annual report", "duckduckgo", proxy="http://127.0.0.1:7897"),
            mock.call("CNOOC annual report", "yahoo", proxy=None),
        ])
        self.assertEqual(receipt["selected_backend"], "yahoo")
        self.assertIsNone(receipt["selected_proxy_endpoint"])
        self.assertEqual(receipt["search_attempts"][1]["proxy_endpoint"], "http://127.0.0.1:7897")
        self.assertEqual([attempt["result_count"] for attempt in receipt["search_attempts"]], [0, 0, 1])
        self.assertTrue(all("elapsed_seconds" in attempt for attempt in receipt["search_attempts"]))
        self.assertTrue(all("error_type" in attempt for attempt in receipt["search_attempts"][:2]))

    def test_second_empty_search_stops_before_a_third_provider_call(self):
        with subject.EvidenceTransport("test-key", self.root, lambda _event: None) as transport:
            with mock.patch.object(subject, "_loopback_system_https_proxy", return_value="http://127.0.0.1:7897"):
                with mock.patch.object(subject, "_run_ddgs_text", return_value=[]) as search:
                    first, _ = transport._call_web_tool("web_search", {"query": "first"}, lambda _event: None)
                    second, _ = transport._call_web_tool("web_search", {"query": "second"}, lambda _event: None)
                self.assertFalse(first["stop_searching"])
                self.assertTrue(second["stop_searching"])
                with self.assertRaisesRegex(subject.ModelProtocolFailure, "EMPTY_SEARCH_QUERY_REWRITE_LIMIT_REACHED"):
                    transport._call_web_tool("web_search", {"query": "third"}, lambda _event: None)
                self.assertEqual(search.call_count, 8)

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

    def test_all_search_backends_failing_records_failure_then_stops(self):
        with subject.EvidenceTransport("test-key", self.root, lambda _event: None) as transport:
            with mock.patch.object(subject, "_loopback_system_https_proxy", return_value=None):
                with mock.patch.object(
                    subject, "_run_ddgs_text", side_effect=[RuntimeError("DDGSException"), RuntimeError("DDGSException")]
                ) as search:
                    with self.assertRaisesRegex(subject.SystemFailure, "SEARCH_BACKENDS_UNAVAILABLE"):
                        transport._call_web_tool("web_search", {"query": "one query"}, lambda _event: None)
        self.assertEqual(search.call_count, 2)
        receipt = json.loads((self.root / "tool-01.receipt.json").read_text(encoding="utf-8"))
        raw = json.loads((self.root / "tool-01.raw.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["error_code"], "search_backends_unavailable")
        self.assertEqual([row["backend"] for row in raw["search_attempts"]], ["duckduckgo", "yahoo"])
        self.assertEqual([row["status"] for row in raw["search_attempts"]], ["ERROR", "ERROR"])
        self.assertEqual([row["result_count"] for row in raw["search_attempts"]], [0, 0])
        self.assertTrue((self.root / "tool-01.request.json").is_file())

    def test_route_error_mixed_with_empty_results_is_not_reported_as_true_empty(self):
        with subject.EvidenceTransport("test-key", self.root, lambda _event: None) as transport:
            with mock.patch.object(subject, "_loopback_system_https_proxy", return_value="http://127.0.0.1:7897"):
                with mock.patch.object(
                    subject, "_run_ddgs_text",
                    side_effect=[RuntimeError("DDGSException"), [], RuntimeError("DDGSException"), []],
                ):
                    with self.assertRaisesRegex(subject.SystemFailure, "SEARCH_BACKENDS_UNAVAILABLE"):
                        transport._call_web_tool("web_search", {"query": "one query"}, lambda _event: None)
        receipt = json.loads((self.root / "tool-01.receipt.json").read_text(encoding="utf-8"))
        raw = json.loads((self.root / "tool-01.raw.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual([row["status"] for row in raw["search_attempts"]], ["ERROR", "NO_RESULTS", "ERROR", "NO_RESULTS"])

    def test_repeated_search_query_is_blocked_without_another_provider_call(self):
        with subject.EvidenceTransport("test-key", self.root, lambda _event: None) as transport:
            with mock.patch.object(subject, "_loopback_system_https_proxy", return_value=None):
                with mock.patch.object(subject, "_run_ddgs_text", return_value=[]) as search:
                    transport._call_web_tool("web_search", {"query": "annual report"}, lambda _event: None)
                with self.assertRaisesRegex(subject.ModelProtocolFailure, "WEB_SEARCH_QUERY_REPEATED"):
                    transport._call_web_tool("web_search", {"query": " Annual   Report "}, lambda _event: None)
                self.assertEqual(search.call_count, 2)

    def test_loopback_https_proxy_discovery_uses_existing_setting_only(self):
        response = mock.Mock(returncode=0, stdout="""<dictionary> {
  HTTPSProxy : 127.0.0.1
  HTTPSPort : 7897
  HTTPSEnable : 1
}
""")
        with mock.patch.object(subject.subprocess, "run", return_value=response):
            self.assertEqual(subject._loopback_system_https_proxy(), "http://127.0.0.1:7897")
        response.stdout = """<dictionary> {
  HTTPSProxy : proxy.example.com
  HTTPSPort : 7897
  HTTPSEnable : 1
}
"""
        with mock.patch.object(subject.subprocess, "run", return_value=response):
            self.assertIsNone(subject._loopback_system_https_proxy())


if __name__ == "__main__":
    unittest.main()
