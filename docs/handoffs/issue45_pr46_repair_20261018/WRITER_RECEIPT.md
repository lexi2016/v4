# Issue 45 PR46 writer receipt

**Writer handoff state:** `READY_FOR_INDEPENDENT_REVIEW`. This is not a reviewer verdict or final acceptance.

The candidate repairs target the frozen Issue 45 PR46 defects in `/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0`. The comparison baseline is the provided `original_pr/` snapshot; the SCOPE base is `a56dbdaff45f887e7f8dbb38047a66d09fe5b1db`, the initial PR head is `579c71d997424d058ff6ebffee911eeb7cf92bbb`, and the handoff branch is `codex/issue45-us-close-repair-20261018`.

The scheduler binds a cursor to the exact US target/session and owner artifact, receipt, manifest, cutoff, and paths. It leaves a new request pending when an older same-lane job is active, checks the returned job's pinned identity before advancing the cursor, and retries retryable terminal jobs. After independent review identified a saved-plan recovery gap, the no-cursor path now resolves a matching `PlanSnapshot.run_id` to its exact `JobRecord`, verifies the owner pin again, consumes only `SUCCEEDED`, retries retryable `FAILED`/`INTERRUPTED`/`PARTIAL`, and leaves other states pending. The new regression uses the real `JobCoordinator` and `WorkbenchStore` and reproduces cursor `OSError` after a retryable partial plan was saved.

The source binding validates the standard producer receipt fields and exact payload/snapshot identity; `us_session_date` remains optional, but is checked when present. The full mapping overlay keeps per-field research SHA values and use-scope data. The engine accounts for catalog observations separately from fixed-33 quote coverage, then appends catalog relations as `UNASSESSED` observations. No ranking, BUY, production, or order behavior was added.

The seven changed candidate files and before/after SHA-256 values are recorded in [WRITER_RECEIPT.json](WRITER_RECEIPT.json). Four files in the 11-file PR allowlist were unchanged from `original_pr/`: `contracts/runtime_workloads.json`, `ops/run_us_market_slot.py`, `tests/test_us_owner_handoff.py`, and `v4/manager_workbench/inputs/native.py`.

Before the saved-plan repair, the combined focused regression passed **6 tests**. After that repair, the changed scheduler suite was rerun and passed **4 tests**:

```sh
env -u PYTHONPATH -u PYTHONHOME /Users/lexi/Desktop/学习/v4_app/.venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/tmp/issue45-p1-scheduler --disable-warnings tests/manager_workbench/test_us_close_handoff_scheduler.py
```

The frozen focused baseline selection returned **228 passed, 3 failed, 1 deselected**. The same three documented source-baseline failures remain: the `READY` market-snapshot quote-coverage fixture, the proposed-relation reason expectation, and the unsupported-universe gap expectation. The unrelated intraday dispatcher test remains explicitly deselected as required by the baseline README. The full command and test IDs are in the JSON receipt.

The portable, read-only offline canary is [verify_real_overlay.py](verify_real_overlay.py), SHA-256 `96aae24c25dcb7bfe7dfdc43695dcd869e86c992dd36cb81d957098fadcd0a5e`. Its source, config, US owner, relation owner, and overlay roots are supplied as command-line arguments or environment variables. It makes no network calls and writes no owner/runtime files.

The canary passed through candidate `source_bindings.us_mapping` → `NativeAdapters.us_mapping` → `run_us_mapping` using the actual current API LaunchAgent config and existing owner roots. The config path was confirmed by the parent/reviewer as the active LaunchAgent input; the loaded `relation_root` matched the existing release app used for the read-only overlay. The test preserves all **667** catalog stocks in the summary and all **1,003** relation identities through the consumer, with closure counts **757/221/25**, research-use counts **985/10/5/3**, all seven field SHA entries and use-scope projections intact, and all overlay decisions `UNASSESSED`. Fixed-33 quote coverage remains 33/33, with no count-mismatch gaps. The consumer returns relation rows for 649 distinct stock codes; 18 catalog stock rows have no relation row to emit. The canary supplies no Connect membership owner, so quote assessment remains 0/33 and the unassessed gaps are expected for this isolated overlay check.

This canary exercises candidate code offline and does not deploy it. Live candidate dispatch, API/UI, notification, and natural-slot behavior remain `CANNOT_CONFIRM`. No commit, push, merge, deploy, or service operation was performed. Independent review of the saved-plan repair and final verdict are pending.
