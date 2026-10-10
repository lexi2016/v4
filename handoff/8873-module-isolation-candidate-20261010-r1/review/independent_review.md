# Issue 30 — independent code review

Reviewer identity: `/root/independent_review` (different from the implementation and native-publisher authors).

Initial review time: 2026-10-10 15:00 UTC. Baseline: local commit `d8b69322963d7ec5dfd5838849a0b7593e64f904`; reviewed working changes over the fixed input snapshots. The working tree was still changing during this review. Final verification and exact reviewed source hashes are recorded below when available.

## Status

**Final result at 2026-10-10 15:06 UTC: ACCEPT for the isolated candidate/source-handoff scope.** Four P1 output-boundary defects and one P2 ownership-schema defect were found, fixed by the author, and independently rechecked. All five are closed; no known P0/P1/P2 code finding remains open in the reviewed candidate scope. The exact final source hashes and final tests are recorded at the end of this report.

**Initial result was REQUEST CHANGES.** The initial findings and reproductions below are retained as an audit record; they describe the vulnerable earlier revision, not the final corrected source.

This review does not approve a Mac service change. The patched native script is a frozen historical reference, with current publisher identity and production owner bindings explicitly `CANNOT_CONFIRM`.

## Scope and method

Read `verified_input/CHAT_TASK.md`, `analysis/IMPLEMENTATION_PLAN.md`, `analysis/ownership_audit.md`, `analysis/publisher_audit.md`, the implementation diff, the new business-ownership validator, the existing integration/lock implementation, and the added synthetic/native tests. Inspected the runtime-B source for actual external data-root variable names. The optional reviewer-template resource could not be read; no claim is made that it was available.

The reviewer did not modify `work/`, invoke launchd, contact 8873, read production owner state, or use a real service. Every reproduction used `tempfile.TemporaryDirectory`, the supplied synthetic `setup_active`/`build` helpers, and the actual production builder/integration functions. Only analysis artifacts were written outside those temporary fixtures.

## Findings

### F1 — P1: explicit build receipt can write active app or owner state

Affected entry: `ops/build_release_candidate.py::build_module_candidate` / `_build_module_candidate_locked`, before `_json_dump(receipt_path, receipt)`.

The receipt path was checked against the source/formal-release roots, but not the active release, external state, or the candidate itself. Three independent synthetic calls all returned `READY_FOR_REVIEW`:

| Explicit receipt destination | Observed result |
| --- | --- |
| `active_app/review_unexpected.json` | Wrote a file into the active app; subsequent active identity read failed with `API_RELEASE_ACTIVE_APPLICATION_INVENTORY_DRIFT`. |
| `owner_state/review_unexpected.json` | Wrote owner state while candidate verification still returned `PASS`. |
| `candidate/app/modules/beta.py` | Overwrote the non-target beta source after the manifest/plan checks; subsequent candidate verification failed with inventory drift. |

Evidence: `analysis/review_receipt_repro.json`. These are actual observed return values, not expected assertions substituted for execution.

Required fix: validate candidate, success receipt, and failure receipt outputs before any candidate or receipt writes. Require exact, existing parents; reject the active/retained release trees, externally bound state/data, launch-agent directory, ownership authority, and the candidate artifact tree itself for external receipts. Preserve all previous bytes when refusing.

Author response: accepted; regression cases and pre-write guards being implemented.

### F2 — P1: rollback preparation can corrupt an intermediate immutable release

Affected entry: `ops/api_release_integration.py::prepare_module_rollback` / `assert_business_output_boundary`.

The reverse-output guard protected the current release, target release, and target's direct parent, but not intermediate ancestors. Reproduction: synthesize `G → A(alpha) → B(beta) → C(beta)` and request rollback of A with `output_root=B/app/review-poisoned-history`. Preparation returned `READY_FOR_REVIEW` and wrote its source/receipt into the retained B app. Current C remained active, but a subsequent ordinary rollback preparation failed with `API_RELEASE_ACTIVE_APPLICATION_INVENTORY_DRIFT` because B's immutable inventory had been destroyed.

Evidence: `analysis/review_lineage_output_repro.json`.

Required fix: verify and collect the retained lineage, then reject every candidate/receipt/reverse output that overlaps any retained release root. Missing or invalid ancestry should produce a precise refusal rather than permit a write. The retention dependency must be documented because future safe rollback depends on those exact bytes.

Author response: accepted; a common full-lineage boundary is being implemented.

### F3 — P1: real external data bindings are omitted by the state/data name heuristic

Affected entry: `ops/api_release_integration.py::assert_business_output_boundary`.

Only environment names containing `STATE_ROOT` or `DATA_ROOT` were protected. The supplied runtime-B source also reads `V4_MANAGER_SCREEN_AUTHORITY_ROOT`, `V4_MANAGER_NEWS_OWNER_ROOT`, and `V4_DAILY_REVIEW_ROOT`, among other source/archive/research roots. For each of those three variables, a synthetic active plist binding and `candidate_root=<bound root>/A` produced `READY_FOR_REVIEW` and wrote app/plans/receipts directly into that owner-product directory.

Evidence: `analysis/review_data_binding_repro.json`. Source evidence: `verified_input/source/runtime-B-release/apps/api/v35_api/app.py`, the review-reader construction and manager-research service initialization (including the reads of the exact variable names above).

Required fix: protect all relevant absolute bindings from both `ProgramArguments` and `EnvironmentVariables` without silently discarding conflicting definitions; fail closed on unresolved relative path bindings. Explicit, approved protected external roots are also needed for default data locations not represented in the plist. Production closure still requires actual source/runtime evidence, rather than inferring ownership from a directory label.

Author response: accepted; collecting all absolute environment bindings and adding explicit protected roots to the approved contract.

### F4 — P1: a candidate `config` symlink permits staged-plist writes into state

Affected entry: `ops/prepare_api_only_cutover.py::render_module_cutover`.

Reproduction: build an otherwise valid A candidate; replace its non-app `config` directory with a symlink to the synthetic state directory; call `render_module_cutover(..., module_id='alpha')` using the intact manifest and owner contract. Verification passed because `config` is outside the app inventory. `config_dir.mkdir(exist_ok=True)` accepted the symlink, and the renderer returned a plan after adding `api-module-cutover-plan.json` and `com.lexi.v35.api-only.plist` to owner state.

Evidence: `analysis/review_plan_symlink_repro.json`.

Required fix: reject a symlink/alias in the config directory or any ancestor before any staged-plist/plan write. Check both destination parents and refuse partially existing configuration safely. The direct renderer must enforce its own boundary rather than rely solely on the builder normally creating a fresh candidate.

Author response: accepted; explicit config-path guard and test being added.

## Verification interpretation and non-completion boundaries

The new A/B and reverse-delta tests exercise the actual builder, inventory, receipt, owner, and lock algorithms. Their `synthetic_commit` rewrites only a temporary plist, so they prove isolation mechanics but do not prove launchd/CAS or runtime health. The separate native fixture exercises the historical switch implementation with deterministic launcher/HTTP/clock substitutions; that is an appropriate isolated seam test, not a Mac deployment observation.

One native test deliberately observes a loaded but non-running candidate. It returns `ROLLBACK_INCOMPLETE` and leaves the temporary active pointer at that candidate. Its test assertion passing means the limitation is reported honestly. It does **not** satisfy the task's stronger failure-matrix outcome that the old release is active and healthy. The final matrix must show that recovery branch as `PARTIAL`/`CANNOT_CONFIRM` rather than count it as completed recovery.

Other explicit limits remain: the current Mac native publisher and final-release staging identity have not been bound; real owner contracts are unapproved; shared/frontend changes are rejected without an approved joint integration; the historical script's final guard pins still need to be frozen and freshly verified. No `DEPLOYED`, live API/UI, natural-run, or all-modules-complete status is warranted from these source fixtures.

## Resolution and final re-review

### Re-review at 2026-10-10 15:03 UTC

**F1–F4 are CLOSED.** The reviewer independently reran all original exploit shapes against the corrected code, with eight total branches. Every attempt was rejected before the protected output was written. Active app/state/plist bytes remained unchanged; the intermediate retained B inventory remained intact; a normally located rollback could still be prepared after the refused history write.

The executable recheck is `analysis/independent_verify_boundaries.py`; the actual result with timestamps, Python version, exact source SHA values, and rejection codes is `analysis/independent_boundary_verification.json`. This run exited 0. It does not rely solely on the author's regression-test assertions.

The five final native guard pins were independently parsed with AST and compared with file bytes and `analysis/final_guard_pins.json`. The reviewer also loaded the guard in a fresh isolated `python -I` interpreter. It compiled the verified closure successfully, without reading any live owner binding or invoking a service. Result: `analysis/independent_native_pin_verification.json`, exit 0. This establishes the fresh-process path only: same-origin modules already imported by a long-lived embedding process are reused and are not separately attested as in-memory bytecode. Deployment must not generalize this fresh-process evidence to an unverified embedding environment.

The reviewer read the final clean-environment full-suite receipt and log: `logs/final-locked-suite.json` / `.log`, command `testenv_final/bin/python -m pytest -q -p no:cacheprovider`, **104 passed in 6.93 seconds**, exit 0. The previous full-suite run in the environment with duplicate installed metadata is not the final environment evidence. The native constant audit in `logs/final-native-frozen-pins.json` records 47 unchanged historical constants; the reviewed native script SHA was `059c892008db468f4b3691de944bb762a84f769e8225351b57483308d686ccae`.

### F5 — P2: malformed shared-path declarations are accepted

The final schema pass found that shared declarations did not receive the wildcard rejection already applied to ordinary owned paths, nor an ancestor-overlap check across owned/shared paths. An approved synthetic contract with shared declaration `shared/*.py` or `shared` and exact alpha ownership of `shared/registry.py` was accepted, allowing the registry to change. Both ambiguous declarations should fail closed under the implementation plan's exact-file, non-overlapping contract rule; they should not silently change the intended shared boundary.

Evidence: `analysis/review_shared_contract_repro.json`. Required narrow fix: apply the same canonical exact-file restrictions to shared paths and reject ancestor/descendant ownership overlaps. This does not require implementing joint integration. Sent to the author after the 104-test run.

### Final re-review at 2026-10-10 15:06 UTC

**F5 is CLOSED.** The corrected schema rejects wildcard shared declarations with `API_BUSINESS_SOURCE_PATH_FORBIDDEN` and ancestor overlap with `API_BUSINESS_PATH_OWNER_OVERLAP`. The independent verification script now reruns all original findings: **10 branches passed**, exit 0, using the clean `testenv_final` interpreter. The previous eight-branch record is preserved as `analysis/independent_boundary_verification-r1.json`; the final record is `analysis/independent_boundary_verification.json`.

The reviewer reread `logs/final-locked-suite-r2.json` and `.log`: the complete available suite passed **106 tests in 6.35 seconds**, exit 0. It used the clean Python 3.14.6 environment and the bare command `testenv_final/bin/python -m pytest -q -p no:cacheprovider`, without selectors or skips. This supersedes the 104-test revision as the final source-suite result.

After the ownership-schema fix, all five guard hashes were independently checked again, and the fresh `python -I` guard-loader check passed again. The reviewer independently compared all **47 original uppercase constant AST values** with the historical script and found none changed. Final proof: `analysis/independent_native_pin_verification.json`; the prior revision remains in the `-r1.json` record.

| Final reviewed source | SHA-256 |
| --- | --- |
| `ops/api_business_modules.py` | `0c5b8bc454fb5ae3c55df8bf9a01d935abc14913e9a105b78cfa449ee6d85fc5` |
| `ops/api_release_integration.py` | `9cda26b37c8d0912aa007323f7eefce4e23f7ddc8a58a57a0e7935792ef6040c` |
| `ops/build_release_candidate.py` | `09314d301640f97a0b95b0fd66107d2bfd2252d0b93c90b294da3b9ff9ae573b` |
| `ops/prepare_api_only_cutover.py` | `db42d1c392799b531adf65b2f20748790ab37a9f888c73a3c8bd0e7b9744a9de` |
| `publisher_reference/api_only_cutover_r2_ready.py` | `2b74e2193c7924b0c580129677738f3c766b938aea4d32341a0a7798ddfe7cd3` |
| `tests/test_api_business_modules.py` | `c0db71e9b6500bf86f31ecbb87d7de163a110329b926f87e333dcb0b76ab0217` |
| `tests/test_api_native_module_guard.py` | `3c4abe1ec737d48683f50bf1b3fb291744caf805d2fdc8c63450823ef9ea4455` |

### Final readiness boundary

The code is suitable for delivery as an independently reviewed, synthetic-tested candidate. **Production execution is NOT APPROVED by this review.** The following are still required before a real change can be evaluated:

- Bind the then-current complete immutable active release, manifest/inventory/generation, exact gateway launch identity, static/build identity, and real publisher/staging command to fresh read-only evidence.
- Approve real source owners, exact paths/routes/dependencies, external default data roots, and state compatibility using actual source/build/runtime evidence. Synthetic A/B approval is not production authority.
- Resolve or explicitly stop on non-running/unknown recovery states. Passing the test that reports `ROLLBACK_INCOMPLETE` does not establish old-release health, crash continuity, or service availability.
- Obtain the separately required real-service authorization. This task supplied no permission to reload launchd or deploy the 8873 service.

Shared/frontend joint integration, actual Mac reload/readback, production API/UI behavior, and natural-run behavior remain outside the verified outcome. Historical reference call sites are demonstrated; connection to the current native publisher is still `CANNOT_CONFIRM`. These are material delivery limits, not open claims of completed production acceptance.
