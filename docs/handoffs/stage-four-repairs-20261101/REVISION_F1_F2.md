# F1/F2 bounded revision — sealed r3

Latest API integration: [actual Junda baseline, r4 API](API_REBASE_R4.md). R3 Stage and A-pre-capture roots/bytes/pins below remain unchanged; only the r3 API companion has been superseded after the actual API baseline changed.

Current: **r3 independently reviewed PASS**, business source `d6f60ca5ad633cc18e6257f7c8f92f211e1d63f0`; remaining P0/P1/P2=0 per controller's independent Reviewer receipt. The five affected cases, wrong Stage release_id negative, three inventories and twenty protected SHAs passed. Formal incremental evidence: `/private/tmp/stage-four-independent-incremental-r3.json`, SHA `f3eff7a9e88a2e6d9623ead69ba84a726ea610627315efa903c25851064e3adc`. This document-only follow-up does not change business code, config or candidate bytes and does not claim deployment/natural/manual-provider execution.

The prior r2 controller review was `REVIEWED/FAIL` for two P2 findings; no P0/P1 was reported. Its original evidence is preserved at `/private/tmp/stage-four-independent-review-a83b782.json`, SHA `7abae5149d342a32518c0ec46309927e1423cec76c998b2ad783a950c70cd22f`. That JSON records ten passing regression cases; those test passes are distinct from the controller's two-finding review verdict and are not rewritten here.

Source repair commits:

- F1: `207af9ad1` — preserve original SDK error messages in immutable diagnostics.
- F2: `d6f60ca5ad633cc18e6257f7c8f92f211e1d63f0` — bind the sealed API manual config to the new Stage, without changing manual collection business code.

## Exact repair

F1 adds the original exception message to `provider_diagnostics` for Futu import, context creation and close failures. Existing errors/status and public type-code boundaries remain intact. The existing get/subscribe/unsubscribe diagnostics already retained messages. Incremental case14 injects import/context/get/close/unsubscribe exceptions, invokes the actual fetch function, writes its result through the actual immutable capture writer and verifies the original messages in those bytes. It does not put real provider error bodies into chat/Git, call OpenD or change cleanup/temporal acceptance.

F2 repairs the separate API manual execution path. The existing API service loaded an external configuration whose executable owner was `hk-stage8-network-20261020-r1`; updating the primary Stage did not update that owner. The assembler now seals a new config under the candidate API app using the same accepted key set, data roots and Python interpreter. It changes `stage_owner_root` to the new Stage and takes `shared_data_root` from that Stage's existing accepted config. The Stage authority config's `release_id` is aligned with its actual new directory, as required by the existing manual service constructor.

`infrastructure/manual_collection.py`, the router and the fixed `_OWNER_PROGRAM` retain their original API bytes. The program handles only HK Stage8. Its relevant executable identity is rebound by the unchanged service to the Stage cwd, PYTHONPATH, V4_APP_ROOT and release_id. It inherits API manifest environment variables, which this fixed HK path does not consume; the probe explicitly reports those as inherited API fields, **not Stage attestation pins**. No unused A research path or new manual functionality is added.

## Prepared identities, not applied

Bundle: `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/stage-four-repairs-20261101-r3`.

| Role | App suffix under bundle | Manifest SHA256 |
| --- | --- | --- |
| primary Stage | `stage-four-repairs-20261101-r3-stage/app` | `ff62078ab7fb5d05318233fbfab18bd34408a0fc5b162359080c080633ee4115` |
| API / manual config / SOP | `stage-four-repairs-20261101-r3-api/app` | `94adf623a468990427d4ceae79385108f68e7216d9ab4a3ca8e07e5282083f48` |
| A pre-capture | `stage-four-repairs-20261101-r3-a_precapture/app` | `e497fcb246747269cf8d6b4911c4a89d7ffd85fd56d53fb27e54dbb754c56b3b` |

Prepared API environment must include:

```text
V4_MANUAL_COLLECTION_STAGE_CONFIG=/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/stage-four-repairs-20261101-r3/stage-four-repairs-20261101-r3-api/app/config/api-v4_manual_collection_stage_config.json
```

Manual config SHA: `1fade05041d43e60e253c00f82dbe8a5e8a5815b669dbba62d6e985a11c9a9b9`.

Stage authority config SHA: `6601d5e66a063dc7d17af4387d15d19ae833c10dd099aeaa5a1c3d4011365be4`.

The complete API own runtime tuple and manual binding are in `activation-environment.json` under the bundle, SHA `a4f8049ca67f8732ef27026a89be02a77d0bb6a7ec2d7e7b6d9b1ba22124c17f`. Status is `PREPARED_NOT_APPLIED`. The new config must be selected before API/router creation during a future authorized activation; file existence alone does not change a loaded API. Existing env/config/plist/services and original external config remain untouched. A path move requires updating both manual owner/config paths and release/config/manifest seals, then checking the affected identity chain again.

## Targeted verification

Actual command, with the project absolute interpreter:

```sh
PYTHONDONTWRITEBYTECODE=1 STAGE_FOUR_BUNDLE='/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/stage-four-repairs-20261101-r3' STAGE_FOUR_RESULTS=/private/tmp/v4-stage-four-repairs-20261101/revision-r3-F1-F2-identity.json '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B tests/test_stage_four_repairs.py test_14_SDK_original_errors_retained_in_actual_capture test_15_actual_manual_router_owner_parameters_without_spawn test_02_real_hourly_owner_and_cutoff test_08_sealed_SOP_and_API_identity test_13_actual_API_SOP_endpoint_inprocess_isolated_state
```

All five passed. Case15 uses the actual router constructor and its real service to load the config from the prepared API env, then calls `_invoke_owner` and intercepts Popen **before creating a subprocess**. It verifies the actual Python command/fixed program SHA, Stage cwd/PYTHONPATH/root/release identity, config SHA, authority SHA and absence of the old executable owner. Popen executed0, provider calls0 and state writes0. This is a parameter probe, not a successful manual collection run.

Cases02/08/13 recheck only the changed r3 identity/config/doc chain: actual D30 historical owners/context, final API manifest identity, fixed sealed SOP reader and actual ASGI endpoint 200/422/503 using isolated state. No listener or GUI is started.

All three full inventories passed. R3-vs-r2 app delta is exactly:

- Stage: `stage_center/hk_stage8/rtdata.py`, `stage_center_tick_config.json`.
- API: added `config/api-v4_manual_collection_stage_config.json`; updated `docs/operations/STAGE_SELECTION_SOP.md`.
- A pre-capture: no app-byte difference; only its new root/manifest identity is resealed.

The original four-repair behavior cases, raw/HK preservation, entity filter and process-retention passes are reused by matching unchanged code/function hashes; no unrelated ten-case rerun. Evidence and exact before/after hashes are in [revision_evidence.json](revision_evidence.json). The original FAIL and earlier r2 evidence remain preserved. Deployment, natural verification, real manual/provider execution and remote synchronization remain NOT_RUN by this Writer. The D30 missing original RT_DATA limitation remains unchanged. Controller owns final Git push/readback and operational handoff.
