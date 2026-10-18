# Issue 45 PR46 independent review

**Verdict: `PASS` for the frozen source and offline-consumer scope.** The final candidate passes the focused regressions and the exact canonical-owner overlay consumer check. `REVIEWED` and source/offline `BEHAVIOR_VERIFIED` are complete. Live behavior of this candidate remains `CANNOT_CONFIRM` because it was not deployed.

## Findings

- **P0:** none.
- **P1:** none open. During review I found that a missing cursor plus a saved retryable partial plan could be marked `CONSUMED`. The final scheduler now resolves a matching plan to its exact job, consumes only `SUCCEEDED`, retries a retryable terminal job, and leaves other states pending ([scheduler.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/v4/manager_workbench/scheduler.py:154)). The added real `JobCoordinator`/`WorkbenchStore` regression injects a cursor `OSError` after saving a retryable partial plan, then verifies the same input is retried and succeeds ([test_us_close_handoff_scheduler.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/tests/manager_workbench/test_us_close_handoff_scheduler.py:226)).
- **P2:** none open.

The final candidate's seven changed-file SHA-256 values match `WRITER_RECEIPT.json`, and the actual changed-file set versus `original_pr/` matches that receipt. Four allowlisted files are unchanged from the original PR candidate. Review found no ranking, BUY, production, or order behavior change.

## Frozen acceptance evidence

1. **Invalid identity submits no job.** The scheduler gates on `POST_CLOSE`, ready status, and exact US session, then rejects future/invalid cutoff or incomplete artifact/receipt/manifest identity before submission ([scheduler.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/v4/manager_workbench/scheduler.py:112)). The regression verifies a partial owner capture produces no submission or saved plan ([test_us_close_handoff_scheduler.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/tests/manager_workbench/test_us_close_handoff_scheduler.py:273)). The binding rejects altered producer identity fields and accepts the standard receipt, where `us_session_date` is optional ([source_bindings.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/v4/manager_workbench/inputs/source_bindings.py:539), [test_manager_us_mapping_bindings_r3.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/tests/test_manager_us_mapping_bindings_r3.py:266)).

2. **Date/session target.** Slot `0415` for Shanghai business date `20261017` resolves the HK securities target to `20261020` ([run_us_market_slot.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/ops/run_us_market_slot.py:146), [test_run_us_market_slot.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/tests/test_run_us_market_slot.py:154)). The real-owner offline consumer binds the dated artifact to US session `20261016` and target `20261020`.

3. **Exact input and retry behavior.** Binding validates the artifact bytes against the manifest, producer schema/date/source, full payload SHA, exact receipt path, market-snapshot SHA/metadata, and cutoff; it checks `us_session_date` only if present ([source_bindings.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/v4/manager_workbench/inputs/source_bindings.py:539)). The scheduler cursor key includes target/session, artifact/receipt/manifest SHAs and paths, and cutoff; it pins the same owner binding into the job and checks job identity before cursor advancement ([scheduler.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/v4/manager_workbench/scheduler.py:30)). Tests cover an older active same-lane job, retryable failure, saved-plan cursor-write failure, and idempotent repeat delivery ([test_us_close_handoff_scheduler.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/tests/manager_workbench/test_us_close_handoff_scheduler.py:146)).

4. **Full overlay identity and safety.** The source binding validates all 667 catalog stocks, 1,003 unique relation IDs, recovery status counts, seven field SHA entries, and use-scope projections ([source_bindings.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/v4/manager_workbench/inputs/source_bindings.py:435)). The engine keeps catalog observations outside the fixed-33 quote denominator and emits them as `UNASSESSED` observations ([us_mapping.py](/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T/v4-issue45-pr46-j681d3m0/candidate/v4/manager_workbench/engines/us_mapping.py:53)). The portable canary independently passed against canonical owner files: 667 stocks in the summary; all 1,003 relation IDs conserved; closure counts 757/221/25; research-use counts 985/10/5/3; seven field SHA entries and `use_scope` preserved; all 1,003 decisions `UNASSESSED`; fixed-33 quote coverage 33/33 with no count-mismatch gaps. The consumer has relation rows for 649 distinct stock codes; 18 catalog stocks have no relation row. The canary intentionally supplies no Connect membership owner, so assessment is 0/33 and its unassessed gaps are expected.

## Independent verification

Final focused command, run from the candidate directory:

```sh
env -u PYTHONPATH -u PYTHONHOME /Users/lexi/Desktop/学习/v4_app/.venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/tmp/issue45-review-focused-final-freeze --disable-warnings tests/manager_workbench/test_us_close_handoff_scheduler.py tests/manager_workbench/engines/test_us_mapping.py::test_full_overlay_relations_are_consumed_as_non_selectable_observations tests/test_manager_us_mapping_bindings_r3.py::test_us_mapping_receipt_fails_closed_on_producer_identity_and_allows_standard_receipt tests/test_run_us_market_slot.py::test_us_close_slot_keeps_hk_target_distinct_and_skips_holiday
```

Result: **7 passed**. The changed scheduler suite separately passed **4 tests** after the saved-plan fix.

I independently reran the frozen baseline selection: **228 passed, 3 failed, 1 deselected**. The same documented baseline failures remain: the `READY` market-snapshot quote-coverage fixture; the proposed-relation reason expectation; and the unsupported-universe gap expectation. The unrelated intraday dispatcher test remained deselected as specified by the baseline receipt. No new baseline failure appeared.

The portable owner-consumer check also passed. Its exact command and full observed values are in [WRITER_RECEIPT.json](WRITER_RECEIPT.json); its script SHA-256 is `96aae24c25dcb7bfe7dfdc43695dcd869e86c992dd36cb81d957098fadcd0a5e`. It made no network calls and wrote no owner or runtime files.

## Runtime boundary

Read-only `launchctl print` confirmed the running API LaunchAgent loads `/Users/lexi/Library/Application Support/com.lexi.v4.local/config/us-hk-recovery-v2r1-20261016-r2.json` (SHA-256 `589eaa058b9abd9cef59ab71ef2c3f4c3c998bae18dd26777134bf0fa22ef86e`). Its `relation_root` is the existing release app at `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-recovery-v2r1-20261016-r2/app`; the catalog, review, and recovery owner files exist there with the canonical hashes recorded in the writer receipt. This corrects the earlier unverified description of the loaded root as a retired worktree path.

The API process is running, but this candidate was not deployed. Candidate live dispatch, API output, UI, notification, and natural-slot behavior remain `CANNOT_CONFIRM`; this source/offline batch does not require them for acceptance.
