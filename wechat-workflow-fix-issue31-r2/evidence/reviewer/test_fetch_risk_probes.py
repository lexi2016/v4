"""Independent probes for the frozen Issue 31 fetch candidate.

This file is reviewer evidence only; it does not modify product or candidate
tests. Each test expresses a required fail-closed invariant so a failure records
a concrete counterexample against the frozen snapshot.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "candidate" / "wechat" / "scripts"))
sys.path.insert(0, str(ROOT / "candidate" / "wechat" / "tests"))

import wechat_article_fetch as fetch  # noqa: E402
import wechat_prepare_ocr as prepare_ocr  # noqa: E402


URL = "https://mp.weixin.qq.com/s/OfflineFixtureToken"


class FrozenFetchRiskProbes(unittest.TestCase):
    def setUp(self) -> None:
        from test_wechat_article_fetch_recovery import WechatArticleFetchRecoveryTests

        self.fixture = WechatArticleFetchRecoveryTests("test_ocr_failure_preserves_verified_source_and_resume_does_not_refetch")
        self.fixture.setUp()
        self.root = self.fixture.root
        self.run_dir = self.fixture.run_dir
        self.collector = self.fixture.collector
        self.collector_calls = self.fixture.collector_calls

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _call(self, extra: list[str] | None = None) -> int:
        return self.fixture._call(extra)

    def _seed_source_and_prepare(self) -> None:
        self.assertEqual(self._call(), 0)
        self.assertEqual(prepare_ocr.main(["--run-dir", str(self.run_dir)]), 0)

    def test_changed_raw_html_is_not_accepted_from_stale_http_identity(self) -> None:
        self.assertEqual(self._call(), 0)
        html_path = self.run_dir / "wechat_article_raw.html"
        original_sha = hashlib.sha256(html_path.read_bytes()).hexdigest()
        summary = json.loads((self.run_dir / "wechat_article_intake_summary.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(summary["identity_validation"]["raw_html_sha256"], original_sha)
        html_path.write_bytes(b"<!doctype html><html><body><div id=\"js_content\">changed source bytes</div></body></html>")

        code = self._call()

        self.assertNotEqual(code, 0, "cached HTTP source with a raw HTML SHA mismatch was reused")
        self.assertEqual(self.collector_calls.read_text(), "1", "rejected cache must not overwrite it with another fetch")

    def test_changed_image_url_after_prepare_is_not_accepted_as_same_source(self) -> None:
        self._seed_source_and_prepare()
        manifest_path = self.run_dir / "wechat_article_image_manifest.csv"
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        original_url = rows[0]["url"]
        rows[0]["url"] = "https://mmbiz.qpic.cn/fixture/replaced-url"
        with manifest_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

        code = self._call()

        self.assertNotEqual(code, 0, f"changed image URL {original_url!r} was accepted as reusable source evidence")
        self.assertEqual(self.collector_calls.read_text(), "1")

    def test_ocr_ok_summary_without_ocr_artifacts_is_not_package_ready(self) -> None:
        self.assertEqual(self._call(), 0)
        summary_path = self.run_dir / "wechat_article_ocr_summary.json"
        summary_path.write_text(json.dumps({"status": "OCR_OK", "image_count": 50}), encoding="utf-8")
        self.assertFalse((self.run_dir / "windows_ocr_results.json").exists())
        self.assertFalse((self.run_dir / "windows_ocr_checkpoint.json").exists())

        self.assertEqual(self._call(), 0)
        state = json.loads((self.run_dir / "wechat_article_fetch_state.json").read_text(encoding="utf-8-sig"))

        self.assertNotEqual(state["next_missing_stage"], "package", "OCR summary status alone was treated as complete OCR")
        self.assertEqual(self.collector_calls.read_text(), "1")

    def test_summary_claim_does_not_replace_real_body_html(self) -> None:
        collector = self.root / "empty_body_collector.py"
        collector.write_text(
            '''import argparse, csv, hashlib, json
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--html-file", default="")
args, _ = parser.parse_known_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
html = b"<!doctype html><html><head><title>not an article</title></head><body></body></html>"
(out / "wechat_article_raw.html").write_bytes(html)
manifest = out / "wechat_article_image_manifest.csv"
manifest.write_text("idx,url,local_path,download_status\\n", encoding="utf-8")
summary = {"article_url": args.url, "canonical_url": args.url, "canonical_token": args.url.rsplit("/", 1)[-1],
  "title": "自报文章", "account_name": "合成公众号", "biz": "fixture-biz", "article_date": "20261008",
  "content_hash": hashlib.sha256(html).hexdigest(), "http_status": 200, "html_bytes": len(html),
  "article_body_found": True, "text_preview_length": 18, "image_count": 0, "downloaded_image_count": 0,
  "final_label": "WECHAT_RESEARCH_INTAKE_COMPLETE", "fetch_error": "",
  "html_path": str(out / "wechat_article_raw.html"), "image_manifest_path": str(manifest)}
(out / "wechat_article_intake_summary.json").write_text(json.dumps(summary))
raise SystemExit(0)
''',
            encoding="utf-8",
        )

        with patch.object(fetch, "_intake_script", return_value=collector):
            code = fetch.main(["--url", URL, "--out", str(self.run_dir)])

        self.assertNotEqual(code, 0, "self-reported article_body_found=true promoted HTML with no article BODY")
        self.assertFalse((self.run_dir / "wechat_article_raw.html").exists())

    def test_output_abbreviation_cannot_escape_the_attempt_root(self) -> None:
        outside = self.root / "escaped-output"
        code = self._call(["--o", str(outside)])

        self.assertFalse(
            (outside / "wechat_article_raw.html").exists(),
            "argparse --o abbreviation let the child collector write outside the isolated attempt",
        )
        self.assertNotEqual(code, 0)

    def test_saved_html_promotion_receipt_gap_recovers_after_summary_commit(self) -> None:
        self.collector.with_suffix(".mode").write_text("saved_html", encoding="utf-8")
        saved_html = self.root / "saved_article.html"
        saved_html.write_bytes(b"<!doctype html><html><body><div id=\"js_content\">saved offline fixture</div></body></html>")
        real_write_event = fetch._write_attempt_event

        def interrupt_before_promotion_receipt(attempt_dir: Path, name: str, value: dict) -> None:
            if name == "PROMOTION_RECEIPT.json":
                raise KeyboardInterrupt("reviewer interruption after summary commit")
            real_write_event(attempt_dir, name, value)

        with patch.object(fetch, "_intake_script", return_value=self.collector), \
                patch.object(fetch, "_write_attempt_event", side_effect=interrupt_before_promotion_receipt):
            with self.assertRaises(KeyboardInterrupt):
                fetch.main(["--url", URL, "--out", str(self.run_dir), "--html-file", str(saved_html)])

        self.assertTrue((self.run_dir / "wechat_article_intake_summary.json").is_file())
        self.assertEqual(list((self.run_dir / "evidence" / "wechat_article_fetch_attempts").glob("*/PROMOTION_RECEIPT.json")), [])
        with patch.object(fetch, "_intake_script", return_value=self.collector):
            code = fetch.main(["--url", URL, "--out", str(self.run_dir), "--html-file", str(saved_html)])

        self.assertEqual(code, 0, "saved HTML source was permanently rejected before pending-attempt recovery")
        self.assertEqual(self.collector_calls.read_text(), "1")
        self.assertEqual(len(list((self.run_dir / "evidence" / "wechat_article_fetch_attempts").glob("*/PROMOTION_RECEIPT.json"))), 1)


if __name__ == "__main__":
    unittest.main()
