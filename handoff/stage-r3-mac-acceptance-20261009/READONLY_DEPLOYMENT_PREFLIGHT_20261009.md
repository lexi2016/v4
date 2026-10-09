# R3 read-only deployment preflight and existing-command plan

Date: 2026-10-09 (Asia/Shanghai)

## Result

`READONLY_DEPLOYMENT_PREFLIGHT=BLOCKED_PREIMAGE_AND_ROOT_BINDING`.

This phase prepared only preflight evidence. It did not create an integrated release candidate, change production state, or switch/reload the service. The existing R3 API reader files match the current Issue32 source. The three R3 UI preimages do not match the UI source in the current Issue32 release. The current API also has no approved binding for the R3 backfill run, and its configured reader accepts one selection root at a time. The frozen release guard does not own the R3 API or static asset paths.

Previously accepted R3 evidence was reused, not rerun:

- Local receipt: `handoff/R3_LOCAL_INTEGRATION_RECEIPT_20261009.md`, SHA-256 `232fe0f46fcba3323da33604d04618adb97a7840733c4b177046c176cae88642`.
- Isolated HTTP/UI evidence: `evidence/r3_http_20261009/http_ui_verification.json`, SHA-256 `cf9b1ba2a277f4a55025bc05cbc82860d87825a2a96fa3162cf0ff7d143f74b5`.
- Independent Reviewer receipt: `evidence/review/independent_actual_ui_same_run_20261009.json`, SHA-256 `4178978125ed28dc802e7ef1ea8972252c94c11cfed8839cc50c5d577c621050`; previously reported `REVIEWED / TESTED / BEHAVIOR_VERIFIED PASS` for the isolated candidate.
- Real canary: `candidate/mac_apply_20261009_r3_01/research_0935/run_manifest.json`, SHA-256 `9b5df949141ed1533cb7a71e2c46bebe341bea663f5f966bda16225754e89857`; trade date `20261009`, stage `STAGE_0930_0935`, backfill namespace `85e29661ecd848fe9b8344ea59279e86`, HK selection run `run-cfbdc9b36a7308da178d193a`. This remains research-only, with `production_allowed`, `buy_gate_updated`, and `orders_sent` false.

Those receipts establish the isolated R3 candidate behavior. They do not establish that the current 8873 release can serve the run or preserve its existing Stage history after a release switch.

## Current loaded identity and source preflight

The last read-only service identity for this phase is PID `78617`, listening at `127.0.0.1:8873`, running from:

`/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app`

Its command includes `--stage-selection-root /Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection`. The parent confirmed this PID had not changed before this phase. The Issue32 release manifest is one directory above the app root and has SHA-256 `16675f6016d40e8a5eaf7b1e3e37694228364fae544e8a7b73e4bf17e1f5a9e6`. The loaded `apps/api/v35_api/app.py` SHA-256 is `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5`.

Read-only launch-agent file identities: `/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist` SHA-256 `c88e4069f6deb467a204b4510824e62b15cb8fc11dfa7892a43e5ec8eaed8ec4`; `/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist` SHA-256 `b9e9e8361e9ce6eaca58df0688fcd214bf35bdc702f5febe405d07c6ceb05754`. Neither file was changed.

R3 `SOURCE_MAP.json` SHA-256 is `3ec3e7774119bd106185c03be0b5c572b6fe2ca4148b93379d8b116a72994457`. I ran the package's existing `tools/prepare_canary.py --inspect-only` against the current Issue32 app root. The full machine receipts are:

- `evidence/deployment_preflight/api_inspect_only.json`, SHA-256 `05854adf4a014e1358bfa7c19c4daaf179415a00d6968ce4e0b902d7a7b9d1b9`: `PREFLIGHT_OK`; `stage_center/execution_evidence.py` observed SHA `e4c4ea94d892158383620beab1825014f21e926b57907354475f8c9ff382704b` and `stage_center/consumer.py` observed SHA `61f8a3541aa7a2e698cc4374385e3d20d41b40ffd5a3cd7d87c9494cb8726cf4`; both are accepted R3 before images.
- `evidence/deployment_preflight/ui_inspect_only.json`, SHA-256 `e0d3aa6be2965b006bbfa36df404c358b14163910880a327c942faeef78d464b`: `PREFLIGHT_FAILED`, with three source SHA mismatches and no tool errors:

| R3 UI path | Current Issue32 app SHA | R3 accepted before | R3 operation / after SHA |
| --- | --- | --- | --- |
| `apps/web/src/App.vue` | `f43bdb2c7214bce09221757eecb75eea9d5e1c746a3213bb53e6d0c84b751d9c` | `ffbfcde222175c7849dfd5a1089cafe6c104dea2a1760b18645d95bc48780530` | modify / `9eda6f27950eea3e2377335a79420fe43b16ca62ad32c87e701f9dda69f6c15d` |
| `apps/web/src/components/review/StageExecutionEvidencePanel.vue` | `07188178bbcd5ae2b01b9d6c1ef9dffd7b94f1b27f0211501cc2464566c5bc8b` | absent (accepted list empty) | add / `eca21b9d5674e3a18b09672c43401164ca356fd84fd6c719c14453c006f0ee5d` |
| `apps/web/src/contracts/runtime.ts` | `9a882a174b433488684b05781ade00beb665706e962f753700960a4250d13419` | `6d66ae53d26a6c48110d040ad0440bb023e88d49924a697d6671c6da51176d92` | modify / `ff6ee3eadd8d9a20668bcb91b94d828d366c71e438b2358062140d4d2da173ba` |

The existing panel path is already present with different bytes although R3 marks it as an addition. Applying the R3 `App.vue` or panel bytes by bypassing the guard would overwrite current Issue32 UI behavior. No such write was made. The original R3 UI manifest was prepared from canonical `/Users/lexi/Desktop/学习/v4_app`, not from the loaded Issue32 release.

The API-only source candidate from the previous phase already uses the live Issue32 app as its source: `candidate/mac_apply_20261009_r3_01/api_app/CANARY_SOURCE_MANIFEST.json` SHA-256 `6c5b8adfe6f74d727e976eb08b0f00c18476938906193973cd8666c55b1aed74`; its source-tree SHA is `60fe706b851a921562d1e73ce51dc02fded1d1d8d1bc474da497a8c840e45323`, and candidate-tree SHA is `4e84be7e01b2c0bb1613ed1efab0787a1428271ad112a0485d778b193ce71b0a`. It remains an isolated canary source copy, not an integrated release.

For context, the earlier isolated UI build used the R3 candidate and its own static bundle. The prior comparison recorded current Issue32 static tree SHA-256 `43e67de78174cd2c7c958f391fa603187f01af034e468eaef6adef9f7f2aa546` versus canonical `apps/web/dist` tree SHA-256 `028add04f0d78488d7c86a7b1980bac4a39675313bca0df169b36d91321e8178`, with four differing entry/manager-selection files. The current dist was not rebuilt or replaced.

## Existing API read contract and the R3 run

The current route is `GET /api/v3/workbench/stage` in `apps/api/v35_api/app.py`.

- A normal date/stage read uses the single configured `stage_selection_root` and `StageSelectionConsumer.get(...)`. `SelectionStore` reads its `selection_runs/` and `selection_latest.json` beneath that root.
- A backfill read requires `market` and `backfill_run_id` together. The route first looks up the exact tuple `(date, stage, market, backfill_run_id)` in `_APPROVED_EXACT_STAGE_BACKFILLS`, then resolves `<configured_selection_root>/backfill/<backfill_run_id>` and verifies the selected run, manifest, artifact, receipts, and safety fields.
- The current API source contains neither R3 identifier `85e29661ecd848fe9b8344ea59279e86` nor HK selection run `run-cfbdc9b36a7308da178d193a`. R3's API source map modifies only `stage_center/execution_evidence.py` and `stage_center/consumer.py`; it does not add a binding in `apps/api/v35_api/app.py`. The exact current route therefore has no approved request for this run.
- The configured 8873 root currently has `selection_latest.json`, `backfill/`, and 19 `selection_runs/` date directories. The R3 output is under `candidate/mac_apply_20261009_r3_01/research_0935/selection/backfill/85e29661ecd848fe9b8344ea59279e86`; that separate root has `backfill/` but no `selection_runs/` history.

Keeping the current 8873 root leaves the R3 namespace unavailable there. Repointing the API to the R3 root makes the canary namespace addressable by path but leaves the existing 19 date directories outside the configured root. The current route has no multi-root overlay, and its path resolver rejects symlink namespaces. Copying or relocating the canary artifacts into the live state root is outside this task. Thus the current release has no proven way to read this R3 run while retaining the existing date/stage results.

## Existing release tools and exact gaps

The reusable guard `/Users/lexi/Desktop/学习/agents调试/V4_ISSUE30_MAC_20261008/package/after/ops/api_release_integration.py` has the task-specified SHA-256 `1f4afc70d7e5920b67c2b148def6b9167819664c33c92b475d919a097b9dd050`. Its parameterized interfaces are:

- `build_integrated_app(*, active_api_plist_path, source_root, candidate_root, delta_receipt_path, explicit_untracked_paths=(), source_path_allowlist=None)`
- `verify_api_release_candidate(*, candidate_root, active_api_plist_path, expected_manifest_sha256=None, active_pointer="base", lock_lease=None, require_shared_lock=False)`
- `module_scope(module, shared_paths=())`

The existing policy has only `preselection`, `manager`, `research_review`, and `api_platform` modules; its `POLICY_SHA256` is `c55f4f09269661e0db05fa566aa1be9a96b2aa681912223c38fb802c4127e1b6`. Read-only calls against that policy reject `module="stage"` as `API_RELEASE_MODULE_UNKNOWN`, reject R3 `stage_center/execution_evidence.py` as `API_RELEASE_MODULE_PATH_NOT_OWNED`, and reject `apps/web/dist/assets/main.js` as `API_RELEASE_MODULE_PATH_NOT_OWNED`. The adjacent existing wrappers are `create_api_module_delta.py` (SHA-256 `04e67a3ce948eecf9dac04083277bd919c7ec8880ec5814bbe57e7a5ba8d0072`) and `build_release_candidate.py` (SHA-256 `81f4290a6f51e5958048d782c2d4b1eecfc42f892e387e6c1a22bb71912abef6`). They require a reviewed change set/delta receipt and preserve the current active app outside declared deltas; they do not make unowned R3 paths eligible.

The current Issue32 cutover script `/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/tools/api_only_cutover_issue32_r4.py` SHA-256 is `864a07b9bdf915a14b877eac89ddc931bb0f4976b70599c242671ff177e9cf25`. Its release root, API inventory SHA, static tree SHA, plan, and manifest checks are fixed to the Issue32 candidate. It is not an R3 release command and must remain unchanged.

## Exact handoff requirements for Chat

1. Rebase the three R3 UI files against the current Issue32 source preimages listed above. In particular, the panel path exists with SHA `07188178bbcd5ae2b01b9d6c1ef9dffd7b94f1b27f0211501cc2464566c5bc8b`, so R3 must not treat it as an absent add. Preserve the current `App.vue` and manager behavior, then provide a reviewed `SOURCE_MAP.json`/after set that passes the original `tools/prepare_canary.py --inspect-only` from the Issue32 app root.
2. Identify an existing route/binding and data-root arrangement for the R3 namespace `85e29661ecd848fe9b8344ea59279e86` that preserves the current `selection_runs` history. The present route uses an exact in-source binding and a single root. The exact `apps/api/v35_api/app.py` before SHA is `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5`; the R3 API map does not include this file. Do not satisfy the gap by copying canary artifacts into live state or by repointing the sole root to the isolated candidate.
3. Supply an existing reviewed integration path that accepts `stage_center/execution_evidence.py`, `stage_center/consumer.py`, and the required generated static assets while preserving the active Issue32 app. The specified Issue30 guard SHA and policy rejection are above; do not substitute an unreviewed module-isolation variant or edit the frozen Issue32 cutover constants.
4. If the existing code/tool contracts cannot meet these requirements, return the exact supported source preimages and a proposed review scope to the parent for a separate decision. This local phase did not create an adapter or business/release logic.

## Existing-command plan and stop point

The only source-preflight commands run in this phase were these read-only calls (the Xcode Python path is the recorded `sys.executable`):

```sh
/Applications/Xcode.app/Contents/Developer/usr/bin/python3 /Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/incoming/stage-r2-mac-adaptation-20261009-r3/tools/prepare_canary.py --package /Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/incoming/stage-r2-mac-adaptation-20261009-r3 --group api --source-root /Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app --inspect-only
/Applications/Xcode.app/Contents/Developer/usr/bin/python3 /Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/incoming/stage-r2-mac-adaptation-20261009-r3/tools/prepare_canary.py --package /Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/incoming/stage-r2-mac-adaptation-20261009-r3 --group ui --source-root /Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app --inspect-only
```

API preflight passed; UI preflight failed on the three exact SHA mismatches above. No `--destination` was supplied.

The existing candidate-only sequence, once a reviewed R3 change set has exact current before images and an approved root-preservation contract, is:

```sh
API_PLIST='/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist'
SCHEDULER_PLIST='/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist'
PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
AFTER_ROOT='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/source_staging/r3_after'
CHANGE_SET='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/source_staging/r3-change-set.json'
SOURCE_ROOT='/path/to/reviewed-git-source-root-containing-the-exact-R3-delta'

python3 /Users/lexi/Desktop/学习/agents调试/V4_ISSUE30_MAC_20261008/package/after/ops/create_api_module_delta.py \
  --active-api-plist "$API_PLIST" \
  --after-root "$AFTER_ROOT" \
  --change-set "$CHANGE_SET" \
  --output /Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/release_candidate/r3-api-delta.json

python3 /Users/lexi/Desktop/学习/agents调试/V4_ISSUE30_MAC_20261008/package/after/ops/build_release_candidate.py \
  --source-root "$SOURCE_ROOT" \
  --candidate-root /Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/release_candidate/r3 \
  --api-plist "$API_PLIST" \
  --scheduler-plist "$SCHEDULER_PLIST" \
  --python "$PYTHON" \
  --release-id r3-prepared-20261009 \
  --api-integration-delta-receipt /Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/release_candidate/r3-api-delta.json \
  --receipt-path /Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/deployment_plan/r3-build-receipt.json
```

The actual Issue32 app root is not a Git checkout: `git -C /Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app rev-parse --show-toplevel` returned `fatal: not a git repository (or any of the parent directories): .git`. The existing full candidate builder reads Git tracked/untracked paths from `--source-root`, so that active app root cannot serve as its source root. The builder also expects a Git source tree carrying the reviewed delta bytes; no such integrated R3 workspace/change set exists under the allowed paths.

This is a candidate-building template only; it is not runnable against the current R3 package because its UI preimages fail, the frozen release policy rejects the R3 API/UI paths, and the loaded app root is not a Git source tree. `SOURCE_ROOT` and the two staged inputs are intentionally unresolved inputs, not claimed ready paths. No cutover command is supplied: the only identified cutover script is frozen to Issue32, and the one-root API storage contract is unresolved. Do not run these candidate commands until Chat supplies the exact rebased files/change set plus an already-reviewed existing mechanism for the path ownership and selection-root/binding requirements. Do not change the guard policy or add a release adapter in this task.

## State and remaining evidence

- `IMPLEMENTED`: this read-only preflight and command-plan document only.
- `TESTED`: no tests rerun by design; reused the accepted prior 352-check result and isolated 24-assertion HTTP/UI receipt above. This phase's `prepare_canary.py --inspect-only` results are `api=PREFLIGHT_OK`, `ui=PREFLIGHT_FAILED`.
- `INTEGRATED` / `DEPLOYED` / 8873 `API_VERIFIED` / 8873 `UI_VERIFIED`: not performed.
- `CANNOT_CONFIRM`: an R3 API call path on the current 8873 release, a storage-root arrangement preserving historical date/stage reads, and a release guard scope for the R3 paths.
- No service, plist, canonical source, live state, static dist, scheduler, or production setting was written by this phase.

## Key read-only inspection commands

```sh
sed -n '3738,3785p' '/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app/apps/api/v35_api/app.py'
sed -n '4730,4920p' '/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app/apps/api/v35_api/app.py'
sed -n '1760,1835p' '/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app/stage_center/selection.py'
sed -n '2045,2070p' '/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app/stage_center/selection.py'
rg -n '_APPROVED_EXACT_STAGE_BACKFILLS|85e29661ecd848fe9b8344ea59279e86|run-cfbdc9b36a7308da178d193a' '/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app/apps/api/v35_api/app.py'
```

The helper interface/policy checks were in-memory reads of the exact Issue30 `api_release_integration.py`; they did not write a delta receipt or release candidate.
