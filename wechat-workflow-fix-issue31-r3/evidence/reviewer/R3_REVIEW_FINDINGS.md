# Issue 31 R3 independent review

**Verdict:** `REVIEWED=PASS_OFFLINE_SCOPE`; `SOURCE_CANDIDATE_TESTED=PASS`; `BEHAVIOR_VERIFIED=PARTIAL`. The R3 saved-HTML revalidation has **not** been run on the actual Mac, so `MAC_R3_REVALIDATION=CANNOT_CONFIRM`. Full Drive ZIP raw-byte readback remains `CANNOT_CONFIRM`. There are no open P0/P1/P2 product-source findings in the reviewed offline scope. The prior P1 `R2-MAC-001` is resolved in the frozen candidate.

## Frozen files reviewed

The three changed product/test files match the frozen byte bindings:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `candidate/wechat/scripts/wechat_article_fetch.py` | 91,948 | `192564aea7421a9af42b0116c32708848765cbb433c8692351f0db75098b860f` |
| `candidate/wechat/scripts/wechat_pipeline_runner.py` | 77,999 | `46d8761e44a250642cbcd7a513604fad1148d09726010d6f0eab5f269f256bcd` |
| `candidate/wechat/tests/test_wechat_article_fetch_recovery.py` | 52,232 | `3c2316ff77f291c91bb2d04efe00b3f0304c9c8cdf461d731da48b3435d83e92` |

I also byte-checked the corrected Writer receipt (`bebde41f…e7d86c`, 17,417 bytes) and Mac acceptance instructions (`a4cc517f…f6b8f1`, 8,168 bytes). The receipt correctly records comment `6072731268`, the baseline reproduction's exit code `0`, and preserves the initial metadata files. The command document requires verifying the complete ZIP SHA before trusting its manifest hashes and defines `WECHAT_WORKTREE` as the `wechat` root that contains `scripts/`.

## Independent checks

The full affected suite ran from the candidate tests directory on Python 3.12.14/Linux with pytest 9.1.1:

```text
python -m pytest -vv --basetemp=/workspace/scratch/64559d708105/issue31/r3/reviewer_scratch/pytest_final/fetch_recovery test_wechat_article_fetch_recovery.py
25 passed, 3 subtests passed; exit 0
```

Log: [r3_fetch_recovery_pytest.log](/workspace/scratch/64559d708105/issue31/r3/reviewer_evidence/r3_fetch_recovery_pytest.log), SHA-256 `865f1c04de08a3b04382e148d1c853dd58e9acd989f848d731a6e5187e89860e`.

The focused adoption/refusal selection also passed (`2 passed, 23 deselected`, exit 0). It is a subset of the full suite and is not added to the full-suite count. Log SHA-256: `f5e19c800b3beb028da2e187c4e80d127819d4635ada67107ca79265fc700017`.

I ran a separate [reviewer end-to-end probe](/workspace/scratch/64559d708105/issue31/r3/reviewer_evidence/r3_runner_resume_prepare_probe.py) against the frozen candidate. It used an offline synthetic frozen ZIP, source summary/CSV and 50-image cache, then executed the actual candidate runner, adapter subprocess and existing `prepare_ocr` child path for saved HTML with `http_status=0`. Adoption ran through `--stage fetch`; a resume then reported `fetch SKIP_RESUME` and `prepare_ocr RUN`. It verified all 50 images under the isolated run root, preserved source and existing OCR result/cache hashes, produced one revalidation receipt, reported `next_missing_stage=package`, and observed zero collector calls or network attempts during adoption/resume. Exit code was 0; log SHA-256 `b40cdf7079e79039156054c592243622f76f29379597b02d7e00e478b939fe0a`.

Fixture setup emitted a prior synthetic collector fixture result (`collector_returncode=17`) before the measured adoption/resume. That fixture creation is not historical collection evidence. The measured stages called no collector and attempted no network. The probe patched the runner platform branch in Linux; it does not establish actual Mac behavior.

The baseline repro log [r2_mac_001_baseline_repro.log](/workspace/scratch/64559d708105/issue31/r3/reviewer_evidence/r2_mac_001_baseline_repro.log), SHA-256 `e8f55fb0e6d1a9e5646a3a5af13a2c725c3b6be176b79e08350603f595496771`, records the old defect: a text-bearing BODY with an mmbiz image and no manifest rows was accepted with `identity_image_count=0`, while a duplicate-URL image-only BODY was rejected despite the real collector's ordered unique mmbiz projection. The frozen R3 tests now cover the collector-bound ordered projection for text and image-only BODYs, missing rows, de-duplication/order, GIF/non-mmbiz exclusion, and source binding.

## Findings and acceptance boundary

**Resolved P1 — `R2-MAC-001`.** R3 validates each BODY against the actual bound collector's ordered unique mmbiz image projection, including BODYs with text. It no longer treats a summary claim as the BODY source. The candidate regression suite and separate baseline evidence support closure for the frozen source.

**Historical revalidation — pass for offline scope, Mac replay pending.** Adoption requires the caller-supplied frozen ZIP SHA, package ID and input digest; the existing handoff validator checks the ZIP and descriptor. The exact original summary/manifest bytes must match the ZIP's `source_intake_sha256` and `source_manifest_sha256`. The current isolated copy is limited to exact run-root rebinding for the four collector summary path keys and manifest `local_path`; stable values, row order and image identity remain bound. The current raw HTML, BODY projection, image bytes and safe in-run paths are checked. Unanchored `http_status=0`, non-path summary edits, external paths, traversal, and symlinks are refused. The receipt records current revalidation only; it does not claim a historical promotion or collector run.

The Linux synthetic end-to-end probe demonstrates the adapter/runner/prepare mechanism and OCR cache preservation. It does not prove that the original Mac ZIP, summary, manifest or raw HTML files are present, that the Mac paths were prepared as documented, or that this sequence runs successfully on the actual Mac. The R3 Mac replay remains required before claiming restored real-run behavior.

## Inherited Mac evidence and remaining limits

Earlier R2 Mac evidence remains useful for its original scope: 17 fetch recovery tests, three targeted appendix tests, saved-HTML/cache reuse for 50 images with no network attempts, and runner OCR-cache reuse with zero OCR attempts. It also records that the ordinary historical fetch failed closed before R3's explicit adoption path existed. Those results were not rerun or upgraded to R3 acceptance here. No fresh collector request, Vision/OCR engine execution, product data modification, deployment, or issue closure occurred in this review.

Drive metadata was available, but the full ZIP artifact download returned HTTP 403/code 1010, so its raw bytes remain `CANNOT_CONFIRM`. The parent readback evidence is [DRIVE_R2_ZIP_READBACK.json](/workspace/scratch/64559d708105/issue31/r3/root_evidence/DRIVE_R2_ZIP_READBACK.json), SHA-256 `6a819e6f5b947ffd9c0798bee02b04fd0d7ad8757e298ed53e195cfd672409a4`.

Machine-readable bindings, commands, exits, log hashes, inherited Mac evidence, and boundaries are recorded in [R3_REVIEW_RECEIPT.json](/workspace/scratch/64559d708105/issue31/r3/reviewer_evidence/R3_REVIEW_RECEIPT.json).
