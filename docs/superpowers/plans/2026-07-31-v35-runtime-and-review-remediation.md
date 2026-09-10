# V3.5 Runtime Governance and Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the recently confirmed legacy V3 runtime-governance, non-trading-day research, task-status, A-share close-review, and research-date behaviors with independently testable V3.5-native vertical slices.

**Architecture:** Keep V3.5 as a modular monolith. A single lightweight dispatcher reads one V3.5-owned workload catalog and one canonical trading calendar; business runners never decide their own scheduling eligibility. A-share review and research archives use exact-date, SHA-verified V3.5 stores, while the API exposes compatibility projections without reading or proxying legacy V3 at runtime.

**Tech Stack:** Python 3.14, FastAPI, pytest, Vue 3, TypeScript, Vitest, Vite, Windows Task Scheduler with one thin PowerShell launcher, JSON manifests/receipts with SHA-256.

## Global Constraints

- Legacy V3 at `C:\Users\huang\Desktop\学习\v3_system` remains read-only runtime authority until a later cutover approval.
- V3.5 runtime must not import, execute, proxy, or read any file under `v3_system`; offline imports accept only an explicitly supplied file and copy verified data into V3.5-owned storage.
- V3.5 remains on `http://127.0.0.1:8872/`; no changes to legacy port 8771 are authorized by this plan.
- Preserve `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false` in every response, receipt, fixture, and visible page.
- Desktop only; mobile behavior is outside this batch.
- Do not register, disable, delete, or change a Windows Task; do not restart a service. This plan may render dry-run task definitions only.
- Current dirty files belong to the user/current work. No stash, reset, checkout overwrite, or broad formatting is allowed.
- Dirty-file SHA-256 values are computed from raw bytes. Freeze only the exact pre-existing dirty paths; `.git`, `.pytest_cache`, `__pycache__`, compiled files, ignored runtime data, and other generated directories are outside the batch contract.
- Implementation writer is one Sol agent at a time. Review agents, if used, are read-only.
- Baseline frozen on 2026-07-31: `123` Python tests pass, `15` web tests pass, and `vue-tsc --noEmit` passes.
- Migration inventory remains `PENDING` until the exact replacement has machine evidence; engineering tests do not imply `DEPLOYED`, `UI_VERIFIED`, or `READY_TO_REPLACE`.

## Approved Product Decisions Encoded by This Plan

1. Hourly research is eligible only on an A-share or HK-Connect trading day; weekends and exchange holidays produce no live research manifest.
2. Windows owns one V3.5 dispatcher, not one process per business workload. Non-trading days may wake the dispatcher once, but no trade-day-only runner may start.
3. A workload has one stable `workload_id`, one active execution owner, zero or more aliases, and a separate retired-owner inventory.
4. A-share review is exact-date. It never silently falls back to another date and never lets a sparse compatibility object hide a richer canonical review.
5. Research archive views separate `page_date`, `requested_archive_date`, and `resolved_archive_date`; exact-date and latest-archive are separate endpoints.
6. The old V3 task flow and review information hierarchy are reused as behavior specifications; no new product flow is invented in this batch.

---

## Phase A — Calendar, Dispatcher, and Task Identity

### Task 1: Freeze the batch contract and protect the dirty worktree

**Files:**
- Create: `contracts/migration/runtime_review_batch_contract.json`
- Create: `tests/test_runtime_review_batch_contract.py`
- Do not modify any currently dirty production file.

**Interfaces:**
- Produces: `runtime_review_batch_contract.v1` with `bug_ids`, `frozen_dates`, `run_policy`, `allowed_paths`, `baseline_tests`, and safety flags.

- [ ] **Step 1: Write the failing contract test**

```python
def test_runtime_review_batch_contract_is_frozen() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["bug_ids"] == ["037", "045", "046", "047", "048", "049"]
    assert contract["run_policy"] == "A_OR_HK_CONNECT_TRADE_DAY"
    assert contract["frozen_dates"] == {
        "weekend": "20260725",
        "weekend_after_cadence_change": "20260726",
        "trading_day": "20260730",
    }
    assert contract["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
```

- [ ] **Step 2: Run the test and verify it fails because the contract is absent**

Run: `python -m pytest tests/test_runtime_review_batch_contract.py -q`

Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Add the frozen contract**

Record the current dirty-path list and SHA-256 for every dirty file using binary reads (`Path.read_bytes()` or an equivalent raw-byte stream). Do not recursively hash the repository or add ignored/generated paths to the contract. The contract must state that a later task may modify a dirty file only after its pre-edit SHA matches this baseline or the user explicitly accepts the newer version.

- [ ] **Step 4: Run the contract and architecture tests**

Run: `python -m pytest tests/test_runtime_review_batch_contract.py tests/test_architecture.py -q`

Expected: PASS; zero legacy runtime dependency remains.

- [ ] **Step 5: Commit only the contract and its test**

```powershell
git add -- contracts/migration/runtime_review_batch_contract.json tests/test_runtime_review_batch_contract.py
git commit -m "test: freeze runtime review remediation contract"
```

### Task 2: Introduce one canonical trading-day eligibility service

**Files:**
- Create: `contracts/market_calendar_2026.json`
- Create: `contracts/trading_calendar.py`
- Create: `domains/runtime_policy.py`
- Create: `tests/test_trading_calendar_policy.py`
- Read without modifying: `contracts/trading_calendar_2026.json` as the existing A-share holiday input; it is not sufficient by itself for runtime policy.

**Interfaces:**
- Produces: `RunPolicy`, `MarketScope`, `SessionRequirement`, `TradingDayState`, and `evaluate_run_policy(policy: RunPolicy, trade_date: str, slot: str | None, *, market_scope: MarketScope, session_requirement: SessionRequirement) -> RunDecision`.
- `contracts/market_calendar_2026.json` is a V3.5-owned, provenance-bearing contract with separate `a_share`, `hk_securities`, and `hk_connect_southbound` records. Each date resolves to `FULL_TRADING_DAY`, `HALF_TRADING_DAY_AM`, `NON_TRADING_DAY`, or `UNKNOWN`; the contract contains market sessions and the official source URL used to freeze each exception.
- `MarketScope` values: `A_SHARE`, `HK_CONNECT`, `CROSS_MARKET`.
- `SessionRequirement` values: `DAY_ELIGIBILITY_ONLY`, `SESSION_OPEN`, `POST_CLOSE`.
- `RunDecision` fields: `eligible`, `reason`, `calendar_status`, `trade_date`, `slot`, `policy`, `eligible_markets`, `blocked_markets`, `market_states`, and `session_status`.
- `eligible_markets` and `blocked_markets` are sorted tuples containing `a_share` and/or `hk_connect`; `market_states` contains both keys for `CROSS_MARKET`, so a single boolean never hides partial market availability.

- [ ] **Step 1: Write failing weekend, holiday, and trading-day tests**

```python
def test_research_is_ineligible_on_weekend() -> None:
    decision = evaluate_run_policy(
        RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
        "20260725",
        "1200",
        market_scope=MarketScope.CROSS_MARKET,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )
    assert decision.eligible is False
    assert decision.reason == "NON_TRADING_DAY"

def test_research_is_eligible_on_frozen_trading_day() -> None:
    decision = evaluate_run_policy(
        RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
        "20260730",
        "1200",
        market_scope=MarketScope.CROSS_MARKET,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )
    assert decision.eligible is True
```

Also freeze: one ordinary weekend, one A-share holiday, one HK-only holiday such as `20260701`, one 2026 HK half day such as `20261224`, one full day, and one unknown/out-of-contract date. At `20261224 1400`, a cross-market `SESSION_OPEN` decision keeps the A-share lane eligible and blocks the HK lane; a blanket “all workloads after noon are ineligible” rule is forbidden. `POST_CLOSE` is evaluated against that market's actual close and may be eligible after a half-day close. Do not infer exchange holidays from weekday alone.

- [ ] **Step 2: Run tests and verify missing implementation**

Run: `python -m pytest tests/test_trading_calendar_policy.py -q`

Expected: FAIL on missing modules.

- [ ] **Step 3: Implement strict calendar loading and pure policy evaluation**

```python
class RunPolicy(StrEnum):
    A_SHARE_TRADE_DAY = "A_SHARE_TRADE_DAY"
    HK_CONNECT_TRADE_DAY = "HK_CONNECT_TRADE_DAY"
    A_OR_HK_CONNECT_TRADE_DAY = "A_OR_HK_CONNECT_TRADE_DAY"

@dataclass(frozen=True)
class RunDecision:
    eligible: bool
    reason: str
    calendar_status: str
    trade_date: str
    slot: str | None
    policy: RunPolicy
    eligible_markets: tuple[str, ...]
    blocked_markets: tuple[str, ...]
    market_states: dict[str, str]
    session_status: str
```

Reject malformed calendar records. Unknown dates fail closed with `eligible=False`, `calendar_status=UNKNOWN`, and all requested markets in `blocked_markets`. For `CROSS_MARKET`, start only the eligible lane(s); pass the immutable market decision to the workload and never let a blocked lane perform live work.

- [ ] **Step 4: Run focused and full Python tests**

Run: `python -m pytest tests/test_trading_calendar_policy.py -q`

Run: `python -m pytest -q`

Expected: PASS; existing 123 tests remain green plus new tests.

- [ ] **Step 5: Commit the pure calendar slice**

```powershell
git add -- contracts/market_calendar_2026.json contracts/trading_calendar.py domains/runtime_policy.py tests/test_trading_calendar_policy.py
git commit -m "feat: add canonical trading day policy"
```

### Task 3: Replace per-task wakeups with a single dry-run dispatcher contract

**Files:**
- Create: `contracts/runtime_workloads.json`
- Create: `contracts/runtime_tasks.py`
- Create: `infrastructure/scheduling/__init__.py`
- Create: `infrastructure/scheduling/catalog.py`
- Create: `infrastructure/scheduling/dispatcher.py`
- Create: `infrastructure/scheduling/execution_ledger.py`
- Create: `ops/run_dispatcher.py`
- Create: `ops/launch_v35_dispatcher.ps1`
- Create: `tests/test_runtime_dispatcher.py`
- Create: `tests/test_runtime_workload_catalog.py`

**Interfaces:**
- Consumes: `evaluate_run_policy()` from Task 2.
- Produces: `DispatchMode`, `WorkloadDefinition`, `DispatchRequest`, `DispatchReceipt`, and `dispatch_due(request, catalog, executor) -> DispatchReceipt`.
- `DispatchMode` values: `LIVE`, `REPLAY`, `BACKFILL`.
- `DispatchRequest` fields: `scheduled_date`, `business_date`, `slot`, and `mode`; `BACKFILL` and `REPLAY` must be explicitly requested and can never update live/latest pointers.
- Every workload declares `workload_id`, `owner_id`, `run_policy`, `market_scope`, `session_requirement`, `slots`, `command`, `aliases`, `enabled`, `scheduled_date_role`, `signal_date_role`, `target_date_role`, and safety flags.
- The deterministic execution identity is `(workload_id, business_date, slot, mode)`. The execution ledger exposes an atomic non-blocking claim for that identity using standard-library/OS primitives; do not add `filelock` or another locking dependency.

- [ ] **Step 1: Write failing catalog uniqueness and weekend no-run tests**

```python
def test_catalog_has_one_owner_per_workload() -> None:
    catalog = load_workload_catalog()
    assert len({row.workload_id for row in catalog}) == len(catalog)
    assert len({row.owner_id for row in catalog if row.enabled}) == len([row for row in catalog if row.enabled])

def test_weekend_dispatch_starts_no_trade_day_runner(fake_executor) -> None:
    receipt = dispatch_due(
        DispatchRequest("20260725", "20260725", "1200", DispatchMode.LIVE),
        load_workload_catalog(),
        fake_executor,
    )
    assert receipt.started_workload_ids == ()
    assert fake_executor.calls == []
```

The catalog test must also reject missing keys, wrong types, duplicate aliases/owners, unsupported enum values, and unknown top-level or workload fields. Add a two-process canary for the same execution identity: exactly one process obtains the claim; the other returns `CONCURRENCY_SKIPPED`, starts zero workloads, and creates no per-workload receipt or business artifact.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest tests/test_runtime_workload_catalog.py tests/test_runtime_dispatcher.py -q`

Expected: FAIL on missing modules.

- [ ] **Step 3: Implement one dispatcher and one aggregate skip receipt**

The dispatcher evaluates the calendar once and claims the deterministic execution identity before workload selection or any business write. On a non-trading day it may write one `v3_5.dispatch.v1` aggregate receipt, but it must not create per-workload run directories or terminal receipts. A duplicate claimant prints `CONCURRENCY_SKIPPED`, exits successfully with zero workload side effects, and relies on the winning claim/receipt as the audit record. Alias rows are catalog metadata only and never enter the execution list.

`LIVE` requires `scheduled_date == business_date`. `REPLAY` and `BACKFILL` may use a different business date only when explicitly requested; they write isolated namespaces, never update live/latest pointers, and never become an automatic retry path. Resolve `signal_date_role` and `target_date_role` deterministically from the catalog and record the resolved dates in the aggregate receipt.

- [ ] **Step 4: Add a thin launcher without registering it**

`ops/launch_v35_dispatcher.ps1` may only locate the pinned Python executable and call `python -m ops.run_dispatcher`. It must contain no business rules, calendar rules, or task list.

- [ ] **Step 5: Run canaries at frozen dates**

Run: `python -m ops.run_dispatcher --mode live --scheduled-date 20260725 --business-date 20260725 --slot 1200 --dry-run`

Expected: one aggregate `NON_TRADING_DAY` result, zero workload commands.

Run: `python -m ops.run_dispatcher --mode live --scheduled-date 20260730 --business-date 20260730 --slot 1200 --dry-run`

Expected: only catalog workloads due at 12:00 are selected; no command is executed in dry-run.

Run the same frozen request in two concurrent processes. Expected: one selector receipt and one `CONCURRENCY_SKIPPED` result; zero duplicate workload commands or per-workload receipts. Also run an explicit `--mode backfill --scheduled-date 20260731 --business-date 20260730 --dry-run` canary and verify it selects only the isolated BACKFILL namespace and cannot update live/latest pointers.

- [ ] **Step 6: Run tests and commit**

```powershell
python -m pytest tests/test_runtime_workload_catalog.py tests/test_runtime_dispatcher.py tests/test_architecture.py -q
git add -- contracts/runtime_workloads.json contracts/runtime_tasks.py infrastructure/scheduling ops/run_dispatcher.py ops/launch_v35_dispatcher.ps1 tests/test_runtime_dispatcher.py tests/test_runtime_workload_catalog.py
git commit -m "feat: add single-owner runtime dispatcher"
```

### Task 4: Expose truthful task identity and status without mixing row types

**Files:**
- Create: `domains/task_status.py`
- Create: `apps/api/v35_api/runtime_router.py`
- Modify: `apps/api/v35_api/app.py`
- Create: `apps/web/src/contracts/runtime.ts`
- Create: `apps/web/src/api/runtime.ts`
- Create: `apps/web/src/views/TaskStatusView.vue`
- Create: `apps/web/src/views/TaskStatusView.spec.ts`
- Modify: `apps/web/src/App.vue`
- Modify: `apps/web/src/App.spec.ts`
- Modify: `apps/web/src/style.css`
- Create: `tests/test_task_status_api.py`

**Interfaces:**
- Consumes: workload catalog and execution ledger from Task 3.
- Produces: `GET /api/v3/tasks/status?date=YYYYMMDD`.
- Response fields: `logical_workload_count`, `active_owner_count`, `alias_count`, `retired_owner_count`, `groups.logical`, `groups.active_owners`, `groups.aliases`, `groups.retired`, `cannot_confirm`, and safety flags.

- [ ] **Step 1: Write the API contract test**

```python
def test_task_status_separates_identity_groups(client) -> None:
    body = client.get("/api/v3/tasks/status?date=20260730").json()
    assert set(body["groups"]) == {"logical", "active_owners", "aliases", "retired"}
    assert body["logical_workload_count"] == len(body["groups"]["logical"])
    assert body["active_owner_count"] == len(body["groups"]["active_owners"])
    assert body["production_allowed"] is False
```

- [ ] **Step 2: Write the Vue behavior test**

Render a fixture containing one active owner, one alias, one retired owner, one failed workload, one calendar skip, and `cannot_confirm: ["EXECUTION_RECEIPT_MISSING"]`. Assert that the UI never labels the alias as a second execution, that failure appears before success, and that the evidence gap produces a visible degraded warning rather than appearing only in collapsed diagnostics.

- [ ] **Step 3: Implement the API and desktop view**

The first screen shows four counts, failure/late status, last run, next due time, duration, result code, freshness, receipt link, and any `cannot_confirm` evidence gap. Paths and raw catalog fields stay in a collapsed diagnostic section; `cannot_confirm` must not be hidden there.

- [ ] **Step 4: Run focused tests, typecheck, and full regression**

```powershell
python -m pytest tests/test_task_status_api.py -q
cd apps/web
npm test -- src/views/TaskStatusView.spec.ts src/App.spec.ts
npm run typecheck
cd ../..
python -m pytest -q
```

Expected: all commands PASS.

- [ ] **Step 5: Commit and stop for Phase A approval**

Commit only Task 4-owned paths. Do not register the dispatcher task. Present the API fixture, weekend dry-run receipt, and built page at 8872. Stop until the user approves Phase A.

---

## Phase B — Canonical A-Share Close Review

### Task 5: Build an exact-date V3.5-owned A-share review domain and store

**Files:**
- Create: `contracts/a_share_review.py`
- Create: `domains/a_share_review.py`
- Create: `domains/review_envelope.py`
- Create: `infrastructure/owned_path.py`
- Create: `infrastructure/a_share_review_store.py`
- Create: `ops/import_a_share_review_reference.py`
- Create: `tests/test_a_share_review.py`
- Create: `tests/test_a_share_review_store.py`
- Modify: `domains/close_review.py` only to delegate envelope composition; do not rewrite HK calculations.

**Interfaces:**
- Produces: `A_SHARE_REVIEW_SCHEMA = "v3_5.a_share_review.v1"` and `build_a_share_review(trade_date: str, *, big_picture: list[dict[str, Any]], mainlines: list[dict[str, Any]], core_stocks: list[dict[str, Any]], observation_pool: list[dict[str, Any]], trigger_rows: list[dict[str, Any]], quality_gate_rows: list[dict[str, Any]], source_sha256: str) -> dict[str, Any]`.
- Produces: `resolve_owned_path(root: Path, relative: str) -> Path`. It rejects absolute/parent-traversal destinations and any resolved destination outside the canonical V3.5 `.runtime/data` root, including escape through an existing symlink or Windows junction/reparse-point ancestor. External `--input` files remain explicitly allowed as read-only sources and are never subjected to the destination-root rule.
- Canonical fields: `trade_date`, `headline`, `market_regime`, `risk_tone`, `big_picture`, `mainlines`, `core_stocks`, `observation_pool`, `next_day_trigger_tree`, `quality_gate`, `cannot_confirm`, `source_sha256`, and safety flags.
- `review_envelope()` exposes one canonical A review plus the existing HK review; compatibility key `fupan_review_v3` is a projection of the canonical A object, not a second store.

- [ ] **Step 1: Freeze the Bug047 regression fixture**

Create a test fixture where `market_reviews.A` is sparse while canonical A review contains 9 big-picture rows, 4 trigger rows, 12 observation rows, 7 quality-gap rows, and no formal core stock.

- [ ] **Step 2: Write failing domain and store tests**

Assert exact date, SHA validation, idempotent import, rejection of cross-date rows, visible separation between `core_stocks=[]` and `observation_pool`, and fail-closed destination checks for absolute paths, `..`, symlink escape, and Windows junction/reparse-point escape. The failure must occur before any destination directory, payload, manifest, or receipt is written.

- [ ] **Step 3: Implement the domain and V3.5-owned store**

Offline import accepts `--input <explicit-file>` as a read-only source and writes only through `resolve_owned_path()` under `.runtime/data/a_share_reviews/`. Runtime readers receive only the V3.5 store root and cannot resolve legacy paths. Do not require the explicit source file to live under `.runtime/data`, and do not interpret `source_sha256` or other payload text as a filesystem path.

- [ ] **Step 4: Run focused tests and zero-legacy scan**

```powershell
python -m pytest tests/test_a_share_review.py tests/test_a_share_review_store.py tests/test_architecture.py -q
```

Expected: PASS; injected legacy-path tests still fail closed.

- [ ] **Step 5: Commit the domain/store slice**

Commit only the files listed in Task 5.

### Task 6: Render the old V3 review task flow from the canonical A-share contract

**Files:**
- Create: `apps/api/v35_api/review_router.py`
- Modify: `apps/api/v35_api/app.py`
- Create: `apps/web/src/contracts/review.ts`
- Create: `apps/web/src/api/review.ts`
- Create: `apps/web/src/views/ReviewView.vue`
- Create: `apps/web/src/components/review/AshareReviewPanel.vue`
- Create: `apps/web/src/components/review/HkCloseReviewPanel.vue`
- Create: `apps/web/src/components/review/ReviewEvidencePanel.vue`
- Create: `apps/web/src/views/ReviewView.spec.ts`
- Modify: `apps/web/src/App.vue`
- Modify: `apps/web/src/App.spec.ts`
- Modify: `apps/web/src/style.css`
- Create: `tests/test_review_api_contract.py`

**Interfaces:**
- `GET /api/v3/review?date=YYYYMMDD` returns exact-date A/H review; `requested_date == resolved_date` or the response is locally `NOT_MATERIALIZED`.
- `loadReview(date: string, signal?: AbortSignal) -> Promise<ReviewEnvelope>` performs one exact-date request and never loops through previous dates.

- [ ] **Step 1: Write the API regression test**

Assert that a rich canonical A review wins over sparse compatibility metadata and that HK unavailability does not alter the A status.

- [ ] **Step 2: Write the visible-page regression test**

The Bug047 fixture must visibly render: market/risk summary, 4 trigger/invalidation rows, 12 observation rows labeled `观察池/非正式核心票`, and `正式核心票待补`. It must not render `核心观察 -` as the end state.

- [ ] **Step 3: Implement the existing V3 hierarchy, not a redesign**

Order the desktop view as: `主线/风险 → 股票角色或观察池 → 次日触发/失效条件 → 自动复盘/证据缺口`. Keep HK review in its own panel. Put paths, hashes, training diagnostics, and acceptance details under a collapsed evidence panel.

- [ ] **Step 4: Remove silent cross-date fallback**

Replace the loop currently in `App.vue::loadCloseReview()` with the exact-date client. A missing selected date displays `该交易日复盘尚未生成`; it never substitutes an earlier review.

- [ ] **Step 5: Run component, API, type, and full tests**

```powershell
python -m pytest tests/test_review_api_contract.py tests/test_a_share_review.py -q
cd apps/web
npm test -- src/views/ReviewView.spec.ts src/App.spec.ts
npm run typecheck
npm run build
cd ../..
python -m pytest -q
```

- [ ] **Step 6: Run the built-in-browser acceptance and stop for Phase B approval**

At 8872, inspect 20260730 at the same desktop viewport used for legacy evidence. Verify visible counts and text, no endless loading, no horizontal page overflow, and zero page-console exceptions. Save screenshots and a machine-readable receipt. Stop until the user approves Phase B.

---

## Phase C — Research Date Binding

### Task 7: Separate exact-date research archives from latest research

**Files:**
- Create: `contracts/research_archive.py`
- Create: `domains/research_archive.py`
- Create: `infrastructure/research_store.py`
- Create: `ops/import_research_archive.py`
- Create: `apps/api/v35_api/research_router.py`
- Modify: `apps/api/v35_api/app.py`
- Create: `apps/web/src/contracts/research.ts`
- Create: `apps/web/src/api/research.ts`
- Create: `apps/web/src/views/ResearchView.vue`
- Create: `apps/web/src/views/ResearchView.spec.ts`
- Modify: `apps/web/src/App.vue`
- Modify: `apps/web/src/App.spec.ts`
- Modify: `apps/web/src/style.css`
- Create: `tests/test_research_archive.py`
- Create: `tests/test_research_api_contract.py`

**Interfaces:**
- `GET /api/v3/research/articles?archive_date=YYYYMMDD` uses `EXACT_DATE_NO_FALLBACK`.
- `GET /api/v3/research/articles/latest` is the only latest-archive route.
- Both responses contain `page_date`, `requested_archive_date`, `resolved_archive_date`, `date_policy`, `fallback_reason`, `published_at`, `collected_at`, `first_seen_at`, and safety flags.
- `published_at`, `collected_at`, and `first_seen_at` are offset-aware ISO 8601 values. Import rejects naive timestamps; the API preserves the instant and the Vue client renders them in `Asia/Shanghai` without changing the associated archive date.
- `NOT_MATERIALIZED` remains a typed response and is not forced to HTTP 404. The client must terminate loading and render the missing-date placeholder for that status.

- [ ] **Step 1: Write Bug048 exact/latest separation tests**

For a request of 20260730 with only a 20260731 archive present, exact-date must return `NOT_MATERIALIZED` with no 20260731 rows; latest must return 20260731 and declare `LATEST_ARCHIVE`. Exercise both real FastAPI routes with `TestClient` and assert `/latest` resolves to the latest handler. Do not add a dynamic `/{article_id}` or `/{archive_date}` route; if a future task adds one, its static-path ordering requires a new regression test in that task.

- [ ] **Step 2: Implement SHA-verified archive import and strict reads**

Each material is keyed by `source_id + canonical_url + published_at`; collection times never replace publication time. All three timestamps must contain a UTC offset and round-trip without losing the instant. The store uses Task 5's `resolve_owned_path()` and rejects destination escape, cross-date manifest mismatch, and receipt mismatch while continuing to allow an explicitly supplied external source file as read-only input.

- [ ] **Step 3: Bind the hourly-research workload to Task 2 policy**

Add `hourly_research` to `runtime_workloads.json` with `A_OR_HK_CONNECT_TRADE_DAY`. The dispatcher tests must prove zero live manifest on 20260725/26 and normal due-slot selection on 20260730.

- [ ] **Step 4: Implement the desktop research view**

The default is exact selected-date material. A separate labeled control loads latest archive. Every card shows published, collected, and first-seen times rendered with `timeZone: "Asia/Shanghai"`; boundary fixtures around UTC midnight must retain the intended archive date and show no silent day shift. The hourly timeline filters the visible material list rather than acting as a decorative status row.

- [ ] **Step 5: Run focused and full tests**

```powershell
python -m pytest tests/test_research_archive.py tests/test_research_api_contract.py tests/test_runtime_dispatcher.py -q
cd apps/web
npm test -- src/views/ResearchView.spec.ts src/App.spec.ts
npm run typecheck
cd ../..
python -m pytest -q
```

- [ ] **Step 6: Multi-day browser acceptance and stop for Phase C approval**

Verify one trading day, one weekend, one holiday, an exact-date miss, and latest-archive mode in the built-in browser. Stop before any scheduler registration or service cutover.

---

## Phase D — Replacement Evidence and Release Gate

### Task 8: Record only proven replacements and generate the batch acceptance receipt

**Files:**
- Create: `ops/migration/record_replacement.py`
- Create: `tests/test_record_replacement.py`
- Modify: `contracts/migration/v35_replacement_inventory.json`
- Create: `docs/evidence/runtime-review-batch-20260731.json`
- Create: `tests/test_runtime_review_acceptance.py`

**Interfaces:**
- `record_replacement(inventory, record_selector, evidence) -> inventory` moves only selected records from `PENDING` to `IN_PROGRESS` or `COMPLETE`.
- `COMPLETE` requires replacement module, tests, artifact/receipt paths, SHA-256, and zero-legacy scan result.

- [ ] **Step 1: Write tests that reject unsupported status promotion**

```python
def test_complete_requires_machine_evidence() -> None:
    with pytest.raises(InventoryValidationError):
        record_replacement(inventory, selector, {"status": "COMPLETE", "replacement_evidence": []})
```

- [ ] **Step 2: Implement deterministic inventory updates**

Select records by exact old source/entrypoint/task identity. Do not bulk-promote all 335 sources, 89 entrypoints, 69 runtime tasks, or 11 features.

- [ ] **Step 3: Generate the batch receipt**

The receipt records baseline and final test counts, full/half/asymmetric/unknown calendar fixtures, concurrent-dispatch claim results, LIVE/REPLAY/BACKFILL namespace evidence, dispatcher process/receipt counts, owned-path escape checks, API contracts, timezone-aware research fixtures, browser screenshots, source hashes, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`, and explicit `DEPLOYED=false` unless a later approved deployment occurs. Do not introduce or retroactively freeze a code-coverage threshold in this batch.

- [ ] **Step 4: Run full acceptance**

```powershell
python -m pytest -q
cd apps/web
npm test
npm run typecheck
npm run build
cd ../..
python -m pytest tests/test_process_smoke.py tests/test_architecture.py tests/test_migration_inventory.py tests/test_runtime_review_acceptance.py -q
```

Expected: PASS with zero legacy runtime dependencies.

- [ ] **Step 5: Report evidence levels and stop**

Report `IMPLEMENTED`, `TESTED`, and browser `UI_VERIFIED` separately. Keep `INTEGRATED`, `DEPLOYED`, and `READY_TO_REPLACE` false until their later gates are actually met. Do not register the single dispatcher or disable legacy tasks under this plan.

---

## Phase Acceptance Gates

| Phase | PASS signal | Automatic rejection |
| --- | --- | --- |
| A | Full day, weekend, official holiday, HK half day, A/HK asymmetric day, and unknown date matrix passes; cross-market work starts only eligible lanes; two concurrent dispatchers produce one claim and one `CONCURRENCY_SKIPPED`; task UI separates logical/active/alias/retired and visibly exposes `cannot_confirm` | Any blocked market lane starts; half-day handling globally disables valid A-share or post-close work; duplicate claim creates a workload artifact/receipt; alias produces a second artifact; 55 mixed rows remain |
| B | Exact-date A review visibly shows canonical big picture, observation rows, and trigger tree; HK failure stays local; destination path escape fails before writes | Cross-date fallback, sparse `market_reviews.A` hides canonical review, endless loading, page-only HTTP check, or any resolved destination outside V3.5 `.runtime/data` |
| C | Exact and latest research routes never masquerade as each other; non-trading research creates zero live manifests; BACKFILL/REPLAY cannot update live/latest; timezone-aware fields retain their instant and intended archive date | Historical page shows latest archive without explicit latest mode; weekend produces READY research; naive timestamp is accepted; replay/backfill updates live/latest; UI changes the archive date through timezone conversion |
| D | Selected inventory records have hashes and machine evidence; full tests, build, zero-legacy scan, and in-app-browser receipt pass | Bulk status promotion, legacy runtime read/proxy, task registration, service cutover, BUY/order boundary change |

## Explicitly Rejected Additions

- No global Enum/`StrEnum` response middleware. API contract tests assert literal string values at the boundary.
- No alias-specific execution endpoint and no HTTP 301/308 compatibility redirect without a proven consumer contract.
- No forced HTTP 404 for `NOT_MATERIALIZED`; typed business status plus a completed loading state is the frozen behavior.
- No Playwright pixel-diff matrix, new CI service, or code-coverage threshold in this batch.
- No automatic retry loop, exponential backoff, dead-letter queue, or automatic historical backfill in the dispatcher.
- No blanket “all work after noon is ineligible” rule on half days; eligibility is market- and session-specific.
- No reverse sync, dual write, runtime proxy, or runtime read of legacy V3, and no opportunistic HK close-review refactor.
- No mandatory third-party file-lock or JSON-schema package; use existing language/runtime primitives and typed loaders.

## Explicitly Deferred

- Registering the one Windows dispatcher task.
- Disabling or deleting any legacy Windows Task.
- Restarting 8872/8771 as a production service.
- Completing all 335/89/69 replacement records.
- Five-trading-day parallel run, old-code isolation, cutover, observation period, and deletion approval.
- Mobile UI.

Those require separate approval after this remediation batch passes all four phase gates.
