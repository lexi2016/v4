# V3.5 Equivalent Rebuild Corrective Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` task by task. Sol is the controller; a fresh Terra implementer is the sole writer for each task; Explorer and Reviewer remain read-only.

**Goal:** Refactor legacy V3 into a production-grade V3.5 that independently produces the same business results and preserves the same user-visible product behavior from the same raw inputs, dates, cutoffs, models, pools, and sources.

**Architecture:** Legacy V3 is the read-only business specification and output oracle, never a V3.5 runtime dependency. Every vertical slice is bound to frozen graph nodes and source SHA before implementation, then closes raw input -> producer/model -> artifact/manifest/receipt -> API -> legacy-equivalent DOM behavior.

**Tech Stack:** Python 3.14, FastAPI, Vue 3, TypeScript, pytest, Vitest, PowerShell, deterministic JSON and SHA-256 evidence.

## Global Constraints

- Old V3 remains read-only. Never write, proxy, import, or execute it from the V3.5 live runtime.
- V3 final API/page outputs are expected-answer fixtures only; `LEGACY_FINAL_API` is forbidden as LIVE producer input.
- Preserve V3 models, features, thresholds, ordering, data-source priority, task semantics, date roles, separate pool boundaries, page entries, section order, sources, and interactions.
- New engineering code is allowed only for modularization, typed contracts, atomic writes, SHA/manifest/receipt, idempotency, concurrency safety, tests, and semantic-preserving performance.
- Keep `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false` until a separate final production GO.
- Do not modify Windows Tasks before final GO. Do not add redirects, hidden latest fallback, automatic cross-date replay, dead-letter queues, V3 dual writes, or global enum middleware.
- One Terra writer per task. Sol does not edit that task's production or test files. Explorer, specialist auditors, and Reviewer are read-only.
- If the requested model route is unavailable, record `MODEL_ROUTE_UNAVAILABLE`; never substitute silently.
- Machine gates auto-continue only on strict PASS. Critical `CANNOT_CONFIRM` is FAIL, not PASS-with-warning.
- Every task freezes one hypothesis, one input set, one main variable, PASS and rejection conditions before code.

## Karpathy Execution Contract

1. One independently reviewable vertical slice per task.
2. Freeze graph hash, old source SHA, raw inputs, date, cutoff, code and config first.
3. Freeze expected V3 behavior before writing the failing V3.5 test.
4. Change one producer/consumer chain per task.
5. Record falsifiable PASS and REJECT conditions in the slice contract.
6. Port the simplest authoritative V3 path before any refactor or optimization.
7. Pass one-date/one-pool canaries before production-scale or multi-day runs.
8. Commit only passing slices; failed routes are stopped and not stacked.
9. Keep only graph, SHA, receipt, test and page evidence in the ledger.
10. Stop only for permission, credential, irreversible action, graph/semantic conflict, model-route failure, or final GO.

## Required Interfaces

- `GraphSliceContract`: slice identity, graph baseline hash, graph node ids, old source SHA, raw input SHA, business date/cutoff, V3 producer/API/DOM identities, expected behavior, allowed paths, PASS/REJECT and safety.
- `ParityReceipt`: raw input SHA, V3/V3.5 producer status, artifact/manifest/receipt SHA, API rows and semantics, DOM selectors/rows/interactions, screenshot, console errors, timing, safety and `PASS|FAIL|CANNOT_CONFIRM`.
- `DispatchRequest`: `scheduled_date`, `business_date`, `slot`, `mode=LIVE|REPLAY|BACKFILL`.
- `RunDecision`: `eligible`, `eligible_markets`, `blocked_markets`, `market_states`, `session_status` and reason.
- Preserve `/api/v1/runs/date-list`, `/api/v3/preselection-pools`, `/api/v3/workbench/stage`, `/api/v3/review`, and `/api/v3/tasks/status` semantics.
- Research keeps exact `GET /api/v3/research/articles?archive_date=YYYYMMDD` and explicit `GET /api/v3/research/articles/latest`; no implicit fallback.

---

### Task 1: Freeze and quarantine the wrong-direction batch

**Owned paths:** recovery script/tests, `.runtime/evidence/recovery/<run-id>`, one superseding corrective authority receipt. Do not modify legacy V3 or the user-owned untracked 2026-07-31 plan.

- [ ] Freeze current HEAD, branch, status, raw-byte SHA for the 21 tracked dirty files, untracked file identities, runtime manifest/date catalog, and the ten 20260731 injected runtime files.
- [ ] Write a failing dry-run recovery test covering SHA drift, unexpected dirty paths, exact-path-only restoration, manifest cleanup, latest-pointer protection, and rollback idempotency.
- [ ] Implement an explicit recovery utility that first writes the complete patch/hash/runtime inventory to `.runtime/evidence/recovery`, then restores only SHA-matched wrong-direction tracked paths to HEAD and moves only the ten injected runtime files into quarantine.
- [ ] Remove only matching injected manifest/date-catalog/latest references; never broadly delete, clean, reset, stash or checkout.
- [ ] Preserve the three frozen V3 20260731 exports as expected-answer fixtures, not runtime data.
- [ ] Emit a superseding authority receipt marking historical Phase 1-6 receipts `ENGINEERING_ONLY / NOT_BUSINESS_PARITY` without rewriting them.
- [ ] Run focused recovery tests, verify unrelated dirty state is unchanged, review, commit, and auto-continue.

**Gate:** served V3.5 runtime no longer consumes injected 20260731 final outputs; the complete pre-recovery state is recoverable; old V3 and Windows Tasks are unchanged.

### Task 2: Refresh the authoritative V3 graph and inventory v4

- [ ] Read V3 only and refresh Atlas/current task/API/page graph into V3.5 evidence.
- [ ] Reconcile the expected starting counts of 336 sources, 90 entrypoints, 69 runtime records and 11 features; explain every change before continuing.
- [ ] Freeze raw source SHA, producer/consumer identities, API routes, page DOM selectors/order/interactions and task identities.
- [ ] Generate `v35_replacement_inventory_v4` without overwriting v1-v3; reject duplicate identity, parse failure, missing source, invalid SHA or unexplained count drift.
- [ ] Obtain read-only Explorer lineage and Reviewer gate evidence.

**Gate:** reproducible graph hash, zero parse failures, zero unexplained differences and zero V3 writes.

### Task 3: Make graph-slice and parity receipts mandatory

- [ ] Add failing tests that reject missing graph ids, source SHA, raw input SHA, expected V3 behavior, DOM identity or PASS/REJECT rules.
- [ ] Reject `LEGACY_FINAL_API` as LIVE input and any critical `CANNOT_CONFIRM` as a passing slice.
- [ ] Freeze the first actual built-in-browser V3 viewport and capture V3 DOM behavior contracts; do not use pixel equality.
- [ ] Require artifact/manifest, API and visible-page lanes to pass independently.
- [ ] Mark the current custom V3.5 research/review/preselection behavior as an expected failing baseline rather than adapting the oracle to it.

**Gate:** no production implementation can be committed without a valid slice contract and strict parity receipt.

### Task 4: Revalidate the daily runtime and scheduling spine

- [ ] Reuse only graph-neutral calendar, dispatcher, ledger, atomic-write, owned-path and mode-isolation code that passes the refreshed contracts.
- [ ] Enforce market-specific full/half/closed/unknown decisions and cross-market partial eligibility.
- [ ] Enforce atomic identity `(workload_id,business_date,slot,mode)`, `CONCURRENCY_SKIPPED`, no duplicate artifacts, no automatic cross-date replay, and no REPLAY/BACKFILL live/latest updates.
- [ ] Map all 35 task specifications, 36 actual Windows Tasks, 34 timeline nodes and 69 runtime inventory records to canonical owners; incomplete producers remain blocked, not executable placeholders.
- [ ] Restore V3 date-navigation semantics from actual materialized daily indexes; never make `future_target` appear as completed data.

**Gate:** zero duplicate ownership, zero unexplained task/slot gaps, non-trading zero LIVE output and no Windows Task mutation.

### Task 5: Migrate separate preselection pools from raw producers

- [ ] Freeze V3 source paths, SHA, cutoff and expected same-input rows for A premarket, A review watchlist, Stage7/intraday, research, Baimao, WeChat and HK Connect D-1 pools.
- [ ] Write failing tests that reject read-time pool synthesis, `legacy_partial_migration`, merged boundaries and final-API imports.
- [ ] Port the authoritative raw producers and store each pool independently with its own provenance.
- [ ] Restore V3 page group order, labels, source visibility and interactions in Vue without new information architecture.
- [ ] Run 20260730 frozen parity and a 20260731 empty-data-root materialization canary.

**Gate:** empty V3.5 storage independently produces every due pool; artifact, API and page groups match V3.

### Task 6: Migrate all eight stages and the A-share 09:25 V1.1 lane

- [ ] Freeze all stage graph nodes, raw inputs, cutoffs, scoring/model SHA and DOM behavior.
- [ ] Keep A 09:25 as upstream pools -> tdxpy exact-date auction -> V1.1 price-volume adapter -> candidate -> selected; never replace tdxpy with Futu.
- [ ] Preserve the 20260730 oracle: requested 147, source 146, missing `A.300333`, candidate 50, selected 50.
- [ ] Port the other seven V3 stages without new features, thresholds or ordering.
- [ ] Keep A/HK failures local and restore the V3 stage workbench layout and interactions.

**Gate:** same frozen inputs yield field-equivalent stage artifacts/API/DOM; 20260731 is independently materialized, not imported.

### Task 7: Migrate the complete close-review and model chain

- [ ] Freeze and port the graph order for close materials, A/H structure, Bilibili discovery/download, video check, ASR, OCR alignment, stockdict, gap/guard, publish/verify and model review.
- [ ] Reject LLM-generated market regime, mainline, anchor, trigger or invalidation content as production data.
- [ ] Preserve A/H separate statuses, model identity, stock-role boundaries and exact-date semantics.
- [ ] Restore the V3 review page hierarchy, source links, model state and evidence visibility; no generic custom summary page.

**Gate:** same-day raw materials independently produce the review; missing stages remain typed NOT_MATERIALIZED and never become invented prose.

### Task 8: Migrate the complete research desk

- [ ] Freeze V3 finance, ZSXQ, morning-news, WeChat and hourly-delta producers, cutoff, dedupe key and time roles.
- [ ] Produce exact-date research archives from raw source snapshots; final V3 lane/API exports remain oracle-only.
- [ ] Keep `published_at`, `collected_at`, and `first_seen_at` offset-aware and archive-date stable in Asia/Shanghai.
- [ ] Restore the V3 priority/feed/context three-column layout, source tabs, event pinning, timeline filtering, original links and pool boundaries.
- [ ] Verify trading day, weekend, holiday, exact miss and explicit latest cases.

**Gate:** empty storage independently produces the same-source/cutoff research result and V3-equivalent page behavior.

### Task 9: Close remaining features, entrypoints and task producers

- [ ] Complete navigation, runtime status, tasks registry, research panels, Baimao refresh, WQ101 prewarm and every remaining reachable graph chain.
- [ ] Do not invent implementations for unreachable legacy loader symbols and do not delete them; record evidence-backed non-executing COMPAT disposition.
- [ ] Require real producer commands and receipts for every executable task owner; mappings alone never count as implementation.
- [ ] Promote inventory records individually only with graph, old SHA, replacement, tests, artifact, receipt, API and page evidence as applicable.

**Gate:** no PENDING and no blocking CANNOT_CONFIRM for reachable required records; no unapproved REMOVE.

### Task 10: Apply semantic-preserving production engineering

- [ ] Freeze one performance hypothesis, V3 baseline, production-size input and rejection threshold per change.
- [ ] Permit only atomic I/O, verified caching, connection reuse, pagination, idempotency and path safety changes.
- [ ] Reject any model, score, order, source-priority or pool-membership SHA change.
- [ ] Keep only before/after improvements that preserve output and meet graph-defined downstream slots.

**Gate:** every optimization has an independent receipt, unchanged business SHA and no slower successful production baseline.

### Task 11: Full acceptance and five eligible trading-day shadow run

- [ ] Run Python full suite, Vue tests, typecheck, build, architecture scan, path escape, tamper, date, concurrency and safety matrices.
- [ ] Run five eligible trading days with V3 unchanged and V3.5 shadow-only against the same captured external inputs and cutoffs.
- [ ] At every due slot compare producer, artifact/manifest, API, actual page rows/grouping/interactions, loading, overflow and console state at the same viewport.
- [ ] Reset the five-day counter after any critical unexplained variance; do not carry a failed day forward.

**Gate:** five clean eligible days, zero duplicate run, zero cross-date data, zero unexplained empty pool, zero critical business/UI variance.

### Task 12: Final GO package and guarded production cutover

- [ ] Present terminal inventory, task/feature coverage, five-day results, performance, screenshots, risks and rollback evidence.
- [ ] Keep `READY_TO_REPLACE=false` and `DEPLOYED=false` until the user explicitly says GO.
- [ ] After GO only: export old task definitions and SHA, register one disabled V3.5 dispatcher, validate it, enable V3.5, then disable matched V3 tasks.
- [ ] Roll back immediately on health, receipt, date, pool, model or page gate failure.
- [ ] Retain disabled V3 for at least ten trading days; deletion needs separate approval.

**Gate:** user-approved GO, successful guarded cutover and verified rollback point; production deployment remains distinct from trading authorization.

## Fixed Acceptance Matrix

- Calendar: 20260730 full, 20260725 weekend, 20260217 holiday, 20260701 A/HK asymmetric, 20261224 half-day sessions, 20270104 unknown.
- Data: raw-source-only LIVE, exact/latest isolation, cross-date refusal, external input read-only, symlink/junction escape, SHA/manifest/receipt tamper.
- Runtime: concurrent dispatchers, aliases, LIVE/REPLAY/BACKFILL isolation, non-trading zero LIVE artifact.
- Business: V1.1, tdxpy 09:25, separate pools, exact review-model provenance, research sources/dedupe, local A/HK failure.
- Page: same date and viewport, legacy section order/interactions, real stock rows, visible source/status, ended loading, no horizontal overflow, zero console exceptions.
- Safety: `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`; no V3 writes and no Windows Task change before final GO.
