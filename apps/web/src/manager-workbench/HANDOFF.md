# C / manager-workbench frontend candidate handoff

Contract: MWB_V1_20261013, schema_version=v4.manager_workbench.v1.
Issue: https://github.com/lexi2016/v4/issues/41
Requirements base: 5017c9125bd970e0bcd5d7bb6efcdae63c58742f.
B public contract baseline: **761df4b6e7d712a28794c440c9e77fa3cdb8d3cb**. B HTTP candidate examined: **5010f866a993bf8a764c283696b6e2ee9a8ca18b** (api.py); Mac HTTP integration/deployment remains NOT_RUN.
Only synthetic fixtures are included here. The fixture data cannot establish real-source coverage or deployed UI acceptance.

## Scope and architecture

- Vue 3 page at existing /manager-selection/; candidate mount replaces only that page's entry import.
- api.ts is the only HTTP client; GET endpoints never trigger generation; POST is restricted to /runs and /runs/{id}/retry.
- route.ts interprets legacy plan_date as target date, validates YYYYMMDD and phase, and writes canonical date/phase/run_id.
- useWorkbench.ts owns abort/request sequence, isolated day/phase/run identity, same-query stale badges, per-panel reads, POST task polling.
- Workbench.vue renders five panels, counts independent from pagination, original lane decisions and evidence with no front-end strategy calculation.
- All decision/scope/ratio/Top20 calculations belong to A/B. HTTP consumer shapes are pinned to B api.py: GET DayData.snapshot/versions; GET HistoryData.versions; StockDetails.plan_run_id/stock/lane_details; ReviewSummary top20_rows/strict_coverage.ratio. Mac still must confirm actual deployed HTTP serialization before cutover. The C names for StockDecision.membership_status, ReviewSummary.top20_rows/selected_denominator/lane_incremental_coverage/uncovered_reasons, EvidenceRef.source_session/source_url, and RESEARCH_ONLY are aligned to the B contracts.py baseline.

## Verification (candidate, not production)

When the canonical Mac full web project is present, run from apps/web:
- npm test -- src/manager-workbench/__tests__
- npm run typecheck
- npm run build

Do not install, vendor, or modify dependencies in this C branch. The requirements-only GitHub baseline does not contain apps/web/package.json, vite.config.ts or the original full source tree, so full-project test/typecheck/build cannot run from this branch alone. All unexecuted commands are NOT_RUN, not PASS. Mac owns actual API/UI test and refresh.
Test fixtures cover day/null/unknown/empty/partial, page 251+ rows, late-date response, stale refresh, detail, task+retry 409, historical legacy, Top20/zero denominator, and security flags.

## Cutover and rollback

Keep the old page and modules unchanged. Mac may first mount the candidate in its complete local app after B's fixed contract sample is pinned and real API integration passes; restore old main.ts import to revert the candidate. Do not claim this commit is a deployable full V4 application. Never merge into main automatically.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false are the intended research safety contract, not an observed live claim.

Status: IMPLEMENTED_REPAIR_CANDIDATE; B_CONTRACT_TYPES_PINNED=761df4b6; B_HTTP_CANDIDATE_PINNED=5010f866; REAL_API/UI=NOT_RUN; MAC_NATURAL=NOT_RUN; INDEPENDENT_REVIEW_OF_REPAIR=NOT_RUN.


## 2026-10-13 Mac reviewer repair / Issue #41

Ownership: C branch only; do not modify the Mac integration branch, B/A, old manager, BUY, or deployment. This section supersedes the initial B HTTP-binding-pending caveat only for the B candidate wire shapes; it is not evidence of deployment.

Sources pinned read-only:
- C baseline e1ca8d1866851531c13746f58c92872db118e613.
- B HTTP candidate 5010f866a993bf8a764c283696b6e2ee9a8ca18b: v4/manager_workbench/api.py and service.py.
- A candidate 290592aa0c0934a69811eff9fb65284e39618a0e: engines/core.py and engines/review.py.
- B public Python contracts 761df4b6e7d712a28794c440c9e77fa3cdb8d3cb.

Verified source-shape corrections (runtime acceptance still required):
1. GET history uses data.versions (not entries), with date from data.date when absent on each item, NEW version state/SHAs, LEGACY original identity/gaps.
2. GET stock uses plan_run_id and lane_details[].rows/evidence_refs, not a top-level evidence_refs. Link opening is restricted to HTTP(S).
3. A lane_decisions[lane] is an array of separate business outputs. C shows every entry in original order; no browser selection, ranking or promotion. Stage/CLOSE remain observations.
4. A ReviewSummary coverage uses covered/denominator/ratio, not rate. C renders B/A ratio without recomputing, with 0/null/zero-denominator/missing complete Top20 distinguished. Top20 stock_decision is displayed.
5. FastAPI HTTPException error body detail is preserved for 404/409/422/503 (including NOT_RETRYABLE); Pydantic 422 validation list is rendered as bounded labels, not raw request traces. POST retry returns JobCreated and a separate GET reads JobRecord.
6. Navigation invalidates pending create/retry ticket, resets operationLoading, ignores old POST results on new date/phase/run_id. POST is never aborted: canceling a browser read cannot cancel a healthy backend task.

New C regression: apps/web/src/manager-workbench/__tests__/b_http_regression.spec.ts; old tests and synthetic fixture updated to B consumer keys. The B-shape regression literals are based on B router and A outputs, NOT captured live FastAPI TestClient output. They do not count as actual integration tests.

Mac execution commands (cd apps/web):
- npm test -- src/manager-workbench/__tests__
- npm run typecheck
- npm run build

Truthful status at this handoff: Vitest / vue-tsc / Vite build = NOT_RUN in the isolated GitHub requirement snapshot (full frontend package, toolchain and dependencies absent). Mac real B TestClient -> C, full counts pagination, refresh, 09:25/16:30 = NOT_RUN. Independent review of new repair commit = NOT_RUN. No deployment, no main merge.


## C-only Mac real-browser announcement detail repair (2026-10-13)

Scope: UI projection and synthetic B/A-shaped regression only. It does not change the A prompt/model, B HTTP contract/store, stock classification, source evidence, staged admission rules, or any Mac integration file. Stage/CLOSE stay observation-only. User/Mac reports that existing endpoints, 251-row pagination and unchanged full counts, filtered empty set, date/history reads passed; **real announcement detail failed** and the official service remains on the old path.

Grounded data shape: A engines/announcement.py at 1c596d794b3af54d8a5a3bb61028cf1b7c36e4e2 produces row.reason machine identifier ANNOUNCEMENT_* and a separate row.semantic object. The latter has original `reason`, `risk_notes` (array), and five lists of `{claim,quote,locator}`: `facts`, `changes`, `impact`, `confirmation_conditions`, `counter_evidence`. A core.py appends the whole row to `StockDecision.lane_decisions[lane]`; it aggregates row.risks but not semantic.risk_notes. B api.py at 2d0682a631b4c038457716afece37425d3d6a14f returns the same StockDecision plus lane_details[].rows and lane-specific evidence refs. Thus C must read `semantic` directly without reclassifying research or reconstructing evidence.

Changes in C-only UI:
- Null/empty name: accessible detail button and header use symbol only when name is absent; never emit literal `null` or `undefined`.
- Readable reason: the saved semantic.reason wins over technical row.reason in the summary; technical status is available in folded audit. No automatic translation of codes into fabricated research text; missing human reason explicitly says missing.
- Risk: display both persisted semantic.risk_notes even if stock.risks is empty, with originating research category. Stored stock.risks remain visible without duplicating identical text.
- Evidence: list exactly saved claims, source quotes and locators in the five groups; the original source URL is only linked if B evidence refs provide HTTP(S) URL. The browser does not infer truth, causal impact, admission, new score, liquidity or price thresholds.
- Raw machine fields and raw B rows are hidden behind per-research collapsed audit, with a nested independent raw-row disclosure. Main headings and task wording use business terms; safety/scheme diagnostic flags remain in footer audit.

Regression source: `apps/web/src/manager-workbench/__tests__/announcement_semantics.spec.ts` (synthetic text, **actual A/B structural nesting**), plus adjusted existing `b_http_regression.spec.ts` and `Workbench.spec.ts`. Include null-name a11y, nested semantic reason over machine tag, five quote/locator groups, both risk notes, folded raw rows, no decision promotion, and five-view navigation. No real announcement contents or Mac browser recordings committed.

Mac verification in the complete canonical web workspace (from `apps/web`):
- `npm test -- src/manager-workbench/__tests__/announcement_semantics.spec.ts`
- `npm test -- src/manager-workbench/__tests__` (includes prior 251+ server pagination/full counts and date/version/late-response tests)
- `npm run typecheck`
- `npm run build`
- Browser: inspect a real saved ANNOUNCEMENT stock with name=null and semantic.risk_notes length 2; verify quote/locator/original URL, raw fields folded, no accidental classification change; refresh same date+run and navigate. Do not replace deployed manager routing until Mac review passes.

Delivery proof: GitHub HEAD/compare/blob readback is separate from any executable verification. This isolated GitHub branch still lacks the full apps/web dependency manifest/build harness. Until executed in Mac project, Vitest/vue-tsc/Vite **NOT_RUN**, real C browser **NOT_VERIFIED**, actual cutover **NOT_RUN**. The Mac user's prior independent successful test count is not attributed to this new revision.
