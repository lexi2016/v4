from __future__ import annotations

import csv
import hashlib
import json
import os
import runpy
import shutil
import socket
import sys
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parent
candidate = root / "candidate"
scripts = candidate / "scripts"
source_run = candidate / "runs" / "20261008_html_recovery_ZfZPPo1xSsfROmFZbaqSuw"
target_run = root / "collector_cli_probe_run2"
network_log = root / "collector_cli_network_attempts2.jsonl"
real_collector = Path("/Users/lexi/.codex/skills/wechat-research-intake/scripts/wechat_article_intake.py")
wrapper = root / "wechat_article_intake_probe_wrapper2.py"
if target_run.exists() or wrapper.exists():
    raise SystemExit("refusing to overwrite existing reviewer probe files")
if not real_collector.is_file():
    raise SystemExit(f"current external collector not found: {real_collector}")

wrapper.write_text(f'''import csv, json, runpy, shutil, socket, sys, urllib.request
from pathlib import Path
args = list(sys.argv[1:])
out = Path(args[args.index("--out") + 1])
source_run = Path({str(source_run)!r})
source_images = source_run / "wechat_article_images"
target_images = out / "wechat_article_images"
target_images.mkdir(parents=True, exist_ok=True)
for image in source_images.iterdir():
    if image.is_file(): shutil.copy2(image, target_images / image.name)
checkpoint = json.loads((source_run / "wechat_article_image_checkpoint.json").read_text(encoding="utf-8-sig"))
checkpoint["images"] = [{{**row, "local_path": str(target_images / Path(row["local_path"]).name)}} for row in checkpoint["images"]]
(out / "wechat_article_image_checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
with (source_run / "wechat_article_image_manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
    reader = csv.DictReader(stream); fields = list(reader.fieldnames or []); rows = list(reader)
for row in rows: row["local_path"] = str(target_images / Path(row["local_path"]).name)
with (out / "wechat_article_image_manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
def blocked(*args, **kwargs):
    with Path({str(network_log)!r}).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({{"argv": sys.argv, "args": [str(x) for x in args]}}, ensure_ascii=False) + "\\n")
    raise RuntimeError("independent acceptance network guard blocked access")
urllib.request.urlopen = blocked
socket.getaddrinfo = blocked
sys.argv = [str(Path({str(real_collector)!r})), *args]
runpy.run_path(str(Path({str(real_collector)!r})), run_name="__main__")
''', encoding="utf-8")

sys.path.insert(0, str(scripts))
import wechat_article_fetch as fetch
import wechat_prepare_ocr as prepare
fetch._intake_script = lambda: wrapper
url = "https://mp.weixin.qq.com/s/ZfZPPo1xSsfROmFZbaqSuw"
html = source_run / "wechat_article_raw.html"
code = fetch.main(["--url", url, "--out", str(target_run), "--html-file", str(html), "--skip-ocr", "--image-workers", "3"])
summary_path = target_run / "wechat_article_intake_summary.json"
summary = json.loads(summary_path.read_text(encoding="utf-8-sig")) if summary_path.is_file() else {}
manifest_path = target_run / "wechat_article_image_manifest.csv"
rows = list(csv.DictReader(manifest_path.open(encoding="utf-8-sig", newline=""))) if manifest_path.is_file() else []
state_path = target_run / "wechat_article_fetch_state.json"
state = json.loads(state_path.read_text(encoding="utf-8-sig")) if state_path.is_file() else {}
image_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((target_run / "wechat_article_images").glob("img_*"))}
prepare_code = prepare.main(["--run-dir", str(target_run)]) if code == 0 else None
result = {
    "adapter_exit_code": code,
    "collector_path": str(real_collector),
    "collector_sha256": hashlib.sha256(real_collector.read_bytes()).hexdigest(),
    "target_run": str(target_run),
    "fetch_state": state,
    "collector_summary": {k: summary.get(k) for k in ("final_label", "http_status", "fetch_transport", "article_body_found", "image_count", "downloaded_image_count", "reused_image_count", "failed_image_count", "ocr_status")},
    "manifest_rows": len(rows),
    "all_manifest_urls_ordered": len(rows) == 50,
    "promoted_image_count": len(image_hashes),
    "network_attempt_count": len(network_log.read_text(encoding="utf-8").splitlines()) if network_log.exists() else 0,
    "prepare_ocr_exit_code": prepare_code,
    "prepare_ocr_summary": json.loads((target_run / "ocr_slice_manifest.json").read_text(encoding="utf-8-sig")) if (target_run / "ocr_slice_manifest.json").is_file() else None,
    "image_sha256_by_name": image_hashes,
}
(root / "collector_cli_probe_receipt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: v for k, v in result.items() if k != "image_sha256_by_name"}, ensure_ascii=False, indent=2))
