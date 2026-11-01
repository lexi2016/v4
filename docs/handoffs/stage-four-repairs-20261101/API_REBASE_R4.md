# Current integration: Junda r4 API + accepted r3 Stage/pre-capture

Status: **r4 API increment independently reviewed PASS**, integration source `c311455620ef7b3149f15fbc4c5aa6d1f15addef`. The accepted Stage business source remains `d6f60ca5ad633cc18e6257f7c8f92f211e1d63f0`. Per the controller's independent Reviewer, 4/4 API cases, current baseline/pin, allowed delta, panel/binding preservation, read-only stage ensure and mandatory manual `_invoke_owner` binding passed; the final r4 API+r3 Stage/pre-capture set has no blocking finding. This is an API input-baseline correction, not another Stage repair or a deployment.

## Why this API candidate replaces r3-api

After the prior 20:28 audit, another task legitimately published the Junda API at 20:32. The controller's earlier assembly still used the old date-history API baseline. The current disk plist and loaded V4 environment match; **this was a stale assembly baseline, not a loaded-vs-disk mismatch**. Replacing the new API with the old-base r3-api would have risked restoring older research-panel behavior.

Actual current API base:

```text
/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/junda-single-20261101-8e342a6d64746507/app
manifest SHA256 80ef9ab95df0eb2168051ec62c628dea0a6efe63173059fab85bbeda087b5c7b
```

The assembler's current API pin now uses this loaded identity. It rechecks the loaded API and specified panel environment before cloning. Current disk+loaded agreement and the actual immutable manifest/inventory are the next activation CAS baseline. The earlier audit snapshot alone must not select a release.

## Exact scope and identities

New API app:

```text
/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/stage-four-repairs-20261101-r4-api/app
manifest SHA256 21fb1a6b8c272ae29441b5d5af1814be78e9d4dbd8615d1c5d880a752131107a
inventory SHA256 935360ad58add98cfa0cb1f3d5260f75eb4adca388a39656b281c644e42542fa
```

Only five paths differ from the complete actual Junda app:

- `infrastructure/operations_sop_reader.py`
- `docs/SOP.md`
- `docs/operations/STAGE_SELECTION_SOP.md`
- `docs/operations/records/2026-10-28_29-stage-selection-repair.md`
- `config/api-v4_manual_collection_stage_config.json`

All other app bytes are inherited from Junda. No apps/web, research business module, host module, manual collection business code, source/provider, entity filter, scoring or pool behavior is overlaid. Full inventory1330 entries and all550 app paths classified as apps/web/research/workbench matched the current base outside this allowlist.

The deployment set reuses these existing accepted identities verbatim; neither app was copied, modified or resealed:

| Owner | Existing r3 app | Existing manifest SHA256 |
| --- | --- | --- |
| primary Stage | `stage-four-repairs-20261101-r3/stage-four-repairs-20261101-r3-stage/app` under candidates | `ff62078ab7fb5d05318233fbfab18bd34408a0fc5b162359080c080633ee4115` |
| A pre-capture | `stage-four-repairs-20261101-r3/stage-four-repairs-20261101-r3-a_precapture/app` under candidates | `e497fcb246747269cf8d6b4911c4a89d7ffd85fd56d53fb27e54dbb754c56b3b` |

The r3-api remains the superseded pre-integration evidence and is not the API proposed for activation.

## Preserve the current external research bindings

The app clone retains the actual manifest's `research_panel` and `prior_research_panel` objects unchanged. External panel files are read-only dependencies; they were not copied or rewritten. The new activation tuple explicitly preserves:

```text
V4_RESEARCH_PANEL_ROOT=/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/junda-single-20261101-8e342a6d64746507/research-panel
V4_RESEARCH_PANEL_ASSET_MANIFEST=/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/junda-single-20261101-8e342a6d64746507/research-panel-assets.json
V4_WORKBENCH_HOST_BINDING=/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/junda-single-20261101-8e342a6d64746507/config/workbench-binding.json
V4_WORKBENCH_HOST_BINDING_SHA256=e2ab06e46919b85ac292fa066d33ac2ffeb4be96e69d82ed7981d39c68152249
V4_MANAGER_WORKBENCH_CONFIG_PATH=/Users/lexi/Library/Application Support/com.lexi.v4.local/config/us-industry-observed-api-20261018-r1.json
```

External asset manifest SHA: `0296a5755aaa7eae60e31e8b89a647bd1aab78b2a71033127d013e5211b023e9`; all487 listed panel files matched its hashes. Manager config SHA: `75c1efbd5a092b7945fc5baed98c64b37a7165ccf7eafc6abb9c1d540917c5db`. No older panel root or host binding should be restored from an earlier audit snapshot. Other current loaded environment values must also remain preserved.

API's manual config is selected before router creation by:

```text
V4_MANUAL_COLLECTION_STAGE_CONFIG=/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/stage-four-repairs-20261101-r4-api/app/config/api-v4_manual_collection_stage_config.json
manual config SHA256 1fade05041d43e60e253c00f82dbe8a5e8a5815b669dbba62d6e985a11c9a9b9
```

That config is byte-identical to the accepted r3 config and points to the same r3 Stage. The complete own API identity, current external bindings and reused Stage tuple are in r4-api's `activation-environment.json`, SHA `44ff66523c1d1024d82a818eec039e24b334d69dd6c021626556aa235f82f3a4`, status `PREPARED_NOT_APPLIED`.

## Actual commands and verification

```sh
PYTHONDONTWRITEBYTECODE=1 '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B ops/prepare_stage_four_repairs.py --output '/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/stage-four-repairs-20261101-r4-api' --reuse-stage-bundle '/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/stage-four-repairs-20261101-r3'
PYTHONDONTWRITEBYTECODE=1 STAGE_FOUR_BUNDLE='/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/stage-four-repairs-20261101-r4-api' STAGE_FOUR_RESULTS=/private/tmp/v4-stage-four-repairs-20261101/rebase-r4-api-identity-SOP-manual-preservation.json '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B tests/test_stage_four_repairs.py test_08_sealed_SOP_and_API_identity test_13_actual_API_SOP_endpoint_inprocess_isolated_state test_15_actual_manual_router_owner_parameters_without_spawn test_16_current_loaded_API_allowlist_and_panel_bindings
```

All four passed: actual new API manifest identity/sealed SOP; actual ASGI SOP endpoint HTTP200/422/503 with the current external bindings; actual router→service→r3 Stage command/environment parameter probe intercepted before Popen; complete allowlisted app inventory and external binding/resource preservation. The endpoint uses isolated state and no listener. Popen/provider execution and live state writes are zero. Other accepted Stage/raw/retry/SDK results are reused, not rerun.

Details, source hashes, candidate delta and explicit preserved bindings are in [api_rebase_evidence.json](api_rebase_evidence.json).

## Limits and next gate

The actual Junda `stage_center/candidate_input.py` has its original older SHA `947dca238598380bd7fe0e50d67c9beca7542500dc8354542494c5c6d218c244`; it is deliberately not replaced in this API-only rebase. This is preservation of the actual current baseline, not a claim that all r3-api overlay code exists in Junda. The repaired execution reader remains in accepted r3 Stage. No unrelated old fixes were backported.

The independent API integration review has passed; the r3 Stage/pre-capture approvals remain valid. The combination is explicitly listed in r4-api's `candidates.json`, with API env/manual/external-binding settings in its `activation-environment.json`. Before activation, re-read current loaded+disk identities, manifest/config pins and these explicit external panel bindings; an intervening release requires a new input decision instead of overwriting it. No production env/config/plist/service or external panel file changed here; no push/deploy/real manual collection/natural verification was performed. Controller owns the formal review receipt, remote sync/readback and operational handoff.
