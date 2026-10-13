# C / manager-workbench frontend candidate handoff

Contract: MWB_V1_20261013, schema_version=v4.manager_workbench.v1.
Issue: https://github.com/lexi2016/v4/issues/41
Requirements base: 5017c9125bd970e0bcd5d7bb6efcdae63c58742f.
B public contract baseline commit: **761df4b6e7d712a28794c440c9e77fa3cdb8d3cb** (contracts.py plus normative raw PlanSnapshot/Job/Legacy samples, observed 2026-10-13); B HTTP response implementation and its fixed integration commit remain PENDING.
Only synthetic fixtures are included here. The fixture data cannot establish real-source coverage or deployed UI acceptance.

## Scope and architecture

- Vue 3 page at existing /manager-selection/; candidate mount replaces only that page's entry import.
- api.ts is the only HTTP client; GET endpoints never trigger generation; POST is restricted to /runs and /runs/{id}/retry.
- route.ts interprets legacy plan_date as target date, validates YYYYMMDD and phase, and writes canonical date/phase/run_id.
- useWorkbench.ts owns abort/request sequence, isolated day/phase/run identity, same-query stale badges, per-panel reads, POST task polling.
- Workbench.vue renders five panels, counts independent from pagination, original lane decisions and evidence with no front-end strategy calculation.
- All decision/scope/rate/top20 calculations belong to A/B. The TypeScript read shapes in types.ts are consumer candidates until B publishes normative samples. In particular, B must confirm GET DayData.snapshot/versions, GET HistoryData.entries, ReviewSummary response mapping and StockDetails.stock shape before Mac integration. The C names for StockDecision.membership_status, ReviewSummary.top20_rows/selected_denominator/lane_incremental_coverage/uncovered_reasons, EvidenceRef.source_session/source_url, and RESEARCH_ONLY are aligned to the B contracts.py baseline.

## Verification (candidate, not production)

When the canonical Mac full web project is present, run from apps/web:
- npm test -- src/manager-workbench/__tests__
- npm run typecheck
- npm run build

Do not install, vendor, or modify dependencies in this C branch. The requirements-only GitHub baseline does not contain apps/web/package.json, vite.config.ts or the original full source tree, so full-project test/typecheck/build cannot run from this branch alone. All unexecuted commands are NOT_RUN, not PASS. Mac owns actual API/UI test and refresh.
Test fixtures cover day/null/unknown/empty/partial, page 251+ rows, late-date response, stale refresh, detail, task+retry 409, historical legacy, Top20/zero denominator, and security flags.

## Cutover and rollback

Keep the old page and modules unchanged. Mac may first mount the candidate in its complete local app after B's fixed contract sample is pinned and real API integration passes; restore old main.ts import to revert the candidate. Do not claim this commit is a deployable full V4 application. Never merge into main automatically.

research_only=true; production_allowed=false; buy_gate_updated=false; orders_sent=false are the intended research safety contract, not an observed live claim.

Status: IMPLEMENTED_CANDIDATE; B_CONTRACT_TYPES_PINNED=761df4b6; B_HTTP_BINDING=PENDING; REAL_API/UI=NOT_RUN; MAC_NATURAL=NOT_RUN; INDEPENDENT_REVIEWER=NOT_RUN.
