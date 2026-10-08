"""Process-kill probe for a partial create-only promotion artifact."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "candidate" / "wechat" / "scripts"
URL = "https://mp.weixin.qq.com/s/OfflineFixtureToken"


class FetchSigkillProbe(unittest.TestCase):
    def test_killed_halfway_through_image_write_can_roll_forward(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "run"
            run_dir.mkdir()
            marker = root / "partial_write_started"
            collector = root / "collector.py"
            collector.write_text(
                '''import argparse, base64, csv, hashlib, json
from pathlib import Path
from urllib.parse import urlsplit
parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--out", required=True)
args, _ = parser.parse_known_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
body = b'<!doctype html><html><body><div id="js_content">valid body</div></body></html>'
(out / "wechat_article_raw.html").write_bytes(body)
image_dir = out / "wechat_article_images"
image_dir.mkdir(exist_ok=True)
image_path = image_dir / "img_01.png"
image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jxh8AAAAASUVORK5CYII=")
image_path.write_bytes(image)
image_sha = hashlib.sha256(image).hexdigest()
url = "https://mmbiz.qpic.cn/fixture/1"
manifest = out / "wechat_article_image_manifest.csv"
with manifest.open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=["idx", "url", "local_path", "download_status", "sha256"])
    writer.writeheader()
    writer.writerow({"idx": 1, "url": url, "local_path": str(image_path), "download_status": "OK", "sha256": image_sha})
(out / "wechat_article_image_checkpoint.json").write_text(json.dumps([{"idx": 1, "url": url, "local_path": str(image_path), "sha256": image_sha, "status": "OK"}]))
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
            child = root / "first_attempt.py"
            child.write_text(
                textwrap.dedent(
                    f'''\
                    import os, sys, time
                    from pathlib import Path
                    sys.path.insert(0, {str(SCRIPTS)!r})
                    import wechat_article_fetch as fetch
                    fetch._intake_script = lambda: Path({str(collector)!r})
                    original = fetch._write_bytes_create_only
                    marker = Path({str(marker)!r})
                    def crash_during_image(path, payload, *, label):
                        if label == "article image":
                            path.parent.mkdir(parents=True, exist_ok=True)
                            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                            os.write(fd, payload[:max(1, len(payload) // 2)])
                            os.close(fd)
                            marker.write_text(str(path))
                            while True:
                                time.sleep(0.05)
                        return original(path, payload, label=label)
                    fetch._write_bytes_create_only = crash_during_image
                    raise SystemExit(fetch.main(["--url", {URL!r}, "--out", {str(run_dir)!r}]))
                    '''
                ),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONPATH"] = f"{ROOT / 'test_deps'}:{SCRIPTS}:{ROOT / 'candidate' / 'wechat' / 'tests'}:{ROOT / 'candidate' / 'v4_app'}"
            process = subprocess.Popen([sys.executable, str(child)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 10
            try:
                while time.monotonic() < deadline and not marker.exists():
                    if process.poll() is not None:
                        break
                    time.sleep(0.02)
                self.assertTrue(marker.exists(), "child did not reach the injected half-write window")
                partial_path = Path(marker.read_text())
                self.assertTrue(0 < partial_path.stat().st_size < 68)
            finally:
                if process.poll() is None:
                    process.kill()
                child_output = process.communicate(timeout=5)[0].decode("utf-8", errors="replace")

            from unittest.mock import patch
            import wechat_article_fetch as fetch

            with patch.object(fetch, "_intake_script", return_value=collector):
                code = fetch.main(["--url", URL, "--out", str(run_dir)])
            self.assertEqual(
                code, 0,
                f"pending attempt did not recover after process death mid-image write; first process output={child_output!r}",
            )
            self.assertTrue((run_dir / "wechat_article_intake_summary.json").is_file())
            self.assertEqual((run_dir / "wechat_article_images" / "img_01.png").read_bytes(), base64_image())


def base64_image() -> bytes:
    import base64
    return base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jxh8AAAAASUVORK5CYII=")


if __name__ == "__main__":
    unittest.main()
