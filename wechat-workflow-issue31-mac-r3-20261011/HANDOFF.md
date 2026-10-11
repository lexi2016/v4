# Issue #31 R3 Mac acceptance handoff

Writer-side actual Mac acceptance is complete for the frozen R3 candidate and is ready for independent review. This is not integration, deployment, Issue closure, or final acceptance.

- Writer receipt: `WRITER_RECEIPT.json` (SHA-256 `3de3df5aafd8c35e6ab23130890dcbe26ee43cb65b97a6e515d31b8a086a0998`)
- Evidence inventory: `evidence_inventory.json` (SHA-256 `a03100f40fa599eef98c7b8e7bd67945675636ad9e7b998d837fc11f249307a3`, 149 files)
- Candidate root: `working/wechat/`
- Actual patch: `github/actual_diff.patch` (SHA-256 `739df58d9cfb1213bfa7ff879ecd4ec660c1778acb3d85ad1a92ce619ecc1f12`)
- Fixed GitHub base: `lexi2016/v4` at `fd57619a99dfe88266f1e2d78475b94ffdd161c4`
- Working run: `working/runs/20261008_html_recovery_ZfZPPo1xSsfROmFZbaqSuw/`

The three patched candidate files match `SOURCE_MANIFEST.json` after-SHA values; patch reverse dry-run succeeds. Added body-binding tests: 6 passed. Real runner explicit adoption, default fetch reuse, and `prepare_ocr` each exited 0. The actual child fetch commands contained `--skip-ocr`; explicit adoption wrote only its new revalidation evidence; default fetch reused it. All seven rejection probes failed closed with expected exit code 2. The prepare comparison passed: 50 images were decoded and byte-verified; source summary, raw HTML, checkpoint, and existing OCR result/cache files stayed byte-identical; CSV stayed unchanged; only the OCR slice manifest refreshed as permitted; no new fetch/OCR attempts or network guard events were recorded. The focused existing adoption-rejection regression passed (1 test). R2 Vision50 was not rerun.

Reviewer rerun entry points (all within this isolated evidence tree):

1. `working/run_explicit_adoption.sh`
2. `working/run_default_fetch_reuse.sh`
3. `working/run_prepare_ocr.sh`
4. Run the body-binding unittest shown in `WRITER_RECEIPT.json` from `working/wechat/tests/` using the recorded Python 3.12.14 environment.
5. Run the focused pytest command shown in `WRITER_RECEIPT.json`.
6. `working/run_rejection_probes.py` with the command and environment recorded in the receipt.
7. `working/compare_prepare_ocr_state.py` to compare the before/after snapshots.

Known non-acceptance gaps: independent `REVIEWED`/`BEHAVIOR_VERIFIED` are pending; Drive full ZIP byte readback remains `CANNOT_CONFIRM` because the prior fixed R2 attempt returned HTTP 403/code1010; the batch is not integrated or deployed and does not close Issue #31.
