# Independent recovery bridge review

```text
schema_version: v4.oversold_daily_recovery_bridge_review.v1
status: PASS_RECOVERY_BRIDGE
reviewer_identity: /root/oversold_daily_review
writer_identity: oversold_daily_writer
reviewed_at_utc: 2026-10-15 18:34:10 UTC
behavior_verified: PASS_TARGETED_PREFLIGHT_AND_PLAN
live_recovery: CANNOT_CONFIRM
```

## Frozen inputs

- `recover_oversold_20261016.py`: SHA-256 `b757420def3382d363331d8a6bc46c28eced034bdf220f2d7fa60a639d00da5f`
- `test_recover_oversold_20261016.py`: SHA-256 `c8e0a8d78a8b3bc231b86965274a5c62abaf8f62544eb60cea1338e2c88975fb`
- `test_scheduler_release_runtime_guards.py`: SHA-256 `d18690747872fb3fc7db831fab64edce99aaa4bbbd33fd9a2026f85cdafd0e33`
- Reused unchanged runtime helper `scheduler_release_cutover.py`: SHA-256 `af4b537b6ec107b7624a8865d8f94d0abc6912192c81d8d6a736e7bb9fe82fc6`
- Reused live identity/inheritance evidence [`LIVE_IDENTITY_REVIEW.md`](LIVE_IDENTITY_REVIEW.md): SHA-256 `3f75e38fe2633d55e746f4bea6892f56e44dece44289ae2d349882e60accae5c`
- Prior recovery-helper SHA recorded by the accepted R2 review: `3d526c1ea47517f84a8cac26cff1e1f7596129e57c3d8e2a6dcb2f3e6f790f5d`

The prior helper bytes are not present in this handoff or either relevant release tree, so a bytewise diff against that SHA is `CANNOT_CONFIRM`. This review assessed the full current helper at the exact SHA above against the frozen bridge behavior and reused R2 only for its previously accepted scope.

## Findings and target behavior

P0 findings: **0**. P1 findings: **0**. No code-level P2 defect found in the frozen bridge behavior.

When the exact daily cursor is absent, `_recovery_cursor_preflight` returns a bridge only after `_validate_legacy_nextday_bridge` verifies the derived legacy key, target date, completed terminal job with `finished_at`, matching job/run identity, exact source and target in both job and plan contexts, `NEXT_DAY`, scheduled trigger, an OVERSOLD request, exactly one OVERSOLD plan lane, and that lane's `INPUT_MISSING` state ([`recover_oversold_20261016.py:192-284`](recover_oversold_20261016.py)). Queued/running jobs, unfinished jobs, missing or mismatched cursors, context mismatches, and other lane states fail closed.

The bridge preflight only reads the legacy cursor/job/plan and does not call `set_cursor`. After preflight succeeds, `_child` calls the existing `driver.tick()` ([`recover_oversold_20261016.py:311-318`](recover_oversold_20261016.py)); the inherited r4 driver initializes a missing exact-date cursor through its normal empty-state scheduling path at `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/zsxq-pdf-ocr-scheduler-20261016-r4/app/v4/manager_workbench/oversold_daily.py:135-186`. The helper does not write the legacy cursor or modify its old plan. Tests enforce zero preflight cursor writes and preserve existing exact-date cursor reuse.

The run gate pins the active r4 PID `32762`, LaunchAgent plist SHA `e347c7a08037948a1d1a40e392f8ad95ce28a2555306a94dcb17513346a82d72`, manifest SHA `4710696eb61e60ac5dbd1ea56aa2e7a3762d9c1f9170d206b4dc0beac4769e91`, config SHA `65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca`, all six inherited source SHAs, the launchd selectors, interpreter/module, and cwd ([`recover_oversold_20261016.py:87-185`](recover_oversold_20261016.py)). The current-process and six-file readback are reused from the live identity receipt above. The exact configured interpreter's `--plan` output returned `RECOVERY_PLAN_ONLY`, `network_or_formal_run: false`, source `20261015`, target `20261016`, r4 release id, and the pinned PID/plist/manifest/config hashes.

## Verification and limits

The two focused test files passed with exit code 0 using the repository `.venv` and an isolated pytest basetemp: **28 passed in 0.16s**. Coverage includes the valid legacy partial bridge, existing-cursor reuse, missing/mismatched cursor, queued/running/unfinished jobs, source/target/phase mismatch, non-`INPUT_MISSING` lanes, exact r4 pins, changed PID/source/config rejection, process identity guards, and plan-only CLI behavior.

Nonblocking P2 coverage note: tests use the valid `SCHEDULED` trigger and OVERSOLD `requested_lanes` in the positive fixture, but do not separately test rejection when the trigger differs or OVERSOLD is absent from `requested_lanes`; the implementation has explicit guards at lines 197-203. Regression behavior for those two guards is therefore `CANNOT_CONFIRM` from the suite alone.

No `--run`, service control, network request, or live state write was performed, as required. Consequently a real-store bridge transition, subsequent asynchronous job outcome, API/UI readback, and natural scheduled result remain `CANNOT_CONFIRM`; this review does not claim live recovery acceptance.
