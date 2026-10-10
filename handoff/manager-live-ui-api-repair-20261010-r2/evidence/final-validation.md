# Final paired offline regression validation — 2026-10-10

**Status: PROPOSAL_ONLY. Full Python, full frontend, whole-app typecheck and build remain FAIL.** The final frozen candidate passes the new 56-case Python regression file, all 44 new frontend tests (including six actual router DTOs), and the unchanged original 76 Issue8R2 guards. This is bounded offline acceptance, not deployment or live API/UI acceptance.

This validator changed no production source and no existing test. It restored the exact old Issue8R2 spec to both assemblies and copied missing new focused tests to the baseline; all test paths are now byte-identical across the pair. The underlying fixed source/test-support failures remain visible. No Git, service, network, owner, Stage, scheduling, BUY or Vibe operation was performed by this validator.

## Results and comparable populations

| Gate | Frozen baseline | Frozen candidate | Actual status |
|---|---:|---:|---|
| Full pytest, continue after collection errors | 302 FAIL / 1241 PASS / 20 SKIP / 33 ERROR | 288 FAIL / 1255 PASS / 20 SKIP / 33 ERROR | FAIL both; 8 collection + 25 setup errors each |
| New focused backend file, included above | 16 FAIL / 40 PASS | 56 PASS | Candidate focused PASS |
| Original backend population, excluding new56 | 286 FAIL / 1201 PASS / 20 SKIP / 33 ERROR | 288 FAIL / 1199 PASS / 20 SKIP / 33 ERROR | 2 candidate-only original full-run failures; see below |
| Full npm test, Vue-enabled config | 60 FAIL / 332 PASS / 1 SKIP | 20 FAIL / 372 PASS / 1 SKIP | FAIL both; same 4 load failures |
| Frontend files | 14 FAIL / 22 PASS / 1 SKIP (37) | 11 FAIL / 25 PASS / 1 SKIP (37) | JSON nested suite totals are not file totals |
| Original Issue8R2 guards, unchanged | 76 PASS | 76 PASS | PASS both; no guard edits |
| New API identity diagnostic boundary | 16 FAIL / 7 PASS | 23 PASS | Candidate PASS |
| New actual panel synthetic runtime | 12 FAIL / 3 PASS | 15 PASS | Candidate PASS |
| New actual backend DTO → validator → mount | 6 FAIL | 6 PASS | Candidate PASS; fixture env configured, zero skips |
| Whole-app npm run typecheck | FAIL, exit2 | FAIL, exit2 | Same 3 diagnostic lines |
| Whole-app npm run build | FAIL, exit1 | FAIL, exit1 | Same missing entry module |
| Strict tsc on all changed TS and new specs | NOT_RUN (candidate gate) | PASS, exit0 | Focused gate only |

The earlier baseline result **286 FAIL / 1201 PASS / 20 SKIP / 33 ERROR** is preserved in `review/baseline-validation.json` and `evidence/logs/baseline-pytest-continue.log`. Its original failure identity set matches this final baseline exactly. The count increase is solely the newly identical 56-case Python file: +16 FAIL and +40 PASS. The earlier supported frontend baseline was 26 FAIL /246 PASS /1 SKIP; restoring76 old guards and adding44 new tests produces exactly60 FAIL /332 PASS /1 SKIP. No former result is overwritten or presented as a pass.

The raw bare pytest run had already failed with 8 collection errors; it was not repeated. Final `--continue-on-collection-errors` runs collected1588 actual tests per side; JUnit contains1596 entries because it also represents the8 collection failures. Both commands exited1. Full raw logs, JUnit XML, Vitest JSON, their SHA256 and exact execution receipts are indexed in `final-validation.json`.

## Failure deltas and remaining acceptance boundaries

### Original backend: two observed candidate-only full-run failures

1. `tests/test_manager_daily_automation_20261008.py::test_late_input_advances_same_day_plan_without_overwriting_preopen_history` stays **FAIL** on the candidate, including the single necessary paired targeted rerun. Its monkeypatch replaces only `value["input_identity"]` with a synthetic new SHA while retaining `input_identity_components` bound to the old identity. The new readback gate rejects that inconsistent metadata with `WORKSPACE_PLAN_SAVE_READBACK_FAILED`. This explains a legacy fixture/new metadata contract mismatch; the original test was not rewritten and the old late-input test is not claimed to pass.

The whole-change reviewer separately exercised an actual bound archive payload/receipt change through the original same-day catch-up path: **1 PASS on each source root**, CURRENT readback, changed plan identity and unchanged old preopen plan bytes. This validator read the probe/logs and verified their SHA (`review/whole-review-bound-late-input.json`). That supports the contract-conflict explanation for the identity-only fixture; it does not replace the original FAIL or establish live/PIT acceptance.

2. `tests/test_manager_history_control_r1.py::test_projection_memo_capacity_bytes_ttl_and_exceptions` failed only in the candidate full run: an expected single cache entry had expired to zero. It uses a15ms TTL, sleeps20ms, then expects an entry to survive subsequent exception calls without a frozen clock. The paired full runs executed concurrently; this candidate case took89ms. One sequential targeted paired rerun passed on both source roots. The memo implementation is byte-identical across baseline and candidate. This is a timing-sensitive observed failure; the original full-suite FAIL and288 count are retained, with no assertion that the entire suite is green.

Exactly16 Python failure→pass changes are all in the new focused file. There are **no resolved original Python failure names**. The319 original failures/errors already present at baseline remain shared, alongside the2 observed candidate-only full-run failures. All names and original/candidate outcomes appear in the JSON inventories.

### Original frontend: seven resolved, one introduced, nineteen shared test failures

Seven unmodified existing dailyChannels runtime tests now pass:

- `src/manager-selection/dailyChannels.runtime.spec.ts > first-screen independent research channels > aborts the older plan request and never lets its late response replace selected bindings`
- `src/manager-selection/dailyChannels.runtime.spec.ts > first-screen independent research channels > binds the publication alias deterministically through the actual GET: publication_date=20261006`
- `src/manager-selection/dailyChannels.runtime.spec.ts > first-screen independent research channels > binds the publication alias deterministically through the actual GET: publication_date=20261006&announcement_date=20261007`
- `src/manager-selection/dailyChannels.runtime.spec.ts > first-screen independent research channels > keeps cancellation effective while the one-time legacy binding read is pending`
- `src/manager-selection/dailyChannels.runtime.spec.ts > first-screen independent research channels > reloads the selected canonical GET after manual generation and does not claim a scheduled run`
- `src/manager-selection/dailyChannels.runtime.spec.ts > first-screen independent research channels > renders stock, original reason, data date, run and status without expanding diagnostics`
- `src/manager-selection/dailyChannels.runtime.spec.ts > first-screen independent research channels > shows three unverified channels for an older workspace instead of inferring zero counts`

One unmodified old assertion newly fails: `src/manager-selection/catalystObservationPanel.runtime.spec.ts > catalyst workspace runtime boundary > reuses the validated refresh response instead of issuing a second same-date GET`. It requires reuse of the POST preview, while the authorized repair requires one selected canonical GET after manual generation. This is retained as an **original contract-difference FAIL**, with the new actual-mount selected-GET test passing. No old test was changed to hide the difference.

The shared old `rebinds one legacy default GET when a new backend returns different display/publication dates` case also remains FAIL: it expects a second implicit fallback GET and a publication default coupled to the Stage day. Current source/date binding and the owner prior-publication default are preserved by the repair. This discrepancy is documented, not counted as PASS.

The other shared frontend failures include seven announcement business-status assertions, five full `ManagerSelectionView.dailyIntegration` assertions, and six unavailable Mac owner/announcement fixture assertions. The five full-parent cases remain genuine FAIL; some candidate cases advance to a later failing assertion after the panel wiring succeeds. Bounded panel/DTO tests do not establish whole-parent acceptance. The4 common suite-load errors are3 imports of missing `views/ResearchView.vue` and1 missing `manager-selection/index.html`.

All34 new frontend baseline failures resolve on the candidate. All44 new cases execute, including all6 actual Python router/service DTOs; none is skipped. The restored76 old guard tests pass unchanged on both sides.

### Full typecheck/build and backend support errors

Whole-app typecheck fails identically on both sides:

- `src/App.vue(6,26): error TS2307: Cannot find module './views/ResearchView.vue' or its corresponding type declarations.`
- `src/views/ManagerSelectionView.spec.ts(4,1): error TS2578: Unused '@ts-expect-error' directive.`
- `src/views/ManagerSelectionView.spec.ts(6,1): error TS2578: Unused '@ts-expect-error' directive.`

Whole-app build fails identically because `daily-research-command/index.html` is missing. It transforms0 modules. The missing source/entry files were not fabricated. Candidate strict focused tsc includes `managerWorkspace.ts`, the diagnostic spec, all four changed panel/channel/business/research files, and both new mount specs; it exits0.

The8 collection failures remain missing `stage_center.research_read_binding` (6 files), missing `_read_hk_prefix_research_asset` (1), and missing `ops.build_manager_source_successor_proof` (1). The25 setup errors include unavailable Stage/app support, `contracts/runtime_workloads.json`, an absent `STAGE_RECOVERY_EXPECTED_APP_ROOT` prerequisite and the HK child-owner entry. Full create_app acceptance remains CANNOT_CONFIRM. Exact error node IDs and messages are retained in the JSON.

## Source and original guard verification

Fixed Git input: `c0fc35c7b39502f49e43c2e75139dad7822091cf`, tree inventory SHA `21e0e3ae3cd9434ae95400b4ed2abbd0c16ff1bd`. The original guard spec is copied from the prior restoration handoff and verified by Git blob hashing against the supplied fixed tree:

| Fixed file | Git blob SHA1 | SHA256 |
|---|---|---|
| issue8R2.spec.ts | `a37994c4a54b4fec2d1a4b5ff8969e17ade60592` | `3b8e004f31135674d63c1affd25cc41d759bfd10187a1dfc318f64c53636f873` |
| issue8R2.fixture.ts | `7decbc76298a57a1c0c6e05caeb1125517bbe42a` | `173d1711fc86fbb392eb616d4dde7bcab21b5b1a74b24372b9314b1297a31525` |
| issue8R2.ownerObservations.json | `5ef20fed9a3f31a1ac5df9a2b7b1af71263f7c60` | `0a56e12d5a56e7534b9a484e8bc2443677a2abeb5d3a9feea56ac0d641b2dce8` |

The byte-identical old spec was added to both `apps/web/src/manager-selection/__tests__/issue8R2.spec.ts`. Existing fixture files were verified, not rewritten. The4 new focused paths are identical across baseline/candidate; the diagnostic spec already existed identically, while the other missing baseline new files were copied. The final backend file has56 cases and SHA `bf16a6d5e94cc2d70e92735a6e69da998afc960569bda6d908c3712d4237ae42`; the final six-case DTO spec has SHA `b08218ab27bde6628dc54d75889369543fd5e8a4ec429339c55de3943139d1f8`.

All1076 baseline files and1077 candidate files in the recorded source inventory are unchanged between pre-test and post-test SHA snapshots. The only pairwise production differences are the9 frozen proposed paths below; the validator did not change any of them. Full before/after fields, protected unchanged sources, and tree digests are in `final-validation.json` and the three `final-source-*.json` receipts.

| Proposed path | Baseline SHA256 (pre/post same) | Candidate SHA256 (pre/post same) |
|---|---|---|
| `apps/web/src/api/managerWorkspace.ts` | `2c02d4cff38d749fcad91b892da83029c8269287fbb867a2216f09ef8aa2c43f` | `3dd4771366b5aa5e377024a94785c33159b89e396fde80f12f4a6a4cb4e7b7d5` |
| `apps/web/src/manager-selection/businessStatus.ts` | `36228506f199f26dc59c7919634e4c347171d156ec89b3d6b2359c764ed45d90` | `f55b62da1af832386182752912f908bd387bc2b53f0351e56b7350267e83e9c0` |
| `apps/web/src/manager-selection/catalystObservationPanel.ts` | `6650b7948cdfd7fc7eee81dbe9e47d7b86e9aa64ac476e27a72f726c35749355` | `dc01e30151193e4e22966ba1621770b7e9c907b215acbd987da3244c7ba7011a` |
| `apps/web/src/manager-selection/dailyChannels.ts` | `c60254b69de369c8b50ef0ffa14dd49c802a3ae56ac4266dd9fe5f39ea40fecc` | `b7ad877a63d688709a3bb47f832f84fbaf7856ebb4c3888aa19beae8c7da529c` |
| `apps/web/src/manager-selection/researchAttention.ts` | `3ec804fcb248eb50793eff6f237c7e211d75c2e60e138400d4a55f74a57be698` | `f250918be48647c0f3c1028e48ce4fa943922833797594dd67f95ebf08625baa` |
| `v4/manager_research/archive_catalyst_inputs.py` | `968b26e66cb041adcf503e251c2c710728ce33638627123ff618357398b37b71` | `3a16ba2b996156ff923ce601d247c98778a546bae874850e1603ea7fcb8c5ae3` |
| `v4/manager_research/workspace.py` | `7a4875f1ab5ba46ac6c18bdaffe2c103a136734fda276fbee918163332844bb0` | `9a01a023f9c4244ba13a0d23c3f0f36e9e6e90db9d88073e3a4bf94bb7b8fa67` |
| `v4/manager_research/workspace_identity.py` | `ABSENT` | `bc4e516b98e518190dfa76277598cefc3da7b096610eebd5d3d32d2536acd0c6` |
| `v4/manager_research/workspace_projection.py` | `027d855613e675e1f569b401b9a8344e40766b88c31e987e791d05a0b3a2f200` | `54e98d1d46c24719906dfef0ae4fe9f11524d7e8cb02c66126877fb15bb54f4c` |

`archive_catalyst_inputs.py` is a verified fixed-Git support preimage, outside the25 supplied current-fused files; its actual deployed preimage remains CANNOT_CONFIRM until the Mac owner checks the SHA. No container snapshot is represented as the active Mac source. The research source reader, existing-material reader, catalyst owner and projection memo source are unchanged on both sides.

## Runtime, commands and evidence

- Baseline source: `/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/baseline/app`; candidate source: `/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app`.
- Python: task-local `runtime/bin/python`, CPython3.12.14 on Linux. All31 locked third-party package versions match `uv.lock`. Project requirement `>=3.14` is **NOT_MET**; this is not an exact production interpreter. The old `four_function_gaps/runtime_locked/bin/python` was missing and was not used.
- Node24.19.0; npm11.9.0; Vitest4.1.10; TypeScript5.9.3; Vue3.5.40; Vue plugin6.0.8; vue-tsc3.3.8; jsdom28.1.0. Existing isolated frontend dependency root and Vue-enabled integration config are recorded in the runtime receipt.
- Per-source environment explicitly sets `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH`, `PLAN_AUDIT_APP_ROOT`, `V4_TEST_SOURCE_ROOT`, `V4_TEST_PYTHON`, isolated `V4_TEST_CACHE_DIR`, and `V4_BACKEND_UI_FIXTURE_ROOT`. Inherited task-specific V4/V35/TASK1/PLAN_AUDIT variables are cleared before those values. `PATH` prioritizes the observed Node/task Python/local frontend tool directories. No new dependency installation occurred.
- Execution receipt times use UTC; underlying test logs inherit the container local timezone recorded in `final-runtime.json`. Test dates/cutoffs are synthetic explicit clocks, not natural executions.

Actual commands are stored without abbreviation in the `commands` section of `final-validation.json` and in `review/final-command-records.json`, including complete argv/environment, working directory, UTC start/end, return code, log and SHA. The exact full-suite argv are:

```bash
# final-baseline-npm-test; CWD /workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/baseline/app/apps/web
/opt/codex/runtimes/codex-primary-runtime/dependencies/node/bin/npm test -- --config /workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/vitest.integration.config.mjs --reporter=default --reporter=json --outputFile.json=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/evidence/logs/final-baseline-vitest.json
# final-baseline-pytest; CWD /workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/baseline/app
/workspace/scratch/0e089a11ee60/live_ui_api_20261010/runtime/bin/python -B -m pytest -p no:cacheprovider --continue-on-collection-errors --basetemp=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/final-baseline-pytest-tmp --junitxml=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/evidence/logs/final-baseline-pytest.xml
# final-candidate-npm-test; CWD /workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app/apps/web
/opt/codex/runtimes/codex-primary-runtime/dependencies/node/bin/npm test -- --config /workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/vitest.integration.config.mjs --reporter=default --reporter=json --outputFile.json=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/evidence/logs/final-candidate-vitest.json
# final-candidate-pytest; CWD /workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app
/workspace/scratch/0e089a11ee60/live_ui_api_20261010/runtime/bin/python -B -m pytest -p no:cacheprovider --continue-on-collection-errors --basetemp=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/final-candidate-pytest-tmp --junitxml=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/evidence/logs/final-candidate-pytest.xml
```

The same recorded per-source environment is used for actual `npm run typecheck` and `npm run build`. One additional targeted paired run of the two newly failing original Python cases resolves only the concrete timing/contract question. No full-suite rerun replaces the initial final results.

| Command receipt | Exit | Seconds | Full log |
|---|---:|---:|---|
| `final-baseline-build` | 1 | 0.37 | `evidence/logs/final-baseline-build.log` |
| `final-baseline-introduced-originals` | 0 | 0.667 | `evidence/logs/final-baseline-introduced-originals.log` |
| `final-baseline-npm-test` | 1 | 63.419 | `evidence/logs/final-baseline-npm-test.log` |
| `final-baseline-pytest` | 1 | 85.757 | `evidence/logs/final-baseline-pytest.log` |
| `final-baseline-typecheck` | 2 | 6.132 | `evidence/logs/final-baseline-typecheck.log` |
| `final-candidate-build` | 1 | 0.615 | `evidence/logs/final-candidate-build.log` |
| `final-candidate-focused-tsc` | 0 | 2.311 | `evidence/logs/final-candidate-focused-tsc.log` |
| `final-candidate-introduced-originals` | 1 | 0.822 | `evidence/logs/final-candidate-introduced-originals.log` |
| `final-candidate-npm-test` | 1 | 52.316 | `evidence/logs/final-candidate-npm-test.log` |
| `final-candidate-pytest` | 1 | 86.744 | `evidence/logs/final-candidate-pytest.log` |
| `final-candidate-typecheck` | 2 | 8.535 | `evidence/logs/final-candidate-typecheck.log` |

Six backend DTOs are actual outputs of the repaired registered router/service using synthetic local artifacts; they are not live owner data. Both frontend trees consume the same six unchanged outputs. Their names/SHA/status evidence is in `final-backend-fixtures.json`; candidate statuses are CURRENT/MATCH for both unmaterialized and materialized catalyst manifest-only changes, CHANGED for consumed-content/availability/date changes, and CANNOT_CONFIRM for missing legacy metadata. These raw temporary response files and full synthetic temp plans are not needed in a compact Git handoff.

## Final acceptance statement

Candidate focused backend, diagnostic-validator, actual panel and cross-language DTO gates pass within their explicit offline scopes, including unchanged original76 guards. Full backend/frontend/typecheck/build gates remain FAIL with the above identities preserved. Independent review/integration must use these failure dispositions; this report does not approve deployment, full create_app, complete parent UI, live8873 or natural-time behavior.

Mac canonical source `/Users/lexi/Desktop/学习/v4_app`, actual API/Stage process identity, historical changed field, unique live root cause and browser-loaded JavaScript SHA remain outside this execution. Deployment, services, schedules, owner capture/import, Stage/BUY/Vibe8910 and natural sessions are NOT_RUN. The existing693pending/PIT/authority/full-marketUS/announcement09–08 data gaps remain unchanged. Git synchronization and remote commit/blob readback are root-owned; this validator performs neither.

