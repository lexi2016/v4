# PDF text preparation

The batch now has two separate stages. `--prepare-text-only` extracts and quality-checks page text, stores source-bound page checkpoints, and records a terminal outcome for each selected document. It never binds the local model runtime or sends a model request. An explicit `--document-id` selection is a partial sample: it returns `PARTIAL_SCOPE_COMPLETE`, creates no model-consumable manifest, and cannot satisfy the execution gate.

Only a run that processes the frozen 2,209-document inventory can write `prepared-text-manifest.json`. It is `FROZEN_COMPLETE` only after every inventory row is `READY`, `QUARANTINED`, or `FAILED` and `pending=0`. The manifest, its parent inventory SHA, every document receipt, page checkpoint, and page-input SHA are verified before model execution. Only `READY` documents are eligible. The model stage reads the frozen page inputs and does not extract, render, or OCR PDFs.

To prepare the four previously identified watermark PDFs as a text-only canary, run this from the implementation worktree. It writes a partial-scope receipt under the existing PDF research `prepared/` directory and deliberately cannot open the model gate:

```sh
cd /Users/lexi/.codex/worktrees/pdf-text-preprocess-20261019/v4_app
/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python -m ops.run_pdf_research_batch \
  --manifest /Users/lexi/Desktop/学习/agents调试/V4_PDF_SIMPLE_BATCH_20261018_R1/inventory/batch-manifest.json \
  --prepare-text-only \
  --prepare-run-id watermark-canary-20261019-r1 \
  --document-id 7052556b692edfebc775264197739f05bd31689673d09d34137aa06ab9abbc45 \
  --document-id ec5bf849aa8396938f760aeae69faf0c9b437624ad6cd0495352c0d10e6ad209 \
  --document-id fd8339f54835829ef83e649b54465c178a6d2dc0cd826ac3369fdcaed6a91b4e \
  --document-id be787224b08e3655c16331260adbafdd08cca3a3bfd830a2d3a485f476084aaa
```

The only full-cohort preparation command omits `--document-id`. Resume the same run ID for the exact parent inventory and extractor identity. Use a new ID only for a changed binding; matching existing page checkpoints are imported:

```sh
cd /Users/lexi/.codex/worktrees/pdf-text-preprocess-20261019/v4_app
/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python -m ops.run_pdf_research_batch \
  --manifest /Users/lexi/Desktop/学习/agents调试/V4_PDF_SIMPLE_BATCH_20261018_R1/inventory/batch-manifest.json \
  --prepare-text-only \
  --prepare-run-id full-cohort-20261019-r1
```

After an independently reviewed full-cohort manifest is available and its existing model-stage authorization has been rebound to the reviewed source and manifest, pass its exact path and SHA-256 to the existing remaining-document dispatcher. The dispatcher still requires its existing root authorization and pilot gates:

```sh
cd /Users/lexi/.codex/worktrees/pdf-text-preprocess-20261019/v4_app
/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python -m ops.run_pdf_research_remaining_once \
  --prepared-text-manifest \
  "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/pdf_local/research/prepared/full-cohort-20261019-r1/prepared-text-manifest.json" \
  --prepared-text-manifest-sha256 <sha256-from-prepare-receipt> \
  --execute
```

`PREPARATION_INCOMPLETE` has no frozen manifest and cannot enter the model stage. `PARTIAL_SCOPE_COMPLETE` is useful only as a sample receipt. `FROZEN_COMPLETE` means every input document has a terminal preparation disposition; quarantined and failed documents remain excluded from model use. The report receipts preserve prior successful reports and list hash-bound `supersedes` references when the prepared page text changes.

## 2026-10-19 bounded release and retained work

`PREPROCESS_RELEASE` and `MODEL_CONTINUATION` are separate acceptance surfaces. An independent `PREPROCESS_PASS` may release full preparation after the source-selection, serial OCR, checkpoint reuse, isolated document failures, resource pause, and full-manifest round-trip checks pass. Full preparation does not wait for model authorization migration. Model execution still requires the complete frozen manifest and its own independent acceptance.

Use the same run ID to resume unchanged inputs and source identity. A new run imports page checkpoints from matching parent/PDF/page/extractor identities, verifies each text hash, and writes new immutable references; it does not overwrite the old run. The completed Sol native/scan/mixed canary is explicitly compatible after the model-only input bridge/count-verifier changes: its original extractor SHA, unchanged extraction AST under Python 3.12, pinned PDF helpers, and Vision/render identities must match. This narrow migration fails closed if those extraction functions change. The older cached four-document watermark evidence is retained; its original caches remain reusable.

Image presence is checked for every native page without a qualified replacement cache. A passing native text layer cannot suppress OCR of an embedded image body. Unresolved/unknown image identity is quarantined. A short OCR footer can also remain quarantined; a terminal disposition does not establish semantic source accuracy. OCR remains serial. Before each page the existing 8-GiB available-memory/512-MiB swap-growth gate can return `PAUSED_RESOURCE`; existing page checkpoints remain, no document failure or consumed OCR attempt is manufactured by that pause. Resume the same run after the resource condition clears. Per-document extraction failures receive immutable FAILED receipts and processing continues; identity/integrity conflicts stop the run.

The model dispatcher now uses the original `remaining-execution-r1` journal. It excludes non-READY frozen rows before selecting a new child, and refuses a fresh root that would hide historical dispatches. The root authorization and adoption evidence must both bind `prepared_text_manifest_sha256`; old authorizations intentionally fail until the controller issues the exact reviewed binding. The original 39-event prefix/HALT, old authorization, failure SSE and measured resource-change adoption remain required. Neither a new journal nor a new prepared manifest clears that HALT.

For a legitimate historical memory recovery, a READY prepared input may retain the original page-input bytes/SHA only through `prepared-recovery-input-bridge.json`: same PDF/parent, exact page count and sequential page numbers, identical nonempty text on every page, verified text hashes, and hash-bound historical input. The new immutable bridge binds both input SHAs, the prepared manifest and extractor identities. Metadata-only changes are not source-body defects. Any changed/missing page remains blocked. The original input, receipt and journal are never rewritten.

`audit_historical_inputs` audits bound historical inputs without OCR/model calls or report rewrites. The frozen membership receipt selects the exact 90 completed IDs plus seven journal successes; two additional discovered receipts remain separately visible outside that 97-item cohort. Image presence or repeated furniture alone requires source review; only the four already visually evidenced watermark PDFs, missing pages, or empty input pages establish the deterministic invalid-input disposition. No such audit proves a report's complete semantic correctness or authorizes automatic regeneration of every changed-metadata report.
