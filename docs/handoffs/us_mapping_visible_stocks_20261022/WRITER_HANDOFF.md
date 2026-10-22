# Writer handoff — visible saved single-day stocks

Status: IMPLEMENTED; Writer checks complete. Independent Reviewer acceptance, deployment and live candidate UI verification remain NOT_RUN.

## Frozen scope

- Goal: display the saved run's five BENEFIT research stocks directly, retain full diagnostic sources collapsed, and offer an explicit same-target-date saved-version entrance when the selected run has no single-day mapping.
- Writer: `/root/visible_stocks_writer`; independent Reviewer: assigned by controller.
- Allowed source changes: `apps/web/src/manager-workbench/Workbench.vue`, `useWorkbench.ts`, necessary manager-workbench tests. Evidence: this handoff directory.
- Forbidden: backend decisions/gates/data/business state, Vibe 8910, service operations, deployment, commits and pushes.
- Pass scope: actual saved BENEFIT code/name/research nature visible outside collapsed details; zero/risk/unknown remain separate; all 410 diagnostic candidates retained; source run/phase/cutoff explicit; selected run unchanged until explicit navigation; date/phase changes discard stale results.
- Stop: a change to research semantics or a producer is required, or inputs cannot support the display. Neither occurred.

## Source and changes

Source root: `/Users/lexi/.codex/worktrees/workbench-date-top20/v4_app`; branch `codex/us-mapping-visible-stocks-20261022`; baseline HEAD `4e00084d8ef9c606bfff2892dcab35515423c776`.

Changed source files only:

1. `apps/web/src/manager-workbench/Workbench.vue`: move original saved BENEFIT/RISK categories before diagnostics; label them research observations with current run, phase, cutoff and formal-selected count; fold the complete diagnostic table; render explicit same-date version navigation.
2. `apps/web/src/manager-workbench/useWorkbench.ts`: read-only same-date discovery, prioritizing existing NEXT_DAY versions and stopping on first validated match; retain only navigation metadata, not another run's rows; abort/sequence guards prevent stale entries after navigation.
3. `apps/web/src/manager-workbench/__tests__/visible_stocks.spec.ts`: six targeted cases, including five actual classified fixture rows versus 410 unrelated diagnostic fixtures, zero/risk separation, default and explicit run locks, explicit navigation and phase reset, invalid response identity, and late date-navigation responses.

The pre-existing accepted runtime calendar behavior was preserved from the actual release's Workbench/useWorkbench, rather than reverting to this branch's older saved-date dropdown. This is a reused baseline, not a new date feature. The patch does not change saved classifications, ranking, gates or formal eligibility.

Before/after source SHA-256, runtime-baseline SHA and candidate asset SHA are in `source_manifest.json`. Runtime-relative diffs are in `local_only/*.runtime-delta.patch`.

## Dated original saved result

Read-only GET of `days/20261022/recommendations/US_MAPPING?phase=NEXT_DAY&run_id=173530a9ac4b4105b41094337907b801&limit=1` confirmed:

- NEXT_DAY / SCHEDULED; cutoff `2026-10-22T04:17:10.466630+08:00`; US and HK price sessions `20261021`; target `20261022`.
- 698 single-day rows: BENEFIT 5, RISK 0, OBSERVATION 303, UNMAPPED 378, UNASSESSED 12; diagnostic candidates 410; formal selected 0.
- The five original BENEFIT rows are HK.00992 Lenovo Group Limited, HK.01211 BYD Company Limited, HK.01810 Xiaomi Corporation, HK.02015 Li Auto Inc., HK.09868 XPeng Inc.
- Names and classes are displayed verbatim; target-date eligibility remains CANNOT_CONFIRM.

Compact readback and response SHA: `local_only/saved-run-readback.json`. No POST or rerun was made.

## Verification

Commands below run from `apps/web` unless stated otherwise, using the existing Node v24.19.0 / npm 11.17.0 dependencies. A local untracked `apps/web/node_modules` symlink reuses the canonical project's existing dependencies; no packages were installed.

```sh
npm test -- --run src/manager-workbench/__tests__/visible_stocks.spec.ts --reporter=json --outputFile=/tmp/visible-stocks-tests-final.json
npm run APP_TYPECHECK
npm run build -- --outDir ../../docs/handoffs/us_mapping_visible_stocks_20261022/local_only/candidate-dist
npm test -- --config /Users/lexi/.codex/worktrees/workbench-date-top20/v4_app/docs/handoffs/us_mapping_visible_stocks_20261022/local_only/baseline.config.ts src/manager-workbench/__tests__/us_factor.spec.ts --reporter=json --outputFile=/tmp/visible-stocks-baseline.json
npm run build -- --config /Users/lexi/.codex/worktrees/workbench-date-top20/v4_app/docs/handoffs/us_mapping_visible_stocks_20261022/local_only/runtime-compatible.config.ts
npm test -- --config /Users/lexi/.codex/worktrees/workbench-date-top20/v4_app/docs/handoffs/us_mapping_visible_stocks_20261022/local_only/runtime-compatible.config.ts src/manager-workbench/__tests__/visible_stocks.spec.ts --reporter=json --outputFile=/tmp/visible-stocks-runtime-tests.json
```

- New targeted suite: 6/6 pass, including with frozen runtime dependencies.
- APP_TYPECHECK: exit 0.
- Standard build: exit 0; **not a deployment candidate** because unrelated branch dependencies are older than runtime.
- Runtime-compatible manager-entry-only build: exit 0, 19 modules.
- `git diff --check` from the worktree root: exit 0.
- Additional existing suites originally run together: `us_mapping_stock_lists.spec.ts` 6/6 pass; `us_factor.spec.ts` 2/5 pass. The three failing assertions expect saved source-count text that is already gated out by the original runtime Workbench. The exact untouched-runtime Workbench comparison reproduced the same 2/5 pass and identical three assertions. The single-day mapping case passed. These were not repaired outside the frozen goal.
- Initial new-fixture issues (missing unrelated required summary fields, a seconds-sensitive formatted cutoff expectation, and input-versus-change test events) were corrected. Earlier setup commands used the wrong relative working directory and failed without changing source. Final six cases have no unhandled errors.

Logs and JSON test reports are retained in `local_only/`. Existing dropdown-specific calendar tests are stale against the already accepted runtime calendar; they were not included or rewritten in this scope.

## Build and integration boundary

Actual static serving directory was verified from the runtime API mount: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-semantic-recovery-20261021-r4/app/apps/web/dist`. The existing entry references `managerSelection-B98kzZVK.js` and `managerSelection-DyRS0oUB.css`.

This branch's AnnouncementCandidates.vue/api.ts/types.ts/workbench.css differ from runtime. Deploying the ordinary branch bundle would regress unrelated announcement UI. The reviewable build therefore uses a local Vite load overlay with frozen byte-identical runtime copies of those four dependencies. Their original paths and SHA are recorded in `local_only/runtime-dependencies.json`; no original dependency file or live release file was modified.

Candidate build: `local_only/runtime-compatible-dist/` contains only:

- `manager-selection/index.html`
- `assets/managerSelection-BgE49dzD.js`
- `assets/managerSelection-DyRS0oUB.css` (same hash/name as runtime)

For a separately authorized integration, use only these assets and this entry; preserve existing assets and all other entry points. Do not copy ordinary `candidate-dist`, root index, main, daily-research-command, or old announcement files. Recheck dependency SHA if runtime changes before deployment.

NOT_RUN: independent Reviewer verdict; candidate browser/UI rendering; integration; deploy; natural execution; commit/push/remote readback. Source is ready for independent review, not final acceptance. The branch alone still lacks newer unrelated runtime dependency source; a clean full-branch deployment is CANNOT_CONFIRM until the controller resolves that integration boundary.
