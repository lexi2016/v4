# Task 1 — consumed archive identity and stale diagnostics

## Status and identity boundary

**PROPOSAL_ONLY.** The frozen-snapshot candidate has passed **56 focused tests**, including the confirmed materialized archived-catalyst case, existing material reader/projection, real ManagerResearchJobService persistence, and the registered manager router hosted in an isolated FastAPI test app. The same final test file gives **40 PASS / 16 FAIL on the frozen baseline**. The comparison against four existing test modules has **100 PASS / 16 FAIL on both baseline and final candidate**, with no introduced failure names after the compatibility correction.

This worker did not use the live 8873 service, any Mac path, an owner capture/import, a business-data producer, a deployment, scheduling, BUY, Stage mutations or Vibe 8910. Actual live API/UI and natural-session acceptance are NOT_RUN. Historical live changed field, unique live root cause and browser-loaded JS identity remain CANNOT_CONFIRM.

Independent review confirmed an additional whole-manifest coupling in the materialized archived-catalyst binding guard (`archive_catalyst_inputs.py`): unchanged consumed payload/receipt bytes plus an unrelated manifest entry made a saved CURRENT plan stale. Root explicitly authorized the exact additional source after this probe. The final candidate corrects the complete frozen replay, and the independent probe now passes with CURRENT retained, unchanged input identity, one provenance change and no GET writes. This is a reproduced offline code path, not an attribution of the historical Mac failure.

The additional source was **not in the uploaded current-fused25 snapshot**. Its approved preimage is fixed-Git support from `c0fc35c7b39502f49e43c2e75139dad7822091cf`, under `handoff/v4-running-source-20261005/canonical/`, Git blob `91901e86fcd2bf9d09391c47c2c1963c1dbb27b3`, SHA256 `968b26e66cb041adcf503e251c2c710728ce33638627123ff618357398b37b71`. This verifies the candidate comparison source. **The deployed preimage remains CANNOT_CONFIRM until the Mac file SHA is checked.**

- Fixed Git input: `c0fc35c7b39502f49e43c2e75139dad7822091cf`.
- Deployed identity supplied by the task: `stage_r4_manager_r2_owner_input_r1_fused_r1`; release manifest `fd7f21af0205b9d25a8ab5d33592aff42bf76c0419799b7c1724b94a286aeb86`. This is contextual identity, not a claim that this container ran that release.
- Canonical source: `/Users/lexi/Desktop/学习/v4_app` (not accessed).
- Read-only test baseline: `/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/baseline/app`.
- Candidate source: `/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app`.
- Target `20261009`, announcement publication `20261008`, task observation/review `20261010`. Synthetic plan clock is explicitly `2026-10-09T08:00:00+08:00`; no natural execution is inferred.
- Safety retained: RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false; A/HK boundaries and all owner gates remain in force.

## Concrete change

`workspace_identity.py` introduces a narrow semantic copy at a material's **top-level `source_refs`** boundary. It excludes only `manifest_sha256` on a complete, recognizable, already VERIFIED `V35_RESEARCH_DATA_ROOT` archive/hourly binding with exact path/date/mode and existing safety fields. Unknown references are left untouched. It does not recursively drop key names. `source_row`, `original_source_row`, arbitrary semantic fields, source date/root, payload path/hash, receipt path/hash, market, availability and content keep their existing identity effect.

`workspace_projection.py` includes the explicit `CONSUMED_ARTIFACTS_V1` identity discriminator and hashes the same projection inputs with those material bindings normalized. It records named component fingerprints and restores original bindings for returned material/derived DTO provenance.

`workspace.py` creates the semantic copies **before** material discovery and issuer relation IDs, the relation-material input, research attention and the outer identity extensions. Normalizing only the final projection hash would leave those downstream identities coupled to global provenance. Original owner materials/bindings are retained, then overlaid on returned DTOs after semantic identities have been computed. The global registry SHA remains visible in the original material bindings and diagnostic provenance.

New plans persist the component snapshot inside their already sealed workspace product. It contains per-input hashes and a grouped fingerprint for each unique consumed V35 artifact locator. It never stores another raw-data layer. On GET, comparison produces named changes with relative source/receipt paths and hashes, without titles, article bodies or source rows. GET does not write a plan, rewrite a receipt or run a producer.

The original `ResearchLaneSource` and `existing_materials.py` are byte-unchanged. Their verification remains authoritative. In particular, the frozen archive article schema rejects newly added `available_at`, `market` or arbitrary `manifest_sha256` fields; tests retain that rejection instead of broadening the schema. Separate projection tests prove that supported semantic availability and same-name content fields still affect identity.

### Materialized archived-catalyst correction

`archive_catalyst_inputs.py` still calls the original exact reader first, and frozen replay still uses only the captured date/slot list. Its small `_replay_selection` helper reuses the same bounded archive-binding recognizer and compares the entire selection after removing only the top-level binding `manifest_sha256` from two temporary copies. Unknown, missing or malformed bindings do not receive this exception. Payload SHA, receipt SHA, exact source date/root/path, mode, source status, selection error and all other content must remain equal.

After that comparison succeeds, the helper copies the materials and replaces only their exact original one-element `source_refs` binding with the frozen binding. This retains capture-time registry provenance in the snapshot, cards and rejected rows. It does not traverse or normalize semantic source rows. The unmodified PIT clock checks, original native security-master witness check, entire archive projection comparison and final catalyst-card/envelope comparison then run normally. `catalyst_observations.py` is byte-unchanged; there is no skipped equality check, forced CURRENT state or saved-product rewrite. Current registry provenance remains separately visible through the normal current material binding and diagnostic provenance change.

The final added tests include two distinct evidence levels. **Real fixed-store/owner tests** publish synthetic artifacts with the original store, materialize the catalyst, save the plan, and use real service/router GETs. They cover unchanged payload/receipt plus global-only updates, complete rejected-row/snapshot equality, no new slot enumeration during frozen replay, and fail-closed consumed-source, missing source, receipt, date/path/root/mode and malformed-binding changes. The original daily and hourly schema has no explicit `available_at`/`retrieved_at` article fields, so these real rows remain isolated with `ARCHIVE_EXPLICIT_ACQUISITION_TIME_REQUIRED` and zero admitted archive cards.

**Projection-boundary tests** substitute only the exact reader's output boundary with coherent invented explicit-clock payload/binding values; they do not claim the fixed store admits an extended schema. With all downstream code unchanged, these tests produce a nonempty native issuer card and verify complete owner replay equality after a registry-only change, real native-master artifact loss rejection, semantic acquisition changes and out-of-window PIT isolation. The reader-output seam is disclosed in the test fixture. No production schema, clock guard or source reader was changed to make this coverage pass.

## Migration and compatibility

A newly computed projection always has the new identity discriminator and component snapshot. There is no legacy-manifest rewrite, old-identity reuse or forced CURRENT path. A saved product missing the new metadata cannot be consumed by the newly computed workspace: the plan stays unconsumed and the diagnostic reports `CANNOT_CONFIRM / SAVED_COMPONENT_METADATA_MISSING`. An ordinary owner refresh publishes a new immutable run and the subsequent GET is CURRENT; the migration test verifies this transition.

The existing v1 product/DTO schemas remain readable. A legacy internal caller supplying **both** saved and current DTOs without the optional metadata retains the pre-existing exact-identity/date/cutoff/owner-attempt guard. It receives no new optional diagnostic, avoiding a contradictory CANNOT_CONFIRM diagnostic alongside a legacy consumed result. The actual new `_compute_workspace` path always creates metadata, so this compatibility branch cannot reinterpret an old plan as a new semantic plan.

When metadata is present, the stored checksum, embedded workspace identity, component IDs/hashes and complete allowlisted source/provenance shapes must verify. A resealed malformed metadata fixture fails closed, including unknown raw source fields or malformed provenance. The existing saved-product SHA, owner attempt, cutoff, semantic-version and date guards remain additional conditions for CURRENT. Scheduled duplicate publication now also requires compatible metadata; unchanged/global-only inputs reuse the existing run without writes.

Existing archived-catalyst snapshot schema and saved bytes are unchanged. A previously sealed snapshot can replay with its own historical registry provenance when the exact consumed artifact still verifies. New source enumeration belongs to an ordinary new owner refresh; a later hourly slot cannot silently enter frozen replay. This catalyst compatibility does not bypass the separate saved-plan component-metadata migration above.

## Additive diagnostic contract

Workspace field:

```text
input_identity_components = {
  schema_version: "v4.manager_input_identity_components.v1",
  identity_contract: "CONSUMED_ARTIFACTS_V1",
  input_identity: SHA64,
  components: [{component_id, sha256, source?, provenance?}],
  sha256: SHA64
}
```

Source-bearing components use `material_source:<locator hash>` and have exactly seven non-null strings: `source_id` (`V35_RESEARCH_DATA_ROOT`), `source_date` (YYYYMMDD), `source_root_sha256`, `payload_path`, `receipt_path`, `slot` (empty or HHMM), and `mode` (LIVE/REPLAY/BACKFILL). Paths are exact relative archive/hourly paths. The root is represented by a hash in the diagnostic. `provenance` contains only `manifest_path="manifest.json"` and `manifest_sha256`. Non-source components omit these objects.

Plan-product field:

```text
input_identity_diagnostic = {
  schema_version: "v4.manager_input_identity_diagnostic.v1",
  status: "MATCH" | "CHANGED" | "CANNOT_CONFIRM",
  saved_input_identity: SHA64 | null,
  current_input_identity: SHA64 | null,
  reason_codes: string[],
  changed_components: [{
    component_id, change: "CHANGED" | "ADDED" | "REMOVED",
    saved_sha256: SHA64 | null, current_sha256: SHA64 | null, source?
  }],
  provenance_changes: [{
    component_id, source?,
    saved_manifest_sha256: SHA64 | null, current_manifest_sha256: SHA64 | null
  }]
}
```

MATCH requires matching verified identities and no semantic component differences; global-only changes appear in `provenance_changes`. CHANGED has at least one real component difference. The independent existing `date_bindings` guard is represented explicitly; a date-only difference is meaningful even if another identity happens to be equal. CANNOT_CONFIRM has reason codes for absent/invalid component metadata, an unattributed identity change, the cutoff guard or an unverified owner attempt. This diagnostic is read comparison evidence, not an attribution of the original historical live failure.

## Validation evidence

| Check | Frozen baseline | Final candidate | Exit status |
|---|---|---|---|
| Initial valid test-first set before implementation | 6 FAIL / 20 PASS | — | 1 |
| Current 56-case focused file | 16 FAIL / 40 PASS | 56 PASS | baseline 1; candidate 0 |
| Saved metadata shape fault injection (incremental RED) | Intermediate candidate: 2 FAIL | Included in final 56 PASS | red 1; green 0 |
| Both-legacy optional diagnostic (incremental RED) | Intermediate candidate: 1 FAIL | Included in final 56 PASS | red 1; green 0 |
| Materialized-catalyst correction, 23 added cases | Pre-correction candidate: 4 FAIL / 19 PASS | 23 PASS | red 1; green 0 |
| Independent materialized-catalyst probe | Pre-correction candidate: 1 FAIL | 1 PASS | red 1; green 0 |
| Four existing related modules (116 cases) | 16 FAIL / 100 PASS | 16 FAIL / 100 PASS | both 1 |
| AST parse of all eight listed source/test paths | — | PASS | 0 |
| Full project pytest | Coordinated by root; not a worker PASS claim | Root report governs | See root report |
| Full `create_app` | Blocked by missing `stage_center.research_read_binding` in fixed support | Same limitation | Initial integration setup errors retained |
| Real service + registered manager router in isolated FastAPI | Exercised | PASS | 0 in focused file |
| Live API/UI, Mac deployment, natural sessions | NOT_RUN | NOT_RUN | NOT_RUN |

The original initial log `task-1-red.log` is retained: it includes the fixed-support `create_app` import errors and three over-permissive test fixture expectations. These were corrected to the original closed archive contract; no production validator was changed. `task-1-red-final.log` is the clean six-failure RED captured before the first production edit. The earlier 33-case comparison remains in `task-1-red-final-v3.log` and `task-1-green-final-v3.log`; its source inventory is retained as `task-1-source-sha-v3.json`. The final 56-case comparison is in `task-1-red-final-v4.log` and `task-1-green-final-v4.log`.

For the additional confirmed case, `task-1-catalyst-red-valid.log` was captured against the verified `968b26e6…` preimage before changing the upstream file: three positive replay assertions failed, and the native identity-loss check was prematurely blocked by the same global-manifest mismatch. The initial `task-1-catalyst-red.log` also contains one test-only wrong native asset-root path; it was corrected before the production edit and retained as evidence. `task-1-catalyst-green.log` is 23 PASS. The independent original failure is in `independent-catalyst-probe-runtime.log`, and the unedited probe's passing rerun is `task-1-independent-catalyst-green.log`.

The focused tests verify unchanged and global-only owner/GET transitions with both unmaterialized and materialized archive-catalyst states, semantic payload changes or original-reader rejection, payload/receipt/manifest-entry/date corruption, projected availability, arbitrary same-named source content, source root/path/mode/hash changes, frozen replay without new enumeration, full snapshot/card equality, original native identity and PIT guards, scheduled reuse without republishing, legacy-to-new owner refresh, malformed metadata, explicit date differences, saved run/SHA retention and snapshots showing no GET writes to synthetic source or manager roots.

### Exact commands and runtime

Machine-readable executed commands, environment, working directory, outputs and exit statuses: `review/task-1-test-commands.json`. All roots are absolute in that record. Final candidate command:

```bash
PYTHONDONTWRITEBYTECODE=1 PLAN_AUDIT_APP_ROOT=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app PYTHONPATH=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/work/candidate/app TASK1_BACKEND_FIXTURE_ROOT=/workspace/scratch/0e089a11ee60/live_ui_api_20261010/review/backend-ui-fixtures /workspace/scratch/0e089a11ee60/live_ui_api_20261010/runtime/bin/python -m pytest tests/test_manager_semantic_identity_20261010.py -vv --tb=short -p no:cacheprovider --basetemp /workspace/scratch/0e089a11ee60/live_ui_api_20261010/review/task-1-green-final-v4-tmp
```

The baseline command uses the baseline working directory and baseline `PLAN_AUDIT_APP_ROOT`/`PYTHONPATH`, while passing the absolute new candidate test file. The same four legacy modules are run against each source root; no baseline source/test file is changed.

Actual runtime is Python 3.12.14 on Linux; executable `/workspace/scratch/0e089a11ee60/live_ui_api_20261010/runtime/bin/python`, resolving to `/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3.12`. The project declares >=3.14, so this is a documented test-environment deviation. Locked packages: pytest 9.1.1, FastAPI 0.141.1, Starlette 1.6.0, httpx 0.28.1, pandas 3.0.6, NumPy 2.5.3, PyArrow 24.0.0. One Starlette/httpx TestClient deprecation warning remains; no runtime dependencies were changed by this worker. Details: `review/task-1-runtime.json`.

### Final focused baseline failures (all final candidate PASS)

- `test_unconsumed_manifest_entry_does_not_change_identity`
- `test_owner_saved_plan_stays_current_after_global_only_update`
- `test_scheduled_plan_global_only_update_does_not_republish`
- `test_true_stale_readback_locates_consumed_source_without_raw_payload[source_title-\u661f\u6d77\u79d1\u6280\u4e1a\u52a1\u8bb0\u5f55\uff1a\u65b0\u589e\u7ea6\u675f]`
- `test_true_stale_readback_locates_consumed_source_without_raw_payload[available_at-2026-10-08T17:02:00+08:00]`
- `test_legacy_plan_without_component_metadata_is_not_forced_current`
- `test_invalid_saved_component_metadata_cannot_authorize_reuse[checksum]`
- `test_invalid_saved_component_metadata_cannot_authorize_reuse[identity]`
- `test_invalid_saved_component_metadata_cannot_authorize_reuse[component_hash]`
- `test_invalid_saved_component_metadata_cannot_authorize_reuse[source_extra_field]`
- `test_invalid_saved_component_metadata_cannot_authorize_reuse[provenance_shape]`
- `test_date_binding_stale_diagnostic_remains_explicit`
- `test_materialized_archive_catalyst_global_only_keeps_full_replay_and_plan_current`
- `test_materialized_archive_catalyst_frozen_replay_never_enumerates_new_slots`
- `test_archive_projection_boundary_nonempty_cards_keep_frozen_provenance`
- `test_archive_projection_boundary_native_identity_loss_still_fails_closed`

### Existing failures retained on both sides

- `tests/test_manager_workspace_targeted_r2.py::test_half_day_close_is_native_and_can_anchor_window`
- `tests/test_manager_workspace_targeted_r2.py::test_missing_half_day_close_is_an_explicit_calendar_gap`
- `tests/test_manager_workspace_targeted_r2.py::test_rebound_screen_binds_panel_recovery_to_latest_native_previous5_session`
- `tests/test_manager_workspace_targeted_r2.py::test_two_character_unique_chinese_issuer_in_delimited_title`
- `tests/test_manager_workspace_targeted_r2.py::test_native_name_prefix_collision_uses_longest_non_overlapping_match[\u5357\u65b9\u6e2f\u80a1\u901a\u7ea2\u5229\u653f\u7b56\u53d8\u5316-master2-expected2]`
- `tests/test_manager_workspace_targeted_r2.py::test_native_name_separate_source_positions_keep_both_issuers`
- `tests/test_manager_plan_identity_r2.py::test_scheduled_existing_plan_is_not_reused_when_inputs_changed`
- `tests/test_manager_plan_identity_r2.py::test_scheduled_same_inputs_do_not_double_publish`
- `tests/test_manager_plan_identity_r2.py::test_autorun_cannot_shortcut_stale_plan_by_timestamp_alone`
- `tests/test_manager_plan_readback_issue24.py::test_legacy_over_64_mib_is_read_losslessly_without_rewrite`
- `tests/test_manager_plan_readback_issue24.py::test_failed_save_readback_never_gets_success_journal[READBACK_FAILED]`
- `tests/test_manager_plan_readback_issue24.py::test_failed_save_readback_never_gets_success_journal[STALE_INPUTS_CHANGED]`
- `tests/test_manager_plan_readback_issue24.py::test_failed_save_readback_never_gets_success_journal[NOT_MATERIALIZED]`
- `tests/test_manager_plan_readback_issue24.py::test_failed_save_readback_never_gets_success_journal[CURRENT_WRONG_RUN]`
- `tests/test_manager_plan_readback_issue24.py::test_failed_save_readback_never_gets_success_journal[CURRENT_WRONG_SHA]`
- `tests/test_manager_plan_readback_issue24.py::test_failed_save_readback_never_gets_success_journal[CURRENT_NOT_CONSUMED]`

These failures are not hidden or relabeled PASS. The paired final failure-name sets are identical. They include calendar expectations, existing issuer semantics and legacy owner/save/autorun fixture expectations. They were not modified in this task. Details and the empty introduced/resolved delta: `review/task-1-verification-summary.json`.

## Files and source SHA256

All paths below are relative to the baseline/candidate `app` root. ABSENT means a new task file; no old file was overwritten.

| Path | Before SHA256 | After SHA256 | State |
|---|---|---|---|
| `infrastructure/research_lane_source.py` | `2a58fe0db5c5d7915e7dbc884b8720e7d32a8c0084fe5e78b0e9e37f9e738cd4` | `2a58fe0db5c5d7915e7dbc884b8720e7d32a8c0084fe5e78b0e9e37f9e738cd4` | UNCHANGED |
| `v4/manager_research/existing_materials.py` | `88144b666e4a78ef46513f6eaf9846367ad0189478d9b3b85b9ac8124a5ca6e1` | `88144b666e4a78ef46513f6eaf9846367ad0189478d9b3b85b9ac8124a5ca6e1` | UNCHANGED |
| `v4/manager_research/workspace_projection.py` | `027d855613e675e1f569b401b9a8344e40766b88c31e987e791d05a0b3a2f200` | `54e98d1d46c24719906dfef0ae4fe9f11524d7e8cb02c66126877fb15bb54f4c` | CHANGED |
| `v4/manager_research/workspace.py` | `7a4875f1ab5ba46ac6c18bdaffe2c103a136734fda276fbee918163332844bb0` | `9a01a023f9c4244ba13a0d23c3f0f36e9e6e90db9d88073e3a4bf94bb7b8fa67` | CHANGED |
| `v4/manager_research/workspace_identity.py` | `ABSENT` | `bc4e516b98e518190dfa76277598cefc3da7b096610eebd5d3d32d2536acd0c6` | CHANGED |
| `v4/manager_research/archive_catalyst_inputs.py` | `968b26e66cb041adcf503e251c2c710728ce33638627123ff618357398b37b71` | `3a16ba2b996156ff923ce601d247c98778a546bae874850e1603ea7fcb8c5ae3` | CHANGED; fixed-Git preimage only |
| `v4/manager_research/catalyst_observations.py` | `9b1b4ecabc635c24580ba85fc293911f635ad056b8bf49a5feaa3adc1db5057f` | `9b1b4ecabc635c24580ba85fc293911f635ad056b8bf49a5feaa3adc1db5057f` | UNCHANGED |
| `tests/test_manager_semantic_identity_20261010.py` | `ABSENT` | `bf16a6d5e94cc2d70e92735a6e69da998afc960569bda6d908c3712d4237ae42` | CHANGED |

Actual unified diff: `review/task-1-diff.patch`, SHA256 `2682762c45ba3f7e749f5e0672d904db33d36f0d9f9b9a2f0de9ba1d1bf92e8e`. SHA inventory: `review/task-1-source-sha.json`. Source edits are exactly `workspace_projection.py`, `workspace.py`, the new `workspace_identity.py`, and the additionally authorized `archive_catalyst_inputs.py`; the only test edit is the new `test_manager_semantic_identity_20261010.py`. The extra upstream file's deployed preimage must still be checked on the Mac before applying it. No frontend, Stage, baseline, shared runtime or services were modified by this worker.

## Frontend integration fixtures

The final test run exported six **invented-data actual router responses** into `review/backend-ui-fixtures/` using the documented optional `TASK1_BACKEND_FIXTURE_ROOT` environment variable:

- `manifest_only_match.json`: CURRENT, consumed=true, MATCH, one provenance change.
- `consumed_content_changed.json`: STALE_INPUTS_CHANGED, consumed=false, CHANGED with exact consumed source locator.
- `consumed_availability_rejected.json`: STALE_INPUTS_CHANGED, consumed=false, CHANGED with the removed source locator after the unchanged schema rejects the added field.
- `legacy_missing_components.json`: STALE_INPUTS_CHANGED, consumed=false, CANNOT_CONFIRM with missing saved metadata.
- `date_bindings_changed.json`: STALE_INPUTS_CHANGED, consumed=false, CHANGED including `date_bindings`.
- `materialized_catalyst_manifest_only_match.json`: real fixed-store materialized-catalyst path, CURRENT, consumed=true, MATCH, one provenance change.

These are reproducible temporary fixtures for the existing frontend validator/mount, not live evidence and not proposed Git payloads. A small receipt listing their SHA/status/component IDs is `review/task-1-fixture-summary.json`. Root/frontend owns the cross-language validation result.

## Handoff and remaining limits

Independent code acceptance, integrated frontend acceptance, full-suite disposition and Git commit/push/readback are owned by root. This worker made no commit, push, merge or deployment. The independently confirmed materialized archived-catalyst defect is resolved in the candidate and its unedited probe passes; root's review of this final source governs acceptance. The additional fixed-Git-only file's deployed identity, full create_app support and actual Mac API/UI behavior remain unverified here.

The unchanged task data/PIT gaps remain: no new 20261009/20261008 announcement import; no assertion that exact security-master, six-day scale, provider finality or HK membership authority is closed on the user's Mac; no expansion of the four reviewed US relations to full-market completeness; no conclusion about the user's reported 2026-09-30 success receipt. The candidate is an offline code proposal until the proper Mac owner/API/UI acceptance occurs.
