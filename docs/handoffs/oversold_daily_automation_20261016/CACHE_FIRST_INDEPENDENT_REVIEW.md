# Independent cache-first repair review

```text
status: PASS_CACHE_FIRST_REPAIR
reviewer_identity: /root/oversold_daily_review
writer_identity: oversold_daily_writer
reviewed_at_utc: 2026-10-15 19:05:48 UTC
behavior_verified: PASS_FOCUSED_TESTS_AND_OFFLINE_REAL_CACHE_REPLAY
live_scheduler_recovery: CANNOT_CONFIRM
```

## Frozen inputs

- r4 release manifest SHA-256: `4710696eb61e60ac5dbd1ea56aa2e7a3762d9c1f9170d206b4dc0beac4769e91`
- Candidate [`oversold_daily.py`](runtime_candidate_r4/v4/manager_workbench/oversold_daily.py) SHA-256: `9ebeed117ee883805ac8a5e3331cb53fa688892905dd8292912ee5ba4b20099e`
- Candidate [`hk_daily_supplement.py`](runtime_candidate_r4/upstreams/v3_shared_data/shared_data/hk_daily_supplement.py) SHA-256: `7b09a85431b2d4398de4f057a755b8b7398e82e26611297df9ba2efab8dbb250`
- Exact two-file patch SHA-256: `45ade21a1373ca418cb5208162c321deade6d141bb6dcb1d16d14e61a3b11669`
- Delta manifest SHA-256: `37b1ebb7ee0e9d2df0382954179fd7dd6534ece25251b11e5a40e2b319dfb1a4`
- Delta preparation/check script SHA-256: `488feca6343e726dee51a778a8301828bd2597b0c0dd2ff53bec017df2bbc5c3`
- Focused test SHAs: `test_hk_daily_supplement_tdxpy61.py` `42a949a6cae748e376ea5534d5f645f72b693e6ec8632eb444aceeed9f78f548`; `test_oversold_daily_scheduler.py` `73ff736afd9d8ad959c3edc3e6811218cf9135fa7cde81215d3812c8af80eab4`.

The r4 `--check` returned `R4_RUNTIME_DELTA_CHECK_PASS`; the exact manifest and both candidate files matched the pinned base and staged patch. No runtime file was replaced.

## Findings and target behavior

P0 findings: **0**. P1 findings: **0**. No blocking P2 finding in the frozen scope.

The repair classifies `ResponseHeaderRecvFails` as transport while `ValueError` remains outside the transport type set ([`hk_daily_supplement.py:732-747`](../../../upstreams/v3_shared_data/shared_data/hk_daily_supplement.py)). The focused owner tests assert the exact classifier behavior and prove an exact cache hit avoids connector calls. In a mixed cached/missing request set, the new owner path determines request-cache misses before attempting the connector, catches connector failure, then validates cached records before admitting them; the verified offline replay below confirms those cached rows survive.

Nonblocking P2 scope note: the pre-connection pass checks whether each exact cache path exists (`hk_daily_supplement.py:1070-1083`); `_verify_window_record` validates bytes later when each row is consumed (`1123-1129`). Thus the receipt's wording that cache entries are validated before connecting is stronger than this code path. The frozen valid-cache behavior passed; whether a corrupt existing cache should trigger a network refetch while offline is `CANNOT_CONFIRM` and outside this repair's stated target. Corrupt bytes are not admitted as READY.

The one-time terminal migration is constrained to the pinned 2026-10-15 source / 2026-10-16 target, prior `PARTIAL_TERMINAL` with the expected disposition and zero retryable errors, exact old job/run/capture IDs, capture and parent manifest SHAs, parent signature, and prior attempt counts (`oversold_daily.py:19-33, 160-221`). It reads and verifies the pinned old capture manifest and raw SHA, requires matching run/date/scope and actual retryable transport evidence, and fails closed otherwise (`oversold_daily.py:288-322`). A changed old manifest SHA remains terminal in the regression test (`test_oversold_daily_scheduler.py:383-397`). The migration marker stays at one; the migration regression retains the existing capture/job counters and the 300-second retry delay (`test_oversold_daily_scheduler.py:343-378`). The exhausted-probe branch no longer resets the attempt counters (`oversold_daily.py:358-366`).

The old capture manifest and raw are read-only evidence in the migration helper. I called `_verify_classifier_migration_source` directly against the pinned old artifact with a read-only service shim; it returned `source_verified=true` for the exact `PANEL_GAPS` manifest and its raw recorded 689 unresolved rows with 1,378 `ResponseHeaderRecvFails` errors. This did not tick the scheduler or write the cursor. The new path writes the cursor migration marker and invokes the existing capture/submission flow; it does not write the pinned old capture path or old run ID. The old run was not executed or modified during this review. Bytewise live-store immutability after a production migration remains `CANNOT_CONFIRM` because no live recovery run was permitted.

Nonblocking P2 test note: the positive scheduler fixture stubs `_verify_classifier_migration_source` to `True` (`test_oversold_daily_scheduler.py:353-354`); there is no automated negative fixture for corrupt old raw/manifest or missing transport evidence. The actual pinned artifact passed the read-only verifier call above, and the implementation fails closed on those mismatches (`oversold_daily.py:288-322`), but regression coverage for those negative verifier branches is `CANNOT_CONFIRM` from the focused suite.

## Independent verification

The requested focused suite was rerun with an isolated pytest temporary root:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --tb=short --basetemp=/tmp/pytest-oversold-cache-first-review upstreams/v3_shared_data/tests/test_hk_daily_supplement_tdxpy61.py tests/manager_workbench/test_oversold_daily_scheduler.py
18 passed in 0.17s
```

I independently reused the real `20261015` `PANEL_GAPS` input manifest (`9780a44c5cb6d6f02137d35c`, SHA-256 `a4ee2b1fc23e85650a0937355881c6c54b3557c219d69bb27ec5919cc1b0d68f`) and the prior `FULL_MASTER` run (`7484c9312ffe565ca8778264`, 567 READY rows). The owner ran with copies of the existing catalogue/cache trees under a disposable `/tmp` output root and a connector stub that always raises; it made no real network requests and wrote no authoritative cache files.

- `HK.00001` canary: 1 READY, 1 cache hit, 0 connector calls, 0 bar requests.
- 689-code `PANEL_GAPS` replay: 567 READY, 122 UNASSESSED, 567 cache hits, 0 bar requests. Both configured endpoint calls went only to the offline stub. Every retained READY response SHA matched the prior `FULL_MASTER` record.
- The produced 689-row capture passed `read_tdxpy_window_supplement`; temporary cache/catalogue hashes stayed unchanged and temporary outputs were discarded.

The tests and exact source review cover classifier stability, one-time migration, retained attempt budget/backoff, and fail-closed mismatch behavior. A live scheduler transition, actual TDX availability, API/UI readback, and a natural scheduled result remain `CANNOT_CONFIRM`; this review did not deploy, control services, alter owner data, or run the scheduler.
