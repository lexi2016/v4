# Task 2 — current fused manager panel repair

## Result and identity

Candidate implementation is **PROPOSAL_ONLY**. The focused synthetic HTTP → production request/parser/validator → actual panel mount tests pass. This is offline candidate acceptance, not live owner/API/browser acceptance. **LIVE_API_UI_NOT_RUN**; deployment and natural-session acceptance **NOT_RUN**. Historical browser-loaded JS SHA and original live changed-component attribution remain **CANNOT_CONFIRM**.

Fixed baseline commit: `c0fc35c7b39502f49e43c2e75139dad7822091cf`. Supplied deployed identity: `stage_r4_manager_r2_owner_input_r1_fused_r1`, manifest `fd7f21af0205b9d25a8ab5d33592aff42bf76c0419799b7c1724b94a286aeb86`. Actual tested source: `/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app`. Frozen comparison: `work/baseline/app`, read-only. Canonical project remains `/Users/lexi/Desktop/学习/v4_app`; no Mac project or running 8873 was accessed. Target/selection day `20261009`, publication day `20261008`, observation `20261010` remain distinct.

This worker changed only four allowed frontend production files and two new focused runtime specs. No backend, API validator, existing regression spec, shared runtime/config, Stage or Vibe8910 edit; no service/owner operations or Git operation. Root owns API additive typing/validation, support fixtures, independent review and final Git sync. Root's API changes are separately owned and not in this worker's hash table.

## Evidence and root cause

Read `input/package/CHAT_REPAIR_REQUEST.md`, `PROBLEM_REPORT.md`, `evidence/frontend_boundary_report_20261010.md`, current frozen source and actual main/US/pending screenshot images through image inspection. Main screenshot shows stale plan; US screenshot shows separate local `VALID_EMPTY`; pending screenshot preserves 693 unresolved/695 gaps. The helper existed but no `renderDailyChannels` call was made by actual `mountCatalystObservations` rendering. Core research was appended after stock/background content, and close-recapture rows preceded it. A helper-only render could not validate that missing call.

Systematic-debugging and TDD skills were read; writing-good-tests was read from the installed local skill after opaque resource locators failed. Workspace AGENTS was read. Referenced `/Users/lexi/.codex/AGENTS.md` and `/Users/lexi/Desktop/学习/AGENTS.md` are unavailable here; no Mac access attempted.

## Changes

- Mount the existing `renderDailyChannels` with the same validated workspace response and its `date_bindings`. Legacy DTOs display three unverified channels with unknown counts; optional absence is supported. Clear channel cards when failed/date-invalid/safety-invalid data clears the workspace. Stale saved-plan state does not hide valid channel information.
- Show channel owner, product SHA, input identity, gaps, data day, run and pending/unknown count alongside the existing candidates and reasons. Existing text-node escaping remains in place. All row iteration remains complete.
- Place plan business status first, then daily channels and core evidence/research, before the full raw close-observation audit. The audit uses semantic `details`/`summary`, defaults closed and keeps complete original observation rows and each row's expandable full source object. Test includes 201 rows to catch 100/200-row truncation. Source objects are unchanged byte-for-byte in the synthetic input; no producer input slicing or mutation.
- Keep the logical business row label `美股` for existing consumers, add scoped display label `美股输入评估／完整度`. The daily card is `每日 US-HK 已审映射`; `VALID_EMPTY` derives reviewed count from the returned coverage instead of inventing 4. Four reviewed relations are explicitly local, not full-market emptiness or passing complete US input assessment.
- Bind source/selection to `selection_date ?? URL date ?? initialDate`; bind publication only when `announcement_date` or `publication_date` explicitly supplied (`announcement_date` wins). Otherwise preserve the owner publication default, including target09/publication08. The explicit publication aliases also scope standalone review/analysis; unspecified standalone behavior remains preserved. Request and returned optional bindings are checked through existing validators. Cross-plan date changes retain the independent Stage/source day.
- After manual generation perform one selected canonical GET with the same view/channel bindings, preserving finite deadline, current sequence and cancellation behavior. Root explicitly authorized this current-readback requirement. No retry/poll loop or implicit collection. Add an abort check to reject a late resolved response after user cancellation.
- Render optional root/backend diagnostic adjacent to plan status without changing admission. `CHANGED` shows the first source-backed component/date/path/saved-current SHA visibly and the complete list in collapsed details. Manifest-only provenance changes have a separate `仅 provenance；不作为陈旧原因` label. `CANNOT_CONFIRM` explicitly states the difference cannot be located. No raw payload bodies or internal component projection are rendered. All fields are text nodes; hostile source-name fixture remains literal text.

Safety remains `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`. Existing validators are consumed, not weakened. A/HK contracts, selection/price/rank/BUY gates are unchanged.

## SHA-256 and allowed modified files

| Relative candidate path | Before SHA-256 | After SHA-256 |
|---|---|---|
| apps/web/src/manager-selection/catalystObservationPanel.ts | 6650b7948cdfd7fc7eee81dbe9e47d7b86e9aa64ac476e27a72f726c35749355 | dc01e30151193e4e22966ba1621770b7e9c907b215acbd987da3244c7ba7011a |
| apps/web/src/manager-selection/businessStatus.ts | 36228506f199f26dc59c7919634e4c347171d156ec89b3d6b2359c764ed45d90 | 04a8f82577cd9fb0f21a5d934d75d7ac2b0865d968204a5f816cb549ffebc380 |
| apps/web/src/manager-selection/researchAttention.ts | 3ec804fcb248eb50793eff6f237c7e211d75c2e60e138400d4a55f74a57be698 | f250918be48647c0f3c1028e48ce4fa943922833797594dd67f95ebf08625baa |
| apps/web/src/manager-selection/dailyChannels.ts | c60254b69de369c8b50ef0ffa14dd49c802a3ae56ac4266dd9fe5f39ea40fecc | b7ad877a63d688709a3bb47f832f84fbaf7856ebb4c3888aa19beae8c7da529c |
| apps/web/src/manager-selection/catalystObservationPanel.liveRepair.runtime.spec.ts | NEW | 05f31ebc81b41ea52dde12ef834e56fd71043ce159113e1bfef741a0f470275c |
| apps/web/src/manager-selection/catalystObservationPanel.backendDto.runtime.spec.ts | NEW | 19cb634da133a0beab195b070dc9af9a482760ba2dd1f6a09ecd37d8cb6e6a5b |

Machine-readable manifest: `review/task-2/sha256.json`. Minimal patch including new focused spec: `review/task-2/minimal.diff`. No stylesheet change was needed.

## TDD receipts

Actual commands use the isolated source/cache environment; no live request leaves the fetch double.

| Receipt | Actual result | What failed or passed |
|---|---|---|
| `red.log` | FAIL: 4 failed, 3 passed | Actual mount missing three channels, raw collapsed audit, scoped US label, legacy unknown-channel cards. Fixtures validate; date/safety rejection already passed. This ran before production edits, whose before SHA matched frozen source. |
| `binding-red.log` | FAIL: 1 failed, 8 passed | Wrong explicitly selected publication day was self-consistent but admitted READY; expected FAILED. |
| `diagnostic-red.log` | FAIL: 3 failed, 9 passed | Additive diagnostic absent from actual mount, including changed source, provenance-only and CANNOT_CONFIRM. |
| `source-refresh-red.log` | FAIL: 2 failed, 12 passed | Wrong Stage/source date admitted; POST preview rendered rather than canonical selected GET. |
| `cancel-red.log` | FAIL: 1 failed, 14 skipped | Late response after Cancel admitted READY; expected FAILED. |
| `focused-final.log` | PASS: 8 files, 71 tests | New 15-case synthetic mount spec, 5-case actual backend DTO mount spec, and six existing channel/research/API contract suites. Root API diagnostic validator included in final run. |
| `focused-typecheck.log` | PASS, exit 0 | Strict focused TypeScript on all modified source/spec and their imported dependencies. |

Initial implementation test attempt failed due to an accidentally referenced absent `scalar` helper; corrected to `String(returned_count ?? '数量未知')` and reran. That intermediate green log was superseded, not acceptance. Focused tsc initially omitted `DOM.Iterable` in the standalone CLI invocation; reran with appropriate DOM iterable lib. Adding the Node-backed fixture spec also required `node` in the standalone CLI types list; reran with `--types vitest/globals,node`. Root additive types then correctly rejected synthetic `mode:RESEARCH_ONLY`; corrected fixture to contract `REPLAY` and current identity/slot to the validated envelope. None of these temporary failures is presented as acceptance.

### Exact commands

Initial actual-panel RED (candidate production bytes still frozen):

```bash
V4_TEST_SOURCE_ROOT=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app V4_TEST_CACHE_DIR=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/review/task-2/cache-red /workspace/scratch/0e089a11ee60/work/web_runtime/node_modules/.bin/vitest run --config /workspace/scratch/0e089a11ee60/work/vitest.config.mjs src/manager-selection/catalystObservationPanel.liveRepair.runtime.spec.ts
```

Publication binding, diagnostic, source/refresh RED use this same test path/config with caches `cache-binding-red`, `cache-diagnostic-red`, `cache-source-refresh-red`, and separate logs. Cancellation RED uses `cache-cancel-red` plus `-t 'does not admit a late bound response'`.

Final focused suite:

```bash
V4_TEST_SOURCE_ROOT=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app V4_TEST_PYTHON=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/runtime/bin/python V4_BACKEND_UI_FIXTURE_ROOT=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/review/backend-ui-fixtures V4_TEST_CACHE_DIR=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/review/task-2/cache-focused-final /workspace/scratch/0e089a11ee60/work/web_runtime/node_modules/.bin/vitest run --config /workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/vitest.integration.config.mjs src/manager-selection/catalystObservationPanel.liveRepair.runtime.spec.ts src/manager-selection/catalystObservationPanel.backendDto.runtime.spec.ts src/manager-selection/dailyChannels.spec.ts src/manager-selection/__tests__/researchAttention.spec.ts src/api/managerWorkspace.threeChannel.spec.ts src/api/managerWorkspace.usIsolation.spec.ts src/api/managerWorkspace.attention.spec.ts src/api/managerWorkspace.dailyAutomation.spec.ts
```

Focused tsc, working directory candidate `apps/web`:

```bash
/workspace/scratch/0e089a11ee60/work/web_runtime/node_modules/.bin/tsc --noEmit --strict --skipLibCheck --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM,DOM.Iterable --types vitest/globals,node src/manager-selection/catalystObservationPanel.ts src/manager-selection/businessStatus.ts src/manager-selection/researchAttention.ts src/manager-selection/dailyChannels.ts src/manager-selection/catalystObservationPanel.liveRepair.runtime.spec.ts src/manager-selection/catalystObservationPanel.backendDto.runtime.spec.ts
```

Runtime: Node `v24.19.0`, Vitest `4.1.10`, jsdom, offline synthetic HTTP. Python subprocess fixture runtime is task-local 3.12.14, below project `>=3.14` declared baseline; this deviation must not be described as exact production environment.

## Remaining regression failures and initial broader runs

Final runtime command uses the final integration config and isolated `cache-runtime-final`, paths `src/manager-selection/dailyChannels.runtime.spec.ts src/manager-selection/catalystObservationPanel.runtime.spec.ts`. `runtime-final.log`: **3 failed / 29 passed** (2 files failed):

1. `catalyst workspace runtime boundary > reuses the validated refresh response instead of issuing a second same-date GET`: old expected behavior contradicts root-authorized selected canonical GET after manual POST. New actual-mount regression verifies fresh canonical result; old spec not edited.
2. `catalyst workspace runtime boundary > renders the actual Eastmoney owner workspace readback instead of reporting a network failure`: absent Mac-only `/Users/lexi/Desktop/学习/agents调试/EASTMONEY_HK_ANN_20260929/integration/workspace_after.json`. NOT_RUN for that real-owner fixture; not replaced with invented data.
3. `first-screen independent research channels > rebinds one legacy default GET when a new backend returns different display/publication dates`: requires a second implicit legacy-date fallback GET and default publication=Stage day. Current contract binds source day on the first canonical GET and leaves unspecified publication to owner prior-HK-day default. It is incompatible with current date boundaries, not a reason to force target-day announcements. Existing spec preserved.

Initial broader runs were performed before root supplied the Vue-enabled integration config and restored frozen ownerObservations fixture. `regression.log` was 8 files failed/12 passed; 30 tests failed/141 passed, including temporary display-label lookup failures (fixed using stable logical label). Initial full candidate `full-suite.log` was 21 files failed/13 passed, 19 tests failed/177 passed; full baseline `baseline-full-suite.log` was 21 files failed/12 passed, 21 tests failed/168 passed. Vue parse/import and missing-file collection failures make these runs incomplete and not final suite acceptance. Root owns the full final baseline/candidate integration run after support restoration; this worker did not duplicate it.

Whole-app `vue-tsc --noEmit -p apps/web/tsconfig.json` failed on both frozen baseline and candidate with the same initial six errors: missing `views/ResearchView.vue`; missing `issue8R2.ownerObservations.json`; two resulting implicit-any parameters in that fixture; two unused `@ts-expect-error` directives in `ManagerSelectionView.spec.ts`. Logs `typecheck.log` and `baseline-typecheck.log` are identical. Root subsequently restored the frozen issue8 fixture; broad post-restoration typecheck is root-owned. The focused modified-source check passes.

See `initial-failure-identifiers.md` for preserved names from initial incomplete/full regression runs. No existing tests were altered to conceal failures.

## Acceptance boundary and review inputs

Candidate synthetic acceptance PASS within tested scope. Actual backend-emitted additive DTO roundtrip through this panel: **PASS, 5/5**; complete emitted router/service DTOs are validated and mounted without reshaping. `manifest_only_match` stays CURRENT/consumed/MATCH with separate provenance; `consumed_content_changed` and `consumed_availability_rejected` remain stale/nonconsumed/CHANGED; `legacy_missing_components` remains stale/nonconsumed/CANNOT_CONFIRM; `date_bindings_changed` retains source/selection20261008 and plan20261009 with explicit CHANGED. Input objects remain unchanged. `backend-dto.log` and `backend-fixture-sha256.json` record this offline cross-language acceptance. These are synthetic original-owner fixtures, not live owner data. Independent acceptance, final backend/frontend integration, deployment, live API/UI and natural-session acceptance remain root/Mac responsibilities. Screenshot layout is inspected input evidence; a repaired browser screenshot was not claimed. There is no claim that all 693 pending inputs, PIT gaps, HK target membership, full-market US coverage or announcement09/08 import have been resolved.

Review inputs are the six whitelisted paths, minimal diff, before/after manifest, actual RED logs, focused/runtime/typecheck logs, plus root-owned exact backend DTO validator and receipt. GitHub sync is not performed by this worker; root must commit explicit necessary paths and read back remote commit/blob SHA before reporting synchronization.

## Actual backend DTO generation prerequisite

The cross-language spec reads `V4_BACKEND_UI_FIXTURE_ROOT` and explicitly skips its five cases if the directory is not configured; the reported actual integration run configured it and had no skipped cases. Root exported fresh DTOs by exercising the real router/service through `tests/test_manager_semantic_identity_20261010.py` with `TASK1_BACKEND_FIXTURE_ROOT`. Reproducible prerequisite from candidate source root (root-owned generation; this worker consumed the already generated DTOs):

```bash
TASK1_BACKEND_FIXTURE_ROOT=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/review/backend-ui-fixtures PYTHONDONTWRITEBYTECODE=1 /workspace/scratch/0e089a11ee60/live_ui_api_20261010/runtime/bin/python -m pytest tests/test_manager_semantic_identity_20261010.py --basetemp /workspace/scratch/0e089a11ee60/live_ui_api_20261010/review/backend-dto-regeneration-tmp
```

The five JSON response files remain temporary/reproducible and should not be uploaded needlessly; new focused spec and this explicit generation prerequisite are sufficient. Regenerate if backend semantic metadata changes before final acceptance and recapture fixture SHA.
