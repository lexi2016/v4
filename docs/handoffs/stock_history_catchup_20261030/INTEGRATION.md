# D29 candidate247 historical catch-up

This batch consumes the existing shared research-panel generation and retained
51-value/22-drawing formula projections. It invokes the actual Main owner's
`compute_stock(..., reuse_history_prefix=True)` and the unchanged R5 predicate.
It replaces the formula call with the exact retained result. No provider,
adjustment query, rendering, selector update, service or scheduler action occurs.

The output is isolated under the contract's `output_root`. A successful offline
result is not a published daily product, API verification, UI verification, or
historical PIT certification. RESEARCH_ONLY; production/trading flags remain false.

## Running and recovery

Use the absolute `PANEL_PYTHON` frozen by the controller. Run the adapter with
`--prepare` to bind inputs, then register the resulting immutable CONTRACT_*.json SHA before
`--run-started ROOT_RECEIPT.json --phase canary`. The receipt has
`status=ROOT_RUN_STARTED_REGISTERED`, `contract` (immutable path/SHA),
`contract_sha256`, and `event_sha256`.
After the same-contract 001328.SZ canary succeeds, use `--phase batch` with the
same receipt. The batch includes the completed canary and accepted 002003.SZ
without evaluating them again. It does not extend the 247-stock universe.

Each stock has a fixed `journals/<symbol>/BINDING.json` and chained, fsynced
`dates.jsonl` blocks of at most 25 completed dates or five seconds. The journal
stores only group states; source identity, qualifications and original inputs
are bound once. A crash-torn last block is discarded; any complete-block hash
or binding mismatch fails closed. Existing dates and terminal stock results
are reused. A consumer-compatible full cache is expanded and saved at the end,
not at each checkpoint. Source drift is an explicit gap, not silent cache reset.

No changes to price/rule/qualification semantics are made for speed. Canonical
prefix hashes are computed once with the original hash algorithm, census AST
compilation is cached by source SHA/date, the same-source calendar is prepared
once, and raw dated-G4 maps are initialized before workers fork. Original
`normalize` (row-local) and `fund_keys` (only current/past bars, trailing MA20/40
and prior PLRY) run once, with exact input-prefix checks before slicing their
original outputs. All 65 synthetic prefixes, including MA window boundaries,
zero volume, negative prices and UNKNOWN, match the original helpers. The real
001328 canary compares the complete old/new predicate at its first, 41st and
sixth-from-last dates. The original rule evaluates each missing cutoff; no
cutoff's qualification, census, G4, risk or outcome is taken from the final day.
Peak RSS and elapsed time are emitted
per stock. The frozen plan is 14 workers, 28 queued tasks, a 64 GiB job budget,
and 24 GiB system reserve; the controller monitors actual pressure.

## Output contract

- `RESULT.json`: exact candidate247 coverage, completed/failed/remaining lists,
  row and complete-event-case refs, protected numeric/chart SHA readback.
- `rows/<symbol>.json`: original row, with only `statistics` and
  `historical_coverage` changed. Display names remain owned by the existing
  name projection.
- `daily_products/a_share/history/<ruleSHA>/<symbol>/checkpoint.json`: original
  owner cache schema, same generation/config/qualification and exact price
  prefix. The accepted 002003 cache remains an external unchanged ref.
- `event_cases/<symbol>.json`: all accepted event dates, both D2/D5 outcomes,
  overall aggregates and own-prefix 250-valid-positive-close fixed 20pp buckets.
  Each event uses only its cutoff's price history. Flat outcomes remain valid;
  missing/nonpositive prices and immature targets remain explicitly classified;
  no valid observations means null. 002003's accepted event cases are reused.

## Integration boundary: statistics update must preserve original charts

The installed C9 reader is a profile separate from the canonical worktree file.
Its `read_original_chart` bridge accepts `chart_origin_manifest` but currently
requires exactly one changed row (`len(changed) != 1` at installed source line
963). The canonical worktree reader does not contain that deployed bridge.
Do not copy either complete file across profiles or point a live index at the
offline rows without adapting this contract.

For the authorized integration stage, the original product owner should:

1. Read the frozen original product and accepted catch-up result. Mechanically
   require the identical 247 candidate set, generation/input/formula/rule/calendar
   bindings, complete date coverage, zero remaining errors, and strict equality
   of each old/new row outside `statistics,historical_coverage`. Preserve every
   non-target ref and all original summary memberships/counts.
2. Save immutable updated rows and a new complete product/manifest. Save history
   caches first. Preserve the original chart manifest, receipt, HTML, PNG and
   projection SHA. Retain the original numerical/chart origin manifest.
3. Bind `history_updated_symbols` to the exact original-to-new ref difference
   (including the already-updated 002003 relative to the chart origin); reject
   duplicates and symbols outside the frozen candidates. Bind the catch-up
   contract/result refs. Publish only through the existing owner/index/completion
   path with its lock/CAS rules, after independent acceptance and authorization.
4. Incrementally adapt the deployed bridge's single-row restriction to this
   exact bound difference. Keep source/product/market/date and non-statistical
   equality checks. Perform all-row parity once when preparing publication;
   per-chart GET should hash/read only the requested changed row plus already
   bound manifest metadata, avoiding a 247-row full-cache scan on every click.
5. Rebind each event-case shard to the new numeric manifest and accepted row's
   statistics SHA using the existing C9 event-case index. Keep company material
   data independent. Verify the installed API and representative real UI only
   in that separately authorized stage; leave natural-run status unclaimed.

This document is an integration plan. No bridge, live product, event index,
release, Main, Stage, pins, pointers, API or UI was changed by this batch.

## Persistent matured-event reuse: source ready, offline only

Pipeline: existing shared panel + retained formula projections → frozen R2
one-time missing-label catch-up/journals → `EventCaseCache` SQLite event outcomes
and causal prefix percentiles → per-group D2/D5/current-percentile aggregates →
existing read-only event-case API/UI after separate owner integration.
No formula or historical-label producer was added. The running R2 source remains
SHA256 `6626459582e06398d9819b652b2fc54ae69648d4cde9fbe8c598550b56e52212`.

`domains/research_event_case_cache.py` stores every outcome by symbol, market,
source authority, basis, rule SHA, formula SHA and statistics source SHA. The
return dependency is only its event-to-target calendar slice, maturity and exact
entry/target prices (including missing-bar versus missing-price). Own-event
percentiles bind only the last250 valid positive own-prefix prices and current
event price. Appending calendar dates or changing generation/contract/asof alone
cannot invalidate a mature unchanged outcome; affected prices/calendar slices,
new events and newly matured events use the original `_evaluate_event_return`.
The original `stratify_event_cases_by_prefix_percentile` owns percentile math.
Earlier-asof reads never retrieve later matured returns. Bin-edge changes only
aggregate cached outcomes/ranks. Cache versions coexist, so an earlier-asof
read does not erase the mature version. Missing/invalid/flat states are retained.

The executable offline consumer is `ops/reuse_stock_event_cases.py`. It verifies
registered contract/code and completed R2 shard refs, seeds accepted outcomes,
compares every consumed group/horizon/case/conditional to the accepted source,
and reads the persistent store again with zero return/percentile calculations.
The retained002003 calendar is a different ref with the same exact SZ dates;
the consumer verifies the bound original bytes and calendar-value equality.

Run from this task worktree, with the controller's absolute `PANEL_PYTHON`:

```sh
B='/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/stock_history_catchup_20261030'
"$PANEL_PYTHON" ops/reuse_stock_event_cases.py --batch "$B" --store "$B/event_outcomes.sqlite3" --output "$B/cached_event_cases"
```

This consumes available completed stocks and lists every pending symbol. After
R2 exits, the existing owner/heartbeat can invoke the same command with
`--require-complete`. That option first requires R2 `RESULT.json` to identify the
exact247, matching contract, zero failures/remaining and unchanged protected refs,
then hashes every completed result and consumes/validates all shards. A failed
batch is not promoted. Re-running this consumer does not rerun historical rules.
Output: `cached_event_cases/RECEIPT.json` plus per-stock shards; SQLite identity and
checksum are recorded in the receipt. A receipt's store SHA is a point-in-time
snapshot and changes as additional outcomes are added.

Existing owner's precise incremental hook: after authoritative panel completion,
accepted event membership and same-source market calendar are available, call
`EventCaseCache.build(identity=..., event_dates=..., close_rows=...,
calendar=..., asof=...)` once per stock/group, with the same durable database.
Supply `source_authority` as the stable reader identity and `basis` as semantic
convention (exclude generation/asof; revised QFQ prices are detected by consumed
values). Do not pass `accepted_seed` on changed inputs; it is reserved for the
adapter's hash-verified frozen R2 import. Persist the returned cases/aggregates
through the existing owner/manifest/index/completion path. Read-only page GETs
consume those artifacts; no page-triggered fit, label evaluation or calculation.
This hook is executable source handoff; no scheduler/owner/API/UI installation
was performed.

Observed validation:14 helper tests passed; current-asof real accepted shards
matched exactly with zero newly evaluated returns;001328 at earlier2026-10-28
selectively evaluated one changed-maturity outcome, reused121 returns, and its
immediate repeated read evaluated zero. This is descriptive NONPIT reuse, not a
model claim. Full247 completion and live consumer integration remain open.

A separately authorized narrow UI source fix also preserves the sidebar's
eligible group when opening a stock; `all`/unavailable groups fall back to the
stock's first own group. Success-card titles show the chosen group. Two tests
execute the actual binding and async consumer source, covering001328 pullback,
fallback and stale replies. No framework/filtering behavior was changed.
