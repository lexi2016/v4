# Daily execution candidate: ledger plus existing US owner binding

Base: 1ec23f8ad3abfff1f8e814e9b2fb87fa7b67df06. Reference-only comparison: 74478a0e62be215c8527ccc9a14b89b51042d014, handoff/manager-four-functional-gaps-20261009/package/DAY_RUN_REUSE_AND_INTEGRATION.md and actual_owner_runner_20261009/tests/run_actual_us_mapping_20261009.py. That package proves callable original interfaces and partial fixed-sample results; it does not prove broad relations or a complete historical three-lane success.

## Implemented candidate

run_ledger records identity = lane + HK target date + exact request SHA + research cutoff + implementation/config/dependency SHA. Files use descriptor-relative no-follow opens, atomic replacement, fsync and a per-lane/day flock. Concurrent identical claims admit one attempt. Successful identical computation reuses its ledger product reference. Failures cannot replace a prior identity's ledger success. RUNNING after interruption remains outcome-unknown, never automatically restarted. Explicit no-external-effect failures permit at most three total attempts (default two). There is no background retry loop.

daily_dispatch admits explicit supplied slots against the pinned original HK calendar and actual wall clock. Old dates, missed windows, future cutoffs, unbound half-days, missing adapters and mismatching identity/request are rejected. Each lane has its own admission/error result. US request target/cutoff must equal the ledger identity. This is callable orchestration, not an installed scheduler or new source producer.

daily_us_owner binds directly to the existing run_us_mapping implementation. It preserves original build/persist/readback, verifies returned readback equality and original artifact SHA, and records original run_id/session/status/root plus ledger run_id. COMPLETED/VALID_EMPTY is execution success only within the original fixed sample; INPUT_MISSING/PARTIAL/CANNOT_CONFIRM remain failed ledger outcomes with original artifact reference. The wrapper preserves MANUAL_RECOVERY, target_date_eligibility=CANNOT_CONFIRM and natural_verified=false. It does not turn US into HK_CONNECT or change manager-plan admission.

Use bind_us_owner(config) immediately before each dispatch; its registration hashes the current US adapter and shared execution files, original capsule/calendar identities and the supplied explicit config. The scheduler must construct immutable jobs from this registration, use the approved slot config, and retain the exact identity for a retry. Recomputing cutoff on every tick creates a different computation and is not an idempotent retry.

## Integration contract and remaining work

The existing Mac task can use dispatch_due(jobs, {'us_mapping': bind_us_owner(config)}, ledger_root). ledger_root must be a separate initialized directory with `.v5-daily-run-ledger` containing `v5.daily-run-ledger.v1\n`. Each job supplies lane, identity, owner_request (unchanged existing US request), scheduled_at, deadline, half_day_bound and max_attempts. The bound registration fields code_sha256/config_sha256/dependency_sha256 must match identity, and input_sha256 is sha256_json(owner_request). No slots or automatic installation are supplied or presumed approved here.

Announcement/rebound registered adapters remain NOT_BOUND until their owners provide them. Those adapters must compute current binding fingerprints and verify actual product readback; common ledger receipt validation alone does not independently verify their source evidence. Source fetching/deduplication across changed identities remains with the original owners. Crash reconciliation requires actual owner readback before any future resume; there is deliberately no time-based lease expiry or automatic retry of unknown effects.

There is no global lane/day latest-success publication pointer: success retention described above applies to immutable computation identities in this ledger. The original US owner's own latest pointer semantics are unchanged, including when it persists an incomplete run. This increment neither activates API generations nor refreshes the manager plan. Existing manager consumption still needs its later real cutoff, original source identity and independent saved-plan readback. Owner automation slots, installation, three-lane manager integration and actual cross-day natural execution remain NOT_RUN/CANNOT_CONFIRM, not completion claims.

## Independent Mac verification

Cloud checks only AST and diff; no product tests, owner execution, installation, API/preview or production action occurred. Synthetic candidates (7 ledger, 5 dispatcher, 4 US wrapper cases):

```bash
PYTHONPATH=V5/src:V5/tests python3 -B -m unittest test_run_ledger test_daily_dispatch test_daily_us_owner -v
```

Scope regression from preceding increment:

```bash
PYTHONPATH=V5/src:V5/tests python3 -B -m unittest test_us_mapping_scope -v
```

Use a marked isolated output for any authorized Mac real-owner verification. Do not add these synthetic counts to historical baselines or call a manual recovery a natural run. Broader US relation input remains missing verified original acquisition clocks/material evidence and an admitted owner binding; this code does not manufacture those inputs.
