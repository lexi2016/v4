# US mapping E2E implementation receipt

## Restored deployed build dependencies

The isolated worktree lacked Vite entry modules and their daily-research and shared UI imports. The frozen `SCOPE.json` was updated before restoration; 50 absent source files were copied byte-for-byte from the deployed release at:

`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-visible-stock-lists-api-20261019-r2/app`

Every SHA-256 below was computed from the deployed source and restored worktree bytes, then checked against `SCOPE.json`.

| Path | Deployed source SHA-256 | Restored worktree SHA-256 |
|---|---|---|
| `apps/web/src/main.ts` | `e6500223b08750e885d03202ca2776bb169095420cbc9608f8bbf03b6c7d2c41` | `e6500223b08750e885d03202ca2776bb169095420cbc9608f8bbf03b6c7d2c41` |
| `apps/web/src/manager-workbench/AnnouncementCandidates.vue` | `e517c05557700bdf4fa5c61be9194d14239f33737ab8f58e81e87bdd10e60305` | `e517c05557700bdf4fa5c61be9194d14239f33737ab8f58e81e87bdd10e60305` |
| `apps/web/src/App.vue` | `71fb358a0ca855273ae0159691fe9a9715fae75d8c6944d275417278a37ef776` | `71fb358a0ca855273ae0159691fe9a9715fae75d8c6944d275417278a37ef776` |
| `apps/web/src/api/globalIndustries.ts` | `023b0316f3961abcd298cb0ae5fce05949e377548a57361c015ad2ad7eb9cdbe` | `023b0316f3961abcd298cb0ae5fce05949e377548a57361c015ad2ad7eb9cdbe` |
| `apps/web/src/api/pool_stage.ts` | `f56ff86f819ded834bb9f7309d3b8a3194f40ad1dc4739f2828f74dfb827ebca` | `f56ff86f819ded834bb9f7309d3b8a3194f40ad1dc4739f2828f74dfb827ebca` |
| `apps/web/src/api/research_lane.ts` | `e543f7d5e6c750678818bce166ccdbaf5175382e8a9471b8c73531eaf39c2c86` | `e543f7d5e6c750678818bce166ccdbaf5175382e8a9471b8c73531eaf39c2c86` |
| `apps/web/src/api/review.ts` | `fc2c7551fe386a9b01375d6d82d7f633990bba169f48e9b918386e31baa6dd7d` | `fc2c7551fe386a9b01375d6d82d7f633990bba169f48e9b918386e31baa6dd7d` |
| `apps/web/src/api/runtime.ts` | `96d257a9266400443b7aad1252c4f709a0f24873ce9afab3f4a6dc9a189ff7c0` | `96d257a9266400443b7aad1252c4f709a0f24873ce9afab3f4a6dc9a189ff7c0` |
| `apps/web/src/api/wechat_research.ts` | `eb42b8dcdec5ae8b6bf72e132f94394009cc9ea65f4b83471fc077e59a1084fa` | `eb42b8dcdec5ae8b6bf72e132f94394009cc9ea65f4b83471fc077e59a1084fa` |
| `apps/web/src/app_shell/formatters.ts` | `35529e105f67227f11fb73548144fdb9cc22698090e0a0c73bd2fbfdd0d23440` | `35529e105f67227f11fb73548144fdb9cc22698090e0a0c73bd2fbfdd0d23440` |
| `apps/web/src/app_shell/timeline.ts` | `58cb16b14b6791c25dc69fcfa1c1fd2c1980bd593a0ed407b3c5ea98b08470e8` | `58cb16b14b6791c25dc69fcfa1c1fd2c1980bd593a0ed407b3c5ea98b08470e8` |
| `apps/web/src/app_shell/types.ts` | `af426dc751a38a48c75c4216d6ba782f6244588c2aee00cc2bb4af5e2ede0c1f` | `af426dc751a38a48c75c4216d6ba782f6244588c2aee00cc2bb4af5e2ede0c1f` |
| `apps/web/src/app_shell/useAppShell.ts` | `4e4eb64238c5d5c5734f8c5c5a642cb05688d9554589ec12616dbdab6f1fa0d8` | `4e4eb64238c5d5c5734f8c5c5a642cb05688d9554589ec12616dbdab6f1fa0d8` |
| `apps/web/src/components/research/GlobalIndustryMap.vue` | `185b3cb586f5e0daeefe7f0016674bc904c22edd465e88b92bedfa87d02467ce` | `185b3cb586f5e0daeefe7f0016674bc904c22edd465e88b92bedfa87d02467ce` |
| `apps/web/src/components/research/ResearchAppendix.vue` | `2969a9c32e5a253c7f4165f30f1faa3cf3283ebcb33aae0fb83f1c9b209f4a21` | `2969a9c32e5a253c7f4165f30f1faa3cf3283ebcb33aae0fb83f1c9b209f4a21` |
| `apps/web/src/components/research/ResearchContextPane.vue` | `1cbcfcc7109e7b1a15d49e64435ba32b67c204f0bf0ea2a797a2a93687afac59` | `1cbcfcc7109e7b1a15d49e64435ba32b67c204f0bf0ea2a797a2a93687afac59` |
| `apps/web/src/components/research/ResearchFeedCard.vue` | `6f3c6593fe19fccee3ed7b47e63a7c4493ce4199e2216d31dfc0ecf5a9b9ffbd` | `6f3c6593fe19fccee3ed7b47e63a7c4493ce4199e2216d31dfc0ecf5a9b9ffbd` |
| `apps/web/src/components/research/ResearchFeedPane.vue` | `8980cd832a42b8d9bd353933ae98cb458d3fb13bc28c36e2f0df5892ddf72e4a` | `8980cd832a42b8d9bd353933ae98cb458d3fb13bc28c36e2f0df5892ddf72e4a` |
| `apps/web/src/components/research/ResearchImpactList.vue` | `c2248151611747cf2c14f7e07983470cc85a94b3d566e7616ab133f533e7e087` | `c2248151611747cf2c14f7e07983470cc85a94b3d566e7616ab133f533e7e087` |
| `apps/web/src/components/research/ResearchSourceColumns.vue` | `4b6d6ee1344dfcca5ed45df8e60853be099942a1930047f6091b9ded0359fe1c` | `4b6d6ee1344dfcca5ed45df8e60853be099942a1930047f6091b9ded0359fe1c` |
| `apps/web/src/components/research/ResearchStatusStrip.vue` | `5066ba418f6502e4ae6eefb2d7ac94221232aab16f187cbe875e33172ad4ac8a` | `5066ba418f6502e4ae6eefb2d7ac94221232aab16f187cbe875e33172ad4ac8a` |
| `apps/web/src/components/research/WechatMentionPool.vue` | `e542fb168e3f3fd6b8303e01df3002c8ae01a33c353ab30da944de7b59f18ce7` | `e542fb168e3f3fd6b8303e01df3002c8ae01a33c353ab30da944de7b59f18ce7` |
| `apps/web/src/components/research/WechatResearchPanel.vue` | `4cb44d8e06164d967339c201dca48cabef7aa1b7678c30a107c7ecab1b143592` | `4cb44d8e06164d967339c201dca48cabef7aa1b7678c30a107c7ecab1b143592` |
| `apps/web/src/components/review/AshareReviewPanel.vue` | `f9deaf8d15a3273d3237458b083b847a72f6dcda86824d37731103c13d6672bf` | `f9deaf8d15a3273d3237458b083b847a72f6dcda86824d37731103c13d6672bf` |
| `apps/web/src/components/review/DailyResearchReviewPanel.vue` | `a62d8c47419cac7d3d674693eddb5984b12f18268188f0328b163a60d590efb9` | `a62d8c47419cac7d3d674693eddb5984b12f18268188f0328b163a60d590efb9` |
| `apps/web/src/components/review/HkCloseReviewPanel.vue` | `7a1eacbe709d38071107e116cdc81be8eed3659e5eaf9ca294273c1f88127e33` | `7a1eacbe709d38071107e116cdc81be8eed3659e5eaf9ca294273c1f88127e33` |
| `apps/web/src/components/review/ReviewEvidencePanel.vue` | `6164c5cd0042f70315b3aa6daf102b706c8b99055dffa702a574ca96ce025ef4` | `6164c5cd0042f70315b3aa6daf102b706c8b99055dffa702a574ca96ce025ef4` |
| `apps/web/src/components/review/StageSummaryPanel.vue` | `4457dfd6aa6e138493026358b186011bed6e7b09f9ba33a6a529db1b3a6483b5` | `4457dfd6aa6e138493026358b186011bed6e7b09f9ba33a6a529db1b3a6483b5` |
| `apps/web/src/composables/researchFeedPresentation.ts` | `6ab145253d6ad1957902c5262ed0c82cc2adb4d58dff09ebc484fed4f76d0e52` | `6ab145253d6ad1957902c5262ed0c82cc2adb4d58dff09ebc484fed4f76d0e52` |
| `apps/web/src/composables/useResearchLane.ts` | `c185614a38c401a9afdf9d392c1e866b3942b7740f870894b120a83c690401ff` | `c185614a38c401a9afdf9d392c1e866b3942b7740f870894b120a83c690401ff` |
| `apps/web/src/contracts/globalIndustries.ts` | `1d99226b27c1716833828c4c2d442e4e7a40fa36bd8d4507cd41a0a845e57b3d` | `1d99226b27c1716833828c4c2d442e4e7a40fa36bd8d4507cd41a0a845e57b3d` |
| `apps/web/src/contracts/review.ts` | `079adf7971e346a8da5d40c49bc3c1fdfb2307aaf6ed70df5ed4d9312699c507` | `079adf7971e346a8da5d40c49bc3c1fdfb2307aaf6ed70df5ed4d9312699c507` |
| `apps/web/src/contracts/runtime.ts` | `b3d437e906f81d08af045f5b0f3990662c64676572376d42edddaf109f3dd980` | `b3d437e906f81d08af045f5b0f3990662c64676572376d42edddaf109f3dd980` |
| `apps/web/src/style.css` | `97b8dc6595fc7e972f543aad247feadfc2ddaf7b6439fd6655d217acf08d26ba` | `97b8dc6595fc7e972f543aad247feadfc2ddaf7b6439fd6655d217acf08d26ba` |
| `apps/web/src/styles/v3-research-lane.css` | `d7b56919209d8551d5fb44789db20246d745b63273a42a60d0b34927be7232e8` | `d7b56919209d8551d5fb44789db20246d745b63273a42a60d0b34927be7232e8` |
| `apps/web/src/views/ResearchView.vue` | `cc84ad2e71af8e3c3ce67c31d8eb3e1af10fc7e33018d32ab5b134b9b79f5aca` | `cc84ad2e71af8e3c3ce67c31d8eb3e1af10fc7e33018d32ab5b134b9b79f5aca` |
| `apps/web/src/views/ReviewView.vue` | `cb1f4f19d9b8100d0caf86a5563990a90b627fdb72699b9ccbe499b1e9542c71` | `cb1f4f19d9b8100d0caf86a5563990a90b627fdb72699b9ccbe499b1e9542c71` |
| `apps/web/src/views/TaskStatusView.vue` | `f86f3403f377653ea34568c298048cab96e39a27754f52c6f538ef7fb4cce045` | `f86f3403f377653ea34568c298048cab96e39a27754f52c6f538ef7fb4cce045` |
| `apps/web/src/components/daily-research-command/DailyResearchAlertPanel.vue` | `f682b6cc37c9d2f7236c1a0c4b7ad3ba99fa81d4073efbb08afe07b9b41abf9c` | `f682b6cc37c9d2f7236c1a0c4b7ad3ba99fa81d4073efbb08afe07b9b41abf9c` |
| `apps/web/src/components/daily-research-command/DailyResearchHero.vue` | `c5b47faf17654b89e140358ecab6ceb31868eae79bd7c973f3f3557ad061e185` | `c5b47faf17654b89e140358ecab6ceb31868eae79bd7c973f3f3557ad061e185` |
| `apps/web/src/components/daily-research-command/DailyResearchHourlyDiagnostic.vue` | `99994f2ec38e2b3061b5fdf7d6363d6eaad24805b787cf1822edbab0f106092e` | `99994f2ec38e2b3061b5fdf7d6363d6eaad24805b787cf1822edbab0f106092e` |
| `apps/web/src/components/daily-research-command/DailyResearchLineage.vue` | `94fa1c74db8701a9af734795a0c74579adba03d6ca3cceb262848ab95a5f9422` | `94fa1c74db8701a9af734795a0c74579adba03d6ca3cceb262848ab95a5f9422` |
| `apps/web/src/components/daily-research-command/DailyResearchMetrics.vue` | `71f4f68432a9f8a9b23022aa2aae929954a6aa5100972042f9b4746ae3dcb3f4` | `71f4f68432a9f8a9b23022aa2aae929954a6aa5100972042f9b4746ae3dcb3f4` |
| `apps/web/src/components/daily-research-command/DailyResearchPools.vue` | `b03af7d1ca0f0abfcd6231bb9ba53f4e272349cf740b2bf179bcd0543ebfc395` | `b03af7d1ca0f0abfcd6231bb9ba53f4e272349cf740b2bf179bcd0543ebfc395` |
| `apps/web/src/components/daily-research-command/DailyResearchSlotMatrix.vue` | `ac61c10627dfa1b5cd0269efc22ae50412f681c91db88e8b6d4ae7845e845d57` | `ac61c10627dfa1b5cd0269efc22ae50412f681c91db88e8b6d4ae7845e845d57` |
| `apps/web/src/components/daily-research-command/types.ts` | `7b06a9da0e790083636a13b5994808676713d2ff91eea5e1de11ef8933bf5607` | `7b06a9da0e790083636a13b5994808676713d2ff91eea5e1de11ef8933bf5607` |
| `apps/web/src/contracts/research.ts` | `74324e313f8811822c18b3c65c7f80a6661d3dca8ac5a7f02820139d55bd7bf9` | `74324e313f8811822c18b3c65c7f80a6661d3dca8ac5a7f02820139d55bd7bf9` |
| `apps/web/src/daily-research-command/main.ts` | `b8235092c762fc5cb485b649a6a45a05b434511301ca9f0444515bb04a465385` | `b8235092c762fc5cb485b649a6a45a05b434511301ca9f0444515bb04a465385` |
| `apps/web/src/styles/daily-research-command.css` | `f49ca125c89c8420136260ebe2c911f897863247c3506f6813370c49e02374e7` | `f49ca125c89c8420136260ebe2c911f897863247c3506f6813370c49e02374e7` |
| `apps/web/src/views/DailyResearchCommandView.vue` | `38854e4945c10802596845e2a3f00cbecee628b6e723831b5a3ac9182c95b2b7` | `38854e4945c10802596845e2a3f00cbecee628b6e723831b5a3ac9182c95b2b7` |

The static local import/CSS closure for all three Vite HTML inputs (`apps/web/index.html`, `apps/web/daily-research-command/index.html`, and the existing `apps/web/manager-selection/index.html`) visits 59 source/assets and has 0 missing local dependencies after restoration. The restoration contains no business edits.

## Implementation and verification record

- Baseline: `0a43bc203545b81bfe54135e9c81de2e1ef7212f`; task branch: `codex/us-mapping-e2e-repair-20261019`.
- `SCOPE.json` SHA-256: `51b07af967e802b11f352824fc2836333fba4614123c11095c139f8e116b03d1`.
- Final implementation source/test SHA-256 values:

| Path | SHA-256 |
|---|---|
| `apps/web/src/manager-workbench/Workbench.vue` | `00c0dad5e67d43e2c75b8661e785c2d1be8bb115a0b7fe46f86d34c646f213ec` |
| `apps/web/src/manager-workbench/__tests__/us_mapping_stock_lists.spec.ts` | `2975e0e747da29afdcfe8be2f97c3f7d650e78ee1eeda485152724fe2a2f0eba` |
| `apps/web/src/manager-workbench/api.ts` | `956a6b671ea02e1635096415585989ce1e8efdd6c8d3b718dc45b5ee5630f827` |
| `apps/web/src/manager-workbench/us_mapping_stock_lists.ts` | `cb3934d9b6f9a6804123a089901c55b37a435633fd183758a51e0f5ad2e62c57` |
| `apps/web/src/manager-workbench/useWorkbench.ts` | `31ef076cce59efefbefc12d5b4ec259222705f51fcc2867dddf888eea5992aa7` |
| `tests/manager_workbench/engines/test_us_mapping.py` | `2296d39d4ce162c566b2e7e3364b1e1f35ddf192a028e255cec19d6ef53da13c` |
| `tests/manager_workbench/engines/test_us_mapping_consumption.py` | `4b847099127400e8a536d547d567113ab69e87dbd4e4a4d69e8bf15f7ddfc0b3` |
| `tests/manager_workbench/runtime/test_strict_us_selection.py` | `d90206bc2444e209aecc00ef84f341fd549547f4f5f3bf1fce79adad0885ee92` |
| `v4/manager_workbench/engines/strict_us_selection.py` | `7178bb4f0b19ee2c09c1f1a6d32ac1b7e0f1d7afd980512f44afc238d1615c48` |
| `v4/manager_workbench/engines/us_mapping.py` | `6d98c575e9c03ca58eace87331bb08ec17243738923af9160a8e1eee5eac6ec1` |
| `v4/manager_workbench/engines/us_mapping_consumption.py` | `b29d529697ff76e6a5830bdfef82cd3cb742b9c0a77e4d159d380e526c26316c` |
| `v4/manager_workbench/inputs/source_bindings.py` | `1c080a44370260d75439b06e7747d592192fe919aa68261624062b699b0f8456` |

The restored build configuration SHA-256 values are `apps/web/package.json` `83def8f02a4a690b46017513bb9e984f1ca5746ecea40a02bd31295b271b69a5`, `apps/web/package-lock.json` `3f0b8425f35a7fdeb13cc0e5422b7814b386a6c7559d0e5c6b2f8340bc01be47`, `apps/web/tsconfig.json` `f73fccb15b645e725ff611de1d10f70bebd1b43f17ae50cc72fd57a89f467b2b`, `apps/web/vite.config.ts` `759c67c769f5f2553ec54eee08a1e2ecf958a6323006f0eb9228083b9dfde123`, and `pyproject.toml` `956930fce7721aa3edafaab797c684b3d7e1af89ee0738a16e5f730b1d0308c8`. The added Vite entries are `apps/web/index.html` (`4a03a2c60e2becc71dfa7a4aeb9c7da7ed04e74832b77151cedc2cc9c814594d`) and `apps/web/daily-research-command/index.html` (`a6994e5ce3832cada2ce4b6c4667969d9e33e905b5865c41a9db30217f3bde6e`).

Targeted checks, run in this worktree on 2026-10-19:

| Command | Result |
|---|---|
| `PYTHONPATH=. ./.venv/bin/pytest -q tests/manager_workbench/engines/test_us_mapping_consumption.py tests/manager_workbench/engines/test_us_mapping.py tests/manager_workbench/runtime/test_strict_us_selection.py` | PASS, 49 tests |
| `npm --prefix apps/web run typecheck` | PASS, `APP_TYPECHECK`; manager-workbench app TS/Vue source only |
| From `apps/web`: `./node_modules/.bin/vue-tsc --noEmit --target ES2022 --module ESNext --moduleResolution Bundler --strict --skipLibCheck --types vitest/globals src/manager-workbench/__tests__/us_mapping_stock_lists.spec.ts` | PASS |
| `npm --prefix apps/web run test -- src/manager-workbench/__tests__/us_mapping_stock_lists.spec.ts` | PASS, 6 tests |
| `npm --prefix apps/web run build` | PASS, 3 HTML inputs and 100 modules |
| `git diff --check` | PASS |
| Node `JSON.parse` of `apps/web/package.json`, `apps/web/tsconfig.json`, and `SCOPE.json` | PASS |

The initial broad frontend typecheck was attempted before narrowing the target and failed on errors in restored unrelated App/HK review modules and existing test imports for absent `independent-recommendations-http.local.json` and `real-announcement-http.local.json` fixtures. Those fixtures were not fabricated or restored. The final `APP_TYPECHECK` deliberately covers only manager-workbench application source; the focused changed spec was typechecked and executed separately. Full frontend typecheck and full Vitest suite remain `CANNOT_CONFIRM` / `NOT_RUN` for final scope acceptance.

Local verification artifacts `.venv/`, `apps/web/node_modules/`, `apps/web/dist/`, and generated `__pycache__/` directories remain in the worktree to support independent review; they are not source deliverables. No commit, push, deploy, runtime change, or business-data change was made. This receipt is a writer handoff; independent Reviewer acceptance remains pending.

Verification environment: Python `3.12.14`, pytest `9.1.1` in worktree `.venv`; pydantic `2.14.0` and FastAPI `0.148.0` from the configured bundled Python runtime; Node `v24.19.0`; npm `11.17.0`. These local test/build dependencies are not deployed or included as source deliverables. The npm dependency lock/config was restored from the deployed V4 build as described above.


## Incremental correction after independent review

The first review identified two defects in the actual `run_us_mapping -> run_single_day_mapping` path. Before correction, the new entry regression reproduced both: explicit `EXCLUDED_CURRENT` produced `ADOPTED_BUSINESS_PEER`; a quote retrieved by the `BAD` map key with inner `symbol=WMT` and no `previous_close` produced `quote_status=VERIFIED`. The corrected test uses synthetic inline catalog rows and quote maps; it does not load the fixture below or local raw market JSON.

Disposition now preserves `EXCLUDED_FOR_SPECIFIED_RESEARCH_USE` with `CATALOG_RESEARCH_USE_EXPLICITLY_EXCLUDED`, and the candidate builder independently rejects explicitly excluded `catalog_research_use`. Manual quotes now require normalized inner symbol identity, finite positive `last` and `previous_close`, finite `change_pct`, and agreement with the existing `(last / previous_close - 1) * 100` contract within `0.001` percentage points. Bad quote evidence remains isolated to its relation; the regression proves another valid positive candidate remains.

The candidate-gate unit regression deliberately pairs `catalog_research_use=EXCLUDED_CURRENT` with a stale `ADOPTED_BUSINESS_PEER` disposition and confirms no candidate is emitted, so the use guard is independently exercised.

Input identity correction: `tests/fixtures/issue45/real_relation_projection.json` has SHA-256 `400b7ea8c556205518c72f3653b4afb583ee456283d2a7ef12a08475fdf49230`; it is a read-only identity reference and is not consumed by the changed tests. The former `17ead71366273364ad3057830e626392d856c554120df971f4b1c1d5416b82b9` value belongs to `local_only/actual_full_mapping_r2/lane-response.json`, not that fixture. Audit handoff/crosswalk/dependency-readback files are background references. Regression inputs are synthetic helper-built records and synthetic quote scopes documented in `SCOPE.json`. No original/raw market JSON was copied or committed.

| Delta verification command | Result |
|---|---|
| `PYTHONPATH=. ./.venv/bin/pytest -q tests/manager_workbench/engines/test_us_mapping.py::test_real_us_mapping_entry_quarantines_excluded_use_and_invalid_manual_quotes` | PASS, 1 test |
| `PYTHONPATH=. ./.venv/bin/pytest -q tests/manager_workbench/engines/test_us_mapping_consumption.py tests/manager_workbench/engines/test_us_mapping.py tests/manager_workbench/runtime/test_strict_us_selection.py` | PASS, 51 tests |
| `node -e 'JSON.parse(require("fs").readFileSync("docs/handoffs/us_mapping_e2e_repair_20261019/SCOPE.json","utf8"))'` | PASS |
| `git diff --check` | PASS |

No frontend source changed in this delta. The prior independent review's six Vitest checks, focused Vue typecheck, `APP_TYPECHECK`, and build evidence apply to unchanged frontend inputs; this delta did not rerun them. Full frontend typecheck and full Vitest suite remain `CANNOT_CONFIRM` / `NOT_RUN`. Updated `SCOPE.json` SHA-256: `51b07af967e802b11f352824fc2836333fba4614123c11095c139f8e116b03d1`. Independent re-review of this changed source/test/scope hash is pending; this remains a writer handoff.
