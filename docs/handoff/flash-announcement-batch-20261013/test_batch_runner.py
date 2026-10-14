from __future__ import annotations

import hashlib
import contextlib
import copy
import io
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


def synthetic_five_disposition_batch() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    batch = synthetic_batch()
    template = batch["articles"][0]
    dispositions = [
        ("NOT_ASSESSED", "NOT_ASSESSED", "UNKNOWN", "INSUFFICIENT_EXISTING_FACTS"),
        ("NOT_SELECTED", "NOT_SELECTED", "NEUTRAL", "VERIFIED_EXISTING_FACTS"),
        ("CONDITIONAL_WATCH", "CONDITIONAL_WATCH", "MIXED", "VERIFIED_EXISTING_FACTS"),
        ("SELECTED_EVENT", "OPERATING_EVENT", "POSITIVE", "VERIFIED_EXISTING_FACTS"),
        ("SELECTED_PERFORMANCE", "PERFORMANCE_RESEARCH", "POSITIVE", "VERIFIED_EXISTING_FACTS"),
    ]
    articles: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for index, (disposition, basis, direction, sufficiency) in enumerate(dispositions):
        article = copy.deepcopy(template)
        symbol = f"HK.{2000 + index:05d}"
        body = f"  Issuer {index} reports  10 units, estimate only.\nNo comparator disclosed.  "
        article["article_id"] = f"EASTMONEY:SYNTH{index}:{symbol}"
        article["source_sha256"] = sha(f"source-{index}")
        article["body_sha256"] = sha(body)
        article["article_body"] = body
        metadata = article["article_metadata"]
        metadata["title"] = f"Synthetic article {index}"
        metadata["symbol"] = symbol
        metadata["source_issuer_codes"] = [
            {"code": symbol, "name": "Synthetic issuer", "market_code": "116"}
        ]
        metadata["source_origins"][0]["source_row_index"] = 100 + index
        metadata["source_origins"][0]["row_fingerprint_sha256"] = sha(f"listing-{index}")
        metadata["source_origins"][1]["source_row_index"] = 200 + index
        metadata["source_origins"][1]["row_fingerprint_sha256"] = sha(f"body-{index}")
        articles.append(article)

        output = reader_output(article)
        output.update(
            disposition=disposition,
            selection_basis=basis,
            direction=direction,
            evidence_sufficiency=sufficiency,
            reason=f"Synthetic {disposition} fixture.",
        )
        quote = body[2 : body.index("\n") + 1]
        evidence = {
            "claim": "Synthetic exact source evidence.",
            "quote": quote,
            "locator": "article_body",
        }
        for field in ("facts", "changes", "impact", "confirmation_conditions", "counter_evidence"):
            output[field] = [copy.deepcopy(evidence)]
        outputs.append(output)
    batch["batch_id"] = "synthetic-five-disposition-batch"
    batch["expected_count"] = len(articles)
    batch["articles"] = articles
    return batch, outputs


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

    def test_grounded_prompt_is_opt_in_and_preserves_legacy_prompt_schema_and_body(self) -> None:
        batch = synthetic_batch("  Issuer states estimate,  unaudited.\n ")
        contract = runner.load_active_contract()
        legacy = runner.build_messages(batch, contract)
        grounded = runner.build_messages(batch, contract, "grounded")
        self.assertEqual(
            sha(legacy[0]["content"]),
            "8c4dd30de9df230cfb93278b60b7b99458490d1b06760a00b877fbbed9086638",
        )
        self.assertEqual(legacy[1], grounded[1])
        self.assertEqual(
            legacy[0]["content"].split("ACTIVE_READER_JSON_SCHEMA_BEGIN\n", 1)[1].split(
                "\nACTIVE_READER_JSON_SCHEMA_END", 1
            )[0],
            grounded[0]["content"].split("ACTIVE_READER_JSON_SCHEMA_BEGIN\n", 1)[1].split(
                "\nACTIVE_READER_JSON_SCHEMA_END", 1
            )[0],
        )
        self.assertTrue(grounded[0]["content"].startswith(legacy[0]["content"] + "\n\n"))
        self.assertEqual(
            sha(grounded[0]["content"]),
            "9ca4648a15b33e8dd15eebf5447d1530c98edf6b949f1f20d27fbe18b5a18627",
        )
        self.assertIn("Read the complete supplied body before considering any tool.", grounded[0]["content"])
        self.assertIn("Web tools are available only for a specifically named external fact", grounded[0]["content"])
        self.assertIn("Every quote field must be a short, exact, continuous substring", grounded[0]["content"])
        self.assertNotIn("AN202610131830380437", grounded[0]["content"])
        self.assertEqual(
            sha(legacy[0]["content"]),
            sha(runner.build_system_prompt(contract, "legacy")),
        )
        limits = {
            "context_limit_tokens": 262144,
            "completion_max_tokens": 32768,
            "completion_limit_resolution": "GLOBAL_MAX_TOKENS",
        }
        with mock.patch.object(runner, "count_prompt_tokens", return_value=1234):
            legacy_prepare = runner.prepare_batch(batch, contract, runtime_limits=limits)
            grounded_prepare = runner.prepare_batch(
                batch, contract, prompt_profile="grounded", runtime_limits=limits
            )
        self.assertNotEqual(legacy_prepare["system_prompt_sha256"], grounded_prepare["system_prompt_sha256"])
        self.assertEqual(legacy_prepare["reader_schema_sha256"], grounded_prepare["reader_schema_sha256"])
        self.assertEqual(legacy_prepare["tool_schema_sha256"], grounded_prepare["tool_schema_sha256"])
        self.assertEqual(legacy_prepare["input_sha256"], grounded_prepare["input_sha256"])
        self.assertEqual(legacy_prepare["article_ids"], grounded_prepare["article_ids"])

    def test_decision_first_profile_is_opt_in_and_preserves_the_existing_contract(self) -> None:
        batch = synthetic_batch("  Issuer reports planned enrollment, no outcome disclosed.\n ")
        contract = runner.load_active_contract()
        legacy_default = runner.build_messages(batch, contract)
        legacy = runner.build_messages(batch, contract, "legacy")
        grounded = runner.build_messages(batch, contract, "grounded")
        decision_first = runner.build_messages(batch, contract, "decision_first")

        self.assertEqual(runner.PROMPT_PROFILES, ("legacy", "grounded", "decision_first", "decision_grounded"))
        self.assertEqual(legacy_default, legacy)
        self.assertEqual(
            sha(legacy[0]["content"]),
            "8c4dd30de9df230cfb93278b60b7b99458490d1b06760a00b877fbbed9086638",
        )
        self.assertEqual(
            sha(grounded[0]["content"]),
            "9ca4648a15b33e8dd15eebf5447d1530c98edf6b949f1f20d27fbe18b5a18627",
        )
        self.assertEqual(
            contract.source_sha256,
            "c786c837d4e3b8e06da017f3b7615e7561b5cd782c82b313e570b2bb00d09ee9",
        )
        self.assertEqual(
            runner.sha256_bytes(runner.canonical_json_bytes(contract.reader_schema)),
            "883da16a4935a3aa3cab37706d18012f280740a5a4fb5470f068d240255e57ae",
        )
        self.assertEqual(decision_first[1], legacy[1])
        self.assertTrue(decision_first[0]["content"].startswith(legacy[0]["content"] + "\n\n"))
        self.assertIn("A SELECTED_EVENT or SELECTED_PERFORMANCE disposition requires", decision_first[0]["content"])
        self.assertIn("direction=POSITIVE", decision_first[0]["content"])
        self.assertIn("evidence_sufficiency=VERIFIED_EXISTING_FACTS", decision_first[0]["content"])
        self.assertIn("Importance, suspension/resumption", decision_first[0]["content"])
        self.assertIn("Keep CONDITIONAL_WATCH under its current contract semantics", decision_first[0]["content"])
        self.assertIn("not disclosed", decision_first[0]["content"])
        self.assertIn("preclinical findings, or completed enrollment", decision_first[0]["content"])
        self.assertIn("Carry each input pit_status value exactly into risk_notes", decision_first[0]["content"])
        self.assertNotIn(runner.GROUNDED_PROCESS_ADDENDUM, decision_first[0]["content"])
        addendum = runner.DECISION_FIRST_ADDENDUM
        for stock_fragment in ("HK.02105", "HK.03696", "HK.02555", "HK.01389", "Southern Motion"):
            self.assertNotIn(stock_fragment, addendum)

        schema_marker = "ACTIVE_READER_JSON_SCHEMA_BEGIN\n"
        schema_end = "\nACTIVE_READER_JSON_SCHEMA_END"
        schemas = [
            message[0]["content"].split(schema_marker, 1)[1].split(schema_end, 1)[0]
            for message in (legacy, grounded, decision_first)
        ]
        self.assertEqual(schemas[0], schemas[1])
        self.assertEqual(schemas[0], schemas[2])
        limits = {
            "context_limit_tokens": 262144,
            "completion_max_tokens": 32768,
            "completion_limit_resolution": "GLOBAL_MAX_TOKENS",
        }
        with mock.patch.object(runner, "count_prompt_tokens", return_value=2345):
            legacy_prepare = runner.prepare_batch(batch, contract, runtime_limits=limits)
            grounded_prepare = runner.prepare_batch(
                batch, contract, prompt_profile="grounded", runtime_limits=limits
            )
            decision_prepare = runner.prepare_batch(
                batch, contract, prompt_profile="decision_first", runtime_limits=limits
            )
        self.assertEqual(legacy_prepare["prompt_profile"], "legacy")
        self.assertEqual(grounded_prepare["prompt_profile"], "grounded")
        self.assertEqual(decision_prepare["prompt_profile"], "decision_first")
        self.assertEqual(
            len({legacy_prepare["reader_schema_sha256"], grounded_prepare["reader_schema_sha256"], decision_prepare["reader_schema_sha256"]}),
            1,
        )
        self.assertEqual(
            len({legacy_prepare["active_contract_source_sha256"], grounded_prepare["active_contract_source_sha256"], decision_prepare["active_contract_source_sha256"]}),
            1,
        )
        self.assertEqual(legacy_prepare["tool_schema_sha256"], decision_prepare["tool_schema_sha256"])
        self.assertEqual(legacy_prepare["input_sha256"], decision_prepare["input_sha256"])
        self.assertEqual(legacy_prepare["article_ids"], decision_prepare["article_ids"])

    def test_decision_grounded_is_opt_in_and_preserves_all_older_profiles(self) -> None:
        batch = synthetic_batch("Exact body\nwith spaces  and disclosed facts.")
        contract = runner.load_active_contract()
        older = {
            profile: runner.build_messages(batch, contract, profile)
            for profile in ("legacy", "grounded", "decision_first")
        }
        candidate = runner.build_messages(batch, contract, "decision_grounded")

        self.assertEqual(runner.build_messages(batch, contract), older["legacy"])
        self.assertEqual(
            {profile: sha(messages[0]["content"]) for profile, messages in older.items()},
            {
                "legacy": "8c4dd30de9df230cfb93278b60b7b99458490d1b06760a00b877fbbed9086638",
                "grounded": "9ca4648a15b33e8dd15eebf5447d1530c98edf6b949f1f20d27fbe18b5a18627",
                "decision_first": "9b32e0b4d7d93384ab14b54a5b2f1a7a504c80baa8e13c319dbe4537f414f395",
            },
        )
        self.assertEqual(candidate[1], older["legacy"][1])
        self.assertTrue(
            candidate[0]["content"].startswith(older["decision_first"][0]["content"] + "\n\n")
        )
        self.assertEqual(
            sha(candidate[0]["content"]),
            "107fb203c20440ed904763d12f90bee4ca6984c43292527dfc61ba6f8384f772",
        )
        self.assertEqual(len(contract.reader_schema["properties"]), 13)
        for phrase in (
            "could change an existing Reader field or decision",
            "do not hold up the batch",
            "do not blindly retry with alternate queries",
            "mark only the unsupported point unverified",
            "Never invent the missing fact",
            "OUTPUT SHAPE CLARIFICATION",
            'exactly one top-level key, "results"',
            'exactly "article_id" and "reader_output"',
            "all 13 fields",
        ):
            self.assertIn(phrase, candidate[0]["content"])
        self.assertNotIn("AN202610131830380437", candidate[0]["content"])

        schema_marker = "ACTIVE_READER_JSON_SCHEMA_BEGIN\n"
        schema_end = "\nACTIVE_READER_JSON_SCHEMA_END"
        candidate_schema = candidate[0]["content"].split(schema_marker, 1)[1].split(schema_end, 1)[0]
        legacy_schema = older["legacy"][0]["content"].split(schema_marker, 1)[1].split(schema_end, 1)[0]
        self.assertEqual(candidate_schema, legacy_schema)
        limits = {
            "context_limit_tokens": 262144,
            "completion_max_tokens": 32768,
            "completion_limit_resolution": "GLOBAL_MAX_TOKENS",
        }
        with mock.patch.object(runner, "count_prompt_tokens", return_value=2345):
            prepared = runner.prepare_batch(
                batch, contract, prompt_profile="decision_grounded", runtime_limits=limits
            )
        self.assertEqual(prepared["prompt_profile"], "decision_grounded")
        self.assertEqual(prepared["prompt_tokens_exact_initial_request"], 2345)
        self.assertEqual(
            prepared["reader_schema_sha256"],
            "883da16a4935a3aa3cab37706d18012f280740a5a4fb5470f068d240255e57ae",
        )

    def test_prepare_cli_records_decision_first_without_calling_inference(self) -> None:
        batch = synthetic_batch("  Exact body remains unchanged.\n ")
        runtime_limits = {
            "context_limit_tokens": 262144,
            "completion_max_tokens": 32768,
            "completion_limit_resolution": "GLOBAL_MAX_TOKENS",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "batch.json"
            input_path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
            evidence_dir = root / "evidence"
            with (
                mock.patch.object(runner, "EVIDENCE_DIR", evidence_dir),
                mock.patch.object(runner, "load_runtime_limits", return_value=runtime_limits),
                mock.patch.object(runner, "count_prompt_tokens", return_value=2345),
                mock.patch.object(runner, "load_local_api_key", side_effect=AssertionError("API key read")) as key_reader,
                mock.patch.object(runner, "OmlxTransport") as transport,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = runner.main([str(input_path), "--prompt-profile", "decision_first"])
            self.assertEqual(result, 0)
            key_reader.assert_not_called()
            transport.assert_not_called()
            receipts = list(evidence_dir.glob("prepare_*.json"))
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertEqual(receipt["prompt_profile"], "decision_first")
            self.assertEqual(receipt["prompt_tokens_exact_initial_request"], 2345)
            self.assertEqual(receipt["status"], "INPUT_FITS")

    def test_prepare_cli_records_grounded_profile_without_calling_inference(self) -> None:
        batch = synthetic_batch("  Exact body text.\n ")
        runtime_limits = {
            "context_limit_tokens": 262144,
            "completion_max_tokens": 32768,
            "completion_limit_resolution": "GLOBAL_MAX_TOKENS",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "batch.json"
            input_path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
            evidence_dir = root / "evidence"
            with (
                mock.patch.object(runner, "EVIDENCE_DIR", evidence_dir),
                mock.patch.object(runner, "load_runtime_limits", return_value=runtime_limits),
                mock.patch.object(runner, "count_prompt_tokens", return_value=1234),
                mock.patch.object(runner, "load_local_api_key", side_effect=AssertionError("API key read")) as key_reader,
                mock.patch.object(runner, "OmlxTransport") as transport,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = runner.main([str(input_path), "--prompt-profile", "grounded"])
            self.assertEqual(result, 0)
            key_reader.assert_not_called()
            transport.assert_not_called()
            receipts = list(evidence_dir.glob("prepare_*.json"))
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertEqual(receipt["prompt_profile"], "grounded")
            self.assertEqual(receipt["prompt_tokens_exact_initial_request"], 1234)
            self.assertEqual(receipt["status"], "INPUT_FITS")

    def test_prepare_cli_records_decision_grounded_without_calling_inference(self) -> None:
        batch = synthetic_batch("  Exact body remains untouched by the candidate profile.\n ")
        runtime_limits = {
            "context_limit_tokens": 262144,
            "completion_max_tokens": 32768,
            "completion_limit_resolution": "GLOBAL_MAX_TOKENS",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "batch.json"
            input_path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
            evidence_dir = root / "evidence"
            with (
                mock.patch.object(runner, "EVIDENCE_DIR", evidence_dir),
                mock.patch.object(runner, "load_runtime_limits", return_value=runtime_limits),
                mock.patch.object(runner, "count_prompt_tokens", return_value=3456),
                mock.patch.object(runner, "load_local_api_key", side_effect=AssertionError("API key read")) as key_reader,
                mock.patch.object(runner, "OmlxTransport") as transport,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = runner.main([str(input_path), "--prompt-profile", "decision_grounded"])
            self.assertEqual(result, 0)
            key_reader.assert_not_called()
            transport.assert_not_called()
            receipts = list(evidence_dir.glob("prepare_*.json"))
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertEqual(receipt["prompt_profile"], "decision_grounded")
            self.assertEqual(receipt["prompt_tokens_exact_initial_request"], 3456)
            self.assertEqual(receipt["system_prompt_sha256"], "107fb203c20440ed904763d12f90bee4ca6984c43292527dfc61ba6f8384f772")
            self.assertEqual(receipt["status"], "INPUT_FITS")

    def test_active_validator_checks_all_five_dispositions_and_never_repairs_quotes(self) -> None:
        batch, outputs = synthetic_five_disposition_batch()
        contract = runner.load_active_contract()
        payload = json.dumps(
            {
                "results": [
                    {"article_id": article["article_id"], "reader_output": output}
                    for article, output in zip(batch["articles"], outputs)
                ]
            },
            ensure_ascii=False,
        )
        valid, errors = runner._validate_batch_output(payload, batch, contract)
        self.assertEqual(errors, {})
        self.assertEqual(set(valid), {article["article_id"] for article in batch["articles"]})
        self.assertEqual(
            {output["disposition"] for output in valid.values()},
            {"NOT_ASSESSED", "NOT_SELECTED", "CONDITIONAL_WATCH", "SELECTED_EVENT", "SELECTED_PERFORMANCE"},
        )

        for index, article in enumerate(batch["articles"]):
            invalid_payload = json.loads(payload)
            invalid_output = invalid_payload["results"][index]["reader_output"]
            original = invalid_output["facts"][0]["quote"]
            invalid_output["facts"][0]["quote"] = original.replace("  ", " ", 1)
            invalid_text = json.dumps(invalid_payload, ensure_ascii=False)
            invalid_before = sha(invalid_text)
            rejected, rejected_errors = runner._validate_batch_output(invalid_text, batch, contract)
            self.assertNotIn(article["article_id"], rejected)
            self.assertEqual(
                rejected_errors[article["article_id"]],
                "ANNOUNCEMENT_UNSUPPORTED_SOURCE_QUOTE",
            )
            self.assertEqual(sha(invalid_text), invalid_before)

            wrong_hash_payload = json.loads(payload)
            wrong_hash_payload["results"][index]["reader_output"]["source_sha256"] = "0" * 64
            _, hash_errors = runner._validate_batch_output(
                json.dumps(wrong_hash_payload, ensure_ascii=False), batch, contract
            )
            self.assertEqual(
                hash_errors[article["article_id"]],
                "ANNOUNCEMENT_READER_SOURCE_MISMATCH",
            )

            extra_field_payload = json.loads(payload)
            extra_field_payload["results"][index]["reader_output"]["invented_field"] = "not allowed"
            _, schema_errors = runner._validate_batch_output(
                json.dumps(extra_field_payload, ensure_ascii=False), batch, contract
            )
            self.assertEqual(
                schema_errors[article["article_id"]],
                "$output:ADDITIONAL_PROPERTIES",
            )

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
