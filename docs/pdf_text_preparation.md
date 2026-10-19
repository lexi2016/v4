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

The only full-cohort preparation command omits `--document-id`. Give each attempt a new run ID; reuse the same run ID only to resume that exact parent inventory and extractor identity:

```sh
cd /Users/lexi/.codex/worktrees/pdf-text-preprocess-20261019/v4_app
/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python -m ops.run_pdf_research_batch \
  --manifest /Users/lexi/Desktop/学习/agents调试/V4_PDF_SIMPLE_BATCH_20261018_R1/inventory/batch-manifest.json \
  --prepare-text-only \
  --prepare-run-id full-cohort-20261019-r1
```

After an independently reviewed full-cohort manifest is available and the model stage is separately authorized, pass its exact path and SHA-256 to the existing remaining-document dispatcher. The dispatcher still requires its existing root authorization and pilot gates:

```sh
cd /Users/lexi/.codex/worktrees/pdf-text-preprocess-20261019/v4_app
/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python -m ops.run_pdf_research_remaining_once \
  --prepared-text-manifest \
  "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/pdf_local/research/prepared/full-cohort-20261019-r1/prepared-text-manifest.json" \
  --prepared-text-manifest-sha256 <sha256-from-prepare-receipt> \
  --execute
```

`PREPARATION_INCOMPLETE` has no frozen manifest and cannot enter the model stage. `PARTIAL_SCOPE_COMPLETE` is useful only as a sample receipt. `FROZEN_COMPLETE` means every input document has a terminal preparation disposition; quarantined and failed documents remain excluded from model use. The report receipts preserve prior successful reports and list hash-bound `supersedes` references when the prepared page text changes.
