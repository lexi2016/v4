"""Regression checks for the exact combined Main source overlay."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest


APP_ROOT = Path(os.environ["V4_DAILY_SCOPE_TEST_APP_ROOT"]).resolve()
sys.path.insert(0, str(APP_ROOT))
SOURCE = Path(os.environ.get("V4_DAILY_SCOPE_TEST_DAILY_SOURCE", APP_ROOT / "ops" / "research_panel_daily_product.py")).resolve()
spec = importlib.util.spec_from_file_location("ops.research_panel_daily_product", SOURCE)
daily = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = daily
spec.loader.exec_module(daily)


class CurrentUniverseScopeTests(unittest.TestCase):
    def test_only_exact_confirmed_lifecycle_quarantine_rows_are_excluded(self):
        source = [
            "600001.SH", "920001.BJ", "000001.SZ", "000002.SZ", "000003.SZ",
            "000004.SZ", "000005.SZ", "000006.SZ", "000007.SZ", "000008.SZ",
        ]
        eligible = {
            "920001.BJ": dict(classification="QUARANTINED", quarantine=True,
                              target_date_ready=False, reason_code="VERIFIED_BSE_OLD_CODE_REPLACED"),
            "000001.SZ": dict(classification="QUARANTINED", quarantine=True,
                              target_date_ready=False, reason_code="VERIFIED_DELISTED_NO_CURRENT_BARS"),
            "000002.SZ": dict(classification="ACCEPTED", quarantine=True,
                              target_date_ready=False, reason_code="VERIFIED_DELISTED_NO_CURRENT_BARS"),
            "000003.SZ": dict(classification="QUARANTINED", quarantine=False,
                              target_date_ready=False, reason_code="VERIFIED_DELISTED_NO_CURRENT_BARS"),
            "000004.SZ": dict(classification="QUARANTINED", quarantine=True,
                              target_date_ready=True, reason_code="VERIFIED_DELISTED_NO_CURRENT_BARS"),
            "000005.SZ": dict(classification="QUARANTINED", quarantine=True,
                              target_date_ready=False, reason_code="TARGET_DATE_MISSING"),
            "000006.SZ": dict(classification="QUARANTINED", quarantine=True,
                              target_date_ready=False, reason="VERIFIED_DELISTED_NO_CURRENT_BARS"),
            "000007.SZ": dict(classification="QUARANTINED", quarantine=1,
                              target_date_ready=False, reason_code="VERIFIED_DELISTED_NO_CURRENT_BARS"),
            "000008.SZ": dict(classification="QUARANTINED", quarantine=True,
                              target_date_ready=0, reason_code="VERIFIED_DELISTED_NO_CURRENT_BARS"),
            "999999.SZ": dict(classification="QUARANTINED", quarantine=True,
                              target_date_ready=False, reason_code="VERIFIED_DELISTED_NO_CURRENT_BARS"),
        }

        original, active, excluded = daily.current_daily_universe({
            "original_target_codes": source,
            "symbols": {},
            "original_quarantine_eligible": eligible,
        })

        self.assertEqual(original, sorted(source))
        self.assertEqual(excluded, {
            "920001.BJ": "VERIFIED_BSE_OLD_CODE_REPLACED",
            "000001.SZ": "VERIFIED_DELISTED_NO_CURRENT_BARS",
        })
        self.assertEqual(active, sorted(set(source) - set(excluded)))
        self.assertEqual(daily.current_universe_exclusion_summary(excluded), {
            "count": 2,
            "by_reason_code": {
                "VERIFIED_BSE_OLD_CODE_REPLACED": 1,
                "VERIFIED_DELISTED_NO_CURRENT_BARS": 1,
            },
        })

    def test_missing_eligibility_metadata_keeps_source_scope(self):
        original, active, excluded = daily.current_daily_universe({"symbols": {"600001.SH": {}}})
        self.assertEqual(original, ["600001.SH"])
        self.assertEqual(active, original)
        self.assertEqual(excluded, {})

if __name__ == "__main__":
    unittest.main()
