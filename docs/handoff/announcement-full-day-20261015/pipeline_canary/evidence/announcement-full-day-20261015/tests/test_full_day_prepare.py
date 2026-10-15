from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


PIPELINE_DIR = Path(__file__).resolve().parents[3]
HELPER_PATH = PIPELINE_DIR / "evidence" / "recent-day-20261014" / "recent_day_freeze.py"
SPEC = importlib.util.spec_from_file_location("recent_day_freeze_full_day_test", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


class FullDayPopulationPreparationTests(unittest.TestCase):
    def test_frozen_population_is_partitioned_without_losing_missing_bodies(self) -> None:
        source, complete, population = HELPER._full_day_load_population()

        self.assertEqual(len(population), 392)
        self.assertEqual(len(complete), 391)
        self.assertEqual(sum(row["disposition"] == "QUEUED_NEW_MODEL_REQUEST" for row in population), 390)
        self.assertEqual(sum(row["disposition"] == "BODY_GAP_EXCLUDED_FROM_REQUESTS" for row in population), 1)
        self.assertEqual(source["coverage"]["20261015"]["body_gap_count"], 199)
        self.assertEqual(source["recovery_evidence"]["previous_complete_count"], 193)
        self.assertEqual(source["recovery_evidence"]["newly_complete_count"], 198)
        self.assertEqual(source["recovery_evidence"]["remaining_body_gap_count"], 1)
        self.assertEqual(source["recovery_evidence"]["independent_source_review_status"], "SOURCE_REVIEW_PASS")
        self.assertEqual(source["recovery_evidence"]["independent_source_review_sha256"], HELPER.FULL_DAY_SOURCE_REVIEW_SHA256)
        gap = next(row for row in population if row["disposition"] == "BODY_GAP_EXCLUDED_FROM_REQUESTS")
        self.assertEqual(gap["body_gap_codes"], ["CAPTURE_TRANSPORT_NOT_BOUND"])
        self.assertEqual({row["publication_date"] for row in population}, {"2026-10-15"})
        self.assertEqual(len({row["article_id"] for row in population}), 392)
        self.assertEqual(
            sum(row["disposition"] == "REUSED_PRIOR_VERIFIED_RESULT" for row in population),
            1,
        )

    def test_complete_bodies_remain_bound_to_their_source_hashes(self) -> None:
        _source, complete, _population = HELPER._full_day_load_population()

        self.assertEqual(len(complete), 391)
        for item in complete:
            article = item["article"]
            self.assertEqual(HELPER._sha(article["article_body"].encode("utf-8")), article["body_sha256"])
            self.assertEqual(article["article_metadata"]["publication_date"], "2026-10-15")
            self.assertEqual(item["unit_map"]["body_sha256"], article["body_sha256"])

    def test_prepared_candidate_has_zero_attempts_and_uses_existing_range_workflow(self) -> None:
        root = HELPER.FULL_DAY_CANDIDATE_ROOT
        if not (root / "candidate-manifest.json").is_file():
            self.skipTest("full-day candidate has not been prepared yet")

        ui = HELPER._RecentDayUI(root)
        status = ui.status()
        manifest = ui.manifest
        self.assertTrue(ui.is_full_day)
        self.assertTrue(ui.uses_range_citations)
        self.assertEqual(manifest["model_request_policy"]["workflow_profile"], "decision_simple_facts_unit_ranges_v2")
        self.assertEqual(manifest["model_request_policy"]["request_temperature"], 0.0)
        self.assertIs(manifest["model_request_policy"]["enable_thinking"], False)
        self.assertEqual(len(status["items"]), 390)
        self.assertTrue(status["items"][0]["issuer_name"])
        self.assertEqual(status["counts"]["source_catalogue_articles"], 392)
        self.assertEqual(status["counts"]["complete_body_articles"], 391)
        self.assertEqual(status["counts"]["new_model_request_count"], 390)
        self.assertEqual(status["counts"]["reused_completed_results"], 1)
        self.assertEqual(status["counts"]["body_gap_articles_excluded"], 1)
        self.assertEqual(status["direct_pending_count"], status["counts"]["direct_single_request_articles"])
        self.assertEqual(status["awaiting_chunking_count"], status["counts"]["awaiting_full_body_chunking_articles"])
        self.assertEqual(status["queue_status_counts"].get("PENDING"), 390)
        self.assertTrue(
            all(count == 0 for key, count in status["queue_status_counts"].items() if key != "PENDING")
        )
        self.assertEqual(sum(item["attempt_count"] for item in status["items"]), 0)
        self.assertFalse(status["model_called"])
        self.assertIn("正文缺口", ui.candidate_description)
        self.assertIn("CANNOT_CONFIRM", ui.candidate_description)

        pending_ids = {item["article_id"] for item in status["items"]}
        self.assertNotIn(HELPER.FULL_DAY_PRIOR_REUSE_ID, pending_ids)
        self.assertEqual(len(pending_ids), 390)
        awaiting_ids = set(manifest["preflight"]["awaiting_full_body_chunking_ids"])
        self.assertEqual(status["awaiting_chunking_count"], len(awaiting_ids))
        self.assertTrue(awaiting_ids.issubset(pending_ids))
        self.assertEqual(manifest["source_inputs"]["independent_source_review_status"], "SOURCE_REVIEW_PASS")
        self.assertEqual(manifest["source_inputs"]["independent_source_review_sha256"], HELPER.FULL_DAY_SOURCE_REVIEW_SHA256)
        self.assertEqual(manifest["source_population"]["initial_capture_complete_body_count"], 193)
        self.assertEqual(manifest["source_population"]["recovered_body_count"], 198)
        self.assertEqual(manifest["source_population"]["body_gap_count"], 1)
        receipt = json.loads((root / "prepare-receipt.json").read_bytes())
        self.assertEqual(receipt["status"], "PREPARED_ZERO_NEW_ATTEMPTS")
        self.assertEqual(receipt["initial_capture_complete_body_articles"], 193)
        self.assertEqual(receipt["recovered_body_articles"], 198)
        self.assertEqual(receipt["complete_body_articles"], 391)
        self.assertEqual(receipt["new_requests"], 390)
        self.assertEqual(receipt["reused_results"], 1)
        self.assertEqual(receipt["body_gaps"], 1)
        self.assertEqual(receipt["independent_source_review_status"], "SOURCE_REVIEW_PASS")
        self.assertEqual(receipt["review_status"], "PENDING_INDEPENDENT_READONLY_REVIEW")
        self.assertFalse(receipt["model_called"])
        self.assertFalse(receipt["ui_started"])
        self.assertEqual(receipt["attempt_count_total"], 0)

    def test_reuse_receipt_is_a_link_and_does_not_copy_prior_answer(self) -> None:
        reuse_path = HELPER.FULL_DAY_CANDIDATE_ROOT / "prior-result-reuse.json"
        if not reuse_path.is_file():
            self.skipTest("full-day candidate has not been prepared yet")

        reuse = json.loads(reuse_path.read_bytes())
        self.assertEqual(reuse["article_id"], HELPER.FULL_DAY_PRIOR_REUSE_ID)
        self.assertEqual(reuse["status"], "REUSED_PRIOR_VERIFIED_RESULT")
        self.assertEqual(reuse["prior_independent_review"], "PASS_WITH_LIMITATION")
        self.assertIn("prior_raw_response_sha256", reuse)
        self.assertNotIn("answer", reuse)
        self.assertNotIn("raw_response", reuse)


if __name__ == "__main__":
    unittest.main()
