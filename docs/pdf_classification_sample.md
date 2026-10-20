# Offline PDF ledger and classification sample

This one-purpose tool consumes a fixed existing OCR progress snapshot and the original 2,209-document manifest. It writes derivative review artifacts only: full identity CSV/JSON, candidate statistics, a reproducible 60-document evidence sample, ten real material-relation examples, and a standalone HTML report. It never extracts PDFs, performs OCR, calls models, downloads data, starts a service, deletes/merges material, or changes the original OCR run.

The progress file must first be read once into a snapshot with its exact SHA and capture time. Only terminal rows in that snapshot can supply existing immutable receipt/page-input references. Later live OCR additions do not enter this delivery. Pending rows stay visible in the 2,209 denominator. Every input receipt, page-input and page-text SHA is checked; identity/coverage/hash drift fails closed.

## Reproduce

Use the existing Python runtime and a derivative evidence directory containing:

- `input/batch-manifest.json`, exact original manifest SHA.
- `input/ocr-progress-snapshot.json` and `snapshot-receipt.json`, single-read frozen progress.
- `input/industry-taxonomy.json`, extracted labels/version/source SHA from the existing canonical `CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP`; no new industry authority.
- `input/selection60.json`, frozen sample IDs bound to manifest/progress SHAs.
- `input/writer-sample-review.json` and `writer-relations-review.json`, scoped manual readback decisions with page/excerpt hashes; independent semantic acceptance is separate.

```sh
python -m ops.build_pdf_classification_sample \
  --input-root /absolute/derivative-evidence/input \
  --prepared-root /absolute/existing/prepared/full-cohort-sol-20261019-r1 \
  --output-root /absolute/derivative-evidence/delivery \
  --selection /absolute/derivative-evidence/input/selection60.json \
  --sample-review /absolute/derivative-evidence/input/writer-sample-review.json \
  --relation-review /absolute/derivative-evidence/input/writer-relations-review.json
```

To initially freeze the existing dictionary, supply `--taxonomy-source` pointing to canonical `infrastructure/research_peripheral_store.py`. AST literal reading extracts only the existing 24 theme labels and mapping version; it does not import or execute that source. These are text-topic candidates, not issuer industry assignments, listed-security mappings, or market eligibility.

## Evidence and classification boundaries

All 2,209 rule classifications remain candidates. Filename text is a hint; body publication/record/news structure controls material classification. A broker report citing minutes or a white paper remains broker research. A `风口研报` news compilation does not become a broker original because it quotes several analysts. Institution abbreviations have Latin token boundaries: `UBS` must not match `Subsidlary`. Date candidates exclude related-research sections and export/transcript timestamps; reviewed publication/header dates retain literal body evidence, otherwise unknown. Collection-directory dates are separately labelled and never substituted for report dates.

The Writer sample distinguishes main research subjects from mentioned companies and retains literal name evidence. It supplies no guessed ticker/exchange mappings. Some old audio-derived guides contain incoherent text and cannot authenticate their branded filename: classify the derivative material, keep source/content uncertainty visible, and route it to REVIEW. Six main categories do not imply that the current snapshot contains at least five verified documents in every category; shortfalls stay explicit. The sample deliberately covers boundary/quality cases and is not a random estimate of population frequencies or overall accuracy. Rule/Writer disagreements and per-class source/content uncertainty (including non-READY inputs) are reported, and independent semantic accuracy is not self-scored.

Routes are SAVE, REUSE_CANDIDATE, REVIEW, LIGHT_EXTRACTION_CANDIDATE, or DEEP_RESEARCH_CANDIDATE. They are candidates only. No explicit research question means no automatic deep-research/high-value assignment. No reviewed valid existing-result binding means no executed analysis reuse. No summaries, three research packages, investment analysis, or buy signals are generated in this phase.

## Document relations

Exact text identity uses NFC plus whitespace collapse per page, with page sequence preserved. Digits, signs, dates, units, case and numeric/word boundaries are retained: `1 2` differs from `12`, `-5%` differs from `+5%`. The original PDF SHA remains separate. Exact normalized text matches retain every source record; fuzzy title/topic overlap proposes candidates only. Numeric-token differences explicitly cover only the stated prepared-page window, not a complete factual audit. OCR/watermark differences do not automatically establish a new forecast or a revised report. Same theme is a retrieval group, never sufficient grounds to merge.

`report.html` is self-contained for viewing/filtering all 60 samples and ten relation examples, with no external scripts/styles or server. Linked CSV/JSON provide the full ledger. All snippets are HTML escaped and checked against the bound page text. CSV formula-like fields receive a display-only apostrophe; JSON identities and deduplication inputs are unchanged.

## Acceptance

Run only `tests/test_pdf_classification_sample.py` for this tool. Writer test results are handoff evidence. Independent review must reconcile all 2,209 IDs; assess the 60 material labels (target at least95%, with per-class uncertainty disclosed); review ten relation pairs with zero false merges; and confirm zero security-code mismatches. Passing local mechanical checks does not establish full-cohort semantic acceptance or authorize model analysis. The original OCR executor continues independently.
