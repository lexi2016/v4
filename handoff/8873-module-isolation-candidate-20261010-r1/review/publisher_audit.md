# Publisher / launcher seam audit for Issue #30

Date: 2026-10-10. Initial scope: read-only source investigation, with implementation and failure-test recommendations. Sections 1–9 describe the original fixed source. An authorized implementation follow-up and its verification status are recorded in section 10. No real launcher or service was invoked and no external messages were sent.

## 1. Main finding

The supplied historical publisher gives an exact, reusable **8873 plist replacement and launchctl boundary**. Its mutation is in `api_only_cutover_r2_ready.py::_run_switch`: second preflight, `bootout`, confirmation of unloaded job, candidate revalidation, `_atomic_replace_bytes(ACTIVE_API_PLIST, ...)`, `bootstrap`, then runtime/HTTP/static readback. Preserve and guard that callsite rather than implementing another switcher.

The actual **current** gateway caller and the **formal immutable-release staging/copy operation** are not in the supplied evidence. Both remain `CANNOT_CONFIRM`. A fully patched historical reference can demonstrate guard placement and be tested with isolated adapters; it cannot establish current Mac wiring, current active identity, production readiness, or live failure recovery.

The current canonical candidate helpers are a suitable base for business-module validation, but their `gateway/stage/manager` values denote service roles. The `stage`/`manager` role paths lead to 8874/8875 and must not be used as business module identities for this task. Keep every business change on role `gateway`, base role `gateway`, the existing `com.lexi.v35.api-only` label, the original plist, and 127.0.0.1:8873.

## 2. Evidence and fixed provenance

The audit read the full relevant functions from these fixed commits and compared the downloaded source SHA values below.

| Evidence | Fixed source | SHA256 of materialized file |
| --- | --- | --- |
| Historical actual switch reference | `a0a0b88dc133d14ee5763569272c174bcd7cc445`, `handoff/api-module-release-20261008/source/actual_cutover_reference/api_only_cutover_r2_ready.py` | `ddb7c5b5b95aed1e2e9fb8a592503b88ec3966f6e34c9350c47648bb0f97ce4a` |
| Current integration core | `f615f4edcf4eb57aa6cf9ab407f2c2c2ed329a9b`, `handoff/8873-module-isolation-issue-20261010-r1/source/canonical-worktree/ops/api_release_integration.py` | `718dfd1ba18facfb4204e30c557a330bc3a6a45b1636a18ff95a76263e697c9c` |
| Current builder | Same current commit/package, `source/canonical-worktree/ops/build_release_candidate.py` | `6b34291924d1f5099e2af2603311b94029c415c077dcc5f564ae58eccb566561` |
| Current plan renderer | Same current commit/package, `source/canonical-worktree/ops/prepare_api_only_cutover.py` | `e12bd6d2ce53f5038e5a52412fa19dd9b673501302016a831820776b38a14c3c` |

Source labels used below:

- **H**: [historical actual switch reference](https://github.com/lexi2016/v4/blob/a0a0b88dc133d14ee5763569272c174bcd7cc445/handoff/api-module-release-20261008/source/actual_cutover_reference/api_only_cutover_r2_ready.py).
- **I**: [current integration core](https://github.com/lexi2016/v4/blob/f615f4edcf4eb57aa6cf9ab407f2c2c2ed329a9b/handoff/8873-module-isolation-issue-20261010-r1/source/canonical-worktree/ops/api_release_integration.py).
- **B**: [current builder](https://github.com/lexi2016/v4/blob/f615f4edcf4eb57aa6cf9ab407f2c2c2ed329a9b/handoff/8873-module-isolation-issue-20261010-r1/source/canonical-worktree/ops/build_release_candidate.py).
- **P**: [current plan renderer](https://github.com/lexi2016/v4/blob/f615f4edcf4eb57aa6cf9ab407f2c2c2ed329a9b/handoff/8873-module-isolation-issue-20261010-r1/source/canonical-worktree/ops/prepare_api_only_cutover.py).
- **L**: [owned interprocess lock](https://github.com/lexi2016/v4/blob/f615f4edcf4eb57aa6cf9ab407f2c2c2ed329a9b/handoff/8873-module-isolation-issue-20261010-r1/source/canonical-worktree/infrastructure/interprocess_lock.py).
- **OLD**: [historical handoff README](https://github.com/lexi2016/v4/blob/a0a0b88dc133d14ee5763569272c174bcd7cc445/handoff/api-module-release-20261008/README.md), especially sections 3 and 5.
- **CHAIN**: [current publication-chain evidence](https://github.com/lexi2016/v4/blob/f615f4edcf4eb57aa6cf9ab407f2c2c2ed329a9b/handoff/8873-module-isolation-issue-20261010-r1/PUBLICATION_CHAIN.md), especially sections 2 and 3.
- **TASK**: [current implementation task](https://github.com/lexi2016/v4/blob/f615f4edcf4eb57aa6cf9ab407f2c2c2ed329a9b/handoff/8873-module-isolation-issue-20261010-r1/CHAT_TASK.md).

| Claim | Evidence status |
| --- | --- |
| Exact historical 8873 mutation callsite | Established by H and identified as the actual 10/8 switch by OLD section 3. |
| Current candidate generation and plan generation | Established statically by B/P; neither calls launchctl. |
| Current runtime-B calls the canonical helpers | `CANNOT_CONFIRM`; CHAIN says the publisher modules are absent from the runtime-B source snapshot and live caller was not found/verified. |
| Actual formal release staging / copying / freezing entrypoint | `CANNOT_CONFIRM`; H validates an existing stage receipt and existing formal release; the producer of that receipt is absent. |
| Current active release, complete manifest, launch identity | `CANNOT_CONFIRM` for deployment use; TASK requires a fresh read and says the package snapshot cannot replace it. |
| Same-gateway business-module rollback | Absent from current code; H restores a whole preimage and P describes role-local rollback. |
| All launcher failures preserve continuous service | Not established and inconsistent with H's deliberate bootout-before-bootstrap sequence. |

## 3. Exact historical trace and existing guarantees

### 3.1 Plan and candidate loading

`H::_load_plan` (170–257) binds task root, target release/app roots, release ID, inventory hash, several fixed receipt paths and SHA values, and allowed write paths. These are hardcoded historical identities, not portable defaults. Do not silently repin or weaken them to make a new module candidate pass.

`H::_load_candidate_release` (447–520) requires an already existing `release_root/app` and `release-manifest.json`, checks manifest identity and the pinned full app inventory, compares that inventory with the task's source candidate app, verifies manager-specific review/delta receipts, checks static HTML/assets, and verifies `api_release_r2_stage_receipt.json` with status `STAGED_AND_VERIFIED_NOT_DEPLOYED`. It does **not** construct, copy, move, or freeze the release. In particular, the receipt consumed at 502–514 is evidence of a prior step whose actual publisher implementation is not supplied.

The old inventory check proves candidate self-consistency and identity relative to the old task candidate. It never compares the candidate to the current active release plus a declared complete delta. That is the gap to close by calling I rather than replacing the inventory algorithm.

`H::_load_inventory_backend` (389–405) dynamically executes a pinned builder file and relies on its `inventory_tree`/`inventory_digest`. If adding another dynamic guard import, avoid reproducing the historical unpinned guard dependency problem described separately in OLD. A hash of only the outer Python file does not bind any modules that file subsequently imports. The executed guard, policy/role contract, lock implementation, and their import closure must come from an independently identified checked-in or installed tool root, with dependency identity captured before mutation.

### 3.2 Existing preflight

`H::_preflight` (654–723) loads review receipts and immutable candidate evidence, compares the active API plist SHA and metadata, checks scheduler plist and disabled-binding SHA values, compares both on-disk and loaded runtime release identities, regenerates and compares the staged plist/diff, and performs historical GET readback. This is a strong place to add the common base/delta/owner verifier, but calling it only here is insufficient unless it runs under the shared lock and is repeated at the mutation boundary.

`H::_candidate_plist_bytes` (294–332) and `_staged_plist_diff` (335–386) are useful preservation checks. They limit changed environment keys to `V35_APP_ROOT`, `V35_RELEASE_ID`, `V35_RELEASE_MANIFEST_PATH`, `V35_RELEASE_MANIFEST_SHA256`, and `PYTHONPATH`, with `WorkingDirectory` adjusted to the new app root. Remaining environment, command shape, manager state binding, disabled binding, safety values, and unrelated plist top-level fields are preserved.

### 3.3 Actual pointer and service mutation

`H::main` enters `_locked()` for `execute` or `rollback` (1652–1661). `_locked()` currently uses `_switch_lock()`, whose file is `_operation_root() / '.api_only_cutover.lock'` (1608–1626). Since `_operation_root()` is below this task's evidence directory (1318–1325), another task's publisher does not contend on the same lock. This confirms OLD R4 from executable code.

The exact forward sequence is `H::_run_switch` (1452–1539):

1. Check explicit confirmation and supplied expected current/staged plist SHA values; initial preflight at 1456.
2. Write exclusive preimage backup, metadata, preflight evidence, and a `PREPARED` receipt at 1468–1486.
3. Repeat preflight immediately before service stop, compare its before identity with the original one, then mark `bootout_started=True` at 1491–1495.
4. `launchctl bootout` at 1496; confirm `NOT_LOADED` and unchanged current plist at 1497–1501.
5. Recheck read-only scheduler/binding and candidate at 1502–1504.
6. **Actual plist mutation:** `_atomic_replace_bytes(ACTIVE_API_PLIST, staged_raw, ACTIVE_API_PLIST, expected_current_sha=before_sha)` at 1505–1506.
7. Confirm installed SHA, `launchctl bootstrap` at 1509, then `_wait_for_candidate` at 1510–1512.
8. Recheck scheduler and write verified receipt at 1513–1528. Any caught exception after step 3 attempts `_restore_after_failure` at 1535–1539.

`H::_atomic_replace_bytes` (899–931) creates a same-directory temporary file with exclusive create, flushes and fsyncs it, applies metadata, rechecks current inode and SHA, then calls `os.replace` at 921. It fsyncs the containing directory and checks installed SHA/metadata. This is an atomic file replacement with a cooperative precondition check; it is not an operating-system compare-and-swap primitive that can exclude an uncooperative writer between the last check and rename. The common lock makes that protocol meaningful when every publisher participates.

## 4. Failure atomicity and limitations

| Failure point in H | Existing behavior and practical limit |
| --- | --- |
| Initial/second preflight before `bootout_started` | Rejects before service mutation. Second-preflight failures record `ABORTED_BEFORE_BOOTOUT`. |
| Bootout returns failure while old job and old plist remain | Recovery recognizes old identity plus old SHA and verifies OpenAPI; records `OLD_API_REMAINS_LOADED`. |
| Bootout succeeds, package/CAS/temp write fails before rename | Old plist remains but service has been stopped. Recovery can bootstrap the old release when it can confirm `NOT_LOADED`. |
| Rename succeeds but directory fsync or postcondition fails | Exception is inside the recovery region because `bootout_started` is already true. If the current plist has the candidate SHA and no unknown job is present, recovery replaces it with the immediate preimage and bootstraps that release. |
| Bootstrap/health fails and candidate is running with recognized identity | Recovery stops the recognized candidate, restores the preimage, starts it, and checks old runtime/OpenAPI. This is recovery after an interruption, not uninterrupted availability. |
| Candidate is loaded but is not in `state=running` | `H::_loaded_identity` rejects before extracting release identity (585–599); `_observe_loaded` maps this to `LOADED_UNVERIFIED` with `identity=None` (624–625). Recovery does not boot out that state and fails its required `NOT_LOADED` check (1384–1398), returning `ROLLBACK_INCOMPLETE`. |
| Unknown loaded identity, third-party plist SHA, symlink or invalid path | Recovery refuses to overwrite/stop an unknown state; reports `ROLLBACK_INCOMPLETE`. This is appropriate refusal, but cannot satisfy an unconditional old-active/healthy claim. |
| Process death or kill after bootout / rename | `except Exception` does not provide crash recovery or restart a launcher after abrupt termination. The durable preimage is useful evidence, but automatic recovery is not established. |
| Restore/bootstrap/readback/receipt I/O failure | Recovery may remain incomplete. It attempts a receipt but receipt-write failure can also escape; no infallible journal is established. |

Additional precision:

- `H::_restore_after_failure` (1354–1449) validates backup bytes and metadata, restores the immediate previous plist, and can recreate a missing active plist using `_create_preimage_exclusive` (943–964). The separate double-link/hidden-claim defect mentioned in OLD was an earlier tool's synthetic failure; do not attribute that defect to this reference, whose normal installation uses `os.replace` and whose recovery explicitly handles absence.
- Existing recovery identity checks are intentionally conservative. To improve the non-running-candidate case, first separate launchd's bound release identity from its running/readiness state, then permit stop only when the bound job identity is positively established as the candidate. Do not turn `UNKNOWN` into permission to stop a job. This is an additional behavioral change that needs an isolated test; it should not be hidden inside a guard-only patch.
- Old readback is manager-specific: `_wait_for_candidate` (1288–1310) verifies runtime identity, OpenAPI manager route, manager-selection HTML/assets, and two pinned historical analysis responses. `_verify_historical_product_readback` deliberately leaves workspace status `CANNOT_CONFIRM` (1244–1262). These checks do not establish all five business-module behaviors or a browser reload.

## 5. Minimum extension to the existing core

I already provides `read_active_release`, `build_integrated_app`, `_verify_delta_files`, `verify_api_release_candidate`, `shared_api_release_lock`, and `assert_api_release_lock`. Reuse these exact mechanics for any business-module wrapper. Avoid a second active pointer, inventory scheme, or lock.

### 5.1 Business and generation binding

Add a module ownership/policy record and module-publication record around the existing integration block. Bind policy identity, business `module_id`, current accepted generation, source release ID/manifest/inventory identity, authorized target paths, before/after identities, and any joint shared-owner approval. Recompute policy ownership against the actual candidate delta both at build time and immediately before publishing; do not trust only a copied `module_id` string.

`I::_base_binding` (338–346) currently binds release/app/manifest paths, release ID, manifest SHA, inventory SHA, and entry count. It omits a publication generation and the whole plist SHA. Retain that format for existing core compatibility, then add and check generation and precise plist preimage in the business/cutover layer. An accepted generation should be part of the immutable release identity and advanced by a successful forward or reverse-delta publication, not an independent mutable side pointer requiring its own transaction.

The task requires candidates to originate from an active identity read while holding the shared lock. The current `I::build_integrated_app` reads active outside any lease (455–481), and the current builder calls it without a lock (B 405–414 and 574–580). A small wrapper can acquire `shared_api_release_lock(active_plist, role='gateway')`, read/validate the current base, build using that active immutable app, and verify again while still in the lock. The later publish must independently reacquire the same lock and reject the candidate if any accepted generation or full base identity has changed. Building A and B from G may be allowed; committing B after A must reject G rather than silently rebase.

### 5.2 Reverse delta

`H::_run_rollback` (1542–1590) requires exact current candidate plist SHA and runtime identity, then restores the whole preimage. It safely rejects a later release, but does not implement preservation of later modules. The business rollback operation should therefore:

1. Resolve an exact original module publication receipt and original before/after file identities.
2. Read **current** active under the shared gateway lock.
3. Require every reverse target to match the original module's accepted after-image, or reject as a rollback conflict. Verify ownership/policy and shared-dependency safety again.
4. Create a new complete candidate by applying only inverse changes to current active. This new candidate's base is current active, its generation is current+1, and its metadata identifies the reversed receipt.
5. Publish this candidate via the same guarded forward `_run_switch` callsite. If it fails, the immediate pre-switch recovery restores the current release that includes later module changes.

Keep immediate failed-cutover recovery separate from user-requested module rollback. For business-module receipts, reject the legacy whole-plist `rollback` command with a stable `REVERSE_DELTA_REQUIRED` error or route to the new reverse-candidate preparation flow. Do not use A's old whole-release pointer as the rollback target.

The core currently permits additions and modifications, but no deletions: `_validate_delta_receipt` requires a string `after_sha256` (I 363–401), `_verify_delta_files` rejects every removed file (411–415), and `build_integrated_app` unconditionally opens each after-image source (487–516). Inverting an original addition requires an explicit deletion operation or an explicit unsupported-operation refusal. A proper extension must authorize deletions individually, preserve all other inventory entries, and keep path/symlink checks. Do not accidentally weaken the blanket deletion rejection without binding the deletion to the authorized inverse receipt.

If a reversed path is shared and later-module dependency independence cannot be demonstrated, reject the inverse candidate. A matching current file SHA alone does not prove that later code does not depend on the shared addition.

## 6. Minimum patch to the historical reference

A narrow, full patched reference can keep all existing staging checks, metadata/CAS code, launchctl actions, receipts, and recovery logic. The proposed interface shape is:

```python
def _load_candidate_release(plan, *, lock_lease=None,
                            active_pointer='base', require_shared_lock=False): ...

def _preflight(plan, *, lock_lease=None, require_shared_lock=False): ...

def _run_switch(plan, *, confirmation, expected_current_sha,
                expected_staged_sha, lock_lease): ...
```

The minimum placements are:

1. `_switch_lock`/`_locked` delegate to `I::shared_api_release_lock(ACTIVE_API_PLIST, role='gateway')` and yield its actual lease. Keep that lease alive across the complete forward operation, verification, and recovery. The task-private lock can cease to be the publication authority.
2. `_run_switch` asserts the lease immediately at entry, so a direct Python call cannot bypass the lock wrapper.
3. `_load_candidate_release` retains original pinned inventory/stage validation and also invokes the extended common business verifier on the **final release root**, `active_pointer='base'`, with `expected_manifest_sha256` from the checked plan. The mutating path sets `require_shared_lock=True`; plan/staging/read-only preflight can remain observational.
4. Thread the same lease through both `_preflight` calls, then through the package check immediately preceding `_atomic_replace_bytes` at H 1503. Reassert the lease immediately at the write boundary as well. Do not merely write a `requires_lock` field to JSON.
5. After installation, verify `active_pointer='candidate'` and the same business metadata before claiming acceptance, alongside original runtime/readback checks.
6. If retaining old `_run_rollback` for historical emergency use, its candidate check must use `active_pointer='candidate'`; a default base-pointer check would reject because current points at the installed candidate. Require the same actual lease. For business operation rollback, use the reverse candidate procedure above and reject the legacy command.
7. Record accepted policy SHA, module ID, base/current/new generation, delta receipt SHA, whole manifest/inventory SHA, installed plist SHA, and recovery outcome. These are identities, not substitutes for invoking the checks.

Two important implementation constraints:

- Do not make emergency `_restore_after_failure` depend on a successful revalidation of the failing candidate. The candidate may have failed integrity/health checks. Recovery needs the trusted preimage, current-pointer match, known loaded identity, and the retained lock. Requiring the candidate to pass again can prevent the very restoration the guard failure requires.
- The historical constants, confirmation text, review receipt formats, and accepted success status are all 10/8-specific. Adding guards must make a legacy package without base/delta fail closed. This patched reference must remain marked `REFERENCE_ADAPTER_NOT_CURRENTLY_BOUND` until an authorized operator supplies the genuine current command, regenerated plan, final release, full guard import closure, and active identity. Do not change frozen pins simply to get an old fixture through the new gate.

## 7. Builder/plan integration traps

`B::build_module_candidate` already calls `build_integrated_app` (405–414) and `P::render_module_cutover` (475–485). However it requires a `deployment/api_module_contracts.json` in the candidate (417–427), writes service `module_role`, and supports role-local ports. This alone does not implement business ownership. The business wrapper must explicitly target the original gateway and cannot depend on introducing the 8874/8875 proxy topology.

**Avoid blindly reusing legacy `P::render_cutover` for business publication.** It creates a candidate manager state tree and `.commits` at 535–536, then passes that new root to `rewrite_api_only_plist` at 547–554. This changes `V4_MANAGER_RESEARCH_STATE_ROOT`, contrary to the current task's preservation boundary. The lower-level `rewrite_api_only_plist(..., candidate_manager_state_root=None)` preserves that root; a same-gateway module plan should use this behavior and explicitly verify the allowed environment/top-level delta as H already does.

`P::render_module_cutover` preserves inherited state roots, but inserts role environment and can choose other labels/ports. Pin gateway role and validate label/host/port at its business entry; do not accept service-role selection as business selection.

Both renderers are preparatory only. `P::render_cutover` even outputs descriptive future `cp`/launchctl strings (600–609). Those strings do not execute the common lock/CAS protocol and must not become a new production install command. The tested historical adapter remains the relevant concrete mutation seam.

There is also a relocation boundary: candidate manifests and plans contain absolute candidate root/app/manifest paths. A formal publisher cannot copy to a new root and reuse the old manifest/plist SHA. The missing formal staging operation must finalize the target-root-bound manifest and receipt, freeze inventory/modes consistently, and run the common verifier against that final root before the plist points to it. Its implementation is `CANNOT_CONFIRM` in this package; document the required interface without inventing an existing command.

Finally, `L` imports `infrastructure.owned_io`, which is absent from the supplied source snapshot. Full lock behavior cannot be certified by a fake replacement module. Obtain the exact dependency from the corresponding full checkout and run real subprocess lock tests against it, or report those tests unavailable. `L` deliberately rejects forged, copied, expired, moved, cross-thread, and cross-process leases and uses a persistent kernel `.mutex` inode plus PID/token ownership; preserve this machinery.

## 8. Targeted failure and acceptance tests

All tests below use synthetic private roots, fake launcher/GET adapters, and actual common lock code where dependencies are available. They must never call Mac launchctl, bind 8873, or access owner data. These are recommendations; no tests were executed by this read-only audit.

| Test | Required assertion |
| --- | --- |
| Direct `_run_switch` with absent, forged, expired, wrong-path, wrong-role or foreign lease | Stable rejection before backup/bootout/active writes; use real lease authority tests, not a truthy sentinel. |
| A/B from identical G, A accepted first | B's publish revalidation rejects stale base/generation before bootout; A remains active with unchanged app/static/state hashes. |
| Lock held by another process | Second publisher cannot pass the before-bootout gate or alter plist; lock path is identical across independent task roots. |
| Active plist changes between build and prepare, or between prepare and switch | Exact base/plist/generation mismatch before service action. Include same release fields with changed preserved environment. |
| Candidate mutation after initial preflight | Second preflight rejects before bootout; mutation after second preflight but before rename is caught by immediate revalidation and old release is recovered in the fake launcher. |
| Unlisted source/static/config mutation, removed non-delta path, duplicate/unknown owner, unapproved shared delta | Stable ownership/inventory rejection before service mutation. Full non-target inventory is the oracle. |
| Build/source-copy/temp file failure | Candidate remains visibly incomplete or is safely cleaned only within the invocation-owned root; no active effect. Do not report a partially built manifest as ready. |
| `_atomic_replace_bytes` failure before `os.replace` | Old plist bytes and metadata remain; if bootout occurred, fake launcher returns to the immediate old identity and healthy state. |
| Failure immediately after successful rename, during fsync or postcondition | Candidate pointer may have been installed transiently; recovery restores exact preimage and old fake service, or reports incomplete honestly. Assert final disk and loaded identities together. |
| Bootstrap returns failure but candidate did start | Recovery recognizes and stops only that candidate, restores exact preimage, and verifies it. |
| Candidate loaded but non-running/crashing | Current H produces `ROLLBACK_INCOMPLETE`; a revised recovery must prove the job identity before stopping it. Never make this test pass by treating unknown identity as candidate. |
| Old loaded job with old plist when bootout command errors | Recovery does not stop/restart an already healthy old job unnecessarily and verifies the old identity/readback. |
| Unknown process identity or third-party plist during recovery | Refuses overwrite/stop, preserves evidence, returns explicit incomplete status; never false PASS. |
| Health failure / restored-service bootstrap failure / recovery receipt I/O failure | Distinguish original failure, actual recovery actions, final pointer, final process, and evidence durability; no unconditional old-healthy claim. |
| A then B then inverse A | Reverse candidate is based on current A+B, restores only A's own paths, retains all B/shared/static bytes, increments generation, and runs through the same forward cutover seam. |
| Original A added a file | Inverse deletion is individually authorized and removes only that file; if deletion is unsupported, reject explicitly without creating an accepted candidate. |
| A shared change later depended on by B, or A after-image drift | Reject rollback as conflict before write/reload; do not revert an old whole package. |
| Failure while publishing inverse A from A+B | Emergency recovery returns to immediate pre-switch A+B, not to A's historical parent. |
| State and safety preservation | Staged plist retains all external state/data roots, safety flags, interpreter command, label/host/port, and unrelated fields; synthetic state hashes remain unchanged. |
| Formal finalization / immutable target relocation | Final manifest root, app root, plist manifest path and SHA all agree; stale staged path or changed final inventory rejects. This can validate the required interface but does not prove the missing live producer. |

## 9. Scope conclusion for the parent task

The safe deliverable is an extension of the existing integration core and candidate/plan tools, plus a narrowly patched **historical** publisher reference using the same shared lock and verification logic. Real module rollback is a new inverse candidate sent through the same forward cutover. The existing preimage restoration remains recovery for a single failed transaction.

The precise outstanding production evidence is the current Mac publisher command/script and its code identity, its caller-to-helper binding, the immutable final-release staging function and receipt, fresh active/full manifest/inventory/launch/static identities, and authorization for service actions. Until those are supplied and verified, current publisher integration, live reload/recovery, API/UI/natural behavior, and deployment remain `CANNOT_CONFIRM`.

## 10. Authorized implementation follow-up

The parent subsequently authorized edits only to `work/publisher_reference/api_only_cutover_r2_ready.py` and `work/tests/test_api_native_module_guard.py`, while the parent separately implements the common core extension. The reference now requires the common business-module verifier, threads a real shared gateway lease into `_run_switch`, asserts it at direct entry and before the active write, repeats candidate verification immediately before replacement, and verifies `active_pointer='candidate'` before acceptance. Its receipt includes the accepted business-module proof and `CANNOT_CONFIRM_CURRENT_MAC_BINDING`.

The legacy public whole-plist rollback is rejected with `BUSINESS_MODULE_REVERSE_DELTA_REQUIRED`. Immediate `_restore_after_failure` retains its prior behavior and does not depend on the failed candidate passing verification. No second pointer or launcher was added.

The dynamic historical builder is now validated as evidence but is not executed. The actual common integration inventory is used. A synthetic equivalence check covers read-only and executable modes, ordinary symlinks, and missing-target symlinks against the original builder's inventory interface.

The guard loader checks a fixed five-file SHA closure before executable loading: `ops/api_release_integration.py`, `ops/api_business_modules.py`, `infrastructure/interprocess_lock.py`, `infrastructure/owned_io.py`, and `deployment/api_module_contracts.json`. Fresh modules are compiled from the already verified source bytes, so a forged matching-timestamp bytecode cache cannot execute. Previously imported modules must have the same exact canonical origins. Unexpected package initializers or mismatched closure entries fail closed. The parent subsequently finalized the source closure pins after its core changes stopped; the final test explicitly checks the delivered static pins without overriding them. Reused same-origin modules in an existing interpreter are source-file/origin checked, but their already loaded in-memory bytecode is not separately attested; the fresh standalone invocation is the reviewed execution context.

An AST comparison found all **47 historical top-level constant expressions unchanged**, including old deployment roots, review/release SHA pins, labels, service URL, confirmation strings, and safety/environment allowlists. Evidence: `logs/native-frozen-pins.json`.

Verification evidence at this addendum's creation:

- `logs/native-red.log`: 7 failures on the original reference for the missing shared lease, direct-entry lease checking, import pin guard, and forbidden whole-release rollback behavior.
- `logs/native-green-initial.log`: those 7 checks passed after the narrow patch.
- `logs/native-flow-first.log`: 16 isolated tests passed, including the actual native switch with real common module guards and filesystem replacement plus synthetic external launchd/HTTP/clock adapters.
- `logs/native-flow-red.log`: a sensitivity mutation bypassing only the new business verification was detected by both owner-drift tests; both failed with **DID NOT RAISE**, showing that the original mutation path would otherwise accept unapproved drift. The production file was not changed for that run.
- `logs/native-original-replay-blocked.log`: a separate attempt to replay the full old reference against the newer builder failed before the behavioral oracle because its dynamic import omits a `sys.modules` registration now required by the current stage-refactor binder. This is recorded as an unusable replay, not counted as proof of the owner regression.
- `logs/native-pin-pending.log`: 19 passed; the sole failure is the deliberately unfilled delivered-closure pin test. This must be followed by a fresh successful run after the parent freezes the five reviewed hashes.
- `logs/native-full-suite-pin-pending.log`: the bare project pytest command ran all materialized tests, with **69 passed, 1 failed**. The same unfilled-closure-pin gate was the only failure; no other project test failures were observed.

The tests exercise owner-contract drift before service action and after bootout, before/after atomic-replacement failure, candidate health failure, a bootstrap error after candidate startup, actual candidate pointer readback, state preservation, missing/forged/expired leases, pinned source loading, foreign cached origins, bytecode substitution, and whole-release rollback rejection. They deliberately document that a loaded but non-running candidate produces `ROLLBACK_INCOMPLETE`; they do not disguise that limitation as successful old-service recovery. All releases, plists, product receipts, and state fixtures are synthetic temporary files.

### Staged launch-binding follow-up

Inspection of the candidate-only verification seam found one concrete staging gap. `I::_plist_environment` accepts consistent release identities declared in both `ProgramArguments` and `EnvironmentVariables`. Historical `H::_candidate_plist_bytes`, however, rewrites only the former, while `H::_staged_plist_diff` requires the latter to remain byte-equivalent as a top-level value. Such a valid active plist could therefore generate a staged plist with contradictory old/new release identities. The common candidate-pointer verifier would reject after bootstrap, but the configuration should be rejected before any service action.

The patched reference now runs the already pinned common `_plist_environment` parser over the derived staged payload and checks its four release-identity values before emitting staged bytes. It deliberately preserves the historical rewrite allowlist: a dual-encoded active identity that becomes inconsistent is rejected, rather than silently expanding the set of changed fields. The common parser is included in the guarded callable interface check. Existing `_candidate_plist_bytes` safety checks, `_staged_plist_diff` exact command/argument/top-level preservation, and the common base/candidate launch-binding digest together retain the launch, external state, and safety bindings.

`logs/native-staged-red.log` records the new focused regression failing with **DID NOT RAISE** before this check. `logs/native-staged-green.log` records **2 passed** afterward: the inconsistent staged identity is refused before its staged file or operation receipt exists, and the ordinary native switch still reaches candidate readback. The source active plist remains the valid initial release and the synthetic state sentinel remains unchanged. No full-suite rerun or production-pin update was performed during this follow-up; the parent is still freezing the common core.

## 11. Final verification after the reviewed closure was frozen

The parent finalized all five static closure hashes and supplied a clean `testenv_final` interpreter installed from the required `uv.lock` dependency subset. A fresh full test run, with no test selectors or added skips, completed successfully:

```text
cwd: /workspace/scratch/a245cda1e07c/work
/workspace/scratch/a245cda1e07c/testenv_final/bin/python -m pytest -q -p no:cacheprovider
104 passed in 6.93s
exit code: 0
```

The complete output is `logs/final-locked-suite.log`; its command, working directory, timestamps, exit code, and scope are recorded in `logs/final-locked-suite.json`. This final run includes the static delivered-pin gate, the staged dual-identity regression, and the full materialized core, legacy-entry, and native-reference tests. No source or test edits were made during this final verification.

The preceding `logs/final-full-suite.log` also reported 104 passing tests, but the parent discovered duplicate distribution metadata in that older environment. That evidence is retained without alteration; it is not the final locked-environment result. All earlier red and intermediate failure logs are also retained.

A fresh AST comparison reconfirmed **47 original historical top-level constants, zero changed or missing expressions**. `logs/final-native-frozen-pins.json` records the complete names, original source SHA `ddb7c5b5b95aed1e2e9fb8a592503b88ec3966f6e34c9350c47648bb0f97ce4a`, and final patched reference SHA `059c892008db468f4b3691de944bb762a84f769e8225351b57483308d686ccae`.

These results validate the isolated implementation and historical callsite adaptation. The current Mac caller binding, immutable formal-release producer, real service actions, live readback, and owner behavior remain `CANNOT_CONFIRM`; this test run does not replace their missing evidence or service-action authorization. The documented loaded-but-non-running recovery limitation remains explicit.

## 12. Final r2 verification after the shared-path review fix

The parent subsequently fixed the reviewed shared-path glob and ancestor-overlap cases in the business helper, added their regression coverage, and repinned the five-file guard closure. **Use the r2 receipts and reference SHA in this section for the final delivered code.** Section 11 and its receipts remain preserved evidence for the earlier code state.

The parent's fresh complete run in the clean locked environment is recorded in `logs/final-locked-suite-r2.json` and `logs/final-locked-suite-r2.log`. I read both completed files directly: the command was `/workspace/scratch/a245cda1e07c/testenv_final/bin/python -m pytest -q -p no:cacheprovider`, run from `work`, and the actual result was **106 passed in 6.35s, exit code 0**. I did not duplicate that test run or add optional tests.

My subsequent AST verification is `logs/final-native-frozen-pins-r2.json`: **47 original historical constants, zero changed or missing expressions, PASS**. The final r2 patched publisher reference SHA-256 is:

```text
2b74e2193c7924b0c580129677738f3c766b938aea4d32341a0a7798ddfe7cd3
```

The original historical source SHA remains `ddb7c5b5b95aed1e2e9fb8a592503b88ec3966f6e34c9350c47648bb0f97ce4a`. No earlier evidence files were rewritten. The isolation, current-live-binding, formal-publisher, and non-running recovery qualifications above continue to apply.
