# R2 Mac blockers handoff

Frozen delivery: `lexi2016/v4`, commit `7a9c94d43a296372488541b02e8e35a0f763dc1a`, branch `handoff/stage-research-recovery-20261009-r2`. The complete 328-file package is under `incoming/stage-research-recovery-20261009-r2`; all Git blob object SHAs matched (328/328), and `tools/verify_package.py` returned PASS (21 mapped files, 166 offline support files). Copied `SOURCE_MAP.json` is this directory; SHA-256 `f402f93009ff1e8ef588e04c994eec1897274d80970fc20ee07748a506156ce4`.

## Local prepare results

Raw tool receipts are preserved under `evidence/`: `stage_prepare.json`, `api_prepare.json`, and `ui_prepare.json`. All three were run once with the fixed package's `tools/prepare_canary.py`. No helper was changed and no actual or canonical source was edited.

- **Stage:** `PREFLIGHT_FAILED`, `write_performed=false`. All 16 mapped files were `BEFORE_MATCH`; all 21 packaged after files were `AFTER_SHA_MATCH`. The tool rejected two source-tree symlinks:
  - `app/v3_shared_data` link text `upstreams/v3_shared_data`; target exists inside the Stage root. The read-only tick config's `shared_data_root` points at that target, so it is a configured shared-data dependency.
  - `app/upstreams/v3.5` link text `/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260818T140000Z-v35-stage-input-owner/app/upstreams/v3.5`; target exists outside the Stage root. Whether this legacy target is required by the current Stage run is `CANNOT_CONFIRM`; its contents were not read.
  - The exact helper errors were `SOURCE_TREE_SYMLINK:/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app/v3_shared_data` and `SOURCE_TREE_SYMLINK:/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app/upstreams/v3.5`.
- **API:** `COPY_FAILED`, `write_performed=true`. Both mapped files were `BEFORE_MATCH`; all package after files matched. The source API app and `stage_center` directories are owned by `lexi:staff`, mode `0555`; both mapped files are mode `0444`. Copying preserved these modes on the destination. Replacement then failed creating `/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R2_MAC_20261009/candidate/mac_apply_20261009_7a9c94d4/api_app/stage_center/tmp0pz8q150`: `[Errno 13] Permission denied`. The temp path does not exist; its parent `/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R2_MAC_20261009/candidate/mac_apply_20261009_7a9c94d4/api_app/stage_center` is owned by `lexi:staff`, mode `0555`. The partial isolated copy remains at `candidate/mac_apply_20261009_7a9c94d4/api_app`; do not treat it as a prepared API candidate.
- **UI:** `PREFLIGHT_FAILED`, `write_performed=false`. The canonical source tree remains untouched. Actual mapped files do not match an accepted before/R1 SHA, and one mapped file is absent:
  - `apps/web/src/App.vue`: current 27,412 bytes, SHA-256 `ffbfcde222175c7849dfd5a1089cafe6c104dea2a1760b18645d95bc48780530`; accepted `995a680995cc42feadeaa8d2bdd44294c8ec782a908d664c698faf69d4cf02a1` or `e13a92e7f990ef18de0909edf0d2644410ba55194b21b583d43b76d648801dc5`.
  - `apps/web/src/components/review/StageExecutionEvidencePanel.vue`: missing.
  - `apps/web/src/contracts/runtime.ts`: current 1,540 bytes, SHA-256 `6d66ae53d26a6c48110d040ad0440bb023e88d49924a697d6671c6da51176d92`; accepted `9a882a174b433488684b05781ade00beb665706e962f753700960a4250d13419` or `c440de3ff964daa01994cbcd04d9b3ce1f417737a39034520c478ef83448bebe`.
  - The dirty tree also contains symlinks, including `v3_shared_data` and pytest temporary links. The complete rejection list is preserved in `evidence/ui_prepare.json`.

Full current `App.vue` and `runtime.ts` byte copies are in `ui_actual/apps/web/src/`; both hashes above are the copy source hashes. A narrow credential-pattern scan found no private-key, GitHub token, OpenAI key, Slack token, or AWS access-key formats in these two files. The missing panel is recorded in `local_observations.json`.

## Unblocked checks

`tools/run_checks.py` completed on macOS 26.6.2 arm64 with the LaunchAgent's lexical Python path (Python 3.14.6) and Node 24.19.0:

- Stage: 148 passed
- API: 82 passed
- Vue: 45 passed, 0 skipped
- Synthetic full-chain fixture API and Vue reads: both exit 0

The command used the package's offline `test_support/stage_base_app` because actual Stage preparation failed; it did not load the actual Stage root. Results and logs are under `candidate/mac_apply_20261009_7a9c94d4/independent_checks/`. The report scope is `ISOLATED_SOURCE_FIXTURE_TESTS_NOT_MAC_MARKET_API_DEPLOYMENT_OR_NATURAL_ACCEPTANCE`.

## Not run / CANNOT_CONFIRM

The real HK PyTDX canary and real same-run consumer readback were not run because the exact Stage preparation gate failed. API/UI actual-copy preparation also failed as above. No price data, HK raw market files, state, full plist, or credentials are included here. No service, scheduler, or formal state was changed. Safety flags remain `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.

The next code adaptation belongs to Chat under the frozen division of work. Do not weaken or bypass the package preimage/symlink guard locally.

