> 本文保留初次跨日修复阶段的计划/证据。独立审查后追加的 exact journal 缺失拒绝及最终整合结果，以交付根 README.md、VALIDATION.md、CHANGE_MANIFEST.json 为准；本文旧测试数量不是最终总数。

# V5 current recovery plan: minimal change and verification scope

## Fixed inputs and root cause

Manager source baseline: `3d9541aca3e5d28e94109609940503cca239b9fe`.
The original manager capsule and its source descriptor remain unchanged.

The original refresh path computes a dynamic workspace using the supplied aware
`now`, writes a manual owner plan, and independently verifies the exact run and
attempt. The original ordinary `view=auto` read instead sends every target earlier
than the Hong Kong date of `now` through historical pre-session qualification.
Consequently, the fixed target `20261009` saved on the actual later date returns a
run and SHA, but its immediate ordinary read returns
`HISTORY_QUALIFIED_SAVED_PLAN_MISSING` and no run. This was reproduced unchanged on
the fixed original revision-chain fixture before implementing the repair.

## Minimal implementation plan

1. Add V5 adapter routing for a separate `current_recovery` owner store below the
   marked manager output root. Only a cross-day refresh creates this store. The
   same frozen owner writes the same original plan and attempt formats there.
   Existing `workspace_plans`, run files and their `latest.json` remain untouched.
2. On a past-target `auto` or `dynamic` read, use that store only when its exact
   target `latest.json` exists. Dispatch that read to the original dynamic owner
   projection and original saved-input/attempt comparison. Preserve native
   rejection statuses for changed inputs, unavailable cutoff, or invalid attempt.
3. Identify successful recovery consumption as `CURRENT_RECOVERY`; identify the
   read mode, requested view, actual supplied cutoff, underlying owner dynamic
   view, and nonhistorical scope explicitly. Keep the saved run and SHA unchanged.
   Expose `readback.store_relative` so the committed owner files are addressable.
4. Explicit `historical` reads, and ordinary auto reads without a recovery plan
   for that exact target, continue through the original history owner and original
   root. Do not make recovery data eligible for historical PIT.
5. Cover fixed-date cross-day failure, same-day behavior, actual generated times,
   old-byte stability, changed inputs, repeated reads, exact-target store
   selection, invalid attempts, future `now`, path safety, and loopback ordinary
   API query readback. Extend the existing fixed revision-chain test to verify
   consumed revised announcement identity and stale readback after removal.

Future `now` remains rejected by `MANAGER_FUTURE_CUTOFF`. Future target dates retain
the original next-session plan capability; no new future-target restriction is
introduced. Production BUY, Stage, native selection/admission, V4, and original
history code are outside the change.

## Runtime and acceptance boundary

Initial reproduction runtime: Linux x86_64, CPython 3.12.14, pandas installed,
pyarrow absent. This is compatibility evidence, not the required Mac CPython
3.14.6 locked-dependency or real Chrome acceptance. The e06d fixture is synthetic
and runs its real original owner chain locally; it is not the private 392-article
business input. No private assets, 392 decisions, reviewer PASS, or natural run
evidence are synthesized. Follow-up logs record the exact interpreter used.

Frozen sources were obtained and checked per file by the parent task; this is not
a claim that the unavailable binary ZIP itself was downloaded and verified.
