from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import httpx

import automatic_canary_server as canary
import batch_runner as runner
import announcement_queue as queue_module

sys.path.insert(0, str(Path(__file__).resolve().parent / "evidence" / "recent-day-20261014"))
import recent_day_freeze as recent_day

from test_batch_runner import reader_output, synthetic_batch


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sse(content: str) -> bytes:
    chunks = [
        {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}], "model": canary.MODEL_ID},
        {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}, "model": canary.MODEL_ID},
    ]
    return b"".join(
        b"data: " + json.dumps(item, ensure_ascii=False).encode("utf-8") + b"\n\n"
        for item in chunks
    ) + b"data: [DONE]\n\n"


class AnnouncementRootCauseTests(unittest.TestCase):
    def test_range_profile_separates_event_status_from_economic_direction(self) -> None:
        contract = runner.load_active_contract()
        prompt = runner.build_system_prompt(contract, runner.SIMPLE_WORKFLOW_RANGE_PROFILE)
        self.assertNotIn("facts 和 changes 必须都输出空数组", prompt)
        self.assertNotIn("facts 和 changes 均为 []", prompt)
        self.assertIn("facts 必须输出空数组", prompt)
        self.assertIn("changes 中填写正文披露且符合既有标准的经营/业绩变化", prompt)
        self.assertIn("不会从固定账本生成、删除、替换或改写 changes", prompt)
        self.assertIn("事件发生/状态完成”和“经营或业绩方向”分开判断", prompt)
        self.assertIn("完成本身不证明收入、利润、现金流、产能、协同、前景或其他经济效益为正", prompt)
        self.assertIn("必须另有公告直接披露的经营或业绩利益/改善", prompt)
        self.assertIn("不要机械改写或预定 disposition", prompt)
        self.assertIn("start_source_unit_id", prompt)
        self.assertIn("end_source_unit_id", prompt)
        single_prompt = runner.build_system_prompt(contract, runner.SIMPLE_WORKFLOW_PROFILE)
        self.assertTrue(single_prompt.startswith(runner.SIMPLE_WORKFLOW_PROMPT))
        self.assertIn("facts 和 changes 必须都输出空数组", single_prompt)
        self.assertIn("facts 和 changes 均为 []", single_prompt)
        wire_schema = runner.build_simple_workflow_schema(
            contract, runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL
        )["properties"]["reader_output"]["anyOf"][0]
        self.assertEqual(
            wire_schema["properties"]["changes"]["items"]["required"],
            ["claim", "start_source_unit_id", "end_source_unit_id"],
        )
        self.assertFalse(wire_schema["properties"]["changes"]["items"]["additionalProperties"])

    def test_rendered_range_prompt_matches_recent_day_projection_responsibility(self) -> None:
        body = (
            "公司名称：示例有限公司\n证券代号：01234\n\n"
            "2024年净利润预计为 100 至 120 百万港元。\n\n"
            "较上年增长 20% 至 30%。\n\n"
            "公司提示上述数字未经审计。"
        )
        batch = synthetic_batch(body)
        article = batch["articles"][0]
        contract = runner.load_active_contract()
        prompt = recent_day._recent_day_system_prompt(
            contract, runner.SIMPLE_WORKFLOW_RANGE_PROFILE
        )
        messages = recent_day._messages_for_article(
            article,
            contract,
            prompt,
            runner.SIMPLE_WORKFLOW_RANGE_PROFILE,
        )

        self.assertEqual(prompt, runner.build_system_prompt(contract, runner.SIMPLE_WORKFLOW_RANGE_PROFILE))
        self.assertEqual(messages[0]["content"], prompt)
        self.assertNotIn("facts 和 changes 必须都输出空数组", messages[0]["content"])
        self.assertNotIn("facts 和 changes 均为 []", messages[0]["content"])
        self.assertIn("changes 由模型", messages[0]["content"])
        self.assertIn("连续 source-unit 范围端点", messages[0]["content"])

        unit_map = runner.build_source_unit_map(body, article["body_sha256"])
        self.assertEqual(len(unit_map["units"]), 4)
        fixed_fact_ledger = runner._simple_fixed_fact_ledger(article, unit_map)
        self.assertTrue(fixed_fact_ledger["reader_facts"])
        wire_reader = reader_output(article)
        wire_reader["facts"] = []
        wire_reader["changes"] = [{
            "claim": "2024年净利润预计为 100 至 120 百万港元，较上年增长 20% 至 30%。",
            "start_source_unit_id": f"{article['article_id']}::{unit_map['units'][1]['source_unit_id']}",
            "end_source_unit_id": f"{article['article_id']}::{unit_map['units'][2]['source_unit_id']}",
        }]
        envelope = {"action": "complete", "lookup_request": None, "reader_output": wire_reader}
        projected, receipt = recent_day._project_recent_day_simple_output(
            envelope,
            article,
            contract,
            unit_map["source_unit_map_sha256"],
            range_profile=True,
            batch=batch,
        )

        projected_reader = projected["results"][0]["reader_output"]
        expected_quote = body[unit_map["units"][1]["start_cp"]:unit_map["units"][2]["end_cp"]]
        self.assertEqual(
            [item["claim"] for item in projected_reader["facts"]],
            [item["claim"] for item in fixed_fact_ledger["reader_facts"]],
        )
        for projected_fact, ledger_fact in zip(projected_reader["facts"], fixed_fact_ledger["reader_facts"]):
            fact_unit = next(unit for unit in unit_map["units"] if unit["source_unit_id"] == ledger_fact["source_unit_id"])
            self.assertEqual(projected_fact["quote"], fact_unit["text"])
            self.assertEqual(
                projected_fact["locator"],
                f"article_body[codepoint:{fact_unit['start_cp']}:{fact_unit['end_cp']}]",
            )
        self.assertEqual(len(projected_reader["changes"]), 1)
        self.assertEqual(projected_reader["changes"][0]["claim"], wire_reader["changes"][0]["claim"])
        self.assertEqual(projected_reader["changes"][0]["quote"], expected_quote)
        self.assertEqual(
            projected_reader["changes"][0]["locator"],
            f"article_body[codepoint:{unit_map['units'][1]['start_cp']}:{unit_map['units'][2]['end_cp']}]",
        )
        self.assertEqual(receipt["protocol"], "recent_day_fixed_facts_model_changes_unit_ranges_v2")
        self.assertEqual(receipt["model_changes_preserved_count"], 1)

    def test_range_message_uses_article_bound_ids_and_projects_exact_contiguous_rows(self) -> None:
        body = (
            "2024年净利润预计为 100 至 120 百万港元。\n\n"
            "较上年增长 20% 至 30%。\n\n"
            "公司提示上述数字未经审计。"
        )
        batch = synthetic_batch(body)
        article = batch["articles"][0]
        contract = runner.load_active_contract()
        unit_map = runner.build_source_unit_map(body, article["body_sha256"])
        self.assertEqual(len(unit_map["units"]), 3)

        messages = runner.build_messages(batch, contract, runner.SIMPLE_WORKFLOW_RANGE_PROFILE)
        user_payload = json.loads(
            messages[1]["content"].split("ARTICLE_DATA_BEGIN\n", 1)[1].split("\nARTICLE_DATA_END", 1)[0]
        )
        model_article = user_payload["article"]
        self.assertEqual(user_payload["schema"], runner.SIMPLE_WORKFLOW_RANGE_INPUT_SCHEMA)
        self.assertEqual(model_article["article_id"], article["article_id"])
        self.assertEqual(
            [item["source_unit_id"] for item in model_article["source_units"]],
            [f"{article['article_id']}::{unit['source_unit_id']}" for unit in unit_map["units"]],
        )
        self.assertEqual(
            "".join(item["text"] for item in model_article["source_units"]), body
        )
        source_unit_ids = set(model_article["fixed_fact_ledger"]["source_unit_ids"])
        self.assertTrue(all(item.startswith(article["article_id"] + "::") for item in source_unit_ids))
        self.assertTrue(all(
            ref["source_unit_id"].startswith(article["article_id"] + "::")
            for record in model_article["fixed_fact_ledger"]["records"]
            for ref in record.get("source_refs", [])
        ))

        wire_reader = reader_output(article)
        wire_reader["facts"] = []
        wire_reader["changes"] = [{
            "claim": "2024年净利润预测为 100 至 120 百万港元，较上年增长 20% 至 30%。",
            "start_source_unit_id": f"{article['article_id']}::{unit_map['units'][0]['source_unit_id']}",
            "end_source_unit_id": f"{article['article_id']}::{unit_map['units'][1]['source_unit_id']}",
        }]
        envelope = {"action": "complete", "lookup_request": None, "reader_output": wire_reader}
        projected, receipt = runner.project_simple_workflow_output(
            envelope,
            batch,
            contract,
            expected_source_unit_map_sha256_by_article={article["article_id"]: unit_map["source_unit_map_sha256"]},
            citation_protocol=runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL,
            preserve_model_changes=True,
        )
        projected_reader = projected["results"][0]["reader_output"]
        citation = projected_reader["changes"][0]
        expected_quote = body[unit_map["units"][0]["start_cp"]:unit_map["units"][1]["end_cp"]]
        self.assertEqual(citation["quote"], expected_quote)
        self.assertEqual(citation["quote"], "".join(unit["text"] for unit in unit_map["units"][:2]))
        self.assertEqual(
            citation["locator"],
            f"article_body[codepoint:{unit_map['units'][0]['start_cp']}:{unit_map['units'][1]['end_cp']}]",
        )
        self.assertEqual(citation["claim"], wire_reader["changes"][0]["claim"])
        self.assertEqual(receipt["citation_protocol"], runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL)
        projection = next(item for item in receipt["citation_projections"] if item["field"] == "changes")
        self.assertEqual(projection["range_sha256"], _sha(expected_quote.encode("utf-8")))

        for start, end, error in (
            ("OTHER-ARTICLE::U000001", "OTHER-ARTICLE::U000001", "CROSS_ARTICLE"),
            (f"{article['article_id']}::U999999", f"{article['article_id']}::U999999", "UNKNOWN_ID"),
            (f"{article['article_id']}::U000002", f"{article['article_id']}::U000001", "REVERSED"),
        ):
            invalid = copy.deepcopy(envelope)
            invalid["reader_output"]["changes"][0]["start_source_unit_id"] = start
            invalid["reader_output"]["changes"][0]["end_source_unit_id"] = end
            with self.subTest(error=error), self.assertRaisesRegex(runner.BatchError, error):
                runner.project_simple_workflow_output(
                    invalid,
                    batch,
                    contract,
                    citation_protocol=runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL,
                    preserve_model_changes=True,
                )

    def test_target_transport_records_request_time_settings_and_distinct_schema_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = root / "settings.json"
            model_settings = root / "model_settings.json"
            settings.write_bytes(b'{"model_temperature":1.0}\n')
            model_settings.write_bytes(b'{"force_sampling":false}\n')
            runtime_sha = _sha(settings.read_bytes())
            model_sha = _sha(model_settings.read_bytes())
            sent: list[httpx.Request] = []

            def handler(request: httpx.Request) -> httpx.Response:
                sent.append(request)
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_sse("{}"))

            job = queue_module.QueueJob("a" * 64, "rootcause-test", canary.MODEL_ID, {}, {}, 1)
            transport = canary.GatedStreamingTransport(
                "unit-secret",
                root / "evidence",
                expected_runtime_settings_sha256=runtime_sha,
                expected_model_settings_sha256=model_sha,
                runtime_settings_path=settings,
                model_settings_path=model_settings,
                http_transport=httpx.MockTransport(handler),
            )
            transport.begin_job(job)
            schema = runner.build_simple_workflow_schema(
                runner.load_active_contract(), runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL
            )
            completion = transport._stream_completion(
                [{"role": "user", "content": "fixture"}],
                lambda _event: None,
                tools=[],
                structured_outputs={"json": schema},
                workflow_profile=runner.SIMPLE_WORKFLOW_RANGE_PROFILE,
            )
            transport.finish_job(status="TEST_COMPLETE")
            receipt_path = transport._attempt_dir / "stream-receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt_text = receipt_path.read_text(encoding="utf-8")
            transport.close()

        self.assertEqual(len(sent), 1)
        actual_wrapper = json.loads(sent[0].content)["structured_outputs"]
        round_receipt = receipt["rounds"][0]
        self.assertEqual(actual_wrapper, {"json": schema})
        self.assertEqual(round_receipt["structured_outputs_inner_json_schema_sha256"], _sha(runner.canonical_json_bytes(schema)))
        self.assertEqual(round_receipt["structured_outputs_wrapper_sha256"], _sha(canary.canonical_json(actual_wrapper)))
        self.assertNotEqual(
            round_receipt["structured_outputs_inner_json_schema_sha256"],
            round_receipt["structured_outputs_wrapper_sha256"],
        )
        self.assertEqual(round_receipt["request_settings_binding"]["status"], "MATCH")
        self.assertEqual(round_receipt["request_settings_binding"]["bindings"][0]["observed_sha256"], runtime_sha)
        self.assertEqual(round_receipt["request_settings_binding"]["bindings"][1]["observed_sha256"], model_sha)
        self.assertEqual(round_receipt["request_settings_binding"]["active_server_memory_settings"], "CANNOT_CONFIRM")
        self.assertNotIn("unit-secret", receipt_text)
        self.assertNotIn("model_temperature", receipt_text)

    def test_target_transport_blocks_settings_drift_before_http_post(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = root / "settings.json"
            model_settings = root / "model_settings.json"
            settings.write_bytes(b'{"model_temperature":1.0}\n')
            model_settings.write_bytes(b'{"force_sampling":false}\n')
            sent: list[httpx.Request] = []
            job = queue_module.QueueJob("b" * 64, "rootcause-test", canary.MODEL_ID, {}, {}, 1)
            transport = canary.GatedStreamingTransport(
                "unit-secret",
                root / "evidence",
                expected_runtime_settings_sha256="0" * 64,
                expected_model_settings_sha256=_sha(model_settings.read_bytes()),
                runtime_settings_path=settings,
                model_settings_path=model_settings,
                http_transport=httpx.MockTransport(lambda request: sent.append(request) or httpx.Response(200)),
            )
            transport.begin_job(job)
            with self.assertRaisesRegex(runner.TransportError, "RUNTIME_SETTINGS_BINDING_MISMATCH"):
                transport._stream_completion(
                    [{"role": "user", "content": "fixture"}],
                    lambda _event: None,
                    tools=[],
                    structured_outputs={"json": runner.build_simple_workflow_schema(runner.load_active_contract())},
                    workflow_profile=runner.SIMPLE_WORKFLOW_PROFILE,
                )
            transport.finish_job(status="FAILED", code="RUNTIME_SETTINGS_BINDING_MISMATCH")
            receipt = json.loads((transport._attempt_dir / "stream-receipt.json").read_bytes())
            transport.close()

        self.assertEqual(sent, [])
        binding = receipt["request_settings_bindings"][0]
        self.assertEqual(binding["status"], "MISMATCH_OR_UNREADABLE")
        self.assertEqual(binding["bindings"][0]["status"], "MISMATCH")
        self.assertFalse(binding["matches_expected"])
        self.assertEqual(receipt["request_preflight_failure"], "RUNTIME_SETTINGS_BINDING_MISMATCH")

    def test_range_candidate_prepares_only_two_items_without_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "guoen-targeted-range-v2" / "candidate-one"
            with mock.patch.object(recent_day, "GUOEN_TARGETED_RANGE_CANDIDATE_ROOT", root.parent):
                result = recent_day.prepare_guoen_targeted(root, range_profile=True)
            manifest = json.loads((root / "candidate-manifest.json").read_bytes())
            queue = queue_module.SerialAnnouncementQueue(
                manifest["queue"]["state_root"],
                manifest["queue"]["queue_id"],
                manifest["model_request_policy"]["model_id"],
                max_attempts=manifest["queue"]["max_attempts"],
                max_body_bytes=None,
            )
            snapshot = queue.snapshot()
            ui_status = recent_day._RecentDayUI(root).status()

        self.assertEqual(result["status"], "PREPARED_ZERO_ATTEMPTS")
        self.assertEqual(manifest["schema"], recent_day.GUOEN_TARGETED_RANGE_SCHEMA)
        self.assertEqual(manifest["model_request_policy"]["workflow_profile"], runner.SIMPLE_WORKFLOW_RANGE_PROFILE)
        self.assertEqual(manifest["model_request_policy"]["citation_protocol"], runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL)
        self.assertEqual(manifest["target_article_ids"], list(recent_day.GUOEN_TARGETED_IDS))
        policy = manifest["model_request_policy"]
        schema = runner.build_simple_workflow_schema(
            runner.load_active_contract(), runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL
        )
        self.assertEqual(policy["structured_output_schema_inner_sha256"], _sha(runner.canonical_json_bytes(schema)))
        self.assertEqual(policy["structured_output_schema_wrapper_sha256"], _sha(canary.canonical_json({"json": schema})))
        self.assertNotEqual(policy["structured_output_schema_inner_sha256"], policy["structured_output_schema_wrapper_sha256"])
        self.assertEqual(policy["request_settings_sha256_provenance"], "candidate_prepare_local_disk_readback")
        self.assertEqual(len(snapshot["items"]), 2)
        self.assertTrue(all(item["attempt_count"] == 0 and item["status"] == "PENDING" for item in snapshot["items"]))
        self.assertEqual(ui_status["direct_pending_count"], 2)
        self.assertFalse(ui_status["model_called"])
        self.assertEqual(manifest["safety"]["model_called"], False)
        self.assertEqual(manifest["safety"]["ui_started"], False)
        self.assertEqual(manifest["model_request_policy"]["active_server_memory_settings"], "CANNOT_CONFIRM")


if __name__ == "__main__":
    unittest.main()
