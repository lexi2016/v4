# Independent frontend review — frontend_01

> **Archival scope clarification, added during final handoff review:** This report approves the immutable `frontend_01` snapshot and the 20-case green evidence recorded at that review time. The mutable `work/reports/frontend.green.json` was subsequently replaced by the final 22-case run, so its current contents must not be used as though they were the original 20-case evidence. The snapshot hashes and review-time observations below remain historical evidence. The final one-line 64-character diagnostic cap and final candidate are separately reviewed in `integration_03`; final runtime evidence is `frontend.final.json` and the portable 22-case reports. This report does not extend its approval silently to a later postimage.

## Verdict

- **Spec: PASS** for the offline repair candidate in Task 2.
- **Code quality: APPROVE.** No blocking correctness or scope finding was identified in the reviewed snapshot.
- **Delivery/acceptance status: PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN.** This review does not establish deployed behavior, Mac owner execution, browser bundle identity, browser paint/layout, or natural-session acceptance.

## Scope and exact identity

Reviewed the immutable files in `work/reviews/frontend_01/{before,after}`, its `review.diff`, and `hashes.json`; did not substitute mutable candidate production files for the frontend review. The unchanged API validator and actual Vue callsite were inspected from `work/baseline/apps/web/src/api/managerWorkspace.ts` and `work/baseline/apps/web/src/views/ManagerSelectionView.vue`.

All five snapshot files match the recorded preimage/postimage SHA-256 values. All five postimage SHA-256 values also match the `source_modules` hashes in `work/reports/frontend.green.json`, so the recorded green runtime evidence applies to the exact reviewed frontend files.

| File under `apps/web/src/manager-selection/` | Reviewed postimage SHA-256 |
| --- | --- |
| `businessStatus.ts` | `615171ac463c14d64c78f5c3f2526f100186a57c6ed85dc6017b5d02234be005` |
| `catalystObservationPanel.ts` | `ba13f895bf8b315c9649e73b4a4a6e843cf5d1475b25587745d72a76e7ef7173` |
| `dailyChannels.ts` | `44b2fa24a470e4dec6c4318a49c9d028e481a67e93d3f996775cd933bd1a040e` |
| `researchAttention.ts` | `40c168a7f69a0bf5c655b550e865e6b54b0348d1c4c1bba9718696cc663fe9b0` |
| `catalystObservationPanel.repair.spec.ts` | `a0d5fbe18da903c59625fb6d2a7b1f123eab6ef2799c5eca401b9c564b345e4c` |

The backend candidate's `workspace_identity.py` and diagnostic assembly in `workspace.py` were read only to cross-check the proposed additive diagnostics shape; this is not an independent backend approval.

## Spec findings

### 1. Actual mounted renderer and same response/date binding — PASS

`catalystObservationPanel.ts:5,142-143,479-486` imports, initializes, and calls the existing `renderDailyChannels` inside the real panel entry point. The call receives `value.daily_channels` and the explicitly validated `value.date_bindings` from the same workspace response. It does not create another producer or fetch a separate daily result.

The unchanged API path validates workspace dates and the daily projection, including workspace run references, before admission (`managerWorkspace.ts:1635-1641,1643-1672`). Both canonical GET and refresh pass the same explicit `dailyRequestBindings` (`catalystObservationPanel.ts:91-100,655-663`); a successful POST response is reused once rather than followed by an unnecessary GET. The real Vue view still mounts this panel (`ManagerSelectionView.vue:2750-2757,2778`). This closes the reported wiring omission at the actual entry point.

### 2. Visible states, gaps, provenance and independent stale channels — PASS

The daily section is placed immediately after the plan-consumption status and outside a collapsed region (`catalystObservationPanel.ts:178-181`). `dailyChannels.ts:190-218,230-236` displays all three channels, explicit status codes including `CANNOT_CONFIRM`, response dates, candidate/pending/watch counts, data date, run ID, owner, product SHA, input identity, generation time, and a bounded first-three gap summary. Full channel objects remain in expandable source diagnostics. Existing candidate rows and scoped empty states remain intact.

`catalystObservationPanel.ts:501` makes `STALE_INPUTS_CHANGED` and `consumed=false` visible before the daily results. Rendering the summary is not gated on plan consumption. Independent valid channel results remain available when the plan is stale; non-announcement plan references still pass the unchanged API validator and cannot impersonate a consumed stale plan. No stale-to-current promotion or guard bypass was added.

### 3. Compact, bounded stale identity diagnostics — PASS

`businessStatus.ts:48-66` admits only the expected diagnostic schema, `CHANGED`/`RECORDED_COMPONENTS_CHANGED`, a differing saved identity, and a current identity bound to the validated workspace. It requires a bounded positive integer count, up to 16 unique component rows, consistent truncation, valid component names, and differing valid/null component SHA values. It shows at most four component names and points to the existing source audit; `catalystObservationPanel.ts:557-560` retains the entire `plan_product`, including diagnostics, in that audit.

The consumed flag and plan status are never changed by this presentation. Missing, unsupported, malformed, duplicate, or unbound component evidence falls back to an explicit `CANNOT_CONFIRM` explanation. The schema/reason/count/row/truncation fields match the proposed backend diagnostics. The explanatory text preserves the distinction between this read's recorded differences and the unconfirmed historical live mismatch root cause.

### 4. Adjacent US scopes and dynamic reviewed population — PASS

`businessStatus.ts:150,159-164,183-184` labels the original upper scope as `美股评估/完整度` and adds an immediately adjacent `每日 US-HK 已审映射（N 项）` row. The reviewed count derives from `daily_run.coverage.reviewed_us_symbol_count`; an absent/unknown count remains unknown rather than becoming four or zero. Dates and matched relation count are included, with explicit limits on full-market/completeness inference.

`researchAttention.ts:210-228` uses that same dynamic reviewed scope for the detailed mapping title and `VALID_EMPTY` explanation. The hard-coded four/33 language is removed from the display, while the actual four-reviewed fixture still shows four. The original global assessment remains unassessed when that is what its input says. Daily empty results are not promoted into complete US coverage or a full-market empty result.

### 5. Core order and complete raw observations — PASS

`catalystObservationPanel.ts:161-163,178-181,514-516,562-567` places the original filters, stocks and background containers into an initially collapsed raw audit region after core daily/research results. Reading a new response resets this region to collapsed and updates its count. `renderStocks` at `266-290` retains the existing complete front/background partition and source filters; no slicing of the raw stock set or producer/consumer alteration was added. Stock expansion still retains the entire raw row via `stock` at `236-264`.

The mounted regression verifies all 100 raw observations, the hundredth stock's exact payload marker after expansion, original input immutability, and the existing research/safety text. Safety flags and original Stage/rank/BUY behavior remain outside this repair boundary.

### 6. Independent historical catalog date and late responses — PASS by implementation review

`catalystObservationPanel.ts:91,101-102,583-590` separates the historical selector into `analysis_date`, including an explicit empty value for automatic mode. It never rewrites the workspace `announcement_date`. Captured explicit daily bindings remain stable across reads and refreshes; reload rehydrates them independently of the catalog selector. The two mounted regressions cover selected and automatic catalog modes across read, refresh and remount.

The existing workspace sequence/date/view/disposed checks at `640-678` guard against older in-flight requests repainting a newer selection; disposal increments the sequence and aborts controllers (`701`). Historical analysis requests have their own sequence and target-date checks (`592-604`). The added rendering occurs inside those existing guarded success paths. A delayed-response runtime case is not present in this suite; race protection was checked statically and this is a remaining test-coverage limitation, not an identified regression.

### 7. Optional and invalid data — PASS

Absent `daily_channels` produces three explicit unavailable cards and clears previous data rather than reusing an earlier run (`dailyChannels.ts:198-215`; `catalystObservationPanel.ts:567`). Missing response bindings show unverified dates. Date/source/safety contract errors from the unchanged validator clear old results through the existing `WORKSPACE_` failure handling (`catalystObservationPanel.ts:637,665-670`). The mounted cases cover projection omission, legacy missing dates, mismatched channel dates, mismatched refresh binding, and unsafe daily flags. Optional US mapping omission preserves an unknown count and an unavailable explanation; malformed mapping objects are rejected by the unchanged API validator before this renderer.

## Runtime evidence and limits

- Latest recorded green evidence: `work/reports/frontend.green.json`, **20 passed / 0 failed**, no setup error, with exact snapshot hashes matched as above.
- Recorded command: `/opt/codex/runtimes/codex-primary-runtime/dependencies/node/bin/node /workspace/scratch/5105f9851ff9/work/tools/run_ui_harness.mjs --source-root candidate --report reports/frontend.green.json` (run from `work`).
- Original red evidence: **1 passed / 13 failed**. Follow-up red evidence: **14 passed / 6 failed**. These are different suite stages; they should not be described as an identical unchanged suite across all stages.
- `npm test` is **NOT_RUN** as a full repository gate: ENOENT for `work/candidate/apps/web/package.json`, recorded in `frontend.full_suite.json`. That is not a successful build or full-suite run.
- The inspected harness uses the official LinkeDOM worker with explicit reflected select/details shims and synthetic fetches. It executes the actual panel/API/renderers, but has no browser layout, paint, screenshot, native details click synthesis, real navigation, or live service.
- The independent review did not rerun the same suite without an uncovered defect. It checked the recorded evidence and SHA applicability instead.

No live network/service/owner/deployment action or production code edit was performed in this review. Full real-browser build/UI acceptance and Mac owner API acceptance remain outside this evidence and must retain **PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN**.

## Blocking findings

None. The remaining limitations are the unavailable full application/build environment and unexecuted browser/live-owner acceptance, plus static rather than mounted delayed-response verification. They do not establish live success and do not require widening this minimal repair candidate.
