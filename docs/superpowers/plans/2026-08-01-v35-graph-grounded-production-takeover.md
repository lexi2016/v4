# V3.5 Graph-Grounded Production Takeover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`. Codex/Sol is the sole writer; read-only agents never modify formal files.

**Goal:** Replace every legacy V3 capability covered by the frozen graph with an evidenced V3.5 disposition, complete five trading days of shadow parity, and request the user's final GO before production cutover.

**Architecture:** Legacy V3 remains read-only and supplies the static Atlas, refreshed runtime/task graph, source SHA, entrypoint, task, API, and page identities. Each V3.5 vertical slice closes page → API → domain → artifact/manifest/receipt → test evidence before its precise inventory records can advance.

**Tech Stack:** Python 3.14, FastAPI, Vue 3, TypeScript, Vitest, pytest, PowerShell, deterministic JSON/SHA-256 evidence.

## Global Constraints

- `GOAL`: graph-covered V3 capabilities receive evidence-backed V3.5 dispositions and a guarded production takeover.
- `WRITER`: `codex_sol` only.
- `ALLOWED_PATHS`: V3.5 `apps`, `contracts`, `domains`, `infrastructure`, `ops`, `tests`, and `docs/evidence`.
- `FORBIDDEN_PATHS`: legacy V3 writes, trading configuration, BUY gates, orders, and Windows Task mutation before final user GO.
- Preserve V1.1 models, score thresholds, data-source priority, date roles, and separate pool boundaries.
- Keep `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.
- No global enum middleware, alias redirects, automatic cross-date replay, dead-letter queue, V3 dual write, or hidden latest fallback.
- One falsifiable goal, one frozen input set, one main variable, and one independent acceptance gate per slice.

## Model Capability Routing

- Codex/Sol: Controller, architecture, sole implementation writer, integration, and final decision.
- Luna/Explorer: read-only legacy graph, data lineage, path, and identity evidence.
- Reviewer: read-only correctness, security, and gate review.
- Deterministic Python: SHA, counts, parity, timing, and numeric acceptance.
- Terra: disabled as a writer in this batch; it may become the sole writer only in a separately frozen implementation batch.
- Gem: hypothesis and falsification only in a future model experiment; no migration code or model changes.
- Worker `READY` is a handoff, never Controller acceptance.

---

### Task 1: Freeze the working state and build graph baseline v2

**Files:** `ops/migration/graph_baseline.py`, `contracts/migration/v3_graph_baseline_v2.json`, `contracts/migration/v35_replacement_inventory_v2.json`, `tests/test_graph_baseline_v2.py`

- [ ] Freeze HEAD, dirty paths and raw-byte SHA, tool versions, legacy V3 HEAD/status, and baseline tests.
- [ ] Collect the current V3 script/task graph with an explicit V3.5 output directory and prove no legacy tracked-state change.
- [ ] Reconcile Atlas012, current graph, and orphaned inventory v1; fail on parse errors, path escape, duplicate identity, bad SHA, or unexplained count difference.
- [ ] Generate deterministic baseline/inventory contracts and run architecture/migration tests.
- [ ] Obtain independent Explorer and Reviewer handoffs; record conflicts and `CANNOT_CONFIRM`.

**Gate:** reproducible composite hash, 0 parse errors, 0 missing current Atlas files, 0 unexplained differences; runtime findings remain visible and do not become runtime acceptance.

### Task 2: Build parity receipts and built-in-browser comparison

**Interfaces:** `ParityReceipt` contains graph hash, input/date/source SHA, artifact/manifest, API rows, page rows, screenshot, console errors, timing, safety, and verdict.

- [ ] Write failing receipt-schema, tamper, date-mismatch, and incomplete-page tests.
- [ ] Implement atomic receipt storage under V3.5 data/evidence roots.
- [ ] Lock the first observed built-in-browser viewport and compare V3:8771 with V3.5:8872 using the same date and view.
- [ ] Emit the fixed acceptance table; no pixel-diff gate.

**Gate:** artifact, API, and page lanes independently pass or visibly report `CANNOT_CONFIRM`.

### Task 3: Revalidate and seal existing Tasks 1–6

- [ ] Recheck calendar, dispatcher, task identity, pools, eight stages, and close review against exact graph nodes.
- [ ] Lock A-share 09:25 to tdxpy exact-date transactions and the V1.1 price-volume adapter.
- [ ] Preserve separate A core, Stage7/intraday, research, and HK Connect pools.
- [ ] Freeze the 20260730 147 requested / 146 source / missing `A.300333` / 50 candidate / 50 selected fixture.

**Gate:** each accepted node has its own parity receipt and only exact inventory records advance.

### Task 4: Complete exact-date research and decision desk

**APIs:** `GET /api/v3/research/articles?archive_date=YYYYMMDD` and `GET /api/v3/research/articles/latest`.

- [ ] Preserve V3 source universe, cutoff, dedupe key, publication/collection/first-seen times, and pool boundary.
- [ ] Reject naive timestamps; render offset-aware timestamps in `Asia/Shanghai` without archive-date drift.
- [ ] Return typed `NOT_MATERIALIZED` and end page loading on an exact-date miss.
- [ ] Compare research counts only with the same captured source and cutoff.

**Gate:** trading day, weekend, holiday, exact miss, and explicit latest modes pass API and browser comparison.

### Task 5: Close all eleven feature verticals

- [ ] Process `navigation.dates`, `preselection.pools`, `stage.workbench`, `stage.model_review_close`, `review.close`, `research.desk`, `runtime.status`, and `tasks.registry` in dependency order.
- [ ] Migrate the three orphan loaders only if the refreshed graph proves reachability; otherwise retain `CANNOT_CONFIRM` and propose evidence-backed removal.
- [ ] Close news, ZSXQ, Bilibili, video/ASR/OCR, stockdict, gap/guard, publish, Baimao, and WQ101 chains from their actual graph nodes.

**Gate:** every feature has a graph-supported `KEEP`, `REWRITE`, `COMPAT`, or user-approved `REMOVE` disposition.

### Task 6: Map all task and entrypoint identities

- [ ] Map 34 timeline nodes, 35 Windows Task records, and all current entrypoints to one canonical workload owner each.
- [ ] Keep aliases and historical bundles non-executable; one dispatcher produces one artifact namespace.
- [ ] Enforce market/session/date roles and LIVE/REPLAY/BACKFILL separation.
- [ ] Prove concurrency skip, no automatic cross-date replay, and zero live output on ineligible days.

**Gate:** no duplicate owner, omitted slot, unexplained entrypoint, or task mutation.

### Task 7: Apply production engineering optimizations after parity

- [ ] Freeze one performance hypothesis and metric before each change.
- [ ] Permit only semantic-preserving atomic writes, SHA/receipts, idempotency, connection reuse, pagination, and content-addressed caching.
- [ ] Reject any change to model, score, order, source priority, or pool membership.
- [ ] Keep only changes that pass production-scale parity and the graph-defined downstream deadline.

**Gate:** each retained optimization has before/after evidence and unchanged business-contract SHA.

### Task 8: Complete inventory and full acceptance

- [ ] Require graph nodes, source SHA, module, tests, artifact, receipt, API, and browser evidence for each status promotion.
- [ ] Require reachability/duplication evidence and user approval for `REMOVE`; prove the unique consumer for `COMPAT`.
- [ ] Run full Python/Vue tests, typecheck, build, zero-legacy-runtime scan, path escape, date, concurrency, and safety matrices.

**Gate:** the current v2 inventory has no `PENDING`; all residual gaps are explicit blockers, not bulk-promoted records.

### Task 9: Run five eligible trading days in shadow

- [ ] Run V3 unchanged and V3.5 shadow-only against the same captured inputs.
- [ ] Compare every due slot, artifact, pool, stage, review, research response, task state, and page.
- [ ] Use the built-in browser daily; record actual rows, pool grouping, date, loading, overflow, and console state.

**Gate:** five eligible trading days have no critical variance, duplicate execution, cross-date data, or unexplained empty pool.

### Task 10: Present GO/NO_GO and cut over only after user GO

- [ ] Deliver the complete inventory/task/feature/five-day/browser/performance/rollback table.
- [ ] Before GO, keep `INTEGRATED=false`, `DEPLOYED=false`, and `READY_TO_REPLACE=false` and make no Windows Task change.
- [ ] After GO, export legacy task definitions and SHA, register one disabled V3.5 dispatcher, validate it, then enable V3.5 and disable matched V3 tasks.
- [ ] Roll back immediately on critical health, receipt, date, pool, or page failure.
- [ ] Retain disabled V3 for at least ten trading days; deletion needs separate approval.

## Fixed Test Matrix

- Calendar: 20260730 full, 20260725 weekend, 20260217 holiday, 20260701 asymmetric, 20261224 half-day, 20270104 unknown.
- Data: exact/latest, cross-date refusal, read-only external input, symlink/junction escape, SHA/manifest/receipt mismatch.
- Runtime: concurrent dispatchers, aliases, mode isolation, and non-trading zero-live output.
- Business: V1.1, tdxpy 09:25, separate pools, research provenance, and local A/HK failures.
- Page: same date/viewport, real stock rows, visible `cannot_confirm`, completed loading, no horizontal overflow, zero console exceptions.
