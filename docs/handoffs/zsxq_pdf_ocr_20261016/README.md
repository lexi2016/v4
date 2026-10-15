# ZSXQ PDF download, local OCR, and research workbench

This delivery reuses the existing authenticated `zsxq-cli` and the generic Apple Vision OCR implementation already installed locally. Existing Poppler tools render each PDF page. It does not introduce an OCR service, cloud OCR call, database, or another source producer. Routine execution does not call Codex; development and review agents do use Codex.

## Behavior

- The existing hourly task starts a bounded PDF continuation only after its main research work succeeds. PDF pending/failure states do not change that main result. Partial work resumes through the existing source-bound derived index; completed documents are reused.
- Raw topic attachments, including topics excluded by stock/entity analysis, supply the inventory. Original source files are not rewritten. Source date, slot, run ID, input hashes, PDF hash, page hashes, and actual processing times remain bound to receipts.
- A verified partial PDF reuses its cached bytes; `downloaded_at` means the most recent real download, not an invented first-download time. Unknown PDF publication time stays unknown. Explicit compact offsets such as `+0800` are displayed as the equivalent `+08:00`; missing offsets are not inferred.
- Missing exact-date enumeration is unassessed, not zero. Verified empty enumeration may report zero. Raw PDF references with incomplete identity prevent an empty-result claim.
- The research lane exposes a metadata/excerpt projection and a read-only exact-date document-detail endpoint. The existing feed can expand all OCR pages and the final-page excerpt, displaying page progress and provenance. Old asynchronous details cannot replace a newly selected date/document.
- Late OCR appears as a current-knowledge supplement and is not injected into historical scores or trading decisions. `research_only=true`; production, BUY, and order flags remain false.

## Scope and verification

Batch 1 independently verified an actual two-page PDF download and local Vision OCR, including page/text correlation, hashes, and retry reuse. Batch 2 independently passed API tests (19), scheduler tests (19, with the API-only case covered separately), and focused frontend tests (34). Browser acceptance then identified and drove the narrow timestamp/cache/unknown-count repairs in Batch 3.

Final deployment, API readback, browser evidence, and final commit identity are recorded in `delivery.json` when complete. Natural hourly continuation is explicitly separate from the manual real-PDF canary. The canary does not claim that the remaining queue has completed or that the OCR text has undergone semantic investment analysis.

Known unrelated baseline failures remain: one research-lane capture-provenance fixture lacks `captured_at`; global frontend type checking reports pre-existing manager/fixture spec errors. No manager, WeChat, or Vibe implementation was changed for this delivery. The existing WeChat OCR source is reused read-only.

## Source and runtime packaging

Canonical source is the V4 workspace. The PDF module is byte-identical across canonical and the API/scheduler packages. Runtime router/runner shapes differ from canonical, so the deployment uses explicit function-level deltas on exact active releases, preserving other files. Runtime-specific deltas are archived alongside this handoff; package manifests retain their base identities and per-file proof. Immutable manifest creation status is not the live process status; LaunchAgent, PID/cwd, and API readback establish activation.

Only necessary source, tests, and sanitized handoff evidence are synchronized to private `lexi2016/v4`, branch `codex/zsxq-pdf-ocr-20261016-r1`. No PDFs, OCR bodies, source responses, credentials, signed URLs, build directories, or business archives are uploaded. Batch 1 commit: `f44a6b631deb0fb60cf0ee0b7522b86607669d75`. Batch 2 commit: `80bf688aca718f3566bd9c5a1459598f69a1358f`.

Rollback is a switch to the prior code release using the preserved local plist and release lock. It does not remove PDF data, rewrite historical receipts, or move any latest business-data pointer backward.

## External implementation references

- [Apple Vision text recognition](https://developer.apple.com/documentation/vision/recognizing-text-in-images): the existing local recognition engine used here.
- [Docling full-page OCR example](https://docling-project.github.io/docling/_generated/examples/full_page_ocr/): page-based PDF processing pattern, without installing another framework.
- [OCRmyPDF cookbook](https://github.com/ocrmypdf/OCRmyPDF/blob/main/docs/cookbook.md): sidecar output alone does not establish complete page coverage; this pipeline checks page completion explicitly.
