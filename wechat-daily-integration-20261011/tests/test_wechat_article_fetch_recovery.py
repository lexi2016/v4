# -*- coding: utf-8 -*-
"""Offline recovery tests through the real fetch adapter main()."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_DEFAULT_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
_SCRIPT_DIR = Path(os.environ.get("ISSUE31_FETCH_SCRIPTS", _DEFAULT_SCRIPT_DIR)).resolve()
sys.path.insert(0, str(_SCRIPT_DIR))
import wechat_article_fetch as fetch  # noqa: E402
import wechat_chat_handoff as handoff  # noqa: E402
import wechat_pipeline_runner as runner  # noqa: E402
import wechat_prepare_ocr as prepare_ocr  # noqa: E402

_COLLECTOR_PATH = Path(__file__).resolve().parents[1] / "external" / "wechat_article_intake.py"
_COLLECTOR_NAMESPACE = __import__("runpy").run_path(str(_COLLECTOR_PATH))
collector_extract_image_urls = _COLLECTOR_NAMESPACE["extract_image_urls"]


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

    def _prepare_historical_package_fixture(self) -> tuple[Path, Path, Path, Path, dict[str, object]]:
        """Build a frozen v2 source plus a path-rebound run without live inputs."""
        self.assertEqual(self._call(), 0)
        self.assertEqual(prepare_ocr.main(["--run-dir", str(self.run_dir)]), 0)
        with (self.run_dir / "wechat_article_image_manifest.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as stream:
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
        ocr_text = "\n\n".join(
            f"=====IMAGE{item['index']:03d} {item['name']} [OCR_OK=====\n{item['text']}"
            for item in results
        )
        (self.run_dir / "wechat_article_ocr_text.txt").write_text(ocr_text, encoding="utf-8")
        (self.run_dir / "wechat_article_ocr_summary.json").write_text(json.dumps({
            "status": "OCR_OK", "mode": "Full", "image_count": 50,
            "ocr_applicable": True, "body_source_required": False,
            "processed_count": 50, "ok_count": 50,
            "timeout_count": 0, "error_count": 0, "empty_count": 0,
            "text_length": sum(item["text_length"] for item in results),
            "engine": "OFFLINE_FIXTURE",
        }), encoding="utf-8")

        # The exact source summary is legacy-shaped: BODY identity is present,
        # while no R2 attempt/promotion claim is synthesized.
        summary_path = self.run_dir / "wechat_article_intake_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
        for key in (
            "fetch_attempt_id", "identity_validation_version", "identity_validation_mode",
            "identity_validation", "saved_html_sha256",
        ):
            summary.pop(key, None)
        summary["identity_status"] = "PASS"
        # Historical saved-HTML intake has no HTTP transport response. The
        # explicitly trusted package plus exact original source anchors must
        # authorize this shape; an unanchored status=0 source stays rejected.
        summary["http_status"] = 0
        summary["fetch_mode"] = "saved_html"
        summary["ocr_text_path"] = str(self.run_dir / "wechat_article_ocr_text.txt")
        summary["image_checkpoint_path"] = str(self.run_dir / "wechat_article_image_checkpoint.json")
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8-sig")

        legacy_summary = summary_path
        manifest_path = self.run_dir / "wechat_article_image_manifest.csv"
        legacy_manifest = manifest_path
        package_dir = self.root / "frozen_package"
        receipt = handoff.package_run(self.run_dir, package_dir, "legacy_fixture_r1")
        frozen_zip = package_dir / receipt["zip"]["path"]

        rebound_parent = self.root / "rebound"
        rebound_parent.mkdir()
        rebound_run = rebound_parent / self.run_dir.name
        shutil.copytree(self.run_dir, rebound_run)
        attempts = rebound_run / "evidence" / "wechat_article_fetch_attempts"
        if attempts.exists():
            shutil.rmtree(attempts)
        (rebound_run / "wechat_article_fetch_state.json").unlink(missing_ok=True)
        rebound_summary_path = rebound_run / "wechat_article_intake_summary.json"
        rebound_summary = json.loads(rebound_summary_path.read_text(encoding="utf-8-sig"))
        path_fields = {
            "html_path": "wechat_article_raw.html",
            "image_manifest_path": "wechat_article_image_manifest.csv",
            "image_checkpoint_path": "wechat_article_image_checkpoint.json",
            "ocr_text_path": "wechat_article_ocr_text.txt",
        }
        for key, relative in path_fields.items():
            if key in rebound_summary:
                rebound_summary[key] = str(rebound_run / relative)
        rebound_summary_path.write_text(
            json.dumps(rebound_summary, ensure_ascii=False, indent=2), encoding="utf-8-sig"
        )
        rebound_manifest_path = rebound_run / "wechat_article_image_manifest.csv"
        with rebound_manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = list(reader.fieldnames or [])
            rebound_rows = list(reader)
        for row in rebound_rows:
            row["local_path"] = str(rebound_run / "wechat_article_images" / Path(row["local_path"]).name)
        with rebound_manifest_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rebound_rows)

        article = {
            "url": URL,
            "title": summary["title"],
            "target_date": summary["article_date"],
            "account": summary["account_name"],
            "biz": summary["biz"],
            "content_hash": summary["content_hash"],
        }
        (rebound_run / "article_research.json").write_text(
            json.dumps({"schema_version": 1, "article": article}, ensure_ascii=False), encoding="utf-8"
        )
        ocr_cache_names = {
            "windows_ocr_results.json", "windows_ocr_checkpoint.json",
            "wechat_article_ocr_text.txt", "wechat_article_ocr_summary.json",
        }
        ocr_hashes = {
            name: hashlib.sha256((rebound_run / name).read_bytes()).hexdigest()
            for name in ocr_cache_names
        }
        return rebound_run, frozen_zip, legacy_summary, legacy_manifest, {
            "package_id": receipt["package_id"],
            "input_digest": receipt["input_digest"],
            "package_sha256": receipt["zip"]["sha256"],
            "ocr_hashes": ocr_hashes,
        }

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

    def test_runner_adopts_frozen_legacy_source_then_prepare_reuses_cache(self) -> None:
        run_dir, frozen_zip, legacy_summary, legacy_manifest, frozen = self._prepare_historical_package_fixture()
        source_names = (
            "wechat_article_intake_summary.json",
            "wechat_article_raw.html",
            "wechat_article_image_manifest.csv",
            "wechat_article_image_checkpoint.json",
        )
        source_before = {
            name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
            for name in source_names
        }
        ocr_before = frozen["ocr_hashes"]
        with patch.object(fetch, "_intake_script") as collector_entry:
            self.assertEqual(fetch.main(["--url", URL, "--out", str(run_dir), "--skip-ocr"]), 2)
            collector_entry.assert_not_called()
        args = [
            "--run-dir", str(run_dir), "--url", URL,
            "--title", "离线合成文章", "--target-date", "20261008",
            "--stage", "fetch",
            "--adopt-frozen-package", str(frozen_zip),
            "--adopt-package-sha256", str(frozen["package_sha256"]),
            "--adopt-package-id", str(frozen["package_id"]),
            "--adopt-input-digest", str(frozen["input_digest"]),
            "--legacy-source-summary", str(legacy_summary),
            "--legacy-source-manifest", str(legacy_manifest),
        ]

        with patch.object(runner.sys, "platform", "darwin"):
            self.assertEqual(runner.main(args), 0)

        receipt_paths = list((run_dir / "evidence" / "wechat_article_fetch_adoptions").glob("*/REVALIDATION_RECEIPT.json"))
        self.assertEqual(len(receipt_paths), 1)
        adoption = json.loads(receipt_paths[0].read_text(encoding="utf-8-sig"))
        self.assertFalse(adoption["historical_promotion_claimed"])
        self.assertFalse(adoption["collector_invoked"])
        self.assertEqual(adoption["package"]["package_id"], frozen["package_id"])
        self.assertEqual(source_before, {
            name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
            for name in source_names
        })
        state = json.loads((run_dir / "wechat_article_fetch_state.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(state["next_missing_stage"], "package")
        self.assertEqual(state["historical_promotion_claimed"], False)
        self.assertEqual(state["ocr_cache_status"], "OCR_OK")

        with (run_dir / "wechat_article_image_manifest.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as stream:
            reader = csv.DictReader(stream)
            manifest_fields_before = list(reader.fieldnames or [])
            manifest_rows_before = list(reader)
        source_projection_before = fetch._image_source_projection_sha256(
            manifest_fields_before, manifest_rows_before,
        )
        image_paths_before = [row["local_path"] for row in manifest_rows_before]

        self.assertEqual(prepare_ocr.main(["--run-dir", str(run_dir)]), 0)
        self.assertEqual(ocr_before, {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in run_dir.iterdir()
            if path.is_file() and path.name in ocr_before
        })
        self.assertEqual(
            {name: source_before[name] for name in source_names if name != "wechat_article_image_manifest.csv"},
            {
                name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
                for name in source_names if name != "wechat_article_image_manifest.csv"
            },
        )
        with (run_dir / "wechat_article_image_manifest.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as stream:
            reader = csv.DictReader(stream)
            manifest_fields_after = list(reader.fieldnames or [])
            manifest_rows_after = list(reader)
        self.assertEqual(
            fetch._image_source_projection_sha256(manifest_fields_after, manifest_rows_after),
            source_projection_before,
        )
        self.assertEqual([row["local_path"] for row in manifest_rows_after], image_paths_before)
        with patch.object(fetch, "_intake_script") as collector_entry:
            self.assertEqual(fetch.main(["--url", URL, "--out", str(run_dir), "--skip-ocr"]), 0)
            collector_entry.assert_not_called()
        reused_state = json.loads(
            (run_dir / "wechat_article_fetch_state.json").read_text(encoding="utf-8-sig")
        )
        self.assertEqual(reused_state["status"], "LEGACY_SOURCE_REUSED_OCR_READY")
        self.assertFalse(reused_state["collector_invoked"])
        self.assertFalse(list((run_dir / "evidence" / "wechat_article_fetch_attempts").glob("*/PROMOTION_RECEIPT.json")))

    def test_frozen_adoption_rejects_summary_mutation_and_unsafe_image_rebinding(self) -> None:
        run_dir, frozen_zip, legacy_summary, legacy_manifest, frozen = self._prepare_historical_package_fixture()
        args = [
            "--url", URL, "--out", str(run_dir), "--skip-ocr",
            "--adopt-frozen-package", str(frozen_zip),
            "--adopt-package-sha256", str(frozen["package_sha256"]),
            "--adopt-package-id", str(frozen["package_id"]),
            "--adopt-input-digest", str(frozen["input_digest"]),
            "--legacy-source-summary", str(legacy_summary),
            "--legacy-source-manifest", str(legacy_manifest),
        ]

        def reject_without_collector() -> None:
            with patch.object(fetch, "_intake_script") as collector_entry:
                self.assertEqual(fetch.main(args), 2)
                collector_entry.assert_not_called()

        summary_path = run_dir / "wechat_article_intake_summary.json"
        original_summary = summary_path.read_bytes()
        changed_summary = json.loads(original_summary.decode("utf-8-sig"))
        changed_summary["description"] = "mutated after frozen package"
        summary_path.write_text(json.dumps(changed_summary, ensure_ascii=False), encoding="utf-8")
        reject_without_collector()
        summary_path.write_bytes(original_summary)

        manifest_path = run_dir / "wechat_article_image_manifest.csv"
        original_manifest = manifest_path.read_bytes()
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields, rows = list(reader.fieldnames or []), list(reader)

        rows[0]["local_path"] = "/tmp/forged/wechat_article_images/img_01.png"
        with manifest_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        reject_without_collector()

        rows[0]["local_path"] = f"{run_dir.name}/wechat_article_images/../outside.png"
        with manifest_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        reject_without_collector()

        rows[0]["local_path"] = str(run_dir / "wechat_article_images" / "img_01.png")
        with manifest_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        image_path = run_dir / "wechat_article_images" / "img_01.png"
        backup_path = image_path.with_name("img_01.png.writer-test-backup")
        image_path.rename(backup_path)
        image_path.symlink_to(self.run_dir / "wechat_article_images" / "img_01.png")
        try:
            reject_without_collector()
        finally:
            image_path.unlink()
            backup_path.rename(image_path)
            manifest_path.write_bytes(original_manifest)

        self.assertFalse(list((run_dir / "evidence" / "wechat_article_fetch_adoptions").glob("*/REVALIDATION_RECEIPT.json")))

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


class WechatArticleBodyBindingMacCompatibilityTests(unittest.TestCase):
    """The BODY/manifest contract must equal the current real collector projection."""

    @staticmethod
    def _body(inner: str) -> bytes:
        return (
            '<!doctype html><html><body><div id="js_content">'
            + inner
            + "</div></body></html>"
        ).encode("utf-8")

    @staticmethod
    def _rows(urls: list[str]) -> list[dict[str, str]]:
        return [{"idx": str(index), "url": url} for index, url in enumerate(urls, 1)]

    def test_bound_collector_source_matches_mac_input_binding(self) -> None:
        digest = hashlib.sha256(_COLLECTOR_PATH.read_bytes()).hexdigest()
        self.assertEqual(
            digest,
            "de9499c2e049bcf6d3da5ea6375831aece5eb2374e338e057f04e60dfd0c6058",
        )

    def test_text_body_with_missing_projected_manifest_row_is_rejected(self) -> None:
        url = "https://mmbiz.qpic.cn/fixture/missing-row"
        body = self._body(f"正文<img data-src=\"{url}\"/>")
        self.assertEqual(collector_extract_image_urls(body.decode()), [url])

        with self.assertRaisesRegex(ValueError, "manifest"):
            fetch._validate_article_body(body, [])

    def test_prepare_promotion_rejects_text_body_image_missing_from_manifest(self) -> None:
        url = "https://mp.weixin.qq.com/s/TokenABC"
        image_url = "https://mmbiz.qpic.cn/fixture/missing-row"
        body = self._body(f"正文<img data-src=\"{image_url}\"/>")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html_path = root / "wechat_article_raw.html"
            manifest_path = root / "wechat_article_image_manifest.csv"
            html_path.write_bytes(body)
            manifest_path.write_text("idx,url,sha256\n", encoding="utf-8-sig")
            summary = {
                "article_url": url,
                "canonical_url": url,
                "canonical_token": "TokenABC",
                "title": "Fixture article",
                "account_name": "Fixture account",
                "biz": "fixture-biz",
                "article_date": "20261008",
                "content_hash": "a" * 40,
                "http_status": 200,
                "html_bytes": len(body),
                "article_body_found": True,
                "text_preview_length": 2,
                "image_count": 0,
                "downloaded_image_count": 0,
                "final_label": "WECHAT_RESEARCH_INTAKE_COMPLETE",
                "fetch_error": "",
                "html_path": str(html_path),
                "image_manifest_path": str(manifest_path),
            }
            (root / "wechat_article_intake_summary.json").write_text(
                json.dumps(summary), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "manifest"):
                fetch._prepare_promotion(root, url, attempt_id="attempt_fixture")

    def test_collector_projection_decodes_amp_filters_and_deduplicates_in_order(self) -> None:
        first = "https://mmbiz.qpic.cn/fixture/a?x=1&y=2"
        second = "https://mmbiz.qpic.cn/fixture/encoded/path"
        body = self._body(
            "正文"
            '<img data-src="https://mmbiz.qpic.cn/fixture/a?x=1&amp;y=2"/>'
            '<img src="https://mmbiz.qpic.cn/fixture/a?x=1&amp;y=2"/>'
            '<img data-src="https://mmbiz.qpic.cn/fixture/encoded%2Fpath"/>'
            '<img data-src="https://mmbiz.qpic.cn/fixture/animation?wx_fmt=gif"/>'
            '<img data-src="https://example.invalid/not-mmbiz.png"/>'
        )
        projected = collector_extract_image_urls(body.decode())
        self.assertEqual(projected, [first, second])

        fetch._validate_article_body(body, self._rows(projected))
        with self.assertRaises(ValueError):
            fetch._validate_article_body(body, self._rows([first]))

    def test_text_and_image_only_body_accept_only_ordered_unique_manifest(self) -> None:
        first = "https://mmbiz.qpic.cn/fixture/first"
        second = "https://mmbiz.qpic.cn/fixture/second"
        image_only = self._body(
            f'<img data-src="{first}"/><img data-src="{first}"/>'
            f'<img data-src="{second}"/><img data-src="{second}"/>'
        )
        self.assertEqual(collector_extract_image_urls(image_only.decode()), [first, second])
        fetch._validate_article_body(image_only, self._rows([first, second]))
        for invalid_urls in ([second, first], [first, first, second], [first]):
            with self.subTest(manifest=invalid_urls):
                with self.assertRaisesRegex(ValueError, "manifest"):
                    fetch._validate_article_body(image_only, self._rows(list(invalid_urls)))

        text_body = self._body(f"正文<img data-src=\"{first}\"/><img data-src=\"{second}\"/>")
        with self.assertRaisesRegex(ValueError, "manifest"):
            fetch._validate_article_body(text_body, self._rows([first]))

    def test_image_only_gif_or_non_mmbiz_body_does_not_create_image_evidence(self) -> None:
        body = self._body(
            '<img data-src="https://mmbiz.qpic.cn/fixture/animation?wx_fmt=gif"/>'
            '<img data-src="https://example.invalid/cover.png"/>'
        )
        self.assertEqual(collector_extract_image_urls(body.decode()), [])

        with self.assertRaises(ValueError):
            fetch._validate_article_body(body, [])

        text_body = self._body(
            "正文"
            '<img data-src="https://mmbiz.qpic.cn/fixture/animation?wx_fmt=gif"/>'
            '<img data-src="https://example.invalid/cover.png"/>'
        )
        fetch._validate_article_body(text_body, [])


if __name__ == "__main__":
    unittest.main()
