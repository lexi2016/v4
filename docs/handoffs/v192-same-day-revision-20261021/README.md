# V192 same-day revision adapter · static handoff

This batch adds one opt-in operation module and its isolated acceptance tests. It has no import-time action or executable live CLI. It does not select stocks, regenerate formula inputs, change generic store behavior, or claim that two roots are atomic.

Current R4 status: `TEST_ORACLE_STATIC_CORRECTION_NOT_EXECUTED`. Independent R2 returned 7 failed / 42 passed / 49 total. Independent R3 returned 3 failed / 16 passed / 42 deselected; its three failures caught the expected STOPs and differed only by the normally released dead-child local import lock. Original results are retained in `review_round2/` and `review_round3/`. Payload remains unchanged at `1eee2f9731afb12bf6672b73822c0a828c27f24553898cd4193998d0304bb710`. R4 tests, deployment and real apply have not run. Whole-pool real admission remains `CANNOT_CONFIRM`.

The controller's explicit post-third-round ruling authorizes only the three test-oracle corrections in `R4_ACCEPTANCE_PLAN.md`. Only the exact operation's `local_root/.import.lock` is newly excluded, after schema/PID/claim matching and independent ESRCH proof. All business bytes and live/unknown/replaced-lock assertions remain. R4 is not an automatic continuation of business patching; another failure must return to the controller.

Revision R2 addressed the controller-relayed round 1 `STATIC_FAIL`. Round 1 did not execute unit tests or numerical evaluation. Original payload/test/receipt snapshots and the three findings are retained in `review_round1/`; its initial R2 Writer handoff had not run tests.

That R2 handoff was subsequently tested by the independent Reviewer and failed on seven actual process-exit lock cases. R3 preserves this FAIL and uses the controller's revised bounded original-lock recovery requirement below. Its incremental acceptance command is in `R3_ACCEPTANCE_PLAN.md`; do not repeat the 42 previously passing cases without new directly relevant evidence.

## Frozen behavior

`SameDayRevision(binding, local_store=existing_store, runtime=Runtime())` exposes `apply()` and `rollback()`. Calling either is a write operation and is not authorized by this handoff. The controller must separately freeze the real input/old identities, consume the independent whole-pool PASS, register execution and authorize its executor.

The module uses the exact APP and SHARED release roots embedded in its constants. All ten controller-provided dependency SHA values are fixed. Imports from another application tree are rejected. Use a dedicated Python process and `PYTHONDONTWRITEBYTECODE=1` so release imports do not create bytecode caches.

The actual caller at `APP/ops/materialize_scheduled_preselection.py:117` calls the original shared projection. Lines 259-261 publish via `PreselectionPoolStore(args.data_root)` with no gate arguments. The original store constructor defaults to `write_gate_context=None, require_write_gate_context=False` (lines 425-434), and `scope_gate.assert_write_allowed` returns immediately for None (lines 396-407). The adapter freezes this existing caller configuration in `write_gate`; it does not introduce a new permit. An enabled caller context and its requirement flag must match the binding, and all original preflight/under-lock gate checks still run. No gate or real permit is written.

Admission pins the independent PASS receipt's bytes and requires its exact scope, independent Writer/Reviewer identities, full candidate seven-field identity, strict generation pointer SHA/id, panel SHA and generation role, all dependency SHA values, dates and original producer universe summary. The original producer JSON evidence and explicit field paths must read back the same signal-date key count and key SHA. The adapter never computes a new universe or treats candidate row count/`whole_pool=true` as evidence of completeness.

The PASS receipt schema consumed here is `v192.whole_pool_independent_pass.v1`: `decision=PASS`, `scope=WHOLE_POOL`, `independent=true`, `partial=false`, distinct nonempty `writer`/`reviewer`, and `binding` equal to the binding's `candidate`, `generation`, `source_panel`, `universe`, `dependencies`, `signal_date`, `target_date`, `safety` fields. This must be the independent reviewer's receipt, or an independently reviewed controller admission record anchored to the original producer evidence. The Writer must not fabricate it for real input. If existing producer metadata lacks the required universe key summary, retain `CANNOT_CONFIRM`; creating such upstream evidence is outside this adapter.

`source_panel.generation_role` is explicitly `selector` or `selector_source`. Its actual path and SHA must equal the corresponding strict generation reader output. A different provenance relationship requires a controller scope decision rather than an adapter fallback. This frozen revision accepts a nonempty READY candidate; an empty-candidate policy is outside its scope.

Generation is dated by the source signal day, 20261020. R3's strict generation call uses `expected_target_date=SIGNAL`, matching original `ops/materialize_shared_v192_preselection.py:36-40`; the V192 pool independently retains target 20261021. Selector/backtest/source/sidecar fixtures contain only signal-day rows. The generic generation reader is unchanged.

`PREPARED` is durable before shared replay and retains the entire verified local old trio and shared old latest entry. The original `_V192ManifestStore` replays the verified candidate CSV with its fixed original SourceSpec, complete seven-field `expected_previous` and `historical_backfill=True`. Its real manifest and receipt are regenerated. Old run bytes remain untouched.

The lock order is local `.import.lock` then shared lock. Replay takes its own shared lock and is called without an already-held shared lock. The adapter reacquires the shared lock, verifies the exact new trio/supersession and projects through the original `build_shared_v192_premarket_pool`. It archives old/new local revisions and uses `_commit_main_snapshot`, merging just A into the current manifest. Both apply and rollback retain other pool entries.

The original shared lock is ASCII `pid:uuid32hex`, created by O_EXCL, with timeout 10 seconds and stale cleanup strictly after mtime age 30 seconds. It does not participate in the local kernel mutex. R3 does not install a new shared lock protocol or use a private mutex as authority to delete a legacy lock. It never unlinks shared `.store.lock`.

After each original shared lock acquisition and before business work/phase saves, R3 persists an operation-specific local control claim containing the exact binding SHA, roots, expected old identity/run, PID/token, lock device/inode/mtime/ctime and root device/inode. Normal original release precedes deletion of only that local claim; an actual process exit retains both. Recovery requires the exact claim and PREPARED record, unchanged lock identity, and `kill(pid,0)` returning ESRCH. A live/reused PID, EPERM, unknown error, malformed/unknown owner, missing claim, binding drift or replacement stops before delegating to original cleanup.

For a proved dead owner only, the acquisition stage waits and rechecks token/inode/death until the existing stale window, reserving the unchanged original 10-second timeout inside a 40-second budget. Deadline exhaustion or uncertain clock yields explicit STOP. Original acquisition owns stale handling and O_EXCL; no business phase is rerun merely to wait. After waiting, input identity and the existing write gate are rechecked before existing actual-state CAS. This is the controller-authorized recovery-time revision, not a claim of immediate recovery or an atomic conditional unlink primitive. The original legacy protocol's concurrency policy is unchanged. The wait holds the existing local import lock, so other local writers may remain blocked during this bounded recovery.

Claims are not backfilled from a PID string or old failure report. An R2/legacy orphan without this exact acquisition claim stops even if its PID appears dead. R3 acceptance creates fresh registered fixtures with R3 claims; it does not retroactively adopt the old pytest temporary locks.

Reentry checks actual shared and local identities, including deterministic run id, CSV SHA, provenance and the full superseded identity. Receipt phase alone never grants continuation. Shared new/local old resumes the local commit; both new is idempotent. A third A revision stops. A record can lag as far as PREPARED after the shared commit; pending recovery derives the expected new local identity from the verified immutable new run.

Before invoking original pending reconciliation, the adapter validates the exact A journal and archived sides, and compares all non-A current manifest entries against both journal sides. Drift yields `STOP_PENDING_OTHER_POOL_DRIFT` before any recovery write. Other pending journals are refused. The original unsafe generic reconciliation behavior is not changed.

R2 also requires the physical A artifact/receipt/manifest bytes to equal an exact journal prefix: old/old/old, new/old/old, new/new/old, or new/new/new, matching the original artifact→receipt→manifest commit and reverse restoration order. Missing, noncanonical, third-version or out-of-order A components yield `STOP_LOCAL_A_CAS` before generic reconciliation, even when non-A entries did not change.

Local revision archives are bound to a durable operation `local_archive_intent` before either archive component is created. Every existing component of both planned revisions must match its exact expected canonical bytes before archive writes. An incomplete pair is completed only when the previously persisted intent matches this operation's exact pair; unclaimed partial archives and changed bytes stop. The adapter completes only the missing component and retains the original generic archive validator. Apply and conditional rollback can reenter after a process exit between the old or new archive's two writes; generic store behavior is unchanged.

When shared latest still names the old identity, any retained deterministic target-run directory is refused before PREPARED/replay. The same check runs inside this instance's original replay lock acquisition, closing the check-to-replay gap without a generic-store change. This deliberately includes a complete READY run retained by rollback and an orphaned partial target run: the adapter does not rewrite or assume ownership of either. Such an old-latest/retained-target state requires controller disposition. A latest-new run belonging to the prepared operation still follows the existing verified idempotent path.

Rollback verifies both sides under both locks, restores only this date/role's old shared latest entry, and commits the old local A revision using the current manifest with only A changed. It neither replays old CSV nor rewrites old run trios. An interruption may leave one side restored; reentry completes the conditional rollback. A later apply refuses an operation whose direction is already ROLLBACK. Third-party A changes require controller intervention.

## Registered synthetic acceptance command · historical full scope

The controller creates a separate execution contract with `scope=SYNTHETIC_SAME_DAY_REVISION_ONLY`, `payload_sha256`, and `test_sha256`, then appends its actual RUN_STARTED. Test context JSON contains `contract_path`, `registry_path`, and `execution_id`. The test session refuses missing/mismatched hashes or an execution whose latest event is not RUN_STARTED.

```sh
cd '/Users/lexi/Desktop/学习/.worktrees/v192-projection-repair-20261021-delivery'
PYTHONDONTWRITEBYTECODE=1 NEXT_V192_PUBLISH_ADAPTER_TEST_CONTEXT='/absolute/controller-created-context.json' python3 -m pytest -q -p no:cacheprovider tests/test_v192_same_day_revision.py
```

Use the controller-selected existing interpreter containing pytest/pyarrow and the pinned release dependencies. Do not install or switch environments as part of this batch. Only fixture artifacts under pytest's temporary directory are opened by tests; application/shared release source is read for the real implementations. No live data root, Windows endpoint, account or service is accessed. One fixture uses a bounded local fork with `os._exit(73)` to exercise an actual process exit; all other fault injection is fixture-scoped.

The independent reviewer should inspect the actual diff and run this exact file under a separately registered review execution. Existing accepted 17-field and action-reference tests are outside the changed scope and are not repeated. A synthetic PASS supports only the adapter contract; real source admission, panel publication and API/UI behavior remain separate.

The full-file command above documents the original baseline scope. `R3_ACCEPTANCE_PLAN.md` is the retained executed 19-case scope. Current R4 acceptance uses only the exact three-node command in `R4_ACCEPTANCE_PLAN.md`, with a new contract/RUN_STARTED and current test SHA. The separately scoped 16 R3 passes and 42 R2 passes are reused per the controller's ruling.

## Required real binding · not prepared or admitted

Required top-level fields: `schema`, `revision_mode`, `operation_id`, `signal_date`, `target_date`, `dependencies`, `safety`, `local_root`, `shared_root`, `write_gate`, `expected_previous_shared`, `expected_previous_local`, `candidate`, `generation`, `source_panel`, `universe`, `independent_pass`.

- `expected_previous_shared` and `candidate.identity`: run_id, artifact/manifest/receipt SHA and artifact/manifest/receipt relative paths, all seven required.
- `expected_previous_local`: artifact SHA, raw receipt SHA, artifact relative path and receipt relative path. Whole-manifest SHA is recorded for audit, not used to overwrite another pool's concurrent revision.
- `candidate`: independently passed original-producer store root and seven-field identity. It must be separate from the live shared root.
- `generation`: pointer path, pointer SHA and generation_id. The original strict reader also authenticates all its bound artifacts and source metadata.
- `source_panel`: path, SHA and explicit generation_role. Candidate manifest provenance must name the same panel SHA.
- `universe`: scope=WHOLE_POOL, signal_date, integer key_count, key_sha256, producer_evidence={path,sha256}, and producer_fields mapping signal_date/key_count/key_sha256 to lists of existing JSON field names.
- `independent_pass`: path and SHA of the exact independent whole-pool admission receipt described above.
- `write_gate`: `require_write_gate_context` and `context`; default caller uses `{require_write_gate_context:false,context:null}`. Enabled context serializes its control_dir, expected_permit_sha256, expected_owner_id, expected_release_sha256 and expected_root exactly.

No real binding or whole-pool receipt is invented by this batch. Missing metadata, dependencies, real gate errors and source scope remain `CANNOT_CONFIRM`, with formal apply `NOT_RUN`.
