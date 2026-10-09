# R3 Writer Implementation Plan

## Goal

Close reviewer finding R2-MAC-001 and support explicit, evidence-bound recovery of the historical saved-HTML run in the isolated R3 Mac-source candidate. Keep the real external collector and existing OCR/handoff consumers. Do not deploy, use production or market data, run the OCR engine, or modify the collector or handoff consumer.

## Baseline and regression target

1. Reproduce both supplied BODY/image-binding findings against the frozen R2 candidate and keep full red logs.
2. Add focused tests to the existing `test_wechat_article_fetch_recovery.py` (no third test file): every BODY uses the real collector's `js_content` image URL projection (mmbiz only, GIF filtered, first-seen order, URL de-duplication), and the manifest must exactly match it while existing path/index/hash gates remain enforced.
3. Test historical recovery through the real runner and adapter. Write a new append-only current revalidation receipt; do not synthesize a past attempt or promotion. Reuse verified source/image bytes and existing OCR cache bytes without collector fetch or OCR execution. Test explicit saved-HTML `http_status=0` with frozen package anchors, and reject the same legacy source without anchors.
4. Add only an explicit opt-in adoption route through the actual runner into the existing adapter. Verify the frozen package with handoff `_validate_package_zip`; bind the original summary/manifest bytes by the ZIP's source SHA fields; revalidate current BODY, source image projection, image bytes, identity and article_research fields. The original-to-current summary mapping is limited to `html_path`, `image_manifest_path`, `ocr_text_path`, and `image_checkpoint_path`; image `local_path` must map the same filename under the old and isolated run roots. Do not rewrite historical summary/manifest bytes or fabricate an R2 attempt/promotion receipt. Runner validation must recheck the current receipt and artifacts before resuming.
5. Require first-adoption manifest columns and row order to match the original source and frozen ZIP exactly, except for the `local_path` root mapping. After `prepare_ocr`, permit only its known `download_status`, `image_size`, and `ocr_text_length` field updates; validate download status and dimensions against current image bytes, and validate any non-empty changed OCR length against verified OCR records. Keep all other columns and row order bound to the original source/ZIP.
5. Use the existing `test_wechat_article_fetch_recovery.py` for P1 and controlled-adoption cases; no additional test file is planned. Run only focused regression cases and the affected existing fetch recovery suite; log each command, exit code, complete stdout/stderr, network-guard outcome, and log SHA under `r3/writer_evidence/`.

## Historical-copy boundary

The current Mac Writer receipt pins the original R1 package at ZIP SHA `c8a0dcfb548012bc8feb4e818e0cad7eead7de5a564a0ecaa85d64ce3763956f`, package ID `wechat_20261008_ZfZPPo1xSsfROmFZbaqSuw_r1`, and input digest `c93e458747fe18fa33373785d79a9b026c15792d02fa9263db7b6f2bda48abc2`. The cited R2 copy receipt is 6,380 bytes / SHA `709350d03c1bf1fa37be42070d7710346c0cb485dd4db052011d18e8cafd8d4e`, but its bytes are not in the R3 input bundle, so this candidate does not rely on or infer its schema. Explicit adoption requires the frozen ZIP with its external expected SHA/id/digest and the exact original summary/CSV files from the source run; those two raw files must hash to the package's `source_intake_sha256` and `source_manifest_sha256`. The isolated current copy must already have consumer-safe paths under its own run root. Missing original summary/CSV, an unresolved old absolute current path, or any non-path identity/content mismatch remains fail-closed. The original ZIP, current Mac run, raw article, and 50 original images are not available in this Linux workspace, so tests use synthetic offline artifacts and do not claim to reread them or execute Mac OCR.

## Pass criteria

- Both supplied red reproductions are resolved: missing manifest rows reject; duplicate URL, GIF, and non-mmbiz projection follows the actual collector contract.
- Valid controlled historical source with saved-HTML `http_status=0` can pass through the real runner → adapter → `prepare_ocr` path offline. The revalidation receipt reports the local OCR cache status separately and never claims past promotion. Existing OCR results/checkpoint/text/summary byte hashes remain unchanged; `prepare_ocr` may refresh its own `ocr_slice_manifest.json` and its three identified mutable manifest fields.
- Missing or altered identity/artifacts remain refused; no previously validated image is fetched again.
- Exact product write scope is `r3/candidate/wechat/scripts/wechat_article_fetch.py`, `r3/candidate/wechat/scripts/wechat_pipeline_runner.py`, and `r3/candidate/wechat/tests/test_wechat_article_fetch_recovery.py`; records remain in `r3/writer_evidence/`.
