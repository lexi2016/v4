# Futu R4 canonical source integration writer receipt

Status: `IMPLEMENTED` and writer-tested; independent Reviewer acceptance is pending.

Frozen packet: `/Users/lexi/Desktop/学习/agents调试/V4_AFTERNOON_AUTO_STAGES_20261012/futu/recovery_r4`
Packet manifest SHA256: `8d79ddc00fc6accd17fb2d330bc207867aebc4f82afca8c0998ce3e2b3c792bd`
Source manifest: `source_integration/SOURCE_MANIFEST.json` (SHA256 `e66e85932160fa8f35cb5d142b09cb6809813edc3a97b4adf2e9ad5eebc85412`)

The canonical V4 implementation covers the five Futu R4 source files and their focused test from the first increment. This increment restores only the independently reviewed HK projection behavior to `apps/api/v35_api/app.py`, confined to `_hk_display_mode` and `project_shared_selection`. Valid `OBSERVATION_UNVERIFIED` rows retain their visible count and `PARTIAL_WITH_ROWS` status with `NO_BUY`; rows lacking valid identity or status are hidden from HK display, unified rows, and `selection_markets`. Existing canonical HKEX and other adjacent fields remain intact.

The API file was snapshotted before modification at `source_integration/api_delta/canonical_app_before.py`, SHA256 `40fbefd92acc8d0a1037dd25e95ffad3592caf86c4e16e47120d54b7ade9ad67`. Final API SHA256 is `d6632563997987f7b98519709c6111ee8fc114bed69711bdb768b31c7fd732a7`. The exact patch is `source_integration/api_delta/canonical_app_delta.patch`, SHA256 `289dc3c75a0e0618f730c6db143faa9a1e60945ec4226e7e33a817fe3841d06e`. The reviewed candidate SHA was `864cfafd69b1aa6a8245e40b008f84d75dff8f232fc69723494999a98d5c3863`, based on `1b144675d94ef0efb8d92063b5a5b8b04391108bcb0e9db8b46cbb975bb35dfa`.

Validation run by this writer:

- `.venv/bin/python -m py_compile apps/api/v35_api/app.py tests/test_futu_observation_api_projection_r4.py` — PASS.
- `.venv/bin/python -m pytest -q tests/test_futu_observation_api_projection_r4.py --tb=short --basetemp=/tmp/futu-r4-api-delta-check` — 2 passed.
- First-increment compile of the five R4 sources and `tests/test_futu_afternoon_recovery_r4.py` — PASS; the focused R4/HK regression command recorded in the manifest returned 31 passed.
- `.venv/bin/python -m pytest -q tests/test_hk_historical_observation_contract.py --tb=short --basetemp=/tmp/futu-r4-historical-contract-check` — 3 passed, 2 failed with `ValueError("missing historical pool provenance fields")` in `infrastructure/preselection_pool_store.py:320`; this path is outside scope.

The frozen API candidate test was adapted against canonical once and stopped at its assertion that `execution_evidence.execution_verified` is false; the current canonical response has `execution_evidence=null`. The new direct projection regression covers the two approved function blocks without asserting that unrelated response field.

Task-start source baselines are partially recoverable. The API starting bytes are the snapshot above. `ops/_run_stage_center_nodes_parts/stage_dispatch.py` baseline is `source_integration/baseline_remote_stage_dispatch.py`, SHA256 `8f0220eece86a15ae7048e59230635c70e02a420e8f2172ce5105ffc6c14bb3a`; the controller recovered it from GitHub frozen commit `109337ae9152217db919763633c54bfe7780a50a`, and the hash exactly matches the recorded task-start SHA. Exact task-start bytes for the other four original R4 source files were not retained, and those paths returned 404 at that commit; their precise task-start unified diffs remain `CANNOT_CONFIRM`.

The LaunchAgent plist was inspected read-only. The packet cache paths and SHAs are in the manifest. The controller reported both original cached CLI runs successful in order (14:45, then 13:00), formal-provider guard count 0, API ports 8873 and 61796 returning HK 10 for all three stages, and 13:00/14:45 UI each showing HK 10 with the original A run and bytes preserved. The writer did not re-run the CLI or touch live services.

Reviewer must inspect the actual shared-tree source diff and frozen PASS scope. Remaining `CANNOT_CONFIRM` items are the exact task-start diffs for four R4 sources, the two out-of-scope historical provenance test failures, and the unchanged frozen candidate test's absent `execution_evidence` response field. No provider call, deployment, restart, or Git mutation was performed by this writer.
