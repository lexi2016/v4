# -*- coding: utf-8 -*-
"""Focused tests for the runtime-bound prior-article performance appendix."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pandas as pd
    import pyarrow  # noqa: F401
except ImportError:
    pd = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import wechat_yesterday_performance as yp  # noqa: E402


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class PriorMentionsPerformanceAppendixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.article_dir = self.root / "article"
        self.article_dir.mkdir()
        self.calendar_path = self.root / "market_calendar_2026.json"
        calendar = {
            "schema_version": "v3_5.market_calendar_2026.v1",
            "year": 2026,
            "timezone": "Asia/Shanghai",
            "official_sources": [
                {"market": "a_share", "name": "A calendar"},
                {"market": "hk_securities", "name": "HK calendar"},
            ],
            "markets": {
                "a_share": {"holiday_periods": [], "half_days": []},
                "hk_securities": {"holiday_periods": [], "half_days": []},
            },
        }
        self.calendar_path.write_text(json.dumps(calendar), encoding="utf-8")
        self._write_prior_archive()
        self._write_current_package()
        self._write_runtime_data()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_prior_archive(self) -> None:
        rows = [
            {"market": "A", "code": "000001.SZ", "name": "平安银行", "source_index": "BODY", "entity_id": "issuer-a"},
            {"market": "A", "code": "000001.SZ", "name": "平安银行", "source_index": "IMAGE001", "entity_id": "issuer-a"},
            {"market": "BJ", "code": "000001.BJ", "name": "北交所公司", "source_index": "BODY", "entity_id": "issuer-bj"},
            {"market": "HK", "code": "00001.HK", "name": "长和", "source_index": "BODY", "entity_id": "issuer-hk-in"},
            {"market": "HK", "code": "09999.HK", "name": "未覆盖港股", "source_index": "IMAGE002", "entity_id": "issuer-hk-out"},
        ]
        mentions_path = self.article_dir / "mentions.csv"
        with mentions_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["market", "code", "name", "source_index", "entity_id"])
            writer.writeheader()
            writer.writerows(rows)
        mentions_sha = _sha(mentions_path.read_bytes())
        receipt = {
            "status": "REPORT_AND_STRUCTURED_ARCHIVED",
            "binding": {
                "package_id": "wechat_test_prior",
                "input_digest": "a" * 64,
                "package_sha256_declared": "b" * 64,
                "package_sha256_observed": "b" * 64,
                "frozen_manifest_sha256_observed": "c" * 64,
                "package_identity_status": "VERIFIED",
                "package_sha256_status": "VERIFIED",
                "article_date": "20260927",
                "published_at": "2026-09-27T22:20:20+08:00",
                "article_url": "https://mp.weixin.qq.com/s/test-prior",
                "article_title": "测试前篇",
            },
            "local_acceptance": {
                "input_binding_valid": True,
                "structure_valid": True,
                "chat_claimed_complete": False,
            },
            "archived_files": {"mentions": {"sha256": mentions_sha}},
        }
        summary = {
            "package_id": "wechat_test_prior",
            "input_digest": "a" * 64,
            "url": "https://mp.weixin.qq.com/s/test-prior",
            "article_date": "20260927",
            "status": "PARTIAL",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "mentions_counts": {"total": 5, "A": 2, "BJ": 1, "HK": 2},
            "artifact_sha256": {"mentions.csv": mentions_sha},
        }
        (self.article_dir / "IMPORT_RECEIPT.json").write_text(json.dumps(receipt), encoding="utf-8")
        (self.article_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    def _write_current_package(self) -> None:
        handoff_dir = self.root / "handoff"
        handoff_dir.mkdir()
        zip_path = handoff_dir / "frozen.zip"
        zip_path.write_bytes(b"frozen package fixture")
        receipt = {
            "status": "PACKAGE_READY",
            "package_id": "wechat_test_current",
            "input_digest": "e" * 64,
            "article_date": "20260928",
            "published_at": "2026-09-28T22:39:03+08:00",
            "original_url": "https://mp.weixin.qq.com/s/test-current",
            "manifest_sha256": "f" * 64,
            "zip": {"path": zip_path.name, "sha256": _sha(zip_path.read_bytes()), "bytes": zip_path.stat().st_size},
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        self.current_package_receipt = handoff_dir / "PACKAGE_RECEIPT.json"
        self.current_package_receipt.write_text(json.dumps(receipt), encoding="utf-8")

    def _write_runtime_data(self) -> None:
        if pd is None:
            return
        self.receipt_root = self.root / "receipts"
        self.receipt_root.mkdir()
        self.hk_asset_root = self.root / "hk-assets"
        self.hk_asset_root.mkdir()
        self.selector_pointer = self.root / "CURRENT_SELECTOR_READY_PANEL.txt"
        self.selector_panel = self.root / "selector.parquet"
        selector = pd.DataFrame([
            {"trade_date": "20260928", "ts_code": "000001.SZ", "name": "平安银行", "close": 11.0,
             "pre_close": 10.0, "pct_chg": 10.0, "market_type": "A_SHARE"},
            {"trade_date": "20260928", "ts_code": "000001.BJ", "name": "北交所公司", "close": 20.0,
             "pre_close": 19.0, "pct_chg": (20.0 / 19.0 - 1.0) * 100.0, "market_type": "BJ"},
        ])
        selector.to_parquet(self.selector_panel, index=False)
        self.selector_pointer.write_text(str(self.selector_panel), encoding="utf-8")
        selector_sha = _sha(self.selector_panel.read_bytes())
        a_receipt = {
            "status": "PARTIAL",
            "target_date": "20260928",
            "row_count": 2,
            "target_count": 3,
            "accepted_count": 3,
            "coverage_rate": 2 / 3,
            "selector_sha256": selector_sha,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "formula": {
                "status": "READY",
                "target_date": 20260928,
                "selector": str(self.selector_panel),
                "selector_sha256": selector_sha,
            },
            "sync": {"authority": {"authority_status": "REBUILD_REQUIRED"}},
        }
        (self.receipt_root / "a-20260928.json").write_text(json.dumps(a_receipt), encoding="utf-8")

        prior_panel_path = self.hk_asset_root / "panels/20260925-test/prior.parquet"
        prior_panel_path.parent.mkdir(parents=True)
        prior_frame = pd.DataFrame([
            {"trade_date": 20260925, "code_norm": "HK.00001", "ts_code": "00001.HK_CONNECT",
             "close": 10.0, "pre_close": 9.0, "pct_chg": 100.0 / 9.0},
        ])
        prior_frame.to_parquet(prior_panel_path, index=False)
        prior_panel_sha = _sha(prior_panel_path.read_bytes())
        prior_manifest_path = self.hk_asset_root / "panels/20260925-test/manifest.json"
        prior_manifest = {
            "asset_schema_version": "v3_shared_data.hk_0_2_panel_asset.v2",
            "increment_contract": "tdx_vipdoc_71_day_daily_append.v1",
            "panel_relative": "panels/20260925-test/prior.parquet",
            "panel_sha256": prior_panel_sha,
            "parent_panel_sha256": "0" * 64,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "native_observation": {
                "session_finality": "NOT_ATTESTED_BY_PROVIDER",
                "fields": {"price": {"transform": "NONE", "currency_status": "NOT_PROVEN"}},
            },
        }
        prior_manifest_path.write_text(json.dumps(prior_manifest), encoding="utf-8")
        (self.receipt_root / "hk-20260925.json").write_text(json.dumps({
            "schema_version": "v3.macos.research_panel_receipt.v1",
            "status": "READY",
            "target_date": "20260925",
            "row_count": 1,
            "universe_count": 2,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "authority": {
                "status": "READY",
                "target_date": "20260925",
                "through_date": "20260925",
                "manifest_relative": "panels/20260925-test/manifest.json",
                "panel_sha256": prior_panel_sha,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        }), encoding="utf-8")

        current_panel_path = self.hk_asset_root / "panels/20260928-test/current.parquet"
        current_panel_path.parent.mkdir(parents=True)
        current_frame = pd.DataFrame([
            {"trade_date": 20260925, "code_norm": "HK.00001", "ts_code": "00001.HK_CONNECT",
             "close": 10.0, "pre_close": 9.0, "pct_chg": 100.0 / 9.0},
            {"trade_date": 20260928, "code_norm": "HK.00001", "ts_code": "00001.HK_CONNECT",
             "close": 12.5, "pre_close": 10.0, "pct_chg": 25.0},
        ])
        current_frame.to_parquet(current_panel_path, index=False)
        current_panel_sha = _sha(current_panel_path.read_bytes())
        current_manifest_path = self.hk_asset_root / "panels/20260928-test/manifest.json"
        current_manifest = {
            "asset_schema_version": "v3_shared_data.hk_0_2_panel_asset.v2",
            "increment_contract": "tdx_vipdoc_71_day_daily_append.v1",
            "panel_relative": "panels/20260928-test/current.parquet",
            "panel_sha256": current_panel_sha,
            "parent_panel_sha256": prior_panel_sha,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "native_observation": {
                "session_finality": "NOT_ATTESTED_BY_PROVIDER",
                "fields": {"price": {"transform": "NONE", "currency_status": "NOT_PROVEN"}},
            },
        }
        current_manifest_path.write_text(json.dumps(current_manifest), encoding="utf-8")
        (self.receipt_root / "hk-20260928.json").write_text(json.dumps({
            "schema_version": "v3.macos.research_panel_receipt.v1",
            "status": "READY",
            "target_date": "20260928",
            "row_count": 1,
            "universe_count": 2,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "authority": {
                "status": "READY",
                "target_date": "20260928",
                "through_date": "20260928",
                "manifest_relative": "panels/20260928-test/manifest.json",
                "panel_sha256": current_panel_sha,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        }), encoding="utf-8")

        self.runtime_evidence = self.root / "runtime_pointer_discovery.json"
        self.runtime_evidence.write_text(json.dumps({
            "observed_at": "2026-09-28T16:08:19.891821+00:00",
            "source": "launchctl print current loaded scheduler environment",
            "exit_code": 0,
            "bindings": {
                "V35_RESEARCH_PANEL_A_SELECTOR_POINTER": str(self.selector_pointer),
                "V35_RESEARCH_PANEL_RECEIPT_ROOT": str(self.receipt_root),
                "V35_RESEARCH_PANEL_HK_ASSET_ROOT": str(self.hk_asset_root),
            },
            "pointer_targets": {
                "V35_RESEARCH_PANEL_A_SELECTOR_POINTER": str(self.selector_panel),
            },
        }), encoding="utf-8")

    def _build(self) -> dict:
        return yp.build_prior_mentions_performance_appendix(
            prior_article_dir=self.article_dir,
            current_package_receipt=self.current_package_receipt,
            observation_date="20260928",
            runtime_config_evidence=self.runtime_evidence,
            calendar_json=self.calendar_path,
        )

    @unittest.skipIf(pd is None, "pandas and pyarrow are required for the parquet integration fixture")
    def test_every_unique_market_listing_is_retained_and_receipt_bound(self) -> None:
        prior = yp._load_prior_article_mentions(self.article_dir)
        self.assertEqual(prior["unique_listings"], 4)
        self.assertEqual(prior["listing_counts"], {"A": 1, "BJ": 1, "HK": 2})
        result = self._build()
        self.assertEqual(result["source_article"]["article_relation_to_observation"], "EXACT_PREVIOUS_CALENDAR_DAY")
        self.assertEqual(result["current_package_binding"]["package_id"], "wechat_test_current")
        self.assertEqual(result["unique_listings"], 4)
        self.assertEqual(result["market_summary"]["A"]["observed_listings"], 1)
        self.assertEqual(result["market_summary"]["BJ"]["observed_listings"], 1)
        self.assertEqual(result["market_summary"]["HK"]["observed_listings"], 1)
        hk_row = next(row for row in result["rows"] if row["code"] == "00001.HK")
        self.assertEqual(hk_row["status"], "OBSERVED_RAW_CLOSE_TO_PRIOR_SESSION_CLOSE")
        self.assertEqual(hk_row["prior_session_date"], "20260925")
        self.assertEqual(hk_row["prior_session_close"], 10.0)
        self.assertEqual(hk_row["pct_chg_close"], 25.0)
        self.assertEqual(hk_row["corporate_action_adjustment_status"], "NOT_VERIFIED")
        missing = next(row for row in result["rows"] if row["code"] == "09999.HK")
        self.assertEqual(missing["status"], "CANNOT_CONFIRM")
        self.assertIsNone(missing["pct_chg_close"])
        self.assertEqual(result["market_summary"]["HK"]["status"], "PARTIAL_DATA")
        self.assertEqual(result["runtime_configuration"]["evidence_source"],
                         "launchctl print current loaded scheduler environment")
        self.assertFalse(result["production_allowed"])
        self.assertFalse(result["buy_gate_updated"])
        self.assertFalse(result["orders_sent"])
        markdown = yp.render_prior_mentions_performance_appendix(result)
        self.assertIn("原始、未复权", markdown)
        self.assertIn("00001.HK", markdown)

    def test_tampered_mentions_bytes_fail_archive_binding(self) -> None:
        mentions_path = self.article_dir / "mentions.csv"
        mentions_path.write_bytes(mentions_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(yp.PerformanceAppendixError, "do not match"):
            yp._load_prior_article_mentions(self.article_dir)

    @unittest.skipIf(pd is None, "pandas and pyarrow are required for the parquet integration fixture")
    def test_runtime_pointer_target_must_match_loaded_environment_evidence(self) -> None:
        evidence = json.loads(self.runtime_evidence.read_text())
        evidence["pointer_targets"]["V35_RESEARCH_PANEL_A_SELECTOR_POINTER"] = str(self.root / "wrong.parquet")
        self.runtime_evidence.write_text(json.dumps(evidence), encoding="utf-8")
        result = self._build()
        self.assertEqual(result["market_summary"]["A"]["observed_listings"], 0)
        self.assertEqual(result["market_summary"]["BJ"]["observed_listings"], 0)
        self.assertTrue(all(row["status"] == "CANNOT_CONFIRM" for row in result["rows"]))

    @unittest.skipIf(pd is None, "pandas and pyarrow are required for the parquet integration fixture")
    def test_failed_a_bj_root_receipt_cannot_emit_observed_rows(self) -> None:
        receipt_path = self.receipt_root / "a-20260928.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["status"] = "FAILED"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

        result = self._build()
        a_bj_rows = [row for row in result["rows"] if row["market"] in ("A", "BJ")]
        self.assertTrue(a_bj_rows)
        self.assertTrue(all(row["status"] == "CANNOT_CONFIRM" for row in a_bj_rows))
        self.assertFalse(any(row["status"].startswith("OBSERVED_") for row in a_bj_rows))
        for market in ("A", "BJ"):
            self.assertEqual(result["market_summary"][market]["status"], "CANNOT_CONFIRM")
            self.assertEqual(result["market_summary"][market]["observed_listings"], 0)


if __name__ == "__main__":
    unittest.main()
