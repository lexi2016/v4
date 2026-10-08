# -*- coding: utf-8 -*-
"""Offline recovery tests through the real fetch adapter main()."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import subprocess
import tempfile
import textwrap
import time
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
    image_tags = "".join(f'<img data-src="https://mmbiz.qpic.cn/fixture/{index}"/>' for index in range(1, 51))
    if mode == "saved_html":
        body = Path(args.html_file).read_bytes()
    elif mode == "image_only":
        body = f'<!doctype html><html><body><div id="js_content">{image_tags}</div></body></html>'.encode()
    else:
        body = f'<!doctype html><html><body><div id="js_content">offline verified article body{image_tags}</div></body></html>'.encode()
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
        "article_date": "20261008", "published_at": "2026-10-08T12:00:00+08:00",
        "content_hash": hashlib.sha256(body).hexdigest(),
        "http_status": 0 if mode == "saved_html" else (503 if mode == "http_failure" else 200),
        "html_bytes": len(body), "article_body_found": True,
        "text_preview_length": 0 if mode == "image_only" else 18, "image_count": 50, "downloaded_image_count": 50,
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
        self.assertEqual(state["next_missing_stage"], "ocr_full")
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
        image_tags = "".join(
            f'<img data-src="https://mmbiz.qpic.cn/fixture/{index}"/>' for index in range(1, 51)
        )
        saved_bytes = f'<!doctype html><html><body><div id="js_content">saved offline fixture{image_tags}</div></body></html>'.encode()
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

        def interrupt_after_first_image(path: Path, payload: bytes, *, label: str,
                                        temp_dir: Path | None = None) -> None:
            real_write(path, payload, label=label, temp_dir=temp_dir)
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

    def test_process_killed_during_temp_image_write_rolls_forward_atomically(self) -> None:
        marker = self.root / "partial_temp_write_started"
        collector = self.root / "sigkill_collector.py"
        collector.write_text(
            '''import argparse, csv, hashlib, json
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image
callfile = Path(__file__).with_suffix(".calls")
callfile.write_text(str(int(callfile.read_text() or "0") + 1) if callfile.exists() else "1")
parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--out", required=True)
args, _ = parser.parse_known_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
body = b'<!doctype html><html><body><div id="js_content">valid body<img data-src="https://mmbiz.qpic.cn/fixture/1"/></div></body></html>'
(out / "wechat_article_raw.html").write_bytes(body)
image_dir = out / "wechat_article_images"
image_dir.mkdir(exist_ok=True)
image_path = image_dir / "img_01.png"
Image.new("RGB", (8, 12), (20, 30, 40)).save(image_path, format="PNG")
image = image_path.read_bytes()
image_sha = hashlib.sha256(image).hexdigest()
manifest = out / "wechat_article_image_manifest.csv"
with manifest.open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=["idx", "url", "local_path", "download_status", "image_size", "sha256", "bytes"])
    writer.writeheader()
    writer.writerow({"idx": 1, "url": "https://mmbiz.qpic.cn/fixture/1", "local_path": str(image_path),
        "download_status": "OK", "image_size": "8x12", "sha256": image_sha, "bytes": len(image)})
(out / "wechat_article_image_checkpoint.json").write_text(json.dumps([{"idx": 1, "url": "https://mmbiz.qpic.cn/fixture/1",
    "local_path": str(image_path), "sha256": image_sha, "status": "OK"}]))
token = urlsplit(args.url).path.rsplit("/", 1)[-1]
summary = {"article_url": args.url, "canonical_url": args.url, "canonical_token": token,
    "title": "offline", "account_name": "fixture", "biz": "fixture-biz", "article_date": "20261008",
    "content_hash": hashlib.sha256(body).hexdigest(), "http_status": 200, "html_bytes": len(body),
    "article_body_found": True, "text_preview_length": 10, "image_count": 1, "downloaded_image_count": 1,
    "final_label": "WECHAT_RESEARCH_INTAKE_PARTIAL_NEED_OCR", "ocr_status": "OCR_IMPORT_ERROR",
    "fetch_error": "", "html_path": str(out / "wechat_article_raw.html"),
    "image_manifest_path": str(manifest)}
(out / "wechat_article_intake_summary.json").write_text(json.dumps(summary))
raise SystemExit(17)
''',
            encoding="utf-8",
        )
        child = self.root / "first_sigkill_attempt.py"
        child.write_text(
            textwrap.dedent(
                f'''\
                import os, sys, time
                from pathlib import Path
                sys.path.insert(0, {str(Path(fetch.__file__).resolve().parent)!r})
                import wechat_article_fetch as fetch
                fetch._intake_script = lambda: Path({str(collector)!r})
                marker = Path({str(marker)!r})
                original_write = fetch._write_bytes_create_only
                def stop_during_temp_write(temp_path, descriptor, payload):
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(payload[:max(1, len(payload) // 2)])
                        handle.flush()
                        os.fsync(handle.fileno())
                    marker.write_text(str(temp_path))
                    while True:
                        time.sleep(0.05)
                def select_image_write(path, payload, *, label, temp_dir=None):
                    if label == "article image":
                        fetch._write_temporary_payload = stop_during_temp_write
                    return original_write(path, payload, label=label, temp_dir=temp_dir)
                fetch._write_bytes_create_only = select_image_write
                raise SystemExit(fetch.main(["--url", {URL!r}, "--out", {str(self.run_dir)!r}]))
                '''
            ),
            encoding="utf-8",
        )
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = ":".join([
            str(Path(fetch.__file__).resolve().parent),
            str(Path(__file__).resolve().parent),
        ])
        process = subprocess.Popen(
            [sys.executable, str(child)], env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline and not marker.exists():
                if process.poll() is not None:
                    break
                time.sleep(0.02)
            self.assertTrue(marker.exists(), "child did not reach the injected partial temp-write window")
            temporary_path = Path(marker.read_text())
            self.assertGreater(temporary_path.stat().st_size, 0)
            self.assertLess(temporary_path.stat().st_size, 100)
            target_path = self.run_dir / "wechat_article_images" / "img_01.png"
            self.assertFalse(target_path.exists(), "partial bytes became visible at the final image path")
        finally:
            if process.poll() is None:
                process.kill()
            child_output = process.communicate(timeout=5)[0].decode("utf-8", errors="replace")

        with patch.object(fetch, "_intake_script", return_value=collector):
            code = fetch.main(["--url", URL, "--out", str(self.run_dir)])

        state = json.loads((self.run_dir / "wechat_article_fetch_state.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(code, 0, f"pending attempt did not recover after SIGKILL: {child_output!r}")
        self.assertFalse(temporary_path.exists())
        self.assertEqual(state["status"], "SOURCE_RECOVERED_NEED_OCR")
        self.assertEqual(collector.with_suffix(".calls").read_text(), "1")
        self.assertEqual([path.name for path in (self.run_dir / "wechat_article_images").iterdir()], ["img_01.png"])

    def test_malformed_old_summary_with_orphan_images_refuses_new_collector(self) -> None:
        (self.run_dir / "wechat_article_intake_summary.json").write_text("{bad json", encoding="utf-8")
        image_dir = self.run_dir / "wechat_article_images"
        image_dir.mkdir()
        (image_dir / "old.png").write_bytes(b"orphan")
        code = self._call()
        self.assertNotEqual(code, 0)
        self.assertFalse(self.collector_calls.exists())
        self.assertEqual((image_dir / "old.png").read_bytes(), b"orphan")

    def test_image_only_body_is_valid_when_ordered_images_match_manifest(self) -> None:
        self.collector.with_suffix(".mode").write_text("image_only", encoding="utf-8")

        code = self._call()

        summary = json.loads((self.run_dir / "wechat_article_intake_summary.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(code, 0)
        self.assertEqual(summary["text_preview_length"], 0)
        self.assertEqual(summary["identity_status"], "PASS")
        rows = list(csv.DictReader((self.run_dir / "wechat_article_image_manifest.csv").open(encoding="utf-8-sig", newline="")))
        fetch._validate_article_body((self.run_dir / "wechat_article_raw.html").read_bytes(), rows)

    def test_http_failure_keeps_candidate_outputs_only_in_attempt_evidence(self) -> None:
        self.collector.with_suffix(".mode").write_text("http_failure", encoding="utf-8")

        code = self._call()

        self.assertNotEqual(code, 0)
        for name in fetch._FETCH_SOURCE_FILES:
            self.assertFalse((self.run_dir / name).exists(), f"HTTP failure promoted {name}")
        self.assertFalse((self.run_dir / "wechat_article_images").exists())
        attempts = list((self.run_dir / "evidence" / "wechat_article_fetch_attempts").glob("attempt_*"))
        self.assertEqual(len(attempts), 1)
        attempt = attempts[0]
        self.assertTrue((attempt / self.run_dir.name / "wechat_article_raw.html").is_file())
        result = json.loads((attempt / "ATTEMPT_RESULT.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("HTTP 200", result["reason"])

    def test_changed_raw_html_is_not_accepted_from_stale_http_identity(self) -> None:
        self.assertEqual(self._call(), 0)
        html_path = self.run_dir / "wechat_article_raw.html"
        original_sha = hashlib.sha256(html_path.read_bytes()).hexdigest()
        summary = json.loads((self.run_dir / "wechat_article_intake_summary.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(summary["identity_validation"]["raw_html_sha256"], original_sha)
        html_path.write_bytes(b'<!doctype html><html><body><div id="js_content">changed source bytes</div></body></html>')

        code = self._call()

        self.assertNotEqual(code, 0, "cached HTTP source with a raw HTML SHA mismatch was reused")
        self.assertEqual(self.collector_calls.read_text(), "1", "rejected cache must not overwrite it with another fetch")

    def test_changed_image_url_after_prepare_is_not_accepted_as_same_source(self) -> None:
        self.assertEqual(self._call(), 0)
        self.assertEqual(prepare_ocr.main(["--run-dir", str(self.run_dir)]), 0)
        manifest_path = self.run_dir / "wechat_article_image_manifest.csv"
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        rows[0]["url"] = "https://mmbiz.qpic.cn/fixture/replaced-url"
        with manifest_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

        code = self._call()

        self.assertNotEqual(code, 0, "changed image URL was accepted as reusable source evidence")
        self.assertEqual(self.collector_calls.read_text(), "1")

    def test_ocr_ok_summary_without_valid_ocr_artifacts_is_not_package_ready(self) -> None:
        self.assertEqual(self._call(), 0)
        summary_path = self.run_dir / "wechat_article_ocr_summary.json"
        summary_path.write_text(json.dumps({"status": "OCR_OK", "image_count": 50}), encoding="utf-8")
        self.assertFalse((self.run_dir / "windows_ocr_results.json").exists())
        self.assertFalse((self.run_dir / "windows_ocr_checkpoint.json").exists())

        self.assertEqual(self._call(), 0)
        state = json.loads((self.run_dir / "wechat_article_fetch_state.json").read_text(encoding="utf-8-sig"))

        self.assertNotEqual(state["next_missing_stage"], "package", "summary status alone was treated as complete OCR")
        self.assertEqual(state["ocr_summary_status"], "INVALID")
        self.assertEqual(self.collector_calls.read_text(), "1")

    def test_valid_full_ocr_cache_is_reused_and_package_is_next_stage(self) -> None:
        self.assertEqual(self._call(), 0)
        self.assertEqual(prepare_ocr.main(["--run-dir", str(self.run_dir)]), 0)
        with (self.run_dir / "wechat_article_image_manifest.csv").open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        results = []
        for index, row in enumerate(rows, 1):
            text = f"fixture OCR {index}"
            results.append({
                "index": index,
                "name": Path(row["local_path"]).name,
                "path": row["local_path"],
                "image_sha256": row["sha256"],
                "status": "OCR_OK",
                "text": text,
                "text_length": len(text),
                "engine": "OFFLINE_FIXTURE",
                "parts": [],
                "error": "",
            })
        (self.run_dir / "windows_ocr_results.json").write_text(json.dumps(results), encoding="utf-8")
        (self.run_dir / "windows_ocr_checkpoint.json").write_text(json.dumps(results), encoding="utf-8")
        text = "\n\n".join(
            f"=====IMAGE{item['index']:03d} {item['name']} [OCR_OK=====\n{item['text']}"
            for item in results
        )
        (self.run_dir / "wechat_article_ocr_text.txt").write_text(text, encoding="utf-8")
        (self.run_dir / "wechat_article_ocr_summary.json").write_text(json.dumps({
            "status": "OCR_OK", "mode": "Full", "image_count": 50,
            "ocr_applicable": True, "body_source_required": False,
            "processed_count": 50, "ok_count": 50,
            "timeout_count": 0, "error_count": 0, "empty_count": 0,
            "text_length": sum(item["text_length"] for item in results),
            "engine": "OFFLINE_FIXTURE",
        }), encoding="utf-8")
        ocr_files_before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.run_dir.iterdir()
            if path.is_file() and "ocr" in path.name.lower()
        }
        self.assertEqual(fetch._validated_ocr_status(self.run_dir, {}, 50), "OCR_OK")

        self.assertEqual(self._call(), 0)
        state = json.loads((self.run_dir / "wechat_article_fetch_state.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(self.collector_calls.read_text(), "1")
        self.assertEqual(state["ocr_summary_status"], "OCR_OK")
        self.assertEqual(state["next_missing_stage"], "package")
        self.assertEqual(ocr_files_before, {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.run_dir.iterdir()
            if path.is_file() and "ocr" in path.name.lower()
        })

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

        self.assertNotEqual(code, 0, "self-reported BODY claim promoted HTML with no js_content BODY")
        self.assertFalse((self.run_dir / "wechat_article_raw.html").exists())

    def test_output_abbreviation_cannot_escape_the_attempt_root(self) -> None:
        outside = self.root / "escaped-output"

        code = self._call(["--o", str(outside)])

        self.assertFalse((outside / "wechat_article_raw.html").exists())
        self.assertNotEqual(code, 0)
        self.assertFalse(self.collector_calls.exists())

    def test_saved_html_promotion_receipt_gap_recovers_after_summary_commit(self) -> None:
        self.collector.with_suffix(".mode").write_text("saved_html", encoding="utf-8")
        saved_html = self.root / "saved_article.html"
        image_tags = "".join(
            f'<img data-src="https://mmbiz.qpic.cn/fixture/{index}"/>' for index in range(1, 51)
        )
        saved_html.write_text(
            f'<!doctype html><html><body><div id="js_content">saved offline fixture{image_tags}</div></body></html>',
            encoding="utf-8",
        )
        real_write_event = fetch._write_attempt_event

        def interrupt_before_promotion_receipt(attempt_dir: Path, name: str, value: dict) -> None:
            if name == "PROMOTION_RECEIPT.json":
                raise KeyboardInterrupt("offline interruption after summary commit")
            real_write_event(attempt_dir, name, value)

        with patch.object(fetch, "_intake_script", return_value=self.collector), \
                patch.object(fetch, "_write_attempt_event", side_effect=interrupt_before_promotion_receipt):
            with self.assertRaises(KeyboardInterrupt):
                fetch.main(["--url", URL, "--out", str(self.run_dir), "--html-file", str(saved_html)])

        self.assertTrue((self.run_dir / "wechat_article_intake_summary.json").is_file())
        self.assertEqual(list((self.run_dir / "evidence" / "wechat_article_fetch_attempts").glob("*/PROMOTION_RECEIPT.json")), [])
        with patch.object(fetch, "_intake_script", return_value=self.collector):
            code = fetch.main(["--url", URL, "--out", str(self.run_dir), "--html-file", str(saved_html)])

        self.assertEqual(code, 0)
        self.assertEqual(self.collector_calls.read_text(), "1")
        self.assertEqual(len(list((self.run_dir / "evidence" / "wechat_article_fetch_attempts").glob("*/PROMOTION_RECEIPT.json"))), 1)


if __name__ == "__main__":
    unittest.main()
