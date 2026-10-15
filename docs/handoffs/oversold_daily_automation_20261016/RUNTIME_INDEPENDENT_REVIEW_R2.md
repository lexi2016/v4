# Independent runtime release review R2

```text
schema_version: v4.oversold_daily_scheduler_runtime_review.v1
status: PASS_RUNTIME_RELEASE
behavior_verified: PASS
candidate_release_id: oversold-daily-auto-20261016-r1
candidate_release_manifest_sha256: d9750660f989198e9000b1686801ac514def52e27c5dff75c93bdccb3a4a05d6
candidate_staged_plist_sha256: 91d83bd16af4b7932fb07007651339ee3978aa8a293d72e25e828962c8403072
writer_identity: oversold_daily_writer
reviewer_identity: /root/oversold_daily_review
reviewed_at_utc: 2026-10-15 18:14:30 UTC
```

R2 passes the two runtime-helper repairs for the exact candidate manifest above. This is a candidate release review for the activation gate; it does not claim activation or deployed runtime acceptance. The earlier [`RUNTIME_INDEPENDENT_REVIEW.md`](RUNTIME_INDEPENDENT_REVIEW.md) remains the historical FAIL for the previous helper SHAs; this report supersedes it only for the reviewed helper and plan revisions below.

## Frozen review inputs

- `scheduler_release_cutover.py`: SHA-256 `af4b537b6ec107b7624a8865d8f94d0abc6912192c81d8d6a736e7bb9fe82fc6`
- `recover_oversold_20261016.py`: SHA-256 `3d526c1ea47517f84a8cac26cff1e1f7596129e57c3d8e2a6dcb2f3e6f790f5d`
- `test_scheduler_release_runtime_guards.py`: SHA-256 `4fcf440360dd644f931d17fdf1f62b67e707d0d81a34c6041e87eb54356b95d6`
- `SCHEDULER_CUTOVER_PLAN.json`: SHA-256 `d67a0b50ed9575bfd8fa22d5cbd62f76d66102c55c4a13f01a794b8b40fe1e9a`
- Candidate manifest SHA was independently read from disk and matches both the preparation receipt and current plan. Prior source R2, six-file delta, 1,022-entry non-delta inventory, and seven-module import PASS are reused from the unchanged preparation/source receipts as requested.

## Findings and verification

P0/P1/P2 findings: **0** within this frozen helper scope.

The process-root fix now binds the live process to the launchd label PID and loaded plist path, then checks the plist's release selectors, configured interpreter command, daemon module, and actual process cwd ([`scheduler_release_cutover.py:56-74`](scheduler_release_cutover.py), [`:99-208`](scheduler_release_cutover.py)). It checks PID absence separately from label absence and repeats both after the three-second settle period ([`:240-254`](scheduler_release_cutover.py)); the process scan also uses cwd/module/interpreter evidence rather than requiring the app root in argv ([`:211-231`](scheduler_release_cutover.py)).

I independently called read-only `launchctl print` and the helper's identity check for the current base process. The label was `running`, PID `90252`, loaded plist `/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist`, program `/bin/bash`, and working directory `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-tdx-conflict-repair-main-20261015-r2/app`. All process identity checks passed: label/PID/plist/program/cwd, base app/release/manifest/PYTHONPATH/config selectors, configured interpreter command, and daemon module. The staged candidate plist separately passed the same selector and candidate-manifest checks. No candidate process was started.

The recovery helper now exposes mutually exclusive `--plan` and `--run` modes; the plan path returns before service imports and states no network/formal run occurred ([`recover_oversold_20261016.py:106-148`](recover_oversold_20261016.py)). The configured scheduler interpreter ran `recover_oversold_20261016.py --plan` successfully and returned `RECOVERY_PLAN_ONLY`, source day `20261015`, target date `20261016`, current Hong Kong time basis, and no historical cutoff. The seven focused tests passed with exit code 0 using an isolated pytest `--basetemp`: `7 passed in 0.13s`. The tests cover process identity/selector checks, PID mismatch, cwd mismatch, process scanning, live-PID detach blocking, and plan CLI behavior including conflicting-mode rejection. The first shared-temp pytest invocation also showed seven passing tests but exited during cleanup with a `PermissionError` on a pytest garbage directory from another test case; the isolated-basetemp rerun completed cleanly.

Activation and formal recovery remain unperformed. No `launchctl` mutation, network request, active-state write, or `--run` was performed. Candidate process startup, live recovery/cache semantics, API/UI readback, and natural scheduled execution remain `CANNOT_CONFIRM`; `NATURAL_VERIFIED` is not claimed. Research safety remains `RESEARCH_ONLY=true`, `PRODUCTION_ALLOWED=false`, `BUY_GATE_UPDATED=false`, and `ORDERS_SENT=false`.
