# Independent combined candidate review — before corrective follow-up

Review date: 2026-10-10. Candidate: `/workspace/scratch/17ec887ca39d/work/interface/V5`.
Runtime actually used: Linux, CPython 3.14.6, `/workspace/scratch/17ec887ca39d/runtime/v5-env/bin/python`.
No candidate files were modified by this review. The accompanying probe's before/after source hashes are identical.

**Disposition: changes requested. Critical: 0. Important: 4. Minor: 0.**

## Important 1 — real callback timestamps are rejected as future

Locations: `src/v5_shadow/daily_review_handoff.py:113` and `:126`; rejecting condition is `:96`.

`_exchange` samples the default wall clock before calling `channel.submit` or `channel.poll`. It then passes that earlier time to `validate_review_return`. A valid host callback that stamps its acknowledgement/heartbeat inside the call necessarily returns a timestamp later than that snapshot. The implementation consequently rejects an ordinary valid response as `BLOCKED_INVALID_REVIEW_RETURN`.

The independent probe calls both public methods without supplying `now`. Its synthetic host callback sets `submitted_at` and `heartbeat_at` with the actual UTC clock inside the callback. Both operations return `BLOCKED_INVALID_REVIEW_RETURN`. No artificial delay is necessary. Existing tests supply a fixed `now` that follows their static receipt timestamps, so they do not exercise this normal production path.

User result: the newly callable interface cannot accept normal fresh acknowledgements and poll heartbeats. A submission may already have happened externally while the caller receives a blocked transport result.

Minimal correction: retain the initial time for pre-submission task/deadline admission, but sample wall time again after the callback when validating the return. Preserve the explicitly injected deterministic clock for tests. Test both submit and poll with return timestamps generated during the call, and keep genuinely future receipts rejected.

## Important 2 — missing recovery journals still yield consumed CURRENT_RECOVERY

Location: `src/v5_shadow/manager_plan.py:454-460`, through the original owner's `workspace.py:792-799` and `:829-835`.

The new recovery path delegates consumption entirely to the owner's dynamic read. That owner intentionally returns `None` from `verified_plan_attempt` when a manual legacy plan has no exact journal. `_readback_plan` permits that legacy path after source replay. This is inappropriate for the new `current_recovery` store, whose save path explicitly requires an independently verified exact journal.

The probe saves a new recovery plan, deletes `current_recovery/workspace_plan_runs/20261009/<run_id>.json`, and performs an ordinary auto read. The response remains `CURRENT_RECOVERY`, `consumed=true`, and retains the saved run/SHA. Deleting `latest.json` in the journal directory as well still produces the same consumed result, now with `workspace_plan_attempt=null`.

User result: deleting mandatory new-store commit evidence does not invalidate the reported readback. The new explicit recovery identity overstates the evidence available for that run.

Minimal correction: only in the recovery scope, require the original exact-plan attempt validator to return a non-`None` verified journal. Enforce this before the owner builds channel/readback consumption projections, so those projections also fail closed. Leave the original legacy and explicit-history paths unchanged. Add separate regressions for missing exact journal with latest present, and both journals missing.

## Important 3 — contradictory reviewer semantic-file binding passes preclaim validation

Location: `src/v5_shadow/daily_review_handoff.py:164-175`. The unchanged authoritative rejection is in `vendor/announcement_revision_baseline/ops/run_manager_daily_announcement.py:560-563`.

Preflight reads and hashes `semantic_catalog` and `reviewer_output`, but never checks whether the reviewer's `semantic_catalog_sha256` actually equals the semantic file SHA being submitted. It checks the decision digest and revision binding, so this remaining direct source mismatch can appear ready even though the later original register-handoff command must reject it.

The probe writes a reviewer with `semantic_catalog_sha256` equal to 64 zeroes and updates the caller's reviewer file SHA to match those actual bytes. The real semantic file SHA is `813d2285cdb3e8b3a45eb962ac84afb2ff94eac899d10fec8959a611f748e27d`. Preflight still returns `READY_FOR_ORIGINAL_OWNER`.

User result: this known-invalid source binding can consume the daily business attempt. Original create/prepare occur before the later register-handoff source check; the original owner still prevents import, but the early no-attempt requirement is missed and a partial revision can be left behind.

Minimal correction: compare the reviewer's semantic source SHA against the already validated `create.semantic_sha256` during preflight. Test both missing and contradictory metadata with zero owner calls and unchanged announcement ledger. This does not require copying the original semantic/content gates into the adapter.

## Important 4 — preflight becomes stale while an earlier lane runs

Locations: `src/v5_shadow/daily_tick.py:56` and `:71`; claim happens in `src/v5_shadow/daily_dispatch.py:37`; the second validation is after that claim at `src/v5_shadow/daily_announcement_revision.py:15`.

Tick preflights every announcement while constructing the entire job list, then dispatches the list sequentially. A preceding lane can take time. If the reviewer file disappears or changes during that period, the dispatcher still claims the announcement attempt before `run_revision` discovers the now-missing or changed input.

The probe supplies a two-job bundle, US then announcement. All review files are valid at tick's preflight. The synthetic first owner removes the synthetic reviewer file before returning. Announcement then receives `WAITING_REAL_REVISION_INPUT_FILES`, but its durable ledger contains one BLOCKED attempt with `retry_safe_without_external_effect=false`.

User result: waiting for a valid review consumes the sole default business attempt. Restoring the original reviewed file does not restore that attempt under the unchanged request identity.

Minimal correction: perform a read-only revision preflight at each announcement's actual admission point immediately before its claim, for example through a narrow optional preclaim adapter hook. Retain the owner-side check as defense against changes after claim. Test a preceding lane changing/removing a file and confirm no announcement state/attempt is created. This finding concerns the avoidable entire-prior-lane delay, not a claim of atomicity across unrelated files and the ledger.

## Verified behavior and scope

- `test_manager_current_recovery` plus `test_daily_review_handoff`: **24 tests passed** in 14.204 seconds.
- `test_daily_revision_chain` with the fixed e06d fixture bundle: **3 tests passed** in 11.299 seconds.
- The fixture chain exercised original create/prepare/register/verify/import/readback and the recovery save/auto read. These were synthetic fixture operations, not a new review of the 392 announcements or a real model channel.
- Existing recovery tests correctly cover separate destination storage, retained legacy plan bytes, exact target routing, explicit historical qualification, changed admitted input, malformed journal, and symlink rejection. The findings above add missing boundary cases.
- Directory comparison confirmed no vendor production source differences in the reviewed candidate. The reviewed production differences were the five expected adapter/handoff files; documentation/tests were also present, plus an existing generated cache directory.
- No real Mac/browser deployment, private business owner execution, external review submission, or original reviewer PASS was claimed or performed.

## Evidence and reproduction

`findings-before.json` records the source identities and all four probe results. `reproduce_review_findings.py` contains the synthetic probes and writes only temporary fixtures; it never edits the candidate.

Run from the candidate root:

```sh
PYTHONPATH=src:tests /workspace/scratch/17ec887ca39d/runtime/v5-env/bin/python -B /workspace/scratch/17ec887ca39d/evidence/review_combined/reproduce_review_findings.py
```

Review status refers to the exact hashes in `findings-before.json`. Subsequent corrections require targeted verification before closing these findings.
