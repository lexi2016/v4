# Issue 29 — Mac isolated acceptance, 2026-10-08

Input: `0602f34fd10f7daff9bf688a710835d1bda43865`, based on `b22836ef3f8fcc6b9218f3422a9bcd7aa61152e9`. The original 48-file package is retained by commit ancestry. This handoff adds Mac evidence and the bounded read-only probe, without duplicating raw plans, market data, or the unchanged source package.

## Candidate and runtime identity

The candidate was initialized from active `manager-workbench-r1-mac-20261008-api-r2` (1,016 API files) and the existing P2 web snapshot (333 files). The independent Reviewer confirmed exactly the seven declared source/test changes, all after-SHAs, all nine preservation pins, and the postpatch inventories. The production changes remain limited to `workspace_history.py` and `workspace.py`. No Mac business-source adaptation was necessary.

The probe verified the active launch configuration SHA `495a9be82e715979d59c03f5c4dd883a7570c55f15b72fa5ed309cacb3914356`, label `com.lexi.v35.api-only`, PID `34989`, actual `python -B -m apps.api.v35_api.run` entry, and filtered runtime paths including the original Vibe binding. This identifies the observed runtime; it is not a deployment receipt for the candidate.

## Independent results

- Four packaged Python test files: 78 passed, 1 existing HK02 fixture failure (`PLAN_HK_02_PANEL_LATEST_MANIFEST_UNREADABLE`).
- New Python tests: 34 passed; this overlaps the preceding set and must not be added to it.
- Historical control and regex tests: 23 passed.
- Frontend scope: 13 tests passed; targeted strict TypeScript check exited 0. This is not a full application build or browser acceptance.
- Writer diagnostic: 95 passed / 7 failed, retained. Six failures arose before US business assertions because `TemporaryDirectory()` still used the macOS `/var` symlink. The independent Reviewer exercised the same cases successfully with a task-local `TMPDIR`; `--basetemp` alone does not redirect those fixtures. No production file-access rule was relaxed.
- The first probe stopped before app creation/GET because its launch-command parser omitted `-B`. A bounded tool-only adaptation added the exact active argument shape, preserved `RESEARCH_ONLY=1`, and included the original Vibe binding. The original failure is retained.

## Real 2026-09-30 historical read

The final probe reached the candidate's in-process ASGI GET with the real stored run `ba13fba330464300b760fe940ba579a1`. HTTP 200 returned `SOURCE_FAILED / HISTORY_SOURCE_INPUTS_CHANGED`, with `HISTORICAL_AS_OF`, exact run match, stable target-file identities, and `write_performed=false`.

This verifies that the read progressed beyond the former reader-version rejection to source revalidation. It does **not** establish consumption, restored historical success, live API acceptance, or three-channel completion. The cutoff is represented by a hash in the probe output; its actual text and the null attempt summary remain `CANNOT_CONFIRM`. No old plan, run, cutoff, source SHA, or trading rule was rewritten.

## Daily continuation findings

- HK 10/7: the original 17:20 dispatch was stopped before its child by `NON_TRADING_DAY`.
- HK 10/8: dispatch and the panel have success evidence. Same-run capture, membership/security-master and exact V2 publication lineage remains incomplete. The examined producer and reader master roots match; a simple root mismatch is not established.
- US 10/8: the exact 10/7 source snapshot has a matching payload/receipt/manifest chain, but the target 10/8 mapping run is absent. The existing refresh method is available; the plan owner explicitly returns `NOT_ATTEMPTED`, and the scheduler has no enabled daily mapping workload. A bounded call to the original owner remains to be integrated.

These findings are metadata-only. See `input_readiness/issue29_hk_us_boundary_20261008.json` for exact evidence locations and limits. No source rows were uploaded or feature-level leakage audit claimed.

## Acceptance boundary

`IMPLEMENTED` and `REVIEWED`: the two isolated fixes and declared test changes. `TESTED`: the independent scope above, with the existing failure retained. `BEHAVIOR_VERIFIED`: the engineered failure isolation/compatibility cases and the real historical read's precise next rejection only.

`INTEGRATED`: isolated candidate only. Joint integration with Issue 28 is not complete; the observed R2 shared entry still has the previously identified preselection regression. `DEPLOYED`, live `API_VERIFIED`, complete-page `UI_VERIFIED`, and daily three-channel behavior are not established. `NATURAL_VERIFIED=NATURAL_SLOT_UNVERIFIED`.

Publication remains frozen under the shared-entry coordination. No service, scheduler, binding, Stage, Vibe, live release, or formal business state was changed by this batch. Research-only remains enabled; production, BUY-gate updates and orders remain false.
