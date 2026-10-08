# Issue #31 offline implementation plan

## Scope

Work only in the authorized candidate: harden the existing `wechat_article_fetch.py` adapter and the R1 `wechat_yesterday_performance.py` appendix disclosure. Add focused offline tests and a short default-flow note. Do not create or claim the missing pipeline runner, external intake collector, parent-level `AGENTS.md`, or Mac behavior.

## Failure model and approach

1. Reproduce the fetch failure through the real adapter `main()` with an isolated fixture collector: a valid BODY/image set followed by an OCR-only failure, then a verification-page response. Require that the adapter preserve the verified source and image order, never invoke a second BODY fetch while OCR is missing, preserve existing OCR/cache bytes, and report the next missing stage. Also reject an old run with an invalid summary and orphaned images.
2. Reproduce the appendix failure using synthetic prior mentions (A81/BJ3/HK24), real temporary Parquet files, a PARTIAL A/BJ receipt with an exact-row-count mismatch, and a missing previous-session HK receipt. Assert that all 108 listings remain, no market values are emitted, receipt coverage/status/authority/path/SHA survive, both Markdown and JSON disclose the separate failure states, and each market probe runs once.
3. Implement fail-closed attempt isolation and verified-source reuse in the adapter. Keep OCR and other existing run artifacts outside fetch promotion. Cache both successful and failed appendix probes; preserve readable receipt facts while returning no rows on a failed binding. Keep the R1 source line endings intact.
4. Run the focused offline tests, then relevant existing WeChat regressions. Save commands and exit results under `issue31/writer_evidence/`. Report Mac runner/collector behavior as unverified because those sources and hardware are absent from the snapshots.

## Acceptance boundaries

Only temporary synthetic data is used by tests. The changes do not fetch real articles or market data, install OCR, modify schedulers/pointers, restart services, deploy, stage, alter a BUY gate, or trade.
