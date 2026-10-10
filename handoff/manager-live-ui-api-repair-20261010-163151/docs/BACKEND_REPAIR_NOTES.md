# Backend semantic identity proposal

Status: **PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN**. Python 3.12.14, Linux isolated workspace. No Mac owner roots, live 8873 calls, market-data capture/import, backfill, scheduler execution/change, service restart, or deployment. The backend implementation/test phase performed no Git writes; the final authorized handoff sync is recorded separately in `GIT_SYNC_RECEIPT.json`.

## Evidence and scope

The supplied live receipts establish equal run/product/date and a later changed input identity; they do not preserve the old manifest bytes or the later full response body. The unique historical changed field remains **CANNOT_CONFIRM**. The retained counterfactual establishes a global-manifest coupling contributor, not the unique historical cause. The 1,970 original material rows are absent from the package; this proposal does not claim to replay their exact missing bytes or the historical ca3292/e0f5ed hashes.

The three omitted source files were recovered at fixed repository commit `lexi2016/v4@c0fc35c7b39502f49e43c2e75139dad7822091cf`. Their bytes match all three SHA256 pins from the supplied root-cause report. Source paths, Git blob hashes, byte counts, and SHA256 values are retained in `evidence/backend/recovered_before_sources.json`; deployment source preconditions are in `SOURCE_SHA256.json`. The correct `existing_materials.py` is the recovered API variant; the canonical variant is different and was not substituted.

`research_attention.py` is a fixed-commit recovered API dependency with before SHA256 `3f5385ed850b0336cb85ad85cac3aeab44d2908620c636a4cfc19f5fdf3619aa`. That file is not independently live-pinned by the report. Its two-line repair therefore has this explicit before-image SHA precondition; a differing owner file needs reconciliation, not blind replacement. Other recovered modules are fixed source dependencies for isolated tests and are not claims about current live bytes.

## Changes

1. New `workspace_identity.py` computes a semantic copy for hashing. It drops only `manifest_sha256` inside source-ref/input-binding containers when the complete binding is a verified, read-only `V35_RESEARCH_DATA_ROOT` registry binding with exact date/slot/mode/payload/receipt paths, SHA shapes, and research-only flags. The payload SHA is also the original source reader's exact manifest-entry value. An optional explicit entry SHA remains semantic and must agree for the exemption. Incomplete/unrecognized bindings remain fully identity-sensitive. Original `source_row`, `original_source_row`, and structured `content` are protected from traversal; arbitrary fields with the same name are not globally removed.
2. Pinned `workspace_projection.py` hashes that semantic copy of the same input fields as before. It retains original materials and their complete source refs, including the global manifest SHA. It adds `input_identity_schema` and named `input_identity_components` to the workspace product.
3. Provided `workspace.py` uses the same semantic hash for the previously raw `selection_materials`/relation-card identity boundaries, keeps every existing identity extension, and adds named diagnostic components for projection, Connect scope, attention, announcement inputs/review/product, US payload, and cutoff-admitted daily US mapping.
4. Recovered `research_attention.py` applies the semantic hash only to admitted `attention_cards_digest`. The original validators still receive the full refs. A direct admitted-card test proved this additional coupling before the two-line change. HK/Stage/other manifest identity fields are unchanged.
5. `_readback_plan` retains its exact plan hash, safety flags, date bindings, semantic version, research cutoff, and same-run owner-attempt checks. New compatibility requires saved and current semantic component contracts. It returns `plan_product.input_identity_diagnostics` with `MATCH`, `CHANGED`, or `CANNOT_CONFIRM`, saved/current input identities, and source-backed changed components. Date/version/cutoff guard failures report their concrete compared values. A missing legacy schema/component set returns `STALE_INPUTS_CHANGED` with reason `SAVED_IDENTITY_COMPONENTS_UNAVAILABLE_OWNER_REFRESH_REQUIRED`; it is never migrated or made CURRENT by reading.
6. The existing scheduled `ALREADY_MATERIALIZED` reuse branch (shared by preopen and morning) uses the same compatibility diagnostics, including the prepared cutoff, before consuming a saved run. This closes an independent-review finding that ordinary readback rejected a legacy plan while the older reuse shortcut still consumed it. Existing scheduling windows, attempts, cutoff checks, and immutable per-run products remain intact. No scheduler code was changed or executed.

No changes were made to the exact recovered `infrastructure/research_lane_source.py` or `existing_materials.py`; their original per-artifact validators/read boundaries and provenance projection remain byte-identical.

## Response contract

New saved workspace fields:

- `input_identity_schema = "v4.manager_research.input_identity.v2"`.
- `input_identity_components`: named `{sha256, sources}` components. Source refs retain full provenance.

New readback field:

```json
{
  "plan_product": {
    "status": "STALE_INPUTS_CHANGED",
    "consumed": false,
    "input_identity_diagnostics": {
      "schema_version": "v4.manager_research.input_identity_diagnostics.v1",
      "input_identity_schema": "v4.manager_research.input_identity.v2",
      "status": "CHANGED",
      "saved_input_identity": "...",
      "current_input_identity": "...",
      "changed_components": [
        {
          "component": "projection.materials",
          "saved_sha256": "...",
          "current_sha256": "...",
          "saved_sources": [],
          "current_sources": []
        }
      ]
    }
  }
}
```

Actual changed-source lists are included in `evidence/backend/diagnostic_example.json`, which is clearly labeled synthetic and is not a live receipt. Guard components additionally include `saved_value` / `current_value`. `CANNOT_CONFIRM` carries a reason when a saved/current diagnostic contract is absent or an identity difference cannot be accounted for. Existing status/consumed/run/product fields remain authoritative. The four research-only flags remain unchanged.

## Executed regressions

The final suite contains 21 unittest methods with parameterized subcases. It uses actual source imports and function calls; no AST extraction is used in the final tests.

- Actual `build_workspace` ignores only the global registry provenance mutation, while returned full refs preserve it.
- Payload SHA, receipt SHA, manifest-entry SHA, source/date/root/path, material availability, and source content changes remain identity-sensitive.
- Unknown/partial/malformed/non-research bindings retain the global SHA in identity; business `source_row` fields remain semantic.
- Real sealed product + same-run attempt readback remains CURRENT for repeated manifest-only changes, preserving run/product/date and stored bytes; genuine changes stay stale and expose source-backed components.
- Date bindings use the actual `{plan_date, selection_date, announcement_date}` contract. Target is 20261009 and publication date is 20261008.
- Old saved products never become current by copying their input hash; plan hash/safety flags, missing exact attempts, changed semantic version/dates, and earlier cutoff remain fail-closed.
- Actual admitted research-attention cards preserve the global-only identity and still react to changed payload/receipt/availability.
- Actual `_compute_workspace` executes projection, Connect gating, event lane, attention, outer extension assembly, then sealed readback. It confirms repeated same run/product/date, real daily-channel date binding, true leaf-change diagnostics, and independent announcement/daily-mapping extension invalidation. External original owner-return boundaries use explicit synthetic fixtures; the announcement-owner module import is replaced at that same boundary because its transitively imported storage code is absent. No identity, guard, projection, or attention function is mocked.
- Both existing preopen/morning reuse entries reject legacy saved plans and retain compatible v2 plans with no writes on reuse. These are in-memory function tests with native calendar windows injected; no scheduler is run.
- The actual daily mapping reference helper excludes artifacts after the plan cutoff and retains the synthetic fixture's four reviewed relations / non-full-market scope.

## Portable execution

Run these commands from the extracted delivery root with Python (verified on Python 3.12.14). The runner and final tests use the standard library; no package installation is needed for this isolated suite.

```bash
python tools/run_backend_tests.py --source-image before
python tools/run_backend_tests.py --source-image after
```

The `before` command deliberately returns exit 1 because the new regression assertions expose the original behavior. The `after` command returns exit 0. The runner propagates the real test exit code; it does not convert the expected baseline failure to a success.

The runner verifies the hashes of 21 unchanged source files under `test_support/python`, copies those imports into a temporary directory, and overlays only Python files from the selected `before` or `after` tree. It sets `WORKSPACE_SOURCE_ROOT` and `WORKSPACE_DEPENDENCY_ROOT` to that assembly, isolates caller import paths, and suppresses bytecode writes. The added identity helper must be absent from `before` and present in `after`. The five packaged test files are byte-identical to the final development regressions. None of these operations changes the source images, test support, or production candidate.

`test_support/python/SOURCE_PROVENANCE.json` records the exact bytes and supplied/fixed-repository authority for the 21 unchanged dependencies. These files allow real module imports in this incomplete source snapshot; they are test support, not an additional deployment overlay. The synthetic owner-return fixtures, in-memory stores, calendar-window injections, and announcement-owner import boundary described above remain explicit. No owner storage, market rows, local state, package caches, or AST extraction harness is included.

Final results (all logs are under `evidence/backend`):

| Run | Actual result | Log |
|---|---|---|
| Portable before assembly, same 21 methods | Exit 1; 19 assertion failures including subcases; no import/test errors | `portable_before.log` |
| Portable after assembly, same 21 methods | Exit 0; 21 tests passed | `portable_after.log` |
| Development before assembly, retained final run | Exit 1; 19 assertion failures including subcases; no import/test errors | `red_all.log` |
| Development candidate, retained final run | Exit 0; 21 tests passed | `green_all.log` |
| Independent reviewer legacy-reuse reproduction after fix | Exit 0; 1 test passed | `green_independent_review.log` |
| Full repository test command `python -m pytest -q`, invoked from candidate | Blocked before collection: `No module named pytest` | `repository_suite_unavailable.log` |

The independent review reproduction is separate from the 21 packaged test methods; its final log is retained here. `evidence/backend/portable_results.json` records the portable runner commands, exit codes, environment, log hashes, and the check that the selected source images and unchanged test support retained identical bytes after execution.

The full repository suite is **NOT_RUN**: pytest and the complete repository test/config snapshot are absent. Live API/UI, Mac owner behavior, natural-time behavior, exact historical changed field, original 1,970-material replay, and full-market US coverage remain **CANNOT_CONFIRM / NOT_RUN**. The isolated tests do not establish any of those outcomes.

Source before/after SHA256 values and the development test/environment summary are in `evidence/backend/backend_source_sha256.json`. The source candidate remains a reviewable proposal. Backend implementation and tests performed no Git writes; final handoff synchronization is reported separately in `GIT_SYNC_RECEIPT.json`. No deployment was performed.
