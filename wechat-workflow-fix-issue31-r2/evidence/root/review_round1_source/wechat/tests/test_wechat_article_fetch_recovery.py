# -*- coding: utf-8 -*-
"""Offline recovery tests through the real fetch adapter main()."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import wechat_article_fetch as fetch  # noqa: E402
import wechat_prepare_ocr as prepare_ocr  # noqa: E402


URL = "https://mp.weixin.qq.com/s/OfflineFixtureToken"


class WechatArticleFetchRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        self.collector = self.root / "fixture_collector.py"
        self.collector_calls = self.collector.with_suffix(".calls")
        self._write_collector()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_collector(self) -> None:
        self.collector.write_text(
            '''from __future__ import annotations
import argparse, csv, hashlib, json
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--html-file", default="")
args, _ = parser.parse_known_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
callfile = Path(__file__).with_suffix(".calls")
count = int(callfile.read_text() or "0") + 1 if callfile.exists() else 1
callfile.write_text(str(count))
token = urlsplit(args.url).path.rsplit("/", 1)[-1]
mode_path = Path(__file__).with_suffix(".mode")
mode = mode_path.read_text() if mode_path.exists() else "source_then_verify"
if count == 1 and mode != "verify_first":
    body = Path(args.html_file).read_bytes() if mode == "saved_html" else b"<!doctype html><html><body><div id=\\\"js_content\\\">offline verified article body</div></body></html>"
    (out / "wechat_article_raw.html").write_bytes(body)
    image_dir = out / "wechat_article_images"
    image_dir.mkdir(exist_ok=True)
    manifest = out / "wechat_article_image_manifest.csv"
    image_rows, checkpoint_rows = [], []
    for index in range(1, 51):
        image_path = image_dir / f"img_{index:02d}.png"
        Image.new("RGB", (16, 24), (index, 92, 141)).save(image_path, format="PNG")
        image = image_path.read_bytes()
        image_sha = hashlib.sha256(image).hexdigest()
        image_url = f"https://mmbiz.qpic.cn/fixture/{index}"
        image_rows.append({"idx": index, "url": image_url, "local_path": str(image_path),
                           "download_status": "OK", "image_size": "16x24", "sha256": image_sha, "bytes": len(image)})
        checkpoint_rows.append({"idx": index, "url": image_url, "local_path": str(image_path),
                                "sha256": image_sha, "status": "OK"})
    with manifest.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["idx", "url", "local_path", "download_status", "image_size", "sha256", "bytes"])
        writer.writeheader()
        writer.writerows(image_rows)
    (out / "wechat_article_image_checkpoint.json").write_text(json.dumps(checkpoint_rows))
    summary = {"article_url": args.url, "canonical_url": args.url, "canonical_token": token,
        "title": "离线合成文章", "account_name": "合成公众号", "biz": "fixture-biz",
        "article_date": "20261008", "content_hash": hashlib.sha256(body).hexdigest(),
        "http_status": 0 if mode == "saved_html" else 200, "html_bytes": len(body), "article_body_found": True,
        "text_preview_length": 18, "image_count": 50, "downloaded_image_count": 50,
        "final_label": "WECHAT_RESEARCH_INTAKE_PARTIAL_NEED_OCR",
        "ocr_status": "OCR_SKIPPED" if mode == "saved_html" else "OCR_IMPORT_ERROR",
        "ocr_error": "" if mode == "saved_html" else "ModuleNotFoundError: No module named easyocr", "fetch_error": "",
        "html_path": str(out / "wechat_article_raw.html"),
        "image_manifest_path": str(manifest)}
    (out / "wechat_article_intake_summary.json").write_text(json.dumps(summary))
    if mode == "module_not_found":
        raise ModuleNotFoundError("No module named easyocr")
    if mode == "unknown_exception":
        raise RuntimeError("unexpected post-capture failure")
    if mode == "saved_html":
        raise SystemExit(0)
    raise SystemExit(17)

body = b"<html><body><script>SecItPtPage/verify</script></body></html>"
(out / "wechat_article_raw.html").write_bytes(body)
(out / "wechat_article_image_manifest.csv").write_text("idx,url,local_path,download_status\\n")
summary = {"article_url": args.url, "canonical_url": args.url, "canonical_token": token,
    "final_label": "WECHAT_RESEARCH_INTAKE_BLOCKED_BY_WECHAT_VERIFY", "http_status": 200,
    "html_bytes": len(body), "article_body_found": False, "text_preview_length": 0,
    "image_count": 0, "downloaded_image_count": 0,
    "html_path": str(out / "wechat_article_raw.html"),
    "image_manifest_path": str(out / "wechat_article_image_manifest.csv")}
(out / "wechat_article_intake_summary.json").write_text(json.dumps(summary))
''',
            encoding="utf-8",
        )

    def _call(self, extra: list[str] | None = None) -> int:
        with patch.object(fetch, "_intake_script", return_value=self.collector):
            return fetch.main(["--url", URL, "--out", str(self.run_dir), "--skip-ocr", "--image-workers", "3", *(extra or [])])

    def test_ocr_failure_preserves_verified_source_and_resume_does_not_refetch(self) -> None:
        first_code = self._call()
        raw_path = self.run_dir / "wechat_article_raw.html"
        manifest_path = self.run_dir / "wechat_article_image_manifest.csv"
        summary_path = self.run_dir / "wechat_article_intake_summary.json"
        image_dir = self.run_dir / "wechat_article_images"
        image_paths = [image_dir / f"img_{index:02d}.png" for index in range(1, 51)]
        image_path = image_paths[0]
        self.assertEqual(first_code, 0)
        self.assertTrue(raw_path.is_file())
        self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8-sig"))["identity_status"], "PASS")
        self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8-sig"))["ocr_status"], "OCR_IMPORT_ERROR")
        self.assertEqual(prepare_ocr.main(["--run-dir", str(self.run_dir)]), 0)
        tracked_paths = [raw_path, manifest_path, summary_path,
                         self.run_dir / "wechat_article_image_checkpoint.json",
                         self.run_dir / "ocr_slice_manifest.json", *image_paths]
        before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in tracked_paths
        }

        second_code = self._call()
        state_path = self.run_dir / "wechat_article_fetch_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        self.assertEqual(second_code, 0)
        self.assertEqual(self.collector_calls.read_text(), "1")
        self.assertEqual(state["status"], "SOURCE_REUSED_NEED_OCR")
        self.assertEqual(state["next_missing_stage"], "prepare_ocr")
        self.assertEqual(before, {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in tracked_paths
        })
        rows = list(csv.DictReader(manifest_path.read_text(encoding="utf-8-sig").splitlines()))
        self.assertEqual([row["idx"] for row in rows], [str(index) for index in range(1, 51)])
        self.assertEqual([row["url"] for row in rows], [f"https://mmbiz.qpic.cn/fixture/{index}" for index in range(1, 51)])
        self.assertEqual([Path(row["local_path"]).resolve() for row in rows], [path.resolve() for path in image_paths])
        self.assertIn("ocr_text_length", rows[0])

    def test_verify_page_is_kept_only_as_attempt_evidence(self) -> None:
        self.collector.with_suffix(".mode").write_text("verify_first", encoding="utf-8")
        code = self._call()
        self.assertNotEqual(code, 0)
        self.assertFalse((self.run_dir / "wechat_article_raw.html").exists())
        self.assertFalse((self.run_dir / "wechat_article_intake_summary.json").exists())
        attempt_receipts = list((self.run_dir / "evidence" / "wechat_article_fetch_attempts").glob("*/ATTEMPT_RESULT.json"))
        self.assertEqual(len(attempt_receipts), 1)
        receipt = json.loads(attempt_receipts[0].read_text(encoding="utf-8-sig"))
        self.assertEqual(receipt["status"], "REJECTED")
        self.assertIn("verification", receipt["reason"].lower())

    def test_module_not_found_after_complete_body_is_source_only_resume(self) -> None:
        self.collector.with_suffix(".mode").write_text("module_not_found", encoding="utf-8")
        code = self._call()
        state = json.loads((self.run_dir / "wechat_article_fetch_state.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(code, 0)
        self.assertEqual(state["source_status"], "BODY_IDENTITY_VERIFIED")
        self.assertEqual(state["collector_execution_status"], "OCR_IMPORT_ERROR")
        self.assertEqual(state["continuation_status"], "RESUME_VIA_PREPARE_OCR")
        self.assertEqual(state["next_missing_stage"], "prepare_ocr")
        self.assertTrue((self.run_dir / "wechat_article_raw.html").is_file())

    def test_explicit_saved_html_permission_is_bound_to_attempt_and_source_bytes(self) -> None:
        self.collector.with_suffix(".mode").write_text("saved_html", encoding="utf-8")
        saved_html = self.root / "saved_article.html"
        saved_bytes = b"<!doctype html><html><body><div id=\\\"js_content\\\">saved offline fixture</div></body></html>"
        saved_html.write_bytes(saved_bytes)
        code = self._call(["--html-file", str(saved_html)])
        summary = json.loads((self.run_dir / "wechat_article_intake_summary.json").read_text(encoding="utf-8-sig"))
        promotion = json.loads(next((self.run_dir / "evidence" / "wechat_article_fetch_attempts").glob("*/PROMOTION_RECEIPT.json")).read_text(encoding="utf-8-sig"))
        self.assertEqual(code, 0)
        self.assertEqual(summary["identity_validation_mode"], "SAVED_HTML")
        self.assertEqual(summary["saved_html_sha256"], hashlib.sha256(saved_bytes).hexdigest())
        self.assertTrue(promotion["allow_saved_html"])
        self.assertEqual(promotion["saved_html_sha256"], hashlib.sha256(saved_bytes).hexdigest())
        self.assertEqual(self._call(["--html-file", str(saved_html)]), 0)
        self.assertEqual(self.collector_calls.read_text(), "1")

    def test_unknown_exception_retains_source_but_does_not_claim_fetch_pass(self) -> None:
        self.collector.with_suffix(".mode").write_text("unknown_exception", encoding="utf-8")
        code = self._call()
        state = json.loads((self.run_dir / "wechat_article_fetch_state.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(code, 2)
        self.assertEqual(state["status"], "SOURCE_RETAINED_CONTINUATION_UNVERIFIED")
        self.assertEqual(state["source_status"], "BODY_IDENTITY_VERIFIED")
        self.assertEqual(state["collector_execution_status"], "UNEXPECTED_EXCEPTION")
        self.assertEqual(state["continuation_status"], "UNVERIFIED")
        self.assertTrue((self.run_dir / "wechat_article_raw.html").is_file())

    def test_interrupted_promotion_recovers_the_same_verified_attempt(self) -> None:
        real_write = fetch._write_bytes_create_only
        interrupted = {"done": False}

        def interrupt_after_first_image(path: Path, payload: bytes, *, label: str) -> None:
            real_write(path, payload, label=label)
            if label == "article image" and not interrupted["done"]:
                interrupted["done"] = True
                raise KeyboardInterrupt("offline promotion interruption fixture")

        with patch.object(fetch, "_intake_script", return_value=self.collector), \
                patch.object(fetch, "_write_bytes_create_only", side_effect=interrupt_after_first_image):
            with self.assertRaises(KeyboardInterrupt):
                fetch.main(["--url", URL, "--out", str(self.run_dir), "--skip-ocr"])
        self.assertFalse((self.run_dir / "wechat_article_intake_summary.json").exists())
        self.assertTrue((self.run_dir / "wechat_article_images" / "img_01.png").is_file())
        code = self._call()
        state = json.loads((self.run_dir / "wechat_article_fetch_state.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(code, 0)
        self.assertEqual(self.collector_calls.read_text(), "1")
        self.assertTrue((self.run_dir / "wechat_article_intake_summary.json").is_file())
        self.assertEqual(state["status"], "SOURCE_RECOVERED_NEED_OCR")
        self.assertEqual(state["next_missing_stage"], "prepare_ocr")

    def test_malformed_old_summary_with_orphan_images_refuses_new_collector(self) -> None:
        (self.run_dir / "wechat_article_intake_summary.json").write_text("{bad json", encoding="utf-8")
        image_dir = self.run_dir / "wechat_article_images"
        image_dir.mkdir()
        (image_dir / "old.png").write_bytes(b"orphan")
        code = self._call()
        self.assertNotEqual(code, 0)
        self.assertFalse(self.collector_calls.exists())
        self.assertEqual((image_dir / "old.png").read_bytes(), b"orphan")


if __name__ == "__main__":
    unittest.main()
