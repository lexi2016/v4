from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import batch_runner as runner


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def synthetic_batch(body: str = "敏华公告：Southern Motion预估收入增长，未经审计。") -> dict[str, Any]:
    product_listing = "1" * 64
    product_cache = "2" * 64
    row_listing = "3" * 64
    row_cache = "4" * 64
    article_id = "EASTMONEY:AN202610131830380019:HK.01999"
    return {
        "schema": runner.INPUT_SCHEMA,
        "batch_id": "synthetic-unit-batch",
        "expected_count": 1,
        "source_products": [
            {"source_ref": "synthetic://bound-listing", "sha256": product_listing},
            {"source_ref": "synthetic://body-cache", "sha256": product_cache},
        ],
        "articles": [
            {
                "article_id": article_id,
                "source_sha256": "5" * 64,
                "body_sha256": sha(body),
                "article_body": body,
                "article_metadata": {
                    "publication_date": "2026-10-13",
                    "title": "盈利警告",
                    "issuer_name": "敏华控股有限公司",
                    "source_issuer_codes": [
                        {"code": "HK.01999", "name": "敏华控股有限公司", "market_code": "116"}
                    ],
                    "symbol": "HK.01999",
                    "observed_at": "2026-10-13T12:00:00+08:00",
                    "available_at": "2026-10-13T12:00:00+08:00",
                    "pit_status": "CANNOT_CONFIRM",
                    "source_origins": [
                        {
                            "source_ref": "synthetic://bound-listing/row/799",
                            "source_product_sha256": product_listing,
                            "source_row_index": 799,
                            "row_fingerprint_sha256": row_listing,
                        },
                        {
                            "source_ref": "synthetic://body-cache/row/1",
                            "source_product_sha256": product_cache,
                            "source_row_index": 1,
                            "row_fingerprint_sha256": row_cache,
                        },
                    ],
                },
            }
        ],
    }


def reader_output(article: dict[str, Any]) -> dict[str, Any]:
    return {
        "disposition": "NOT_ASSESSED",
        "selection_basis": "NOT_ASSESSED",
        "direction": "UNKNOWN",
        "evidence_sufficiency": "INSUFFICIENT_EXISTING_FACTS",
        "reason": "Synthetic fixture has no independent assessment.",
        "risk_notes": ["synthetic test fixture"],
        "facts": [],
        "changes": [],
        "impact": [],
        "confirmation_conditions": [],
        "counter_evidence": [],
        "source_sha256": article["source_sha256"],
        "body_sha256": article["body_sha256"],
    }


def sse_response(chunks: list[dict[str, Any]]) -> httpx.Response:
    payload = "".join("data: " + json.dumps(item, ensure_ascii=False) + "\n\n" for item in chunks)
    payload += "data: [DONE]\n\n"
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=payload.encode("utf-8"),
    )


class BatchRunnerTests(unittest.TestCase):
    def test_batch_validation_preserves_exact_body_and_two_origins(self) -> None:
        batch = synthetic_batch("  公告\nSouthern Motion：预计增长，未经审计。\n ")
        validated = runner.validate_batch(batch)
        self.assertEqual(validated[0]["article_body"], "  公告\nSouthern Motion：预计增长，未经审计。\n ")
        messages = runner.build_messages(batch, runner.load_active_contract())
        content = messages[1]["content"]
        embedded = json.loads(content.removeprefix("ARTICLE_DATA_BEGIN\n").removesuffix("\nARTICLE_DATA_END"))
        self.assertEqual(embedded["articles"][0]["article_body"], batch["articles"][0]["article_body"])
        self.assertIn("source_origins", batch["articles"][0]["article_metadata"])
        self.assertIn("source_issuer_codes", batch["articles"][0]["article_metadata"])
        self.assertNotIn("source_origins", content)
        self.assertNotIn("source_issuer_codes", content)
        self.assertNotIn("row_fingerprint_sha256", content)
        self.assertEqual(embedded["articles"][0]["article_metadata"]["pit_status"], "CANNOT_CONFIRM")
        self.assertIn("Southern Motion", runner.build_system_prompt(runner.load_active_contract()))

    def test_batch_validation_rejects_body_hash_mismatch(self) -> None:
        batch = synthetic_batch()
        batch["articles"][0]["body_sha256"] = "a" * 64
        with self.assertRaisesRegex(runner.BatchError, "ARTICLE_BODY_SHA_MISMATCH"):
            runner.validate_batch(batch)

    def test_prepare_counts_full_message_without_calling_model(self) -> None:
        batch = synthetic_batch()
        contract = runner.load_active_contract()
        with mock.patch.object(runner, "count_prompt_tokens", return_value=1234) as counter:
            receipt = runner.prepare_batch(
                batch, contract, tokenizer_path=Path("synthetic"), context_limit=262144,
                runtime_limits={"context_limit_tokens": 262144, "completion_max_tokens": 32768,
                                "completion_limit_resolution": "GLOBAL_MAX_TOKENS"},
            )
        self.assertEqual(receipt["prompt_tokens_exact_initial_request"], 1234)
        self.assertEqual(receipt["theoretical_remaining_tokens"], 260910)
        self.assertEqual(receipt["status"], "INPUT_FITS")
        self.assertEqual(receipt["context_limit_tokens"], 262144)
        self.assertEqual(receipt["article_manifest"][0]["body_sha256"], batch["articles"][0]["body_sha256"])
        self.assertTrue(receipt["web_tools_enabled"])
        self.assertIsNone(receipt["thinking_request_override"])
        self.assertEqual(receipt["completion_max_tokens_effective"], 32768)
        self.assertIsNone(receipt["completion_request_override"])
        counter.assert_called_once()

    def test_context_resolution_uses_native_config_before_global_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_config = root / "config.json"
            settings = root / "settings.json"
            model_settings = root / "model_settings.json"
            model_config.write_text(json.dumps({"text_config": {"max_position_embeddings": 262144}}))
            settings.write_text(json.dumps({"sampling": {
                "max_context_window": 32768,
                "max_context_window_policy": None,
                "max_tokens": 32768,
            }}))
            model_settings.write_text(json.dumps({"models": {runner.MODEL_ID: {
                "max_context_window": None,
                "max_tokens": None,
            }}}))
            limits = runner.load_runtime_limits(
                model_config_path=model_config,
                settings_path=settings,
                model_settings_path=model_settings,
            )
        self.assertEqual(limits["context_limit_tokens"], 262144)
        self.assertEqual(limits["context_resolution"], "MODEL_NATIVE_CONTEXT")
        self.assertEqual(limits["global_context_fallback_tokens"], 32768)
        self.assertIsNone(limits["global_context_policy_cap_tokens"])
        self.assertIsNone(limits["per_model_context_override_tokens"])
        self.assertEqual(limits["completion_max_tokens"], 32768)
        self.assertEqual(limits["completion_limit_resolution"], "GLOBAL_MAX_TOKENS")

    def test_tokenizer_count_uses_batch_encoding_input_ids(self) -> None:
        class FakeTokenizer:
            def apply_chat_template(self, messages: Any, **kwargs: Any) -> dict[str, Any]:
                return {"input_ids": [7, 8, 9, 10], "attention_mask": [1, 1, 1, 1]}

        fake_auto = types.SimpleNamespace(from_pretrained=lambda *args, **kwargs: FakeTokenizer())
        fake_transformers = types.SimpleNamespace(AutoTokenizer=fake_auto)
        with mock.patch.dict(sys.modules, {"transformers": fake_transformers}):
            count = runner.count_prompt_tokens([], [], tokenizer_path=Path("synthetic"))
        self.assertEqual(count, 4)

    def test_active_contract_validator_requires_exact_source_quote(self) -> None:
        batch = synthetic_batch("Revenue was estimated at 10 million and unaudited.")
        article = batch["articles"][0]
        output = reader_output(article)
        contract = runner.load_active_contract()
        output["disposition"] = "SELECTED_PERFORMANCE"
        output["selection_basis"] = "PERFORMANCE_RESEARCH"
        output["direction"] = "POSITIVE"
        output["evidence_sufficiency"] = "VERIFIED_EXISTING_FACTS"
        for field in ("facts", "changes", "impact", "confirmation_conditions", "counter_evidence"):
            output[field] = [{"claim": "estimate", "quote": "10 million audited", "locator": "body"}]
        with self.assertRaisesRegex(ValueError, "ANNOUNCEMENT_UNSUPPORTED_SOURCE_QUOTE"):
            contract.validate_reader(article["article_body"], article, output)

    def test_mock_streaming_web_tool_round_redacts_reasoning_and_suppresses_duplicate(self) -> None:
        batch = synthetic_batch()
        article = batch["articles"][0]
        final_text = json.dumps(
            {"results": [{"article_id": article["article_id"], "reader_output": reader_output(article)}]},
            ensure_ascii=False,
        )
        calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content) if request.content else {}
            calls.append((request.url.path, body, dict(request.headers)))
            if request.url.path == "/v1/chat/completions":
                self.assertEqual(request.headers.get("authorization"), "Bearer test-secret")
                self.assertEqual(body["model"], runner.MODEL_ID)
                self.assertTrue(body["stream"])
                self.assertEqual(body["stream_options"], {"include_usage": True})
                self.assertEqual(body["response_format"], {"type": "json_object"})
                self.assertNotIn("thinking_budget", body)
                self.assertNotIn("enable_thinking", body)
                self.assertNotIn("temperature", body)
                if not any(message.get("role") == "tool" for message in body["messages"]):
                    delta_calls = [
                        {"index": 0, "id": "call_1", "type": "function", "function": {"name": "web_search", "arguments": '{"query":"Southern Motion estimate"}'}},
                        {"index": 1, "id": "call_2", "type": "function", "function": {"name": "web_search", "arguments": '{"query":"southern   motion   estimate"}'}},
                    ]
                    return sse_response(
                        [
                            {
                                "model": runner.MODEL_ID,
                                "choices": [{"index": 0, "delta": {"reasoning_content": "SECRET_REASONING_SENTINEL"}, "finish_reason": None}],
                            },
                            {
                                "choices": [{"index": 0, "delta": {"content": "Checking source…", "tool_calls": delta_calls}, "finish_reason": "tool_calls"}],
                            },
                            {"choices": [], "usage": {"prompt_tokens": 1200, "completion_tokens": 20, "total_tokens": 1220}},
                        ]
                    )
                continuation = next(message for message in body["messages"] if message.get("role") == "assistant" and message.get("tool_calls"))
                self.assertEqual(continuation.get("reasoning_content"), "SECRET_REASONING_SENTINEL")
                tool_messages = [message for message in body["messages"] if message.get("role") == "tool"]
                self.assertEqual(len(tool_messages), 2)
                self.assertEqual(tool_messages[0]["content"], tool_messages[1]["content"])
                return sse_response(
                    [
                        {"choices": [{"index": 0, "delta": {"content": final_text}, "finish_reason": None}]},
                        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                        {"choices": [], "usage": {"prompt_tokens": 800, "completion_tokens": 200, "total_tokens": 1000}},
                    ]
                )
            if request.url.path == "/v1/web/search":
                self.assertEqual(body, {"query": "Southern Motion estimate"})
                return httpx.Response(
                    200,
                    json={"ok": True, "results": [{"title": "Source", "url": "https://example.com/source", "snippet": "Estimate"}]},
                )
            self.fail(f"unexpected route: {request.url.path}")

        events: list[dict[str, Any]] = []
        with runner.OmlxTransport("test-secret", http_transport=httpx.MockTransport(handler)) as transport:
            result = transport.complete_batch(
                runner.build_messages(batch, runner.load_active_contract()), on_event=events.append
            )
        self.assertEqual(len([call for call in calls if call[0] == "/v1/chat/completions"]), 2)
        self.assertEqual(len([call for call in calls if call[0] == "/v1/web/search"]), 1)
        self.assertEqual(result.usage, {"prompt_tokens": 2000, "completion_tokens": 220, "total_tokens": 2220})
        self.assertEqual(result.final_text, final_text)
        self.assertEqual(sum(1 for item in result.tool_receipts if item["reused_cached_result"]), 1)
        emitted = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("SECRET_REASONING_SENTINEL", emitted)
        self.assertNotIn("test-secret", emitted)
        self.assertTrue(any(item.get("type") == "answer_chunk" for item in events))

    def test_reader_batch_output_uses_active_validator_and_exact_id_conservation(self) -> None:
        batch = synthetic_batch()
        article = batch["articles"][0]
        text = json.dumps(
            {"results": [{"article_id": article["article_id"], "reader_output": reader_output(article)}]},
            ensure_ascii=False,
        )
        outputs, errors = runner._validate_batch_output(text, batch, runner.load_active_contract())
        self.assertEqual(errors, {})
        self.assertEqual(set(outputs), {article["article_id"]})
        malformed, errors = runner._validate_batch_output("not-json", batch, runner.load_active_contract())
        self.assertEqual(malformed, {})
        self.assertEqual(errors[article["article_id"]], "MODEL_OUTPUT_INVALID_JSON")

    def test_malformed_fetch_url_returns_tool_error_and_batch_continues(self) -> None:
        batch = synthetic_batch()
        article = batch["articles"][0]
        final_text = json.dumps(
            {"results": [{"article_id": article["article_id"], "reader_output": reader_output(article)}]},
            ensure_ascii=False,
        )
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            if request.url.path == "/v1/chat/completions":
                body = json.loads(request.content) if request.content else {}
                if not any(message.get("role") == "tool" for message in body["messages"]):
                    return sse_response(
                        [
                            {
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": [{
                                            "index": 0,
                                            "id": "malformed_url_call",
                                            "type": "function",
                                            "function": {
                                                "name": "fetch_url",
                                                "arguments": json.dumps({"url": "http://[::zz]/bad"}),
                                            },
                                        }]
                                    },
                                    "finish_reason": "tool_calls",
                                }]
                            },
                            {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105}},
                        ]
                    )
                tool_result = next(message["content"] for message in body["messages"] if message.get("role") == "tool")
                self.assertEqual(json.loads(tool_result), {"ok": False, "error": {"code": "WEB_FETCH_ARGUMENT_INVALID"}})
                return sse_response(
                    [
                        {"choices": [{"index": 0, "delta": {"content": final_text}, "finish_reason": None}]},
                        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                        {"choices": [], "usage": {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220}},
                    ]
                )
            self.fail(f"malformed URL must not reach web route: {request.url.path}")

        with runner.OmlxTransport("test-secret", http_transport=httpx.MockTransport(handler)) as transport:
            result = transport.complete_batch(runner.build_messages(batch, runner.load_active_contract()))
        self.assertEqual(requests, ["/v1/chat/completions", "/v1/chat/completions"])
        self.assertEqual(len(result.tool_receipts), 1)
        self.assertEqual(result.tool_receipts[0]["status"], "failed")
        self.assertEqual(result.final_text, final_text)

    def test_receipts_are_per_id_and_do_not_persist_body_or_reasoning(self) -> None:
        batch = synthetic_batch()
        article = batch["articles"][0]
        output = reader_output(article)
        prepare = {"status": "INPUT_FITS", "prompt_tokens_exact_initial_request": 1234}
        with tempfile.TemporaryDirectory() as temp:
            directory = runner.write_receipts(
                batch,
                "f" * 64,
                prepare,
                result_status_by_id={article["article_id"]: "READER_OUTPUT_VALIDATED"},
                reader_outputs={article["article_id"]: output},
                output_root=Path(temp),
            )
            files = list(directory.glob("*.json"))
            self.assertEqual(len(files), 2)
            artifact = json.loads(next(path.read_text() for path in files if path.name != "run-receipt.json"))
            serialized = json.dumps(artifact, ensure_ascii=False)
            self.assertNotIn(article["article_body"], serialized)
            self.assertEqual(artifact["formal_selection"], "CANNOT_CONFIRM_REQUIRES_INDEPENDENT_REVIEW")
            self.assertEqual(artifact["pit_status"], "CANNOT_CONFIRM")

    def test_runtime_limit_receipt_does_not_fingerprint_secret_bearing_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_config = root / "config.json"
            settings = root / "settings.json"
            model_settings = root / "model_settings.json"
            model_config.write_text(json.dumps({"text_config": {"max_position_embeddings": 262144}}))
            settings.write_text(json.dumps({"auth": {"api_key": "do-not-copy"}, "sampling": {
                "max_context_window": 32768,
                "max_context_window_policy": None,
                "max_tokens": 32768,
            }}))
            model_settings.write_text(json.dumps({"models": {runner.MODEL_ID: {}}}))
            limits = runner.load_runtime_limits(
                model_config_path=model_config,
                settings_path=settings,
                model_settings_path=model_settings,
            )
        serialized = json.dumps(limits)
        self.assertNotIn("do-not-copy", serialized)
        self.assertNotIn("global_settings_sha256", limits)
        self.assertIn("global_sampling_contract_sha256", limits)


if __name__ == "__main__":
    unittest.main()
