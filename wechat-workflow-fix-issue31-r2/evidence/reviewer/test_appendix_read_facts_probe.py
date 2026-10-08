"""Independent edge-case probe for facts read before a failed HK binding."""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "candidate" / "wechat" / "scripts"))
sys.path.insert(0, str(ROOT / "candidate" / "wechat" / "tests"))


class AppendixReadFactsProbe(unittest.TestCase):
    def setUp(self) -> None:
        from test_prior_mentions_performance_appendix import PriorMentionsPerformanceAppendixTests

        self.fixture = PriorMentionsPerformanceAppendixTests("test_every_unique_market_listing_is_retained_and_receipt_bound")
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def test_current_hk_receipt_facts_and_sha_survive_panel_binding_failure(self) -> None:
        receipt_path = self.fixture.receipt_root / "hk-20260928.json"
        receipt_bytes = receipt_path.read_bytes()
        expected_receipt = json.loads(receipt_bytes)
        current_panel = self.fixture.hk_asset_root / "panels/20260928-test/current.parquet"
        current_panel.write_bytes(current_panel.read_bytes() + b"tampered-after-receipt")

        result = self.fixture._build()
        probe = result["source_data_probe"]["markets"]["HK"]

        self.assertEqual(probe.get("current_receipt_status"), expected_receipt["status"])
        self.assertEqual(probe.get("current_receipt_sha256"), hashlib.sha256(receipt_bytes).hexdigest())
        self.assertEqual(probe.get("current_receipt_rows"), expected_receipt["row_count"])
        self.assertEqual(probe.get("binding_status"), "CANNOT_CONFIRM")
        self.assertTrue(all(row["pct_chg_close"] is None for row in result["rows"] if row["market"] == "HK"))


if __name__ == "__main__":
    unittest.main()
