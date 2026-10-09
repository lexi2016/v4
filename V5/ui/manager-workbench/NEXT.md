# Next original-UI candidate (not deployed)

P2 production candidate already fixed at b26e5616a6fe0b36bc3db2cecc2689efecb7a45e.
This directory stages UI regressions while the preview's exact source/build
identity is being resolved. It does not replace an existing static bundle.

Read-only source findings at original commit 8342862f05ca9f6516f51b3164b6110651e5af77:

- `handoff/manager-workbench-mac-completion-20261008/source/web/apps/web/src/manager-selection/catalystObservationPanel.ts`
  SHA fbb20e417bb4d9ff7cbd25c5aa29f387a1650438d6e638216b3f4d7c1a209497.
  A non-explicit first GET receives correct backend date_bindings, then compares
  against local same-day defaults and sends a second invented explicit query.
  `hadDailyExtension` also turns subsequent reads into explicit requests.
- Same prefix `src/api/managerWorkspace.ts`
  SHA 5854af5d1e2b33cc469ba6abd49096bb2f727280161c663edf4b757742f9ce92.
  Non-OK responses become WORKSPACE_HTTP_<status>. The panel maps every 503 to
  "并发上限", without evidence of MODULE_BUSY.
- `handoff/manager-workbench-repair-20261008/after/apps/web/src/manager-selection/dailyChannels.ts`
  SHA c60254b69de369c8b50ef0ffa14dd49c802a3ae56ac4266dd9fe5f39ea40fecc.
  Legacy date is a fallback; only selection/announcement URL input is explicit.

Minimal intended correction: retain explicit user query intent separately from
validated server-returned display dates. A default request accepts original
validated date_bindings without a second guessed GET and remains unbound on
reread. Explicit user date changes still issue that exact query and reject a
mismatched payload; no API alias/fabricated record. A generic 503 gets an honest
unavailable message, never a claimed capacity cause. Keep all original DTO,
nullable count, stale-result and cancellation gates.

`next-tests/dailyChannels.v5Bindings.spec.ts` contains actual mount/API-validator
regressions for default first read and reread, explicit date mismatch rejection,
and a genuine MODULE_RESULT_NOT_AVAILABLE 503. Transport fixtures deliberately
return 503 for invented queries. These are not browser or real US DTO acceptance.
Install this test beside the original helper only in the isolated verified UI
candidate source, then use its existing vitest command; no cloud UI test run.

Exact missing source/build identity requested from the existing preview task:
current source/static manifest; actual catalystObservationPanel.ts,
managerWorkspace.ts and dailyChannels.ts SHAs/paths; package/build root and
entry. Original ManagerSelectionView.vue mount source and the matching
`dailyChannels.testHelper.ts`/runtime-spec files are needed if the above R2
source slice is not already assembled there. Do not mix the older r7 validator
or patch hashed minified assets before that mapping is established.

Existing original dailyChannels runtime tests which intentionally expect a
non-explicit fallback to issue a second guessed query must be reconciled to the
corrected semantics while retaining cancellation/stale-response coverage; do
not merely delete them. Preserve V4 and the fixed preview until Mac validates.
