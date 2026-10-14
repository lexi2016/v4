# 20261014 six-stage monitoring closure

Six due HK stages checked. Main assistant only per explicit user instruction; no subagents. Strict NATURAL_VERIFIED remains CANNOT_CONFIRM for all six. Earlier fixed receipts are reused; no duplicate provider collection or manual runner invocation in this checkpoint.

| Stage | Verified state | Remaining natural gap |
|---|---|---|
|09:30–09:35|100 input, 10 output, READY; existing API/UI receipt reused|MANUAL_FULL_POOL_POLICY_REBUILD|
|09:35–09:40|100 input, 10 output, READY; existing API/UI receipt reused|MANUAL_FULL_POOL_POLICY_REBUILD|
|09:40–09:45|100 input, 10 output, PARTIAL_WITH_ROWS|Manual rebuild; FUTU_AFTERFACT_CAPTURE_NOT_PIT_SAFE and HK_HISTORICAL_ORDERBOOK_UNAVAILABLE|
|09:45–10:30|100 pre-cutoff books; 100 minute series, 44 bars 09:46–10:29; A10/HK10 API/UI|Legacy LATE_CATCHUP_REPLAY; full execution binding unavailable|
|13:00–13:15|100 pre-cutoff books; 100 minute series, 14 bars 13:01–13:14; A10/HK10 API/UI|NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING|
|14:45–15:00|100 pre-cutoff books; 100 minute series, 14 bars 14:46–14:59; A10/HK10 API/UI|Same independent-binding gap; original RECOVERY declaration retained|

Prior evidence: `HANDOFF_HK_FULL_POOL_RANKING_20261014.md` and `HANDOFF_NATURAL_MONITOR_20261014_1032.md`. The six checks are complete, not six natural passes. Formal eligibility remains false and HK display remains OBSERVATION_UNVERIFIED.

## Afternoon capture and consumption

Exact D-1 Top100 SHA: `1627efe05e26228fbd036c2a0507000d52ebe77589863dea57e3cf4fa3986aff`.

13:15 snapshot ran 13:14:06.230079–13:14:09.425894 Beijing; minute capture 13:16:30.812742. Owner evaluated 13:15:02.471546; START 13:15:05.090966; RETURN 13:17:29.218982. Dispatch NATURAL / DUE. HK selection `run-64dc5bdb11338e7aa5711151`.

15:00 snapshot ran 14:59:00.851908–14:59:03.417371; minute capture 15:01:32.092384. Owner evaluated 15:00:05.478530; START 15:00:07.947151; RETURN 15:02:28.693206. Original dispatch RECOVERY / DUE. HK selection `run-ae24b6bf96582eed104acf3b`.

Both snapshot loaders verified exact date/stage/pool SHA, 100 ten-level Bid/Ask raw responses and request/receive timestamps before cutoff. Minute file SHA, true capture time and frozen window aggregation verified. RawStore/SelectionStore verified against owner receipt and live API. Owner history and referenced selection trios are now bound, but independent execution attestation remains unverified. Fresh background 8873 pages on both exact stages displayed A10/HK10, original dispatch declarations and CANNOT_CONFIRM execution/natural evidence.

Both A actual candidate sets equal all 381 valid physical aggregate codes. All fixed 292 baseline codes retained; 89 new valid codes included. Candidate-current SHA `3b54b786eac952d1119f6d60dd24ddcabfbd6abf035eb0d8717044202c258535`. Raw contains 380 codes plus explicit missing BJ.920285; union equals all 381, no unaccounted or pagination loss. A result stays PARTIAL_WITH_ROWS; this is not full quote coverage. Exact source-pool provenance and code sets are in local receipts.

## Observed minimal repair

First remaining break: `_node_mode` reused the five-second pre-cutoff wait budget for dispatch classification. A natural launch evaluated 5.478530 seconds after 15:00 was thus RECOVERY although the scheduler correctly said DUE. Changed only the mode predicate to the scheduled minute, aligned with existing evaluate_due. Pre-cutoff, next-minute and historical invocations remain recovery/not-due as applicable. Market-data cutoffs, PIT gates and the wait budget unchanged.

Canonical root `/Users/lexi/Desktop/学习/v4_app`; private GitHub baseline `6cb270f1c1a1a84dde96693a284930c87e693129`. Allowed source `ops/run_stage_center_nodes.py`, new test `tests/test_node_mode_minute_20261014.py`, this handoff. Existing untracked entrypoint preserved with only the exact predicate delta; no unrelated workspace staging.

Reproduced 2 failing timing cases before repair. Canonical command `.venv/bin/python -m pytest -q tests/test_node_mode_minute_20261014.py tests/test_natural_lineage_20261014.py --basetemp=<isolated evidence directory>`: 15 passed. Initial shared-temp cleanup failed on an existing permission issue; isolated rerun exited 0. Actual candidate runtime `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python -B -m pytest -q <isolated copied timing test> --basetemp=<isolated runtime directory>` with PYTHONPATH bound to candidate: 6 passed. Import path verified from candidate before activation.

Stage cloned from actual parent natural-lineage-stage-20261014-r1 and activated as node-minute-stage-20261014-r1 at 15:14:05.994372. Manifest SHA `9218888255e513840e25d1e16cebd0da1d5976f39e33a0fa0f5785461dfd8e13`. Idle scheduler checked before reload; launchd loaded root read back. API remains news-link-api-20261014-r2. Existing owner receipt bytes and both afternoon A/HK run IDs unchanged after activation. No retrospective natural promotion or hand-created proof.

IMPLEMENTED / INTEGRATED / DEPLOYED; main-agent regressions passed; API_VERIFIED / UI_VERIFIED apply to afternoon results. Independent REVIEWED / TESTED / BEHAVIOR_VERIFIED: NOT_RUN (explicit no-subagent instruction). New predicate future natural-slot acceptance: NATURAL_SLOT_UNVERIFIED. No further feature or attestation subsystem added.

Source SHA256 before: b0cde8d66727e16bbf526050a61aea17381f636d2fd96dbb0d2be6964d7f1e13
Source SHA256 after: 3262f8c8e0c0faf580c8272dd8aac3d60250bc8a95b762a060f814876f5e48bf

Local evidence root `/Users/lexi/Desktop/学习/agents调试/V4_NATURAL_MONITOR_20261014`: `1502-<stage>-receipt.json`, API/UI files, `1502-fix-scope.json`, isolated test log, activation, post-fix readback, and `final-summary.json`. Raw quotes/full API responses remain local, excluded from GitHub.

Monitoring closure: automation v4 deleted after all six checks, as confirmed by the automation tool. No monitoring extends beyond this day; existing separate 16:16 close monitor unchanged. Research-only; production_allowed=false, buy_gate_updated=false, orders_sent=false. Vibe 8910 unchanged.
