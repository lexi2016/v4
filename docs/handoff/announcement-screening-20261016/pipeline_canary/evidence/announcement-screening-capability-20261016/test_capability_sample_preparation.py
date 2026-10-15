from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

PIPELINE_DIR = Path(__file__).resolve().parents[2]
FREEZE_DIR = PIPELINE_DIR / "evidence" / "recent-day-20261014"
if str(FREEZE_DIR) not in sys.path:
    sys.path.insert(0, str(FREEZE_DIR))
import recent_day_freeze as freeze


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class _FakeTokenizer:
    def apply_chat_template(self, _messages, **_kwargs):
        return list(range(1024))


class CapabilitySamplePreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        freeze.CAPABILITY_SAMPLE_ROOT.mkdir(parents=True, exist_ok=True)
        freeze.CAPABILITY_SAMPLE_CANDIDATE_ROOT.mkdir(parents=True, exist_ok=True)
        cls._temp = tempfile.TemporaryDirectory(
            prefix="capability-sample-tests-", dir=freeze.CAPABILITY_SAMPLE_ROOT
        )
        cls.temp_root = Path(cls._temp.name)
        cls._candidate_temp = tempfile.TemporaryDirectory(
            prefix="capability-candidate-tests-", dir=freeze.CAPABILITY_SAMPLE_CANDIDATE_ROOT
        )
        cls.candidate_temp_root = Path(cls._candidate_temp.name)

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()
        cls._candidate_temp.cleanup()

    def test_six_reviewed_source_rows_load_without_history_in_model_rows(self):
        manifest, rows = freeze._load_capability_sample_rows(
            freeze.CAPABILITY_SOURCE_INPUT.read_bytes(),
            freeze.CAPABILITY_SOURCE_MANIFEST.read_bytes(),
            freeze.CAPABILITY_SOURCE_INPUT_SHA256,
            freeze.CAPABILITY_SOURCE_MANIFEST_SHA256,
        )
        self.assertEqual(len(rows), 6)
        self.assertEqual(len(manifest["sample"]), 6)
        self.assertTrue(all(record["input"]["source"] == "EASTMONEY_HK" for record in rows))
        self.assertTrue(all("history_class" not in record["input"] for record in rows))
        self.assertEqual(
            [record["source_history"]["history_class"] for record in rows],
            [item["history_class"] for item in manifest["sample"]],
        )

    def test_unseen_manifest_is_exactly_bound_to_both_capture_provenance_files(self):
        manifest_path = self.temp_root / "unseen-source-manifest.json"
        result = freeze.prepare_unseen_nonroutine_source_manifest(manifest_path)
        self.assertEqual(result["article_id"], freeze.UNSEEN_NONROUTINE_ARTICLE_ID)
        self.assertEqual(result["input_sha256"], freeze.UNSEEN_NONROUTINE_INPUT_SHA256)
        raw = manifest_path.read_bytes()
        self.assertEqual(sha(raw), result["manifest_sha256"])
        manifest, rows = freeze._load_capability_sample_rows(
            freeze.UNSEEN_NONROUTINE_INPUT.read_bytes(), raw,
            freeze.UNSEEN_NONROUTINE_INPUT_SHA256, result["manifest_sha256"],
        )
        provenance = freeze._verify_capability_sample_source_provenance(
            manifest, freeze.UNSEEN_NONROUTINE_INPUT, manifest_path, rows
        )
        self.assertEqual(provenance["capture_manifest_sha256"], freeze.UNSEEN_NONROUTINE_CAPTURE_MANIFEST_SHA256)
        self.assertEqual(provenance["coverage_sha256"], freeze.UNSEEN_NONROUTINE_COVERAGE_SHA256)
        self.assertEqual(provenance["original_point_in_time_availability"], "CANNOT_CONFIRM")
        self.assertEqual(rows[0]["source_history"], {"history_class": "UNSEEN", "stratum": "nonroutine_unseen"})
        self.assertNotIn("expected_output", manifest)

    def test_unseen_provenance_hash_mismatch_fails_closed(self):
        manifest_path = self.temp_root / "tampered-source-manifest.json"
        freeze.prepare_unseen_nonroutine_source_manifest(manifest_path)
        manifest = json.loads(manifest_path.read_bytes())
        manifest["source_provenance"]["coverage_sha256"] = "0" * 64
        records_manifest = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        _source, rows = freeze._load_capability_sample_rows(
            freeze.UNSEEN_NONROUTINE_INPUT.read_bytes(), records_manifest,
            freeze.UNSEEN_NONROUTINE_INPUT_SHA256, sha(records_manifest),
        )
        with self.assertRaisesRegex(RuntimeError, "UNSEEN_NONROUTINE_NORMALIZED_MANIFEST_PROVENANCE_MISMATCH"):
            freeze._verify_capability_sample_source_provenance(
                manifest, freeze.UNSEEN_NONROUTINE_INPUT, manifest_path, rows
            )

    def test_six_item_candidate_prepares_zero_attempts_and_loads_in_ui(self):
        candidate_root = self.candidate_temp_root / "six-candidate"
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=_FakeTokenizer()):
            result = freeze.prepare_capability_sample(
                candidate_root, source_review_status="SOURCE_REVIEW_PASS"
            )
        self.assertEqual(result["status"], "PREPARED_ZERO_ATTEMPTS")
        self.assertEqual(result["article_ids"], [item["article_id"] for item in json.loads(freeze.CAPABILITY_SOURCE_MANIFEST.read_bytes())["sample"]])
        self.assertEqual(result["attempt_count_total"], 0)
        self.assertFalse(result["model_called"])
        self.assertFalse(result["ui_started"])
        ui = freeze._RecentDayUI(candidate_root)
        self.assertEqual(ui.manifest["counts"]["target_article_count"], 6)
        self.assertIn("混合历史", ui.candidate_description)
        self.assertEqual(ui.queue.snapshot()["status_counts"]["PENDING"], 6)
        for item in ui.queue.snapshot()["items"]:
            persisted_state = json.loads(ui.queue.state_path.read_bytes())
            state_item = persisted_state["jobs"][item["idempotency_key"]]
            payload = json.loads((ui.queue.state_root / state_item["input_path"]).read_bytes())
            content = payload["messages"][1]["content"]
            self.assertNotIn('"history_class"', content)
            self.assertNotIn('"stratum"', content)

    def test_single_unseen_nonroutine_candidate_is_separate_and_source_pinned(self):
        manifest_path = self.temp_root / "one-item-source-manifest.json"
        source = freeze.prepare_unseen_nonroutine_source_manifest(manifest_path)
        candidate_root = self.candidate_temp_root / "unseen-candidate"
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=_FakeTokenizer()):
            result = freeze.prepare_capability_sample(
                candidate_root,
                source_input_path=freeze.UNSEEN_NONROUTINE_INPUT,
                source_manifest_path=manifest_path,
                expected_input_sha256=source["input_sha256"],
                expected_manifest_sha256=source["manifest_sha256"],
                source_review_status="SOURCE_REVIEW_PASS",
            )
        self.assertEqual(result["article_ids"], [freeze.UNSEEN_NONROUTINE_ARTICLE_ID])
        self.assertEqual(result["attempt_count_total"], 0)
        self.assertFalse(result["model_called"])
        manifest = json.loads((candidate_root / "candidate-manifest.json").read_bytes())
        self.assertEqual(manifest["sample_history"]["history_class_counts"], {"UNSEEN": 1})
        self.assertEqual(manifest["source_inputs"]["capture_provenance"]["capture_manifest_sha256"], freeze.UNSEEN_NONROUTINE_CAPTURE_MANIFEST_SHA256)
        self.assertEqual(manifest["articles"][0]["first_hkex_publication_time"], "CANNOT_CONFIRM")
        ui = freeze._RecentDayUI(candidate_root)
        self.assertEqual(ui.queue.snapshot()["status_counts"]["PENDING"], 1)
        self.assertIn("单类样本", ui.candidate_description)
        self.assertIn("UNSEEN", ui.candidate_description)


if __name__ == "__main__":
    unittest.main()
