import json
import pathlib
import unittest

import check_stage_oct8_candidate as candidate


class StageOct8CandidatePinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = candidate.verify_candidate()
        cls.pin = json.loads(candidate.PIN_PATH.read_text(encoding="utf-8"))

    def test_candidate_manifest_inventory_and_18_entry_closure_are_pinned(self):
        self.assertEqual(self.summary["status"], "PIN_CHECK_OK")
        self.assertEqual(self.summary["application_inventory_count"], 918)
        self.assertEqual(self.summary["runtime_dependency_closure_count"], 18)
        self.assertEqual(self.summary["symlink_count"], 2)

    def test_existing_invalid_target_pool_does_not_enable_fallback(self):
        gate = self.pin["input_gate"]
        self.assertTrue(gate["artifact_present"])
        self.assertEqual(gate["state"], "CANNOT_CONFIRM")
        self.assertFalse(gate["historical_provenance_present"])
        self.assertFalse(gate["fallback_allowed"])

    def test_research_and_service_activation_safety_remains_closed(self):
        self.assertEqual(self.pin["safety"]["production_allowed"], False)
        self.assertEqual(self.pin["safety"]["buy_gate_updated"], False)
        self.assertEqual(self.pin["safety"]["orders_sent"], False)
        self.assertEqual(self.pin["safety"]["provider_invoked"], False)
        self.assertEqual(self.pin["safety"]["service_activated"], False)

    def test_runtime_lock_gap_is_not_reported_as_missing_imports(self):
        runtime = self.pin["runtime_python"]
        self.assertEqual(runtime["package_manifest_status"], "CANNOT_CONFIRM")
        self.assertEqual(runtime["stage_imports_missing"], [])
        self.assertEqual(len(runtime["packages"]), 5)
        self.assertFalse(runtime["pip_available"])


if __name__ == "__main__":
    unittest.main()
