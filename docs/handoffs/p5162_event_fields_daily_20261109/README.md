# P5162 panel-reference daily fields: candidate handoff

This is a research-only, isolated candidate. No runtime, scheduler, producer formula, model, trading gate or order has been changed. This document does not claim independent review, deployment, API/UI access, or a natural daily run.

## Contract and data

The original `materialize_daily_product` retains ownership. After the numeric manifest is complete, it saves the panel-reference sidecar using the owner's governed immutable save seam and attaches its descriptor to the existing dated index and completion event. A `require_cached_numeric=True` recovery path reuses the existing same-date numeric manifest and row refs; it does not execute prefill, numeric computation, charts, score/action history or the original formula. Index and event are checked for concurrent change before publication. Each item has the original key components, primary/earlier roles, original preK selected segment, original group/reason/risk, source row ref, non-PIT status and missing reasons. Event family and ending remain unbound.

The three reference fields describe the original panel's latest prior new key, not the old 12.2 tracker event. Their definitions are: exchange-session difference from the primary reference date; `(reference high - target close) / reference high * 100`; and target volume divided by reference volume. Both prices and volumes use the parent selector generation and its QFQ/volume basis. Original R3 fields remain null and the model-facing reader raises `R3_MODEL_INPUT_NOT_ADMITTED:SEMANTIC_MAPPING_NOT_CERTIFIED`. The missing R3 checkpoint/prestep, separate trigger identity and branch, both-date RAW/QFQ and volume-unit evidence are not substituted by the panel reference. Historical PIT is not certified.

The algorithm identity binds source row/config SHA, generation, date, per-exchange calendar hash, target bar, event IDs, and both source-code hashes. The immutable record is also addressed by its content hash. A changed/late input changes its cache identity; unchanged stock entries are reused. Sample runs require an isolated output root and never write the owner index/events.

## Verified isolated replay

Source: 2026-11-09, parent generation `427800f1ca9a1cc1c6cdca72dc022f12112bb7e2c4c18178f1d38107a023b24f`; parent manifest SHA `022f892701fb791569aad1ddb69ee6ffafcacf9ca17ecb113cf651832149fb6b`. The replay reads existing row refs, one target-date selector projection and an exchange/date-only selector window from 2024-04-08 to 2026-11-09; it neither recollects data nor recomputes historical formulas. The initial 2026-10-01 calendar window was insufficient for a retained 2024-04-08 key; its failure is recorded in `writer/FIRST_REPLAY_BOUNDARY.json` and the window was corrected before the final replay.

- Three representative stocks agree with their exact source rows: `300949.SZ` 20261106 K, age 1, price distance 1.228070%, volume ratio 1.197422, original groups empty and redgreen FALSE; `301132.SZ` 20261104 K, age 3, distance 9.179393%, ratio 0.710562, original groups empty and redgreen FALSE; `601825.SH` 20261027 K, age 9, distance 1.411509%, ratio 0.514865, original groups `nav_smallk|nav_pullback`, redgreen TRUE, selected original preK 20260921–20261026, n=20.
- The frozen preview 20 is completely covered: 19 have all three reference fields; `002731.SZ` is UNKNOWN because `CURRENT_SYMBOL_HISTORY_END_MISMATCH`. This is not a newly screened candidate list.
- All 5,808 saved scope references have output rows: 5,520 have all three reference fields; 238 have history-end mismatch, 38 are absent from the current snapshot, and 12 have no latest reference. R3 model admissible: 0. These are mechanical coverage counts, not individual semantic reviews of all stocks.
- Frozen model, parent product/manifest, active owner/score-action and the fixed-20 file matched the six protected SHA references. The original formula and source-config files also match their pinned SHAs; see `writer/FORMULA_GUARD.json`.

The replay receipt and its exact indexes/records are under `/Users/lexi/Desktop/学习/agents调试/Z哥方法论/p5162_event_fields_daily_20261109/run_20261109_r1/writer/REPLAY_RECEIPT.json`. For this frozen run, rerun `PYTHONPATH=. /Users/lexi/Desktop/学习/runtime/venvs/v02-parity/bin/python -B /Users/lexi/Desktop/学习/agents调试/Z哥方法论/p5162_event_fields_daily_20261109/run_20261109_r1/writer/replay.py` from the worktree.

## Scheduler runtime bridge

The current Git base `5a15f7aa8d443c0c57f8084657dbd65e9ce16ef5` contains a split scheduler, but the actual Main app runs the unsplit `executor_registry.py` from Git commit `7e99fdc78`. Its exact pre-SHA is `6f848524e991ccb3631cb56927d3beb7361f6ee8882a2eceea5b8a58903bcf4f`. The attached minimal hunk checks the new descriptor when an existing same-day numeric/chart leaf would otherwise short-circuit. A missing or mismatched descriptor, index, completion or stock record invokes the same governed owner with `require_cached_numeric=True`; an intact leaf remains idempotently reusable. Existing chart recovery and time window are unchanged. Each record's bytes are verified by its reader; this fast path checks record existence and the index SHA, not all record SHA bytes on every scheduler wake.

`scheduler_runtime_bridge.patch` SHA `9ac4054346e3eb973675782c17007d025d26ba399c7311a926d7f14b63b75227`; the patched runtime-file SHA is `e2cff40fa0daa3f2670539067fc9790ba0f6a47f3cbee3731cc97accbc6e7d3e`. The SHA-guarded `apply_scheduler_bridge.py` applies only to an isolated candidate root, rejects any pre-SHA drift and refuses the active `com.lexi.v4.local` runtime tree. This patch is an explicit bridge against that exact runtime, not a replacement of the split canonical scheduler. Candidate integration must preserve this distinction and run its own release/owner checks.

## Verification and rollback

Run the focused tests from the worktree:

```sh
PYTHONPATH=. /Users/lexi/Desktop/学习/runtime/venvs/v02-parity/bin/python -B -m pytest -q -c /dev/null -p no:cacheprovider --basetemp="<isolated-test-directory>" tests/test_p5162_event_fields.py tests/test_p5162_event_fields_scheduler_bridge.py
```

12 tests passed in the pinned Python environment. They execute the actual owner function boundary and the actual patched scheduler method body with isolated source/context fixtures; they cover numeric-cache recovery without formula/score calls, changed input, idempotency, missing stock record, per-stock isolation, dates/generations/stock/basis conflicts, model namespace rejection, governed save use and scheduler base drift. The existing codebase's global pytest config requires `starlette`, which is absent in this Python environment; `-c /dev/null` isolates the focused test config rather than changing dependencies.

Rollback the candidate by dropping only the new event-fields owner delta, domain/adapter, tests and bridge assets, and restoring the scheduler candidate from the exact pre-SHA file. Do not overwrite the running scheduler or alter shared numeric/checkpoint data. Deployment, independently reviewed acceptance and subsequent natural run are not part of this receipt.
