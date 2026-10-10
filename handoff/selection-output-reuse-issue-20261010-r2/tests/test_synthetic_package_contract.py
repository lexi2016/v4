"""Package-only checks of synthetic field-pair fixtures; not app behavior tests."""
import json
from pathlib import Path
import unittest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_lane_contracts.json"

class SyntheticContractFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_announcement_requires_exact_target_and_publication_pair(self):
        block = self.data["announcement"]
        good, old = block["positive"], block["negative_cross_date_rebind"]
        self.assertEqual(good["expected"], "EXACT_PAIR_MATCH")
        self.assertEqual((good["request"]["target_trade_date"], good["request"]["publication_date"]),
                         (good["product"]["target_trade_date"], good["product"]["publication_date"]))
        self.assertEqual(old["expected"], "REJECT_TARGET_AND_PUBLICATION_MISMATCH")
        self.assertNotEqual((old["request"]["target_trade_date"], old["request"]["publication_date"]),
                            (old["product"]["target_trade_date"], old["product"]["publication_date"]))

    def test_hk_fixture_requires_target_dated_membership_and_cutoff(self):
        good, bad = self.data["hk_connect"]["positive"], self.data["hk_connect"]["negative_missing_or_wrong_date"]
        self.assertEqual(good["source_date"], good["target_trade_date"])
        self.assertLessEqual(good["available_at"], good["research_cutoff"])
        self.assertTrue(good["membership_codes"] and good["source_sha256"])
        self.assertEqual(bad["expected"], "CANNOT_CONFIRM")
        self.assertNotEqual(bad["source_date"], bad["target_trade_date"])
        self.assertIsNone(bad["artifact_schema"])

    def test_oversold_fixture_carries_complete_history_and_attested_units(self):
        good, bad = self.data["oversold"]["positive"], self.data["oversold"]["negative_unit_or_coverage_unknown"]
        self.assertEqual((good["prior60_sessions"], good["previous5_sessions"]), (60, 5))
        self.assertEqual(good["history_coverage"], "COMPLETE")
        self.assertTrue(good["volume_unit"] and good["unit_attestation_sha256"] and good["source_panel_sha256"])
        self.assertEqual(bad["expected"], "CANNOT_CONFIRM")
        self.assertNotEqual(bad["prior60_sessions"], 60)
        self.assertIsNone(bad["volume_unit"])

    def test_stage_fixture_binds_market_specific_fixed_pools(self):
        stage = self.data["stage"]
        a, hk, bad = stage["positive_a"], stage["positive_hk"], stage["negative_generic_or_wrong_date"]
        self.assertEqual((a["pool_contract"], a["pool_date"]), ("a_all_pool_rows", a["target_trade_date"]))
        self.assertEqual(hk["pool_contract"], "CANONICAL_D1_TOP100")
        self.assertEqual(hk["membership_count"], 100)
        self.assertTrue(hk["pool_date"] < hk["target_trade_date"])
        self.assertIsNotNone(a["artifact_sha256"])
        self.assertEqual(bad["expected"], "CANNOT_CONFIRM")
        self.assertIsNone(bad["artifact_sha256"])

if __name__ == "__main__":
    unittest.main()
