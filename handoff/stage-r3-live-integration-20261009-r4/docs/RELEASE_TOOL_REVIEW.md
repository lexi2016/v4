# Stage R4 release integration review

## Outcome and scope

The exact Issue30 release guard and two existing wrappers now support one bounded Stage API/UI release delta. They retain the active-release manifest, complete application inventory, shared-path ownership, before/after SHA and mode, text diff, directory preservation, anchored no-follow file access, late snapshot revalidation, and persistent publication-lock checks.

Only these existing files change:

| File | Change |
| --- | --- |
| `ops/api_release_integration.py` | Adds narrow Stage ownership and a complete before/after static inventory contract; allows declared removals only within that Stage static contract. |
| `ops/create_api_module_delta.py` | Adds a concrete isolated Git source preparer to the existing CLI; carries the complete static proof through the existing reviewed delta receipt. |
| `ops/build_release_candidate.py` | Reports the actual origin of an updated static tree and exposes its existing candidate verifier as a read-only CLI. |

No API modularization, producer, Stage service, active pointer, launch agent, live business state, dirty canonical tree, deployment publisher, or frozen Issue32 cutover constant changes are part of this work. The existing generic `prepare_api_only_cutover.py` and five builder dependencies are unchanged support inputs. The original Issue30 guard/wrapper bytes are retained under `before/ops`; `SOURCE_MAP_RELEASE.json` records every exact before/after SHA and the ownership policy change.

The authoritative preimages were fetched from `lexi2016/v4`, commit `137431f5de3917ff4526784351f5638e115061e5`, prefix `handoff/issue30-api-module-isolation-20261008-r1/after`. Their guard and wrapper SHA-256 values match the task's three required identities. A patch generated from these exact bytes passes `git apply --check` and reconstructs every after file byte for byte in a new isolated roundtrip directory.

## Ownership

The new `stage` module owns these exact non-static paths:

- `stage_center/consumer.py`
- `stage_center/execution_evidence.py`
- `stage_center/research_read_binding.py`
- `stage_center/approved_research_read.json`
- `stage_center/approved_research_read.sha256`
- `apps/web/src/components/review/StageExecutionEvidencePanel.vue`

It may declare the shared files `apps/api/v35_api/app.py`, `apps/web/src/App.vue`, and `apps/web/src/contracts/runtime.ts`. The shared list must equal the shared paths actually present in the delta. It gains no ownership of `stage_center/selection.py`, runners, API config/run files, preselection, manager source, other Vue components, scheduler, or release tools. Existing module ownership remains unchanged except that the shared API app also admits the Stage module.

`apps/web/dist/` is the only new owned prefix. Generated content-hashed assets can require removal of old names. Removal remains forbidden for every source path and every other module, and static removal cannot pass without the complete inventory proof below. Directory deletion is not introduced; base directories and their modes are preserved, including empty directories left by a static file removal.

## Static proof contract

The existing v2 delta receipt accepts one optional field, `static_tree`. It is mandatory for any static delta and is valid only for the Stage module:

```json
{
  "schema_version": "v4.api_release_static_tree.v1",
  "root": "apps/web/dist",
  "before": {
    "entry_count": 11,
    "aggregate_sha256": "actual digest of the complete before entries",
    "entries": []
  },
  "after": {
    "entry_count": 11,
    "aggregate_sha256": "actual digest of the complete generated entries",
    "entries": []
  }
}
```

This is a schema illustration, not a runnable input. The generator emits the actual entries and digests. Each entry contains precisely `path`, `kind=file`, `sha256`, `mode`, and `size`. Paths are full app-relative paths beginning with `apps/web/dist/`, unique, sorted, and distinct under case folding. Static symlinks and special files are rejected. The generated tree must contain `apps/web/dist/index.html`.

The digest formula, shared with the existing builder's `frontend_dist` inventory, is:

```python
rows = [
    dict(row, path="apps/web/dist/" + row["path"])
    for row in guard.inventory_tree(built_dist_root)
]
expected_static_inventory_sha256 = guard.inventory_digest(rows)
```

`inventory_digest` hashes UTF-8 JSON with `ensure_ascii=False`, sorted object keys, separators `(',', ':')`, and the already sorted entries list. The complete before tree must equal the current active inventory. The set of static delta paths must equal the actual differences between the complete before and after inventories. Every static file row must have matching before/after SHA and mode. A removal uses null `after_sha256` and `after_mode`, with the exact before SHA/mode. Text assets retain the original text diff proof; binary static assets use the full SHA/mode/tree proof. This exception does not admit binary modifications for ordinary source files.

The generator checks the whole generated tree, the delta builder checks the whole supplied source static tree, and the final candidate verifier recomputes the complete candidate static tree. The proof is embedded both in the copied delta receipt and in `api_integration`, and the verifier requires them to match. Resealing the general candidate inventory does not make undeclared asset, manager, file-mode, or deletion drift acceptable.

## Concrete source staging from a non-Git active app

The existing full builder still reads Git provenance from its source root. The active Issue32 app remains non-Git. The new preparation method creates a separate, new local Git root from only the reviewed after files and the complete verified UI build. It does not initialize Git inside active or canonical source.

```python
prepare_stage_source(
    *,
    active_api_plist_path: Path,
    after_root: Path,
    change_set_path: Path,
    built_dist_root: Path,
    expected_static_inventory_sha256: str,
    source_root: Path,
    output_change_set_path: Path,
) -> dict
```

The package orchestration supplies an ordinary reviewed code/config change set with `schema_version=v4.api_module_change_set.v1`, `module=stage`, exact `shared_paths`, and file rows containing only `path`, `before_sha256`, `after_sha256`, `before_mode`, and `after_mode`. It derives those rows from the frozen package source map and the validated generated binding receipt. The operator does not write JSON or choose arbitrary path permissions.

Preparation validates all code paths and pins before it creates the source destination. It reads the active app through the original manifest/inventory contract and rejects a reviewed preimage mismatch. It reads readonly after files without changing them, then gives only the new copies their reviewed `after_mode`. It records the complete generated static tree and derives every required static add, modification, and removal from the actual before/after inventories.

Only the explicit non-static source rows are committed in this new local Git repository. All generated static files remain untracked; no remote is configured and no push occurs. The function verifies the exact committed and indexed path sets, clean tracked status, permitted untracked files, and every copied byte/mode before returning. Its result includes the real `source_root`, `source_commit`, `change_set_path`, `change_set_sha256`, the input change-set SHA, static root/digest, current base binding, and the exact `include_untracked_paths` required by the existing full builder. The include list contains changed static after files only; deleted paths cannot be included as source after files.

The source root and output change-set must be new and outside all protected input roots. Aliases, existing destinations, unreviewed code paths, wrong code SHA, wrong static digest, missing/extra static members, source mutation during preparation, and unexpected Git entries fail. An interrupted source preparation retains an incomplete marker; a candidate build retains the original candidate-in-progress marker. Existing input files are never removed or chmodded.

The CLI extension is `create_api_module_delta.py --prepare-stage-source` with the existing `--active-api-plist`, `--after-root`, `--change-set`, and `--output` arguments plus `--built-dist-root`, `--expected-static-inventory-sha256`, and `--source-root`. In this mode `--output` names the complete generated change set. Without the new mode flag, the existing delta CLI behavior remains intact.

The caller must bind its UI build receipt to the same full active app identity before preparation. The release helper proves the supplied generated bytes and exact integration boundary; it does not claim to prove that an arbitrary external UI build used the right source graph. The package's source clone/build proof supplies that link and must preserve the live lock/build graph outside the three reviewed UI modifications.

## Candidate creation and verification

The next two steps use the existing interfaces, with real paths returned by source preparation:

1. Call `create_module_delta` using the generated source root as `after_root` and the complete generated change-set path. It binds the current full active identity into the ordinary v2 delta receipt.
2. Call `build_candidate` using that source root and delta receipt, and pass the returned `include_untracked_paths` exactly. The builder copies the verified active app and applies only declared deltas. It writes the existing inactive API cutover plan and inactive scheduler copy. It does not call launchctl, change a live plist, or activate any service.

For a static update, the manifest now accurately reports `source.working_tree_dist_included=true`, `frontend_dist.included_from_current_source=true`, and `frontend_dist.preserved_from_active_release=false`. The non-delta preservation proof remains true and continues to cover every active file outside the exact delta paths. These static metadata changes are not claims that any UI source outside the delta was copied from a different branch.

The existing `verify_api_release_candidate` function is unchanged as a public API. Its new read-only CLI form is:

```text
build_release_candidate.py --verify-api-candidate
  --candidate-root <the concrete candidate directory>
  --api-plist <the active API plist>
  --expected-manifest-sha256 <the generated candidate manifest SHA>
```

The package orchestration supplies those values from the build receipt. The expected manifest SHA is mandatory in this mode. It checks the still-active base and candidate and performs no writes, lock creation, publication, or runtime activation. The actual publisher must retain the original requirement to revalidate under the persistent shared API pointer lock immediately around authorized writes. No new cutover executor is introduced here, and the frozen Issue32 executor remains untouched.

## Verification

All testing used the isolated Linux source fixture directory and synthetic release/plist/static data. The exact original Issue30 release suite first passed **112/112**. Stage TDD phase one produced **15 expected failures in 34 tests** for missing Stage ownership/source preparation; a later three-test refinement failed on the missing read-only verifier CLI and missing final source/Git drift checks. The final bare package pytest run passed **152/152**, consisting of all 112 original regressions and 40 R4 cases, with zero skips, xfails, collection errors, or test errors.

R4 coverage includes exact ownership/shared scope, preservation of manager/preselection bytes, hashed asset additions/modifications/removals, complete static inventory proof, binary asset changes, missing/extra static members, proof/schema/digest tampering, source deletion rejection, existing and aliased destinations, stale before/after source, readonly input copies, readonly active directory modes, concrete sparse Git source creation, full builder integration, truthful static provenance, a readonly SHA-pinned CLI, and resealed candidate/active drift.

Reproduce from the assembled `candidate_run` directory:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -B -m pytest -q -p no:cacheprovider -c pytest.ini
```

The input layout is the four existing release tool files plus the five exact unchanged support files in `ops/`, all original release tests plus `test_stage_release_r4.py` flattened into `tests/`, and an empty pytest configuration. `REFERENCE_INPUTS.json` records the fetched support/source provenance. `evidence/TEST_RESULTS.json`, the baseline/red/final JUnit and text logs, and `evidence/PATCH_ROUNDTRIP.json` record the actual results.

The environment was Python 3.12.14 on Linux, UID/EUID 0. The tests assert unchanged source bytes, file modes, and directory modes. An additional attempt to run the readonly cases under an unprivileged UID could not start because subprocess UID/GID demotion failed before pytest. The previously used R3 namespace mechanism was also checked and failed before Python with `unshare: write failed /proc/self/uid_map: Operation not permitted`. That separate probe remains **NOT_RUN**, with both errors retained in `evidence/unprivileged_permissions.*`. No escalation or global permission change was attempted. Mac ACLs, flags, extended attributes, local dependency closure, actual Issue32 app integration, real Mac compilation, 8873 API/UI, cutover, and natural-session behavior are **NOT_RUN by this release work**. Previously accepted R3 Mac/real-canary receipts remain separate evidence and were not rerun or relabeled.
