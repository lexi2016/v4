# Frontend fixed-snapshot repair report

## Status and boundary

**PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN.** The isolated candidate passes the focused mounted-panel DOM integration suite. These checks run the real `mountCatalystObservations`, the unchanged workspace request/response validator, the existing renderers and the stock adapter with synthetic fetch responses. They do not run a deployed browser, owner service, live API, or natural market session.

This frontend task changed four existing manager-selection source files and added one focused spec. The original supplied snapshot remains the preimage. `apps/web/src/api/managerWorkspace.ts` and the original `catalystObservationPanel.runtime.spec.ts` are byte-for-byte unchanged. No source collection, owner capture/import, scheduler, plan producer, financial gate, deployment or Mac state action was performed by this task.

## Root causes and changes

### Missing daily renderer wiring

The fixed panel imported and called the attention renderer but had no `renderDailyChannels` import or call. Its response type and API validator already accepted `daily_channels` together with `date_bindings`. The candidate adds a dedicated section to the existing panel and calls the existing renderer inside the actual `render(value)` path with **that same response's** channel projection and date bindings.

The renderer remains independent of `plan_product.status`. The panel's leading status now shows the saved-plan status and `consumed` explicitly. A stale saved plan can therefore coexist with independently admitted channel information without relabelling the saved plan CURRENT.

The daily cards now visibly include the source status code, candidate/watch/pending counts, data date, run ID, owner, product SHA, input identity and up to three reported gap reasons with the total gap count. All channel fields and complete gap arrays remain in the existing lazy diagnostic details. This bounds the first view without reducing the underlying input or audit data. Missing date bindings display unknown dates; omitted or rejected projections display three unavailable cards. Date/source/safety failures retain the original `WORKSPACE_` fail-closed path and clear the old result.

### Explicit date binding and independent historical catalog selection

The panel now forwards only explicit workspace source/publication request bindings to the existing GET and refresh functions. The API contract is unchanged. Before rendering either response, the panel checks the response's binding against the current plan date and those explicit request bindings. This also protects successful refresh responses, whose existing parser does not itself forward expected request bindings into validation.

Independent review identified an actual follow-up URL consistency defect: the historical announcement selector previously changed `announcement_date`, while the new workspace request binding retained its mount-time value. A reread and a reload could consequently request different publication dates. A mounted regression reproduced the reload rejection before the repair.

The resolution uses separate frontend URL state for the historical catalog. The existing selector writes `analysis_date` and leaves the workspace binding intact. An explicitly empty `analysis_date` preserves automatic catalog-date mode across reloads. Initial mounting still falls back to legacy `announcement_date` when `analysis_date` is absent. Changing the historical selector does not generate a plan, change workspace GET/refresh inputs, or replace the plan date. No owner/API entry point was added.

| URL field | Preserved or explicit purpose |
|---|---|
| `date` | Existing Stage/source display day; not proof of a daily announcement publication day |
| `plan_date` | Existing workspace plan target day |
| `selection_date` | Optional explicit workspace source/selection binding |
| `announcement_date` / `publication_date` | Optional explicit workspace publication binding, with `announcement_date` taking precedence; legacy initial catalog fallback remains |
| `analysis_date` | Independent historical catalog selection; an empty value means automatic mode |

### US assessment versus daily reviewed scope

The old upper label `美股` described assessment/completeness, while the lower daily `VALID_EMPTY` result described a reviewed subset. The lower explanatory prose also hard coded four reviewed relations and 33 configured symbols.

The candidate labels the upper row `美股评估/完整度` and places a separate `每日 US-HK 已审映射（4 项）` status immediately beside it. Both the adjacent status and the existing detailed mapping section derive the reviewed count from `daily_run.coverage.reviewed_us_symbol_count`; unknown remains unknown. The detailed completed-result explanation uses the response's configured count as well. The text states that a scoped `VALID_EMPTY` does not establish full-market coverage or complete US input. Tests exercise four, seven and unknown reviewed counts.

### Core results before complete expandable raw rows

The actual DOM append order now places header controls and plan status first, then the daily summary, business/US scope status and core research results. Historical announcement analysis and raw observations come later. Its existing catalog date control remains mounted and usable.

The existing source filters, stock container and background container are moved intact into an initially closed `<details data-raw-observations>` region after the core results. `renderStocks` and the stock adapter retain their previous classifications, stock collection and lazy per-row source details. The mounted 100-row test checks that every row is retained and that the hundredth row expands to its exact raw source marker. It also verifies that rendering does not mutate the input object or safety flags. Native nested background and per-stock details remain available.

### Bounded, sourced stale diagnostics

`businessStatus.ts` reads the new backend `plan_product.input_identity_diagnostics` field only for a stale saved plan. A known summary requires the expected schema, `CHANGED / RECORDED_COMPONENTS_CHANGED`, a saved identity distinct from the current response identity, correctly bounded unique component records and valid nullable SHA values. Evidence must bind to the current workspace `input_identity`.

The status displays the total changed count and at most four component names; the existing plan/source audit preserves the supplied detailed comparison and SHA values. The display admits at most 16 supplied rows and 64 total changed components. Each backend saved/current map allows at most 32 components, so two valid disjoint maps can have a union of 64. The visible summary still includes at most four names. Missing or unbound evidence produces `CANNOT_CONFIRM`; it does not identify a historical changed field. The copy describes the current comparison only and does not claim the unique cause of the earlier live mismatch.

## Executed tests and evidence

All commands below were run from `/workspace/scratch/5105f9851ff9/work`, except the documented `npm test` attempt.

| Stage | Command | Actual result | Evidence |
|---|---|---|---|
| Initial RED, before production edits | `node tools/run_ui_harness.mjs --source-root input/package/code/current_fused_app --report reports/frontend.red.json` | Exit 1; 1 PASS / 13 FAIL; no setup error | `frontend.red.json`, `frontend.red.log` |
| Follow-up RED, before independent catalog date and diagnostic changes | `node tools/run_ui_harness.mjs --source-root candidate --report reports/frontend.followup.red.json` | Exit 1; 14 PASS / 6 FAIL; no setup error | `frontend.followup.red.json`, `frontend.followup.red.log` |
| Independent-review boundary RED, before widening the valid union total | `node tools/run_ui_harness.mjs --source-root candidate --report reports/frontend.boundary.red.json` | Exit 1; 21 PASS / 1 FAIL; no setup error | `frontend.boundary.red.json`, `frontend.boundary.red.log` |
| Candidate GREEN, final focused suite | `node tools/run_ui_harness.mjs --source-root candidate --report reports/frontend.green.json` | Exit 0; 22 PASS / 0 FAIL; no setup error | `frontend.green.json`, `frontend.green.log` |
| Normal project suite attempt | `npm test`, cwd `candidate/apps/web` | Exit 254; suite NOT_RUN because `package.json` is absent (ENOENT) | `frontend.full_suite.json`, `frontend.full_suite.log` |

The initial RED failures were actual mounted behavior failures after the fixture reached the expected READY state, not import errors or invalid fixture failures. The follow-up RED reproduced catalog-date reload behavior and the missing known/unknown component display. The existing unsafe-response rejection already passed on the original source and remains passing.

The 22 final cases cover actual mounting and response validation, three mixed channel statuses, visible gap/identity data, explicit GET and refresh binding, refresh response reuse, stale-plan independence, missing/legacy/mismatched projection behavior, independent catalog selection including automatic mode across reload, scoped US counts, bounded known/unknown identity differences, complete raw-row expansion, immutable inputs and preserved safety rejection.

Independent integration review identified the valid 64-component union boundary. The mounted 64-total/16-row case failed before the one-line admission limit change. It passes after that change; a 65-total malformed diagnostic remains `CANNOT_CONFIRM`. The current-input binding, schema/status checks, per-row validation, unique-component guard, 16-row admission bound and four-name visible limit remain intact.

The normal Vitest project suite and full frontend build are **NOT_RUN**. The supplied package omits the package manifest and normal dependencies; the retained original runtime spec also references an unavailable absolute Mac owner fixture. No claim is made that those original cases ran.

The isolated harness uses Node's experimental TypeScript stripping and official LinkeDOM v0.18.12. It supplies documented reflected `select.value` and `details.open` properties absent from that DOM implementation. Tests explicitly dispatch `toggle` for lazy details. There is no real layout, paint, native browser details-click synthesis or live navigation. Node emitted its experimental TypeScript warning; the attempted npm invocation also reported the existing environment's unknown `http-proxy` configuration warning. These are recorded limitations, not application test failures.

The missing imported `workspaceDecision` and `managerAnnouncementAnalysis` modules are supplied under the integration-owned `test_support/upstream` tree, with hashes and recovery provenance in `reports/test_support_sources.json` and the harness reports. They were not silently inserted into this frontend runtime patch.

## Exact source SHA-256

The machine-readable table is `frontend.source_hashes.json`.

| File | Before SHA-256 | After SHA-256 |
|---|---|---|
| `apps/web/src/manager-selection/catalystObservationPanel.ts` | `6650b7948cdfd7fc7eee81dbe9e47d7b86e9aa64ac476e27a72f726c35749355` | `ba13f895bf8b315c9649e73b4a4a6e843cf5d1475b25587745d72a76e7ef7173` |
| `apps/web/src/manager-selection/dailyChannels.ts` | `c60254b69de369c8b50ef0ffa14dd49c802a3ae56ac4266dd9fe5f39ea40fecc` | `44b2fa24a470e4dec6c4318a49c9d028e481a67e93d3f996775cd933bd1a040e` |
| `apps/web/src/manager-selection/businessStatus.ts` | `36228506f199f26dc59c7919634e4c347171d156ec89b3d6b2359c764ed45d90` | `25504185cef4cb8fdae83ec3043b371631fe9448d752e24105a1fe9438f47aba` |
| `apps/web/src/manager-selection/researchAttention.ts` | `3ec804fcb248eb50793eff6f237c7e211d75c2e60e138400d4a55f74a57be698` | `40c168a7f69a0bf5c655b550e865e6b54b0348d1c4c1bba9718696cc663fe9b0` |
| `apps/web/src/manager-selection/catalystObservationPanel.repair.spec.ts` | `NEW_TEST` | `bb36821bd7ff8a718dda93300c67e434ee29825f804d10691f91e37b07d4feee` |

## Remaining acceptance boundary

This work establishes a source repair candidate and offline mounted DOM behavior. It does not establish the browser-loaded bundle SHA, deployed layout or paint, live owner/API readback, natural-session behavior, the unique changed field behind the historical live mismatch, or full-market US coverage. Those remain `CANNOT_CONFIRM` / `LIVE_API_UI_NOT_RUN` under the supplied task boundary. Existing research-only and fail-closed source contracts remain the authority.
