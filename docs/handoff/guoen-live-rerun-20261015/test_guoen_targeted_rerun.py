from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PIPELINE_DIR = Path(__file__).resolve().parents[2]
FREEZE_PATH = Path(__file__).with_name("recent_day_freeze.py")
SPEC = importlib.util.spec_from_file_location("recent_day_freeze_targeted_test", FREEZE_PATH)
assert SPEC is not None and SPEC.loader is not None
freeze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(freeze)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


class _FakeTokenizer:
    def apply_chat_template(self, _messages, **_kwargs):
        return list(range(1024))


class GuoenTargetedRerunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary_root = tempfile.TemporaryDirectory(
            prefix="writer-test-", dir=freeze.GUOEN_TARGETED_EVIDENCE_ROOT
        )
        cls.test_root = Path(cls._temporary_root.name)
        cls.candidate_root = cls.test_root / "candidate"
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=_FakeTokenizer()):
            cls.prepared = freeze.prepare_guoen_targeted(cls.candidate_root)
        cls.manifest_path = cls.candidate_root / "candidate-manifest.json"
        cls.manifest_raw = cls.manifest_path.read_bytes()
        cls.manifest = json.loads(cls.manifest_raw)

    @classmethod
    def tearDownClass(cls):
        cls._temporary_root.cleanup()

    def test_candidate_contains_only_the_two_frozen_notices_and_zero_attempts(self):
        self.assertEqual(self.prepared["status"], "PREPARED_ZERO_ATTEMPTS")
        self.assertEqual(self.prepared["attempt_count_total"], 0)
        self.assertFalse(self.prepared["model_called"])
        self.assertFalse(self.prepared["ui_started"])
        self.assertEqual(self.manifest["candidate_kind"], "guoen_targeted_two_article_rerun")
        self.assertEqual(set(self.manifest["target_article_ids"]), set(freeze.GUOEN_TARGETED_IDS))
        self.assertEqual(self.manifest["counts"]["target_article_count"], 2)
        self.assertEqual(self.manifest["counts"]["queued_complete_articles"], 2)
        self.assertEqual(self.manifest["queue"]["max_attempts"], 1)
        self.assertEqual(self.manifest["queue"]["max_concurrency"], 1)
        self.assertEqual(self.manifest["model_request_policy"]["fixed_fact_parser_sha256"], sha((PIPELINE_DIR / "simple_fixed_facts.py").read_bytes()))
        self.assertEqual(self.manifest["model_request_policy"]["canonical_contract_source_sha256"], sha(freeze.V4_ROOT.joinpath("v4/manager_workbench/engines/announcement.py").read_bytes()))

        old_root = freeze.GUOEN_TARGETED_SOURCE_ROOT
        old_batch = json.loads((old_root / "validated-batch.json").read_bytes())
        old_by_id = {row["article_id"]: row for row in old_batch["articles"]}
        batch_path = self.candidate_root / "validated-batch.json"
        batch = json.loads(batch_path.read_bytes())
        self.assertEqual(batch["expected_count"], 2)
        self.assertEqual([row["article_id"] for row in batch["articles"]], self.manifest["target_article_ids"])
        for row in batch["articles"]:
            old = old_by_id[row["article_id"]]
            for key in ("article_id", "article_body", "article_metadata", "source_sha256", "body_sha256"):
                self.assertEqual(row[key], old[key], f"{row['article_id']} {key}")
            self.assertEqual(row["fixed_fact_ledger"]["protocol"], self.manifest["model_request_policy"]["fixed_fact_parser_protocol"])
        queue = json.loads((self.candidate_root / "zero-attempt-queue.json").read_bytes())
        self.assertEqual(queue["article_count"], 2)
        self.assertEqual(queue["attempt_count_total"], 0)
        self.assertEqual(queue["max_attempts"], 1)
        self.assertTrue(all(item["attempt_count"] == 0 and item["status"] == "PENDING" for item in queue["items"]))
        self.assertEqual(self.manifest["safety"]["model_called"], False)
        self.assertEqual(self.manifest["safety"]["ui_started"], False)

    def test_ui_loads_targeted_queue_and_legacy_172_candidate(self):
        ui = freeze._RecentDayUI(self.candidate_root)
        self.assertTrue(ui.is_guoen_targeted)
        self.assertEqual(len(ui.article_meta), 2)
        self.assertEqual(len(ui._direct_pending_keys()), 2)
        self.assertIn("qwen3_8_flash_next", ui.candidate_description)
        self.assertIn("temperature=0", ui.candidate_description)

        legacy_root = freeze.GUOEN_TARGETED_SOURCE_ROOT
        protected = [
            legacy_root / "candidate-manifest.json",
            legacy_root / "candidate-manifest.sha256",
            legacy_root / "validated-batch.json",
            legacy_root / "zero-attempt-queue.json",
            Path(json.loads((legacy_root / "candidate-manifest.json").read_bytes())["queue"]["state_root"]) / "queue-state.json",
        ]
        before = {path: file_sha(path) for path in protected}
        legacy_ui = freeze._RecentDayUI(legacy_root)
        self.assertFalse(legacy_ui.is_guoen_targeted)
        self.assertEqual(len(legacy_ui.article_meta), 172)
        self.assertEqual(legacy_ui.manifest["schema"], "recent_day_flash_172_candidate.v1")
        self.assertEqual({path: file_sha(path) for path in protected}, before)

    def test_target_candidate_rejects_parser_or_contract_sha_mismatch(self):
        sidecar = self.candidate_root / "candidate-manifest.sha256"
        original_manifest = self.manifest_path.read_bytes()
        original_sidecar = sidecar.read_bytes()
        for key, bad_value, expected_code in (
            ("fixed_fact_parser_sha256", "0" * 64, "GUOEN_TARGETED_LIVE_BINDING_MISMATCH:fixed_fact_parser_sha256"),
            ("canonical_contract_source_sha256", "f" * 64, "GUOEN_TARGETED_LIVE_BINDING_MISMATCH:canonical_contract_source_sha256"),
        ):
            with self.subTest(key=key):
                value = json.loads(original_manifest)
                value["model_request_policy"][key] = bad_value
                bad_raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
                self.manifest_path.write_bytes(bad_raw)
                sidecar.write_text(sha(bad_raw) + "\n", encoding="ascii")
                with self.assertRaisesRegex(RuntimeError, expected_code):
                    freeze._RecentDayUI(self.candidate_root)
        self.manifest_path.write_bytes(original_manifest)
        sidecar.write_bytes(original_sidecar)
        self.assertEqual(file_sha(self.manifest_path), sha(original_manifest))

    def test_start_rechecks_manifest_before_any_model_request(self):
        ui = freeze._RecentDayUI(self.candidate_root)
        sidecar = self.candidate_root / "candidate-manifest.sha256"
        original_manifest = self.manifest_path.read_bytes()
        original_sidecar = sidecar.read_bytes()
        value = json.loads(original_manifest)
        value["model_request_policy"]["system_prompt_sha256"] = "0" * 64
        changed_raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        self.manifest_path.write_bytes(changed_raw)
        sidecar.write_text(sha(changed_raw) + "\n", encoding="ascii")
        try:
            started, code = ui.start()
            self.assertFalse(started)
            self.assertEqual(code, "GUOEN_TARGETED_MANIFEST_CHANGED")
            self.assertEqual(ui.model_requests_started, 0)
        finally:
            self.manifest_path.write_bytes(original_manifest)
            sidecar.write_bytes(original_sidecar)

    def test_existing_and_out_of_scope_candidate_roots_are_not_overwritten(self):
        protected = [
            freeze.GUOEN_TARGETED_SOURCE_ROOT / "candidate-manifest.json",
            freeze.GUOEN_TARGETED_SOURCE_ROOT / "validated-batch.json",
            freeze.GUOEN_TARGETED_SOURCE_ROOT / "zero-attempt-queue.json",
        ]
        before = {path: file_sha(path) for path in protected}
        with self.assertRaisesRegex(RuntimeError, "GUOEN_TARGETED_CANDIDATE_ROOT_OUTSIDE_EVIDENCE"):
            freeze.prepare_guoen_targeted(freeze.GUOEN_TARGETED_SOURCE_ROOT)
        with self.assertRaisesRegex(RuntimeError, "GUOEN_TARGETED_CANDIDATE_ROOT_ALREADY_EXISTS"):
            freeze.prepare_guoen_targeted(self.candidate_root)
        self.assertEqual({path: file_sha(path) for path in protected}, before)
        self.assertEqual(self.manifest_path.read_bytes(), self.manifest_raw)

    def test_system_failure_prevents_starting_the_remaining_target(self):
        ui = freeze._RecentDayUI(self.candidate_root)
        job = SimpleNamespace(
            payload={"article_id": freeze.GUOEN_TARGETED_IDS[0]},
            idempotency_key="synthetic-system-failure",
            attempt=1,
        )
        ui._persist_system_failure(job, "MODEL_TRANSPORT_FAILURE", {"error_code": "MODEL_TRANSPORT_FAILURE"}, None, b"")
        started, code = ui.start()
        self.assertFalse(started)
        self.assertEqual(code, "SYSTEM_FAILURE_STOPPED")
        self.assertEqual(ui.queue.snapshot()["status_counts"]["PENDING"], 2)
        self.assertEqual(ui.model_requests_started, 0)


if __name__ == "__main__":
    unittest.main()
