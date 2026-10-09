# R3 Mac acceptance commands

This is an explicit, offline source-revalidation path for an isolated Mac working copy of the historical run. Normal daily work still enters through the existing `wechat_pipeline_runner.py`. This command is not a replacement for that workflow and must target an isolated run copy, not production data.

The expected run basename is `20261008_html_recovery_ZfZPPo1xSsfROmFZbaqSuw`; its article URL is `https://mp.weixin.qq.com/s/ZfZPPo1xSsfROmFZbaqSuw`, title is `风言风语信息更新 10.8`, and target date is `20261008`. The isolated copy must already have consumer-safe path rebinding: all current summary artifact paths and image `local_path` entries resolve to regular files inside that run directory, with no symlink or `..` traversal. The run basename remains unchanged to match the frozen package's `source_run_id`.

## Locate the exact original summary and manifest anchors

The frozen ZIP is pinned by the Mac writer receipt:

```bash
ZIP="/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/evidence/issue31_r2_mac_20261009/mac_actual/original_inputs/wechat_chat_materials_wechat_20261008_ZfZPPo1xSsfROmFZbaqSuw_r1.zip"
WORKSPACE_ROOT="/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号"
shasum -a 256 "$ZIP"
```

The expected ZIP SHA-256 is `c8a0dcfb548012bc8feb4e818e0cad7eead7de5a564a0ecaa85d64ce3763956f` (11,012,092 bytes), package ID `wechat_20261008_ZfZPPo1xSsfROmFZbaqSuw_r1`, and input digest `c93e458747fe18fa33373785d79a9b026c15792d02fa9263db7b6f2bda48abc2`.

Read only the two expected source-file hashes from the ZIP manifest, then find files with those exact byte hashes under the existing `workspace_root/runs` and `workspace_root/evidence`. This prints hashes and matching paths only; it does not print article text or image data.

```bash
python3 - "$ZIP" "$WORKSPACE_ROOT" <<'PY'
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

archive = Path(sys.argv[1])
workspace = Path(sys.argv[2])
expected_zip_sha256 = "c8a0dcfb548012bc8feb4e818e0cad7eead7de5a564a0ecaa85d64ce3763956f"
zip_bytes = archive.read_bytes()
observed_zip_sha256 = hashlib.sha256(zip_bytes).hexdigest()
if observed_zip_sha256 != expected_zip_sha256:
    raise SystemExit(f"ZIP SHA-256 mismatch: observed {observed_zip_sha256}")
with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
    manifest = json.loads(zf.read("manifest.json"))
expected = {
    "wechat_article_intake_summary.json": str(manifest["source_intake_sha256"]).lower(),
    "wechat_article_image_manifest.csv": str(manifest["source_manifest_sha256"]).lower(),
}
for name, digest in expected.items():
    matches = []
    for base in (workspace / "runs", workspace / "evidence"):
        if not base.is_dir():
            continue
        listing = subprocess.run(
            ["rg", "--files", "--hidden", "-0", str(base)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if listing.returncode not in (0, 1):
            raise SystemExit(listing.stderr.decode("utf-8", errors="replace"))
        for raw_path in listing.stdout.split(b"\0"):
            if not raw_path:
                continue
            path = Path(os.fsdecode(raw_path))
            if path.name != name:
                continue
            if path.is_symlink() or not path.is_file():
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                matches.append(str(path))
    print(f"{name} expected_sha256={digest}")
    for path in matches:
        print(f"  MATCH {path}")
    if not matches:
        print("  NO_MATCH")
PY
```

Use the matching summary and CSV from the same original frozen run directory. The ZIP descriptor's `source_intake_sha256` and `source_manifest_sha256` are the required exact hashes. A path-rebound candidate copy whose bytes no longer match either hash is not an original anchor. The original source run's exact absolute directory was not present in the R3 review inputs, so do not infer it from the cited `COPY_REBIND_RECEIPT` hash or from the current copy. If either exact hash has no match, stop: adoption remains refused until those original bytes are available.

## Run explicit adoption on an isolated copy

Set `WECHAT_WORKTREE` to the isolated **`wechat` root directory containing `scripts/`**, not its parent directory. Set `RUN_DIR` to a fresh isolated path-rebound run directory with the required basename, and the two anchor variables to the matching original files found above. The supplied R2 `mac_actual/candidate/runs/...` copy is evidence, not the target for a new write.

```bash
cd "$WECHAT_WORKTREE"
python3 scripts/wechat_pipeline_runner.py \
  --run-dir "$RUN_DIR" \
  --url "https://mp.weixin.qq.com/s/ZfZPPo1xSsfROmFZbaqSuw" \
  --title "风言风语信息更新 10.8" \
  --target-date 20261008 \
  --stage fetch \
  --adopt-frozen-package "$ZIP" \
  --adopt-package-sha256 c8a0dcfb548012bc8feb4e818e0cad7eead7de5a564a0ecaa85d64ce3763956f \
  --adopt-package-id wechat_20261008_ZfZPPo1xSsfROmFZbaqSuw_r1 \
  --adopt-input-digest c93e458747fe18fa33373785d79a9b026c15792d02fa9263db7b6f2bda48abc2 \
  --legacy-source-summary "$LEGACY_SOURCE_SUMMARY" \
  --legacy-source-manifest "$LEGACY_SOURCE_MANIFEST"
```

This explicit fetch stage must write a current `REVALIDATION_RECEIPT.json` with `historical_promotion_claimed=false`, `collector_invoked=false`, and `network_attempts=0`. The adapter does not call the collector or OCR engine. Saved-HTML `http_status=0` is eligible only after the raw HTML hash, identity, package, and both original source-file hashes validate through this route; unanchored status 0 remains rejected. Inspect the current state and receipt under `$RUN_DIR/evidence/wechat_article_fetch_adoptions/` for `ocr_cache_status` and `next_missing_stage`. OCR readiness is derived from the current verified artifacts; it is never inferred from an old summary or from the ZIP alone. Continue through the existing runner's next stage only when the state reports it is ready.

## Manifest comparison boundary

At first adoption, the original summary bytes and CSV bytes must match the frozen ZIP's source hashes exactly. The current summary must match every original field except the exact run-root mapping of these collector path keys: `html_path`, `image_manifest_path`, `ocr_text_path`, and `image_checkpoint_path` (the required current HTML and manifest paths must exist). All other summary values, including identity and HTTP status, must match.

The original, current, and packaged CSVs must keep the same column names and order and the same image row order. At first adoption, the only permitted row value change is `local_path`: it must map the same `wechat_article_images/<filename>` from the original run root to the current isolated run root and to the frozen package's ordered `images/IMAGE###.<ext>` member. URLs, indices, byte lengths, hashes, and all other row values stay bound to the original CSV and ZIP.

After the existing `prepare_ocr` step, the current CSV may update values in its already-present `download_status`, `image_size`, and `ocr_text_length` columns. No columns may be added, removed, or reordered; row order, `local_path`, URL, index, byte length, image hash, and every other field remain fixed. Status and dimensions are checked against the current image bytes; a changed non-empty OCR text length must match the verified OCR record for that image. `prepare_ocr` may refresh its own OCR slice manifest. The source summary, raw HTML, checkpoint, and existing OCR result/cache files are expected to retain their byte hashes.

Missing original anchors, an external or unsafe current path, symlinks, path traversal, a non-path summary mutation, a changed source row, or a mismatched raw HTML/image hash fails closed. A revalidation receipt records the current proof; it does not create historical attempt/promotion evidence. Linux tests use offline synthetic data and did not reread the Mac article or original images, execute the Mac collector, or run OCR. Actual Mac acceptance remains pending.
