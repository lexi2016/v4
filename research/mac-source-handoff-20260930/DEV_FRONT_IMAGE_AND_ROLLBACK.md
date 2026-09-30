# Development front image and rollback — 2026-09-30

**Use this as the source-selection and preservation contract for the next local development task.** This is packaging guidance, not a build or behavior acceptance receipt. No candidate was built and no business tests were run for this guide.

## Source choice

Use `source/canonical/` as the primary editable source image. It is a byte-frozen copy of the local V4 checkout at `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054` plus its captured working-tree source bytes. The handoff contains 680 source files: 211 tracked-clean, 77 tracked-modified, 93 untracked, and 299 untracked-or-external. Treat the packet copy as immutable evidence; make edits in a newly assembled isolated development tree. GitHub `main` at `615d1ce5417ed65ca2c8b736435c5d4596b79b19` contains only a README and is not an application source image.

Use `source/releases/<owner>/` only as the corresponding owner’s frozen operational reference. The owner identities, launch-selected configuration, manifest pins, disk hashes, and process state are separate in `runtime/runtime_inventory.json`; exact per-file source/release identities are in `source_inventory.json` and `references/github_baseline_comparison.json`. A hash mismatch is a path-specific conflict, not proof that either side should overwrite the other. Do not copy a release tree over canonical source or another owner’s release. The Issue #8 manager scheduler’s 15:55 release is not evidence for the 17:20 owner. Its source/build binding remains `CANNOT_CONFIRM`.

## Files whose captured bytes must be preserved

These are the named Stage Mac-repair and manager Issue #8 work paths. The SHA-256 values identify the canonical handoff bytes; each complete row also records byte count, Git blob SHA-1, and captured status. Preserve the full split-package directories from the inventory, including unlisted neighbors and namespace files.

| Area | Repository-relative path | Captured status | Canonical SHA-256 |
|---|---|---:|---|
| A-auction collector | `stage_center/_live_collectors_parts/a_auction.py` | untracked_or_external | `b74756748e98035d8058447f5f2644aa5709e4739bfe0ee9f365d4f0c7094e2c` |
| A-auction selection | `stage_center/_selection_parts/a_auction.py` | untracked_or_external | `d0a96edcb4d87f223b117917a8f0d68276bd088a88abe8f787d245c8e1c669ad` |
| Fixed TDX minute provider | `infrastructure/tdx_minute_replay_provider.py` | tracked_modified | `8afaea9b97edb790df33dc67b5ef4992b4a0f655a376ca458655509e2c6df9a9` |
| HK replay provider | `infrastructure/hkconnect_stage_replay_provider.py` | tracked_clean | `cbd6704b33963907262af10d1252de18c394fe1c4d6f3ae91746707a1c16b08f` |
| Stage node entry | `ops/_run_stage_center_nodes_parts/node_entry.py` | untracked_or_external | `54defb0f45adbafcf4b661611f41d0b43d89abf492d89d587c28962eff9b36fe` |
| Stage dispatcher, settled-partial recovery | `ops/_run_stage_center_nodes_parts/stage_dispatch.py` | untracked_or_external | `df6221a177d82f0fd683896b3ef21cd66cd7a8a4b6c6c8b95571f277108d52fe` |
| Stage A/HK calendar lanes | `stage_center/calendar.py` | tracked_modified | `31fed97066d9b804a71f15c48d4e0f8baa5d9af621e1d81dc0340fd6619e4099` |
| Stage runner and prior-observation binding | `stage_center/runner.py` | tracked_modified | `648fe7af52df1b4eba31802361f9af2d03decbbebb3286ecc7a5dc0b06523205` |
| HK candidate authority | `stage_center/_runner_parts/hk_candidate_authority.py` | untracked_or_external | `1fd933e8436e4316832c29f89da16c1ccf3ed78b14ee853262ed758e476d2f95` |
| HK late-observation slot execution | `stage_center/_runner_parts/slot_execution.py` | untracked_or_external | `a6584015f7196091f69b25f810b6e83755b86d7ac8ce36891e479a4203b1945c` |
| Stage observation receipt binding | `stage_center/_runner_parts/runner_receipts.py` | untracked_or_external | `3d0d3fcc244d94b2e289e97429cd7863d2272c4151a733fef96920b47c741b0e` |
| Collector/selection construction | `stage_center/_live_collectors_parts/selection_builder_registry.py` | untracked_or_external | `5b315c482723f4bbfb187e36241ea422f2a59518a2056be037d1fdbe2f00eb22` |
| Stage selection | `stage_center/selection.py` | tracked_modified | `ccf7dddfb72fe88b5bff68ce9501e0a8ef9f41a212008a495824017943675294` |
| Stage consumer | `stage_center/consumer.py` | tracked_clean | `9e3a864c74eaec6c616b911b09c167c8cb407db8435343c1b522de4f4c9459eb` |
| Preselection pool store | `infrastructure/preselection_pool_store.py` | tracked_modified | `a640d28ec54119ae383f5dd838fe467d6ae8b5b0d87fa2c4afbb0646fbfe658a` |
| Settled/deadline state | `stage_center/end_to_end_deadline.py` | untracked | `f25d91cf1eaf4ea7d1a9a57fc1f8288d14d98536a63dee16467550974b2a812e` |
| Manager dispatcher | `infrastructure/scheduling/dispatcher.py` | tracked_modified | `64e596ff1c554937c93ac921671a204b889f51acd307c88e1aaa2184daadbc01` |
| Manager capture retry split | `infrastructure/scheduling/manager_capture_retry.py` | untracked | `6054e4e5560bcfac89e4dacda624926dcf59385c2ce3d40786aebab06f55b842` |
| Manager qualification/publish owner | `infrastructure/scheduling/manager_announcement_supervisor.py` | untracked | `fd41e7ae1ba82429fb75364d42e96c435aa5855fb471c4fb55a0d38c962aa22a` |
| Manager qualification reader | `infrastructure/scheduling/_executor_registry_parts/daily_reader.py` | untracked_or_external | `cb2259407fe86356e7e1528dea417559c355e0fcc9bc17a9ad2193a2650fbaa7` |
| Manager close capture/diagnostic path | `infrastructure/scheduling/manager_close_executor.py` | untracked | `ddb39500c3a426b259b14c1a6bada16b4734c738c9715ac969469368305c26d3` |
| Saved-plan qualification | `v4/manager_research/workspace_plan.py` | untracked | `96e8e8b7763f932cf353316acbfb45991b79fe00f1a7ca007659ebb76c728f4c` |
| Saved-plan identity/history | `v4/manager_research/workspace_history.py` | untracked | `44d4506bb12b4fe875ce6ce359d265c1221c153f0c89f035acd6dbf84430bb2b` |
| Saved-plan owner dispatch | `v4/manager_research/plan_owner_dispatch.py` | untracked | `1c71301b9f49f387ceb8e6243fb645adc72bfea11fa6cfea7f25aeb9d2a2db20` |
| Saved-plan autorun | `v4/manager_research/workspace_plan_autorun.py` | untracked | `e785ae1d465175bec0517e7c3b4a8d6e16593967cba554aa0428817a85cd079b` |
| Manager source reader | `v4/manager_research/reader_source.py` | tracked_clean | `41d1abd481f043ad4309c39c04f179e3b9f2f0c511f89b32c3d4554bd7ac42f4` |
| Manager workbench API/diagnostics | `apps/api/v35_api/manager_workbench_router.py` | untracked | `d202bace0da2fec3e59977240af31a52026e18639b6b08878ebbbd60d52fe88b` |
| Manager research API | `apps/api/v35_api/manager_research_router.py` | tracked_modified | `d66b0a4184d6490f92eccf6996446f872adef7289b5821aeecc35338145f4410` |
| Manager cycle entry | `ops/run_manager_announcement_cycle.py` | untracked | `56e9d6d73f48443d4502278f8a00b82faa7974031d75fb4ca6198aa62f627ff8` |

The most consequential disk conflicts are already explicit in the inventory: canonical TDX provider `8afaea…` differs from stage scheduler `02d750…`, HK deadline `5561d4…`, and both manager releases `4bb95a…`; canonical `stage_dispatch.py` `df6221…` differs from stage scheduler `dcb478…` while matching the HK-deadline disk file; canonical manager `dispatcher.py` `64e596…` differs from the Stage/API release `7e61cb…` and manager 15:55 release `a93d78…`. The manager 17:20 `manager_capture_retry.py` and split qualification/reader paths are missing from the 15:55 package. Compare complete 64-character values and owner rows in `source_inventory.json`; abbreviated values here are only navigation aids. Never resolve one of these mismatches by copying the release over the canonical snapshot.

The eight build-time sources added to this revision are also hash-pinned in `development_build_tool_inventory` and `canonical_source_rows`: `ops/build_release_candidate.py`, `ops/build_release_candidate_stage.py`, `ops/release_candidate_sources.py`, `ops/release_candidate_audit.py`, `ops/release_candidate_ports.py`, `ops/prepare_api_only_cutover.py`, `ops/stage_service_overlay_contract.py`, and `ops/verify_source_release.py`. The main builder, cutover helper, and source verifier are present in the Stage scheduler, Stage HK-deadline, and manager API disk releases with manifest matches; they are absent from manager 15:55. The extracted Stage helper and release refactor modules are absent from all four configured application releases. They remain build-time source; no release bytes were changed.

## Preserve remote patches as references

Keep issue patches at their captured commits and compare by exact file identity before applying any behavior to the new local candidate. A path whose blob differs from the canonical SHA is a three-way review conflict; do not blindly cherry-pick, replace, or call it integrated.

- Stage Issue #11 PR12 is commit `cb33d2fe2241079f46ae5e09e605f11a2fd5462f`, against base `3d03ca4ade08ac4c5f3f049756997d3934c782e3`. Its changed paths are `ops/_run_stage_center_nodes_parts/node_entry.py`, `ops/_run_stage_center_nodes_parts/stage_dispatch.py`, and `tests/test_manager_stage_rearm_rework.py`. The PR12 Git blob SHA-1 values for the first two are `a2748870d1caa98c41c362ce9c3dc19adc4195b1` and `d2dc607ae3344d591561b874748bf692d7e6eb06`; canonical currently matches the base blobs `6daf7bee2118d71e15a4d2da0c3dca288863ad5c` and `6b0ab0656a0f878c6732ad900513410abe4f2862`. Preserve the canonical Stage Mac bytes and the remote patch independently until a path-by-path decision is made.
- Stage Issue #10 PR13 is commit `8af24212ecdbdd4105a44ac536f8b469b5ad9660`. The captured issue review classifies its changed README/inspection script/test as diagnostic-only; PR13 leaves the Stage dispatch/node-entry files at the common-base blobs and does not establish HK observation-pool integration. Keep its diagnostic evidence without treating it as a product fix.
- Manager R9 source/evidence is commit `4c1e2de72ef8a026aa5229caca6e4a5e98b17e36`; the R3 preflight fix and prior local preflight artifacts are `a6ade9d919608a1954bbdf367bf16302465808cc` and `852708f6f210f3e7e9abcc065d7826815c8f39f2`. Keep baseline and candidate trees separate. The remote `v4/manager_research/connect_selection.py` candidate has no canonical or configured-release identity here. R3 offline source-binding checks do not establish the 17:20 runtime owner.

All remote path/blob records and available local matches are in `references/github_baselines.json` and `references/github_baseline_comparison.json`. A missing local identity is not a match. The safest forward-alignment route is a new isolated candidate based on the frozen canonical image, with the exact accepted patch behavior reviewed against these refs and the local Mac-repair SHA list above. Do not rewrite the canonical handoff to make its history appear to bind to a release.

## Assemble an isolated editing/test tree

Use only the rows whose `copied` value is `true`; the matching source path and destination-relative path are explicit in `source_inventory.json`. Choose a new empty absolute destination outside every source and release root. Preserve each repository-relative path exactly:

1. `source/canonical/<row.path>` → `<dev-tree>/<row.path>` for `canonical_source_rows`.
2. `source/tests/<row.path>` → `<dev-tree>/<row.path>` for `test_source_rows`.
3. `source/test_dependencies/<row.path>` → `<dev-tree>/<row.path>` for copied `test_dependency_rows` and `test_import_source_rows`.
4. Before writing, verify the listed SHA-256. If two rows name the same destination, proceed only when their SHA-256 values match. Abort on a hash mismatch, absolute path, `..` segment, symlink, or any pre-existing destination file. Verify each destination hash after copying.
5. Do not copy anything from `non_replayable_test_inputs`; those rows are metadata-only exclusions. The assembled tree has no `.git` metadata and is for direct editing and available tests only.

For an actual inactive release candidate in a later authorized task, the existing builder requires a Git source tree and refuses an existing candidate root. Use a **separate new Git worktree pinned to the captured HEAD**, overlay the verified handoff paths with the same conflict checks, and stop if a required `untracked_or_external` dependency cannot be represented by the builder’s explicit include rules. Its actual CLI is in the included `ops/build_release_candidate.py` source:

```text
python3 -B ops/build_release_candidate.py \
  --source-root <isolated-git-worktree> \
  --candidate-root <new-nonexistent-inactive-candidate-root> \
  --api-plist <reviewed-api-plist> \
  --scheduler-plist <reviewed-scheduler-plist> \
  --release-id <reviewed-unique-id> \
  --receipt-path <new-receipt-outside-source-and-formal-release-roots>
```

`--include-untracked-path <repository-relative-path>` may be repeated for explicit, current, non-ignored untracked files. The builder reads Git tracked/untracked status; it does not silently include ignored/external rows. For a Stage-only candidate, use the same script with `--stage-service-candidate --stage-plist <reviewed-stage-plist>` and, only after reviewing the included overlay contract, repeat `--stage-overlay-path <allowed-relative-path>`. The combined and Stage-only modes, candidate-root guard, and receipt rules were read statically; neither command was run. The builder creates an inactive candidate and does not activate a service. Its staged `apps/web/dist` input is not included in this source packet; use the existing `apps/web/package.json` and lockfile only in the isolated tree if a future candidate requires that build output.

After a candidate exists, the included `ops/verify_source_release.py` accepts `--source-root`, `--release-root`, and an optional external `--receipt` path. Run it only in that future, authorized candidate task and preserve its receipt with the exact candidate identity. Passing the packaging checks here does not prove an active service loaded those bytes.

## Rollback and stop conditions

- Keep this handoff and its manifest immutable. If a source edit fails review or tests, discard only that task’s isolated editing tree and reassemble it from these hashes. Do not reset or clean the shared checkout and do not restore from `HEAD`, which would erase the captured local Mac repairs.
- Candidate roots are create-once. On an error, retain the incomplete marker/receipt for inspection and use a different new path for a later build; never overwrite or reuse that root.
- This handoff changes no active release, manifest, plist, service, or data. A future inactive candidate remains unactivated on failure. Any later activation/rollback requires its own authorization and exact owner-specific prior manifest/plist pins. The manager 17:20 owner has no confirmed prior binding; the 15:55 release is not its rollback target.
- Stop on any canonical/release SHA conflict, missing required source dependency, source-to-build-history claim without a receipt, or uncertainty about which manager owner consumes the candidate. Keep target-day qualification, API/UI behavior, loaded Python bytes, and natural-run results as `CANNOT_CONFIRM` until independently evidenced.
- Preserve research-only safety: `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.

## Historical test fixtures intentionally not copied

These ten files are listed in `source_inventory.json` with `content_copied=false`; this table contains only path, byte count, and hashes. Fixture-backed cases are not replayable from this packet. No raw quote, minute, pool, or pre-open screen rows were copied.

| Relative path | Bytes | SHA-256 | Dependent test(s) / reason |
|---|---:|---|---|
| `tests/fixtures/stage_0925_20260730_tdxpy_input.json` | 127800 | `d447078fee592a9dd741dddc16bd637ed02d2043b91c6648fab15aca3c6b284c` | `test_stage_0925_frozen_regression.py`, `test_stage_0925_vertical_parity.py`, `test_stage_eight_runs.py`; frozen raw Stage input rows excluded. |
| `tests/fixtures/stage_0925_20260730_tdxpy_provider_snapshot.json` | 79100 | `91f0eedfaf07e662b985b15e9ee3b9cdb5fea34bc793a31529611f5ced2e3793` | `test_stage_0925_vertical_parity.py`, `test_stage_eight_runs.py`; frozen raw provider rows excluded. |
| `tests/fixtures/hkconnect_stage_replay/manifest.json` | 1038 | `0c5e2467f0ed32e0267a4c4d1e5cadb502856d890b80f0567a9068e6968dc74e` | `tests/test_hkconnect_stage_replay_provider.py`; manifest without its rows cannot replay the HK fixture-backed cases. |
| `tests/fixtures/hkconnect_stage_replay/20260730/STAGE_0930_0935/hkconnect_rtdata_stage_replay_20260730_STAGE_0930_0935.csv` | 29385 | `83b0cb0ca85a31ca974f42b9d0dc3540ba8cf84989e624a1465645a3769fbd66` | Same test module; historical HK replay rows excluded. |
| `tests/fixtures/hkconnect_stage_replay/20260730/STAGE_1300_1315/hkconnect_rtdata_stage_replay_20260730_STAGE_1300_1315.csv` | 1606 | `e35c4a8d756ff3432d01ba79705cefe530c8ecfecebb478d02df22bafce323f4` | Same test module; historical HK replay rows excluded. |
| `tests/fixtures/hkconnect_stage_replay/20260730/STAGE_1445_1500/hkconnect_rtdata_stage_replay_20260730_STAGE_1445_1500.csv` | 41292 | `8923320d6b224fea1d2a13da462c2c37a05359f4438d873766119bd134c0458a` | Same test module; historical HK replay rows excluded. |
| `tests/fixtures/preselection_optional_pools/manifest.json` | 6361 | `3773b76be8bb934eb696ec2293a430b703b529fd21e8ce90bafabef232e7de46` | `tests/test_preselection_optional_pools.py::test_stage_input_uses_frozen_base259_only_and_excludes_overlay43`; manifest without the frozen pool payloads is insufficient. |
| `tests/fixtures/preselection_optional_pools/base_20260730.json` | 401933 | `2dcad50851265ba3f93bf1a0f18f6ad70f8ed544d7f3e9e5bb9df87593d008ca` | Same test; historical base-pool rows excluded. |
| `tests/fixtures/preselection_optional_pools/overlay_20260730.json` | 51185 | `14065b23bb04d8e8a9fd9050798cd5aa503906b1687ace8b18103f4a06952fa5` | Same test; historical overlay-pool rows excluded. |
| `tests/fixtures/manager_20260924_preopen_screen.json` | 2575054 | `efbeb63690b81cdc4d2e6317ca74a1273ce660e53e916b05cda92b09afbdc8a6` | `test_real_preopen_screen_is_not_mutated_and_top5_remain_near`, `test_cutoff_bound_official_event_can_raise_a_near_name_without_changing_screen_rank`, `test_after_cutoff_duplicate_does_not_shadow_pre_cutoff_copy`; historical screen rows excluded. |

Tests other than the listed fixture-backed cases may use synthetic inputs and remain separate. No business test was executed for the handoff or this guide.
