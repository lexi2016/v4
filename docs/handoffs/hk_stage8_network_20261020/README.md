# HK Stage8 transient network retry candidate — 20261020

Frozen goal: stop a single empty transport failure from terminating Stage8 pre-capture when the original 15:50–15:55 window still permits another attempt.

Writer: close_stage_repair (Sol High). Independent Reviewer: rounds 1 and 2 FAIL; third-round incremental review pending.
Worktree: /Users/lexi/.codex/worktrees/hk-stage8-network-20261020/v4_app
Branch: codex/hk-stage8-network-20261020-r1
Git baseline: 55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054

## Change and boundary

Only Stage8 retries empty results with an explicitly recognized transport failure. Three is the total attempt limit, with one second between attempts. Every probe retains the existing actual wall-clock start/finish/window guards. Retry waits recheck actual time, and Stage8 checks actual time again before snapshot creation. Each attempt's errors, source evidence, row counts and provider timestamps remain in the returned receipt and immutable snapshot. Existing verified snapshots remain no-op reads.

A bridge response containing any rows before the shared wrapper's Mapping filter or the snapshot's code filter, an unknown error, a pool/date/coverage error without a transport failure, or a closed capture window terminates immediately. Stage8 observes the original subprocess marker payload inside guarded_process_runner, before the shared wrapper can discard non-Mapping rows. Source evidence records its original row count, VERIFIED/UNKNOWN/NO_RESPONSE status and payload SHA256. The wrapper's returned row count is retained separately and cannot establish original emptiness. Unknown or multiple transport observations never qualify as an empty result. Explicit transport exception types are recognized both with and without a detail suffix. Other stages retain one attempt and their existing result shape. Safety flags, exact-stage/exact-date/pool identity, coverage, per-stock eligibility and the Stage8 PARTIAL_WITH_ROWS consumer guard are unchanged.

## Source and unintegrated dependencies

The Git baseline does not track stage_center/hk_stage8 or its current split dependencies. The only source copied into this worktree is the allowlisted snapshot.py, from canonical and the actual stage release with identical before SHA:

65a7da2d63dd7cec12a2b3caeb494dcebf386c64411f4d0252ae14c9543444b9

Tests explicitly use read-only dependencies at:
/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-precapture-isolation-20261016-r1/app

They load the candidate snapshot.py by absolute path using importlib; they exercise its real prepare_hk_active_snapshot entry, real shared bridge request/response decoder, real validators and real immutable file publication. Only the external subprocess and wall clock are controlled. Dependencies were not copied into or changed in the worktree. writer_receipt.json lists imported dependency files and SHA256. This branch alone is not a complete deployable release.

## Reproduction and verification

The initial single-case RED used the original copied snapshot bytes: expected READY after a transient network failure followed by valid data, observed CANNOT_CONFIRM. The implementation then passed all 16 target cases.

The independent first review found two P2 defects: detail-free ConnectionResetError was not retried, and malformed nonempty bridge rows could be filtered to zero then incorrectly retried. Both failures were reproduced through the real shared bridge decoder before revision. The revised candidate passes all 18 target cases. Earlier RED/GREEN results and the first-review FAIL findings remain in writer_receipt.json.

The second review closed the detail-free exception defect but retained the original nonempty-response P2: shared fetch_futu_snapshot itself removes non-Mapping entries before returning its tuple. The revision now observes the original stdout protocol at the existing guarded process boundary, requiring no shared-wrapper or allowlist extension. Parameterized real-bridge cases cover string/None/nested-list rows, empty mappings and code fields, mixed lists, and unknown/non-list/missing rows payloads. Target result after this revision: 29 passed. Both previous FAIL rounds and their earlier results remain recorded.

```sh
PYTHONDONTWRITEBYTECODE=1 V4_STAGE8_TEST_DEPENDENCY_ROOT='/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-precapture-isolation-20261016-r1/app' /Users/lexi/Desktop/学习/v4_app/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_hk_stage8_snapshot_transient_retry_20261020.py --basetemp=/tmp/hk-stage8-network-green-review-r3-final-20261020
```

Direct related regression: 17 passed, 1 failed. Existing failure:
test_hk_stage8_v4_recovery.py::test_runner_precapture_is_before_due_decision_and_exact_window

The old fixture supplies a nonexistent D1 JSON path. The deployed runner now reads its status and returns "HK D1 binding status unreadable". A separate control using the unmodified runtime snapshot reproduced the same failure. No out-of-scope runner or fixture edits were made. Exact wrapper commands and complete captured results, including the failed baseline control, are in writer_receipt.json.

After the two review revisions, the 17 directly related regression cases passed again; the already-proven unrelated fixture failure was deselected (17 passed, 1 deselected).

The same directly related regression cases also passed after the raw-transport boundary revision: 17 passed, 1 known baseline fixture failure deselected.

An initial RED command using pytest's shared default temporary directory hit an existing permission error during unrelated temporary-directory cleanup. All subsequent commands use unique batch temporary directories; no permission or cleanup changes were made.

## Handoff status

IMPLEMENTED; Writer verification only. Independent REVIEWED/TESTED/BEHAVIOR_VERIFIED pending. No integration, deployment, API/UI/natural verification, commit or push performed.

No existing 20261020 Stage8 active snapshot, RT_DATA capture or exact-stage replay exists at the configured paths. Earlier minute captures contain zero rows in 15:45–15:55. This patch cannot restore today's missing original-window observations. The separate 20261016 PARTIAL_WITH_ROWS rejection remains out of scope.

Full-repository tests: NOT_RUN under the frozen acceptance scope. Network/OpenD behavior, whether retries would have recovered the historical event, deployment and future natural-slot results remain CANNOT_CONFIRM. RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.

