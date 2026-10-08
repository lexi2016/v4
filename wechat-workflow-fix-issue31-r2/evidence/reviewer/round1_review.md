# Issue #31 independent review — round 1

**Verdict: do not accept this snapshot.** It contains six blocking P1 fetch findings and one P2 appendix disclosure gap. This is a historical review of the first frozen candidate; the writer later resumed fixes, so these findings apply to the exact SHA set below and do not decide the later snapshot.

## Snapshot reviewed

The supplied baseline is `bdb736bddd3c04e061eff0a43c47104523d144a0` with the R1 overlay at `e7dcf69d342a43d605521d551aafb4dc5c3911af`. I verified the exact bytes and sizes of the four round-one product/test files before running tests:

| File | SHA-256 | Bytes |
| --- | --- | ---: |
| `candidate/wechat/scripts/wechat_article_fetch.py` | `988d6d10acb427c2ba8624443342c22f248cce08348d3bf0e09aff4477d2b597` | 49,555 |
| `candidate/wechat/tests/test_wechat_article_fetch_recovery.py` | `cd5fcaaa24b8fa33ba8ee756f70c2b13a45a0e5134e262860405b7b18c5340c4` | 13,499 |
| `candidate/wechat/scripts/wechat_yesterday_performance.py` | `6723cb4b57e7c95c6bfe4ed3fce4dc61cbcb588e5d633a8be11bb753f49d6445` | 88,428 |
| `candidate/wechat/tests/test_prior_mentions_performance_appendix.py` | `315b78978e0ba8c715d573229a5eeee40c0351cafa6a644430c8288c6ce340df` | 25,364 |

The candidate tests use a mocked isolated collector, Pillow-generated decodable PNGs, temporary Parquet panels, and offline-only fixtures. Those are useful source regressions; they do not exercise the real Mac workflow.

## Blocking findings

### P1 — empty BODY accepted from a summary claim

I supplied an 83-byte HTML document with an empty `<body>`, a header-only image manifest, and a summary that claimed `article_body_found=true` and `text_preview_length=18`. The adapter promoted it, returned 0, and reported `SOURCE_CAPTURED_BODY_READY` with `BODY_IDENTITY_VERIFIED`. The adapter relies on summary claims for body presence and does not establish a real article BODY from the HTML bytes. This allows an invalid source to become the verified source.

### P1 — cached HTTP source reuses changed HTML bytes

After a successful capture, I replaced only `wechat_article_raw.html` and kept the existing identity summary and its `identity_validation.raw_html_sha256`. The next invocation returned `SOURCE_REUSED_NEED_OCR`; it did not compare the changed bytes to the recorded SHA. A later stage can therefore consume HTML that no longer matches the immutable identity evidence.

### P1 — cached image URL sequence can change after prepare

I created 50 decodable PNGs, ran the real `wechat_prepare_ocr.main()`, changed only the first manifest URL, and kept all image bytes, hashes, and indexes unchanged. Fetch reuse still returned `SOURCE_REUSED_NEED_OCR`. Reuse must bind the ordered source URL projection as well as image bytes, while allowing `prepare_ocr` to add its legitimate OCR fields.

### P1 — `OCR_OK` summary alone marks the package as next

I wrote only `wechat_article_ocr_summary.json` with `status=OCR_OK` and `image_count=50`; `windows_ocr_results.json` and `windows_ocr_checkpoint.json` were absent. The next invocation reported `next_missing_stage=package`. The state machine treats a summary status as proof of OCR completion without checking the corresponding results/checkpoint artifacts.

### P1 — `--o` bypasses isolated output rewriting

With `--out <run> --o <escaped-output>`, the `argparse` abbreviation remained in the child arguments. The isolated fake collector wrote `wechat_article_raw.html` into `escaped-output` before the adapter rejected the missing attempt-local summary. This breaches the new attempt output boundary.

### P1 — saved-HTML promotion cannot recover after summary commit

I injected one `KeyboardInterrupt` immediately before `PROMOTION_RECEIPT.json` was created, after the active summary had been committed. The next `main()` call returned 2 with `saved HTML source lacks an immutable promotion receipt`; `_existing_verified_source` failed before pending-attempt recovery could run. This leaves a validated saved-HTML attempt unable to resume at that interruption point.

## P2 appendix disclosure gap

When the current HK receipt was readable but its Parquet panel SHA no longer matched the receipt/manifest, the helper raised after reading the receipt. The caller returned a generic `CANNOT_CONFIRM` probe and dropped the observed receipt status (`READY`), row count, and receipt SHA. All HK price rows stayed null, so this is a facts-disclosure gap rather than an incorrect price observation. The tested missing-prior-session path did retain the current receipt SHA and the exact missing receipt date/path.

## Passing regression evidence on this snapshot

- The frozen fetch regression file passed **7 tests**. It covers real synthetic PNGs, the actual prepare step, reuse without another collector call, and interruption during image promotion.
- The appendix regression file passed **6 tests**. Its 108-listing fixture keeps A81/BJ3/HK24, preserves receipt facts on the A/BJ row-count mismatch, emits null prices and `CANNOT_CONFIRM` rows, distinguishes 5137/5800 panel coverage from the 108 listing universe, records the missing HK prior receipt, and caches failed probe functions once.
- The adjacent `test_chat_review_regressions.py` passed **29 tests**; one pre-existing Starlette deprecation warning was emitted. Invalid HK denominators (`0`, `None`, `NaN`, `Inf`, boolean) still leave the invalid listing unobserved without discarding a separate valid listing.
- The six independent fetch counterexamples and the single HK receipt-facts counterexample failed as expected. Their exact logs, probe scripts, and hashes are indexed in `round1_review.json`.

The first run of the reviewer-only probe file also collected the imported candidate `TestCase`; I corrected the reviewer harness to import that helper inside setup and to point `collector_calls` at the helper fixture. The corrected run still produced exactly six intended counterexamples. No candidate source or candidate test was changed by that correction.

## State and limits

`SOURCE_CANDIDATE_TESTED`: yes, for this exact source snapshot and offline fixtures only. `REVIEWED`: blocked by six P1 findings and the P2 disclosure gap. `BEHAVIOR_VERIFIED`: isolated synthetic regressions/counterexamples only.

`MAC_BEHAVIOR_CANNOT_CONFIRM`: the active Mac runner, external collector, parent-level `AGENTS.md`, and live runtime are absent from the supplied source snapshot. I did not invoke real Mac Vision, WeChat, scheduler/panel data, Drive, or a full recovery-to-Drive workflow. Those behaviors remain `CANNOT_CONFIRM`; Linux fixtures do not establish them.

No P0 finding was observed. The round-one report and logs do not imply deployment, production use, BUY-gate changes, orders, or real-world behavior verification.
